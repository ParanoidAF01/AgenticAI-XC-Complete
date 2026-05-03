"""
Reports & Analytics API routes.

GET  /api/reports/kpi                    — 4 KPI cards (MTTR, Auto-Heal Rate, Time Saved, Total Errors)
GET  /api/reports/heatmap                — Error Type Heatmap (time_bucket × error_type matrix)
GET  /api/reports/error-prone-pipelines  — Top 5 most error-prone pipelines
GET  /api/reports/top-root-causes        — Top root causes with affected pipeline count
GET  /api/reports/restart-exhaustion     — Pipelines that exhausted all retry attempts
GET  /api/reports/export/csv             — Download full report as CSV
GET  /api/reports/export/pdf             — Download full report as PDF
"""
import io
import csv
import re
from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from typing import Optional
from datetime import datetime, timedelta, timezone
from backend.db import call_proc

# IST timezone (UTC+5:30)
IST = timezone(timedelta(hours=5, minutes=30))

router = APIRouter(prefix="/api/reports", tags=["Reports"])

TABLE_NAME = "dbo.PipelineRunLog"


# ── Helpers ─────────────────────────────────────────────────

TIME_RANGE_DAYS = {"today": 0, "1w": 7, "15d": 15, "1m": 30, "4m": 120}


def _resolve_dates(time_range: str, start_date: Optional[str], end_date: Optional[str]):
    """Compute (start_date, end_date) from time_range or overrides."""
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
    return sd, ed


def _time_filter_param(time_range: str) -> str:
    """Map time_range key to the @TimeFilter value the heatmap SP expects."""
    key = time_range.lower()
    mapping = {"today": "TODAY", "1w": "1W", "15d": "15D", "1m": "1M", "4m": "4M"}
    return mapping.get(key, "1M")


# ── Endpoint 1: KPI Cards ──────────────────────────────────

@router.get("/kpi")
def get_report_kpis(
    time_range: str = Query("1m", description="Time range: today, 1w, 15d, 1m, 4m"),
    start_date: Optional[str] = Query(None, description="Override: custom start date ISO"),
    end_date: Optional[str] = Query(None, description="Override: custom end date ISO"),
):
    """
    Returns 4 KPI cards for the Reports page:
      1. MTTR (Mean Time To Resolution) in minutes
      2. Auto-Heal Rate (%) — how many failures were auto-resolved
      3. Estimated Time Saved (hours)
      4. Total Errors count

    Each KPI includes a delta_pc comparing current vs previous period.
    """
    sd, ed = _resolve_dates(time_range, start_date, end_date)
    base_params = {"TableName": TABLE_NAME, "StartDate": sd, "EndDate": ed}

    # Calculate previous period dates (same duration, shifted back)
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
    prev_params = {"TableName": TABLE_NAME, "StartDate": prev_sd, "EndDate": prev_ed}

    def _calc_delta(current, previous):
        """Calculate percentage change. Returns (delta_pc, direction)."""
        if previous == 0:
            return (0.0, "neutral")
        delta = round(((current - previous) / abs(previous)) * 100, 1)
        direction = "up" if delta > 0 else ("down" if delta < 0 else "neutral")
        return (abs(delta), direction)

    # 1. MTTR (current + previous)
    mttr_result = call_proc("ui.sp_report_mttr", base_params)
    mttr_seconds = float(mttr_result[0][0].get("MTTR", 0) or 0) if mttr_result and mttr_result[0] else 0
    mttr_minutes = round(mttr_seconds / 60, 1) if mttr_seconds else 0

    prev_mttr_result = call_proc("ui.sp_report_mttr", prev_params)
    prev_mttr_seconds = float(prev_mttr_result[0][0].get("MTTR", 0) or 0) if prev_mttr_result and prev_mttr_result[0] else 0
    prev_mttr_minutes = round(prev_mttr_seconds / 60, 1) if prev_mttr_seconds else 0
    mttr_delta, mttr_dir = _calc_delta(mttr_minutes, prev_mttr_minutes)

    # 2. Auto-Heal Rate (current + previous)
    autoheal_result = call_proc("ui.sp_report_autoheal", base_params)
    autoheal_rate = float(autoheal_result[0][0].get("AutoHealRate", 0) or 0) if autoheal_result and autoheal_result[0] else 0

    prev_autoheal_result = call_proc("ui.sp_report_autoheal", prev_params)
    prev_autoheal_rate = float(prev_autoheal_result[0][0].get("AutoHealRate", 0) or 0) if prev_autoheal_result and prev_autoheal_result[0] else 0
    autoheal_delta, autoheal_dir = _calc_delta(autoheal_rate, prev_autoheal_rate)

    # 3. Time Saved (current + previous)
    time_saved_result = call_proc("ui.sp_report_time_saved", base_params)
    mins_saved = int(time_saved_result[0][0].get("MinsSaved", 0) or 0) if time_saved_result and time_saved_result[0] else 0
    hours_saved = round(mins_saved / 60, 1)

    prev_time_result = call_proc("ui.sp_report_time_saved", prev_params)
    prev_mins = int(prev_time_result[0][0].get("MinsSaved", 0) or 0) if prev_time_result and prev_time_result[0] else 0
    prev_hours = round(prev_mins / 60, 1)
    time_delta, time_dir = _calc_delta(hours_saved, prev_hours)

    # 4. Total Errors (current + previous)
    errors_result = call_proc("ui.sp_report_errors_kpi", base_params)
    total_errors = int(errors_result[0][0].get("TotalErrors", 0) or 0) if errors_result and errors_result[0] else 0

    prev_errors_result = call_proc("ui.sp_report_errors_kpi", prev_params)
    prev_errors = int(prev_errors_result[0][0].get("TotalErrors", 0) or 0) if prev_errors_result and prev_errors_result[0] else 0
    errors_delta, errors_dir = _calc_delta(total_errors, prev_errors)

    return {
        "mttr": {
            "value": mttr_minutes, "unit": "min", "label": "MTTR",
            "delta_pc": mttr_delta, "direction": mttr_dir,
            "delta_is_good": mttr_dir == "down",  # lower MTTR = better
        },
        "autoheal_rate": {
            "value": autoheal_rate, "unit": "%", "label": "Auto-Heal Rate",
            "delta_pc": autoheal_delta, "direction": autoheal_dir,
            "delta_is_good": autoheal_dir == "up",  # higher rate = better
        },
        "time_saved": {
            "value": hours_saved, "unit": "hrs", "label": "Estimated Savings",
            "delta_pc": time_delta, "direction": time_dir,
            "delta_is_good": time_dir == "up",  # more savings = better
        },
        "total_errors": {
            "value": total_errors, "unit": "", "label": "Total Errors",
            "delta_pc": errors_delta, "direction": errors_dir,
            "delta_is_good": errors_dir == "down",  # fewer errors = better
        },
    }


