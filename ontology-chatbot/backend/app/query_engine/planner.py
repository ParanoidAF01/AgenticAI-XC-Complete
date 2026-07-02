"""Query planner – builds the ontology context and calls the LLM to produce
a structured execution plan.

build_plan is async because it calls call_llm.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from app.ontology.neo4j_repository import Neo4jRepo
from app.query_engine.errors import PlannerError
from app.query_engine.helpers import (
    DEFAULT_RESULT_LIMIT,
    MAX_RESULT_LIMIT,
    extract_json_text,
    make_json_safe,
    normalize_period,
    normalize_text,
)
from app.query_engine.llm_client import call_llm
from app.query_engine.plan_validator import validate_plan
from app.query_engine.prompts import PLANNER_V2_PROMPT
from app.query_engine.router import extract_candidate_terms

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Ontology context builder
# ------------------------------------------------------------------

def build_planner_context(profile_name: str, question: str, repo: Neo4jRepo) -> Dict[str, Any]:
    nq = normalize_text(question)
    candidate_terms = extract_candidate_terms(nq)
    term_hits = repo.lookup_terms(profile_name, candidate_terms)
    entities = repo.get_entities(profile_name)
    metrics = repo.get_metrics(profile_name)
    relationships = repo.get_relationships(profile_name)
    matched_term_summary = []
    for r in term_hits[:50]:
        matched_term_summary.append(
            {
                "input_term": r["input_term"],
                "term_text": r["term_text"],
                "maps_to_type": r["maps_to_type"],
                "maps_to_name": r["maps_to_name"],
                "priority": r["priority"],
                "notes": r.get("notes"),
            }
        )
    entity_summary = []
    for e in entities:
        entity_summary.append(
            {
                "entity_name": e["entity_name"],
                "canonical_name": e.get("canonical_name"),
                "entity_type": e.get("entity_type"),
                "business_role": e.get("business_role"),
                "grain_description": e.get("grain_description"),
                "default_list_fields": e.get("default_list_fields", []),
                "default_detail_fields": e.get("default_detail_fields", []),
                "groupable_fields": e.get("groupable_fields", []),
                "filterable_fields": e.get("filterable_fields", []),
                "date_fields": e.get("date_fields", []),
                "measure_fields": e.get("measure_fields", []),
                "synonyms": e.get("synonyms", []),
                "description": e.get("description"),
            }
        )
    metric_summary = []
    for m in metrics:
        metric_summary.append(
            {
                "metric_name": m["metric_name"],
                "canonical_name": m.get("canonical_name"),
                "fact_entity": m.get("fact_entity"),
                "source_table": m.get("source_table"),
                "source_column": m.get("source_column"),
                "aggregation": m.get("aggregation"),
                "default_date_property": m.get("default_date_property"),
                "allowed_dimension_entities": m.get("allowed_dimension_entities", []),
                "default_group_properties": m.get("default_group_properties", []),
                "synonyms": m.get("synonyms", []),
                "description": m.get("description"),
            }
        )
    rel_summary = []
    for r in relationships:
        rel_summary.append(
            {
                "from_entity": r["from_entity"],
                "to_entity": r["to_entity"],
                "relationship_name": r["relationship_name"],
                "business_meaning": r.get("business_meaning"),
                "path_priority": r.get("path_priority"),
                "duplication_risk": r.get("duplication_risk"),
                "aggregation_safety": r.get("aggregation_safety"),
                "when_to_use": r.get("when_to_use"),
                "when_not_to_use": r.get("when_not_to_use"),
                "question_hints": r.get("question_hints", []),
            }
        )
    logger.info(
        f"Ontology context built -> term_hits={len(matched_term_summary)}, entities={len(entity_summary)}, metrics={len(metric_summary)}, rels={len(rel_summary)}"
    )
    return {
        "normalized_question": nq,
        "matched_terms": matched_term_summary,
        "entities": entity_summary,
        "metrics": metric_summary,
        "relationships": rel_summary,
    }


# ------------------------------------------------------------------
# Filter normalisation (used by both planner and validator)
# ------------------------------------------------------------------

def normalize_task_filters(task: Dict[str, Any]) -> Dict[str, Any]:
    filters = task.get("filters") or []
    normalized: List[Dict[str, Any]] = []
    result_limit = task.get("result_limit", DEFAULT_RESULT_LIMIT)
    for flt in filters:
        if not isinstance(flt, dict):
            continue
        ftype = flt.get("type")
        if ftype == "limit":
            try:
                result_limit = min(max(int(flt.get("value", DEFAULT_RESULT_LIMIT)), 1), MAX_RESULT_LIMIT)
            except Exception:
                pass
            continue
        if ftype == "date_range":
            op = normalize_period(flt.get("operator"))
            if op:
                normalized.append({"type": "date_range", "property_ref": flt.get("property_ref"), "operator": op, "value": None})
            continue
        if ftype == "field":
            normalized.append(
                {
                    "type": "field",
                    "property_ref": flt.get("property_ref"),
                    "operator": flt.get("operator"),
                    "value": flt.get("value"),
                }
            )
            continue
    task["filters"] = normalized
    task["result_limit"] = result_limit
    return task


# ------------------------------------------------------------------
# Plan builder (async – calls LLM)
# ------------------------------------------------------------------

async def build_plan(
    profile_name: str,
    question: str,
    route: Dict[str, Any],
    context: Dict[str, Any],
    repo: Neo4jRepo,
    schema_cache: Dict[str, List[str]],
) -> Dict[str, Any]:
    if route["route"] == "general_chat":
        return {
            "question_type": "general_chat",
            "user_question": question,
            "database_profile": profile_name,
            "intent": "general_chat",
            "requires_multi_task": False,
            "tasks": [],
            "combine_strategy": "none",
            "comparison_dimension": None,
            "confidence": 1.0,
            "needs_clarification": False,
            "clarification_reason": "",
            "notes": ["general_chat_route"]
        }
    payload = {
        "route": route,
        "user_question": question,
        "database_profile": profile_name,
        "ontology_context": context,
    }
    raw = await call_llm(
        [
            {"role": "system", "content": PLANNER_V2_PROMPT},
            {"role": "user", "content": json.dumps(make_json_safe(payload), indent=2)},
        ],
        max_tokens=2400,
    )
    logger.info(f"Planner raw LLM response -> {raw[:1800]}")
    try:
        plan = json.loads(extract_json_text(raw))
    except Exception as e:
        raise PlannerError(f"Planner returned invalid JSON: {raw}") from e
    ok, errs = validate_plan(plan, profile_name, repo, schema_cache)
    if not ok:
        repair_payload = {
            "original_question": question,
            "route": route,
            "ontology_context": context,
            "invalid_plan": plan,
            "validation_errors": errs,
            "instruction": "Fix the JSON plan. Keep only schema-valid values allowed by ontology context. Return JSON only.",
        }
        raw2 = await call_llm(
            [
                {"role": "system", "content": PLANNER_V2_PROMPT},
                {"role": "user", "content": json.dumps(make_json_safe(repair_payload), indent=2)},
            ],
            max_tokens=2600,
        )
        logger.info(f"Planner repair raw LLM response -> {raw2[:1800]}")
        try:
            plan = json.loads(extract_json_text(raw2))
        except Exception as e:
            raise PlannerError(f"Planner repair returned invalid JSON: {raw2}") from e
        ok, errs = validate_plan(plan, profile_name, repo, schema_cache)
        if not ok:
            raise PlannerError("Planner validation failed: " + "; ".join(errs))
    logger.info("Planner V2 JSON validated successfully")
    return plan
