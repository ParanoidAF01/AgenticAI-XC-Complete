"""
Step 6 — Clarification Check node.

Decides whether the pipeline has enough information to proceed or needs to
ask the user a follow‑up question.  Rules are intent‑dependent.
"""

from __future__ import annotations

import logging
from typing import Any

from app.graph.state import WorkflowState

logger = logging.getLogger(__name__)


# ── helpers ──────────────────────────────────────────────────────────────────

def _entity_types(entities: list[dict[str, Any]]) -> set[str]:
    """Return the set of entity *type* values present in *entities*."""
    return {
        str(e.get("type", "")).lower()
        for e in entities
        if e.get("type")
    }


def _has_business_object(types: set[str]) -> bool:
    """Check whether at least one well‑known business object is present."""
    business_objects = {
        "agent", "policy", "broker", "coverage", "lob",
        "company", "product", "program", "premium", "commission",
        "section", "risk", "location", "party", "classification",
    }
    return bool(types & business_objects)


def _has_identifier(entities: list[dict[str, Any]]) -> bool:
    """Check whether any entity carries an identifying value."""
    for ent in entities:
        if ent.get("value") and str(ent.get("value")).strip():
            return True
    return False


def _count_compare_items(entities: list[dict[str, Any]]) -> int:
    """Count the number of distinct comparable items in entities."""
    comparable_types = {"agent", "broker", "company", "lob", "product", "coverage"}
    items: set[str] = set()
    for ent in entities:
        etype = str(ent.get("type", "")).lower()
        value = str(ent.get("value", "")).strip()
        if etype in comparable_types and value:
            items.add(f"{etype}::{value}")
    return len(items)


# ── main node ────────────────────────────────────────────────────────────────


async def clarity_checker(state: WorkflowState) -> dict:
    """Check whether the extracted information is sufficient for the intent.

    Rules
    -----
    * **COUNT** — needs at least one business object (e.g. "policies",
      "agents").
    * **LOOKUP** — needs an identifier (a name, code, or number to look
      up).
    * **COMPARE** — needs at least two comparable items.
    * **LIST / AGGREGATE / OTHER** — needs at least one business object.

    If any rule is not satisfied the node sets
    ``needs_clarification = True`` and produces a clarification question.

    Returns
    -------
    dict
        Partial state update with ``needs_clarification``,
        ``clarification_question``, and ``current_node``.
    """
    logger.info("clarity_checker ▸ ENTER")

    try:
        intent: str = (state.get("intent") or "OTHER").upper()
        entities: list[dict[str, Any]] = state.get("entities", [])
        types = _entity_types(entities)

        needs_clarification = False
        clarification_question: str | None = None

        if intent == "COUNT":
            if not _has_business_object(types):
                needs_clarification = True
                clarification_question = (
                    "Could you specify what you'd like to count? "
                    "For example: policies, agents, brokers, or claims."
                )

        elif intent == "LOOKUP":
            if not _has_identifier(entities):
                needs_clarification = True
                clarification_question = (
                    "Which specific record are you looking for? "
                    "Please provide a name, code, or policy number."
                )

        elif intent == "COMPARE":
            if _count_compare_items(entities) < 2:
                needs_clarification = True
                clarification_question = (
                    "A comparison needs at least two items. "
                    "Could you specify which items you'd like to compare?"
                )

        else:
            # LIST, AGGREGATE, OTHER — at minimum need a business object
            if not _has_business_object(types):
                needs_clarification = True
                clarification_question = (
                    "I'm not sure which data you're referring to. "
                    "Could you mention a specific business entity such as "
                    "policy, agent, broker, or coverage?"
                )

        if needs_clarification:
            logger.info(
                "clarity_checker ▸ EXIT  needs_clarification=True  q=%r",
                clarification_question,
            )
        else:
            logger.info("clarity_checker ▸ EXIT  needs_clarification=False")

        return {
            "needs_clarification": needs_clarification,
            "clarification_question": clarification_question,
            "current_node": "clarity_checker",
        }

    except Exception as exc:
        logger.exception("clarity_checker ▸ unexpected error")
        # On error, don't block — let the pipeline continue.
        return {
            "needs_clarification": False,
            "clarification_question": None,
            "current_node": "clarity_checker",
            "error": f"Clarity check failed: {exc}",
        }
