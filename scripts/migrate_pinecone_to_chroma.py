"""
Vector DB Migration Script — Pinecone to ChromaDB.

Uses Method 4 (ID Enumeration):
  1. index.list(namespace) → paginated list of ALL vector IDs
  2. index.fetch(ids=batch) → get vectors + metadata in batches
  3. ChromaDB collection.add() → insert into local ChromaDB

One ChromaDB collection per Pinecone namespace (pipeline).

Usage:
    python scripts/migrate_pinecone_to_chroma.py
"""
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

from pinecone import Pinecone
from openai import OpenAI
import chromadb

# ── Config ──────────────────────────────────────────────────────
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "adf-error-logs")
CHROMA_PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR",
    os.path.join(os.path.dirname(__file__), "..", "chroma_db"))

BATCH_SIZE = 100  # Fetch this many vectors at a time


def migrate():
    print("=" * 60)
    print("Pinecone → ChromaDB Migration")
    print("=" * 60)

    # ── Step 1: Connect to Pinecone ─────────────────────────────
    print("\n[1/4] Connecting to Pinecone...")
    if not PINECONE_API_KEY:
        print("[ERROR] PINECONE_API_KEY not set in .env")
        sys.exit(1)

    pc = Pinecone(api_key=PINECONE_API_KEY)
    index = pc.Index(PINECONE_INDEX_NAME)
    print(f"  Connected to index: {PINECONE_INDEX_NAME}")

    # ── Step 2: Get namespace stats ─────────────────────────────
    print("\n[2/4] Fetching index stats...")
    stats = index.describe_index_stats()
    namespaces = stats.namespaces

    if not namespaces:
        print("  [WARN] No namespaces found in index. Nothing to migrate.")
        return

    total_vectors = stats.total_vector_count
    print(f"  Total vectors: {total_vectors}")
    print(f"  Namespaces: {len(namespaces)}")
    for ns, ns_stats in namespaces.items():
        print(f"    - '{ns}': {ns_stats.vector_count} vectors")

    # ── Step 3: Connect to ChromaDB ─────────────────────────────
    print("\n[3/4] Initializing ChromaDB...")
    os.makedirs(CHROMA_PERSIST_DIR, exist_ok=True)
    chroma_client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
    print(f"  ChromaDB persist directory: {CHROMA_PERSIST_DIR}")

    # ── Step 4: Migrate each namespace ──────────────────────────
    print("\n[4/4] Migrating namespaces...\n")

    total_migrated = 0
    migration_summary = []

    for ns_name, ns_stats in namespaces.items():
        expected_count = ns_stats.vector_count
        print(f"  ── Namespace: '{ns_name}' ({expected_count} vectors) ──")

        # Create ChromaDB collection for this namespace
        safe_name = ns_name.replace(" ", "_")[:63]
        if len(safe_name) < 3:
            safe_name = safe_name + "_ns"
        collection = chroma_client.get_or_create_collection(
            name=safe_name,
            metadata={"hnsw:space": "cosine"}
        )

        # List all vector IDs in this namespace (paginated)
        all_ids = []
        print(f"    Listing vector IDs...")

        try:
            # Pinecone v5: index.list() returns paginated results
            list_response = index.list(namespace=ns_name)

            # Handle paginated results
            if hasattr(list_response, 'vectors'):
                # v5 format
                all_ids = [v.id for v in list_response.vectors]
            elif isinstance(list_response, dict) and 'vectors' in list_response:
                all_ids = [v['id'] for v in list_response['vectors']]
            else:
                # Try iteration (some SDK versions return an iterator)
                page_ids = []
                for id_list in list_response:
                    if isinstance(id_list, str):
                        page_ids.append(id_list)
                    elif isinstance(id_list, list):
                        page_ids.extend(id_list)
                    elif hasattr(id_list, 'id'):
                        page_ids.append(id_list.id)
                all_ids = page_ids

        except Exception as e:
            print(f"    [WARN] index.list() failed: {e}")
            print(f"    [FALLBACK] Using query-based extraction...")

            # Fallback: Use a zero vector to query all vectors
            # This works for small datasets
            from config.settings import CompanyAPIConfig
            embedding_client = OpenAI(
                base_url=CompanyAPIConfig.BASE_URL,
                api_key=CompanyAPIConfig.API_KEY
            )
            # Create a simple query to fetch vectors
            dummy_response = embedding_client.embeddings.create(
                model=os.getenv("COMPANY_EMBEDDING_MODEL", "text-embedding-3-large"),
                input="error"
            )
            dummy_vector = dummy_response.data[0].embedding

            query_result = index.query(
                vector=dummy_vector,
                namespace=ns_name,
                top_k=min(10000, expected_count),
                include_metadata=True
            )

            if query_result.matches:
                # We have vectors + metadata directly from query
                ids_batch = []
                embeddings_batch = []
                metadatas_batch = []
                documents_batch = []

                for match in query_result.matches:
                    meta = match.metadata or {}
                    ids_batch.append(match.id)
                    metadatas_batch.append(
                        {k: ("" if v is None else v) for k, v in meta.items()
                         if isinstance(v, (str, int, float, bool)) or v is None}
                    )
                    documents_batch.append(
                        meta.get("error_message", "")[:5000]
                    )

                # We need actual embeddings — re-embed the error messages
                print(f"    Re-embedding {len(ids_batch)} vectors...")
                for i in range(0, len(ids_batch), BATCH_SIZE):
                    batch_ids = ids_batch[i:i + BATCH_SIZE]
                    batch_metas = metadatas_batch[i:i + BATCH_SIZE]
                    batch_docs = documents_batch[i:i + BATCH_SIZE]

                    # Embed the documents
                    batch_embeddings = []
                    for doc in batch_docs:
                        text_to_embed = doc if doc else "unknown error"
                        resp = embedding_client.embeddings.create(
                            model=os.getenv("COMPANY_EMBEDDING_MODEL", "text-embedding-3-large"),
                            input=text_to_embed
                        )
                        batch_embeddings.append(resp.data[0].embedding)
                        time.sleep(0.1)  # Rate limit

                    collection.upsert(
                        ids=batch_ids,
                        embeddings=batch_embeddings,
                        metadatas=batch_metas,
                        documents=batch_docs
                    )
                    print(f"    Inserted batch {i // BATCH_SIZE + 1} "
                          f"({len(batch_ids)} vectors)")

                migrated = len(ids_batch)
                total_migrated += migrated
                migration_summary.append((ns_name, expected_count, migrated))
                print(f"    [OK] Migrated {migrated}/{expected_count} vectors (via fallback)")
                continue

        if not all_ids:
            print(f"    [WARN] No IDs found for namespace '{ns_name}'. Skipping.")
            migration_summary.append((ns_name, expected_count, 0))
            continue

        print(f"    Found {len(all_ids)} vector IDs")

        # Fetch vectors in batches and insert into ChromaDB
        migrated = 0
        for i in range(0, len(all_ids), BATCH_SIZE):
            batch_ids = all_ids[i:i + BATCH_SIZE]

            # Fetch vectors + metadata from Pinecone
            fetch_response = index.fetch(ids=batch_ids, namespace=ns_name)
            vectors = fetch_response.vectors if hasattr(fetch_response, 'vectors') else fetch_response.get('vectors', {})

            if not vectors:
                continue

            chroma_ids = []
            chroma_embeddings = []
            chroma_metadatas = []
            chroma_documents = []

            for vec_id, vec_data in vectors.items():
                values = vec_data.values if hasattr(vec_data, 'values') else vec_data.get('values', [])
                metadata = vec_data.metadata if hasattr(vec_data, 'metadata') else vec_data.get('metadata', {})

                # Clean metadata: ChromaDB requires str/int/float/bool values
                clean_meta = {}
                for k, v in (metadata or {}).items():
                    if v is None:
                        clean_meta[k] = ""
                    elif isinstance(v, (str, int, float, bool)):
                        clean_meta[k] = v
                    else:
                        clean_meta[k] = str(v)

                chroma_ids.append(vec_id)
                chroma_embeddings.append(values)
                chroma_metadatas.append(clean_meta)
                chroma_documents.append(
                    clean_meta.get("error_message", "")[:5000]
                )

            # Insert into ChromaDB
            if chroma_ids:
                collection.upsert(
                    ids=chroma_ids,
                    embeddings=chroma_embeddings,
                    metadatas=chroma_metadatas,
                    documents=chroma_documents
                )
                migrated += len(chroma_ids)
                print(f"    Batch {i // BATCH_SIZE + 1}: "
                      f"inserted {len(chroma_ids)} vectors "
                      f"(total: {migrated}/{expected_count})")

            time.sleep(0.2)  # Be gentle with Pinecone API

        total_migrated += migrated
        migration_summary.append((ns_name, expected_count, migrated))
        print(f"    [OK] Migrated {migrated}/{expected_count} vectors\n")

    # ── Summary ─────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("MIGRATION SUMMARY")
    print("=" * 60)
    print(f"\n{'Namespace':<30} {'Expected':>10} {'Migrated':>10} {'Status':>10}")
    print("-" * 60)
    for ns, expected, migrated in migration_summary:
        status = "OK" if migrated >= expected else "PARTIAL"
        print(f"{ns:<30} {expected:>10} {migrated:>10} {status:>10}")
    print("-" * 60)
    print(f"{'TOTAL':<30} {total_vectors:>10} {total_migrated:>10}")
    print()

    # Verify
    print("[VERIFY] ChromaDB collections:")
    for coll in chroma_client.list_collections():
        count = chroma_client.get_collection(coll.name).count()
        print(f"  - {coll.name}: {count} vectors")

    print(f"\n[DONE] Migration complete. ChromaDB data at: {CHROMA_PERSIST_DIR}")


if __name__ == "__main__":
    migrate()
