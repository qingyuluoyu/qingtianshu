from __future__ import annotations

import pandas as pd

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

    overview = service.market_overview()
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


def test_sector_cards_and_activity_match_frontend_contract():
    service = make_service()

    industries = service.industry_rotation(limit=5)
    themes = service.hot_themes(limit=5)
    flows = service.sector_fund_flow(limit=5)
    activity = service.trading_activity(days=2)

    assert len(industries) == 5
    assert industries[0]["turnover"] == 10.0
    assert themes[0]["tags"] == ["20家上涨", "0家下跌"]
    assert len(flows) == 5
    assert flows[0]["value"] > 0
    assert flows[-1]["value"] < 0
    assert activity["points"][-1]["value"] == 12000.0


def test_new_demo_is_isolated_from_legacy_demo_and_contains_no_secret(client):
    legacy = client.get("/old-demo")
    new = client.get("/demo")

    assert legacy.status_code == 200
    assert new.status_code == 200
    assert "金融研究 Agent" in legacy.text
    new_js = client.get("/static/high-fidelity-demo.js")
    assert new_js.status_code == 200
    frontend_text = new.text + new_js.text
    assert "window.QSTodayConfig" in frontend_text
    assert "TUSHARE_TOKEN" not in frontend_text
    assert "市场数据已更新" in frontend_text
    assert 'id="marketOverviewMeta"' in frontend_text
    assert "涨跌停截至" in frontend_text


def test_new_demo_index_adapter_is_available(client):
    response = client.get(
        "/api/v1/market/index-quote",
        params={"code": "399006.SZ"},
    )

    assert response.status_code == 200
    assert response.json()["code"] == "399006.SZ"
    assert response.json()["name"] == "创业板"
