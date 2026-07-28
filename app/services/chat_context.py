from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
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


def _prefers_bound_candidate_research(message: str) -> bool:
    """Keep one-stock candidate follow-ups in its long-term research conversation."""

    folded = re.sub(r"\s+", "", message).casefold()
    broad_screening_terms = (
        "筛选a股",
        "筛a股",
        "筛选股票",
        "筛股票",
        "候选股票",
        "股票候选",
        "找几只",
        "挑几只",
        "选几只",
        "一批股票",
    )
    research_terms = (
        "为什么进入",
        "为什么入选",
        "入选原因",
        "这个逻辑",
        "逻辑还",
        "是否成立",
        "还成立",
        "持续性",
        "反方证据",
        "风险",
        "核验",
    )
    return any(term in folded for term in research_terms) and not any(
        term in folded for term in broad_screening_terms
    )


def _financial_education_sources(message: str) -> list[str]:
    folded = message.casefold().replace(" ", "")
    fund_terms = (
        "基金",
        "etf",
        "指数基金",
        "联接基金",
        "场内基金",
        "场外基金",
        "主动基金",
        "被动基金",
        "基金定投",
    )
    bond_terms = (
        "债券",
        "债基",
        "债券基金",
        "国债",
        "信用债",
        "可转债",
        "利率",
        "降息",
        "加息",
        "久期",
        "固收",
    )
    suitability_terms = (
        "资产配置",
        "怎么配置",
        "如何配置",
        "适合我",
        "适不适合",
        "哪个更适合",
        "哪一个更适合",
        "哪类更适合",
        "怎么选",
        "如何选择",
        "该选",
        "选哪个",
        "风险承受",
        "风险偏好",
        "能亏",
        "亏多少",
        "投资期限",
        "持有多久",
        "应急资金",
        "闲钱",
        "养老",
        "退休",
        "流动性需求",
        "理财产品怎么选",
    )
    product_terms = (
        "金融产品",
        "理财产品",
        "银行理财",
        "货币基金",
        "存款",
        "保险",
        "股票和基金",
        "基金和股票",
        "黄金",
    )

    sources: list[str] = []
    if any(term in folded for term in fund_terms):
        sources.append("builtin:fund-etf-practical-guide.md")
    if any(term in folded for term in bond_terms):
        sources.append("builtin:fixed-income-and-rates.md")
    if any(term in folded for term in suitability_terms):
        sources.append("builtin:risk-return-and-allocation.md")
    if sources or any(term in folded for term in product_terms):
        sources.append("builtin:financial-products-basics.md")
    return list(dict.fromkeys(sources))


