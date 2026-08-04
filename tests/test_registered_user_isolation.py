from __future__ import annotations

from fastapi.testclient import TestClient


def _registered_client(app, *, account: str, phone: str) -> tuple[TestClient, dict]:
    client = TestClient(app)
    response = client.post(
        "/auth/register",
        json={"account": account, "phone": phone, "password": "Password-123"},
    )
    assert response.status_code == 201
    return client, response.json()


def _create_workspace(client: TestClient, thesis: str) -> dict:
    response = client.post(
        "/me/watchlist",
        json={
            "symbol": "000063",
            "name": "中兴通讯",
            "market": "A股",
            "thesis": thesis,
        },
    )
    assert response.status_code == 200
    return client.get("/v1/stocks/000063/workspace").json()


def test_registered_users_cannot_cross_read_or_mutate_real_theses_tasks_or_workspaces(app):
    alice, alice_user = _registered_client(app, account="registered-alice", phone="13800138000")
    bob, _ = _registered_client(app, account="registered-bob", phone="13900139000")
    alice_secret = "仅属于 Alice 的正式判断内容"
    alice_workspace = _create_workspace(alice, alice_secret)
    bob_workspace = _create_workspace(bob, "仅属于 Bob 的正式判断内容")

    assert alice_workspace["relation"]["workspace_id"] != bob_workspace["relation"]["workspace_id"]
    assert alice_workspace["thesis"]["id"] != bob_workspace["thesis"]["id"]

    thesis = alice.post(
        "/v1/stocks/000063/theses",
        json={
            "reason_text": "Alice 的待确认 thesis",
            "watch_items": ["订单兑现"],
            "recheck_conditions": ["核验现金流"],
            "source": "user",
            "base_version": 1,
        },
    )
    assert thesis.status_code == 201
    thesis_id = thesis.json()["id"]
    bob_theses = bob.get("/v1/stocks/000063/theses")
    assert bob_theses.status_code == 200
    assert alice_secret not in bob_theses.text
    for action in ("confirm", "reject"):
        response = bob.post(f"/v1/stocks/000063/theses/{thesis_id}/{action}")
        assert response.status_code == 404
        assert "Alice" not in response.text

    task = alice.post(
        "/v1/stocks/000063/observation-tasks",
        json={
            "title": "Alice 私有观察任务",
            "description": "核验下一报告期现金流",
            "priority": "high",
            "source_type": "user",
        },
    )
    assert task.status_code == 201
    task_id = task.json()["id"]
    assert task.json()["workspace_id"] == alice_workspace["relation"]["workspace_id"]
    assert bob.get(f"/v1/observation-tasks/{task_id}").status_code == 404
    assert (
        bob.patch(
            f"/v1/observation-tasks/{task_id}",
            json={"base_version": 1, "title": "Bob 越权修改"},
        ).status_code
        == 404
    )
    assert (
        bob.post(
            f"/v1/observation-tasks/{task_id}/transition",
            json={"base_version": 1, "status": "in_progress"},
        ).status_code
        == 404
    )
    assert "Alice 私有观察任务" not in bob.get("/v1/observation-tasks").text

    conversation = alice.post(
        "/me/conversations",
        json={"title": "Alice 私有研究对话", "quality_scope": "user"},
    )
    assert conversation.status_code == 201
    conversation_id = conversation.json()["id"]
    assert bob.get(f"/me/conversations/{conversation_id}").status_code == 404
    assert (
        bob.patch(
            f"/me/conversations/{conversation_id}",
            json={"title": "Bob 越权重命名"},
        ).status_code
        == 404
    )
    assert bob.delete(f"/me/conversations/{conversation_id}").status_code == 404
    assert "Alice 私有研究对话" not in bob.get("/me/conversations").text

    run = app.state.database.create_run(
        alice_user["id"],
        "stock_research",
        "economy",
        {"message": "Alice 候选写回隔离"},
        app.state.settings.workspace_root,
    )
    candidate = app.state.structured_ai._create_thesis_writeback(
        user_id=alice_user["id"],
        run_id=run["id"],
        conversation_id=None,
        symbol="000063.SZ",
        evidence={"display_name": "中兴通讯"},
        ledger={
            "claims": [
                {
                    "id": "alice-private-claim",
                    "relation": "supports",
                    "claim": "Alice 私有写回证据",
                }
            ]
        },
        citation_by_claim={},
    )
    assert candidate is not None
    writeback_path = f"/v1/ai-writebacks/{candidate['id']}"
    assert bob.get(writeback_path).status_code == 404
    assert bob.post(f"{writeback_path}/confirm").status_code == 404
    assert bob.post(f"{writeback_path}/reject").status_code == 404

    request_id = "registered-alice-private-stream"
    app.state.agent_streams.open(request_id, alice_user["id"])
    app.state.agent_streams.publish(
        request_id,
        alice_user["id"],
        {"type": "agent_stream_complete", "status": "completed"},
    )
    assert bob.get(f"/me/chat/stream/{request_id}").status_code == 404
    owner_stream = alice.get(f"/me/chat/stream/{request_id}")
    assert owner_stream.status_code == 200
    assert owner_stream.headers["content-type"].startswith("text/event-stream")
