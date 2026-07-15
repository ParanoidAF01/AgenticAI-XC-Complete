from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from skc.cli import app
from skc.config import load_config
from skc.ir.common import Confidence, NormalizedType, StageStatus
from skc.ir.kir import BusinessEntity, KnowledgeGraph
from skc.ir.mir import MIRColumn, MIRDatabase, MIRPrimaryKey, MIRSchema, MIRTable
from skc.ir.serde import read_jsonl, write_jsonl
from skc.pipeline.base import PipelineStage
from skc.pipeline.context import CompilationContext
from skc.pipeline.runner import PipelineRunner
from skc.plugins.loader import PluginLoader
from skc.plugins.registry import PluginRegistry
from skc.utils.hashing import compute_node_hash
from skc.utils.naming import is_amount_column, is_date_column, is_id_column, snake_to_title


def test_config_loads_defaults_and_override(tmp_path: Path) -> None:
    override = tmp_path / "override.yaml"
    override.write_text(
        """
pipeline:
  output_dir: /tmp/skc-custom-output
  fail_fast: false
connector:
  type: ddl_file
""",
        encoding="utf-8",
    )

    cfg = load_config(override)

    assert cfg.connector.type == "ddl_file"
    assert cfg.pipeline.output_dir == Path("/tmp/skc-custom-output")
    assert cfg.pipeline.fail_fast is False
    assert cfg.llm.model


def test_mir_jsonl_roundtrip(tmp_path: Path) -> None:
    mir = MIRDatabase(
        name="warehouse",
        dialect="postgres",
        schemas=[
            MIRSchema(
                name="public",
                tables=[
                    MIRTable(
                        name="customers",
                        schema_name="public",
                        primary_key=MIRPrimaryKey(columns=["id"], name="customers_pkey"),
                        columns=[
                            MIRColumn(
                                name="id",
                                data_type="integer",
                                normalized_type=NormalizedType.INTEGER,
                                ordinal_position=1,
                                is_primary_key=True,
                            )
                        ],
                    )
                ],
            )
        ],
    )
    path = tmp_path / "mir.jsonl"

    mir.to_jsonl(path)
    loaded = MIRDatabase.from_jsonl(path)

    assert loaded.name == "warehouse"
    assert loaded.table_count == 1
    assert loaded.get_table("public", "customers").primary_key_columns == ["id"]


def test_kir_jsonl_roundtrip_and_counts(tmp_path: Path) -> None:
    entity = BusinessEntity(name="Customer", confidence=Confidence.from_score(0.9))
    graph = KnowledgeGraph(entities=[entity])
    path = tmp_path / "kir.jsonl"

    write_jsonl(path, [graph])
    loaded = read_jsonl(path, KnowledgeGraph)[0]

    assert loaded.node_count == 1
    assert loaded.edge_count == 0
    assert loaded.get_entity(entity.id).name == "Customer"


@pytest.mark.asyncio
async def test_pipeline_runner_orders_stages_and_writes_manifest(tmp_path: Path) -> None:
    events: list[str] = []

    class FirstStage(PipelineStage):
        name = "first"

        async def validate_inputs(self, ctx: CompilationContext) -> list[str]:
            return []

        async def run(self, ctx: CompilationContext):
            events.append(self.name)
            return self._create_result(StageStatus.COMPLETED, datetime.utcnow())

    class SecondStage(PipelineStage):
        name = "second"
        requires = ["first"]

        async def validate_inputs(self, ctx: CompilationContext) -> list[str]:
            return []

        async def run(self, ctx: CompilationContext):
            events.append(self.name)
            return self._create_result(StageStatus.COMPLETED, datetime.utcnow())

    ctx = CompilationContext(config=load_config(), output_dir=tmp_path)
    results = await PipelineRunner(ctx, [SecondStage(), FirstStage()]).run()

    assert events == ["first", "second"]
    assert list(results) == ["first", "second"]
    assert (tmp_path / "build_manifest.json").exists()


@pytest.mark.asyncio
async def test_pipeline_runner_records_validation_skip_when_not_fail_fast(tmp_path: Path) -> None:
    cfg = load_config()
    cfg = cfg.model_copy(update={"pipeline": cfg.pipeline.model_copy(update={"fail_fast": False})})

    class InvalidStage(PipelineStage):
        name = "invalid"

        async def validate_inputs(self, ctx: CompilationContext) -> list[str]:
            return ["missing input"]

        async def run(self, ctx: CompilationContext):
            raise AssertionError("stage should not run")

    ctx = CompilationContext(config=cfg, output_dir=tmp_path)
    results = await PipelineRunner(ctx, [InvalidStage()]).run()

    assert results["invalid"].status == StageStatus.SKIPPED
    assert results["invalid"].errors == ["missing input"]


def test_plugin_loader_loads_yaml_plugin(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plugins" / "insurance"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.yaml").write_text(
        """
name: insurance
version: 1.0.0
industries:
  - insurance
""",
        encoding="utf-8",
    )
    (plugin_dir / "ontology.yaml").write_text(
        """
- name: Policy
  description: Insurance policy
  mapped_tables:
    - public.policies
""",
        encoding="utf-8",
    )
    (plugin_dir / "metrics.yaml").write_text(
        """
- name: Loss Ratio
  formula: incurred_losses / earned_premium
""",
        encoding="utf-8",
    )
    (plugin_dir / "rules.yaml").write_text(
        """
- name: Premium Positive
  expression: premium > 0
""",
        encoding="utf-8",
    )
    (plugin_dir / "synonyms.yaml").write_text(
        """
Policy:
  - Contract
""",
        encoding="utf-8",
    )

    registry = PluginRegistry()
    loaded = PluginLoader(registry).load_from_directory(tmp_path / "plugins")

    assert [plugin.name for plugin in loaded] == ["insurance"]
    assert registry.get_by_industry("insurance")[0].version == "1.0.0"
    assert registry.get_ontology_seeds()[0].name == "Policy"
    assert registry.get_metrics()[0].name == "Loss Ratio"
    assert registry.get_rules()[0].name == "Premium Positive"
    assert registry.get_all_synonyms()["Policy"] == ["Contract"]


def test_utilities_are_deterministic() -> None:
    entity = BusinessEntity(name="Customer", confidence=Confidence.from_score(0.75))

    assert len(compute_node_hash(entity)) == 64
    assert compute_node_hash(entity) == compute_node_hash(entity)
    assert snake_to_title("customer_order") == "Customer Order"
    assert is_id_column("customer_id")
    assert is_date_column("created_at")
    assert is_amount_column("total_amount")


def test_cli_compile_smoke_writes_manifest(tmp_path: Path) -> None:
    runner = CliRunner()
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "sample_schema.sql"

    result = runner.invoke(app, ["compile", "--source", str(fixture), "--output", str(tmp_path)])

    assert result.exit_code == 0
    assert (tmp_path / "build_manifest.json").exists()
