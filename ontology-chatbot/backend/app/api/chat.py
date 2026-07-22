"""
Chat API endpoints.
Session CRUD, messages, profiles, and health.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.api.dependencies import CurrentUser, get_redis, get_profile_manager, get_neo4j_repo
from app.db.repositories.session_repository import (
    create_session,
    delete_session,
    get_session,
    list_sessions,
    update_session,
)
from app.db.repositories.message_repository import (
    create_message,
    get_messages,
)
from app.schemas.chat import (
    ChatResponse,
    CreateSessionRequest,
    MessageRequest,
    MessageResponse,
    SessionResponse,
    UpdateSessionRequest,
)
from app.schemas.common import HealthResponse, ProfileResponse
from app.services.cache_service import RedisCacheService
from app.services.profile_manager import ProfileManager
from app.services.query_orchestrator import QueryOrchestrator

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])


# ── Session CRUD ──────────────────────────────────────────────

@router.post("/chats", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def create_chat(
    body: CreateSessionRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Create a new chat session."""
    session = await create_session(
        db,
        session_id=uuid.uuid4(),
        user_id=uuid.UUID(current_user["sub"]),
        title=body.title or "New Chat",
        profile=body.profile,
    )
    return SessionResponse(
        id=session.id,
        title=session.title,
        profile=session.profile,
        is_archived=session.is_archived,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


@router.get("/chats", response_model=list[SessionResponse])
async def list_chats(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """List all chat sessions for the current user."""
    sessions = await list_sessions(db, user_id=uuid.UUID(current_user["sub"]))
    return [
        SessionResponse(
            id=s.id,
            title=s.title,
            profile=s.profile,
            is_archived=s.is_archived,
            created_at=s.created_at,
            updated_at=s.updated_at,
        )
        for s in sessions
    ]


@router.get("/chats/{session_id}", response_model=SessionResponse)
async def get_chat(
    session_id: uuid.UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Get a specific chat session (ownership enforced)."""
    session = await get_session(db, session_id=session_id, user_id=uuid.UUID(current_user["sub"]))
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return SessionResponse(
        id=session.id,
        title=session.title,
        profile=session.profile,
        is_archived=session.is_archived,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


@router.patch("/chats/{session_id}", response_model=SessionResponse)
async def update_chat(
    session_id: uuid.UUID,
    body: UpdateSessionRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Update chat session title or archive status."""
    session = await get_session(db, session_id=session_id, user_id=uuid.UUID(current_user["sub"]))
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    updated = await update_session(
        db,
        session_id=session_id,
        user_id=uuid.UUID(current_user["sub"]),
        title=body.title,
        is_archived=body.is_archived,
        profile=body.profile,
    )
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return SessionResponse(
        id=updated.id,
        title=updated.title,
        profile=updated.profile,
        is_archived=updated.is_archived,
        created_at=updated.created_at,
        updated_at=updated.updated_at,
    )


@router.delete("/chats/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chat(
    session_id: uuid.UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Delete a chat session (ownership enforced)."""
    session = await get_session(db, session_id=session_id, user_id=uuid.UUID(current_user["sub"]))
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    await delete_session(db, session_id=session_id, user_id=uuid.UUID(current_user["sub"]))
    return None


# ── Messages ──────────────────────────────────────────────────

@router.get("/chats/{session_id}/messages", response_model=list[MessageResponse])
async def list_messages(
    session_id: uuid.UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Get messages for a chat session (ownership enforced)."""
    session = await get_session(db, session_id=session_id, user_id=uuid.UUID(current_user["sub"]))
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    messages = await get_messages(db, session_id=session_id, user_id=uuid.UUID(current_user["sub"]))
    return [
        MessageResponse(
            id=m.id,
            session_id=m.session_id,
            role=m.role,
            content=m.content,
            metadata_=m.metadata_,
            created_at=m.created_at,
        )
        for m in messages
    ]


@router.post("/chats/{session_id}/messages", response_model=ChatResponse)
async def send_message(
    session_id: uuid.UUID,
    body: MessageRequest,
    request: Request,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Send a message and receive the assistant's response."""
    user_id = current_user["sub"]

    # Verify session ownership
    session = await get_session(db, session_id=session_id, user_id=uuid.UUID(user_id))
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

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
            user_id=user_id,
            session_id=str(session_id),
            message=body.content,
            db=db,
        )
        return response
    except Exception as e:
        logger.error("Error processing message: %s", e, exc_info=True)
        # Save error as assistant message
        error_msg = await create_message(
            db,
            message_id=uuid.uuid4(),
            session_id=session_id,
            role="assistant",
            content=f"❌ Error: {str(e)}",
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


# ── Profiles ──────────────────────────────────────────────────

@router.get("/profiles", response_model=list[ProfileResponse])
async def list_profiles(
    current_user: CurrentUser,
    request: Request,
):
    """List available database profiles."""
    pm: ProfileManager = request.app.state.profile_manager
    profiles = pm.get_profiles()
    return [
        ProfileResponse(name=p["name"], display_name=p["display_name"], description=p["description"])
        for p in profiles
    ]


# ── Health ────────────────────────────────────────────────────

@router.get("/health", response_model=HealthResponse)
async def health():
    """Health check endpoint."""
    return HealthResponse(
        status="ok",
        timestamp=datetime.now(timezone.utc),
    )
