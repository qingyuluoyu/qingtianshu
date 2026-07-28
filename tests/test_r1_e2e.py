from __future__ import annotations

import json

from fastapi.testclient import TestClient


SYMBOL = "000063.SZ"


def _create_user(client: TestClient, name: str) -> dict:
    response = client.post("/users", json={"name": name})
    assert response.status_code == 201
    return response.json()


def _group(payload: dict, key: str) -> list[dict]:
    return next(
        (group["items"] for group in payload["groups"] if group["key"] == key),
        [],
    )


def _seed_search_universe(app) -> None:
    run = app.state.database.start_tushare_sync_run(
        job_scope="universe:a_share",
        as_of_date="2026-07-22",
        datasets=["stock_basic", "daily_basic"],
    )
    app.state.database.save_tushare_dataset_snapshot(
        dataset="a_share_universe",
        scope_key="all",
        as_of_date="2026-07-22",
        report_period=None,
        source_updated_at="2026-07-22T15:00:00+08:00",
        sync_run_id=run["id"],
        data_version="r1-e2e-universe-v1",
        data_status="stable",
        payload={
            "as_of_date": "2026-07-22",
            "items": [
                {
                    "symbol": SYMBOL,
                    "ts_code": SYMBOL,
                    "name": "中兴通讯",
                    "industry": "通信设备",
                    "market": "主板",
                    "exchange": "SZSE",
                }
            ],
        },
    )


def _seed_operation_context(app) -> None:
    with app.state.database.connect() as connection:
        connection.execute(
            """
            INSERT INTO market_bars(
                symbol, interval, timestamp, open, high, low, close,
                adjusted_close, volume, source, fetched_at
            ) VALUES ('000063.SZ', '1d', '2026-07-09T15:00:00+08:00',
                      10, 11, 9, 10.5, 10.5, 1000, 'r1-e2e',
                      '2026-07-09T15:01:00+08:00')
            """
        )
        connection.execute(
            """
            INSERT INTO market_bars(
                symbol, interval, timestamp, open, high, low, close,
                adjusted_close, volume, source, fetched_at
            ) VALUES ('000001.SS', '1d', '2026-07-09T15:00:00+08:00',
                      3000, 3010, 2990, 3005, 3005, 1000, 'r1-e2e',
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
            ) VALUES ('r1-e2e-valuation', '000063.SZ', '中兴通讯', 'CNY',
                      10.5, 10, 5, 1, 20, 20, 20, 2, 1, 2,
                      '2026-07-09T15:00:00+08:00', 'r1-e2e',
                      'https://example.invalid/r1-e2e/valuation', '{}', '[]',
                      '2026-07-09T15:01:00+08:00')
            """
        )
        connection.execute(
            """
            INSERT INTO research_reports(
                id, symbol, name, title, summary, body, status, fingerprint,
                evidence_json, run_id, market_timestamp, generated_at
            ) VALUES ('r1-e2e-report', '000063.SZ', '中兴通讯', '操作前研究',
                      '利润与经营现金流仍需核验', '确定性测试证据正文', 'published',
                      'r1-e2e-report-fingerprint', '{}', NULL,
                      '2026-07-09T15:00:00+08:00',
                      '2026-07-09T16:00:00+08:00')
            """
        )


