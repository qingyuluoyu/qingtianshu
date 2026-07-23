from __future__ import annotations

from fastapi.testclient import TestClient


def _create_user(client: TestClient, name: str) -> dict:
    response = client.post("/users", json={"name": name})
    assert response.status_code == 201
    return response.json()


def _seed_report(
    app,
    *,
    symbol: str,
    name: str,
    return_1d_pct: float,
    daily_timestamp: str,
    current_quote_timestamp: str,
    current_quote_pct_change: float,
    fingerprint: str,
) -> dict:
    return app.state.database.create_research_report(
        symbol=symbol,
        name=name,
        title=f"{name}研究快照",
        summary="确定性测试快照",
        body="研究正文",
        status="completed",
        fingerprint=fingerprint,
        evidence={
            "display_name": name,
            "metrics": {
                "latest_close": 37.5,
                "return_1d_pct": return_1d_pct,
                "volume_ratio_5_20": 1.3029,
            },
            "provenance": {
                "market_timestamp": daily_timestamp,
                "source": "Verified daily source",
                "source_url": "https://example.invalid/daily",
            },
            "current_quote": {
                "market_timestamp": current_quote_timestamp,
                "pct_change": current_quote_pct_change,
                "source": "Realtime quote source",
            },
        },
        run_id=None,
        market_timestamp=daily_timestamp,
    )


def test_price_anomaly_uses_complete_daily_bar_and_is_idempotent(app):
    client = TestClient(app)
    user = _create_user(client, "Price Change Owner")
    app.state.database.upsert_watchlist(
        user["id"], "000063.SZ", "中兴通讯", "A股", "核验完整日线异常"
    )
    _seed_report(
        app,
        symbol="000063.SZ",
        name="中兴通讯",
        return_1d_pct=7.5115,
        daily_timestamp="2026-07-22T01:30:00+00:00",
        current_quote_timestamp="2026-07-23T12:05:30+08:00",
        current_quote_pct_change=-3.97,
        fingerprint="price-anomaly-zte",
    )

    first = app.state.change_events.get_user_packet(user["id"])
    second = app.state.change_events.get_user_packet(user["id"])

    price_events = [
        item for item in first["items"] if item["event_type"] == "daily_price_anomaly"
    ]
    assert len(price_events) == 1
    event = price_events[0]
    assert event["occurred_at"] == "2026-07-22T01:30:00+00:00"
    assert "2026-07-22" in event["fact_summary"]
    assert "7.51%" in event["fact_summary"]
    assert "5日与20日平均成交量之比为1.30" in event["fact_summary"]
    assert event["payload"]["current_quote_timestamp"] == ("2026-07-23T12:05:30+08:00")
    assert event["payload"]["current_quote_pct_change"] == -3.97
    assert event["payload"]["current_quote_excluded"] is True
    assert (
        len(
            [
                item
                for item in second["items"]
                if item["event_type"] == "daily_price_anomaly"
            ]
        )
        == 1
    )
    persisted = app.state.database.list_change_events(symbol="000063.SZ")
    assert sum(item["event_type"] == "daily_price_anomaly" for item in persisted) == 1


def test_price_event_reuses_same_trading_day_when_report_value_is_corrected(app):
    client = TestClient(app)
    user = _create_user(client, "Corrected Price Change Owner")
    app.state.database.upsert_watchlist(
        user["id"], "000063.SZ", "中兴通讯", "A股", "核验同日校正去重"
    )
    _seed_report(
        app,
        symbol="000063.SZ",
        name="中兴通讯",
        return_1d_pct=7.5115,
        daily_timestamp="2026-07-22T01:30:00+00:00",
        current_quote_timestamp="2026-07-23T12:05:30+08:00",
        current_quote_pct_change=-3.97,
        fingerprint="price-anomaly-zte-before-correction",
    )
    before = next(
        item
        for item in app.state.change_events.get_user_packet(user["id"])["items"]
        if item["event_type"] == "daily_price_anomaly"
    )

    _seed_report(
        app,
        symbol="000063.SZ",
        name="中兴通讯",
        return_1d_pct=8.2,
        daily_timestamp="2026-07-22T01:30:00+00:00",
        current_quote_timestamp="2026-07-23T12:10:30+08:00",
        current_quote_pct_change=-3.8,
        fingerprint="price-anomaly-zte-after-correction",
    )
    after_items = [
        item
        for item in app.state.change_events.get_user_packet(user["id"])["items"]
        if item["event_type"] == "daily_price_anomaly"
    ]

    assert len(after_items) == 1
    assert after_items[0]["event_id"] == before["event_id"]
    assert "8.20%" in after_items[0]["title"]
    assert after_items[0]["payload"]["return_1d_pct"] == 8.2
    persisted = app.state.database.list_change_events(symbol="000063.SZ")
    assert sum(item["event_type"] == "daily_price_anomaly" for item in persisted) == 1


