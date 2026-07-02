"""Audit repository – query pipeline audit trail."""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.query_audit import QueryAudit
from ..models.chat_session import ChatSession


async def create_audit(
    db: AsyncSession,
    *,
    audit_id: uuid.UUID | None = None,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    message_id: uuid.UUID | None = None,
    profile: str | None = None,
    question: str | None = None,
    route: Dict[str, Any] | None = None,
    planner_json: Dict[str, Any] | None = None,
    raw_sql: Dict[str, Any] | None = None,
    final_sql: Dict[str, Any] | None = None,
    validation_trace: Dict[str, Any] | None = None,
    result_summary: Dict[str, Any] | None = None,
    answer: str | None = None,
    duration_ms: int | None = None,
    error: str | None = None,
) -> QueryAudit:
    """Persist a full audit record for one query pipeline execution."""
    audit = QueryAudit(
        id=audit_id or uuid.uuid4(),
        user_id=user_id,
        session_id=session_id,
        message_id=message_id,
        profile=profile,
        question=question,
        route=route,
        planner_json=planner_json,
        raw_sql=raw_sql,
        final_sql=final_sql,
        validation_trace=validation_trace,
        result_summary=result_summary,
        answer=answer,
        duration_ms=duration_ms,
        error=error,
    )
    db.add(audit)
    await db.flush()
    await db.refresh(audit)
    return audit


async def get_audits(
    db: AsyncSession,
    session_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    limit: int = 50,
) -> List[QueryAudit]:
    """Fetch audit records for a session owned by *user_id*."""
    stmt = (
        select(QueryAudit)
        .join(ChatSession, QueryAudit.session_id == ChatSession.id)
        .where(
            QueryAudit.session_id == session_id,
            ChatSession.user_id == user_id,
        )
        .order_by(QueryAudit.created_at.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())
