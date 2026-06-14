"""
Step 3 — Input Processing node.

Sanitises, normalises and validates the raw user query before it enters
the classification / extraction pipeline.
"""

from __future__ import annotations

import html
import logging
import re

from app.graph.state import WorkflowState

logger = logging.getLogger(__name__)

# ── constants ────────────────────────────────────────────────────────────────
_MAX_QUERY_LENGTH = 2000
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


async def input_processor(state: WorkflowState) -> dict:
    """Sanitise and validate the raw user query.

    Processing steps
    ----------------
    1. Strip HTML tags and unescape HTML entities.
    2. Collapse consecutive whitespace into a single space.
    3. Strip leading / trailing whitespace.
    4. Lower‑case the entire string.
    5. Validate: non‑empty and within *MAX_QUERY_LENGTH* characters.

    Returns
    -------
    dict
        Partial state update with ``cleaned_query``, ``current_node``, and
        optionally ``error``.
    """
    logger.info("input_processor ▸ ENTER")

    try:
        raw_query: str = state.get("user_query", "")

        # 1. Unescape HTML entities  &amp; → &  etc.
        cleaned = html.unescape(raw_query)

        # 2. Strip HTML tags
        cleaned = _HTML_TAG_RE.sub("", cleaned)

        # 3. Normalise whitespace
        cleaned = _WHITESPACE_RE.sub(" ", cleaned).strip()

        # 4. Lower‑case
        cleaned = cleaned.lower()

        # 5. Validation ──────────────────────────────────────────────────
        if not cleaned:
            logger.warning("input_processor ▸ empty query after sanitisation")
            return {
                "cleaned_query": "",
                "current_node": "input_processor",
                "error": "Query is empty after sanitisation. Please provide a valid question.",
            }

        if len(cleaned) > _MAX_QUERY_LENGTH:
            logger.warning(
                "input_processor ▸ query too long (%d chars)", len(cleaned)
            )
            return {
                "cleaned_query": cleaned[:_MAX_QUERY_LENGTH],
                "current_node": "input_processor",
                "error": (
                    f"Query exceeds the maximum length of {_MAX_QUERY_LENGTH} "
                    "characters. Please shorten your question."
                ),
            }

        logger.info("input_processor ▸ EXIT  cleaned_query=%r", cleaned[:80])
        return {
            "cleaned_query": cleaned,
            "current_node": "input_processor",
        }

    except Exception as exc:
        logger.exception("input_processor ▸ unexpected error")
        return {
            "cleaned_query": state.get("user_query", ""),
            "current_node": "input_processor",
            "error": f"Input processing failed: {exc}",
        }
