"""Neo4j graph writer for MIR and KIR artifacts."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from skc.config import Neo4jConfig
from skc.graph.schema import SKC_GRAPH_SCHEMA
from skc.ir.common import Provenance, ReviewStatus
from skc.ir.kir import (
    BusinessConcept,
    BusinessEntity,
    BusinessRule,
    KnowledgeGraph,
    Metric,
    SecurityTag,
    Synonym,
    TimeIntelligence,
)
from skc.ir.mir import MIRColumn, MIRDatabase, MIRForeignKey, MIRTable
from skc.utils.hashing import compute_node_hash


@dataclass
class GraphOperation:
    """A single Cypher operation and its parameters."""

    name: str
    statement: str
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass
class GraphWriteStats:
    """Counts produced by graph generation."""

    nodes_written: int = 0
    nodes_updated: int = 0
    nodes_deprecated: int = 0
    nodes_unchanged: int = 0
    relationships_written: int = 0
    nodes_skipped: int = 0
    operations: list[GraphOperation] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes_written": self.nodes_written,
            "nodes_updated": self.nodes_updated,
            "nodes_deprecated": self.nodes_deprecated,
            "nodes_unchanged": self.nodes_unchanged,
            "relationships_written": self.relationships_written,
            "nodes_skipped": self.nodes_skipped,
            "operations": [
                {
                    "name": operation.name,
                    "statement": operation.statement,
                    "parameters": operation.parameters,
                }
                for operation in self.operations
            ],
        }


class GraphWriter:
    """Write MIR/KIR structures to Neo4j using idempotent Cypher."""

    def __init__(self, config: Neo4jConfig, build_id: str, build_version: str) -> None:
        self.config = config
        self.build_id = build_id
        self.build_version = build_version
        self.driver: Any = None
        self.operations: list[GraphOperation] = []

    def connect(self) -> None:
        if self.config.dry_run:
            return
        try:
            from neo4j import GraphDatabase
        except Exception as exc:
            raise RuntimeError("neo4j package is required for live graph writes") from exc
        self.driver = GraphDatabase.driver(
            self.config.uri,
            auth=(self.config.username, self.config.password),
        )

    def close(self) -> None:
        if self.driver is not None:
            self.driver.close()
            self.driver = None

    def __enter__(self) -> GraphWriter:
        self.connect()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    def ensure_schema(self) -> list[GraphOperation]:
        """Create configured constraints and indexes if needed."""
        operations: list[GraphOperation] = []
        for index, statement in enumerate(
            [*SKC_GRAPH_SCHEMA.get_constraint_cypher(), *SKC_GRAPH_SCHEMA.get_index_cypher()]
        ):
            operations.append(self._execute(f"schema_{index}", statement, {}))
        return operations

    def write_mir(self, mir: MIRDatabase) -> GraphWriteStats:
        """Write structural MIR nodes and relationships."""
        stats = GraphWriteStats()
        database_row = self._database_row(mir)
        schema_rows = [self._schema_row(mir, schema.name) for schema in mir.schemas]
        table_rows = [self._table_row(mir, table) for table in mir.get_all_tables()]
        column_rows = [
            self._column_row(mir, table, column)
            for table in mir.get_all_tables()
            for column in table.columns
        ]
        fk_rows = [
            self._fk_row(mir, table, fk)
            for table in mir.get_all_tables()
            for fk in table.foreign_keys
            if fk.referred_table and fk.columns and fk.referred_columns
        ]

        stats.operations.extend(
            [
                self._merge_nodes("merge_database_nodes", "Database", [database_row]),
                self._merge_nodes("merge_schema_nodes", "Schema", schema_rows),
                self._merge_nodes("merge_table_nodes", "Table", table_rows),
                self._merge_nodes("merge_column_nodes", "Column", column_rows),
                self._merge_relationships(
                    "merge_database_schema_relationships",
                    "Database",
                    "Schema",
                    "CONTAINS_SCHEMA",
                    [{"from_id": database_row["id"], "to_id": row["id"], "properties": {}} for row in schema_rows],
                ),
                self._merge_relationships(
                    "merge_schema_table_relationships",
                    "Schema",
                    "Table",
                    "CONTAINS_TABLE",
                    [{"from_id": row["schema_id"], "to_id": row["id"], "properties": {}} for row in table_rows],
                ),
                self._merge_relationships(
                    "merge_table_column_relationships",
                    "Table",
                    "Column",
                    "HAS_COLUMN",
                    [{"from_id": row["table_id"], "to_id": row["id"], "properties": {}} for row in column_rows],
                ),
                self._merge_relationships(
                    "merge_foreign_key_relationships",
                    "Column",
                    "Column",
                    "FOREIGN_KEY_TO",
                    fk_rows,
                ),
            ]
        )
        stats.nodes_written += 1 + len(schema_rows) + len(table_rows) + len(column_rows)
        stats.relationships_written += len(schema_rows) + len(table_rows) + len(column_rows) + len(fk_rows)
        stats.operations = [operation for operation in stats.operations if operation is not None]
        return stats

    def write_kir(self, kir: KnowledgeGraph, approved_only: bool = True) -> GraphWriteStats:
        """Write semantic KIR nodes and relationships."""
        stats = GraphWriteStats()
        approved = {ReviewStatus.APPROVED, ReviewStatus.AUTO_APPROVED}
        candidates = kir.iter_candidates()
        approved_ids = {
            candidate.id
            for candidate in candidates
            if not approved_only or candidate.review_status in approved
        }
        stats.nodes_skipped += len([candidate for candidate in candidates if candidate.id not in approved_ids])

        entities = [entity for entity in kir.entities if entity.id in approved_ids]
        concepts = [concept for concept in kir.concepts if concept.id in approved_ids]
        metrics = [metric for metric in kir.metrics if metric.id in approved_ids]
        rules = [rule for rule in kir.rules if rule.id in approved_ids]
        relationships = [rel for rel in kir.relationships if rel.id in approved_ids]
        time_items = [item for item in kir.time_intelligence if item.id in approved_ids]
        security_tags = [tag for tag in kir.security_tags if tag.id in approved_ids]
        synonyms = self._synonyms_for_approved(kir.synonyms, entities, concepts)

        entity_rows = [self._entity_row(entity) for entity in entities]
        concept_rows = [self._concept_row(concept) for concept in concepts]
        metric_rows = [self._metric_row(metric) for metric in metrics]
        rule_rows = [self._rule_row(rule) for rule in rules]
        synonym_rows = [self._synonym_row(synonym) for synonym in synonyms]
        time_rows = [self._time_row(item) for item in time_items]
        security_rows = [self._security_row(tag) for tag in security_tags]

        stats.operations.extend(
            [
                self._merge_nodes("merge_business_entity_nodes", "BusinessEntity", entity_rows),
                self._merge_nodes("merge_business_concept_nodes", "BusinessConcept", concept_rows),
                self._merge_nodes("merge_metric_nodes", "Metric", metric_rows),
                self._merge_nodes("merge_business_rule_nodes", "BusinessRule", rule_rows),
                self._merge_nodes("merge_synonym_nodes", "Synonym", synonym_rows),
                self._merge_nodes("merge_time_intelligence_nodes", "TimeIntelligence", time_rows),
                self._merge_nodes("merge_security_tag_nodes", "SecurityTag", security_rows),
                self._merge_relationships(
                    "merge_entity_table_mappings",
                    "BusinessEntity",
                    "Table",
                    "MAPS_TO_TABLE",
                    self._entity_table_relationships(entities),
                ),
                self._merge_relationships(
                    "merge_concept_column_mappings",
                    "BusinessConcept",
                    "Column",
                    "MAPS_TO_COLUMN",
                    self._concept_column_relationships(concepts),
                ),
                self._merge_relationships(
                    "merge_entity_relationships",
                    "BusinessEntity",
                    "BusinessEntity",
                    "RELATED_TO",
                    self._business_relationship_rows(relationships),
                ),
                self._merge_relationships(
                    "merge_entity_metric_relationships",
                    "BusinessEntity",
                    "Metric",
                    "HAS_METRIC",
                    self._entity_metric_relationships(entities, metrics),
                ),
                self._merge_relationships(
                    "merge_entity_rule_relationships",
                    "BusinessEntity",
                    "BusinessRule",
                    "HAS_RULE",
                    self._entity_rule_relationships(entities, rules),
                ),
                self._merge_relationships(
                    "merge_entity_synonym_relationships",
                    "BusinessEntity",
                    "Synonym",
                    "ENTITY_HAS_SYNONYM",
                    self._entity_synonym_relationships(entities, synonyms),
                ),
                self._merge_relationships(
                    "merge_concept_synonym_relationships",
                    "BusinessConcept",
                    "Synonym",
                    "CONCEPT_HAS_SYNONYM",
                    self._concept_synonym_relationships(concepts, synonyms),
                ),
                self._merge_relationships(
                    "merge_time_relationships",
                    "Column",
                    "TimeIntelligence",
                    "HAS_TIME_INTELLIGENCE",
                    self._column_node_relationships(time_rows, "column_id"),
                ),
                self._merge_relationships(
                    "merge_column_security_relationships",
                    "Column",
                    "SecurityTag",
                    "COLUMN_HAS_SECURITY",
                    self._column_node_relationships(security_rows, "scope_id"),
                ),
            ]
        )
        stats.operations.extend(
            self._incremental_version_operations(
                {
                    "BusinessEntity": entity_rows,
                    "BusinessConcept": concept_rows,
                    "Metric": metric_rows,
                    "BusinessRule": rule_rows,
                    "Synonym": synonym_rows,
                    "TimeIntelligence": time_rows,
                    "SecurityTag": security_rows,
                }
            )
        )

        provenance_stats = self._write_provenance_for_candidates(
            [*entities, *concepts, *metrics, *rules, *relationships, *time_items, *security_tags]
        )
        stats.nodes_written += (
            len(entity_rows)
            + len(concept_rows)
            + len(metric_rows)
            + len(rule_rows)
            + len(synonym_rows)
            + len(time_rows)
            + len(security_rows)
            + provenance_stats.nodes_written
        )
        if self.config.incremental:
            stats.nodes_updated = len(
                [
                    row
                    for row in [
                        *entity_rows,
                        *concept_rows,
                        *metric_rows,
                        *rule_rows,
                        *synonym_rows,
                        *time_rows,
                        *security_rows,
                    ]
                    if row.get("logical_id")
                ]
            )
        stats.relationships_written += sum(
            len(operation.parameters.get("rows", []))
            for operation in stats.operations
            if operation is not None and "MERGE (from)-[r:" in operation.statement
        )
        stats.relationships_written += provenance_stats.relationships_written
        stats.operations = [operation for operation in stats.operations if operation is not None]
        stats.operations.extend(provenance_stats.operations)
        return stats

    def write_build(self, status: str = "completed") -> GraphWriteStats:
        """Write a build manifest node."""
        row = {
            "id": self.build_id,
            "build_id": self.build_id,
            "build_version": self.build_version,
            "started_at": datetime.utcnow().isoformat(),
            "completed_at": datetime.utcnow().isoformat(),
            "status": status,
        }
        operation = self._merge_nodes("merge_build_node", "Build", [row])
        return GraphWriteStats(nodes_written=1, operations=[operation])

    def _execute(self, name: str, statement: str, parameters: dict[str, Any]) -> GraphOperation:
        operation = GraphOperation(name=name, statement=statement, parameters=parameters)
        self.operations.append(operation)
        if self.config.dry_run:
            return operation
        if self.driver is None:
            self.connect()
        with self.driver.session(database=self.config.database) as session:
            session.run(statement, parameters)
        return operation

    def _merge_nodes(self, name: str, label: str, rows: list[dict[str, Any]]) -> GraphOperation:
        statement = f"UNWIND $rows AS row MERGE (n:{label} {{id: row.id}}) SET n += row"
        return self._execute(name, statement, {"rows": rows})

    def _merge_relationships(
        self,
        name: str,
        from_label: str,
        to_label: str,
        relationship_type: str,
        rows: list[dict[str, Any]],
    ) -> GraphOperation:
        from_pattern = f"from:{from_label}" if not from_label.startswith("_") else "from"
        to_pattern = f"to:{to_label}" if not to_label.startswith("_") else "to"
        statement = (
            "UNWIND $rows AS row "
            f"MATCH ({from_pattern} {{id: row.from_id}}) "
            f"MATCH ({to_pattern} {{id: row.to_id}}) "
            f"MERGE (from)-[r:{relationship_type}]->(to) "
            "SET r += row.properties"
        )
        return self._execute(name, statement, {"rows": rows})

    def _database_row(self, mir: MIRDatabase) -> dict[str, Any]:
        return {
            "id": self._database_id(mir),
            "name": mir.name,
            "dialect": self._value(mir.dialect),
            "build_version": self.build_version,
        }

    def _schema_row(self, mir: MIRDatabase, schema_name: str) -> dict[str, Any]:
        return {
            "id": self._schema_id(mir, schema_name),
            "name": schema_name,
            "database": mir.name,
            "build_version": self.build_version,
        }

    def _table_row(self, mir: MIRDatabase, table: MIRTable) -> dict[str, Any]:
        full_name = f"{table.schema_name}.{table.name}"
        return {
            "id": self._table_id(mir, table.schema_name, table.name),
            "schema_id": self._schema_id(mir, table.schema_name),
            "name": table.name,
            "schema": table.schema_name,
            "database": mir.name,
            "full_name": full_name,
            "table_type": self._value(table.table_type),
            "row_count": table.row_count,
            "topology": self._value(table.table_topology),
            "build_version": self.build_version,
        }

    def _column_row(self, mir: MIRDatabase, table: MIRTable, column: MIRColumn) -> dict[str, Any]:
        full_name = f"{table.schema_name}.{table.name}.{column.name}"
        return {
            "id": self._column_id(mir, table.schema_name, table.name, column.name),
            "table_id": self._table_id(mir, table.schema_name, table.name),
            "name": column.name,
            "table": table.name,
            "schema": table.schema_name,
            "database": mir.name,
            "full_name": full_name,
            "data_type": column.data_type,
            "normalized_type": self._value(column.normalized_type),
            "is_nullable": column.is_nullable,
            "is_primary_key": column.is_primary_key,
            "is_foreign_key": column.is_foreign_key,
            "build_version": self.build_version,
        }

    def _fk_row(self, mir: MIRDatabase, table: MIRTable, fk: MIRForeignKey) -> dict[str, Any]:
        source_column = fk.columns[0]
        target_column = fk.referred_columns[0]
        target_schema = fk.referred_schema or table.schema_name
        return {
            "from_id": self._column_id(mir, table.schema_name, table.name, source_column),
            "to_id": self._column_id(mir, target_schema, fk.referred_table, target_column),
            "properties": {"fk_name": fk.name},
        }

    def _entity_row(self, entity: BusinessEntity) -> dict[str, Any]:
        row = {
            "id": self._semantic_id(entity.id),
            "name": entity.name,
            "description": entity.description,
            "entity_type": entity.entity_type,
            "confidence_score": entity.confidence.score,
            "review_status": entity.review_status.value,
            "build_version": entity.build_version or self.build_version,
        }
        return self._with_incremental_metadata(row, entity.id, entity)

    def _concept_row(self, concept: BusinessConcept) -> dict[str, Any]:
        row = {
            "id": self._semantic_id(concept.id),
            "name": concept.name,
            "description": concept.description,
            "category": concept.category,
            "confidence_score": concept.confidence.score,
            "review_status": concept.review_status.value,
            "build_version": concept.build_version or self.build_version,
        }
        return self._with_incremental_metadata(row, concept.id, concept)

    def _metric_row(self, metric: Metric) -> dict[str, Any]:
        row = {
            "id": self._semantic_id(metric.id),
            "name": metric.name,
            "description": metric.description,
            "formula": metric.formula,
            "formula_type": metric.formula_type,
            "unit": metric.unit,
            "confidence_score": metric.confidence.score,
            "review_status": metric.review_status.value,
            "build_version": metric.build_version or self.build_version,
        }
        return self._with_incremental_metadata(row, metric.id, metric)

    def _rule_row(self, rule: BusinessRule) -> dict[str, Any]:
        row = {
            "id": self._semantic_id(rule.id),
            "name": rule.name,
            "description": rule.description,
            "rule_type": rule.rule_type,
            "expression": rule.expression,
            "confidence_score": rule.confidence.score,
            "review_status": rule.review_status.value,
            "build_version": rule.build_version or self.build_version,
        }
        return self._with_incremental_metadata(row, rule.id, rule)

    def _synonym_row(self, synonym: Synonym) -> dict[str, Any]:
        logical_id = self._synonym_id(synonym)
        row = {
            "id": self._semantic_id(logical_id),
            "term": synonym.term,
            "canonical_name": synonym.canonical_name,
            "language": synonym.language,
            "confidence_score": synonym.confidence.score,
            "build_version": self.build_version,
        }
        return self._with_incremental_metadata(row, logical_id, synonym)

    def _time_row(self, item: TimeIntelligence) -> dict[str, Any]:
        row = {
            "id": self._semantic_id(item.id),
            "column_id": self._column_id_from_ref(item.column_ref),
            "column_ref": item.column_ref,
            "time_role": item.time_role,
            "granularity": item.granularity,
            "timezone": item.timezone,
            "build_version": self.build_version,
        }
        return self._with_incremental_metadata(row, item.id, item)

    def _security_row(self, tag: SecurityTag) -> dict[str, Any]:
        row = {
            "id": self._semantic_id(tag.id),
            "scope_id": self._column_id_from_ref(tag.scope),
            "scope": tag.scope,
            "classification": tag.classification,
            "build_version": self.build_version,
        }
        return self._with_incremental_metadata(row, tag.id, tag)

    def _entity_table_relationships(self, entities: list[BusinessEntity]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for entity in entities:
            for mapped_table in entity.mapped_tables:
                rows.append(
                    {
                        "from_id": self._semantic_id(entity.id),
                        "to_id": self._table_id_from_ref(mapped_table),
                        "properties": {"confidence": entity.confidence.score},
                    }
                )
        return rows

    def _concept_column_relationships(self, concepts: list[BusinessConcept]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for concept in concepts:
            for mapped_column in concept.mapped_columns:
                rows.append(
                    {
                        "from_id": self._semantic_id(concept.id),
                        "to_id": self._column_id_from_ref(mapped_column),
                        "properties": {"confidence": concept.confidence.score},
                    }
                )
        return rows

    def _business_relationship_rows(self, relationships: list[Any]) -> list[dict[str, Any]]:
        return [
            {
                "from_id": self._semantic_id(relationship.from_entity_id),
                "to_id": self._semantic_id(relationship.to_entity_id),
                "properties": {
                    "logical_id": relationship.id,
                    "content_hash": compute_node_hash(relationship),
                    "build_version": self.build_version,
                    "relationship_type": relationship.relationship_type,
                    "cardinality": relationship.cardinality,
                    "description": relationship.description,
                    "confidence": relationship.confidence.score,
                },
            }
            for relationship in relationships
        ]

    def _entity_metric_relationships(
        self,
        entities: list[BusinessEntity],
        metrics: list[Metric],
    ) -> list[dict[str, Any]]:
        entity_by_table = self._entity_by_table(entities)
        rows: list[dict[str, Any]] = []
        for metric in metrics:
            for column in metric.source_columns or metric.base_columns:
                table_ref = ".".join(column.split(".")[:2])
                entity = entity_by_table.get(table_ref)
                if entity is not None:
                    rows.append({"from_id": self._semantic_id(entity.id), "to_id": self._semantic_id(metric.id), "properties": {}})
                    break
        return rows

    def _entity_rule_relationships(
        self,
        entities: list[BusinessEntity],
        rules: list[BusinessRule],
    ) -> list[dict[str, Any]]:
        entity_by_table = self._entity_by_table(entities)
        rows: list[dict[str, Any]] = []
        for rule in rules:
            for scope_table in rule.scope_tables:
                entity = entity_by_table.get(scope_table)
                if entity is not None:
                    rows.append({"from_id": self._semantic_id(entity.id), "to_id": self._semantic_id(rule.id), "properties": {}})
                    break
        return rows

    def _entity_synonym_relationships(
        self,
        entities: list[BusinessEntity],
        synonyms: list[Synonym],
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for entity in entities:
            for synonym in synonyms:
                if synonym.canonical_name == entity.name:
                    rows.append({"from_id": self._semantic_id(entity.id), "to_id": self._semantic_id(self._synonym_id(synonym)), "properties": {}})
        return rows

    def _concept_synonym_relationships(
        self,
        concepts: list[BusinessConcept],
        synonyms: list[Synonym],
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for concept in concepts:
            for synonym in synonyms:
                if synonym.canonical_name == concept.name:
                    rows.append({"from_id": self._semantic_id(concept.id), "to_id": self._semantic_id(self._synonym_id(synonym)), "properties": {}})
        return rows

    def _column_node_relationships(self, rows: list[dict[str, Any]], column_key: str) -> list[dict[str, Any]]:
        return [
            {"from_id": row[column_key], "to_id": row["id"], "properties": {}}
            for row in rows
            if row.get(column_key)
        ]

    def _write_provenance_for_candidates(self, candidates: list[Any]) -> GraphWriteStats:
        provenance_rows: list[dict[str, Any]] = []
        relationship_rows: list[dict[str, Any]] = []
        for candidate in candidates:
            for provenance in candidate.provenance:
                row = self._provenance_row(provenance)
                provenance_rows.append(row)
                relationship_rows.append({"from_id": self._semantic_id(candidate.id), "to_id": row["id"], "properties": {}})
        if not provenance_rows:
            return GraphWriteStats()
        operations = [
            self._merge_nodes("merge_provenance_nodes", "Provenance", provenance_rows),
            self._merge_relationships(
                "merge_candidate_provenance_relationships",
                "_Any",
                "Provenance",
                "HAS_PROVENANCE",
                relationship_rows,
            ),
        ]
        return GraphWriteStats(
            nodes_written=len(provenance_rows),
            relationships_written=len(relationship_rows),
            operations=operations,
        )

    def _provenance_row(self, provenance: Provenance) -> dict[str, Any]:
        raw = f"{provenance.source_type.value}:{provenance.source_id}:{provenance.source_detail}:{provenance.timestamp.isoformat()}"
        return {
            "id": f"prov_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]}",
            "source_type": provenance.source_type.value,
            "source_id": provenance.source_id,
            "source_detail": provenance.source_detail,
            "timestamp": provenance.timestamp.isoformat(),
            "build_version": provenance.build_version or self.build_version,
        }

    def _synonyms_for_approved(
        self,
        synonyms: list[Synonym],
        entities: list[BusinessEntity],
        concepts: list[BusinessConcept],
    ) -> list[Synonym]:
        approved_names = {entity.name for entity in entities} | {concept.name for concept in concepts}
        return [synonym for synonym in synonyms if synonym.canonical_name in approved_names]

    def _entity_by_table(self, entities: list[BusinessEntity]) -> dict[str, BusinessEntity]:
        return {
            mapped_table: entity
            for entity in entities
            for mapped_table in entity.mapped_tables
        }

    def _database_id(self, mir: MIRDatabase) -> str:
        return f"database:{mir.name}"

    def _schema_id(self, mir: MIRDatabase, schema: str) -> str:
        return f"schema:{mir.name}.{schema}"

    def _table_id(self, mir: MIRDatabase, schema: str, table: str) -> str:
        return f"table:{mir.name}.{schema}.{table}"

    def _column_id(self, mir: MIRDatabase, schema: str, table: str, column: str) -> str:
        return f"column:{mir.name}.{schema}.{table}.{column}"

    def _table_id_from_ref(self, ref: str) -> str:
        return f"table:{self._database_name_from_build()}.{ref}"

    def _column_id_from_ref(self, ref: str) -> str:
        return f"column:{self._database_name_from_build()}.{ref}"

    def _database_name_from_build(self) -> str:
        # The writer uses full refs for semantic mappings. The concrete
        # database name is not carried in KIR, so graph-generator sets this
        # attribute from MIR before writing KIR.
        return getattr(self, "_current_database_name", "database")

    def set_current_database(self, database_name: str) -> None:
        self._current_database_name = database_name

    def _synonym_id(self, synonym: Synonym) -> str:
        raw = f"{synonym.language}:{synonym.canonical_name}:{synonym.term}"
        return f"synonym_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]}"

    def _semantic_id(self, logical_id: str) -> str:
        if not self.config.incremental:
            return logical_id
        return f"{logical_id}@{self.build_version}"

    def _with_incremental_metadata(self, row: dict[str, Any], logical_id: str, model: Any) -> dict[str, Any]:
        if not self.config.incremental:
            return row
        return {
            **row,
            "logical_id": logical_id,
            "content_hash": compute_node_hash(model),
            "deprecated": False,
            "build_id": self.build_id,
        }

    def _incremental_version_operations(
        self,
        rows_by_label: dict[str, list[dict[str, Any]]],
    ) -> list[GraphOperation]:
        if not self.config.incremental:
            return []

        timestamp = datetime.utcnow().isoformat()
        operations: list[GraphOperation] = []
        for label, rows in rows_by_label.items():
            rows = [row for row in rows if row.get("logical_id")]
            if not rows:
                continue
            logical_ids = sorted({row["logical_id"] for row in rows})
            operations.append(
                self._execute(
                    f"incremental_supersede_{label.lower()}",
                    (
                        "UNWIND $rows AS row "
                        f"MATCH (current:{label} {{id: row.id}}) "
                        f"MATCH (previous:{label} {{logical_id: row.logical_id}}) "
                        "WHERE previous.id <> current.id "
                        "AND coalesce(previous.deprecated, false) = false "
                        "AND previous.content_hash <> row.content_hash "
                        "MERGE (current)-[r:SUPERSEDES]->(previous) "
                        "SET previous.deprecated = true, "
                        "previous.deprecated_at = $timestamp, "
                        "r.created_at = $timestamp"
                    ),
                    {"rows": rows, "timestamp": timestamp},
                )
            )
            operations.append(
                self._execute(
                    f"incremental_deprecate_removed_{label.lower()}",
                    (
                        f"MATCH (previous:{label}) "
                        "WHERE previous.build_version <> $build_version "
                        "AND previous.logical_id IS NOT NULL "
                        "AND NOT previous.logical_id IN $logical_ids "
                        "AND coalesce(previous.deprecated, false) = false "
                        "SET previous.deprecated = true, previous.deprecated_at = $timestamp"
                    ),
                    {
                        "build_version": self.build_version,
                        "logical_ids": logical_ids,
                        "timestamp": timestamp,
                    },
                )
            )
        return operations

    def _value(self, value: Any) -> Any:
        if value is None:
            return None
        return value.value if hasattr(value, "value") else value
