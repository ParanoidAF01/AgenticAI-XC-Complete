"""
WorkflowState — the single TypedDict that flows through every LangGraph node.

All fields use ``total=False`` so each node can return a *partial* update
containing only the keys it changes.  LangGraph merges the partial dict
back into the full state automatically.
"""

from __future__ import annotations

from typing import TypedDict


class WorkflowState(TypedDict, total=False):
    """Shared state object passed between every node in the LangGraph pipeline.

    Fields
    ------
    session_id : str
        Unique identifier for the current conversation session.
    user_query : str
        Raw user input as received from the API layer.
    cleaned_query : str
        Sanitised / normalised version of the query produced by
        ``input_processor``.
    intent : str | None
        Classified intent — one of COUNT, LIST, AGGREGATE, COMPARE,
        LOOKUP, OTHER.
    intent_confidence : float
        Model confidence (0‑1) in the classified intent.
    entities : list[dict]
        Extracted entities (both SpaCy NER + LLM domain extraction).
    ontology_context : dict
        Resolved ontology relationships (tables, joins, columns).
    graphrag_context : dict
        Semantic context retrieved via Neo4j GraphRAG.
    schema_context : dict
        Concrete SQL schema details (columns, data types, FKs).
    generated_sql : str | None
        The SQL statement produced by the LLM.
    sql_valid : bool
        Whether ``sql_validator`` approved the generated SQL.
    sql_error : str | None
        Human‑readable validation error when ``sql_valid`` is False.
    query_result : list[dict] | None
        Rows returned from SQL execution (list of dicts).
    result_count : int
        Number of rows in ``query_result``.
    final_response : str | None
        Natural‑language answer sent back to the user.
    needs_clarification : bool
        True when the pipeline cannot proceed without more info.
    clarification_question : str | None
        Question to ask the user when clarification is needed.
    retry_count : int
        Number of SQL‑generation retry attempts (max 3).
    current_node : str
        Name of the node that last updated state (for tracing).
    tables_used : list[str]
        Table names referenced in the generated SQL.
    execution_time_ms : float
        Wall‑clock time (ms) for SQL execution.
    error : str | None
        Non‑recoverable error message; set instead of raising.
    """

    session_id: str
    user_query: str
    cleaned_query: str
    intent: str | None
    intent_confidence: float
    entities: list[dict]
    ontology_context: dict
    graphrag_context: dict
    schema_context: dict
    generated_sql: str | None
    sql_valid: bool
    sql_error: str | None
    query_result: list[dict] | None
    result_count: int
    final_response: str | None
    needs_clarification: bool
    clarification_question: str | None
    retry_count: int
    current_node: str
    tables_used: list[str]
    execution_time_ms: float
    error: str | None
