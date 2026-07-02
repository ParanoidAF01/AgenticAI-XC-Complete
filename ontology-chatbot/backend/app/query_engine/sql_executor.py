"""
SQL executor — runs validated SQL against MSSQL.
Extracted from legacy app lines 1080–1093.
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.query_engine.errors import SQLExecutionError
from app.query_engine.helpers import make_json_safe

logger = logging.getLogger(__name__)

DEFAULT_QUERY_TIMEOUT = 30  # seconds


def execute_sql(
    engine: Engine,
    sql: str,
    max_preview_rows: int = 500,
    timeout: int = DEFAULT_QUERY_TIMEOUT,
) -> Dict[str, Any]:
    """
    Execute a validated SELECT query against MSSQL and return results.

    Args:
        engine: SQLAlchemy Engine connected to MSSQL.
        sql: The validated SQL string to execute.
        max_preview_rows: Maximum rows to include in preview.
        timeout: Query timeout in seconds.

    Returns:
        Dict with columns, rows, row_count, execution_time_ms.
    """
    start = time.time()
    try:
        with engine.connect() as conn:
            # Set query timeout
            conn = conn.execution_options(timeout=timeout)
            res = conn.execute(text(sql))
            rows = res.fetchall()
            cols = list(res.keys())

        ms = int((time.time() - start) * 1000)
        safe_rows = [
            make_json_safe(list(r) if not isinstance(r, (list, tuple)) else list(r))
            for r in rows[:max_preview_rows]
        ]
        safe_columns = [str(c) for c in cols]
        logger.info(
            "SQL execution successful -> row_count=%d, execution_time_ms=%d",
            len(rows), ms,
        )
        return {
            "columns": safe_columns,
            "rows": safe_rows,
            "row_count": len(rows),
            "execution_time_ms": ms,
        }
    except Exception as e:
        raise SQLExecutionError(str(e))
