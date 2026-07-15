"""Governance, validation, and review models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ValidationIssue(BaseModel):
    """A validation warning or error."""

    model_config = ConfigDict(frozen=True)

    severity: str
    code: str
    message: str
    node_id: str | None = None
    node_type: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ValidationReport(BaseModel):
    """Validation results for a complete KIR."""

    model_config = ConfigDict(frozen=True)

    build_id: str
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    issues: list[ValidationIssue] = Field(default_factory=list)
    stats: dict[str, Any] = Field(default_factory=dict)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.severity == "error"]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.severity == "warning"]

    @property
    def has_errors(self) -> bool:
        return bool(self.errors)


class ReviewSummary(BaseModel):
    """Summary produced by the review workflow."""

    model_config = ConfigDict(frozen=True)

    total_candidates: int
    auto_approved: int = 0
    pending_review: int = 0
    approved: int = 0
    rejected: int = 0
    modified: int = 0
    mandatory_review: int = 0
    optional_review: int = 0
    store_path: str | None = None
