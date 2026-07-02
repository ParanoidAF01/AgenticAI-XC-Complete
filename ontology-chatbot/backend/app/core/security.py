"""Password hashing, JWT helpers, and FastAPI auth dependency."""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

from .config import get_settings

_settings = get_settings()

# ── Password hashing ────────────────────────────────────────────
_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """Return a bcrypt hash of *password*."""
    return _pwd_ctx.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify *plain_password* against *hashed_password*."""
    return _pwd_ctx.verify(plain_password, hashed_password)


# ── JWT helpers ──────────────────────────────────────────────────

def create_access_token(user_id: UUID, is_admin: bool = False) -> str:
    """Create a JWT access token valid for 7 days."""
    now = datetime.now(timezone.utc)
    payload: Dict[str, Any] = {
        "sub": str(user_id),
        "is_admin": is_admin,
        "iat": now,
        "exp": now + timedelta(days=_settings.JWT_ACCESS_TOKEN_EXPIRE_DAYS),
        "type": "access",
    }
    return jwt.encode(payload, _settings.JWT_SECRET, algorithm=_settings.JWT_ALGORITHM)


def create_refresh_token() -> str:
    """Return a cryptographically random 64-byte hex string."""
    return secrets.token_hex(64)


def decode_access_token(token: str) -> Dict[str, Any]:
    """Decode and validate a JWT access token.

    Returns a dict with ``user_id`` (str) and ``is_admin`` (bool).
    Raises *HTTPException 401* on any failure.
    """
    try:
        payload = jwt.decode(
            token,
            _settings.JWT_SECRET,
            algorithms=[_settings.JWT_ALGORITHM],
        )
        user_id: str | None = payload.get("sub")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: missing subject",
            )
        return {
            "sub": user_id,
            "is_admin": payload.get("is_admin", False),
        }
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {exc}",
        )


# ── FastAPI dependency ───────────────────────────────────────────
_bearer_scheme = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
) -> Dict[str, Any]:
    """Extract the current user from the Authorization Bearer header.

    Returns ``{"user_id": "<uuid-str>", "is_admin": bool}``.
    """
    return decode_access_token(credentials.credentials)
