from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.services.chat_context import (
    ChatConversationNotFound,
    ChatRequestContextService,
    ChatUploadExpired,
    ChatUploadNotFound,
    _knowledge_request,
    build_financial_advisor_context,
)


class FakeDatabase:
    def __init__(self) -> None:
        self.conversation: dict[str, Any] | None = None
        self.history: list[dict[str, Any]] = []
        self.messages: list[dict[str, Any]] = []
        self.upload: dict[str, Any] | None = None
        self.used_uploads: list[str] = []
        self.deep_stock: dict[str, Any] | None = None
        self.universe_items: list[dict[str, Any]] = []

    def get_conversation(self, user_id: str, conversation_id: str):
        del user_id, conversation_id
        return self.conversation

    def create_conversation(
        self, user_id: str, title: str, *, quality_scope: str
    ) -> dict[str, Any]:
        del user_id
        self.conversation = {
            "id": "conversation-1",
            "title": title,
            "status": "active",
            "quality_scope": quality_scope,
        }
        return self.conversation

    def list_conversation_messages(
        self, user_id: str, conversation_id: str, *, limit: int
    ) -> list[dict[str, Any]]:
        del user_id, conversation_id, limit
        return list(self.history)

    def rename_conversation(
        self, user_id: str, conversation_id: str, title: str
    ) -> dict[str, Any] | None:
        del user_id, conversation_id
        if self.conversation is not None:
            self.conversation["title"] = title
        return self.conversation

    def list_watchlist(self, user_id: str) -> list[dict[str, Any]]:
        del user_id
        return []

    def get_user_upload(self, user_id: str, image_id: str):
        del user_id, image_id
        return self.upload

    def mark_user_upload_used(self, user_id: str, image_id: str) -> None:
        del user_id
        self.used_uploads.append(image_id)

    def add_conversation_message(self, **payload: Any) -> dict[str, Any]:
        self.messages.append(payload)
        return {"id": f"message-{len(self.messages)}"}

    def get_deep_stock_session_by_conversation(
        self, user_id: str, conversation_id: str
    ) -> dict[str, Any] | None:
        del user_id, conversation_id
        return self.deep_stock

    def latest_tushare_dataset_snapshot(
        self, dataset: str, scope_key: str
    ) -> dict[str, Any] | None:
        assert dataset == "a_share_universe"
        assert scope_key == "all"
        return {
            "data_version": "chat-context-test-v1",
            "payload": {"items": list(self.universe_items)},
        }


class FakeKnowledge:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def retrieve(
        self,
        user_id: str,
        query: str,
        *,
        max_results: int,
        required_source_keys: list[str] | None,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "user_id": user_id,
                "query": query,
                "max_results": max_results,
                "required_source_keys": required_source_keys,
            }
        )
        return {"items": [], "coverage": {"matched_documents": 0}}


def build_service() -> tuple[ChatRequestContextService, FakeDatabase, FakeKnowledge]:
    database = FakeDatabase()
    knowledge = FakeKnowledge()
    return ChatRequestContextService(database, knowledge), database, knowledge


def test_chat_context_module_does_not_import_main() -> None:
    source = Path(__file__).parents[1] / "app/services/chat_context.py"
    content = source.read_text(encoding="utf-8")
    assert "from app.main import" not in content
    assert "import app.main" not in content


def test_prepare_creates_conversation_and_requires_market_knowledge() -> None:
    service, database, knowledge = build_service()

    prepared = service.prepare(
        user_id="user-1",
        message="美股为什么收盘跌了",
        conversation_id=None,
        quality_scope="product",
        requested_symbol=None,
        image_id=None,
        model_tier="economy",
    )

    assert prepared.conversation_id == "conversation-1"
    assert prepared.explicit_market_query is True
    assert prepared.symbol is None
    assert knowledge.calls[0]["required_source_keys"] == [
        "builtin:evidence-hierarchy.md",
        "builtin:market-causality.md",
        "builtin:market-trend-risk.md",
    ]
    assert "市场涨跌原因" in knowledge.calls[0]["query"]
    assert database.messages[0]["role"] == "user"
    assert database.messages[0]["metadata"]["model_tier"] == "economy"


