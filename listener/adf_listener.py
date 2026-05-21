"""
ADF SDK Listener Service (v2 — Two-Table Architecture).

Polls Azure Data Factory SDK every 30 seconds for ALL pipeline runs.
Logs every run into adf.PipelineRunLog (we do the INSERT, not a SP).
For failures, follows the same saga pattern as sql_listener:
  Step A: adf.ModelActions  — check pending child runs
  Step B: ADF SDK poll      — log all runs, process failures

Tables:
  adf.PipelineRunLog  — all pipeline runs (success + failure)
  adf.ModelActions     — restart attempts / child runs
"""
import time
import threading
import pyodbc
import schedule
import sys
import os
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config.settings import AzureConfig, SqlConfig, POLL_INTERVAL
from intelligence.error_processor import (
    process_error, handle_escalation, MAX_RESTART_ATTEMPTS,
    RESTART_STRATEGIES
)


class ADFListener:
    """
    Polls ADF SDK for all pipeline runs and manages the two-table saga.

    Each 30s poll cycle:
      Step A: _poll_child_runs()   — check adf.ModelActions for finished children
      Step B: _poll_adf_runs()     — query ADF SDK, INSERT into adf.PipelineRunLog,
                                     process any failures
    """

    def __init__(self):
        print("[INIT] Connecting to Azure Data Factory + SQL Database...")

        # ADF SDK client
        from azure.identity import ClientSecretCredential
        from azure.mgmt.datafactory import DataFactoryManagementClient

        self.credential = ClientSecretCredential(
            tenant_id=AzureConfig.TENANT_ID,
            client_id=AzureConfig.CLIENT_ID,
            client_secret=AzureConfig.CLIENT_SECRET
        )
        self.adf_client = DataFactoryManagementClient(
            credential=self.credential,
            subscription_id=AzureConfig.SUBSCRIPTION_ID
        )

        # SQL connection string
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

        # Test SQL connection
        try:
            conn = pyodbc.connect(self.conn_str)
            conn.close()
            print(f"[OK] SQL Connected: {SqlConfig.SERVER}/{SqlConfig.DATABASE}")
        except Exception as e:
            print(f"[ERROR] SQL connection failed: {e}")
            raise

        # Track processed ADF run IDs (prevent duplicate INSERTs)
        self.processed_run_ids = set()

        # How far back to look on first poll
        self.last_check_time = datetime.now(IST) - timedelta(minutes=5)

        # Saga state
        self._active_sagas = {}
        self._pending_restarts = set()
        self._lock = threading.Lock()

        print(f"[OK] ADF Connected: {AzureConfig.FACTORY_NAME}")
        print(f"[INFO] Resource Group: {AzureConfig.RESOURCE_GROUP}")

    def _get_connection(self):
        return pyodbc.connect(self.conn_str)

    # ── Main Poll Cycle ────────────────────────────────────────

    def check_for_failures(self):
        now = datetime.now(IST)
        print(f"\n[POLL] [{now.strftime('%H:%M:%S')}] Poll cycle starting...")
        self._poll_child_runs()
        self._poll_adf_runs()

    # ── Step A: Poll Child Runs (adf.ModelActions) ─────────────

    def _poll_child_runs(self):
        """Check adf.ModelActions for children whose ADF run completed."""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT
                    ma.ActionId, ma.OrgLogId, ma.OrgPipelineRunId,
                    ma.PipelineRunId, ma.HealerRetryAttempt, ma.IsSuccess,
                    prl.PipelineName, prl.HealerErrorType AS OrgErrorType
                FROM adf.ModelActions ma
                JOIN adf.PipelineRunLog prl ON prl.LogId = ma.OrgLogId
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
                self._check_single_child(dict(zip(columns, row)))

        except Exception as e:
            print(f"   [ERROR] Child poll error: {e}")

    def _check_single_child(self, child):
        from listener.azure_client import get_pipeline_run_status

        action_id = child["ActionId"]
        org_log_id = child["OrgLogId"]
        child_run_id = child["PipelineRunId"]
        attempt = child["HealerRetryAttempt"]
        pipeline_name = child["PipelineName"]
        org_error_type = child.get("OrgErrorType", "")

        with self._lock:
            if org_log_id in self._pending_restarts:
                return

        status_result = get_pipeline_run_status(child_run_id)
        adf_status = status_result.get("status", "Unknown")

        if adf_status in ("InProgress", "Queued", "Cancelling"):
            return

        if adf_status == "Succeeded":
            print(f"   [HEALED] '{pipeline_name}' retry succeeded! "
                  f"(Attempt {attempt}, Child: {child_run_id})")
            self._update_model_action(action_id, True, org_error_type, "auto_restart")
            self._write_final_outcome(org_log_id, "AutoHealed")
            with self._lock:
                self._active_sagas.pop(org_log_id, None)
                self._pending_restarts.discard(org_log_id)

        elif adf_status in ("Failed", "Cancelled"):
            print(f"   [RETRY-FAIL] '{pipeline_name}' retry failed "
                  f"(Attempt {attempt}/{MAX_RESTART_ATTEMPTS}, Child: {child_run_id})")
            self._update_model_action(action_id, False, org_error_type, "auto_restart")

            if attempt < MAX_RESTART_ATTEMPTS:
                error_type_num = self._parse_error_type_num(org_error_type)
                _, wait_secs = RESTART_STRATEGIES.get(error_type_num, ("Retry", 60))
                print(f"   [RETRY] Scheduling attempt {attempt + 1}/{MAX_RESTART_ATTEMPTS}")
                self._schedule_restart(pipeline_name, org_log_id,
                                       child["OrgPipelineRunId"], attempt + 1, wait_secs)
            else:
                print(f"   [LIMIT] All {MAX_RESTART_ATTEMPTS} attempts failed for "
                      f"'{pipeline_name}'. Escalating...")
                self._write_final_outcome(org_log_id, "Escalated")
                self._trigger_escalation(org_log_id, "max_retries_exhausted")
                with self._lock:
                    self._active_sagas.pop(org_log_id, None)
                    self._pending_restarts.discard(org_log_id)

    # ── Step B: Poll ADF SDK ───────────────────────────────────

    def _poll_adf_runs(self):
        """Query ADF SDK for all pipeline runs, INSERT into adf.PipelineRunLog."""
        now = datetime.now(IST)
        try:
            runs_response = self.adf_client.pipeline_runs.query_by_factory(
                resource_group_name=AzureConfig.RESOURCE_GROUP,
                factory_name=AzureConfig.FACTORY_NAME,
                filter_parameters={
                    "lastUpdatedAfter": self.last_check_time,
                    "lastUpdatedBefore": now,
                }
            )
            all_runs = runs_response.value or []
            self.last_check_time = now

            if not all_runs:
                print("  [OK] ADF SDK: 0 new pipeline runs.")
                return

            new_runs = [r for r in all_runs if r.run_id not in self.processed_run_ids]
            if not new_runs:
                print(f"  [OK] ADF SDK: {len(all_runs)} runs (all already processed).")
                return

            succeeded = [r for r in new_runs if r.status == "Succeeded"]
            failed = [r for r in new_runs if r.status in ("Failed", "Cancelled")]
            other = [r for r in new_runs if r.status not in ("Succeeded", "Failed", "Cancelled")]

            print(f"   [SDK] {len(new_runs)} new run(s): "
                  f"{len(succeeded)} succeeded, {len(failed)} failed, {len(other)} other")

            conn = self._get_connection()

            # Log ALL runs (success + failure) into adf.PipelineRunLog
            for run in new_runs:
                if run.status in ("InProgress", "Queued", "Cancelling"):
                    continue  # Skip still-running pipelines
                self.processed_run_ids.add(run.run_id)
                log_id = self._insert_pipeline_run(conn, run)

                # Process failures through the saga
                if run.status in ("Failed", "Cancelled") and log_id:
                    error_details = self._build_error_details(run, log_id)
                    self._process_failure(conn, log_id, error_details, run)

            conn.close()

        except Exception as e:
            print(f"   [ERROR] ADF SDK poll error: {e}")

    def _insert_pipeline_run(self, conn, run) -> int:
        """INSERT a pipeline run into adf.PipelineRunLog. Returns LogId."""
        try:
            cursor = conn.cursor()
            duration = None
            if run.run_start and run.run_end:
                duration = int((run.run_end - run.run_start).total_seconds())

            # Extract error info
            error_code = None
            error_message = run.message or None
            failure_type = None
            failed_activity = None

            if run.status in ("Failed", "Cancelled"):
                # Get activity-level errors
                act_errors = self._get_activity_errors(run)
                if act_errors["failed_activities"]:
                    first = act_errors["failed_activities"][0]
                    error_code = first.get("error_code")
                    error_message = first.get("error_message") or run.message
                    failed_activity = first.get("activity_name")

            is_success = 1 if run.status == "Succeeded" else 0

            cursor.execute("""
                INSERT INTO adf.PipelineRunLog (
                    DataFactoryName, PipelineName, PipelineRunId,
                    TriggerName, TriggerType, TriggerTime,
                    IsSuccess, ExecutionStatus,
                    StartTime, EndTime, DurationInSeconds,
                    ErrorCode, ErrorMessage, FailureType, FailedActivityName,
                    RowsCopied, DataRead, DataWritten
                )
                OUTPUT INSERTED.LogId
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                AzureConfig.FACTORY_NAME, run.pipeline_name, run.run_id,
                None, None, None,  # trigger info not available from SDK
                is_success, run.status,
                run.run_start, run.run_end, duration,
                error_code, error_message, failure_type, failed_activity,
                None, None, None  # metrics
            )

            # OUTPUT INSERTED.LogId returns the identity as a result set
            row = cursor.fetchone()
            log_id = int(row[0]) if row and row[0] else None
            conn.commit()

            if log_id:
                status_label = "✓" if is_success else "✗"
                print(f"   [{status_label}] Logged: '{run.pipeline_name}' "
                      f"({run.status}) → LogId {log_id}")
            else:
                print(f"   [WARN] INSERT succeeded but no LogId returned for {run.run_id}")
            return log_id

        except Exception as e:
            print(f"   [WARN] Could not INSERT run {run.run_id}: {e}")
            return None

    def _process_failure(self, conn, log_id, error_details, run):
        """Process a failed pipeline run through the classification + saga."""
        pipeline_name = run.pipeline_name
        pipeline_run_id = run.run_id

        print(f"\n   [FAILED] Processing: '{pipeline_name}' "
              f"(LogId: {log_id}, RunId: {pipeline_run_id})")

        try:
            result = process_error(error_details)
            action = result["action"]
            error_type = result["error_type"]
            error_type_name = result["error_type_name"]
            classification = result["classification"]
            pipeline_metadata = result["pipeline_metadata"]
            wait_secs = result["wait_seconds"]

            error_type_str = f"Type {error_type} - {error_type_name}"
            self._update_initial_action(conn, log_id, error_type_str, action)

            with self._lock:
                self._active_sagas[log_id] = {
                    "error_details": error_details,
                    "classification": classification,
                    "pipeline_metadata": pipeline_metadata,
                }

            if action == "auto_restart":
                self._schedule_restart(pipeline_name, log_id, pipeline_run_id,
                                       1, wait_secs)
            elif action == "escalate":
                self._write_final_outcome(log_id, "Escalated")
                handle_escalation(error_details, classification, pipeline_metadata)
                with self._lock:
                    self._active_sagas.pop(log_id, None)

        except Exception as e:
            print(f"   [ERROR] Processing failed for LogId {log_id}: {e}")
            self._update_initial_action(conn, log_id, "Unknown", "processing_error")
            self._write_final_outcome(log_id, "ProcessingError")

    # ── ADF Activity Errors ───────────────────────────────────

    def _get_activity_errors(self, pipeline_run):
        """Get activity-level error details for a pipeline run."""
        try:
            activities = self.adf_client.activity_runs.query_by_pipeline_run(
                resource_group_name=AzureConfig.RESOURCE_GROUP,
                factory_name=AzureConfig.FACTORY_NAME,
                run_id=pipeline_run.run_id,
                filter_parameters={
                    "lastUpdatedAfter": pipeline_run.run_start or self.last_check_time,
                    "lastUpdatedBefore": datetime.now(IST)
                }
            )
            failed_activities = []
            error_messages = []
            for act in (activities.value or []):
                if act.status == "Failed":
                    err_msg = ""
                    err_code = "Unknown"
                    if act.error:
                        if isinstance(act.error, dict):
                            err_msg = str(act.error.get("message", ""))
                            err_code = act.error.get("errorCode", "Unknown")
                        else:
                            err_msg = str(act.error)
                    failed_activities.append({
                        "activity_name": act.activity_name,
                        "activity_type": act.activity_type,
                        "error_message": err_msg,
                        "error_code": err_code,
                        "duration": f"{act.duration_in_ms}ms" if act.duration_in_ms else "N/A"
                    })
                    error_messages.append(err_msg)
            return {"failed_activities": failed_activities,
                    "combined_error": " | ".join(error_messages)}
        except Exception as e:
            print(f"   [WARN] Could not get activities: {e}")
            return {"failed_activities": [], "combined_error": pipeline_run.message or ""}

    def _build_error_details(self, run, log_id):
        """Build the error_details dict from an ADF SDK run object."""
        act_info = self._get_activity_errors(run)
        return {
            "pipeline_name": run.pipeline_name,
            "run_id": run.run_id,
            "combined_error": act_info["combined_error"],
            "timestamp": datetime.now(IST).isoformat(),
            "failed_activities": act_info["failed_activities"],
            "data_factory": AzureConfig.FACTORY_NAME,
            "execution_status": run.status,
            "start_time": str(run.run_start or ""),
            "end_time": str(run.run_end or ""),
            "duration_seconds": (
                int((run.run_end - run.run_start).total_seconds())
                if run.run_start and run.run_end else None
            ),
            "log_id": log_id,
        }

    # ── Non-Blocking Restart ──────────────────────────────────

    def _schedule_restart(self, pipeline_name, log_id, org_run_id, attempt, wait_secs):
        with self._lock:
            if log_id in self._pending_restarts:
                print(f"   [SKIP] Restart already pending for LogId {log_id}")
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
                    print(f"   [OK] Restarted. Child: {child_run_id} (attempt {attempt})")
                    self._insert_model_action(log_id, org_run_id, child_run_id,
                                              attempt, "auto_restart")
                    # Mark this child run as processed so _poll_adf_runs skips it
                    self.processed_run_ids.add(child_run_id)
                else:
                    print(f"   [WARN] Restart API failed: {result['message']}")
                    self._insert_model_action(log_id, org_run_id, None,
                                              attempt, "restart_api_failed")
                    if attempt >= MAX_RESTART_ATTEMPTS:
                        self._write_final_outcome(log_id, "Escalated")
                        self._trigger_escalation(log_id, "restart_api_failed")
                    else:
                        with self._lock:
                            self._pending_restarts.discard(log_id)
                        self._schedule_restart(pipeline_name, log_id, org_run_id,
                                               attempt + 1, wait_secs)
                        return
            except Exception as e:
                print(f"   [ERROR] Restart thread error: {e}")
            finally:
                with self._lock:
                    self._pending_restarts.discard(log_id)

        thread = threading.Thread(target=_do_restart, daemon=True,
                                  name=f"adf-restart-{pipeline_name}-{attempt}")
        thread.start()

    # ── SQL Write Helpers (adf schema) ────────────────────────

    def _update_initial_action(self, conn, log_id, error_type, action):
        try:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE adf.PipelineRunLog
                SET HealerErrorType = ?, HealerInitialActionTaken = ?
                WHERE LogId = ?
            """, error_type, action, log_id)
            conn.commit()
            print(f"   [SQL] Updated LogId {log_id}: error_type={error_type}, action={action}")
        except Exception as e:
            print(f"   [WARN] Could not update LogId {log_id}: {e}")

    def _write_final_outcome(self, log_id, outcome):
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE adf.PipelineRunLog
                SET HealerFinalOutcome = ?, HealerResolvedAt = SYSUTCDATETIME()
                WHERE LogId = ?
            """, outcome, log_id)
            conn.commit()
            conn.close()
            print(f"   [SQL] Final outcome for LogId {log_id}: {outcome}")
        except Exception as e:
            print(f"   [WARN] Could not write final outcome for LogId {log_id}: {e}")

    def _insert_model_action(self, org_log_id, org_run_id, child_run_id, attempt, action):
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO adf.ModelActions
                    (OrgLogId, OrgPipelineRunId, PipelineRunId,
                     HealerRetryAttempt, IsSuccess, HealerActionTaken)
                VALUES (?, ?, ?, ?, 0, ?)
            """, org_log_id, org_run_id, child_run_id, attempt, action)
            conn.commit()
            conn.close()
            print(f"   [SQL] Inserted ModelAction: OrgLogId={org_log_id}, "
                  f"child={child_run_id}, attempt={attempt}")
        except Exception as e:
            print(f"   [WARN] Could not insert ModelAction: {e}")

    def _update_model_action(self, action_id, is_success, error_type, action_taken):
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE adf.ModelActions
                SET IsSuccess = ?, HealerErrorType = ?,
                    HealerActionTaken = ?, HealerProcessedAt = SYSUTCDATETIME()
                WHERE ActionId = ?
            """, 1 if is_success else 0, error_type, action_taken, action_id)
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"   [WARN] Could not update ModelAction {action_id}: {e}")

    # ── Escalation & Utilities ────────────────────────────────

    def _trigger_escalation(self, log_id, reason="max_retries_exhausted"):
        with self._lock:
            saga = self._active_sagas.get(log_id)
        if not saga:
            print(f"   [WARN] No saga context for LogId {log_id}")
            return
        error_details = saga["error_details"]
        error_details["retry_info"] = {"max_retries": MAX_RESTART_ATTEMPTS, "reason": reason}
        handle_escalation(error_details, saga["classification"],
                          saga["pipeline_metadata"], reason=reason)

    @staticmethod
    def _parse_error_type_num(error_type_str):
        if not error_type_str:
            return 1
        try:
            return int(error_type_str.split(" - ")[0].replace("Type ", "").strip())
        except (ValueError, IndexError):
            return 1


def start_listener():
    print("=" * 60)
    print("[START] ADF SDK Listener v2 (Two-Table Architecture)")
    print("=" * 60)
    print(f"[INFO] Tables: adf.PipelineRunLog + adf.ModelActions")
    print(f"[INFO] Max restart attempts: {MAX_RESTART_ATTEMPTS}")

    listener = ADFListener()
    schedule.every(POLL_INTERVAL).seconds.do(listener.check_for_failures)
    listener.check_for_failures()

    print(f"\n[INFO] Polling every {POLL_INTERVAL}s. Press Ctrl+C to stop.\n")
    try:
        while True:
            schedule.run_pending()
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\n[STOP] Listener stopped.")


if __name__ == "__main__":
    start_listener()
