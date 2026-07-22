from __future__ import annotations

from fastapi.testclient import TestClient


def _create_user(client: TestClient, name: str) -> dict:
    response = client.post("/users", json={"name": name})
    assert response.status_code == 201
    return response.json()


def _workspace_evidence() -> dict:
    return {
        "generated_at": "2026-07-22T15:00:00+08:00",
        "display_name": "中兴通讯",
        "current_quote": {
            "name": "中兴通讯",
            "price": 40.8,
            "pct_change": -2.3,
            "currency": "CNY",
            "quote_label": "最新报价",
            "market_timestamp": "2026-07-22T14:55:00+08:00",
        },
        "metrics": {
            "latest_close": 41.76,
            "return_1d_pct": -1.1,
            "return_20d_pct": 8.0,
            "ma20": 38.0,
            "rsi_14": 55.0,
        },
        "provenance": {"market_timestamp": "2026-07-21T15:00:00+08:00"},
        "research_frame": {
            "missing_information": ["核验下一份财报中的经营现金流变化"]
        },
        "business_structure": {
            "status": "available",
            "anchor_report_date": "2025-12-31",
            "dimensions": [{"classification": "product"}],
        },
        "fundamentals": {
            "status": "available",
            "financial_periods": [{"report_period": "2026-03-31"}],
            "valuation": {
                "price": 40.8,
                "pe_ttm": 20.0,
                "market_timestamp": "2026-07-22T14:55:00+08:00",
            },
        },
        "earnings_quality": {
            "status": "available",
            "report_period": "2026-03-31",
            "generated_at": "2026-07-22T12:00:00+08:00",
            "latest_report": {"report_date": "2026-03-31"},
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
            "bear_case": [
                {
                    "claim": "利润承压",
                    "evidence": "毛利率同比下降",
                    "source": "deterministic_earnings_quality",
                }
            ],
            "risk_committee": [
                {
                    "risk": "现金流背离",
                    "evidence": "经营现金流弱于利润",
                    "action": "核验应收账款和存货变化",
                }
            ],
        },
        "analysis_board": {
            "tracking_plan": [
                {
                    "horizon_sessions": 5,
                    "checks": ["复核公告、现金流和行业相对表现"],
                }
            ]
        },
        "conditional_outlook": {
            "status": "available",
            "label": "条件观察",
            "invalidation": "价格跨越关键参考位后必须重算当前判断。",
            "scenarios": [
                {
                    "name": "下行风险",
                    "condition": "收盘跌破关键参考位，同时20日收益继续恶化",
                    "meaning": "原有判断需要重新核验。",
                }
            ],
        },
    }


def test_workspace_returns_honest_candidate_empty_state(app):
    client = TestClient(app)
    _create_user(client, "Workspace Candidate")

    response = client.get("/v1/stocks/300308/workspace")

    assert response.status_code == 200
    payload = response.json()
    assert payload["contract_version"] == "stock_workspace_v1"
    assert payload["symbol"] == "300308.SZ"
    assert payload["relation"]["type"] is None
    assert payload["relation"]["preview_state"] == "candidate"
    assert payload["thesis"]["status"] == "empty"
    assert payload["stage_progress"]["status"] == "not_started"
    assert payload["latest_report"] is None
    assert payload["conversation"] is None
    assert payload["position_snapshot"] == {
        "available": False,
        "status": "not_configured",
    }
    assert payload["completeness"]["has_stock_space"] is False
    assert "尚未加入股票研究空间" in payload["completeness"]["missing_items"]


