from __future__ import annotations

from pathlib import Path
from typing import Any

from app.services.chat_execution import ChatAgentExecutionService


class FakeAgent:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def run(self, **payload: Any) -> dict[str, Any]:
        self.calls.append(payload)
        return {
            "id": "run-1",
            "status": "completed",
            "answer": "本轮针对性回答",
            "error": None,
        }


class FakeStructuredAI:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[dict[str, Any]] = []

    def build_and_persist(self, **payload: Any) -> dict[str, Any]:
        self.calls.append(payload)
        if self.fail:
            raise RuntimeError("structured unavailable")
        return {"cards": [{"type": "research_summary"}]}


class FakeDeepStock:
    def observe_chat(self, **payload: Any) -> dict[str, Any]:
        return {"status": "observed", "run_id": payload["run"]["id"]}


class FakeEvidenceTasks:
    def capture_from_chat(self, **payload: Any) -> dict[str, Any]:
        return {"captured": 1, "run_id": payload["run_id"]}


class FakeChatStream:
    def __init__(self) -> None:
        self.progress_events: list[tuple[str, str, dict[str, Any]]] = []
        self.structured_events: list[tuple[dict[str, Any] | None, bool]] = []
        self.completed: list[dict[str, Any]] = []

    def progress(self, stage: str, label: str, **payload: Any) -> None:
        self.progress_events.append((stage, label, payload))

    def forward_agent_progress(self, payload: dict[str, Any]) -> None:
        del payload

    def forward_agent_stream(self, text: str) -> None:
        del text

    def publish_structured(
        self, structured_answer: dict[str, Any] | None, *, failed: bool
    ) -> None:
        self.structured_events.append((structured_answer, failed))

    def complete(self, **payload: Any) -> None:
        self.completed.append(payload)


def build_service(
    *, structured_fail: bool = False
) -> tuple[ChatAgentExecutionService, FakeAgent, FakeStructuredAI]:
    agent = FakeAgent()
    structured = FakeStructuredAI(fail=structured_fail)
    return (
        ChatAgentExecutionService(
            agent=agent,
            structured_ai=structured,
            deep_stock=FakeDeepStock(),
            evidence_tasks=FakeEvidenceTasks(),
        ),
        agent,
        structured,
    )


def test_chat_execution_module_does_not_import_main() -> None:
    source = Path(__file__).parents[1] / "app/services/chat_execution.py"
    content = source.read_text(encoding="utf-8")
    assert "from app.main import" not in content
    assert "import app.main" not in content


def test_execution_runs_agent_and_persists_complete_response() -> None:
    service, agent, structured = build_service()
    stream = FakeChatStream()
    persisted: list[tuple[dict[str, Any], dict[str, Any]]] = []

    def persist_response(
        response_payload: dict[str, Any], **metadata: Any
    ) -> dict[str, Any]:
        persisted.append((response_payload, metadata))
        return {**response_payload, "conversation_id": "conversation-1"}

    result = service.execute(
        user={"id": "user-1"},
        user_id="user-1",
        intent="stock_research",
        message="分析中兴通讯",
        evidence={"type": "stock_research", "symbol": "000063.SZ"},
        model_tier="economy",
        execute_agent=True,
        image_path=None,
        conversation_id="conversation-1",
        conversation_history=[],
        knowledge_context={"items": []},
        request_started=0.0,
        request_id="request-1",
        symbol="000063.SZ",
        chat_stream=stream,
        persist_response=persist_response,
    )

    assert stream.progress_events[0][0] == "evidence_ready"
    assert callable(agent.calls[0]["progress_callback"])
    assert callable(agent.calls[0]["stream_callback"])
    assert structured.calls[0]["symbol"] == "000063.SZ"
    assert persisted[0][0]["structured_answer"] == {
        "cards": [{"type": "research_summary"}]
    }
    assert persisted[0][0]["evidence_tasks"] == {
        "captured": 1,
        "run_id": "run-1",
    }
    assert persisted[0][1]["run_id"] == "run-1"
    assert stream.completed == [{"status": "completed", "run_id": "run-1"}]
    assert result["answer"] == "本轮针对性回答"


def test_structured_failure_keeps_valid_agent_answer() -> None:
    service, agent, _ = build_service(structured_fail=True)
    stream = FakeChatStream()
    persisted: list[dict[str, Any]] = []

    def persist_response(
        response_payload: dict[str, Any], **metadata: Any
    ) -> dict[str, Any]:
        del metadata
        persisted.append(response_payload)
        return response_payload

    result = service.execute(
        user={"id": "user-2"},
        user_id="user-2",
        intent="market_brief",
        message="美股为什么跌",
        evidence={"type": "market_brief"},
        model_tier="economy",
        execute_agent=False,
        image_path=None,
        conversation_id="conversation-2",
        conversation_history=[],
        knowledge_context={"items": []},
        request_started=0.0,
        request_id=None,
        symbol=None,
        chat_stream=stream,
        persist_response=persist_response,
    )

    assert agent.calls[0]["stream_callback"] is None
    assert stream.structured_events == [(None, True)]
    assert persisted[0]["answer"] == "本轮针对性回答"
    assert persisted[0]["structured_answer"] is None
    assert result["status"] == "completed"


def test_read_only_execution_skips_mutation_capable_collaborators() -> None:
    service, _, structured = build_service()
    stream = FakeChatStream()

    result = service.execute(
        user={"id": "user-3"},
        user_id="user-3",
        intent="market_brief",
        message="今天市场怎么样",
        evidence={"type": "market_brief"},
        model_tier="economy",
        execute_agent=False,
        image_path=None,
        conversation_id="conversation-3",
        conversation_history=[],
        knowledge_context={"items": []},
        request_started=0.0,
        request_id=None,
        symbol=None,
        chat_stream=stream,
        persist_response=lambda response_payload, **metadata: {
            **response_payload,
            **metadata,
        },
        read_only=True,
    )

    assert structured.calls == []
    assert result["structured_answer"] is None
    assert result["evidence_tasks"] == {}
    assert result["deep_stock_session"] is None
