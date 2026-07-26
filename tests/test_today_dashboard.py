from __future__ import annotations

import pandas as pd

from app.db import Database
from app.services.today_dashboard import TodayDashboardService


class FakeDatabase:
    def list_market_breadth_snapshots(self, limit: int = 21):
        return [
            {
                "market_date": "2026-07-21",
                "turnover": {"total_amount_100m_cny": 10000},
            },
            {
                "market_date": "2026-07-22",
                "turnover": {"total_amount_100m_cny": 12000},
            },
        ][:limit]


class FakeAnalysis:
    def market_breadth(self):
        return {
            "status": "available",
            "market_date": "2026-07-22",
            "market_timestamp": "2026-07-22T07:00:00+00:00",
            "fetched_at": "2026-07-22T07:00:05+00:00",
            "source": "Fake breadth",
            "breadth": {
                "total": 100,
                "advancers": 60,
                "decliners": 35,
                "unchanged": 5,
                "advance_ratio": 0.6,
                "decline_ratio": 0.35,
                "unchanged_ratio": 0.05,
            },
            "turnover": {"total_amount_100m_cny": 12000},
            "distribution": {
                "bins": {
                    "strong_advancers_ge_3": 10,
                    "mild_advancers_gt_0_lt_3": 50,
                    "unchanged": 5,
                    "mild_decliners_lt_0_gt_neg3": 30,
                    "strong_decliners_le_neg3": 5,
                }
            },
        }

    def hot_sectors(self, limit: int = 20):
        rows = [
            {
                "code": f"BK{index:04d}",
                "name": f"板块{index}",
                "latest": 100 + index,
                "pct_change": 5 - index,
                "turnover": 1_000_000_000 + index * 100_000_000,
                "main_net_inflow": (5 - index) * 100_000_000,
                "advancers": 20 - index,
                "decliners": index,
            }
            for index in range(8)
        ]
        return {
            "source": "Fake sectors",
            "market_timestamp": "2026-07-22T07:00:00+00:00",
            "sectors": rows[:limit],
        }


class FakeIndexProvider:
    def fetch_intraday(self, symbol: str):
        return {
            "symbol": symbol,
            "latest_price": 3888.8,
            "previous_close": 3860.0,
            "pct_change": 0.7461,
            "market_timestamp": "2026-07-22T07:00:00+00:00",
            "fetched_at": "2026-07-22T07:00:05+00:00",
            "source": "Fake index minute",
            "warnings": [],
            "points": [
                {"close": 3860.0, "amount": 2_000_000_000},
                {"close": 3888.8, "amount": 3_000_000_000},
            ],
        }


class FakeTushare:
    def query(self, api_name: str, **params):
        if api_name == "limit_list_d":
            if params.get("limit_type") == "U":
                return pd.DataFrame(
                    {"ts_code": ["600000.SH", "300001.SZ", "000001.SZ"]}
                )
            return pd.DataFrame({"ts_code": ["688001.SH"]})
        return pd.DataFrame()


def make_service() -> TodayDashboardService:
    return TodayDashboardService(
        FakeDatabase(),
        FakeAnalysis(),
        intraday_index_provider=FakeIndexProvider(),
        tushare_client=FakeTushare(),
    )


def test_index_quote_keeps_secret_server_side_and_maps_board_limits():
    result = make_service().index_quote("000001.SH")

    assert result["value"] == 3888.8
    assert result["turnover"] == 50.0
    assert result["limitUp"] == 1
    assert result["limitDown"] == 0
    assert result["trend"] == [3860.0, 3888.8]
    assert "token" not in str(result).lower()


def test_market_overview_and_distribution_use_audited_breadth():
    service = make_service()

    overview = service.market_overview(
        limit_snapshot={
            "market_date": "2026-07-22",
            "limit_up": 3,
            "limit_down": 1,
        }
    )
    distribution = service.rise_fall_distribution()

    assert overview["total"] == 100
    assert overview["rising"] == 60
    assert overview["flat"] == 5
    assert overview["falling"] == 35
    assert (
        overview["rising"]
        + overview["flat"]
        + overview["falling"]
        == overview["total"]
    )
    assert overview["limitUp"] == 3
    assert overview["limitDown"] == 1
    assert distribution["rising"] == 60
    assert [item["count"] for item in distribution["bins"]] == [10, 50, 5, 30, 5]


def test_market_overview_does_not_merge_cross_date_limit_counts():
    service = make_service()

    overview = service.market_overview(
        limit_snapshot={
            "market_date": "2026-07-21",
            "limit_up": 88,
            "limit_down": 12,
        }
    )

    assert overview["marketDate"] == "2026-07-22"
    assert overview["limitDataAsOf"] == "2026-07-21"
    assert overview["limitDataStatus"] == "date_mismatch"
    assert overview["limitUp"] is None
    assert overview["limitDown"] is None


