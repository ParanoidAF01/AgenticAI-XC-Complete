from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from typer.testing import CliRunner

from skc.cli import app
from skc.config import load_config
from skc.connectors.ddl_file import DDLFileConnector
from skc.ir.common import NormalizedType, StageStatus
from skc.ir.mir import (
    ConstraintType,
    MIRColumn,
    MIRDatabase,
    MIRSchema,
    MIRTable,
    TableTopology,
)
from skc.pipeline.context import CompilationContext
from skc.pipeline.runner import PipelineRunner
from skc.stages import DataProfilerStage, SchemaGraphBuilderStage, SchemaParserStage


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "sample_schema.sql"


def _ddl_config(tmp_path: Path):
    cfg = load_config()
    return cfg.model_copy(
        update={
            "connector": cfg.connector.model_copy(
                update={"type": "ddl_file", "ddl_path": str(FIXTURE), "connection_string": ""}
            ),
            "pipeline": cfg.pipeline.model_copy(update={"output_dir": tmp_path}),
        }
    )


def test_ddl_connector_extracts_complete_mir(tmp_path: Path) -> None:
    cfg = _ddl_config(tmp_path)

    connector = DDLFileConnector(cfg.connector)
    with connector:
        mir = connector.extract_metadata()

    assert mir.dialect == "ddl_file"
    assert mir.table_count == 5

    orders = mir.get_table("public", "orders")
    assert orders is not None
    assert orders.primary_key_columns == ["id"]
    assert [fk.referred_table for fk in orders.foreign_keys] == ["customers"]
    assert any(index.name == "idx_orders_customer" for index in orders.indexes)
    assert any(constraint.type == ConstraintType.CHECK for constraint in orders.constraints)

    customer_email = next(column for column in mir.get_table("public", "customers").columns if column.name == "email")
    assert customer_email.max_length == 255
    assert customer_email.is_nullable is False


@pytest.mark.asyncio
async def test_phase3_pipeline_from_ddl_writes_artifacts(tmp_path: Path) -> None:
    cfg = _ddl_config(tmp_path)
    ctx = CompilationContext(config=cfg, output_dir=tmp_path)

    results = await PipelineRunner(
        ctx,
        [SchemaParserStage(), SchemaGraphBuilderStage(), DataProfilerStage()],
    ).run()

    assert results["schema_parser"].status == StageStatus.COMPLETED
    assert results["schema_graph_builder"].status == StageStatus.COMPLETED
    assert results["data_profiler"].status == StageStatus.SKIPPED
    assert ctx.mir is not None
    assert (tmp_path / "mir" / "database.jsonl").exists()
    assert (tmp_path / "mir" / "database_enriched.jsonl").exists()
    assert (tmp_path / "mir" / "topology_report.json").exists()

    enriched = MIRDatabase.from_jsonl(tmp_path / "mir" / "database_enriched.jsonl")
    assert enriched.get_table("public", "customers").table_topology == TableTopology.DIMENSION
    assert enriched.get_table("public", "orders").table_topology == TableTopology.FACT
    assert enriched.get_table("public", "order_items").table_topology == TableTopology.BRIDGE
    assert enriched.get_table("public", "audit_log").table_topology == TableTopology.STANDALONE

    report = json.loads((tmp_path / "mir" / "topology_report.json").read_text(encoding="utf-8"))
    assert "public.customers" in report["hub_tables"]
    assert "public.order_items" in report["bridge_tables"]
    assert "public.audit_log" in report["orphan_tables"]


def test_schema_graph_builder_classifies_without_runner(tmp_path: Path) -> None:
    cfg = _ddl_config(tmp_path)
    connector = DDLFileConnector(cfg.connector)
    with connector:
        mir = connector.extract_metadata()

    enriched, report = SchemaGraphBuilderStage().enrich_mir(mir)

    assert len(report["connected_components"]) == 2
    assert report["table_topology"]["public.products"] == "DIMENSION"
    assert enriched.get_table("public", "products").table_topology == TableTopology.DIMENSION


@pytest.mark.asyncio
async def test_data_profiler_skips_without_live_connection(tmp_path: Path) -> None:
    cfg = _ddl_config(tmp_path)
    connector = DDLFileConnector(cfg.connector)
    with connector:
        mir = connector.extract_metadata()

    ctx = CompilationContext(config=cfg, output_dir=tmp_path, mir=mir)
    result = await DataProfilerStage().run(ctx)

    assert result.status == StageStatus.SKIPPED
    assert result.warnings
    assert ctx.profiles is None


@pytest.mark.asyncio
async def test_data_profiler_writes_profiles_for_live_sqlite(tmp_path: Path) -> None:
    db_path = tmp_path / "profile.db"
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE customers ("
                "id INTEGER PRIMARY KEY, email TEXT, status TEXT, total_amount NUMERIC)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO customers (email, status, total_amount) VALUES "
                "('a@example.com', 'active', 10.5), "
                "('b@example.com', 'active', 20.0), "
                "('c@example.com', 'inactive', NULL)"
            )
        )
    engine.dispose()

    cfg = _ddl_config(tmp_path)
    cfg = cfg.model_copy(
        update={
            "connector": cfg.connector.model_copy(update={"connection_string": f"sqlite:///{db_path}"})
        }
    )
    mir = MIRDatabase(
        name="profile",
        dialect="sqlite",
        schemas=[
            MIRSchema(
                name="public",
                tables=[
                    MIRTable(
                        name="customers",
                        schema_name="public",
                        columns=[
                            MIRColumn(
                                name="email",
                                data_type="TEXT",
                                normalized_type=NormalizedType.STRING,
                                ordinal_position=1,
                            ),
                            MIRColumn(
                                name="status",
                                data_type="TEXT",
                                normalized_type=NormalizedType.STRING,
                                ordinal_position=2,
                            ),
                            MIRColumn(
                                name="total_amount",
                                data_type="NUMERIC",
                                normalized_type=NormalizedType.DECIMAL,
                                ordinal_position=3,
                            ),
                        ],
                    )
                ],
            )
        ],
    )
    ctx = CompilationContext(config=cfg, output_dir=tmp_path, mir=mir)

    result = await DataProfilerStage().run(ctx)

    assert result.status == StageStatus.COMPLETED
    assert ctx.profiles is not None
    email_profile = ctx.profiles.get_profile("public", "customers", "email")
    amount_profile = ctx.profiles.get_profile("public", "customers", "total_amount")
    assert email_profile.pattern_summary == "email-like"
    assert amount_profile.mean_value == pytest.approx(15.25)
    assert (tmp_path / "mir" / "profiles.jsonl").exists()


def test_cli_compile_runs_phase3_ddl_pipeline(tmp_path: Path) -> None:
    runner = CliRunner()

    result = runner.invoke(app, ["compile", "--source", str(FIXTURE), "--output", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert (tmp_path / "mir" / "database.jsonl").exists()
    assert (tmp_path / "mir" / "database_enriched.jsonl").exists()
    assert (tmp_path / "build_manifest.json").exists()
