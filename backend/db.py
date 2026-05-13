"""
Database connection helper for Azure SQL.
Provides reusable functions to query views and call stored procedures.

Falls back to mock data when pyodbc/ODBC driver is not available (local dev).
Set USE_MOCK_DB=true in .env to force mock mode.
"""
import os
import json
from datetime import datetime, timedelta, timezone
import random

# IST timezone (UTC+5:30)
IST = timezone(timedelta(hours=5, minutes=30))

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

# Pipeline data for both list and detail views
MOCK_PIPELINE_DATA = [
    {"name": "PL_Template_Quarterly_Error_Credentials", "owner": "Data Platform", "sr": 35.0, "status": "Critical"},
    {"name": "PL_Template_Monthly_Error_Dataset", "owner": "Data Platform", "sr": 42.0, "status": "Critical"},
    {"name": "PL_Template_3_schema", "owner": "Data Platform", "sr": 45.0, "status": "Critical"},
    {"name": "PL_Synapse_DataFlow_Transform", "owner": "Analytics", "sr": 65.0, "status": "Warning"},
    {"name": "PL_Logistics_Realtime", "owner": "Ops", "sr": 75.0, "status": "Warning"},
    {"name": "PL_Template_Monthly_Error_Paramter", "owner": "Data Platform", "sr": 72.0, "status": "Warning"},
    {"name": "PL_WebAPI_LargeDataTransfer", "owner": "Integration", "sr": 78.0, "status": "Warning"},
    {"name": "PL_ProcessCustomerData_AzureFunction", "owner": "Core Services", "sr": 80.5, "status": "Warning"},
    {"name": "PL_Copy_Sales_Data", "owner": "Sales Eng", "sr": 98.0, "status": "Healthy"},
    {"name": "PL_AzureSQL_CopyCustomerData", "owner": "Core Services", "sr": 95.0, "status": "Healthy"},
    {"name": "PL_ERP_Sync", "owner": "Finance IT", "sr": 100.0, "status": "Healthy"},
    {"name": "PL_Finance_Daily", "owner": "Finance IT", "sr": 92.0, "status": "Healthy"},
    {"name": "PL_HR_Systems_Ingest", "owner": "HR Tech", "sr": 99.0, "status": "Healthy"},
    {"name": "PL_Marketing_Analytics", "owner": "Marketing", "sr": 96.0, "status": "Healthy"},
    {"name": "PL_MLScoring_PredictChurn", "owner": "Data Science", "sr": 88.0, "status": "Healthy"},
    {"name": "PL_ADLA_ProcessUSQLScript", "owner": "Analytics", "sr": 91.0, "status": "Healthy"},
    {"name": "PL_Template_Yearly_Schema", "owner": "Data Platform", "sr": 85.0, "status": "Healthy"},
    {"name": "PL_Template_date_config", "owner": "Data Platform", "sr": 90.0, "status": "Healthy"},
    {"name": "pl_ingest_salesforce_daily", "owner": "Sales Eng", "sr": 94.0, "status": "Healthy"},
    {"name": "pl_transform_inventory", "owner": "Supply Chain", "sr": 97.0, "status": "Healthy"},
]

MOCK_ERROR_TYPES = [
    "Type 1 - Parameter Errors",
    "Type 2 - Dataset Type Errors",
    "Type 3 - Credentials Expired",
    "Type 4 - Large Data / Timeout",
    "Type 5 - Server Slow",
    "Type 6 - Subscription Corrupt",
]

MOCK_ACTIONS_DETAIL = ["Success", "Auto-Restarted", "Escalated", "Failed", "Skipped(Duplicate)", "max Retries Reached"]
MOCK_ACTIONS = ["auto_restart", "escalated", "auto_restart", "auto_restart", "escalated"]
MOCK_STATUSES = ["Succeeded", "Succeeded", "Succeeded", "Failed", "Succeeded", "Cancelled"]


