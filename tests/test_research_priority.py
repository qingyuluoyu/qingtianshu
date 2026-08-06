from __future__ import annotations

from datetime import datetime, timezone


def _create_user(client, name: str) -> dict:
    response = client.post("/users", json={"name": name})
    assert response.status_code == 201
    return response.json()


def _evidence(symbol: str, *, stressed: bool) -> dict:
    metrics = {
        "latest_close": 33.73 if stressed else 120.0,
        "return_1d_pct": -6.31 if stressed else 0.3,
        "return_20d_pct": -14.46 if stressed else 2.0,
        "max_drawdown_60d_pct": -25.0 if stressed else -4.0,
        "volatility_20d_annualized_pct": 70.0 if stressed else 18.0,
        "technical_state": "动量转弱" if stressed else "技术分化",
        "volume_ratio_5_20": 1.6 if stressed else 0.9,
    }
    latest_report = {
        "report_date": "2026-03-31",
        "revenue_yoy_pct": 6.0,
        "net_profit_yoy_pct": -46.0 if stressed else 8.0,
    }
    return {
        "type": "stock_research",
        "symbol": symbol,
        "display_name": "高风险样本" if stressed else "稳定样本",
        "metrics": metrics,
        "fundamentals": {
            "summary": {
                "latest_report": latest_report,
                "operating_cashflow_to_net_profit": -1.5 if stressed else 1.2,
            }
        },
        "analysis_board": {
            "ready_modules": 6,
            "total_modules": 6,
            "tracking_plan": [
                {
                    "horizon_sessions": 3,
                    "focus": "复核价格结构与新证据",
                    "checks": ["检查MA20位置", "检查公告和现金流"],
                }
            ],
        },
    }


def test_research_priority_ranks_review_urgency_and_persists_snapshot(client, app):
    user = _create_user(client, "Priority User")
    database = app.state.database
    database.upsert_watchlist(user["id"], "000063.SZ", "高风险样本", "A股", "验证利润与现金流")
    database.upsert_watchlist(user["id"], "300308.SZ", "稳定样本", "A股", "持续观察")

    stressed_evidence = _evidence("000063.SZ", stressed=True)
    stressed_evidence["a_share_information"] = {
        "news": [
            {
                "title": "中兴通讯目标价上调丨券商评级观察",
                "published_at": datetime.now(timezone.utc).isoformat(),
            }
        ]
    }
    stressed_report = database.create_research_report(
        symbol="000063.SZ",
        name="高风险样本",
        title="高风险样本研究快照",
        summary="压力证据摘要",
        body="压力证据正文",
        status="preview",
        fingerprint="priority-stressed",
        evidence=stressed_evidence,
        run_id=None,
        market_timestamp="2026-07-20T15:00:00+08:00",
    )
    stable_evidence = _evidence("300308.SZ", stressed=False)
    stable_evidence["a_share_information"] = {
        "news": [
            {
                "title": "某基金季度报告与市场观点",
                "published_at": datetime.now(timezone.utc).isoformat(),
            }
        ]
    }
    database.create_research_report(
        symbol="300308.SZ",
        name="稳定样本",
        title="稳定样本研究快照",
        summary="稳定证据摘要",
        body="稳定证据正文",
        status="preview",
        fingerprint="priority-stable",
        evidence=stable_evidence,
        run_id=None,
        market_timestamp="2026-07-20T15:00:00+08:00",
    )
    database.save_research_change_event(
        symbol="000063.SZ",
        report_id=stressed_report["id"],
        previous_report_id=None,
        event_type="baseline",
        severity="attention",
        summary="高风险样本出现需要复核的重要证据变化。",
        payload={"changes": []},
    )

    response = client.get("/me/research-priority")
    assert response.status_code == 200
    payload = response.json()
    assert payload["method"] == "watchlist_research_urgency_v1"
    assert [item["symbol"] for item in payload["items"]] == [
        "000063.SZ",
        "300308.SZ",
    ]
    first = payload["items"][0]
    assert first["priority_label"] == "优先复核"
    assert first["priority_score"] == 100
    assert {item["key"] for item in first["components"]} >= {
        "evidence_change",
        "price_move",
        "drawdown",
        "volatility",
        "fundamentals",
        "cashflow",
    }
    assert all(component["key"] != "event" for component in first["components"])
    assert "不是买卖评级" in payload["boundary"]
    assert all(
        component["key"] != "event"
        for component in payload["items"][1]["components"]
    )
    assert database.latest_research_priority_snapshot(user["id"]) is not None
    assert any(
        item["title"] == "我的最新研究优先级"
        for item in database.list_knowledge_documents(user["id"])
    )


def test_chat_routes_natural_language_to_research_priority(client, app):
    user = _create_user(client, "Priority Chat User")
    app.state.database.upsert_watchlist(
        user["id"], "000063.SZ", "中兴通讯", "A股", "验证利润与现金流"
    )
    app.state.database.create_research_report(
        symbol="000063.SZ",
        name="中兴通讯",
        title="中兴通讯研究快照",
        summary="研究摘要",
        body="研究正文",
        status="preview",
        fingerprint="priority-chat",
        evidence=_evidence("000063.SZ", stressed=True),
        run_id=None,
        market_timestamp="2026-07-20T15:00:00+08:00",
    )

    response = client.post(
        "/me/chat",
        json={"message": "今天我的自选股先看什么？", "execute_agent": False},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"] == "research_priority"
    assert "研究复核顺序" in payload["answer"]
    assert "不是投资排名" in payload["answer"]
