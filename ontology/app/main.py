"""FastAPI application entry-point.

Creates the ASGI application, configures middleware, wires up routers,
and manages the lifecycle of external services (Neo4j, LLM, MSSQL,
Redis, SpaCy) via an async lifespan context manager.

Run with::

    uvicorn app.main:app --reload
"""

from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from typing import AsyncIterator

import spacy
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import Settings, get_settings
from app.routers import chat, health
from app.services.neo4j_service import Neo4jService
from app.services.llm_service import LLMService
from app.services.sql_service import SQLService
from app.services.redis_service import RedisService

# ── Logging ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


# ── Lifespan ────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage startup / shutdown of external resources.

    On **startup** the function:

    1. Loads application settings from ``.env`` / environment.
    2. Initialises service connectors (Neo4j, LLM, SQL, Redis).
    3. Stores every service on ``app.state`` so routers can access them
       through :pydata:`request.app.state`.
    4. Pre-loads the SpaCy language model.

    On **shutdown** it closes Neo4j and Redis connections.
    """
    settings: Settings = get_settings()
    app.state.settings = settings

    logger.info("Starting up  app=%s  version=%s", settings.app_name, settings.app_version)

    # ── Neo4j ───────────────────────────────────────────────────────────
    neo4j_service = Neo4jService(
        uri=settings.neo4j_uri,
        user=settings.neo4j_user,
        password=settings.neo4j_password,
    )
    app.state.neo4j_service = neo4j_service
    logger.info("Neo4j service initialised  uri=%s", settings.neo4j_uri)

    # ── LLM (OpenAI) ───────────────────────────────────────────────────
    llm_service = LLMService(
        api_key=settings.openai_api_key,
        model=settings.openai_model,
        base_url=settings.openai_base_url,
    )
    app.state.llm_service = llm_service
    logger.info("LLM service initialised  model=%s", settings.openai_model)

    # ── MSSQL ───────────────────────────────────────────────────────────
    sql_service = SQLService(
        server=settings.mssql_server,
        database=settings.mssql_database,
        user=settings.mssql_user,
        password=settings.mssql_password,
        driver=settings.mssql_driver,
    )
    app.state.sql_service = sql_service
    logger.info("SQL service initialised  server=%s", settings.mssql_server)

    # ── Redis ───────────────────────────────────────────────────────────
    redis_service = RedisService(url=settings.redis_url)
    app.state.redis_service = redis_service
    logger.info("Redis service initialised  url=%s", settings.redis_url)

    # ── SpaCy ───────────────────────────────────────────────────────────
    try:
        nlp = spacy.load(settings.spacy_model)
        app.state.spacy_nlp = nlp
        logger.info("SpaCy model loaded  model=%s", settings.spacy_model)
    except OSError:
        logger.warning(
            "SpaCy model '%s' not found. "
            "Run:  python -m spacy download %s",
            settings.spacy_model,
            settings.spacy_model,
        )
        app.state.spacy_nlp = None

    logger.info("All services initialised — ready to serve requests")

    # ── Yield control to the application ────────────────────────────────
    yield

    # ── Shutdown ────────────────────────────────────────────────────────
    logger.info("Shutting down — closing external connections")

    try:
        await neo4j_service.close()
        logger.info("Neo4j driver closed")
    except Exception:
        logger.warning("Error closing Neo4j driver", exc_info=True)

    try:
        await redis_service.close()
        logger.info("Redis connection closed")
    except Exception:
        logger.warning("Error closing Redis connection", exc_info=True)

    logger.info("Shutdown complete")


# ── Application factory ────────────────────────────────────────────────────

app = FastAPI(
    title="Ontology-Driven Insurance Chatbot",
    description=(
        "Natural language to SQL using a Neo4j metadata graph. "
        "Ask business questions in plain English and receive structured "
        "answers backed by live database queries."
    ),
    version="1.0.0",
    lifespan=lifespan,
)


# ── CORS middleware ─────────────────────────────────────────────────────────
# Wide-open for local development; tighten `allow_origins` in production.

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Routers ─────────────────────────────────────────────────────────────────

app.include_router(health.router)
app.include_router(chat.router)


# ── Exception handlers ─────────────────────────────────────────────────────

@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """Return a clean 422 with human-readable validation details."""
    logger.warning("Validation error  path=%s  errors=%s", request.url.path, exc.errors())
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "detail": "Request validation failed",
            "errors": [
                {
                    "field": " → ".join(str(loc) for loc in err.get("loc", [])),
                    "message": err.get("msg", "Unknown error"),
                    "type": err.get("type", ""),
                }
                for err in exc.errors()
            ],
        },
    )


@app.exception_handler(ValueError)
async def value_error_handler(
    request: Request,
    exc: ValueError,
) -> JSONResponse:
    """Catch unhandled ``ValueError`` and return 400."""
    logger.warning("ValueError  path=%s  detail=%s", request.url.path, exc)
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"detail": str(exc)},
    )


@app.exception_handler(Exception)
async def generic_error_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    """Catch-all for unhandled exceptions → 500 with safe message."""
    logger.exception("Unhandled exception  path=%s", request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An unexpected error occurred. Please try again later."},
    )


# ── Root redirect ──────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    """Redirect browsers to the interactive API docs."""
    return {
        "message": "Ontology-Driven Insurance Chatbot API",
        "docs": "/docs",
        "health": "/health",
    }
