"""Pydantic schemas for Power BI integration endpoints."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ReportContextFilter(BaseModel):
    """A single Power BI report filter (Phase 2)."""
    field: str
    values: list[str]


class PowerBIChatRequest(BaseModel):
    """Request body for the Power BI chat endpoint."""
    message: str = Field(..., min_length=1, max_length=10_000)
    session_id: str | None = None          # Auto-created if missing
    profile: str | None = None             # Falls back to POWERBI_DEFAULT_PROFILE
    report_context: list[ReportContextFilter] | None = None  # Phase 2


class PowerBIChatResponse(BaseModel):
    """Simplified response for the Power BI visual."""
    answer: str
    session_id: str
    has_error: bool = False
    sql: list[str] | None = None
    chart_config: Dict[str, Any] | None = None
    is_clarification: bool = False
