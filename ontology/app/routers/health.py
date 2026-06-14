"""Health-check router.

Exposes a single ``GET /health`` endpoint that probes each external
dependency (Neo4j, MSSQL, Redis) and reports aggregate readiness.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request

from app.models.schemas import HealthResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["monitoring"])


# ── Dependency helpers ──────────────────────────────────────────────────────

def _get_neo4j(request: Request) -> Any:
    """Retrieve the Neo4j service from application state."""
    return request.app.state.neo4j_service


def _get_sql(request: Request) -> Any:
    """Retrieve the SQL service from application state."""
    return request.app.state.sql_service


def _get_redis(request: Request) -> Any:
    """Retrieve the Redis service from application state."""
    return request.app.state.redis_service


# ── Health endpoint ─────────────────────────────────────────────────────────

@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Service health check",
    description="Probes Neo4j, MSSQL, and Redis and returns connectivity status.",
)
async def health_check(request: Request) -> HealthResponse:
    """Return a structured health report for all backing services.

    Each service is tested independently so a single outage does not
    prevent the remaining checks from executing.  The top-level
    ``status`` field is ``"healthy"`` only when **all** services are
    reachable.
    """

    neo4j_ok = await _probe_neo4j(request)
    mssql_ok = await _probe_mssql(request)
    redis_ok = await _probe_redis(request)

    overall = "healthy" if all([neo4j_ok, mssql_ok, redis_ok]) else "degraded"

    return HealthResponse(
        status=overall,
        neo4j_connected=neo4j_ok,
        mssql_connected=mssql_ok,
        redis_connected=redis_ok,
    )


# ── Individual probes ───────────────────────────────────────────────────────

async def _probe_neo4j(request: Request) -> bool:
    """Test Neo4j connectivity by running a lightweight Cypher statement."""
    try:
        neo4j_svc = _get_neo4j(request)
        await neo4j_svc.verify_connectivity()
        return True
    except Exception:
        logger.warning("Neo4j health-check failed", exc_info=True)
        return False


async def _probe_mssql(request: Request) -> bool:
    """Test MSSQL connectivity by issuing ``SELECT 1``."""
    try:
        sql_svc = _get_sql(request)
        await sql_svc.execute("SELECT 1")
        return True
    except Exception:
        logger.warning("MSSQL health-check failed", exc_info=True)
        return False


async def _probe_redis(request: Request) -> bool:
    """Test Redis connectivity by sending a ``PING`` command."""
    try:
        redis_svc = _get_redis(request)
        await redis_svc.ping()
        return True
    except Exception:
        logger.warning("Redis health-check failed", exc_info=True)
        return False