def test_market_experience_gap_uses_only_causality_reference() -> None:
    _, sources, max_results = _knowledge_request(
        message=(
            "今天为什么指数表现和大多数个股的体感不一样？"
            "请结合成交额自然回答。"
        ),
        symbol=None,
        prior_intent=None,
        contextual_followup=False,
        explicit_market_query=True,
        li_zong_query=False,
        stock_screen_query=False,
        stock_comparison_query=False,
        analyst_expectations_context=False,
        event_timeline_context=False,
    )

    assert sources == ["builtin:market-causality.md"]
    assert max_results == 1


def test_short_market_observation_followup_skips_repeated_rule_documents() -> None:
    query, sources, max_results = _knowledge_request(
        message="不要重复刚才的数字，接下来最值得观察哪两个变量？",
        symbol=None,
        prior_intent="market_brief",
        contextual_followup=True,
        explicit_market_query=False,
        li_zong_query=False,
        stock_screen_query=False,
        stock_comparison_query=False,
        analyst_expectations_context=False,
        event_timeline_context=False,
    )

    assert query == "不要重复刚才的数字，接下来最值得观察哪两个变量？"
    assert sources is None
    assert max_results == 0


def test_prepare_resolves_full_a_share_name_from_security_master() -> None:
    service, database, _ = build_service()
    database.universe_items = [
        {
            "symbol": "000065.SZ",
            "name": "北方国际",
            "industry": "建筑装饰",
            "market": "主板",
        }
    ]

    prepared = service.prepare(
        user_id="user-a-share-name",
        message="北方国际最近为什么下跌，现金流有什么变化？",
        conversation_id=None,
        quality_scope="evaluation",
        requested_symbol=None,
        image_id=None,
        model_tier="economy",
    )

    assert prepared.symbol == "000065.SZ"
    assert prepared.symbols == ["000065.SZ"]


def test_prepare_requires_financial_education_sources_for_fund_etf_question() -> None:
    service, _, knowledge = build_service()

    prepared = service.prepare(
        user_id="user-finance",
        message="基金和ETF有什么区别，哪个更适合长期持有？",
        conversation_id=None,
        quality_scope="product",
        requested_symbol=None,
        image_id=None,
        model_tier="economy",
    )

    assert prepared.symbol is None
    assert knowledge.calls[0]["required_source_keys"] == [
        "builtin:fund-etf-practical-guide.md",
        "builtin:risk-return-and-allocation.md",
        "builtin:financial-products-basics.md",
    ]
    assert knowledge.calls[0]["max_results"] == 4
    assert "底层资产" in knowledge.calls[0]["query"]
    assert "适合性" in knowledge.calls[0]["query"]


def test_prepare_requires_risk_and_bond_guides_for_suitability_question() -> None:
    service, _, knowledge = build_service()

    service.prepare(
        user_id="user-bond",
        message="退休后债券基金适不适合我，我需要保留流动性",
        conversation_id=None,
        quality_scope="product",
        requested_symbol=None,
        image_id=None,
        model_tier="economy",
    )

    assert knowledge.calls[0]["required_source_keys"] == [
        "builtin:fund-etf-practical-guide.md",
        "builtin:fixed-income-and-rates.md",
        "builtin:risk-return-and-allocation.md",
        "builtin:financial-products-basics.md",
    ]
    assert knowledge.calls[0]["max_results"] == 5


def test_financial_advisor_context_keeps_retirement_question_conditional() -> None:
    context = build_financial_advisor_context(
        "我快退休了，有一笔闲钱，股票基金和债券基金哪个更适合我？"
    )

    assert context is not None
    assert context["mode"] == "product_suitability"
    assert context["status"] == "needs_profile"
    assert "资金使用时间" in context["missing_fields"]
    assert "可接受回撤" in context["missing_fields"]
    assert "资金使用时间" in context["missing_fields"]
    assert "可接受回撤" in context["missing_fields"]
    assert any("不根据年龄推断收入" in item for item in context["hard_boundaries"])


def test_financial_advisor_context_treats_beginner_choice_as_suitability() -> None:
    context = build_financial_advisor_context(
        "基金和ETF有什么区别？如果我是刚开始理财的普通投资者，"
        "应该根据哪些条件选择？信息不足时请先给选择逻辑，不要替我下结论。"
    )

    assert context is not None
    assert context["mode"] == "product_suitability"
    assert context["status"] == "needs_profile"


def test_financial_advisor_context_keeps_beginner_explanation_concept_only() -> None:
    context = build_financial_advisor_context(
        "基金和ETF到底是什么关系？请用小白能看懂的话简短说明。",
        confirmed_profile={
            "version_no": 1,
            "answer_labels": {
                "fund_use_horizon": "长期不用",
                "loss_tolerance": "可以接受一定波动",
            },
        },
    )

    assert context is not None
    assert context["status"] == "concept_only"
    assert "confirmed_risk_profile" not in context


