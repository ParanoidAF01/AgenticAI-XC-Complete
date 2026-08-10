"""Chat-related Pydantic v2 schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ── Session ──────────────────────────────────────────────────────

class CreateSessionRequest(BaseModel):
    profile: str | None = None
    title: str | None = None


class UpdateSessionRequest(BaseModel):
    title: str | None = None
    is_archived: bool | None = None
    profile: str | None = None


class SessionResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    title: str | None = None
    profile: str | None
    is_archived: bool = False
    created_at: datetime
    updated_at: datetime


class SessionListResponse(BaseModel):
    sessions: List[SessionResponse]


# ── Messages ─────────────────────────────────────────────────────

class MessageRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=10_000)


class MessageResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    session_id: UUID
    role: str
    content: str
    metadata_: Dict[str, Any] | None = Field(None, alias="metadata_")
    created_at: datetime


# ── Orchestrator response ────────────────────────────────────────

class ChatResponse(BaseModel):
    """Full response returned by the query orchestrator."""
    message: MessageResponse
    route: Dict[str, Any] | None = None
    plan: Dict[str, Any] | None = None
    sql: List[Any] | None = None
    validation_trace: List[Any] | None = None
    results: Dict[str, Any] | None = None
    is_clarification: bool = False
    chart_config: Dict[str, Any] | None = None
