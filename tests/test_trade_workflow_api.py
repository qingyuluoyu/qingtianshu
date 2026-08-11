from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def _create_user(client: TestClient, name: str) -> dict:
    response = client.post("/users", json={"name": name})
    assert response.status_code == 201
    return response.json()


def _add_stock(client: TestClient) -> None:
    response = client.post(
        "/me/watchlist",
        json={
            "symbol": "000063",
            "name": "中兴通讯",
            "market": "A股",
            "thesis": "核验订单、利润和经营现金流能否同步改善",
        },
    )
    assert response.status_code == 200


def _opening(client: TestClient, *, as_of_date: str = "2025-01-01") -> None:
    response = client.post(
        "/v1/stocks/000063/position/opening",
        headers={"Idempotency-Key": f"opening-{as_of_date}"},
        json={
            "as_of_date": as_of_date,
            "quantity": "500",
            "cost_price": "100",
            "fees": "5",
            "note": "测试期初持仓",
        },
    )
    assert response.status_code == 201


def _create_plan(
    client: TestClient,
    *,
    action_type: str,
    key: str,
    target_quantity: str | None = None,
    target_position_percent: str | None = None,
) -> dict:
    response = client.post(
        "/v1/stocks/000063/action-plans",
        headers={"Idempotency-Key": key},
        json={
            "action_type": action_type,
            "trigger_text": "只记录用户自己的触发条件，等待证据变化后复核",
            "target_quantity": target_quantity,
            "target_position_percent": target_position_percent,
        },
    )
    assert response.status_code == 201
    return response.json()


def _save_plan(client: TestClient, plan: dict) -> dict:
    checked = client.post(
        f"/v1/action-plans/{plan['id']}/transition",
        json={"base_version": plan["version"], "status": "checked"},
    )
    assert checked.status_code == 200
    saved = client.post(
        f"/v1/action-plans/{plan['id']}/transition",
        json={"base_version": checked.json()["version"], "status": "saved"},
    )
    assert saved.status_code == 200
    return saved.json()


