"""Profile manager – maps logical profile names to MSSQL connection URLs."""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from ..core.config import get_settings
from ..schemas.common import ProfileResponse

logger = logging.getLogger(__name__)

# ── Profile catalogue ────────────────────────────────────────────
# Each entry maps a logical name to its env-var connection URL.
_PROFILE_CATALOGUE: Dict[str, Dict[str, str]] = {
    "idp_reporting": {
        "display_name": "IDP Reporting",
        "description": "IDP Reporting database (production read-only)",
        "env_key": "MSSQL_IDP_REPORTING_URL",
    },
    "idp_stage_ext": {
        "display_name": "IDP Stage External",
        "description": "IDP Stage External database",
        "env_key": "MSSQL_IDP_STAGE_EXT_URL",
    },
}


class ProfileManager:
    """Manages MSSQL profile connections with a lightweight pool per profile."""

    def __init__(self) -> None:
        self._engines: Dict[str, Engine] = {}
        self._settings = get_settings()

    # ── public API ───────────────────────────────────────────────

    def get_profiles(self) -> List[ProfileResponse]:
        """Return metadata for every configured profile."""
        profiles: List[ProfileResponse] = []
        for name, meta in _PROFILE_CATALOGUE.items():
            url = self._resolve_url(name)
            if url:
                profiles.append(
                    ProfileResponse(
                        name=name,
                        display_name=meta["display_name"],
                        description=meta["description"],
                    )
                )
        return profiles

    def validate_profile(self, profile_name: str) -> bool:
        """Return True if *profile_name* is known and has a configured URL."""
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
                f"Profile '{profile_name}' is not configured or has no URL"
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

    def dispose_all(self) -> None:
        """Dispose all cached engines (call on shutdown)."""
        for name, engine in self._engines.items():
            logger.info("Disposing MSSQL engine for profile=%s", name)
            engine.dispose()
        self._engines.clear()

    # ── internals ────────────────────────────────────────────────

    def _resolve_url(self, profile_name: str) -> Optional[str]:
        """Resolve a profile name to its connection URL from settings."""
        meta = _PROFILE_CATALOGUE.get(profile_name)
        if meta is None:
            return None
        attr = meta["env_key"]
        url: str = getattr(self._settings, attr, "") or ""
        return url if url else None
