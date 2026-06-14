"""
Step 8 — Ontology Relationship Lookup node.

Converts the GraphRAG context (business concepts) into concrete SQL
schema information: join relationships, pre‑computed join paths, column
details, and table metadata.
"""

from __future__ import annotations

import logging
from typing import Any

from app.config import get_settings
from app.graph.state import WorkflowState
from app.services.neo4j_service import Neo4jService

logger = logging.getLogger(__name__)


async def ontology_lookup(state: WorkflowState) -> dict:
    """Resolve ontology relationships for tables identified by GraphRAG.

    Sub‑steps
    ---------
    1. **JOINS_TO relationships** — ``get_join_paths()`` returns
       ``(:Table)-[:JOINS_TO]→(:Table)`` edges with ``sql_snippet``.
    2. **Pre‑computed JoinPath nodes** — ``get_precomputed_paths()``
       fetches ``JoinPath`` nodes for multi‑hop traversals.
    3. **Columns** — ``get_columns_for_table()`` per table.
    4. **Table details** — ``get_table_details()`` for descriptions and
       business purposes.

    Returns
    -------
    dict
        Partial state update with ``ontology_context``, ``schema_context``,
        and ``current_node``.
    """
    logger.info("ontology_lookup ▸ ENTER")

    neo4j: Neo4jService | None = None
    try:
        settings = get_settings()
        tables_used: list[str] = state.get("tables_used", [])
        graphrag_ctx: dict[str, Any] = state.get("graphrag_context", {})

        neo4j = Neo4jService(
            uri=settings.neo4j_uri,
            user=settings.neo4j_user,
            password=settings.neo4j_password,
        )

        # ── 8.1  JOINS_TO relationships ─────────────────────────────
        joins: list[dict[str, Any]] = []
        if len(tables_used) >= 2:
            joins = await neo4j.get_join_paths(tables_used)
        logger.info("ontology_lookup ▸ %d join relationships found", len(joins))

        # ── 8.2  Pre‑computed JoinPath nodes ────────────────────────
        precomputed_paths: list[dict[str, Any]] = await neo4j.get_precomputed_paths(
            tables_used
        )
        logger.info(
            "ontology_lookup ▸ %d pre‑computed paths found", len(precomputed_paths)
        )

        # ── 8.3  Columns for each table ─────────────────────────────
        columns_by_table: dict[str, list[dict[str, Any]]] = {}
        for table_name in tables_used:
            cols = await neo4j.get_columns_for_table(table_name)
            columns_by_table[table_name] = cols

        total_cols = sum(len(v) for v in columns_by_table.values())
        logger.info("ontology_lookup ▸ %d total columns across tables", total_cols)

        # ── 8.4  Table details ──────────────────────────────────────
        table_details: dict[str, dict[str, Any]] = {}
        for table_name in tables_used:
            detail = await neo4j.get_table_details(table_name)
            if detail:
                table_details[table_name] = detail

        # ── Assemble contexts ────────────────────────────────────────
        ontology_context: dict[str, Any] = {
            "joins": joins,
            "join_paths": precomputed_paths,
            "table_details": table_details,
            "concepts": graphrag_ctx.get("concepts", []),
        }

        schema_context: dict[str, Any] = {
            "tables": table_details,
            "columns": columns_by_table,
            "joins": joins,
            "precomputed_paths": precomputed_paths,
            "business_concepts": graphrag_ctx.get("concepts", []),
            "query_patterns": graphrag_ctx.get("patterns", []),
        }

        logger.info("ontology_lookup ▸ EXIT")
        return {
            "ontology_context": ontology_context,
            "schema_context": schema_context,
            "current_node": "ontology_lookup",
        }

    except Exception as exc:
        logger.exception("ontology_lookup ▸ unexpected error")
        return {
            "ontology_context": {},
            "schema_context": {},
            "current_node": "ontology_lookup",
            "error": f"Ontology lookup failed: {exc}",
        }
    finally:
        if neo4j is not None:
            await neo4j.close()
