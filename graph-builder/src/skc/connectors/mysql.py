"""MySQL metadata connector backed by SQLAlchemy introspection."""

from __future__ import annotations

from skc.connectors.postgres import PostgresConnector
from skc.ir.mir import DatabaseDialect


class MySQLConnector(PostgresConnector):
    """Extract structural metadata from MySQL using SQLAlchemy."""

    name = "mysql"
    version = "0.1.0"
    dialect = DatabaseDialect.MYSQL
    default_database_name = "mysql"
    ignored_schemas = {"information_schema", "mysql", "performance_schema", "sys"}
    ignored_schema_prefixes: tuple[str, ...] = ()

    def _materialized_view_names(self, inspector, schema_name: str) -> list[str]:
        return []
