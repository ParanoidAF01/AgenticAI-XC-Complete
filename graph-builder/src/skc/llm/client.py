"""LiteLLM client wrapper for narrow semantic inference calls."""

from __future__ import annotations

import hashlib
import json
import random
import time
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel
import structlog

from skc.config import LLMConfig

T = TypeVar("T", bound=BaseModel)
logger = structlog.get_logger(__name__)


class LLMClient:
    """Small provider-agnostic wrapper around LiteLLM."""

    def __init__(self, config: LLMConfig, cache_dir: str | Path | None = None) -> None:
        self.config = config
        self.cache_dir = Path(cache_dir) if cache_dir is not None else None
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0
        self.cost_usd = 0.0
        if self.cache_dir is not None:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    def prompt_hash(self, prompt: str) -> str:
        """Return a stable hash for a prompt/model pair."""
        payload = f"{self.config.model}\n{prompt}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def complete_json(
        self,
        prompt: str,
        response_model: type[T],
        system_prompt: str | None = None,
        max_retries: int = 3,
        fallback: T | dict[str, Any] | None = None,
    ) -> T:
        """Call LiteLLM and parse a JSON object into ``response_model``."""
        cache_key = self.prompt_hash(prompt)
        cached = self._read_cache(cache_key)
        if cached is not None:
            logger.info("llm_cache_hit", prompt_hash=cache_key, model=self.config.model)
            return response_model.model_validate(cached)

        last_error: Exception | None = None
        for attempt in range(max_retries):
            try:
                raw = self._completion(prompt, system_prompt)
                parsed_json = self._extract_json(raw)
                self._write_cache(cache_key, parsed_json)
                return response_model.model_validate(parsed_json)
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "llm_call_failed",
                    prompt_hash=cache_key,
                    model=self.config.model,
                    attempt=attempt + 1,
                    max_retries=max_retries,
                    error=str(exc),
                )
                if attempt < max_retries - 1:
                    delay = (0.25 * (2**attempt)) + random.uniform(0.0, 0.1)
                    time.sleep(delay)

        if fallback is not None:
            logger.warning(
                "llm_fallback_used",
                prompt_hash=cache_key,
                model=self.config.model,
                error=str(last_error),
            )
            return fallback if isinstance(fallback, response_model) else response_model.model_validate(fallback)

        raise RuntimeError(f"LLM call failed after {max_retries} attempts: {last_error}")

    def _completion(self, prompt: str, system_prompt: str | None) -> str:
        try:
            import litellm
        except Exception as exc:
            raise RuntimeError("litellm is required for LLM calls") from exc

        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        started = time.monotonic()
        response = litellm.completion(
            model=self.config.model,
            messages=messages,
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
            response_format={"type": "json_object"},
        )
        latency_ms = int((time.monotonic() - started) * 1000)
        usage = self._usage(response)
        cost = self._cost(litellm, response)
        self.calls += 1
        self.prompt_tokens += usage.get("prompt_tokens", 0)
        self.completion_tokens += usage.get("completion_tokens", 0)
        self.total_tokens += usage.get("total_tokens", 0)
        self.cost_usd += cost
        logger.info(
            "llm_call_completed",
            prompt_hash=self.prompt_hash(prompt),
            model=self.config.model,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
            latency_ms=latency_ms,
            cost_usd=cost,
        )
        content = response["choices"][0]["message"]["content"]
        if not isinstance(content, str):
            raise ValueError("LLM response did not contain text content")
        return content

    def usage_summary(self) -> dict[str, float | int]:
        """Return aggregate token and cost counters for this client."""
        return {
            "calls": self.calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": round(self.cost_usd, 6),
        }

    def _usage(self, response: Any) -> dict[str, int]:
        usage = getattr(response, "usage", None)
        if usage is None and isinstance(response, dict):
            usage = response.get("usage")
        if usage is None:
            return {}
        if hasattr(usage, "model_dump"):
            usage = usage.model_dump()
        return {
            "prompt_tokens": int(usage.get("prompt_tokens", 0)),
            "completion_tokens": int(usage.get("completion_tokens", 0)),
            "total_tokens": int(usage.get("total_tokens", 0)),
        }

    def _cost(self, litellm: Any, response: Any) -> float:
        try:
            return round(float(litellm.completion_cost(completion_response=response)), 6)
        except Exception:
            return 0.0

    def _extract_json(self, raw: str) -> dict[str, Any]:
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.startswith("json"):
                raw = raw[4:].strip()
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("Expected a JSON object from LLM response")
        return parsed

    def _cache_path(self, cache_key: str) -> Path | None:
        if not self.cache_dir or not self.config.cache_responses:
            return None
        return self.cache_dir / f"{cache_key}.json"

    def _read_cache(self, cache_key: str) -> dict[str, Any] | None:
        path = self._cache_path(cache_key)
        if path is None or not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_cache(self, cache_key: str, payload: dict[str, Any]) -> None:
        path = self._cache_path(cache_key)
        if path is None:
            return
        path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
