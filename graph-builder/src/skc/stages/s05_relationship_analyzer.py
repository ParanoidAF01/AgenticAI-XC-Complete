"""Stage 5: relationship analyzer."""

from __future__ import annotations

from datetime import datetime

from skc.ir.common import StageStatus
from skc.ir.kir import BusinessEntity, BusinessRelationship, GrainDefinition, JoinPath
from skc.ir.mir import MIRForeignKey, MIRTable
from skc.ir.serde import write_jsonl
from skc.pipeline.base import PipelineStage, StageResult
from skc.pipeline.context import CompilationContext
from skc.stages.semantic_helpers import (
    confidence,
    deterministic_provenance,
    entity_name_for_table,
    stable_id,
    table_ref,
)


class RelationshipAnalyzerStage(PipelineStage):
    """Create business relationships and entity grains from MIR structure."""

    name = "relationship_analyzer"
    version = "0.1.0"
    description = "Analyze FK-backed relationships and grain."
    requires = ["semantic_inferencer"]
    produces = ["kir_relationships"]

    async def validate_inputs(self, ctx: CompilationContext) -> list[str]:
        errors: list[str] = []
        if ctx.mir is None:
            errors.append("MIR is required before relationship analysis")
        if not ctx.kir.entities:
            errors.append("KIR entities are required before relationship analysis")
        return errors

    async def run(self, ctx: CompilationContext) -> StageResult:
        started_at = datetime.utcnow()
        mir = ctx.get_mir()
        graph = ctx.get_kir()

        entity_by_table = {
            entity.metadata.get("source_table", entity.mapped_tables[0] if entity.mapped_tables else ""): entity
            for entity in graph.entities
        }

        relationships: list[BusinessRelationship] = list(graph.relationships)
        for table in mir.get_all_tables():
            source_entity = entity_by_table.get(table_ref(table))
            if source_entity is None:
                continue
            for fk in table.foreign_keys:
                target_ref = f"{fk.referred_schema or table.schema_name}.{fk.referred_table}"
                target_entity = entity_by_table.get(target_ref)
                if target_entity is None:
                    continue
                relationships.append(self._relationship(table, fk, source_entity, target_entity, ctx.build_version))

        updated_entities = [
            self._with_grain(entity, self._table_for_entity(mir.get_all_tables(), entity), ctx.build_version)
            for entity in graph.entities
        ]
        graph = graph.model_copy(update={"entities": updated_entities, "relationships": relationships})
        ctx.update_kir(graph)

        path = ctx.output_dir / "kir" / "relationships.jsonl"
        write_jsonl(path, [graph])
        ctx.register_artefact("kir_relationships", path)

        return self._create_result(
            StageStatus.COMPLETED,
            started_at,
            artefacts=["kir_relationships"],
            stats={"relationships": len(relationships), "entities_with_grain": sum(1 for e in updated_entities if e.grain)},
        )

    def _relationship(
        self,
        table: MIRTable,
        fk: MIRForeignKey,
        source_entity: BusinessEntity,
        target_entity: BusinessEntity,
        build_version: str,
    ) -> BusinessRelationship:
        deterministic_confidence = confidence(0.9, "Relationship is backed by a source foreign key.")
        join_path = JoinPath(
            from_table=table_ref(table),
            from_columns=fk.columns,
            to_table=f"{fk.referred_schema or table.schema_name}.{fk.referred_table}",
            to_columns=fk.referred_columns,
            join_type="INNER",
            is_deterministic=True,
            provenance=deterministic_provenance(self.name, build_version),
            confidence=deterministic_confidence,
        )
        cardinality = "one-to-many" if not self._fk_is_unique(table, fk) else "one-to-one"
        name = f"{source_entity.name} references {target_entity.name}"
        return BusinessRelationship(
            id=stable_id("relationship", table_ref(table), ",".join(fk.columns), join_path.to_table),
            name=name,
            from_entity_id=source_entity.id,
            to_entity_id=target_entity.id,
            relationship_type=cardinality,
            cardinality=cardinality,
            join_paths=[join_path],
            join_columns=list(zip(fk.columns, fk.referred_columns)),
            is_deterministic=True,
            description=f"FK-backed relationship from {table_ref(table)} to {join_path.to_table}.",
            confidence=deterministic_confidence,
            provenance=deterministic_provenance(self.name, build_version),
            build_version=build_version,
            metadata={
                "source_table": table_ref(table),
                "target_table": join_path.to_table,
                "is_deterministic": True,
                "fk_name": fk.name,
            },
        )

    def _fk_is_unique(self, table: MIRTable, fk: MIRForeignKey) -> bool:
        fk_columns = set(fk.columns)
        if set(table.primary_key_columns) == fk_columns:
            return True
        return any(index.is_unique and set(index.columns) == fk_columns for index in table.indexes)

    def _with_grain(
        self,
        entity: BusinessEntity,
        table: MIRTable | None,
        build_version: str,
    ) -> BusinessEntity:
        if table is None or not table.primary_key_columns:
            return entity
        grain = GrainDefinition(
            grain_columns=table.primary_key_columns,
            description=f"Grain is defined by the primary key of {table_ref(table)}.",
            provenance=deterministic_provenance(self.name, build_version),
        )
        return entity.model_copy(update={"grain": grain, "grain_columns": table.primary_key_columns})

    def _table_for_entity(self, tables: list[MIRTable], entity: BusinessEntity) -> MIRTable | None:
        source_ref = entity.metadata.get("source_table") or (entity.mapped_tables[0] if entity.mapped_tables else "")
        return next((table for table in tables if table_ref(table) == source_ref), None)
