"""
Answer generator — LLM-powered answer synthesis from query results.
Extracted from legacy app lines 109–117, 1519–1548.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict

from app.query_engine.helpers import make_json_safe
from app.query_engine.llm_client import call_llm
from app.query_engine.prompts import ANSWER_SYSTEM_PROMPT, GENERAL_CHAT_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


async def build_general_llm_answer(question: str, context: str = "") -> str:
    """
    Generate a natural language response for a general (non-DB) question.
    Optionally includes conversation context.
    """
    payload: Dict[str, Any] = {"user_message": question}
    if context:
        payload["conversation_context"] = context

    messages = [
        {"role": "system", "content": GENERAL_CHAT_SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(payload, indent=2)},
    ]
    return (await call_llm(messages, max_tokens=400)).strip()


async def build_answer(
    question: str,
    profile_name: str,
    plan: Dict[str, Any],
    execution_output: Dict[str, Any],
    context: str = "",
) -> str:
    """
    Generate a natural language answer from execution results.
    Preserves the exact legacy payload structure for the LLM.
    """
    # Truncate results to save tokens — LLM doesn't need 500 rows
    MAX_ANSWER_ROWS = 25
    truncated_outputs = []
    for t in execution_output.get("task_outputs", []):
        result_copy = dict(t["result"])
        rows = result_copy.get("rows", [])
        if len(rows) > MAX_ANSWER_ROWS:
            result_copy["rows"] = rows[:MAX_ANSWER_ROWS]
            result_copy["truncated"] = True
            result_copy["total_row_count"] = len(rows)
        truncated_outputs.append({**t, "result": result_copy})

    payload: Dict[str, Any] = {
        "user_question": question,
        "database_profile": profile_name,
        "plan_summary": {
            "question_type": plan.get("question_type"),
            "intent": plan.get("intent"),
            "requires_multi_task": plan.get("requires_multi_task"),
            "combine_strategy": plan.get("combine_strategy"),
            "comparison_dimension": plan.get("comparison_dimension"),
            "tasks": [
                {
                    "task_id": t["task"].get("task_id"),
                    "task_type": t["task"].get("task_type"),
                    "metric_name": t["task"].get("metric_name"),
                    "selected_properties": t["task"].get("selected_properties", []),
                    "row_count": t["result"].get("row_count", 0),
                }
                for t in truncated_outputs
            ],
        },
        "results": {**execution_output, "task_outputs": truncated_outputs},
    }
    if context:
        payload["conversation_context"] = context

    messages = [
        {"role": "system", "content": ANSWER_SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(make_json_safe(payload), indent=2)},
    ]
    return (await call_llm(messages, max_tokens=1000)).strip()
