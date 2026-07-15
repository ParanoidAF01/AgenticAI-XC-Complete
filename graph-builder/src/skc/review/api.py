"""Optional FastAPI review API."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from skc.ir.kir import (
    BusinessConcept,
    BusinessEntity,
    BusinessRelationship,
    BusinessRule,
    Metric,
    SecurityTag,
    TimeIntelligence,
)
from skc.review.store import CandidateStore


CANDIDATE_MODELS = {
    "business_entity": BusinessEntity,
    "business_concept": BusinessConcept,
    "metric": Metric,
    "business_rule": BusinessRule,
    "relationship": BusinessRelationship,
    "time_intelligence": TimeIntelligence,
    "security_tag": SecurityTag,
}


def create_app(store_path: str | Path, publish_callback: Callable[[], dict[str, Any]] | None = None):
    """Create a FastAPI app for reviewing persisted candidates."""
    try:
        from fastapi import FastAPI, HTTPException
        from fastapi.responses import HTMLResponse
        from pydantic import BaseModel
    except Exception as exc:
        raise RuntimeError("fastapi is required to use the review API") from exc

    class RejectRequest(BaseModel):
        reason: str
        reviewer: str | None = None

    class ReviewRequest(BaseModel):
        reviewer: str | None = None
        notes: str | None = None

    class ModifyRequest(BaseModel):
        node: dict[str, Any]
        reviewer: str | None = None
        notes: str | None = None

    store = CandidateStore(store_path)
    app = FastAPI(title="SKC Review API")

    @app.get("/", response_class=HTMLResponse)
    def dashboard(status: str | None = None) -> str:
        rows = store.get_by_status(status) if status else store.all()
        stats = store.count_by_status()
        row_html = "\n".join(_candidate_row(row) for row in rows)
        stats_html = " ".join(
            f"<span class='stat'><b>{name}</b>: {count}</span>"
            for name, count in sorted(stats.items())
        )
        return f"""
        <!doctype html>
        <html>
        <head>
          <title>SKC Review</title>
          <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 32px; }}
            table {{ border-collapse: collapse; width: 100%; }}
            th, td {{ border-bottom: 1px solid #ddd; padding: 8px; text-align: left; vertical-align: top; }}
            code {{ white-space: pre-wrap; }}
            button {{ margin-right: 6px; }}
            .stat {{ margin-right: 16px; }}
          </style>
        </head>
        <body>
          <h1>SKC Review Queue</h1>
          <p>{stats_html}</p>
          <table>
            <thead>
              <tr><th>Name</th><th>Type</th><th>Confidence</th><th>Status</th><th>Actions</th></tr>
            </thead>
            <tbody>{row_html}</tbody>
          </table>
          <script>
            async function approve(id) {{
              await fetch(`/candidates/${{id}}/approve`, {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{reviewer: 'web'}})
              }});
              location.reload();
            }}
            async function rejectCandidate(id) {{
              const reason = prompt('Reason for rejection?') || 'Rejected in web review';
              await fetch(`/candidates/${{id}}/reject`, {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{reviewer: 'web', reason}})
              }});
              location.reload();
            }}
            async function modifyCandidate(id) {{
              const raw = prompt('JSON fields to update?', '{{}}');
              if (!raw) return;
              await fetch(`/candidates/${{id}}/modify`, {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{reviewer: 'web', notes: 'Modified in web review', node: JSON.parse(raw)}})
              }});
              location.reload();
            }}
          </script>
        </body>
        </html>
        """

    @app.get("/candidates")
    def candidates(status: str | None = None) -> list[dict[str, Any]]:
        if status:
            return store.get_by_status(status)
        return store.all()

    @app.get("/candidates/{candidate_id}")
    def candidate(candidate_id: str) -> dict[str, Any]:
        for row in store.all():
            if row["id"] == candidate_id:
                return row
        raise HTTPException(status_code=404, detail="Candidate not found")

    @app.post("/candidates/{candidate_id}/approve")
    def approve(candidate_id: str, request: ReviewRequest) -> dict[str, str]:
        try:
            store.approve(candidate_id, reviewer=request.reviewer, notes=request.notes)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"status": "approved"}

    @app.post("/candidates/{candidate_id}/reject")
    def reject(candidate_id: str, request: RejectRequest) -> dict[str, str]:
        try:
            store.reject(candidate_id, reason=request.reason, reviewer=request.reviewer)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"status": "rejected"}

    @app.post("/candidates/{candidate_id}/modify")
    def modify(candidate_id: str, request: ModifyRequest) -> dict[str, str]:
        existing = _candidate_or_404(store, candidate_id, HTTPException)
        payload = dict(existing["serialized_node"])
        payload.update(request.node)
        model_type = CANDIDATE_MODELS.get(payload.get("candidate_type") or existing["node_type"])
        if model_type is None:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported candidate type: {payload.get('candidate_type') or existing['node_type']}",
            )
        try:
            updated_node = model_type.model_validate(payload)
            store.modify(candidate_id, updated_node, reviewer=request.reviewer, notes=request.notes)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"status": "modified"}

    @app.get("/stats")
    def stats() -> dict[str, int]:
        return store.count_by_status()

    @app.post("/publish")
    def publish() -> dict[str, Any]:
        if publish_callback is None:
            return {"status": "not_configured"}
        return {"status": "published", "result": publish_callback()}

    return app


def _candidate_or_404(store: CandidateStore, candidate_id: str, http_exception: Any) -> dict[str, Any]:
    for row in store.all():
        if row["id"] == candidate_id:
            return row
    raise http_exception(status_code=404, detail="Candidate not found")


def _candidate_row(row: dict[str, Any]) -> str:
    confidence = f"{row['confidence_score']:.2f} ({row['confidence_tier']})"
    return (
        "<tr>"
        f"<td>{_escape(row['name'])}</td>"
        f"<td>{_escape(row['node_type'])}</td>"
        f"<td>{_escape(confidence)}</td>"
        f"<td>{_escape(row['review_status'])}</td>"
        "<td>"
        f"<button onclick=\"approve('{_escape(row['id'])}')\">Approve</button>"
        f"<button onclick=\"rejectCandidate('{_escape(row['id'])}')\">Reject</button>"
        f"<button onclick=\"modifyCandidate('{_escape(row['id'])}')\">Modify</button>"
        f"<a href=\"/candidates/{_escape(row['id'])}\">JSON</a>"
        "</td>"
        "</tr>"
    )


def _escape(value: Any) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )
