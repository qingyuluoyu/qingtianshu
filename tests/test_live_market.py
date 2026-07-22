from __future__ import annotations

from datetime import datetime, timezone

from app.catalog import LIVE_MARKET_CATALOG
from app.services import live_market
from app.services.live_market import (
    freshness_label,
    market_quote_semantics,
    market_session,
    market_session_details,
)


def test_china_market_session_schedule():
    china = next(item for item in LIVE_MARKET_CATALOG if item["key"] == "china")
    open_time = datetime(2026, 7, 21, 2, 0, tzinfo=timezone.utc)  # 10:00 Shanghai
    is_open, label, local = market_session(china, open_time)
    assert is_open is True
    assert label == "交易中"
    assert local.hour == 10

    lunch = datetime(2026, 7, 21, 4, 0, tzinfo=timezone.utc)  # 12:00 Shanghai
    lunch_details = market_session_details(china, lunch)
    assert lunch_details["is_open"] is False
    assert lunch_details["session_label"] == "午间休市"
    assert lunch_details["calendar_status"] == "verified"
    assert lunch_details["break_start"] == "2026-07-21T11:30:00+08:00"


def test_a_share_quote_semantics_distinguish_intraday_and_post_close():
    intraday = market_quote_semantics(
        "china",
        "2026-07-22T13:20:03+08:00",
        now_utc=datetime(2026, 7, 22, 5, 20, tzinfo=timezone.utc),
    )
    post_close = market_quote_semantics(
        "china",
        "2026-07-22T15:06:30+08:00",
        now_utc=datetime(2026, 7, 22, 7, 10, tzinfo=timezone.utc),
    )

    assert intraday["quote_basis"] == "intraday_snapshot"
    assert intraday["quote_label"] == "盘中最新报价"
    assert intraday["is_intraday"] is True
    assert post_close["quote_basis"] == "post_close_snapshot"
    assert post_close["quote_label"] == "收盘后最新报价"
    assert post_close["is_intraday"] is False


def test_exchange_calendars_cover_holidays_and_us_early_close():
    markets = {item["key"]: item for item in LIVE_MARKET_CATALOG}
    china_holiday = market_session_details(
        markets["china"], datetime(2026, 1, 1, 2, 0, tzinfo=timezone.utc)
    )
    assert china_holiday["session_status"] == "holiday"
    assert china_holiday["session_label"] == "休市"

    us_pre_open = market_session_details(
        markets["us"], datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)
    )
    assert us_pre_open["session_status"] == "pre_open"
    assert us_pre_open["session_label"] == "未开盘"

    early_open = market_session_details(
        markets["us"], datetime(2026, 11, 27, 15, 0, tzinfo=timezone.utc)
    )
    early_closed = market_session_details(
        markets["us"], datetime(2026, 11, 27, 19, 0, tzinfo=timezone.utc)
    )
    assert early_open["is_open"] is True
    assert early_open["session_close"] == "2026-11-27T13:00:00-05:00"
    assert early_closed["session_status"] == "closed"


def test_london_gold_daily_maintenance_is_not_reported_as_open():
    gold = next(
        item for item in LIVE_MARKET_CATALOG if item["key"] == "london_gold"
    )
    before_break = market_session_details(
        gold, datetime(2026, 7, 21, 20, 30, tzinfo=timezone.utc)
    )
    during_break = market_session_details(
        gold, datetime(2026, 7, 21, 21, 30, tzinfo=timezone.utc)
    )

    assert before_break["is_open"] is True
    assert during_break["is_open"] is False
    assert during_break["session_status"] == "break"
    assert during_break["session_label"] == "每日维护"
    assert during_break["session_method"] == "otc_daily_break_v1"


def test_calendar_failure_degrades_to_weekday_schedule(monkeypatch):
    china = next(item for item in LIVE_MARKET_CATALOG if item["key"] == "china")
    monkeypatch.setattr(live_market, "exchange_calendars", None)
    details = market_session_details(
        china, datetime(2026, 7, 21, 2, 0, tzinfo=timezone.utc)
    )
    assert details["is_open"] is True
    assert details["calendar_status"] == "fallback"
    assert details["session_method"] == "weekday_schedule_fallback_v1"


def test_freshness_labels_do_not_call_closed_markets_stale():
    assert freshness_label(False, 50_000, False) == "closed_snapshot"
    assert freshness_label(True, 60, False) == "near_realtime"
    assert freshness_label(True, 600, False) == "delayed"
    assert freshness_label(True, 2_000, False) == "stale"
    assert freshness_label(True, 10, True) == "stale_cache"
