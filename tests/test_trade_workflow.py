from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.services.trade_workflow import TradeWorkflowService


def _create_user(client: TestClient, name: str) -> dict:
    response = client.post("/users", json={"name": name})
    assert response.status_code == 201
    return response.json()


def test_review_draft_normalization_separates_price_and_internal_language() -> None:
    normalized = TradeWorkflowService.normalize_review_agent_draft(
        {"action_plan": {"id": "plan-1"}},
        {
            "logic_result": (
                "操作价37.4元，第3个后续交易日复权收盘35.25元。"
                "但"
                "操作时保存的记录缺失经营现金流和订单核验，无法验证原判断。"
                "当时逻辑离计划设定的触发门槛还有距离。"
                "本次减少数量与计划一致。"
                "计划要求的两个触发条件与实际理由条件强度不同，"
                "需要用户确认条件已满足。"
                "操作时持仓成本36元，操作价35.90元，属于亏损卖出。"
            ),
            "plan_deviation": (
                "计划（版本3）触发条件是经营现金流继续恶化，但实际理由只是尚未改善，"
                "条件强度不同；冻结时计划状态为已保存，后续更新为已执行，"
                "操作前没有记录订单核验。"
            ),
            "bias_tags": ["确认偏差", "可得性启发", "叙事谬误"],
            "improvement_text": (
                "把核验数据冻结到操作上下文中，并加入thesis的watch_items。"
                "例如经营现金流连续两个季度同比下降超过X%，"
                "或在手订单低于预期X%。"
            ),
        },
    )

    assert "持仓成本" not in normalized["logic_result"]
    assert "操作价" not in normalized["logic_result"]
    assert "亏损卖出" not in normalized["logic_result"]
    assert not normalized["logic_result"].startswith("但")
    assert "计划的触发条件" not in normalized["logic_result"]
    assert "计划要求" not in normalized["logic_result"]
    assert "计划设定" not in normalized["logic_result"]
    assert "计划一致" not in normalized["logic_result"]
    assert "thesis" not in normalized["improvement_text"]
    assert "watch_items" not in normalized["improvement_text"]
    assert "随操作记录一并保存" in normalized["improvement_text"]
    assert "X%" not in normalized["improvement_text"]
    assert "由用户自己写清判断标准" in normalized["improvement_text"]
    assert "版本3" not in normalized["plan_deviation"]
    assert "冻结时" not in normalized["plan_deviation"]
    assert "后续更新为已执行" not in normalized["plan_deviation"]
    assert normalized["bias_tags"] == ["证据未留档", "触发条件待确认"]


def test_review_agent_answer_decodes_nested_json_string() -> None:
    nested = json.dumps(
        json.dumps(
            {
                "logic_result": "操作时证据不足，需要继续核验。",
                "plan_deviation": None,
                "bias_tags": ["证据未留档"],
                "improvement_text": None,
            },
            ensure_ascii=False,
        ),
        ensure_ascii=False,
    )

    parsed = TradeWorkflowService.parse_review_agent_answer(nested)

    assert parsed["logic_result"] == "操作时证据不足，需要继续核验。"
    assert parsed["bias_tags"] == ["证据未留档"]


def _add_stock(client: TestClient) -> None:
    response = client.post(
        "/me/watchlist",
        json={
            "symbol": "000063",
            "name": "中兴通讯",
            "market": "A股",
            "thesis": "核验利润与现金流能否同步改善",
        },
    )
    assert response.status_code == 200


def _opening(client: TestClient) -> None:
    response = client.post(
        "/v1/stocks/000063/position/opening",
        headers={"Idempotency-Key": "trade-workflow-opening"},
        json={
            "as_of_date": "2026-07-01",
            "quantity": "100",
            "cost_price": "10",
            "fees": "5",
            "note": "期初持仓",
        },
    )
    assert response.status_code == 201


def _create_saved_plan(client: TestClient, *, quantity: str = "10") -> dict:
    created = client.post(
        "/v1/stocks/000063/action-plans",
        headers={"Idempotency-Key": f"trade-plan-{quantity}"},
        json={
            "action_type": "reduce",
            "trigger_text": "公告与现金流证据恶化后，按自己的计划减少持仓",
            "target_quantity": quantity,
        },
    )
    assert created.status_code == 201
    plan = created.json()
    checked = client.post(
        f"/v1/action-plans/{plan['id']}/transition",
        json={"base_version": plan["version"], "status": "checked"},
    )
    assert checked.status_code == 200
    plan = checked.json()
    saved = client.post(
        f"/v1/action-plans/{plan['id']}/transition",
        json={"base_version": plan["version"], "status": "saved"},
    )
    assert saved.status_code == 200
    return saved.json()


