"""
Query orchestrator — single entry point coordinating the full chat→answer pipeline.
Wires up all query_engine modules extracted from the legacy app.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
import uuid as uuid_mod
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories import (
    audit_repository,
    message_repository,
    session_repository,
)
from app.query_engine.answer_generator import build_answer, build_general_llm_answer
from app.query_engine.errors import AppError
from app.query_engine.helpers import (
    augment_tasks_for_placeholders,
    build_task_result_context,
    dedupe,
    make_json_safe,
    parse_property_ref,
    resolve_task_placeholders,
)
from app.query_engine.plan_validator import validate_plan
from app.query_engine.planner import build_plan, build_planner_context
from app.query_engine.router import route_question
from app.query_engine.sql_compiler import build_task_sql
from app.query_engine.sql_executor import execute_sql
from app.query_engine.sql_validator import validate_and_repair_sql, validate_sql_safety
from app.schemas.chat import ChatResponse, MessageResponse
from app.services.cache_service import RedisCacheService
from app.services.context_service import ContextService
from app.services.profile_manager import ProfileManager

logger = logging.getLogger(__name__)

MAX_QUESTION_LENGTH = 1500


class QueryOrchestrator:
    """End-to-end handler for a user chat message."""

    def __init__(
        self,
        cache_service: RedisCacheService,
        neo4j_repo: Any,
        profile_manager: ProfileManager,
    ) -> None:
        self._cache = cache_service
        self._neo4j = neo4j_repo
        self._profile_manager = profile_manager
        self._context_service = ContextService(cache_service)

    async def process_chat_message(
        self,
        user_id: str,
        session_id: str,
        message: str,
        db: AsyncSession,
    ) -> ChatResponse:
        """Process one user message through the full pipeline."""
        start = time.perf_counter()
        error_text: Optional[str] = None
        route_info: Optional[Dict[str, Any]] = None
        planner_json: Optional[Dict[str, Any]] = None
        raw_sql_list: Optional[List[str]] = None
        final_sql_list: Optional[List[str]] = None
        validation_trace_list: Optional[List[Any]] = None
        result_summary: Optional[Dict[str, Any]] = None
        answer_text: str = ""
        is_clarification = False

        uid = UUID(user_id)
        sid = UUID(session_id)

        try:
            # ── 1. Validate session ownership ───────────────────
            session = await session_repository.get_session(db, session_id=sid, user_id=uid)
            if session is None:
                raise PermissionError("Session not found or access denied")

            profile = session.profile

            # ── 2. Validate input ───────────────────────────────
            if not message.strip():
                raise AppError("Please enter a question.")
            if len(message) > MAX_QUESTION_LENGTH:
                raise AppError(f"Question too long. Max {MAX_QUESTION_LENGTH} characters.")

            # ── 3. Save user message ────────────────────────────
            user_msg = await message_repository.create_message(
                db,
                message_id=uuid_mod.uuid4(),
                session_id=sid,
                role="user",
                content=message,
            )

            # ── 4. Build context ────────────────────────────────
            context = await self._context_service.get_context(sid, uid, db)
            recent_messages = context.get("recent_messages", [])

            # Build a conversation transcript from recent messages
            # for the router and planner to understand follow-ups.
            conversation_parts: list[str] = []
            for msg in recent_messages:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if content:
                    # Truncate very long assistant responses to save tokens
                    if role == "assistant" and len(content) > 500:
                        content = content[:500] + "..."
                    conversation_parts.append(f"{role}: {content}")
            context_text = "\n".join(conversation_parts) if conversation_parts else ""

            # ── 5. Check query cache ────────────────────────────
            cached = await self._cache.get_cached_query_result(uid, profile, message)
            if cached is not None:
                logger.info("Query cache HIT")
                answer_text = cached.get("answer", "")
                route_info = cached.get("route")
                planner_json = cached.get("plan")
                final_sql_list = cached.get("sql")
                result_summary = cached.get("results")
                validation_trace_list = cached.get("validation_trace")
            else:
                # ── 6. Route ────────────────────────────────────
                route_info = await route_question(message, context_text)

                if route_info["route"] == "general_chat":
                    # ── General chat path ───────────────────────
                    answer_text = await build_general_llm_answer(message, context_text)
                else:
                    # ── DB query path ───────────────────────────
                    result = await self._execute_db_pipeline(
                        question=message,
                        profile=profile,
                        route=route_info,
                        context_text=context_text,
                    )
                    answer_text = result["answer"]
                    planner_json = result.get("plan")
                    raw_sql_list = result.get("raw_sql")
                    final_sql_list = result.get("sql")
                    validation_trace_list = result.get("validation_trace")
                    result_summary = result.get("results")
                    is_clarification = result.get("is_clarification", False)

                # ── 7. Cache result ─────────────────────────────
                await self._cache.cache_query_result(
                    uid, profile, message,
                    {
                        "answer": answer_text,
                        "route": route_info,
                        "plan": planner_json,
                        "sql": final_sql_list,
                        "validation_trace": validation_trace_list,
                        "results": result_summary,
                    },
                )

        except PermissionError:
            raise
        except Exception as exc:
            logger.exception("Pipeline error for session=%s", session_id)
            error_text = str(exc)
            answer_text = f"❌ Error: {error_text}"

        # ── 8. Save assistant message ───────────────────────────
        assistant_msg = await message_repository.create_message(
            db,
            message_id=uuid_mod.uuid4(),
            session_id=sid,
            role="assistant",
            content=answer_text,
            metadata_={
                "route": route_info,
                "is_clarification": is_clarification,
                "has_error": error_text is not None,
                "sql": final_sql_list,
            },
        )

        # ── 9. Save audit ──────────────────────────────────────
        duration_ms = int((time.perf_counter() - start) * 1000)
        await audit_repository.create_audit(
            db,
            audit_id=uuid_mod.uuid4(),
            user_id=uid,
            session_id=sid,
            message_id=assistant_msg.id,
            profile=session.profile if session else None,
            question=message,
            route=route_info,
            planner_json=planner_json,
            raw_sql=raw_sql_list,
            final_sql=final_sql_list,
            validation_trace=validation_trace_list,
            result_summary=result_summary,
            answer=answer_text,
            duration_ms=duration_ms,
            error=error_text,
        )

        # ── 10. Update cache ───────────────────────────────────
        await self._cache.cache_recent_messages(
            sid,
            [{"role": "user", "content": message},
             {"role": "assistant", "content": answer_text}],
        )

        # ── 11. Build response ─────────────────────────────────
        msg_response = MessageResponse(
            id=assistant_msg.id,
            session_id=sid,
            role=assistant_msg.role,
            content=assistant_msg.content,
            metadata_=assistant_msg.metadata_,
            created_at=assistant_msg.created_at,
        )

        return ChatResponse(
            message=msg_response,
            route=route_info,
            plan=planner_json,
            sql=final_sql_list,
            validation_trace=validation_trace_list,
            results=result_summary,
            is_clarification=is_clarification,
        )

    async def _execute_db_pipeline(
        self,
        question: str,
        profile: str,
        route: Dict[str, Any],
        context_text: str = "",
    ) -> Dict[str, Any]:
        """Execute the ontology → planner → SQL → execute → answer pipeline.

        Sync operations (Neo4j, MSSQL) run in threadpool.
        """
        repo = self._neo4j
        engine = self._profile_manager.get_engine(profile)

        if engine is None:
            raise AppError(f"No MSSQL engine available for profile: {profile}")
        if repo is None:
            raise AppError("Neo4j repository not available")

        # Get schema cache (sync, run in thread)
        entity_lookup = await asyncio.to_thread(repo.get_entity_table_lookup, profile)
        from app.ontology.neo4j_repository import introspect_schema
        schema_cache = await asyncio.to_thread(introspect_schema, engine, list(entity_lookup.values()))

        # Build ontology context (sync)
        context = await asyncio.to_thread(build_planner_context, profile, question, repo)

        # Build plan (async — calls LLM)
        plan = await build_plan(profile, question, route, context, repo, schema_cache, conversation_context=context_text)

        if plan.get("question_type") == "general_chat":
            answer = await build_general_llm_answer(question, context_text)
            return {"answer": answer, "plan": plan, "is_clarification": False}

        if plan.get("needs_clarification"):
            reason = plan.get("clarification_reason") or "Please clarify your question."
            return {
                "answer": f"⚠️ {reason}",
                "plan": plan,
                "is_clarification": True,
            }

        # Execute plan tasks
        task_outputs: List[Dict[str, Any]] = []
        task_contexts: Dict[str, Dict[str, Any]] = {}
        tasks = await asyncio.to_thread(augment_tasks_for_placeholders, plan.get("tasks", []), repo)

        for task in tasks:
            resolved = resolve_task_placeholders(task, task_contexts)

            # Build SQL (sync)
            raw_sql = await asyncio.to_thread(build_task_sql, resolved, profile, repo)

            # Validate and repair (async — calls LLM for repair)
            final_sql, vtrace = await validate_and_repair_sql(
                engine=engine,
                question=question,
                profile_name=profile,
                task=resolved,
                sql=raw_sql,
                repo=repo,
                schema_cache=schema_cache,
            )

            # Execute (sync)
            result = await asyncio.to_thread(execute_sql, engine, final_sql)

            task_outputs.append({
                "task": resolved,
                "sql": final_sql,
                "raw_sql": raw_sql,
                "validation_trace": vtrace,
                "result": result,
            })

            task_id = resolved.get("task_id")
            if task_id:
                task_contexts[task_id] = build_task_result_context(resolved, result)

        # Merge results
        merged: Dict[str, Any] = {
            "task_outputs": task_outputs,
            "combine_strategy": plan.get("combine_strategy", "none"),
        }

        if (plan.get("combine_strategy") == "compare_on_dimension"
                and len(task_outputs) >= 2
                and plan.get("comparison_dimension")):
            comp_entity, comp_col = parse_property_ref(plan["comparison_dimension"])
            comp_alias = f"{comp_entity}_{comp_col}".lower()
            keyed: Dict[Any, Dict[str, Any]] = {}

            for idx, out in enumerate(task_outputs, start=1):
                cols = out["result"]["columns"]
                rows = out["result"]["rows"]
                if comp_alias not in cols:
                    continue
                comp_idx = cols.index(comp_alias)
                metric_idx = cols.index("metric_value") if "metric_value" in cols else None
                for row in rows:
                    key = row[comp_idx]
                    if key not in keyed:
                        keyed[key] = {comp_alias: key}
                    if metric_idx is not None:
                        metric_name = out["task"].get("metric_name") or f"task_{idx}"
                        keyed[key][metric_name] = row[metric_idx]

            merged["combined_rows"] = list(keyed.values())
            merged["combined_columns"] = dedupe(
                [comp_alias] + [k for row in merged["combined_rows"] for k in row.keys() if k != comp_alias]
            )

        # Generate answer (async — calls LLM)
        answer = await build_answer(question, profile, plan, merged, context_text)

        return {
            "answer": answer,
            "plan": plan,
            "raw_sql": [o["raw_sql"] for o in task_outputs],
            "sql": [o["sql"] for o in task_outputs],
            "validation_trace": [o["validation_trace"] for o in task_outputs],
            "results": make_json_safe(merged),
            "is_clarification": False,
        }
