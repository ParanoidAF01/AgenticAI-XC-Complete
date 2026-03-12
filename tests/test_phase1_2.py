"""
Test script for Phase 1 & 2.
Tests the intelligence layer WITHOUT needing a real ADF failure.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config.metadata_store import add_pipeline, get_pipeline, init_db
from intelligence.pinecone_store import store_error, search_similar_errors
from intelligence.error_classifier import classify_error
from intelligence.error_processor import process_error


def test_metadata_store():
    """Test 1: SQLite metadata store."""
    print("\n" + "=" * 40)
    print("TEST 1: Metadata Store")
    print("=" * 40)

    add_pipeline(
        name="pl_copy_sales_data",
        description="Copies daily sales data from Blob to SQL",
        owner_name="Anmol Gupta",
        owner_email="anmol@example.com",
        schedule="daily 6:00 AM",
        criticality="high"
    )

    result = get_pipeline("pl_copy_sales_data")
    print(f"   Pipeline: {result['pipeline_name']}")
    print(f"   Owner: {result['owner_name']}")
    print(f"   Criticality: {result['criticality']}")
    print("   ✅ PASSED")


def test_pinecone():
    """Test 2: Pinecone embedding + search."""
    print("\n" + "=" * 40)
    print("TEST 2: Pinecone Store")
    print("=" * 40)

    # Store a sample error
    store_error(
        error_id="test-run-001",
        error_text="Connection timeout after 30 seconds while connecting to SQL Server",
        metadata={
            "pipeline_name": "pl_copy_sales_data",
            "error_type": 1,
            "error_type_name": "Transient/Timeout Error",
            "error_message": "Connection timeout after 30 seconds",
            "timestamp": "2026-03-05T10:00:00Z"
        },
        namespace="test-pipeline"
    )

    # Search for similar
    results = search_similar_errors("SQL Server connection timed out", namespace="test-pipeline")
    print(f"   Found {len(results)} similar errors")
    if results:
        print(f"   Top match score: {results[0]['score']:.4f}")
    print("   ✅ PASSED")


def test_classifier():
    """Test 3: Gemini error classification."""
    print("\n" + "=" * 40)
    print("TEST 3: Error Classification")
    print("=" * 40)

    fake_error = {
        "pipeline_name": "pl_copy_sales_data",
        "combined_error": "The connection to server 'sqlserver.database.windows.net' was timeout after 30000ms",
        "failed_activities": [
            {
                "activity_name": "Copy Sales",
                "activity_type": "Copy",
                "error_message": "Connection timeout"
            }
        ]
    }

    result = classify_error(fake_error, [], {"owner_name": "Anmol", "criticality": "high"})
    print(f"   Type: {result['error_type']} ({result['error_type_name']})")
    print(f"   Auto-recoverable: {result['is_auto_recoverable']}")
    print(f"   Priority: {result['priority']}")
    print("   ✅ PASSED")


def test_full_pipeline():
    """Test 4: Full error processing pipeline (minus n8n)."""
    print("\n" + "=" * 40)
    print("TEST 4: Full Processing Pipeline")
    print("=" * 40)

    fake_error = {
        "pipeline_name": "pl_copy_sales_data",
        "run_id": "test-full-001",
        "run_start": "2026-03-05T10:00:00Z",
        "run_end": "2026-03-05T10:01:30Z",
        "status": "Failed",
        "message": "Activity Copy Sales failed",
        "combined_error": (
            "ErrorCode=UserErrorInvalidColumnMappingColumnNotFound. "
            "Column 'SalesAmount' not found in source."
        ),
        "failed_activities": [
            {
                "activity_name": "Copy Sales",
                "activity_type": "Copy",
                "error_message": "Column 'SalesAmount' not found in source",
                "error_code": "UserErrorInvalidColumnMappingColumnNotFound"
            }
        ],
        "timestamp": "2026-03-05T10:01:30Z"
    }

    process_error(fake_error)
    print("   ✅ PASSED")


if __name__ == "__main__":
    print("🧪 Running Phase 1 & 2 Tests...\n")
    test_metadata_store()
    test_pinecone()
    test_classifier()
    test_full_pipeline()
    print("\n\n🎉 All tests passed! Phase 1 & 2 are working.")
