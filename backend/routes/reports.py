"""
Reports & Analytics API routes.
GET /api/reports/mttr-trend          — Daily average MTTR over time
GET /api/reports/error-distribution  — Error type counts with percentages
GET /api/reports/top-failing         — Pipelines ranked by failure count
"""
from fastapi import APIRouter, Query
from backend.db import query_view

router = APIRouter(prefix="/api/reports", tags=["Reports"])


@router.get("/mttr-trend")
def get_mttr_trend(days: int = Query(30, ge=7, le=90)):
    """Return daily average MTTR trend."""
    rows = query_view("vw_MTTRTrend")
    # Filter to requested day range (view returns up to 90 days)
    result = [
        {
            "date": str(r.get("TrendDate", "")),
            "avg_mttr_minutes": round(float(r.get("AvgMTTRMinutes", 0) or 0), 1),
            "processed_count": r.get("ProcessedCount", 0),
        }
        for r in rows
    ]
    # Return only the last N days
    return result[-days:] if len(result) > days else result


@router.get("/error-distribution")
def get_error_distribution():
    """Return error type distribution with counts and percentages."""
    rows = query_view("vw_ErrorTypeDistribution")
    return [
        {
            "error_type": r.get("ErrorType", "Unclassified"),
            "count": r.get("OccurrenceCount", 0),
            "pct": round(float(r.get("Pct", 0) or 0), 1),
        }
        for r in rows
    ]


@router.get("/top-failing")
def get_top_failing(limit: int = Query(10, ge=1, le=20)):
    """Return pipelines ranked by failure count in the last 30 days."""
    rows = query_view("vw_TopFailingPipelines", top=limit)
    return [
        {
            "pipeline_name": r.get("PipelineName", ""),
            "failure_count": r.get("FailureCount", 0),
            "last_failure": str(r.get("LastFailure", "")),
        }
        for r in rows
    ]
