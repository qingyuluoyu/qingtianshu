from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.services.chat_routing import (
    _conversation_title,
    _extract_industry_topic,
    _extract_symbols,
    _intent_from_history,
    _is_analyst_expectations_query,
    _is_business_structure_query,
    _is_contextual_followup,
    _is_earnings_quality_query,
    _is_event_timeline_query,
    _is_financial_driver_query,
    _is_li_zong_strategy_followup,
    _is_market_query,
    _is_peer_comparison_query,
    _is_shareholder_query,
    _is_stock_screen_query,
    _market_question_focus,
    _prefers_stock_context_followup,
    _stock_screen_profile_from_history,
    _symbol_from_history,
    _symbols_from_history,
)


class ChatConversationNotFound(LookupError):
    pass


class ChatUploadNotFound(LookupError):
    pass


class ChatUploadExpired(LookupError):
    pass


@dataclass(slots=True)
class PreparedChatContext:
    message: str
    conversation: dict[str, Any]
    conversation_id: str
    history: list[dict[str, Any]]
    symbols: list[str]
    symbol: str | None
    prior_intent: str | None
    contextual_followup: bool
    stock_context_followup: bool
    explicit_market_query: bool
    explicit_industry_topic: str | None
    explicit_stock_screen_query: bool
    prior_screen_profile: str | None
    stock_screen_query: bool
    explicit_li_zong_query: bool
    li_zong_query: bool
    peer_comparison_query: bool
    stock_comparison_query: bool
    financial_driver_query: bool
    earnings_quality_query: bool
    business_structure_query: bool
    shareholder_query: bool
    analyst_expectations_query: bool
    event_timeline_query: bool
    analyst_expectations_context: bool
    event_timeline_context: bool
    upload: dict[str, Any] | None
    image_path: str | None
    model_tier: str
    knowledge_context: dict[str, Any]


def _knowledge_request(
    *,
    message: str,
    symbol: str | None,
    prior_intent: str | None,
    contextual_followup: bool,
    explicit_market_query: bool,
    li_zong_query: bool,
    stock_screen_query: bool,
    stock_comparison_query: bool,
    analyst_expectations_context: bool,
    event_timeline_context: bool,
) -> tuple[str, list[str] | None]:
    query = message
    required_sources: list[str] | None = None
    if (explicit_market_query and symbol is None) or (
        prior_intent == "market_brief" and contextual_followup
    ):
        question_focus = _market_question_focus(message)
        query = (
            f"{message} 市场涨跌原因 证据规则 清数智算证据层级 "
            f"市场趋势与风险分析规则 {question_focus['label']}"
        )
        required_sources = [
            "builtin:evidence-hierarchy.md",
            "builtin:market-causality.md",
            "builtin:market-trend-risk.md",
        ]
    elif li_zong_query:
        query = (
            f"{message} 李总策略 确定性规则 基本面 股性 量价 "
            "真实涨停价 复权新高 三日放量 历史回放 无前视 "
            "沪深300 超额表现 数据缺失 人工复核"
        )
    elif stock_screen_query:
        query = (
            f"{message} 透明选股 研究候选 财务质量 估值约束 "
            "相对行业表现 反方证据 风险边界"
        )
    elif stock_comparison_query:
        query = (
            f"{message} 多股统一口径比较 报告期可比性 盈利质量 估值 "
            "业务差异 反方证据 风险边界"
        )
    elif analyst_expectations_context:
        query = (
            f"{message} 分析师一致预期 券商研报 EPS修订 评级覆盖 "
            "预测不是公司指引 评级不是交易建议"
        )
    elif event_timeline_context:
        query = (
            f"{message} 公司公告 监管文件 重要事件 催化风险 "
            "官方披露 媒体线索 原文复核"
        )
    return query, required_sources


