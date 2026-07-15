"""Snowflake metadata connector backed by SQLAlchemy introspection."""

from __future__ import annotations

from skc.connectors.postgres import PostgresConnector
from skc.ir.mir import DatabaseDialect


class SnowflakeConnector(PostgresConnector):
    """Extract structural metadata from Snowflake using SQLAlchemy."""

    name = "snowflake"
    version = "0.1.0"
    dialect = DatabaseDialect.SNOWFLAKE
    default_database_name = "snowflake"
    ignored_schemas = {"information_schema"}
    ignored_schema_prefixes: tuple[str, ...] = ()

    def _materialized_view_names(self, inspector, schema_name: str) -> list[str]:
        return []