def _seed_three_following_sessions(app) -> None:
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
            ) VALUES ('000063.SZ', '1d', ?, ?, ?, ?, ?, ?, 1000, 'r1-e2e', ?)
            """,
            [
                (timestamp, close, close, close, close, close, timestamp)
                for timestamp, close in rows
            ],
        )


def _install_completed_agent_stub(app, monkeypatch) -> None:
    def completed_run(**kwargs):
        user = kwargs["user"]
        intent = kwargs["intent"]
        message = kwargs["message"]
        evidence = kwargs["evidence"]
        if intent == "trade_review":
            answer = json.dumps(
                {
                    "logic_result": (
                        "即时复盘认为原判断仅部分成立，经营现金流证据仍需继续核验。"
                        "操作价低于持仓成本，本次属于亏损卖出。"
                    ),
                    "plan_deviation": "本次减仓数量与已记录事实一致。",
                    "bias_tags": ["确认偏差", "可得性启发"],
                    "improvement_text": (
                        "下次操作前先完成现金流与订单兑现的交叉核验，"
                        "并加入thesis的watch_items。"
                    ),
                },
                ensure_ascii=False,
            )
        else:
            answer = (
                f"即时生成研究：{message} 当前支持与反方证据并存，"
                "经营现金流和订单兑现仍是失效条件的关键核验项。"
            )
        run = app.state.database.create_run(
            user_id=user["id"],
            intent=intent,
            model_tier=kwargs["model_tier"],
            input_data={"message": message},
            workspace_path=app.state.settings.workspace_root,
        )
        app.state.database.finish_run(
            run["id"],
            user["id"],
            "completed",
            evidence,
            answer,
            {"prompt_tokens": 1, "completion_tokens": 1},
        )
        return app.state.database.get_run(run["id"], user["id"])

    monkeypatch.setattr(app.state.agent, "run", completed_run)


def test_r1_complete_research_to_archived_review_is_refreshable_and_isolated(
    app, monkeypatch
) -> None:
    _seed_search_universe(app)
    _install_completed_agent_stub(app, monkeypatch)
    owner = TestClient(app)
    owner_user = _create_user(owner, "R1 E2E Owner")

    # 新用户从真实搜索结果进入股票空间，而不是直接调用内部服务造空间。
    searched = owner.get("/v1/search", params={"q": "中兴"})
    assert searched.status_code == 200
    stock = _group(searched.json(), "stocks")[0]
    assert stock["symbol"] == SYMBOL
    added = owner.post(
        "/me/watchlist",
        json={
            "symbol": stock["symbol"],
            "name": stock["title"],
            "market": "A股",
        },
    )
    assert added.status_code == 200
    relation = owner.get(f"/v1/stocks/{SYMBOL}/relation")
    assert relation.status_code == 200
    assert relation.json()["relation_type"] == "watching"
    assert relation.json()["active_thesis"] is None

    thesis_response = owner.post(
        f"/v1/stocks/{SYMBOL}/theses",
        json={
            "reason_text": "关注利润、经营现金流和订单兑现能否同步改善。",
            "watch_items": ["经营现金流", "订单兑现"],
            "recheck_conditions": ["利润和现金流背离时重新判断"],
            "source": "user",
            "base_version": 0,
        },
    )
    assert thesis_response.status_code == 201
    thesis = thesis_response.json()
    assert thesis["status"] == "draft"
    confirmed_thesis = owner.post(
        f"/v1/stocks/{SYMBOL}/theses/{thesis['id']}/confirm"
    )
    assert confirmed_thesis.status_code == 200
    restored_theses = owner.get(f"/v1/stocks/{SYMBOL}/theses").json()
    assert restored_theses["active"]["id"] == thesis["id"]
    assert restored_theses["active"]["status"] == "active"

    deep_stock = owner.post("/me/deep-stock", json={"symbol": SYMBOL})
    assert deep_stock.status_code == 201
    conversation_id = deep_stock.json()["conversation_id"]
    restored_deep_stock = owner.get(f"/me/deep-stock/{SYMBOL}").json()
    assert restored_deep_stock["conversation_id"] == conversation_id

    message = (
        "分析中兴通讯并把“继续核验经营现金流与订单兑现”"
        "保存为核验任务，供我确认。"
    )
    chat = owner.post(
        "/me/chat",
        json={
            "message": message,
            "symbol": SYMBOL,
            "conversation_id": conversation_id,
            "model_tier": "economy",
            "execute_agent": True,
        },
    )
    assert chat.status_code == 200
    chat_payload = chat.json()
    assert chat_payload["status"] == "completed"
    assert chat_payload["conversation_id"] == conversation_id
    assert chat_payload["answer"].startswith("即时生成研究：")
    candidates = [
        item
        for item in chat_payload["structured_answer"]["candidate_writebacks"]
        if item["candidate_type"] == "observation_task"
    ]
    assert len(candidates) == 1
    observation_candidate = candidates[0]
    restored_conversation = owner.get(
        f"/me/conversations/{conversation_id}"
    ).json()
    assert (
        restored_conversation["messages"][-1]["metadata"]["structured_answer"][
            "candidate_writebacks"
        ][0]["id"]
        == observation_candidate["id"]
    )
    assert owner.get("/v1/observation-tasks").json()["items"] == []
    restored_candidate = owner.get(
        f"/v1/ai-writebacks/{observation_candidate['id']}"
    )
    assert restored_candidate.status_code == 200
    assert restored_candidate.json()["status"] == "pending_confirmation"

    confirmed_candidate = owner.post(
        f"/v1/ai-writebacks/{observation_candidate['id']}/confirm"
    )
    assert confirmed_candidate.status_code == 200
    observation_task = confirmed_candidate.json()["observation_task"]
    restored_task = owner.get(
        f"/v1/observation-tasks/{observation_task['id']}"
    ).json()
    assert restored_task["status"] == "pending"
    assert "经营现金流与订单兑现" in restored_task["description"]

    opening = owner.post(
        f"/v1/stocks/{SYMBOL}/position/opening",
        headers={"Idempotency-Key": "r1-e2e-opening"},
        json={
            "as_of_date": "2026-07-01",
            "quantity": "100",
            "cost_price": "10",
            "fees": "5",
            "note": "期初持仓",
        },
    )
    assert opening.status_code == 201
    restored_opening = owner.get(f"/v1/stocks/{SYMBOL}/position").json()
    assert restored_opening["current"]["quantity"] == "100.000000"
    assert len(restored_opening["snapshots"]) == 1

    _seed_operation_context(app)
    operation = owner.post(
        f"/v1/stocks/{SYMBOL}/operations",
        headers={"Idempotency-Key": "r1-e2e-reduce"},
        json={
            "operation_type": "reduce",
            "operated_at": "2026-07-10T10:00:00+08:00",
            "price": "10",
            "quantity": "10",
            "fees": "1",
            "reason_text": "基于已确认判断，记录一次真实减仓。",
            "plan_id": None,
        },
    )
    assert operation.status_code == 201
    restored_position = owner.get(f"/v1/stocks/{SYMBOL}/position").json()
    assert restored_position["current"]["quantity"] == "90.000000"
    assert len(restored_position["operations"]) == 1
    assert len(restored_position["snapshots"]) == 2

    waiting_reviews = owner.get(
        f"/v1/stocks/{SYMBOL}/trade-reviews"
    ).json()["items"]
    assert len(waiting_reviews) == 1
    review_id = waiting_reviews[0]["id"]
    assert waiting_reviews[0]["status"] == "waiting_data"
    assert waiting_reviews[0]["context_snapshot"]["thesis"]["id"] == thesis["id"]
    assert (
        waiting_reviews[0]["context_snapshot"]["data_completeness"]["status"]
        == "partial"
    )

    _seed_three_following_sessions(app)
    ready = owner.get(f"/v1/trade-reviews/{review_id}").json()
    assert ready["status"] == "ready"
    assert ready["price_observation"]["available_sessions"] == 3
    assert ready["price_observation"]["price_change_pct"] == "-5.00"

    generated = owner.post(
        f"/v1/trade-reviews/{review_id}/generate-draft",
        json={"base_version": 0, "model_tier": "economy"},
    )
    assert generated.status_code == 201
    review_candidate = generated.json()
    assert review_candidate["candidate_type"] == "review_draft"
    assert review_candidate["status"] == "pending_confirmation"
    assert "亏损卖出" not in review_candidate["payload"]["logic_result"]
    assert review_candidate["payload"]["bias_tags"] == ["未关联操作计划"]
    assert "thesis" not in review_candidate["payload"]["improvement_text"]
    assert "watch_items" not in review_candidate["payload"]["improvement_text"]
    assert owner.get(f"/v1/trade-reviews/{review_id}").json()[
        "current_version"
    ] is None

    other = TestClient(app)
    _create_user(other, "R1 E2E Other")
    assert other.get(f"/v1/stocks/{SYMBOL}/relation").status_code == 404
    assert (
        other.get(f"/me/conversations/{conversation_id}").status_code == 404
    )
    assert (
        other.get(f"/v1/observation-tasks/{observation_task['id']}").status_code
        == 404
    )
    assert (
        other.get(f"/v1/ai-writebacks/{review_candidate['id']}").status_code
        == 404
    )
    assert other.get(f"/v1/trade-reviews/{review_id}").status_code == 404

    confirmed_review_candidate = owner.post(
        f"/v1/ai-writebacks/{review_candidate['id']}/confirm"
    )
    assert confirmed_review_candidate.status_code == 200
    ai_draft = owner.get(f"/v1/trade-reviews/{review_id}").json()
    assert ai_draft["status"] == "draft"
    assert ai_draft["current_version"]["created_source"] == "ai"
    assert "即时复盘" in ai_draft["current_version"]["logic_result"]

    edited = owner.patch(
        f"/v1/trade-reviews/{review_id}/draft",
        json={
            "base_version": ai_draft["current_version"]["version_no"],
            "price_result": ai_draft["current_version"]["price_result"],
            "logic_result": "用户复核后确认原判断部分成立，但现金流证据仍不足。",
            "plan_deviation": "实际减仓数量符合本次记录。",
            "bias_tags": ["证据确认偏慢"],
            "improvement_text": "以后在操作前先完成现金流证据核验。",
        },
    )
    assert edited.status_code == 200
    user_draft = owner.get(f"/v1/trade-reviews/{review_id}").json()
    assert user_draft["current_version"]["created_source"] == "user"
    assert len(user_draft["versions"]) == 2

    confirmed_review = owner.post(
        f"/v1/trade-reviews/{review_id}/confirm",
        json={"base_version": user_draft["current_version"]["version_no"]},
    )
    assert confirmed_review.status_code == 200
    assert confirmed_review.json()["status"] == "confirmed"
    archived = owner.post(
        f"/v1/trade-reviews/{review_id}/archive",
        json={"base_version": user_draft["current_version"]["version_no"]},
    )
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"

    restored_archive = owner.get(f"/v1/trade-reviews/{review_id}").json()
    assert restored_archive["status"] == "archived"
    assert restored_archive["current_version"]["created_source"] == "user"
    archived_center = owner.get(
        "/v1/trade-reviews", params={"status": "archived"}
    ).json()["items"]
    assert [item["id"] for item in archived_center] == [review_id]
    assert app.state.database.get_user(owner_user["id"]) is not None
