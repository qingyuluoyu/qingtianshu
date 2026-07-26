from __future__ import annotations

from datetime import datetime, timedelta, timezone
from app.catalog import LIVE_MARKET_CATALOG
from app.db import Database
from app.services.data_health import DataHealthService
from app.services.earnings_quality import EarningsQualityService


def test_data_health_audit_persists_detailed_snapshot(settings):
    database = Database(settings.database_path, settings.workspace_root)
    database.initialize()
    service = DataHealthService(database, settings)

    snapshot = service.audit(
        now_utc=datetime(2026, 7, 21, 2, 0, tzinfo=timezone.utc)
    )

    assert snapshot["status"] == "degraded"
    assert snapshot["summary"]["critical"] > 0
    assert snapshot["method"] == "deterministic_data_health_audit_v1"
    assert database.latest_data_health_snapshot()["id"] == snapshot["id"]
    public = service.public_summary(snapshot)
    assert public["user_label"] == "部分数据同步中"
    assert "checks" not in public


def test_market_health_uses_session_state_and_fresh_bars(settings):
    database = Database(settings.database_path, settings.workspace_root)
    database.initialize()
    service = DataHealthService(database, settings)
    now = datetime(2026, 7, 21, 2, 0, tzinfo=timezone.utc)
    timestamp = (now - timedelta(seconds=60)).isoformat(timespec="seconds")
    for market in LIVE_MARKET_CATALOG:
        interval = "5m" if market.get("provider") == "sina_global_futures" else "1m"
        database.upsert_market_bars(
            market["symbol"],
            interval,
            [
                {
                    "timestamp": timestamp,
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 100.5,
                    "volume": 100,
                }
            ],
            "test",
            timestamp,
        )

    checks = service._market_checks(now)

    assert len(checks) == 5
    assert all(item["status"] in {"healthy", "attention"} for item in checks)
    china = next(item for item in checks if item["key"] == "market:china")
    assert china["session_status"] == "open"
    if china["calendar_status"] == "fallback":
        assert china["status"] == "attention"


def test_market_breadth_health_requires_complete_fresh_snapshot(settings):
    database = Database(settings.database_path, settings.workspace_root)
    database.initialize()
    now = datetime(2026, 7, 21, 7, 10, tzinfo=timezone.utc)
    database.put_cache(
        "sina:a-share-market-breadth:hs_a",
        {
            "source": "test",
            "fetched_at": now.isoformat(timespec="seconds"),
            "status": "available",
            "scope": "all_a_shares_including_beijing",
            "coverage": {
                "expected": 5528,
                "returned": 5528,
                "valid_change": 5528,
                "coverage_ratio": 1.0,
            },
            "breadth": {
                "total": 5528,
                "advancers": 3107,
                "decliners": 2300,
                "unchanged": 121,
            },
            "turnover": {
                "status": "available",
                "total_amount_cny": 1_234_000_000_000,
                "coverage": {"coverage_ratio": 1.0},
            },
            "distribution": {
                "status": "available",
                "median_pct_change": 0.72,
                "coverage": {"coverage_ratio": 1.0},
            },
        },
        ttl_seconds=300,
    )

    check = DataHealthService(database, settings)._market_breadth_checks(now)[0]

    assert check["status"] == "healthy"
    assert check["total"] == 5528
    assert check["advancers"] == 3107
    assert check["total_amount_cny"] == 1_234_000_000_000
    assert check["median_pct_change"] == 0.72


def test_market_breadth_health_rejects_all_zero_placeholder(settings):
    database = Database(settings.database_path, settings.workspace_root)
    database.initialize()
    now = datetime(2026, 7, 22, 1, 10, tzinfo=timezone.utc)
    database.put_cache(
        "sina:a-share-market-breadth:hs_a",
        {
            "source": "test",
            "fetched_at": now.isoformat(timespec="seconds"),
            "status": "available",
            "scope": "all_a_shares_including_beijing",
            "coverage": {
                "expected": 5529,
                "returned": 5529,
                "valid_change": 5529,
                "coverage_ratio": 1.0,
            },
            "breadth": {
                "total": 5529,
                "advancers": 0,
                "decliners": 0,
                "unchanged": 5529,
            },
            "turnover": {
                "status": "available",
                "total_amount_cny": 0,
                "coverage": {"coverage_ratio": 1.0},
            },
            "distribution": {
                "status": "available",
                "median_pct_change": 0.0,
                "coverage": {"coverage_ratio": 1.0},
            },
        },
        ttl_seconds=300,
    )

    check = DataHealthService(database, settings)._market_breadth_checks(now)[0]

    assert check["status"] == "critical"
    assert check["label"] == "A股全市场广度或成交分布覆盖不完整"


