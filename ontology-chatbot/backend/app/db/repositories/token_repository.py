"""Refresh-token repository."""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy import select, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.refresh_token import RefreshToken
from ...core.config import get_settings


def _hash_token(raw_token: str) -> str:
    """SHA-256 hash a raw token for storage."""
    return hashlib.sha256(raw_token.encode()).hexdigest()


async def create_refresh_token(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    raw_token: str,
) -> RefreshToken:
    """Store a hashed refresh token."""
    settings = get_settings()
    rt = RefreshToken(
        id=uuid.uuid4(),
        user_id=user_id,
        token_hash=_hash_token(raw_token),
        expires_at=datetime.now(timezone.utc)
        + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS),
    )
    db.add(rt)
    await db.flush()
    await db.refresh(rt)
    return rt


async def get_refresh_token(
    db: AsyncSession,
    raw_token: str,
) -> Optional[RefreshToken]:
    """Look up a non-revoked, non-expired refresh token by its raw value."""
    hashed = _hash_token(raw_token)
    stmt = select(RefreshToken).where(
        RefreshToken.token_hash == hashed,
        RefreshToken.revoked == False,  # noqa: E712
        RefreshToken.expires_at > datetime.now(timezone.utc),
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def revoke_refresh_token(
    db: AsyncSession,
    raw_token: str,
) -> bool:
    """Revoke a single refresh token. Returns True if found."""
    hashed = _hash_token(raw_token)
    stmt = (
        sa_update(RefreshToken)
        .where(RefreshToken.token_hash == hashed)
        .values(revoked=True)
    )
    result = await db.execute(stmt)
    await db.flush()
    return result.rowcount > 0  # type: ignore[union-attr]


async def revoke_all_user_tokens(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> int:
    """Revoke every refresh token for *user_id*. Returns count revoked."""
    stmt = (
        sa_update(RefreshToken)
        .where(
            RefreshToken.user_id == user_id,
            RefreshToken.revoked == False,  # noqa: E712
        )
        .values(revoked=True)
    )
    result = await db.execute(stmt)
    await db.flush()
    return result.rowcount  # type: ignore[union-attr]
