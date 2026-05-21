"""
SQL Table Listener Service (v2 — Two-Table Architecture).

Polls two tables every 30 seconds:
  Step A: sql.ModelActions  — check pending child runs (restart attempts)
  Step B: sql.PipelineRunLog — pick up new failed pipelines

Restarts are NON-BLOCKING — each restart runs in a background thread with
the appropriate wait time, so the main poll loop continues processing new failures.

Tables:
  sql.PipelineRunLog  — original failed pipeline runs (Healer columns updated by us)
  sql.ModelActions     — restart attempts / child runs (fully managed by us)
"""
import time
import threading
import pyodbc
import schedule
import sys
import os
from datetime import datetime, timedelta, timezone

# IST timezone (UTC+5:30)
IST = timezone(timedelta(hours=5, minutes=30))

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config.settings import SqlConfig, POLL_INTERVAL
from intelligence.error_processor import (
    process_error, handle_escalation, MAX_RESTART_ATTEMPTS,
    RESTART_STRATEGIES
)


class SQLListener:
    """
    Continuously monitors PipelineRunLog for failed pipeline runs and
    ModelActions for pending restart children.

    Architecture:
        Each 30s poll cycle:
          Step A: _poll_child_runs()   — check if any restart children finished
          Step B: _poll_new_failures() — pick up new original failures
    """

    def __init__(self):
        """Initialize Azure SQL connection."""
        print("[INIT] Connecting to Azure SQL Database...")

        self.conn_str = (
            f"DRIVER={{ODBC Driver 18 for SQL Server}};"
            f"SERVER={SqlConfig.SERVER};"
            f"DATABASE={SqlConfig.DATABASE};"
            f"UID={SqlConfig.USERNAME};"
            f"PWD={SqlConfig.PASSWORD};"
            f"Encrypt=yes;"
            f"TrustServerCertificate=no;"
            f"Connection Timeout=30;"
        )

        # Test connection on startup
        try:
            conn = pyodbc.connect(self.conn_str)
            conn.close()
            print(f"[OK] Connected to SQL Server: {SqlConfig.SERVER}")
            print(f"[INFO] Database: {SqlConfig.DATABASE}")
        except Exception as e:
            print(f"[ERROR] SQL connection failed: {str(e)}")
            raise

        # Track processed LogIds in memory (prevent duplicates within session)
        self.processed_log_ids = set()

        # In-memory cache: LogId → {classification, error_details, pipeline_metadata}
        # Kept so child failures can reference the parent's classification for escalation
        self._active_sagas = {}

        # Lock for thread-safe access to _active_sagas and SQL writes
        self._lock = threading.Lock()

        # Track OrgLogIds that have an active restart thread pending
        # Prevents duplicate restart threads for the same saga
        self._pending_restarts = set()

    def _get_connection(self):
        """Get a fresh database connection."""
        return pyodbc.connect(self.conn_str)

    # ── Main Poll Cycle ────────────────────────────────────────

    def check_for_failures(self):
        """
        Single poll cycle — runs every 30 seconds.
        Step A: Check pending children in ModelActions
        Step B: Check for new failures in PipelineRunLog
        """
        now = datetime.now(IST).strftime("%H:%M:%S")
        print(f"\n[POLL] [{now}] Poll cycle starting...")

        # Step A: Check pending children (quick — just status checks)
        self._poll_child_runs()

        # Step B: Pick up new failures
        self._poll_new_failures()

    # ── Step A: Poll Child Runs ────────────────────────────────

    def _poll_child_runs(self):
        """
        Check ModelActions for children whose ADF run has completed.

        For each completed child:
          - Succeeded → mark success, write back AutoHealed to PipelineRunLog
          - Failed & attempts < 3 → classify, schedule next restart
          - Failed & attempts = 3 → escalate, write back Escalated to PipelineRunLog
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            # Find children that have a RunId, haven't been processed yet,
            # and whose parent saga is still open.
            # HealerProcessedAt IS NULL ensures we only check children that
            # haven't been resolved — prevents re-polling the same failed child.
            cursor.execute("""
                SELECT
                    ma.ActionId,
                    ma.OrgLogId,
                    ma.OrgPipelineRunId,
                    ma.PipelineRunId,
                    ma.HealerRetryAttempt,
                    ma.IsSuccess,
                    prl.PipelineName,
                    prl.HealerErrorType AS OrgErrorType
                FROM sql.ModelActions ma
                JOIN sql.PipelineRunLog prl ON prl.LogId = ma.OrgLogId
                WHERE ma.PipelineRunId IS NOT NULL
                  AND ma.IsSuccess = 0
                  AND ma.HealerProcessedAt IS NULL
                  AND prl.HealerFinalOutcome IS NULL
                ORDER BY ma.ActionId ASC
            """)

            rows = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description]
            conn.close()

            if not rows:
                return

            print(f"   [CHILDREN] Checking {len(rows)} pending child run(s)...")

            for row in rows:
                child = dict(zip(columns, row))
                self._check_single_child(child)

        except pyodbc.Error as e:
            print(f"   [ERROR] Child poll SQL error: {str(e)}")
        except Exception as e:
            print(f"   [ERROR] Child poll error: {str(e)}")

    def _check_single_child(self, child):
        """
        Check the ADF status of a single child run and take appropriate action.
        """
        from listener.azure_client import get_pipeline_run_status

        action_id = child["ActionId"]
        org_log_id = child["OrgLogId"]
        child_run_id = child["PipelineRunId"]
        attempt = child["HealerRetryAttempt"]
        pipeline_name = child["PipelineName"]
        org_error_type = child.get("OrgErrorType", "")

        # Skip if there's already a restart thread pending for this saga
        with self._lock:
            if org_log_id in self._pending_restarts:
                print(f"   [SKIP] OrgLogId {org_log_id} already has a pending restart, skipping child {child_run_id}")
                return

        # Query ADF for child run status
        status_result = get_pipeline_run_status(child_run_id)
        adf_status = status_result.get("status", "Unknown")

        # Still running — skip, check next cycle (don't stamp HealerProcessedAt)
        if adf_status in ("InProgress", "Queued", "Cancelling"):
            return

        if adf_status == "Succeeded":
            # ── CHILD SUCCEEDED → AutoHealed ──
            print(f"   [HEALED] Pipeline '{pipeline_name}' retry succeeded! "
                  f"(Attempt {attempt}, Child Run: {child_run_id})")

            self._update_model_action(action_id, is_success=True, error_type=org_error_type,
                                      action_taken="auto_restart")
            self._write_final_outcome(org_log_id, "AutoHealed")

            # Clean up saga
            with self._lock:
                self._active_sagas.pop(org_log_id, None)
                self._pending_restarts.discard(org_log_id)

        elif adf_status in ("Failed", "Cancelled"):
            # ── CHILD FAILED ──
            print(f"   [RETRY-FAIL] Pipeline '{pipeline_name}' retry failed "
                  f"(Attempt {attempt}/{MAX_RESTART_ATTEMPTS}, Child Run: {child_run_id})")

            # Classify the child's error for tracking
            child_error_type = org_error_type  # Default to parent's type

            # Update ModelActions with failure
            self._update_model_action(action_id, is_success=False, error_type=child_error_type,
                                      action_taken="auto_restart")

            if attempt < MAX_RESTART_ATTEMPTS:
                # More attempts left — schedule next restart
                # Parse error type number from string like "Type 3 - Credentials Expired"
                error_type_num = self._parse_error_type_num(org_error_type)
                _, wait_secs = RESTART_STRATEGIES.get(error_type_num, ("Retry", 60))

                print(f"   [RETRY] Scheduling attempt {attempt + 1}/{MAX_RESTART_ATTEMPTS} "
                      f"(wait {wait_secs}s)")

                self._schedule_restart(
                    pipeline_name=pipeline_name,
                    log_id=org_log_id,
                    org_run_id=child["OrgPipelineRunId"],
                    attempt=attempt + 1,
                    wait_secs=wait_secs,
                )
            else:
                # Max retries exhausted — escalate
                print(f"   [LIMIT] All {MAX_RESTART_ATTEMPTS} restart attempts failed "
                      f"for '{pipeline_name}'. Escalating...")

                self._write_final_outcome(org_log_id, "Escalated")
                self._trigger_escalation(org_log_id, reason="max_retries_exhausted")

                # Clean up saga
                with self._lock:
                    self._active_sagas.pop(org_log_id, None)
                    self._pending_restarts.discard(org_log_id)

        else:
            # Unknown status — log and skip
            print(f"   [WARN] Child run {child_run_id} has unknown status: {adf_status}")

    # ── Step B: Poll New Failures ──────────────────────────────

    def _poll_new_failures(self):
        """
        Poll PipelineRunLog for unprocessed failed pipeline runs.
        A run is "unprocessed" if HealerInitialActionTaken IS NULL.
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute("""
                SELECT
                    LogId,
                    DataFactoryName,
                    PipelineName,
                    PipelineRunId,
                    TriggerName,
                    TriggerType,
                    TriggerTime,
                    IsSuccess,
                    ExecutionStatus,
                    StartTime,
                    EndTime,
                    DurationInSeconds,
                    ErrorCode,
                    ErrorMessage,
                    FailureType,
                    FailedActivityName,
                    RowsCopied,
                    DataRead,
                    DataWritten,
                    CustomParameter,
                    LoggedAt,
                    LoggedBy
                FROM sql.PipelineRunLog
                WHERE HealerInitialActionTaken IS NULL
                  AND ExecutionStatus IN ('Failed', 'Cancelled')
                ORDER BY LogId ASC
            """)

            rows = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description]

            if not rows:
                conn.close()
                return

            print(f"   [NEW] Found {len(rows)} unprocessed failed run(s)!")

            for row in rows:
                row_dict = dict(zip(columns, row))
                log_id = row_dict["LogId"]

                # Skip if already processed in this session
                if log_id in self.processed_log_ids:
                    continue

                self.processed_log_ids.add(log_id)

                pipeline_name = row_dict["PipelineName"]
                pipeline_run_id = row_dict["PipelineRunId"]

                print(f"\n   [FAILED] Pipeline '{pipeline_name}' "
                      f"(LogId: {log_id}, RunId: {pipeline_run_id})")

                # Build error_details dict (same format as before)
                error_details = self._row_to_error_details(row_dict)

                # Classify through intelligence layer
                try:
                    result = process_error(error_details)

                    action = result["action"]
                    error_type = result["error_type"]
                    error_type_name = result["error_type_name"]
                    classification = result["classification"]
                    pipeline_metadata = result["pipeline_metadata"]
                    wait_secs = result["wait_seconds"]

                    # Format error type string for SQL column
                    error_type_str = f"Type {error_type} - {error_type_name}"

                    # UPDATE PipelineRunLog with initial classification
                    self._update_initial_action(conn, log_id, error_type_str, action)

                    # Store saga context for child handling
                    with self._lock:
                        self._active_sagas[log_id] = {
                            "error_details": error_details,
                            "classification": classification,
                            "pipeline_metadata": pipeline_metadata,
                        }

                    if action == "auto_restart":
                        # Schedule non-blocking restart
                        self._schedule_restart(
                            pipeline_name=pipeline_name,
                            log_id=log_id,
                            org_run_id=pipeline_run_id,
                            attempt=1,
                            wait_secs=wait_secs,
                        )
                    elif action == "escalate":
                        # Immediate escalation (Types 1, 2, 6)
                        self._write_final_outcome(log_id, "Escalated")
                        handle_escalation(error_details, classification, pipeline_metadata)

                        # Clean up saga
                        with self._lock:
                            self._active_sagas.pop(log_id, None)

                except Exception as e:
                    print(f"   [ERROR] Processing failed for LogId {log_id}: {str(e)}")
                    self._update_initial_action(conn, log_id, "Unknown", "processing_error")
                    self._write_final_outcome(log_id, "ProcessingError")

            conn.close()

        except pyodbc.Error as e:
            print(f"   [ERROR] New failures poll SQL error: {str(e)}")
        except Exception as e:
            print(f"   [ERROR] New failures poll error: {str(e)}")

    # ── Non-Blocking Restart ──────────────────────────────────

    def _schedule_restart(self, pipeline_name, log_id, org_run_id, attempt, wait_secs):
        """
        Spawn a background thread that:
          1. Sleeps for wait_secs (60/90/120s depending on error type)
          2. Calls restart_pipeline() via Azure REST API
          3. INSERTs the child run into ModelActions

        The main poll loop continues immediately — NO BLOCKING.
        Guards against duplicate threads via _pending_restarts set.
        """
        # Prevent duplicate restart threads for the same saga
        with self._lock:
            if log_id in self._pending_restarts:
                print(f"   [SKIP] Restart already pending for LogId {log_id}, "
                      f"ignoring duplicate attempt {attempt}")
                return
            self._pending_restarts.add(log_id)

        def _do_restart():
            print(f"   [THREAD] Waiting {wait_secs}s before restart "
                  f"('{pipeline_name}', attempt {attempt})...")
            time.sleep(wait_secs)

            print(f"   [RESTART] Restarting '{pipeline_name}' (attempt {attempt})...")
            try:
                from listener.azure_client import restart_pipeline
                result = restart_pipeline(pipeline_name, parameters={"isChild": 1})

                if result["success"]:
                    child_run_id = result["run_id"]
                    print(f"   [OK] Pipeline restarted. Child Run ID: {child_run_id} "
                          f"(attempt {attempt})")

                    # INSERT into ModelActions
                    self._insert_model_action(
                        org_log_id=log_id,
                        org_run_id=org_run_id,
                        child_run_id=child_run_id,
                        attempt=attempt,
                        action="auto_restart",
                    )
                else:
                    print(f"   [WARN] Restart API failed for '{pipeline_name}': "
                          f"{result['message']}")

                    # Insert a failed ModelActions entry so we don't lose track
                    self._insert_model_action(
                        org_log_id=log_id,
                        org_run_id=org_run_id,
                        child_run_id=None,  # No child created
                        attempt=attempt,
                        action="restart_api_failed",
                    )

                    if attempt >= MAX_RESTART_ATTEMPTS:
                        # Can't restart — escalate
                        self._write_final_outcome(log_id, "Escalated")
                        self._trigger_escalation(log_id, reason="restart_api_failed")
                    else:
                        # Try again with next attempt
                        # Release lock first so recursive call can acquire it
                        with self._lock:
                            self._pending_restarts.discard(log_id)
                        self._schedule_restart(
                            pipeline_name=pipeline_name,
                            log_id=log_id,
                            org_run_id=org_run_id,
                            attempt=attempt + 1,
                            wait_secs=wait_secs,
                        )
                        return  # Skip the finally-style discard below

            except Exception as e:
                print(f"   [ERROR] Restart thread error for '{pipeline_name}': {str(e)}")
            finally:
                # Release the pending lock so next poll can schedule if needed
                with self._lock:
                    self._pending_restarts.discard(log_id)

        thread = threading.Thread(target=_do_restart, daemon=True,
                                  name=f"restart-{pipeline_name}-{attempt}")
        thread.start()

    # ── SQL Write Helpers ─────────────────────────────────────

    def _update_initial_action(self, conn, log_id, error_type, action):
        """
        UPDATE PipelineRunLog with the initial classification and action.
        Called once per original failure (Step B).
        """
        try:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE sql.PipelineRunLog
                SET HealerErrorType = ?,
                    HealerInitialActionTaken = ?
                WHERE LogId = ?
            """, error_type, action, log_id)
            conn.commit()
            print(f"   [SQL] Updated LogId {log_id}: "
                  f"error_type={error_type}, action={action}")
        except Exception as e:
            print(f"   [WARN] Could not update LogId {log_id}: {str(e)}")

    def _write_final_outcome(self, log_id, outcome):
        """
        UPDATE PipelineRunLog with the final outcome.
        Called when saga completes (child succeeded, max retries, or immediate escalation).
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE sql.PipelineRunLog
                SET HealerFinalOutcome = ?,
                    HealerResolvedAt = SYSUTCDATETIME()
                WHERE LogId = ?
            """, outcome, log_id)
            conn.commit()
            conn.close()
            print(f"   [SQL] Final outcome for LogId {log_id}: {outcome}")
        except Exception as e:
            print(f"   [WARN] Could not write final outcome for LogId {log_id}: {str(e)}")

    def _insert_model_action(self, org_log_id, org_run_id, child_run_id, attempt, action):
        """
        INSERT a new row into ModelActions for a restart attempt.
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO sql.ModelActions
                    (OrgLogId, OrgPipelineRunId, PipelineRunId,
                     HealerRetryAttempt, IsSuccess, HealerActionTaken)
                VALUES (?, ?, ?, ?, 0, ?)
            """, org_log_id, org_run_id, child_run_id, attempt, action)
            conn.commit()
            conn.close()
            print(f"   [SQL] Inserted ModelAction: OrgLogId={org_log_id}, "
                  f"child={child_run_id}, attempt={attempt}")
        except Exception as e:
            print(f"   [WARN] Could not insert ModelAction: {str(e)}")

    def _update_model_action(self, action_id, is_success, error_type, action_taken):
        """
        UPDATE a ModelActions row with the child run result.
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE sql.ModelActions
                SET IsSuccess = ?,
                    HealerErrorType = ?,
                    HealerActionTaken = ?,
                    HealerProcessedAt = SYSUTCDATETIME()
                WHERE ActionId = ?
            """, 1 if is_success else 0, error_type, action_taken, action_id)
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"   [WARN] Could not update ModelAction {action_id}: {str(e)}")

    # ── Escalation Helper ─────────────────────────────────────

    def _trigger_escalation(self, log_id, reason="max_retries_exhausted"):
        """
        Trigger escalation using the stored saga context.
        Generates the error document and sends the email notification.
        """
        with self._lock:
            saga = self._active_sagas.get(log_id)

        if not saga:
            print(f"   [WARN] No saga context found for LogId {log_id}, "
                  f"skipping escalation doc/email")
            return

        error_details = saga["error_details"]
        classification = saga["classification"]
        pipeline_metadata = saga["pipeline_metadata"]

        # Add retry info for the escalation message
        error_details["retry_info"] = {
            "max_retries": MAX_RESTART_ATTEMPTS,
            "reason": reason,
        }

        handle_escalation(error_details, classification, pipeline_metadata,
                          reason=reason)

    # ── Data Conversion ───────────────────────────────────────

    def _row_to_error_details(self, row):
        """
        Convert a PipelineRunLog row to the error_details dict format
        expected by process_error(). This is the adapter layer that makes
        the SQL listener compatible with the existing processor.
        """
        error_message = row.get("ErrorMessage") or ""
        error_code = row.get("ErrorCode") or "Unknown"
        activity_name = row.get("FailedActivityName") or "Unknown"
        duration = row.get("DurationInSeconds")

        return {
            # Core fields (same as adf_listener output)
            "pipeline_name": row["PipelineName"],
            "run_id": row["PipelineRunId"],
            "combined_error": error_message,
            "timestamp": str(row.get("LoggedAt") or ""),

            "failed_activities": [
                {
                    "activity_name": activity_name,
                    "activity_type": "Unknown",
                    "error_code": error_code,
                    "error_message": error_message,
                    "duration": f"{duration}s" if duration else "N/A"
                }
            ],

            # Extra context from SQL table
            "failure_type": row.get("FailureType"),
            "data_factory": row.get("DataFactoryName"),
            "execution_status": row.get("ExecutionStatus"),
            "start_time": str(row.get("StartTime") or ""),
            "end_time": str(row.get("EndTime") or ""),
            "duration_seconds": duration,
            "trigger_name": row.get("TriggerName"),
            "trigger_type": row.get("TriggerType"),
            "rows_copied": row.get("RowsCopied"),
            "data_read": row.get("DataRead"),
            "data_written": row.get("DataWritten"),

            # LogId for linking back
            "log_id": row["LogId"],
        }

    # ── Utilities ─────────────────────────────────────────────

    @staticmethod
    def _parse_error_type_num(error_type_str):
        """
        Parse error type number from a string like 'Type 3 - Credentials Expired'.
        Returns int or 1 as default.
        """
        if not error_type_str:
            return 1
        try:
            # Extract the number after "Type "
            parts = error_type_str.split(" - ")[0]  # "Type 3"
            return int(parts.replace("Type ", "").strip())
        except (ValueError, IndexError):
            return 1


def start_listener():
    """Start the SQL table listener service."""
    print("=" * 60)
    print("[START] SQL Table Listener v2 (Two-Table Architecture)")
    print("=" * 60)
    print(f"[INFO] Tables: sql.PipelineRunLog (read/update) + sql.ModelActions (managed)")
    print(f"[INFO] Max restart attempts: {MAX_RESTART_ATTEMPTS}")
    print(f"[INFO] Restart strategies: {RESTART_STRATEGIES}")

    listener = SQLListener()

    # Schedule the check every POLL_INTERVAL seconds
    schedule.every(POLL_INTERVAL).seconds.do(listener.check_for_failures)

    # Run once immediately
    listener.check_for_failures()

    # Keep running forever
    print(f"\n[INFO] Polling every {POLL_INTERVAL} seconds. Press Ctrl+C to stop.\n")
    try:
        while True:
            schedule.run_pending()
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\n[STOP] Listener stopped.")


if __name__ == "__main__":
    start_listener()
