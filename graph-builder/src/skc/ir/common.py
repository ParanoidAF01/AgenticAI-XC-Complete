"""Common enums, base types, and shared models for SKC IR objects.

The models in this module are deliberately small and stable. They are shared by
the MIR, KIR, pipeline framework, confidence scoring, and plugin system.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class StageStatus(str, Enum):
    """Status of a pipeline stage execution.

    Tracks the lifecycle of each stage as it moves through the pipeline,
    from initial scheduling through completion or failure.
    """

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    SUCCESS = "completed"
    WARNING = "warning"
    FAILED = "failed"
    ERROR = "failed"
    SKIPPED = "skipped"


class SourceType(str, Enum):
    """Classification of where a piece of knowledge originated.

    Used by provenance records to indicate the extraction source so that
    downstream consumers can reason about data lineage and trustworthiness.
    """

    DETERMINISTIC = "deterministic"
    LLM_INFERRED = "llm_inferred"
    PLUGIN = "plugin"
    HUMAN = "human"
    GLOSSARY = "glossary"
    DDL = "ddl"
    QUERY_LOG = "query_log"
    LLM = "llm_inferred"
    USER = "human"
    DATA_PROFILE = "data_profile"
    FOREIGN_KEY = "foreign_key"


class ConfidenceTier(str, Enum):
    """Discrete confidence tier derived from a numeric confidence score.

    Thresholds:
        - HIGH:   score >= 0.85
        - MEDIUM: score >= 0.60
        - LOW:    score <  0.60
    """

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ReviewStatus(str, Enum):
    """Human-review lifecycle status for a candidate knowledge element.

    Elements begin as PENDING_REVIEW (or AUTO_APPROVED when confidence is
    sufficiently high) and transition through the review workflow.
    """

    AUTO_APPROVED = "auto_approved"
    PENDING_REVIEW = "pending_review"
    PENDING = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    MODIFIED = "modified"
    NEEDS_REVISION = "needs_revision"


class NormalizedType(str, Enum):
    """Dialect-agnostic column data type.

    Raw database-specific types are mapped to one of these normalized
    categories so that downstream logic can operate without dialect awareness.
    """

    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    DECIMAL = "decimal"
    BOOLEAN = "boolean"
    DATE = "date"
    DATETIME = "datetime"
    TIMESTAMP = "timestamp"
    TIME = "time"
    BINARY = "binary"
    JSON = "json"
    ARRAY = "array"
    UUID = "uuid"
    UNKNOWN = "unknown"
    OTHER = "unknown"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class ConfidenceSignal(BaseModel):
    """A single contributing signal to an overall confidence score.

    Each signal carries a name, a raw value in [0.0, 1.0], a weight that
    controls its contribution to the aggregate score, and optional textual
    evidence that justifies the value.
    """

    model_config = ConfigDict(frozen=True)

    signal_name: str
    weight: float = Field(..., description="Relative weight of this signal in the aggregate score.")
    value: float = Field(..., ge=0.0, le=1.0, description="Signal value between 0.0 and 1.0.")
    reasoning: str | None = None
    evidence: str = ""


class Confidence(BaseModel):
    """Aggregate confidence assessment for a knowledge element.

    Combines a numeric score, a discrete tier, contributing signals, and a
    human-readable explanation.  Use the ``from_score`` class method to
    construct instances with the tier computed automatically.
    """

    model_config = ConfigDict(frozen=True)

    score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Aggregate confidence score between 0.0 and 1.0.",
    )
    threshold_tier: ConfidenceTier = Field(..., description="Discrete tier derived from the score.")
    signals: list[ConfidenceSignal] = Field(default_factory=list)
    explanation: str = ""

    @property
    def tier(self) -> ConfidenceTier:
        """Backward-compatible alias used by early scaffolding code."""
        return self.threshold_tier

    @classmethod
    def from_score(
        cls,
        score: float,
        signals: list[ConfidenceSignal] | None = None,
        explanation: str = "",
    ) -> Confidence:
        """Create a ``Confidence`` instance with the tier computed from the score.

        Args:
            score: Numeric confidence value in [0.0, 1.0].
            signals: Optional list of contributing confidence signals.
            explanation: Optional human-readable justification.

        Returns:
            A new ``Confidence`` instance with the appropriate tier set.
        """
        if score >= 0.85:
            tier = ConfidenceTier.HIGH
        elif score >= 0.60:
            tier = ConfidenceTier.MEDIUM
        else:
            tier = ConfidenceTier.LOW

        return cls(
            score=score,
            threshold_tier=tier,
            signals=signals or [],
            explanation=explanation,
        )


class Provenance(BaseModel):
    """Records the origin of a knowledge element for data-lineage tracking.

    Every piece of extracted or inferred knowledge carries one or more
    provenance records that describe *where* and *when* it was produced.
    """

    model_config = ConfigDict(frozen=True)

    source_type: SourceType = Field(..., description="Category of the originating source.")
    source_id: str = Field(..., description="Unique identifier of the source (e.g. file path, query hash).")
    source_detail: str | None = None
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="When the extraction occurred.")
    build_version: str = ""


class CandidateKnowledge(BaseModel):
    """Base metadata carried by reviewable knowledge elements."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=lambda: str(uuid4()))
    candidate_type: str = Field(default="", description="Kind of knowledge element.")
    name: str = Field(default="", description="Human-readable name for this candidate.")
    confidence: Confidence = Field(default_factory=lambda: Confidence.from_score(0.0))
    provenance: list[Provenance] = Field(default_factory=list)
    review_status: ReviewStatus = ReviewStatus.PENDING_REVIEW
    version: int = 1
    supersedes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


ReviewState = ReviewStatus
