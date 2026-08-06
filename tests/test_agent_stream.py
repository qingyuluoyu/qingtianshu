from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.services.agent_stream import AgentStreamBroker


def _decode_sse(chunk: str) -> dict:
    assert chunk.startswith("data: ")
    return json.loads(chunk.removeprefix("data: ").strip())


def test_agent_stream_is_private_to_its_user():
    broker = AgentStreamBroker()
    broker.open("request-private-001", "alice")
    broker.publish(
        "request-private-001",
        "alice",
        {"type": "agent_delta", "draft": "只属于 Alice 的累计草稿。"},
    )

    with pytest.raises(PermissionError):
        next(broker.stream("request-private-001", "bob"))


def test_agent_stream_reconnect_replays_latest_accumulated_draft():
    broker = AgentStreamBroker()
    request_id = "request-replay-001"
    broker.open(request_id, "alice")

    first_connection = broker.stream(request_id, "alice")
    assert _decode_sse(next(first_connection))["type"] == "agent_stream_connected"
    broker.publish(
        request_id,
        "alice",
        {"type": "agent_delta", "draft": "第一句。"},
    )
    assert _decode_sse(next(first_connection))["draft"] == "第一句。"
    first_connection.close()

    broker.publish(
        request_id,
        "alice",
        {"type": "agent_delta", "draft": "第一句。第二句。"},
    )
    reconnected = broker.stream(request_id, "alice")
    assert _decode_sse(next(reconnected))["type"] == "agent_stream_connected"
    replay = _decode_sse(next(reconnected))

    assert replay["type"] == "agent_delta"
    assert replay["draft"] == "第一句。第二句。"
    reconnected.close()


def test_agent_stream_terminal_event_closes_iterator():
    broker = AgentStreamBroker()
    request_id = "request-terminal-001"
    broker.open(request_id, "alice")
    stream = broker.stream(request_id, "alice")
    next(stream)

    broker.publish(
        request_id,
        "alice",
        {"type": "agent_stream_complete", "status": "completed"},
    )
    terminal = _decode_sse(next(stream))

    assert terminal["type"] == "agent_stream_complete"
    with pytest.raises(StopIteration):
        next(stream)


def test_private_stream_endpoint_rejects_another_session(app):
    alice = TestClient(app)
    bob = TestClient(app)
    alice_id = alice.post("/users", json={"name": "Stream Alice"}).json()["id"]
    bob.post("/users", json={"name": "Stream Bob"})
    request_id = "request-route-private-001"
    app.state.agent_streams.open(request_id, alice_id)
    app.state.agent_streams.publish(
        request_id,
        alice_id,
        {"type": "agent_stream_complete", "status": "completed"},
    )

    rejected = bob.get(f"/me/chat/stream/{request_id}")
    accepted = alice.get(f"/me/chat/stream/{request_id}")

    assert rejected.status_code == 404
    assert accepted.status_code == 200
    assert "agent_stream_complete" in accepted.text
