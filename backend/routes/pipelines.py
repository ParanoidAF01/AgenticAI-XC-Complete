"""
Pipeline API routes.
GET  /api/pipelines                          — List all pipelines with stats, search, filters, pagination
GET  /api/pipelines/{pipeline_name}          — Detail view: summary metrics, error distribution, error history
GET  /api/pipelines/{pipeline_name}/chart    — Failure timeline line chart data
GET  /api/pipelines/{pipeline_name}/reports  — List generated PDF reports
GET  /api/reports/download/{pipeline}/{file} — Download a PDF report
"""
import os
from fastapi import APIRouter, Path, Query, HTTPException
from fastapi.responses import FileResponse
from typing import Optional
from datetime import datetime, timedelta, timezone
from backend.db import call_proc
from backend.report_storage import get_reports

# IST timezone (UTC+5:30)
IST = timezone(timedelta(hours=5, minutes=30))

router = APIRouter(prefix="/api/pipelines", tags=["Pipelines"])

# The PipelineRunLog table — hardcoded, never exposed to frontend
TABLE_NAME = "dbo.PipelineRunLog"


def _default_start_date() -> str:
    """Default to 7 days ago."""
    return (datetime.now(IST) - timedelta(days=7)).strftime("%Y-%m-%dT00:00:00")


def _default_end_date() -> str:
    """Default to now."""
    return datetime.now(IST).strftime("%Y-%m-%dT23:59:59")


