from __future__ import annotations
import json
import os
import re
import time
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote_plus
import requests
import streamlit as st
from dotenv import load_dotenv
from neo4j import GraphDatabase
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

# ============================================================
# Config
# ============================================================
load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env", override=True)
APP_TITLE = "Ontology-Driven Database Chatbot"
APP_SUBTITLE = "IDP Stage + Reporting • Anthropic + Neo4j + MSSQL"
SUPPORTED_DB_PROFILES = ["idp_reporting", "idp_stage_ext"]
MAX_QUESTION_LENGTH = 1500
DEFAULT_RESULT_LIMIT = 25
MAX_RESULT_LIMIT = 500
MAX_SQL_REPAIR_ATTEMPTS = 3

# ============================================================
# Errors
# ============================================================
class AppError(Exception):
    pass

class OntologyProfileError(AppError):
    pass

class PlannerError(AppError):
    pass

class LLMError(AppError):
    pass

class SQLBuildError(AppError):
    pass

class SQLValidationError(AppError):
    pass

class SQLExecutionError(AppError):
    pass

# ============================================================
# Session + logging
# ============================================================
def init_state() -> None:
    defaults = {
        "logs": [],
        "connected": False,
        "developer_mode": False,
        "selected_profile": "idp_reporting",
        "db_engine": None,
        "neo4j_repo": None,
        "entity_table_lookup": {},
        "schema_cache": {},
        "last_router": None,
        "last_plan": None,
        "last_sql": None,
        "last_result": None,
        "last_error": None,
        "mssql_server": "",
        "mssql_port": "1433",
        "mssql_username": "",
        "mssql_password": "",
        "chat_history": [],  # NEW: Store conversation history
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

def log(msg: str, level: str = "INFO") -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [{level}] {msg}"
    print(line)
    st.session_state.logs.append(line)

# ============================================================
# Generic helpers
# ============================================================
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

def is_greeting_or_general(q: str) -> bool:
    greeting_terms = {"hi", "hello", "hey", "thanks", "thank you", "help", "namaste", "hola"}
    return q in greeting_terms or any(q.startswith(x) for x in ["hi ", "hello ", "hey ", "thanks ", "thank you "])

def build_general_llm_answer(question: str) -> str:
    payload = {"user_message": question}
    return call_llm(
        [
            {"role": "system", "content": GENERAL_CHAT_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(payload, indent=2)},
        ],
        max_tokens=400,
    ).strip()

def extract_candidate_terms(q: str) -> List[str]:
    toks = q.split()
    terms = set()
    for n in (4, 3, 2, 1):
        for i in range(len(toks) - n + 1):
            terms.add(" ".join(toks[i:i+n]))
    return sorted(terms, key=lambda x: (-len(x.split()), x))

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
    val = str(val).replace("'", "''")
    return f"'{val}'"

# ============================================================
# LLM
# ============================================================
ROUTER_PROMPT = """
You are a router for a business database chatbot.
Classify the message into one of these routes:
- general_chat
- simple_db
- complex_db
Use general_chat only if the user is not asking about business data/database results.
Use complex_db if the user asks compare, trend, rank, top N, multiple metrics, or multi-part analytical questions.
Respond JSON only in this exact shape:
{"route":"general_chat|simple_db|complex_db","reason":"short reason"}
""".strip()

GENERAL_CHAT_SYSTEM_PROMPT = """
You are a helpful business assistant inside a database chatbot application.
If the user message is not asking for a database/data question, respond naturally and helpfully in plain language.
Do not invent database results.
Return plain text only.
""".strip()

PLANNER_V2_PROMPT = """
You are an ontology-guided query planner for an insurance database chatbot.
Your job is to understand the user question and return a structured execution plan.
The active database profile may be idp_reporting or idp_stage_ext.
You must use only the provided ontology context for the active profile.
You must NOT generate SQL.
You must NOT invent business entities, metrics, paths, or properties outside the provided ontology context.
Return JSON only. No markdown. No backticks.
Planner schema exactly:
{
  "question_type": "scalar_aggregate|grouped_aggregate|entity_list|detail_lookup|compare|trend|ranking|general_chat",
  "user_question": "string",
  "database_profile": "string",
  "intent": "count|sum|list|detail_lookup|compare|trend|ranking|general_chat",
  "requires_multi_task": true,
  "tasks": [
    {
      "task_id": "t1",
      "task_type": "aggregate|list|detail|ranking|trend",
      "target_entity": "string|null",
      "fact_entity": "string|null",
      "metric_name": "string|null",
      "selected_properties": ["Entity.Column"],
      "date_property": "Entity.Column|null",
      "filters": [
        {"type":"field","property_ref":"Entity.Column","operator":"equals|like|in","value":"..."},
        {"type":"date_range","property_ref":"Entity.Column","operator":"last quarter|this quarter|last month|this month|last year|this year|today|yesterday|ytd","value":null},
        {"type":"limit","value":5}
      ],
      "path_candidates": [["EntityA","EntityB"]],
      "chosen_path": [["EntityA","EntityB"]],
      "result_limit": 25,
      "sort": {"field":"metric_value|Entity.Column|null","direction":"asc|desc|null"}
    }
  ],
  "combine_strategy": "none|compare_on_dimension|trend_merge|ranking",
  "comparison_dimension": "Entity.Column|null",
  "confidence": 0.0,
  "needs_clarification": false,
  "clarification_reason": "",
  "notes": ["string"]
}
Rules:
- Use one or more tasks depending on complexity.
- For simple totals, use one aggregate task.
- For questions like "tell me something about any 5 policies", use entity_list with list task and a limit filter.
- For grouped questions, choose selected_properties that are true group/display properties.
- If question needs compare of multiple metrics, use multiple tasks and combine_strategy=compare_on_dimension.
- If question asks top N, use ranking with sort direction desc and limit.
- Use the entity metadata and relationship metadata to choose the best path.
- Prefer direct fact-to-dimension relationships when transaction/policy context is not required.
- Avoid bridge entities unless the question explicitly needs deep business context.
- In idp_stage_ext, bridge entities such as POL_TX_BRIDGE, POL_LOCATION_RISK_BRIDGE, and POL_POLICY_PARTY_ROLE_BRIDGE should be used only when direct relationships are not sufficient.
- If exact wording is imperfect, infer using ontology descriptions and synonyms.
- If still genuinely unclear, ask for clarification.
""".strip()

ANSWER_SYSTEM_PROMPT = """
You are a business answer generation assistant for an ontology-driven insurance database chatbot.
Use only the provided execution summary and results.
Do not invent facts.
Do not mention technical internals unless explicitly asked.
If multiple result sets are provided, compare or summarize them naturally.
If no rows are found, say that clearly.
Return plain text only.
""".strip()

SQL_REPAIR_PROMPT = """
You are a SQL Server T-SQL repair assistant.

Your job is to fix only SQL syntax / compilation issues in the provided query.

Rules:
- Return SQL only. No markdown. No explanation.
- Preserve business intent as much as possible.
- Do NOT invent new tables, columns, joins, or filters outside the provided task and schema context.
- Do NOT change the meaning unless required to make the SQL compile.
- Keep SELECT/GROUP BY/ORDER BY logically consistent.
- If aggregate expressions are used, make sure non-aggregated selected columns are included in GROUP BY.
- If ORDER BY references a non-selected/non-grouped field in an aggregated query, correct it safely.
- Prefer ordering by metric_value for aggregate/ranking/trend queries unless task context clearly requires otherwise.
- Preserve TOP clause.
- Preserve filters and joins unless they are the direct source of compilation failure.
- Output a single valid SQL Server SELECT statement only.
""".strip()


def get_llm_config() -> Dict[str, str]:
    return {
        "provider": os.getenv("LLM_PROVIDER", "anthropic").strip().lower(),
        "api_key": os.getenv("LLM_API_KEY", "").strip(),
        "endpoint": os.getenv("LLM_ENDPOINT", "").strip(),
        "model": os.getenv("LLM_MODEL", "").strip(),
        "api_version": os.getenv("LLM_API_VERSION", "2023-06-01").strip(),
    }

def call_llm(messages: List[Dict[str, str]], max_tokens: int = 1800) -> str:
    cfg = get_llm_config()
    if cfg["provider"] != "anthropic":
        raise LLMError("This app.py is built for Anthropic only")
    if not all([cfg["api_key"], cfg["endpoint"], cfg["model"]]):
        raise LLMError("Missing LLM_API_KEY / LLM_ENDPOINT / LLM_MODEL")
    headers = {
        "x-api-key": cfg["api_key"],
        "anthropic-version": cfg["api_version"] or "2023-06-01",
        "content-type": "application/json",
    }
    system_parts = [m["content"] for m in messages if m["role"] == "system"]
    non_system = [{"role": m["role"], "content": m["content"]} for m in messages if m["role"] != "system"]
    payload = {
        "model": cfg["model"],
        "max_tokens": max_tokens,
        "temperature": 0.0,
        "system": "\n\n".join(system_parts),
        "messages": non_system,
    }
    log("Calling Anthropic LLM")
    resp = requests.post(cfg["endpoint"].rstrip("/"), headers=headers, json=payload, timeout=120)
    if resp.status_code >= 300:
        raise LLMError(f"Anthropic call failed: {resp.status_code} {resp.text}")
    data = resp.json()
    texts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
    final_text = "\n".join(texts).strip()
    if not final_text:
        raise LLMError(f"Anthropic returned empty text response: {data}")
    return final_text

def llm_json(system_prompt: str, user_payload: Dict[str, Any], max_tokens: int = 1800) -> Dict[str, Any]:
    raw = call_llm(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(make_json_safe(user_payload), indent=2)},
        ],
        max_tokens=max_tokens,
    )
    return json.loads(extract_json_text(raw))


