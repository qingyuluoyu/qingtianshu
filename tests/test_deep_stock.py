from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def _create_user(client: TestClient, name: str) -> dict:
    response = client.post("/users", json={"name": name})
    assert response.status_code == 201
    return response.json()


def _stage(payload: dict, key: str) -> dict:
    return next(item for item in payload["stages"] if item["key"] == key)


def test_deep_stock_api_binds_existing_conversation_and_is_user_isolated(app):
    client = TestClient(app)
    user = _create_user(client, "Deep Stock User")
    app.state.database.upsert_watchlist(
        user["id"],
        "000063.SZ",
        "中兴通讯",
        "A股",
        "关注算力业务、利润质量和现金流能否同步改善",
    )
    conversation = client.post(
        "/me/conversations", json={"title": "中兴通讯原有研究"}
    ).json()

    created = client.post(
        "/me/deep-stock",
        json={
            "symbol": "000063",
            "conversation_id": conversation["id"],
        },
    )
    assert created.status_code == 201
    payload = created.json()
    assert payload["symbol"] == "000063.SZ"
    assert payload["conversation_id"] == conversation["id"]
    assert payload["workflow_version"] == "guided_deep_stock_v1"
    assert payload["progress"] == {"completed": 1, "total": 7, "percent": 14}
    assert _stage(payload, "original_thesis")["status"] == "completed"
    assert _stage(payload, "company_industry")["status"] == "in_progress"
    assert payload["current_stage"]["key"] == "company_industry"
    assert payload["evidence_coverage"]["summary"] == {
        "sufficient": 0,
        "partial": 0,
        "insufficient": 0,
        "unavailable": 6,
        "total": 6,
        "refresh_attention": 0,
    }
    assert len(payload["coverage_tasks"]) == 6

    guarded = app.state.deep_stock.observe_chat(
        user_id=user["id"],
        conversation_id=conversation["id"],
        symbol="000063.SZ",
        intent="stock_research",
        message="请研究中兴通讯",
        run={"id": None, "status": "guarded"},
        evidence={},
    )
    assert guarded is not None
    assert guarded["evidence_coverage"]["summary"]["total"] == 6
    assert guarded["evidence_coverage"]["summary"]["unavailable"] == 6
    assert len(guarded["coverage_tasks"]) == 6

    listed = client.get("/me/deep-stock")
    assert listed.status_code == 200
    assert listed.json()["summary"]["active"] == 1
    assert listed.json()["items"][0]["conversation"]["message_count"] == 0
    assert client.get("/me/deep-stock/000063").status_code == 200

    other = TestClient(app)
    _create_user(other, "Deep Stock Other")
    assert other.get("/me/deep-stock/000063").status_code == 404


