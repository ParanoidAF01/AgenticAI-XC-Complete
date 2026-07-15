"""PostgreSQL metadata connector backed by SQLAlchemy introspection."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Engine

from skc.connectors.base import MetadataConnector, normalize_type
from skc.ir.common import Provenance, SourceType
from skc.ir.mir import (
    ConstraintType,
    DatabaseDialect,
    MIRColumn,
    MIRConstraint,
    MIRDatabase,
    MIRForeignKey,
    MIRIndex,
    MIRPrimaryKey,
    MIRSchema,
    MIRTable,
    TableType,
)


class PostgresConnector(MetadataConnector):
    """Extract structural metadata from PostgreSQL using SQLAlchemy."""

    name = "postgres"
    version = "0.1.0"
    dialect = DatabaseDialect.POSTGRES
    default_database_name = "postgres"
    ignored_schemas = {"information_schema", "pg_catalog"}
    ignored_schema_prefixes = ("pg_toast",)

    def __init__(self, config) -> None:
        super().__init__(config)
        self.engine: Engine | None = None

    def connect(self) -> None:
        if not self.config.connection_string:
            raise ValueError(
                f"connector.connection_string is required for {self.name} connector"
            )
        self.engine = create_engine(self.config.connection_string)

    def close(self) -> None:
        if self.engine is not None:
            self.engine.dispose()
            self.engine = None

    def extract_metadata(self) -> MIRDatabase:
        if self.engine is None:
            self.connect()
        assert self.engine is not None

        inspector = inspect(self.engine)
        schemas: list[MIRSchema] = []
        database_name = self.engine.url.database or self.default_database_name

        for schema_name in self._schema_names(inspector):
            tables: list[MIRTable] = []
            table_names = inspector.get_table_names(schema=schema_name)
            view_names = inspector.get_view_names(schema=schema_name)
            materialized_view_names = self._materialized_view_names(inspector, schema_name)

            for table_name in table_names:
                tables.append(self._build_table(inspector, schema_name, table_name, TableType.TABLE))
            for view_name in view_names:
                tables.append(self._build_table(inspector, schema_name, view_name, TableType.VIEW))
            for view_name in materialized_view_names:
                tables.append(
                    self._build_table(inspector, schema_name, view_name, TableType.MATERIALIZED_VIEW)
                )

            if tables:
                schemas.append(MIRSchema(name=schema_name, tables=sorted(tables, key=lambda t: t.name)))

        provenance = Provenance(
            source_type=SourceType.DETERMINISTIC,
            source_id=self.config.connection_string,
            source_detail="SQLAlchemy inspector",
            timestamp=datetime.utcnow(),
            build_version=self.version,
        )
        return MIRDatabase(
            name=database_name,
            dialect=self.dialect,
            connector_version=self.version,
            schemas=schemas,
            provenance=provenance,
        )

    def _schema_names(self, inspector: Any) -> list[str]:
        ignored = {schema.lower() for schema in self.ignored_schemas}
        return [
            schema
            for schema in inspector.get_schema_names()
            if schema.lower() not in ignored
            and not any(schema.lower().startswith(prefix) for prefix in self.ignored_schema_prefixes)
        ]

    def _materialized_view_names(self, inspector: Any, schema_name: str) -> list[str]:
        getter = getattr(inspector, "get_materialized_view_names", None)
        if getter is None:
            return []
        try:
            return getter(schema=schema_name)
        except Exception:
            return []

    def _build_table(
        self,
        inspector: Any,
        schema_name: str,
        table_name: str,
        table_type: TableType,
    ) -> MIRTable:
        pk_info = inspector.get_pk_constraint(table_name, schema=schema_name) or {}
        pk_columns = list(pk_info.get("constrained_columns") or [])
        primary_key = MIRPrimaryKey(columns=pk_columns, name=pk_info.get("name")) if pk_columns else None

        foreign_keys = [
            MIRForeignKey(
                name=fk.get("name"),
                columns=list(fk.get("constrained_columns") or []),
                referred_schema=fk.get("referred_schema") or schema_name,
                referred_table=fk.get("referred_table") or "",
                referred_columns=list(fk.get("referred_columns") or []),
            )
            for fk in inspector.get_foreign_keys(table_name, schema=schema_name)
        ]
        fk_columns = {column for fk in foreign_keys for column in fk.columns}

        columns: list[MIRColumn] = []
        for ordinal, column_info in enumerate(
            inspector.get_columns(table_name, schema=schema_name),
            start=1,
        ):
            raw_type = str(column_info.get("type", "UNKNOWN"))
            columns.append(
                MIRColumn(
                    name=column_info["name"],
                    data_type=raw_type,
                    normalized_type=normalize_type(raw_type),
                    ordinal_position=ordinal,
                    is_nullable=bool(column_info.get("nullable", True)),
                    is_primary_key=column_info["name"] in pk_columns,
                    is_foreign_key=column_info["name"] in fk_columns,
                    default_value=(
                        str(column_info["default"])
                        if column_info.get("default") is not None
                        else None
                    ),
                    max_length=getattr(column_info.get("type"), "length", None),
                    numeric_precision=getattr(column_info.get("type"), "precision", None),
                    numeric_scale=getattr(column_info.get("type"), "scale", None),
                    comment=column_info.get("comment"),
                )
            )

        indexes = [
            MIRIndex(
                name=index.get("name") or "",
                columns=list(index.get("column_names") or []),
                is_unique=bool(index.get("unique", False)),
            )
            for index in inspector.get_indexes(table_name, schema=schema_name)
        ]

        constraints = self._constraints(inspector, table_name, schema_name)
        table_comment = self._table_comment(inspector, table_name, schema_name)

        return MIRTable(
            name=table_name,
            schema_name=schema_name,
            table_type=table_type,
            columns=columns,
            primary_key=primary_key,
            foreign_keys=foreign_keys,
            indexes=indexes,
            constraints=constraints,
            comment=table_comment,
        )

    def _constraints(self, inspector: Any, table_name: str, schema_name: str) -> list[MIRConstraint]:
        constraints: list[MIRConstraint] = []

        try:
            unique_constraints = inspector.get_unique_constraints(table_name, schema=schema_name)
        except Exception:
            unique_constraints = []
        for constraint in unique_constraints:
            constraints.append(
                MIRConstraint(
                    name=constraint.get("name") or "unique_constraint",
                    type=ConstraintType.UNIQUE,
                    columns=list(constraint.get("column_names") or []),
                )
            )

        try:
            check_constraints = inspector.get_check_constraints(table_name, schema=schema_name)
        except Exception:
            check_constraints = []
        for constraint in check_constraints:
            constraints.append(
                MIRConstraint(
                    name=constraint.get("name") or "check_constraint",
                    type=ConstraintType.CHECK,
                    expression=constraint.get("sqltext"),
                )
            )

        return constraints

    def _table_comment(self, inspector: Any, table_name: str, schema_name: str) -> str | None:
        try:
            comment = inspector.get_table_comment(table_name, schema=schema_name)
        except Exception:
            return None
        return comment.get("text") if isinstance(comment, dict) else None
