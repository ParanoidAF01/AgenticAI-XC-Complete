"""
Report Storage — handles uploading PDFs to Azure Blob Storage and
recording metadata in Azure SQL.

Falls back to local file storage when Azure Storage is not configured.
"""
from typing import Optional, List
import os
import re
import json
import threading
from datetime import datetime, timedelta, timezone

# IST timezone (UTC+5:30)
IST = timezone(timedelta(hours=5, minutes=30))

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config.settings import StorageConfig, SqlConfig

# Local fallback directory
LOCAL_DOCS_DIR = os.path.join(os.path.dirname(__file__), "..", "docs")
LOCAL_REGISTRY = os.path.join(LOCAL_DOCS_DIR, "reports_registry.json")
os.makedirs(LOCAL_DOCS_DIR, exist_ok=True)

# Thread lock for registry writes
_registry_lock = threading.Lock()

# ── Azure Blob Storage ──────────────────────────────────────

def _get_blob_service_client():
    """Create a BlobServiceClient. Returns None if not configured."""
    try:
        if not StorageConfig.ACCOUNT_NAME or not StorageConfig.ACCOUNT_KEY:
            return None
        from azure.storage.blob import BlobServiceClient
        conn_str = (
            f"DefaultEndpointsProtocol=https;"
            f"AccountName={StorageConfig.ACCOUNT_NAME};"
            f"AccountKey={StorageConfig.ACCOUNT_KEY};"
            f"EndpointSuffix=core.windows.net"
        )
        return BlobServiceClient.from_connection_string(conn_str)
    except Exception as e:
        print(f"   [WARN] Azure Blob Storage not available: {e}")
        return None


def upload_to_blob(pdf_bytes: bytes, blob_path: str) -> Optional[str]:
    """
    Upload PDF bytes to Azure Blob Storage.

    Args:
        pdf_bytes: The raw PDF file content.
        blob_path: Path within the container (e.g. 'PL_Finance/PL_Finance_creds_20260503.pdf')

    Returns:
        The blob URL if successful, None if fallback to local.
    """
    client = _get_blob_service_client()
    if not client:
        return None

    try:
        container_client = client.get_container_client(StorageConfig.CONTAINER_NAME)
        # Ensure container exists
        try:
            container_client.get_container_properties()
        except Exception:
            container_client.create_container()

        blob_client = container_client.get_blob_client(blob_path)
        blob_client.upload_blob(pdf_bytes, overwrite=True, content_settings={
            "content_type": "application/pdf"
        })

        blob_url = blob_client.url
        print(f"   [BLOB] Uploaded to: {blob_url}")
        return blob_url
    except Exception as e:
        print(f"   [WARN] Blob upload failed: {e}")
        return None


def generate_download_url(blob_path: str, expiry_hours: int = 1) -> Optional[str]:
    """
    Generate a time-limited SAS URL for downloading a PDF.

    Args:
        blob_path: Path within the container.
        expiry_hours: How long the link is valid.

    Returns:
        SAS URL string, or None if not available.
    """
    try:
        if not StorageConfig.ACCOUNT_NAME or not StorageConfig.ACCOUNT_KEY:
            return None
        from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions
        sas_token = generate_blob_sas(
            account_name=StorageConfig.ACCOUNT_NAME,
            container_name=StorageConfig.CONTAINER_NAME,
            blob_name=blob_path,
            account_key=StorageConfig.ACCOUNT_KEY,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.now(IST) + timedelta(hours=expiry_hours),
        )
        blob_url = (
            f"https://{StorageConfig.ACCOUNT_NAME}.blob.core.windows.net/"
            f"{StorageConfig.CONTAINER_NAME}/{blob_path}?{sas_token}"
        )
        return blob_url
    except Exception as e:
        print(f"   [WARN] SAS URL generation failed: {e}")
        return None


# ── SQL Metadata ────────────────────────────────────────────

def _get_sql_connection():
    """Get a pyodbc connection. Returns None if not available."""
    try:
        if not all([SqlConfig.SERVER, SqlConfig.DATABASE, SqlConfig.USERNAME, SqlConfig.PASSWORD]):
            return None
        import pyodbc
        conn_str = (
            f"DRIVER={{ODBC Driver 18 for SQL Server}};"
            f"SERVER={SqlConfig.SERVER};"
            f"DATABASE={SqlConfig.DATABASE};"
            f"UID={SqlConfig.USERNAME};"
            f"PWD={SqlConfig.PASSWORD};"
            f"Encrypt=yes;TrustServerCertificate=no;Connection Timeout=10;"
        )
        return pyodbc.connect(conn_str)
    except Exception:
        return None


def save_report_metadata_sql(metadata: dict) -> bool:
    """Insert report metadata into ui.PipelineReports. Returns True on success."""
    conn = _get_sql_connection()
    if not conn:
        return False
    try:
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO ui.PipelineReports
               (PipelineName, RunId, ErrorType, Priority, FileName, BlobPath, FileSizeBytes, GeneratedAt)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            metadata["pipeline_name"],
            metadata["run_id"],
            metadata.get("error_type"),
            metadata.get("priority"),
            metadata["filename"],
            metadata["blob_path"],
            metadata.get("file_size_bytes", 0),
            metadata["generated_at"],
        )
        conn.commit()
        cursor.close()
        conn.close()
        print(f"   [SQL] Report metadata saved for {metadata['pipeline_name']}")
        return True
    except Exception as e:
        print(f"   [WARN] SQL metadata save failed: {e}")
        return False


