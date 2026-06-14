"""LLM service — thin async wrapper around the OpenAI Chat Completions API.

Provides purpose-built helpers for the pipeline stages (intent classification,
entity extraction, SQL generation, response formatting) while exposing generic
``chat`` / ``chat_json`` methods for ad-hoc use.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


class LLMService:
    """Async OpenAI Chat Completions client tailored for the ontology chatbot."""

    def __init__(self, api_key: str, model: str = "gpt-4o") -> None:
        """Initialise the async OpenAI client.

        Args:
            api_key: OpenAI API key.
            model: Model identifier (e.g. ``gpt-4o``, ``gpt-4o-mini``).
        """
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model
        logger.info("LLMService initialised (model=%s)", model)

    # ── generic helpers ─────────────────────────────────────────────────────

    async def chat(
        self,
        system_prompt: str,
        user_message: str,
        *,
        temperature: float = 0.0,
    ) -> str:
        """Send a plain chat completion and return the assistant text.

        Args:
            system_prompt: System-role instructions.
            user_message: User-role content.
            temperature: Sampling temperature (default deterministic).

        Returns:
            The assistant's response text.
        """
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                temperature=temperature,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
            )
            content = response.choices[0].message.content or ""
            logger.debug(
                "chat completion tokens: prompt=%s, completion=%s",
                response.usage.prompt_tokens if response.usage else "?",
                response.usage.completion_tokens if response.usage else "?",
            )
            return content.strip()
        except Exception:
            logger.exception("chat() call failed")
            raise

    async def chat_json(
        self,
        system_prompt: str,
        user_message: str,
        *,
        temperature: float = 0.0,
    ) -> dict[str, Any]:
        """Chat completion that forces a JSON response.

        The model is asked to reply with valid JSON via
        ``response_format={"type": "json_object"}``.  The raw text is parsed
        and returned as a Python dict.

        Raises:
            ValueError: If the model returns invalid JSON.
        """
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                temperature=temperature,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
            )
            raw = response.choices[0].message.content or "{}"
            logger.debug(
                "chat_json tokens: prompt=%s, completion=%s",
                response.usage.prompt_tokens if response.usage else "?",
                response.usage.completion_tokens if response.usage else "?",
            )
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.error("Model returned invalid JSON: %s", exc)
            raise ValueError(f"Invalid JSON from model: {exc}") from exc
        except Exception:
            logger.exception("chat_json() call failed")
            raise

    # ── pipeline-specific helpers ───────────────────────────────────────────

    async def generate_sql(
        self,
        system_prompt: str,
        schema_context: dict[str, Any],
        question: str,
        intent: str,
        entities: dict[str, Any],
    ) -> str:
        """Generate a SQL query using the provided schema context.

        The *schema_context*, *intent*, and *entities* are serialised into
        the user message so the model has everything it needs.

        Returns:
            The extracted SQL string (fences removed).
        """
        user_payload = (
            f"## Question\n{question}\n\n"
            f"## Intent\n{intent}\n\n"
            f"## Extracted Entities\n{json.dumps(entities, indent=2)}\n\n"
            f"## Schema Context\n{json.dumps(schema_context, indent=2, default=str)}"
        )

        raw = await self.chat(
            system_prompt=system_prompt,
            user_message=user_payload,
            temperature=0.0,
        )

        # Strip markdown SQL fences if present
        sql = self._extract_sql(raw)
        logger.info("Generated SQL (%d chars)", len(sql))
        return sql

    async def format_response(
        self,
        question: str,
        sql: str,
        results: list[dict[str, Any]],
        entities: dict[str, Any],
    ) -> str:
        """Format raw SQL results into a human-readable natural-language answer.

        Args:
            question: The original user question.
            sql: The SQL that was executed.
            results: Rows returned by the database.
            entities: Entities extracted earlier in the pipeline.

        Returns:
            A polished, conversational answer string.
        """
        from app.prompts.response_prompt import RESPONSE_GENERATION_PROMPT

        user_payload = (
            f"## Original Question\n{question}\n\n"
            f"## SQL Executed\n```sql\n{sql}\n```\n\n"
            f"## Query Results\n{json.dumps(results[:50], indent=2, default=str)}\n\n"
            f"## Entities\n{json.dumps(entities, indent=2, default=str)}"
        )

        answer = await self.chat(
            system_prompt=RESPONSE_GENERATION_PROMPT,
            user_message=user_payload,
            temperature=0.2,
        )
        return answer

    # ── internal utilities ──────────────────────────────────────────────────

    @staticmethod
    def _extract_sql(raw: str) -> str:
        """Remove markdown ```sql ... ``` fences and return the inner SQL."""
        pattern = r"```sql\s*(.*?)\s*```"
        match = re.search(pattern, raw, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
        # Fallback: strip any generic fences
        cleaned = re.sub(r"```\w*\s*", "", raw)
        cleaned = cleaned.replace("```", "").strip()
        return cleaned
