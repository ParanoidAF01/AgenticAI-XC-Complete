from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from skc.cli import app
from skc.config import load_config
from skc.ir.common import Confidence, ReviewStatus, StageStatus
from skc.ir.kir import BusinessEntity
from skc.pipeline.context import CompilationContext
from skc.pipeline.runner import PipelineRunner
from skc.review.store import CandidateStore
from skc.stages import (
    ConfidenceEngineStage,
    DataProfilerStage,
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
            "review": cfg.review.model_copy(update={"mode": "batch", "store_path": None}),
        }
    )


async def _run_through_review(tmp_path: Path) -> CompilationContext:
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
        ],
    ).run()
    assert results["human_review"].status == StageStatus.COMPLETED
    return ctx


@pytest.mark.asyncio
async def test_validation_engine_writes_clean_report(tmp_path: Path) -> None:
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
        ],
    ).run()

    assert results["validation_engine"].status == StageStatus.COMPLETED
    report_path = tmp_path / "review" / "validation_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["issues"] == []
    assert report["stats"]["entities"] == 5


def test_validation_engine_detects_duplicate_entity_names(tmp_path: Path) -> None:
    stage = ValidationEngineStage()
    entity = BusinessEntity(name="Customer", mapped_tables=["public.customers"], confidence=Confidence.from_score(0.8))
    duplicate = entity.model_copy(update={"id": "duplicate_entity"})

    from skc.ir.kir import KnowledgeGraph
    from skc.ir.mir import MIRDatabase, MIRSchema, MIRTable

    mir = MIRDatabase(
        name="db",
        dialect="ddl_file",
        schemas=[MIRSchema(name="public", tables=[MIRTable(name="customers", schema_name="public")])],
    )
    report = stage.validate("build", mir, KnowledgeGraph(entities=[entity, duplicate]))

    assert report.has_errors
    assert any(issue.code == "duplicate_entity_name" for issue in report.errors)


def test_candidate_store_persists_and_updates_status(tmp_path: Path) -> None:
    store = CandidateStore(tmp_path / "candidates.sqlite")
    candidate = BusinessEntity(name="Customer", confidence=Confidence.from_score(0.9))

    store.upsert_candidate(candidate)
    assert len(store.get_pending()) == 1

    store.approve(candidate.id, reviewer="tester", notes="looks good")
    approved = store.get_by_status(ReviewStatus.APPROVED)
    assert approved[0]["id"] == candidate.id
    assert approved[0]["reviewer"] == "tester"

    modified = candidate.model_copy(update={"id": "changed_by_request", "name": "Customer Modified"})
    store.modify(candidate.id, modified, reviewer="tester", notes="renamed")
    rows = store.get_by_status(ReviewStatus.MODIFIED)
    assert rows[0]["id"] == candidate.id
    assert rows[0]["serialized_node"]["id"] == candidate.id
    assert rows[0]["serialized_node"]["name"] == "Customer Modified"


@pytest.mark.asyncio
async def test_human_review_stage_persists_queue_and_reviewed_kir(tmp_path: Path) -> None:
    ctx = await _run_through_review(tmp_path)

    store_path = tmp_path / "review" / "candidates.sqlite"
    summary_path = tmp_path / "review" / "review_summary.json"
    reviewed_path = tmp_path / "kir" / "reviewed.jsonl"

    assert store_path.exists()
    assert summary_path.exists()
    assert reviewed_path.exists()

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    store = CandidateStore(store_path)
    counts = store.count_by_status()

    assert summary["total_candidates"] == len(ctx.kir.iter_candidates())
    assert summary["auto_approved"] > 0
    assert summary["pending_review"] > 0
    assert counts[ReviewStatus.AUTO_APPROVED.value] == summary["auto_approved"]
    assert counts[ReviewStatus.PENDING_REVIEW.value] == summary["pending_review"]


def test_cli_review_lists_pending_candidates(tmp_path: Path) -> None:
    runner = CliRunner()
    compile_result = runner.invoke(app, ["compile", "--source", str(FIXTURE), "--output", str(tmp_path)])
    assert compile_result.exit_code == 0, compile_result.output

    review_result = runner.invoke(app, ["review", "--store", str(tmp_path / "review" / "candidates.sqlite")])

    assert review_result.exit_code == 0
    assert "Pending Review Candidates" in review_result.output
