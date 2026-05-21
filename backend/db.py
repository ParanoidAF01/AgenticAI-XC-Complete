"""
Database connection helper for Azure SQL.
Provides reusable functions to query views and call stored procedures.
"""
import pyodbc
from config.settings import SqlConfig


print(f"[DB] Connected to Azure SQL: {SqlConfig.SERVER}/{SqlConfig.DATABASE}")


# ── Connection ───────────────────────────────────────────────

def get_connection():
    """Get a fresh pyodbc connection to Azure SQL."""
    conn_str = (
        f"DRIVER={{ODBC Driver 18 for SQL Server}};"
        f"SERVER={SqlConfig.SERVER};"
        f"DATABASE={SqlConfig.DATABASE};"
        f"UID={SqlConfig.USERNAME};"
        f"PWD={SqlConfig.PASSWORD};"
        f"Encrypt=yes;"
        f"TrustServerCertificate=no;"
        f"Connection Timeout=30;"
    )
    return pyodbc.connect(conn_str)


# ── Public API ───────────────────────────────────────────────

def query_view(view_name: str, top: int = None) -> list[dict]:
    """Query a SQL view and return rows as list of dicts."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        if top:
            cursor.execute(f"SELECT TOP {int(top)} * FROM {view_name}")
        else:
            cursor.execute(f"SELECT * FROM {view_name}")
        columns = [col[0] for col in cursor.description]
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
        return rows
    finally:
        conn.close()


def call_proc(proc_name: str, params: dict) -> list[list[dict]]:
    """Call a stored procedure and return all result sets as list of list of dicts."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        param_str = ", ".join(f"@{k}=?" for k in params)
        cursor.execute(f"EXEC {proc_name} {param_str}", *params.values())
        result_sets = []
        while True:
            if cursor.description:
                columns = [col[0] for col in cursor.description]
                rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
                result_sets.append(rows)
            if not cursor.nextset():
                break
        return result_sets
    finally:
        conn.close()
