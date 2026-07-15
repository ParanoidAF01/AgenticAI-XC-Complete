from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from skc.cli import app
from skc.config import load_config
from skc.graph.schema import SKC_GRAPH_SCHEMA
from skc.graph.writer import GraphWriter
from skc.ir.common import Confidence, ReviewStatus, StageStatus
from skc.ir.kir import BusinessEntity, KnowledgeGraph
from skc.pipeline.context import CompilationContext
from skc.pipeline.runner import PipelineRunner
from skc.stages import (
    ConfidenceEngineStage,
    DataProfilerStage,
    GraphGeneratorStage,
    HumanReviewStage,
    MetricDiscoveryStage,
    RelationshipAnalyzerStage,
    RuleDiscoveryStage,
    SchemaGraphBuilderStage,
    SchemaParserStage,
    SemanticInferencerStage,
    ValidationEngineStage,
)


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "sample_schema.sql"


def _config(tmp_path: Path):
    cfg = load_config()
    return cfg.model_copy(
        update={
            "connector": cfg.connector.model_copy(
                update={"type": "ddl_file", "ddl_path": str(FIXTURE), "connection_string": ""}
            ),
            "pipeline": cfg.pipeline.model_copy(update={"output_dir": tmp_path}),
            "neo4j": cfg.neo4j.model_copy(update={"dry_run": True}),
        }
    )


async def _run_phase5(tmp_path: Path) -> CompilationContext:
    ctx = CompilationContext(config=_config(tmp_path), output_dir=tmp_path)
    results = await PipelineRunner(
        ctx,
        [
            SchemaParserStage(),
            SchemaGraphBuilderStage(),
            DataProfilerStage(),
            SemanticInferencerStage(),
            RelationshipAnalyzerStage(),
            MetricDiscoveryStage(),
            RuleDiscoveryStage(),
            ConfidenceEngineStage(),
            ValidationEngineStage(),
            HumanReviewStage(),
            GraphGeneratorStage(),
        ],
    ).run()
    assert results["graph_generator"].status == StageStatus.COMPLETED
    return ctx


def test_graph_schema_generates_constraints_and_indexes() -> None:
    constraints = SKC_GRAPH_SCHEMA.get_constraint_cypher()
    indexes = SKC_GRAPH_SCHEMA.get_index_cypher()

    assert any("BusinessEntity" in statement for statement in constraints)
    assert any("Table" in statement for statement in indexes)


@pytest.mark.asyncio
async def test_graph_generator_writes_dry_run_plan(tmp_path: Path) -> None:
    ctx = await _run_phase5(tmp_path)

    plan_path = tmp_path / "graph" / "cypher_plan.json"
    assert plan_path.exists()

    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    operation_names = {operation["name"] for operation in plan["operations"]}

    assert plan["dry_run"] is True
    assert plan["nodes_written"] > 0
    assert plan["relationships_written"] > 0
    assert plan["nodes_skipped"] > 0
    assert "merge_database_nodes" in operation_names
    assert "merge_business_entity_nodes" in operation_names
    assert "merge_foreign_key_relationships" in operation_names
    assert ctx.stage_results["graph_generator"].stats["dry_run"] is True


@pytest.mark.asyncio
async def test_graph_writer_plans_mir_and_approved_kir(tmp_path: Path) -> None:
    ctx = await _run_phase5(tmp_path)

    writer = GraphWriter(ctx.config.neo4j, ctx.build_id, ctx.build_version)
    writer.set_current_database(ctx.mir.name)
    mir_stats = writer.write_mir(ctx.mir)
    kir_stats = writer.write_kir(ctx.kir, approved_only=True)

    assert mir_stats.nodes_written >= ctx.mir.table_count
    assert mir_stats.relationships_written >= ctx.mir.table_count
    assert kir_stats.nodes_written > 0
    assert kir_stats.nodes_skipped > 0
    assert any(operation.name == "merge_entity_table_mappings" for operation in kir_stats.operations)


def test_cli_compile_runs_phase5_graph_generation(tmp_path: Path) -> None:
    runner = CliRunner()

    result = runner.invoke(app, ["compile", "--source", str(FIXTURE), "--output", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert (tmp_path / "graph" / "cypher_plan.json").exists()


def test_graph_cli_stats_and_export_from_dry_run_plan(tmp_path: Path) -> None:
    runner = CliRunner()
    compile_result = runner.invoke(
        app,
        ["compile", "--source", str(FIXTURE), "--output", str(tmp_path), "--plugin", "insurance"],
    )
    assert compile_result.exit_code == 0, compile_result.output

    plan_path = tmp_path / "graph" / "cypher_plan.json"
    stats_result = runner.invoke(app, ["graph", "stats", "--plan", str(plan_path)])
    assert stats_result.exit_code == 0, stats_result.output
    assert "Table" in stats_result.output
    assert "FOREIGN_KEY_TO" in stats_result.output

    export_path = tmp_path / "export.json"
    export_result = runner.invoke(
        app,
        ["graph", "export", "--plan", str(plan_path), "--output", str(export_path)],
    )
    assert export_result.exit_code == 0, export_result.output
    payload = json.loads(export_path.read_text(encoding="utf-8"))
    assert payload["nodes"]
    assert payload["relationships"]


def test_incremental_graph_writer_versions_semantic_nodes(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    cfg = cfg.model_copy(update={"neo4j": cfg.neo4j.model_copy(update={"incremental": True})})
    entity = BusinessEntity(
        id="entity_customer",
        name="Customer",
        mapped_tables=["public.customers"],
        confidence=Confidence.from_score(0.9),
        review_status=ReviewStatus.AUTO_APPROVED,
    )
    writer = GraphWriter(cfg.neo4j, build_id="build-1", build_version="20260714.120000.abc123")
    writer.set_current_database("warehouse")

    stats = writer.write_kir(KnowledgeGraph(entities=[entity]), approved_only=True)
    plan = stats.to_dict()
    plan_text = json.dumps(plan)
    entity_rows = next(
        operation.parameters["rows"]
        for operation in stats.operations
        if operation.name == "merge_business_entity_nodes"
    )

    assert entity_rows[0]["id"] == "entity_customer@20260714.120000.abc123"
    assert entity_rows[0]["logical_id"] == "entity_customer"
    assert entity_rows[0]["content_hash"]
    assert "SUPERSEDES" in plan_text
    assert "deprecated" in plan_text
