"""Stage 4: semantic inferencer."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from skc.ir.common import NormalizedType, Provenance, SourceType, StageStatus
from skc.ir.kir import (
    BusinessConcept,
    BusinessEntity,
    KnowledgeGraph,
    SecurityTag,
    Synonym,
    TimeIntelligence,
)
from skc.ir.mir import MIRColumn, MIRColumnProfile, MIRTable, TableTopology
from skc.llm.client import LLMClient
from skc.llm.response_schemas import (
    ConceptInferenceResponse,
    EntityIdentificationResponse,
    SynonymSuggestionResponse,
    TableDescriptionResponse,
)
from skc.pipeline.base import PipelineStage, StageResult
from skc.pipeline.context import CompilationContext
from skc.plugins.loader import PluginLoader
from skc.plugins.registry import PluginRegistry
from skc.stages.semantic_helpers import (
    column_ref,
    confidence,
    deterministic_provenance,
    entity_name_for_table,
    humanize_identifier,
    stable_id,
    table_ref,
)


class SemanticInferencerStage(PipelineStage):
    """Build initial semantic KIR nodes from MIR metadata."""

    name = "semantic_inferencer"
    version = "0.1.0"
    description = "Infer entities, concepts, synonyms, time intelligence, and security tags."
    requires = ["schema_graph_builder"]
    produces = ["kir_initial"]

    async def validate_inputs(self, ctx: CompilationContext) -> list[str]:
        return [] if ctx.mir is not None else ["MIR is required before semantic inference"]

    async def run(self, ctx: CompilationContext) -> StageResult:
        started_at = datetime.utcnow()
        mir = ctx.get_mir()
        graph = KnowledgeGraph()

        for table in mir.get_all_tables():
            entity = self._entity_for_table(table, ctx.build_version)
            graph.add_entity(entity)
            for synonym in entity.synonyms:
                graph.add_synonym(synonym)

            for column in table.columns:
                concept = self._concept_for_column(table, column, ctx.build_version)
                graph.add_concept(concept)
                for synonym in concept.synonyms:
                    graph.add_synonym(synonym)

                time_item = self._time_intelligence(table, column, ctx.build_version)
                if time_item is not None:
                    graph.add_time_intelligence(time_item)

                security_tag = self._security_tag(table, column, self._profile(ctx, table, column), ctx.build_version)
                if security_tag is not None:
                    graph.add_security_tag(security_tag)

        plugin_entities, plugin_synonyms = self._plugin_seeds(ctx)
        existing_entity_names = {entity.name.lower() for entity in graph.entities}
        for entity in plugin_entities:
            if entity.name.lower() not in existing_entity_names:
                graph.add_entity(entity)
                existing_entity_names.add(entity.name.lower())

        existing_synonyms = {
            (synonym.term.lower(), synonym.canonical_name.lower())
            for synonym in graph.synonyms
        }
        for synonym in plugin_synonyms:
            key = (synonym.term.lower(), synonym.canonical_name.lower())
            if key not in existing_synonyms:
                graph.add_synonym(synonym)
                existing_synonyms.add(key)

        llm_stats = self._apply_llm_enrichment(ctx, graph) if ctx.config.llm.enabled else {}

        ctx.update_kir(graph)
        kir_path = ctx.output_dir / "kir" / "initial.jsonl"
        from skc.ir.serde import write_jsonl

        write_jsonl(kir_path, [graph])
        ctx.register_artefact("kir_initial", kir_path)

        return self._create_result(
            StageStatus.COMPLETED,
            started_at,
            artefacts=["kir_initial"],
            stats={
                "entities": len(graph.entities),
                "concepts": len(graph.concepts),
                "synonyms": len(graph.synonyms),
                "time_intelligence": len(graph.time_intelligence),
                "security_tags": len(graph.security_tags),
                "plugin_entities": len(plugin_entities),
                "plugin_synonyms": len(plugin_synonyms),
                **llm_stats,
            },
        )

    def _entity_for_table(self, table: MIRTable, build_version: str) -> BusinessEntity:
        name = entity_name_for_table(table)
        topology = table.table_topology.value if table.table_topology else "UNKNOWN"
        entity_type = self._entity_type(table.table_topology)
        synonyms = self._synonyms(name, table.name, build_version)
        return BusinessEntity(
            id=stable_id("entity", table_ref(table)),
            name=name,
            description=f"Business entity inferred from {table_ref(table)}.",
            mapped_tables=[table_ref(table)],
            entity_type=entity_type,
            source_schema=table.schema_name,
            source_table=table.name,
            synonyms=synonyms,
            confidence=confidence(0.72, f"Derived from table topology {topology}."),
            provenance=deterministic_provenance(self.name, build_version),
            build_version=build_version,
            metadata={"source_table": table_ref(table), "table_topology": topology},
        )

    def _entity_type(self, topology: TableTopology | None) -> str:
        if topology == TableTopology.FACT:
            return "transactional"
        if topology == TableTopology.DIMENSION:
            return "reference"
        if topology == TableTopology.BRIDGE:
            return "bridge"
        return "core"

    def _concept_for_column(
        self,
        table: MIRTable,
        column: MIRColumn,
        build_version: str,
    ) -> BusinessConcept:
        ref = column_ref(table, column)
        category = self._concept_category(column)
        name = humanize_identifier(column.name)
        synonyms = self._synonyms(name, column.name, build_version)
        return BusinessConcept(
            id=stable_id("concept", ref),
            name=name,
            description=f"{category.title()} concept inferred from {ref}.",
            category=category,
            mapped_columns=[ref],
            source_column=column.name,
            source_table=table_ref(table),
            synonyms=synonyms,
            confidence=confidence(0.68, "Derived from column name and normalized type."),
            provenance=deterministic_provenance(self.name, build_version),
            build_version=build_version,
            metadata={
                "source_column": ref,
                "expected_type": column.normalized_type.value,
                "category": category,
            },
        )

    def _concept_category(self, column: MIRColumn) -> str:
        name = column.name.lower()
        if column.normalized_type in {NormalizedType.INTEGER, NormalizedType.FLOAT, NormalizedType.DECIMAL}:
            if any(token in name for token in ("amount", "total", "price", "rate", "balance", "quantity", "count")):
                return "measure"
        if column.normalized_type in {NormalizedType.DATE, NormalizedType.TIMESTAMP, NormalizedType.DATETIME}:
            return "temporal"
        if any(token in name for token in ("status", "state", "type", "category", "segment", "flag")):
            return "classification"
        if name.endswith("_id") or name == "id" or name.endswith("_code"):
            return "dimension"
        return "dimension"

    def _synonyms(self, canonical_name: str, source_name: str, build_version: str) -> list[Synonym]:
        candidates = {
            source_name,
            source_name.replace("_", " "),
            canonical_name,
        }
        return [
            Synonym(
                term=term,
                canonical_name=canonical_name,
                confidence=confidence(0.65, "Generated from identifier variants."),
                provenance=deterministic_provenance(self.name, build_version),
            )
            for term in sorted(candidates)
            if term and term.lower() != canonical_name.lower()
        ]

    def _time_intelligence(
        self,
        table: MIRTable,
        column: MIRColumn,
        build_version: str,
    ) -> TimeIntelligence | None:
        if column.normalized_type not in {NormalizedType.DATE, NormalizedType.TIMESTAMP, NormalizedType.DATETIME}:
            return None

        name = column.name.lower()
        if "created" in name:
            role = "created_at"
        elif "updated" in name:
            role = "updated_at"
        elif "effective" in name:
            role = "effective_from"
        elif "expire" in name or "expired" in name:
            role = "effective_to"
        elif "partition" in name:
            role = "partition"
        else:
            role = "event_time"

        granularity = "day" if column.normalized_type == NormalizedType.DATE else "second"
        ref = column_ref(table, column)
        return TimeIntelligence(
            id=stable_id("time", ref),
            name=humanize_identifier(column.name),
            column_ref=ref,
            time_role=role,
            granularity=granularity,
            confidence=confidence(0.78, "Derived from date/time type and column name."),
            provenance=deterministic_provenance(self.name, build_version),
            metadata={"source_column": ref, "expected_type": column.normalized_type.value},
        )

    def _security_tag(
        self,
        table: MIRTable,
        column: MIRColumn,
        profile: MIRColumnProfile | None,
        build_version: str,
    ) -> SecurityTag | None:
        lower = column.name.lower()
        classification = None
        if any(token in lower for token in ("email", "phone", "ssn", "social_security")):
            classification = "PII"
        elif any(token in lower for token in ("password", "token", "secret")):
            classification = "RESTRICTED"
        elif profile and profile.pattern_summary in {"email-like", "phone-like"}:
            classification = "PII"

        if classification is None:
            return None

        ref = column_ref(table, column)
        return SecurityTag(
            id=stable_id("security", ref, classification),
            name=f"{classification} {humanize_identifier(column.name)}",
            scope=ref,
            classification=classification,
            applies_to=[ref],
            tags=[classification.lower()],
            confidence=confidence(0.82, "Derived from sensitive column naming or profile pattern."),
            provenance=deterministic_provenance(self.name, build_version),
            metadata={"source_column": ref, "classification": classification},
        )

    def _profile(
        self,
        ctx: CompilationContext,
        table: MIRTable,
        column: MIRColumn,
    ) -> MIRColumnProfile | None:
        if ctx.profiles is None:
            return None
        return ctx.profiles.get_profile(table.schema_name, table.name, column.name)

    def _plugin_seeds(self, ctx: CompilationContext) -> tuple[list[BusinessEntity], list[Synonym]]:
        registry = PluginRegistry()
        loader = PluginLoader(registry)
        for search_path in ctx.config.plugins.search_paths:
            loader.load_from_directory(search_path)

        enabled = set(ctx.config.plugins.enabled)
        if not enabled:
            return [], []

        entities: list[BusinessEntity] = []
        synonyms: list[Synonym] = []
        for plugin in registry.get_all():
            if plugin.name not in enabled:
                continue
            entities.extend(plugin.get_ontology())
            for canonical_name, terms in plugin.get_synonyms().items():
                for term in terms:
                    synonyms.append(
                        Synonym(
                            term=term,
                            canonical_name=canonical_name,
                            confidence=plugin._make_confidence(float(getattr(plugin, "trust_score", 0.75))),
                            provenance=[plugin._make_provenance()],
                        )
                    )
        return entities, synonyms

    def _apply_llm_enrichment(self, ctx: CompilationContext, graph: KnowledgeGraph) -> dict:
        """Run optional LLM enrichment, always falling back to deterministic output."""
        stats: dict[str, int | bool] = {
            "llm_enabled": True,
            "llm_calls_attempted": 0,
            "llm_entities_added": 0,
            "llm_concepts_added": 0,
            "llm_synonyms_added": 0,
            "llm_descriptions_updated": 0,
        }
        client = LLMClient(ctx.config.llm, cache_dir=ctx.output_dir / "llm_cache")

        entity_response = self._complete(
            ctx,
            client,
            "entity_identification.j2",
            EntityIdentificationResponse,
            {"entities": []},
            metadata_json=self._tables_metadata_json(ctx),
            stats=stats,
        )
        known_tables = {table_ref(table) for table in ctx.get_mir().get_all_tables()}
        existing_entity_names = {entity.name.lower() for entity in graph.entities}
        for candidate in entity_response.entities:
            mapped_tables = [ref for ref in candidate.mapped_tables if ref in known_tables]
            if not mapped_tables or candidate.name.lower() in existing_entity_names:
                continue
            graph.add_entity(
                BusinessEntity(
                    id=stable_id("llm_entity", candidate.name, *mapped_tables),
                    name=candidate.name,
                    description=candidate.description,
                    mapped_tables=mapped_tables,
                    entity_type="core",
                    confidence=confidence(candidate.confidence, "Suggested by optional LLM enrichment."),
                    provenance=[self._llm_provenance(ctx, "entity_identification")],
                    build_version=ctx.build_version,
                    metadata={"llm_raw_confidence": candidate.confidence, "mapped_tables": mapped_tables},
                )
            )
            existing_entity_names.add(candidate.name.lower())
            stats["llm_entities_added"] += 1

        concept_response = self._complete(
            ctx,
            client,
            "concept_inference.j2",
            ConceptInferenceResponse,
            {"concepts": []},
            metadata_json=self._columns_metadata_json(ctx),
            stats=stats,
        )
        known_columns = {
            column_ref(table, column)
            for table in ctx.get_mir().get_all_tables()
            for column in table.columns
        }
        existing_concepts = {(concept.name.lower(), tuple(concept.mapped_columns)) for concept in graph.concepts}
        for candidate in concept_response.concepts:
            mapped_columns = [ref for ref in candidate.mapped_columns if ref in known_columns]
            key = (candidate.name.lower(), tuple(mapped_columns))
            if not mapped_columns or key in existing_concepts:
                continue
            graph.add_concept(
                BusinessConcept(
                    id=stable_id("llm_concept", candidate.name, *mapped_columns),
                    name=candidate.name,
                    description=candidate.description,
                    category=candidate.category or "dimension",
                    mapped_columns=mapped_columns,
                    confidence=confidence(candidate.confidence, "Suggested by optional LLM enrichment."),
                    provenance=[self._llm_provenance(ctx, "concept_inference")],
                    build_version=ctx.build_version,
                    metadata={"llm_raw_confidence": candidate.confidence, "mapped_columns": mapped_columns},
                )
            )
            existing_concepts.add(key)
            stats["llm_concepts_added"] += 1

        graph.entities = self._llm_describe_entities(ctx, client, graph.entities, stats)
        self._llm_add_synonyms(ctx, client, graph, stats)
        stats["llm_usage"] = client.usage_summary()
        return stats

    def _complete(
        self,
        ctx: CompilationContext,
        client: LLMClient,
        template_name: str,
        response_model,
        fallback: dict,
        stats: dict[str, int | bool],
        **template_args,
    ):
        stats["llm_calls_attempted"] += 1
        prompt = self._render_prompt(template_name, **template_args)
        return client.complete_json(
            prompt,
            response_model,
            max_retries=ctx.config.llm.max_retries,
            fallback=fallback,
        )

    def _llm_describe_entities(
        self,
        ctx: CompilationContext,
        client: LLMClient,
        entities: list[BusinessEntity],
        stats: dict[str, int | bool],
    ) -> list[BusinessEntity]:
        tables = {table_ref(table): table for table in ctx.get_mir().get_all_tables()}
        updated: list[BusinessEntity] = []
        for entity in entities:
            if not entity.mapped_tables:
                updated.append(entity)
                continue
            table = tables.get(entity.mapped_tables[0])
            if table is None:
                updated.append(entity)
                continue
            response = self._complete(
                ctx,
                client,
                "table_description.j2",
                TableDescriptionResponse,
                {"description": entity.description, "confidence": entity.confidence.score},
                metadata_json=json.dumps(self._table_metadata(table), sort_keys=True),
                stats=stats,
            )
            if response.description and response.description != entity.description:
                updated.append(
                    entity.model_copy(
                        update={
                            "description": response.description,
                            "confidence": confidence(
                                max(entity.confidence.score, response.confidence),
                                "Description enriched by optional LLM pass.",
                            ),
                            "metadata": {
                                **entity.metadata,
                                "llm_raw_confidence": response.confidence,
                            },
                        }
                    )
                )
                stats["llm_descriptions_updated"] += 1
            else:
                updated.append(entity)
        return updated

    def _llm_add_synonyms(
        self,
        ctx: CompilationContext,
        client: LLMClient,
        graph: KnowledgeGraph,
        stats: dict[str, int | bool],
    ) -> None:
        existing = {
            (synonym.term.lower(), synonym.canonical_name.lower())
            for synonym in graph.synonyms
        }
        terms = [entity.name for entity in graph.entities] + [concept.name for concept in graph.concepts]
        for term in terms[:50]:
            response = self._complete(
                ctx,
                client,
                "synonym_suggestion.j2",
                SynonymSuggestionResponse,
                {"synonyms": []},
                term=term,
                stats=stats,
            )
            for candidate in response.synonyms:
                key = (candidate.term.lower(), term.lower())
                if key in existing or candidate.term.lower() == term.lower():
                    continue
                graph.add_synonym(
                    Synonym(
                        term=candidate.term,
                        canonical_name=term,
                        language=candidate.language,
                        confidence=confidence(candidate.confidence, "Suggested by optional LLM enrichment."),
                        provenance=[self._llm_provenance(ctx, "synonym_suggestion")],
                    )
                )
                existing.add(key)
                stats["llm_synonyms_added"] += 1

    def _render_prompt(self, template_name: str, **kwargs) -> str:
        prompt_dir = Path(__file__).resolve().parents[1] / "llm" / "prompts"
        env = Environment(loader=FileSystemLoader(prompt_dir), autoescape=False)
        return env.get_template(template_name).render(**kwargs)

    def _tables_metadata_json(self, ctx: CompilationContext) -> str:
        return json.dumps(
            [self._table_metadata(table) for table in ctx.get_mir().get_all_tables()],
            sort_keys=True,
        )

    def _columns_metadata_json(self, ctx: CompilationContext) -> str:
        return json.dumps(
            [
                {
                    "column": column_ref(table, column),
                    "data_type": column.data_type,
                    "normalized_type": column.normalized_type.value,
                    "nullable": column.is_nullable,
                    "profile": (
                        self._profile(ctx, table, column).model_dump(mode="json")
                        if self._profile(ctx, table, column)
                        else None
                    ),
                }
                for table in ctx.get_mir().get_all_tables()
                for column in table.columns
            ],
            sort_keys=True,
        )

    def _table_metadata(self, table: MIRTable) -> dict:
        return {
            "table": table_ref(table),
            "table_type": str(table.table_type),
            "topology": table.table_topology.value if table.table_topology else None,
            "columns": [
                {
                    "name": column.name,
                    "data_type": column.data_type,
                    "normalized_type": column.normalized_type.value,
                    "nullable": column.is_nullable,
                }
                for column in table.columns
            ],
        }

    def _llm_provenance(self, ctx: CompilationContext, task: str) -> Provenance:
        return Provenance(
            source_type=SourceType.LLM_INFERRED,
            source_id=f"llm:{ctx.config.llm.model}:{task}",
            source_detail="optional LLM enrichment",
            build_version=ctx.build_version,
        )