def test_workspace_aggregates_private_context_and_public_evidence(app):
    client = TestClient(app)
    user = _create_user(client, "Workspace Owner")
    database = app.state.database
    database.upsert_watchlist(
        user["id"],
        "000063.SZ",
        "中兴通讯",
        "A股",
        "关注算力业务、利润质量和经营现金流是否同步改善",
    )
    report = database.create_research_report(
        symbol="000063.SZ",
        name="中兴通讯",
        title="中兴通讯研究快照",
        summary="价格走弱与经营证据需要交叉核验。",
        body="研究正文",
        status="completed",
        fingerprint=f"workspace-{user['id']}",
        evidence=_workspace_evidence(),
        run_id=None,
        market_timestamp="2026-07-21T15:00:00+08:00",
    )
    database.save_research_change_event(
        symbol="000063.SZ",
        report_id=report["id"],
        previous_report_id=None,
        event_type="evidence_change",
        severity="attention",
        summary="利润和现金流反证需要复核。",
        payload={
            "data_as_of": "2026-07-21T15:00:00+08:00",
            "changes": [{"detail": "利润质量出现新的反方证据。"}],
            "new_evidence": [],
        },
    )
    duplicate_report = database.create_research_report(
        symbol="000063.SZ",
        name="中兴通讯",
        title="中兴通讯研究快照（刷新）",
        summary="价格走弱与经营证据需要交叉核验。",
        body="研究正文（刷新）",
        status="completed",
        fingerprint=f"workspace-refresh-{user['id']}",
        evidence=_workspace_evidence(),
        run_id=None,
        market_timestamp="2026-07-21T15:00:00+08:00",
    )
    database.save_research_change_event(
        symbol="000063.SZ",
        report_id=duplicate_report["id"],
        previous_report_id=report["id"],
        event_type="evidence_change",
        severity="attention",
        summary="利润和现金流反证需要复核。",
        payload={
            "data_as_of": "2026-07-21T15:00:00+08:00",
            "changes": [{"detail": "利润质量出现新的反方证据。"}],
            "new_evidence": [],
        },
    )
    started = client.post("/me/deep-stock", json={"symbol": "000063"})
    assert started.status_code == 201

    response = client.get("/v1/stocks/000063/workspace")

    assert response.status_code == 200
    payload = response.json()
    assert payload["name"] == "中兴通讯"
    assert payload["relation"]["type"] == "watching"
    assert payload["relation"]["priority"] == "normal"
    assert payload["relation"]["workflow_status"] == "researching"
    assert payload["thesis"]["source"] == "legacy_watchlist_confirmed"
    assert payload["thesis"]["version"] == 1
    assert payload["conversation"]["id"] == started.json()["conversation_id"]
    assert payload["overview"]["quote"]["price"] == 40.8
    assert payload["overview"]["quote"]["daily_close"] == 41.76
    assert payload["overview"]["quote_meta"] == {
        "quote_as_of": "2026-07-22T14:55:00+08:00",
        "daily_as_of": "2026-07-21T15:00:00+08:00",
        "semantic_label": "最新报价",
        "dual_time_anchor": True,
    }
    assert payload["important_changes"][0]["summary"] == "利润和现金流反证需要复核。"
    assert len(payload["important_changes"]) == 1
    assert payload["evidence_summary"]["summary"]["sufficient"] == 6
    assert {item["kind"] for item in payload["counterevidence"]} == {
        "bear_case",
        "risk_committee",
    }
    assert payload["claim_ledger"]["method"] == "structured_claim_ledger_v1"
    assert payload["claim_ledger"]["summary"]["weakens"] == 1
    assert payload["counterevidence"][0]["source_name"] == "财报质量确定性分析"
    assert payload["counterevidence"][0]["data_time"] == "2026-03-31"
    assert payload["counterevidence"][0]["coverage_status"] == "partial"
    assert payload["invalidation_conditions"][0]["kind"] == "overall_invalidation"
    assert any(
        "经营现金流" in item["description"]
        for item in payload["next_evidence"]
    )
    assert payload["latest_report"]["body"] in {"研究正文", "研究正文（刷新）"}
    assert payload["data_meta"]["private_context_user_isolated"] is True

    evidence_response = client.get("/v1/stocks/000063/workspace/evidence")
    assert evidence_response.status_code == 200
    assert evidence_response.json()["contract_version"] == (
        "stock_workspace_evidence_v1"
    )
    assert evidence_response.json()["claim_ledger"]["claims"]

    timeline_response = client.get("/v1/stocks/000063/workspace/timeline")
    assert timeline_response.status_code == 200
    assert timeline_response.json()["contract_version"] == (
        "stock_workspace_timeline_v1"
    )
    assert len(timeline_response.json()["important_changes"]) == 1

    actions_response = client.get("/v1/stocks/000063/workspace/actions")
    assert actions_response.status_code == 200
    assert actions_response.json()["contract_version"] == (
        "stock_workspace_actions_v1"
    )
    assert "不生成买卖" in actions_response.json()["boundary"]


def test_workspace_does_not_leak_another_users_private_context(app):
    owner = TestClient(app)
    owner_user = _create_user(owner, "Workspace Private Owner")
    app.state.database.upsert_watchlist(
        owner_user["id"],
        "000063.SZ",
        "中兴通讯",
        "A股",
        "这是仅属于甲用户的私人判断",
    )
    owner_session = owner.post("/me/deep-stock", json={"symbol": "000063"})
    assert owner_session.status_code == 201

    other = TestClient(app)
    _create_user(other, "Workspace Other User")
    response = other.get("/api/v1/stocks/000063/workspace")

    assert response.status_code == 200
    payload = response.json()
    assert payload["relation"]["type"] is None
    assert payload["relation"]["preview_state"] == "candidate"
    assert payload["thesis"]["summary"] is None
    assert payload["conversation"] is None
    assert all(
        "这是仅属于甲用户的私人判断" not in str(value)
        for value in payload.values()
    )
