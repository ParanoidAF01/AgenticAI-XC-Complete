"""
SQL safety validator and compile-time validation with LLM repair loop.
Extracted from legacy app lines 1189–1351.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.query_engine.errors import SQLBuildError, SQLValidationError
from app.query_engine.helpers import (
    extract_sql_text,
    make_json_safe,
    parse_property_ref,
)
from app.query_engine.llm_client import call_llm
from app.query_engine.prompts import SQL_REPAIR_PROMPT

logger = logging.getLogger(__name__)

# ── SQL Safety ────────────────────────────────────────────────
# Dangerous keywords that must not appear as standalone SQL statements
_BLOCKED_KEYWORDS = [
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE",
    "MERGE", "EXEC", "EXECUTE", "CREATE", "GRANT", "REVOKE",
]

# Pattern matches a blocked keyword that appears at a word boundary,
# but NOT inside a quoted string literal.  We use a conservative approach:
# strip string literals first, then check.
_BLOCKED_PATTERN = re.compile(
    r"\b(" + "|".join(_BLOCKED_KEYWORDS) + r")\b",
    re.IGNORECASE,
)

_STRING_LITERAL_PATTERN = re.compile(r"'(?:[^']|'')*'")


def validate_sql_safety(sql: Optional[str]) -> Tuple[bool, Optional[str]]:
    """
    Check that SQL is a safe SELECT-only query.

    Returns:
        (True, None) if safe
        (False, reason) if blocked
    """
    if not sql or not sql.strip():
        return False, "Empty SQL statement"

    cleaned = sql.strip()

    # Remove single-line comments
    cleaned_no_comments = re.sub(r"--.*$", "", cleaned, flags=re.MULTILINE)
    # Remove multi-line comments
    cleaned_no_comments = re.sub(r"/\*.*?\*/", "", cleaned_no_comments, flags=re.DOTALL)

    # Check for multiple statements (semicolons in non-string context)
    without_strings = _STRING_LITERAL_PATTERN.sub("", cleaned_no_comments)
    if ";" in without_strings.rstrip().rstrip(";"):
        # More than one semicolon-delimited statement
        parts = [p.strip() for p in without_strings.split(";") if p.strip()]
        if len(parts) > 1:
            return False, "Multiple SQL statements detected; only single SELECT is allowed"

    # Check for blocked keywords outside string literals
    match = _BLOCKED_PATTERN.search(without_strings)
    if match:
        keyword = match.group(1).upper()
        return False, f"Blocked SQL keyword detected: {keyword}. Only SELECT queries are allowed."

    # Verify the statement starts with SELECT, WITH, or parenthesized subquery
    stripped = without_strings.strip().lstrip("(").strip()
    if not re.match(r"^\s*(SELECT|WITH)\b", stripped, re.IGNORECASE):
        return False, "SQL must start with SELECT or WITH (CTE)"

    return True, None


# ── Schema context for repair ─────────────────────────────────

def build_task_schema_context(
    task: Dict[str, Any],
    profile_name: str,
    repo: Any,
    schema_cache: Dict[str, List[str]],
) -> Dict[str, List[str]]:
    """
    Build a mapping of table -> columns relevant to a task.
    Used to constrain LLM SQL repair to known tables/columns only.
    """
    tables: set[str] = set()

    if task.get("metric_name"):
        metric = repo.get_metric(profile_name, task["metric_name"])
        if metric:
            if metric.get("source_table"):
                tables.add(metric["source_table"])
            if metric.get("fact_entity"):
                fact_entity = repo.get_entity(metric["fact_entity"])
                if fact_entity and fact_entity.get("table_name"):
                    tables.add(fact_entity["table_name"])

    for prop in task.get("selected_properties", []):
        try:
            entity_name, _ = parse_property_ref(prop)
            entity = repo.get_entity(entity_name)
            if entity and entity.get("table_name"):
                tables.add(entity["table_name"])
        except Exception:
            continue

    if task.get("date_property"):
        try:
            entity_name, _ = parse_property_ref(task["date_property"])
            entity = repo.get_entity(entity_name)
            if entity and entity.get("table_name"):
                tables.add(entity["table_name"])
        except Exception:
            pass

    for flt in task.get("filters", []):
        try:
            if flt.get("property_ref"):
                entity_name, _ = parse_property_ref(flt["property_ref"])
                entity = repo.get_entity(entity_name)
                if entity and entity.get("table_name"):
                    tables.add(entity["table_name"])
        except Exception:
            continue

    # Join steps
    try:
        from app.query_engine.sql_compiler import resolve_join_steps
        for step in resolve_join_steps(task, repo):
            if step.get("from_table"):
                tables.add(step["from_table"])
            if step.get("to_table"):
                tables.add(step["to_table"])
    except Exception:
        pass

    base_entity_name = task.get("fact_entity") or task.get("target_entity")
    if base_entity_name:
        entity = repo.get_entity(base_entity_name)
        if entity and entity.get("table_name"):
            tables.add(entity["table_name"])

    return {t: schema_cache.get(t, []) for t in sorted(tables)}


# ── Compile validation ────────────────────────────────────────

def validate_sql_compile(engine: Engine, sql: str) -> Tuple[bool, Optional[str]]:
    """
    Validate SQL Server query without executing it.
    Uses sys.sp_describe_first_result_set to force SQL Server compilation/binding.
    """
    try:
        with engine.connect() as conn:
            conn.execute(
                text("""
                EXEC sys.sp_describe_first_result_set
                    @tsql = :tsql,
                    @params = NULL,
                    @browse_information_mode = 0
                """),
                {"tsql": sql},
            )
        return True, None
    except Exception as e:
        return False, str(e)


# ── LLM repair ────────────────────────────────────────────────

async def repair_sql_with_llm(
    question: str,
    profile_name: str,
    task: Dict[str, Any],
    sql: str,
    validation_error: str,
    repo: Any,
    schema_cache: Dict[str, List[str]],
) -> str:
    """Call LLM to fix a SQL query that failed compilation."""
    schema_context = build_task_schema_context(task, profile_name, repo, schema_cache)

    payload = {
        "user_question": question,
        "database_profile": profile_name,
        "task": make_json_safe(task),
        "sql_to_fix": sql,
        "validation_error": validation_error,
        "relevant_schema": schema_context,
        "instruction": "Fix the SQL so that it compiles in SQL Server and preserves intent. "
                       "Do NOT introduce tables or columns outside the relevant_schema.",
    }

    import json
    raw = await call_llm(
        [
            {"role": "system", "content": SQL_REPAIR_PROMPT},
            {"role": "user", "content": json.dumps(payload, indent=2)},
        ],
        max_tokens=1800,
    )
    repaired = extract_sql_text(raw)
    logger.info("SQL repair LLM output -> %s", repaired[:1800])

    # Validate repaired SQL doesn't introduce tables outside schema context
    _validate_repair_tables(repaired, schema_context)

    return repaired


def _validate_repair_tables(sql: str, schema_context: Dict[str, List[str]]) -> None:
    """
    Best-effort check that repaired SQL doesn't reference tables
    outside the provided schema context.
    """
    allowed_tables = {t.lower() for t in schema_context}
    # Extract [TableName] patterns from SQL
    table_refs = re.findall(r"\[(\w+)\]", sql)
    # Also check bare table references after FROM/JOIN
    bare_refs = re.findall(r"(?:FROM|JOIN)\s+(\w+)", sql, re.IGNORECASE)
    all_refs = {r.lower() for r in table_refs + bare_refs}

    # Filter out column names (those that appear after a dot)
    dot_prefixed = re.findall(r"\[(\w+)\]\.\[(\w+)\]", sql)
    table_only = {t.lower() for t, c in dot_prefixed}

    if table_only:
        unknown = table_only - allowed_tables
        if unknown:
            logger.warning(
                "SQL repair introduced unknown tables: %s (allowed: %s)",
                unknown, allowed_tables,
            )
            raise SQLValidationError(
                f"SQL repair introduced tables outside schema context: {unknown}"
            )


# ── Validate and repair loop ─────────────────────────────────

MAX_SQL_REPAIR_ATTEMPTS = 3


async def validate_and_repair_sql(
    engine: Engine,
    question: str,
    profile_name: str,
    task: Dict[str, Any],
    sql: str,
    repo: Any,
    schema_cache: Dict[str, List[str]],
    max_attempts: int = MAX_SQL_REPAIR_ATTEMPTS,
) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Validate SQL, attempt LLM repair if compilation fails.

    Returns:
        (final_sql, validation_trace)
    """
    validation_trace: List[Dict[str, Any]] = []
    current_sql = sql

    # Safety check first
    is_safe, safety_reason = validate_sql_safety(current_sql)
    if not is_safe:
        raise SQLValidationError(f"SQL safety check failed: {safety_reason}")

    for attempt in range(1, max_attempts + 2):  # original + repair attempts
        ok, err = validate_sql_compile(engine, current_sql)

        validation_trace.append(
            {
                "attempt": attempt,
                "valid": ok,
                "error": err,
                "sql": current_sql,
            }
        )

        if ok:
            logger.info("SQL validation passed on attempt %d", attempt)
            return current_sql, validation_trace

        logger.warning("SQL validation failed on attempt %d -> %s", attempt, err)

        if attempt > max_attempts:
            break

        current_sql = await repair_sql_with_llm(
            question=question,
            profile_name=profile_name,
            task=task,
            sql=current_sql,
            validation_error=err or "Unknown SQL compilation error",
            repo=repo,
            schema_cache=schema_cache,
        )

        # Re-check safety after repair
        is_safe, safety_reason = validate_sql_safety(current_sql)
        if not is_safe:
            raise SQLValidationError(f"SQL repair produced unsafe SQL: {safety_reason}")

    raise SQLValidationError(
        "SQL validation failed after repair attempts. Last error: "
        + (validation_trace[-1].get("error") or "Unknown error")
    )
