"""Confidence scoring engine."""

from __future__ import annotations

from typing import Any

from skc.config import ConfidenceConfig
from skc.confidence.signals import SignalRegistry
from skc.ir.common import CandidateKnowledge, Confidence, ConfidenceSignal
from skc.ir.mir import MIRProfileSet


class ConfidenceScorer:
    """Compute confidence for reviewable KIR candidates."""

    def __init__(self, config: ConfidenceConfig) -> None:
        self.config = config

    def score_candidate(
        self,
        candidate: CandidateKnowledge,
        context: dict[str, Any] | None = None,
    ) -> Confidence:
        """Score a candidate using configured signal evaluators."""
        context = context or {}
        signals = SignalRegistry.evaluate_all(candidate, context)
        signals = [self._with_config_weight(signal) for signal in signals]

        signal_score = SignalRegistry.compute_score(signals)
        final_score = max(candidate.confidence.score, signal_score)
        explanation = (
            f"Computed from {len(signals)} signal(s); "
            f"prior={candidate.confidence.score:.2f}, signal_score={signal_score:.2f}."
        )
        return Confidence.from_score(final_score, signals=signals, explanation=explanation)

    def context_for_candidate(
        self,
        candidate: CandidateKnowledge,
        profiles: MIRProfileSet | None = None,
        plugin_matches: list[str] | None = None,
    ) -> dict[str, Any]:
        """Build signal context from candidate metadata and optional profiles."""
        context: dict[str, Any] = {
            "supporting_signals_count": self._supporting_count(candidate),
        }

        if candidate.metadata.get("is_deterministic"):
            context["supporting_signals_count"] += 1

        if "llm_raw_confidence" in candidate.metadata:
            context["llm_raw_confidence"] = candidate.metadata["llm_raw_confidence"]

        if plugin_matches is not None:
            context["plugin_matches"] = plugin_matches

        source_column = candidate.metadata.get("source_column")
        if profiles is not None and source_column:
            profile = self._profile_for_ref(profiles, source_column)
            if profile is not None:
                distinct_ratio = None
                if profile.distinct_count is not None and profile.null_count is not None:
                    denominator = profile.distinct_count + profile.null_count
                    distinct_ratio = profile.distinct_count / denominator if denominator else None
                context["profile_data"] = {
                    "distinct_ratio": distinct_ratio or 0,
                    "null_ratio": profile.null_ratio if profile.null_ratio is not None else 1.0,
                    "pattern_match": bool(profile.pattern_summary),
                }
                context["sample_values"] = profile.sample_values

        return context

    def _with_config_weight(self, signal: ConfidenceSignal) -> ConfidenceSignal:
        configured = self.config.signal_weights.get(signal.signal_name)
        if configured is None:
            return signal
        return signal.model_copy(update={"weight": configured})

    def _supporting_count(self, candidate: CandidateKnowledge) -> int:
        count = len(candidate.provenance)
        if candidate.metadata:
            count += 1
        if candidate.confidence.score >= self.config.mandatory_review_threshold:
            count += 1
        return count

    def _profile_for_ref(self, profiles: MIRProfileSet, source_column: str):
        parts = source_column.split(".")
        if len(parts) != 3:
            return None
        schema, table, column = parts
        return profiles.get_profile(schema, table, column)
