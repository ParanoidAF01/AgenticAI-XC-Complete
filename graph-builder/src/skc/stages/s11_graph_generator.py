"""Stage 11: graph generator."""

from __future__ import annotations

from datetime import datetime

from skc.graph.writer import GraphWriteStats, GraphWriter
from skc.ir.common import StageStatus
from skc.pipeline.base import PipelineStage, StageResult
from skc.pipeline.context import CompilationContext


class GraphGeneratorStage(PipelineStage):
    """Write MIR/KIR artifacts to Neo4j or produce a dry-run Cypher plan."""

    name = "graph_generator"
    version = "0.1.0"
    description = "Generate the Neo4j semantic knowledge graph."
    requires = ["human_review"]
    produces = ["graph_write_plan"]

    async def validate_inputs(self, ctx: CompilationContext) -> list[str]:
        errors: list[str] = []
        if ctx.mir is None:
            errors.append("MIR is required before graph generation")
        if ctx.kir.node_count == 0:
            errors.append("KIR is required before graph generation")
        if not ctx.config.neo4j.dry_run and not ctx.config.neo4j.password:
            errors.append("neo4j.password is required when neo4j.dry_run=false")
        return errors

    async def run(self, ctx: CompilationContext) -> StageResult:
        started_at = datetime.utcnow()
        mir = ctx.get_mir()
        total = GraphWriteStats()

        with GraphWriter(ctx.config.neo4j, ctx.build_id, ctx.build_version) as writer:
            writer.set_current_database(mir.name)
            schema_operations = writer.ensure_schema()
            mir_stats = writer.write_mir(mir)
            kir_stats = writer.write_kir(ctx.get_kir(), approved_only=True)
            build_stats = writer.write_build(status="completed")

            total.nodes_written = (
                mir_stats.nodes_written + kir_stats.nodes_written + build_stats.nodes_written
            )
            total.nodes_updated = kir_stats.nodes_updated
            total.nodes_deprecated = kir_stats.nodes_deprecated
            total.nodes_unchanged = kir_stats.nodes_unchanged
            total.relationships_written = (
                mir_stats.relationships_written
                + kir_stats.relationships_written
                + build_stats.relationships_written
            )
            total.nodes_skipped = kir_stats.nodes_skipped
            total.operations = [
                *schema_operations,
                *mir_stats.operations,
                *kir_stats.operations,
                *build_stats.operations,
            ]

        plan = total.to_dict()
        plan["dry_run"] = ctx.config.neo4j.dry_run
        plan["database"] = ctx.config.neo4j.database
        plan["operation_count"] = len(total.operations)

        path = ctx.write_artefact("graph_write_plan", "graph/cypher_plan.json", plan)
        warnings = []
        if ctx.config.neo4j.dry_run:
            warnings.append("Neo4j dry-run enabled; no graph writes were executed")

        return self._create_result(
            StageStatus.COMPLETED,
            started_at,
            artefacts=["graph_write_plan"],
            warnings=warnings,
            stats={
                "nodes_written": total.nodes_written,
                "nodes_updated": total.nodes_updated,
                "nodes_deprecated": total.nodes_deprecated,
                "nodes_unchanged": total.nodes_unchanged,
                "relationships_written": total.relationships_written,
                "nodes_skipped": total.nodes_skipped,
                "operations": len(total.operations),
                "dry_run": ctx.config.neo4j.dry_run,
                "plan_path": str(path),
            },
        )
