"""
Step 9 — SQL Generation node.

Feeds the accumulated schema context, entities, intent, and cleaned
query into the LLM to produce a SQL statement.
"""

from __future__ import annotations

import logging
from typing import Any

from app.config import get_settings
from app.graph.state import WorkflowState
from app.prompts.sql_prompt import SQL_GENERATION_PROMPT
from app.services.llm_service import LLMService

logger = logging.getLogger(__name__)


async def sql_generator(state: WorkflowState) -> dict:
    """Generate a SQL statement using the LLM.

    Uses ``LLMService.generate_sql()`` which takes:

    * ``system_prompt`` — SQL_GENERATION_PROMPT
    * ``schema_context`` — tables, columns, joins, precomputed paths
    * ``question`` — the cleaned user query
    * ``intent`` — classified intent (COUNT, LIST, …)
    * ``entities`` — extracted entities dict

    On retry (``retry_count > 0``), the previous ``sql_error`` is appended
    to the question so the LLM can self‑correct.

    Returns
    -------
    dict
        Partial state update with ``generated_sql`` and ``current_node``.
    """
    logger.info("sql_generator ▸ ENTER")

    try:
        settings = get_settings()
        cleaned_query: str = state.get("cleaned_query", "")
        intent: str = state.get("intent") or "OTHER"
        entities: list[dict[str, Any]] = state.get("entities", [])
        schema_context: dict[str, Any] = state.get("schema_context", {})
        sql_error: str | None = state.get("sql_error")

        # On retry, include the previous validation error for self-correction.
        question = cleaned_query
        if state.get("retry_count", 0) > 0 and sql_error:
            question = (
                f"{cleaned_query}\n\n"
                f"--- PREVIOUS ATTEMPT FAILED ---\n"
                f"Error: {sql_error}\n"
                f"Please fix the SQL to address this error."
            )

        # Convert entity list to a dict keyed by type for the LLM helper.
        entities_dict: dict[str, Any] = {}
        for ent in entities:
            etype = ent.get("type", "unknown")
            entities_dict[etype] = {
                k: v for k, v in ent.items() if k != "source"
            }

        llm = LLMService(api_key=settings.openai_api_key, model=settings.openai_model)
        sql: str = await llm.generate_sql(
            system_prompt=SQL_GENERATION_PROMPT,
            schema_context=schema_context,
            question=question,
            intent=intent,
            entities=entities_dict,
        )

        if not sql.strip():
            logger.warning("sql_generator ▸ LLM returned empty SQL")
            return {
                "generated_sql": None,
                "current_node": "sql_generator",
                "error": "LLM returned an empty SQL statement.",
            }

        logger.info("sql_generator ▸ EXIT  sql=%s", sql[:120])
        return {
            "generated_sql": sql,
            "current_node": "sql_generator",
        }

    except Exception as exc:
        logger.exception("sql_generator ▸ unexpected error")
        return {
            "generated_sql": None,
            "current_node": "sql_generator",
            "error": f"SQL generation failed: {exc}",
        }
