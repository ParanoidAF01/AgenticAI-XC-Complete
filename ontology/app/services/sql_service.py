"""SQL service — executes validated queries against Microsoft SQL Server.

Uses ``pyodbc`` for connectivity with proper connection-string construction
and basic connection pooling (pyodbc keeps an internal pool by default when
``pooling=True``).
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

import pyodbc

logger = logging.getLogger(__name__)

# ── Dangerous SQL patterns (case-insensitive) ──────────────────────────────
_DANGEROUS_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bDROP\b", re.IGNORECASE),
    re.compile(r"\bDELETE\b", re.IGNORECASE),
    re.compile(r"\bUPDATE\b", re.IGNORECASE),
    re.compile(r"\bINSERT\b", re.IGNORECASE),
    re.compile(r"\bEXEC\b", re.IGNORECASE),
    re.compile(r"\bEXECUTE\b", re.IGNORECASE),
    re.compile(r"\bxp_", re.IGNORECASE),
    re.compile(r"\bTRUNCATE\b", re.IGNORECASE),
    re.compile(r"\bALTER\b", re.IGNORECASE),
    re.compile(r"\bCREATE\b", re.IGNORECASE),
    re.compile(r"\bGRANT\b", re.IGNORECASE),
    re.compile(r"\bREVOKE\b", re.IGNORECASE),
]


class SQLService:
    """Synchronous MSSQL query executor with built-in safety checks.

    .. note::

        ``pyodbc`` is inherently synchronous.  In the async FastAPI pipeline
        this service should be called inside ``asyncio.to_thread()`` (or
        ``run_in_executor``) to avoid blocking the event loop.  The caller is
        responsible for that wrapper.
    """

    def __init__(
        self,
        server: str,
        database: str,
        user: str,
        password: str,
        driver: str = "ODBC Driver 17 for SQL Server",
    ) -> None:
        """Build the ODBC connection string and enable pooling.

        Args:
            server: SQL Server hostname or IP.
            database: Target database name.
            user: SQL login username.
            password: SQL login password.
            driver: ODBC driver name installed on the host.
        """
        self._connection_string = (
            f"DRIVER={{{driver}}};"
            f"SERVER={server};"
            f"DATABASE={database};"
            f"UID={user};"
            f"PWD={password};"
            "TrustServerCertificate=yes;"
        )
        # Enable pyodbc internal connection pooling
        pyodbc.pooling = True
        logger.info(
            "SQLService initialised (server=%s, database=%s)", server, database
        )

    # ── helpers ─────────────────────────────────────────────────────────────

    def _get_connection(self) -> pyodbc.Connection:
        """Open (or reuse from pool) a database connection."""
        return pyodbc.connect(self._connection_string, timeout=30)

    # ── public API ──────────────────────────────────────────────────────────

    def execute_query(
        self,
        sql: str,
        params: Optional[dict[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        """Execute a **read-only** SQL query and return rows as dicts.

        Args:
            sql: The SQL statement to execute.
            params: Optional mapping of named parameters.  Values are bound
                positionally in the order they appear in the SQL string.

        Returns:
            A list of ``{column_name: value}`` dicts.

        Raises:
            ValueError: If the SQL fails the safety validation.
            pyodbc.Error: On database-level errors.
        """
        is_safe, reason = self.validate_sql(sql)
        if not is_safe:
            raise ValueError(f"SQL rejected: {reason}")

        conn: Optional[pyodbc.Connection] = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            if params:
                # pyodbc uses ``?`` placeholders — convert named params
                ordered_values = list(params.values())
                cursor.execute(sql, ordered_values)
            else:
                cursor.execute(sql)

            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            rows = cursor.fetchall()

            results: list[dict[str, Any]] = [
                dict(zip(columns, row)) for row in rows
            ]

            logger.info(
                "Query executed successfully — %d row(s) returned", len(results)
            )
            return results

        except pyodbc.Error:
            logger.exception("Database error while executing query")
            raise
        finally:
            if conn is not None:
                conn.close()

    def validate_sql(self, sql: str) -> tuple[bool, str]:
        """Check *sql* for dangerous / mutating statements.

        Returns:
            ``(True, "")`` when the query is safe, or
            ``(False, "<reason>")`` when a forbidden keyword is detected.
        """
        if not sql or not sql.strip():
            return False, "Empty SQL statement"

        for pattern in _DANGEROUS_PATTERNS:
            if pattern.search(sql):
                keyword = pattern.pattern.strip("\\b").rstrip("\\b")
                msg = f"Forbidden keyword detected: {keyword}"
                logger.warning("SQL validation failed: %s — sql=%r", msg, sql[:200])
                return False, msg

        return True, ""

    def test_connection(self) -> bool:
        """Perform a lightweight connectivity check.

        Returns:
            ``True`` when a ``SELECT 1`` succeeds, ``False`` otherwise.
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
            conn.close()
            logger.info("MSSQL connection test passed")
            return True
        except Exception:
            logger.exception("MSSQL connection test failed")
            return False
