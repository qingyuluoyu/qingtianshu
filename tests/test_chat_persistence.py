from __future__ import annotations

from pathlib import Path
from typing import Any

from app.services.chat_persistence import ChatResponsePersistence


class FakeDatabase:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    def add_conversation_message(self, **payload: Any) -> dict[str, Any]:
        self.messages.append(payload)
        return {"id": f"message-{len(self.messages)}"}


class FakeConversationQuality:
    def __init__(self) -> None:
        self.user_ids: list[str] = []

    def analyze(self, user_id: str) -> dict[str, Any]:
        self.user_ids.append(user_id)
        return {}


def build_service() -> tuple[ChatResponsePersistence, FakeDatabase, FakeConversationQuality]:
    database = FakeDatabase()
    quality = FakeConversationQuality()
    return ChatResponsePersistence(database, quality), database, quality  # type: ignore[arg-type]


def test_chat_persistence_does_not_import_main() -> None:
    source = Path(__file__).parents[1] / "app/services/chat_persistence.py"
    content = source.read_text(encoding="utf-8")
    assert "from app.main import" not in content
    assert "import app.main" not in content


def test_focused_price_move_persists_evidence_not_generic_library_sources() -> None:
    service, database, quality = build_service()
    result = service.persist(
        {"answer": "当前回答"},
        user_id="user-1",
        conversation={"title": "中兴通讯为什么大跌"},
        conversation_id="conversation-1",
        knowledge_context={
            "items": [
                {"document_id": "doc-1", "title": "旧研究", "scope": "user"}
            ],
            "coverage": {"matched_documents": 1},
        },
        model_tier="economy",
        assistant_content="当前回答",
        response_intent="stock_research",
        response_symbol="000063.SZ",
        evidence_payload={
            "type": "stock_research",
            "user_question": "中兴通讯为什么大跌",
            "display_name": "中兴通讯",
        },
    )

    metadata = database.messages[0]["metadata"]
    assert metadata["knowledge_sources"] == []
    assert metadata["research_targets"] == [
        {"symbol": "000063.SZ", "name": "中兴通讯"}
    ]
    assert metadata["conversation_scope"] == "stock"
    assert result["assistant_message_id"] == "message-1"
    assert result["knowledge"]["coverage"] == {"matched_documents": 1}
    assert quality.user_ids == ["user-1"]


def test_relative_industry_persists_only_selected_evidence_sources() -> None:
    service, database, _ = build_service()
    result = service.persist(
        {"answer": "相对行业回答"},
        user_id="user-relative-industry",
        conversation={"title": "宁德时代相对电池行业"},
        conversation_id="conversation-relative-industry",
        knowledge_context={
            "items": [
                {
                    "document_id": "doc-generic",
                    "title": "无关通用资料",
                    "scope": "common",
                }
            ],
            "coverage": {"matched_documents": 1},
        },
        model_tier="deep",
        assistant_content="相对行业回答",
        response_intent="stock_research",
        response_symbol="300750.SZ",
        evidence_payload={
            "type": "stock_research",
            "user_question": "宁德时代相对电池行业表现如何",
            "display_name": "宁德时代",
            "research_plan": {"focus": "relative_industry"},
            "visible_evidence_sources": [
                {"title": "CS电池同日行情", "kind": "industry_comparison"}
            ],
        },
    )

    assert database.messages[0]["metadata"]["knowledge_sources"] == []
    assert result["knowledge"]["items"] == []
    assert result["knowledge"]["coverage"] == {"matched_documents": 1}


def test_comparison_persists_all_structured_research_targets() -> None:
    service, database, _ = build_service()
    result = service.persist(
        {"answer": "比较结果"},
        user_id="user-2",
        conversation={"title": "比较公司"},
        conversation_id="conversation-2",
        knowledge_context={"items": [], "coverage": {}},
        model_tier="deep",
        assistant_content="比较结果",
        response_intent="stock_comparison",
        evidence_payload={
            "targets": [
                {"symbol": "000063.SZ", "name": "中兴通讯"},
                {"symbol": "NVDA", "name": "英伟达"},
            ]
        },
    )

    expected = [
        {"symbol": "000063.SZ", "name": "中兴通讯"},
        {"symbol": "NVDA", "name": "英伟达"},
    ]
    assert database.messages[0]["metadata"]["research_targets"] == expected
    assert database.messages[0]["metadata"]["conversation_scope"] == "stock"
    assert result["research_targets"] == expected


def test_fund_context_persists_a_dedicated_conversation_scope() -> None:
    service, database, _ = build_service()
    service.persist(
        {"answer": "基金回答"},
        user_id="user-fund",
        conversation={"title": "股票基金还是债券基金"},
        conversation_id="conversation-fund",
        knowledge_context={"items": [], "coverage": {}},
        model_tier="economy",
        assistant_content="基金回答",
        response_intent="general_research",
        evidence_payload={
            "financial_advisor_context": {"status": "needs_profile"},
        },
    )

    assert database.messages[0]["metadata"]["conversation_scope"] == "funds"
