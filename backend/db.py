"""
Database connection helper for Azure SQL.
Provides reusable functions to query views and call stored procedures.

Falls back to mock data when pyodbc/ODBC driver is not available (local dev).
Set USE_MOCK_DB=true in .env to force mock mode.
"""
import os
import json
from datetime import datetime, timedelta
import random

# Try importing pyodbc — fail gracefully for local dev
try:
    import pyodbc
    from config.settings import SqlConfig
    PYODBC_AVAILABLE = True
except (ImportError, Exception):
    PYODBC_AVAILABLE = False

# Force mock mode via env var
USE_MOCK = os.getenv("USE_MOCK_DB", "false").lower() == "true" or not PYODBC_AVAILABLE

if USE_MOCK:
    print("[DB] Running in MOCK mode — returning synthetic data.")
else:
    print(f"[DB] Connected to Azure SQL: {SqlConfig.SERVER}/{SqlConfig.DATABASE}")


# ── Live Azure SQL Functions ─────────────────────────────────

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


def _query_view_live(view_name: str, top: int = None) -> list[dict]:
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


def _call_proc_live(proc_name: str, params: dict) -> list[list[dict]]:
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


# ── Mock Data Functions ──────────────────────────────────────

MOCK_PIPELINES = [
    "pl_ingest_salesforce_daily",
    "pl_transform_finance_reports",
    "pl_load_crm_contacts",
    "pl_sync_inventory_hourly",
    "pl_export_analytics_weekly",
    "pl_ingest_erp_transactions",
    "pl_validate_data_quality",
    "pl_archive_historical_logs",
]

MOCK_ERROR_TYPES = [
    "Parameter Errors",
    "Dataset Type Errors",
    "Credentials Expired",
    "Large Data / Timeout",
    "Server Slow",
    "Subscription Corrupt",
]

MOCK_ACTIONS = ["auto_restart", "escalated", "auto_restart", "auto_restart", "escalated"]
MOCK_STATUSES = ["Succeeded", "Succeeded", "Succeeded", "Failed", "Succeeded", "Cancelled"]


def _mock_dashboard_summary():
    return [{
        "TotalPipelines": len(MOCK_PIPELINES),
        "TotalRunsToday": random.randint(80, 160),
        "FailedRunsToday": random.randint(2, 10),
        "ActiveAlerts": random.randint(0, 5),
        "AvgMTTRMinutes": round(random.uniform(2.0, 8.0), 1),
        "AutoHealRatePct": round(random.uniform(55.0, 75.0), 1),
        "SuccessRatePct": round(random.uniform(88.0, 97.0), 1),
    }]


def _mock_recent_activity(top=20):
    rows = []
    for i in range(min(top, 20)):
        rows.append({
            "PipelineName": random.choice(MOCK_PIPELINES),
            "RunId": f"RUN-{random.randint(1000, 9999)}",
            "Status": random.choice(["Failed", "Cancelled"]),
            "HealerAction": random.choice(MOCK_ACTIONS),
            "ErrorType": random.choice(MOCK_ERROR_TYPES),
            "Timestamp": (datetime.utcnow() - timedelta(hours=random.randint(1, 72))).isoformat(),
            "DurationSeconds": random.randint(10, 600),
        })
    return sorted(rows, key=lambda x: x["Timestamp"], reverse=True)


def _mock_pipeline_list():
    rows = []
    for name in MOCK_PIPELINES:
        total = random.randint(20, 60)
        failures = random.randint(1, 8)
        rows.append({
            "PipelineName": name,
            "LastStatus": random.choice(["Succeeded", "Failed"]),
            "LastRunTime": (datetime.utcnow() - timedelta(hours=random.randint(1, 24))).isoformat(),
            "TotalRuns30d": total,
            "FailureCount30d": failures,
            "SuccessRatePct": round((total - failures) * 100.0 / total, 1),
        })
    return rows


def _mock_pipeline_detail(pipeline_name):
    total = random.randint(25, 60)
    failures = random.randint(2, 10)

    # Result set 1: summary
    summary = [{
        "PipelineName": pipeline_name,
        "TotalRuns": total,
        "TotalFailures": failures,
        "SuccessRatePct": round((total - failures) * 100.0 / total, 1),
        "AvgDurationSeconds": random.randint(30, 300),
    }]

    # Result set 2: error distribution
    dist = []
    for etype in random.sample(MOCK_ERROR_TYPES, min(3, len(MOCK_ERROR_TYPES))):
        dist.append({"ErrorType": etype, "OccurrenceCount": random.randint(1, 5)})

    # Result set 3: error history
    history = []
    for i in range(min(failures, 10)):
        history.append({
            "RunId": f"RUN-{random.randint(1000, 9999)}",
            "ErrorType": random.choice(MOCK_ERROR_TYPES),
            "ErrorMessage": f"Mock error message for {pipeline_name} — simulated failure #{i+1}",
            "HealerAction": random.choice(MOCK_ACTIONS),
            "Timestamp": (datetime.utcnow() - timedelta(days=random.randint(1, 30))).isoformat(),
        })

    return [summary, dist, history]


def _mock_mttr_trend():
    rows = []
    for i in range(30):
        date = datetime.utcnow() - timedelta(days=30 - i)
        rows.append({
            "TrendDate": date.strftime("%Y-%m-%d"),
            "AvgMTTRMinutes": round(random.uniform(2.0, 10.0), 1),
            "ProcessedCount": random.randint(1, 15),
        })
    return rows


def _mock_error_distribution():
    total = 0
    rows = []
    for etype in MOCK_ERROR_TYPES:
        count = random.randint(5, 40)
        total += count
        rows.append({"ErrorType": etype, "OccurrenceCount": count, "Pct": 0})
    for r in rows:
        r["Pct"] = round(r["OccurrenceCount"] * 100.0 / total, 1)
    return rows


def _mock_top_failing():
    rows = []
    for name in random.sample(MOCK_PIPELINES, min(5, len(MOCK_PIPELINES))):
        rows.append({
            "PipelineName": name,
            "FailureCount": random.randint(3, 20),
            "LastFailure": (datetime.utcnow() - timedelta(hours=random.randint(1, 48))).isoformat(),
        })
    return sorted(rows, key=lambda x: x["FailureCount"], reverse=True)


# ── Mock view dispatcher ────────────────────────────────────

MOCK_VIEWS = {
    "vw_DashboardSummary": _mock_dashboard_summary,
    "vw_RecentActivity": _mock_recent_activity,
    "vw_PipelineList": _mock_pipeline_list,
    "vw_MTTRTrend": _mock_mttr_trend,
    "vw_ErrorTypeDistribution": _mock_error_distribution,
    "vw_TopFailingPipelines": _mock_top_failing,
}


# ── Public API ───────────────────────────────────────────────

def query_view(view_name: str, top: int = None) -> list[dict]:
    """Query a SQL view. Falls back to mock data if Azure SQL is unavailable."""
    if USE_MOCK:
        fn = MOCK_VIEWS.get(view_name)
        if fn:
            result = fn() if view_name != "vw_RecentActivity" else fn(top or 20)
            return result[:top] if top else result
        return []
    return _query_view_live(view_name, top)


def call_proc(proc_name: str, params: dict) -> list[list[dict]]:
    """Call a stored procedure. Falls back to mock data if Azure SQL is unavailable."""
    if USE_MOCK:
        if proc_name == "sp_PipelineDetail":
            return _mock_pipeline_detail(params.get("PipelineName", "unknown"))
        return [[]]
    return _call_proc_live(proc_name, params)
