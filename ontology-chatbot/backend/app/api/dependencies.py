"""
Shared API dependencies.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from app.core.security import get_current_user
from app.services.cache_service import RedisCacheService
from app.services.profile_manager import ProfileManager


async def get_redis(request: Request) -> RedisCacheService:
    """Get the Redis cache service from app state."""
    return request.app.state.cache_service


async def get_profile_manager(request: Request) -> ProfileManager:
    """Get the profile manager from app state."""
    return request.app.state.profile_manager


async def get_neo4j_repo(request: Request):
    """Get the Neo4j repository from app state."""
    return request.app.state.neo4j_repo


CurrentUser = Annotated[dict, Depends(get_current_user)]
