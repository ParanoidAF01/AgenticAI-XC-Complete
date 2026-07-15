"""Stage 3: data profiler."""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from skc.ir.common import NormalizedType, StageStatus
from skc.ir.mir import MIRColumn, MIRColumnProfile, MIRProfileSet, MIRTable
from skc.ir.serde import write_jsonl
from skc.pipeline.base import PipelineStage, StageResult
from skc.pipeline.context import CompilationContext


class DataProfilerStage(PipelineStage):
    """Profile live table data and attach column-level statistics."""

    name = "data_profiler"
    version = "0.1.0"
    description = "Collect optional data profiles from a live database connection."
    requires = ["schema_parser"]
    produces = ["mir_profiles"]

    async def validate_inputs(self, ctx: CompilationContext) -> list[str]:
        return [] if ctx.mir is not None else ["MIR is required before data profiling"]

    async def run(self, ctx: CompilationContext) -> StageResult:
        started_at = datetime.utcnow()
        connection_string = ctx.config.connector.connection_string
        if not connection_string:
            warning = "No live database connection configured; data profiling skipped"
            return self._create_result(StageStatus.SKIPPED, started_at, warnings=[warning])

        engine = create_engine(connection_string)
        try:
            profiles, warnings = self.profile(ctx, engine)
        finally:
            engine.dispose()

        profile_set = MIRProfileSet(profiles=profiles)
        ctx.set_profiles(profile_set)
        profile_path = ctx.output_dir / "mir" / "profiles.jsonl"
        write_jsonl(profile_path, profiles)
        ctx.register_artefact("mir_profiles", profile_path)

        return self._create_result(
            StageStatus.COMPLETED,
            started_at,
            artefacts=["mir_profiles"],
            warnings=warnings,
            stats={"profiles_written": len(profiles)},
        )

    def profile(self, ctx: CompilationContext, engine: Engine) -> tuple[list[MIRColumnProfile], list[str]]:
        """Profile all MIR columns using a SQLAlchemy engine."""
        mir = ctx.get_mir()
        stage_cfg = ctx.config.pipeline.stages.get(self.name, {})
        sample_size = int(stage_cfg.get("sample_size", 100000))
        parallel_workers = max(1, int(stage_cfg.get("parallel_workers", 1)))
        profiles: list[MIRColumnProfile] = []
        warnings: list[str] = []
        columns = [
            (table, column)
            for table in mir.get_all_tables()
            for column in table.columns
        ]

        if parallel_workers > 1 and len(columns) > 1:
            with ThreadPoolExecutor(max_workers=parallel_workers) as pool:
                futures = {
                    pool.submit(self._profile_column_with_new_connection, engine, table, column, sample_size): (
                        table,
                        column,
                    )
                    for table, column in columns
                }
                for future in as_completed(futures):
                    table, column = futures[future]
                    try:
                        profiles.append(future.result())
                    except Exception as exc:
                        warnings.append(
                            f"Failed to profile {table.schema_name}.{table.name}.{column.name}: {exc}"
                        )
            return profiles, warnings

        with engine.connect() as connection:
            for table, column in columns:
                try:
                    profiles.append(
                        self._profile_column(connection, engine, table, column, sample_size)
                    )
                except Exception as exc:
                    warnings.append(
                        f"Failed to profile {table.schema_name}.{table.name}.{column.name}: {exc}"
                    )

        return profiles, warnings

    def _profile_column_with_new_connection(
        self,
        engine: Engine,
        table: MIRTable,
        column: MIRColumn,
        sample_size: int,
    ) -> MIRColumnProfile:
        with engine.connect() as connection:
            return self._profile_column(connection, engine, table, column, sample_size)

    def _profile_column(
        self,
        connection: Any,
        engine: Engine,
        table: MIRTable,
        column: MIRColumn,
        sample_size: int,
    ) -> MIRColumnProfile:
        qualified_table = self._qualified_table(engine, table)
        quoted_column = self._quote(engine, column.name)
        sample = f"(SELECT * FROM {qualified_table} LIMIT {sample_size}) AS sample_data"

        row_count = self._scalar(connection, f"SELECT COUNT(*) FROM {sample}") or 0
        distinct_count = self._scalar(
            connection,
            f"SELECT COUNT(DISTINCT {quoted_column}) FROM {sample}",
        )
        null_count = self._scalar(
            connection,
            f"SELECT COUNT(*) FROM {sample} WHERE {quoted_column} IS NULL",
        )
        null_ratio = (float(null_count) / float(row_count)) if row_count else None

        min_value = self._optional_scalar(
            connection,
            f"SELECT MIN({quoted_column}) FROM {sample}",
        )
        max_value = self._optional_scalar(
            connection,
            f"SELECT MAX({quoted_column}) FROM {sample}",
        )
        mean_value = None
        if column.normalized_type in {NormalizedType.INTEGER, NormalizedType.FLOAT, NormalizedType.DECIMAL}:
            mean = self._optional_scalar(
                connection,
                f"SELECT AVG({quoted_column}) FROM {sample} WHERE {quoted_column} IS NOT NULL",
            )
            mean_value = float(mean) if mean is not None else None

        sample_values = [
            str(value)
            for value in self._rows(
                connection,
                f"SELECT {quoted_column} FROM {sample} WHERE {quoted_column} IS NOT NULL LIMIT 10",
            )
        ]
        value_distribution = {
            str(row[0]): int(row[1])
            for row in connection.execute(
                text(
                    f"SELECT {quoted_column}, COUNT(*) AS value_count "
                    f"FROM {sample} WHERE {quoted_column} IS NOT NULL "
                    f"GROUP BY {quoted_column} ORDER BY value_count DESC LIMIT 10"
                )
            ).fetchall()
        }

        return MIRColumnProfile(
            schema_name=table.schema_name,
            table_name=table.name,
            column_name=column.name,
            distinct_count=int(distinct_count) if distinct_count is not None else None,
            null_count=int(null_count) if null_count is not None else None,
            null_ratio=null_ratio,
            min_value=str(min_value) if min_value is not None else None,
            max_value=str(max_value) if max_value is not None else None,
            mean_value=mean_value,
            sample_values=sample_values,
            value_distribution=value_distribution,
            pattern_summary=self._pattern_summary(sample_values, distinct_count, row_count),
        )

    def _scalar(self, connection: Any, sql: str) -> Any:
        return connection.execute(text(sql)).scalar()

    def _optional_scalar(self, connection: Any, sql: str) -> Any:
        try:
            return self._scalar(connection, sql)
        except Exception:
            return None

    def _rows(self, connection: Any, sql: str) -> list[Any]:
        return [row[0] for row in connection.execute(text(sql)).fetchall()]

    def _qualified_table(self, engine: Engine, table: MIRTable) -> str:
        table_name = self._quote(engine, table.name)
        if engine.dialect.name == "sqlite" or not table.schema_name:
            return table_name
        return f"{self._quote(engine, table.schema_name)}.{table_name}"

    def _quote(self, engine: Engine, identifier: str) -> str:
        return engine.dialect.identifier_preparer.quote(identifier)

    def _pattern_summary(
        self,
        samples: list[str],
        distinct_count: int | None,
        row_count: int,
    ) -> str | None:
        if not samples:
            return None

        lowered = [sample.lower() for sample in samples]
        if all(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", sample) for sample in lowered):
            return "email-like"
        if all(re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", sample) for sample in lowered):
            return "uuid-like"
        if all(re.match(r"^\+?[0-9 .()\-]{7,}$", sample) for sample in samples):
            return "phone-like"
        if all(sample.startswith(("http://", "https://")) for sample in lowered):
            return "url-like"
        if all(sample in {"true", "false", "0", "1", "yes", "no", "t", "f", "y", "n"} for sample in lowered):
            return "boolean-like"
        if distinct_count is not None and row_count and distinct_count <= min(20, max(3, row_count // 10)):
            return "enum-like"
        if all(re.match(r"^\d{4}-\d{2}-\d{2}", sample) for sample in samples):
            return "date-string"
        return None
