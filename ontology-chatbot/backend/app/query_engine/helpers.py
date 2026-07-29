"""Generic helper / utility functions extracted from the legacy app."""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from app.query_engine.errors import PlannerError, SQLBuildError, SQLValidationError

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Constants (carried over from legacy)
# ------------------------------------------------------------------
DEFAULT_RESULT_LIMIT: int = 25
MAX_RESULT_LIMIT: int = 500

# ------------------------------------------------------------------
# Generic helpers
# ------------------------------------------------------------------

def dedupe(items: List[Any]) -> List[Any]:
    seen = set()
    out: List[Any] = []
    for item in items:
        marker = json.dumps(item, sort_keys=True, default=str) if isinstance(item, (dict, list)) else str(item)
        if marker not in seen:
            seen.add(marker)
            out.append(item)
    return out


def normalize_text(text: str) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def make_json_safe(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except Exception:
            return repr(value)
    if isinstance(value, dict):
        return {str(k): make_json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [make_json_safe(v) for v in value]
    return value


def extract_json_text(raw_text: str) -> str:
    text = (raw_text or "").strip()
    if not text:
        raise PlannerError("LLM returned empty response")
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise PlannerError(f"Could not find JSON object in LLM response: {raw_text}")
    return text[start:end + 1]


def extract_sql_text(raw_text: str) -> str:
    text = (raw_text or "").strip()
    if not text:
        raise SQLValidationError("LLM returned empty SQL repair response")
    if text.startswith("```"):
        text = re.sub(r"^```(?:sql)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    return text.strip().rstrip(";")


def parse_property_ref(ref: str) -> Tuple[str, str]:
    if not ref or "." not in ref:
        raise PlannerError(f"Invalid property_ref: {ref}")
    entity_name, column_name = ref.split(".", 1)
    return entity_name.strip(), column_name.strip()


def normalize_period(op: Optional[str]) -> Optional[str]:
    if not op:
        return None
    val = str(op).strip().lower().replace("_", " ")
    allowed = {
        "today", "yesterday", "last week", "this week", "last month", "this month",
        "last quarter", "this quarter", "last year", "this year", "ytd", "mtd", "qtd"
    }
    return val if val in allowed else None


def quote_sql_literal(val: Any) -> str:
    if val is None:
        return "NULL"
    if isinstance(val, (int, float)):
        return str(val)
    val_str = str(val)
    # Block suspiciously long values (likely not a legitimate filter)
    if len(val_str) > 500:
        raise SQLBuildError(f"Filter value too long ({len(val_str)} chars), max 500")
    # Block SQL injection patterns — dangerous keywords following a semicolon or standalone
    _injection_pattern = re.compile(
        r';\s*(DROP|DELETE|INSERT|UPDATE|ALTER|EXEC|EXECUTE|CREATE|TRUNCATE|MERGE|GRANT|REVOKE)\b',
        re.IGNORECASE,
    )
    if _injection_pattern.search(val_str):
        raise SQLBuildError(f"Suspicious filter value blocked: {val_str[:80]}")
    # Strip control characters (null bytes, backspace, etc.)
    val_str = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', val_str)
    val_str = val_str.replace("'", "''")
    return f"'{val_str}'"


# ------------------------------------------------------------------
# Task-result helpers (used during plan execution)
# ------------------------------------------------------------------

def build_task_result_context(task: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
    ctx: Dict[str, Any] = {}
    rows = result.get("rows", [])
    cols = result.get("columns", [])
    if not rows:
        return ctx
    first_row = rows[0]
    for col, val in zip(cols, first_row):
        ctx[col] = val
    selected_props = task.get("selected_properties", [])
    for prop in selected_props:
        try:
            entity_name, column_name = parse_property_ref(prop)
            alias = f"{entity_name}_{column_name}".lower()
            if alias in cols:
                val = first_row[cols.index(alias)]
                ctx[prop] = val
                ctx[column_name] = val
                ctx[alias] = val
        except Exception:
            continue
    return ctx


def resolve_placeholder_value(value: Any, task_contexts: Dict[str, Dict[str, Any]]) -> Any:
    if not isinstance(value, str):
        return value
    pattern = r"\{\{\s*([a-zA-Z0-9_]+)\.([^}]+)\s*\}\}"
    match = re.fullmatch(pattern, value.strip())
    if not match:
        return value
    task_id = match.group(1).strip()
    field_name = match.group(2).strip()
    if task_id not in task_contexts:
        raise SQLBuildError(f"Placeholder references unknown task: {task_id}")
    ctx = task_contexts[task_id]
    # Guard: upstream task returned 0 rows → context is empty
    if not ctx:
        raise SQLBuildError(
            f"Placeholder '{value}' cannot be resolved: upstream task '{task_id}' "
            f"returned no rows. Consider adding a fallback or removing this dependency."
        )
    if field_name in ctx:
        return ctx[field_name]
    for k, v in ctx.items():
        if str(k).lower() == field_name.lower():
            return v
    raise SQLBuildError(f"Could not resolve placeholder '{value}'. Available fields for {task_id}: {list(ctx.keys())}")


def resolve_task_placeholders(task: Dict[str, Any], task_contexts: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    resolved = json.loads(json.dumps(task))
    filters = resolved.get("filters", [])
    for flt in filters:
        if isinstance(flt, dict) and "value" in flt:
            flt["value"] = resolve_placeholder_value(flt["value"], task_contexts)
    return resolved


def augment_tasks_for_placeholders(tasks: List[Dict[str, Any]], repo: Any) -> List[Dict[str, Any]]:
    """
    If a downstream task references {{t1.FIELD_NAME}}, ensure task t1 selects that field.
    This makes placeholder resolution generic and stable.
    """
    tasks = json.loads(json.dumps(tasks))  # deep copy
    task_lookup = {t.get("task_id"): t for t in tasks if t.get("task_id")}

    pattern = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\.([^}]+)\s*\}\}")

    for task in tasks:
        for flt in task.get("filters", []):
            val = flt.get("value")
            if not isinstance(val, str):
                continue

            match = pattern.fullmatch(val.strip())
            if not match:
                continue

            upstream_task_id = match.group(1).strip()
            field_name = match.group(2).strip()

            upstream_task = task_lookup.get(upstream_task_id)
            if not upstream_task:
                continue

            base_entity_name = upstream_task.get("fact_entity") or upstream_task.get("target_entity")
            if not base_entity_name:
                continue

            # if placeholder is just POLICY_SK, assume it belongs to upstream base entity
            if "." in field_name:
                ref = field_name
            else:
                ref = f"{base_entity_name}.{field_name}"

            selected = upstream_task.setdefault("selected_properties", [])
            if ref not in selected:
                selected.append(ref)

    return tasks
