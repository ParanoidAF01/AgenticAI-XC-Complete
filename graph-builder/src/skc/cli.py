"""Typer command line interface for SKC."""

from __future__ import annotations

import asyncio
import csv
import json
import re
from pathlib import Path
from typing import List, Optional

import typer
from rich.console import Console
from rich.table import Table

from skc.config import SKCConfig, load_config
from skc.graph.reader import GraphReader
from skc.ir.kir import KnowledgeGraph
from skc.ir.mir import MIRDatabase
from skc.ir.serde import read_jsonl
from skc.pipeline.checkpoint import CheckpointManager
from skc.pipeline.context import CompilationContext
from skc.pipeline.runner import PipelineRunner
from skc.plugins.loader import PluginLoader
from skc.plugins.registry import PluginRegistry
from skc.stages import (
    ConfidenceEngineStage,
    DataProfilerStage,
    GraphGeneratorStage,
    HumanReviewStage,
    MetricDiscoveryStage,
    RelationshipAnalyzerStage,
    RuleDiscoveryStage,
    SchemaGraphBuilderStage,
    SchemaParserStage,
    SemanticInferencerStage,
    ValidationEngineStage,
)

app = typer.Typer(help="Semantic Knowledge Compiler (SKC) CLI")
console = Console()

inspect_app = typer.Typer(help="Inspect IR artefacts")
app.add_typer(inspect_app, name="inspect")

plugins_app = typer.Typer(help="Manage SKC plugins")
app.add_typer(plugins_app, name="plugins")

graph_app = typer.Typer(help="Graph utilities")
app.add_typer(graph_app, name="graph")


def _with_cli_overrides(
    cfg: SKCConfig,
    source: str | None,
    output: str | None,
    plugins: list[str] | None,
) -> SKCConfig:
    connector = cfg.connector
    pipeline = cfg.pipeline
    plugin_cfg = cfg.plugins

    if source:
        connector_update: dict[str, str] = {}
        source_path = Path(source).expanduser()
        if source_path.exists() or source.endswith(".sql"):
            connector_update["type"] = "ddl_file"
            connector_update["ddl_path"] = str(source_path)
        elif "://" in source:
            connector_update["connection_string"] = source
        else:
            connector_update["type"] = source
        connector = connector.model_copy(update=connector_update)

    if output:
        pipeline = pipeline.model_copy(update={"output_dir": Path(output)})

    if plugins:
        plugin_cfg = plugin_cfg.model_copy(update={"enabled": plugins})

    return cfg.model_copy(
        update={
            "connector": connector,
            "pipeline": pipeline,
            "plugins": plugin_cfg,
        }
    )


def _implemented_stages() -> dict[str, object]:
    return {
        SchemaParserStage.name: SchemaParserStage(),
        SchemaGraphBuilderStage.name: SchemaGraphBuilderStage(),
        DataProfilerStage.name: DataProfilerStage(),
        SemanticInferencerStage.name: SemanticInferencerStage(),
        RelationshipAnalyzerStage.name: RelationshipAnalyzerStage(),
        MetricDiscoveryStage.name: MetricDiscoveryStage(),
        RuleDiscoveryStage.name: RuleDiscoveryStage(),
        ConfidenceEngineStage.name: ConfidenceEngineStage(),
        ValidationEngineStage.name: ValidationEngineStage(),
        HumanReviewStage.name: HumanReviewStage(),
        GraphGeneratorStage.name: GraphGeneratorStage(),
    }


def _selected_stages(cfg: SKCConfig, requested: list[str] | None) -> list[object]:
    implemented = _implemented_stages()
    requested_set = set(requested or [])

    if requested_set:
        unknown = requested_set - set(implemented)
        if unknown:
            raise typer.BadParameter(
                f"Stage(s) not implemented yet: {', '.join(sorted(unknown))}"
            )
        selected_names = set(requested_set)
    else:
        selected_names = {
            name
            for name in implemented
            if cfg.pipeline.stages.get(name, {}).get("enabled", True)
        }

    changed = True
    while changed:
        changed = False
        for name in list(selected_names):
            for required in implemented[name].requires:
                if required not in implemented:
                    continue
                if required not in selected_names:
                    selected_names.add(required)
                    changed = True

    return [stage for name, stage in implemented.items() if name in selected_names]