def test_dashboard_market_date_uses_latest_trading_day_not_weekend_generation_time():
    service = make_service()

    payload = service._with_date_alignment(
        {
            "generatedAt": "2026-07-25T10:00:00+00:00",
            "indices": [
                {
                    "code": "000001.SH",
                    "marketTimestamp": "2026-07-24T07:00:00+00:00",
                }
            ],
            "marketOverview": {
                "marketDate": "2026-07-24",
                "limitDataAsOf": "2026-07-24",
            },
            "industryRotation": [{"marketDate": "2026-07-24"}],
            "tradingActivity": {
                "points": [{"marketDate": "2026-07-24", "value": 19_442.25}]
            },
        }
    )

    assert payload["asOfMarketDate"] == "2026-07-24"
    assert payload["dateAlignment"]["status"] == "aligned"
    assert payload["dateAlignment"]["mismatchedModules"] == []
    assert "2026-07-25" not in payload["dateAlignment"]["moduleMarketDates"].values()


def test_dashboard_date_alignment_marks_cross_date_modules_without_relabeling():
    service = make_service()

    payload = service._with_date_alignment(
        {
            "generatedAt": "2026-07-25T10:00:00+00:00",
            "marketOverview": {"marketDate": "2026-07-24"},
            "industryRotation": [{"marketDate": "2026-07-23"}],
            "tradingActivity": {
                "points": [{"marketDate": "2026-07-24", "value": 19_442.25}]
            },
        }
    )

    assert payload["asOfMarketDate"] == "2026-07-24"
    assert payload["dateAlignment"]["status"] == "mixed"
    assert payload["dateAlignment"]["moduleMarketDates"]["industryRotation"] == (
        "2026-07-23"
    )
    assert payload["dateAlignment"]["mismatchedModules"] == ["industryRotation"]


def test_sector_cards_and_activity_match_frontend_contract():
    service = make_service()

    industries = service.industry_rotation(limit=5)
    themes = service.hot_themes(limit=5)
    flows = service.sector_fund_flow(limit=5)
    activity = service.trading_activity(days=2)

    assert len(industries) == 5
    assert industries[0]["turnover"] == 10.0
    assert themes[0]["tags"] == ["20家上涨", "0家下跌"]
    assert flows["metric"] == "main_net_inflow_estimate_100m_cny"
    assert flows["data_status"] == "available"
    assert len(flows["items"]) == 5
    assert flows["items"][0]["value"] > 0
    assert flows["items"][-1]["value"] < 0
    assert flows["summary"]["positive_count"] == 3
    assert flows["summary"]["negative_count"] == 2
    assert activity["points"][-1]["value"] == 12000.0
    assert activity["latest"] == 12000.0
    assert activity["previous_average"] == 10000.0
    assert activity["change_pct"] == 20.0
    assert activity["relative_to_average_pct"] == 9.09
    assert activity["activity_label"] == "较近2日均值放量"


def test_industry_rotation_uses_real_history_and_computes_period_change():
    class HistoryAnalysis(FakeAnalysis):
        def sector_history(self, code, days=5, allow_remote=True):
            assert code == "BK0000"
            assert days == 5
            assert allow_remote is True
            return {
                "status": "available",
                "source": "Fake sector history",
                "points": [
                    {"market_date": "2026-07-20", "close": 100},
                    {"market_date": "2026-07-21", "close": 101},
                    {"market_date": "2026-07-22", "close": 103},
                    {"market_date": "2026-07-23", "close": 104},
                    {"market_date": "2026-07-24", "close": 110},
                ],
            }

    service = TodayDashboardService(
        FakeDatabase(),
        HistoryAnalysis(),
        intraday_index_provider=FakeIndexProvider(),
        tushare_client=FakeTushare(),
    )

    item = service.industry_rotation(limit=1)[0]

    assert item["trend"] == [100.0, 101.0, 103.0, 104.0, 110.0]
    assert item["trendMarketDates"] == [
        "2026-07-20",
        "2026-07-21",
        "2026-07-22",
        "2026-07-23",
        "2026-07-24",
    ]
    assert item["trendStatus"] == "available"
    assert item["fiveDayChangePct"] == 10.0
    assert item["marketDate"] == "2026-07-24"


def test_industry_rotation_does_not_invent_two_point_history_when_unavailable():
    class MissingHistoryAnalysis(FakeAnalysis):
        def sector_history(self, code, days=5, allow_remote=True):
            return {
                "status": "unavailable",
                "source": "Fake sector history",
                "points": [],
            }

    service = TodayDashboardService(
        FakeDatabase(),
        MissingHistoryAnalysis(),
        intraday_index_provider=FakeIndexProvider(),
        tushare_client=FakeTushare(),
    )

    item = service.industry_rotation(limit=1)[0]

    assert item["trend"] == []
    assert item["trendMarketDates"] == []
    assert item["trendStatus"] == "unavailable"
    assert item["fiveDayChangePct"] is None


