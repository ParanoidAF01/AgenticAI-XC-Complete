"""
Power BI integration API endpoints.
Provides a simplified chat endpoint and profiles endpoint for the Power BI custom visual.
Uses API-key authentication instead of JWT.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.db.repositories.session_repository import create_session, get_session
from app.db.repositories.message_repository import create_message
from app.schemas.powerbi import PowerBIChatRequest, PowerBIChatResponse
from app.schemas.common import ProfileResponse
from app.services.profile_manager import ProfileManager
from app.services.query_orchestrator import QueryOrchestrator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/powerbi", tags=["powerbi"])

# ── Dedicated Power BI system user UUID ──
# This is a fixed UUID used for all Power BI sessions (no real user login).
POWERBI_SYSTEM_USER_ID = uuid.UUID("00000000-0000-4000-a000-000000000001")


# ── API Key Dependency ────────────────────────────────────────

async def verify_powerbi_api_key(
    x_api_key: str = Header(..., alias="X-API-Key"),
) -> str:
    """Validate the X-API-Key header against the configured secret."""
    settings = get_settings()
    if not settings.POWERBI_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Power BI integration is not configured. Set POWERBI_API_KEY in .env",
        )
    if x_api_key != settings.POWERBI_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )
    return x_api_key


# ── Profiles ──────────────────────────────────────────────────

@router.get("/profiles", response_model=list[ProfileResponse])
async def powerbi_list_profiles(
    request: Request,
    _api_key: str = Depends(verify_powerbi_api_key),
):
    """List available database profiles for the Power BI visual dropdown."""
    pm: ProfileManager = request.app.state.profile_manager
    profiles = pm.get_profiles()
    return [
        ProfileResponse(
            name=p["name"],
            display_name=p["display_name"],
            description=p.get("description", ""),
        )
        for p in profiles
    ]


# ── Chat ──────────────────────────────────────────────────────

@router.post("/chat", response_model=PowerBIChatResponse)
async def powerbi_chat(
    body: PowerBIChatRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_powerbi_api_key),
):
    """
    Send a message from the Power BI visual and receive the assistant's response.

    - If no session_id is provided, a new session is auto-created.
    - If a session_id is provided, the existing session is reused for
      conversation continuity.
    - The profile defaults to POWERBI_DEFAULT_PROFILE if not specified.
    """
    settings = get_settings()

    # Resolve profile
    profile = body.profile or settings.POWERBI_DEFAULT_PROFILE or None

    # Resolve or create session
    session_uuid: uuid.UUID
    if body.session_id:
        try:
            session_uuid = uuid.UUID(body.session_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid session_id format. Must be a valid UUID.",
            )
        # Try to fetch existing session
        existing = await get_session(db, session_id=session_uuid, user_id=POWERBI_SYSTEM_USER_ID)
        if not existing:
            # Session doesn't exist yet — create it
            await create_session(
                db,
                session_id=session_uuid,
                user_id=POWERBI_SYSTEM_USER_ID,
                profile=profile,
                title="Power BI Chat",
            )
    else:
        # No session_id provided — create a brand new one
        session_uuid = uuid.uuid4()
        await create_session(
            db,
            session_id=session_uuid,
            user_id=POWERBI_SYSTEM_USER_ID,
            profile=profile,
            title="Power BI Chat",
        )

    # Get services from app state
    cache_service = request.app.state.cache_service
    neo4j_repo = request.app.state.neo4j_repo
    profile_manager = request.app.state.profile_manager

    orchestrator = QueryOrchestrator(
        cache_service=cache_service,
        neo4j_repo=neo4j_repo,
        profile_manager=profile_manager,
    )

    try:
        response = await orchestrator.process_chat_message(
            user_id=str(POWERBI_SYSTEM_USER_ID),
            session_id=str(session_uuid),
            message=body.message,
            db=db,
        )

        # Extract fields from the full ChatResponse into simplified PBI response
        answer = response.message.content if response.message else "No response generated."
        sql_list = None
        chart_cfg = None
        has_error = False
        is_clarification = response.is_clarification

        # Extract SQL from response
        if response.sql:
            sql_list = [str(s) for s in response.sql] if isinstance(response.sql, list) else [str(response.sql)]

        # Extract chart config
        if response.chart_config:
            chart_cfg = response.chart_config

        # Check for errors in metadata
        if response.message and response.message.metadata_:
            has_error = response.message.metadata_.get("has_error", False)

        return PowerBIChatResponse(
            answer=answer,
            session_id=str(session_uuid),
            has_error=has_error,
            sql=sql_list,
            chart_config=chart_cfg,
            is_clarification=is_clarification,
        )

    except Exception as e:
        logger.error("Power BI chat error: %s", e, exc_info=True)

        # Save error message to DB for context continuity
        try:
            await create_message(
                db,
                message_id=uuid.uuid4(),
                session_id=session_uuid,
                role="assistant",
                content=f"Error: {type(e).__name__}: {str(e)}",
            )
        except Exception:
            pass  # Don't fail if we can't save the error message

        return PowerBIChatResponse(
            answer=f"Something went wrong: {type(e).__name__}: {str(e)}",
            session_id=str(session_uuid),
            has_error=True,
        )
