"""Stage 6: metric discovery."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from skc.ir.common import Provenance, SourceType
from skc.ir.common import NormalizedType, StageStatus
from skc.ir.kir import Metric
from skc.ir.mir import MIRColumn, MIRTable
from skc.ir.serde import write_jsonl
from skc.llm.client import LLMClient
from skc.llm.response_schemas import MetricInferenceResponse
from skc.pipeline.base import PipelineStage, StageResult
from skc.pipeline.context import CompilationContext
from skc.plugins.loader import PluginLoader
from skc.plugins.registry import PluginRegistry
from skc.stages.semantic_helpers import (
    column_ref,
    confidence,
    deterministic_provenance,
    humanize_identifier,
    stable_id,
    table_ref,
)


class MetricDiscoveryStage(PipelineStage):
    """Discover deterministic and plugin-provided metric candidates."""

    name = "metric_discovery"
    version = "0.1.0"
    description = "Discover candidate metrics from numeric metadata."
    requires = ["relationship_analyzer"]
    produces = ["kir_metrics"]

    async def validate_inputs(self, ctx: CompilationContext) -> list[str]:
        errors: list[str] = []
        if ctx.mir is None:
            errors.append("MIR is required before metric discovery")
        if not ctx.kir.entities:
            errors.append("KIR entities are required before metric discovery")
        return errors

    async def run(self, ctx: CompilationContext) -> StageResult:
        started_at = datetime.utcnow()
        graph = ctx.get_kir()
        existing = {metric.id for metric in graph.metrics}
        metrics = list(graph.metrics)

        for table in ctx.get_mir().get_all_tables():
            numeric_columns = [column for column in table.columns if self._is_numeric(column)]
            for column in numeric_columns:
                if self._looks_metric(column):
                    for metric in self._aggregation_metrics(table, column, ctx.build_version):
                        if metric.id not in existing:
                            metrics.append(metric)
                            existing.add(metric.id)
            for metric in self._ratio_metrics(table, numeric_columns, ctx.build_version):
                if metric.id not in existing:
                    metrics.append(metric)
                    existing.add(metric.id)

        for plugin_metric in self._plugin_metrics(ctx):
            if plugin_metric.id not in existing:
                metrics.append(plugin_metric)
                existing.add(plugin_metric.id)

        llm_added = 0
        llm_usage = {}
        if ctx.config.llm.enabled:
            llm_metrics, llm_usage = self._llm_metrics(ctx)
            for llm_metric in llm_metrics:
                if llm_metric.id not in existing:
                    metrics.append(llm_metric)
                    existing.add(llm_metric.id)
                    llm_added += 1

        graph = graph.model_copy(update={"metrics": metrics})
        ctx.update_kir(graph)
        path = ctx.output_dir / "kir" / "metrics.jsonl"
        write_jsonl(path, [graph])
        ctx.register_artefact("kir_metrics", path)

        return self._create_result(
            StageStatus.COMPLETED,
            started_at,
            artefacts=["kir_metrics"],
            stats={"metrics": len(metrics), "llm_metrics_added": llm_added, "llm_usage": llm_usage},
        )

    def _is_numeric(self, column: MIRColumn) -> bool:
        return column.normalized_type in {NormalizedType.INTEGER, NormalizedType.FLOAT, NormalizedType.DECIMAL}

    def _looks_metric(self, column: MIRColumn) -> bool:
        lower = column.name.lower()
        return any(
            token in lower
            for token in ("amount", "total", "count", "quantity", "price", "rate", "balance", "premium", "loss")
        )

    def _aggregation_metrics(self, table: MIRTable, column: MIRColumn, build_version: str) -> list[Metric]:
        ref = column_ref(table, column)
        metric_base = humanize_identifier(column.name)
        aggregations = ["SUM", "AVG", "MIN", "MAX"]
        if column.normalized_type == NormalizedType.INTEGER and "count" in column.name.lower():
            aggregations = ["SUM", "AVG"]
        return [
            Metric(
                id=stable_id("metric", ref, aggregation),
                name=f"{aggregation.title()} {metric_base}",
                description=f"{aggregation} aggregation over {ref}.",
                formula=f"{aggregation}({ref})",
                formula_type="aggregation",
                base_columns=[ref],
                source_columns=[ref],
                confidence=confidence(0.74, "Generated from numeric metric naming pattern."),
                provenance=deterministic_provenance(self.name, build_version),
                build_version=build_version,
                metadata={"source_column": ref, "aggregation": aggregation},
            )
            for aggregation in aggregations
        ]

    def _ratio_metrics(
        self,
        table: MIRTable,
        numeric_columns: list[MIRColumn],
        build_version: str,
    ) -> list[Metric]:
        amount_columns = [column for column in numeric_columns if "amount" in column.name.lower() or "total" in column.name.lower()]
        count_columns = [column for column in numeric_columns if "count" in column.name.lower() or "quantity" in column.name.lower()]
        metrics: list[Metric] = []
        for numerator in amount_columns[:2]:
            for denominator in count_columns[:2]:
                if numerator.name == denominator.name:
                    continue
                numerator_ref = column_ref(table, numerator)
                denominator_ref = column_ref(table, denominator)
                metrics.append(
                    Metric(
                        id=stable_id("metric", numerator_ref, denominator_ref, "ratio"),
                        name=f"{humanize_identifier(numerator.name)} per {humanize_identifier(denominator.name)}",
                        description=f"Ratio of {numerator_ref} to {denominator_ref}.",
                        formula=f"{numerator_ref} / NULLIF({denominator_ref}, 0)",
                        formula_type="ratio",
                        base_columns=[numerator_ref, denominator_ref],
                        source_columns=[numerator_ref, denominator_ref],
                        confidence=confidence(0.62, "Generated from numeric column ratio heuristic."),
                        provenance=deterministic_provenance(self.name, build_version),
                        build_version=build_version,
                        metadata={"source_table": table_ref(table), "formula_type": "ratio"},
                    )
                )
        return metrics

    def _plugin_metrics(self, ctx: CompilationContext) -> list[Metric]:
        registry = PluginRegistry()
        loader = PluginLoader(registry)
        for search_path in ctx.config.plugins.search_paths:
            loader.load_from_directory(search_path)
        enabled = set(ctx.config.plugins.enabled)
        if not enabled:
            return []

        metrics: list[Metric] = []
        for plugin in registry.get_all():
            if plugin.name not in enabled:
                continue
            metrics.extend(plugin.get_metrics())
        return metrics

    def _llm_metrics(self, ctx: CompilationContext) -> tuple[list[Metric], dict]:
        numeric_columns = [
            {
                "column": column_ref(table, column),
                "data_type": column.data_type,
                "normalized_type": column.normalized_type.value,
            }
            for table in ctx.get_mir().get_all_tables()
            for column in table.columns
            if self._is_numeric(column)
        ]
        if not numeric_columns:
            return [], {}

        prompt = self._render_prompt(
            "metric_inference.j2",
            metadata_json=json.dumps(numeric_columns, sort_keys=True),
        )
        client = LLMClient(ctx.config.llm, cache_dir=ctx.output_dir / "llm_cache")
        response = client.complete_json(
            prompt,
            MetricInferenceResponse,
            max_retries=ctx.config.llm.max_retries,
            fallback={"metrics": []},
        )
        known_columns = {item["column"] for item in numeric_columns}
        metrics: list[Metric] = []
        for candidate in response.metrics:
            base_columns = [ref for ref in candidate.base_columns if ref in known_columns]
            if not base_columns:
                continue
            metrics.append(
                Metric(
                    id=stable_id("llm_metric", candidate.name, *base_columns),
                    name=candidate.name,
                    description=candidate.description,
                    formula=candidate.formula,
                    formula_type=candidate.formula_type or "derived",
                    base_columns=base_columns,
                    source_columns=base_columns,
                    confidence=confidence(candidate.confidence, "Suggested by optional LLM metric pass."),
                    provenance=[self._llm_provenance(ctx)],
                    build_version=ctx.build_version,
                    metadata={"llm_raw_confidence": candidate.confidence},
                )
            )
        return metrics, client.usage_summary()

    def _render_prompt(self, template_name: str, **kwargs) -> str:
        prompt_dir = Path(__file__).resolve().parents[1] / "llm" / "prompts"
        env = Environment(loader=FileSystemLoader(prompt_dir), autoescape=False)
        return env.get_template(template_name).render(**kwargs)

    def _llm_provenance(self, ctx: CompilationContext) -> Provenance:
        return Provenance(
            source_type=SourceType.LLM_INFERRED,
            source_id=f"llm:{ctx.config.llm.model}:metric_inference",
            source_detail="optional LLM metric enrichment",
            build_version=ctx.build_version,
        )
