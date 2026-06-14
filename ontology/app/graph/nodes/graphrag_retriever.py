"""
Step 7 — GraphRAG Context Retrieval node.

Queries the Neo4j metadata graph to retrieve semantically relevant
tables, business concepts, query patterns, and domain context.
"""

from __future__ import annotations

import logging
from typing import Any

from app.config import get_settings
from app.graph.state import WorkflowState
from app.services.neo4j_service import Neo4jService

logger = logging.getLogger(__name__)


async def graphrag_retriever(state: WorkflowState) -> dict:
    """Retrieve semantic context from the Neo4j ontology graph.

    Sub‑steps
    ---------
    1. **Full‑text table search** — ``find_relevant_tables()`` to discover
       ``Table`` nodes whose name, description, or business_purpose match.
    2. **Business concept search** — ``get_business_concepts()`` to surface
       high‑level domain concepts with SQL logic hints.
    3. **Query pattern search** — ``get_query_patterns()`` to find canonical
       SQL templates for similar questions.
    4. **Domain context** — ``get_domain_context()`` to pull ``Domain`` nodes
       linked to the matched tables.

    Returns
    -------
    dict
        Partial state update with ``graphrag_context``, ``tables_used``,
        and ``current_node``.
    """
    logger.info("graphrag_retriever ▸ ENTER")

    neo4j: Neo4jService | None = None
    try:
        settings = get_settings()
        cleaned_query: str = state.get("cleaned_query", "")
        entities: list[dict[str, Any]] = state.get("entities", [])

        neo4j = Neo4jService(
            uri=settings.neo4j_uri,
            user=settings.neo4j_user,
            password=settings.neo4j_password,
        )

        # Build a combined search string from the query and entity values.
        entity_values = " ".join(
            str(e.get("value", ""))
            for e in entities
            if e.get("value")
        )
        search_text = f"{cleaned_query} {entity_values}".strip()

        # ── 7.1  Full‑text table search ─────────────────────────────
        matched_tables: list[dict[str, Any]] = await neo4j.find_relevant_tables(
            search_text
        )
        logger.info(
            "graphrag_retriever ▸ matched %d tables", len(matched_tables)
        )

        table_names: list[str] = [
            t.get("table_name", "") for t in matched_tables if t.get("table_name")
        ]

        # ── 7.2  Business concept search ────────────────────────────
        concepts: list[dict[str, Any]] = await neo4j.get_business_concepts(
            search_text
        )
        logger.info(
            "graphrag_retriever ▸ matched %d concepts", len(concepts)
        )

        # ── 7.3  Query pattern search ───────────────────────────────
        patterns: list[dict[str, Any]] = await neo4j.get_query_patterns(
            search_text
        )
        logger.info(
            "graphrag_retriever ▸ matched %d patterns", len(patterns)
        )

        # ── 7.4  Domain context for matched tables ──────────────────
        domains: list[dict[str, Any]] = []
        if table_names:
            domains = await neo4j.get_domain_context(table_names)

        graphrag_context: dict[str, Any] = {
            "matched_tables": matched_tables,
            "concepts": concepts,
            "patterns": patterns,
            "domains": domains,
        }

        logger.info(
            "graphrag_retriever ▸ EXIT  tables_used=%s", table_names
        )
        return {
            "graphrag_context": graphrag_context,
            "tables_used": table_names,
            "current_node": "graphrag_retriever",
        }

    except Exception as exc:
        logger.exception("graphrag_retriever ▸ unexpected error")
        return {
            "graphrag_context": {
                "matched_tables": [],
                "concepts": [],
                "patterns": [],
                "domains": [],
            },
            "tables_used": [],
            "current_node": "graphrag_retriever",
            "error": f"GraphRAG retrieval failed: {exc}",
        }
    finally:
        if neo4j is not None:
            await neo4j.close()
