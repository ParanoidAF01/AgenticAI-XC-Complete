"""Session repository – all queries enforce user_id ownership."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import select, update as sa_update, delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.chat_session import ChatSession


async def create_session(
    db: AsyncSession,
    *,
    session_id: uuid.UUID | None = None,
    user_id: uuid.UUID,
    profile: str,
    title: str | None = None,
) -> ChatSession:
    """Create a new chat session for the given user."""
    session = ChatSession(
        id=session_id or uuid.uuid4(),
        user_id=user_id,
        profile=profile,
        title=title,
    )
    db.add(session)
    await db.flush()
    await db.refresh(session)
    return session


async def get_session(
    db: AsyncSession,
    session_id: uuid.UUID,
    user_id: uuid.UUID,
) -> Optional[ChatSession]:
    """Fetch a single session owned by *user_id*."""
    stmt = select(ChatSession).where(
        ChatSession.id == session_id,
        ChatSession.user_id == user_id,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def list_sessions(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    include_archived: bool = False,
) -> List[ChatSession]:
    """Return all sessions for *user_id*, newest first."""
    stmt = select(ChatSession).where(ChatSession.user_id == user_id)
    if not include_archived:
        stmt = stmt.where(ChatSession.is_archived == False)  # noqa: E712
    stmt = stmt.order_by(ChatSession.updated_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def update_session(
    db: AsyncSession,
    session_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    title: str | None = None,
    is_archived: bool | None = None,
) -> Optional[ChatSession]:
    """Update mutable session fields. Returns the updated session or None."""
    values: dict = {"updated_at": datetime.now(timezone.utc)}
    if title is not None:
        values["title"] = title
    if is_archived is not None:
        values["is_archived"] = is_archived

    stmt = (
        sa_update(ChatSession)
        .where(ChatSession.id == session_id, ChatSession.user_id == user_id)
        .values(**values)
        .returning(ChatSession)
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row:
        await db.flush()
    return row


async def delete_session(
    db: AsyncSession,
    session_id: uuid.UUID,
    user_id: uuid.UUID,
) -> bool:
    """Hard-delete a session owned by *user_id*. Returns True if deleted."""
    stmt = sa_delete(ChatSession).where(
        ChatSession.id == session_id,
        ChatSession.user_id == user_id,
    )
    result = await db.execute(stmt)
    await db.flush()
    return result.rowcount > 0  # type: ignore[union-attr]
