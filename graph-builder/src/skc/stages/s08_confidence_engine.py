"""Stage 8: confidence engine."""

from __future__ import annotations

from datetime import datetime
from typing import TypeVar

from skc.confidence.scorer import ConfidenceScorer
from skc.ir.common import CandidateKnowledge, ConfidenceTier, ReviewStatus, StageStatus
from skc.ir.serde import write_jsonl
from skc.pipeline.base import PipelineStage, StageResult
from skc.pipeline.context import CompilationContext

T = TypeVar("T", bound=CandidateKnowledge)


class ConfidenceEngineStage(PipelineStage):
    """Compute confidence for all reviewable KIR candidates."""

    name = "confidence_engine"
    version = "0.1.0"
    description = "Apply confidence scoring to KIR nodes."
    requires = ["rule_discovery"]
    produces = ["kir_confident"]

    async def validate_inputs(self, ctx: CompilationContext) -> list[str]:
        return [] if ctx.kir.node_count > 0 else ["KIR nodes are required before confidence scoring"]

    async def run(self, ctx: CompilationContext) -> StageResult:
        started_at = datetime.utcnow()
        graph = ctx.get_kir()
        scorer = ConfidenceScorer(ctx.config.confidence)
        plugin_matches = self._plugin_matches(ctx)

        updates = {
            "entities": self._score_list(graph.entities, scorer, ctx, plugin_matches),
            "concepts": self._score_list(graph.concepts, scorer, ctx, plugin_matches),
            "metrics": self._score_list(graph.metrics, scorer, ctx, plugin_matches),
            "rules": self._score_list(graph.rules, scorer, ctx, plugin_matches),
            "relationships": self._score_list(graph.relationships, scorer, ctx, plugin_matches),
            "time_intelligence": self._score_list(graph.time_intelligence, scorer, ctx, plugin_matches),
            "security_tags": self._score_list(graph.security_tags, scorer, ctx, plugin_matches),
        }

        graph = graph.model_copy(update=updates)
        ctx.update_kir(graph)
        path = ctx.output_dir / "kir" / "confident.jsonl"
        write_jsonl(path, [graph])
        ctx.register_artefact("kir_confident", path)

        tier_counts = {"high": 0, "medium": 0, "low": 0}
        for candidate in graph.iter_candidates():
            tier_counts[candidate.confidence.threshold_tier.value] += 1

        return self._create_result(
            StageStatus.COMPLETED,
            started_at,
            artefacts=["kir_confident"],
            stats={
                "candidates_scored": len(graph.iter_candidates()),
                "confidence_tiers": tier_counts,
            },
        )

    def _score_list(
        self,
        candidates: list[T],
        scorer: ConfidenceScorer,
        ctx: CompilationContext,
        plugin_matches: list[str],
    ) -> list[T]:
        return [
            self._score_candidate(candidate, scorer, ctx, plugin_matches)
            for candidate in candidates
        ]

    def _score_candidate(
        self,
        candidate: T,
        scorer: ConfidenceScorer,
        ctx: CompilationContext,
        plugin_matches: list[str],
    ) -> T:
        context = scorer.context_for_candidate(candidate, ctx.profiles, plugin_matches)
        scored = scorer.score_candidate(candidate, context)
        review_status = candidate.review_status
        if (
            ctx.config.review.auto_approve_high
            and scored.threshold_tier == ConfidenceTier.HIGH
            and candidate.review_status == ReviewStatus.PENDING_REVIEW
        ):
            review_status = ReviewStatus.AUTO_APPROVED
        return candidate.model_copy(update={"confidence": scored, "review_status": review_status})

    def _plugin_matches(self, ctx: CompilationContext) -> list[str]:
        terms: list[str] = []
        for entity in ctx.kir.entities:
            terms.append(entity.name)
        for concept in ctx.kir.concepts:
            terms.append(concept.name)
        return terms
