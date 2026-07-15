"""Stage 1: schema parser."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from skc.connectors import create_connector
from skc.ir.common import StageStatus
from skc.pipeline.base import PipelineStage, StageResult
from skc.pipeline.context import CompilationContext


class SchemaParserStage(PipelineStage):
    """Extract source metadata into MIR."""

    name = "schema_parser"
    version = "0.1.0"
    description = "Extract source database or DDL metadata into MIR."
    requires: list[str] = []
    produces = ["mir_database"]

    async def validate_inputs(self, ctx: CompilationContext) -> list[str]:
        connector = ctx.config.connector
        errors: list[str] = []
        if connector.type == "ddl_file" and not connector.ddl_path:
            errors.append("connector.ddl_path is required for ddl_file connector")
        if connector.type == "ddl_file" and connector.ddl_path and not Path(connector.ddl_path).expanduser().exists():
            errors.append(f"DDL file does not exist: {connector.ddl_path}")
        live_connectors = {"postgres", "mysql", "snowflake", "bigquery"}
        if connector.type in live_connectors and not connector.connection_string:
            errors.append(f"connector.connection_string is required for {connector.type} connector")
        if connector.type not in {"ddl_file", *live_connectors}:
            errors.append(f"Unsupported connector type: {connector.type}")
        return errors

    async def run(self, ctx: CompilationContext) -> StageResult:
        started_at = datetime.utcnow()
        connector = create_connector(ctx.config.connector)

        with connector:
            mir = connector.extract_metadata()

        ctx.set_mir(mir)
        artefact_path = ctx.output_dir / "mir" / "database.jsonl"
        mir.to_jsonl(artefact_path)
        ctx.register_artefact("mir_database", artefact_path)

        tables = mir.get_all_tables()
        stats = {
            "schemas_parsed": len(mir.schemas),
            "tables_parsed": len(tables),
            "columns_parsed": sum(len(table.columns) for table in tables),
            "fks_found": sum(len(table.foreign_keys) for table in tables),
        }
        return self._create_result(
            StageStatus.COMPLETED,
            started_at,
            artefacts=["mir_database"],
            stats=stats,
        )
