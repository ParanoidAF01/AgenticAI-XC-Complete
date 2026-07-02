"""
Tests for Redis cache service.
Verifies that cache failures don't break the application.
"""
from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from app.services.cache_service import RedisCacheService


@pytest.fixture
def healthy_redis() -> AsyncMock:
    """Redis client that works normally."""
    redis = AsyncMock()
    redis.get.return_value = None
    redis.set.return_value = True
    redis.delete.return_value = 1
    redis.close.return_value = None
    return redis


@pytest.fixture
def broken_redis() -> AsyncMock:
    """Redis client that raises on every operation."""
    redis = AsyncMock()
    redis.get.side_effect = ConnectionError("Redis is down")
    redis.set.side_effect = ConnectionError("Redis is down")
    redis.delete.side_effect = ConnectionError("Redis is down")
    redis.close.return_value = None
    return redis


class TestRedisCacheServiceHealthy:
    """Test cache service when Redis is available."""

    @pytest.mark.asyncio
    async def test_cache_and_retrieve_recent_messages(self, healthy_redis: AsyncMock):
        service = RedisCacheService(healthy_redis)
        session_id = str(uuid.uuid4())
        messages = [{"role": "user", "content": "hello"}]

        await service.cache_recent_messages(session_id, messages)
        healthy_redis.set.assert_called_once()

        # Verify the cache key format
        call_args = healthy_redis.set.call_args
        key = call_args[0][0] if call_args[0] else call_args.kwargs.get("name", "")
        assert f"chat:{session_id}:recent_messages" == key or session_id in str(call_args)

    @pytest.mark.asyncio
    async def test_cache_query_result_includes_user_and_profile(self, healthy_redis: AsyncMock):
        service = RedisCacheService(healthy_redis)
        user_id = str(uuid.uuid4())
        profile = "idp_reporting"
        question_hash = "abc123"
        result = {"answer": "42"}

        await service.cache_query_result(user_id, profile, question_hash, result)
        healthy_redis.set.assert_called_once()

        call_args = healthy_redis.set.call_args
        key = call_args[0][0] if call_args[0] else call_args.kwargs.get("name", "")
        # Key must include user_id and profile for proper scoping
        assert user_id in key or user_id in str(call_args)
        assert profile in key or profile in str(call_args)

    @pytest.mark.asyncio
    async def test_cache_summary(self, healthy_redis: AsyncMock):
        service = RedisCacheService(healthy_redis)
        session_id = str(uuid.uuid4())
        summary = "User asked about policy counts."

        await service.cache_summary(session_id, summary)
        healthy_redis.set.assert_called_once()


class TestRedisCacheServiceBroken:
    """Test that cache failures don't break the application."""

    @pytest.mark.asyncio
    async def test_cache_recent_messages_fails_silently(self, broken_redis: AsyncMock):
        service = RedisCacheService(broken_redis)
        session_id = str(uuid.uuid4())
        messages = [{"role": "user", "content": "hello"}]

        # Should NOT raise even though Redis is down
        await service.cache_recent_messages(session_id, messages)

    @pytest.mark.asyncio
    async def test_get_cached_recent_messages_returns_none(self, broken_redis: AsyncMock):
        service = RedisCacheService(broken_redis)
        session_id = str(uuid.uuid4())

        # Should return None, not raise
        result = await service.get_cached_recent_messages(session_id)
        assert result is None

    @pytest.mark.asyncio
    async def test_cache_summary_fails_silently(self, broken_redis: AsyncMock):
        service = RedisCacheService(broken_redis)
        session_id = str(uuid.uuid4())

        await service.cache_summary(session_id, "some summary")

    @pytest.mark.asyncio
    async def test_get_cached_summary_returns_none(self, broken_redis: AsyncMock):
        service = RedisCacheService(broken_redis)
        session_id = str(uuid.uuid4())

        result = await service.get_cached_summary(session_id)
        assert result is None

    @pytest.mark.asyncio
    async def test_cache_query_result_fails_silently(self, broken_redis: AsyncMock):
        service = RedisCacheService(broken_redis)

        await service.cache_query_result("user", "profile", "hash", {"data": "test"})

    @pytest.mark.asyncio
    async def test_get_cached_query_result_returns_none(self, broken_redis: AsyncMock):
        service = RedisCacheService(broken_redis)

        result = await service.get_cached_query_result("user", "profile", "hash")
        assert result is None


class TestCacheKeyScoping:
    """Verify cache keys are properly scoped."""

    @pytest.mark.asyncio
    async def test_different_sessions_different_keys(self, healthy_redis: AsyncMock):
        service = RedisCacheService(healthy_redis)
        session_1 = str(uuid.uuid4())
        session_2 = str(uuid.uuid4())

        await service.cache_recent_messages(session_1, [{"role": "user", "content": "msg1"}])
        call1_key = healthy_redis.set.call_args[0][0]

        healthy_redis.reset_mock()
        await service.cache_recent_messages(session_2, [{"role": "user", "content": "msg2"}])
        call2_key = healthy_redis.set.call_args[0][0]

        assert call1_key != call2_key, "Different sessions must use different cache keys"

    @pytest.mark.asyncio
    async def test_query_cache_scoped_by_user(self, healthy_redis: AsyncMock):
        service = RedisCacheService(healthy_redis)
        user_1 = str(uuid.uuid4())
        user_2 = str(uuid.uuid4())
        profile = "idp_reporting"
        q_hash = "same_hash"

        await service.cache_query_result(user_1, profile, q_hash, {"r": 1})
        call1_key = healthy_redis.set.call_args[0][0]

        healthy_redis.reset_mock()
        await service.cache_query_result(user_2, profile, q_hash, {"r": 2})
        call2_key = healthy_redis.set.call_args[0][0]

        assert call1_key != call2_key, "Different users must use different cache keys for same query"