@app.command()
def compile(
    source: Optional[str] = typer.Option(None, "--source", help="Source connector type or connection string"),
    config: Optional[str] = typer.Option(None, "--config", help="Configuration file path"),
    stages: Optional[List[str]] = typer.Option(None, "--stages", help="Stages to run"),
    resume: Optional[str] = typer.Option(None, "--resume", help="Resume from a previous build artefact"),
    output: Optional[str] = typer.Option(None, "--output", help="Output path"),
    plugin: Optional[List[str]] = typer.Option(None, "--plugin", help="Plugins to enable"),
) -> None:
    """Run the currently implemented compilation pipeline."""
    cfg = _with_cli_overrides(load_config(config), source, output, plugin)
    context = CompilationContext(config=cfg, output_dir=cfg.pipeline.output_dir)

    resume_path = resume or (str(cfg.pipeline.resume_from) if cfg.pipeline.resume_from else None)
    if resume_path:
        checkpoint_path = CheckpointManager.resolve_checkpoint_path(resume_path)
        checkpoint = CheckpointManager.load_checkpoint(checkpoint_path)
        CheckpointManager.restore_context(context, checkpoint)
        completed_count = len(checkpoint.get("completed_stages", []))
        console.print(f"Resuming from checkpoint: {checkpoint_path}")
        console.print(f"Completed stages restored: {completed_count}")

    selected_stages = _selected_stages(cfg, stages)
    results = asyncio.run(PipelineRunner(context, selected_stages).run())
    console.print(f"Build manifest: {context.get_artefact('build_manifest')}")
    console.print(f"Build report: {context.get_artefact('build_report')}")
    console.print(f"Stages executed: {len(results)}")


@app.command()
def review(
    store: str = typer.Option("output/review/candidates.sqlite", "--store", help="Review store path"),
) -> None:
    """Print pending review candidates from a review store."""
    from skc.review.store import CandidateStore

    review_store = CandidateStore(store)
    pending = review_store.get_pending()
    if not pending:
        console.print("No pending review candidates.")
        return
    table = Table(title="Pending Review Candidates")
    table.add_column("ID")
    table.add_column("Type")
    table.add_column("Name")
    table.add_column("Confidence", justify="right")
    for row in pending:
        table.add_row(
            row["id"],
            row["node_type"],
            row["name"],
            f"{row['confidence_score']:.2f} ({row['confidence_tier']})",
        )
    console.print(table)


@app.command("review-api")
def review_api(
    store: str = typer.Option("output/review/candidates.sqlite", "--store", help="Review store path"),
    host: str = typer.Option("127.0.0.1", "--host", help="API bind host"),
    port: int = typer.Option(8000, "--port", help="API bind port"),
) -> None:
    """Serve the optional FastAPI review dashboard."""
    try:
        import uvicorn
    except Exception as exc:
        raise typer.BadParameter("uvicorn is required to serve the review API") from exc

    from skc.review.api import create_app

    uvicorn.run(create_app(store), host=host, port=port)


@inspect_app.command("mir")
def inspect_mir(path: str) -> None:
    """Pretty-print a MIR artefact summary."""
    mir = MIRDatabase.from_jsonl(path)
    table = Table(title="MIR Summary")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("database", mir.name)
    table.add_row("dialect", str(mir.dialect))
    table.add_row("schemas", str(len(mir.schemas)))
    table.add_row("tables", str(mir.table_count))
    console.print(table)


@inspect_app.command("kir")
def inspect_kir(path: str) -> None:
    """Pretty-print a KIR artefact summary."""
    graphs = read_jsonl(Path(path), KnowledgeGraph)
    if not graphs:
        raise typer.BadParameter(f"No KnowledgeGraph records found in {path}")
    kir = graphs[0]
    table = Table(title="KIR Summary")
    table.add_column("Element")
    table.add_column("Count", justify="right")
    table.add_row("entities", str(len(kir.entities)))
    table.add_row("concepts", str(len(kir.concepts)))
    table.add_row("metrics", str(len(kir.metrics)))
    table.add_row("rules", str(len(kir.rules)))
    table.add_row("relationships", str(len(kir.relationships)))
    table.add_row("nodes", str(kir.node_count))
    table.add_row("edges", str(kir.edge_count))
    console.print(table)


@plugins_app.command("list")
def list_plugins(config: Optional[str] = typer.Option(None, "--config", help="Configuration file path")) -> None:
    """List plugins discoverable from configured search paths."""
    cfg = load_config(config)
    registry = PluginRegistry()
    loader = PluginLoader(registry)
    for search_path in cfg.plugins.search_paths:
        loader.load_from_directory(Path(search_path))

    plugins = registry.get_all()
    if not plugins:
        console.print("No plugins found.")
        return

    table = Table(title="Installed Plugins")
    table.add_column("Name")
    table.add_column("Version")
    table.add_column("Industries")
    for loaded_plugin in plugins:
        table.add_row(
            loaded_plugin.name,
            loaded_plugin.version,
            ", ".join(loaded_plugin.industries),
        )
    console.print(table)


