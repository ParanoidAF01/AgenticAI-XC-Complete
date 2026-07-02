"""
Authentication API endpoints.
POST /api/v1/auth/signup
POST /api/v1/auth/login
POST /api/v1/auth/refresh
POST /api/v1/auth/logout
GET  /api/v1/auth/me
"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import (
    create_access_token,
    hash_password,
    verify_password,
)
from app.core.config import get_settings
from app.api.dependencies import CurrentUser
from app.db.repositories.user_repository import (
    create_user,
    get_user_by_email,
    get_user_by_id,
)
from app.db.repositories.token_repository import (
    create_refresh_token,
    get_refresh_token,
    revoke_refresh_token,
    revoke_all_user_tokens,
)
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    SignupRequest,
    TokenResponse,
    UserResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def signup(body: SignupRequest, db: AsyncSession = Depends(get_db)):
    """Register a new user."""
    existing = await get_user_by_email(db, body.email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    user = await create_user(
        db,
        user_id=uuid.uuid4(),
        email=body.email,
        password_hash=hash_password(body.password),
        display_name=body.display_name or body.email.split("@")[0],
    )
    return UserResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        is_admin=user.is_admin,
        created_at=user.created_at,
    )


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Login and receive access + refresh tokens."""
    user = await get_user_by_email(db, body.email)
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    settings = get_settings()
    access_token = create_access_token(str(user.id), is_admin=user.is_admin)

    # Generate refresh token
    raw_refresh = secrets.token_hex(64)
    refresh_hash = hashlib.sha256(raw_refresh.encode()).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)

    await create_refresh_token(
        db,
        token_id=uuid.uuid4(),
        user_id=user.id,
        token_hash=refresh_hash,
        expires_at=expires_at,
    )

    return TokenResponse(
        access_token=access_token,
        refresh_token=raw_refresh,
        token_type="bearer",
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    """Rotate refresh token and issue a new access token."""
    incoming_hash = hashlib.sha256(body.refresh_token.encode()).hexdigest()
    token_record = await get_refresh_token(db, incoming_hash)

    if not token_record:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    if token_record.revoked:
        # Possible token reuse attack — revoke all tokens for this user
        await revoke_all_user_tokens(db, token_record.user_id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has been revoked (possible reuse detected)",
        )

    if token_record.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token expired",
        )

    # Revoke old token
    await revoke_refresh_token(db, token_record.id)

    # Get user for new token
    user = await get_user_by_id(db, token_record.user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    # Issue new tokens
    settings = get_settings()
    new_access = create_access_token(str(user.id), is_admin=user.is_admin)
    new_raw_refresh = secrets.token_hex(64)
    new_refresh_hash = hashlib.sha256(new_raw_refresh.encode()).hexdigest()
    new_expires = datetime.now(timezone.utc) + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)

    await create_refresh_token(
        db,
        token_id=uuid.uuid4(),
        user_id=user.id,
        token_hash=new_refresh_hash,
        expires_at=new_expires,
    )

    return TokenResponse(
        access_token=new_access,
        refresh_token=new_raw_refresh,
        token_type="bearer",
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    """Revoke the provided refresh token."""
    incoming_hash = hashlib.sha256(body.refresh_token.encode()).hexdigest()
    token_record = await get_refresh_token(db, incoming_hash)
    if token_record and not token_record.revoked:
        await revoke_refresh_token(db, token_record.id)
    return None


@router.get("/me", response_model=UserResponse)
async def me(current_user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """Get current user info."""
    user = await get_user_by_id(db, uuid.UUID(current_user["sub"]))
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return UserResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        is_admin=user.is_admin,
        created_at=user.created_at,
    )
