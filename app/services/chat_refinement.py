from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

from fastapi import HTTPException

from app.api_models import ChatRefineRequest
from app.services.chat_knowledge_context import (
    _filter_knowledge_context as filter_knowledge_context,
)


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ChatRefinementService:
    database: Any
    knowledge: Any
    agent: Any
    evidence_tasks: Any
    deep_stock: Any
    structured_ai: Any
    conversation_quality: Any

    _allowed_intents = {
        "market_brief",
        "stock_screen",
        "stock_research",
        "stock_comparison",
        "earnings_quality",
        "financial_drivers",
        "business_structure",
        "shareholder_structure",
        "analyst_expectations",
        "event_timeline",
        "research_tracking",
        "research_priority",
        "research_actions",
        "research_outcome",
        "watchlist_brief",
        "general_research",
    }

    def refine(
        self, user: dict[str, Any], payload: ChatRefineRequest
    ) -> dict[str, Any]:
        user_id = str(user["id"])
        conversation = self.database.get_conversation(
            user_id, payload.conversation_id
        )
        if conversation is None or conversation.get("status") != "active":
            raise HTTPException(status_code=404, detail="研究对话不存在")

        preview_run = self.database.get_run(payload.preview_run_id, user_id)
        if (
            preview_run is None
            or preview_run.get("intent") not in self._allowed_intents
        ):
            raise HTTPException(status_code=404, detail="待深化研究不存在")

        assistant_message = self.database.get_conversation_message(
            user_id, payload.assistant_message_id
        )
        if (
            assistant_message is None
            or assistant_message.get("conversation_id") != payload.conversation_id
            or assistant_message.get("role") != "assistant"
        ):
            raise HTTPException(status_code=404, detail="待深化回答不存在")
        if assistant_message.get("run_id") != payload.preview_run_id:
            return {
                "status": "already_refined",
                "intent": assistant_message.get("intent"),
                "answer": assistant_message.get("content"),
                "conversation_id": payload.conversation_id,
                "assistant_message_id": payload.assistant_message_id,
                "run_id": assistant_message.get("run_id"),
                "structured_answer": (assistant_message.get("metadata") or {}).get(
                    "structured_answer"
                ),
            }

        evidence = preview_run.get("evidence") or {}
        input_data = preview_run.get("input") or {}
        message = str(input_data.get("message") or "").strip()
        if not message or not evidence:
            raise HTTPException(status_code=422, detail="待深化研究缺少可复用证据")

        history = self.database.list_conversation_messages(
            user_id, payload.conversation_id, limit=80
        )
        preview_index = next(
            (
                index
                for index, item in enumerate(history)
                if item.get("id") == payload.assistant_message_id
            ),
            len(history),
        )
        conversation_history = history[:preview_index]
        knowledge_context = evidence.get(
            "knowledge_context"
        ) or self.knowledge.retrieve(user_id, message, max_results=5)
        refine_symbol = (
            evidence.get("symbol")
            or (evidence.get("item") or {}).get("symbol")
            or (assistant_message.get("metadata") or {}).get("symbol")
        )
        knowledge_context = filter_knowledge_context(
            knowledge_context,
            intent=str(preview_run["intent"]),
            symbol=str(refine_symbol) if refine_symbol else None,
            evidence=evidence,
        )
        run = self.agent.run(
            user=user,
            intent=str(preview_run["intent"]),
            message=message,
            evidence=evidence,
            model_tier=payload.model_tier,
            execute_agent=True,
            conversation_id=payload.conversation_id,
            conversation_history=conversation_history,
            knowledge_context=knowledge_context,
        )
        if run.get("status") != "completed":
            return {
                "status": "kept_preview",
                "intent": preview_run.get("intent"),
                "answer": assistant_message.get("content"),
                "conversation_id": payload.conversation_id,
                "assistant_message_id": payload.assistant_message_id,
                "run_id": payload.preview_run_id,
            }

        self.evidence_tasks.capture_from_chat(
            user_id=user_id,
            conversation_id=payload.conversation_id,
            run_id=run["id"],
            intent=str(preview_run["intent"]),
            message=message,
            evidence=evidence,
            symbol=str(refine_symbol) if refine_symbol else None,
        )
        deep_stock_session = self.deep_stock.observe_chat(
            user_id=user_id,
            conversation_id=payload.conversation_id,
            symbol=str(refine_symbol) if refine_symbol else None,
            intent=str(preview_run["intent"]),
            message=message,
            run=run,
            evidence=evidence,
        )

        structured_answer = None
        try:
            structured_answer = self.structured_ai.build_and_persist(
                user_id=user_id,
                run=run,
                evidence=evidence,
                answer=str(run.get("answer") or ""),
                message=message,
                conversation_id=payload.conversation_id,
                symbol=str(refine_symbol) if refine_symbol else None,
            )
        except Exception:
            logger.exception(
                "Failed to persist refined structured AI answer for run %s",
                run.get("id"),
            )

        metadata = {
            **(assistant_message.get("metadata") or {}),
            "model_tier": payload.model_tier,
            "refined": True,
            "structured_answer": structured_answer,
        }
        updated = self.database.update_assistant_conversation_message(
            user_id=user_id,
            conversation_id=payload.conversation_id,
            message_id=payload.assistant_message_id,
            content=run["answer"],
            intent=str(preview_run["intent"]),
            run_id=run["id"],
            metadata=metadata,
        )
        if updated is None:
            raise HTTPException(status_code=409, detail="回答已发生变化，请刷新对话")
        try:
            self.conversation_quality.analyze(user_id)
        except Exception:
            pass
        return {
            "status": "completed",
            "intent": preview_run.get("intent"),
            "answer": run["answer"],
            "conversation_id": payload.conversation_id,
            "assistant_message_id": payload.assistant_message_id,
            "run_id": run["id"],
            "deep_stock_session": deep_stock_session,
            "structured_answer": structured_answer,
        }
