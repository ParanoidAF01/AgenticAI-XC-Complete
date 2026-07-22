"""
Shared test fixtures and configuration for the ontology chatbot test suite.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator, Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# ---------------------------------------------------------------------------
# Override settings BEFORE importing app modules so the app sees test values.
# ---------------------------------------------------------------------------
os.environ.setdefault("POSTGRES_URL", "sqlite+aiosqlite:///./test.db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-do-not-use-in-prod")
os.environ.setdefault("LLM_API_KEY", "test-key")
os.environ.setdefault("LLM_ENDPOINT", "https://test.anthropic.com/v1/messages")
os.environ.setdefault("LLM_MODEL", "claude-sonnet-4-20250514")
os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USERNAME", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "test")
os.environ.setdefault("MSSQL_IDP_REPORTING_SERVER", "localhost")
os.environ.setdefault("MSSQL_IDP_REPORTING_DATABASE", "idp_reporting")
os.environ.setdefault("MSSQL_IDP_REPORTING_USER", "test")
os.environ.setdefault("MSSQL_IDP_REPORTING_PASSWORD", "test")
os.environ.setdefault("MSSQL_IDP_STAGE_EXT_SERVER", "localhost")
os.environ.setdefault("MSSQL_IDP_STAGE_EXT_DATABASE", "idp_stage_ext")
os.environ.setdefault("MSSQL_IDP_STAGE_EXT_USER", "test")
os.environ.setdefault("MSSQL_IDP_STAGE_EXT_PASSWORD", "test")

from app.core.config import Settings, get_settings  # noqa: E402
from app.core.database import Base  # noqa: E402
from app.core.security import create_access_token, hash_password  # noqa: E402


# ---------------------------------------------------------------------------
# Test settings override
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def test_settings() -> Settings:
    return Settings(
        POSTGRES_URL="sqlite+aiosqlite:///./test.db",
        REDIS_URL="redis://localhost:6379/1",
        JWT_SECRET="test-jwt-secret-do-not-use-in-prod",
        LLM_API_KEY="test-key",
        LLM_ENDPOINT="https://test.anthropic.com/v1/messages",
        LLM_MODEL="claude-sonnet-4-20250514",
        NEO4J_URI="bolt://localhost:7687",
        NEO4J_USERNAME="neo4j",
        NEO4J_PASSWORD="test",
        MSSQL_IDP_REPORTING_SERVER="localhost",
        MSSQL_IDP_REPORTING_DATABASE="idp_reporting",
        MSSQL_IDP_REPORTING_USER="test",
        MSSQL_IDP_REPORTING_PASSWORD="test",
        MSSQL_IDP_STAGE_EXT_SERVER="localhost",
        MSSQL_IDP_STAGE_EXT_DATABASE="idp_stage_ext",
        MSSQL_IDP_STAGE_EXT_USER="test",
        MSSQL_IDP_STAGE_EXT_PASSWORD="test",
    )


# ---------------------------------------------------------------------------
# In-memory SQLite async engine for tests
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture(scope="session")
async def test_engine():
    engine = create_async_engine("sqlite+aiosqlite:///./test.db", echo=False)

    # SQLite needs special handling for foreign keys
    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()
    # Clean up test db file
    if os.path.exists("./test.db"):
        os.remove("./test.db")


@pytest_asyncio.fixture
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    session_factory = async_sessionmaker(test_engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
        await session.rollback()


# ---------------------------------------------------------------------------
# Test user helpers
# ---------------------------------------------------------------------------
@pytest.fixture
def test_user_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def test_user_id_2() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def test_user_email() -> str:
    return f"test_{uuid.uuid4().hex[:8]}@example.com"


@pytest.fixture
def test_access_token(test_user_id: uuid.UUID) -> str:
    return create_access_token(str(test_user_id), is_admin=False)


@pytest.fixture
def test_admin_token(test_user_id: uuid.UUID) -> str:
    return create_access_token(str(test_user_id), is_admin=True)


@pytest.fixture
def auth_headers(test_access_token: str) -> dict:
    return {"Authorization": f"Bearer {test_access_token}"}


# ---------------------------------------------------------------------------
# Mock services
# ---------------------------------------------------------------------------
@pytest.fixture
def mock_redis():
    """Mock Redis client that simulates cache misses."""
    redis = AsyncMock()
    redis.get.return_value = None
    redis.set.return_value = True
    redis.delete.return_value = True
    redis.close.return_value = None
    return redis


@pytest.fixture
def mock_neo4j_repo():
    """Mock Neo4j repository."""
    repo = MagicMock()
    repo.test.return_value = True
    repo.get_profile.return_value = {
        "profile_name": "idp_reporting",
        "ontology_status": "ready",
        "display_name": "IDP Reporting",
        "description": "IDP Reporting Database",
    }
    repo.get_entities.return_value = [
        {
            "entity_name": "POLICY",
            "canonical_name": "Policy",
            "table_name": "POLICY",
            "schema_name": "dbo",
            "entity_type": "dimension",
            "business_role": "core",
            "primary_key": "POLICY_SK",
            "synonyms": ["policy", "pol"],
            "description": "Insurance policy",
        }
    ]
    repo.get_metrics.return_value = [
        {
            "metric_name": "policy_count",
            "canonical_name": "Policy Count",
            "fact_entity": "POLICY",
            "source_table": "POLICY",
            "source_column": "POLICY_SK",
            "aggregation": "count_distinct",
            "description": "Count of policies",
        }
    ]
    repo.get_relationships.return_value = []
    repo.get_entity_table_lookup.return_value = {"POLICY": "POLICY"}
    repo.close.return_value = None
    return repo


@pytest.fixture
def mock_mssql_engine():
    """Mock MSSQL engine."""
    engine = MagicMock()
    return engine
