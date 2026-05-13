"""
SQL Table Listener Service.
Polls the Azure SQL PipelineRunLog table every 30 seconds for failed pipeline runs.
When a failure is detected, it builds an error_details dict and sends it
to the intelligence layer for classification — same interface as adf_listener.
"""
import time
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
from intelligence.error_processor import process_error, restart_tracker


class SQLListener:
    """Continuously monitors PipelineRunLog table for failed pipeline runs."""

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

        # Track processed run IDs in memory (prevent duplicates within session)
        self.processed_runs = set()

    def _get_connection(self):
        """Get a fresh database connection."""
        return pyodbc.connect(self.conn_str)

    def check_for_failures(self):
        """Poll PipelineRunLog for unprocessed failed pipeline runs."""
        now = datetime.now(IST).strftime("%H:%M:%S")
        print(f"\n[POLL] [{now}] Checking PipelineRunLog for failed runs...")

        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            # Query unprocessed failed/cancelled runs
            cursor.execute("""
                SELECT
                    LogId,
                    DataFactoryName,
                    PipelineName,
                    PipelineRunId,
                    TriggerName,
                    TriggerType,
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
                    CustomParameters,
                    RetryAttempt,
                    IsRetry,
                    LoggedAt
                FROM PipelineRunLog
                WHERE ProcessedByHealer = 0
                  AND ExecutionStatus IN ('Failed', 'Cancelled')
                ORDER BY LogId ASC
            """)

            rows = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description]

            if not rows:
                print("   [OK] No unprocessed failures found.")
                conn.close()
                return 0

            print(f"   [ALERT] Found {len(rows)} unprocessed failed run(s)!")

            for row in rows:
                # Convert row to dict for easier access
                row_dict = dict(zip(columns, row))

                pipeline_run_id = row_dict["PipelineRunId"]
                log_id = row_dict["LogId"]

                # Skip if already processed in this session
                if pipeline_run_id in self.processed_runs:
                    self._mark_processed(conn, log_id, "skipped_duplicate")
                    continue

                self.processed_runs.add(pipeline_run_id)

                # Check if this run was created by a restart (child of a previous failure)
                is_retry = restart_tracker.is_restart_child(pipeline_run_id)
                if is_retry:
                    print(f"\n   [RETRY-FAIL] Pipeline '{row_dict['PipelineName']}' "
                          f"failed again (Run ID: {pipeline_run_id})")
                else:
                    print(f"\n   [FAILED] Pipeline '{row_dict['PipelineName']}' "
                          f"(Run ID: {pipeline_run_id})")

                # Build error_details dict (same format as adf_listener)
                error_details = self._row_to_error_details(row_dict)

                # Process the error through the intelligence layer
                try:
                    result = process_error(error_details)

                    # Use the classification result to update all tracking fields
                    self._mark_processed(
                        conn=conn,
                        log_id=log_id,
                        action=result.get("action", "unknown"),
                        error_type_name=result.get("error_type_name", ""),
                        is_retry=result.get("is_retry", is_retry),
                        retry_attempt=result.get("attempt_count", 0),
                    )

                except Exception as e:
                    print(f"   [ERROR] Processing failed for LogId {log_id}: {str(e)}")
                    self._mark_processed(
                        conn=conn,
                        log_id=log_id,
                        action="processing_error",
                        error_type_name="",
                        is_retry=is_retry,
                        retry_attempt=0,
                    )

            # After processing failures, check for successful child runs
            # that need IsRetry marking (retry succeeded → never goes through process_error)
            self._mark_successful_retries(conn)

            conn.close()
            return len(rows)

        except pyodbc.Error as e:
            print(f"   [ERROR] SQL query failed: {str(e)}")
            return 0
        except Exception as e:
            print(f"   [ERROR] Unexpected error: {str(e)}")
            return 0

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

            # Extra context from SQL table (available for classifier)
            "failure_type": row.get("FailureType"),
            "data_factory": row.get("DataFactoryName"),
            "execution_status": row.get("ExecutionStatus"),
            "start_time": str(row.get("StartTime") or ""),
            "end_time": str(row.get("EndTime") or ""),
            "duration_seconds": duration,
            "adf_retry_attempt": row.get("RetryAttempt") or 0,
            "adf_is_retry": bool(row.get("IsRetry")),
            "trigger_name": row.get("TriggerName"),
            "trigger_type": row.get("TriggerType"),
            "rows_copied": row.get("RowsCopied"),
            "data_read": row.get("DataRead"),
            "data_written": row.get("DataWritten"),
        }

    def _mark_processed(self, conn, log_id, action, error_type_name="",
                         is_retry=False, retry_attempt=0):
        """
        Update the PipelineRunLog row to mark it as processed by the healer.
        Writes all tracking fields: ProcessedByHealer, HealerProcessedAt,
        HealerAction, HealerErrorType, IsRetry, RetryAttempt.
        """
        try:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE PipelineRunLog
                SET ProcessedByHealer = 1,
                    HealerProcessedAt = SYSUTCDATETIME(),
                    HealerAction = ?,
                    HealerErrorType = ?,
                    IsRetry = ?,
                    RetryAttempt = ?
                WHERE LogId = ?
            """, action, error_type_name, 1 if is_retry else 0, retry_attempt, log_id)
            conn.commit()
            print(f"   [SQL] Updated LogId {log_id}: action={action}, "
                  f"error_type={error_type_name}, is_retry={is_retry}, "
                  f"retry_attempt={retry_attempt}")
        except Exception as e:
            print(f"   [WARN] Could not update LogId {log_id}: {str(e)}")

    def _mark_successful_retries(self, conn):
        """
        Scan for succeeded pipeline runs that are known restart children.
        When a retry succeeds, the listener never processes it (only failures
        are processed), so its IsRetry field stays 0. This method fixes that.
        """
        child_run_ids = restart_tracker.get_all_child_run_ids()
        if not child_run_ids:
            return

        try:
            cursor = conn.cursor()
            # Build parameterized IN clause
            placeholders = ",".join(["?" for _ in child_run_ids])
            query = f"""
                SELECT LogId, PipelineRunId, PipelineName
                FROM PipelineRunLog
                WHERE PipelineRunId IN ({placeholders})
                  AND ExecutionStatus = 'Succeeded'
                  AND IsRetry = 0
            """
            cursor.execute(query, list(child_run_ids))
            rows = cursor.fetchall()

            for row in rows:
                log_id, run_id, pipeline_name = row[0], row[1], row[2]
                attempt_num = restart_tracker.get_child_attempt_number(run_id)

                cursor.execute("""
                    UPDATE PipelineRunLog
                    SET IsRetry = 1,
                        RetryAttempt = ?,
                        ProcessedByHealer = 1,
                        HealerProcessedAt = SYSUTCDATETIME(),
                        HealerAction = 'auto_healed'
                    WHERE LogId = ?
                """, attempt_num, log_id)
                conn.commit()

                print(f"   [HEALED] Pipeline '{pipeline_name}' retry succeeded! "
                      f"(Run: {run_id}, Attempt: {attempt_num}) → IsRetry=1")

                # Reset tracker for this pipeline since the retry worked
                restart_tracker.reset_pipeline(pipeline_name)

        except Exception as e:
            print(f"   [WARN] Error checking successful retries: {str(e)}")


def start_listener():
    """Start the SQL table listener service."""
    print("=" * 60)
    print("[START] SQL Table Listener - Starting...")
    print("=" * 60)

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
