"""
Pinecone Vector Store.
Handles storing error log embeddings and searching for similar past errors.
Uses company's OpenAI-compatible embedding API (text-embedding-3-large).
"""
from pinecone import Pinecone, ServerlessSpec
from openai import OpenAI
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config.settings import PineconeConfig, CompanyAPIConfig

# Initialize the OpenAI-compatible embedding client
print("📦 Initializing embedding model via Company API...")
embedding_client = OpenAI(
    base_url=CompanyAPIConfig.BASE_URL,
    api_key=CompanyAPIConfig.API_KEY
)
EMBEDDING_MODEL = CompanyAPIConfig.EMBEDDING_MODEL
EMBEDDING_DIMS = 3072  # text-embedding-3-large outputs 3072 dimensions
print(f"✅ Embedding model ready: {EMBEDDING_MODEL}")

# Initialize Pinecone client
pc = Pinecone(api_key=PineconeConfig.API_KEY)

# Create index if it doesn't exist (or recreate if dimensions mismatch)
INDEX_NAME = PineconeConfig.INDEX_NAME
existing_indexes = pc.list_indexes().names()

if INDEX_NAME in existing_indexes:
    # Check if dimensions match
    desc = pc.describe_index(INDEX_NAME)
    if desc.dimension != EMBEDDING_DIMS:
        print(f"⚠️  Index exists with {desc.dimension} dims, need {EMBEDDING_DIMS}. Deleting and recreating...")
        pc.delete_index(INDEX_NAME)
        import time
        time.sleep(5)  # Wait for deletion to propagate
        existing_indexes = []

if INDEX_NAME not in pc.list_indexes().names():
    print(f"📌 Creating Pinecone index: {INDEX_NAME} ({EMBEDDING_DIMS} dimensions)...")
    pc.create_index(
        name=INDEX_NAME,
        dimension=EMBEDDING_DIMS,
        metric="cosine",
        spec=ServerlessSpec(cloud="aws", region="us-east-1")
    )
    # Wait for index to be ready
    import time
    time.sleep(10)
    print("✅ Index created.")

# Connect to the index
index = pc.Index(INDEX_NAME)


def embed_text(text: str) -> list:
    """Convert text to a vector using the company's embedding API."""
    response = embedding_client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=text
    )
    return response.data[0].embedding


def store_error(error_id: str, error_text: str, metadata: dict, namespace: str = "default"):
    """
    Store an error log embedding in Pinecone.

    Args:
        error_id: Unique ID (e.g., run_id)
        error_text: The error message text to embed
        metadata: Dict with keys like pipeline_name, error_type, timestamp, etc.
        namespace: Pinecone namespace (use pipeline name)
    """
    vector = embed_text(error_text)
    index.upsert(
        vectors=[{"id": error_id, "values": vector, "metadata": metadata}],
        namespace=namespace
    )
    print(f"   📌 Stored error embedding in Pinecone (namespace: {namespace})")


def search_similar_errors(error_text: str, namespace: str = "default", top_k: int = 5):
    """
    Search for similar past errors.

    Args:
        error_text: The current error message
        namespace: Pipeline namespace to search in
        top_k: Number of similar results to return

    Returns:
        List of similar errors with their metadata and similarity scores.
    """
    vector = embed_text(error_text)
    results = index.query(
        vector=vector,
        namespace=namespace,
        top_k=top_k,
        include_metadata=True
    )
    return [
        {
            "score": match.score,
            "metadata": match.metadata
        }
        for match in results.matches
    ]
