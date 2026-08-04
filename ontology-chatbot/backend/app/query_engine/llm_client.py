"""Async LLM client – Anthropic only.

Converted from the legacy synchronous requests.post implementation to
httpx.AsyncClient while preserving the exact same Anthropic API contract
(headers, payload shape, response parsing).

Supports automatic continuation when LLM output is truncated mid-response.
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


async def call_llm(
    messages: List[Dict[str, str]],
    max_tokens: int = 1800,
    auto_continue: bool = False,
    max_continuations: int = 2,
) -> str:
    """Call the Anthropic LLM API.

    Args:
        messages: List of message dicts with 'role' and 'content'.
        max_tokens: Maximum tokens per API call.
        auto_continue: If True, automatically detect truncation via
            the API's stop_reason and send follow-up requests to
            complete the response. Up to max_continuations extra calls.
        max_continuations: Maximum number of continuation calls (default 2,
            so 3 total calls max).

    Returns:
        The complete LLM response text.
    """
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
    non_system = [
        {"role": m["role"], "content": m["content"]}
        for m in messages
        if m["role"] != "system"
    ]
    system_text = "\n\n".join(system_parts)

    # ── First call ──────────────────────────────────────────────
    payload = {
        "model": cfg["model"],
        "max_tokens": max_tokens,
        "temperature": 0.0,
        "system": system_text,
        "messages": non_system,
    }

    logger.info("Calling Anthropic LLM")
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            cfg["endpoint"].rstrip("/"), headers=headers, json=payload
        )
    if resp.status_code >= 300:
        raise LLMError(f"Anthropic call failed: {resp.status_code} {resp.text}")

    data = resp.json()
    texts = [
        b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"
    ]
    final_text = "\n".join(texts).strip()
    if not final_text:
        raise LLMError(f"Anthropic returned empty text response: {data}")

    # ── Auto-continuation loop ──────────────────────────────────
    if auto_continue:
        stop_reason = data.get("stop_reason") or data.get("stop", "")
        accumulated = final_text
        conversation = list(non_system)  # mutable copy for continuation
        continuations_done = 0

        while stop_reason == "max_tokens" and continuations_done < max_continuations:
            continuations_done += 1
            logger.warning(
                "LLM output truncated (stop_reason=max_tokens). "
                "Auto-continuing, attempt %d/%d",
                continuations_done,
                max_continuations,
            )

            # Feed partial response back as assistant, ask to continue
            conversation.append({"role": "assistant", "content": accumulated})
            conversation.append({
                "role": "user",
                "content": (
                    "Your previous response was truncated. Continue your JSON output "
                    "from EXACTLY where you left off. Do NOT repeat any text that was "
                    "already generated. Output ONLY the remaining JSON."
                ),
            })

            cont_payload = {
                "model": cfg["model"],
                "max_tokens": max_tokens,
                "temperature": 0.0,
                "system": system_text,
                "messages": conversation,
            }

            async with httpx.AsyncClient(timeout=120.0) as client:
                cont_resp = await client.post(
                    cfg["endpoint"].rstrip("/"), headers=headers, json=cont_payload
                )
            if cont_resp.status_code >= 300:
                raise LLMError(
                    f"Anthropic continuation call failed: "
                    f"{cont_resp.status_code} {cont_resp.text}"
                )

            cont_data = cont_resp.json()
            cont_texts = [
                b.get("text", "")
                for b in cont_data.get("content", [])
                if b.get("type") == "text"
            ]
            cont_text = "\n".join(cont_texts).strip()
            if not cont_text:
                logger.warning("Continuation returned empty text, stopping.")
                break

            accumulated = accumulated + cont_text
            stop_reason = cont_data.get("stop_reason") or cont_data.get("stop", "")

            logger.info(
                "Continuation %d complete (stop_reason=%s, +%d chars)",
                continuations_done,
                stop_reason,
                len(cont_text),
            )

        if stop_reason == "max_tokens":
            logger.error(
                "LLM output still truncated after %d continuations. "
                "Total accumulated length: %d chars",
                max_continuations,
                len(accumulated),
            )

        final_text = accumulated

    return final_text


async def llm_json(
    system_prompt: str, user_payload: Dict[str, Any], max_tokens: int = 1800
) -> Dict[str, Any]:
    raw = await call_llm(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(make_json_safe(user_payload), indent=2)},
        ],
        max_tokens=max_tokens,
    )
    return json.loads(extract_json_text(raw))