class ChatRequestContextService:
    def __init__(self, database: Any, knowledge: Any) -> None:
        self.database = database
        self.knowledge = knowledge

    def prepare(
        self,
        *,
        user_id: str,
        message: str,
        conversation_id: str | None,
        quality_scope: str,
        requested_symbol: str | None,
        image_id: str | None,
        model_tier: str,
    ) -> PreparedChatContext:
        message = message.strip()
        if conversation_id:
            conversation = self.database.get_conversation(user_id, conversation_id)
            if conversation is None or conversation.get("status") != "active":
                raise ChatConversationNotFound
        else:
            conversation = self.database.create_conversation(
                user_id,
                _conversation_title(message),
                quality_scope=quality_scope,
            )
        resolved_conversation_id = str(conversation["id"])
        history = self.database.list_conversation_messages(
            user_id, resolved_conversation_id, limit=40
        )
        if not history and conversation.get("title") == "新的研究对话":
            conversation = (
                self.database.rename_conversation(
                    user_id,
                    resolved_conversation_id,
                    _conversation_title(message),
                )
                or conversation
            )

        symbols = _extract_symbols(
            requested_symbol,
            message,
            watchlist=self.database.list_watchlist(user_id),
        )
        symbol = symbols[0] if len(symbols) == 1 else None
        prior_intent = _intent_from_history(history)
        contextual_followup = _is_contextual_followup(message)
        stock_context_followup = (
            contextual_followup and _prefers_stock_context_followup(message)
        )
        if not symbols and prior_intent == "stock_comparison" and contextual_followup:
            symbols = _symbols_from_history(history)
            symbol = symbols[0] if len(symbols) == 1 else None

        explicit_market_query = _is_market_query(message)
        explicit_industry_topic = _extract_industry_topic(message)
        explicit_stock_screen_query = _is_stock_screen_query(message)
        prior_screen_profile = _stock_screen_profile_from_history(history)
        stock_screen_query = explicit_stock_screen_query or (
            prior_intent == "stock_screen" and contextual_followup
        )
        explicit_li_zong_query = "李总" in message and any(
            keyword in message for keyword in ("策略", "选股", "候选", "触发", "规则")
        )
        li_zong_query = explicit_li_zong_query or (
            prior_intent == "stock_screen"
            and prior_screen_profile == "li_zong"
            and (contextual_followup or _is_li_zong_strategy_followup(message))
        )
        peer_comparison_query = _is_peer_comparison_query(message)
        stock_comparison_query = (
            len(symbols) >= 2
            and not explicit_stock_screen_query
            and not explicit_li_zong_query
        )
        financial_driver_query = (
            _is_financial_driver_query(message) and not peer_comparison_query
        )
        earnings_quality_query = (
            _is_earnings_quality_query(message) and not peer_comparison_query
        )
        business_structure_query = (
            _is_business_structure_query(message) and not peer_comparison_query
        )
        shareholder_query = _is_shareholder_query(message)
        analyst_expectations_query = _is_analyst_expectations_query(message)
        event_timeline_query = _is_event_timeline_query(message)
        analyst_expectations_context = analyst_expectations_query or (
            prior_intent == "analyst_expectations" and contextual_followup
        )
        event_timeline_context = event_timeline_query or (
            prior_intent == "event_timeline" and contextual_followup
        )
        if symbol is None and stock_context_followup:
            symbol = _symbol_from_history(history)
        if (
            symbol is None
            and (not explicit_market_query or li_zong_query or stock_context_followup)
            and prior_intent
            in {
                "stock_research",
                "research_tracking",
                "research_outcome",
                "earnings_quality",
                "financial_drivers",
                "business_structure",
                "shareholder_structure",
                "analyst_expectations",
                "event_timeline",
                "stock_screen",
            }
            and (
                contextual_followup
                or li_zong_query
                or earnings_quality_query
                or financial_driver_query
                or business_structure_query
                or shareholder_query
                or analyst_expectations_query
                or event_timeline_query
            )
        ):
            symbol = _symbol_from_history(history)

        upload: dict[str, Any] | None = None
        image_path: str | None = None
        resolved_model_tier = model_tier
        if image_id:
            upload = self.database.get_user_upload(user_id, image_id)
            if upload is None:
                raise ChatUploadNotFound
            image_path = str(upload["workspace_path"])
            if not Path(image_path).is_file():
                raise ChatUploadExpired
            self.database.mark_user_upload_used(user_id, image_id)
            resolved_model_tier = "vision"

        knowledge_query, required_knowledge_sources = _knowledge_request(
            message=message,
            symbol=symbol,
            prior_intent=prior_intent,
            contextual_followup=contextual_followup,
            explicit_market_query=explicit_market_query,
            li_zong_query=li_zong_query,
            stock_screen_query=stock_screen_query,
            stock_comparison_query=stock_comparison_query,
            analyst_expectations_context=analyst_expectations_context,
            event_timeline_context=event_timeline_context,
        )
        knowledge_context = self.knowledge.retrieve(
            user_id,
            knowledge_query,
            max_results=5,
            required_source_keys=required_knowledge_sources,
        )
        self.database.add_conversation_message(
            user_id=user_id,
            conversation_id=resolved_conversation_id,
            role="user",
            content=message,
            metadata={
                "image_id": image_id,
                "model_tier": resolved_model_tier,
            },
        )

        return PreparedChatContext(
            message=message,
            conversation=conversation,
            conversation_id=resolved_conversation_id,
            history=history,
            symbols=symbols,
            symbol=symbol,
            prior_intent=prior_intent,
            contextual_followup=contextual_followup,
            stock_context_followup=stock_context_followup,
            explicit_market_query=explicit_market_query,
            explicit_industry_topic=explicit_industry_topic,
            explicit_stock_screen_query=explicit_stock_screen_query,
            prior_screen_profile=prior_screen_profile,
            stock_screen_query=stock_screen_query,
            explicit_li_zong_query=explicit_li_zong_query,
            li_zong_query=li_zong_query,
            peer_comparison_query=peer_comparison_query,
            stock_comparison_query=stock_comparison_query,
            financial_driver_query=financial_driver_query,
            earnings_quality_query=earnings_quality_query,
            business_structure_query=business_structure_query,
            shareholder_query=shareholder_query,
            analyst_expectations_query=analyst_expectations_query,
            event_timeline_query=event_timeline_query,
            analyst_expectations_context=analyst_expectations_context,
            event_timeline_context=event_timeline_context,
            upload=upload,
            image_path=image_path,
            model_tier=resolved_model_tier,
            knowledge_context=knowledge_context,
        )


__all__ = [
    "ChatConversationNotFound",
    "ChatRequestContextService",
    "ChatUploadExpired",
    "ChatUploadNotFound",
    "PreparedChatContext",
]
