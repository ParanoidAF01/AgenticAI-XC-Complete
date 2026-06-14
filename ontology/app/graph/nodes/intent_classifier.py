"""
Step 4 — Intent Classification node.

Sends the cleaned query to GPT‑4o via ``LLMService.chat()`` and parses
the structured JSON response into an intent label + confidence score.
"""

from __future__ import annotations

import json
import logging

from app.config import get_settings
from app.graph.state import WorkflowState
from app.prompts.intent_prompt import INTENT_CLASSIFICATION_PROMPT
from app.services.llm_service import LLMService

logger = logging.getLogger(__name__)

# Valid intent labels recognised by downstream nodes.
_VALID_INTENTS: set[str] = {"COUNT", "LIST", "AGGREGATE", "COMPARE", "LOOKUP", "OTHER"}


async def intent_classifier(state: WorkflowState) -> dict:
    """Classify the user's intent using the LLM.

    The LLM is expected to return a JSON object::

        {"intent": "COUNT", "confidence": 0.95, "reasoning": "..."}

    If the response cannot be parsed or the intent is unrecognised, the
    node falls back to ``OTHER`` with a low confidence score.

    Returns
    -------
    dict
        Partial state update with ``intent``, ``intent_confidence``, and
        ``current_node``.
    """
    logger.info("intent_classifier ▸ ENTER")

    try:
        settings = get_settings()
        cleaned_query: str = state.get("cleaned_query", "")

        llm = LLMService(api_key=settings.openai_api_key, model=settings.openai_model)
        parsed: dict = await llm.chat_json(
            system_prompt=INTENT_CLASSIFICATION_PROMPT,
            user_message=cleaned_query,
        )

        intent = str(parsed.get("intent", "OTHER")).upper()
        confidence = float(parsed.get("confidence", 0.0))

        # Clamp / validate
        if intent not in _VALID_INTENTS:
            logger.warning(
                "intent_classifier ▸ unrecognised intent %r, falling back to OTHER",
                intent,
            )
            intent = "OTHER"
            confidence = min(confidence, 0.3)

        confidence = max(0.0, min(1.0, confidence))

        logger.info(
            "intent_classifier ▸ EXIT  intent=%s  confidence=%.2f",
            intent,
            confidence,
        )
        return {
            "intent": intent,
            "intent_confidence": confidence,
            "current_node": "intent_classifier",
        }

    except (json.JSONDecodeError, KeyError, ValueError) as parse_err:
        logger.warning("intent_classifier ▸ parse error: %s", parse_err)
        return {
            "intent": "OTHER",
            "intent_confidence": 0.0,
            "current_node": "intent_classifier",
            "error": f"Intent classification parse error: {parse_err}",
        }
    except Exception as exc:
        logger.exception("intent_classifier ▸ unexpected error")
        return {
            "intent": "OTHER",
            "intent_confidence": 0.0,
            "current_node": "intent_classifier",
            "error": f"Intent classification failed: {exc}",
        }