def test_confirmed_risk_profile_does_not_invent_existing_assets() -> None:
    confirmed_profile = {
        "version_no": 1,
        "answer_labels": {
            "fund_use_horizon": "长期不用",
            "liquidity_need": "可以等待到账",
            "loss_tolerance": "会不安，但能先核验原因",
            "emergency_reserve": "已单独准备",
            "debt_burden": "负债压力较小",
            "investment_experience": "刚开始了解",
            "primary_objective": "在波动与增长之间平衡",
        },
        "derived": {"constraints": ["产品规则需要用通俗语言解释"]},
    }

    context = build_financial_advisor_context(
        "请结合我已经确认的风险画像，帮我梳理哪些基金和ETF更适合我优先比较。",
        confirmed_profile=confirmed_profile,
    )

    assert context is not None
    assert context["mode"] == "product_suitability"
    assert context["status"] == "needs_profile"
    assert context["provided_fields"] == [
        "资金使用时间",
        "可接受回撤",
        "应急储备",
        "负债情况",
    ]
    assert context["missing_fields"] == ["已有资产"]
    assert context["confirmed_risk_profile"]["version_no"] == 1

    completed = build_financial_advisor_context(
        "请结合我的风险画像帮我选择。我目前主要持有银行存款，没有基金和股票。",
        confirmed_profile=confirmed_profile,
    )
    assert completed is not None
    assert completed["status"] == "ready_for_conditional_guidance"
    assert completed["missing_fields"] == []

    natural_followup = build_financial_advisor_context(
        "我目前主要持有银行存款，没有基金和股票。"
        "请基于这些已知条件继续帮我缩小优先比较范围。",
        confirmed_profile=confirmed_profile,
    )
    assert natural_followup is not None
    assert natural_followup["mode"] == "product_suitability"
    assert natural_followup["status"] == "ready_for_conditional_guidance"
    assert natural_followup["missing_fields"] == []


def test_prepare_restores_stock_target_for_contextual_followup() -> None:
    service, database, _ = build_service()
    database.conversation = {
        "id": "conversation-2",
        "title": "中兴通讯研究",
        "status": "active",
    }
    database.history = [
        {
            "role": "assistant",
            "intent": "stock_research",
            "metadata": {
                "symbol": "000063.SZ",
                "research_targets": [{"symbol": "000063.SZ"}],
            },
        }
    ]

    prepared = service.prepare(
        user_id="user-2",
        message="它相对通信设备行业更强还是更弱",
        conversation_id="conversation-2",
        quality_scope="product",
        requested_symbol=None,
        image_id=None,
        model_tier="economy",
    )

    assert prepared.symbol == "000063.SZ"
    assert prepared.contextual_followup is True
    assert prepared.stock_context_followup is True
    assert prepared.explicit_market_query is True


def test_bound_deep_stock_defaults_to_current_symbol_for_natural_research() -> None:
    service, database, _ = build_service()
    database.conversation = {
        "id": "conversation-bound",
        "title": "北方国际研究",
        "status": "active",
    }
    database.deep_stock = {"symbol": "000065.SZ"}

    prepared = service.prepare(
        user_id="user-bound",
        message=(
            "最近20日下跌8.04%，这次回撤最可能与哪些已经确认的公司事件、"
            "财务和现金流变化有关？请先直接回答，再说明哪些原因目前没有证据；"
            "同时判断近5日0.00%能不能算企稳。不要复述选股卡片。"
        ),
        conversation_id="conversation-bound",
        quality_scope="product",
        requested_symbol=None,
        image_id=None,
        model_tier="deep",
    )

    assert prepared.symbol == "000065.SZ"
    assert prepared.symbols == ["000065.SZ"]
    assert prepared.explicit_stock_screen_query is False
    assert prepared.stock_screen_query is False


