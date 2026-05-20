"""
Dashboard API routes — 5 endpoints powered by stored procedures.

GET /api/dashboard/kpi               — KPI cards (Total Failures, Auto-Healed, Escalated, Active Pipelines + deltas)
GET /api/dashboard/failure-trend     — Failure trend line chart data (time-bucketed)
GET /api/dashboard/success-vs-failure — Donut chart: success vs failure counts + health %
GET /api/dashboard/error-breakdown   — Error type breakdown horizontal bar chart
GET /api/dashboard/recent-activity   — Recent 5 activity items with status badges
"""
from fastapi import APIRouter, Query
from typing import Optional
from datetime import datetime, timedelta, timezone
from backend.db import call_proc

# IST timezone (UTC+5:30)
IST = timezone(timedelta(hours=5, minutes=30))

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])

TABLE_NAME = "sql.PipelineRunLog"

# ── Date Range Helpers ──────────────────────────────────────

TIME_RANGE_DAYS = {
    "today": 0,
    "1w": 7,
    "15d": 15,
    "1m": 30,
    "4m": 120,
}


def _compute_date_ranges(time_range: str):
    """
    Compute current and previous date ranges from a time range key.
    
    For '1m' (1 month):
      current:  last 30 days → today
      previous: 60 days ago → 30 days ago  (the period before current, same length)
    
    Returns: (curr_start, curr_end, prev_start, prev_end) as ISO strings.
    """
    now = datetime.now(IST)
    key = time_range.lower()
    days = TIME_RANGE_DAYS.get(key, 30)

    if key == "today":
        curr_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        curr_end = now
        # Previous = yesterday
        prev_start = curr_start - timedelta(days=1)
        prev_end = curr_start - timedelta(seconds=1)
    else:
        curr_start = now - timedelta(days=days)
        curr_end = now
        prev_start = curr_start - timedelta(days=days)
        prev_end = curr_start - timedelta(seconds=1)

    fmt = "%Y-%m-%dT%H:%M:%S"
    return (
        curr_start.strftime(fmt),
        curr_end.strftime(fmt),
        prev_start.strftime(fmt),
        prev_end.strftime(fmt),
    )


def _compute_simple_range(time_range: str):
    """Compute a single (start, end) range for SPs that don't need comparison."""
    now = datetime.now(IST)
    key = time_range.lower()
    days = TIME_RANGE_DAYS.get(key, 30)

    if key == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        start = now - timedelta(days=days)

    fmt = "%Y-%m-%dT%H:%M:%S"
    return start.strftime(fmt), now.strftime(fmt)


# ── Endpoint 1: KPI Cards ──────────────────────────────────

@router.get("/kpi")
def get_kpi(
    time_range: str = Query("1m", description="Time range: today, 1w, 15d, 1m, 4m"),
    start_date: Optional[str] = Query(None, description="Override: custom start date ISO"),
    end_date: Optional[str] = Query(None, description="Override: custom end date ISO"),
):
    """
    4 KPI cards + period-over-period delta percentages.

    Calls: EXEC ui.sp_home_kpi @TableName, @CurrStartDate, @CurrEndDate, @PrevStartDate, @PrevEndDate

    Returns: TotalFailures, AutoHealed, Escalated, ActivePipelines,
             FailureDeltaPc, AutoHealedDeltaPc, EscalatedDeltaPc,
             *DeltaIsGood (boolean flags for green/red arrows)
    """
    cs, ce, ps, pe = _compute_date_ranges(time_range)
    if start_date:
        cs = start_date
    if end_date:
        ce = end_date

    result_sets = call_proc("ui.sp_home_kpi", {
        "TableName": TABLE_NAME,
        "CurrStartDate": cs,
        "CurrEndDate": ce,
        "PrevStartDate": ps,
        "PrevEndDate": pe,
    })

    if not result_sets or not result_sets[0]:
        return {
            "total_failures": 0, "auto_healed": 0, "escalated": 0, "active_pipelines": 0,
            "failure_delta_pc": None, "auto_healed_delta_pc": None, "escalated_delta_pc": None,
            "failure_delta_is_good": True, "auto_healed_delta_is_good": True, "escalated_delta_is_good": True,
        }

    row = result_sets[0][0]
    return {
        "total_failures": row.get("TotalFailures", 0),
        "auto_healed": row.get("AutoHealed", 0),
        "escalated": row.get("Escalated", 0),
        "active_pipelines": row.get("ActivePipelines", 0),
        "failure_delta_pc": _safe_float(row.get("FailureDeltaPc")),
        "auto_healed_delta_pc": _safe_float(row.get("AutoHealedDeltaPc")),
        "escalated_delta_pc": _safe_float(row.get("EscalatedDeltaPc")),
        "failure_delta_is_good": bool(row.get("FailureDeltaIsGood", 1)),
        "auto_healed_delta_is_good": bool(row.get("AutoHealedDeltaIsGood", 1)),
        "escalated_delta_is_good": bool(row.get("EscalatedDeltaIsGood", 1)),
    }


# ── Endpoint 2: Failure Trend Chart ────────────────────────

