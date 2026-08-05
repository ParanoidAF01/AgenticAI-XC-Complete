"""Plan validation – synchronous checks against the ontology and live schema."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from app.ontology.neo4j_repository import Neo4jRepo
from app.query_engine.helpers import normalize_period, parse_property_ref

logger = logging.getLogger(__name__)


def validate_property_ref(
    property_ref: str,
    repo: Neo4jRepo,
    schema_cache: Dict[str, List[str]],
) -> bool:
    """Validate that a property_ref (Entity.Column) exists in both the
    ontology graph and the live MSSQL schema."""
    try:
        entity_name, column_name = parse_property_ref(property_ref)
        entity = repo.get_entity(entity_name)
        if not entity:
            return False
        table_name = entity["table_name"]
        # Check live MSSQL schema
        if column_name not in schema_cache.get(table_name, []):
            return False
        return True
    except Exception:
        return False


def _get_column_meta(
    entity_name: str,
    column_name: str,
    repo: Neo4jRepo,
) -> Optional[Dict[str, Any]]:
    """Look up a single column's metadata from the ontology graph.

    Returns None if the column is not found in the entity's ontology columns.
    """
    columns = repo.get_entity_columns(entity_name)
    for col in columns:
        if col.get("column_name") == column_name:
            return col
    return None


def _validate_column_flags(
    property_ref: str,
    usage: str,
    repo: Neo4jRepo,
) -> List[str]:
    """Validate that the column's boolean flags allow its intended usage.

    Args:
        property_ref: "Entity.Column" format
        usage: one of "select", "filter", "group", "aggregate", "date"
    """
    warnings: List[str] = []
    try:
        entity_name, column_name = parse_property_ref(property_ref)
    except Exception:
        return warnings

    col_meta = _get_column_meta(entity_name, column_name, repo)
    if col_meta is None:
        # Column not found in ontology — flag as warning (not hard error,
        # since it may still exist in MSSQL)
        warnings.append(
            f"Column {property_ref} not found in ontology graph (HAS_COLUMN). "
            f"It may exist in MSSQL but lacks ontology metadata."
        )
        return warnings

    if col_meta.get("is_selectable") is False and usage == "select":
        warnings.append(f"{property_ref}: is_selectable=false, should not be in selected_properties")

    if col_meta.get("is_filterable") is False and usage == "filter":
        warnings.append(f"{property_ref}: is_filterable=false, should not be used in WHERE filter")

    if col_meta.get("is_groupable") is False and usage == "group":
        warnings.append(f"{property_ref}: is_groupable=false, should not be used in GROUP BY")

    if col_meta.get("is_aggregatable") is False and usage == "aggregate":
        warnings.append(f"{property_ref}: is_aggregatable=false, should not be aggregated")

    if usage == "date" and col_meta.get("supports_time_grouping") is False:
        warnings.append(f"{property_ref}: supports_time_grouping=false, may not be suitable for date filtering")

    return warnings


def validate_task(
    task: Dict[str, Any],
    profile_name: str,
    repo: Neo4jRepo,
    schema_cache: Dict[str, List[str]],
) -> List[str]:
    errs: List[str] = []

    # Metric validation
    if task.get("metric_name"):
        metric = repo.get_metric(profile_name, task["metric_name"])
        if not metric:
            errs.append(f"Unknown metric: {task['metric_name']}")
        else:
            if metric["source_column"] not in schema_cache.get(metric["source_table"], []):
                errs.append(f"Metric source not in live schema: {metric['source_table']}.{metric['source_column']}")

    # Selected properties validation
    for prop in task.get("selected_properties", []):
        if not validate_property_ref(prop, repo, schema_cache):
            errs.append(f"Invalid property_ref: {prop}")
        else:
            errs.extend(_validate_column_flags(prop, "select", repo))

    # Date property validation
    if task.get("date_property"):
        if not validate_property_ref(task["date_property"], repo, schema_cache):
            errs.append(f"Invalid date_property: {task['date_property']}")
        else:
            errs.extend(_validate_column_flags(task["date_property"], "date", repo))

    # Filter validation
    for flt in task.get("filters", []):
        ftype = flt.get("type")
        if ftype == "field":
            if not validate_property_ref(flt.get("property_ref"), repo, schema_cache):
                errs.append(f"Invalid filter property_ref: {flt.get('property_ref')}")
            else:
                errs.extend(_validate_column_flags(flt["property_ref"], "filter", repo))
        elif ftype == "date_range":
            if not validate_property_ref(flt.get("property_ref"), repo, schema_cache):
                errs.append(f"Invalid date filter property_ref: {flt.get('property_ref')}")
            else:
                errs.extend(_validate_column_flags(flt["property_ref"], "date", repo))
            if not normalize_period(flt.get("operator")):
                errs.append(f"Invalid date operator: {flt.get('operator')}")
        else:
            errs.append(f"Unsupported filter type: {ftype}")

    # Path validation
    for branch in task.get("chosen_path", []):
        if isinstance(branch, str) or len(branch) <= 1:
            continue
        rows = repo.find_preferred_path(branch[0], branch[-1], max_hops=max(2, len(branch)))
        if not rows:
            errs.append(f"Chosen path not resolvable: {branch}")

    # ── Aggregation safety enforcement ──
    if task.get("task_type") in {"aggregate", "ranking", "trend"}:
        for branch in task.get("chosen_path", []):
            if isinstance(branch, str) or len(branch) <= 1:
                continue
            for i in range(len(branch) - 1):
                seg_rows = repo.find_preferred_path(branch[i], branch[i + 1], max_hops=2)
                if not seg_rows:
                    seg_rows = repo.find_preferred_path(branch[i + 1], branch[i], max_hops=2)
                if seg_rows:
                    for rel in seg_rows[0]["relationship_path"]:
                        safety = (rel.get("aggregation_safety") or "safe").lower()
                        if safety == "unsafe":
                            errs.append(
                                f"Join {rel.get('from_table')} -> {rel.get('to_table')} has "
                                f"aggregation_safety='unsafe' and will produce wrong aggregate numbers"
                            )
                        elif safety == "preaggregate_required":
                            errs.append(
                                f"Join {rel.get('from_table')} -> {rel.get('to_table')} requires "
                                f"pre-aggregation (aggregation_safety='preaggregate_required'). "
                                f"Metric must be aggregated before this join"
                            )

    # ── Default date property enforcement ──
    if task.get("metric_name"):
        metric = repo.get_metric(profile_name, task["metric_name"])
        if metric and metric.get("default_date_property"):
            default_dp = metric["default_date_property"]
            date_filters = [f for f in task.get("filters", []) if f.get("type") == "date_range"]
            for df in date_filters:
                if df.get("property_ref") and df["property_ref"] != default_dp:
                    errs.append(
                        f"Date filter uses '{df['property_ref']}' but metric "
                        f"'{task['metric_name']}' defines default_date_property='{default_dp}'. "
                        f"Use '{default_dp}' instead"
                    )

    # ── Metric dimension validation (soft warning, not hard error) ──
    # The allowed_dimension_entities is an ontology hint, not a database constraint.
    # If the LLM picks a metric whose allowed dims don't include the target entity,
    # log a warning but allow the query to proceed — the SQL join is still valid.
    if task.get("metric_name") and task.get("selected_properties"):
        metric = repo.get_metric(profile_name, task["metric_name"])
        if metric and metric.get("allowed_dimension_entities"):
            allowed = set(metric["allowed_dimension_entities"])
            fact_entity = metric.get("fact_entity")
            for prop in task.get("selected_properties", []):
                try:
                    entity_name, _ = parse_property_ref(prop)
                except Exception:
                    continue
                if entity_name != fact_entity and entity_name not in allowed:
                    logger.warning(
                        "Metric '%s' does not list '%s' in allowed_dimension_entities %s. "
                        "Proceeding anyway — join path may still be valid.",
                        task["metric_name"], entity_name, sorted(allowed),
                    )

    return errs


def validate_plan(
    plan: Dict[str, Any],
    profile_name: str,
    repo: Neo4jRepo,
    schema_cache: Dict[str, List[str]],
) -> Tuple[bool, List[str]]:
    required = [
        "question_type", "user_question", "database_profile", "intent", "requires_multi_task", "tasks",
        "combine_strategy", "comparison_dimension", "confidence", "needs_clarification", "clarification_reason", "notes"
    ]
    errs = [f"Missing key: {k}" for k in required if k not in plan]
    if errs:
        return False, errs
    if plan["database_profile"] != profile_name:
        errs.append(f"Plan profile mismatch: {plan['database_profile']}")
    if plan.get("question_type") == "general_chat":
        return len(errs) == 0, errs
    if plan.get("needs_clarification") is True:
        try:
            c = float(plan.get("confidence", 0.0))
            if c < 0 or c > 1:
                errs.append("confidence must be between 0 and 1")
        except Exception:
            errs.append("confidence not numeric")
        return len(errs) == 0, errs
    tasks = plan.get("tasks") or []
    if not tasks:
        errs.append("Planner returned no tasks")
        return False, errs
    # Import here to avoid circular dependency at module level
    from app.query_engine.planner import normalize_task_filters
    for task in tasks:
        normalize_task_filters(task)
        errs.extend(validate_task(task, profile_name, repo, schema_cache))
    if plan.get("comparison_dimension"):
        if not validate_property_ref(plan["comparison_dimension"], repo, schema_cache):
            errs.append(f"Invalid comparison_dimension: {plan['comparison_dimension']}")
    try:
        c = float(plan.get("confidence", 0.0))
        if c < 0 or c > 1:
            errs.append("confidence must be between 0 and 1")
    except Exception:
        errs.append("confidence not numeric")
    return len(errs) == 0, errs


def validate_plan_per_task(
    plan: Dict[str, Any],
    profile_name: str,
    repo: Neo4jRepo,
    schema_cache: Dict[str, List[str]],
) -> Tuple[List[str], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Validate each task independently.

    Returns:
        (plan_level_errors, valid_tasks, failed_tasks)
        where failed_tasks = [{"task": dict, "errors": [str]}]

    Plan-level errors (missing keys, profile mismatch, etc.) are returned
    separately because they cannot be fixed by per-task repair.
    """
    required = [
        "question_type", "user_question", "database_profile", "intent",
        "requires_multi_task", "tasks", "combine_strategy",
        "comparison_dimension", "confidence", "needs_clarification",
        "clarification_reason", "notes",
    ]
    plan_errs: List[str] = [f"Missing key: {k}" for k in required if k not in plan]
    if plan["database_profile"] != profile_name:
        plan_errs.append(f"Plan profile mismatch: {plan['database_profile']}")
    if plan_errs:
        return plan_errs, [], []

    # Quick-exit paths that don't involve per-task validation
    if plan.get("question_type") == "general_chat":
        return [], list(plan.get("tasks") or []), []
    if plan.get("needs_clarification") is True:
        return [], list(plan.get("tasks") or []), []

    tasks = plan.get("tasks") or []
    if not tasks:
        return ["Planner returned no tasks"], [], []

    # Import here to avoid circular dependency at module level
    from app.query_engine.planner import normalize_task_filters

    valid_tasks: List[Dict[str, Any]] = []
    failed_tasks: List[Dict[str, Any]] = []

    for task in tasks:
        normalize_task_filters(task)
        task_errs = validate_task(task, profile_name, repo, schema_cache)
        if task_errs:
            failed_tasks.append({"task": task, "errors": task_errs})
        else:
            valid_tasks.append(task)

    # Plan-level checks (non-task)
    if plan.get("comparison_dimension"):
        if not validate_property_ref(plan["comparison_dimension"], repo, schema_cache):
            plan_errs.append(f"Invalid comparison_dimension: {plan['comparison_dimension']}")
    try:
        c = float(plan.get("confidence", 0.0))
        if c < 0 or c > 1:
            plan_errs.append("confidence must be between 0 and 1")
    except Exception:
        plan_errs.append("confidence not numeric")

    return plan_errs, valid_tasks, failed_tasks
