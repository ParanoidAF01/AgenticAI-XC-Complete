"""
Answer generator — LLM-powered answer synthesis from query results.

Uses pre-computed statistics from ALL rows so the LLM gets 100% accurate
numbers without needing to see every raw row.
"""
from __future__ import annotations

import json
import logging
import statistics
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

from app.query_engine.helpers import make_json_safe
from app.query_engine.llm_client import call_llm
from app.query_engine.prompts import GENERAL_CHAT_SYSTEM_PROMPT, get_answer_prompt, get_current_ist_context

logger = logging.getLogger(__name__)

# ── Summarisation constants ──────────────────────────────────────
SAMPLE_ROWS = 5             # representative sample rows for context
MAX_CATEGORICAL_VALUES = 15  # top N distinct values to show per column


# ------------------------------------------------------------------
# Helpers: detect types and compute statistics
# ------------------------------------------------------------------

def _is_numeric(value: Any) -> bool:
    """Check if a value is numeric (int, float, or numeric string)."""
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        try:
            float(value.replace(",", ""))
            return True
        except (ValueError, AttributeError):
            return False
    return False


def _to_float(value: Any) -> Optional[float]:
    """Coerce a value to float, or None if impossible."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(",", ""))
        except (ValueError, AttributeError):
            return None
    return None


def _compute_numeric_stats(values: List[float]) -> Dict[str, Any]:
    """Compute summary statistics for a list of numeric values."""
    if not values:
        return {"count": 0}
    return {
        "count": len(values),
        "min": round(min(values), 2),
        "max": round(max(values), 2),
        "avg": round(sum(values) / len(values), 2),
        "sum": round(sum(values), 2),
        "median": round(statistics.median(values), 2),
    }


def _compute_categorical_stats(
    values: List[Any], limit: int = MAX_CATEGORICAL_VALUES,
) -> Dict[str, Any]:
    """Compute value distribution for a categorical column."""
    counter = Counter(v for v in values if v is not None)
    total = sum(counter.values())
    top = counter.most_common(limit)
    distribution = {str(k): v for k, v in top}
    result: Dict[str, Any] = {
        "unique_count": len(counter),
        "total_non_null": total,
        "top_values": distribution,
    }
    if len(counter) > limit:
        result["note"] = f"showing top {limit} of {len(counter)} unique values"
    return result


# ------------------------------------------------------------------
# Main summariser — works on ANY result set dynamically
# ------------------------------------------------------------------

def _summarize_results_for_llm(
    execution_output: Dict[str, Any],
) -> Dict[str, Any]:
    """Summarise execution results using pre-computed statistics.

    For each task's result set:
    - Strips internal columns (surrogate keys ending in _hk)
    - Classifies remaining columns as numeric or categorical
    - Computes exact statistics from ALL rows (not a sample)
    - Includes a small sample of rows for the LLM to see the data shape

    Returns a compact dict suitable for LLM context (~500-2000 tokens
    regardless of how many rows the query returned).
    """
    summarised_outputs: List[Dict[str, Any]] = []

    for task_out in execution_output.get("task_outputs", []):
        task = task_out.get("task", {})
        result = task_out.get("result", {})
        columns: List[str] = result.get("columns", [])
        rows: List[list] = result.get("rows", [])
        total_rows = len(rows)

        # Strip surrogate key columns (_hk) — meaningless to the LLM
        keep_indices = [
            i for i, col in enumerate(columns)
            if not col.lower().endswith("_hk")
        ]
        clean_columns = [columns[i] for i in keep_indices]

        # Build sample rows (strip _hk columns)
        sample = [
            [row[i] for i in keep_indices]
            for row in rows[:SAMPLE_ROWS]
        ]

        # Classify columns and compute stats from ALL rows
        numeric_stats: Dict[str, Any] = {}
        categorical_stats: Dict[str, Any] = {}

        for idx, col_name in zip(keep_indices, clean_columns):
            all_values = [row[idx] for row in rows]
            non_null = [v for v in all_values if v is not None]

            if not non_null:
                continue

            # Check if column is numeric by sampling up to 20 non-null values
            sample_check = non_null[:20]
            numeric_count = sum(1 for v in sample_check if _is_numeric(v))

            if numeric_count >= len(sample_check) * 0.8:
                # Numeric column — compute exact stats from ALL rows
                float_values = [
                    f for f in (_to_float(v) for v in non_null) if f is not None
                ]
                if float_values:
                    numeric_stats[col_name] = _compute_numeric_stats(float_values)
            else:
                # Categorical column — compute distribution from ALL rows
                categorical_stats[col_name] = _compute_categorical_stats(non_null)

        task_summary: Dict[str, Any] = {
            "task_id": task.get("task_id"),
            "task_type": task.get("task_type"),
            "metric_name": task.get("metric_name"),
            "selected_properties": task.get("selected_properties", []),
            "total_rows": total_rows,
            "columns": clean_columns,
            "sample_rows": sample,
        }
        if numeric_stats:
            task_summary["numeric_column_stats"] = numeric_stats
        if categorical_stats:
            task_summary["categorical_column_stats"] = categorical_stats
        if result.get("verification_warnings"):
            task_summary["warnings"] = result["verification_warnings"]

        summarised_outputs.append(task_summary)

    summarised: Dict[str, Any] = {
        "task_summaries": summarised_outputs,
        "combine_strategy": execution_output.get("combine_strategy", "none"),
    }

    # Carry over combined_rows if present (already small for compare_on_dimension)
    if "combined_rows" in execution_output:
        summarised["combined_rows"] = execution_output["combined_rows"]
        summarised["combined_columns"] = execution_output.get("combined_columns", [])

    # Carry over dropped/skipped metadata
    for key in ("dropped_task_count", "skipped_task_count", "total_planned_tasks"):
        if key in execution_output:
            summarised[key] = execution_output[key]

    return summarised


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------

async def build_general_llm_answer(question: str, context: str = "") -> str:
    """
    Generate a natural language response for a general (non-DB) question.
    Optionally includes conversation context.
    """
    payload: Dict[str, Any] = {
        "user_message": question,
        "current_datetime": get_current_ist_context(),
    }
    if context:
        payload["conversation_context"] = context

    messages = [
        {"role": "system", "content": GENERAL_CHAT_SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(payload, indent=2)},
    ]
    return (await call_llm(messages, max_tokens=400)).strip()


async def build_answer(
    question: str,
    profile_name: str,
    plan: Dict[str, Any],
    execution_output: Dict[str, Any],
    context: str = "",
) -> Tuple[str, Optional[Dict[str, Any]]]:
    """
    Generate a natural language answer from execution results.

    Uses pre-computed statistics from ALL rows so the LLM gets 100%
    accurate numbers in a compact payload (~1-2K tokens regardless
    of result set size).

    Returns:
        (answer_text, chart_config) — chart_config may be None
    """
    # Summarise results — exact stats from ALL rows, not trimmed
    summarised = _summarize_results_for_llm(execution_output)

    payload: Dict[str, Any] = {
        "user_question": question,
        "database_profile": profile_name,
        "current_datetime": get_current_ist_context(),
        "plan_summary": {
            "question_type": plan.get("question_type"),
            "intent": plan.get("intent"),
            "requires_multi_task": plan.get("requires_multi_task"),
            "combine_strategy": plan.get("combine_strategy"),
            "comparison_dimension": plan.get("comparison_dimension"),
        },
        "execution_summary": summarised,
    }
    if context:
        payload["conversation_context"] = context

    serialized = json.dumps(make_json_safe(payload), indent=2)
    logger.info(
        "Answer generator payload: ~%d tokens",
        len(serialized) // 4,
    )

    messages = [
        {"role": "system", "content": get_answer_prompt()},
        {"role": "user", "content": serialized},
    ]
    raw = (await call_llm(messages, max_tokens=1500)).strip()

    # Parse the LLM response — expecting JSON with "answer" and "chart" keys
    chart_config: Optional[Dict[str, Any]] = None
    answer_text: str = raw

    try:
        # Try to extract JSON from the response
        from app.query_engine.helpers import extract_json_text
        json_str = extract_json_text(raw)
        parsed = json.loads(json_str)
        if isinstance(parsed, dict) and "answer" in parsed:
            answer_text = parsed["answer"]
            chart = parsed.get("chart")
            if isinstance(chart, dict) and chart.get("show"):
                chart_config = chart
                logger.info(
                    "Chart config extracted: type=%s, title=%s",
                    chart.get("type"), chart.get("title"),
                )
    except (json.JSONDecodeError, Exception) as exc:
        # LLM returned plain text — use as-is, no chart
        logger.warning("Answer LLM did not return valid JSON, using raw text: %s", exc)
        answer_text = raw

    return answer_text, chart_config

