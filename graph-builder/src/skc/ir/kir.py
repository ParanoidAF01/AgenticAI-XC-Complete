"""Knowledge Intermediate Representation (KIR) models.

KIR captures reviewable semantic knowledge: entities, concepts, metrics,
rules, relationships, synonyms, time intelligence, security tags, and learning
metadata. Every primary KIR node inherits candidate metadata from
``CandidateKnowledge`` so confidence, provenance, review state, and versioning
are consistent across the graph.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from skc.ir.common import CandidateKnowledge, Confidence, Provenance, ReviewStatus


class Synonym(BaseModel):
    """Alternative term for a canonical business name."""

    model_config = ConfigDict(frozen=True)

    term: str
    canonical_name: str = ""
    language: str = "en"
    confidence: Confidence = Field(default_factory=lambda: Confidence.from_score(0.0))
    provenance: list[Provenance] = Field(default_factory=list)


class GrainDefinition(BaseModel):
    """Columns that uniquely identify one instance of an entity."""

    model_config = ConfigDict(frozen=True)

    grain_columns: list[str] = Field(default_factory=list)
    description: str = ""
    provenance: list[Provenance] = Field(default_factory=list)


class JoinPath(BaseModel):
    """Concrete table/column path used to join two entities."""

    model_config = ConfigDict(frozen=True)

    from_table: str
    from_columns: list[str] = Field(default_factory=list)
    to_table: str
    to_columns: list[str] = Field(default_factory=list)
    join_type: str = "INNER"
    is_deterministic: bool = False
    provenance: list[Provenance] = Field(default_factory=list)
    confidence: Confidence = Field(default_factory=lambda: Confidence.from_score(0.0))


class MetricFilter(BaseModel):
    """Filter expression attached to a metric definition."""

    model_config = ConfigDict(frozen=True)

    column: str
    operator: str
    value: str


class BusinessEntity(CandidateKnowledge):
    """A business-level entity derived from one or more tables."""

    candidate_type: str = "business_entity"
    name: str
    description: str = ""
    mapped_tables: list[str] = Field(default_factory=list)
    entity_type: str = "table"
    synonyms: list[Synonym] = Field(default_factory=list)
    grain: GrainDefinition | None = None
    source_schema: str = ""
    source_table: str = ""
    build_version: str = ""
    grain_columns: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class BusinessConcept(CandidateKnowledge):
    """A business concept tied to source columns."""

    candidate_type: str = "business_concept"
    name: str
    description: str = ""
    category: str = ""
    mapped_columns: list[str] = Field(default_factory=list)
    synonyms: list[Synonym] = Field(default_factory=list)
    source_column: str = ""
    source_table: str = ""
    build_version: str = ""


class Metric(CandidateKnowledge):
    """A quantitative metric derived from source columns."""

    candidate_type: str = "metric"
    name: str
    description: str = ""
    formula: str = ""
    formula_type: str = ""
    base_columns: list[str] = Field(default_factory=list)
    source_columns: list[str] = Field(default_factory=list)
    filters: list[MetricFilter] = Field(default_factory=list)
    grain: GrainDefinition | None = None
    unit: str | None = None
    build_version: str = ""


class BusinessRule(CandidateKnowledge):
    """A business rule or constraint."""

    candidate_type: str = "business_rule"
    name: str
    description: str = ""
    rule_type: str = ""
    expression: str = ""
    scope_tables: list[str] = Field(default_factory=list)
    scope_columns: list[str] = Field(default_factory=list)
    applies_to: list[str] = Field(default_factory=list)
    build_version: str = ""


class BusinessRelationship(CandidateKnowledge):
    """A directed relationship between two business entities."""

    candidate_type: str = "relationship"
    name: str
    from_entity_id: str = ""
    to_entity_id: str = ""
    relationship_type: str = ""
    cardinality: str | None = None
    join_paths: list[JoinPath] = Field(default_factory=list)
    description: str = ""
    join_columns: list[tuple[str, str]] = Field(default_factory=list)
    is_deterministic: bool = False
    build_version: str = ""

    @property
    def from_entity(self) -> str:
        """Plan-compatible alias for the source entity ID."""
        return self.from_entity_id

    @property
    def to_entity(self) -> str:
        """Plan-compatible alias for the target entity ID."""
        return self.to_entity_id


class TimeIntelligence(CandidateKnowledge):
    """Time-related metadata for a date or datetime column."""

    candidate_type: str = "time_intelligence"
    name: str = ""
    column_ref: str
    time_role: str = ""
    granularity: str = ""
    timezone: str | None = None


class SecurityTag(CandidateKnowledge):
    """Security or data-classification tag."""

    candidate_type: str = "security_tag"
    name: str = ""
    scope: str = ""
    classification: str = ""
    applies_to: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


SecurityMetadata = SecurityTag


class LearningMetadata(BaseModel):
    """Human feedback captured for future recompilation."""

    model_config = ConfigDict(frozen=True)

    entity_ref: str
    feedback_type: str
    original_value: Any = None
    corrected_value: Any = None
    feedback_by: str = ""
    feedback_at: datetime = Field(default_factory=datetime.utcnow)
    applied: bool = False


class KnowledgeGraph(BaseModel):
    """Mutable container aggregating all KIR elements."""

    model_config = ConfigDict(frozen=False)

    entities: list[BusinessEntity] = Field(default_factory=list)
    concepts: list[BusinessConcept] = Field(default_factory=list)
    metrics: list[Metric] = Field(default_factory=list)
    rules: list[BusinessRule] = Field(default_factory=list)
    relationships: list[BusinessRelationship] = Field(default_factory=list)
    synonyms: list[Synonym] = Field(default_factory=list)
    time_intelligence: list[TimeIntelligence] = Field(default_factory=list)
    security_tags: list[SecurityTag] = Field(default_factory=list)
    learning_metadata: list[LearningMetadata] = Field(default_factory=list)

    def add_entity(self, entity: BusinessEntity) -> None:
        self.entities.append(entity)

    def add_concept(self, concept: BusinessConcept) -> None:
        self.concepts.append(concept)

    def add_metric(self, metric: Metric) -> None:
        self.metrics.append(metric)

    def add_rule(self, rule: BusinessRule) -> None:
        self.rules.append(rule)

    def add_relationship(self, relationship: BusinessRelationship) -> None:
        self.relationships.append(relationship)

    def add_synonym(self, synonym: Synonym) -> None:
        self.synonyms.append(synonym)

    def add_time_intelligence(self, item: TimeIntelligence) -> None:
        self.time_intelligence.append(item)

    def add_security_tag(self, tag: SecurityTag) -> None:
        self.security_tags.append(tag)

    def get_entity(self, entity_id: str) -> BusinessEntity | None:
        return next((entity for entity in self.entities if entity.id == entity_id), None)

    def get_entity_by_name(self, name: str) -> BusinessEntity | None:
        return next((entity for entity in self.entities if entity.name == name), None)

    def get_concept(self, concept_id: str) -> BusinessConcept | None:
        return next((concept for concept in self.concepts if concept.id == concept_id), None)

    def iter_candidates(self) -> list[CandidateKnowledge]:
        """Return all reviewable KIR nodes."""
        return [
            *self.entities,
            *self.concepts,
            *self.metrics,
            *self.rules,
            *self.relationships,
            *self.time_intelligence,
            *self.security_tags,
        ]

    @property
    def node_count(self) -> int:
        return (
            len(self.entities)
            + len(self.concepts)
            + len(self.metrics)
            + len(self.rules)
            + len(self.synonyms)
            + len(self.time_intelligence)
            + len(self.security_tags)
        )

    @property
    def edge_count(self) -> int:
        return len(self.relationships)
