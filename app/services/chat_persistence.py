from __future__ import annotations

from typing import Any

from app.catalog import RESEARCH_TARGETS
from app.db import Database
from app.services.conversation_quality import ConversationQualityService
from app.services.evidence_presentation import build_visible_evidence_sources
from app.services.stock_price_move import is_stock_price_move_question


class ChatResponsePersistence:
    """Persist one assistant response and expose only public conversation metadata."""

    def __init__(
        self,
        database: Database,
        conversation_quality: ConversationQualityService,
    ) -> None:
        self.database = database
        self.conversation_quality = conversation_quality

    @staticmethod
    def _knowledge_sources(
        *,
        response_intent: str,
        evidence_payload: dict[str, Any],
        knowledge_context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        research_focus = str(
            (evidence_payload.get("research_plan") or {}).get("focus") or ""
        ).strip()
        focused_price_move = response_intent == "stock_research" and (
            is_stock_price_move_question(
                str(evidence_payload.get("user_question") or "")
            )
        )
        if focused_price_move or research_focus == "relative_industry":
            return []
        return [
            {
                "document_id": item.get("document_id"),
                "title": item.get("title"),
                "scope": item.get("scope"),
            }
            for item in knowledge_context.get("items", [])
        ]

    @staticmethod
    def _research_targets(
        *,
        response_intent: str,
        response_symbol: str | None,
        evidence_payload: dict[str, Any],
    ) -> list[dict[str, str]]:
        targets: list[dict[str, str]] = []
        if response_intent == "stock_comparison":
            for target in evidence_payload.get("targets") or []:
                target_symbol = str(target.get("symbol") or "").strip()
                if not target_symbol:
                    continue
                targets.append(
                    {
                        "symbol": target_symbol,
                        "name": str(target.get("name") or target_symbol),
                    }
                )
            return targets

        if response_intent == "stock_screen":
            requested = list(evidence_payload.get("requested_symbols") or [])
            if not requested and evidence_payload.get("requested_symbol"):
                requested = [evidence_payload["requested_symbol"]]
            item_targets = {
                str(item.get("internal_symbol") or item.get("symbol")): item
                for item in evidence_payload.get("items") or []
                if item.get("internal_symbol") or item.get("symbol")
            }
            for target_symbol in requested[:10]:
                target = item_targets.get(str(target_symbol)) or {}
                targets.append(
                    {
                        "symbol": str(target_symbol),
                        "name": str(target.get("name") or target_symbol),
                    }
                )
            return targets

        if response_symbol:
            target = RESEARCH_TARGETS.get(response_symbol) or {}
            targets.append(
                {
                    "symbol": response_symbol,
                    "name": str(
                        evidence_payload.get("display_name")
                        or evidence_payload.get("name")
                        or target.get("name")
                        or response_symbol
                    ),
                }
            )
        return targets

    @staticmethod
    def _conversation_scope(
        *,
        response_intent: str,
        response_symbol: str | None,
        evidence_payload: dict[str, Any],
    ) -> str:
        """Persist a stable history category without adding a database column."""

        if evidence_payload.get("fund_product_context") is not None or evidence_payload.get(
            "financial_advisor_context"
        ) is not None:
            return "funds"
        if response_intent == "stock_screen":
            return "screening"
        if response_intent in {"market_brief", "market_pulse_article"}:
            return "market"
        if response_intent in {"watchlist_brief", "watchlist_update"}:
            return "portfolio"
        if response_symbol or response_intent in {
            "stock_research",
            "stock_comparison",
            "analyst_expectations",
            "event_timeline",
            "shareholder_structure",
            "business_structure",
            "financial_drivers",
            "earnings_quality",
            "research_priority",
            "research_actions",
            "research_outcome",
            "research_tracking",
            "visual_research",
        }:
            return "stock"
        return "other"

    def persist(
        self,
        response_payload: dict[str, Any],
        *,
        user_id: str,
        conversation: dict[str, Any],
        conversation_id: str,
        knowledge_context: dict[str, Any],
        model_tier: str,
        assistant_content: str,
        response_intent: str,
        response_symbol: str | None = None,
        run_id: str | None = None,
        evidence_payload: dict[str, Any] | None = None,
        structured_answer: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        evidence = evidence_payload or {}
        sources = self._knowledge_sources(
            response_intent=response_intent,
            evidence_payload=evidence,
            knowledge_context=knowledge_context,
        )
        market_sources = [
            {
                "title": item.get("title"),
                "published_at": item.get("published_at"),
            }
            for item in (evidence.get("market_drivers") or {}).get("items", [])[:6]
        ]
        market_key = (evidence.get("market_drivers") or {}).get("market_key")
        analysis_target = evidence.get("analysis_target") or None
        research_targets = self._research_targets(
            response_intent=response_intent,
            response_symbol=response_symbol,
            evidence_payload=evidence,
        )
        conversation_scope = self._conversation_scope(
            response_intent=response_intent,
            response_symbol=response_symbol,
            evidence_payload=evidence,
        )
        evidence_sources = build_visible_evidence_sources(evidence_payload)
        assistant_message = self.database.add_conversation_message(
            user_id=user_id,
            conversation_id=conversation_id,
            role="assistant",
            content=assistant_content,
            intent=response_intent,
            run_id=run_id,
            metadata={
                "symbol": response_symbol,
                "market_key": market_key,
                "analysis_target": analysis_target,
                "knowledge_sources": sources,
                "market_sources": market_sources,
                "evidence_sources": evidence_sources,
                "research_targets": research_targets,
                "conversation_scope": conversation_scope,
                "structured_answer": structured_answer,
                "model_tier": model_tier,
                "stock_screen_profile": (
                    (evidence.get("profile") or {}).get("key")
                    if response_intent == "stock_screen"
                    else None
                ),
            },
        )
        try:
            self.conversation_quality.analyze(user_id)
        except Exception:
            pass
        return {
            **response_payload,
            "conversation_id": conversation_id,
            "conversation_title": conversation.get("title"),
            "assistant_message_id": assistant_message.get("id"),
            "knowledge": {
                "items": sources,
                "coverage": knowledge_context.get("coverage", {}),
            },
            "evidence_sources": evidence_sources,
            "research_targets": research_targets,
            "structured_answer": structured_answer,
        }


__all__ = ("ChatResponsePersistence",)
