"""
ChromaDB Data Viewer — Browse collections and vectors from the terminal.

Usage:
    python scripts/view_chroma.py                     # List all collections
    python scripts/view_chroma.py PL_Template_3_schema  # View a specific collection
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

import chromadb

PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR",
    os.path.join(os.path.dirname(__file__), "..", "chroma_db"))

client = chromadb.PersistentClient(path=PERSIST_DIR)


def list_collections():
    """Show all collections with vector counts."""
    collections = client.list_collections()
    print(f"\nChromaDB: {PERSIST_DIR}")
    print(f"Total collections: {len(collections)}\n")
    print(f"{'Collection':<45} {'Vectors':>8}")
    print("-" * 55)
    total = 0
    for coll in sorted(collections, key=lambda c: c.name):
        count = client.get_collection(coll.name).count()
        total += count
        print(f"{coll.name:<45} {count:>8}")
    print("-" * 55)
    print(f"{'TOTAL':<45} {total:>8}")


def view_collection(name):
    """Show all vectors in a collection with metadata."""
    try:
        coll = client.get_collection(name)
    except Exception:
        print(f"[ERROR] Collection '{name}' not found.")
        return

    data = coll.get(include=["metadatas", "documents"])
    count = coll.count()

    print(f"\nCollection: {name}")
    print(f"Vectors: {count}\n")

    if not data["ids"]:
        print("  (empty)")
        return

    for i, doc_id in enumerate(data["ids"]):
        meta = data["metadatas"][i] if data["metadatas"] else {}
        doc = (data["documents"][i][:200] + "...") if data["documents"] and data["documents"][i] else "N/A"

        print(f"  [{i+1}] ID: {doc_id}")
        print(f"      Error Type: {meta.get('error_type', 'N/A')}")
        print(f"      Type Name:  {meta.get('error_type_name', 'N/A')}")
        print(f"      Pipeline:   {meta.get('pipeline_name', 'N/A')}")
        print(f"      Priority:   {meta.get('priority', 'N/A')}")
        print(f"      Timestamp:  {meta.get('timestamp', 'N/A')}")
        print(f"      Root Cause: {meta.get('root_cause', 'N/A')[:150]}")
        print(f"      Message:    {doc[:150]}")
        print()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        view_collection(sys.argv[1])
    else:
        list_collections()
        print("\nUsage: python scripts/view_chroma.py <collection_name>")
