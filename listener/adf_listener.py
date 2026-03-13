"""
ADF Log Listener Service.
Polls Azure Data Factory every 30 seconds for failed pipeline runs.
When a failure is detected, it captures the error details and sends them
to the intelligence layer for classification.
"""
import time
from datetime import datetime, timedelta, timezone
from azure.identity import ClientSecretCredential
from azure.mgmt.datafactory import DataFactoryManagementClient
import schedule
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config.settings import AzureConfig, POLL_INTERVAL
from intelligence.error_processor import process_error


class ADFListener:
    """Continuously monitors ADF pipelines for failures."""

    def __init__(self):
        """Initialize Azure credentials and ADF client."""
        print("🔌 Connecting to Azure Data Factory...")

        # Create Azure credential using Service Principal
        self.credential = ClientSecretCredential(
            tenant_id=AzureConfig.TENANT_ID,
            client_id=AzureConfig.CLIENT_ID,
            client_secret=AzureConfig.CLIENT_SECRET
        )

        # Create ADF management client
        self.adf_client = DataFactoryManagementClient(
            credential=self.credential,
            subscription_id=AzureConfig.SUBSCRIPTION_ID
        )

        # Track which run IDs we've already processed (avoid duplicates)
        self.processed_runs = set()

        # How far back to look on first run
        self.last_check_time = datetime.now(timezone.utc) - timedelta(minutes=5)

        print(f"[OK] Connected to ADF: {AzureConfig.FACTORY_NAME}")
        print(f"[INFO] Resource Group: {AzureConfig.RESOURCE_GROUP}")

    def check_for_failures(self):
        """Poll ADF for any pipeline runs that failed since last check."""
        now = datetime.now(timezone.utc)
        print(f"\n[POLL] [{now.strftime('%H:%M:%S')}] Checking for failed pipeline runs...")

        try:
            # Query pipeline runs in the time window
            filter_params = {
                "lastUpdatedAfter": self.last_check_time,
                "lastUpdatedBefore": now,
                "filters": [
                    {
                        "operand": "Status",
                        "operator": "Equals",
                        "values": ["Failed"]
                    }
                ]
            }

            # Get failed runs
            runs = self.adf_client.pipeline_runs.query_by_factory(
                resource_group_name=AzureConfig.RESOURCE_GROUP,
                factory_name=AzureConfig.FACTORY_NAME,
                filter_parameters=filter_params
            )

            failed_runs = runs.value if runs.value else []

            if not failed_runs:
                print("   [OK] No failures detected.")
            else:
                print(f"   [ALERT] Found {len(failed_runs)} failed run(s)!")

                for run in failed_runs:
                    # Skip if already processed
                    if run.run_id in self.processed_runs:
                        continue

                    self.processed_runs.add(run.run_id)
                    print(f"\n   [FAILED] Pipeline '{run.pipeline_name}' (Run ID: {run.run_id})")

                    # Get detailed activity logs for this run
                    error_details = self._get_activity_errors(run)

                    # Send to intelligence layer for classification
                    process_error(error_details)

            # Update the check window
            self.last_check_time = now

        except Exception as e:
            print(f"   [ERROR] Error polling ADF: {str(e)}")

    def _get_activity_errors(self, pipeline_run):
        """Get activity-level error details for a failed pipeline run."""
        activities = self.adf_client.activity_runs.query_by_pipeline_run(
            resource_group_name=AzureConfig.RESOURCE_GROUP,
            factory_name=AzureConfig.FACTORY_NAME,
            run_id=pipeline_run.run_id,
            filter_parameters={
                "lastUpdatedAfter": pipeline_run.run_start or self.last_check_time,
                "lastUpdatedBefore": datetime.now(timezone.utc)
            }
        )

        # Find the failed activities
        failed_activities = []
        error_messages = []

        for activity in (activities.value or []):
            if activity.status == "Failed":
                error_msg = ""
                if activity.error:
                    error_msg = (
                        str(activity.error.get("message", ""))
                        if isinstance(activity.error, dict)
                        else str(activity.error)
                    )

                failed_activities.append({
                    "activity_name": activity.activity_name,
                    "activity_type": activity.activity_type,
                    "error_message": error_msg,
                    "error_code": (
                        activity.error.get("errorCode", "Unknown")
                        if isinstance(activity.error, dict)
                        else "Unknown"
                    ),
                    "duration": (
                        str(activity.duration_in_ms) + "ms"
                        if activity.duration_in_ms
                        else "N/A"
                    )
                })
                error_messages.append(error_msg)

        return {
            "pipeline_name": pipeline_run.pipeline_name,
            "run_id": pipeline_run.run_id,
            "run_start": str(pipeline_run.run_start),
            "run_end": str(pipeline_run.run_end),
            "status": pipeline_run.status,
            "message": pipeline_run.message or "",
            "failed_activities": failed_activities,
            "combined_error": " | ".join(error_messages),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }


def start_listener():
    """Start the listener service."""
    print("=" * 60)
    print("[START] ADF Self-Healing Listener - Starting...")
    print("=" * 60)

    listener = ADFListener()

    # Schedule the check every POLL_INTERVAL seconds
    schedule.every(POLL_INTERVAL).seconds.do(listener.check_for_failures)

    # Run once immediately
    listener.check_for_failures()

    # Keep running forever
    print(f"\n⏰ Polling every {POLL_INTERVAL} seconds. Press Ctrl+C to stop.\n")
    try:
        while True:
            schedule.run_pending()
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\n🛑 Listener stopped.")


if __name__ == "__main__":
    start_listener()
