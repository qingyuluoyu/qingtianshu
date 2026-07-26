from __future__ import annotations

import pytest

from app.db import Database


class RecordingQueue:
    def __init__(self) -> None:
        self.calls = 0

    def publish_pending(self, limit: int = 100) -> int:
        self.calls += 1
        return 1


def test_dispatcher_persists_pending_task_and_publishes_once(tmp_path) -> None:
    from app.services.research_dispatcher import ResearchDispatcher

    database = Database(tmp_path / "qingshu.db", tmp_path / "workspaces")
    database.initialize()
    user = database.create_user("dispatcher")
    conversation = database.create_conversation(user["id"], "研究")
    queue = RecordingQueue()

    dispatcher = ResearchDispatcher(database, queue)
    run = dispatcher.submit(
        user_id=user["id"], conversation_id=conversation["id"],
        targets=[{"symbol": "300750.SZ", "name": "宁德时代"}],
        question="研究问题", idempotency_key="dispatch-key-0001",
    )

    assert run["execution_status"] == "pending"
    assert database.get_research_task(run["task_id"])["status"] == "pending"
    assert queue.calls == 1


def test_dispatcher_enforces_per_user_concurrency_before_second_task(tmp_path):
    from app.services.research_dispatcher import ResearchDispatcher

    database = Database(tmp_path / "qingshu.db", tmp_path / "workspaces")
    database.initialize()
    user = database.create_user("limited dispatcher")
    first_conversation = database.create_conversation(user["id"], "first")
    second_conversation = database.create_conversation(user["id"], "second")
    queue = RecordingQueue()
    dispatcher = ResearchDispatcher(database, queue, max_concurrent_per_user=1)

    dispatcher.submit(
        user_id=user["id"],
        conversation_id=first_conversation["id"],
        targets=[{"symbol": "000063.SZ", "name": "中兴通讯"}],
        question="first question",
        idempotency_key="dispatcher-limit-key-0001",
    )

    with pytest.raises(ValueError, match="research_concurrency_limit"):
        dispatcher.submit(
            user_id=user["id"],
            conversation_id=second_conversation["id"],
            targets=[{"symbol": "300308.SZ", "name": "中际旭创"}],
            question="second question",
            idempotency_key="dispatcher-limit-key-0002",
        )

    assert queue.calls == 1


def test_http_research_submission_uses_fast_dispatcher_when_configured(
    client, app, monkeypatch
):
    from app.services.research_dispatcher import ResearchDispatcher

    created_user = client.post("/users", json={"name": "fast enqueue user"})
    assert created_user.status_code == 201
    queue = RecordingQueue()
    app.state.research_dispatcher = ResearchDispatcher(app.state.database, queue)
    monkeypatch.setattr(
        app.state.research_evidence,
        "build",
        lambda *_args, **_kwargs: pytest.fail(
            "evidence collection must not run in the request thread"
        ),
    )

    response = client.post(
        "/me/ai-research/runs",
        headers={"Idempotency-Key": "http-fast-enqueue-key-0001"},
        json={
            "question": "研究中兴通讯的经营质量",
            "targets": [{"symbol": "000063.SZ", "name": "中兴通讯"}],
        },
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["execution_status"] == "pending"
    assert payload["task_id"]
    assert queue.calls == 1
    assert response.headers["idempotency-key"] == "http-fast-enqueue-key-0001"
    task = app.state.database.get_research_task(payload["task_id"])
    assert task["request_id"] == response.headers["x-request-id"]
    assert task["trace_id"] == response.headers["x-trace-id"]
    assert task["timeout_seconds"] == 900
