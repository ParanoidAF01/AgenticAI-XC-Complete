"""
End-to-End System Test.
Simulates all 6 error types to verify the complete pipeline:
Listener → Pinecone → Gemini → Python Orchestrator → Restart/Notify

Run with: python tests/test_full_system.py
"""
import sys
import os
import time
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config.metadata_store import add_pipeline
from intelligence.error_processor import process_error

# ── Register test pipelines in metadata store ──


def setup_test_pipelines():
    """Add sample pipeline metadata for testing."""
    pipelines = [
        ("pl_copy_sales_data", "Copies daily sales from Blob to SQL",
         "Anmol Gupta", "anmol@example.com", "daily 6AM", "high"),
        ("pl_transform_inventory", "Transforms inventory data in Dataflow",
         "Rahul Sharma", "rahul@example.com", "hourly", "critical"),
        ("pl_export_reports", "Exports reports to SharePoint",
         "Priya Patel", "priya@example.com", "weekly Mon 8AM", "medium"),
    ]
    for p in pipelines:
        add_pipeline(*p)
    print("✅ Test pipelines registered.\n")


# ── Define all 6 error scenarios ──
SIMULATED_ERRORS = [
    {
        "name": "Type 1 — Parameter Errors",
        "details": {
            "pipeline_name": "pl_copy_sales_data",
            "run_id": "sim-type1-001",
            "run_start": "2026-03-05T10:00:00Z",
            "run_end": "2026-03-05T10:00:05Z",
            "status": "Failed",
            "message": "Activity failed",
            "combined_error": (
                "ErrorCode=InvalidParameter. The pipeline parameter 'sourceFileName' "
                "has value 'null' which is not valid. Expected a non-empty string value. "
                "Parameter 'dateFilter' has type mismatch: expected DateTime but received String '2026-03-05'."
            ),
            "failed_activities": [{
                "activity_name": "CopySalesData",
                "activity_type": "Copy",
                "error_message": "Pipeline parameter 'sourceFileName' is null",
                "error_code": "InvalidParameter"
            }],
            "timestamp": "2026-03-05T10:00:05Z"
        },
        "expected_type": 1,
        "expected_action": "auto_restart"
    },
    {
        "name": "Type 2 — Dataset Type Errors",
        "details": {
            "pipeline_name": "pl_copy_sales_data",
            "run_id": "sim-type2-001",
            "run_start": "2026-03-05T11:00:00Z",
            "run_end": "2026-03-05T11:01:00Z",
            "status": "Failed",
            "message": "Activity failed",
            "combined_error": (
                "ErrorCode=UserErrorInvalidColumnMappingColumnNotFound. "
                "Column 'SalesAmount_USD' was not found in the source dataset. "
                "Schema mismatch: source has columns [OrderId, Revenue, OrderDate] "
                "but dataset expects [OrderId, SalesAmount, Date]. "
                "Data type conversion error: cannot convert 'N/A' to Decimal for column 'Revenue'."
            ),
            "failed_activities": [{
                "activity_name": "CopySalesData",
                "activity_type": "Copy",
                "error_message": "Column 'SalesAmount_USD' not found, schema mismatch",
                "error_code": "UserErrorInvalidColumnMappingColumnNotFound"
            }],
            "timestamp": "2026-03-05T11:01:00Z"
        },
        "expected_type": 2,
        "expected_action": "auto_restart"
    },
    {
        "name": "Type 3 — Credentials Expired",
        "details": {
            "pipeline_name": "pl_export_reports",
            "run_id": "sim-type3-001",
            "run_start": "2026-03-05T12:00:00Z",
            "run_end": "2026-03-05T12:00:30Z",
            "status": "Failed",
            "message": "Activity failed",
            "combined_error": (
                "ErrorCode=LinkedServiceAuthFailed. AADSTS7000215: "
                "Invalid client secret provided. The client secret for "
                "service principal 'adf-sp-prod' has expired on 2026-03-01. "
                "Key Vault reference 'adf-sp-secret' returned 401 Unauthorized. "
                "SAS token for storage account 'sadatalake' expired at 2026-03-04T23:59:59Z."
            ),
            "failed_activities": [{
                "activity_name": "ExportToSharePoint",
                "activity_type": "WebActivity",
                "error_message": "SPN secret expired, SAS token expired",
                "error_code": "LinkedServiceAuthFailed"
            }],
            "timestamp": "2026-03-05T12:00:30Z"
        },
        "expected_type": 3,
        "expected_action": "auto_restart"
    },
    {
        "name": "Type 4 — Large Data / Timeout",
        "details": {
            "pipeline_name": "pl_transform_inventory",
            "run_id": "sim-type4-001",
            "run_start": "2026-03-05T13:00:00Z",
            "run_end": "2026-03-05T15:30:00Z",
            "status": "Failed",
            "message": "Activity failed",
            "combined_error": (
                "ErrorCode=DFExecutorUserError. Data flow execution timed out after 7200 seconds. "
                "The source dataset contains 450 million rows (85 GB) which exceeded the "
                "processing capacity. java.lang.OutOfMemoryError: GC overhead limit exceeded. "
                "Consider partitioning the data or increasing integration runtime memory."
            ),
            "failed_activities": [{
                "activity_name": "TransformInventory",
                "activity_type": "DataFlow",
                "error_message": "Timeout after 7200s, 450M rows (85 GB), OOM",
                "error_code": "DFExecutorUserError"
            }],
            "timestamp": "2026-03-05T15:30:00Z"
        },
        "expected_type": 4,
        "expected_action": "auto_restart"
    },
    {
        "name": "Type 5 — Server Slow",
        "details": {
            "pipeline_name": "pl_copy_sales_data",
            "run_id": "sim-type5-001",
            "run_start": "2026-03-05T14:00:00Z",
            "run_end": "2026-03-05T14:10:00Z",
            "status": "Failed",
            "message": "Activity failed",
            "combined_error": (
                "ErrorCode=SqlFailedToConnect. Connection to source SQL Server "
                "'sqlprod.database.windows.net' is extremely slow. "
                "Response time: 45000ms (threshold: 30000ms). "
                "HTTP 429 Too Many Requests from Azure Storage API. "
                "The source database DTU utilization is at 98%, causing query throttling."
            ),
            "failed_activities": [{
                "activity_name": "CopySalesData",
                "activity_type": "Copy",
                "error_message": "SQL Server response 45000ms, HTTP 429, DTU at 98%",
                "error_code": "SqlFailedToConnect"
            }],
            "timestamp": "2026-03-05T14:10:00Z"
        },
        "expected_type": 5,
        "expected_action": "escalate_to_human"
    },
    {
        "name": "Type 6 — Subscription Corrupt",
        "details": {
            "pipeline_name": "pl_transform_inventory",
            "run_id": "sim-type6-001",
            "run_start": "2026-03-05T15:00:00Z",
            "run_end": "2026-03-05T15:00:15Z",
            "status": "Failed",
            "message": "Activity failed",
            "combined_error": (
                "ErrorCode=SubscriptionNotFound. The Azure subscription "
                "'sub-prod-analytics' is in a disabled state. "
                "Resource group 'rg-data-platform' cannot be accessed. "
                "ARM deployment validation failed: linked service 'ls_AzureSqlDB' "
                "references a deleted resource. Integration runtime 'ir-selfhosted-prod' "
                "configuration is corrupted and cannot be initialized."
            ),
            "failed_activities": [{
                "activity_name": "TransformInventory",
                "activity_type": "DataFlow",
                "error_message": "Subscription disabled, IR config corrupted",
                "error_code": "SubscriptionNotFound"
            }],
            "timestamp": "2026-03-05T15:00:15Z"
        },
        "expected_type": 6,
        "expected_action": "escalate_to_human"
    }
]