def test_open_market_delay_is_critical(settings):
    database = Database(settings.database_path, settings.workspace_root)
    database.initialize()
    service = DataHealthService(database, settings)
    now = datetime(2026, 7, 21, 2, 0, tzinfo=timezone.utc)
    stale_time = (now - timedelta(minutes=20)).isoformat(timespec="seconds")
    china = next(item for item in LIVE_MARKET_CATALOG if item["key"] == "china")
    database.upsert_market_bars(
        china["symbol"],
        "1m",
        [{"timestamp": stale_time, "close": 100.0}],
        "test",
        stale_time,
    )

    check = next(
        item for item in service._market_checks(now) if item["key"] == "market:china"
    )

    assert check["status"] == "critical"
    assert check["age_seconds"] == 1200


def test_earnings_quality_health_matches_latest_financial_period(settings):
    database = Database(settings.database_path, settings.workspace_root)
    database.initialize()
    period = {
        "symbol": "000063.SZ",
        "name": "中兴通讯",
        "report_date": "2026-03-31",
        "report_type": "一季报",
        "report_date_name": "2026一季报",
        "currency": "CNY",
        "revenue_yoy_pct": 6.13,
        "parent_net_profit": 1_310_444_000.0,
        "net_profit_yoy_pct": -46.58,
        "gross_margin_pct": 28.28,
        "net_margin_pct": 3.77,
        "debt_asset_ratio_pct": 65.87,
        "operating_cashflow": -1_978_648_000.0,
        "period_basis": "year_to_date_cumulative",
        "source": "test",
        "source_url": "https://example.invalid",
        "warnings": [],
    }
    database.upsert_financial_periods([period])
    EarningsQualityService(database).get_packet("000063.SZ")

    check = next(
        item
        for item in DataHealthService(database, settings)._earnings_quality_checks()
        if item["key"] == "earnings-quality:000063.SZ"
    )

    assert check["status"] == "healthy"
    assert check["report_date"] == "2026-03-31"


def test_background_refresh_builds_earnings_quality_for_research_symbols(app):
    app.state.fundamentals.refresh_symbols(["000063.SZ", "300308.SZ"])
    app.state.us_fundamentals.refresh_symbols(["NVDA"])

    result = app.state.background._refresh_earnings_quality()

    assert result["requested"] == 3
    assert result["completed"] == 3
    checks = app.state.data_health._earnings_quality_checks()
    assert len(checks) == 3
    assert all(item["status"] == "healthy" for item in checks)


def test_background_refresh_builds_financial_drivers_and_health_checks(app):
    app.state.fundamentals.refresh_symbols(["000063.SZ", "300308.SZ"])
    app.state.us_fundamentals.refresh_symbols(["NVDA"])

    result = app.state.background._refresh_financial_drivers()

    assert result["requested"] == 3
    assert result["completed"] == 3
    checks = app.state.data_health._financial_driver_checks()
    assert len(checks) == 3
    assert all(item["status"] == "healthy" for item in checks)
    assert all(
        item["statement_types"] == ["balance", "cashflow", "income"]
        for item in checks
    )


def test_background_refresh_builds_a_share_filing_evidence_and_health_checks(app):
    app.state.fundamentals.refresh_symbols(["000063.SZ", "300308.SZ"])

    result = app.state.background._refresh_a_share_filings()

    assert result["requested"] == 3
    assert result["completed"] == 3
    assert result["documents"] == 3
    checks = app.state.data_health._filing_checks()
    assert len(checks) == 2
    assert all(item["status"] == "healthy" for item in checks)
    assert all(item["explicit_explanations"] >= 1 for item in checks)


def test_background_refresh_builds_business_structure_and_health_checks(app):
    result = app.state.background._refresh_business_structure()

    assert result["requested"] == 3
    assert result["completed"] == 3
    assert result["rows"] == 66
    checks = app.state.data_health._business_structure_checks()
    assert len(checks) == 2
    assert all(item["status"] == "healthy" for item in checks)
    assert all(item["dimensions"] == 3 for item in checks)


def test_background_refresh_builds_shareholder_structure_and_health_checks(app):
    result = app.state.background._refresh_shareholders()

    assert result["requested"] == 3
    assert result["completed"] == 3
    checks = app.state.data_health._shareholder_structure_checks()
    assert len(checks) == 2
    assert all(item["status"] == "healthy" for item in checks)
    assert all(item["holder_history_points"] == 3 for item in checks)
    assert all(item["top_holders"] == 3 for item in checks)


def test_background_refresh_builds_analyst_expectations_and_health_checks(app):
    result = app.state.background._refresh_analyst_expectations()

    assert result["requested"] == 3
    assert result["completed"] == 3
    checks = app.state.data_health._analyst_expectation_checks()
    assert len(checks) == 2
    assert all(item["status"] == "healthy" for item in checks)
    assert all(item["rating_organizations"] == 11 for item in checks)
    assert all(item["estimate_years"] == 2 for item in checks)
    assert all(item["reports"] == 1 for item in checks)


def test_background_information_refresh_builds_event_timelines_and_health(app):
    result = app.state.background._refresh_a_share_information()

    assert result["event_timelines"]["requested"] == result["requested"]
    assert result["event_timelines"]["completed"] == result["requested"]
    checks = app.state.data_health._event_timeline_checks()
    assert len(checks) == 2
    assert all(item["status"] == "healthy" for item in checks)
    assert all(item["official_events"] >= 1 for item in checks)