def test_guarded_runs_do_not_complete_stages_but_valid_evidence_does(app):
    client = TestClient(app)
    user = _create_user(client, "Deep Workflow User")
    app.state.database.upsert_watchlist(
        user["id"],
        "000063.SZ",
        "中兴通讯",
        "A股",
        "验证利润、现金流和业务结构",
    )
    session = client.post("/me/deep-stock", json={"symbol": "000063"}).json()
    evidence = {
        "metrics": {
            "latest_close": 40.0,
            "return_20d_pct": 8.0,
            "ma20": 38.0,
            "rsi_14": 55.0,
        },
        "research_frame": {"missing_information": []},
        "business_structure": {
            "status": "available",
            "anchor_report_date": "2025-12-31",
            "dimensions": [{"classification": "product"}],
        },
        "fundamentals": {
            "status": "available",
            "financial_periods": [{"report_period": "2026-03-31"}],
            "valuation": {"price": 40.0, "pe_ttm": 20.0},
        },
        "earnings_quality": {
            "status": "available",
            "report_period": "2026-03-31",
            "factors": [{"label": "利润质量"}],
        },
        "financial_drivers": {
            "status": "available",
            "report_period": "2026-03-31",
            "confirmed_mechanical_drivers": [{"label": "毛利变化"}],
        },
        "peer_comparison": {
            "status": "available",
            "metrics": [{"key": "pe_ttm"}],
            "peers": [{"symbol": "600498.SS"}],
        },
        "analyst_expectations": {
            "status": "available",
            "industry": "通信设备",
            "forecast_eps": [{"year": 2026, "value": 1.4}],
        },
        "event_timeline": {
            "status": "available",
            "events": [{"title": "季度报告"}],
        },
        "a_share_information": {
            "status": "available",
            "announcements": [{"title": "季度报告"}],
        },
        "evidence_debate": {
            "status": "available",
            "bear_case": [{"claim": "利润承压"}],
            "risk_committee": [{"risk": "现金流背离"}],
        },
        "analysis_board": {
            "modules": [
                {"key": "fundamental", "label": "基本面", "status": "ready"}
            ]
        },
        "conditional_outlook": {
            "status": "available",
            "label": "条件观察",
            "scenarios": [{"label": "区间"}],
        },
    }

    guarded = app.state.deep_stock.observe_chat(
        user_id=user["id"],
        conversation_id=session["conversation_id"],
        symbol="000063.SZ",
        intent="stock_research",
        message="请完整分析中兴通讯",
        run={"id": None, "status": "guarded"},
        evidence=evidence,
    )
    assert guarded is not None
    assert guarded["progress"]["completed"] == 1
    assert "没有推进研究阶段" in guarded["unresolved_items"][-1]

    specialized = app.state.deep_stock.observe_chat(
        user_id=user["id"],
        conversation_id=session["conversation_id"],
        symbol="000063.SZ",
        intent="business_structure",
        message="中兴通讯靠什么赚钱，主营结构如何？",
        run={"id": None, "status": "preview"},
        evidence={"status": "available", "rows": [{"item_name": "运营商网络"}]},
    )
    assert specialized is not None
    assert specialized["progress"]["completed"] == 1
    assert _stage(specialized, "company_industry")["status"] == "in_progress"
    specialized_coverage = {
        item["key"]: item
        for item in specialized["evidence_coverage"]["dimensions"]
    }
    assert specialized_coverage["company_operating"]["coverage_status"] == "sufficient"
    assert len(specialized["coverage_history"]) == 1

    researched = app.state.deep_stock.observe_chat(
        user_id=user["id"],
        conversation_id=session["conversation_id"],
        symbol="000063.SZ",
        intent="stock_research",
        message="请完整分析并主动检查反方证据",
        run={"id": None, "status": "completed"},
        evidence=evidence,
    )
    assert researched is not None
    assert researched["progress"]["completed"] == 6
    assert _stage(researched, "counterevidence")["status"] == "completed"
    assert _stage(researched, "invalidation_next")["status"] == "in_progress"

    completed = app.state.deep_stock.observe_chat(
        user_id=user["id"],
        conversation_id=session["conversation_id"],
        symbol="000063.SZ",
        intent="stock_research",
        message="请总结失效条件、下一步需要核验的证据和观察条件",
        run={"id": None, "status": "completed"},
        evidence=evidence,
    )
    assert completed is not None
    assert completed["status"] == "completed"
    assert completed["progress"]["completed"] == 7
    assert completed["current_stage"] is None
    coverage = completed["evidence_coverage"]
    assert coverage["summary"] == {
        "sufficient": 6,
        "partial": 0,
        "insufficient": 0,
        "unavailable": 0,
        "total": 6,
        "refresh_attention": 0,
    }
    assert {item["key"] for item in coverage["dimensions"]} == {
        "company_operating",
        "financial_quality",
        "industry_relative",
        "valuation",
        "technical_state",
        "risk_events",
    }

    stored_user = app.state.database.get_user(user["id"])
    snapshot = (
        Path(stored_user["workspace_path"])
        / "deep-stock"
        / "000063_SZ.json"
    )
    assert snapshot.is_file()
    assert '"guided_deep_stock_v1"' in snapshot.read_text(encoding="utf-8")

    restored = client.get("/me/deep-stock/000063").json()
    assert restored["evidence_coverage"]["summary"]["sufficient"] == 6
    assert restored["coverage_tasks"] == []
    assert len(restored["coverage_history"]) == 3

    thinned = app.state.deep_stock.observe_chat(
        user_id=user["id"],
        conversation_id=session["conversation_id"],
        symbol="000063.SZ",
        intent="stock_research",
        message="只刷新一个很薄的专项数据包",
        run={"id": None, "status": "completed"},
        evidence={
            "business_structure": {"status": "available"},
            "analysis_board": {"modules": []},
        },
    )
    assert thinned is not None
    assert thinned["evidence_coverage"]["summary"] == {
        "sufficient": 6,
        "partial": 0,
        "insufficient": 0,
        "unavailable": 0,
        "total": 6,
        "refresh_attention": 6,
    }
    assert len(thinned["coverage_tasks"]) == 6
    assert all(
        task["coverage_status"] == "sufficient"
        and task["last_observed_status"] != "sufficient"
        for task in thinned["coverage_tasks"]
    )
    history_before_failure = list(thinned["coverage_history"])

    failed = app.state.deep_stock.observe_chat(
        user_id=user["id"],
        conversation_id=session["conversation_id"],
        symbol="000063.SZ",
        intent="stock_research",
        message="本轮模型输出未通过校验",
        run={"id": None, "status": "guarded"},
        evidence={},
    )
    assert failed is not None
    assert failed["evidence_coverage"]["summary"]["sufficient"] == 6
    assert failed["coverage_history"] == history_before_failure
    assert "没有推进研究阶段" in failed["unresolved_items"][-1]

    restored_after_failure = client.get("/me/deep-stock/000063").json()
    assert restored_after_failure["evidence_coverage"] == failed["evidence_coverage"]
    assert restored_after_failure["coverage_tasks"] == failed["coverage_tasks"]
    assert restored_after_failure["coverage_history"] == history_before_failure


def test_thin_packets_do_not_advance_research_stages(app):
    client = TestClient(app)
    user = _create_user(client, "Coverage Gate User")
    app.state.database.upsert_watchlist(
        user["id"],
        "000063.SZ",
        "中兴通讯",
        "A股",
        "验证业务结构和利润质量",
    )
    session = client.post("/me/deep-stock", json={"symbol": "000063"}).json()

    observed = app.state.deep_stock.observe_chat(
        user_id=user["id"],
        conversation_id=session["conversation_id"],
        symbol="000063.SZ",
        intent="stock_research",
        message="请完整分析中兴通讯",
        run={"id": None, "status": "completed"},
        evidence={
            "business_structure": {"status": "available"},
            "fundamentals": {"status": "available"},
            "peer_comparison": {"status": "available"},
            "event_timeline": {"status": "available"},
            "analysis_board": {"modules": []},
        },
    )

    assert observed is not None
    assert observed["progress"]["completed"] == 1
    assert _stage(observed, "company_industry")["status"] == "in_progress"
    coverage = {
        item["key"]: item for item in observed["evidence_coverage"]["dimensions"]
    }
    assert coverage["company_operating"]["coverage_status"] == "insufficient"
    assert coverage["financial_quality"]["coverage_status"] == "insufficient"
