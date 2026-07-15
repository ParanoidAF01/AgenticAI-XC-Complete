"""Metadata Intermediate Representation (MIR) for the SKC project.

This module defines the structural metadata models that capture the physical
schema of a database — tables, columns, foreign keys, indexes, and data
profiles.  MIR is the first IR produced by the extraction pipeline and serves
as the foundation on which the Knowledge Intermediate Representation (KIR) is
built.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field

from skc.ir.common import NormalizedType, Provenance


class DatabaseDialect(str, Enum):
    """Supported source dialect identifiers."""

    POSTGRES = "postgres"
    MYSQL = "mysql"
    MSSQL = "mssql"
    SNOWFLAKE = "snowflake"
    BIGQUERY = "bigquery"
    DDL_FILE = "ddl_file"
    UNKNOWN = "unknown"


class TableType(str, Enum):
    """Physical database object type."""

    TABLE = "TABLE"
    VIEW = "VIEW"
    MATERIALIZED_VIEW = "MATERIALIZED_VIEW"
    EXTERNAL = "EXTERNAL"


class ConstraintType(str, Enum):
    """Supported table constraint categories."""

    CHECK = "CHECK"
    UNIQUE = "UNIQUE"
    NOT_NULL = "NOT_NULL"
    DEFAULT = "DEFAULT"


class TableTopology(str, Enum):
    """Structural role assigned by the schema graph builder."""

    FACT = "FACT"
    DIMENSION = "DIMENSION"
    BRIDGE = "BRIDGE"
    STANDALONE = "STANDALONE"
    UNKNOWN = "UNKNOWN"


class MIRColumn(BaseModel):
    """A single column within a database table.

    Stores both the raw database type string and a dialect-agnostic
    ``NormalizedType`` so that downstream logic can operate without
    knowledge of the source dialect.
    """

    model_config = ConfigDict(frozen=True)

    name: str = Field(..., description="Column name as it appears in the database.")
    data_type: str = Field(..., description="Raw database-specific type string (e.g. 'VARCHAR(255)').")
    normalized_type: NormalizedType = Field(..., description="Dialect-agnostic normalized type.")
    ordinal_position: int = Field(..., description="1-based position of the column in the table.")
    is_nullable: bool = True
    is_primary_key: bool = False
    is_foreign_key: bool = False
    default_value: str | None = None
    max_length: int | None = None
    numeric_precision: int | None = None
    numeric_scale: int | None = None
    comment: str | None = None


class MIRPrimaryKey(BaseModel):
    """Primary-key constraint for a table."""

    model_config = ConfigDict(frozen=True)

    columns: list[str] = Field(default_factory=list)
    name: str | None = None


class MIRForeignKey(BaseModel):
    """A foreign-key constraint linking columns across two tables.

    Captures the full qualified path on both sides of the relationship
    (schema + table + columns) so that cross-schema references are
    unambiguous.
    """

    model_config = ConfigDict(frozen=True)

    name: str | None = Field(default=None, description="Constraint name as defined in the database.")
    columns: list[str] = Field(default_factory=list, description="Referencing columns.")
    referred_schema: str = Field(default="", description="Schema containing the referenced table.")
    referred_table: str = Field(default="", description="Name of the referenced table.")
    referred_columns: list[str] = Field(default_factory=list, description="Referenced columns.")


class MIRIndex(BaseModel):
    """An index defined on a database table.

    Records the indexed columns and whether the index enforces uniqueness.
    """

    model_config = ConfigDict(frozen=True)

    name: str = Field(..., description="Index name as defined in the database.")
    columns: list[str] = Field(default_factory=list, description="Ordered list of columns included in the index.")
    is_unique: bool = False


class MIRConstraint(BaseModel):
    """A table-level constraint extracted from source metadata."""

    model_config = ConfigDict(frozen=True)

    name: str
    type: ConstraintType
    columns: list[str] = Field(default_factory=list)
    expression: str | None = None


class MIRTable(BaseModel):
    """A database table (or view) and its structural metadata.

    Aggregates columns, primary-key information, foreign keys, and indexes
    into a single cohesive representation of a database object.
    """

    model_config = ConfigDict(frozen=True)

    name: str = Field(..., description="Table name as it appears in the database.")
    schema_name: str = Field(..., description="Schema that contains this table.")
    table_type: TableType | str = Field(default=TableType.TABLE, description="Object type.")
    row_count: int | None = Field(default=None, description="Approximate row count, if available.")
    columns: list[MIRColumn] = Field(default_factory=list)
    primary_key: MIRPrimaryKey | None = None
    foreign_keys: list[MIRForeignKey] = Field(default_factory=list)
    indexes: list[MIRIndex] = Field(default_factory=list)
    constraints: list[MIRConstraint] = Field(default_factory=list)
    table_topology: TableTopology | None = None
    comment: str | None = None
    ddl: str | None = None

    @property
    def primary_key_columns(self) -> list[str]:
        """Return the table's primary-key column names."""
        return self.primary_key.columns if self.primary_key else []


