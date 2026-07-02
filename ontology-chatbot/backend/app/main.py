"""
FastAPI application entry point.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.services.cache_service import RedisCacheService
from app.services.profile_manager import ProfileManager

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize and teardown shared resources."""
    setup_logging()
    settings = get_settings()
    logger.info("Starting Ontology Chatbot Backend")

    # ── Redis ──
    try:
        redis_client = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
        )
        await redis_client.ping()
        logger.info("Redis connected")
    except Exception as e:
        logger.warning("Redis connection failed (cache will be unavailable): %s", e)
        redis_client = None

    app.state.cache_service = RedisCacheService(redis_client)

    # ── Neo4j ──
    try:
        from app.ontology.neo4j_repository import Neo4jRepo
        neo4j_repo = Neo4jRepo(
            uri=settings.NEO4J_URI,
            username=settings.NEO4J_USERNAME,
            password=settings.NEO4J_PASSWORD,
        )
        if neo4j_repo.test():
            logger.info("Neo4j connected")
        else:
            logger.warning("Neo4j connection test returned False")
    except Exception as e:
        logger.warning("Neo4j connection failed: %s", e)
        neo4j_repo = None

    app.state.neo4j_repo = neo4j_repo

    # ── MSSQL Profiles ──
    profile_manager = ProfileManager(settings)
    profile_manager.initialize()
    app.state.profile_manager = profile_manager
    logger.info("Profile manager initialized with profiles: %s",
                [p["name"] for p in profile_manager.get_profiles()])

    yield

    # ── Teardown ──
    logger.info("Shutting down")
    if redis_client:
        await redis_client.close()
    if neo4j_repo:
        neo4j_repo.close()
    profile_manager.cleanup()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="Ontology Chatbot API",
        description="Ontology-driven insurance database chatbot API",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # ── CORS ──
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Routers ──
    from app.api.auth import router as auth_router
    from app.api.chat import router as chat_router

    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(chat_router, prefix="/api/v1")

    return app


app = create_app()
