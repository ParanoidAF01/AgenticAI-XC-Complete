"""
Tests for authentication endpoints and security.
"""
from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.db.models.user import User


class TestPasswordHashing:
    """Test password hashing utilities."""

    def test_hash_password_returns_hash(self):
        hashed = hash_password("mypassword123")
        assert hashed != "mypassword123"
        assert len(hashed) > 20

    def test_verify_correct_password(self):
        hashed = hash_password("mypassword123")
        assert verify_password("mypassword123", hashed) is True

    def test_verify_wrong_password(self):
        hashed = hash_password("mypassword123")
        assert verify_password("wrongpassword", hashed) is False

    def test_different_passwords_different_hashes(self):
        h1 = hash_password("password1")
        h2 = hash_password("password2")
        assert h1 != h2

    def test_same_password_different_hashes(self):
        """bcrypt uses random salt, so same password produces different hashes."""
        h1 = hash_password("samepassword")
        h2 = hash_password("samepassword")
        assert h1 != h2
        assert verify_password("samepassword", h1) is True
        assert verify_password("samepassword", h2) is True


class TestJWTTokens:
    """Test JWT token creation and verification."""

    def test_create_access_token(self):
        user_id = str(uuid.uuid4())
        token = create_access_token(user_id, is_admin=False)
        assert isinstance(token, str)
        assert len(token) > 0

    def test_decode_valid_token(self):
        user_id = str(uuid.uuid4())
        token = create_access_token(user_id, is_admin=False)
        payload = decode_access_token(token)
        assert payload["sub"] == user_id
        assert payload["is_admin"] is False

    def test_decode_admin_token(self):
        user_id = str(uuid.uuid4())
        token = create_access_token(user_id, is_admin=True)
        payload = decode_access_token(token)
        assert payload["sub"] == user_id
        assert payload["is_admin"] is True

    def test_decode_invalid_token_raises(self):
        with pytest.raises(Exception):
            decode_access_token("invalid.token.here")

    def test_decode_empty_token_raises(self):
        with pytest.raises(Exception):
            decode_access_token("")

    def test_token_contains_expiry(self):
        user_id = str(uuid.uuid4())
        token = create_access_token(user_id, is_admin=False)
        payload = decode_access_token(token)
        assert "exp" in payload


class TestUserCRUD:
    """Test user creation and retrieval in database."""

    @pytest_asyncio.fixture
    async def created_user(self, db_session: AsyncSession) -> User:
        user = User(
            id=uuid.uuid4(),
            email=f"test_{uuid.uuid4().hex[:8]}@example.com",
            password_hash=hash_password("testpassword"),
            display_name="Test User",
            is_admin=False,
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)
        return user

    @pytest.mark.asyncio
    async def test_create_user(self, db_session: AsyncSession):
        user = User(
            id=uuid.uuid4(),
            email=f"new_{uuid.uuid4().hex[:8]}@example.com",
            password_hash=hash_password("password123"),
            display_name="New User",
        )
        db_session.add(user)
        await db_session.commit()

        result = await db_session.execute(select(User).where(User.id == user.id))
        fetched = result.scalar_one_or_none()
        assert fetched is not None
        assert fetched.email == user.email

    @pytest.mark.asyncio
    async def test_user_email_unique(self, db_session: AsyncSession, created_user: User):
        duplicate = User(
            id=uuid.uuid4(),
            email=created_user.email,  # Same email
            password_hash=hash_password("other"),
            display_name="Duplicate",
        )
        db_session.add(duplicate)
        with pytest.raises(Exception):
            await db_session.commit()
