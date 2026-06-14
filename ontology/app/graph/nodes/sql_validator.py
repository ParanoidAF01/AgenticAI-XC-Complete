"""
Step 10 — SQL Validation node.

Performs security checks, schema validation, and complexity analysis on
the generated SQL before it reaches the database.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from app.config import get_settings
from app.graph.state import WorkflowState
from app.services.sql_service import SQLService

logger = logging.getLogger(__name__)

# ── complexity limits ────────────────────────────────────────────────────────
_MAX_JOINS = 10
_MAX_SUBQUERY_DEPTH = 3


def _count_joins(sql: str) -> int:
    """Count the number of JOIN clauses (all flavours)."""
    return len(re.findall(r"\bJOIN\b", sql, re.IGNORECASE))


def _max_subquery_depth(sql: str) -> int:
    """Estimate nesting depth by counting parenthesised SELECT statements."""
    depth = 0
    max_depth = 0
    upper = sql.upper()
    for i, ch in enumerate(upper):
        if ch == "(":
            rest = upper[i + 1:].lstrip()
            if rest.startswith("SELECT"):
                depth += 1
                max_depth = max(max_depth, depth)
        elif ch == ")":
            if depth > 0:
                depth -= 1
    return max_depth


def _check_complexity(sql: str) -> str | None:
    """Return an error message if complexity limits are exceeded."""
    join_count = _count_joins(sql)
    if join_count > _MAX_JOINS:
        return (
            f"Query is too complex: {join_count} JOINs detected "
            f"(maximum allowed: {_MAX_JOINS})."
        )

    sq_depth = _max_subquery_depth(sql)
    if sq_depth > _MAX_SUBQUERY_DEPTH:
        return (
            f"Query is too complex: subquery nesting depth {sq_depth} "
            f"(maximum allowed: {_MAX_SUBQUERY_DEPTH})."
        )

    return None


def _check_tables_exist(
    sql: str, ontology_context: dict[str, Any]
) -> str | None:
    """Verify that tables referenced in the SQL exist in the ontology."""
    known_tables: set[str] = set()

    for key in ("table_details", "tables"):
        if key in ontology_context:
            known_tables.update(
                t.lower() for t in ontology_context[key]
            )

    if not known_tables:
        return None

    # Extract table references from FROM / JOIN clauses (heuristic).
    table_refs: set[str] = set()
    for match in re.finditer(
        r"(?:FROM|JOIN)\s+([a-zA-Z_][\w.]*)", sql, re.IGNORECASE
    ):
        raw_name = match.group(1).strip().lower()
        parts = raw_name.rsplit(".", 1)
        table_refs.add(parts[-1])

    unknown = table_refs - known_tables
    if unknown:
        return (
            f"Unknown table(s) not found in ontology: {', '.join(sorted(unknown))}. "
            "Please use only tables from the schema context."
        )

    return None


# ── main node ────────────────────────────────────────────────────────────────


async def sql_validator(state: WorkflowState) -> dict:
    """Validate the generated SQL for security, schema, and complexity.

    Checks
    ------
    1. **Security** — ``SQLService.validate_sql()`` rejects dangerous
       DDL / DML / injection patterns (returns ``(bool, str)``).
    2. **Schema validation** — verify table references match the ontology.
    3. **Complexity** — max 10 JOINs, max subquery depth 3.

    If validation fails and ``retry_count < 3`` the pipeline will loop
    back to ``sql_generator`` for self‑correction.

    Returns
    -------
    dict
        Partial state update with ``sql_valid``, ``sql_error``,
        ``retry_count``, and ``current_node``.
    """
    logger.info("sql_validator ▸ ENTER")

    try:
        sql: str | None = state.get("generated_sql")
        retry_count: int = state.get("retry_count", 0)
        ontology_context: dict[str, Any] = state.get("ontology_context", {})

        if not sql:
            logger.warning("sql_validator ▸ no SQL to validate")
            return {
                "sql_valid": False,
                "sql_error": "No SQL statement was generated.",
                "retry_count": retry_count + 1,
                "current_node": "sql_validator",
            }

        # ── 1. Security check via SQLService ────────────────────────
        #   validate_sql() is synchronous → run in a thread.
        settings = get_settings()
        sql_svc = SQLService(
            server=settings.mssql_server,
            database=settings.mssql_database,
            user=settings.mssql_user,
            password=settings.mssql_password,
            driver=settings.mssql_driver,
        )
        is_safe, reason = await asyncio.to_thread(sql_svc.validate_sql, sql)
        if not is_safe:
            logger.warning("sql_validator ▸ security check failed: %s", reason)
            return {
                "sql_valid": False,
                "sql_error": reason,
                "retry_count": retry_count + 1,
                "current_node": "sql_validator",
            }

        # ── 2. Schema validation ────────────────────────────────────
        tbl_err = _check_tables_exist(sql, ontology_context)
        if tbl_err:
            logger.warning("sql_validator ▸ schema validation failed: %s", tbl_err)
            return {
                "sql_valid": False,
                "sql_error": tbl_err,
                "retry_count": retry_count + 1,
                "current_node": "sql_validator",
            }

        # ── 3. Complexity validation ────────────────────────────────
        cx_err = _check_complexity(sql)
        if cx_err:
            logger.warning("sql_validator ▸ complexity check failed: %s", cx_err)
            return {
                "sql_valid": False,
                "sql_error": cx_err,
                "retry_count": retry_count + 1,
                "current_node": "sql_validator",
            }

        logger.info("sql_validator ▸ EXIT  sql_valid=True")
        return {
            "sql_valid": True,
            "sql_error": None,
            "retry_count": retry_count,
            "current_node": "sql_validator",
        }

    except Exception as exc:
        logger.exception("sql_validator ▸ unexpected error")
        return {
            "sql_valid": False,
            "sql_error": f"Validation error: {exc}",
            "retry_count": state.get("retry_count", 0) + 1,
            "current_node": "sql_validator",
        }
