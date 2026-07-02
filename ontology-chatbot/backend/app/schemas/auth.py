"""Auth-related Pydantic v2 schemas."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, model_config


# ── Requests ─────────────────────────────────────────────────────

class SignupRequest(BaseModel):
    model_config = model_config  # Pydantic v2 style

    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    display_name: str | None = Field(None, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


# ── Responses ────────────────────────────────────────────────────

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    email: str
    display_name: str | None = None
    is_admin: bool = False
    created_at: datetime
