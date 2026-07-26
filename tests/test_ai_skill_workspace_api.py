from __future__ import annotations

from app.services.research_dispatcher import ResearchDispatcher


class RecordingQueue:
    def __init__(self) -> None:
        self.calls = 0

    def publish_pending(self, limit: int = 100) -> int:
        self.calls += 1
        return 1


def _login(client, name: str = "双 Skill 工作区用户") -> dict:
    response = client.post("/users", json={"name": name})
    assert response.status_code == 201
    return response.json()


def test_five_dimension_submission_persists_independent_workflow(client, app):
    _login(client)
    queue = RecordingQueue()
    app.state.research_dispatcher = ResearchDispatcher(app.state.database, queue)

    response = client.post(
        "/me/ai-research/five-dimension-runs",
        headers={"Idempotency-Key": "five-dimension-workspace-0001"},
        json={
            "symbol": "300750.SZ",
            "name": "宁德时代",
            "focus": "盈利持续性",
        },
    )

    assert response.status_code == 202
    run = response.json()
    assert run["workflow"] == "five_dimension_v7"
    assert run["skill_bundle"]["version"] == "7.0.0"
    assert set(run["dimensions"]) == {
        "fundamental",
        "industry",
        "valuation",
        "technical",
        "risk",
    }
    assert run["execution_status"] == "pending"
    assert queue.calls == 1
    task = app.state.database.get_research_task(run["task_id"])
    assert task["payload"]["workflow"] == "five_dimension_v7"
    assert "conversation_messages" not in task["payload"]
    assert "instructions" not in response.text


def test_lao_li_submission_keeps_its_own_workflow(client, app):
    _login(client, "老李工作区用户")
    queue = RecordingQueue()
    app.state.research_dispatcher = ResearchDispatcher(app.state.database, queue)

    response = client.post(
        "/me/ai-research/runs",
        headers={"Idempotency-Key": "lao-li-workspace-key-0001"},
        json={
            "question": "按老李框架判断当前最重要的验证条件",
            "targets": [{"symbol": "000063.SZ", "name": "中兴通讯"}],
        },
    )

    assert response.status_code == 202
    run = response.json()
    assert run["workflow"] == "lao_li_diagnosis_v1"
    task = app.state.database.get_research_task(run["task_id"])
    assert task["payload"]["workflow"] == "lao_li_diagnosis_v1"


def test_five_dimension_submission_rejects_non_a_share(client):
    _login(client, "市场边界用户")

    response = client.post(
        "/me/ai-research/five-dimension-runs",
        headers={"Idempotency-Key": "five-dimension-market-0001"},
        json={"symbol": "NVDA", "name": "NVIDIA", "focus": ""},
    )

    assert response.status_code == 422
    assert "A 股" in response.json()["detail"]
