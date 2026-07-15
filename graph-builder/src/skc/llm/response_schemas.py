"""Structured response schemas for narrow LLM tasks."""

from __future__ import annotations

from pydantic import BaseModel, Field


class EntityCandidate(BaseModel):
    """LLM-suggested business entity."""

    name: str
    description: str = ""
    mapped_tables: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class EntityIdentificationResponse(BaseModel):
    """Response for entity identification."""

    entities: list[EntityCandidate] = Field(default_factory=list)


class SynonymCandidate(BaseModel):
    """LLM-suggested synonym."""

    term: str
    language: str = "en"
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class SynonymSuggestionResponse(BaseModel):
    """Response for synonym suggestion."""

    synonyms: list[SynonymCandidate] = Field(default_factory=list)


class TableDescriptionResponse(BaseModel):
    """Response for table description generation."""

    description: str
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class ConceptCandidate(BaseModel):
    """LLM-suggested business concept."""

    name: str
    category: str = ""
    description: str = ""
    mapped_columns: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class ConceptInferenceResponse(BaseModel):
    """Response for business concept inference."""

    concepts: list[ConceptCandidate] = Field(default_factory=list)


class MetricCandidate(BaseModel):
    """LLM-suggested metric."""

    name: str
    formula: str = ""
    description: str = ""
    formula_type: str = ""
    base_columns: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class MetricInferenceResponse(BaseModel):
    """Response for metric inference."""

    metrics: list[MetricCandidate] = Field(default_factory=list)


class RuleCandidate(BaseModel):
    """LLM-suggested rule."""

    name: str
    rule_type: str = ""
    expression: str = ""
    description: str = ""
    scope_tables: list[str] = Field(default_factory=list)
    scope_columns: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class RuleInferenceResponse(BaseModel):
    """Response for rule inference."""

    rules: list[RuleCandidate] = Field(default_factory=list)
