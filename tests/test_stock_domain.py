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


def test_watchlist_persists_private_price_and_position_fields(app):
    client = TestClient(app)
    _create_user(client, "Private Position")

    response = client.post(
        "/me/watchlist",
        json={
            "symbol": "000063",
            "name": "中兴通讯",
            "market": "A股",
            "thesis": "只记录个人研究参数",
            "psychological_price": "31.50",
            "purchase_price": "29.80",
            "holding_quantity": 1200,
            "sell_price": "34.20",
        },
    )

    assert response.status_code == 200
    item = response.json()
    assert item["psychological_price"] == "31.50"
    assert item["purchase_price"] == "29.80"
    assert item["holding_quantity"] == 1200
    assert item["sell_price"] == "34.20"


def test_profile_summary_returns_only_current_users_real_assets(app):
    owner = TestClient(app)
    other = TestClient(app)
    _create_user(owner, "Profile Owner")
    _create_user(other, "Profile Other")
    _add_stock(owner, "owner thesis")
    _add_stock(other, "other thesis")

    response = owner.get("/api/v1/me/profile-summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["research_assets"]["watchlist_count"] == 1
    assert payload["research_assets"]["conversation_count"] == 0
    assert payload["membership"]["status"] == "not_available"
    assert payload["account"]["id"] == owner.get("/session").json()["id"]
    assert payload["account"]["workspace_isolated"] is True
    assert "token" not in str(payload).lower()


def test_profile_workbench_aggregates_only_current_users_persisted_assets(app):
    owner = TestClient(app)
    other = TestClient(app)
    owner_public = _create_user(owner, "Workbench Owner")
    _create_user(other, "Workbench Other")
    _add_stock(owner, "owner workbench thesis")
    database = app.state.database
    database.upsert_watchlist(
        user_id=owner_public["id"],
        symbol="NVDA",
        name="历史非 A 股记录",
        market="US",
        thesis="legacy record must not cross the A-share product boundary",
    )
    owner_user = database.get_user(owner_public["id"])
    conversations = [
        database.create_conversation(owner_public["id"], title)
        for title in ("queued research", "failed research")
    ]
    runs = []
    for index, conversation in enumerate(conversations):
        run, _ = database.create_ai_research_submission(
            user_id=owner_public["id"],
            conversation_id=conversation["id"],
            idempotency_key=f"profile-workbench-{index:04d}",
            request_fingerprint=f"profile-workbench-fingerprint-{index}",
            targets=[{"symbol": "000063.SZ", "name": "中兴通讯"}],
            question=f"research question {index}",
            snapshot={},
            dimensions={},
            workspace_path=owner_user["workspace_path"],
        )
        runs.append(run)
    database.claim_research_task(runs[1]["task_id"], "test-worker")
    database.finish_research_task(
        runs[1]["task_id"], "failed", "provider temporarily unavailable"
    )
    position = database.create_position(
        user_id=owner_public["id"],
        symbol="000063.SZ",
        name="中兴通讯",
        account_type="simulated",
        quantity="100",
        cost_price="30.00",
        current_price="31.00",
        status="open",
        data_as_of="2026-07-25T15:00:00+08:00",
    )
    database.create_trade(
        user_id=owner_public["id"],
        position_id=position["id"],
        symbol="000063.SZ",
        side="buy",
        executed_at="2026-07-25T10:00:00+08:00",
        price="30.00",
        quantity="100",
        fee="5.00",
        realized_pnl=None,
    )

    workbench = owner.get("/api/v1/me/profile-summary").json()["workbench"]

    assert workbench["summary"] == {
        "pending_count": 2,
        "watchlist_count": 1,
        "research_total": 2,
        "research_running": 1,
        "position_count": 1,
        "trade_count": 1,
        "review_pending_count": None,
    }
    assert [item["kind"] for item in workbench["todos"]] == [
        "research_failed",
        "research_running",
    ]
    assert all(item["href"].startswith("#") for item in workbench["todos"])
    assert len(workbench["recent_research"]) == 2
    assert len(workbench["recent_watchlist"]) == 1
    assert all(item["symbol"] != "NVDA" for item in workbench["recent_watchlist"])
    assert other.get("/api/v1/me/profile-summary").json()["workbench"][
        "summary"
    ]["watchlist_count"] == 0


def test_phone_contact_is_private_and_alipay_order_remains_a_non_payment_draft(app):
    owner = TestClient(app)
    other = TestClient(app)
    _create_user(owner, "Phone Owner")
    _create_user(other, "Phone Other")

    contact = owner.put("/me/contact-phone", json={"phone": "13800138000"})
    assert contact.status_code == 200
    assert contact.json()["phone_masked"] == "+86 138****8000"
    assert contact.json()["verification_status"] == "unverified"

    draft = owner.post(
        "/me/payment-orders/draft", json={"product_code": "research_pro"}
    )
    assert draft.status_code == 201
    assert draft.json()["provider"] == "alipay"
    assert draft.json()["status"] == "draft"
    assert draft.json()["payment_enabled"] is False
    assert "13800138000" not in str(draft.json())

    own_summary = owner.get("/api/v1/me/profile-summary").json()
    other_summary = other.get("/api/v1/me/profile-summary").json()
    assert own_summary["account"]["phone_masked"] == "+86 138****8000"
    assert other_summary["account"]["phone_masked"] is None
