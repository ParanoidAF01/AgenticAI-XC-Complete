"""Application configuration loaded from environment variables.

Uses *pydantic-settings* so every value can be overridden via a ``.env`` file
sitting in the project root **or** via real environment variables (which take
precedence).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve the .env that lives next to the project root (one level above /app).
_ENV_FILE: Path = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    """Centralised, validated configuration for every subsystem."""

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── OpenAI ──────────────────────────────────────────────────────────────
    openai_api_key: str = Field(..., description="OpenAI API key")
    openai_model: str = Field(default="gpt-4o", description="Chat model name")

    # ── Neo4j ───────────────────────────────────────────────────────────────
    neo4j_uri: str = Field(
        default="bolt://localhost:7687", description="Neo4j Bolt URI"
    )
    neo4j_user: str = Field(default="neo4j", description="Neo4j username")
    neo4j_password: str = Field(..., description="Neo4j password")

    # ── Microsoft SQL Server ────────────────────────────────────────────────
    mssql_server: str = Field(default="localhost", description="MSSQL host")
    mssql_database: str = Field(
        default="insurance_db", description="MSSQL database name"
    )
    mssql_user: str = Field(default="sa", description="MSSQL username")
    mssql_password: str = Field(..., description="MSSQL password")
    mssql_driver: str = Field(
        default="ODBC Driver 17 for SQL Server",
        description="ODBC driver string",
    )

    # ── Redis ───────────────────────────────────────────────────────────────
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL",
    )

    # ── SpaCy ───────────────────────────────────────────────────────────────
    spacy_model: str = Field(
        default="en_core_web_sm", description="SpaCy model to load"
    )

    # ── Application defaults ────────────────────────────────────────────────
    app_name: str = Field(
        default="Ontology Chatbot",
        description="Display name shown in API docs",
    )
    app_version: str = Field(default="1.0.0", description="Semantic version")
    debug: bool = Field(default=False, description="Enable debug logging")
    sql_result_limit: int = Field(
        default=100,
        description="Default TOP N limit appended to generated SQL",
    )
    redis_cache_ttl: int = Field(
        default=300, description="Default cache TTL in seconds"
    )
    db_schema: str = Field(
        default="idp_stage",
        description="Default SQL Server schema prefix for all tables",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached :class:`Settings` singleton.

    Using ``lru_cache`` ensures the ``.env`` file is read only once during the
    process lifetime while still allowing tests to monkeypatch the function.
    """
    return Settings()  # type: ignore[call-arg]