# ── Endpoint 2: Error Type Heatmap ─────────────────────────

@router.get("/heatmap")
def get_error_heatmap(
    time_range: str = Query("1m", description="Time range: today, 1w, 15d, 1m, 4m"),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
):
    """
    Error Type Heatmap — a 2D grid of (time_bucket × error_type → count).

    Calls: EXEC ui.sp_report_heatmap @TableName, @TimeFilter, @StartDate, @EndDate

    Returns a structured matrix:
      - rows: time buckets (hours/days/weeks depending on time range)
      - columns: error types
      - cells: error counts (0 for no errors)
    """
    sd, ed = _resolve_dates(time_range, start_date, end_date)
    tf = _time_filter_param(time_range)

    result_sets = call_proc("ui.sp_report_heatmap", {
        "TableName": TABLE_NAME,
        "TimeFilter": tf,
        "StartDate": sd,
        "EndDate": ed,
    })

    if not result_sets or not result_sets[0]:
        return {"cells": [], "time_buckets": [], "error_types": [], "time_filter": tf}

    # Raw rows: {TimeBucket, HealerErrorType, ErrorCount}
    raw = result_sets[0]

    # Collect unique axes
    time_buckets = list(dict.fromkeys(str(r.get("TimeBucket", "")) for r in raw))
    error_types = list(dict.fromkeys(r.get("HealerErrorType", "") for r in raw))

    # Build lookup
    lookup = {}
    for r in raw:
        key = (str(r.get("TimeBucket", "")), r.get("HealerErrorType", ""))
        lookup[key] = r.get("ErrorCount", 0)

    # Build matrix rows
    matrix = []
    for tb in time_buckets:
        row = {"time_bucket": tb}
        for et in error_types:
            row[et] = lookup.get((tb, et), 0)
        matrix.append(row)

    # Also return flat cells for simpler frontend rendering
    cells = [
        {
            "time_bucket": str(r.get("TimeBucket", "")),
            "error_type": r.get("HealerErrorType", ""),
            "count": r.get("ErrorCount", 0),
        }
        for r in raw
    ]

    return {
        "cells": cells,
        "matrix": matrix,
        "time_buckets": time_buckets,
        "error_types": error_types,
        "time_filter": tf,
    }


