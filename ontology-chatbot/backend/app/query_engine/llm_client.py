"""Async LLM client – Anthropic only.

Converted from the legacy synchronous requests.post implementation to
httpx.AsyncClient while preserving the exact same Anthropic API contract
(headers, payload shape, response parsing).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List

import httpx

from app.query_engine.errors import LLMError
from app.query_engine.helpers import extract_json_text, make_json_safe

logger = logging.getLogger(__name__)


def get_llm_config() -> Dict[str, str]:
    return {
        "provider": os.getenv("LLM_PROVIDER", "anthropic").strip().lower(),
        "api_key": os.getenv("LLM_API_KEY", "").strip(),
        "endpoint": os.getenv("LLM_ENDPOINT", "").strip(),
        "model": os.getenv("LLM_MODEL", "").strip(),
        "api_version": os.getenv("LLM_API_VERSION", "2023-06-01").strip(),
    }


async def call_llm(messages: List[Dict[str, str]], max_tokens: int = 1800) -> str:
    cfg = get_llm_config()
    if cfg["provider"] != "anthropic":
        raise LLMError("This app.py is built for Anthropic only")
    if not all([cfg["api_key"], cfg["endpoint"], cfg["model"]]):
        raise LLMError("Missing LLM_API_KEY / LLM_ENDPOINT / LLM_MODEL")
    headers = {
        "x-api-key": cfg["api_key"],
        "anthropic-version": cfg["api_version"] or "2023-06-01",
        "content-type": "application/json",
    }
    system_parts = [m["content"] for m in messages if m["role"] == "system"]
    non_system = [{"role": m["role"], "content": m["content"]} for m in messages if m["role"] != "system"]
    payload = {
        "model": cfg["model"],
        "max_tokens": max_tokens,
        "temperature": 0.0,
        "system": "\n\n".join(system_parts),
        "messages": non_system,
    }
    logger.info("Calling Anthropic LLM")
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(cfg["endpoint"].rstrip("/"), headers=headers, json=payload)
    if resp.status_code >= 300:
        raise LLMError(f"Anthropic call failed: {resp.status_code} {resp.text}")
    data = resp.json()
    texts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
    final_text = "\n".join(texts).strip()
    if not final_text:
        raise LLMError(f"Anthropic returned empty text response: {data}")
    return final_text


async def llm_json(system_prompt: str, user_payload: Dict[str, Any], max_tokens: int = 1800) -> Dict[str, Any]:
    raw = await call_llm(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(make_json_safe(user_payload), indent=2)},
        ],
        max_tokens=max_tokens,
    )
    return json.loads(extract_json_text(raw))
