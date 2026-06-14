"""
Step 7 — GraphRAG Context Retrieval node.

Queries the Neo4j metadata graph to retrieve semantically relevant
tables, business concepts, query patterns, and domain context.
"""

from __future__ import annotations

import logging
from typing import Any

from app.graph.state import WorkflowState

logger = logging.getLogger(__name__)


async def graphrag_retriever(state: WorkflowState) -> dict:
    """Retrieve semantic context from the Neo4j ontology graph.

    Uses the shared ``neo4j_service`` from state to query full-text
    indexes and discover relevant tables, concepts, and patterns.

    Returns
    -------
    dict
        Partial state update with ``graphrag_context``, ``tables_used``,
        and ``current_node``.
    """
    logger.info("graphrag_retriever ▸ ENTER")

    try:
        cleaned_query: str = state.get("cleaned_query", "")
        entities: list[dict[str, Any]] = state.get("entities", [])

        neo4j = state.get("neo4j_service")
        if neo4j is None:
            raise RuntimeError("neo4j_service not found in workflow state")

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
