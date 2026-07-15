"""Stage 9: validation engine."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from skc.ir.common import NormalizedType, SourceType, StageStatus
from skc.ir.kir import BusinessRelationship, KnowledgeGraph
from skc.ir.mir import MIRColumn, MIRDatabase, MIRTable
from skc.pipeline.base import PipelineStage, StageResult
from skc.pipeline.context import CompilationContext
from skc.review.models import ValidationIssue, ValidationReport


class ValidationEngineStage(PipelineStage):
    """Validate complete KIR before human review."""

    name = "validation_engine"
    version = "0.1.0"
    description = "Validate KIR structural and semantic consistency."
    requires = ["confidence_engine"]
    produces = ["validation_report"]

    async def validate_inputs(self, ctx: CompilationContext) -> list[str]:
        errors: list[str] = []
        if ctx.mir is None:
            errors.append("MIR is required before validation")
        if ctx.kir.node_count == 0:
            errors.append("KIR is required before validation")
        return errors

    async def run(self, ctx: CompilationContext) -> StageResult:
        started_at = datetime.utcnow()
        report = self.validate(ctx.build_id, ctx.get_mir(), ctx.get_kir())
        path = ctx.write_artefact("validation_report", "review/validation_report.json", report)

        status = StageStatus.FAILED if report.has_errors else StageStatus.COMPLETED
        return self._create_result(
            status,
            started_at,
            artefacts=["validation_report"],
            warnings=[issue.message for issue in report.warnings],
            errors=[issue.message for issue in report.errors],
            stats={
                "errors": len(report.errors),
                "warnings": len(report.warnings),
                "issues": len(report.issues),
                "report_path": str(path),
            },
        )

    def validate(self, build_id: str, mir: MIRDatabase, kir: KnowledgeGraph) -> ValidationReport:
        table_refs = {self._table_ref(table): table for table in mir.get_all_tables()}
        column_refs = {
            self._column_ref(table, column): column
            for table in mir.get_all_tables()
            for column in table.columns
        }
        entity_ids = {entity.id for entity in kir.entities}
        issues: list[ValidationIssue] = []

        issues.extend(self._validate_entities(kir, table_refs))
        issues.extend(self._validate_relationships(kir.relationships, entity_ids, table_refs, column_refs))
        issues.extend(self._validate_metrics(kir, column_refs))
        issues.extend(self._validate_join_paths(kir.relationships, table_refs, column_refs))
        issues.extend(self._validate_duplicates(kir))
        issues.extend(self._validate_cycles(kir.relationships))
        issues.extend(self._validate_time_intelligence(kir, column_refs))
        issues.extend(self._validate_synonyms(kir))
        issues.extend(self._validate_grain(kir, table_refs))

        stats = {
            "entities": len(kir.entities),
            "concepts": len(kir.concepts),
            "metrics": len(kir.metrics),
            "rules": len(kir.rules),
            "relationships": len(kir.relationships),
            "time_intelligence": len(kir.time_intelligence),
            "security_tags": len(kir.security_tags),
        }
        return ValidationReport(build_id=build_id, issues=issues, stats=stats)

    def _validate_entities(
        self,
        kir: KnowledgeGraph,
        table_refs: dict[str, MIRTable],
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        for entity in kir.entities:
            if not entity.mapped_tables:
                severity = "warning" if self._is_plugin_seed(entity) else "error"
                issues.append(self._issue(severity, "entity_no_table", f"Entity {entity.name} maps to no table", entity.id, entity.candidate_type))
            for mapped_table in entity.mapped_tables:
                if mapped_table not in table_refs:
                    issues.append(
                        self._issue(
                            "error",
                            "entity_missing_table",
                            f"Entity {entity.name} maps to missing table {mapped_table}",
                            entity.id,
                            entity.candidate_type,
                        )
                    )
        return issues

    def _is_plugin_seed(self, entity: Any) -> bool:
        return any(provenance.source_type == SourceType.PLUGIN for provenance in entity.provenance)

    def _validate_relationships(
        self,
        relationships: list[BusinessRelationship],
        entity_ids: set[str],
        table_refs: dict[str, MIRTable],
        column_refs: dict[str, MIRColumn],
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        for relationship in relationships:
            if relationship.from_entity_id not in entity_ids:
                issues.append(self._issue("error", "relationship_missing_from", f"Relationship {relationship.name} references missing source entity", relationship.id, relationship.candidate_type))
            if relationship.to_entity_id not in entity_ids:
                issues.append(self._issue("error", "relationship_missing_to", f"Relationship {relationship.name} references missing target entity", relationship.id, relationship.candidate_type))
        return issues

    def _validate_metrics(
        self,
        kir: KnowledgeGraph,
        column_refs: dict[str, MIRColumn],
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        for metric in kir.metrics:
            refs = metric.source_columns or metric.base_columns
            if not refs:
                issues.append(self._issue("warning", "metric_no_columns", f"Metric {metric.name} has no source columns", metric.id, metric.candidate_type))
            for ref in refs:
                if ref not in column_refs:
                    issues.append(self._issue("error", "metric_missing_column", f"Metric {metric.name} references missing column {ref}", metric.id, metric.candidate_type))
            if not metric.formula:
                issues.append(self._issue("warning", "metric_no_formula", f"Metric {metric.name} has no formula", metric.id, metric.candidate_type))
        return issues

    def _validate_join_paths(
        self,
        relationships: list[BusinessRelationship],
        table_refs: dict[str, MIRTable],
        column_refs: dict[str, MIRColumn],
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        for relationship in relationships:
            for path in relationship.join_paths:
                if path.from_table not in table_refs:
                    issues.append(self._issue("error", "join_missing_from_table", f"Join path missing table {path.from_table}", relationship.id, relationship.candidate_type))
                if path.to_table not in table_refs:
                    issues.append(self._issue("error", "join_missing_to_table", f"Join path missing table {path.to_table}", relationship.id, relationship.candidate_type))
                for column in path.from_columns:
                    ref = f"{path.from_table}.{column}"
                    if ref not in column_refs:
                        issues.append(self._issue("error", "join_missing_from_column", f"Join path missing column {ref}", relationship.id, relationship.candidate_type))
                for column in path.to_columns:
                    ref = f"{path.to_table}.{column}"
                    if ref not in column_refs:
                        issues.append(self._issue("error", "join_missing_to_column", f"Join path missing column {ref}", relationship.id, relationship.candidate_type))
        return issues

    def _validate_duplicates(self, kir: KnowledgeGraph) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        names: dict[str, list[str]] = {}
        for entity in kir.entities:
            names.setdefault(entity.name.lower(), []).append(entity.id)
        for lower_name, ids in names.items():
            if len(ids) > 1:
                issues.append(
                    self._issue(
                        "error",
                        "duplicate_entity_name",
                        f"Duplicate entity name: {lower_name}",
                        metadata={"entity_ids": ids},
                    )
                )
        return issues

    def _validate_cycles(self, relationships: list[BusinessRelationship]) -> list[ValidationIssue]:
        pairs = {(relationship.from_entity_id, relationship.to_entity_id) for relationship in relationships}
        issues: list[ValidationIssue] = []
        for source, target in sorted(pairs):
            if source != target and (target, source) in pairs:
                issues.append(
                    self._issue(
                        "warning",
                        "circular_relationship",
                        "Potential circular relationship detected",
                        metadata={"from_entity_id": source, "to_entity_id": target},
                    )
                )
        return issues

    def _validate_time_intelligence(
        self,
        kir: KnowledgeGraph,
        column_refs: dict[str, MIRColumn],
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        temporal_types = {NormalizedType.DATE, NormalizedType.DATETIME, NormalizedType.TIMESTAMP, NormalizedType.TIME}
        for item in kir.time_intelligence:
            column = column_refs.get(item.column_ref)
            if column is None:
                issues.append(self._issue("error", "time_missing_column", f"Time intelligence references missing column {item.column_ref}", item.id, item.candidate_type))
            elif column.normalized_type not in temporal_types:
                issues.append(self._issue("error", "time_non_temporal_column", f"Time intelligence references non-temporal column {item.column_ref}", item.id, item.candidate_type))
        return issues

    def _validate_synonyms(self, kir: KnowledgeGraph) -> list[ValidationIssue]:
        canonical_by_term: dict[str, set[str]] = {}
        for synonym in kir.synonyms:
            canonical_by_term.setdefault(synonym.term.lower(), set()).add(synonym.canonical_name)
        return [
            self._issue(
                "warning",
                "synonym_conflict",
                f"Synonym {term} maps to multiple canonical names",
                metadata={"canonical_names": sorted(canonical_names)},
            )
            for term, canonical_names in canonical_by_term.items()
            if len(canonical_names) > 1
        ]

    def _validate_grain(
        self,
        kir: KnowledgeGraph,
        table_refs: dict[str, MIRTable],
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        for entity in kir.entities:
            if not entity.grain:
                continue
            for mapped_table in entity.mapped_tables:
                table = table_refs.get(mapped_table)
                if table is None:
                    continue
                pk_columns = set(table.primary_key_columns)
                grain_columns = set(entity.grain.grain_columns)
                if pk_columns and not grain_columns.issubset(pk_columns):
                    issues.append(
                        self._issue(
                            "warning",
                            "grain_not_pk_subset",
                            f"Entity {entity.name} grain is not consistent with primary key",
                            entity.id,
                            entity.candidate_type,
                            {"primary_key": sorted(pk_columns), "grain": sorted(grain_columns)},
                        )
                    )
        return issues

    def _issue(
        self,
        severity: str,
        code: str,
        message: str,
        node_id: str | None = None,
        node_type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ValidationIssue:
        return ValidationIssue(
            severity=severity,
            code=code,
            message=message,
            node_id=node_id,
            node_type=node_type,
            metadata=metadata or {},
        )

    def _table_ref(self, table: MIRTable) -> str:
        return f"{table.schema_name}.{table.name}"

    def _column_ref(self, table: MIRTable, column: MIRColumn) -> str:
        return f"{table.schema_name}.{table.name}.{column.name}"
