"""User repository – async CRUD helpers."""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.user import User


async def create_user(
    db: AsyncSession,
    *,
    email: str,
    password_hash: str,
    display_name: str | None = None,
    is_admin: bool = False,
) -> User:
    """Insert a new user and return the ORM instance."""
    user = User(
        id=uuid.uuid4(),
        email=email,
        password_hash=password_hash,
        display_name=display_name,
        is_admin=is_admin,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


async def get_user_by_email(db: AsyncSession, email: str) -> Optional[User]:
    """Fetch a single user by email (case-insensitive)."""
    stmt = select(User).where(User.email == email.lower())
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_user_by_id(db: AsyncSession, user_id: uuid.UUID) -> Optional[User]:
    """Fetch a single user by primary key."""
    stmt = select(User).where(User.id == user_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()
