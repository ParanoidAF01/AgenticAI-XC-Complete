"""
Chat API route.
POST /api/chat — Send a question to the RAG chatbot, get an AI-generated answer.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional


router = APIRouter(prefix="/api", tags=["Chat"])


class ChatRequest(BaseModel):
    """Request body for the chat endpoint."""
    question: str
    pipeline_name: Optional[str] = None


class ChatResponse(BaseModel):
    """Response body for the chat endpoint."""
    answer: str
    pipeline_name: Optional[str] = None


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    """
    Send a natural language question to the RAG chatbot.
    Searches ChromaDB for relevant errors, fetches pipeline metadata,
    and generates an AI-powered response.
    """
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    try:
        # Import here to avoid circular imports and heavy module loading at startup
        from chatbot.rag_pipeline import query as rag_query

        answer = rag_query(
            question=req.question,
            pipeline_name=req.pipeline_name
        )
        return ChatResponse(
            answer=answer,
            pipeline_name=req.pipeline_name
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Chat processing failed: {str(e)}"
        )
