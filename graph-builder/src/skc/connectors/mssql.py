"""Microsoft SQL Server metadata connector backed by SQLAlchemy introspection.

Uses the ``mssql+pyodbc`` or ``mssql+pymssql`` dialect. The connector
inherits the full SQLAlchemy-based extraction logic from
:class:`PostgresConnector` and overrides only the dialect-specific
defaults (ignored system schemas, materialised-view discovery, and the
database name fallback).

Requires one of the following Python drivers:
- ``pymssql``  (simpler, no ODBC driver needed)
- ``pyodbc``   (requires an ODBC driver such as Microsoft ODBC Driver 18)

Install with::

    pip install pymssql          # simpler option
    # or
    pip install pyodbc           # if you already have an ODBC driver
"""

from __future__ import annotations

from skc.connectors.postgres import PostgresConnector
from skc.ir.mir import DatabaseDialect


class MSSQLConnector(PostgresConnector):
    """Extract structural metadata from Microsoft SQL Server using SQLAlchemy.

    Connection string examples::

        mssql+pymssql://sa:password@localhost:1433/mydb
        mssql+pyodbc://sa:password@localhost:1433/mydb?driver=ODBC+Driver+18+for+SQL+Server
        mssql+pyodbc://sa:password@localhost/mydb?driver=FreeTDS&TDS_Version=8.0

    Attributes:
        name: Connector identifier used by the factory.
        dialect: The MIR dialect tag written to extracted metadata.
        ignored_schemas: SQL Server system schemas that are excluded
            from introspection.
    """

    name = "mssql"
    version = "0.1.0"
    dialect = DatabaseDialect.MSSQL
    default_database_name = "mssql"
    ignored_schemas = {
        "information_schema",
        "sys",
        "guest",
        "INFORMATION_SCHEMA",
        "db_owner",
        "db_accessadmin",
        "db_securityadmin",
        "db_ddladmin",
        "db_backupoperator",
        "db_datareader",
        "db_datawriter",
        "db_denydatareader",
        "db_denydatawriter",
    }
    ignored_schema_prefixes: tuple[str, ...] = ()

    def _materialized_view_names(self, inspector, schema_name: str) -> list[str]:
        """SQL Server does not natively support materialised views."""
        return []
