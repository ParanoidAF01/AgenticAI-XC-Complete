"""Confidence signal framework and evaluator implementations.

Defines the SignalEvaluator abstract base class and concrete signal
implementations used by the Confidence Engine to score candidate
knowledge inferences.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from skc.ir.common import CandidateKnowledge, ConfidenceSignal, NormalizedType


# ======================================================================
# Abstract base
# ======================================================================


class SignalEvaluator(ABC):
    """Base class for all confidence-signal evaluators.

    A ``SignalEvaluator`` inspects a :class:`CandidateKnowledge` record
    and an accompanying context dictionary to produce a
    :class:`ConfidenceSignal` (or ``None`` when the evaluator is not
    applicable to the given candidate).

    Sub-classes must set the class-level attributes :pyattr:`name`,
    :pyattr:`weight`, and :pyattr:`description`, and implement the
    :meth:`evaluate` method.

    Attributes:
        name: A unique, machine-readable identifier for this signal
            (e.g. ``"naming_convention_match"``).
        weight: The relative importance of this signal when computing a
            weighted aggregate score.  Values are typically in the range
            ``[0.0, 1.0]``.
        description: A short human-readable explanation of what this
            signal measures.
    """

    name: str
    weight: float
    description: str

    @abstractmethod
    def evaluate(
        self,
        candidate: CandidateKnowledge,
        context: dict[str, Any],
    ) -> ConfidenceSignal | None:
        """Evaluate the candidate and return a confidence signal.

        Args:
            candidate: The candidate knowledge inference to evaluate.
            context: Supplementary data (e.g. profile stats, glossary
                terms, LLM outputs) that individual evaluators may
                consult.

        Returns:
            A :class:`ConfidenceSignal` if this evaluator is applicable
            to the candidate, or ``None`` if it is not.
        """

    def _make_signal(self, value: float, evidence: str = "") -> ConfidenceSignal:
        """Create a :class:`ConfidenceSignal` pre-filled with this evaluator's metadata.

        This is a convenience helper for sub-classes so they do not need
        to repeat the ``signal_name`` and ``weight`` fields.

        Args:
            value: The signal value in the range ``[0.0, 1.0]``.
            evidence: Optional free-text evidence string that explains
                how the value was derived.

        Returns:
            A new ``ConfidenceSignal`` instance.
        """
        return ConfidenceSignal(
            signal_name=self.name,
            value=value,
            weight=self.weight,
            evidence=evidence,
        )


# ======================================================================
# Concrete signal evaluators
# ======================================================================


class NamingConventionSignal(SignalEvaluator):
    """Checks whether entity or column names follow known naming patterns.

    The evaluator maintains a curated set of common column-name suffixes
    (``_id``, ``_date``, ``_amount``, etc.) and scores ``1.0`` when the
    candidate name ends with one of them, ``0.0`` otherwise.
    """

    name: str = "naming_convention_match"
    weight: float = 0.15
    description: str = "Checks if entity/column names match known naming patterns"

    _KNOWN_SUFFIXES: tuple[str, ...] = (
        "_id",
        "_date",
        "_amount",
        "_count",
        "_status",
        "_type",
        "_code",
        "_flag",
        "_name",
        "_description",
        "_at",
        "_on",
        "_by",
        "_num",
        "_pct",
        "_rate",
    )

    def evaluate(
        self,
        candidate: CandidateKnowledge,
        context: dict[str, Any],
    ) -> ConfidenceSignal | None:
        """Evaluate the candidate name against known naming-convention suffixes.

        Args:
            candidate: The candidate knowledge inference to evaluate.
            context: Supplementary context (unused by this evaluator).

        Returns:
            A :class:`ConfidenceSignal` with ``value=1.0`` if the name
            matches a known suffix, or ``value=0.0`` if not.
        """
        lower_name = candidate.name.lower()
        for suffix in self._KNOWN_SUFFIXES:
            if lower_name.endswith(suffix):
                return self._make_signal(
                    value=1.0,
                    evidence=f"Name matches pattern: {suffix}",
                )
        return self._make_signal(
            value=0.0,
            evidence="No naming pattern match",
        )


class ForeignKeyBackedSignal(SignalEvaluator):
    """Checks whether a relationship candidate is backed by a foreign key.

    Only applicable to candidates whose ``candidate_type`` is
    ``"relationship"``.  Returns ``None`` for all other candidate types.
    """

    name: str = "fk_backed"
    weight: float = 0.20
    description: str = "Checks if a relationship is backed by a foreign key constraint"

    def evaluate(
        self,
        candidate: CandidateKnowledge,
        context: dict[str, Any],
    ) -> ConfidenceSignal | None:
        """Evaluate whether the candidate relationship has FK backing.

        Args:
            candidate: The candidate knowledge inference to evaluate.
            context: Supplementary context (unused by this evaluator).

        Returns:
            A :class:`ConfidenceSignal` if the candidate is a
            relationship, or ``None`` otherwise.
        """
        if candidate.candidate_type != "relationship":
            return None

        if candidate.metadata.get("is_deterministic", False):
            return self._make_signal(
                value=1.0,
                evidence="Relationship backed by foreign key",
            )
        return self._make_signal(
            value=0.0,
            evidence="No foreign key backing",
        )


class DataProfileSupportSignal(SignalEvaluator):
    """Checks whether data-profiling statistics corroborate the inference.

    Examines ``context["profile_data"]`` for distinct ratio, null ratio,
    and pattern-match indicators and accumulates a score.  Returns
    ``None`` when no profile data is available.
    """

    name: str = "data_profile_support"
    weight: float = 0.15
    description: str = "Checks if data profiling corroborates the inference"

    def evaluate(
        self,
        candidate: CandidateKnowledge,
        context: dict[str, Any],
    ) -> ConfidenceSignal | None:
        """Evaluate the candidate using available data-profile statistics.

        Args:
            candidate: The candidate knowledge inference to evaluate.
            context: Must contain a ``"profile_data"`` mapping with
                optional keys ``"distinct_ratio"``, ``"null_ratio"``,
                and ``"pattern_match"``.

        Returns:
            A :class:`ConfidenceSignal` derived from profile metrics,
            or ``None`` if ``"profile_data"`` is absent from *context*.
        """
        if "profile_data" not in context:
            return None

        profile = context["profile_data"]
        score = 0.5
        evidence_parts: list[str] = []

        if profile.get("distinct_ratio", 0) > 0.8:
            score += 0.2
            evidence_parts.append("high distinct ratio")

        if profile.get("null_ratio", 1.0) < 0.05:
            score += 0.2
            evidence_parts.append("low null ratio")

        if profile.get("pattern_match", False):
            score += 0.1
            evidence_parts.append("pattern match")

        score = min(score, 1.0)
        evidence = (
            f"Profile support: {', '.join(evidence_parts)}"
            if evidence_parts
            else "Profile support: baseline only"
        )
        return self._make_signal(value=score, evidence=evidence)


class PluginMatchSignal(SignalEvaluator):
    """Checks whether a domain plugin provides corroborating evidence.

    Looks for the candidate's name in
    ``context["plugin_matches"]``.  Returns ``None`` when no plugin
    matches list is available.
    """

    name: str = "plugin_match"
    weight: float = 0.15
    description: str = "Checks if a domain plugin provides corroborating evidence"

    def evaluate(
        self,
        candidate: CandidateKnowledge,
        context: dict[str, Any],
    ) -> ConfidenceSignal | None:
        """Evaluate whether a domain plugin recognised this candidate.

        Args:
            candidate: The candidate knowledge inference to evaluate.
            context: Must contain a ``"plugin_matches"`` list of matched
                term strings.

        Returns:
            A :class:`ConfidenceSignal`, or ``None`` if
            ``"plugin_matches"`` is absent from *context*.
        """
        if "plugin_matches" not in context:
            return None

        lower_matches = [m.lower() for m in context["plugin_matches"]]
        if candidate.name.lower() in lower_matches:
            return self._make_signal(
                value=1.0,
                evidence="Matched by domain plugin",
            )
        return self._make_signal(
            value=0.0,
            evidence="No plugin match found",
        )


class LLMConfidenceSignal(SignalEvaluator):
    """Extracts and calibrates LLM self-reported confidence.

    Applies a 0.8× calibration factor to the raw LLM confidence value
    and clamps the result to ``[0.0, 1.0]``.  Returns ``None`` when no
    raw LLM confidence is present in the context.
    """

    name: str = "llm_confidence"
    weight: float = 0.10
    description: str = "Extracts and calibrates LLM self-reported confidence"

    def evaluate(
        self,
        candidate: CandidateKnowledge,
        context: dict[str, Any],
    ) -> ConfidenceSignal | None:
        """Evaluate the candidate using calibrated LLM confidence.

        Args:
            candidate: The candidate knowledge inference to evaluate.
            context: Must contain ``"llm_raw_confidence"`` as a float
                in ``[0.0, 1.0]``.

        Returns:
            A :class:`ConfidenceSignal` with the calibrated value, or
            ``None`` if ``"llm_raw_confidence"`` is absent.
        """
        if "llm_raw_confidence" not in context:
            return None

        raw = context["llm_raw_confidence"]
        calibrated = max(0.0, min(1.0, raw * 0.8))
        evidence = f"LLM raw={raw:.2f}, calibrated={calibrated:.2f}"
        return self._make_signal(value=calibrated, evidence=evidence)


class GlossaryMatchSignal(SignalEvaluator):
    """Checks whether the candidate term appears in a business glossary.

    Performs a case-insensitive lookup of the candidate name against
    ``context["glossary_terms"]``.  Returns ``None`` when no glossary
    is provided.
    """

    name: str = "glossary_match"
    weight: float = 0.10
    description: str = "Checks if term appears in business glossary"

    def evaluate(
        self,
        candidate: CandidateKnowledge,
        context: dict[str, Any],
    ) -> ConfidenceSignal | None:
        """Evaluate whether the candidate name is in the business glossary.

        Args:
            candidate: The candidate knowledge inference to evaluate.
            context: Must contain ``"glossary_terms"`` as an iterable
                of term strings.

        Returns:
            A :class:`ConfidenceSignal`, or ``None`` if
            ``"glossary_terms"`` is absent from *context*.
        """
        if "glossary_terms" not in context:
            return None

        lower_terms = {t.lower() for t in context["glossary_terms"]}
        if candidate.name.lower() in lower_terms:
            return self._make_signal(
                value=1.0,
                evidence="Term found in business glossary",
            )
        return self._make_signal(
            value=0.0,
            evidence="Term not in glossary",
        )


class CrossReferenceSignal(SignalEvaluator):
    """Counts independent corroborating signals from external sources.

    Normalises the supporting-signal count by dividing by 3 (i.e. three
    or more independent signals yield a perfect score).  Returns
    ``None`` when no count is available.
    """

    name: str = "cross_reference_count"
    weight: float = 0.10
    description: str = "Counts independent corroborating signals"

    def evaluate(
        self,
        candidate: CandidateKnowledge,
        context: dict[str, Any],
    ) -> ConfidenceSignal | None:
        """Evaluate the candidate based on the number of supporting signals.

        Args:
            candidate: The candidate knowledge inference to evaluate.
            context: Must contain ``"supporting_signals_count"`` as an
                integer.

        Returns:
            A :class:`ConfidenceSignal` with a normalised value, or
            ``None`` if the count is absent from *context*.
        """
        if "supporting_signals_count" not in context:
            return None

        count = context["supporting_signals_count"]
        normalised = min(count / 3, 1.0)
        evidence = f"{count} supporting signals (normalised: {normalised:.2f})"
        return self._make_signal(value=normalised, evidence=evidence)


class SampleDataSupportSignal(SignalEvaluator):
    """Checks whether sample values are consistent with the inference.

    When an ``expected_type`` is provided in the candidate's metadata,
    the evaluator verifies that the sample values conform to that type.
    Returns ``None`` when no sample values are available or the sample
    list is empty.
    """

    name: str = "sample_data_support"
    weight: float = 0.05
    description: str = "Checks if sample values are consistent with the inference"

    def evaluate(
        self,
        candidate: CandidateKnowledge,
        context: dict[str, Any],
    ) -> ConfidenceSignal | None:
        """Evaluate sample data consistency with the candidate's expected type.

        Args:
            candidate: The candidate knowledge inference to evaluate.
            context: Must contain ``"sample_values"`` as a list of
                string sample values.

        Returns:
            A :class:`ConfidenceSignal`, or ``None`` if
            ``"sample_values"`` is absent or empty.
        """
        if "sample_values" not in context:
            return None

        samples: list[str] = context["sample_values"]
        if not samples:
            return None

        expected_type: str = candidate.metadata.get("expected_type", "")
        if expected_type:
            score = self._check_type_consistency(samples, expected_type)
        else:
            score = 0.6

        return self._make_signal(
            value=score,
            evidence=f"Sample consistency score: {score:.2f}",
        )

    def _check_type_consistency(
        self,
        samples: list[str],
        expected: str,
    ) -> float:
        """Check whether *samples* are consistent with the *expected* type.

        Examines the proportion of sample values that look like they
        belong to the expected data type and returns a score in
        ``{0.3, 0.7, 1.0}`` (or ``0.6`` for unrecognised types).

        Args:
            samples: Non-empty list of string sample values.
            expected: The expected data type (e.g. ``"date"``,
                ``"integer"``, ``"boolean"``).

        Returns:
            A float score indicating type consistency.
        """
        total = len(samples)
        expected_lower = expected.lower()

        if expected_lower in ("date", "datetime", "timestamp"):
            matches = sum(
                1
                for s in samples
                if ("-" in s or "/" in s) and any(c.isdigit() for c in s)
            )
        elif expected_lower == "integer":
            matches = sum(1 for s in samples if s.strip().lstrip("-").isdigit())
        elif expected_lower in ("float", "decimal"):
            matches = sum(1 for s in samples if "." in s)
        elif expected_lower == "boolean":
            valid_booleans = {"true", "false", "0", "1", "yes", "no", "t", "f", "y", "n"}
            matches = sum(1 for s in samples if s.strip().lower() in valid_booleans)
        else:
            return 0.6

        ratio = matches / total
        if ratio > 0.8:
            return 1.0
        elif ratio > 0.5:
            return 0.7
        else:
            return 0.3


# ======================================================================
# Signal registry
# ======================================================================


class SignalRegistry:
    """Central registry of all available :class:`SignalEvaluator` instances.

    Provides class-level methods to retrieve individual evaluators, run
    all evaluators against a candidate, and compute a weighted aggregate
    confidence score from the resulting signals.
    """

    _signals: list[SignalEvaluator] = [
        NamingConventionSignal(),
        ForeignKeyBackedSignal(),
        DataProfileSupportSignal(),
        PluginMatchSignal(),
        LLMConfidenceSignal(),
        GlossaryMatchSignal(),
        CrossReferenceSignal(),
        SampleDataSupportSignal(),
    ]

    @classmethod
    def get_all(cls) -> list[SignalEvaluator]:
        """Return a copy of all registered signal evaluators.

        Returns:
            A new list containing every :class:`SignalEvaluator`
            instance in the registry.
        """
        return list(cls._signals)

    @classmethod
    def get_by_name(cls, name: str) -> SignalEvaluator | None:
        """Look up a signal evaluator by its unique name.

        Args:
            name: The ``name`` attribute of the desired evaluator.

        Returns:
            The matching :class:`SignalEvaluator`, or ``None`` if no
            evaluator with that name is registered.
        """
        for signal in cls._signals:
            if signal.name == name:
                return signal
        return None

    @classmethod
    def evaluate_all(
        cls,
        candidate: CandidateKnowledge,
        context: dict[str, Any],
    ) -> list[ConfidenceSignal]:
        """Run every registered evaluator and collect non-``None`` results.

        Args:
            candidate: The candidate knowledge inference to evaluate.
            context: Supplementary context forwarded to each evaluator.

        Returns:
            A list of :class:`ConfidenceSignal` instances produced by
            evaluators that were applicable to the candidate.
        """
        results: list[ConfidenceSignal] = []
        for evaluator in cls._signals:
            signal = evaluator.evaluate(candidate, context)
            if signal is not None:
                results.append(signal)
        return results

    @staticmethod
    def compute_score(signals: list[ConfidenceSignal]) -> float:
        """Compute a weighted-average confidence score from a list of signals.

        The score is calculated as::

            sum(signal.value * signal.weight) / sum(signal.weight)

        and clamped to the range ``[0.0, 1.0]``.

        Args:
            signals: The confidence signals to aggregate.

        Returns:
            A float in ``[0.0, 1.0]``.  Returns ``0.0`` if the signal
            list is empty.
        """
        if not signals:
            return 0.0

        total_weight = sum(s.weight for s in signals)
        if total_weight == 0.0:
            return 0.0

        raw = sum(s.value * s.weight for s in signals) / total_weight
        return max(0.0, min(1.0, raw))
