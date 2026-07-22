"""Neo4j repository – synchronous, extracted verbatim from the legacy app.

The neo4j Python driver does not support async natively, so this module
remains fully synchronous.  Also includes ``connect_neo4j_from_env()`` and
``introspect_schema()``.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from neo4j import GraphDatabase
from sqlalchemy import inspect
from sqlalchemy.engine import Engine

from app.query_engine.helpers import dedupe

logger = logging.getLogger(__name__)


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

    def get_entity_columns(self, entity_name: str) -> List[Dict[str, Any]]:
        """Fetch all active column nodes for a single entity."""
        return self._run(
            """
            MATCH (e:OntologyEntity {entity_name:$entity_name})-[r:HAS_COLUMN]->(c:Column)
            WHERE coalesce(r.active, true) = true
            RETURN c.column_name AS column_name,
                   c.canonical_name AS canonical_name,
                   c.description AS description,
                   c.data_type AS data_type,
                   c.semantic_role AS semantic_role,
                   c.business_role AS business_role,
                   c.synonyms AS synonyms,
                   c.when_to_use AS when_to_use,
                   c.when_not_to_use AS when_not_to_use,
                   c.question_hints AS question_hints,
                   c.negative_question_hints AS negative_question_hints,
                   c.is_selectable AS is_selectable,
                   c.is_filterable AS is_filterable,
                   c.is_groupable AS is_groupable,
                   c.is_aggregatable AS is_aggregatable,
                   c.is_joinable AS is_joinable,
                   c.supports_time_grouping AS supports_time_grouping,
                   c.selection_priority AS selection_priority,
                   c.key_type AS key_type,
                   c.is_pii AS is_pii,
                   c.is_sensitive AS is_sensitive,
                   r.ordinal_position AS ordinal_position
            ORDER BY r.ordinal_position
            """,
            {"entity_name": entity_name},
        )

    def get_all_entity_columns(self, profile_name: str) -> Dict[str, List[Dict[str, Any]]]:
        """Bulk-fetch all active columns for every entity in a profile.

        Returns a dict keyed by entity_name -> list of column dicts.
        Single Cypher query to avoid N+1.
        """
        rows = self._run(
            """
            MATCH (:OntologyDatabaseProfile {profile_name:$profile_name})-[:USES_ENTITY]->(e:OntologyEntity)
            MATCH (e)-[r:HAS_COLUMN]->(c:Column)
            WHERE coalesce(r.active, true) = true
            RETURN e.entity_name AS entity_name,
                   c.column_name AS column_name,
                   c.canonical_name AS canonical_name,
                   c.description AS description,
                   c.data_type AS data_type,
                   c.semantic_role AS semantic_role,
                   c.business_role AS business_role,
                   c.synonyms AS synonyms,
                   c.when_to_use AS when_to_use,
                   c.when_not_to_use AS when_not_to_use,
                   c.question_hints AS question_hints,
                   c.negative_question_hints AS negative_question_hints,
                   c.is_selectable AS is_selectable,
                   c.is_filterable AS is_filterable,
                   c.is_groupable AS is_groupable,
                   c.is_aggregatable AS is_aggregatable,
                   c.is_joinable AS is_joinable,
                   c.supports_time_grouping AS supports_time_grouping,
                   c.selection_priority AS selection_priority,
                   c.key_type AS key_type,
                   c.is_pii AS is_pii,
                   c.is_sensitive AS is_sensitive,
                   r.ordinal_position AS ordinal_position
            ORDER BY e.entity_name, r.ordinal_position
            """,
            {"profile_name": profile_name},
        )
        result: Dict[str, List[Dict[str, Any]]] = {}
        for row in rows:
            ename = row.pop("entity_name")
            result.setdefault(ename, []).append(row)
        return result

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


# ------------------------------------------------------------------
# Factory + schema introspection
# ------------------------------------------------------------------

def connect_neo4j_from_env() -> Neo4jRepo:
    uri = os.getenv("NEO4J_URI", "").strip()
    user = os.getenv("NEO4J_USERNAME", "").strip()
    pwd = os.getenv("NEO4J_PASSWORD", "").strip()
    if not all([uri, user, pwd]):
        from app.query_engine.errors import AppError
        raise AppError("Missing Neo4j env vars: NEO4J_URI / NEO4J_USERNAME / NEO4J_PASSWORD")
    repo = Neo4jRepo(uri=uri, username=user, password=pwd)
    if not repo.test():
        from app.query_engine.errors import AppError
        raise AppError("Neo4j connection test failed")
    logger.info("Neo4j Aura connection successful")
    return repo


def introspect_schema(engine: Engine, tables_of_interest: List[str]) -> Dict[str, List[str]]:
    inspector = inspect(engine)
    available = set(inspector.get_table_names())
    cache: Dict[str, List[str]] = {}
    for t in dedupe(tables_of_interest):
        cache[t] = [c["name"] for c in inspector.get_columns(t)] if t in available else []
    logger.info(f"Schema introspection completed for {len(cache)} tables")
    return cache
