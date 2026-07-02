"""
Tests for session/message ownership enforcement.
Ensures that one user cannot access another user's data.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.db.models.chat_message import ChatMessage
from app.db.models.chat_session import ChatSession
from app.db.models.query_audit import QueryAudit
from app.db.models.user import User


@pytest_asyncio.fixture
async def user_a(db_session: AsyncSession) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"user_a_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("passwordA"),
        display_name="User A",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def user_b(db_session: AsyncSession) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"user_b_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("passwordB"),
        display_name="User B",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def session_of_a(db_session: AsyncSession, user_a: User) -> ChatSession:
    session = ChatSession(
        id=uuid.uuid4(),
        user_id=user_a.id,
        title="User A's Chat",
        profile="idp_reporting",
    )
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)
    return session


@pytest_asyncio.fixture
async def message_of_a(db_session: AsyncSession, session_of_a: ChatSession) -> ChatMessage:
    msg = ChatMessage(
        id=uuid.uuid4(),
        session_id=session_of_a.id,
        role="user",
        content="Hello from user A",
    )
    db_session.add(msg)
    await db_session.commit()
    await db_session.refresh(msg)
    return msg


@pytest_asyncio.fixture
async def audit_of_a(db_session: AsyncSession, user_a: User, session_of_a: ChatSession) -> QueryAudit:
    audit = QueryAudit(
        id=uuid.uuid4(),
        user_id=user_a.id,
        session_id=session_of_a.id,
        profile="idp_reporting",
        question="How many policies?",
        answer="There are 100 policies.",
        duration_ms=500,
    )
    db_session.add(audit)
    await db_session.commit()
    await db_session.refresh(audit)
    return audit


class TestSessionOwnership:
    """Verify sessions are scoped to their owner."""

    @pytest.mark.asyncio
    async def test_session_belongs_to_user_a(self, session_of_a: ChatSession, user_a: User):
        assert session_of_a.user_id == user_a.id

    @pytest.mark.asyncio
    async def test_query_session_with_wrong_user_returns_none(
        self,
        db_session: AsyncSession,
        session_of_a: ChatSession,
        user_b: User,
    ):
        from sqlalchemy import select

        result = await db_session.execute(
            select(ChatSession).where(
                ChatSession.id == session_of_a.id,
                ChatSession.user_id == user_b.id,  # Wrong user
            )
        )
        found = result.scalar_one_or_none()
        assert found is None, "User B should NOT be able to access User A's session"

    @pytest.mark.asyncio
    async def test_query_session_with_correct_user_succeeds(
        self,
        db_session: AsyncSession,
        session_of_a: ChatSession,
        user_a: User,
    ):
        from sqlalchemy import select

        result = await db_session.execute(
            select(ChatSession).where(
                ChatSession.id == session_of_a.id,
                ChatSession.user_id == user_a.id,
            )
        )
        found = result.scalar_one_or_none()
        assert found is not None
        assert found.id == session_of_a.id


class TestMessageOwnership:
    """Verify messages can only be accessed through owned sessions."""

    @pytest.mark.asyncio
    async def test_message_via_owned_session(
        self,
        db_session: AsyncSession,
        message_of_a: ChatMessage,
        session_of_a: ChatSession,
        user_a: User,
    ):
        from sqlalchemy import select

        # Query messages through session ownership check
        result = await db_session.execute(
            select(ChatMessage)
            .join(ChatSession, ChatMessage.session_id == ChatSession.id)
            .where(
                ChatMessage.session_id == session_of_a.id,
                ChatSession.user_id == user_a.id,
            )
        )
        messages = result.scalars().all()
        assert len(messages) == 1
        assert messages[0].content == "Hello from user A"

    @pytest.mark.asyncio
    async def test_message_via_wrong_user_returns_empty(
        self,
        db_session: AsyncSession,
        message_of_a: ChatMessage,
        session_of_a: ChatSession,
        user_b: User,
    ):
        from sqlalchemy import select

        result = await db_session.execute(
            select(ChatMessage)
            .join(ChatSession, ChatMessage.session_id == ChatSession.id)
            .where(
                ChatMessage.session_id == session_of_a.id,
                ChatSession.user_id == user_b.id,  # Wrong user
            )
        )
        messages = result.scalars().all()
        assert len(messages) == 0, "User B should NOT see User A's messages"


class TestAuditOwnership:
    """Verify query audits are scoped to their owner."""

    @pytest.mark.asyncio
    async def test_audit_belongs_to_user_a(
        self,
        db_session: AsyncSession,
        audit_of_a: QueryAudit,
        user_a: User,
    ):
        from sqlalchemy import select

        result = await db_session.execute(
            select(QueryAudit).where(
                QueryAudit.user_id == user_a.id,
            )
        )
        audits = result.scalars().all()
        assert len(audits) >= 1
        assert any(a.id == audit_of_a.id for a in audits)

    @pytest.mark.asyncio
    async def test_audit_not_visible_to_user_b(
        self,
        db_session: AsyncSession,
        audit_of_a: QueryAudit,
        user_b: User,
    ):
        from sqlalchemy import select

        result = await db_session.execute(
            select(QueryAudit).where(
                QueryAudit.user_id == user_b.id,
            )
        )
        audits = result.scalars().all()
        assert all(a.id != audit_of_a.id for a in audits), "User B should NOT see User A's audits"
