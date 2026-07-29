"""SQL compiler – converts a validated task into a T-SQL SELECT statement.

All functions are synchronous (they only read from Neo4j which is sync).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from app.ontology.neo4j_repository import Neo4jRepo
from app.query_engine.errors import SQLBuildError
from app.query_engine.helpers import (
    DEFAULT_RESULT_LIMIT,
    dedupe,
    normalize_period,
    parse_property_ref,
    quote_sql_literal,
)

logger = logging.getLogger(__name__)


def resolve_join_steps(task: Dict[str, Any], repo: Neo4jRepo) -> List[Dict[str, Any]]:
    """Resolve join steps from the planner's chosen_path.

    For a path like [A, B, C], resolve each consecutive pair (A→B, B→C)
    individually, so intermediate entities are never skipped. Falls back
    to start→end resolution if consecutive pairs fail.
    """
    steps: List[Dict[str, Any]] = []
    for branch in task.get("chosen_path", []):
        if len(branch) <= 1:
            continue

        # Strategy 1: Resolve consecutive pairs (A→B, B→C, ...)
        # This respects the planner's chosen intermediate entities.
        pair_steps: List[Dict[str, Any]] = []
        pair_ok = True
        for i in range(len(branch) - 1):
            seg_start, seg_end = branch[i], branch[i + 1]
            rows = repo.find_preferred_path(seg_start, seg_end, max_hops=2)
            if not rows:
                # Try reverse direction
                rows = repo.find_preferred_path(seg_end, seg_start, max_hops=2)
            if not rows:
                logger.warning(
                    "No preferred path for segment %s -> %s in branch %s, "
                    "falling back to full branch resolution",
                    seg_start, seg_end, branch,
                )
                pair_ok = False
                break
            for s in rows[0]["relationship_path"]:
                pair_steps.append(s)

        if pair_ok and pair_steps:
            steps.extend(pair_steps)
            continue

        # Strategy 2: Fallback – resolve full branch start→end
        rows = repo.find_preferred_path(branch[0], branch[-1], max_hops=max(2, len(branch)))
        if not rows:
            # Try reverse direction as last resort
            rows = repo.find_preferred_path(branch[-1], branch[0], max_hops=max(2, len(branch)))
        if not rows:
            raise SQLBuildError(f"No preferred path for branch: {branch}")
        for s in rows[0]["relationship_path"]:
            steps.append(s)
    return dedupe(steps)


def build_date_where(property_ref: str, operator: str, repo: Neo4jRepo) -> str:
    entity_name, column_name = parse_property_ref(property_ref)
    entity = repo.get_entity(entity_name)
    if not entity:
        raise SQLBuildError(f"Unknown entity in date property: {property_ref}")
    dq = f"[{entity['table_name']}].[{column_name}]"
    op = normalize_period(operator)
    if not op:
        raise SQLBuildError(f"Unsupported date operator: {operator}")
    if op == "last quarter":
        return f"{dq} >= DATEADD(QUARTER, DATEDIFF(QUARTER, 0, GETDATE()) - 1, 0) AND {dq} < DATEADD(QUARTER, DATEDIFF(QUARTER, 0, GETDATE()), 0)"
    if op == "this quarter":
        return f"{dq} >= DATEADD(QUARTER, DATEDIFF(QUARTER, 0, GETDATE()), 0) AND {dq} < DATEADD(QUARTER, DATEDIFF(QUARTER, 0, GETDATE()) + 1, 0)"
    if op == "last month":
        return f"{dq} >= DATEADD(MONTH, DATEDIFF(MONTH, 0, GETDATE()) - 1, 0) AND {dq} < DATEADD(MONTH, DATEDIFF(MONTH, 0, GETDATE()), 0)"
    if op == "this month":
        return f"{dq} >= DATEADD(MONTH, DATEDIFF(MONTH, 0, GETDATE()), 0) AND {dq} < DATEADD(MONTH, DATEDIFF(MONTH, 0, GETDATE()) + 1, 0)"
    if op == "last year":
        return f"{dq} >= DATEADD(YEAR, DATEDIFF(YEAR, 0, GETDATE()) - 1, 0) AND {dq} < DATEADD(YEAR, DATEDIFF(YEAR, 0, GETDATE()), 0)"
    if op in {"this year", "ytd"}:
        return f"{dq} >= DATEADD(YEAR, DATEDIFF(YEAR, 0, GETDATE()), 0) AND {dq} < DATEADD(DAY, 1, CAST(GETDATE() AS DATE))"
    if op == "today":
        return f"CAST({dq} AS DATE) = CAST(GETDATE() AS DATE)"
    if op == "yesterday":
        return f"CAST({dq} AS DATE) = DATEADD(DAY, -1, CAST(GETDATE() AS DATE))"
    if op == "last week":
        return f"{dq} >= DATEADD(WEEK, DATEDIFF(WEEK, 0, GETDATE()) - 1, 0) AND {dq} < DATEADD(WEEK, DATEDIFF(WEEK, 0, GETDATE()), 0)"
    if op == "this week":
        return f"{dq} >= DATEADD(WEEK, DATEDIFF(WEEK, 0, GETDATE()), 0) AND {dq} < DATEADD(WEEK, DATEDIFF(WEEK, 0, GETDATE()) + 1, 0)"
    if op == "mtd":
        return f"{dq} >= DATEADD(MONTH, DATEDIFF(MONTH, 0, GETDATE()), 0) AND {dq} < DATEADD(DAY, 1, CAST(GETDATE() AS DATE))"
    if op == "qtd":
        return f"{dq} >= DATEADD(QUARTER, DATEDIFF(QUARTER, 0, GETDATE()), 0) AND {dq} < DATEADD(DAY, 1, CAST(GETDATE() AS DATE))"
    raise SQLBuildError(f"Unsupported period: {op}")


def build_task_sql(task: Dict[str, Any], profile_name: str, repo: Neo4jRepo) -> str:
    metric = repo.get_metric(profile_name, task["metric_name"]) if task.get("metric_name") else None
    join_steps = resolve_join_steps(task, repo)
    runtime_limit = int(task.get("result_limit", DEFAULT_RESULT_LIMIT) or DEFAULT_RESULT_LIMIT)

    def qf(entity_name: str, column_name: str) -> str:
        entity = repo.get_entity(entity_name)
        if not entity:
            raise SQLBuildError(f"Unknown entity: {entity_name}")
        return f"[{entity['table_name']}].[{column_name}]"

    base_entity_name = metric["fact_entity"] if metric else (task.get("fact_entity") or task.get("target_entity"))
    base_entity = repo.get_entity(base_entity_name) if base_entity_name else None
    if not base_entity:
        raise SQLBuildError("Could not determine base entity")
    base_table = base_entity["table_name"]
    joined = {base_table}
    join_sql: List[str] = []
    pending = join_steps[:]
    progress = True
    while pending and progress:
        progress = False
        remain: List[Dict[str, Any]] = []
        for s in pending:
            jt = (s.get("join_type") or "inner").upper()
            join_keyword = "LEFT JOIN" if jt == "LEFT" else "JOIN"
            if s["from_table"] in joined and s["to_table"] not in joined:
                join_sql.append(f"{join_keyword} [{s['to_table']}] ON [{s['from_table']}].[{s['from_column']}] = [{s['to_table']}].[{s['to_column']}]")
                joined.add(s["to_table"])
                progress = True
            elif s["to_table"] in joined and s["from_table"] not in joined:
                join_sql.append(f"{join_keyword} [{s['from_table']}] ON [{s['from_table']}].[{s['from_column']}] = [{s['to_table']}].[{s['to_column']}]")
                joined.add(s["from_table"])
                progress = True
            elif s["from_table"] in joined and s["to_table"] in joined:
                progress = True
            else:
                remain.append(s)
        pending = remain
    if pending:
        raise SQLBuildError("Could not resolve join order from ontology path")
    select_parts: List[str] = []
    group_parts: List[str] = []
    for prop in task.get("selected_properties", []):
        entity_name, column_name = parse_property_ref(prop)
        alias = f"{entity_name}_{column_name}".lower()
        select_parts.append(f"{qf(entity_name, column_name)} AS [{alias}]")
        if task.get("task_type") in {"aggregate", "ranking", "trend"}:
            group_parts.append(qf(entity_name, column_name))
    if task.get("metric_name"):
        if not metric:
            raise SQLBuildError("Aggregate/ranking/trend task missing metric")
        source_expr = f"[{metric['source_table']}].[{metric['source_column']}]"
        agg = metric["aggregation"]
        if agg == "count_distinct":
            metric_expr = f"COUNT(DISTINCT {source_expr})"
        elif agg == "sum":
            metric_expr = f"SUM(TRY_CAST(NULLIF({source_expr}, '') AS DECIMAL(38,10)))"
        elif agg == "avg":
            metric_expr = f"AVG(TRY_CAST(NULLIF({source_expr}, '') AS DECIMAL(38,10)))"
        elif agg == "derived_ratio":
            fact_entity = repo.get_entity(metric["fact_entity"])
            if not fact_entity or not fact_entity.get("primary_key"):
                raise SQLBuildError(f"derived_ratio metric requires fact entity primary key: {metric['metric_name']}")
            pk_expr = f"[{metric['source_table']}].[{fact_entity['primary_key']}]"
            # Read positive indicator from metric metadata; fallback to 'Y'
            positive_val = metric.get("positive_value", "Y")
            metric_expr = (
                f"CAST(COUNT(DISTINCT CASE WHEN {source_expr} = {quote_sql_literal(positive_val)} THEN {pk_expr} END) AS DECIMAL(38,10)) "
                f"/ NULLIF(COUNT(DISTINCT {pk_expr}), 0) * 100"
            )
        else:
            metric_expr = source_expr
        select_parts.append(f"{metric_expr} AS [metric_value]")
    else:
        if task.get("task_type") in {"aggregate", "ranking", "trend"}:
            count_entity_name = task.get("fact_entity") or task.get("target_entity") or base_entity_name
            count_entity = repo.get_entity(str(count_entity_name))
            if not count_entity or not count_entity.get("primary_key"):
                raise SQLBuildError(f"Generic count requires entity primary key: {count_entity_name}")
            pk_expr = f"[{count_entity['table_name']}].[{count_entity['primary_key']}]"
            metric_expr = f"COUNT(DISTINCT {pk_expr})"
            select_parts.append(f"{metric_expr} AS [metric_value]")
        else:
            if not select_parts:
                select_parts.append(f"[{base_table}].*")
    where_parts: List[str] = []
    for flt in task.get("filters", []):
        ftype = flt.get("type")
        if ftype == "field":
            entity_name, column_name = parse_property_ref(flt.get("property_ref"))
            qual = qf(entity_name, column_name)
            op = flt.get("operator")
            val = flt.get("value")
            if op == "equals":
                where_parts.append(f"{qual} = {quote_sql_literal(val)}")
            elif op == "like":
                where_parts.append(f"{qual} LIKE {quote_sql_literal('%' + str(val) + '%')}")
            elif op == "in" and isinstance(val, list) and val:
                where_parts.append(f"{qual} IN ({', '.join([quote_sql_literal(v) for v in val])})")
        elif ftype == "date_range":
            where_parts.append(build_date_where(flt.get("property_ref"), flt.get("operator"), repo))

    # ── Apply default entity filters from graph ──
    # Collect all entities involved in this query
    involved_entity_names = {base_entity_name}
    for prop in task.get("selected_properties", []):
        try:
            en, _ = parse_property_ref(prop)
            involved_entity_names.add(en)
        except Exception:
            pass
    for flt in task.get("filters", []):
        if flt.get("property_ref"):
            try:
                en, _ = parse_property_ref(flt["property_ref"])
                involved_entity_names.add(en)
            except Exception:
                pass

    # Track which table.column combos already have user-specified filters
    existing_filter_cols = set()
    for flt in task.get("filters", []):
        if flt.get("property_ref"):
            try:
                en, cn = parse_property_ref(flt["property_ref"])
                entity = repo.get_entity(en)
                if entity:
                    existing_filter_cols.add((entity["table_name"], cn))
            except Exception:
                pass

    for ent_name in involved_entity_names:
        default_filters = repo.get_entity_default_filters(ent_name)
        entity = repo.get_entity(ent_name)
        if not entity or not default_filters:
            continue
        tbl = entity["table_name"]
        schema = entity.get("schema_name") or "dbo"
        for df in default_filters:
            col = df["column"]
            # Skip if user already filters on this column
            if (tbl, col) in existing_filter_cols:
                continue
            qual = f"[{tbl}].[{col}]"
            df_op = (df.get("operator") or "equals").lower()
            df_val = df["value"]
            if df_op == "equals":
                where_parts.append(f"{qual} = {quote_sql_literal(df_val)}")
            elif df_op == "not_equals":
                where_parts.append(f"{qual} != {quote_sql_literal(df_val)}")
            elif df_op == "is_null":
                where_parts.append(f"{qual} IS NULL")
            elif df_op == "is_not_null":
                where_parts.append(f"{qual} IS NOT NULL")

    sql_lines = [
        f"SELECT TOP {runtime_limit}",
        "    " + ",\n    ".join(select_parts),
        f"FROM [{base_table}]",
    ]
    sql_lines.extend(join_sql)
    if where_parts:
        sql_lines.append("WHERE " + "\n  AND ".join(where_parts))
    if group_parts:
        sql_lines.append("GROUP BY " + ", ".join(group_parts))
    sort = task.get("sort") or {}
    sort_field = sort.get("field")
    sort_dir = (sort.get("direction") or "desc").upper()
    if task.get("metric_name") or task.get("task_type") in {"aggregate", "ranking", "trend"}:
        if sort_field == "metric_value" or not sort_field:
            sql_lines.append(f"ORDER BY metric_value {sort_dir}")
        elif sort_field and "." in str(sort_field):
            se, sc = parse_property_ref(sort_field)
            sql_lines.append(f"ORDER BY {qf(se, sc)} {sort_dir}")
    else:
        if sort_field and "." in str(sort_field):
            se, sc = parse_property_ref(sort_field)
            sql_lines.append(f"ORDER BY {qf(se, sc)} {sort_dir}")
        elif select_parts:
            sql_lines.append("ORDER BY 1")
    final_sql = "\n".join(sql_lines)
    logger.info(f"Generated SQL for task {task.get('task_id')} ->\n{final_sql}")
    return final_sql