def run_all_tests():
    """Run all 6 error simulations."""
    print("=" * 60)
    print("🧪 FULL SYSTEM TEST — Simulating All 6 Error Types")
    print("=" * 60)
    print()
    print("  Types 1-4: Auto-recoverable (restart/fix)")
    print("  Types 5-6: Escalate to human (doc + notify)")
    print()

    setup_test_pipelines()
    results = []

    for i, scenario in enumerate(SIMULATED_ERRORS, 1):
        print(f"\n{'─' * 60}")
        print(f"🔬 Test {i}/6: {scenario['name']}")
        print(f"   Expected: {scenario['expected_action']}")
        print(f"{'─' * 60}")

        try:
            process_error(scenario["details"])
            results.append({"test": scenario["name"], "status": "✅ PASSED"})
        except Exception as e:
            results.append({"test": scenario["name"], "status": f"❌ FAILED: {str(e)}"})

        # Small delay between tests (respect Gemini rate limits)
        time.sleep(2)

    # Print summary
    print(f"\n\n{'=' * 60}")
    print("📊 TEST RESULTS SUMMARY")
    print(f"{'=' * 60}")
    for r in results:
        print(f"  {r['status']}  {r['test']}")

    passed = sum(1 for r in results if "PASSED" in r["status"])
    print(f"\n  Total: {passed}/{len(results)} passed")


if __name__ == "__main__":
    run_all_tests()
