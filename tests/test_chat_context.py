from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.services.chat_context import (
    ChatConversationNotFound,
    ChatRequestContextService,
    ChatUploadExpired,
    ChatUploadNotFound,
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
