# KIR — Knowledge Intermediate Representation Specification

> **Version**: 1.0 · **Module**: `skc.ir.kir`

---

## Purpose

The KIR captures **semantic business knowledge** inferred from metadata analysis or contributed by domain plugins. It is the output of Stages 4–8 and the input to Stages 9–11 (Validation, Review, Graph Generation).

Every KIR node extends `CandidateKnowledge` — carrying provenance, confidence, and review status — ensuring that all inferred knowledge is traceable, scoreable, and governable.

---

## Base Model: CandidateKnowledge

All KIR domain models inherit from `CandidateKnowledge`:

| Field | Type | Default | Description |
|---|---|---|---|
| `id` | `str` | UUID | Unique node identifier |
| `provenance` | `Provenance` | required | Source attribution |
| `confidence` | `Confidence` | required | Confidence score + signals |
| `review` | `ReviewStatus` | PENDING | Current review state |
| `version` | `int` | 1 | Schema version |
| `supersedes` | `str \| None` | None | ID of previous version |
| `metadata` | `dict[str, Any]` | {} | Extensible metadata |

---

## Supporting Models

### Synonym

| Field | Type | Default | Description |
|---|---|---|---|
| `term` | `str` | required | Alternative name/alias |
| `language` | `str` | `"en"` | Language code |
| `provenance` | `Provenance` | required | Source attribution |
| `confidence` | `Confidence` | required | Confidence score |

### GrainDefinition

| Field | Type | Default | Description |
|---|---|---|---|
| `grain_columns` | `list[str]` | required | Columns defining the grain |
| `description` | `str` | required | Human-readable grain description |
| `provenance` | `Provenance` | required | Source attribution |

### JoinPath

| Field | Type | Default | Description |
|---|---|---|---|
| `from_table` | `str` | required | Source table reference |
| `from_columns` | `list[str]` | required | Source join columns |
| `to_table` | `str` | required | Target table reference |
| `to_columns` | `list[str]` | required | Target join columns |
| `join_type` | `JoinType` | `INNER` | SQL join type |
| `is_deterministic` | `bool` | `False` | True if FK-backed |
| `provenance` | `Provenance` | required | Source attribution |
| `confidence` | `Confidence` | required | Join path confidence |

### MetricFilter

| Field | Type | Description |
|---|---|---|
| `column` | `str` | Column reference |
| `operator` | `str` | SQL operator (=, >, IN, etc.) |
| `value` | `str` | Filter value |

---

## Domain Models

### BusinessEntity

Represents a semantically identified business entity mapped to database tables.

| Field | Type | Default | Description |
|---|---|---|---|
| `name` | `str` | required | Entity name (e.g. "Customer") |
| `description` | `str` | required | Business description |
| `mapped_tables` | `list[str]` | required | MIR table refs (`schema.table`) |
| `entity_type` | `EntityType` | required | CORE, REFERENCE, TRANSACTIONAL, BRIDGE, AGGREGATE |
| `synonyms` | `list[Synonym]` | [] | Alternative names |
| `grain` | `GrainDefinition \| None` | None | Row-level identity |

### BusinessRelationship

Represents a directed semantic relationship between two business entities.

| Field | Type | Default | Description |
|---|---|---|---|
| `name` | `str` | required | Relationship name (e.g. "Customer PLACES Order") |
| `from_entity` | `str` | required | Source BusinessEntity ID |
| `to_entity` | `str` | required | Target BusinessEntity ID |
| `relationship_type` | `RelType` | required | ONE_TO_ONE, ONE_TO_MANY, MANY_TO_MANY |
| `cardinality` | `str \| None` | None | Cardinality label (e.g. "1:N") |
| `join_paths` | `list[JoinPath]` | [] | Physical join paths |
| `description` | `str` | required | Relationship description |

### BusinessConcept

Represents a column-level business concept.

| Field | Type | Default | Description |
|---|---|---|---|
| `name` | `str` | required | Concept name (e.g. "Revenue") |
| `description` | `str` | required | Business description |
| `category` | `ConceptCategory` | required | MEASURE, DIMENSION, CLASSIFICATION, STATUS, TEMPORAL |
| `mapped_columns` | `list[str]` | required | Column refs (`schema.table.column`) |
| `synonyms` | `list[Synonym]` | [] | Alternative names |

### Metric

Represents a derived business measure with a computation formula.

| Field | Type | Default | Description |
|---|---|---|---|
| `name` | `str` | required | Metric name (e.g. "Total Revenue") |
| `description` | `str` | required | Business description |
| `formula` | `str` | required | SQL expression or pseudo-formula |
| `formula_type` | `FormulaType` | required | AGGREGATE, RATIO, WINDOW, DERIVED |
| `base_columns` | `list[str]` | required | Source column refs |
| `filters` | `list[MetricFilter]` | [] | Optional filter predicates |
| `grain` | `GrainDefinition \| None` | None | Aggregation grain |
| `unit` | `str \| None` | None | Unit of measure (e.g. "USD") |

