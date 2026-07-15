# MIR — Metadata Intermediate Representation Specification

> **Version**: 1.0 · **Module**: `skc.ir.mir`

---

## Purpose

The MIR captures **only technical database metadata** — zero business semantics. It is the output of Stages 1–3 (Schema Parser, Schema Graph Builder, Data Profiler) and the input to Stage 4 (Semantic Inferencer).

---

## Enums

### DatabaseDialect

| Value | Description |
|---|---|
| `POSTGRES` | PostgreSQL |
| `MYSQL` | MySQL / MariaDB |
| `SNOWFLAKE` | Snowflake Data Cloud |
| `BIGQUERY` | Google BigQuery |
| `DDL_FILE` | Parsed from raw DDL files |

### TableType

| Value | Description |
|---|---|
| `TABLE` | Regular table |
| `VIEW` | SQL view |
| `MATERIALIZED_VIEW` | Materialized view |
| `EXTERNAL` | External / foreign table |

### NormalizedType

Dialect-agnostic type normalisation.

| Value | Maps From (Examples) |
|---|---|
| `STRING` | VARCHAR, TEXT, CHAR, NVARCHAR |
| `INTEGER` | INT, BIGINT, SMALLINT, SERIAL |
| `DECIMAL` | DECIMAL, NUMERIC, FLOAT, DOUBLE, REAL |
| `BOOLEAN` | BOOLEAN, BOOL, BIT |
| `DATE` | DATE |
| `TIMESTAMP` | TIMESTAMP, TIMESTAMPTZ, DATETIME |
| `BLOB` | BYTEA, BLOB, BINARY |
| `JSON` | JSON, JSONB |
| `ARRAY` | ARRAY, [] types |
| `OTHER` | Anything unrecognised |

### ConstraintType

| Value | Description |
|---|---|
| `CHECK` | CHECK constraint expression |
| `UNIQUE` | Column(s) uniqueness |
| `NOT_NULL` | Non-nullable constraint |
| `DEFAULT` | Default value constraint |

### TableTopology

Added by Stage 2 (Schema Graph Builder) based on structural heuristics.

| Value | Heuristic |
|---|---|
| `FACT` | Many FKs pointing outward, high row count |
| `DIMENSION` | Many FKs pointing inward from facts |
| `BRIDGE` | Only FK columns (many-to-many junction) |
| `STANDALONE` | No FK relationships |

---

## Models

### MIRDatabase

Top-level container for an entire database extraction.

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | `str` | ✅ | Database name |
| `dialect` | `DatabaseDialect` | ✅ | Source database type |
| `extracted_at` | `datetime` | ✅ | Timestamp of extraction |
| `connector_version` | `str` | ✅ | Version of the connector used |
| `schemas` | `list[MIRSchema]` | | Schemas in this database |

### MIRSchema

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | `str` | ✅ | Schema name |
| `tables` | `list[MIRTable]` | | Tables in this schema |

### MIRTable

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | `str` | ✅ | Table name |
| `schema_name` | `str` | ✅ | Parent schema name |
| `table_type` | `TableType` | | Default: `TABLE` |
| `row_count` | `int \| None` | | Approximate row count |
| `columns` | `list[MIRColumn]` | | Column definitions |
| `primary_key` | `MIRPrimaryKey \| None` | | PK definition |
| `foreign_keys` | `list[MIRForeignKey]` | | FK definitions |
| `indexes` | `list[MIRIndex]` | | Index definitions |
| `constraints` | `list[MIRConstraint]` | | Constraint definitions |
| `comment` | `str \| None` | | Database-level comment |
| `ddl` | `str \| None` | | Raw DDL if available |
| `topology` | `TableTopology \| None` | | Added by Schema Graph Builder |

### MIRColumn

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | `str` | ✅ | Column name |
| `ordinal_position` | `int` | ✅ | Position in table (1-based) |
| `data_type` | `str` | ✅ | Raw database type string |
| `normalized_type` | `NormalizedType` | ✅ | Dialect-agnostic type |
| `is_nullable` | `bool` | | Default: `True` |
| `default_value` | `str \| None` | | Default value expression |
| `max_length` | `int \| None` | | Max character/byte length |
| `numeric_precision` | `int \| None` | | Total digits for numerics |
| `numeric_scale` | `int \| None` | | Decimal digits for numerics |
| `comment` | `str \| None` | | Database-level column comment |
| `is_primary_key` | `bool` | | Part of primary key |
| `is_foreign_key` | `bool` | | Part of a foreign key |

### MIRPrimaryKey

| Field | Type | Required | Description |
|---|---|---|---|
| `columns` | `list[str]` | ✅ | Column names forming the PK |
| `name` | `str \| None` | | Constraint name |

### MIRForeignKey

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | `str \| None` | | Constraint name |
| `columns` | `list[str]` | ✅ | Local column names |
| `referred_schema` | `str` | ✅ | Target schema |
| `referred_table` | `str` | ✅ | Target table |
| `referred_columns` | `list[str]` | ✅ | Target column names |

### MIRIndex

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | `str` | ✅ | Index name |
| `columns` | `list[str]` | ✅ | Indexed columns |
| `is_unique` | `bool` | | Default: `False` |

### MIRConstraint

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | `str` | ✅ | Constraint name |
| `type` | `ConstraintType` | ✅ | Constraint category |
| `columns` | `list[str]` | ✅ | Affected columns |
| `expression` | `str \| None` | | CHECK expression |

### MIRColumnProfile

Attached by Stage 3 (Data Profiler). Stored separately from MIR core.

| Field | Type | Required | Description |
|---|---|---|---|
| `column_ref` | `str` | ✅ | `schema.table.column` reference |
| `distinct_count` | `int` | | Number of distinct values |
| `null_count` | `int` | | Number of NULL values |
| `null_ratio` | `float` | | Ratio of NULLs (0.0–1.0) |
| `min_value` | `str \| None` | | Minimum value (as string) |
| `max_value` | `str \| None` | | Maximum value (as string) |
| `mean_value` | `float \| None` | | Mean for numeric columns |
| `sample_values` | `list[str]` | | Up to 10 representative samples |
| `value_distribution` | `dict[str, int]` | | Top-N value frequencies |
| `pattern_summary` | `str \| None` | | Detected pattern (email, UUID, etc.) |

### MIRProfileSet

| Field | Type | Required | Description |
|---|---|---|---|
| `database_ref` | `str` | ✅ | Database name reference |
| `profiles` | `list[MIRColumnProfile]` | | All column profiles |
| `profiled_at` | `datetime` | ✅ | Profiling timestamp |

---

## Serialisation Format

MIR artefacts are stored as **JSON Lines (`.jsonl`)** files with a header line:

```jsonl
{"_header": true, "schema_version": "1.0", "model_type": "MIRDatabase", "created_at": "2025-01-15T10:30:00Z"}
{"name": "ecommerce", "dialect": "POSTGRES", "extracted_at": "2025-01-15T10:30:00Z", "connector_version": "0.1.0", "schemas": [...]}
```

**Profiles** are stored in a separate file (`profiles.jsonl`) to allow stages 1–2 to run without a live database connection.

---

## Design Decisions

| Decision | Rationale |
|---|---|
| Normalised type enum | Enables dialect-agnostic downstream processing |
| Raw DDL preserved | Supports re-parsing and provides an audit trail |
| Profile is a separate extension | Stages 1–2 can run offline; profiling requires a live connection |
| JSONL serialisation | Each table = one JSON line — streamable, diffable, appendable |
| Topology annotation | Structural heuristics (FACT/DIMENSION/BRIDGE) accelerate semantic inference |