@router.get("")
def get_pipelines(
    start_date: Optional[str] = Query(None, description="ISO date string e.g. 2026-01-01T00:00:00"),
    end_date: Optional[str] = Query(None, description="ISO date string e.g. 2026-12-31T23:59:59"),
    search: Optional[str] = Query(None, description="Search pipeline name (partial match)"),
    status: Optional[str] = Query("all", description="Filter: all, Healthy, Warning, Critical"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    rows: int = Query(10, ge=1, le=100, description="Page size"),
):
    """
    List all pipelines with computed stats.

    Calls: EXEC ui.sp_pipelines_page @TableName, @StartDate, @EndDate, @Search, @Status, @Offset, @Rows

    Returns per pipeline: name, owner, total runs, org success, healed count,
    total failures, success rate %, health status (Healthy/Warning/Critical).
    Also returns total pipeline count and critical pipeline count for the alert banner.
    """
    # Build SP parameters
    sd = start_date or _default_start_date()
    ed = end_date or _default_end_date()
    search_param = f"%{search}%" if search else "%"
    # Normalize status (frontend sends 'healthy', backend SP expects 'Healthy')
    s_norm = status.title() if status else "All"
    status_param = s_norm if s_norm in ("All", "Healthy", "Warning", "Critical") else "All"

    result_sets = call_proc("ui.sp_pipelines_page", {
        "TableName": TABLE_NAME,
        "StartDate": sd,
        "EndDate": ed,
        "Search": search_param,
        "Status": status_param,
        "Offset": offset,
        "Rows": rows,
    })

    if not result_sets or not result_sets[0]:
        return {
            "pipelines": [],
            "total_pipelines": 0,
            "total_critical_pipelines": 0,
            "filter_counts": {"all": 0, "healthy": 0, "warning": 0, "critical": 0},
        }

    # Parse result rows
    pipeline_rows = result_sets[0]

    # TotalPipelines and TotalCriticalPipelines are window columns on every row
    total_pipelines = pipeline_rows[0].get("TotalPipelines", 0) if pipeline_rows else 0
    total_critical = pipeline_rows[0].get("TotalCriticalPipelines", 0) if pipeline_rows else 0

    pipelines = []
    for r in pipeline_rows:
        pipelines.append({
            "pipeline_name": r.get("PipelineName", ""),
            "owner": r.get("Owner", ""),
            "total_runs": r.get("TotalRuns", 0),
            "org_success": r.get("OrgSuccess", 0),
            "healed_count": r.get("HealedCount", 0),
            "total_failures": r.get("TotalFailures", 0),
            "success_rate_pc": float(r.get("SuccessRatePc", 0) or 0),
            "status": r.get("Status", "Healthy"),
        })

    # Compute per-status pill counts (always unfiltered)
    # If current request is already unfiltered, use these rows directly
    if status_param == "all":
        all_count = total_pipelines
        healthy_count = sum(1 for r in pipeline_rows if r.get("Status") == "Healthy")
        warning_count = sum(1 for r in pipeline_rows if r.get("Status") == "Warning")
        critical_count = total_critical
        # Adjust if paginated (counts may not cover all rows)
        # Use TotalPipelines window column which covers everything
        if total_pipelines > len(pipeline_rows):
            # Need a separate unfiltered call for accurate per-status counts
            all_sets = call_proc("ui.sp_pipelines_page", {
                "TableName": TABLE_NAME, "StartDate": sd, "EndDate": ed,
                "Search": search_param, "Status": "all", "Offset": 0, "Rows": 255,
            })
            if all_sets and all_sets[0]:
                all_rows = all_sets[0]
                all_count = all_rows[0].get("TotalPipelines", 0) if all_rows else 0
                healthy_count = sum(1 for r in all_rows if r.get("Status") == "Healthy")
                warning_count = sum(1 for r in all_rows if r.get("Status") == "Warning")
                critical_count = sum(1 for r in all_rows if r.get("Status") == "Critical")
    else:
        # Filtered request — fetch unfiltered counts separately
        all_sets = call_proc("ui.sp_pipelines_page", {
            "TableName": TABLE_NAME, "StartDate": sd, "EndDate": ed,
            "Search": search_param, "Status": "all", "Offset": 0, "Rows": 255,
        })
        if all_sets and all_sets[0]:
            all_rows = all_sets[0]
            all_count = all_rows[0].get("TotalPipelines", 0) if all_rows else 0
            healthy_count = sum(1 for r in all_rows if r.get("Status") == "Healthy")
            warning_count = sum(1 for r in all_rows if r.get("Status") == "Warning")
            critical_count = sum(1 for r in all_rows if r.get("Status") == "Critical")
        else:
            all_count = total_pipelines
            healthy_count = 0
            warning_count = 0
            critical_count = total_critical

    return {
        "pipelines": pipelines,
        "total_pipelines": total_pipelines,
        "total_critical_pipelines": total_critical,
        "filter_counts": {
            "all": all_count,
            "healthy": healthy_count,
            "warning": warning_count,
            "critical": critical_count,
        },
    }


@router.get("/{pipeline_name}")
def get_pipeline_detail(
    pipeline_name: str = Path(..., description="Pipeline name"),
    start_date: Optional[str] = Query(None, description="ISO date string"),
    end_date: Optional[str] = Query(None, description="ISO date string"),
    offset: int = Query(0, ge=0, description="Error history pagination offset"),
    rows: int = Query(10, ge=1, le=100, description="Error history page size"),
):
    """
    Detail view for a specific pipeline.

    Calls: EXEC ui.sp_pipeline_ind @TableName, @PipelineName, @StartDate, @EndDate, @Offset, @Rows

    Returns 3 result sets:
      1. Summary metrics: success rate, total errors, most common error type
      2. Error type distribution: type, count, percentage
      3. Error history: timestamp, run ID, error type, message, action taken (paginated)
    """
    sd = start_date or _default_start_date()
    ed = end_date or _default_end_date()

    result_sets = call_proc("ui.sp_pipeline_ind", {
        "TableName": TABLE_NAME,
        "PipelineName": pipeline_name,
        "StartDate": sd,
        "EndDate": ed,
        "Offset": offset,
        "Rows": rows,
    })

    if not result_sets or not result_sets[0]:
        raise HTTPException(status_code=404, detail=f"Pipeline '{pipeline_name}' not found or no data in the selected date range.")

    # Result set 1: Summary metrics
    summary_row = result_sets[0][0] if result_sets[0] else {}
    summary = {
        "success_rate_pc": float(summary_row.get("SuccessRatePc", 0) or 0),
        "total_errors": summary_row.get("TotalErrors", 0),
        "most_common_error_type": summary_row.get("MostCommonErrorType", None),
        "most_common_error_type_count": summary_row.get("MostCommonErrorTypeCount", 0),
    }

    # Result set 2: Error type distribution
    error_distribution = []
    if len(result_sets) > 1:
        for r in result_sets[1]:
            error_distribution.append({
                "error_type": r.get("HealerErrorType", "Unknown"),
                "count": r.get("ErrorCount", 0),
                "percentage": float(r.get("ErrorPc", 0) or 0),
            })

    # Result set 3: Error history (paginated)
    error_history = []
    if len(result_sets) > 2:
        for r in result_sets[2]:
            error_history.append({
                "timestamp": str(r.get("TriggerTime", "")),
                "run_id": r.get("PipelineRunId", ""),
                "error_type": r.get("HealerErrorType", ""),
                "error_message": r.get("ErrorMessage", ""),
                "action_taken": r.get("ActionTaken", "Failed"),
            })

    # Derive criticality badge from success rate (same thresholds as SP)
    sr = summary["success_rate_pc"]
    if sr < 50:
        criticality = "Critical"
    elif sr < 80:
        criticality = "Warning"
    else:
        criticality = "Healthy"

    # Fetch owner from the list SP (same source as pipelines page)
    owner = ""
    owner_sets = call_proc("ui.sp_pipelines_page", {
        "TableName": TABLE_NAME,
        "StartDate": sd,
        "EndDate": ed,
        "Search": pipeline_name,
        "Status": "all",
        "Offset": 0,
        "Rows": 1,
    })
    if owner_sets and owner_sets[0]:
        owner = owner_sets[0][0].get("Owner", "")

    # Compute success rate delta vs previous period
    from datetime import datetime as dt
    try:
        sd_dt = dt.fromisoformat(sd)
        ed_dt = dt.fromisoformat(ed)
    except ValueError:
        sd_dt = dt.strptime(sd, "%Y-%m-%dT%H:%M:%S")
        ed_dt = dt.strptime(ed, "%Y-%m-%dT%H:%M:%S")
    period_duration = ed_dt - sd_dt
    prev_sd = (sd_dt - period_duration).strftime("%Y-%m-%dT%H:%M:%S")
    prev_ed = sd_dt.strftime("%Y-%m-%dT%H:%M:%S")

    prev_result = call_proc("ui.sp_pipeline_ind", {
        "TableName": TABLE_NAME,
        "PipelineName": pipeline_name,
        "StartDate": prev_sd,
        "EndDate": prev_ed,
        "Offset": 0,
        "Rows": 1,
    })
    prev_sr = 0.0
    if prev_result and prev_result[0]:
        prev_sr = float(prev_result[0][0].get("SuccessRatePc", 0) or 0)

    # Delta: current - previous (absolute points, not percentage-of-percentage)
    sr_delta = round(sr - prev_sr, 1)
    sr_direction = "up" if sr_delta > 0 else ("down" if sr_delta < 0 else "neutral")
    sr_delta_is_good = sr_direction == "up"  # higher success rate = better

    return {
        "pipeline_name": pipeline_name,
        "owner": owner,
        "criticality": criticality,
        "summary": {
            **summary,
            "success_rate_delta": abs(sr_delta),
            "success_rate_direction": sr_direction,
            "success_rate_delta_is_good": sr_delta_is_good,
        },
        "error_distribution": error_distribution,
        "error_history": error_history,
    }


# ── Endpoint 3: Pipeline Failure Timeline Chart ─────────

@router.get("/{pipeline_name}/chart")
def get_pipeline_chart(
    pipeline_name: str = Path(..., description="Pipeline name"),
    time_range: str = Query("1m", description="Time range: today, 1w, 15d, 1m, 4m"),
    start_date: Optional[str] = Query(None, description="Override: custom start date ISO"),
    end_date: Optional[str] = Query(None, description="Override: custom end date ISO"),
):
    """
    Failure timeline line chart for a specific pipeline.
    Same format as GET /api/dashboard/failure-trend but scoped to one pipeline.

    Calls: EXEC ui.sp_pipeline_chart @TableName, @PipelineName, @TimeFilter, @StartDate, @EndDate

    Time bucketing:
      - today  → hourly (0-23)
      - 4m     → weekly
      - others → daily
    """
    TIME_RANGE_DAYS = {"today": 0, "1w": 7, "15d": 15, "1m": 30, "4m": 120}
    now = datetime.now(IST)
    key = time_range.lower()
    days = TIME_RANGE_DAYS.get(key, 30)

    if key == "today":
        sd = now.replace(hour=0, minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M:%S")
    else:
        sd = (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
    ed = now.strftime("%Y-%m-%dT%H:%M:%S")

    if start_date:
        sd = start_date
    if end_date:
        ed = end_date

    time_filter = "TODAY" if key == "today" else ("4M" if key == "4m" else "DEFAULT")

    result_sets = call_proc("ui.sp_pipeline_chart", {
        "TableName": TABLE_NAME,
        "PipelineName": pipeline_name,
        "TimeFilter": time_filter,
        "StartDate": sd,
        "EndDate": ed,
    })

    if not result_sets or not result_sets[0]:
        return {"data": [], "time_filter": time_filter, "pipeline_name": pipeline_name}

    data = []
    for r in result_sets[0]:
        data.append({
            "time_bucket": str(r.get("TimeBucket", "")),
            "failure_count": r.get("FailureCount", 0),
        })

    return {"data": data, "time_filter": time_filter, "pipeline_name": pipeline_name}


# ── Endpoint 4: Pipeline PDF Reports ────────────────────

@router.get("/{pipeline_name}/reports")
def get_pipeline_reports(
    pipeline_name: str = Path(..., description="Pipeline name"),
):
    """
    List all generated PDF error reports for a specific pipeline.
    Reads from Azure SQL (ui.PipelineReports), falls back to local JSON registry.
    """
    reports = get_reports(pipeline_name)
    return {
        "reports": reports,
        "total": len(reports),
        "pipeline_name": pipeline_name,
    }


# ── Standalone report download (local fallback) ─────────

reports_router = APIRouter(prefix="/api/reports", tags=["Reports"])


@reports_router.get("/download/{pipeline_name}/{filename}")
def download_report(
    pipeline_name: str = Path(..., description="Pipeline name"),
    filename: str = Path(..., description="PDF filename"),
):
    """
    Download a locally-stored PDF report.
    Only used when Azure Blob Storage is unavailable (dev/local mode).
    In production, the frontend uses the SAS URL from the reports list.
    """
    docs_dir = os.path.join(os.path.dirname(__file__), "..", "..", "docs")
    filepath = os.path.join(docs_dir, pipeline_name, filename)

    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail=f"Report '{filename}' not found.")

    return FileResponse(
        path=filepath,
        media_type="application/pdf",
        filename=filename,
    )