def _mock_dashboard_summary():
    return [{
        "TotalPipelines": len(MOCK_PIPELINE_DATA),
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
            "PipelineName": random.choice(MOCK_PIPELINE_DATA)["name"],
            "RunId": f"RUN-{random.randint(1000, 9999)}",
            "Status": random.choice(["Failed", "Cancelled"]),
            "HealerAction": random.choice(MOCK_ACTIONS),
            "ErrorType": random.choice(MOCK_ERROR_TYPES),
            "Timestamp": (datetime.now(IST) - timedelta(hours=random.randint(1, 72))).isoformat(),
            "DurationSeconds": random.randint(10, 600),
        })
    return sorted(rows, key=lambda x: x["Timestamp"], reverse=True)


def _mock_pipeline_list():
    rows = []
    for p in MOCK_PIPELINE_DATA:
        total = random.randint(20, 60)
        failures = random.randint(1, 8)
        rows.append({
            "PipelineName": p["name"],
            "LastStatus": random.choice(["Succeeded", "Failed"]),
            "LastRunTime": (datetime.now(IST) - timedelta(hours=random.randint(1, 24))).isoformat(),
            "TotalRuns30d": total,
            "FailureCount30d": failures,
            "SuccessRatePct": round((total - failures) * 100.0 / total, 1),
        })
    return rows


