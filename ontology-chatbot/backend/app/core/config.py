"""Application configuration via Pydantic Settings."""
from __future__ import annotations

from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central config – values come from environment / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── PostgreSQL ──────────────────────────────────────────────
    POSTGRES_URL: str  # e.g. postgresql+asyncpg://user:pass@host/db

    # ── Redis ───────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379"

    # ── JWT ─────────────────────────────────────────────────────
    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_DAYS: int = 7
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # ── LLM ─────────────────────────────────────────────────────
    LLM_API_KEY: str = ""
    LLM_ENDPOINT: str = ""
    LLM_MODEL: str = ""
    LLM_PROVIDER: str = ""
    LLM_API_VERSION: str = ""

    # ── Neo4j ───────────────────────────────────────────────────
    NEO4J_URI: str = ""
    NEO4J_USERNAME: str = ""
    NEO4J_PASSWORD: str = ""
    NEO4J_DATABASE: str = "neo4j"

    # ── MSSQL Profile: IDP Reporting ─────────────────────────────
    MSSQL_IDP_REPORTING_URL: str = ""

    # ── MSSQL Profile: IDP Stage External ───────────────────────
    MSSQL_IDP_STAGE_EXT_URL: str = ""

    # ── SMTP (Email) ────────────────────────────────────────────
    SMTP_SERVER: str = "smtp.office365.com"
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_EMAIL: str = ""

    # ── CORS ────────────────────────────────────────────────────
    CORS_ORIGINS: List[str] = [
        "http://localhost:5173",
        "https://app.powerbi.com",
        "https://app.fabric.microsoft.com",
    ]

    # ── Power BI Integration ───────────────────────────────────
    POWERBI_API_KEY: str = ""              # Shared secret for Power BI visual auth
    POWERBI_DEFAULT_PROFILE: str = ""      # Fallback profile when PBI visual doesn't specify


@lru_cache()
def get_settings() -> Settings:
    """Return a cached Settings singleton."""
    return Settings()  # type: ignore[call-arg]
