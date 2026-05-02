"""
Dashboard API routes.
GET /api/dashboard/summary     — KPI summary (MTTR, auto-heal rate, etc.)
GET /api/dashboard/recent-activity — Recent processed errors
"""
from fastapi import APIRouter, Query
from backend.db import query_view

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])


@router.get("/summary")
def get_dashboard_summary():
    """Return dashboard KPIs: total pipelines, runs today, MTTR, auto-heal rate, success rate."""
    rows = query_view("vw_DashboardSummary")
    if not rows:
        return {
            "total_pipelines": 0,
            "total_runs_today": 0,
            "failed_runs_today": 0,
            "active_alerts": 0,
            "mttr_minutes": 0.0,
            "auto_heal_rate_pct": 0.0,
            "success_rate_pct": 0.0,
        }
    row = rows[0]
    return {
        "total_pipelines": row.get("TotalPipelines", 0),
        "total_runs_today": row.get("TotalRunsToday", 0),
        "failed_runs_today": row.get("FailedRunsToday", 0),
        "active_alerts": row.get("ActiveAlerts", 0),
        "mttr_minutes": round(float(row.get("AvgMTTRMinutes", 0) or 0), 1),
        "auto_heal_rate_pct": round(float(row.get("AutoHealRatePct", 0) or 0), 1),
        "success_rate_pct": round(float(row.get("SuccessRatePct", 0) or 0), 1),
    }


@router.get("/recent-activity")
def get_recent_activity(limit: int = Query(20, ge=1, le=50)):
    """Return recent processed/failed pipeline runs."""
    rows = query_view("vw_RecentActivity", top=limit)
    return [
        {
            "pipeline_name": r.get("PipelineName", ""),
            "run_id": r.get("RunId", ""),
            "status": r.get("Status", ""),
            "healer_action": r.get("HealerAction", "pending"),
            "error_type": r.get("ErrorType", ""),
            "timestamp": str(r.get("Timestamp", "")),
            "duration_seconds": r.get("DurationSeconds", 0),
        }
        for r in rows
    ]