# ── Endpoint 3: Most Error-Prone Pipelines ─────────────────

@router.get("/error-prone-pipelines")
def get_error_prone_pipelines(
    time_range: str = Query("1m", description="Time range"),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
):
    """
    Top 5 most error-prone pipelines (bar chart).

    Calls: EXEC ui.sp_report_pipeline_breakdown @TableName, @StartDate, @EndDate
    Returns: PipelineName, ErrorCount + bar_pc for frontend CSS width binding.
    """
    sd, ed = _resolve_dates(time_range, start_date, end_date)

    result_sets = call_proc("ui.sp_report_pipeline_breakdown", {
        "TableName": TABLE_NAME,
        "StartDate": sd,
        "EndDate": ed,
    })

    if not result_sets or not result_sets[0]:
        return {"pipelines": []}

    pipelines = []
    for r in result_sets[0]:
        pipelines.append({
            "pipeline_name": r.get("PipelineName", ""),
            "error_count": r.get("ErrorCount", 0),
        })

    # Compute bar_pc (relative to max)
    max_count = max((p["error_count"] for p in pipelines), default=1) or 1
    for p in pipelines:
        p["bar_pc"] = round(p["error_count"] * 100.0 / max_count, 1)

    return {"pipelines": pipelines}


# ── Endpoint 4: Top Root Causes ─────────────────────────────

@router.get("/top-root-causes")
def get_top_root_causes(
    time_range: str = Query("1m", description="Time range"),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
):
    """
    Top root causes ranked by occurrence count, with affected pipeline count.

    Calls: EXEC ui.sp_report_errorstype @TableName, @StartDate, @EndDate
    Returns: HealerErrorType, ErrorCount, AffectedPipelines
    """
    sd, ed = _resolve_dates(time_range, start_date, end_date)

    result_sets = call_proc("ui.sp_report_errorstype", {
        "TableName": TABLE_NAME,
        "StartDate": sd,
        "EndDate": ed,
    })

    if not result_sets or not result_sets[0]:
        return {"causes": []}

    causes = []
    for i, r in enumerate(result_sets[0], 1):
        causes.append({
            "rank": i,
            "error_type": r.get("HealerErrorType", "Unknown"),
            "occurrences": r.get("ErrorCount", 0),
            "affected_pipelines": r.get("AffectedPipelines", 0),
        })

    return {"causes": causes}


# ── Endpoint 5: Restart Exhaustion Report ───────────────────

@router.get("/restart-exhaustion")
def get_restart_exhaustion(
    time_range: str = Query("1m", description="Time range"),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
):
    """
    Pipelines that exhausted all retry attempts and need manual intervention.

    Calls: EXEC ui.sp_report_restart_exh @TableName, @StartDate, @EndDate
    Returns: PipelineName, RunId, ErrorType, MaxRetryAttempt, Status
    """
    sd, ed = _resolve_dates(time_range, start_date, end_date)

    result_sets = call_proc("ui.sp_report_restart_exh", {
        "TableName": TABLE_NAME,
        "StartDate": sd,
        "EndDate": ed,
    })

    if not result_sets or not result_sets[0]:
        return {"exhaustions": []}

    exhaustions = []
    for r in result_sets[0]:
        exhaustions.append({
            "pipeline_name": r.get("PipelineName", ""),
            "run_id": r.get("PipelineRunId", ""),
            "error_type": r.get("HealerErrorType", ""),
            "trigger_time": str(r.get("TriggerTime", "")),
            "max_retry_attempt": r.get("MaxRetryAttempt", 0),
            "status": r.get("Status", "Needs Manual Fix"),
        })

    return {"exhaustions": exhaustions}


# ── Export Helpers ──────────────────────────────────────────

