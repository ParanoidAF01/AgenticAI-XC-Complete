"""Plan validation – synchronous checks against the ontology and live schema."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

from app.ontology.neo4j_repository import Neo4jRepo
from app.query_engine.helpers import normalize_period, parse_property_ref

logger = logging.getLogger(__name__)


def validate_property_ref(property_ref: str, repo: Neo4jRepo, schema_cache: Dict[str, List[str]]) -> bool:
    try:
        entity_name, column_name = parse_property_ref(property_ref)
        entity = repo.get_entity(entity_name)
        if not entity:
            return False
        table_name = entity["table_name"]
        return column_name in schema_cache.get(table_name, [])
    except Exception:
        return False


def validate_task(task: Dict[str, Any], profile_name: str, repo: Neo4jRepo, schema_cache: Dict[str, List[str]]) -> List[str]:
    errs: List[str] = []
    if task.get("metric_name"):
        metric = repo.get_metric(profile_name, task["metric_name"])
        if not metric:
            errs.append(f"Unknown metric: {task['metric_name']}")
        else:
            if metric["source_column"] not in schema_cache.get(metric["source_table"], []):
                errs.append(f"Metric source not in live schema: {metric['source_table']}.{metric['source_column']}")
    for prop in task.get("selected_properties", []):
        if not validate_property_ref(prop, repo, schema_cache):
            errs.append(f"Invalid property_ref: {prop}")
    if task.get("date_property") and not validate_property_ref(task["date_property"], repo, schema_cache):
        errs.append(f"Invalid date_property: {task['date_property']}")
    for flt in task.get("filters", []):
        ftype = flt.get("type")
        if ftype == "field":
            if not validate_property_ref(flt.get("property_ref"), repo, schema_cache):
                errs.append(f"Invalid filter property_ref: {flt.get('property_ref')}")
        elif ftype == "date_range":
            if not validate_property_ref(flt.get("property_ref"), repo, schema_cache):
                errs.append(f"Invalid date filter property_ref: {flt.get('property_ref')}")
            if not normalize_period(flt.get("operator")):
                errs.append(f"Invalid date operator: {flt.get('operator')}")
        else:
            errs.append(f"Unsupported filter type: {ftype}")
    for branch in task.get("chosen_path", []):
        if len(branch) <= 1:
            continue
        rows = repo.find_preferred_path(branch[0], branch[-1], max_hops=max(2, len(branch)))
        if not rows:
            errs.append(f"Chosen path not resolvable: {branch}")
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