@router.get("/failure-trend")
def get_failure_trend(
    time_range: str = Query("1m", description="Time range: today, 1w, 15d, 1m, 4m"),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
):
    """
    Failure trend line chart data. Time bucketing depends on range:
      - today  → hourly buckets
      - 4m     → weekly buckets
      - others → daily buckets

    Calls: EXEC ui.sp_home_failure_trend @TableName, @TimeFilter, @StartDate, @EndDate
    """
    sd, ed = _compute_simple_range(time_range)
    if start_date:
        sd = start_date
    if end_date:
        ed = end_date

    # Map time_range to SP's @TimeFilter param
    time_filter = "TODAY" if time_range.lower() == "today" else ("4M" if time_range.lower() == "4m" else "DEFAULT")

    result_sets = call_proc("ui.sp_home_failure_trend", {
        "TableName": TABLE_NAME,
        "TimeFilter": time_filter,
        "StartDate": sd,
        "EndDate": ed,
    })

    if not result_sets or not result_sets[0]:
        return {"data": [], "time_filter": time_filter}

    data = []
    for r in result_sets[0]:
        data.append({
            "time_bucket": str(r.get("TimeBucket", "")),
            "failure_count": r.get("FailureCount", 0),
        })

    return {"data": data, "time_filter": time_filter}


# ── Endpoint 3: Success vs Failure Donut ───────────────────

@router.get("/success-vs-failure")
def get_success_vs_failure(
    time_range: str = Query("1m", description="Time range: today, 1w, 15d, 1m, 4m"),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
):
    """
    Success vs Failure donut chart.

    Calls: EXEC ui.sp_home_SvF @TableName, @StartDate, @EndDate

    Returns: success count, failure count, total runs, health percentage.
    """
    sd, ed = _compute_simple_range(time_range)
    if start_date:
        sd = start_date
    if end_date:
        ed = end_date

    result_sets = call_proc("ui.sp_home_SvF", {
        "TableName": TABLE_NAME,
        "StartDate": sd,
        "EndDate": ed,
    })

    if not result_sets or not result_sets[0]:
        return {"success": 0, "failures": 0, "total_runs": 0, "health_pc": 0.0}

    row = result_sets[0][0]
    return {
        "success": row.get("Success", 0),
        "failures": row.get("Failures", 0),
        "total_runs": row.get("TotalRuns", 0),
        "health_pc": _safe_float(row.get("HealthPc", 0)),
    }


# ── Endpoint 4: Error Type Breakdown ──────────────────────

@router.get("/error-breakdown")
def get_error_breakdown(
    time_range: str = Query("1m", description="Time range: today, 1w, 15d, 1m, 4m"),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
):
    """
    Error type breakdown horizontal bar chart data.

    Calls: EXEC ui.sp_home_errorbreak @TableName, @StartDate, @EndDate

    Returns list of {error_type, count} sorted by count desc.
    """
    sd, ed = _compute_simple_range(time_range)
    if start_date:
        sd = start_date
    if end_date:
        ed = end_date

    result_sets = call_proc("ui.sp_home_errorbreak", {
        "TableName": TABLE_NAME,
        "StartDate": sd,
        "EndDate": ed,
    })

    if not result_sets or not result_sets[0]:
        return {"breakdown": []}

    # Build raw list
    breakdown = []
    for r in result_sets[0]:
        breakdown.append({
            "error_type": r.get("HealerErrorType", "Unknown"),
            "count": r.get("TotalErrors", 0),
        })

    # Compute bar_pc: each bar's width relative to the max count
    max_count = max((b["count"] for b in breakdown), default=1) or 1
    for b in breakdown:
        b["bar_pc"] = round(b["count"] * 100.0 / max_count, 1)

    return {"breakdown": breakdown}


# ── Endpoint 5: Recent Activity Feed ─────────────────────

@router.get("/recent-activity")
def get_recent_activity(
    time_range: str = Query("1m", description="Time range: today, 1w, 15d, 1m, 4m"),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
):
    """
    Recent activity feed (latest 5 items).

    Calls: EXEC ui.sp_home_recent_activity @TableName, @StartDate, @EndDate

    Each item has: pipeline name, run ID, trigger time, error type (nullable), status badge.
    Status values: Success, Healed, Escalated, Failed, Skipped, Processing Error, Max Retries Exhausted
    """
    sd, ed = _compute_simple_range(time_range)
    if start_date:
        sd = start_date
    if end_date:
        ed = end_date

    result_sets = call_proc("ui.sp_home_recent_activity", {
        "TableName": TABLE_NAME,
        "StartDate": sd,
        "EndDate": ed,
    })

    if not result_sets or not result_sets[0]:
        return {"activities": []}

    activities = []
    for r in result_sets[0]:
        activities.append({
            "pipeline_name": r.get("PipelineName", ""),
            "run_id": r.get("PipelineRunId", ""),
            "timestamp": str(r.get("TriggerTime", "")),
            "error_type": r.get("HealerErrorType", None),
            "status": r.get("Status", "Unknown"),
        })

    return {"activities": activities}


# ── Helpers ──────────────────────────────────────────────

def _safe_float(val):
    """Safely convert a value to float, returning None if null."""
    if val is None:
        return None
    try:
        return round(float(val), 1)
    except (ValueError, TypeError):
        return None