### BusinessRule

Represents a constraint, derivation, or validation rule.

| Field | Type | Default | Description |
|---|---|---|---|
| `name` | `str` | required | Rule name |
| `description` | `str` | required | Business description |
| `rule_type` | `RuleType` | required | CONSTRAINT, DERIVATION, CLASSIFICATION, VALIDATION, TEMPORAL |
| `expression` | `str` | required | Logical expression |
| `scope_tables` | `list[str]` | [] | Applicable table refs |
| `scope_columns` | `list[str]` | [] | Applicable column refs |

### TimeIntelligence

Represents temporal metadata for a date/timestamp column.

| Field | Type | Default | Description |
|---|---|---|---|
| `column_ref` | `str` | required | Column reference |
| `time_role` | `TimeRole` | required | EVENT_TIME, CREATED_AT, UPDATED_AT, etc. |
| `granularity` | `TimeGranularity` | required | SECOND through YEAR |
| `timezone` | `str \| None` | None | Timezone if applicable |

### SecurityMetadata

Represents data sensitivity classification.

| Field | Type | Default | Description |
|---|---|---|---|
| `scope` | `str` | required | Table or column ref |
| `classification` | `SecurityClassification` | required | PUBLIC through PCI |
| `tags` | `list[str]` | [] | Additional security tags |

### LearningMetadata

Feedback record — **not** a CandidateKnowledge subclass.

| Field | Type | Default | Description |
|---|---|---|---|
| `id` | `str` | UUID | Unique identifier |
| `entity_ref` | `str` | required | Referenced KIR node ID |
| `feedback_type` | `FeedbackType` | required | CORRECTION, CONFIRMATION, REJECTION, ANNOTATION |
| `original_value` | `Any` | required | Value before correction |
| `corrected_value` | `Any` | required | Value after correction |
| `feedback_by` | `str` | required | Reviewer identifier |
| `feedback_at` | `datetime` | required | Feedback timestamp |
| `applied` | `bool` | False | Whether correction has been applied |

---

## KnowledgeGraph Container

The `KnowledgeGraph` class is the **mutable container** that accumulates all KIR nodes during compilation.

### Fields

| Field | Type | Description |
|---|---|---|
| `entities` | `list[BusinessEntity]` | Business entities |
| `relationships` | `list[BusinessRelationship]` | Entity relationships |
| `concepts` | `list[BusinessConcept]` | Column-level concepts |
| `metrics` | `list[Metric]` | Derived metrics |
| `rules` | `list[BusinessRule]` | Business rules |
| `time_intelligence` | `list[TimeIntelligence]` | Temporal metadata |
| `security` | `list[SecurityMetadata]` | Security classifications |
| `learning` | `list[LearningMetadata]` | Human feedback records |

### Mutator Methods

| Method | Description |
|---|---|
| `add_entity(entity)` | Append a BusinessEntity |
| `add_relationship(rel)` | Append a BusinessRelationship |
| `add_concept(concept)` | Append a BusinessConcept |
| `add_metric(metric)` | Append a Metric |
| `add_rule(rule)` | Append a BusinessRule |
| `add_time_intelligence(ti)` | Append a TimeIntelligence |
| `add_security(sec)` | Append a SecurityMetadata |
| `add_learning(lm)` | Append a LearningMetadata |

### Query Methods

| Method | Returns | Description |
|---|---|---|
| `get_entity_by_name(name)` | `BusinessEntity \| None` | Case-insensitive lookup |
| `get_entity_by_id(id)` | `BusinessEntity \| None` | Exact ID lookup |
| `get_all_candidates()` | `list[CandidateKnowledge]` | All KIR nodes (excludes LearningMetadata) |
| `get_candidates_by_tier(tier)` | `list[CandidateKnowledge]` | Filter by confidence tier |
| `get_pending_review()` | `list[CandidateKnowledge]` | Filter by PENDING status |
| `node_count()` | `dict[str, int]` | Count per node type |

---

## Design Decisions

| Decision | Rationale |
|---|---|
| Every KIR node extends CandidateKnowledge | Uniform provenance + confidence + review for all inferred knowledge |
| JoinPath carries its own confidence | A single relationship may have multiple join paths with different reliability |
| Metric formula stored as string | Human-readable; enables downstream SQL generation by consumers |
| SecurityMetadata separate from BusinessEntity | Security may apply at column granularity, not just entity level |
| LearningMetadata feeds future recompilation | Creates a flywheel — corrections improve the next build |
| KnowledgeGraph is mutable | Stages progressively enrich it; immutability would require rebuilding on each addition |
