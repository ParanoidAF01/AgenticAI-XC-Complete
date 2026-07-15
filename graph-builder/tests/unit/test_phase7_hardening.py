from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from skc.cli import app
from skc.config import load_config
from skc.connectors import create_connector
from skc.connectors.bigquery import BigQueryConnector
from skc.connectors.mysql import MySQLConnector
from skc.connectors.snowflake import SnowflakeConnector
from skc.ir.common import NormalizedType, StageStatus
from skc.ir.mir import MIRColumn, MIRDatabase, MIRSchema, MIRTable
from skc.llm.client import LLMClient
from skc.pipeline.checkpoint import CheckpointManager
from skc.pipeline.context import CompilationContext
from skc.pipeline.runner import PipelineRunner
from skc.plugins.loader import PluginLoader
from skc.plugins.registry import PluginRegistry
from skc.stages import DataProfilerStage, MetricDiscoveryStage, RuleDiscoveryStage, SchemaGraphBuilderStage, SchemaParserStage, SemanticInferencerStage


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "sample_schema.sql"
PLUGIN_ROOT = ROOT / "plugins"


def _ddl_config(tmp_path: Path, plugins: list[str] | None = None):
    cfg = load_config()
    return cfg.model_copy(
        update={
            "connector": cfg.connector.model_copy(
                update={"type": "ddl_file", "ddl_path": str(FIXTURE), "connection_string": ""}
            ),
            "pipeline": cfg.pipeline.model_copy(update={"output_dir": tmp_path}),
            "plugins": cfg.plugins.model_copy(
                update={"search_paths": [PLUGIN_ROOT], "enabled": plugins or []}
            ),
        }
    )


@pytest.mark.asyncio
async def test_build_report_and_checkpoints_are_written(tmp_path: Path) -> None:
    ctx = CompilationContext(config=_ddl_config(tmp_path), output_dir=tmp_path)

    results = await PipelineRunner(
        ctx,
        [SchemaParserStage(), SchemaGraphBuilderStage(), DataProfilerStage()],
    ).run()

    assert results["schema_parser"].status == StageStatus.COMPLETED
    assert (tmp_path / "build_manifest.json").exists()
    report_path = tmp_path / "build_report.json"
    checkpoint_path = tmp_path / "checkpoints" / "schema_graph_builder.json"
    assert report_path.exists()
    assert checkpoint_path.exists()

    report = json.loads(report_path.read_text(encoding="utf-8"))
    checkpoint = CheckpointManager.load_checkpoint(checkpoint_path)

    assert report["counts"]["mir"]["tables"] == 5
    assert report["diagnostics"]["warning_count"] == 1
    assert "schema_parser" in report["stages"]
    assert "schema_graph_builder" in checkpoint["completed_stages"]
    assert checkpoint["ir"]["mir"].endswith("database_enriched.jsonl")


def test_additional_connector_factory_types() -> None:
    cfg = load_config().connector

    assert isinstance(create_connector(cfg.model_copy(update={"type": "mysql"})), MySQLConnector)
    assert isinstance(create_connector(cfg.model_copy(update={"type": "snowflake"})), SnowflakeConnector)
    assert isinstance(create_connector(cfg.model_copy(update={"type": "bigquery"})), BigQueryConnector)


def test_insurance_plugin_loads_curated_seed_data() -> None:
    registry = PluginRegistry()
    loaded = PluginLoader(registry).load_from_directory(PLUGIN_ROOT)

    insurance = next(plugin for plugin in loaded if plugin.name == "insurance")

    assert insurance.version == "1.0.0"
    assert getattr(insurance, "trust_score") == pytest.approx(0.9)
    assert {entity.name for entity in insurance.get_ontology()} >= {"Policy", "Claim", "Premium"}
    assert {metric.name for metric in insurance.get_metrics()} >= {"Loss Ratio", "Combined Ratio"}
    assert registry.get_all_synonyms()["Policy"][0] == "Contract"