def get_reports_by_pipeline_sql(pipeline_name: str) -> Optional[List[dict]]:
    """Fetch all reports for a pipeline from SQL. Returns None if SQL unavailable."""
    conn = _get_sql_connection()
    if not conn:
        return None
    try:
        cursor = conn.cursor()
        cursor.execute(
            """SELECT PipelineName, RunId, ErrorType, Priority, FileName, BlobPath,
                      FileSizeBytes, GeneratedAt
               FROM ui.PipelineReports
               WHERE PipelineName = ?
               ORDER BY GeneratedAt DESC""",
            pipeline_name,
        )
        columns = [col[0] for col in cursor.description]
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
        cursor.close()
        conn.close()
        return rows
    except Exception as e:
        print(f"   [WARN] SQL report fetch failed: {e}")
        return None


# ── Local Fallback (JSON registry) ──────────────────────────

def _load_registry() -> List[dict]:
    """Load the local JSON reports registry."""
    if not os.path.exists(LOCAL_REGISTRY):
        return []
    try:
        with open(LOCAL_REGISTRY, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def _save_registry(entries: list[dict]):
    """Save the local JSON reports registry."""
    with open(LOCAL_REGISTRY, "w") as f:
        json.dump(entries, f, indent=2, default=str)


def save_report_metadata_local(metadata: dict):
    """Save report metadata to local JSON file."""
    with _registry_lock:
        entries = _load_registry()
        entries.append(metadata)
        _save_registry(entries)
    print(f"   [LOCAL] Report metadata saved to {LOCAL_REGISTRY}")


def get_reports_by_pipeline_local(pipeline_name: str) -> List[dict]:
    """Get all reports for a pipeline from local JSON registry."""
    entries = _load_registry()
    return [e for e in entries if e.get("pipeline_name") == pipeline_name]


# ── Public API ──────────────────────────────────────────────

def _make_error_slug(error_type: str) -> str:
    """Convert error type name to a filename-safe slug."""
    # "Type 3 - Credentials Expired" → "credentials_expired"
    # Remove the "Type N - " prefix
    slug = re.sub(r'^Type\s*\d+\s*[-–—]\s*', '', error_type, flags=re.IGNORECASE)
    slug = slug.lower().strip()
    slug = re.sub(r'[^a-z0-9]+', '_', slug)
    slug = slug.strip('_')
    return slug or "unknown"


def store_report(pipeline_name: str, run_id: str, error_type: str,
                 priority: str, pdf_bytes: bytes) -> dict:
    """
    Store a generated PDF report: upload to Blob Storage + save metadata.
    Falls back to local file + JSON registry if Azure is unavailable.

    Args:
        pipeline_name: Name of the pipeline.
        run_id: Pipeline run ID.
        error_type: Error type name (e.g. "Type 3 - Credentials Expired").
        priority: Priority level (e.g. "P1").
        pdf_bytes: Raw PDF content as bytes.

    Returns:
        Metadata dict with filename, path, size, timestamp.
    """
    now = datetime.now(IST)
    timestamp_str = now.strftime("%Y%m%d_%H%M%S")
    error_slug = _make_error_slug(error_type)

    filename = f"{pipeline_name}_{error_slug}_{timestamp_str}.pdf"
    blob_path = f"{pipeline_name}/{filename}"

    metadata = {
        "pipeline_name": pipeline_name,
        "run_id": run_id,
        "error_type": error_type,
        "priority": priority,
        "filename": filename,
        "blob_path": blob_path,
        "file_size_bytes": len(pdf_bytes),
        "generated_at": now.isoformat(),
    }

    # Try Azure Blob Storage first
    blob_url = upload_to_blob(pdf_bytes, blob_path)

    if blob_url:
        metadata["blob_url"] = blob_url
        # Save metadata to SQL
        if not save_report_metadata_sql(metadata):
            # SQL failed — fallback to local registry too
            save_report_metadata_local(metadata)
    else:
        # Fallback: save PDF locally
        pipeline_dir = os.path.join(LOCAL_DOCS_DIR, pipeline_name)
        os.makedirs(pipeline_dir, exist_ok=True)
        local_path = os.path.join(pipeline_dir, filename)
        with open(local_path, "wb") as f:
            f.write(pdf_bytes)
        metadata["local_path"] = local_path
        print(f"   [LOCAL] PDF saved: {local_path}")
        # Save metadata locally
        save_report_metadata_local(metadata)

    return metadata


def get_reports(pipeline_name: str) -> List[dict]:
    """
    Get all report metadata for a pipeline.
    Tries SQL first, falls back to local JSON registry.
    """
    # Try SQL
    sql_reports = get_reports_by_pipeline_sql(pipeline_name)
    if sql_reports is not None:
        results = []
        for r in sql_reports:
            blob_path = r.get("BlobPath", "")
            download_url = generate_download_url(blob_path) if blob_path else None
            results.append({
                "pipeline_name": r.get("PipelineName", ""),
                "run_id": r.get("RunId", ""),
                "error_type": r.get("ErrorType", ""),
                "priority": r.get("Priority", ""),
                "filename": r.get("FileName", ""),
                "file_size_kb": round((r.get("FileSizeBytes", 0) or 0) / 1024, 1),
                "generated_at": str(r.get("GeneratedAt", "")),
                "download_url": download_url,
            })
        return results

    # Fallback: local registry
    local_reports = get_reports_by_pipeline_local(pipeline_name)
    results = []
    for r in local_reports:
        local_path = r.get("local_path", "")
        results.append({
            "pipeline_name": r.get("pipeline_name", ""),
            "run_id": r.get("run_id", ""),
            "error_type": r.get("error_type", ""),
            "priority": r.get("priority", ""),
            "filename": r.get("filename", ""),
            "file_size_kb": round((r.get("file_size_bytes", 0) or 0) / 1024, 1),
            "generated_at": r.get("generated_at", ""),
            "download_url": f"/api/reports/download/{r.get('pipeline_name', '')}/{r.get('filename', '')}",
        })
    return results
