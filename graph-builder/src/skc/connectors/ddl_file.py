"""DDL file metadata connector."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from pathlib import Path

import sqlglot
from sqlglot import exp

from skc.connectors.base import MetadataConnector, normalize_type, resolve_path
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


class DDLFileConnector(MetadataConnector):
    """Extract MIR metadata from SQL DDL files."""

    name = "ddl_file"
    version = "0.1.0"

    def __init__(self, config) -> None:
        super().__init__(config)
        if not config.ddl_path:
            raise ValueError("connector.ddl_path is required for ddl_file connector")
        self.path = resolve_path(config.ddl_path)
        self.sql = ""

    def connect(self) -> None:
        if not self.path.exists():
            raise FileNotFoundError(f"DDL file does not exist: {self.path}")
        self.sql = self.path.read_text(encoding="utf-8")

    def close(self) -> None:
        return None

    def extract_metadata(self) -> MIRDatabase:
        if not self.sql:
            self.connect()

        expressions = sqlglot.parse(self.sql, read="postgres")
        tables: dict[tuple[str, str], MIRTable] = {}
        indexes: dict[tuple[str, str], list[MIRIndex]] = defaultdict(list)
        pending_constraints: dict[tuple[str, str], list[MIRConstraint | MIRForeignKey | MIRPrimaryKey]] = defaultdict(list)

        for expression in expressions:
            if isinstance(expression, exp.Create) and expression.args.get("kind") == "TABLE":
                table = self._parse_create_table(expression)
                tables[(table.schema_name, table.name)] = table
            elif isinstance(expression, exp.Create) and expression.args.get("kind") == "INDEX":
                key, index = self._parse_create_index(expression)
                if key and index:
                    indexes[key].append(index)
            elif isinstance(expression, exp.Alter):
                key, constraints = self._parse_alter_table(expression)
                if key:
                    pending_constraints[key].extend(constraints)

        for key, extra_indexes in indexes.items():
            if key in tables:
                table = tables[key]
                tables[key] = table.model_copy(update={"indexes": [*table.indexes, *extra_indexes]})

        for key, additions in pending_constraints.items():
            if key not in tables:
                continue
            table = tables[key]
            constraints = list(table.constraints)
            foreign_keys = list(table.foreign_keys)
            primary_key = table.primary_key
            for addition in additions:
                if isinstance(addition, MIRForeignKey):
                    foreign_keys.append(addition)
                elif isinstance(addition, MIRPrimaryKey):
                    primary_key = addition
                elif addition.type == ConstraintType.CHECK:
                    constraints.append(addition)
                elif addition.type == ConstraintType.UNIQUE:
                    constraints.append(addition)
                elif addition.type == ConstraintType.NOT_NULL:
                    constraints.append(addition)
                elif addition.type == ConstraintType.DEFAULT:
                    constraints.append(addition)
            columns = self._mark_foreign_key_columns(table.columns, foreign_keys)
            tables[key] = table.model_copy(
                update={
                    "columns": columns,
                    "constraints": constraints,
                    "foreign_keys": foreign_keys,
                    "primary_key": primary_key,
                }
            )

        schemas: dict[str, list[MIRTable]] = defaultdict(list)
        for (schema_name, _table_name), table in sorted(tables.items()):
            schemas[schema_name].append(table)

        provenance = Provenance(
            source_type=SourceType.DDL,
            source_id=str(self.path),
            source_detail="DDL file parser",
            timestamp=datetime.utcnow(),
            build_version=self.version,
        )
        return MIRDatabase(
            name=self.path.stem,
            dialect=DatabaseDialect.DDL_FILE,
            connector_version=self.version,
            schemas=[
                MIRSchema(name=schema_name, tables=sorted(schema_tables, key=lambda t: t.name))
                for schema_name, schema_tables in sorted(schemas.items())
            ],
            provenance=provenance,
        )

    def _parse_create_table(self, create: exp.Create) -> MIRTable:
        schema_expr = create.this
        if not isinstance(schema_expr, exp.Schema):
            raise ValueError(f"CREATE TABLE did not contain a schema expression: {create}")

        table_expr = schema_expr.this
        schema_name, table_name = self._table_parts(table_expr)

        columns: list[MIRColumn] = []
        table_primary_key: MIRPrimaryKey | None = None
        foreign_keys: list[MIRForeignKey] = []
        constraints: list[MIRConstraint] = []

        for ordinal, item in enumerate(schema_expr.expressions or [], start=1):
            if isinstance(item, exp.ColumnDef):
                column, inline_pk, inline_fk, inline_constraints = self._parse_column_def(item, ordinal)
                columns.append(column)
                if inline_pk:
                    table_primary_key = MIRPrimaryKey(columns=[column.name], name=None)
                if inline_fk:
                    foreign_keys.append(inline_fk)
                constraints.extend(inline_constraints)
            else:
                pk, fks, parsed_constraints = self._parse_table_constraint(item)
                if pk:
                    table_primary_key = pk
                foreign_keys.extend(fks)
                constraints.extend(parsed_constraints)

        columns = self._mark_primary_key_columns(columns, table_primary_key)
        columns = self._mark_foreign_key_columns(columns, foreign_keys)

        return MIRTable(
            name=table_name,
            schema_name=schema_name,
            table_type=TableType.TABLE,
            columns=columns,
            primary_key=table_primary_key,
            foreign_keys=foreign_keys,
            constraints=constraints,
            ddl=create.sql(dialect="postgres"),
        )

    def _parse_column_def(
        self,
        column_def: exp.ColumnDef,
        ordinal: int,
    ) -> tuple[MIRColumn, bool, MIRForeignKey | None, list[MIRConstraint]]:
        name = column_def.name
        kind = column_def.args.get("kind")
        raw_type = kind.sql(dialect="postgres") if kind is not None else "UNKNOWN"
        constraints = column_def.args.get("constraints") or []

        is_nullable = True
        is_primary_key = False
        default_value: str | None = None
        inline_fk: MIRForeignKey | None = None
        extra_constraints: list[MIRConstraint] = []

        for constraint in constraints:
            kind_expr = constraint.args.get("kind")
            if isinstance(kind_expr, exp.NotNullColumnConstraint):
                is_nullable = False
                extra_constraints.append(
                    MIRConstraint(
                        name=f"{name}_not_null",
                        type=ConstraintType.NOT_NULL,
                        columns=[name],
                    )
                )
            elif isinstance(kind_expr, exp.PrimaryKeyColumnConstraint):
                is_primary_key = True
            elif isinstance(kind_expr, exp.DefaultColumnConstraint):
                default = kind_expr.this
                default_value = default.sql(dialect="postgres") if default is not None else None
                extra_constraints.append(
                    MIRConstraint(
                        name=f"{name}_default",
                        type=ConstraintType.DEFAULT,
                        columns=[name],
                        expression=default_value,
                    )
                )
            elif isinstance(kind_expr, exp.UniqueColumnConstraint):
                extra_constraints.append(
                    MIRConstraint(
                        name=f"{name}_unique",
                        type=ConstraintType.UNIQUE,
                        columns=[name],
                    )
                )
            elif isinstance(kind_expr, exp.Reference):
                inline_fk = self._reference_to_fk(None, [name], kind_expr)

        max_length, numeric_precision, numeric_scale = self._type_details(kind)
        column = MIRColumn(
            name=name,
            data_type=raw_type,
            normalized_type=normalize_type(raw_type),
            ordinal_position=ordinal,
            is_nullable=is_nullable,
            is_primary_key=is_primary_key,
            is_foreign_key=inline_fk is not None,
            default_value=default_value,
            max_length=max_length,
            numeric_precision=numeric_precision,
            numeric_scale=numeric_scale,
        )
        return column, is_primary_key, inline_fk, extra_constraints

    def _parse_table_constraint(
        self,
        item: exp.Expression,
    ) -> tuple[MIRPrimaryKey | None, list[MIRForeignKey], list[MIRConstraint]]:
        name = self._constraint_name(item)
        expressions = item.args.get("expressions") if isinstance(item, exp.Constraint) else [item]
        primary_key: MIRPrimaryKey | None = None
        foreign_keys: list[MIRForeignKey] = []
        constraints: list[MIRConstraint] = []

        for expression in expressions or []:
            if isinstance(expression, exp.PrimaryKey):
                primary_key = MIRPrimaryKey(columns=self._names(expression.expressions), name=name)
            elif isinstance(expression, exp.ForeignKey):
                reference = expression.args.get("reference")
                if isinstance(reference, exp.Reference):
                    foreign_keys.append(
                        self._reference_to_fk(
                            name,
                            self._names(expression.expressions),
                            reference,
                        )
                    )
            elif isinstance(expression, exp.CheckColumnConstraint):
                constraints.append(
                    MIRConstraint(
                        name=name or "check_constraint",
                        type=ConstraintType.CHECK,
                        expression=expression.this.sql(dialect="postgres") if expression.this else None,
                    )
                )
            elif isinstance(expression, exp.UniqueColumnConstraint):
                constraints.append(
                    MIRConstraint(
                        name=name or "unique_constraint",
                        type=ConstraintType.UNIQUE,
                        columns=self._unique_constraint_columns(expression),
                    )
                )

        return primary_key, foreign_keys, constraints

    def _parse_create_index(self, create: exp.Create) -> tuple[tuple[str, str] | None, MIRIndex | None]:
        index_expr = create.this
        if not isinstance(index_expr, exp.Index):
            return None, None
        table_expr = index_expr.args.get("table")
        if not isinstance(table_expr, exp.Table):
            return None, None

        schema_name, table_name = self._table_parts(table_expr)
        params = index_expr.args.get("params")
        columns: list[str] = []
        if params is not None:
            for column_expr in params.args.get("columns") or []:
                column = column_expr.this if isinstance(column_expr, exp.Ordered) else column_expr
                columns.append(self._expression_name(column))

        return (schema_name, table_name), MIRIndex(
            name=self._expression_name(index_expr.this),
            columns=columns,
            is_unique=bool(create.args.get("unique")),
        )

    def _parse_alter_table(
        self,
        alter: exp.Alter,
    ) -> tuple[tuple[str, str] | None, list[MIRConstraint | MIRForeignKey | MIRPrimaryKey]]:
        if alter.args.get("kind") != "TABLE" or not isinstance(alter.this, exp.Table):
            return None, []

        additions: list[MIRConstraint | MIRForeignKey | MIRPrimaryKey] = []
        for action in alter.args.get("actions") or []:
            for expression in action.args.get("expressions") or []:
                pk, fks, constraints = self._parse_table_constraint(expression)
                additions.extend(fks)
                additions.extend(constraints)
                if pk:
                    additions.append(pk)

        return self._table_parts(alter.this), additions

    def _reference_to_fk(
        self,
        name: str | None,
        columns: list[str],
        reference: exp.Reference,
    ) -> MIRForeignKey:
        ref_schema = reference.this
        if isinstance(ref_schema, exp.Schema):
            schema_name, table_name = self._table_parts(ref_schema.this)
            ref_columns = self._names(ref_schema.expressions)
        else:
            schema_name, table_name = self._table_parts(ref_schema)
            ref_columns = []

        return MIRForeignKey(
            name=name,
            columns=columns,
            referred_schema=schema_name,
            referred_table=table_name,
            referred_columns=ref_columns,
        )

    def _type_details(self, data_type: exp.Expression | None) -> tuple[int | None, int | None, int | None]:
        if data_type is None:
            return None, None, None
        values: list[int] = []
        for param in data_type.args.get("expressions") or []:
            literal = param.this
            if isinstance(literal, exp.Literal) and literal.this.isdigit():
                values.append(int(literal.this))
        if not values:
            return None, None, None
        if normalize_type(data_type.sql(dialect="postgres")) == normalize_type("decimal"):
            return None, values[0], values[1] if len(values) > 1 else None
        return values[0], None, None

    def _table_parts(self, table: exp.Expression | None) -> tuple[str, str]:
        if isinstance(table, exp.Table):
            return table.db or "public", table.name
        if isinstance(table, exp.Schema):
            return self._table_parts(table.this)
        return "public", self._expression_name(table)

    def _constraint_name(self, item: exp.Expression) -> str | None:
        if isinstance(item, exp.Constraint) and item.this is not None:
            return self._expression_name(item.this)
        return None

    def _unique_constraint_columns(self, expression: exp.UniqueColumnConstraint) -> list[str]:
        target = expression.args.get("this")
        if isinstance(target, exp.Schema):
            return self._names(target.expressions)
        return []

    def _names(self, expressions: list[exp.Expression] | None) -> list[str]:
        return [self._expression_name(expression) for expression in expressions or []]

    def _expression_name(self, expression: exp.Expression | None) -> str:
        if expression is None:
            return ""
        if hasattr(expression, "name") and expression.name:
            return expression.name
        if isinstance(expression, exp.Identifier):
            return expression.this
        if isinstance(expression, exp.Column):
            return expression.name
        return expression.sql(dialect="postgres")

    def _mark_primary_key_columns(
        self,
        columns: list[MIRColumn],
        primary_key: MIRPrimaryKey | None,
    ) -> list[MIRColumn]:
        pk_columns = set(primary_key.columns if primary_key else [])
        return [
            column.model_copy(update={"is_primary_key": column.is_primary_key or column.name in pk_columns})
            for column in columns
        ]

    def _mark_foreign_key_columns(
        self,
        columns: list[MIRColumn],
        foreign_keys: list[MIRForeignKey],
    ) -> list[MIRColumn]:
        fk_columns = {column for fk in foreign_keys for column in fk.columns}
        return [
            column.model_copy(update={"is_foreign_key": column.is_foreign_key or column.name in fk_columns})
            for column in columns
        ]
