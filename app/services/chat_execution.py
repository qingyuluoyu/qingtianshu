from __future__ import annotations

from collections.abc import Callable
import logging
import time
from typing import Any

from app.services.evidence_presentation import agent_evidence_progress


logger = logging.getLogger(__name__)


class ChatAgentExecutionService:
    def __init__(
        self,
        *,
        agent: Any,
        structured_ai: Any,
        deep_stock: Any,
        evidence_tasks: Any,
    ) -> None:
        self.agent = agent
        self.structured_ai = structured_ai
        self.deep_stock = deep_stock
        self.evidence_tasks = evidence_tasks

    def execute(
        self,
        *,
        user: dict[str, Any],
        user_id: str,
        intent: str,
        message: str,
        evidence: dict[str, Any],
        model_tier: str,
        execute_agent: bool,
        image_path: str | None,
        conversation_id: str,
        conversation_history: list[dict[str, Any]],
        knowledge_context: dict[str, Any],
        request_started: float,
        request_id: str | None,
        symbol: str | None,
        entry_context: dict[str, Any] | None = None,
        chat_stream: Any,
        persist_response: Callable[..., dict[str, Any]],
        read_only: bool = False,
    ) -> dict[str, Any]:
        chat_stream.progress(
            "evidence_ready",
            "证据与资料已准备，AI 正在组织针对性回答…",
            evidence_progress=agent_evidence_progress(intent, evidence),
        )

        run = self.agent.run(
            user=user,
            intent=intent,
            message=message,
            evidence=evidence,
            model_tier=model_tier,
            execute_agent=execute_agent,
            image_path=image_path,
            conversation_id=conversation_id,
            conversation_history=conversation_history,
            knowledge_context=knowledge_context,
            pre_run_timings={
                "routing_and_evidence_seconds": round(
                    time.perf_counter() - request_started, 3
                )
            },
            progress_callback=chat_stream.forward_agent_progress,
            stream_callback=(
                chat_stream.forward_agent_stream
                if request_id and execute_agent
                else None
            ),
            entry_context=entry_context,
        )

        structured_answer = None
        structured_answer_failed = False
        if not read_only:
            try:
                structured_answer = self.structured_ai.build_and_persist(
                    user_id=user_id,
                    run=run,
                    evidence=evidence,
                    answer=str(run.get("answer") or ""),
                    message=message,
                    conversation_id=conversation_id,
                    symbol=symbol,
                )
            except Exception:
                # Structured cards and writeback candidates must never hide an
                # otherwise valid financial answer. The Run and evidence remain
                # available for diagnosis and a later retry.
                logger.exception(
                    "Failed to persist structured AI answer for run %s",
                    run.get("id"),
                )
                structured_answer_failed = True
                structured_answer = None
        chat_stream.publish_structured(
            structured_answer,
            failed=structured_answer_failed,
        )

        deep_stock_session = None
        captured_evidence_tasks: dict[str, Any] = {}
        if not read_only:
            deep_stock_session = self.deep_stock.observe_chat(
                user_id=user_id,
                conversation_id=conversation_id,
                symbol=symbol,
                intent=intent,
                message=message,
                run=run,
                evidence=evidence,
            )
            captured_evidence_tasks = self.evidence_tasks.capture_from_chat(
                user_id=user_id,
                conversation_id=conversation_id,
                run_id=run["id"],
                intent=intent,
                message=message,
                evidence=evidence,
                symbol=symbol,
            )
        response_payload = {
            "run_id": run["id"],
            "status": run["status"],
            "intent": intent,
            "model_tier": model_tier,
            "answer": run["answer"],
            "evidence": evidence,
            "evidence_tasks": captured_evidence_tasks,
            "deep_stock_session": deep_stock_session,
            "structured_answer": structured_answer,
            "error": run["error"],
        }
        result = persist_response(
            response_payload,
            assistant_content=run["answer"],
            response_intent=intent,
            response_symbol=symbol,
            run_id=run["id"],
            evidence_payload=evidence,
            structured_answer=structured_answer,
        )
        chat_stream.complete(status=run["status"], run_id=run["id"])
        return result


__all__ = ["ChatAgentExecutionService"]