def test_user_packet_hides_legacy_semantic_duplicates_and_keeps_user_state(app):
    client = TestClient(app)
    user = _create_user(client, "Legacy Duplicate Change Owner")
    app.state.database.upsert_watchlist(
        user["id"], "000063.SZ", "中兴通讯", "A股", "核验历史变化事件去重"
    )
    common = {
        "symbol": "000063.SZ",
        "event_type": "daily_price_anomaly",
        "occurred_at": "2026-07-22T01:30:00+00:00",
        "source_name": "Verified daily source",
        "source_url": "https://example.invalid/daily",
        "data_status": "confirmed_daily_bar",
        "rule_version": app.state.change_events.PRICE_RULE_VERSION,
        "payload": {
            "name": "中兴通讯",
            "daily_date": "2026-07-22",
            "daily_timestamp": "2026-07-22T01:30:00+00:00",
            "return_1d_pct": 7.5,
        },
    }
    older = app.state.database.upsert_change_event(
        **common,
        title="中兴通讯上一完整交易日上涨 7.50%",
        fact_summary="旧规则生成的同日价格变化。",
        detected_at="2026-07-23T01:00:00+00:00",
        dedupe_hash="legacy-semantic-change-older",
    )
    app.state.database.upsert_change_event(
        **common,
        title="中兴通讯上一完整交易日上涨 7.51%",
        fact_summary="新规则生成的同日价格变化。",
        detected_at="2026-07-23T02:00:00+00:00",
        dedupe_hash="legacy-semantic-change-newer",
    )
    app.state.database.ensure_user_change_links(user["id"], "000063.SZ")

    links = app.state.database.list_user_change_links(user["id"], symbol="000063.SZ")
    older_link = next(item for item in links if item["event_id"] == older["id"])
    app.state.change_events.mark_read(user["id"], older_link["link_id"])
    app.state.change_events.set_relevance(
        user["id"], older_link["link_id"], "relevant"
    )

    packet = app.state.change_events.get_user_packet(user["id"], refresh=False)

    assert len(packet["items"]) == 1
    assert packet["items"][0]["event_id"] == older["id"]
    assert packet["items"][0]["relevance_status"] == "relevant"
    assert packet["counts"] == {
        "total": 1,
        "pending": 0,
        "pending_unread": 0,
        "relevant": 1,
        "irrelevant": 0,
    }
    assert packet["pending_unread_items"] == []


def test_whitelist_accepts_official_financial_disclosure_not_media_or_unverified_type(
    app,
):
    client = TestClient(app)
    user = _create_user(client, "Disclosure Change Owner")
    app.state.database.upsert_watchlist(
        user["id"], "300308.SZ", "中际旭创", "A股", "核验正式披露"
    )
    app.state.database.save_event_timeline_snapshot(
        {
            "symbol": "300308.SZ",
            "name": "中际旭创",
            "as_of_date": "2026-07-22",
            "method": "test_event_timeline",
            "events": [
                {
                    "event_type": "financial_reporting",
                    "title": "2026年半年度报告",
                    "published_at": "2026-07-22T18:00:00+08:00",
                    "event_date": "2026-07-22",
                    "category": "announcement",
                    "evidence_level": "official_disclosure",
                    "evidence_label": "公司公告",
                    "event_status": "confirmed_disclosure",
                    "source": "交易所公告",
                    "url": "https://example.invalid/official-report",
                },
                {
                    "event_type": "financial_reporting",
                    "title": "媒体解读公司半年业绩",
                    "published_at": "2026-07-22T19:00:00+08:00",
                    "event_date": "2026-07-22",
                    "category": "news",
                    "evidence_level": "media_report",
                    "evidence_label": "媒体报道",
                    "event_status": "reported_clue",
                    "source": "测试媒体",
                    "url": "https://example.invalid/media-report",
                },
                {
                    "event_type": "shareholder_change",
                    "title": "限售股份解除限售提示性公告",
                    "published_at": "2026-07-22T20:00:00+08:00",
                    "event_date": "2026-07-22",
                    "category": "announcement",
                    "evidence_level": "official_disclosure",
                    "evidence_label": "公司公告",
                    "event_status": "confirmed_disclosure",
                    "source": "交易所公告",
                    "url": "https://example.invalid/unlock",
                },
            ],
        },
        "official-financial-whitelist",
    )

    packet = app.state.change_events.get_user_packet(user["id"])

    assert [item["event_type"] for item in packet["items"]] == [
        "official_financial_disclosure"
    ]
    event = packet["items"][0]
    assert event["source_name"] == "交易所公告"
    assert event["source_url"] == "https://example.invalid/official-report"
    assert "只确认官方披露已经发布" in event["boundary"]
    assert packet["coverage"]["event_whitelist_complete"] is False
    assert "restricted_share_unlock" in packet["coverage"]["uncovered_event_types"]


