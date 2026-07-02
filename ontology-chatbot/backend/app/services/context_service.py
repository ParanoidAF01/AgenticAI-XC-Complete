"""Context service – builds the conversational context window."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..db.models.session_context_summary import SessionContextSummary
from ..db.repositories import message_repository
from .cache_service import RedisCacheService

logger = logging.getLogger(__name__)


class ContextService:
    """Retrieves recent messages + rolling summary for a session.

    Strategy:
    1. Try Redis for recent messages & summary.
    2. Fall back to PostgreSQL.
    3. Only returns data for the *current user's current session*.
    """

    def __init__(self, cache: RedisCacheService) -> None:
        self._cache = cache

    async def get_context(
        self,
        session_id: UUID,
        user_id: UUID,
        db: AsyncSession,
    ) -> Dict[str, Any]:
        """Return ``{"recent_messages": [...], "summary": str | None}``."""
        recent = await self._get_recent_messages(session_id, user_id, db)
        summary = await self._get_summary(session_id, db)
        return {
            "recent_messages": recent,
            "summary": summary,
        }

    # ── recent messages ──────────────────────────────────────────

    async def _get_recent_messages(
        self,
        session_id: UUID,
        user_id: UUID,
        db: AsyncSession,
    ) -> List[Dict[str, Any]]:
        # 1. Try cache
        cached = await self._cache.get_cached_recent_messages(session_id)
        if cached is not None:
            logger.debug("Cache HIT for recent_messages session=%s", session_id)
            return cached

        # 2. Fallback to DB (last 10, ownership enforced)
        logger.debug("Cache MISS for recent_messages session=%s", session_id)
        messages = await message_repository.get_recent_messages(
            db, session_id, user_id, limit=10
        )
        serialized = [
            {
                "id": str(m.id),
                "role": m.role,
                "content": m.content,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in messages
        ]
        # Populate cache
        await self._cache.cache_recent_messages(session_id, serialized)
        return serialized

    # ── summary ──────────────────────────────────────────────────

    async def _get_summary(
        self,
        session_id: UUID,
        db: AsyncSession,
    ) -> Optional[str]:
        # 1. Try cache
        cached = await self._cache.get_cached_summary(session_id)
        if cached is not None:
            return cached

        # 2. Fallback to DB
        stmt = (
            select(SessionContextSummary)
            .where(SessionContextSummary.session_id == session_id)
            .order_by(SessionContextSummary.updated_at.desc())
            .limit(1)
        )
        result = await db.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            return None

        await self._cache.cache_summary(session_id, row.summary)
        return row.summary

    # ── semantic retrieval stub (v1 – returns empty) ─────────────

    async def get_semantic_context(
        self,
        session_id: UUID,
        user_id: UUID,
        query: str,
        db: AsyncSession,
    ) -> List[Dict[str, Any]]:
        """Placeholder for future vector/embedding-based retrieval.

        Returns an empty list in v1.
        """
        return []