def _mock_pipelines_page(params):
    """Mock for ui.sp_pipelines_page — returns 2 result sets matching updated SP."""
    search = params.get("Search", "%").replace("%", "").lower()
    status_filter = params.get("Status", "all")
    offset = params.get("Offset", 0)
    rows_count = params.get("Rows", 10)

    all_rows = []
    for p in MOCK_PIPELINE_DATA:
        total = random.randint(30, 200)
        sr = p["sr"]
        org_success = int(total * sr / 100)
        healed = random.randint(0, max(1, int(total * 0.05)))
        failures = total - org_success

        # Generate a last failure date (random recent date)
        days_ago = random.randint(0, 14)
        last_failure_date = (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d")

        all_rows.append({
            "PipelineName": p["name"],
            "Owner": p["owner"],
            "TotalRuns": total,
            "OrgSuccess": org_success,
            "HealedCount": healed,
            "TotalFailures": failures,
            "SuccessRatePc": sr,
            "Status": p["status"],
            "LastFailure": last_failure_date,
        })

    # Compute unfiltered status counts BEFORE applying filters (for RS2)
    status_counts_rs2 = []
    for s in ["Healthy", "Warning", "Critical"]:
        count = len([r for r in all_rows if r["Status"] == s])
        if count > 0:
            status_counts_rs2.append({"Status": s, "StatusCount": count})

    # Apply search filter
    if search:
        all_rows = [r for r in all_rows if search in r["PipelineName"].lower()]

    # Apply status filter
    if status_filter not in ("all", "All"):
        all_rows = [r for r in all_rows if r["Status"] == status_filter]

    # Sort: Critical first, then Warning, then Healthy
    status_order = {"Critical": 1, "Warning": 2, "Healthy": 3}
    all_rows.sort(key=lambda x: (status_order.get(x["Status"], 4), x["SuccessRatePc"]))

    total_pipelines = len(all_rows)
    total_critical = len([r for r in all_rows if r["Status"] == "Critical"])

    # Paginate
    page = all_rows[offset:offset + rows_count]

    # Add window columns (present on every row in the real SP)
    for r in page:
        r["TotalPipelines"] = total_pipelines
        r["TotalCriticalPipelines"] = total_critical

    # Return 2 result sets: RS1 = pipeline rows, RS2 = status counts
    return [page, status_counts_rs2]


def _mock_pipeline_ind(params):
    """Mock for ui.sp_pipeline_ind — returns 3 result sets matching SP columns."""
    pipeline_name = params.get("PipelineName", "unknown")
    offset = params.get("Offset", 0)
    rows_count = params.get("Rows", 10)

    # Find pipeline in mock data or generate
    pdata = None
    for p in MOCK_PIPELINE_DATA:
        if p["name"] == pipeline_name:
            pdata = p
            break
    sr = pdata["sr"] if pdata else random.uniform(50, 95)

    total_errors = random.randint(5, 30)
    most_common_type = random.choice(MOCK_ERROR_TYPES)
    most_common_count = random.randint(int(total_errors * 0.4), total_errors)

    # Result set 1: Summary metrics
    summary = [{
        "SuccessRatePc": sr,
        "TotalErrors": total_errors,
        "MostCommonErrorType": most_common_type,
        "MostCommonErrorTypeCount": most_common_count,
    }]

    # Result set 2: Error type distribution
    dist = []
    remaining = total_errors
    selected_types = random.sample(MOCK_ERROR_TYPES, min(4, len(MOCK_ERROR_TYPES)))
    for i, etype in enumerate(selected_types):
        if i == 0:
            count = most_common_count
        else:
            count = random.randint(1, max(1, remaining - (len(selected_types) - i - 1)))
        remaining -= count
        if remaining < 0:
            count = max(1, count + remaining)
            remaining = 0
        pct = round(count * 100.0 / max(1, total_errors), 1)
        dist.append({
            "HealerErrorType": etype,
            "ErrorCount": count,
            "ErrorPc": pct,
        })
        if remaining <= 0:
            break
    dist.sort(key=lambda x: x["ErrorCount"], reverse=True)

    # Result set 3: Error history (paginated)
    all_history = []
    for i in range(total_errors):
        all_history.append({
            "TriggerTime": (datetime.now(IST) - timedelta(days=random.randint(0, 30), hours=random.randint(0, 23))).isoformat(),
            "PipelineRunId": f"RUN-{random.randint(10000000, 99999999)}",
            "HealerErrorType": random.choice([d["HealerErrorType"] for d in dist]) if dist else "Unknown",
            "ErrorMessage": random.choice([
                f"Azure Key Vault credentials expired for '{pipeline_name}'.",
                f"Connection timeout to SQL DB after 120s in '{pipeline_name}'.",
                f"Schema mismatch: column 'order_date' not found in source dataset.",
                f"Parameter '@startDate' is missing or null in pipeline configuration.",
                f"Data transfer exceeded 10GB limit. Consider partitioning.",
                f"Subscription quota exceeded for resource group.",
            ]),
            "ActionTaken": random.choice(MOCK_ACTIONS_DETAIL),
        })
    all_history.sort(key=lambda x: x["TriggerTime"], reverse=True)
    history_page = all_history[offset:offset + rows_count]

    return [summary, dist, history_page]


def _mock_pipeline_detail_legacy(pipeline_name):
    """Legacy mock for sp_PipelineDetail — kept for backward compat."""
    return _mock_pipeline_ind({"PipelineName": pipeline_name})


def _mock_mttr_trend():
    rows = []
    for i in range(30):
        date = datetime.now(IST) - timedelta(days=30 - i)
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
    for p in random.sample(MOCK_PIPELINE_DATA, min(5, len(MOCK_PIPELINE_DATA))):
        name = p["name"]
        rows.append({
            "PipelineName": name,
            "FailureCount": random.randint(3, 20),
            "LastFailure": (datetime.now(IST) - timedelta(hours=random.randint(1, 48))).isoformat(),
        })
    return sorted(rows, key=lambda x: x["FailureCount"], reverse=True)


# ── Mock view dispatcher ────────────────────────────────────


# ── Dashboard Mock Functions (SP-matched) ────────────────────

def _mock_home_kpi(params):
    """Mock for ui.sp_home_kpi — returns KPI cards with period-over-period deltas."""
    total_failures = random.randint(30, 60)
    auto_healed = int(total_failures * random.uniform(0.6, 0.85))
    escalated = total_failures - auto_healed
    active_pipelines = len(MOCK_PIPELINE_DATA)

    failure_delta = round(random.uniform(-25, 10), 1)
    healed_delta = round(random.uniform(5, 30), 1)
    escalated_delta = round(random.uniform(-15, 15), 1)

    return [[{
        "TotalFailures": total_failures,
        "AutoHealed": auto_healed,
        "Escalated": escalated,
        "ActivePipelines": active_pipelines,
        "FailureDeltaPc": failure_delta,
        "AutoHealedDeltaPc": healed_delta,
        "EscalatedDeltaPc": escalated_delta,
        "FailureDeltaIsGood": 1 if failure_delta <= 0 else 0,
        "AutoHealedDeltaIsGood": 1 if healed_delta >= 0 else 0,
        "EscalatedDeltaIsGood": 1 if escalated_delta <= 0 else 0,
    }]]


def _mock_home_failure_trend(params):
    """Mock for ui.sp_home_failure_trend — returns time-bucketed failure counts."""
    time_filter = params.get("TimeFilter", "DEFAULT")

    data = []
    if time_filter == "TODAY":
        # Hourly buckets 0-23
        for hour in range(24):
            data.append({
                "TimeBucket": hour,
                "FailureCount": random.randint(0, 5),
            })
    elif time_filter == "4M":
        # Weekly buckets for 4 months (~17 weeks)
        base = datetime.now(IST) - timedelta(days=120)
        for w in range(17):
            week_start = base + timedelta(weeks=w)
            data.append({
                "TimeBucket": week_start.strftime("%Y-%m-%d"),
                "FailureCount": random.randint(1, 15),
            })
    else:
        # Daily buckets for 1w/15d/1m
        days_map = {"1w": 7, "15d": 15, "1m": 30}
        # Infer days from params if possible
        num_days = 30
        base = datetime.now(IST) - timedelta(days=num_days)
        for d in range(num_days):
            day = base + timedelta(days=d)
            data.append({
                "TimeBucket": day.strftime("%Y-%m-%d"),
                "FailureCount": random.randint(0, 8),
            })

    return [data]


def _mock_home_svf(params):
    """Mock for ui.sp_home_SvF — returns success vs failure donut data."""
    total_runs = random.randint(400, 800)
    health_pc = round(random.uniform(88, 97), 1)
    success = int(total_runs * health_pc / 100)
    failures = total_runs - success

    return [[{
        "Success": success,
        "Failures": failures,
        "TotalRuns": total_runs,
        "HealthPc": health_pc,
    }]]


def _mock_home_errorbreak(params):
    """Mock for ui.sp_home_errorbreak — returns error type breakdown."""
    breakdown = []
    counts = sorted([random.randint(3, 30) for _ in MOCK_ERROR_TYPES], reverse=True)
    for i, etype in enumerate(MOCK_ERROR_TYPES):
        breakdown.append({
            "HealerErrorType": etype,
            "TotalErrors": counts[i],
        })
    return [breakdown]


def _mock_home_recent_activity(params):
    """Mock for ui.sp_home_recent_activity — returns 5 recent activity items."""
    statuses = ["Success", "Healed", "Escalated", "Skipped", "Max Retries Exhausted"]
    error_types_for_status = {
        "Healed": "Type 4 - Large Data / Timeout",
        "Escalated": "Type 3 - Credentials Expired",
        "Failed": "Type 1 - Parameter Errors",
        "Success": None,
        "Skipped": "Type 1 - Parameter Errors",
        "Processing Error": "Type 2 - Dataset Type Errors",
        "Max Retries Exhausted": "Type 5 - Server Slow",
    }
    error_descriptions = {
        "Type 4 - Large Data / Timeout": "Timeout Error detected",
        "Type 3 - Credentials Expired": "Credential Mismatch",
        "Type 1 - Parameter Errors": "Missing Parameter",
        "Type 2 - Dataset Type Errors": "Dataset Access Denied",
        "Type 5 - Server Slow": "Server response slow",
        None: None,
    }

    activities = []
    for i in range(5):
        status = statuses[i % len(statuses)]
        etype = error_types_for_status.get(status, random.choice(MOCK_ERROR_TYPES))
        activities.append({
            "PipelineName": random.choice(MOCK_PIPELINE_DATA)["name"],
            "PipelineRunId": f"RUN-{random.randint(10000000, 99999999)}",
            "TriggerTime": (datetime.now(IST) - timedelta(hours=i, minutes=random.randint(0, 59))).isoformat(),
            "HealerErrorType": etype,
            "Status": status,
        })

    return [activities]


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
        # Pipeline SPs
        if proc_name == "ui.sp_pipelines_page":
            return _mock_pipelines_page(params)
        if proc_name == "ui.sp_pipeline_ind":
            return _mock_pipeline_ind(params)
        if proc_name == "sp_PipelineDetail":
            return _mock_pipeline_detail_legacy(params.get("PipelineName", "unknown"))
        # Dashboard SPs
        if proc_name == "ui.sp_home_kpi":
            return _mock_home_kpi(params)
        if proc_name == "ui.sp_home_failure_trend":
            return _mock_home_failure_trend(params)
        if proc_name == "ui.sp_home_SvF":
            return _mock_home_svf(params)
        if proc_name == "ui.sp_home_errorbreak":
            return _mock_home_errorbreak(params)
        if proc_name == "ui.sp_home_recent_activity":
            return _mock_home_recent_activity(params)
        if proc_name == "ui.sp_pipeline_chart":
            return _mock_pipeline_chart(params)
        # Report SPs
        if proc_name == "ui.sp_report_mttr":
            return _mock_report_mttr(params)
        if proc_name == "ui.sp_report_autoheal":
            return _mock_report_autoheal(params)
        if proc_name == "ui.sp_report_time_saved":
            return _mock_report_time_saved(params)
        if proc_name == "ui.sp_report_errors_kpi":
            return _mock_report_errors_kpi(params)
        if proc_name == "ui.sp_report_heatmap":
            return _mock_report_heatmap(params)
        if proc_name == "ui.sp_report_pipeline_breakdown":
            return _mock_report_pipeline_breakdown(params)
        if proc_name == "ui.sp_report_errorstype":
            return _mock_report_errorstype(params)
        if proc_name == "ui.sp_report_restart_exh":
            return _mock_report_restart_exh(params)
        return [[]]
    return _call_proc_live(proc_name, params)


def _mock_pipeline_chart(params):
    """Mock for ui.sp_pipeline_chart — per-pipeline failure timeline (same format as dashboard trend)."""
    time_filter = params.get("TimeFilter", "DEFAULT")
    pipeline_name = params.get("PipelineName", "Unknown")

    data = []
    if time_filter == "TODAY":
        for hour in range(24):
            data.append({
                "TimeBucket": hour,
                "FailureCount": random.randint(0, 3),
            })
    elif time_filter == "4M":
        base = datetime.now(IST) - timedelta(days=120)
        for w in range(17):
            week_start = base + timedelta(weeks=w)
            data.append({
                "TimeBucket": week_start.strftime("%Y-%m-%d"),
                "FailureCount": random.randint(0, 6),
            })
    else:
        num_days = 30
        base = datetime.now(IST) - timedelta(days=num_days)
        for d in range(num_days):
            day = base + timedelta(days=d)
            data.append({
                "TimeBucket": day.strftime("%Y-%m-%d"),
                "FailureCount": random.randint(0, 4),
            })

    return [data]


# ── Report SP Mocks ──────────────────────────────────────────

def _mock_report_mttr(params):
    """Mock for ui.sp_report_mttr → returns MTTR in seconds."""
    return [[{"MTTR": random.uniform(180, 360)}]]  # 3–6 minutes in seconds


def _mock_report_autoheal(params):
    """Mock for ui.sp_report_autoheal → returns AutoHealRate as %."""
    return [[{"AutoHealRate": round(random.uniform(60, 85), 1)}]]


def _mock_report_time_saved(params):
    """Mock for ui.sp_report_time_saved → returns MinsSaved."""
    return [[{"MinsSaved": random.randint(400, 900)}]]  # ~7–15 hrs


def _mock_report_errors_kpi(params):
    """Mock for ui.sp_report_errors_kpi → returns TotalErrors count."""
    return [[{"TotalErrors": random.randint(25, 70)}]]


def _mock_report_heatmap(params):
    """Mock for ui.sp_report_heatmap → returns TimeBucket × HealerErrorType × ErrorCount."""
    time_filter = params.get("TimeFilter", "1M")

    error_types = [
        "Type 1 - Connection Timeout",
        "Type 2 - Schema Drift",
        "Type 3 - Credentials Expired",
        "Type 4 - Data Format Mismatch",
        "Type 5 - API Rate Limit",
        "Type 6 - Resource Unavailable",
    ]

    data = []
    if time_filter == "TODAY":
        buckets = list(range(24))
    elif time_filter == "1W":
        buckets = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    elif time_filter == "4M":
        base = datetime.now(IST) - timedelta(days=120)
        buckets = [(base + timedelta(weeks=w)).strftime("%Y-%m-%d") for w in range(17)]
    else:
        num_days = 15 if time_filter == "15D" else 30
        base = datetime.now(IST) - timedelta(days=num_days)
        buckets = [(base + timedelta(days=d)).strftime("%Y-%m-%d") for d in range(num_days)]

    for tb in buckets:
        for et in error_types:
            count = random.choices([0, 0, 0, 1, 2, 3, 5], weights=[40, 20, 10, 15, 8, 5, 2])[0]
            if count > 0:
                data.append({
                    "TimeBucket": str(tb),
                    "HealerErrorType": et,
                    "ErrorCount": count,
                })

    return [data]


def _mock_report_pipeline_breakdown(params):
    """Mock for ui.sp_report_pipeline_breakdown → TOP 5 pipelines by error count."""
    pipelines = [
        {"PipelineName": "PL_Ingest_Salesforce_Daily", "ErrorCount": random.randint(12, 22)},
        {"PipelineName": "PL_Transform_ERP_Finance", "ErrorCount": random.randint(8, 15)},
        {"PipelineName": "PL_Export_Analytics_DW", "ErrorCount": random.randint(5, 10)},
        {"PipelineName": "PL_Sync_User_Profiles", "ErrorCount": random.randint(3, 7)},
        {"PipelineName": "PL_Cleanup_Temp_Blobs", "ErrorCount": random.randint(1, 5)},
    ]
    return [pipelines]


def _mock_report_errorstype(params):
    """Mock for ui.sp_report_errorstype → root causes ranked by count."""
    causes = [
        {"HealerErrorType": "Type 3 - Credentials Expired", "ErrorCount": random.randint(10, 18), "AffectedPipelines": 3},
        {"HealerErrorType": "Type 1 - Connection Timeout", "ErrorCount": random.randint(6, 12), "AffectedPipelines": 1},
        {"HealerErrorType": "Type 4 - Data Format Mismatch", "ErrorCount": random.randint(4, 8), "AffectedPipelines": 2},
        {"HealerErrorType": "Type 5 - API Rate Limit", "ErrorCount": random.randint(2, 6), "AffectedPipelines": 1},
    ]
    return [causes]


def _mock_report_restart_exh(params):
    """Mock for ui.sp_report_restart_exh → pipelines that exhausted retries."""
    now = datetime.now(IST)
    exhaustions = [
        {
            "PipelineName": "PL_Ingest_Salesforce_Daily",
            "PipelineRunId": "RUN-" + "".join(random.choices("ABCDEF0123456789", k=8)),
            "HealerErrorType": "Type 5 - API Rate Limit",
            "TriggerTime": (now - timedelta(hours=random.randint(2, 24))).strftime("%Y-%m-%d %H:%M:%S"),
            "MaxRetryAttempt": 3,
            "Status": "Need Manual Fix",
        },
        {
            "PipelineName": "PL_Transform_ERP_Finance",
            "PipelineRunId": "RUN-" + "".join(random.choices("ABCDEF0123456789", k=8)),
            "HealerErrorType": "Type 2 - Schema Drift",
            "TriggerTime": (now - timedelta(hours=random.randint(5, 48))).strftime("%Y-%m-%d %H:%M:%S"),
            "MaxRetryAttempt": 3,
            "Status": "Need Manual Fix",
        },
        {
            "PipelineName": "PL_Sync_User_Profiles",
            "PipelineRunId": "RUN-" + "".join(random.choices("ABCDEF0123456789", k=8)),
            "HealerErrorType": "Type 3 - Credentials Expired",
            "TriggerTime": (now - timedelta(hours=random.randint(1, 12))).strftime("%Y-%m-%d %H:%M:%S"),
            "MaxRetryAttempt": 3,
            "Status": "Need Manual Fix",
        },
    ]
    return [exhaustions]
