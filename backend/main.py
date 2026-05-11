"""
Self-Healing ADF Pipeline — FastAPI Backend.

Main entry point. Registers all route modules and configures CORS.

Usage:
    uvicorn backend.main:app --reload --port 8000
"""
import sys
import os

# Add project root to path so we can import existing modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.routes import dashboard, pipelines, reports, chat, settings, listener

app = FastAPI(
    title="Self-Healing ADF Pipeline API",
    description="Backend API for the Self-Healing ADF monitoring dashboard.",
    version="1.0.0",
)

# CORS — allow React dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",   # Vite dev server
        "http://localhost:5174",   # Vite dev server (alternate)
        "http://localhost:3000",   # Alternative dev port
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register route modules
app.include_router(dashboard.router)
app.include_router(pipelines.router)
app.include_router(pipelines.reports_router)
app.include_router(reports.router)
app.include_router(chat.router)
app.include_router(settings.router)
app.include_router(listener.router)


@app.get("/api/health")
def health_check():
    """Health check endpoint for monitoring."""
    return {"status": "healthy", "service": "self-healing-adf-api"}
