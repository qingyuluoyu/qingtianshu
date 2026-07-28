from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.services.chat_context import (
    ChatConversationNotFound,
    ChatRequestContextService,
    ChatUploadExpired,
    ChatUploadNotFound,
    build_financial_advisor_context,
)


class FakeDatabase:
    def __init__(self) -> None:
        self.conversation: dict[str, Any] | None = None
        self.history: list[dict[str, Any]] = []
        self.messages: list[dict[str, Any]] = []
        self.upload: dict[str, Any] | None = None
        self.used_uploads: list[str] = []

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