def test_bound_quality_review_keeps_current_stock_when_requesting_industry_boundary():
    service, database, _ = build_service()
    database.conversation = {
        "id": "conversation-bound-quality",
        "title": "宁德时代研究",
        "status": "active",
    }
    database.deep_stock = {"symbol": "300750.SZ"}

    prepared = service.prepare(
        user_id="user-bound-quality",
        message=(
            "这家公司为什么进入经营改善候选？请结合最新公告、同报告期财务、"
            "经营现金流、主营结构和行业口径，直接说明改善是否有质量。"
        ),
        conversation_id="conversation-bound-quality",
        quality_scope="evaluation",
        requested_symbol=None,
        image_id=None,
        model_tier="deep",
    )

    assert prepared.symbol == "300750.SZ"
    assert prepared.symbols == ["300750.SZ"]
    assert prepared.explicit_stock_screen_query is False
    assert prepared.stock_screen_query is False


def test_bound_quality_review_correction_does_not_restart_whole_market_screening():
    service, database, _ = build_service()
    database.conversation = {
        "id": "conversation-bound-quality-correction",
        "title": "宁德时代研究",
        "status": "active",
    }
    database.deep_stock = {"symbol": "300750.SZ"}

    prepared = service.prepare(
        user_id="user-bound-quality-correction",
        message=(
            "请重新核对经营改善候选：投资者关系记录表已明确写出"
            "‘库存增加主要是为下半年市场需求而提前备货’。请据此修正上一回答，"
            "区分公司已解释的备货原因，与仍需量化核验的库存分类、库龄、"
            "订单覆盖和跌价准备；同时保留毛利率、现金流和行业边界。"
            "不要讨论其他候选，不要自行设定库龄阈值，不要编造行业数据。"
        ),
        conversation_id="conversation-bound-quality-correction",
        quality_scope="evaluation",
        requested_symbol=None,
        image_id=None,
        model_tier="deep",
    )

    assert prepared.symbol == "300750.SZ"
    assert prepared.symbols == ["300750.SZ"]
    assert prepared.explicit_market_query is False
    assert prepared.explicit_industry_topic is None
    assert prepared.explicit_stock_screen_query is False
    assert prepared.stock_screen_query is False


def test_stock_margin_language_does_not_load_fixed_income_education() -> None:
    assert (
        build_financial_advisor_context(
            "继续核验这家公司的毛利率、净利率、现金流和行业边界。"
        )
        is None
    )


def test_bound_peer_valuation_question_uses_fixed_peers_as_evidence() -> None:
    service, database, _ = build_service()
    database.conversation = {
        "id": "conversation-bound-valuation",
        "title": "宁德时代研究",
        "status": "active",
    }
    database.deep_stock = {"symbol": "300750.SZ"}
    database.universe_items = [
        {"symbol": "300750.SZ", "name": "宁德时代"},
        {"symbol": "300014.SZ", "name": "亿纬锂能"},
        {"symbol": "002074.SZ", "name": "国轩高科"},
        {"symbol": "300207.SZ", "name": "欣旺达"},
    ]

    prepared = service.prepare(
        user_id="user-bound-valuation",
        message=(
            "宁德时代的PE和PB分别相对亿纬锂能、国轩高科、欣旺达处于什么位置？"
            "不要简单说便宜或贵，请结合同行经营口径缺失说明估值约束。"
        ),
        conversation_id="conversation-bound-valuation",
        quality_scope="evaluation",
        requested_symbol=None,
        image_id=None,
        model_tier="deep",
    )

    assert prepared.symbol == "300750.SZ"
    assert prepared.symbols == ["300750.SZ"]
    assert prepared.peer_comparison_query is True
    assert prepared.explicit_stock_screen_query is False
    assert prepared.stock_screen_query is False
    assert prepared.stock_comparison_query is False


def test_bound_deep_stock_ignores_single_letter_section_label() -> None:
    service, database, _ = build_service()
    database.conversation = {
        "id": "conversation-bound",
        "title": "北方国际研究",
        "status": "active",
    }
    database.deep_stock = {"symbol": "000065.SZ"}

    prepared = service.prepare(
        user_id="user-bound",
        message=(
            "交互验收B：请继续用三段话说明这些财务压力能确认什么、"
            "不能解释什么，以及近5日走平为什么还不能叫企稳。"
        ),
        conversation_id="conversation-bound",
        quality_scope="product",
        requested_symbol=None,
        image_id=None,
        model_tier="economy",
    )

    assert prepared.symbol == "000065.SZ"
    assert prepared.symbols == ["000065.SZ"]