def _seed_operation_context_inputs(app, user_id: str) -> None:
    with app.state.database.connect() as connection:
        thesis = connection.execute(
            """
            SELECT id FROM thesis_versions
            WHERE user_id = ? AND symbol = '000063.SZ' AND status = 'active'
            """,
            (user_id,),
        ).fetchone()
        assert thesis is not None
        connection.execute(
            """
            INSERT INTO market_bars(
                symbol, interval, timestamp, open, high, low, close,
                adjusted_close, volume, source, fetched_at
            ) VALUES ('000063.SZ', '1d', '2026-07-09T15:00:00+08:00',
                      10, 11, 9, 10.5, 10.5, 1000, 'test',
                      '2026-07-09T15:01:00+08:00')
            """
        )
        connection.execute(
            """
            INSERT INTO market_bars(
                symbol, interval, timestamp, open, high, low, close,
                adjusted_close, volume, source, fetched_at
            ) VALUES ('000001.SS', '1d', '2026-07-09T15:00:00+08:00',
                      3000, 3010, 2990, 3005, 3005, 1000, 'test',
                      '2026-07-09T15:01:00+08:00')
            """
        )
        connection.execute(
            """
            INSERT INTO valuation_snapshots(
                id, symbol, name, currency, price, previous_close, pct_change,
                turnover_rate_pct, pe_ttm, pe_dynamic, pe_static, pb,
                float_market_cap, total_market_cap, market_timestamp, source,
                source_url, field_mapping, warnings_json, fetched_at
            ) VALUES ('workflow-valuation', '000063.SZ', '中兴通讯', 'CNY',
                      10.5, 10, 5, 1, 20, 20, 20, 2, 1, 2,
                      '2026-07-09T15:00:00+08:00', 'test',
                      'https://example.invalid/valuation', '{}', '[]',
                      '2026-07-09T15:01:00+08:00')
            """
        )
        connection.execute(
            """
            INSERT INTO research_reports(
                id, symbol, name, title, summary, body, status, fingerprint,
                evidence_json, run_id, market_timestamp, generated_at
            ) VALUES ('workflow-report', '000063.SZ', '中兴通讯', '操作前研究',
                      '利润与现金流仍需核验', '证据正文', 'published',
                      'workflow-report-fingerprint', '{}', NULL,
                      '2026-07-09T15:00:00+08:00',
                      '2026-07-09T16:00:00+08:00')
            """
        )


def _seed_future_bars(app) -> None:
    rows = [
        ("2026-07-13T15:00:00+08:00", 9.9),
        ("2026-07-14T15:00:00+08:00", 9.7),
        ("2026-07-15T15:00:00+08:00", 9.5),
    ]
    with app.state.database.connect() as connection:
        connection.executemany(
            """
            INSERT INTO market_bars(
                symbol, interval, timestamp, open, high, low, close,
                adjusted_close, volume, source, fetched_at
            ) VALUES ('000063.SZ', '1d', ?, ?, ?, ?, ?, ?, 1000, 'test', ?)
            """,
            [
                (timestamp, close, close, close, close, close, timestamp)
                for timestamp, close in rows
            ],
        )


def test_action_plan_state_machine_scope_and_operation_linkage(app) -> None:
    owner = TestClient(app)
    owner_user = _create_user(owner, "Plan Owner")
    _add_stock(owner)
    _opening(owner)
    _seed_operation_context_inputs(app, owner_user["id"])

    targetless = owner.post(
        "/v1/stocks/000063/action-plans",
        headers={"Idempotency-Key": "trade-plan-targetless"},
        json={"action_type": "reduce", "trigger_text": "只有条件没有目标"},
    )
    assert targetless.status_code == 201

    plan = _create_saved_plan(owner)
    stale = owner.patch(
        f"/v1/action-plans/{plan['id']}",
        json={"base_version": 1, "trigger_text": "陈旧页面更新"},
    )
    assert stale.status_code == 409

    other = TestClient(app)
    _create_user(other, "Plan Other")
    _add_stock(other)
    assert other.patch(
        f"/v1/action-plans/{plan['id']}",
        json={"base_version": plan["version"], "trigger_text": "跨用户"},
    ).status_code == 404

    mismatch = owner.post(
        "/v1/stocks/000063/operations",
        headers={"Idempotency-Key": "workflow-mismatch"},
        json={
            "operation_type": "sell",
            "operated_at": "2026-07-10T10:00:00+08:00",
            "price": "10",
            "quantity": "10",
            "fees": "1",
            "reason_text": "实际方向与计划不同",
            "plan_id": plan["id"],
        },
    )
    assert mismatch.status_code == 422

    operation_payload = {
        "operation_type": "reduce",
        "operated_at": "2026-07-10T10:00:00+08:00",
        "price": "10",
        "quantity": "10",
        "fees": "1",
        "reason_text": "按已保存的个人计划记录真实操作",
        "plan_id": plan["id"],
    }
    created = owner.post(
        "/v1/stocks/000063/operations",
        headers={"Idempotency-Key": "workflow-operation"},
        json=operation_payload,
    )
    assert created.status_code == 201
    repeated = owner.post(
        "/v1/stocks/000063/operations",
        headers={"Idempotency-Key": "workflow-operation"},
        json=operation_payload,
    )
    assert repeated.status_code == 201

    plans = owner.get("/v1/stocks/000063/action-plans").json()["items"]
    assert plans[0]["status"] == "executed"
    reviews = owner.get("/v1/stocks/000063/trade-reviews").json()["items"]
    assert len(reviews) == 1
    assert reviews[0]["status"] == "waiting_data"
    assert reviews[0]["context_snapshot"]["action_plan"]["id"] == plan["id"]
    assert reviews[0]["context_snapshot"]["data_completeness"]["status"] == "complete"
    assert other.get(f"/v1/trade-reviews/{reviews[0]['id']}").status_code == 404


