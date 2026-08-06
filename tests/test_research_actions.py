from __future__ import annotations


def _create_user(client, name: str) -> dict:
    response = client.post("/users", json={"name": name})
    assert response.status_code == 201
    return response.json()


def _action_evidence() -> dict:
    return {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "display_name": "中兴通讯",
        "metrics": {
            "latest_close": 33.0,
            "return_1d_pct": -5.0,
            "return_20d_pct": -12.0,
            "ma20": 38.0,
            "max_drawdown_60d_pct": -25.0,
            "volatility_20d_annualized_pct": 70.0,
            "volume_ratio_5_20": 1.8,
            "technical_state": "动量转弱",
        },
        "evidence_readiness": {
            "status": "ready",
            "missing_core_modules": [],
            "optional_gaps": ["行业供需与一致预期尚未接入"],
        },
        "business_structure": {
            "coverage_limits": [
                {
                    "label": "订单与在手订单",
                    "boundary": "主营收入不等于新增订单。",
                    "next_evidence": "公司公告或业绩说明会记录。",
                }
            ]
        },
        "analysis_board": {
            "ready_modules": 6,
            "total_modules": 6,
            "tracking_plan": [
                {
                    "horizon_sessions": 3,
                    "focus": "确认价格结构与信息增量",
                    "checks": ["检查MA20位置", "检查公告和现金流"],
                }
            ],
        },
    }


def _seed_action_report(client, app, name: str = "Action User") -> dict:
    user = _create_user(client, name)
    database = app.state.database
    database.upsert_watchlist(
        user["id"],
        "000063.SZ",
        "中兴通讯",
        "A股",
        "验证订单、利润兑现和经营现金流",
    )
    report = database.create_research_report(
        symbol="000063.SZ",
        name="中兴通讯",
        title="中兴通讯研究快照",
        summary="研究摘要",
        body="研究正文",
        status="preview",
        fingerprint=f"research-actions-{user['id']}",
        evidence=_action_evidence(),
        run_id=None,
        market_timestamp="2026-07-21T13:30:00+08:00",
    )
    database.save_research_change_event(
        symbol="000063.SZ",
        report_id=report["id"],
        previous_report_id=None,
        event_type="evidence_change",
        severity="attention",
        summary="回撤、波动与财务反证需要重新复核。",
        payload={
            "changes": [
                {"detail": "60日最大回撤扩大至 -25%。"},
            ],
            "new_evidence": [],
        },
    )
    return user


def test_research_actions_build_persistent_observation_worklist(client, app):
    user = _seed_action_report(client, app)

    response = client.get("/me/research-actions")

    assert response.status_code == 200
    payload = response.json()
    assert payload["method"] == "deterministic_research_action_board_v1"
    assert payload["summary"]["symbols"] == 1
    assert payload["summary"]["triggered"] >= 5
    assert payload["summary"]["pending_data"] >= 2
    item = payload["items"][0]
    assert item["symbol"] == "000063.SZ"
    assert item["research_status"] == "risk_review"
    action_keys = {action["key"] for action in item["actions"]}
    assert action_keys >= {
        "evidence_change",
        "drawdown_review",
        "volatility_review",
        "ma20_structure",
        "volume_change",
        "optional_evidence_gap",
        "business_evidence_gap",
        "scheduled_review",
    }
    assert all("买入" not in action["next_step"] for action in item["actions"])
    assert "不是价格提醒" in payload["boundary"]
    assert app.state.database.latest_research_action_snapshot(user["id"]) is not None
    documents = app.state.database.list_knowledge_documents(
        user["id"], include_content=True
    )
    action_document = next(
        item
        for item in documents
        if item["source_key"] == f"research-actions:{user['id']}"
    )
    assert "我的最新研究行动与观察条件" in action_document["title"]
    assert "订单与在手订单" in action_document["content"]
    assert "下一步" in action_document["content"]


def test_chat_routes_research_action_questions_to_dedicated_skill(client, app):
    _seed_action_report(client, app, "Action Chat User")

    response = client.post(
        "/me/chat",
        json={
            "message": "我的研究行动和观察条件是什么？",
            "execute_agent": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"] == "research_actions"
    assert payload["evidence"]["type"] == "research_actions"
    assert "需要复核" in payload["answer"]
    assert "待补证" in payload["answer"]
    assert "不是价格提醒" in payload["answer"]


def test_research_actions_create_baseline_task_when_report_is_missing(client, app):
    user = _create_user(client, "Missing Baseline User")
    app.state.database.upsert_watchlist(
        user["id"], "300308.SZ", "中际旭创", "A股", "验证盈利兑现"
    )

    payload = client.get("/me/research-actions").json()

    item = payload["items"][0]
    assert item["research_status"] == "priority_research"
    assert item["actions"][0]["key"] == "baseline"
    assert item["actions"][0]["status"] == "triggered"
    assert "建立首份" in item["actions"][0]["title"]


def test_research_action_refinement_does_not_duplicate_its_own_knowledge_document(
    client, app, monkeypatch
):
    _seed_action_report(client, app, "Action Refine User")
    client.get("/me/research-actions")
    object.__setattr__(app.state.settings, "hermes_enabled", True)
    captured = {}

    def fake_hermes(**kwargs):
        captured["prompt"] = kwargs["prompt"]
        return "优先复核已经达到条件的标的，并逐项补齐资料缺口。", {"model": "fake"}

    monkeypatch.setattr(app.state.agent, "_execute_hermes", fake_hermes)
    preview = client.post(
        "/me/chat",
        json={
            "message": "我的研究行动和观察条件是什么？",
            "execute_agent": False,
        },
    ).json()

    refined = client.post(
        "/me/chat/refine",
        json={
            "preview_run_id": preview["run_id"],
            "conversation_id": preview["conversation_id"],
            "assistant_message_id": preview["assistant_message_id"],
            "model_tier": "economy",
        },
    )

    assert refined.status_code == 200
    assert refined.json()["status"] == "completed"
    assert "我的最新研究行动与观察条件" not in captured["prompt"]
    assert '"type": "research_actions"' in captured["prompt"]