def test_below_threshold_does_not_create_price_event(app):
    client = TestClient(app)
    user = _create_user(client, "Quiet Price Owner")
    app.state.database.upsert_watchlist(
        user["id"], "NVDA", "英伟达", "美股", "低于阈值不提醒"
    )
    _seed_report(
        app,
        symbol="NVDA",
        name="英伟达",
        return_1d_pct=2.3011,
        daily_timestamp="2026-07-22T13:30:00+00:00",
        current_quote_timestamp="2026-07-23T09:30:00-04:00",
        current_quote_pct_change=-0.2,
        fingerprint="quiet-nvda",
    )

    packet = app.state.change_events.get_user_packet(user["id"])

    assert all(item["event_type"] != "daily_price_anomaly" for item in packet["items"])


def test_change_api_is_user_isolated_and_feedback_states_remain_separate(app):
    owner = TestClient(app)
    owner_user = _create_user(owner, "Change API Owner")
    app.state.database.upsert_watchlist(
        owner_user["id"], "000063.SZ", "中兴通讯", "A股", "验证事件反馈闭环"
    )
    _seed_report(
        app,
        symbol="000063.SZ",
        name="中兴通讯",
        return_1d_pct=-6.2,
        daily_timestamp="2026-07-22T01:30:00+00:00",
        current_quote_timestamp="2026-07-23T10:30:00+08:00",
        current_quote_pct_change=1.1,
        fingerprint="change-api-owner",
    )

    listed = owner.get("/v1/changes")
    assert listed.status_code == 200
    event = next(
        item
        for item in listed.json()["items"]
        if item["event_type"] == "daily_price_anomaly"
    )
    link_id = event["link_id"]

    other = TestClient(app)
    other_user = _create_user(other, "Change API Other")
    app.state.database.upsert_watchlist(
        other_user["id"], "000063.SZ", "中兴通讯", "A股", "另一个用户空间"
    )
    other.get("/v1/changes")
    assert other.get(f"/v1/changes/{link_id}").status_code == 404
    assert other.post(f"/v1/user-changes/{link_id}/read").status_code == 404
    assert (
        other.post(
            f"/v1/user-changes/{link_id}/relevance",
            json={"relevance_status": "irrelevant"},
        ).status_code
        == 404
    )

    relevance = owner.post(
        f"/v1/user-changes/{link_id}/relevance",
        json={"relevance_status": "irrelevant"},
    )
    assert relevance.status_code == 200
    assert relevance.json()["relevance_status"] == "irrelevant"
    assert relevance.json()["handled_at"] is not None
    assert relevance.json()["read_at"] is None

    history = owner.get("/v1/changes").json()
    assert any(
        item["link_id"] == link_id and item["relevance_status"] == "irrelevant"
        for item in history["items"]
    )
    overview = owner.get("/v1/today/overview").json()
    assert all(
        item.get("source_ref_id") != link_id
        for item in overview["priority_items"]["items"]
    )
    workspace = owner.get("/v1/stocks/000063/workspace").json()
    assert any(
        item.get("link_id") == link_id for item in workspace["important_changes"]
    )

    read = owner.post(f"/v1/user-changes/{link_id}/read")
    assert read.status_code == 200
    assert read.json()["read_at"] is not None
    assert read.json()["relevance_status"] == "irrelevant"
