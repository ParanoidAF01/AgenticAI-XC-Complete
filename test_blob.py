"""
Azure Blob Storage — Connection Test & PDF Upload
Usage:
    python test_blob.py                          # Test connection only
    python test_blob.py /path/to/report.pdf      # Test + upload a PDF
"""
import os
import sys
from dotenv import load_dotenv

load_dotenv()

ACCOUNT_NAME = os.getenv("AZURE_STORAGE_ACCOUNT_NAME", "")
ACCOUNT_KEY = os.getenv("AZURE_STORAGE_ACCOUNT_KEY", "")
CONTAINER = os.getenv("AZURE_STORAGE_CONTAINER", "adf-healer-reports")

print("=" * 60)
print("  Azure Blob Storage — Connection Test")
print("=" * 60)

# ── Step 1: Check env vars ──────────────────────────────
print("\n[1/4] Checking environment variables...")
if not ACCOUNT_NAME:
    print("  ❌ AZURE_STORAGE_ACCOUNT_NAME is empty or missing in .env")
    sys.exit(1)
if not ACCOUNT_KEY:
    print("  ❌ AZURE_STORAGE_ACCOUNT_KEY is empty or missing in .env")
    sys.exit(1)
print(f"  ✅ Account: {ACCOUNT_NAME}")
print(f"  ✅ Container: {CONTAINER}")
print(f"  ✅ Key: {ACCOUNT_KEY[:8]}...{ACCOUNT_KEY[-4:]}")

# ── Step 2: Import SDK ──────────────────────────────────
print("\n[2/4] Importing azure-storage-blob SDK...")
try:
    from azure.storage.blob import BlobServiceClient
    print("  ✅ SDK imported successfully")
except ImportError:
    print("  ❌ azure-storage-blob not installed. Run:")
    print("     pip install azure-storage-blob")
    sys.exit(1)

# ── Step 3: Connect & check container ───────────────────
print("\n[3/4] Connecting to Azure Blob Storage...")
try:
    conn_str = (
        f"DefaultEndpointsProtocol=https;"
        f"AccountName={ACCOUNT_NAME};"
        f"AccountKey={ACCOUNT_KEY};"
        f"EndpointSuffix=core.windows.net"
    )
    blob_service = BlobServiceClient.from_connection_string(conn_str)

    # Test connection by listing containers
    containers = [c.name for c in blob_service.list_containers()]
    print(f"  ✅ Connected! Found {len(containers)} container(s): {containers}")

    # Check if target container exists
    if CONTAINER in containers:
        print(f"  ✅ Container '{CONTAINER}' exists")
    else:
        print(f"  ⚠️  Container '{CONTAINER}' not found. Creating it...")
        blob_service.create_container(CONTAINER)
        print(f"  ✅ Container '{CONTAINER}' created")

    container_client = blob_service.get_container_client(CONTAINER)

    # List existing blobs
    blobs = list(container_client.list_blobs())
    print(f"  📁 Existing blobs in '{CONTAINER}': {len(blobs)}")
    for b in blobs[:10]:
        print(f"      • {b.name} ({b.size} bytes)")
    if len(blobs) > 10:
        print(f"      ... and {len(blobs) - 10} more")

except Exception as e:
    print(f"  ❌ Connection failed: {str(e)}")
    print(f"\n  Troubleshooting:")
    print(f"  1. Verify account name: {ACCOUNT_NAME}")
    print(f"  2. Verify key is correct (not expired)")
    print(f"  3. Check network/firewall (is your IP whitelisted?)")
    print(f"  4. Check Azure Portal → Storage Account → Access Keys")
    sys.exit(1)

# ── Step 4: Upload PDF (if path provided) ───────────────
if len(sys.argv) > 1:
    pdf_path = sys.argv[1]
    print(f"\n[4/4] Uploading PDF: {pdf_path}")

    if not os.path.exists(pdf_path):
        print(f"  ❌ File not found: {pdf_path}")
        sys.exit(1)

    filename = os.path.basename(pdf_path)
    blob_name = f"test-uploads/{filename}"

    try:
        blob_client = container_client.get_blob_client(blob_name)

        with open(pdf_path, "rb") as f:
            blob_client.upload_blob(f, overwrite=True, content_settings={
                "content_type": "application/pdf"
            })

        # Verify upload
        props = blob_client.get_blob_properties()
        print(f"  ✅ Upload successful!")
        print(f"     Blob name: {blob_name}")
        print(f"     Size: {props.size} bytes")
        print(f"     URL: https://{ACCOUNT_NAME}.blob.core.windows.net/{CONTAINER}/{blob_name}")

    except Exception as e:
        print(f"  ❌ Upload failed: {str(e)}")
        sys.exit(1)
else:
    print("\n[4/4] Skipped — no PDF path provided")
    print("  To upload a PDF, run: python test_blob.py /path/to/file.pdf")

print("\n" + "=" * 60)
print("  Done!")
print("=" * 60)