def test_named_stock_followup_leaves_legacy_screening_conversation() -> None:
    service, database, _ = build_service()
    database.conversation = {
        "id": "conversation-legacy-screening",
        "title": "个股研究｜北方国际",
        "status": "active",
    }
    database.universe_items = [
        {
            "symbol": "000065.SZ",
            "name": "北方国际",
            "industry": "建筑装饰",
            "market": "主板",
        }
    ]
    database.history = [
        {
            "role": "assistant",
            "intent": "stock_screen",
            "metadata": {"stock_screen_profile": "pullback"},
        }
    ]

    prepared = service.prepare(
        user_id="user-legacy-screening",
        message=(
            "请基于最新数据重新回答：北方国际这次回撤与哪些已确认的财务、"
            "经营现金流和公司事件有关？哪些只是静态测算或尚无直接因果证据？"
            "近5日走平能不能叫企稳？"
        ),
        conversation_id="conversation-legacy-screening",
        quality_scope="product",
        requested_symbol=None,
        image_id=None,
        model_tier="economy",
    )

    assert prepared.symbol == "000065.SZ"
    assert prepared.symbols == ["000065.SZ"]
    assert prepared.prior_intent == "stock_screen"
    assert prepared.contextual_followup is True
    assert prepared.explicit_stock_screen_query is False
    assert prepared.stock_screen_query is False


def test_bound_deep_stock_only_leaves_for_explicit_scope_change() -> None:
    service, database, _ = build_service()
    database.conversation = {
        "id": "conversation-bound",
        "title": "中兴通讯研究",
        "status": "active",
    }
    database.deep_stock = {"symbol": "000063.SZ"}

    rescreen = service.prepare(
        user_id="user-bound",
        message="请重新筛选A股，给我一批新的股票候选",
        conversation_id="conversation-bound",
        quality_scope="product",
        requested_symbol=None,
        image_id=None,
        model_tier="deep",
    )
    assert rescreen.symbol is None
    assert rescreen.stock_screen_query is True

    fund_question = service.prepare(
        user_id="user-bound",
        message="基金和ETF有什么区别？",
        conversation_id="conversation-bound",
        quality_scope="product",
        requested_symbol=None,
        image_id=None,
        model_tier="deep",
    )
    assert fund_question.symbol is None
    assert fund_question.stock_screen_query is False

    market_question = service.prepare(
        user_id="user-bound",
        message="今天A股大盘和哪些板块在领涨？",
        conversation_id="conversation-bound",
        quality_scope="product",
        requested_symbol=None,
        image_id=None,
        model_tier="deep",
    )
    assert market_question.symbol is None
    assert market_question.explicit_market_query is True
    assert market_question.stock_screen_query is False

    industry_question = service.prepare(
        user_id="user-bound",
        message="通信设备行业最近走势怎么样？",
        conversation_id="conversation-bound",
        quality_scope="product",
        requested_symbol=None,
        image_id=None,
        model_tier="deep",
    )
    assert industry_question.symbol is None
    assert industry_question.explicit_industry_topic == "通信设备"
    assert industry_question.stock_screen_query is False


def test_prepare_validates_conversation_and_upload_lifecycle(tmp_path: Path) -> None:
    service, database, _ = build_service()
    database.conversation = {"id": "closed", "title": "旧对话", "status": "archived"}
    with pytest.raises(ChatConversationNotFound):
        service.prepare(
            user_id="user-3",
            message="继续研究",
            conversation_id="closed",
            quality_scope="product",
            requested_symbol=None,
            image_id=None,
            model_tier="economy",
        )

    database.conversation = None
    with pytest.raises(ChatUploadNotFound):
        service.prepare(
            user_id="user-3",
            message="分析这张图",
            conversation_id=None,
            quality_scope="product",
            requested_symbol=None,
            image_id="missing",
            model_tier="economy",
        )

    database.upload = {"workspace_path": str(tmp_path / "expired.png")}
    with pytest.raises(ChatUploadExpired):
        service.prepare(
            user_id="user-3",
            message="分析这张图",
            conversation_id=None,
            quality_scope="product",
            requested_symbol=None,
            image_id="expired",
            model_tier="economy",
        )

    image = tmp_path / "current.png"
    image.write_bytes(b"image")
    database.upload = {"workspace_path": str(image)}
    prepared = service.prepare(
        user_id="user-3",
        message="分析这张图",
        conversation_id=None,
        quality_scope="product",
        requested_symbol=None,
        image_id="current",
        model_tier="economy",
    )
    assert prepared.model_tier == "vision"
    assert prepared.image_path == str(image)
    assert database.used_uploads == ["current"]
