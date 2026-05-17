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


from typing import Optional


def compute_consensus(similar_errors: list,
                      score_threshold: float = 0.90,
                      min_agree: int = 3) -> Optional[dict]:
    """
    Layer 2: Consensus-based classification from ChromaDB results.

    Given top-N similar errors from search_similar_errors():
    - Best match score must be >= score_threshold
    - At least min_agree results must agree on the same error_type
    - Returns the majority type with averaged confidence

    Args:
        similar_errors: Output from search_similar_errors()
        score_threshold: Minimum similarity score for best match
        min_agree: Minimum number of results that must agree

    Returns:
        Classification dict if consensus reached, None otherwise.
    """
    if not similar_errors or len(similar_errors) < min_agree:
        return None

    # Check if best match meets score threshold
    best_score = similar_errors[0]["score"]
    if best_score < score_threshold:
        return None

    # Count error_type votes from high-scoring matches
    from collections import Counter
    type_votes = Counter()
    type_details = {}

    for err in similar_errors:
        if err["score"] < score_threshold * 0.85:  # Allow some slack for lower-ranked matches
            continue
        meta = err.get("metadata", {})
        error_type_raw = meta.get("error_type", "")
        # error_type stored as "3 - Credentials Expired" or just "3"
        try:
            if isinstance(error_type_raw, str) and " - " in error_type_raw:
                error_type_int = int(error_type_raw.split(" - ")[0])
            else:
                error_type_int = int(error_type_raw)
        except (ValueError, TypeError):
            continue

        type_votes[error_type_int] += 1
        if error_type_int not in type_details:
            type_details[error_type_int] = {
                "scores": [],
                "type_name": meta.get("error_type_name", ""),
                "root_cause": meta.get("root_cause", ""),
            }
        type_details[error_type_int]["scores"].append(err["score"])

    if not type_votes:
        return None

    # Check if majority type has enough votes
    majority_type, majority_count = type_votes.most_common(1)[0]
    if majority_count < min_agree:
        return None

    # Build result
    details = type_details[majority_type]
    avg_score = sum(details["scores"]) / len(details["scores"])

    type_names = {
        1: "Parameter Errors", 2: "Dataset Type Errors",
        3: "Credentials Expired", 4: "Large Data / Timeout",
        5: "Server Slow", 6: "Subscription Corrupt",
    }

    return {
        "error_type": majority_type,
        "error_type_name": type_names.get(majority_type, details["type_name"]),
        "confidence": round(avg_score, 4),
        "root_cause_summary": details["root_cause"] or f"Consensus from {majority_count} similar errors",
        "is_auto_recoverable": majority_type in (3, 4, 5),
        "recommended_action": f"Based on {majority_count}/{len(similar_errors)} similar past errors.",
        "priority": {1: "P2", 2: "P2", 3: "P3", 4: "P3", 5: "P4", 6: "P1"}.get(majority_type, "P2"),
        "classified_by": "L2_chromadb_consensus",
        "consensus_count": majority_count,
        "consensus_avg_score": round(avg_score, 4),
    }
