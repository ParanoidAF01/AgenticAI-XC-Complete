"""Message repository – reads enforce ownership via session join."""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.chat_message import ChatMessage
from ..models.chat_session import ChatSession


async def create_message(
    db: AsyncSession,
    *,
    message_id: uuid.UUID | None = None,
    session_id: uuid.UUID,
    role: str,
    content: str,
    metadata_: Dict[str, Any] | None = None,
) -> ChatMessage:
    """Insert a new chat message."""
    msg = ChatMessage(
        id=message_id or uuid.uuid4(),
        session_id=session_id,
        role=role,
        content=content,
        metadata_=metadata_,
    )
    db.add(msg)
    await db.flush()
    await db.refresh(msg)
    return msg


async def get_messages(
    db: AsyncSession,
    session_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    limit: int = 50,
    offset: int = 0,
) -> List[ChatMessage]:
    """Fetch messages for a session owned by *user_id*, oldest first."""
    stmt = (
        select(ChatMessage)
        .join(ChatSession, ChatMessage.session_id == ChatSession.id)
        .where(
            ChatMessage.session_id == session_id,
            ChatSession.user_id == user_id,
        )
        .order_by(ChatMessage.created_at.asc())
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_recent_messages(
    db: AsyncSession,
    session_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    limit: int = 10,
) -> List[ChatMessage]:
    """Return the last *limit* messages (for context window).

    Joins through chat_sessions to enforce ownership.
    Returns oldest-first within the window.
    """
    # Sub-select the latest N, then re-order ascending
    subq = (
        select(ChatMessage.id)
        .join(ChatSession, ChatMessage.session_id == ChatSession.id)
        .where(
            ChatMessage.session_id == session_id,
            ChatSession.user_id == user_id,
        )
        .order_by(ChatMessage.created_at.desc())
        .limit(limit)
        .subquery()
    )
    stmt = (
        select(ChatMessage)
        .where(ChatMessage.id.in_(select(subq)))
        .order_by(ChatMessage.created_at.asc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())