def _fetch_all_report_data(sd, ed, time_range):
    """Fetch all report data for export (reuses the same SP calls)."""
    base = {"TableName": TABLE_NAME, "StartDate": sd, "EndDate": ed}

    # KPIs
    mttr_r = call_proc("ui.sp_report_mttr", base)
    mttr_sec = float(mttr_r[0][0].get("MTTR", 0) or 0) if mttr_r and mttr_r[0] else 0
    mttr_min = round(mttr_sec / 60, 1)

    ah_r = call_proc("ui.sp_report_autoheal", base)
    ah_rate = float(ah_r[0][0].get("AutoHealRate", 0) or 0) if ah_r and ah_r[0] else 0

    ts_r = call_proc("ui.sp_report_time_saved", base)
    mins = int(ts_r[0][0].get("MinsSaved", 0) or 0) if ts_r and ts_r[0] else 0
    hrs = round(mins / 60, 1)

    err_r = call_proc("ui.sp_report_errors_kpi", base)
    total_err = int(err_r[0][0].get("TotalErrors", 0) or 0) if err_r and err_r[0] else 0

    kpis = {"MTTR (min)": mttr_min, "Auto-Heal Rate (%)": ah_rate,
            "Time Saved (hrs)": hrs, "Total Errors": total_err}

    # Error-prone pipelines
    pb_r = call_proc("ui.sp_report_pipeline_breakdown", base)
    pipelines = []
    if pb_r and pb_r[0]:
        for r in pb_r[0]:
            pipelines.append({"Pipeline": r.get("PipelineName", ""), "Error Count": r.get("ErrorCount", 0)})

    # Root causes
    rc_r = call_proc("ui.sp_report_errorstype", base)
    causes = []
    if rc_r and rc_r[0]:
        for r in rc_r[0]:
            causes.append({
                "Error Type": r.get("HealerErrorType", ""),
                "Occurrences": r.get("ErrorCount", 0),
                "Affected Pipelines": r.get("AffectedPipelines", 0),
            })

    # Restart exhaustion
    re_r = call_proc("ui.sp_report_restart_exh", base)
    exhaustions = []
    if re_r and re_r[0]:
        for r in re_r[0]:
            exhaustions.append({
                "Pipeline": r.get("PipelineName", ""),
                "Run ID": r.get("PipelineRunId", ""),
                "Error Type": r.get("HealerErrorType", ""),
                "Trigger Time": str(r.get("TriggerTime", "")),
                "Retries": r.get("MaxRetryAttempt", 0),
                "Status": r.get("Status", ""),
            })

    return kpis, pipelines, causes, exhaustions


# ── Endpoint 6: Export CSV ───────────────────────────────

@router.get("/export/csv")
def export_csv(
    time_range: str = Query("1m"),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
):
    """
    Generate a full CSV report with all sections.
    Returns a downloadable CSV file.
    """
    sd, ed = _resolve_dates(time_range, start_date, end_date)
    kpis, pipelines, causes, exhaustions = _fetch_all_report_data(sd, ed, time_range)

    now = datetime.now(IST)
    output = io.StringIO()
    writer = csv.writer(output)

    # Header
    writer.writerow(["ADF Healer - Reports & Analytics"])
    writer.writerow([f"Generated: {now.strftime('%Y-%m-%d %H:%M IST')}"])
    writer.writerow([f"Period: {sd} to {ed}"])
    writer.writerow([])

    # Section 1: KPIs
    writer.writerow(["=== KEY METRICS ==="])
    writer.writerow(["Metric", "Value"])
    for k, v in kpis.items():
        writer.writerow([k, v])
    writer.writerow([])

    # Section 2: Error-Prone Pipelines
    writer.writerow(["=== MOST ERROR-PRONE PIPELINES ==="])
    if pipelines:
        writer.writerow(pipelines[0].keys())
        for p in pipelines:
            writer.writerow(p.values())
    writer.writerow([])

    # Section 3: Root Causes
    writer.writerow(["=== TOP ROOT CAUSES ==="])
    if causes:
        writer.writerow(causes[0].keys())
        for c in causes:
            writer.writerow(c.values())
    writer.writerow([])

    # Section 4: Restart Exhaustion
    writer.writerow(["=== RESTART EXHAUSTION REPORT ==="])
    if exhaustions:
        writer.writerow(exhaustions[0].keys())
        for e in exhaustions:
            writer.writerow(e.values())

    output.seek(0)
    filename = f"ADF_Healer_Report_{now.strftime('%Y%m%d_%H%M')}.csv"

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Endpoint 7: Export PDF ───────────────────────────────

