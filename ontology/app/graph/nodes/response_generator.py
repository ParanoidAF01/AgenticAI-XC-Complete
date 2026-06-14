"""
Step 12 — Response Generation node.

Converts the raw SQL result set into a natural‑language answer using
the LLM.
"""

from __future__ import annotations

import logging
from typing import Any

from app.graph.state import WorkflowState

logger = logging.getLogger(__name__)

# Maximum number of result rows to send to the LLM to avoid context overflow.
_MAX_RESULT_ROWS = 50


async def response_generator(state: WorkflowState) -> dict:
    """Generate a human‑readable answer from the SQL result.

    Uses ``LLMService.format_response(question, sql, results, entities)``
    which internally calls the LLM with ``RESPONSE_GENERATION_PROMPT`` as
    the system prompt.

    Returns
    -------
    dict
        Partial state update with ``final_response`` and ``current_node``.
    """
    logger.info("response_generator ▸ ENTER")

    try:
        user_query: str = state.get("user_query", "")
        generated_sql: str | None = state.get("generated_sql")
        query_result: list[dict[str, Any]] | None = state.get("query_result")
        entities: list[dict[str, Any]] = state.get("entities", [])
        error: str | None = state.get("error")

        # If an upstream error is present and there are no results,
        # produce a graceful error response.
        if error and not query_result:
            logger.warning("response_generator ▸ upstream error present: %s", error)
            return {
                "final_response": (
                    "I'm sorry, I wasn't able to answer your question due to "
                    f"an internal error: {error}"
                ),
                "current_node": "response_generator",
            }

        llm = state.get("llm_service")
        if llm is None:
            raise RuntimeError("llm_service not found in workflow state")

        # Truncate results for the LLM context window.
        truncated_results: list[dict[str, Any]] = (query_result or [])[:_MAX_RESULT_ROWS]

        # Convert entity list to a dict keyed by type for the LLM helper.
        entities_dict: dict[str, Any] = {}
        for ent in entities:
            etype = ent.get("type", "unknown")
            entities_dict[etype] = {
                k: v for k, v in ent.items() if k != "source"
            }

        response: str = await llm.format_response(
            question=user_query,
            sql=generated_sql or "N/A",
            results=truncated_results,
            entities=entities_dict,
        )

        if not response.strip():
            response = "The query returned results but I was unable to summarise them."

        logger.info(
            "response_generator ▸ EXIT  response_len=%d", len(response)
        )
        return {
            "final_response": response.strip(),
            "current_node": "response_generator",
        }

    except Exception as exc:
        logger.exception("response_generator ▸ unexpected error")
        return {
            "final_response": (
                "I encountered an error while generating your answer. "
                "Please try rephrasing your question."
            ),
            "current_node": "response_generator",
            "error": f"Response generation failed: {exc}",
        }
