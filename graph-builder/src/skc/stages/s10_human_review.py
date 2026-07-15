"""Stage 10: human review."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.prompt import Confirm
from rich.table import Table

from skc.ir.common import ReviewStatus, StageStatus
from skc.ir.serde import write_jsonl
from skc.pipeline.base import PipelineStage, StageResult
from skc.pipeline.context import CompilationContext
from skc.review.reviewer import ReviewWorkflow
from skc.review.store import CandidateStore


class HumanReviewStage(PipelineStage):
    """Persist and optionally review candidates before graph publication."""

    name = "human_review"
    version = "0.1.0"
    description = "Apply batch or CLI review workflow to KIR candidates."
    requires = ["validation_engine"]
    produces = ["review_store", "review_summary", "kir_reviewed"]

    async def validate_inputs(self, ctx: CompilationContext) -> list[str]:
        errors: list[str] = []
        if ctx.kir.node_count == 0:
            errors.append("KIR is required before human review")
        if "validation_report" not in ctx.artefacts:
            errors.append("Validation report is required before human review")
        if ctx.config.review.mode not in {"batch", "cli", "api"}:
            errors.append(f"Unsupported review mode: {ctx.config.review.mode}")
        return errors

    async def run(self, ctx: CompilationContext) -> StageResult:
        started_at = datetime.utcnow()
        store_path = self._store_path(ctx)
        store = CandidateStore(store_path)

        if ctx.config.review.mode == "cli":
            graph, summary = self._run_cli(ctx, store)
        else:
            # API mode persists the queue and exits; serving the API is exposed
            # separately in skc.review.api for deployments that need it.
            workflow = ReviewWorkflow(ctx.config.review, store)
            graph, summary = workflow.run_batch(ctx.get_kir())

        ctx.update_kir(graph)
        reviewed_path = ctx.output_dir / "kir" / "reviewed.jsonl"
        write_jsonl(reviewed_path, [graph])
        ctx.register_artefact("kir_reviewed", reviewed_path)
        ctx.register_artefact("review_store", store_path)
        summary_path = ctx.write_artefact("review_summary", "review/review_summary.json", summary)

        return self._create_result(
            StageStatus.COMPLETED,
            started_at,
            artefacts=["review_store", "review_summary", "kir_reviewed"],
            stats={
                "total_candidates": summary.total_candidates,
                "auto_approved": summary.auto_approved,
                "pending_review": summary.pending_review,
                "mandatory_review": summary.mandatory_review,
                "optional_review": summary.optional_review,
                "store_path": str(store_path),
                "summary_path": str(summary_path),
            },
        )

    def _store_path(self, ctx: CompilationContext) -> Path:
        configured = ctx.config.review.store_path
        if configured:
            path = Path(configured)
            if not path.is_absolute():
                path = ctx.output_dir / path
            return path
        return ctx.output_dir / "review" / "candidates.sqlite"

    def _run_cli(self, ctx: CompilationContext, store: CandidateStore):
        workflow = ReviewWorkflow(ctx.config.review, store)
        graph, summary = workflow.run_batch(ctx.get_kir())
        console = Console()
        pending = store.get_pending()
        if not pending:
            console.print("No pending review candidates.")
            return graph, summary

        table = Table(title="Pending Review Candidates")
        table.add_column("ID")
        table.add_column("Type")
        table.add_column("Name")
        table.add_column("Confidence")
        for row in pending:
            table.add_row(
                row["id"],
                row["node_type"],
                row["name"],
                f"{row['confidence_score']:.2f} ({row['confidence_tier']})",
            )
        console.print(table)

        for row in pending:
            if Confirm.ask(f"Approve {row['node_type']} '{row['name']}'?", default=False):
                store.approve(row["id"], reviewer="cli")
                graph = self._update_candidate_status(graph, row["id"], ReviewStatus.APPROVED)

        summary = workflow._summary(graph)
        return graph, summary

    def _update_candidate_status(self, graph, candidate_id: str, status: ReviewStatus):
        updates = {}
        for field in [
            "entities",
            "concepts",
            "metrics",
            "rules",
            "relationships",
            "time_intelligence",
            "security_tags",
        ]:
            values = getattr(graph, field)
            updates[field] = [
                item.model_copy(update={"review_status": status}) if item.id == candidate_id else item
                for item in values
            ]
        return graph.model_copy(update=updates)