def _operation(
    client: TestClient,
    *,
    operation_type: str,
    operated_at: str,
    quantity: str,
    plan_id: str | None,
    key: str,
    fees: str | None = "1",
) -> dict:
    response = client.post(
        "/v1/stocks/000063/operations",
        headers={"Idempotency-Key": key},
        json={
            "operation_type": operation_type,
            "operated_at": operated_at,
            "price": "105",
            "quantity": quantity,
            "fees": fees,
            "reason_text": "记录已经发生的真实操作",
            "plan_id": plan_id,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_action_plan_api_is_idempotent_versioned_and_user_isolated(app) -> None:
    owner = TestClient(app)
    _create_user(owner, "Plan Owner")
    _add_stock(owner)

    missing_key = owner.post(
        "/v1/stocks/000063/action-plans",
        json={"action_type": "hold", "trigger_text": "继续观察"},
    )
    assert missing_key.status_code == 422

    plan = _create_plan(owner, action_type="hold", key="plan-hold-001")
    assert plan["action_type"] == "hold"
    assert plan["target_quantity"] is None
    repeated = _create_plan(owner, action_type="hold", key="plan-hold-001")
    assert repeated["id"] == plan["id"]

    saved = _save_plan(owner, plan)
    assert saved["status"] == "saved"
    assert saved["check_result"]["passed"] is True
    assert "执行完成度不能自动判断" in "".join(
        saved["check_result"]["checks"]
    )

    stale = owner.post(
        f"/v1/action-plans/{plan['id']}/transition",
        json={"base_version": 1, "status": "cancelled"},
    )
    assert stale.status_code == 409

    history = owner.get(f"/v1/action-plans/{plan['id']}/history")
    assert history.status_code == 200
    assert [item["version"] for item in history.json()["items"]] == [3, 2, 1]

    other = TestClient(app)
    _create_user(other, "Plan Other")
    assert other.get(f"/v1/action-plans/{plan['id']}").status_code == 404
    assert other.get(f"/v1/action-plans/{plan['id']}/history").status_code == 404


def test_plan_progress_uses_cumulative_operations_and_never_guesses_position_target(
    client: TestClient,
) -> None:
    _create_user(client, "Plan Progress")
    _add_stock(client)
    _opening(client)

    plan = _save_plan(
        client,
        _create_plan(
            client,
            action_type="add",
            key="plan-cumulative-001",
            target_quantity="150",
        ),
    )
    for index, quantity in enumerate(("50", "50"), start=1):
        _operation(
            client,
            operation_type="add",
            operated_at=f"2025-01-{10 + index:02d}T10:00:00+08:00",
            quantity=quantity,
            plan_id=plan["id"],
            key=f"plan-cumulative-op-{index}",
        )
        current = client.get(f"/v1/action-plans/{plan['id']}").json()
        assert current["status"] == "partially_executed"

    _operation(
        client,
        operation_type="add",
        operated_at="2025-01-13T10:00:00+08:00",
        quantity="50",
        plan_id=plan["id"],
        key="plan-cumulative-op-3",
    )
    executed = client.get(f"/v1/action-plans/{plan['id']}").json()
    assert executed["status"] == "executed"
    assert executed["history"][0]["snapshot"]["execution_progress"] == {
        "cumulative_quantity": "150.000000",
        "cumulative_amount": "15750.0000",
        "target_position_percent_verified": False,
    }

    position_plan = _save_plan(
        client,
        _create_plan(
            client,
            action_type="add",
            key="plan-position-001",
            target_position_percent="20",
        ),
    )
    _operation(
        client,
        operation_type="add",
        operated_at="2025-01-14T10:00:00+08:00",
        quantity="10",
        plan_id=position_plan["id"],
        key="plan-position-op-1",
    )
    assert client.get(f"/v1/action-plans/{position_plan['id']}").json()[
        "status"
    ] == "partially_executed"


def test_review_flow_uses_frozen_context_hermes_draft_and_version_conflicts(
    app, monkeypatch
) -> None:
    client = TestClient(app)
    user = _create_user(client, "Review Owner")
    _add_stock(client)
    _opening(client)
    history = client.get("/stocks/000063/history?range=1y")
    assert history.status_code == 200
    history_payload = history.json()
    app.state.database.upsert_market_bars(
        "000063.SZ",
        "1d",
        history_payload["points"],
        history_payload["source"],
        history_payload["fetched_at"],
    )

    plan = _save_plan(
        client,
        _create_plan(
            client,
            action_type="reduce",
            key="plan-review-001",
            target_quantity="20",
        ),
    )
    position = _operation(
        client,
        operation_type="reduce",
        operated_at="2025-01-10T10:00:00+08:00",
        quantity="20",
        plan_id=plan["id"],
        key="review-operation-001",
        fees=None,
    )
    operation_id = position["operations"][0]["id"]

    context_response = client.get(f"/v1/operations/{operation_id}/context")
    assert context_response.status_code == 200
    context = context_response.json()
    assert context["plan_id"] == plan["id"]
    assert context["thesis_version_id"]
    assert context["snapshot_version"] == "trade_context_v2"
    assert context["snapshot"]["market_bar"]["timestamp"][:10] < "2025-01-10"

    readiness = app.state.trade_workflow.refresh_pending_reviews()
    assert readiness["promoted_to_ready"] == 1
    reviews = client.get("/v1/stocks/000063/trade-reviews").json()["items"]
    assert len(reviews) == 1
    review = reviews[0]
    assert review["status"] == "ready"
    assert review["price_observation"]["fees_complete"] is False
    assert "不计算精确净收益" in review["price_observation"]["summary"]

    center = client.get("/v1/trade-reviews?status=ready&q=中兴")
    assert center.status_code == 200
    center_payload = center.json()
    assert center_payload["contract_version"] == "trade_review_center_v1"
    assert center_payload["summary"]["actionable"] == 1
    assert [item["id"] for item in center_payload["items"]] == [review["id"]]

    invalid_filter = client.get("/v1/trade-reviews?status=unknown")
    assert invalid_filter.status_code == 422

    answer = (
        '{"logic_result":"冻结判断得到部分价格路径支持，但当时缺少研究报告与估值快照，'
        '反方证据仍需核验。","plan_deviation":"实际数量与冻结计划一致。",'
        '"bias_tags":["结果偏差待核对"],"improvement_text":"下次记录费用并补齐操作时证据。"}'
    )
    stored_user = app.state.database.get_user(user["id"])
    assert stored_user is not None
    run = app.state.database.create_run(
        user_id=user["id"],
        intent="trade_review",
        model_tier="economy",
        input_data={"message": "交易复盘"},
        workspace_path=Path(stored_user["workspace_path"]),
    )
    app.state.database.finish_run(
        run_id=run["id"],
        user_id=user["id"],
        status="completed",
        evidence={},
        answer=answer,
    )
    completed = app.state.database.get_run(run["id"], user["id"])
    monkeypatch.setattr(app.state.agent, "run", lambda **_: completed)

    generated = client.post(
        f"/v1/trade-reviews/{review['id']}/generate-draft",
        json={"base_version": 0, "model_tier": "economy"},
    )
    assert generated.status_code == 201, generated.text
    candidate = generated.json()
    assert candidate["candidate_type"] == "review_draft"
    assert candidate["status"] == "pending_confirmation"
    assert client.get(f"/v1/trade-reviews/{review['id']}").json()[
        "current_version"
    ] is None
    confirmed_candidate = client.post(
        f"/v1/ai-writebacks/{candidate['id']}/confirm"
    )
    assert confirmed_candidate.status_code == 200
    draft = confirmed_candidate.json()["trade_review"]
    assert draft["status"] == "draft"
    assert draft["current_version"]["created_source"] == "ai"
    assert draft["current_version"]["source_run_id"] == run["id"]
    assert draft["current_version"]["bias_tags"] == ["结果偏差待核对"]

    edited = client.patch(
        f"/v1/trade-reviews/{review['id']}/draft",
        json={
            "base_version": 1,
            "price_result": draft["current_version"]["price_result"],
            "logic_result": "用户核对后保留逻辑边界，并补充当时未确认的信息。",
            "plan_deviation": "执行数量符合计划。",
            "bias_tags": ["待用户确认"],
            "improvement_text": "以后同步记录费用与证据链接。",
        },
    )
    assert edited.status_code == 200
    assert edited.json()["current_version"]["version_no"] == 2
    assert edited.json()["current_version"]["created_source"] == "user"

    stale_edit = client.patch(
        f"/v1/trade-reviews/{review['id']}/draft",
        json={
            "base_version": 1,
            "price_result": "旧版本价格结果",
            "logic_result": "旧版本逻辑结果",
            "bias_tags": [],
        },
    )
    assert stale_edit.status_code == 409

    confirmed = client.post(
        f"/v1/trade-reviews/{review['id']}/confirm",
        json={"base_version": 2},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "confirmed"

    stale_archive = client.post(
        f"/v1/trade-reviews/{review['id']}/archive",
        json={"base_version": 1},
    )
    assert stale_archive.status_code == 409
    archived = client.post(
        f"/v1/trade-reviews/{review['id']}/archive",
        json={"base_version": 2},
    )
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"

    archived_center = client.get("/v1/trade-reviews?status=archived").json()
    assert archived_center["summary"]["archived"] == 1
    assert archived_center["items"][0]["id"] == review["id"]

    other = TestClient(app)
    _create_user(other, "Review Other")
    assert other.get("/v1/trade-reviews").json()["items"] == []
    assert other.get(f"/v1/trade-reviews/{review['id']}").status_code == 404
    assert other.get(f"/v1/operations/{operation_id}/context").status_code == 404