# ============================================================
# Neo4j repository (Ontology V2)
# ============================================================
class Neo4jRepo:
    def __init__(self, uri: str, username: str, password: str):
        self.driver = GraphDatabase.driver(uri, auth=(username, password))

    def close(self) -> None:
        self.driver.close()

    def _run(self, query: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        params = params or {}
        with self.driver.session() as session:
            return [r.data() for r in session.run(query, params)]

    def test(self) -> bool:
        rows = self._run("RETURN 1 AS ok")
        return bool(rows and rows[0]["ok"] == 1)

    def get_profile(self, profile_name: str) -> Optional[Dict[str, Any]]:
        rows = self._run(
            """
            MATCH (p:OntologyDatabaseProfile {profile_name:$profile_name})
            RETURN p.profile_name AS profile_name,
                   p.ontology_status AS ontology_status,
                   p.display_name AS display_name,
                   p.description AS description
            """,
            {"profile_name": profile_name},
        )
        return rows[0] if rows else None

    def get_entity_table_lookup(self, profile_name: str) -> Dict[str, str]:
        rows = self._run(
            """
            MATCH (:OntologyDatabaseProfile {profile_name:$profile_name})-[:USES_ENTITY]->(e:OntologyEntity)
            RETURN e.entity_name AS entity_name, e.table_name AS table_name
            """,
            {"profile_name": profile_name},
        )
        return {r["entity_name"]: r["table_name"] for r in rows}

    def get_entities(self, profile_name: str) -> List[Dict[str, Any]]:
        return self._run(
            """
            MATCH (:OntologyDatabaseProfile {profile_name:$profile_name})-[:USES_ENTITY]->(e:OntologyEntity)
            RETURN e.entity_name AS entity_name,
                   e.canonical_name AS canonical_name,
                   e.table_name AS table_name,
                   e.schema_name AS schema_name,
                   e.entity_type AS entity_type,
                   e.business_role AS business_role,
                   e.grain_description AS grain_description,
                   e.primary_key AS primary_key,
                   e.business_keys AS business_keys,
                   e.default_display_fields AS default_display_fields,
                   e.default_list_fields AS default_list_fields,
                   e.default_detail_fields AS default_detail_fields,
                   e.groupable_fields AS groupable_fields,
                   e.filterable_fields AS filterable_fields,
                   e.date_fields AS date_fields,
                   e.status_fields AS status_fields,
                   e.measure_fields AS measure_fields,
                   e.synonyms AS synonyms,
                   e.description AS description
            ORDER BY e.entity_name
            """,
            {"profile_name": profile_name},
        )

    def get_entity(self, entity_name: str) -> Optional[Dict[str, Any]]:
        rows = self._run(
            """
            MATCH (e:OntologyEntity {entity_name:$entity_name})
            RETURN e.entity_name AS entity_name,
                   e.canonical_name AS canonical_name,
                   e.table_name AS table_name,
                   e.schema_name AS schema_name,
                   e.entity_type AS entity_type,
                   e.business_role AS business_role,
                   e.grain_description AS grain_description,
                   e.primary_key AS primary_key,
                   e.business_keys AS business_keys,
                   e.default_display_fields AS default_display_fields,
                   e.default_list_fields AS default_list_fields,
                   e.default_detail_fields AS default_detail_fields,
                   e.groupable_fields AS groupable_fields,
                   e.filterable_fields AS filterable_fields,
                   e.date_fields AS date_fields,
                   e.status_fields AS status_fields,
                   e.measure_fields AS measure_fields,
                   e.synonyms AS synonyms,
                   e.description AS description
            """,
            {"entity_name": entity_name},
        )
        return rows[0] if rows else None

    def get_metrics(self, profile_name: str) -> List[Dict[str, Any]]:
        return self._run(
            """
            MATCH (:OntologyDatabaseProfile {profile_name:$profile_name})-[:USES_METRIC]->(m:OntologyMetric)
            RETURN m.metric_name AS metric_name,
                   m.canonical_name AS canonical_name,
                   m.fact_entity AS fact_entity,
                   m.source_table AS source_table,
                   m.source_column AS source_column,
                   m.aggregation AS aggregation,
                   m.default_date_property AS default_date_property,
                   m.allowed_dimension_entities AS allowed_dimension_entities,
                   m.default_group_properties AS default_group_properties,
                   m.synonyms AS synonyms,
                   m.description AS description
            ORDER BY m.metric_name
            """,
            {"profile_name": profile_name},
        )

    def get_metric(self, profile_name: str, metric_name: str) -> Optional[Dict[str, Any]]:
        rows = self._run(
            """
            MATCH (:OntologyDatabaseProfile {profile_name:$profile_name})-[:USES_METRIC]->(m:OntologyMetric {metric_name:$metric_name})
            RETURN m.metric_name AS metric_name,
                   m.canonical_name AS canonical_name,
                   m.fact_entity AS fact_entity,
                   m.source_table AS source_table,
                   m.source_column AS source_column,
                   m.aggregation AS aggregation,
                   m.default_date_property AS default_date_property,
                   m.allowed_dimension_entities AS allowed_dimension_entities,
                   m.default_group_properties AS default_group_properties,
                   m.synonyms AS synonyms,
                   m.description AS description
            """,
            {"profile_name": profile_name, "metric_name": metric_name},
        )
        return rows[0] if rows else None

    def get_terms(self, profile_name: str) -> List[Dict[str, Any]]:
        return self._run(
            """
            MATCH (:OntologyDatabaseProfile {profile_name:$profile_name})-[:USES_TERM]->(t:OntologyTerm)
            RETURN t.term_key AS term_key,
                   t.term_text AS term_text,
                   t.normalized_term AS normalized_term,
                   t.maps_to_type AS maps_to_type,
                   t.maps_to_name AS maps_to_name,
                   t.priority AS priority,
                   t.notes AS notes
            ORDER BY t.priority DESC
            """,
            {"profile_name": profile_name},
        )

    def lookup_terms(self, profile_name: str, terms: List[str]) -> List[Dict[str, Any]]:
        return self._run(
            """
            UNWIND $terms AS input_term
            MATCH (:OntologyDatabaseProfile {profile_name:$profile_name})-[:USES_TERM]->(t:OntologyTerm)
            WHERE coalesce(t.active_flag,true)=true
              AND (
                    t.normalized_term = input_term
                 OR input_term CONTAINS t.normalized_term
                 OR t.normalized_term CONTAINS input_term
              )
            RETURN input_term,
                   t.term_key AS term_key,
                   t.term_text AS term_text,
                   t.normalized_term AS normalized_term,
                   t.maps_to_type AS maps_to_type,
                   t.maps_to_name AS maps_to_name,
                   t.priority AS priority,
                   t.notes AS notes
            ORDER BY t.priority DESC
            """,
            {"profile_name": profile_name, "terms": terms},
        )

    def get_relationships(self, profile_name: str) -> List[Dict[str, Any]]:
        return self._run(
            """
            MATCH (p:OntologyDatabaseProfile {profile_name:$profile_name})-[:USES_ENTITY]->(a:OntologyEntity)
            MATCH (a)-[r:ONTOLOGY_RELATION]->(b:OntologyEntity)
            MATCH (p)-[:USES_ENTITY]->(b)
            RETURN a.entity_name AS from_entity,
                b.entity_name AS to_entity,
                r.relationship_name AS relationship_name,
                r.business_meaning AS business_meaning,
                r.from_table AS from_table,
                r.from_column AS from_column,
                r.to_table AS to_table,
                r.to_column AS to_column,
                r.cardinality AS cardinality,
                r.join_type AS join_type,
                r.path_priority AS path_priority,
                r.is_primary_path AS is_primary_path,
                r.duplication_risk AS duplication_risk,
                r.aggregation_safety AS aggregation_safety,
                r.bridge_flag AS bridge_flag,
                r.when_to_use AS when_to_use,
                r.when_not_to_use AS when_not_to_use,
                r.question_hints AS question_hints,
                r.description AS description
            ORDER BY r.path_priority DESC
            """,
            {"profile_name": profile_name},
    )

    def find_preferred_path(self, start_entity: str, end_entity: str, max_hops: int = 4) -> List[Dict[str, Any]]:
        query = f"""
        MATCH p=(start:OntologyEntity {{entity_name:$start_entity}})-[rels:ONTOLOGY_RELATION*1..{max_hops}]->(end:OntologyEntity {{entity_name:$end_entity}})
        WHERE ALL(r IN rels WHERE coalesce(r.is_primary_path,false)=true)
        RETURN [n IN nodes(p) | n.entity_name] AS entity_path,
               [r IN rels | {{
                    relationship_name:r.relationship_name,
                    from_table:r.from_table,
                    from_column:r.from_column,
                    to_table:r.to_table,
                    to_column:r.to_column,
                    cardinality:r.cardinality,
                    path_priority:r.path_priority,
                    duplication_risk:r.duplication_risk,
                    aggregation_safety:r.aggregation_safety,
                    business_meaning:r.business_meaning,
                    when_to_use:r.when_to_use,
                    when_not_to_use:r.when_not_to_use
               }}] AS relationship_path,
               reduce(score = 0, r IN rels | score + (100 - coalesce(r.path_priority,50)) + CASE WHEN coalesce(r.duplication_risk,'')='high' THEN 50 WHEN coalesce(r.duplication_risk,'')='medium' THEN 10 ELSE 0 END) AS path_score
        ORDER BY path_score ASC, size(rels) ASC
        LIMIT 5
        """
        return self._run(query, {"start_entity": start_entity, "end_entity": end_entity})

# ============================================================
# MSSQL connection
# ============================================================
def build_mssql_uri(server: str, port: str, db_name: str, username: str, password: str) -> str:
    if not all([server, db_name, username, password]):
        raise AppError("Missing required MSSQL connection details")
    safe_password = quote_plus(password)
    port = port or "1433"
    return f"mssql+pyodbc://{username}:{safe_password}@{server}:{port}/{db_name}?driver=ODBC+Driver+17+for+SQL+Server&Encrypt=yes&TrustServerCertificate=yes"

def connect_mssql(server: str, port: str, db_name: str, username: str, password: str) -> Engine:
    uri = build_mssql_uri(server, port, db_name, username, password)
    log(f"Building MSSQL engine for server='{server}', db='{db_name}'")
    engine = create_engine(uri)
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    log("MSSQL connection test successful")
    return engine

def connect_neo4j_from_env() -> Neo4jRepo:
    uri = os.getenv("NEO4J_URI", "").strip()
    user = os.getenv("NEO4J_USERNAME", "").strip()
    pwd = os.getenv("NEO4J_PASSWORD", "").strip()
    if not all([uri, user, pwd]):
        raise AppError("Missing Neo4j env vars: NEO4J_URI / NEO4J_USERNAME / NEO4J_PASSWORD")
    repo = Neo4jRepo(uri=uri, username=user, password=pwd)
    if not repo.test():
        raise AppError("Neo4j connection test failed")
    log("Neo4j Aura connection successful")
    return repo

def introspect_schema(engine: Engine, tables_of_interest: List[str]) -> Dict[str, List[str]]:
    inspector = inspect(engine)
    available = set(inspector.get_table_names())
    cache: Dict[str, List[str]] = {}
    for t in dedupe(tables_of_interest):
        cache[t] = [c["name"] for c in inspector.get_columns(t)] if t in available else []
    log(f"Schema introspection completed for {len(cache)} tables")
    return cache

# ============================================================
# Router + context builder
# ============================================================
def route_question(question: str) -> Dict[str, Any]:
    nq = normalize_text(question)
    if is_greeting_or_general(nq):
        return {"route": "general_chat", "reason": "greeting"}
    try:
        routed = llm_json(ROUTER_PROMPT, {"user_question": question}, max_tokens=150)
        route = routed.get("route")
        if route not in {"general_chat", "simple_db", "complex_db"}:
            route = "simple_db"
        return {"route": route, "reason": routed.get("reason", "")}
    except Exception as e:
        log(f"Router fallback due to error -> {e}", level="WARNING")
        return {"route": "simple_db", "reason": "fallback"}

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
    log(
        f"Ontology context built -> term_hits={len(matched_term_summary)}, entities={len(entity_summary)}, metrics={len(metric_summary)}, rels={len(rel_summary)}"
    )
    return {
        "normalized_question": nq,
        "matched_terms": matched_term_summary,
        "entities": entity_summary,
        "metrics": metric_summary,
        "relationships": rel_summary,
    }

# ============================================================
# Planner V2
# ============================================================
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

def validate_plan(plan: Dict[str, Any], profile_name: str, repo: Neo4jRepo, schema_cache: Dict[str, List[str]]) -> Tuple[bool, List[str]]:
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

def build_plan(profile_name: str, question: str, route: Dict[str, Any], context: Dict[str, Any], repo: Neo4jRepo, schema_cache: Dict[str, List[str]]) -> Dict[str, Any]:
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
    raw = call_llm(
        [
            {"role": "system", "content": PLANNER_V2_PROMPT},
            {"role": "user", "content": json.dumps(make_json_safe(payload), indent=2)},
        ],
        max_tokens=2400,
    )
    log(f"Planner raw LLM response -> {raw[:1800]}")
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
        raw2 = call_llm(
            [
                {"role": "system", "content": PLANNER_V2_PROMPT},
                {"role": "user", "content": json.dumps(make_json_safe(repair_payload), indent=2)},
            ],
            max_tokens=2600,
        )
        log(f"Planner repair raw LLM response -> {raw2[:1800]}")
        try:
            plan = json.loads(extract_json_text(raw2))
        except Exception as e:
            raise PlannerError(f"Planner repair returned invalid JSON: {raw2}") from e
        ok, errs = validate_plan(plan, profile_name, repo, schema_cache)
        if not ok:
            raise PlannerError("Planner validation failed: " + "; ".join(errs))
    log("Planner V2 JSON validated successfully")
    return plan

# ============================================================
# SQL compiler
# ============================================================
def resolve_join_steps(task: Dict[str, Any], repo: Neo4jRepo) -> List[Dict[str, Any]]:
    steps: List[Dict[str, Any]] = []
    for branch in task.get("chosen_path", []):
        if len(branch) <= 1:
            continue
        rows = repo.find_preferred_path(branch[0], branch[-1], max_hops=max(2, len(branch)))
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
            if s["from_table"] in joined and s["to_table"] not in joined:
                join_sql.append(f"JOIN [{s['to_table']}] ON [{s['from_table']}].[{s['from_column']}] = [{s['to_table']}].[{s['to_column']}]")
                joined.add(s["to_table"])
                progress = True
            elif s["to_table"] in joined and s["from_table"] not in joined:
                join_sql.append(f"JOIN [{s['from_table']}] ON [{s['from_table']}].[{s['from_column']}] = [{s['to_table']}].[{s['to_column']}]")
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
            metric_expr = (
                f"CAST(COUNT(DISTINCT CASE WHEN {source_expr} = 'Y' THEN {pk_expr} END) AS DECIMAL(38,10)) "
                f"/ NULLIF(COUNT(DISTINCT {pk_expr}), 0) * 100"
            )
        else:
            metric_expr = source_expr
        select_parts.append(f"{metric_expr} AS [metric_value]")
    else:
        if task.get("task_type") in {"aggregate", "ranking", "trend"}:
            count_entity_name = task.get("fact_entity") or task.get("target_entity") or base_entity_name
            count_entity = repo.get_entity(count_entity_name)
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
    log(f"Generated SQL for task {task.get('task_id')} ->\n{final_sql}")
    return final_sql

# ============================================================
# Execute + merge + answer
# ============================================================
def execute_sql(engine: Engine, sql: str, max_preview_rows: int = 500) -> Dict[str, Any]:
    start = time.time()
    try:
        with engine.connect() as conn:
            res = conn.execute(text(sql))
            rows = res.fetchall()
            cols = list(res.keys())
        ms = int((time.time() - start) * 1000)
        safe_rows = [make_json_safe(list(r) if not isinstance(r, (list, tuple)) else list(r)) for r in rows[:max_preview_rows]]
        safe_columns = [str(c) for c in cols]
        log(f"SQL execution successful -> row_count={len(rows)}, execution_time_ms={ms}")
        return {"columns": safe_columns, "rows": safe_rows, "row_count": len(rows), "execution_time_ms": ms}
    except Exception as e:
        raise SQLExecutionError(str(e))

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

def augment_tasks_for_placeholders(tasks: List[Dict[str, Any]], repo: Neo4jRepo) -> List[Dict[str, Any]]:
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


def build_task_schema_context(task: Dict[str, Any], profile_name: str, repo: Neo4jRepo, schema_cache: Dict[str, List[str]]) -> Dict[str, List[str]]:
    tables = set()

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

    try:
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

def repair_sql_with_llm(
    question: str,
    profile_name: str,
    task: Dict[str, Any],
    sql: str,
    validation_error: str,
    repo: Neo4jRepo,
    schema_cache: Dict[str, List[str]],
) -> str:
    schema_context = build_task_schema_context(task, profile_name, repo, schema_cache)

    payload = {
        "user_question": question,
        "database_profile": profile_name,
        "task": make_json_safe(task),
        "sql_to_fix": sql,
        "validation_error": validation_error,
        "relevant_schema": schema_context,
        "instruction": "Fix the SQL so that it compiles in SQL Server and preserves intent.",
    }

    raw = call_llm(
        [
            {"role": "system", "content": SQL_REPAIR_PROMPT},
            {"role": "user", "content": json.dumps(payload, indent=2)},
        ],
        max_tokens=1800,
    )
    repaired = extract_sql_text(raw)
    log(f"SQL repair LLM output -> {repaired[:1800]}")
    return repaired

def validate_and_repair_sql(
    engine: Engine,
    question: str,
    profile_name: str,
    task: Dict[str, Any],
    sql: str,
    repo: Neo4jRepo,
    schema_cache: Dict[str, List[str]],
    max_attempts: int = MAX_SQL_REPAIR_ATTEMPTS,
) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Returns:
      final_sql, validation_trace
    validation_trace keeps history of attempts for debugging/audit.
    """
    validation_trace: List[Dict[str, Any]] = []
    current_sql = sql

    for attempt in range(1, max_attempts + 2):  # original try + repair attempts
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
            log(f"SQL validation passed on attempt {attempt}")
            return current_sql, validation_trace

        log(f"SQL validation failed on attempt {attempt} -> {err}", level="WARNING")

        if attempt > max_attempts:
            break

        current_sql = repair_sql_with_llm(
            question=question,
            profile_name=profile_name,
            task=task,
            sql=current_sql,
            validation_error=err or "Unknown SQL compilation error",
            repo=repo,
            schema_cache=schema_cache,
        )

    raise SQLValidationError(
        "SQL validation failed after repair attempts. Last error: "
        + (validation_trace[-1].get("error") or "Unknown error")
    )

# def execute_plan2(engine: Engine, profile_name: str, plan: Dict[str, Any], repo: Neo4jRepo) -> Dict[str, Any]:
#     task_outputs: List[Dict[str, Any]] = []
#     task_contexts: Dict[str, Dict[str, Any]] = {}
#     for task in plan.get("tasks", []):
#         resolved_task = resolve_task_placeholders(task, task_contexts)
#         sql = build_task_sql(resolved_task, profile_name, repo)
#         result = execute_sql(engine, sql)
#         task_outputs.append({"task": resolved_task, "sql": sql, "result": result})
#         task_id = resolved_task.get("task_id")
#         if task_id:
#             task_contexts[task_id] = build_task_result_context(resolved_task, result)
#     merged: Dict[str, Any] = {"task_outputs": task_outputs, "combine_strategy": plan.get("combine_strategy", "none")}
#     if plan.get("combine_strategy") == "compare_on_dimension" and len(task_outputs) >= 2 and plan.get("comparison_dimension"):
#         comp_entity, comp_col = parse_property_ref(plan["comparison_dimension"])
#         comp_alias = f"{comp_entity}_{comp_col}".lower()
#         keyed: Dict[Any, Dict[str, Any]] = {}
#         for idx, out in enumerate(task_outputs, start=1):
#             cols = out["result"]["columns"]
#             rows = out["result"]["rows"]
#             if comp_alias not in cols:
#                 continue
#             comp_idx = cols.index(comp_alias)
#             metric_idx = cols.index("metric_value") if "metric_value" in cols else None
#             for row in rows:
#                 key = row[comp_idx]
#                 if key not in keyed:
#                     keyed[key] = {comp_alias: key}
#                 if metric_idx is not None:
#                     metric_name = out["task"].get("metric_name") or f"task_{idx}"
#                     keyed[key][metric_name] = row[metric_idx]
#         merged["combined_rows"] = list(keyed.values())
#         merged["combined_columns"] = dedupe(
#             [comp_alias] + [k for row in merged["combined_rows"] for k in row.keys() if k != comp_alias]
#         )
#     return merged


# def execute_plan3(engine: Engine, profile_name: str, plan: Dict[str, Any], repo: Neo4jRepo) -> Dict[str, Any]:
#     task_outputs: List[Dict[str, Any]] = []
#     task_contexts: Dict[str, Dict[str, Any]] = {}

#     tasks = augment_tasks_for_placeholders(plan.get("tasks", []), repo)

#     for task in tasks:
#         resolved_task = resolve_task_placeholders(task, task_contexts)

#         sql = build_task_sql(resolved_task, profile_name, repo)
#         result = execute_sql(engine, sql)

#         task_outputs.append({"task": resolved_task, "sql": sql, "result": result})

#         task_id = resolved_task.get("task_id")
#         if task_id:
#             task_contexts[task_id] = build_task_result_context(resolved_task, result)

#     merged: Dict[str, Any] = {"task_outputs": task_outputs, "combine_strategy": plan.get("combine_strategy", "none")}

#     if plan.get("combine_strategy") == "compare_on_dimension" and len(task_outputs) >= 2 and plan.get("comparison_dimension"):
#         comp_entity, comp_col = parse_property_ref(plan["comparison_dimension"])
#         comp_alias = f"{comp_entity}_{comp_col}".lower()
#         keyed: Dict[Any, Dict[str, Any]] = {}

#         for idx, out in enumerate(task_outputs, start=1):
#             cols = out["result"]["columns"]
#             rows = out["result"]["rows"]
#             if comp_alias not in cols:
#                 continue

#             comp_idx = cols.index(comp_alias)
#             metric_idx = cols.index("metric_value") if "metric_value" in cols else None

#             for row in rows:
#                 key = row[comp_idx]
#                 if key not in keyed:
#                     keyed[key] = {comp_alias: key}
#                 if metric_idx is not None:
#                     metric_name = out["task"].get("metric_name") or f"task_{idx}"
#                     keyed[key][metric_name] = row[metric_idx]

#         merged["combined_rows"] = list(keyed.values())
#         merged["combined_columns"] = dedupe(
#             [comp_alias] + [k for row in merged["combined_rows"] for k in row.keys() if k != comp_alias]
#         )

#     return merged

def execute_plan(
    engine: Engine,
    profile_name: str,
    plan: Dict[str, Any],
    repo: Neo4jRepo,
    schema_cache: Dict[str, List[str]],
    question: str,
) -> Dict[str, Any]:
    task_outputs: List[Dict[str, Any]] = []
    task_contexts: Dict[str, Dict[str, Any]] = {}

    tasks = augment_tasks_for_placeholders(plan.get("tasks", []), repo)

    for task in tasks:
        resolved_task = resolve_task_placeholders(task, task_contexts)

        raw_sql = build_task_sql(resolved_task, profile_name, repo)

        final_sql, validation_trace = validate_and_repair_sql(
            engine=engine,
            question=question,
            profile_name=profile_name,
            task=resolved_task,
            sql=raw_sql,
            repo=repo,
            schema_cache=schema_cache,
        )

        result = execute_sql(engine, final_sql)

        task_outputs.append(
            {
                "task": resolved_task,
                "sql": final_sql,
                "raw_sql": raw_sql,
                "validation_trace": validation_trace,
                "result": result,
            }
        )

        task_id = resolved_task.get("task_id")
        if task_id:
            task_contexts[task_id] = build_task_result_context(resolved_task, result)

    merged: Dict[str, Any] = {
        "task_outputs": task_outputs,
        "combine_strategy": plan.get("combine_strategy", "none"),
    }

    if plan.get("combine_strategy") == "compare_on_dimension" and len(task_outputs) >= 2 and plan.get("comparison_dimension"):
        comp_entity, comp_col = parse_property_ref(plan["comparison_dimension"])
        comp_alias = f"{comp_entity}_{comp_col}".lower()
        keyed: Dict[Any, Dict[str, Any]] = {}

        for idx, out in enumerate(task_outputs, start=1):
            cols = out["result"]["columns"]
            rows = out["result"]["rows"]
            if comp_alias not in cols:
                continue

            comp_idx = cols.index(comp_alias)
            metric_idx = cols.index("metric_value") if "metric_value" in cols else None

            for row in rows:
                key = row[comp_idx]
                if key not in keyed:
                    keyed[key] = {comp_alias: key}
                if metric_idx is not None:
                    metric_name = out["task"].get("metric_name") or f"task_{idx}"
                    keyed[key][metric_name] = row[metric_idx]

        merged["combined_rows"] = list(keyed.values())
        merged["combined_columns"] = dedupe(
            [comp_alias] + [k for row in merged["combined_rows"] for k in row.keys() if k != comp_alias]
        )

    return merged



def build_answer(question: str, profile_name: str, plan: Dict[str, Any], execution_output: Dict[str, Any]) -> str:
    payload = {
        "user_question": question,
        "database_profile": profile_name,
        "plan_summary": {
            "question_type": plan.get("question_type"),
            "intent": plan.get("intent"),
            "requires_multi_task": plan.get("requires_multi_task"),
            "combine_strategy": plan.get("combine_strategy"),
            "comparison_dimension": plan.get("comparison_dimension"),
            "tasks": [
                {
                    "task_id": t["task"].get("task_id"),
                    "task_type": t["task"].get("task_type"),
                    "metric_name": t["task"].get("metric_name"),
                    "selected_properties": t["task"].get("selected_properties", []),
                    "row_count": t["result"].get("row_count", 0),
                }
                for t in execution_output.get("task_outputs", [])
            ],
        },
        "results": execution_output,
    }
    return call_llm(
        [
            {"role": "system", "content": ANSWER_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(make_json_safe(payload), indent=2)},
        ],
        max_tokens=1000,
    ).strip()

# ============================================================
# UI helpers - MODIFIED FOR CHATGPT-LIKE INTERFACE
# ============================================================
def render_logs() -> None:
    with st.expander("Logs", expanded=False):
        for line in st.session_state.logs[-300:]:
            st.text(line)

def render_chat_message(msg: Dict[str, Any]) -> None:
    """Render a single chat message (question or answer)"""
    if msg["role"] == "user":
        with st.chat_message("user"):
            st.markdown(msg["content"])
    else:  # assistant
        with st.chat_message("assistant"):
            st.markdown(msg["content"])
            
            # Show additional details if available
            if "plan" in msg and st.session_state.developer_mode:
                with st.expander("📋 Planner JSON", expanded=False):
                    st.json(msg["plan"])
            
            if "sql" in msg:
                with st.expander("🔍 Generated SQL", expanded=False):
                    if isinstance(msg["sql"], list):
                        for i, sql in enumerate(msg["sql"], start=1):
                            st.markdown(f"**Task {i}**")
                            st.code(sql, language="sql")
                    else:
                        st.code(str(msg["sql"]), language="sql")
            
            if "execution_output" in msg:
                task_outputs = msg["execution_output"].get("task_outputs", [])
                for idx, out in enumerate(task_outputs, start=1):
                    with st.expander(f"📊 Result Preview — Task {idx}", expanded=False):
                        result = out["result"]
                        preview = [{col: val for col, val in zip(result.get("columns", []), row)} 
                                  for row in result.get("rows", [])[:20]]
                        if preview:
                            st.dataframe(preview, use_container_width=True)
                        else:
                            st.info("No rows returned")
                
                if msg["execution_output"].get("combined_rows"):
                    with st.expander("📈 Combined Result Preview", expanded=False):
                        st.dataframe(msg["execution_output"]["combined_rows"][:20], use_container_width=True)

def sidebar_connection_section() -> None:
    st.sidebar.header("Connection")
    profile = st.sidebar.selectbox("Database Profile", SUPPORTED_DB_PROFILES, index=SUPPORTED_DB_PROFILES.index(st.session_state.selected_profile))
    server = st.sidebar.text_input("MSSQL Server", value=st.session_state.mssql_server)
    port = st.sidebar.text_input("MSSQL Port", value=st.session_state.mssql_port)
    username = st.sidebar.text_input("MSSQL Username", value=st.session_state.mssql_username)
    password = st.sidebar.text_input("MSSQL Password", type="password", value=st.session_state.mssql_password)
    st.session_state.developer_mode = st.sidebar.checkbox("Developer Mode", value=st.session_state.developer_mode)
    st.session_state.selected_profile = profile
    st.session_state.mssql_server = server
    st.session_state.mssql_port = port
    st.session_state.mssql_username = username
    st.session_state.mssql_password = password
    if st.sidebar.button("Connect", type="primary"):
        try:
            log(f"Connect initiated for profile='{profile}'")
            repo = connect_neo4j_from_env()
            p = repo.get_profile(profile)
            if not p:
                raise OntologyProfileError(f"Ontology database profile not found in Neo4j for '{profile}'")
            if str(p.get("ontology_status", "")).lower() != "ready":
                raise OntologyProfileError(f"Ontology exists for '{profile}' but status is '{p.get('ontology_status')}'. Not ready yet.")
            log(f"Ontology profile resolved -> {p}")
            engine = connect_mssql(server, port, profile, username, password)
            lookup = repo.get_entity_table_lookup(profile)
            schema = introspect_schema(engine, list(lookup.values()))
            st.session_state.neo4j_repo = repo
            st.session_state.db_engine = engine
            st.session_state.entity_table_lookup = lookup
            st.session_state.schema_cache = schema
            st.session_state.connected = True
            st.sidebar.success("Connected successfully. Ontology profile is ready.")
            log("Application connection state is READY")
        except Exception as e:
            st.session_state.connected = False
            st.session_state.last_error = str(e)
            log(f"Connection failed -> {e}", level="ERROR")
            st.sidebar.error(str(e))
    
    # Clear chat history button
    if st.sidebar.button("🗑️ Clear Chat History"):
        st.session_state.chat_history = []
        st.rerun()

# ============================================================
# Main - MODIFIED FOR CHATGPT-LIKE INTERFACE
# ============================================================
def main() -> None:
    st.set_page_config(page_title=APP_TITLE, layout="wide")
    init_state()
    st.title(APP_TITLE)
    st.caption(APP_SUBTITLE)
    sidebar_connection_section()
    
    if not st.session_state.connected:
        st.info("Connect to a supported ontology-backed database profile from the sidebar to begin.")
        if st.session_state.developer_mode:
            render_logs()
        return
    
    profile = st.session_state.selected_profile
    
    # Display chat history
    for msg in st.session_state.chat_history:
        render_chat_message(msg)
    
    # Chat input at the bottom
    question = st.chat_input("Ask a question (e.g., compare premium and policy count by broker for last quarter)")
    
    if question:
        # Add user message to history
        st.session_state.chat_history.append({"role": "user", "content": question})
        
        # Display user message immediately
        with st.chat_message("user"):
            st.markdown(question)
        
        # Process the question and generate response
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                try:
                    if not question.strip():
                        raise AppError("Please enter a question.")
                    if len(question) > MAX_QUESTION_LENGTH:
                        raise AppError(f"Question too long. Max length is {MAX_QUESTION_LENGTH} characters.")
                    
                    repo: Neo4jRepo = st.session_state.neo4j_repo
                    route = route_question(question)
                    st.session_state.last_router = route
                    log(f"Router decided -> {route}")
                    
                    assistant_msg = {"role": "assistant", "content": ""}
                    
                    if route["route"] == "general_chat":
                        answer = build_general_llm_answer(question)
                        assistant_msg["content"] = answer
                        st.markdown(answer)
                    else:
                        context = build_planner_context(profile, question, repo)
                        plan = build_plan(profile, question, route, context, repo, st.session_state.schema_cache)
                        st.session_state.last_plan = plan
                        assistant_msg["plan"] = plan
                        
                        if plan.get("question_type") == "general_chat":
                            answer = build_general_llm_answer(question)
                            assistant_msg["content"] = answer
                            st.markdown(answer)
                        elif plan.get("needs_clarification"):
                            clarification = plan.get("clarification_reason") or "Please clarify your question."
                            assistant_msg["content"] = f"⚠️ {clarification}"
                            st.warning(clarification)
                        else:
                            # execution_output = execute_plan(st.session_state.db_engine, profile, plan, repo)
                            execution_output = execute_plan(
                                engine=st.session_state.db_engine,
                                profile_name=profile,
                                plan=plan,
                                repo=repo,
                                schema_cache=st.session_state.schema_cache,
                                question=question,
                            )
                            st.session_state.last_result = execution_output
                            st.session_state.last_sql = [o["sql"] for o in execution_output.get("task_outputs", [])]
                            assistant_msg["sql"] = st.session_state.last_sql
                            assistant_msg["execution_output"] = execution_output
                            
                            answer = build_answer(question, profile, plan, execution_output)
                            assistant_msg["content"] = answer
                            
                            # Display answer
                            st.markdown(answer)
                            
                            # Display SQL
                            with st.expander("🔍 Generated SQL", expanded=False):
                                for i, sql in enumerate(st.session_state.last_sql, start=1):
                                    st.markdown(f"**Task {i}**")
                                    st.code(sql, language="sql")
                            
                            # Display results
                            task_outputs = execution_output.get("task_outputs", [])
                            for idx, out in enumerate(task_outputs, start=1):
                                with st.expander(f"📊 Result Preview — Task {idx}", expanded=False):
                                    result = out["result"]
                                    preview = [{col: val for col, val in zip(result.get("columns", []), row)} 
                                              for row in result.get("rows", [])[:20]]
                                    if preview:
                                        st.dataframe(preview, use_container_width=True)
                                    else:
                                        st.info("No rows returned")
                            
                            if execution_output.get("combined_rows"):
                                with st.expander("📈 Combined Result Preview", expanded=False):
                                    st.dataframe(execution_output["combined_rows"][:20], use_container_width=True)
                    
                    # Add assistant response to history
                    st.session_state.chat_history.append(assistant_msg)
                    
                except Exception as e:
                    st.session_state.last_error = str(e)
                    log(f"Request handling failed -> {e}", level="ERROR")
                    error_msg = f"❌ Error: {str(e)}"
                    st.error(error_msg)
                    st.session_state.chat_history.append({"role": "assistant", "content": error_msg})
    
    if st.session_state.developer_mode:
        render_logs()

if __name__ == "__main__":
    main()