"""Metadata connector contract and shared helpers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from skc.config import ConnectorConfig
from skc.ir.mir import MIRDatabase
from skc.ir.common import NormalizedType


class MetadataConnector(ABC):
    """Abstract base class for metadata extraction connectors."""

    name: str = ""
    version: str = "0.1.0"

    def __init__(self, config: ConnectorConfig) -> None:
        self.config = config

    @abstractmethod
    def connect(self) -> None:
        """Initialize any resources needed by this connector."""

    @abstractmethod
    def extract_metadata(self) -> MIRDatabase:
        """Extract source metadata into a MIR database."""

    @abstractmethod
    def close(self) -> None:
        """Release connector resources."""

    def __enter__(self) -> MetadataConnector:
        self.connect()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()


def normalize_type(raw_type: str) -> NormalizedType:
    """Map a raw database type string to a dialect-agnostic type."""
    lower = raw_type.lower()

    if any(token in lower for token in ("char", "text", "string", "varchar", "uuid")):
        if "uuid" in lower:
            return NormalizedType.UUID
        return NormalizedType.STRING
    if any(token in lower for token in ("bigint", "smallint", "integer", "int", "serial")):
        return NormalizedType.INTEGER
    if any(token in lower for token in ("numeric", "decimal", "number", "money")):
        return NormalizedType.DECIMAL
    if any(token in lower for token in ("float", "double", "real")):
        return NormalizedType.FLOAT
    if "bool" in lower:
        return NormalizedType.BOOLEAN
    if "timestamp" in lower or "datetime" in lower:
        return NormalizedType.TIMESTAMP
    if lower == "date" or lower.endswith(" date"):
        return NormalizedType.DATE
    if lower == "time" or lower.startswith("time "):
        return NormalizedType.TIME
    if any(token in lower for token in ("json", "variant")):
        return NormalizedType.JSON
    if "array" in lower:
        return NormalizedType.ARRAY
    if any(token in lower for token in ("blob", "binary", "bytea")):
        return NormalizedType.BINARY
    return NormalizedType.UNKNOWN


def create_connector(config: ConnectorConfig) -> MetadataConnector:
    """Instantiate a metadata connector from configuration."""
    connector_type = config.type.lower()
    if connector_type == "ddl_file":
        from skc.connectors.ddl_file import DDLFileConnector

        return DDLFileConnector(config)
    if connector_type == "postgres":
        from skc.connectors.postgres import PostgresConnector

        return PostgresConnector(config)
    if connector_type == "mysql":
        from skc.connectors.mysql import MySQLConnector

        return MySQLConnector(config)
    if connector_type == "snowflake":
        from skc.connectors.snowflake import SnowflakeConnector

        return SnowflakeConnector(config)
    if connector_type == "bigquery":
        from skc.connectors.bigquery import BigQueryConnector

        return BigQueryConnector(config)
    if connector_type == "mssql":
        from skc.connectors.mssql import MSSQLConnector

        return MSSQLConnector(config)

    raise ValueError(f"Unsupported connector type: {config.type}")


def resolve_path(path: str | Path) -> Path:
    """Resolve a user supplied path without requiring it to exist."""
    return Path(path).expanduser().resolve()