def build_financial_advisor_context(
    message: str,
    *,
    confirmed_profile: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    sources = _financial_education_sources(message)
    if not sources:
        return None
    folded = message.casefold().replace(" ", "")
    explicit_suitability_query = any(
        term in folded
        for term in (
            "适合我",
            "适不适合",
            "哪个更适合",
            "哪一个更适合",
            "哪类更适合",
            "怎么选",
            "如何选择",
            "该选",
            "选哪个",
            "怎么配置",
            "如何配置",
            "资产配置",
            "直接告诉我",
        )
    )
    personal_context_query = any(
        term in folded
        for term in (
            "如果我是",
            "结合我",
            "根据我",
            "基于我的",
            "基于这些已知条件",
            "基于前面的条件",
            "结合前面的条件",
            "我的风险画像",
            "已确认的风险画像",
            "我应该",
            "我该",
            "对我",
            "普通投资者",
            "刚开始理财",
            "理财新手",
            "投资新手",
            "小白",
        )
    )
    profile_reference_query = any(
        term in folded
        for term in (
            "结合我",
            "根据我",
            "基于我的",
            "基于这些已知条件",
            "基于前面的条件",
            "结合前面的条件",
            "我的风险画像",
            "已确认的风险画像",
            "我应该",
            "我该",
            "对我",
        )
    )
    choice_or_advice_query = any(
        term in folded
        for term in (
            "选择",
            "怎么挑",
            "如何挑",
            "优先比较",
            "先比较",
            "应该比较",
            "下一步",
            "配置",
            "下结论",
        )
    )
    suitability_query = explicit_suitability_query or (
        personal_context_query and choice_or_advice_query
    )
    # Once a user has explicitly confirmed a risk profile, a request to keep
    # narrowing or comparing products is still a suitability follow-up even
    # when they naturally say "continue" instead of repeating "for me".
    if confirmed_profile and (profile_reference_query or choice_or_advice_query):
        suitability_query = True
    if not suitability_query:
        return {
            "mode": "financial_education",
            "status": "concept_only",
            "required_sources": sources,
        }

    field_patterns = {
        "资金使用时间": (
            r"(?:\d+|[一二三四五六七八九十]+)(?:年|个月)",
            r"(?:短期|长期|近期|很快|随时)(?:要用|不用|动用|使用)",
        ),
        "可接受回撤": (
            r"(?:能|可以|不能|无法|不太能).{0,8}(?:接受|承受).{0,8}(?:亏|回撤|波动)",
            r"(?:亏|回撤).{0,8}(?:会卖|不卖|能扛|不能扛)",
        ),
        "应急储备": (
            r"(?:已有|有|没有|无).{0,6}(?:应急金|应急储备|备用金)",
        ),
        "负债情况": (
            r"(?:有|没有|无).{0,6}(?:负债|房贷|车贷|贷款)",
        ),
        "已有资产": (
            r"(?:已有|持有|已经买了|目前有).{0,12}(?:存款|基金|股票|债券|理财|保险|房产)",
        ),
    }
    provided = [
        label
        for label, patterns in field_patterns.items()
        if any(re.search(pattern, folded) for pattern in patterns)
    ]
    if confirmed_profile:
        profile_answers = confirmed_profile.get("answer_labels") or {}
        confirmed_field_map = {
            "资金使用时间": "fund_use_horizon",
            "可接受回撤": "loss_tolerance",
            "应急储备": "emergency_reserve",
            "负债情况": "debt_burden",
            # Reserved for a future questionnaire version. The current seven
            # questions do not ask what the user already owns.
            "已有资产": "existing_assets",
        }
        provided.extend(
            label
            for label, answer_key in confirmed_field_map.items()
            if profile_answers.get(answer_key)
        )
    provided = list(dict.fromkeys(provided))
    missing = [label for label in field_patterns if label not in provided]
    context = {
        "mode": "product_suitability",
        "status": "ready_for_conditional_guidance" if not missing else "needs_profile",
        "provided_fields": provided,
        "missing_fields": missing,
        "required_sources": sources,
        "hard_boundaries": [
            "缺少关键个人事实时，只解释选择逻辑并追问，不判断哪类产品更适合。",
            "不使用自创百分比、金额、期限、配置比例或回撤阈值。",
            "不根据年龄推断收入、工作状态、家庭责任或风险承受能力。",
        ],
    }
    if confirmed_profile:
        context["confirmed_risk_profile"] = confirmed_profile
        context["hard_boundaries"].append(
            "已确认问卷只用于条件化解释，不等同于持牌机构适当性结论或自动产品推荐。"
        )
    return context


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
) -> tuple[str, list[str] | None, int]:
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
    financial_sources = _financial_education_sources(message)
    if financial_sources:
        query = (
            f"{query} 金融产品底层资产 风险收益 流动性 费用 "
            "投资期限 适合性 普通投资者解释"
        )
        required_sources = list(
            dict.fromkeys([*(required_sources or []), *financial_sources])
        )
    max_results = (
        min(5, max(3, len(required_sources or []) + 1))
        if financial_sources
        else 5
    )
    return query, required_sources, max_results


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
        bound_session_lookup = getattr(
            self.database,
            "get_deep_stock_session_by_conversation",
            None,
        )
        bound_deep_stock = (
            bound_session_lookup(user_id, resolved_conversation_id)
            if callable(bound_session_lookup)
            else None
        )
        if bound_deep_stock and _prefers_bound_candidate_research(message):
            bound_symbol = str(bound_deep_stock.get("symbol") or "")
            if not symbols and bound_symbol:
                symbols = [bound_symbol]
                symbol = bound_symbol
            if symbol == bound_symbol:
                explicit_stock_screen_query = False
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

        (
            knowledge_query,
            required_knowledge_sources,
            knowledge_max_results,
        ) = _knowledge_request(
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
            max_results=knowledge_max_results,
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
    "build_financial_advisor_context",
]
