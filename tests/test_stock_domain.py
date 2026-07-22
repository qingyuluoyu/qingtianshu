from __future__ import annotations

from fastapi.testclient import TestClient


def _create_user(client: TestClient, name: str) -> dict:
    response = client.post("/users", json={"name": name})
    assert response.status_code == 201
    return response.json()


def _add_stock(client: TestClient, thesis: str) -> dict:
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
    return response.json()


def test_legacy_watchlist_creates_unique_workspace_and_versioned_thesis(app):
    client = TestClient(app)
    _create_user(client, "Stock Domain Legacy")
    _add_stock(client, "关注订单、利润和现金流能否同步改善")

    relation = client.get("/v1/stocks/000063/relation")
    assert relation.status_code == 200
    first = relation.json()
    assert first["relation_type"] == "watching"
    assert first["priority"] == "normal"
    assert first["tracking_status"] == "active"
    assert first["version"] == 1
    assert first["active_thesis"]["version_no"] == 1
    assert first["active_thesis"]["status"] == "active"

    _add_stock(client, "关注订单、利润和现金流能否同步改善")
    same = client.get("/v1/stocks/000063/theses").json()
    assert same["active"]["version_no"] == 1
    assert same["history"] == []

    _add_stock(client, "关注算力订单兑现以及经营现金流改善")
    changed = client.get("/v1/stocks/000063/theses").json()
    assert changed["active"]["version_no"] == 2
    assert changed["active"]["reason_text"] == "关注算力订单兑现以及经营现金流改善"
    assert changed["history"][0]["status"] == "superseded"
    assert changed["history"][0]["version_no"] == 1


def test_thesis_candidate_requires_confirmation_and_detects_stale_base(app):
    client = TestClient(app)
    _create_user(client, "Stock Thesis Confirm")
    _add_stock(client, "原判断：关注主营结构和利润质量")

    draft = client.post(
        "/v1/stocks/000063/theses",
        json={
            "reason_text": "新判断：重点核验订单、毛利和回款",
            "watch_items": ["订单兑现", "毛利率", "经营现金流"],
            "recheck_conditions": ["现金流继续弱于利润时重新判断"],
            "source": "user",
            "base_version": 1,
        },
    )
    assert draft.status_code == 201
    candidate = draft.json()
    assert candidate["status"] == "draft"
    assert candidate["base_version"] == 1

    before_confirm = client.get("/v1/stocks/000063/workspace").json()
    assert before_confirm["thesis"]["version"] == 1
    assert before_confirm["thesis"]["summary"].startswith("原判断")

    confirmed = client.post(
        f"/v1/stocks/000063/theses/{candidate['id']}/confirm"
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "active"
    assert confirmed.json()["version_no"] == 2

    after_confirm = client.get("/v1/stocks/000063/workspace").json()
    assert after_confirm["thesis"]["version"] == 2
    assert after_confirm["thesis"]["watch_items"] == [
        "订单兑现",
        "毛利率",
        "经营现金流",
    ]
    assert client.get("/me/watchlist").json()["items"][0]["thesis"].startswith(
        "新判断"
    )

    stale = client.post(
        "/v1/stocks/000063/theses",
        json={
            "reason_text": "基于旧版本生成的冲突草稿",
            "source": "user",
            "base_version": 1,
        },
    )
    assert stale.status_code == 409
    assert "当前版本为 2" in stale.json()["detail"]


def test_ai_thesis_candidate_needs_completed_run_and_can_be_rejected(app):
    client = TestClient(app)
    user = _create_user(client, "Stock Thesis AI")
    _add_stock(client, "正式判断保持不变")

    rejected_run = app.state.database.create_run(
        user["id"],
        "stock_research",
        "economy",
        {"message": "生成判断草稿"},
        app.state.settings.workspace_root,
    )
    invalid = client.post(
        "/v1/stocks/000063/theses",
        json={
            "reason_text": "模型未完成时不得写入的草稿",
            "source": "ai",
            "source_run_id": rejected_run["id"],
            "base_version": 1,
        },
    )
    assert invalid.status_code == 422

    app.state.database.finish_run(
        rejected_run["id"],
        user["id"],
        "completed",
        {"symbol": "000063.SZ"},
        "候选判断草稿",
        {"prompt_tokens": 1, "completion_tokens": 1},
    )
    created = client.post(
        "/v1/stocks/000063/theses",
        json={
            "reason_text": "AI 候选：继续核验利润和回款",
            "source": "ai",
            "source_run_id": rejected_run["id"],
            "base_version": 1,
        },
    )
    assert created.status_code == 201
    assert created.json()["status"] == "pending_confirmation"

    rejected = client.post(
        f"/v1/stocks/000063/theses/{created.json()['id']}/reject"
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert client.get("/v1/stocks/000063/theses").json()["active"][
        "reason_text"
    ] == "正式判断保持不变"


def test_relation_version_history_end_restore_and_user_isolation(app):
    owner = TestClient(app)
    _create_user(owner, "Relation Owner")
    _add_stock(owner, "保留关系历史和原判断")
    original = owner.get("/v1/stocks/000063/relation").json()
    workspace_id = original["id"]

    holding = owner.patch(
        "/v1/stocks/000063/relation",
        json={
            "base_version": original["version"],
            "relation_type": "holding",
            "priority": "high",
            "tracking_status": "active",
            "workflow_status": "researching",
            "attention_tags": ["report_due", "risk_changed"],
        },
    )
    assert holding.status_code == 200
    holding_payload = holding.json()
    assert holding_payload["relation_type"] == "holding"
    assert holding_payload["priority"] is None
    assert holding_payload["version"] == original["version"] + 1
    assert holding_payload["attention_tags"] == ["report_due", "risk_changed"]

    stale = owner.patch(
        "/v1/stocks/000063/relation",
        json={
            "base_version": original["version"],
            "relation_type": "watching",
            "priority": "normal",
            "tracking_status": "active",
            "workflow_status": "idle",
        },
    )
    assert stale.status_code == 409

    ended = owner.patch(
        "/v1/stocks/000063/relation",
        json={
            "base_version": holding_payload["version"],
            "relation_type": "ended",
            "tracking_status": "paused",
            "workflow_status": "idle",
        },
    )
    assert ended.status_code == 200
    assert ended.json()["relation_type"] == "ended"
    assert owner.get("/me/watchlist").json()["items"] == []
    ended_workspace = owner.get("/v1/stocks/000063/workspace").json()
    assert ended_workspace["relation"]["type"] == "ended"
    assert ended_workspace["thesis"]["summary"] == "保留关系历史和原判断"

    other = TestClient(app)
    _create_user(other, "Relation Other")
    assert other.get("/v1/stocks/000063/relation").status_code == 404

    _add_stock(owner, "保留关系历史和原判断")
    restored = owner.get("/v1/stocks/000063/relation").json()
    assert restored["id"] == workspace_id
    assert restored["relation_type"] == "watching"
    assert len(restored["relation_history"]) == 4
    assert [item["relation_type"] for item in restored["relation_history"]] == [
        "watching",
        "holding",
        "ended",
        "watching",
    ]
