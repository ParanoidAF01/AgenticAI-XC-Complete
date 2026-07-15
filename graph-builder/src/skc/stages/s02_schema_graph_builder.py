"""Stage 2: schema relationship graph builder."""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime
from typing import Any

from skc.ir.common import StageStatus
from skc.ir.mir import MIRDatabase, MIRSchema, MIRTable, TableTopology
from skc.pipeline.base import PipelineStage, StageResult
from skc.pipeline.context import CompilationContext


class SchemaGraphBuilderStage(PipelineStage):
    """Annotate MIR tables with structural topology."""

    name = "schema_graph_builder"
    version = "0.1.0"
    description = "Build table relationship graph and classify table topology."
    requires = ["schema_parser"]
    produces = ["mir_enriched", "schema_topology_report"]

    async def validate_inputs(self, ctx: CompilationContext) -> list[str]:
        return [] if ctx.mir is not None else ["MIR is required before schema graph building"]

    async def run(self, ctx: CompilationContext) -> StageResult:
        started_at = datetime.utcnow()
        mir = ctx.get_mir()
        enriched_mir, report = self.enrich_mir(mir)
        ctx.set_mir(enriched_mir)

        mir_path = ctx.output_dir / "mir" / "database_enriched.jsonl"
        enriched_mir.to_jsonl(mir_path)
        ctx.register_artefact("mir_enriched", mir_path)
        ctx.write_artefact("schema_topology_report", "mir/topology_report.json", report)

        topology_counts: dict[str, int] = defaultdict(int)
        for topology in report["table_topology"].values():
            topology_counts[topology] += 1

        return self._create_result(
            StageStatus.COMPLETED,
            started_at,
            artefacts=["mir_enriched", "schema_topology_report"],
            stats={
                "connected_components": len(report["connected_components"]),
                "hub_tables": len(report["hub_tables"]),
                "bridge_tables": len(report["bridge_tables"]),
                "orphan_tables": len(report["orphan_tables"]),
                "topology_counts": dict(topology_counts),
            },
        )

    def enrich_mir(self, mir: MIRDatabase) -> tuple[MIRDatabase, dict[str, Any]]:
        """Return MIR annotated with table topology and a topology report."""
        table_refs = {self._table_ref(table): table for table in mir.get_all_tables()}
        outgoing: dict[str, set[str]] = defaultdict(set)
        incoming: dict[str, set[str]] = defaultdict(set)
        adjacency: dict[str, set[str]] = {ref: set() for ref in table_refs}

        for ref, table in table_refs.items():
            for fk in table.foreign_keys:
                target_schema = fk.referred_schema or table.schema_name
                target = f"{target_schema}.{fk.referred_table}"
                outgoing[ref].add(target)
                incoming[target].add(ref)
                adjacency.setdefault(ref, set()).add(target)
                adjacency.setdefault(target, set()).add(ref)

        components = self._connected_components(adjacency)
        topology_by_ref: dict[str, TableTopology] = {}
        hub_tables: list[str] = []
        bridge_tables: list[str] = []
        orphan_tables: list[str] = []

        for ref, table in table_refs.items():
            topology = self._classify_table(table, incoming[ref], outgoing[ref])
            topology_by_ref[ref] = topology
            if topology == TableTopology.DIMENSION and incoming[ref]:
                hub_tables.append(ref)
            elif topology == TableTopology.BRIDGE:
                bridge_tables.append(ref)
            elif topology == TableTopology.STANDALONE:
                orphan_tables.append(ref)

        enriched_schemas: list[MIRSchema] = []
        for schema in mir.schemas:
            enriched_tables: list[MIRTable] = []
            for table in schema.tables:
                ref = self._table_ref(table)
                enriched_tables.append(table.model_copy(update={"table_topology": topology_by_ref[ref]}))
            enriched_schemas.append(schema.model_copy(update={"tables": enriched_tables}))

        report = {
            "connected_components": components,
            "hub_tables": sorted(hub_tables),
            "bridge_tables": sorted(bridge_tables),
            "orphan_tables": sorted(orphan_tables),
            "table_topology": {
                ref: topology.value
                for ref, topology in sorted(topology_by_ref.items())
            },
            "edges": [
                {"from": source, "to": target}
                for source, targets in sorted(outgoing.items())
                for target in sorted(targets)
            ],
        }
        return mir.model_copy(update={"schemas": enriched_schemas}), report

    def _classify_table(
        self,
        table: MIRTable,
        incoming: set[str],
        outgoing: set[str],
    ) -> TableTopology:
        if not incoming and not outgoing:
            return TableTopology.STANDALONE
        if self._is_bridge_table(table):
            return TableTopology.BRIDGE
        if outgoing:
            return TableTopology.FACT
        if incoming:
            return TableTopology.DIMENSION
        return TableTopology.UNKNOWN

    def _is_bridge_table(self, table: MIRTable) -> bool:
        if len(table.foreign_keys) < 2 or not table.columns:
            return False
        fk_columns = {column for fk in table.foreign_keys for column in fk.columns}
        non_key_columns = [
            column.name
            for column in table.columns
            if column.name not in fk_columns and not column.is_primary_key
        ]
        return not non_key_columns

    def _connected_components(self, adjacency: dict[str, set[str]]) -> list[list[str]]:
        components: list[list[str]] = []
        seen: set[str] = set()
        for start in sorted(adjacency):
            if start in seen:
                continue
            queue: deque[str] = deque([start])
            seen.add(start)
            component: list[str] = []
            while queue:
                node = queue.popleft()
                component.append(node)
                for neighbor in sorted(adjacency[node]):
                    if neighbor not in seen:
                        seen.add(neighbor)
                        queue.append(neighbor)
            components.append(sorted(component))
        return components

    def _table_ref(self, table: MIRTable) -> str:
        return f"{table.schema_name}.{table.name}"
