from __future__ import annotations

from datetime import datetime, timedelta, timezone


def _create_user(client, name: str) -> dict:
    response = client.post("/users", json={"name": name})
    assert response.status_code == 201
    return response.json()


def _seed_report_and_bars(app, user_id: str, *, future_sessions: int) -> dict:
    database = app.state.database
    symbol = "000063.SZ"
    database.upsert_watchlist(
        user_id,
        symbol,
        "中兴通讯",
        "A股",
        "验证利润、现金流与价格条件是否一致",
    )
    anchor = datetime(2026, 7, 1, 1, 30, tzinfo=timezone.utc)
    points = [
        {
            "timestamp": anchor.isoformat(timespec="seconds"),
            "open": 99.5,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "adjusted_close": 100.0,
            "volume": 1000,
        }
    ]
    for index in range(1, future_sessions + 1):
        close = 100.0 + index
        points.append(
            {
                "timestamp": (anchor + timedelta(days=index)).isoformat(
                    timespec="seconds"
                ),
                "open": close - 0.5,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "adjusted_close": close,
                "volume": 1000 + index,
            }
        )
    database.upsert_market_bars(
        symbol,
        "1d",
        points,
        "deterministic test bars",
        "2026-07-20T00:00:00+00:00",
    )
    evidence = {
        "type": "stock_research",
        "symbol": symbol,
        "display_name": "中兴通讯",
        "metrics": {"latest_close": 100.0},
        "price_levels": {
            "recent_20d_high": 110.0,
            "recent_20d_low": 90.0,
            "ma20": 98.0,
            "ma60": 96.0,
        },
        "conditional_outlook": {
            "label": "震荡观察",
            "confidence": "low",
            "scenarios": [],
        },
        "analysis_board": {
            "tracking_plan": [
                {"horizon_sessions": 3, "checks": ["复核价格区间"]},
                {"horizon_sessions": 5, "checks": ["复核反方证据"]},
                {"horizon_sessions": 10, "checks": ["重新综合研究"]},
            ]
        },
    }
    return database.create_research_report(
        symbol=symbol,
        name="中兴通讯",
        title="中兴通讯研究快照",
        summary="原判断为震荡观察。",
        body="测试研究正文",
        status="preview",
        fingerprint=f"research-outcome-{future_sessions}",
        evidence=evidence,
        run_id=None,
        market_timestamp=anchor.isoformat(timespec="seconds"),
    )


def test_research_outcome_backfill_is_matured_idempotent_and_searchable(client, app):
    user = _create_user(client, "Outcome User")
    _seed_report_and_bars(app, user["id"], future_sessions=12)

    first = app.state.research_outcomes.backfill("000063.SZ")
    assert first["reports_scanned"] == 1
    assert first["updated"] == 3
    assert first["available"] == 3

    second = app.state.research_outcomes.backfill("000063.SZ")
    assert second["updated"] == 0
    assert second["unchanged"] == 3

    rows = app.state.database.list_research_outcomes(["000063.SZ"])
    t3 = next(item for item in rows if item["horizon_sessions"] == 3)
    assert t3["result_status"] == "available"
    assert t3["observed_sessions"] == 3
    assert t3["close_return_pct"] == 3.0
    assert t3["maximum_adverse_excursion_pct"] == 0.0
    assert t3["scenario_result"] == "range_held"
    assert "原区间观察假设" in t3["review_conclusion"]

    packet = client.get(
        "/me/research-outcomes", params={"symbol": "000063", "limit": 50}
    )
    assert packet.status_code == 200
    payload = packet.json()
    assert payload["type"] == "research_outcome"
    assert payload["coverage"]["available_outcomes"] == 3
    assert payload["items"][0]["name"] == "中兴通讯"
    assert len(payload["items"][0]["latest_available"]) == 3
    assert payload["items"][0]["current_research_context"]["metrics"]["latest_close"] == 100.0
    assert "不评价买卖收益" in payload["boundary"]

    chat = client.post(
        "/me/chat",
        json={
            "message": "中兴通讯之前的研究后来怎么样？",
            "execute_agent": False,
        },
    )
    assert chat.status_code == 200
    chat_payload = chat.json()
    assert chat_payload["intent"] == "research_outcome"
    assert "历史研究复盘" in chat_payload["answer"]
    assert "T+3" in chat_payload["answer"]
    assert "荐股" in chat_payload["answer"]

    documents = app.state.database.list_knowledge_documents(
        user["id"], include_content=True
    )
    archive = next(
        item
        for item in documents
        if item["source_key"] == "research-outcome:000063.SZ"
    )
    assert archive["scope"] == "common"
    assert "中兴通讯研究结果复盘" in archive["title"]
    assert "T+3" in archive["content"]


def test_research_outcome_pending_sample_reports_progress_without_claiming_maturity(
    client, app
):
    user = _create_user(client, "Pending Outcome User")
    _seed_report_and_bars(app, user["id"], future_sessions=2)

    result = app.state.research_outcomes.backfill("000063.SZ")
    assert result["available"] == 0
    assert result["pending"] == 3

    t3 = app.state.database.research_outcome_for_anchor(
        "000063.SZ", "2026-07-01T01:30:00+00:00", 3
    )
    assert t3 is not None
    assert t3["result_status"] == "pending"
    assert t3["observed_sessions"] == 2
    assert t3["close_return_pct"] is None
    assert t3["payload"]["partial_return_pct"] == 2.0
    assert "还差1个交易日" in t3["review_conclusion"]

    chat = client.post(
        "/me/chat",
        json={"message": "之前的研究后来怎么样？", "execute_agent": False},
    )
    assert chat.status_code == 200
    assert chat.json()["intent"] == "research_outcome"
    assert "已观察 2 个交易日" in chat.json()["answer"]
    assert "已到期" not in chat.json()["answer"]