def test_cli_resume_restores_checkpoint_context_and_runs_tail(tmp_path: Path) -> None:
    runner = CliRunner()
    partial_output = tmp_path / "partial"
    resumed_output = tmp_path / "resumed"

    partial = runner.invoke(
        app,
        [
            "compile",
            "--source",
            str(FIXTURE),
            "--output",
            str(partial_output),
            "--plugin",
            "insurance",
            "--stages",
            "confidence_engine",
        ],
    )
    assert partial.exit_code == 0, partial.output

    checkpoint = partial_output / "checkpoints" / "confidence_engine.json"
    assert checkpoint.exists()

    resumed = runner.invoke(
        app,
        [
            "compile",
            "--source",
            str(FIXTURE),
            "--output",
            str(resumed_output),
            "--plugin",
            "insurance",
            "--resume",
            str(checkpoint),
            "--stages",
            "graph_generator",
        ],
    )

    assert resumed.exit_code == 0, resumed.output
    assert "Resuming from checkpoint" in resumed.output
    plan_path = resumed_output / "graph" / "cypher_plan.json"
    report_path = resumed_output / "build_report.json"
    assert plan_path.exists()
    assert report_path.exists()

    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    plan_text = json.dumps(plan)

    assert plan["dry_run"] is True
    assert "Policy" in plan_text
    assert report["stages"]["graph_generator"]["status"] == "completed"


@pytest.mark.asyncio
async def test_optional_llm_enrichment_uses_mocked_responses(tmp_path: Path, monkeypatch) -> None:
    cfg = load_config().model_copy(
        update={
            "pipeline": load_config().pipeline.model_copy(update={"output_dir": tmp_path}),
            "llm": load_config().llm.model_copy(update={"enabled": True, "max_retries": 1}),
        }
    )
    mir = MIRDatabase(
        name="warehouse",
        dialect="ddl_file",
        schemas=[
            MIRSchema(
                name="public",
                tables=[
                    MIRTable(
                        name="policies",
                        schema_name="public",
                        columns=[
                            MIRColumn(
                                name="id",
                                data_type="INTEGER",
                                normalized_type=NormalizedType.INTEGER,
                                ordinal_position=1,
                                is_primary_key=True,
                            ),
                            MIRColumn(
                                name="premium_amount",
                                data_type="NUMERIC",
                                normalized_type=NormalizedType.DECIMAL,
                                ordinal_position=2,
                            ),
                        ],
                    )
                ],
            )
        ],
    )

    def fake_completion(self, prompt: str, system_prompt: str | None) -> str:
        if "Identify business entities" in prompt:
            return json.dumps(
                {
                    "entities": [
                        {
                            "name": "Policy Account",
                            "description": "LLM entity",
                            "mapped_tables": ["public.policies"],
                            "confidence": 0.91,
                        }
                    ]
                }
            )
        if "Infer business concepts" in prompt:
            return json.dumps(
                {
                    "concepts": [
                        {
                            "name": "Policy Premium",
                            "category": "measure",
                            "description": "LLM concept",
                            "mapped_columns": ["public.policies.premium_amount"],
                            "confidence": 0.88,
                        }
                    ]
                }
            )
        if "Describe the business meaning" in prompt:
            return json.dumps({"description": "LLM table description.", "confidence": 0.89})
        if "Suggest business synonyms" in prompt:
            return json.dumps({"synonyms": [{"term": "Contract", "language": "en", "confidence": 0.82}]})
        if "Infer useful metrics" in prompt:
            return json.dumps(
                {
                    "metrics": [
                        {
                            "name": "LLM Premium",
                            "formula": "SUM(public.policies.premium_amount)",
                            "formula_type": "aggregation",
                            "description": "LLM metric",
                            "base_columns": ["public.policies.premium_amount"],
                            "confidence": 0.86,
                        }
                    ]
                }
            )
        if "Infer candidate business rules" in prompt:
            return json.dumps(
                {
                    "rules": [
                        {
                            "name": "Premium Must Exist",
                            "rule_type": "validation",
                            "expression": "public.policies.premium_amount IS NOT NULL",
                            "description": "LLM rule",
                            "scope_tables": ["public.policies"],
                            "scope_columns": ["public.policies.premium_amount"],
                            "confidence": 0.83,
                        }
                    ]
                }
            )
        return "{}"

    monkeypatch.setattr(LLMClient, "_completion", fake_completion)
    ctx = CompilationContext(config=cfg, output_dir=tmp_path, mir=mir)

    semantic = await SemanticInferencerStage().run(ctx)
    metrics = await MetricDiscoveryStage().run(ctx)
    rules = await RuleDiscoveryStage().run(ctx)

    assert semantic.stats["llm_entities_added"] == 1
    assert semantic.stats["llm_concepts_added"] == 1
    assert semantic.stats["llm_synonyms_added"] > 0
    assert metrics.stats["llm_metrics_added"] == 1
    assert rules.stats["llm_rules_added"] == 1
    assert any(entity.name == "Policy Account" for entity in ctx.kir.entities)
    assert any(metric.name == "LLM Premium" for metric in ctx.kir.metrics)
    assert any(rule.name == "Premium Must Exist" for rule in ctx.kir.rules)
