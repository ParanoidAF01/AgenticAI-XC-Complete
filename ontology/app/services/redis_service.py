"""Redis service — caching layer and conversation-history store.

Provides two implementations:

* **RedisService** — backed by a real Redis instance (``redis.asyncio``).
* **InMemoryCache** — drop-in fallback when Redis is unavailable.

Both expose the same public interface so the rest of the application is
agnostic to the backing store.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Redis-backed implementation
# ═══════════════════════════════════════════════════════════════════════════════


class RedisService:
    """Async Redis wrapper for query caching and conversation history."""

    def __init__(self, url: str = "redis://localhost:6379/0") -> None:
        """Create the async Redis client.

        The import is deferred so the module can be loaded even when the
        ``redis`` package is absent (the caller should catch and fall back to
        :class:`InMemoryCache`).
        """
        import redis.asyncio as aioredis

        self._client: aioredis.Redis = aioredis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=5,
        )
        self._url = url
        logger.info("RedisService initialised (url=%s)", url)

    # ── lifecycle ───────────────────────────────────────────────────────────

    async def close(self) -> None:
        """Close the underlying connection pool."""
        await self._client.close()
        logger.info("RedisService connection closed.")

    async def health_check(self) -> bool:
        """Return ``True`` when Redis responds to ``PING``."""
        try:
            return await self._client.ping()
        except Exception:
            logger.exception("Redis health check failed")
            return False

    # ── query-result caching ────────────────────────────────────────────────

    async def get_cached_result(
        self, sql_hash: str
    ) -> Optional[list[dict[str, Any]]]:
        """Retrieve a previously cached query result.

        Args:
            sql_hash: Deterministic hash of the SQL string.

        Returns:
            The cached list of row-dicts, or ``None`` on a cache miss.
        """
        key = f"sql_cache:{sql_hash}"
        try:
            raw = await self._client.get(key)
            if raw is not None:
                logger.debug("Cache HIT for %s", key)
                return json.loads(raw)
            logger.debug("Cache MISS for %s", key)
            return None
        except Exception:
            logger.exception("Error reading cache key %s", key)
            return None

    async def cache_result(
        self,
        sql_hash: str,
        result: list[dict[str, Any]],
        ttl: int = 300,
    ) -> None:
        """Store a query result in the cache with a TTL.

        Args:
            sql_hash: Deterministic hash of the SQL string.
            result: Rows to cache.
            ttl: Time-to-live in seconds (default 5 min).
        """
        key = f"sql_cache:{sql_hash}"
        try:
            await self._client.setex(
                key, ttl, json.dumps(result, default=str)
            )
            logger.debug("Cached %d row(s) under %s (ttl=%ds)", len(result), key, ttl)
        except Exception:
            logger.exception("Error writing cache key %s", key)

    # ── conversation history ────────────────────────────────────────────────

    async def save_conversation(
        self, session_id: str, message: dict[str, Any]
    ) -> None:
        """Append a message to the conversation list for *session_id*.

        Each message is stored as a JSON string in a Redis list.  The list
        is capped at 50 entries and expires after 24 hours.
        """
        key = f"conversation:{session_id}"
        try:
            payload = json.dumps(message, default=str)
            await self._client.rpush(key, payload)
            await self._client.ltrim(key, -50, -1)  # keep last 50
            await self._client.expire(key, 86_400)   # 24 h TTL
            logger.debug("Saved message to conversation %s", session_id)
        except Exception:
            logger.exception("Error saving conversation %s", session_id)

    async def get_conversation(
        self, session_id: str
    ) -> list[dict[str, Any]]:
        """Return the full conversation history for *session_id*.

        Returns:
            Ordered list of message dicts (oldest first).
        """
        key = f"conversation:{session_id}"
        try:
            raw_list = await self._client.lrange(key, 0, -1)
            return [json.loads(item) for item in raw_list]
        except Exception:
            logger.exception("Error reading conversation %s", session_id)
            return []

    # ── utilities ───────────────────────────────────────────────────────────

    @staticmethod
    def hash_sql(sql: str) -> str:
        """Produce a deterministic SHA-256 hex digest for a SQL string."""
        normalised = " ".join(sql.lower().split())
        return hashlib.sha256(normalised.encode()).hexdigest()


# ═══════════════════════════════════════════════════════════════════════════════
# In-memory fallback (no Redis required)
# ═══════════════════════════════════════════════════════════════════════════════


class InMemoryCache:
    """Simple in-process cache that mirrors the :class:`RedisService` API.

    Useful for local development or environments where Redis is not available.
    Data is lost when the process exits.
    """

    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, str]] = {}  # key -> (expires_at, json)
        self._conversations: dict[str, list[str]] = {}
        logger.info("InMemoryCache initialised (Redis unavailable)")

    async def close(self) -> None:  # noqa: D102
        self._cache.clear()
        self._conversations.clear()

    async def health_check(self) -> bool:  # noqa: D102
        return True

    # ── caching ─────────────────────────────────────────────────────────────

    async def get_cached_result(
        self, sql_hash: str
    ) -> Optional[list[dict[str, Any]]]:
        key = f"sql_cache:{sql_hash}"
        entry = self._cache.get(key)
        if entry is None:
            return None
        expires_at, raw = entry
        if time.time() > expires_at:
            del self._cache[key]
            return None
        return json.loads(raw)

    async def cache_result(
        self,
        sql_hash: str,
        result: list[dict[str, Any]],
        ttl: int = 300,
    ) -> None:
        key = f"sql_cache:{sql_hash}"
        self._cache[key] = (
            time.time() + ttl,
            json.dumps(result, default=str),
        )

    # ── conversations ───────────────────────────────────────────────────────

    async def save_conversation(
        self, session_id: str, message: dict[str, Any]
    ) -> None:
        key = f"conversation:{session_id}"
        self._conversations.setdefault(key, [])
        self._conversations[key].append(json.dumps(message, default=str))
        # Cap at 50
        self._conversations[key] = self._conversations[key][-50:]

    async def get_conversation(
        self, session_id: str
    ) -> list[dict[str, Any]]:
        key = f"conversation:{session_id}"
        return [json.loads(m) for m in self._conversations.get(key, [])]

    @staticmethod
    def hash_sql(sql: str) -> str:
        """Deterministic SHA-256 hex digest — same algorithm as :class:`RedisService`."""
        normalised = " ".join(sql.lower().split())
        return hashlib.sha256(normalised.encode()).hexdigest()


# ═══════════════════════════════════════════════════════════════════════════════
# Factory
# ═══════════════════════════════════════════════════════════════════════════════


async def create_cache_service(
    redis_url: str = "redis://localhost:6379/0",
) -> RedisService | InMemoryCache:
    """Try to connect to Redis; fall back to :class:`InMemoryCache` on failure.

    This factory is the recommended way to instantiate the caching layer at
    application startup.
    """
    try:
        service = RedisService(url=redis_url)
        if await service.health_check():
            logger.info("Redis is reachable — using RedisService")
            return service
        await service.close()
    except Exception:
        logger.warning("Redis unavailable — falling back to InMemoryCache")

    return InMemoryCache()
