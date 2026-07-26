"""Question router – classifies user input as general_chat / simple_db / complex_db.

route_question is async because it calls llm_json.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from app.query_engine.helpers import normalize_text
from app.query_engine.llm_client import llm_json
from app.query_engine.prompts import ROUTER_PROMPT

logger = logging.getLogger(__name__)


def is_greeting_or_general(q: str) -> bool:
    greeting_terms = {"hi", "hello", "hey", "thanks", "thank you", "help", "namaste", "hola"}
    return q in greeting_terms or any(q.startswith(x) for x in ["hi ", "hello ", "hey ", "thanks ", "thank you "])


def extract_candidate_terms(q: str) -> List[str]:
    toks = q.split()
    terms = set()
    for n in (4, 3, 2, 1):
        for i in range(len(toks) - n + 1):
            terms.add(" ".join(toks[i:i+n]))
    return sorted(terms, key=lambda x: (-len(x.split()), x))


async def route_question(question: str, conversation_context: str = "") -> Dict[str, Any]:
    nq = normalize_text(question)
    if is_greeting_or_general(nq) and not conversation_context:
        return {"route": "general_chat", "reason": "greeting"}
    try:
        payload: Dict[str, Any] = {"user_question": question}
        if conversation_context:
            payload["conversation_context"] = conversation_context
        routed = await llm_json(ROUTER_PROMPT, payload, max_tokens=150)
        route = routed.get("route")
        if route not in {"general_chat", "simple_db", "complex_db"}:
            route = "simple_db"
        return {"route": route, "reason": routed.get("reason", "")}
    except Exception as e:
        logger.warning(f"Router fallback due to error -> {e}")
        return {"route": "simple_db", "reason": "fallback"}
