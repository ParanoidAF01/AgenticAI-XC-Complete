"""
Pipeline API routes.
GET /api/pipelines            — List all pipelines with 30-day stats
GET /api/pipelines/{name}     — Detail view for a specific pipeline
"""
from fastapi import APIRouter, Path, HTTPException
from backend.db import query_view, call_proc

router = APIRouter(prefix="/api/pipelines", tags=["Pipelines"])


@router.get("")
def get_pipelines():
    """Return all pipelines with 30-day run stats."""
    rows = query_view("vw_PipelineList")
    return [
        {
            "pipeline_name": r.get("PipelineName", ""),
            "last_status": r.get("LastStatus", ""),
            "last_run_time": str(r.get("LastRunTime", "")),
            "total_runs_30d": r.get("TotalRuns30d", 0),
            "failure_count_30d": r.get("FailureCount30d", 0),
            "success_rate_pct": round(float(r.get("SuccessRatePct", 0) or 0), 1),
        }
        for r in rows
    ]


@router.get("/{pipeline_name}")
def get_pipeline_detail(pipeline_name: str = Path(..., description="Pipeline name")):
    """Return detail view for a specific pipeline: summary, error distribution, error history."""
    result_sets = call_proc("sp_PipelineDetail", {"PipelineName": pipeline_name})

    if not result_sets or not result_sets[0]:
        raise HTTPException(status_code=404, detail=f"Pipeline '{pipeline_name}' not found.")

    # Result set 0: Summary stats
    summary = result_sets[0][0]

    # Result set 1: Error type distribution
    error_distribution = []
    if len(result_sets) > 1:
        error_distribution = [
            {
                "error_type": r.get("ErrorType", "Unclassified"),
                "count": r.get("OccurrenceCount", 0),
            }
            for r in result_sets[1]
        ]

    # Result set 2: Error history
    error_history = []
    if len(result_sets) > 2:
        error_history = [
            {
                "run_id": r.get("RunId", ""),
                "error_type": r.get("ErrorType", "Unclassified"),
                "error_message": r.get("ErrorMessage", ""),
                "healer_action": r.get("HealerAction", "pending"),
                "timestamp": str(r.get("Timestamp", "")),
            }
            for r in result_sets[2]
        ]

    return {
        "pipeline_name": summary.get("PipelineName", pipeline_name),
        "total_runs": summary.get("TotalRuns", 0),
        "total_failures": summary.get("TotalFailures", 0),
        "success_rate_pct": round(float(summary.get("SuccessRatePct", 0) or 0), 1),
        "avg_duration_seconds": summary.get("AvgDurationSeconds", 0),
        "error_type_distribution": error_distribution,
        "error_history": error_history,
    }
