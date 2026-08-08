from __future__ import annotations

import time
from typing import Any

from app.services.chat_streaming import ChatStreamPublisher


class FakeEventBroker:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def publish(self, event: dict[str, Any]) -> None:
        self.events.append(event)


class FakeAgentStreams:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict[str, Any]]] = []

    def publish(
        self, request_id: str, user_id: str, event: dict[str, Any]
    ) -> None:
        self.events.append((request_id, user_id, event))


def build_publisher(
    *, enabled: bool = True
) -> tuple[ChatStreamPublisher, FakeEventBroker, FakeAgentStreams]:
    public = FakeEventBroker()
    private = FakeAgentStreams()
    publisher = ChatStreamPublisher(
        event_broker=public,  # type: ignore[arg-type]
        agent_streams=private,  # type: ignore[arg-type]
        request_id="request-1" if enabled else None,
        user_id="user-1",
        execute_agent=enabled,
        started_at=time.perf_counter(),
    )
    return publisher, public, private


def test_disabled_chat_stream_publishes_nothing() -> None:
    publisher, public, private = build_publisher(enabled=False)
    publisher.progress("routing_started", "开始")
    publisher.forward_agent_stream({"type": "delta", "draft": "回答"})
    publisher.publish_structured({"citations": [{"id": "c1"}]}, failed=False)
    publisher.complete(status="completed", run_id="run-1")
    assert public.events == []
    assert private.events == []


def test_progress_is_published_to_public_and_private_channels() -> None:
    publisher, public, private = build_publisher()
    publisher.progress("routing_started", "正在识别", detail="value")
    assert public.events[0]["type"] == "agent_progress"
    assert public.events[0]["request_id"] == "request-1"
    assert public.events[0]["detail"] == "value"
    assert private.events[0][2] == public.events[0]


def test_agent_callbacks_preserve_private_stream_protocol() -> None:
    publisher, _, private = build_publisher()
    publisher.forward_agent_progress(
        {"phase": "guard_started", "model_seconds": 2.5}
    )
    publisher.forward_agent_stream(
        {
            "type": "delta",
            "draft": "当前回答",
            "event_index": 2,
            "is_unverified": True,
            "is_guarded_partial": True,
        }
    )
    publisher.forward_agent_stream({"type": "reset"})
    publisher.publish_structured(
        {
            "status": "partial",
            "citations": [{"id": "citation-1"}],
            "candidate_writebacks": [{"id": "candidate-1"}],
        },
        failed=False,
    )
    publisher.complete(status="completed", run_id="run-1")

    event_types = [event[2]["type"] for event in private.events]
    assert event_types == [
        "agent_progress",
        "agent_delta",
        "agent_stream_status",
        "agent_citation",
        "agent_writeback_candidate",
        "agent_structured_partial",
        "agent_stream_complete",
    ]
    assert private.events[1][2]["draft"] == "当前回答"
    assert private.events[1][2]["is_guarded_partial"] is True
    assert private.events[2][2]["reset"] is True
    assert private.events[-1][2]["run_id"] == "run-1"


def test_structured_failure_is_reported_without_hiding_answer() -> None:
    publisher, _, private = build_publisher()
    publisher.publish_structured(None, failed=True)
    assert private.events == [
        (
            "request-1",
            "user-1",
            {"type": "agent_structured_failed", "status": "failed"},
        )
    ]
