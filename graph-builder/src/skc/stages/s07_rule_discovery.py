"""Stage 7: business rule discovery."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from skc.ir.common import Provenance, SourceType
from skc.ir.mir import ConstraintType, MIRColumn, MIRColumnProfile, MIRConstraint, MIRTable
from skc.ir.common import NormalizedType, StageStatus
from skc.ir.kir import BusinessRule
from skc.ir.serde import write_jsonl
from skc.llm.client import LLMClient
from skc.llm.response_schemas import RuleInferenceResponse
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


class RuleDiscoveryStage(PipelineStage):
    """Discover business rules from constraints, profiles, and plugins."""

    name = "rule_discovery"
    version = "0.1.0"
    description = "Discover candidate business rules."
    requires = ["metric_discovery"]
    produces = ["kir_rules"]

    async def validate_inputs(self, ctx: CompilationContext) -> list[str]:
        return [] if ctx.mir is not None else ["MIR is required before rule discovery"]

    async def run(self, ctx: CompilationContext) -> StageResult:
        started_at = datetime.utcnow()
        graph = ctx.get_kir()
        existing = {rule.id for rule in graph.rules}
        rules = list(graph.rules)

        for table in ctx.get_mir().get_all_tables():
            for constraint in table.constraints:
                rule = self._constraint_rule(table, constraint, ctx.build_version)
                if rule.id not in existing:
                    rules.append(rule)
                    existing.add(rule.id)
            for column in table.columns:
                for rule in self._profile_rules(ctx, table, column, ctx.build_version):
                    if rule.id not in existing:
                        rules.append(rule)
                        existing.add(rule.id)

        for plugin_rule in self._plugin_rules(ctx):
            if plugin_rule.id not in existing:
                rules.append(plugin_rule)
                existing.add(plugin_rule.id)

        llm_added = 0
        llm_usage = {}
        if ctx.config.llm.enabled:
            llm_rules, llm_usage = self._llm_rules(ctx)
            for llm_rule in llm_rules:
                if llm_rule.id not in existing:
                    rules.append(llm_rule)
                    existing.add(llm_rule.id)
                    llm_added += 1

        graph = graph.model_copy(update={"rules": rules})
        ctx.update_kir(graph)
        path = ctx.output_dir / "kir" / "rules.jsonl"
        write_jsonl(path, [graph])
        ctx.register_artefact("kir_rules", path)

        return self._create_result(
            StageStatus.COMPLETED,
            started_at,
            artefacts=["kir_rules"],
            stats={"rules": len(rules), "llm_rules_added": llm_added, "llm_usage": llm_usage},
        )

    def _constraint_rule(
        self,
        table: MIRTable,
        constraint: MIRConstraint,
        build_version: str,
    ) -> BusinessRule:
        source_table = table_ref(table)
        rule_type = self._rule_type(constraint.type)
        columns = [f"{source_table}.{column}" for column in constraint.columns]
        expression = constraint.expression or self._constraint_expression(constraint, source_table)
        return BusinessRule(
            id=stable_id("rule", source_table, constraint.name, constraint.type.value),
            name=humanize_identifier(constraint.name),
            description=f"{constraint.type.value.title()} rule extracted from {source_table}.",
            rule_type=rule_type,
            expression=expression,
            scope_tables=[source_table],
            scope_columns=columns,
            confidence=confidence(0.88, "Extracted from deterministic source constraint."),
            provenance=deterministic_provenance(self.name, build_version),
            build_version=build_version,
            metadata={"source_table": source_table, "constraint_type": constraint.type.value},
        )

    def _rule_type(self, constraint_type: ConstraintType) -> str:
        if constraint_type == ConstraintType.CHECK:
            return "constraint"
        if constraint_type == ConstraintType.NOT_NULL:
            return "validation"
        if constraint_type == ConstraintType.DEFAULT:
            return "derivation"
        return "constraint"

    def _constraint_expression(self, constraint: MIRConstraint, source_table: str) -> str:
        if constraint.type == ConstraintType.NOT_NULL and constraint.columns:
            return f"{source_table}.{constraint.columns[0]} IS NOT NULL"
        if constraint.type == ConstraintType.UNIQUE and constraint.columns:
            return f"UNIQUE({', '.join(f'{source_table}.{column}' for column in constraint.columns)})"
        if constraint.type == ConstraintType.DEFAULT and constraint.columns:
            return f"{source_table}.{constraint.columns[0]} DEFAULT {constraint.expression or ''}".strip()
        return constraint.name

    def _profile_rules(
        self,
        ctx: CompilationContext,
        table: MIRTable,
        column: MIRColumn,
        build_version: str,
    ) -> list[BusinessRule]:
        if ctx.profiles is None:
            return []
        profile = ctx.profiles.get_profile(table.schema_name, table.name, column.name)
        if profile is None:
            return []

        rules: list[BusinessRule] = []
        ref = column_ref(table, column)
        if profile.null_ratio == 0 and column.is_nullable:
            rules.append(
                BusinessRule(
                    id=stable_id("rule", ref, "profile_not_null"),
                    name=f"{humanize_identifier(column.name)} Required",
                    description=f"Profile indicates {ref} has no null values.",
                    rule_type="validation",
                    expression=f"{ref} IS NOT NULL",
                    scope_tables=[table_ref(table)],
                    scope_columns=[ref],
                    confidence=confidence(0.66, "Inferred from profile null ratio."),
                    provenance=deterministic_provenance(self.name, build_version),
                    build_version=build_version,
                    metadata={"source_column": ref, "profile_rule": "not_null"},
                )
            )

        if profile.pattern_summary == "enum-like" and profile.value_distribution:
            allowed = ", ".join(repr(value) for value in sorted(profile.value_distribution))
            rules.append(
                BusinessRule(
                    id=stable_id("rule", ref, "enum_values"),
                    name=f"{humanize_identifier(column.name)} Allowed Values",
                    description=f"Profile indicates {ref} is enum-like.",
                    rule_type="classification",
                    expression=f"{ref} IN ({allowed})",
                    scope_tables=[table_ref(table)],
                    scope_columns=[ref],
                    confidence=confidence(0.63, "Inferred from profile value distribution."),
                    provenance=deterministic_provenance(self.name, build_version),
                    build_version=build_version,
                    metadata={"source_column": ref, "profile_rule": "enum"},
                )
            )

        if column.normalized_type in {NormalizedType.INTEGER, NormalizedType.FLOAT, NormalizedType.DECIMAL}:
            try:
                min_value = float(profile.min_value) if profile.min_value is not None else None
            except ValueError:
                min_value = None
            if min_value is not None and min_value >= 0:
                rules.append(
                    BusinessRule(
                        id=stable_id("rule", ref, "non_negative"),
                        name=f"{humanize_identifier(column.name)} Non Negative",
                        description=f"Profile indicates {ref} is non-negative.",
                        rule_type="validation",
                        expression=f"{ref} >= 0",
                        scope_tables=[table_ref(table)],
                        scope_columns=[ref],
                        confidence=confidence(0.64, "Inferred from profile minimum value."),
                        provenance=deterministic_provenance(self.name, build_version),
                        build_version=build_version,
                        metadata={"source_column": ref, "profile_rule": "non_negative"},
                    )
                )

        return rules

    def _plugin_rules(self, ctx: CompilationContext) -> list[BusinessRule]:
        registry = PluginRegistry()
        loader = PluginLoader(registry)
        for search_path in ctx.config.plugins.search_paths:
            loader.load_from_directory(search_path)
        enabled = set(ctx.config.plugins.enabled)
        if not enabled:
            return []

        rules: list[BusinessRule] = []
        for plugin in registry.get_all():
            if plugin.name not in enabled:
                continue
            rules.extend(plugin.get_rules())
        return rules

    def _llm_rules(self, ctx: CompilationContext) -> tuple[list[BusinessRule], dict]:
        metadata = []
        known_tables = set()
        known_columns = set()
        for table in ctx.get_mir().get_all_tables():
            source_table = table_ref(table)
            known_tables.add(source_table)
            known_columns.update(column_ref(table, column) for column in table.columns)
            metadata.append(
                {
                    "table": source_table,
                    "columns": [
                        {
                            "name": column.name,
                            "data_type": column.data_type,
                            "normalized_type": column.normalized_type.value,
                            "nullable": column.is_nullable,
                        }
                        for column in table.columns
                    ],
                    "constraints": [constraint.model_dump(mode="json") for constraint in table.constraints],
                }
            )
        if not metadata:
            return [], {}

        prompt = self._render_prompt(
            "rule_inference.j2",
            metadata_json=json.dumps(metadata, sort_keys=True),
        )
        client = LLMClient(ctx.config.llm, cache_dir=ctx.output_dir / "llm_cache")
        response = client.complete_json(
            prompt,
            RuleInferenceResponse,
            max_retries=ctx.config.llm.max_retries,
            fallback={"rules": []},
        )
        rules: list[BusinessRule] = []
        for candidate in response.rules:
            scope_tables = [ref for ref in candidate.scope_tables if ref in known_tables]
            scope_columns = [ref for ref in candidate.scope_columns if ref in known_columns]
            if not scope_tables and not scope_columns:
                continue
            rules.append(
                BusinessRule(
                    id=stable_id("llm_rule", candidate.name, *(scope_tables or scope_columns)),
                    name=candidate.name,
                    description=candidate.description,
                    rule_type=candidate.rule_type or "validation",
                    expression=candidate.expression,
                    scope_tables=scope_tables,
                    scope_columns=scope_columns,
                    confidence=confidence(candidate.confidence, "Suggested by optional LLM rule pass."),
                    provenance=[self._llm_provenance(ctx)],
                    build_version=ctx.build_version,
                    metadata={"llm_raw_confidence": candidate.confidence},
                )
            )
        return rules, client.usage_summary()

    def _render_prompt(self, template_name: str, **kwargs) -> str:
        prompt_dir = Path(__file__).resolve().parents[1] / "llm" / "prompts"
        env = Environment(loader=FileSystemLoader(prompt_dir), autoescape=False)
        return env.get_template(template_name).render(**kwargs)

    def _llm_provenance(self, ctx: CompilationContext) -> Provenance:
        return Provenance(
            source_type=SourceType.LLM_INFERRED,
            source_id=f"llm:{ctx.config.llm.model}:rule_inference",
            source_detail="optional LLM rule enrichment",
            build_version=ctx.build_version,
        )
