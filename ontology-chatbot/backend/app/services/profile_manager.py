"""Profile manager – maps logical profile names to MSSQL connections.

Builds connection URLs from individual credential fields (server, database,
user, password, driver, port) stored in environment variables.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional
from urllib.parse import quote_plus

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from ..core.config import Settings, get_settings
from ..schemas.common import ProfileResponse

logger = logging.getLogger(__name__)

# ── Profile catalogue ────────────────────────────────────────────
# Maps logical name → display metadata + Settings field prefix.
_PROFILE_CATALOGUE: Dict[str, Dict[str, str]] = {
    "idp_reporting": {
        "display_name": "IDP Reporting",
        "description": "IDP Reporting database (production read-only)",
        "prefix": "MSSQL_IDP_REPORTING",
    },
    "idp_stage_ext": {
        "display_name": "IDP Stage External",
        "description": "IDP Stage External database",
        "prefix": "MSSQL_IDP_STAGE_EXT",
    },
}


def _build_mssql_url(settings: Settings, prefix: str) -> Optional[str]:
    """Retrieve the pyodbc connection URL from the settings.

    Reads settings attributes like {prefix}_URL.
    """
    url = getattr(settings, f"{prefix}_URL", "") or ""
    return url if url else None


class ProfileManager:
    """Manages MSSQL profile connections with a lightweight pool per profile."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._engines: Dict[str, Engine] = {}
        self._settings = settings or get_settings()

    def initialize(self) -> None:
        """Log which profiles are configured (called on startup)."""
        for name in _PROFILE_CATALOGUE:
            url = self._resolve_url(name)
            if url:
                logger.info("Profile '%s' configured", name)
            else:
                logger.warning("Profile '%s' has no credentials configured", name)

    # ── public API ───────────────────────────────────────────────

    def get_profiles(self) -> List[dict]:
        """Return metadata for every configured profile."""
        profiles: List[dict] = []
        for name, meta in _PROFILE_CATALOGUE.items():
            url = self._resolve_url(name)
            if url:
                profiles.append({
                    "name": name,
                    "display_name": meta["display_name"],
                    "description": meta["description"],
                })
        return profiles

    def validate_profile(self, profile_name: str) -> bool:
        """Return True if *profile_name* is known and has credentials."""
        return profile_name in _PROFILE_CATALOGUE and bool(
            self._resolve_url(profile_name)
        )

    def get_engine(self, profile_name: str) -> Engine:
        """Return a (sync) SQLAlchemy Engine for *profile_name*.

        Engines are lazily created and cached for reuse.
        Raises ``ValueError`` if the profile is unknown or not configured.
        """
        if profile_name in self._engines:
            return self._engines[profile_name]

        url = self._resolve_url(profile_name)
        if not url:
            raise ValueError(
                f"Profile '{profile_name}' is not configured. "
                f"Set MSSQL_{profile_name.upper()}_SERVER and related env vars."
            )

        engine = create_engine(
            url,
            pool_size=5,
            max_overflow=5,
            pool_pre_ping=True,
            pool_recycle=1800,
        )
        self._engines[profile_name] = engine
        logger.info("Created MSSQL engine for profile=%s", profile_name)
        return engine

    def test_connection(self, profile_name: str) -> bool:
        """Quick connectivity check. Returns False on failure."""
        try:
            engine = self.get_engine(profile_name)
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except Exception:
            logger.exception("Connection test failed for profile=%s", profile_name)
            return False

    # ── lifecycle ────────────────────────────────────────────────

    def cleanup(self) -> None:
        """Dispose all cached engines (call on shutdown)."""
        for name, engine in self._engines.items():
            logger.info("Disposing MSSQL engine for profile=%s", name)
            engine.dispose()
        self._engines.clear()

    # ── internals ────────────────────────────────────────────────

    def _resolve_url(self, profile_name: str) -> Optional[str]:
        """Build the connection URL for a profile from its credential fields."""
        meta = _PROFILE_CATALOGUE.get(profile_name)
        if meta is None:
            return None
        return _build_mssql_url(self._settings, meta["prefix"])
