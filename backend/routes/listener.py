"""
Listener control API routes.
POST   /api/listener/start         — Start the listener (optionally with a mode)
POST   /api/listener/stop          — Stop the running listener
POST   /api/listener/restart       — Stop + start with new mode
GET    /api/listener/status        — Get current listener status
GET    /api/listener/logs          — Get recent poll logs (for Listener page "Recent Polls")
DELETE /api/listener/logs          — Clear poll logs
GET    /api/listener/health        — Get cached connection health (instant)
POST   /api/listener/health/check  — Force fresh health check (blocks ~3-4s)
"""
from fastapi import APIRouter, Query
from pydantic import BaseModel
from typing import Optional
from backend.listener_manager import listener_manager
from backend.health_checker import health_checker

router = APIRouter(prefix="/api/listener", tags=["Listener"])


class ListenerRequest(BaseModel):
    """Optional mode for start/restart."""
    mode: Optional[str] = None  # "adf" or "sql"


@router.get("/status")
def get_listener_status():
    """Return current listener status: running/stopped, mode, available modes."""
    return listener_manager.get_status()


@router.post("/start")
def start_listener(req: ListenerRequest = ListenerRequest()):
    """Start the listener. Optionally specify mode ('adf' or 'sql')."""
    return listener_manager.start(mode=req.mode)


@router.post("/stop")
def stop_listener():
    """Stop the running listener."""
    return listener_manager.stop()


@router.post("/restart")
def restart_listener(req: ListenerRequest = ListenerRequest()):
    """Stop the current listener and restart with a new mode."""
    return listener_manager.restart(mode=req.mode)


@router.get("/logs")
def get_listener_logs(limit: int = Query(50, ge=1, le=100)):
    """
    Return recent poll logs (newest first).
    The frontend Listener page polls this endpoint every 5 seconds
    to display the "Recent Polls" table.
    """
    return {
        "logs": listener_manager.get_logs(limit=limit),
        "listener_running": listener_manager.is_running,
        "listener_mode": listener_manager.mode,
    }


@router.delete("/logs")
def clear_listener_logs():
    """Clear all poll logs."""
    listener_manager.clear_logs()
    return {"status": "cleared"}


# ─── Connection Health Endpoints ──────────────────────────────────

@router.get("/health")
def get_health():
    """
    Return cached connection health for all 5 services.
    Instant response — returns last known state.
    If cache is stale (>30s), triggers a background refresh automatically.
    """
    result = health_checker.get_cached_results()

    # Auto-trigger background refresh if stale
    if result["stale"] and not result["checking"]:
        health_checker.run_checks_background()

    return result


@router.post("/health/check")
def force_health_check():
    """
    Force an immediate health check on all 5 services.
    Blocks until all checks complete (~3-4 seconds).
    Called on page load to populate the health cards.
    """
    return health_checker.run_checks()
