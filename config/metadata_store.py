"""
Pipeline Metadata Store (SQLite).
Stores information about all ADF pipelines — who owns them, what they do, etc.
This helps the LLM generate better error documents.
"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "pipeline_metadata.db")


def init_db():
    """Create the metadata tables if they don't exist."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Pipeline metadata table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pipelines (
            pipeline_name TEXT PRIMARY KEY,
            description TEXT,
            owner_name TEXT,
            owner_email TEXT,
            schedule TEXT,
            criticality TEXT DEFAULT 'medium',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Error history table (for tracking patterns)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS error_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pipeline_name TEXT,
            run_id TEXT,
            error_type INTEGER,
            error_type_name TEXT,
            error_message TEXT,
            action_taken TEXT,
            resolved BOOLEAN DEFAULT FALSE,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (pipeline_name) REFERENCES pipelines(pipeline_name)
        )
    """)

    # Migration: add error_type_name column if it doesn't exist (for existing DBs)
    try:
        cursor.execute("ALTER TABLE error_history ADD COLUMN error_type_name TEXT")
    except sqlite3.OperationalError:
        pass  # Column already exists

    conn.commit()
    conn.close()
    print("[OK] Database initialized successfully.")


def add_pipeline(name, description, owner_name, owner_email, schedule="manual", criticality="medium"):
    """Add a pipeline to the metadata store."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO pipelines VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
        (name, description, owner_name, owner_email, schedule, criticality)
    )
    conn.commit()
    conn.close()


def get_pipeline(name):
    """Get metadata for a specific pipeline."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM pipelines WHERE pipeline_name = ?", (name,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_pipelines():
    """Get all pipelines from the metadata store."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM pipelines")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def log_error(pipeline_name, run_id, error_type, error_message, action_taken, error_type_name=""):
    """Log an error occurrence to history."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO error_history (pipeline_name, run_id, error_type, error_type_name, error_message, action_taken) VALUES (?, ?, ?, ?, ?, ?)",
        (pipeline_name, run_id, error_type, error_type_name, error_message, action_taken)
    )
    conn.commit()
    conn.close()


def get_error_history(pipeline_name=None, limit=20):
    """Get recent error history, optionally filtered by pipeline."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    if pipeline_name:
        cursor.execute(
            "SELECT * FROM error_history WHERE pipeline_name = ? ORDER BY timestamp DESC LIMIT ?",
            (pipeline_name, limit)
        )
    else:
        cursor.execute("SELECT * FROM error_history ORDER BY timestamp DESC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


# Auto-initialize when imported
init_db()
