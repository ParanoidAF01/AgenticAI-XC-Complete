"""
Settings API routes.
GET  /api/settings — Return current system configuration
POST /api/settings — Update system configuration
"""
import os
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/api/settings", tags=["Settings"])


class SettingsResponse(BaseModel):
    """Current system settings."""
    listener_mode: str
    poll_interval: int
    notify_email: str
    adf_factory_name: str
    sql_server: str
    sql_database: str
    chroma_persist_dir: str


class SettingsUpdateRequest(BaseModel):
    """Fields that can be updated."""
    listener_mode: Optional[str] = None
    poll_interval: Optional[int] = None
    notify_email: Optional[str] = None


@router.get("", response_model=SettingsResponse)
def get_settings():
    """Return current system configuration (non-sensitive values only)."""
    return SettingsResponse(
        listener_mode=os.getenv("LISTENER_MODE", "sql"),
        poll_interval=int(os.getenv("POLL_INTERVAL", "30")),
        notify_email=os.getenv("NOTIFY_RECIPIENT", ""),
        adf_factory_name=os.getenv("ADF_FACTORY_NAME", ""),
        sql_server=os.getenv("SQL_SERVER", ""),
        sql_database=os.getenv("SQL_DATABASE", ""),
        chroma_persist_dir=os.getenv("CHROMA_PERSIST_DIR", "./chroma_db"),
    )


@router.post("")
def update_settings(req: SettingsUpdateRequest):
    """
    Update system settings.
    Note: Changes are applied in-memory for the current session.
    For persistent changes, update the .env file.
    """
    updated = {}

    if req.listener_mode is not None:
        if req.listener_mode not in ("adf", "sql"):
            return {"status": "error", "message": "listener_mode must be 'adf' or 'sql'"}
        os.environ["LISTENER_MODE"] = req.listener_mode
        updated["listener_mode"] = req.listener_mode

    if req.poll_interval is not None:
        if req.poll_interval < 10 or req.poll_interval > 300:
            return {"status": "error", "message": "poll_interval must be between 10 and 300 seconds"}
        os.environ["POLL_INTERVAL"] = str(req.poll_interval)
        updated["poll_interval"] = req.poll_interval

    if req.notify_email is not None:
        os.environ["NOTIFY_RECIPIENT"] = req.notify_email
        updated["notify_email"] = req.notify_email

    return {
        "status": "ok",
        "message": "Settings updated (in-memory). Restart listener to apply.",
        "updated": updated,
    }