@graph_app.command("export")
def export_graph(
    config: Optional[str] = typer.Option(None, "--config", help="Configuration file path"),
    plan: Optional[str] = typer.Option(None, "--plan", help="Dry-run cypher_plan.json to export"),
    output: str = typer.Option("output/graph/export.json", "--output", help="JSON output path or CSV directory"),
    format: str = typer.Option("json", "--format", help="json or csv"),
    limit: Optional[int] = typer.Option(None, "--limit", help="Maximum live nodes/relationships to export"),
) -> None:
    """Export graph contents from Neo4j or a dry-run Cypher plan."""
    if format not in {"json", "csv"}:
        raise typer.BadParameter("--format must be json or csv")

    cfg = load_config(config)
    payload = (
        _export_plan(Path(plan))
        if plan
        else _export_live_graph(cfg, limit)
    )
    output_path = Path(output)
    if format == "json":
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        console.print(f"Graph export written: {output_path}")
    else:
        _write_graph_csv(output_path, payload)
        console.print(f"Graph CSV export written: {output_path}")


@graph_app.command("stats")
def stats_graph(
    config: Optional[str] = typer.Option(None, "--config", help="Configuration file path"),
    plan: Optional[str] = typer.Option(None, "--plan", help="Dry-run cypher_plan.json to summarize"),
) -> None:
    """Print graph statistics from Neo4j or a dry-run Cypher plan."""
    stats = _plan_stats(Path(plan)) if plan else _live_graph_stats(load_config(config))
    table = Table(title="Graph Statistics")
    table.add_column("Category")
    table.add_column("Name")
    table.add_column("Count", justify="right")
    for label, count in sorted(stats.get("nodes", {}).items()):
        table.add_row("node", label, str(count))
    for relationship_type, count in sorted(stats.get("relationships", {}).items()):
        table.add_row("relationship", relationship_type, str(count))
    table.add_section()
    table.add_row("total", "nodes", str(stats.get("total_nodes", 0)))
    table.add_row("total", "relationships", str(stats.get("total_relationships", 0)))
    console.print(table)


def _export_live_graph(cfg: SKCConfig, limit: int | None) -> dict:
    with GraphReader(cfg.neo4j) as reader:
        return reader.export_graph(limit=limit)


def _live_graph_stats(cfg: SKCConfig) -> dict:
    with GraphReader(cfg.neo4j) as reader:
        return reader.graph_stats()


def _load_plan(path: Path) -> dict:
    if not path.exists():
        raise typer.BadParameter(f"Graph plan does not exist: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _export_plan(path: Path) -> dict:
    plan = _load_plan(path)
    nodes: list[dict] = []
    relationships: list[dict] = []
    for operation in plan.get("operations", []):
        statement = operation.get("statement", "")
        rows = operation.get("parameters", {}).get("rows", [])
        node_label = _statement_node_label(statement)
        rel_type = _statement_relationship_type(statement)
        if node_label:
            for row in rows:
                nodes.append({"labels": [node_label], "properties": row})
        elif rel_type:
            for row in rows:
                relationships.append(
                    {
                        "type": rel_type,
                        "from_id": row.get("from_id"),
                        "to_id": row.get("to_id"),
                        "properties": row.get("properties", {}),
                    }
                )
    return {"nodes": nodes, "relationships": relationships, "source_plan": str(path)}


def _plan_stats(path: Path) -> dict:
    export = _export_plan(path)
    node_counts: dict[str, int] = {}
    relationship_counts: dict[str, int] = {}
    for node in export["nodes"]:
        for label in node.get("labels", []):
            node_counts[label] = node_counts.get(label, 0) + 1
    for relationship in export["relationships"]:
        rel_type = relationship.get("type", "UNKNOWN")
        relationship_counts[rel_type] = relationship_counts.get(rel_type, 0) + 1
    return {
        "nodes": node_counts,
        "relationships": relationship_counts,
        "total_nodes": len(export["nodes"]),
        "total_relationships": len(export["relationships"]),
    }


def _statement_node_label(statement: str) -> str | None:
    match = re.search(r"MERGE\s+\(n:([A-Za-z0-9_]+)", statement)
    return match.group(1) if match else None


def _statement_relationship_type(statement: str) -> str | None:
    match = re.search(r"MERGE\s+\(from\)-\[r:([A-Za-z0-9_]+)\]", statement)
    return match.group(1) if match else None


def _write_graph_csv(output_dir: Path, payload: dict) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "nodes.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["labels", "properties"])
        writer.writeheader()
        for node in payload.get("nodes", []):
            writer.writerow(
                {
                    "labels": "|".join(node.get("labels", [])),
                    "properties": json.dumps(node.get("properties", {}), sort_keys=True),
                }
            )
    with (output_dir / "relationships.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["type", "from_id", "to_id", "properties"])
        writer.writeheader()
        for relationship in payload.get("relationships", []):
            writer.writerow(
                {
                    "type": relationship.get("type", ""),
                    "from_id": relationship.get("from_id", ""),
                    "to_id": relationship.get("to_id", ""),
                    "properties": json.dumps(relationship.get("properties", {}), sort_keys=True),
                }
            )


if __name__ == "__main__":
    app()
