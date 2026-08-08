from __future__ import annotations

from fastapi.testclient import TestClient

from app.services.observation_tasks import ObservationTaskService


def _create_user(client: TestClient, name: str) -> dict:
    response = client.post("/users", json={"name": name})
    assert response.status_code == 201
    return response.json()


def _create_task(
    client: TestClient,
    *,
    symbol: str = "000063",
    source_type: str = "user",
    source_ref_id: str | None = None,
) -> dict:
    response = client.post(
        f"/v1/stocks/{symbol}/observation-tasks",
        json={
            "title": "核验下一份财报现金流",
            "description": "比较经营现金流、应收账款和净利润是否同步改善。",
            "priority": "high",
            "source_type": source_type,
            "source_ref_id": source_ref_id,
        },
    )
    assert response.status_code == 201
    return response.json()


def test_observation_task_is_persistent_deduplicated_and_in_stock_workspace(app):
    client = TestClient(app)
    user = _create_user(client, "Observation Task User")
    app.state.database.upsert_watchlist(
        user["id"],
        "000063.SZ",
        "中兴通讯",
        "A股",
        "关注利润质量和经营现金流是否同步改善",
    )

    task = _create_task(
        client,
        source_type="research_action",
        source_ref_id="cashflow-review-v1",
    )
    assert task["symbol"] == "000063.SZ"
    assert task["workspace_id"]
    assert task["status"] == "pending"
    assert task["status_label"] == "待处理"
    assert task["version"] == 1
    assert task["history"][0]["event_type"] == "created"

    duplicate = _create_task(
        client,
        source_type="research_action",
        source_ref_id="cashflow-review-v1",
    )
    assert duplicate["id"] == task["id"]

    listed = client.get("/v1/stocks/000063/observation-tasks")
    assert listed.status_code == 200
    assert listed.json()["summary"]["total"] == 1
    assert listed.json()["summary"]["active"] == 1

    workspace = client.get("/v1/stocks/000063/workspace")
    assert workspace.status_code == 200
    payload = workspace.json()
    assert payload["observation_tasks"]["items"][0]["id"] == task["id"]
    user_action = next(
        item
        for item in payload["pending_actions"]
        if item.get("source") == "observation_task"
    )
    assert user_action["task_id"] == task["id"]
    assert user_action["current_evidence"].startswith("比较经营现金流")

    reloaded_service = ObservationTaskService(app.state.database)
    persisted = reloaded_service.get_task(user_id=user["id"], task_id=task["id"])
    assert persisted["title"] == task["title"]


def test_observation_task_transitions_require_results_and_keep_history(app):
    client = TestClient(app)
    _create_user(client, "Observation Task Lifecycle")
    task = _create_task(client)

    missing_result = client.post(
        f"/v1/observation-tasks/{task['id']}/transition",
        json={"base_version": 1, "status": "completed"},
    )
    assert missing_result.status_code == 422
    assert "填写结果或选择证据" in missing_result.json()["detail"]

    started = client.post(
        f"/v1/observation-tasks/{task['id']}/transition",
        json={"base_version": 1, "status": "in_progress"},
    )
    assert started.status_code == 200
    assert started.json()["version"] == 2

    stale = client.post(
        f"/v1/observation-tasks/{task['id']}/transition",
        json={"base_version": 1, "status": "waiting_data"},
    )
    assert stale.status_code == 409

    waiting = client.post(
        f"/v1/observation-tasks/{task['id']}/transition",
        json={"base_version": 2, "status": "waiting_data"},
    )
    assert waiting.status_code == 200
    assert waiting.json()["status_label"] == "等待数据"

    completed = client.post(
        f"/v1/observation-tasks/{task['id']}/transition",
        json={
            "base_version": 3,
            "status": "completed",
            "result_text": "经营现金流改善，但应收账款仍需下一报告期继续核验。",
            "evidence_refs": ["2026Q2 现金流量表", "2026Q2 资产负债表"],
        },
    )
    assert completed.status_code == 200
    completed_payload = completed.json()
    assert completed_payload["terminal"] is True
    assert completed_payload["completion_evidence"] == [
        "2026Q2 现金流量表",
        "2026Q2 资产负债表",
    ]
    assert len(completed_payload["history"]) == 4

    cannot_edit = client.patch(
        f"/v1/observation-tasks/{task['id']}",
        json={"base_version": 4, "title": "直接改写已完成任务"},
    )
    assert cannot_edit.status_code == 422

    reopened = client.post(
        f"/v1/observation-tasks/{task['id']}/transition",
        json={"base_version": 4, "status": "pending"},
    )
    assert reopened.status_code == 200
    assert reopened.json()["result_text"] is None
    assert reopened.json()["completion_evidence"] == []
    assert reopened.json()["history"][0]["event_type"] == "reopened"

    updated = client.patch(
        f"/v1/observation-tasks/{task['id']}",
        json={
            "base_version": 5,
            "title": "继续核验应收账款变化",
            "description": "等待下一报告期后对比应收账款周转和现金流。",
            "priority": "normal",
            "due_at": "2026-10-31T18:00:00+08:00",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["version"] == 6
    assert updated.json()["due_at"] == "2026-10-31T18:00:00+08:00"
    assert updated.json()["history"][0]["event_type"] == "updated"


def test_observation_tasks_are_user_isolated(app):
    owner = TestClient(app)
    _create_user(owner, "Observation Task Owner")
    task = _create_task(owner)

    other = TestClient(app)
    _create_user(other, "Observation Task Other")
    assert other.get(f"/v1/observation-tasks/{task['id']}").status_code == 404
    assert other.get("/v1/observation-tasks").json()["items"] == []
    assert (
        other.post(
            f"/v1/observation-tasks/{task['id']}/transition",
            json={"base_version": 1, "status": "in_progress"},
        ).status_code
        == 404
    )
