"""
Authentication API endpoints.
POST /api/v1/auth/signup/request
POST /api/v1/auth/signup/verify
POST /api/v1/auth/login
POST /api/v1/auth/refresh
POST /api/v1/auth/logout
POST /api/v1/auth/forgot-password
POST /api/v1/auth/verify-reset-otp
POST /api/v1/auth/reset-password
POST /api/v1/auth/change-password
GET  /api/v1/auth/me
PATCH /api/v1/auth/me
DELETE /api/v1/auth/me
"""
from __future__ import annotations

import hashlib
import random
import secrets
import string
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status, Request
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
    update_user,
    delete_user,
)
from app.db.repositories.token_repository import (
    create_refresh_token,
    get_refresh_token,
    revoke_refresh_token,
    revoke_all_user_tokens,
)
from app.db.repositories.session_repository import delete_empty_sessions
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    SignupRequest,
    SignupVerifyRequest,
    ForgotPasswordRequest,
    VerifyOtpRequest,
    ResetPasswordRequest,
    ChangePasswordRequest,
    UpdateProfileRequest,
    TokenResponse,
    UserResponse,
)
from app.services.email_service import send_signup_otp_email, send_password_reset_otp_email

router = APIRouter(prefix="/auth", tags=["auth"])


def generate_otp() -> str:
    return "".join(random.choices(string.digits, k=6))


@router.post("/signup/request", status_code=status.HTTP_202_ACCEPTED)
async def signup_request(body: SignupRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """Request signup and generate OTP."""
    existing = await get_user_by_email(db, body.email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )
        
    cache = request.app.state.cache_service
    otp = generate_otp()
    
    signup_data = {
        "email": body.email,
        "password": body.password,
        "display_name": body.display_name
    }
    
    await cache.set_signup_data(body.email, signup_data, otp)
    await send_signup_otp_email(body.email, otp, body.display_name)
    
    return {"message": "OTP sent to email."}


@router.post("/signup/verify", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def signup_verify(body: SignupVerifyRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """Verify OTP and create user."""
    cache = request.app.state.cache_service
    stored_otp = await cache.get_signup_otp(body.email)
    
    if not stored_otp:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This verification code has expired. Request a new code.")
        
    if stored_otp != body.otp:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="The verification code is incorrect. Please try again.")
        
    signup_data = await cache.get_signup_data(body.email)
    if not signup_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Signup session expired.")
        
    existing = await get_user_by_email(db, body.email)
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered.")
        
    user = await create_user(
        db,
        email=signup_data["email"],
        password_hash=hash_password(signup_data["password"]),
        display_name=signup_data["display_name"] or signup_data["email"].split("@")[0],
    )
    
    await cache.clear_signup_data(body.email)
    
    return UserResponse.model_validate(user)


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Login and receive access + refresh tokens."""
    user = await get_user_by_email(db, body.email)
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    settings = get_settings()
    access_token = create_access_token(user.id, is_admin=user.is_admin)

    raw_refresh = secrets.token_hex(64)
    await create_refresh_token(db, user_id=user.id, raw_token=raw_refresh)

    return TokenResponse(access_token=access_token, refresh_token=raw_refresh, token_type="bearer")


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    """Rotate refresh token and issue a new access token."""
    token_record = await get_refresh_token(db, body.refresh_token)

    if not token_record:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    if token_record.revoked:
        await revoke_all_user_tokens(db, token_record.user_id)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token has been revoked")

    if token_record.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token expired")

    await revoke_refresh_token(db, body.refresh_token)

    user = await get_user_by_id(db, token_record.user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    settings = get_settings()
    new_access = create_access_token(user.id, is_admin=user.is_admin)
    new_raw_refresh = secrets.token_hex(64)

    await create_refresh_token(db, user_id=user.id, raw_token=new_raw_refresh)

    return TokenResponse(access_token=new_access, refresh_token=new_raw_refresh, token_type="bearer")


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    """Revoke the provided refresh token and cleanup empty sessions."""
    token_record = await get_refresh_token(db, body.refresh_token)
    if token_record:
        if not token_record.revoked:
            await revoke_refresh_token(db, body.refresh_token)
        # Clean up empty sessions when the user explicitly logs out
        await delete_empty_sessions(db, token_record.user_id)
    return None


@router.post("/forgot-password", status_code=status.HTTP_202_ACCEPTED)
async def forgot_password(body: ForgotPasswordRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """Request password reset OTP."""
    user = await get_user_by_email(db, body.email)
    if user:
        cache = request.app.state.cache_service
        otp = generate_otp()
        await cache.set_reset_otp(body.email, otp)
        await send_password_reset_otp_email(body.email, otp, user.display_name)
    return {"message": "If that email exists, we have sent a reset code."}


@router.post("/verify-reset-otp")
async def verify_reset_otp(body: VerifyOtpRequest, request: Request):
    """Verify reset OTP and return short-lived reset token."""
    cache = request.app.state.cache_service
    stored_otp = await cache.get_reset_otp(body.email)
    
    if not stored_otp:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This verification code has expired. Request a new code.")
        
    if stored_otp != body.otp:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="The verification code is incorrect. Please try again.")
        
    reset_token = secrets.token_urlsafe(32)
    await cache.set_reset_token(reset_token, body.email)
    await cache.clear_reset_otp(body.email)
    
    return {"reset_token": reset_token}


@router.post("/reset-password", status_code=status.HTTP_200_OK)
async def reset_password(body: ResetPasswordRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """Reset password using reset token."""
    cache = request.app.state.cache_service
    email = await cache.get_reset_email_by_token(body.reset_token)
    
    if not email:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired reset token.")
        
    user = await get_user_by_email(db, email)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
        
    user.password_hash = hash_password(body.new_password)
    await update_user(db, user)
    
    await cache.clear_reset_token(body.reset_token)
    return {"message": "Password updated successfully."}


@router.post("/change-password", status_code=status.HTTP_200_OK)
async def change_password(body: ChangePasswordRequest, current_user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """Change password (requires authentication)."""
    user = await get_user_by_id(db, uuid.UUID(current_user["sub"]))
    if not user or not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid current password.")
        
    user.password_hash = hash_password(body.new_password)
    await update_user(db, user)
    return {"message": "Password updated successfully."}


@router.get("/me", response_model=UserResponse)
async def me(current_user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """Get current user info."""
    user = await get_user_by_id(db, uuid.UUID(current_user["sub"]))
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return UserResponse.model_validate(user)


@router.patch("/me", response_model=UserResponse)
async def update_profile(body: UpdateProfileRequest, current_user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """Update current user profile."""
    user = await get_user_by_id(db, uuid.UUID(current_user["sub"]))
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        
    if body.display_name is not None:
        user.display_name = body.display_name
        
    await update_user(db, user)
    return UserResponse.model_validate(user)


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(current_user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """Delete current user account."""
    user = await get_user_by_id(db, uuid.UUID(current_user["sub"]))
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        
    await delete_user(db, user)
    return None
