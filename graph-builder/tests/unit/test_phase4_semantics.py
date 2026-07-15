from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from skc.cli import app
from skc.config import load_config
from skc.ir.common import ReviewStatus, StageStatus
from skc.ir.kir import KnowledgeGraph
from skc.ir.serde import read_jsonl
from skc.pipeline.context import CompilationContext
from skc.pipeline.runner import PipelineRunner
from skc.stages import (
    ConfidenceEngineStage,
    DataProfilerStage,
    MetricDiscoveryStage,
    RelationshipAnalyzerStage,
    RuleDiscoveryStage,
    SchemaGraphBuilderStage,
    SchemaParserStage,
    SemanticInferencerStage,
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
        }
    )


async def _run_phase4(tmp_path: Path) -> CompilationContext:
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
        ],
    ).run()
    assert results["confidence_engine"].status == StageStatus.COMPLETED
    return ctx


@pytest.mark.asyncio
async def test_phase4_pipeline_builds_semantic_kir(tmp_path: Path) -> None:
    ctx = await _run_phase4(tmp_path)
    graph = ctx.kir

    assert len(graph.entities) == 5
    assert graph.get_entity_by_name("Customer") is not None
    assert graph.get_entity_by_name("Order").grain_columns == ["id"]
    assert len(graph.relationships) == 3
    assert any(rel.metadata["target_table"] == "public.customers" for rel in graph.relationships)
    assert any(metric.name == "Sum Total Amount" for metric in graph.metrics)
    assert any(rule.name == "Chk Orders Amount" for rule in graph.rules)
    assert any(tag.classification == "PII" and tag.scope == "public.customers.email" for tag in graph.security_tags)
    assert any(item.column_ref == "public.orders.order_date" for item in graph.time_intelligence)
    assert all(candidate.confidence.score > 0 for candidate in graph.iter_candidates())
    assert any(candidate.review_status == ReviewStatus.AUTO_APPROVED for candidate in graph.iter_candidates())

    assert (tmp_path / "kir" / "initial.jsonl").exists()
    assert (tmp_path / "kir" / "relationships.jsonl").exists()
    assert (tmp_path / "kir" / "metrics.jsonl").exists()
    assert (tmp_path / "kir" / "rules.jsonl").exists()
    assert (tmp_path / "kir" / "confident.jsonl").exists()


@pytest.mark.asyncio
async def test_confident_kir_roundtrips(tmp_path: Path) -> None:
    await _run_phase4(tmp_path)

    graph = read_jsonl(tmp_path / "kir" / "confident.jsonl", KnowledgeGraph)[0]

    assert graph.node_count >= 5
    assert graph.edge_count == 3
    assert graph.metrics
    assert graph.rules


def test_cli_compile_runs_phase4_pipeline(tmp_path: Path) -> None:
    runner = CliRunner()

    result = runner.invoke(app, ["compile", "--source", str(FIXTURE), "--output", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert (tmp_path / "kir" / "confident.jsonl").exists()


def test_llm_response_schema_parses() -> None:
    from skc.llm.response_schemas import EntityIdentificationResponse

    parsed = EntityIdentificationResponse.model_validate(
        {"entities": [{"name": "Customer", "mapped_tables": ["public.customers"], "confidence": 0.8}]}
    )

    assert parsed.entities[0].name == "Customer"
    assert parsed.entities[0].confidence == 0.8
