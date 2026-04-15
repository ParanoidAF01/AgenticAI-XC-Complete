"""
ChromaDB Vector Store.
Handles storing error log embeddings and searching for similar past errors.
Uses company's OpenAI-compatible embedding API (text-embedding-3-large).

ChromaDB uses collections (one per pipeline) as the equivalent of
Pinecone namespaces. Each pipeline's errors are stored in its own collection.
"""
import chromadb
from openai import OpenAI
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config.settings import ChromaConfig, CompanyAPIConfig

# Initialize the OpenAI-compatible embedding client
print("[INIT] Initializing embedding model via Company API...")
embedding_client = OpenAI(
    base_url=CompanyAPIConfig.BASE_URL,
    api_key=CompanyAPIConfig.API_KEY
)
EMBEDDING_MODEL = CompanyAPIConfig.EMBEDDING_MODEL
EMBEDDING_DIMS = 3072  # text-embedding-3-large outputs 3072 dimensions
print(f"[OK] Embedding model ready: {EMBEDDING_MODEL}")

# Initialize ChromaDB persistent client
PERSIST_DIR = ChromaConfig.PERSIST_DIR
os.makedirs(PERSIST_DIR, exist_ok=True)

print(f"[INIT] Connecting to ChromaDB (persist: {PERSIST_DIR})...")
chroma_client = chromadb.PersistentClient(path=PERSIST_DIR)
print("[OK] ChromaDB ready.")


def _get_collection(namespace: str):
    """
    Get or create a ChromaDB collection for a pipeline namespace.
    Each pipeline gets its own collection (equivalent of Pinecone namespace).

    Collection uses cosine distance (matches Pinecone's cosine metric).
    """
    # ChromaDB collection names must be 3-63 chars, alphanumeric + underscores/hyphens
    safe_name = namespace.replace(" ", "_")[:63]
    if len(safe_name) < 3:
        safe_name = safe_name + "_ns"
    return chroma_client.get_or_create_collection(
        name=safe_name,
        metadata={"hnsw:space": "cosine"}
    )


def embed_text(text: str) -> list:
    """Convert text to a vector using the company's embedding API."""
    response = embedding_client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=text
    )
    return response.data[0].embedding


def store_error(error_id: str, error_text: str, metadata: dict, namespace: str = "default"):
    """
    Store an error log embedding in ChromaDB.

    Args:
        error_id: Unique ID (e.g., run_id)
        error_text: The error message text to embed
        metadata: Dict with keys like pipeline_name, error_type, timestamp, etc.
        namespace: Collection name (use pipeline name)
    """
    vector = embed_text(error_text)
    collection = _get_collection(namespace)

    # ChromaDB metadata values must be str, int, float, or bool — not None
    clean_metadata = {}
    for k, v in metadata.items():
        if v is None:
            clean_metadata[k] = ""
        elif isinstance(v, (str, int, float, bool)):
            clean_metadata[k] = v
        else:
            clean_metadata[k] = str(v)

    collection.upsert(
        ids=[error_id],
        embeddings=[vector],
        metadatas=[clean_metadata],
        documents=[error_text[:5000]]  # Store original text for reference
    )
    print(f"   [STORE] Stored error embedding in ChromaDB (collection: {namespace})")


def search_similar_errors(error_text: str, namespace: str = "default", top_k: int = 5):
    """
    Search for similar past errors.

    Args:
        error_text: The current error message
        namespace: Pipeline collection to search in
        top_k: Number of similar results to return

    Returns:
        List of similar errors with their metadata and similarity scores.
        Scores are normalized to 0.0-1.0 (higher = more similar),
        matching the same format that Pinecone returned.
    """
    collection = _get_collection(namespace)

    # Check if collection has any vectors
    if collection.count() == 0:
        return []

    vector = embed_text(error_text)

    results = collection.query(
        query_embeddings=[vector],
        n_results=min(top_k, collection.count()),
        include=["metadatas", "distances", "documents"]
    )

    # Convert ChromaDB distances to similarity scores
    # ChromaDB cosine distance: 0.0 (identical) to 2.0 (opposite)
    # Pinecone cosine similarity: 1.0 (identical) to 0.0 (orthogonal)
    # Conversion: score = 1 - (distance / 2)
    similar_errors = []
    if results and results["ids"] and results["ids"][0]:
        for i, doc_id in enumerate(results["ids"][0]):
            distance = results["distances"][0][i]
            score = 1.0 - (distance / 2.0)  # Normalize to 0.0-1.0
            metadata = results["metadatas"][0][i] if results["metadatas"] else {}

            similar_errors.append({
                "score": round(score, 4),
                "metadata": metadata
            })

    return similar_errors


def get_all_collections():
    """List all collections (pipeline namespaces) in ChromaDB."""
    return [c.name for c in chroma_client.list_collections()]


def get_collection_count(namespace: str) -> int:
    """Get the number of vectors in a collection."""
    collection = _get_collection(namespace)
    return collection.count()