class MIRSchema(BaseModel):
    """A database schema containing zero or more tables.

    Serves as a namespace grouping for tables within a database.
    """

    model_config = ConfigDict(frozen=True)

    name: str = Field(..., description="Schema name.")
    tables: list[MIRTable] = Field(default_factory=list)


class MIRDatabase(BaseModel):
    """Top-level MIR node representing an entire database.

    Contains one or more schemas and provides convenience methods for
    navigating the table hierarchy.
    """

    model_config = ConfigDict(frozen=True)

    name: str = Field(..., description="Logical database name.")
    dialect: DatabaseDialect | str = Field(..., description="SQL dialect identifier.")
    connector_version: str = "0.1.0"
    schemas: list[MIRSchema] = Field(default_factory=list)
    extracted_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Timestamp of when the metadata was extracted.",
    )
    provenance: Provenance | None = None

    def get_all_tables(self) -> list[MIRTable]:
        """Return a flat list of every table across all schemas.

        Returns:
            A list of ``MIRTable`` instances from every schema in the database.
        """
        return [table for schema in self.schemas for table in schema.tables]

    def get_table(self, schema_name: str, table_name: str) -> MIRTable | None:
        """Look up a specific table by its schema and table name.

        Args:
            schema_name: The schema to search within.
            table_name: The table name to find.

        Returns:
            The matching ``MIRTable`` if found, otherwise ``None``.
        """
        for schema in self.schemas:
            if schema.name == schema_name:
                for table in schema.tables:
                    if table.name == table_name:
                        return table
        return None

    @property
    def table_count(self) -> int:
        """Total number of tables across all schemas in the database."""
        return sum(len(schema.tables) for schema in self.schemas)

    def to_jsonl(self, path: str | Path, schema_version: str = "1.0") -> None:
        """Write this database as a JSONL artefact."""
        from skc.ir.serde import write_jsonl

        write_jsonl(Path(path), [self], schema_version=schema_version)

    @classmethod
    def from_jsonl(cls, path: str | Path) -> MIRDatabase:
        """Read the first MIR database from a JSONL artefact."""
        from skc.ir.serde import read_jsonl

        databases = read_jsonl(Path(path), cls)
        if not databases:
            raise ValueError(f"No MIRDatabase records found in {path}")
        return databases[0]


# ---------------------------------------------------------------------------
# Data-profiling models
# ---------------------------------------------------------------------------


class MIRColumnProfile(BaseModel):
    """Statistical profile for a single column.

    Captures distribution and quality metrics gathered during the
    data-profiling stage, including distinct counts, null percentages,
    min/max values, and representative sample values.
    """

    model_config = ConfigDict(frozen=True)

    schema_name: str = Field(..., description="Schema containing the profiled column.")
    table_name: str = Field(..., description="Table containing the profiled column.")
    column_name: str = Field(..., description="Name of the profiled column.")
    distinct_count: int | None = None
    null_count: int | None = None
    null_ratio: float | None = None
    min_value: str | None = None
    max_value: str | None = None
    mean_value: float | None = None
    sample_values: list[str] = Field(default_factory=list)
    value_distribution: dict[str, int] = Field(default_factory=dict)
    pattern_summary: str | None = Field(
        default=None,
        description="Human-readable summary of value patterns (e.g. 'email addresses').",
    )

    @property
    def column_ref(self) -> str:
        """Fully qualified column reference."""
        return f"{self.schema_name}.{self.table_name}.{self.column_name}"

    @property
    def null_percentage(self) -> float | None:
        """Backward-compatible alias for ``null_ratio``."""
        return self.null_ratio


class MIRProfileSet(BaseModel):
    """A collection of column profiles produced by a single profiling run.

    Groups all ``MIRColumnProfile`` instances together with a timestamp
    recording when the profiling was performed.
    """

    model_config = ConfigDict(frozen=True)

    profiles: list[MIRColumnProfile] = Field(default_factory=list)
    profiled_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Timestamp of when the profiling run completed.",
    )

    def get_profile(self, schema: str, table: str, column: str) -> MIRColumnProfile | None:
        """Look up a column profile by its fully qualified path.

        Args:
            schema: Schema name.
            table: Table name.
            column: Column name.

        Returns:
            The matching ``MIRColumnProfile`` if found, otherwise ``None``.
        """
        for profile in self.profiles:
            if (
                profile.schema_name == schema
                and profile.table_name == table
                and profile.column_name == column
            ):
                return profile
        return None
