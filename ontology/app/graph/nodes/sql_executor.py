"""
Step 11 — SQL Execution node.

Checks Redis cache first; on cache miss executes the query against MSSQL
via ``SQLService`` and caches the result.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from app.graph.state import WorkflowState
from app.services.redis_service import RedisService

logger = logging.getLogger(__name__)


async def sql_executor(state: WorkflowState) -> dict:
    """Execute the validated SQL statement, with Redis caching.

    Flow
    ----
    1. Compute a SHA‑256 hash of the SQL (via ``RedisService.hash_sql``).
    2. Check Redis for a cached result (``get_cached_result``).
    3. On cache miss → execute via ``SQLService.execute_query()`` in a
       thread (pyodbc is synchronous).
    4. Store the result in Redis (``cache_result``) with TTL from config.
    5. Track wall‑clock ``execution_time_ms``.

    Returns
    -------
    dict
        Partial state update with ``query_result``, ``result_count``,
        ``execution_time_ms``, and ``current_node``.
    """
    logger.info("sql_executor ▸ ENTER")

    try:
        sql: str | None = state.get("generated_sql")

        if not sql:
            logger.warning("sql_executor ▸ no SQL to execute")
            return {
                "query_result": None,
                "result_count": 0,
                "execution_time_ms": 0.0,
                "current_node": "sql_executor",
                "error": "No SQL statement available for execution.",
            }

        t0 = time.perf_counter()

        # ── 1. Cache check ──────────────────────────────────────────
        sql_hash = RedisService.hash_sql(sql)
        cache_svc = state.get("redis_service")

        cached_result = None
        if cache_svc is not None:
            cached_result = await cache_svc.get_cached_result(sql_hash)
        if cached_result is not None:
            elapsed = (time.perf_counter() - t0) * 1000
            logger.info(
                "sql_executor ▸ cache HIT  rows=%d  %.1f ms",
                len(cached_result),
                elapsed,
            )
            return {
                "query_result": cached_result,
                "result_count": len(cached_result),
                "execution_time_ms": round(elapsed, 2),
                "current_node": "sql_executor",
            }

        # ── 2. Execute query (sync → thread) ────────────────────────
        logger.info("sql_executor ▸ cache MISS — executing SQL")
        sql_svc = state.get("sql_service")
        if sql_svc is None:
            raise RuntimeError("sql_service not found in workflow state")
        result: list[dict[str, Any]] = await asyncio.to_thread(
            sql_svc.execute_query, sql
        )
        elapsed = (time.perf_counter() - t0) * 1000

        # ── 3. Cache result ─────────────────────────────────────────
        try:
            if cache_svc is not None:
                await cache_svc.cache_result(
                    sql_hash, result, ttl=300
                )
        except Exception as cache_err:
            logger.warning("sql_executor ▸ failed to cache result: %s", cache_err)

        logger.info(
            "sql_executor ▸ EXIT  rows=%d  %.1f ms", len(result), elapsed
        )
        return {
            "query_result": result,
            "result_count": len(result),
            "execution_time_ms": round(elapsed, 2),
            "current_node": "sql_executor",
        }

    except Exception as exc:
        logger.exception("sql_executor ▸ unexpected error")
        return {
            "query_result": None,
            "result_count": 0,
            "execution_time_ms": 0.0,
            "current_node": "sql_executor",
            "error": f"SQL execution failed: {exc}",
        }