@router.get("/export/pdf")
def export_pdf(
    time_range: str = Query("1m"),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
):
    """
    Generate a professional PDF report with all sections.
    Returns a downloadable PDF file.
    """
    from fpdf import FPDF

    sd, ed = _resolve_dates(time_range, start_date, end_date)
    kpis, pipelines, causes, exhaustions = _fetch_all_report_data(sd, ed, time_range)

    now = datetime.now(IST)

    class ReportPDF(FPDF):
        def header(self):
            # Gold banner
            self.set_fill_color(245, 197, 24)  # #f5c518
            self.rect(0, 0, 210, 22, 'F')
            self.set_font('Helvetica', 'B', 16)
            self.set_text_color(26, 28, 28)
            self.set_y(5)
            self.cell(0, 12, 'ADF Healer - Reports & Analytics', align='C')

            # Sub-header
            self.set_fill_color(50, 50, 50)
            self.rect(0, 22, 210, 8, 'F')
            self.set_font('Helvetica', '', 8)
            self.set_text_color(255, 255, 255)
            self.set_y(23)
            self.cell(0, 6,
                      f'Period: {sd}  to  {ed}  |  Generated: {now.strftime("%Y-%m-%d %H:%M IST")}',
                      align='C')
            self.ln(15)

        def footer(self):
            self.set_y(-15)
            self.set_font('Helvetica', 'I', 8)
            self.set_text_color(128, 128, 128)
            self.cell(0, 10, f'ADF Healer  |  Page {self.page_no()}/{{nb}}', align='C')

        def section_title(self, title):
            self.set_font('Helvetica', 'B', 13)
            self.set_text_color(116, 91, 0)  # #745b00 primary
            self.set_fill_color(255, 224, 139)  # #ffe08b
            self.cell(0, 9, f'  {title}', ln=True, fill=True)
            self.ln(3)

        def kpi_row(self, label, value):
            self.set_font('Helvetica', '', 11)
            self.set_text_color(40, 40, 40)
            self.cell(90, 7, label)
            self.set_font('Helvetica', 'B', 11)
            self.cell(0, 7, str(value), ln=True)

        def table_header(self, cols, widths):
            self.set_font('Helvetica', 'B', 9)
            self.set_fill_color(230, 230, 230)
            self.set_text_color(30, 30, 30)
            for i, col in enumerate(cols):
                self.cell(widths[i], 7, col, border=1, fill=True)
            self.ln()

        def table_row(self, values, widths):
            self.set_font('Helvetica', '', 9)
            self.set_text_color(50, 50, 50)
            for i, val in enumerate(values):
                text = str(val)
                # Truncate long pipeline names
                if len(text) > 35:
                    text = text[:32] + '...'
                self.cell(widths[i], 6, text, border=1)
            self.ln()

    pdf = ReportPDF()
    pdf.alias_nb_pages()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=20)

    # Section 1: KPIs
    pdf.section_title('KEY METRICS')
    for label, value in kpis.items():
        pdf.kpi_row(label, value)
    pdf.ln(6)

    # Section 2: Error-Prone Pipelines
    pdf.section_title('MOST ERROR-PRONE PIPELINES')
    if pipelines:
        cols = list(pipelines[0].keys())
        widths = [120, 40]
        pdf.table_header(cols, widths)
        for p in pipelines:
            pdf.table_row(list(p.values()), widths)
    else:
        pdf.set_font('Helvetica', 'I', 10)
        pdf.cell(0, 7, 'No data available', ln=True)
    pdf.ln(6)

    # Section 3: Root Causes
    pdf.section_title('TOP ROOT CAUSES')
    if causes:
        cols = list(causes[0].keys())
        widths = [80, 40, 50]
        pdf.table_header(cols, widths)
        for c in causes:
            pdf.table_row(list(c.values()), widths)
    else:
        pdf.set_font('Helvetica', 'I', 10)
        pdf.cell(0, 7, 'No data available', ln=True)
    pdf.ln(6)

    # Section 4: Restart Exhaustion
    pdf.section_title('RESTART EXHAUSTION REPORT')
    if exhaustions:
        cols = ["Pipeline", "Error Type", "Retries", "Status"]
        widths = [55, 55, 25, 45]
        pdf.table_header(cols, widths)
        for e in exhaustions:
            pdf.table_row([e["Pipeline"], e["Error Type"], e["Retries"], e["Status"]], widths)
    else:
        pdf.set_font('Helvetica', 'I', 10)
        pdf.cell(0, 7, 'No data available', ln=True)

    pdf_bytes = pdf.output()
    filename = f"ADF_Healer_Report_{now.strftime('%Y%m%d_%H%M')}.pdf"

    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
