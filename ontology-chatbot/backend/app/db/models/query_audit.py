"""QueryAudit ORM model."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ...core.database import Base, JSONVariant


class QueryAudit(Base):
    __tablename__ = "query_audits"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat_messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    profile: Mapped[str | None] = mapped_column(String(128), nullable=True)
    question: Mapped[str | None] = mapped_column(Text, nullable=True)
    route: Mapped[Dict[str, Any] | None] = mapped_column(JSONVariant, nullable=True)
    planner_json: Mapped[Dict[str, Any] | None] = mapped_column(JSONVariant, nullable=True)
    raw_sql: Mapped[Dict[str, Any] | None] = mapped_column(JSONVariant, nullable=True)
    final_sql: Mapped[Dict[str, Any] | None] = mapped_column(JSONVariant, nullable=True)
    validation_trace: Mapped[Dict[str, Any] | None] = mapped_column(JSONVariant, nullable=True)
    result_summary: Mapped[Dict[str, Any] | None] = mapped_column(JSONVariant, nullable=True)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )
