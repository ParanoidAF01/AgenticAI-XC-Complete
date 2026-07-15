"""Database connectors — schema extraction from Postgres, MySQL, Snowflake, BigQuery, DDL files."""
"""Metadata connector exports."""

from skc.connectors.base import MetadataConnector, create_connector, normalize_type
from skc.connectors.bigquery import BigQueryConnector
from skc.connectors.ddl_file import DDLFileConnector
from skc.connectors.mysql import MySQLConnector
from skc.connectors.postgres import PostgresConnector
from skc.connectors.snowflake import SnowflakeConnector

__all__ = [
    "BigQueryConnector",
    "DDLFileConnector",
    "MetadataConnector",
    "MySQLConnector",
    "PostgresConnector",
    "SnowflakeConnector",
    "create_connector",
    "normalize_type",
]