def test_trade_review_requires_live_completed_run_then_user_confirmation(
    app, monkeypatch
) -> None:
    client = TestClient(app)
    user = _create_user(client, "Review Owner")
    _add_stock(client)
    _opening(client)
    _seed_operation_context_inputs(app, user["id"])
    plan = _create_saved_plan(client)
    operation = client.post(
        "/v1/stocks/000063/operations",
        headers={"Idempotency-Key": "review-operation"},
        json={
            "operation_type": "reduce",
            "operated_at": "2026-07-10T10:00:00+08:00",
            "price": "10",
            "quantity": "10",
            "fees": "1",
            "reason_text": "按个人计划减少持仓",
            "plan_id": plan["id"],
        },
    )
    assert operation.status_code == 201
    review = client.get("/v1/stocks/000063/trade-reviews").json()["items"][0]

    premature = client.post(
        f"/v1/trade-reviews/{review['id']}/generate-draft", json={}
    )
    assert premature.status_code == 422

    _seed_future_bars(app)
    ready = client.get(f"/v1/trade-reviews/{review['id']}").json()
    assert ready["status"] == "ready"
    assert ready["price_observation"]["price_change_pct"] == "-5.00"

    monkeypatch.setattr(
        app.state.agent,
        "run",
        lambda **_: {"id": "failed-run", "status": "degraded", "answer": "回退"},
    )
    failed = client.post(
        f"/v1/trade-reviews/{review['id']}/generate-draft", json={}
    )
    assert failed.status_code == 503
    assert client.get(f"/v1/trade-reviews/{review['id']}").json()[
        "current_version"
    ] is None

    stored_user = app.state.database.get_user(user["id"])
    run = app.state.database.create_run(
        user_id=user["id"],
        intent="trade_review",
        model_tier="economy",
        input_data={"message": "即时生成交易复盘"},
        workspace_path=stored_user["workspace_path"],
    )
    app.state.database.finish_run(
        run["id"],
        user["id"],
        "completed",
        {"symbol": "000063.SZ"},
        "即时生成：价格结果与逻辑结果必须分开，反方证据仍需核验。",
        None,
        None,
    )
    completed = app.state.database.get_run(run["id"], user["id"])
    monkeypatch.setattr(app.state.agent, "run", lambda **_: completed)

    generated = client.post(
        f"/v1/trade-reviews/{review['id']}/generate-draft", json={}
    )
    assert generated.status_code == 201
    candidate = generated.json()
    assert candidate["candidate_type"] == "review_draft"
    assert candidate["status"] == "pending_confirmation"
    assert client.get(f"/v1/trade-reviews/{review['id']}").json()[
        "current_version"
    ] is None
    other = TestClient(app)
    _create_user(other, "Review Candidate Other")
    assert other.get(f"/v1/ai-writebacks/{candidate['id']}").status_code == 404
    assert (
        other.post(f"/v1/ai-writebacks/{candidate['id']}/confirm").status_code
        == 404
    )
    confirmed_candidate = client.post(
        f"/v1/ai-writebacks/{candidate['id']}/confirm"
    )
    assert confirmed_candidate.status_code == 200
    draft = confirmed_candidate.json()["trade_review"]
    assert draft["status"] == "draft"
    assert draft["current_version"]["created_source"] == "ai"
    assert draft["current_version"]["source_run_id"] == run["id"]
    assert "即时生成" in draft["current_version"]["logic_result"]
    repeated = client.post(f"/v1/ai-writebacks/{candidate['id']}/confirm")
    assert repeated.status_code == 200
    assert repeated.json()["trade_review"]["current_version"]["id"] == draft[
        "current_version"
    ]["id"]

    edited = client.patch(
        f"/v1/trade-reviews/{review['id']}/draft",
        json={
            "base_version": draft["current_version"]["version_no"],
            "price_result": draft["current_version"]["price_result"],
            "logic_result": "用户核对后认为原逻辑部分成立，但仍需验证现金流。",
            "plan_deviation": "实际数量与计划一致。",
            "bias_tags": ["证据确认偏慢"],
            "improvement_text": "下次在操作前先完成现金流证据核验。",
        },
    )
    assert edited.status_code == 200
    user_draft = edited.json()
    assert user_draft["current_version"]["created_source"] == "user"
    assert len(user_draft["versions"]) == 2

    confirmed = client.post(
        f"/v1/trade-reviews/{review['id']}/confirm",
        json={"base_version": user_draft["current_version"]["version_no"]},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "confirmed"
    archived = client.post(
        f"/v1/trade-reviews/{review['id']}/archive",
        json={"base_version": user_draft["current_version"]["version_no"]},
    )
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"
