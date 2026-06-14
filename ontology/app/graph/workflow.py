"""
LangGraph workflow definition — wires together all pipeline nodes.

This module defines the compiled ``StateGraph`` and exposes a
``create_workflow()`` factory function that returns a ready‑to‑invoke
graph.

Graph topology
--------------
::

    START
      │
      ▼
    input_processor
      │
      ▼
    intent_classifier
      │
      ▼
    entity_extractor
      │
      ▼
    clarity_checker ──── needs_clarification? ──► END (return question)
      │ (no)
      ▼
    graphrag_retriever
      │
      ▼
    ontology_lookup
      │
      ▼
    sql_generator ◄──── retry (sql_valid=False AND retry_count < 3)
      │
      ▼
    sql_validator
      │ ├── sql_valid=False AND retry_count >= 3 ──► END (error)
      │ └── sql_valid=True
      ▼
    sql_executor
      │
      ▼
    response_generator
      │
      ▼
    END
"""

from __future__ import annotations

import logging
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.graph.state import WorkflowState

# ── Import every node ───────────────────────────────────────────────────────
from app.graph.nodes.input_processor import input_processor
from app.graph.nodes.intent_classifier import intent_classifier
from app.graph.nodes.entity_extractor import entity_extractor
from app.graph.nodes.clarity_checker import clarity_checker
from app.graph.nodes.graphrag_retriever import graphrag_retriever
from app.graph.nodes.ontology_lookup import ontology_lookup
from app.graph.nodes.sql_generator import sql_generator
from app.graph.nodes.sql_validator import sql_validator
from app.graph.nodes.sql_executor import sql_executor
from app.graph.nodes.response_generator import response_generator

logger = logging.getLogger(__name__)


# ── Conditional‑edge routing functions ──────────────────────────────────────


def _route_after_clarity(state: WorkflowState) -> str:
    """Decide whether to proceed or end with a clarification question.

    Returns
    -------
    str
        ``"graphrag_retriever"`` if no clarification is needed,
        otherwise ``END`` so the caller receives the clarification
        question from state.
    """
    if state.get("needs_clarification"):
        logger.info("workflow ▸ clarity route → END (needs clarification)")
        return END
    return "graphrag_retriever"


def _route_after_validation(state: WorkflowState) -> str:
    """Decide whether to execute, retry, or abort.

    Returns
    -------
    str
        * ``"sql_executor"``  — SQL is valid.
        * ``"sql_generator"`` — SQL invalid, retries remaining.
        * ``END``             — SQL invalid, retries exhausted.
    """
    if state.get("sql_valid"):
        return "sql_executor"

    retry_count: int = state.get("retry_count", 0)
    if retry_count < 3:
        logger.info(
            "workflow ▸ validation route → sql_generator (retry %d/3)",
            retry_count,
        )
        return "sql_generator"

    logger.warning("workflow ▸ validation route → END (retries exhausted)")
    return END


# ── Graph builder ───────────────────────────────────────────────────────────


def create_workflow() -> Any:
    """Build and compile the LangGraph ``StateGraph``.

    Returns
    -------
    CompiledGraph
        A compiled LangGraph graph that can be invoked with
        ``await graph.ainvoke(initial_state)``.
    """
    graph = StateGraph(WorkflowState)

    # ── Add nodes ────────────────────────────────────────────────────
    graph.add_node("input_processor", input_processor)
    graph.add_node("intent_classifier", intent_classifier)
    graph.add_node("entity_extractor", entity_extractor)
    graph.add_node("clarity_checker", clarity_checker)
    graph.add_node("graphrag_retriever", graphrag_retriever)
    graph.add_node("ontology_lookup", ontology_lookup)
    graph.add_node("sql_generator", sql_generator)
    graph.add_node("sql_validator", sql_validator)
    graph.add_node("sql_executor", sql_executor)
    graph.add_node("response_generator", response_generator)

    # ── Linear edges ─────────────────────────────────────────────────
    graph.add_edge(START, "input_processor")
    graph.add_edge("input_processor", "intent_classifier")
    graph.add_edge("intent_classifier", "entity_extractor")
    graph.add_edge("entity_extractor", "clarity_checker")

    # ── Conditional: after clarity_checker ────────────────────────────
    graph.add_conditional_edges(
        "clarity_checker",
        _route_after_clarity,
        {
            "graphrag_retriever": "graphrag_retriever",
            END: END,
        },
    )

    # ── Continue linear ──────────────────────────────────────────────
    graph.add_edge("graphrag_retriever", "ontology_lookup")
    graph.add_edge("ontology_lookup", "sql_generator")
    graph.add_edge("sql_generator", "sql_validator")

    # ── Conditional: after sql_validator ─────────────────────────────
    graph.add_conditional_edges(
        "sql_validator",
        _route_after_validation,
        {
            "sql_executor": "sql_executor",
            "sql_generator": "sql_generator",
            END: END,
        },
    )

    # ── Final linear path ────────────────────────────────────────────
    graph.add_edge("sql_executor", "response_generator")
    graph.add_edge("response_generator", END)

    # ── Compile ──────────────────────────────────────────────────────
    compiled = graph.compile()
    logger.info("workflow ▸ graph compiled successfully")
    return compiled