def test_remote_activity_refresh_replaces_incomplete_fast_cache():
    class HistoryTushare(FakeTushare):
        def trade_cal(self, **params):
            return pd.DataFrame(
                {"cal_date": ["20260720", "20260721", "20260722"]}
            )

        def query(self, api_name: str, **params):
            if api_name == "daily":
                values = {
                    "20260720": 9000,
                    "20260721": 10000,
                    "20260722": 12000,
                }
                return pd.DataFrame(
                    {
                        "amount": [
                            values[params["trade_date"]] * 100_000 / 3000
                        ]
                        * 3000
                    }
                )
            return super().query(api_name, **params)

    service = TodayDashboardService(
        FakeDatabase(),
        FakeAnalysis(),
        intraday_index_provider=FakeIndexProvider(),
        tushare_client=HistoryTushare(),
    )

    fast = service.trading_activity(days=3, allow_remote=False)
    complete = service.trading_activity(days=3, allow_remote=True)

    assert len(fast["points"]) == 2
    assert len(complete["points"]) == 3
    assert complete["points"][0]["value"] == 9000


def test_daily_snapshot_does_not_regress_to_preopen_turnover(tmp_path):
    database = Database(tmp_path / "today.db", tmp_path / "workspaces")
    database.initialize()
    closed = {
        "market_date": "2026-07-23",
        "source": "test",
        "fetched_at": "2026-07-23T07:01:00+00:00",
        "turnover": {
            "total_amount_cny": 2_209_478_000_000,
            "total_amount_100m_cny": 22094.78,
        },
    }
    preopen = {
        **closed,
        "fetched_at": "2026-07-24T01:29:00+00:00",
        "turnover": {
            "total_amount_cny": 20_278_000_000,
            "total_amount_100m_cny": 202.78,
        },
    }

    database.upsert_market_breadth_snapshot(closed)
    database.upsert_market_breadth_snapshot(preopen)

    saved = database.list_market_breadth_snapshots(limit=1)[0]
    assert saved["turnover"]["total_amount_100m_cny"] == 22094.78


def test_dashboard_reuses_shared_snapshots_and_caches_result():
    class CountingAnalysis(FakeAnalysis):
        def __init__(self):
            self.breadth_calls = 0
            self.sector_calls = []

        def market_breadth(self):
            self.breadth_calls += 1
            return super().market_breadth()

        def hot_sectors(self, limit: int = 20):
            self.sector_calls.append(limit)
            return super().hot_sectors(limit)

    class CountingTushare(FakeTushare):
        def __init__(self):
            self.calls = []

        def query(self, api_name: str, **params):
            self.calls.append((api_name, params))
            return super().query(api_name, **params)

    analysis = CountingAnalysis()
    tushare = CountingTushare()
    service = TodayDashboardService(
        FakeDatabase(),
        analysis,
        intraday_index_provider=FakeIndexProvider(),
        tushare_client=tushare,
    )

    first = service.dashboard()
    second = service.dashboard()

    assert first is second
    assert analysis.breadth_calls == 1
    assert analysis.sector_calls == [100]
    assert len(tushare.calls) == 2
    assert len(first["indices"]) == 4
    assert first["sectorFundFlow"]["metric"] == (
        "main_net_inflow_estimate_100m_cny"
    )


def test_forced_dashboard_refresh_bypasses_stale_persistent_memory_cache():
    service = make_service()
    service._dashboard_cache = (
        float("inf"),
        {
            "generatedAt": "2026-07-23T10:00:00+00:00",
            "marketOverview": {
                "marketDate": "2026-07-23",
                "limitDataAsOf": "2026-07-23",
            },
        },
    )

    refreshed = service._refresh_dashboard(force=True)

    assert refreshed["marketOverview"]["marketDate"] == "2026-07-22"
    assert len(refreshed["indices"]) == 4
    assert refreshed["generatedAt"] != "2026-07-23T10:00:00+00:00"


def test_sector_fund_flow_route_returns_object_contract(client):
    response = client.get(
        "/api/v1/market/sector-fund-flow",
        params={"limit": 5},
    )

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, dict)
    assert payload["metric"] == "main_net_inflow_estimate_100m_cny"
    assert isinstance(payload["items"], list)


def test_demo_contains_no_secret(client):
    new = client.get("/demo")

    assert new.status_code == 200
    new_js = client.get("/static/high-fidelity-demo.js")
    assert new_js.status_code == 200
    frontend_text = new.text + new_js.text
    assert "window.QSTodayConfig" in frontend_text
    assert "TUSHARE_TOKEN" not in frontend_text
    assert "数据截止" in frontend_text
    assert "页面更新" in frontend_text
    assert 'id="marketOverviewMeta"' in frontend_text
    assert "涨跌停数据" in frontend_text
    assert "未与本快照合并" in frontend_text


def test_new_demo_index_adapter_is_available(client):
    response = client.get(
        "/api/v1/market/index-quote",
        params={"code": "399006.SZ"},
    )

    assert response.status_code == 200
    assert response.json()["code"] == "399006.SZ"
    assert response.json()["name"] == "创业板"


def test_new_demo_explains_activity_and_flow_measurement(client):
    script = client.get("/static/high-fidelity-demo.js")

    assert script.status_code == 200
    assert "activity_label" in script.text
    assert "relative_to_average_pct" in script.text
    assert "metric_label" in script.text
    assert "不是全市场资金净流入" in script.text
