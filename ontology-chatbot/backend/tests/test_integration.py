"""
Integration test for the POST message flow.
Uses mocked LLM, Neo4j, and MSSQL to test the full orchestration pipeline.
"""
from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.db.models.chat_message import ChatMessage
from app.db.models.chat_session import ChatSession
from app.db.models.user import User


@pytest_asyncio.fixture
async def integration_user(db_session: AsyncSession) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"integration_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("integrationpass"),
        display_name="Integration Tester",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def integration_session(db_session: AsyncSession, integration_user: User) -> ChatSession:
    session = ChatSession(
        id=uuid.uuid4(),
        user_id=integration_user.id,
        title="Integration Test Chat",
        profile="idp_reporting",
    )
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)
    return session


class TestPostMessageIntegration:
    """Integration test for the full message processing pipeline."""

    @pytest.mark.asyncio
    async def test_general_chat_flow(
        self,
        db_session: AsyncSession,
        integration_user: User,
        integration_session: ChatSession,
    ):
        """Test a general chat message (greeting) flows through the pipeline."""
        from app.services.query_orchestrator import QueryOrchestrator

        mock_cache = AsyncMock()
        mock_cache.get_cached_recent_messages.return_value = None
        mock_cache.get_cached_summary.return_value = None
        mock_cache.get_cached_query_result.return_value = None

        mock_neo4j = MagicMock()
        mock_profile_manager = MagicMock()

        orchestrator = QueryOrchestrator(
            cache_service=mock_cache,
            neo4j_repo=mock_neo4j,
            profile_manager=mock_profile_manager,
        )

        # Mock the LLM call for general chat
        with patch("app.services.query_orchestrator.route_question") as mock_route:
            mock_route.return_value = {"route": "general_chat", "reason": "greeting"}

            with patch("app.services.query_orchestrator.build_general_llm_answer") as mock_answer:
                mock_answer.return_value = "Hello! How can I help you with your insurance data?"

                response = await orchestrator.process_chat_message(
                    user_id=str(integration_user.id),
                    session_id=str(integration_session.id),
                    message="Hello!",
                    db=db_session,
                )

                assert response is not None
                assert response.message.role == "assistant"
                assert "Hello" in response.message.content or "help" in response.message.content.lower()

    @pytest.mark.asyncio
    async def test_session_ownership_enforced_in_orchestrator(
        self,
        db_session: AsyncSession,
        integration_user: User,
        integration_session: ChatSession,
    ):
        """Test that processing a message with wrong user ID fails."""
        from app.services.query_orchestrator import QueryOrchestrator

        mock_cache = AsyncMock()
        mock_cache.get_cached_recent_messages.return_value = None
        mock_cache.get_cached_summary.return_value = None

        mock_neo4j = MagicMock()
        mock_profile_manager = MagicMock()

        orchestrator = QueryOrchestrator(
            cache_service=mock_cache,
            neo4j_repo=mock_neo4j,
            profile_manager=mock_profile_manager,
        )

        wrong_user_id = str(uuid.uuid4())

        with pytest.raises(Exception):  # Should raise permission/not-found error
            await orchestrator.process_chat_message(
                user_id=wrong_user_id,
                session_id=str(integration_session.id),
                message="Hello!",
                db=db_session,
            )


class TestPlannerValidation:
    """Test plan validation preserves legacy behavior."""

    def test_valid_plan_structure(self):
        """Verify the plan validator accepts a well-formed plan."""
        from app.query_engine.plan_validator import validate_plan

        plan = {
            "question_type": "scalar_aggregate",
            "user_question": "How many policies?",
            "database_profile": "idp_reporting",
            "intent": "count",
            "requires_multi_task": False,
            "tasks": [
                {
                    "task_id": "t1",
                    "task_type": "aggregate",
                    "target_entity": "POLICY",
                    "fact_entity": "POLICY",
                    "metric_name": "policy_count",
                    "selected_properties": [],
                    "date_property": None,
                    "filters": [],
                    "path_candidates": [],
                    "chosen_path": [],
                    "result_limit": 25,
                    "sort": {"field": "metric_value", "direction": "desc"},
                }
            ],
            "combine_strategy": "none",
            "comparison_dimension": None,
            "confidence": 0.95,
            "needs_clarification": False,
            "clarification_reason": "",
            "notes": [],
        }

        mock_repo = MagicMock()
        mock_repo.get_metric.return_value = {
            "metric_name": "policy_count",
            "source_table": "POLICY",
            "source_column": "POLICY_SK",
            "aggregation": "count_distinct",
            "fact_entity": "POLICY",
        }
        schema_cache = {"POLICY": ["POLICY_SK", "POLICY_NUMBER", "STATUS"]}

        ok, errs = validate_plan(plan, "idp_reporting", mock_repo, schema_cache)
        assert ok is True, f"Plan should be valid but got errors: {errs}"

    def test_missing_keys_rejected(self):
        """Verify the plan validator rejects plans with missing keys."""
        from app.query_engine.plan_validator import validate_plan

        plan = {"question_type": "scalar_aggregate"}
        mock_repo = MagicMock()
        schema_cache = {}

        ok, errs = validate_plan(plan, "idp_reporting", mock_repo, schema_cache)
        assert ok is False
        assert len(errs) > 0

    def test_wrong_profile_rejected(self):
        """Verify plan with mismatched profile is flagged."""
        from app.query_engine.plan_validator import validate_plan

        plan = {
            "question_type": "general_chat",
            "user_question": "hello",
            "database_profile": "wrong_profile",
            "intent": "general_chat",
            "requires_multi_task": False,
            "tasks": [],
            "combine_strategy": "none",
            "comparison_dimension": None,
            "confidence": 1.0,
            "needs_clarification": False,
            "clarification_reason": "",
            "notes": [],
        }
        mock_repo = MagicMock()
        schema_cache = {}

        ok, errs = validate_plan(plan, "idp_reporting", mock_repo, schema_cache)
        assert any("mismatch" in e.lower() or "profile" in e.lower() for e in errs)
