"""
Chat API routes.
POST   /api/chat           — Send a question to the RAG chatbot, get an AI-generated answer
GET    /api/chat/pipelines  — Get all available pipeline names grouped by source for dropdown
DELETE /api/chat/history    — Clear chat history (server-side session)
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import threading

router = APIRouter(prefix="/api", tags=["Chat"])


# ─── In-memory chat history (per-session, no auth needed) ─────────

_chat_history = []
_history_lock = threading.Lock()


class ChatRequest(BaseModel):
    """Request body for the chat endpoint."""
    question: str
    pipeline_name: Optional[str] = None   # Filter to specific pipeline
    source_filter: Optional[str] = None   # "all", "adf", "sql", "databricks", "snowflake"


class ChatResponse(BaseModel):
    """Response body for the chat endpoint."""
    answer: str
    pipeline_name: Optional[str] = None
    source_filter: Optional[str] = None


class ChatHistoryItem(BaseModel):
    """Single chat message."""
    role: str       # "user" or "assistant"
    content: str
    pipeline_name: Optional[str] = None
    timestamp: str


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    """
    Send a natural language question to the RAG chatbot.
    Searches ChromaDB for relevant errors, fetches pipeline metadata,
    and generates an AI-powered response.

    Optional filters:
      - pipeline_name: restrict search to a specific pipeline collection
      - source_filter: "all", "adf", "sql", "databricks", "snowflake"
    """
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    from datetime import datetime, timezone

    # Save user message to history
    with _history_lock:
        _chat_history.append({
            "role": "user",
            "content": req.question,
            "pipeline_name": req.pipeline_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    try:
        # Import here to avoid circular imports and heavy module loading at startup
        from chatbot.rag_pipeline import query as rag_query

        # Build the effective pipeline filter
        effective_pipeline = req.pipeline_name

        # If a source filter is provided, inject it as context into the question
        # so the RAG pipeline and LLM are aware of the scope
        question = req.question
        if req.source_filter and req.source_filter != "all":
            question = (
                f"[Context: The user is filtering by {req.source_filter.upper()} pipelines only.] "
                f"{req.question}"
            )

        answer = rag_query(
            question=question,
            pipeline_name=effective_pipeline,
        )

        # Save assistant response to history
        with _history_lock:
            _chat_history.append({
                "role": "assistant",
                "content": answer,
                "pipeline_name": req.pipeline_name,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

        return ChatResponse(
            answer=answer,
            pipeline_name=req.pipeline_name,
            source_filter=req.source_filter,
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Chat processing failed: {str(e)}"
        )


@router.get("/chat/pipelines")
def get_chat_pipelines():
    """
    Return all available pipeline names grouped by source for the dropdown.

    Sources:
      - adf: Pipelines known to ADF (from ChromaDB collections + metadata store)
      - sql: Pipelines logged in PipelineRunLog (from SQL error history)
      - databricks: Coming soon
      - snowflake: Coming soon

    The frontend renders these as grouped dropdown options:
      All Pipelines | ADF | SQL | Databricks | Snowflake
    """
    pipelines = {
        "all": [],
        "adf": [],
        "sql": [],
        "databricks": [],    # Coming soon — empty for now
        "snowflake": [],     # Coming soon — empty for now
    }

    # Source 1: ChromaDB collections (each collection = one pipeline's error namespace)
    try:
        from intelligence.chroma_store import get_all_collections
        collections = get_all_collections()
        # Collections are pipeline names stored by the error processor
        pipelines["adf"] = sorted(collections)
    except Exception:
        pass

    # Source 2: SQLite metadata store (all registered pipelines)
    try:
        from config.metadata_store import get_all_pipelines
        meta_pipelines = get_all_pipelines()
        meta_names = [p["pipeline_name"] for p in meta_pipelines]
        # Merge into ADF list (deduplicate)
        existing = set(pipelines["adf"])
        for name in meta_names:
            if name not in existing:
                pipelines["adf"].append(name)
                existing.add(name)
        pipelines["adf"] = sorted(pipelines["adf"])
    except Exception:
        pass

    # Source 3: SQL PipelineRunLog — distinct pipeline names from error history
    try:
        from config.metadata_store import get_error_history
        history = get_error_history(limit=500)
        sql_pipelines = sorted(set(h["pipeline_name"] for h in history if h.get("pipeline_name")))
        pipelines["sql"] = sql_pipelines
    except Exception:
        pass

    # Build unified "all" list (deduplicated, sorted)
    all_names = set()
    for source_list in pipelines.values():
        all_names.update(source_list)
    pipelines["all"] = sorted(all_names)

    return {
        "pipelines": pipelines,
        "total": len(pipelines["all"]),
    }


@router.get("/chat/history")
def get_chat_history():
    """Return the current chat history."""
    with _history_lock:
        return {
            "messages": list(_chat_history),
            "count": len(_chat_history),
        }


@router.delete("/chat/history")
def clear_chat_history():
    """Clear the chat history. Called when user clicks 'Clear Chat'."""
    with _history_lock:
        _chat_history.clear()
    return {"status": "cleared", "message": "Chat history cleared."}
