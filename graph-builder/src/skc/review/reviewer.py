"""Human review workflow orchestration."""

from __future__ import annotations

from typing import TypeVar

from skc.config import ReviewConfig
from skc.ir.common import CandidateKnowledge, ConfidenceTier, ReviewStatus
from skc.ir.kir import KnowledgeGraph
from skc.review.models import ReviewSummary
from skc.review.store import CandidateStore

T = TypeVar("T", bound=CandidateKnowledge)


class ReviewWorkflow:
    """Apply review policy and persist candidates."""

    def __init__(self, config: ReviewConfig, store: CandidateStore) -> None:
        self.config = config
        self.store = store

    def run_batch(self, graph: KnowledgeGraph) -> tuple[KnowledgeGraph, ReviewSummary]:
        """Run non-interactive review policy over a KIR graph."""
        updates = {
            "entities": self._review_list(graph.entities),
            "concepts": self._review_list(graph.concepts),
            "metrics": self._review_list(graph.metrics),
            "rules": self._review_list(graph.rules),
            "relationships": self._review_list(graph.relationships),
            "time_intelligence": self._review_list(graph.time_intelligence),
            "security_tags": self._review_list(graph.security_tags),
        }
        reviewed = graph.model_copy(update=updates)
        summary = self._summary(reviewed)
        return reviewed, summary

    def _review_list(self, candidates: list[T]) -> list[T]:
        return [self._review_candidate(candidate) for candidate in candidates]

    def _review_candidate(self, candidate: T) -> T:
        status = candidate.review_status
        tier = candidate.confidence.threshold_tier

        if status in {ReviewStatus.APPROVED, ReviewStatus.REJECTED, ReviewStatus.MODIFIED}:
            reviewed = candidate
        elif tier == ConfidenceTier.HIGH and self.config.auto_approve_high:
            reviewed = candidate.model_copy(update={"review_status": ReviewStatus.AUTO_APPROVED})
        else:
            reviewed = candidate.model_copy(update={"review_status": ReviewStatus.PENDING_REVIEW})

        self.store.upsert_candidate(reviewed)
        return reviewed

    def _summary(self, graph: KnowledgeGraph) -> ReviewSummary:
        candidates = graph.iter_candidates()
        status_counts = {status.value: 0 for status in ReviewStatus}
        mandatory = 0
        optional = 0

        for candidate in candidates:
            status_counts[candidate.review_status.value] = status_counts.get(candidate.review_status.value, 0) + 1
            if candidate.confidence.threshold_tier == ConfidenceTier.LOW:
                mandatory += 1
            elif candidate.confidence.threshold_tier == ConfidenceTier.MEDIUM:
                optional += 1

        return ReviewSummary(
            total_candidates=len(candidates),
            auto_approved=status_counts.get(ReviewStatus.AUTO_APPROVED.value, 0),
            pending_review=status_counts.get(ReviewStatus.PENDING_REVIEW.value, 0),
            approved=status_counts.get(ReviewStatus.APPROVED.value, 0),
            rejected=status_counts.get(ReviewStatus.REJECTED.value, 0),
            modified=status_counts.get(ReviewStatus.MODIFIED.value, 0),
            mandatory_review=mandatory,
            optional_review=optional,
            store_path=str(self.store.path),
        )
