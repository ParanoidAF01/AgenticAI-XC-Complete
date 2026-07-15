"""Abstract plugin interface for domain-specific knowledge providers.

The :class:`SKCPlugin` ABC defines the contract that industry plugins
must implement to contribute domain knowledge — ontology seeds, metric
definitions, business rules, synonym mappings, and validation
functions — to the SKC compilation pipeline.

Plugins are the **only** mechanism through which domain-specific logic
enters the compiler; the core pipeline remains industry-agnostic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Callable

from skc.ir.common import (
    Confidence,
    ConfidenceSignal,
    ConfidenceTier,
    Provenance,
    ReviewStatus,
    SourceType,
)
from skc.ir.kir import BusinessEntity, BusinessRule, Metric


class SKCPlugin(ABC):
    """Abstract base class for SKC domain plugins.

    A plugin encapsulates all domain-specific knowledge for one or
    more industries.  The compilation pipeline queries registered
    plugins to seed the Knowledge IR with canonical business entities,
    metrics, rules, and synonyms before the semantic-inference stages
    run.

    Attributes:
        name: Unique plugin identifier (e.g. ``"insurance"``).
        version: Semantic version of the plugin (e.g. ``"1.0.0"``).
        description: Human-readable summary of the domain knowledge
            this plugin provides.
        industries: List of industry tags that this plugin applies to
            (e.g. ``["insurance", "reinsurance"]``).
    """

    name: str = ""
    version: str = "0.1.0"
    description: str = ""
    industries: list[str] = []

    # ------------------------------------------------------------------
    # Abstract methods — must be implemented by every plugin
    # ------------------------------------------------------------------

    @abstractmethod
    def get_ontology(self) -> list[BusinessEntity]:
        """Return seed business entities for this domain.

        These entities form the initial ontology skeleton that the
        compiler enriches through metadata analysis and semantic
        inference.

        Returns:
            A list of :class:`BusinessEntity` instances representing
            canonical domain entities (e.g. ``Policy``, ``Claim``,
            ``Premium`` for an insurance plugin).
        """

    @abstractmethod
    def get_metrics(self) -> list[Metric]:
        """Return domain-standard metric definitions.

        Returns:
            A list of :class:`Metric` instances representing canonical
            KPIs and measures for this industry (e.g. ``Loss Ratio``,
            ``Combined Ratio``).
        """

    @abstractmethod
    def get_rules(self) -> list[BusinessRule]:
        """Return domain-standard business rules.

        Returns:
            A list of :class:`BusinessRule` instances representing
            well-known constraints, validations, or derivation rules
            for this domain.
        """

    @abstractmethod
    def get_synonyms(self) -> dict[str, list[str]]:
        """Return synonym mappings for domain terminology.

        Returns:
            A dictionary mapping canonical terms to their known
            synonyms.  For example::

                {"policy": ["contract", "coverage", "policy_record"]}
        """

    @abstractmethod
    def get_validators(self) -> list[Callable]:
        """Return domain-specific validation functions.

        Each validator is a callable that accepts a
        :class:`KnowledgeGraph` and returns a list of validation
        error/warning strings.

        Returns:
            A list of validation callables.
        """

    # ------------------------------------------------------------------
    # Concrete helpers
    # ------------------------------------------------------------------

    def _make_provenance(self) -> Provenance:
        """Create a :class:`Provenance` record attributed to this plugin.

        Returns:
            A provenance instance with ``source_type=PLUGIN``,
            ``source_id`` set to the plugin's :attr:`name`, and the
            current UTC timestamp.
        """
        return Provenance(
            source_type=SourceType.PLUGIN,
            source_id=self.name,
            source_detail=f"Plugin v{self.version}",
            timestamp=datetime.utcnow(),
            build_version=self.version,
        )

    def _make_confidence(self, score: float = 0.75) -> Confidence:
        """Create a :class:`Confidence` with a ``plugin_provided`` signal.

        Plugin-sourced knowledge receives a default confidence derived
        from a single ``plugin_provided`` signal.  Downstream stages
        may augment the confidence with additional signals.

        Parameters:
            score: Base confidence score in the range ``[0.0, 1.0]``.
                Defaults to ``0.75`` (medium-high confidence) because
                plugin knowledge is curated but may not match the
                target database exactly.

        Returns:
            A :class:`Confidence` instance with the computed tier and
            a single ``plugin_provided`` signal.
        """
        signal = ConfidenceSignal(
            signal_name="plugin_provided",
            value=score,
            weight=1.0,
            evidence=f"Provided by plugin '{self.name}' v{self.version}",
        )
        return Confidence.from_score(score=score, signals=[signal])
