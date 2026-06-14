"""
Step 5 — Entity Extraction node (two‑phase).

Phase 1: SpaCy NER to pull standard entities (PERSON, DATE, ORG, GPE,
         MONEY) from the cleaned query.
Phase 2: LLM domain extraction — sends SpaCy output as context and asks
         GPT‑4o to resolve domain‑specific business entities such as
         Agent, Policy, Broker, Coverage, LOB, Company, TimeReference.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any

import spacy

from app.config import get_settings
from app.graph.state import WorkflowState
from app.prompts.entity_prompt import ENTITY_EXTRACTION_PROMPT
from app.services.llm_service import LLMService

logger = logging.getLogger(__name__)

# Lazy‑loaded SpaCy model (loaded once per process).
_nlp: spacy.language.Language | None = None


def _get_nlp() -> spacy.language.Language:
    """Return a cached SpaCy model instance (name from config)."""
    global _nlp  # noqa: PLW0603
    if _nlp is None:
        model_name = get_settings().spacy_model
        try:
            _nlp = spacy.load(model_name)
        except OSError:
            logger.warning(
                "SpaCy model %r not installed — falling back to blank English pipeline.",
                model_name,
            )
            _nlp = spacy.blank("en")
    return _nlp


# ── helpers ──────────────────────────────────────────────────────────────────

_SPACY_LABELS = {"PERSON", "DATE", "ORG", "GPE", "MONEY"}


def _spacy_ner(text: str) -> list[dict[str, str]]:
    """Run SpaCy NER on *text* and return recognised entities."""
    doc = _get_nlp()(text)
    return [
        {"text": ent.text, "label": ent.label_}
        for ent in doc.ents
        if ent.label_ in _SPACY_LABELS
    ]


def _resolve_relative_date(value: str) -> dict[str, str] | None:
    """Best‑effort resolution of common relative date phrases.

    Returns a dict ``{"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}``
    or ``None`` if the phrase is not recognised.
    """
    today = datetime.utcnow().date()
    lower = value.lower().strip()

    if lower in {"last month", "previous month"}:
        first_of_this_month = today.replace(day=1)
        end = first_of_this_month - timedelta(days=1)
        start = end.replace(day=1)
        return {"start": start.isoformat(), "end": end.isoformat()}

    if lower in {"this month", "current month"}:
        start = today.replace(day=1)
        return {"start": start.isoformat(), "end": today.isoformat()}

    if lower in {"last year", "previous year"}:
        start = today.replace(year=today.year - 1, month=1, day=1)
        end = today.replace(year=today.year - 1, month=12, day=31)
        return {"start": start.isoformat(), "end": end.isoformat()}

    if lower in {"this year", "current year"}:
        start = today.replace(month=1, day=1)
        return {"start": start.isoformat(), "end": today.isoformat()}

    if lower in {"last quarter", "previous quarter"}:
        current_quarter = (today.month - 1) // 3 + 1
        if current_quarter == 1:
            start = today.replace(year=today.year - 1, month=10, day=1)
            end = today.replace(year=today.year - 1, month=12, day=31)
        else:
            start_month = (current_quarter - 2) * 3 + 1
            end_month = start_month + 2
            start = today.replace(month=start_month, day=1)
            if end_month == 12:
                end = today.replace(month=12, day=31)
            else:
                end = today.replace(month=end_month + 1, day=1) - timedelta(days=1)
        return {"start": start.isoformat(), "end": end.isoformat()}

    if lower == "yesterday":
        d = today - timedelta(days=1)
        return {"start": d.isoformat(), "end": d.isoformat()}

    if lower == "today":
        return {"start": today.isoformat(), "end": today.isoformat()}

    if lower in {"last week", "previous week"}:
        start = today - timedelta(days=today.weekday() + 7)
        end = start + timedelta(days=6)
        return {"start": start.isoformat(), "end": end.isoformat()}

    return None


def _parse_llm_entities(raw_dict: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert the LLM's structured JSON response into a flat entity list.

    The LLM returns::

        {"entities": {"Agent": {"value": ..., "resolved": ...}, ...},
         "date_context": {...}}

    We flatten it into a list of dicts with ``type``, ``value``, ``resolved``.
    """
    entities_map = raw_dict.get("entities", {})
    result: list[dict[str, Any]] = []
    for entity_type, detail in entities_map.items():
        if isinstance(detail, dict):
            result.append({
                "type": entity_type,
                "value": detail.get("value"),
                "resolved": detail.get("resolved"),
            })
        else:
            result.append({"type": entity_type, "value": detail})

    # Attach date_context if present
    date_ctx = raw_dict.get("date_context", {})
    if date_ctx:
        resolved_range = date_ctx.get("resolved_range", {})
        if resolved_range.get("start") or resolved_range.get("end"):
            # Merge into the TimeReference entity if it exists
            for ent in result:
                if ent["type"] == "TimeReference":
                    ent["resolved_range"] = resolved_range
                    break

    return result


# ── main node ────────────────────────────────────────────────────────────────


async def entity_extractor(state: WorkflowState) -> dict:
    """Extract entities in two phases: SpaCy NER then LLM domain extraction.

    Phase 1
    -------
    Run SpaCy on the cleaned query to detect PERSON, DATE, ORG, GPE, and
    MONEY entities.

    Phase 2
    -------
    Send the SpaCy results as context to the LLM together with the
    ``ENTITY_EXTRACTION_PROMPT`` to resolve domain‑specific entities
    (Agent, Policy, Broker, Coverage, LOB, Company, TimeReference, …).
    Relative date phrases (e.g. "last month") are resolved to concrete
    date ranges.

    Returns
    -------
    dict
        Partial state update with ``entities`` and ``current_node``.
    """
    logger.info("entity_extractor ▸ ENTER")

    try:
        settings = get_settings()
        cleaned_query: str = state.get("cleaned_query", "")

        # ── Phase 1: SpaCy NER ──────────────────────────────────────
        spacy_entities = _spacy_ner(cleaned_query)
        logger.info(
            "entity_extractor ▸ Phase 1 (SpaCy) → %d entities",
            len(spacy_entities),
        )

        # ── Phase 2: LLM domain extraction ──────────────────────────
        llm = LLMService(api_key=settings.openai_api_key, model=settings.openai_model)

        spacy_context = json.dumps(spacy_entities, default=str)
        user_message = (
            f"Question: {cleaned_query}\n\n"
            f"SpaCy NER entities (for reference):\n{spacy_context}"
        )

        parsed: dict[str, Any] = await llm.chat_json(
            system_prompt=ENTITY_EXTRACTION_PROMPT,
            user_message=user_message,
        )

        domain_entities = _parse_llm_entities(parsed)

        # ── Resolve relative dates (local fallback) ──────────────────
        for entity in domain_entities:
            if entity.get("type") == "TimeReference" and entity.get("value"):
                resolved = _resolve_relative_date(entity["value"])
                if resolved and "resolved_range" not in entity:
                    entity["resolved_range"] = resolved

        # Merge SpaCy entities into the output for traceability.
        all_entities: list[dict[str, Any]] = [
            *[
                {"type": e["label"], "value": e["text"], "source": "spacy"}
                for e in spacy_entities
            ],
            *[
                {**e, "source": "llm"}
                for e in domain_entities
            ],
        ]

        logger.info(
            "entity_extractor ▸ EXIT  total_entities=%d", len(all_entities)
        )
        return {
            "entities": all_entities,
            "current_node": "entity_extractor",
        }

    except (json.JSONDecodeError, KeyError, ValueError) as parse_err:
        logger.warning("entity_extractor ▸ LLM parse error: %s", parse_err)
        spacy_fallback = [
            {"type": e["label"], "value": e["text"], "source": "spacy"}
            for e in _spacy_ner(state.get("cleaned_query", ""))
        ]
        return {
            "entities": spacy_fallback,
            "current_node": "entity_extractor",
            "error": f"Entity extraction LLM parse error: {parse_err}",
        }
    except Exception as exc:
        logger.exception("entity_extractor ▸ unexpected error")
        return {
            "entities": [],
            "current_node": "entity_extractor",
            "error": f"Entity extraction failed: {exc}",
        }
