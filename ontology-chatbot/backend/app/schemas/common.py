"""Shared / common Pydantic v2 schemas."""
from __future__ import annotations

from typing import List

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "1.0.0"


class ProfileResponse(BaseModel):
    name: str
    display_name: str
    description: str


class ProfileListResponse(BaseModel):
    profiles: List[ProfileResponse]


class ErrorResponse(BaseModel):
    detail: str
