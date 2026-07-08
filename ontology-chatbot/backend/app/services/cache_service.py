"""Redis cache service – all operations are fire-and-forget safe."""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

# ── TTLs (seconds) ──────────────────────────────────────────────
TTL_RECENT_MESSAGES = 300   # 5 min
TTL_SUMMARY = 600           # 10 min
TTL_ONTOLOGY = 3600         # 1 h
TTL_SCHEMA = 1800           # 30 min
TTL_QUERY = 900             # 15 min


class RedisCacheService:
    """Thin async wrapper around redis.asyncio with JSON ser/de.

    Every public method is wrapped so that a Redis failure is logged
    but **never** propagated to the caller.
    """

    def __init__(self, redis_client: aioredis.Redis) -> None:
        self._r = redis_client

    # ── low-level helpers ────────────────────────────────────────

    async def _get(self, key: str) -> Optional[Any]:
        try:
            raw = await self._r.get(key)
            if raw is None:
                return None
            return json.loads(raw)
        except Exception:
            logger.exception("Redis GET failed for key=%s", key)
            return None

    async def _set(self, key: str, value: Any, ttl: int) -> None:
        try:
            await self._r.set(key, json.dumps(value, default=str), ex=ttl)
        except Exception:
            logger.exception("Redis SET failed for key=%s", key)

    async def _delete(self, key: str) -> None:
        try:
            await self._r.delete(key)
        except Exception:
            logger.exception("Redis DELETE failed for key=%s", key)

    # ── recent messages ──────────────────────────────────────────

    def _recent_key(self, session_id: UUID) -> str:
        return f"chat:{session_id}:recent_messages"

    async def cache_recent_messages(
        self, session_id: UUID, messages: List[Dict[str, Any]]
    ) -> None:
        await self._set(self._recent_key(session_id), messages, TTL_RECENT_MESSAGES)

    async def get_cached_recent_messages(
        self, session_id: UUID
    ) -> Optional[List[Dict[str, Any]]]:
        return await self._get(self._recent_key(session_id))

    # ── session summary ──────────────────────────────────────────

    def _summary_key(self, session_id: UUID) -> str:
        return f"chat:{session_id}:summary"

    async def cache_summary(self, session_id: UUID, summary: str) -> None:
        await self._set(self._summary_key(session_id), summary, TTL_SUMMARY)

    async def get_cached_summary(self, session_id: UUID) -> Optional[str]:
        return await self._get(self._summary_key(session_id))

    # ── ontology data ────────────────────────────────────────────

    async def cache_ontology_data(
        self,
        profile: str,
        kind: str,  # 'entities' | 'metrics' | 'relationships'
        data: Any,
    ) -> None:
        key = f"ontology:{profile}:{kind}"
        await self._set(key, data, TTL_ONTOLOGY)

    async def get_cached_ontology_data(
        self, profile: str, kind: str
    ) -> Optional[Any]:
        key = f"ontology:{profile}:{kind}"
        return await self._get(key)

    # ── schema cache ─────────────────────────────────────────────

    async def cache_schema(self, profile: str, columns: Any) -> None:
        key = f"schema:{profile}:columns"
        await self._set(key, columns, TTL_SCHEMA)

    async def get_cached_schema(self, profile: str) -> Optional[Any]:
        key = f"schema:{profile}:columns"
        return await self._get(key)

    # ── query result cache ───────────────────────────────────────

    @staticmethod
    def _question_hash(question: str) -> str:
        return hashlib.sha256(question.strip().lower().encode()).hexdigest()[:16]

    async def cache_query_result(
        self,
        user_id: UUID,
        profile: str,
        question: str,
        result: Dict[str, Any],
    ) -> None:
        qh = self._question_hash(question)
        key = f"query:{user_id}:{profile}:{qh}"
        await self._set(key, result, TTL_QUERY)

    async def get_cached_query_result(
        self,
        user_id: UUID,
        profile: str,
        question: str,
    ) -> Optional[Dict[str, Any]]:
        qh = self._question_hash(question)
        key = f"query:{user_id}:{profile}:{qh}"
        return await self._get(key)

    # ── invalidation helpers ─────────────────────────────────────

    async def invalidate_session_cache(self, session_id: UUID) -> None:
        """Drop all cached data for a session."""
        await self._delete(self._recent_key(session_id))
        await self._delete(self._summary_key(session_id))

    # ── OTP & Signup ─────────────────────────────────────────────

    async def set_signup_data(self, email: str, data: Dict[str, Any], otp: str) -> None:
        """Store pending signup data and expected OTP (10 min TTL)."""
        await self._set(f"signup:data:{email}", data, 600)
        await self._set(f"signup:otp:{email}", otp, 600)
        
    async def get_signup_data(self, email: str) -> Optional[Dict[str, Any]]:
        return await self._get(f"signup:data:{email}")
        
    async def get_signup_otp(self, email: str) -> Optional[str]:
        return await self._get(f"signup:otp:{email}")
        
    async def clear_signup_data(self, email: str) -> None:
        await self._delete(f"signup:data:{email}")
        await self._delete(f"signup:otp:{email}")

    async def set_reset_otp(self, email: str, otp: str) -> None:
        """Store password reset OTP (10 min TTL)."""
        await self._set(f"reset:otp:{email}", otp, 600)
        
    async def get_reset_otp(self, email: str) -> Optional[str]:
        return await self._get(f"reset:otp:{email}")
        
    async def clear_reset_otp(self, email: str) -> None:
        await self._delete(f"reset:otp:{email}")
        
    async def set_reset_token(self, token: str, email: str) -> None:
        """Store short-lived token mapping to email (15 min TTL)."""
        await self._set(f"reset:token:{token}", email, 900)

    async def get_reset_email_by_token(self, token: str) -> Optional[str]:
        return await self._get(f"reset:token:{token}")
        
    async def clear_reset_token(self, token: str) -> None:
        await self._delete(f"reset:token:{token}")

