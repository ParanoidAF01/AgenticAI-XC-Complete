"""Chat router — REST and WebSocket interfaces for the ontology chatbot.

Provides two entry-points:

* **POST /ask** — synchronous request/response over HTTP.
* **WebSocket /ws** — real-time streaming with per-node progress updates.

Both paths build an initial :pydata:`WorkflowState`, invoke the LangGraph
workflow compiled by :func:`app.graph.workflow.create_workflow`, and
translate the final state into a :class:`ChatResponse`.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect, status
from fastapi.responses import JSONResponse

from app.graph.workflow import create_workflow
from app.models.schemas import ChatRequest, ChatResponse, WebSocketMessage

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])

# Human-readable progress labels keyed by LangGraph node name.
_NODE_PROGRESS: dict[str, str] = {
    "input_processor": "Understanding your question…",
    "intent_classifier": "Identifying intent…",
    "entity_extractor": "Extracting entities…",
    "clarity_checker": "Checking for ambiguity…",
    "graphrag_retriever": "Retrieving graph context…",
    "ontology_lookup": "Looking up schema…",
    "sql_generator": "Generating SQL…",
    "sql_validator": "Validating SQL…",
    "sql_executor": "Executing query…",
    "response_generator": "Formatting answer…",
    "conversation_store": "Saving conversation…",
}


# ── Dependency helpers ──────────────────────────────────────────────────────

def _get_services(request: Request) -> dict[str, Any]:
    """Bundle every service from ``app.state`` into a dict for the workflow."""
    return {
        "neo4j_service": request.app.state.neo4j_service,
        "llm_service": request.app.state.llm_service,
        "sql_service": request.app.state.sql_service,
        "redis_service": request.app.state.redis_service,
        "settings": request.app.state.settings,
    }


def _build_initial_state(
    question: str,
    session_id: str,
    services: dict[str, Any],
) -> dict[str, Any]:
    """Construct the initial ``WorkflowState`` dict consumed by LangGraph.

    Field names deliberately mirror the state schema defined in
    :pymod:`app.graph.workflow`.
    """
    return {
        # User input
        "session_id": session_id,
        "user_query": question,
        # Workflow outputs (initialised to empty/None)
        "intent": None,
        "entities": [],
        "ontology_context": {},
        "graphrag_context": {},
        "generated_sql": None,
        "sql_valid": None,
        "query_result": None,
        "final_response": None,
        "needs_clarification": False,
        "clarification_question": None,
        "error": None,
        "retry_count": 0,
        "current_node": "input_processor",
        # Injected services
        **services,
    }


# ── REST endpoint ───────────────────────────────────────────────────────────

@router.post(
    "/ask",
    response_model=ChatResponse,
    summary="Ask a natural-language question",
    description=(
        "Accepts a question in plain English, runs it through the full "
        "LangGraph pipeline (intent → entity → ontology → SQL → execution "
        "→ response), and returns a structured answer."
    ),
    responses={
        200: {"description": "Successful answer or clarification request"},
        500: {"description": "Unrecoverable pipeline error"},
    },
)
async def ask_question(body: ChatRequest, request: Request) -> ChatResponse | JSONResponse:
    """Synchronous question-answering via the LangGraph workflow.

    Returns a :class:`ChatResponse` on success or when clarification is
    needed (HTTP 200 either way).  Returns HTTP 500 with error details if
    the workflow raises an exception.
    """
    start = time.perf_counter()
    session_id = body.session_id or str(uuid.uuid4())

    logger.info(
        "POST /ask  session=%s  question=%r",
        session_id,
        body.question[:120],
    )

    try:
        services = _get_services(request)
        initial_state = _build_initial_state(body.question, session_id, services)

        workflow = create_workflow()
        final_state = await workflow.ainvoke(initial_state)

        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)

        # ── Clarification path ──────────────────────────────────────────
        if final_state.get("needs_clarification"):
            return ChatResponse(
                session_id=session_id,
                answer=final_state.get("clarification_question", "Could you clarify your question?"),
                needs_clarification=True,
                execution_time_ms=elapsed_ms,
            )

        # ── Error path ──────────────────────────────────────────────────
        if final_state.get("error"):
            logger.error(
                "Workflow error  session=%s  error=%s",
                session_id,
                final_state["error"],
            )
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={
                    "detail": str(final_state["error"]),
                    "session_id": session_id,
                },
            )

        # ── Success path ────────────────────────────────────────────────
        return ChatResponse(
            session_id=session_id,
            answer=final_state.get("final_response", ""),
            generated_sql=final_state.get("generated_sql"),
            query_result=final_state.get("query_result"),
            intent=final_state.get("intent"),
            entities=final_state.get("entities", []),
            needs_clarification=False,
            execution_time_ms=elapsed_ms,
        )

    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        logger.exception("Unhandled error in POST /ask  session=%s", session_id)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "detail": f"Internal pipeline error: {exc}",
                "session_id": session_id,
                "execution_time_ms": elapsed_ms,
            },
        )


# ── WebSocket endpoint ──────────────────────────────────────────────────────

@router.websocket("/ws")
async def websocket_chat(ws: WebSocket) -> None:
    """Real-time chatbot interface with per-node progress streaming.

    **Protocol:**

    1. Client sends a JSON message::

        {"question": "...", "session_id": "..."}

    2. Server streams ``WebSocketMessage`` objects of ``type="progress"``
       as the workflow advances through nodes.
    3. Server sends a final ``WebSocketMessage`` of ``type="final"`` (or
       ``type="error"``).
    4. Connection stays open for further questions until the client
       disconnects.
    """
    await ws.accept()
    logger.info("WebSocket connected  client=%s", ws.client)

    try:
        while True:
            raw = await ws.receive_text()

            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await _ws_send(ws, "error", "Invalid JSON payload.")
                continue

            question = data.get("question", "").strip()
            if not question:
                await _ws_send(ws, "error", "Missing 'question' field.")
                continue

            session_id = data.get("session_id") or str(uuid.uuid4())
            logger.info(
                "WS message  session=%s  question=%r",
                session_id,
                question[:120],
            )

            await _handle_ws_question(ws, question, session_id)

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected  client=%s", ws.client)
    except Exception:
        logger.exception("Unexpected WebSocket error")
        # Attempt a graceful close; ignore if the socket is already gone.
        try:
            await _ws_send(ws, "error", "Server error — connection closing.")
            await ws.close(code=status.WS_1011_INTERNAL_ERROR)
        except Exception:
            pass


async def _handle_ws_question(
    ws: WebSocket,
    question: str,
    session_id: str,
) -> None:
    """Run the LangGraph workflow and stream progress to *ws*."""
    start = time.perf_counter()

    try:
        services = _get_services_from_ws(ws)
        initial_state = _build_initial_state(question, session_id, services)

        workflow = create_workflow()

        # Stream node-by-node progress using LangGraph's astream interface.
        final_state: dict[str, Any] = {}
        async for event in workflow.astream(initial_state, stream_mode="updates"):
            for node_name in event:
                progress_msg = _NODE_PROGRESS.get(node_name, f"Processing {node_name}…")
                await _ws_send(ws, "progress", progress_msg, session_id=session_id)
                # Merge node output into the running state snapshot.
                if isinstance(event[node_name], dict):
                    final_state.update(event[node_name])

        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)

        # ── Clarification ───────────────────────────────────────────────
        if final_state.get("needs_clarification"):
            await _ws_send(
                ws,
                "clarification",
                final_state.get("clarification_question", "Could you clarify your question?"),
                session_id=session_id,
                extra={"execution_time_ms": elapsed_ms},
            )
            return

        # ── Error ────────────────────────────────────────────────────────
        if final_state.get("error"):
            await _ws_send(
                ws,
                "error",
                str(final_state["error"]),
                session_id=session_id,
                extra={"execution_time_ms": elapsed_ms},
            )
            return

        # ── Success ──────────────────────────────────────────────────────
        await _ws_send(
            ws,
            "final",
            final_state.get("final_response", ""),
            session_id=session_id,
            extra={
                "generated_sql": final_state.get("generated_sql"),
                "query_result": final_state.get("query_result"),
                "intent": final_state.get("intent"),
                "entities": final_state.get("entities", []),
                "execution_time_ms": elapsed_ms,
            },
        )

    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        logger.exception("Workflow error over WebSocket  session=%s", session_id)
        await _ws_send(
            ws,
            "error",
            f"Pipeline error: {exc}",
            session_id=session_id,
            extra={"execution_time_ms": elapsed_ms},
        )


# ── WebSocket helpers ───────────────────────────────────────────────────────

def _get_services_from_ws(ws: WebSocket) -> dict[str, Any]:
    """Extract services from the application state via a WebSocket handle."""
    return {
        "neo4j_service": ws.app.state.neo4j_service,
        "llm_service": ws.app.state.llm_service,
        "sql_service": ws.app.state.sql_service,
        "redis_service": ws.app.state.redis_service,
        "settings": ws.app.state.settings,
    }


async def _ws_send(
    ws: WebSocket,
    msg_type: str,
    message: str,
    *,
    session_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Send a ``WebSocketMessage``-shaped JSON frame to the client.

    Parameters
    ----------
    ws:
        The active WebSocket connection.
    msg_type:
        One of ``"progress"``, ``"final"``, ``"clarification"``, or
        ``"error"``.
    message:
        Human-readable message body.
    session_id:
        Current conversation session identifier.
    extra:
        Additional key/value pairs merged into the payload (e.g.
        ``generated_sql``, ``query_result``).
    """
    payload: dict[str, Any] = {
        "type": msg_type,
        "message": message,
    }
    if session_id is not None:
        payload["session_id"] = session_id
    if extra:
        payload.update(extra)

    await ws.send_json(payload)
