from __future__ import annotations

from collections import Counter

import pandas as pd
from fastapi.testclient import TestClient

from app.main import _filter_knowledge_context
from app.services.stock_screener import StockScreenerService


class FakeTushareClient:
    def __init__(self) -> None:
        self.calls: Counter[str] = Counter()
        self.open_dates = [
            value.strftime("%Y%m%d")
            for value in pd.bdate_range(end="2026-07-21", periods=35)
        ]
        self.latest = self.open_dates[-1]
        self.date_5d = self.open_dates[-6]
        self.date_20d = self.open_dates[-21]

    def query(self, api_name: str, **params):
        self.calls[api_name] += 1
        if api_name == "trade_cal":
            return pd.DataFrame(
                {"cal_date": self.open_dates, "is_open": [1] * len(self.open_dates)}
            )
        if api_name == "stock_basic":
            return pd.DataFrame(
                [
                    self._basic("000063.SZ", "中兴通讯", "通信设备", "主板"),
                    self._basic("300308.SZ", "中际旭创", "通信设备", "创业板"),
                    self._basic("000001.SZ", "平安银行", "银行", "主板"),
                    self._basic("600000.SH", "浦发银行", "银行", "主板"),
                    self._basic("600001.SH", "*ST测试", "工业", "主板"),
                ]
            )
        if api_name == "daily":
            trade_date = params["trade_date"]
            closes = {
                self.latest: [100.0, 120.0, 10.0, 11.0, 5.0],
                self.date_5d: [95.0, 100.0, 9.8, 10.5, 5.2],
                self.date_20d: [80.0, 90.0, 9.5, 10.0, 6.0],
            }
            if trade_date not in closes:
                return pd.DataFrame()
            rows = []
            codes = ["000063.SZ", "300308.SZ", "000001.SZ", "600000.SH", "600001.SH"]
            for index, (code, close) in enumerate(zip(codes, closes[trade_date])):
                row = {"ts_code": code, "trade_date": trade_date, "close": close}
                if trade_date == self.latest:
                    row.update(
                        {
                            "open": close - 1,
                            "high": close + 1,
                            "low": close - 2,
                            "pre_close": close - 0.5,
                            "pct_chg": 0.5,
                            "vol": 1000 + index,
                            "amount": 50_000 - index * 1000,
                        }
                    )
                rows.append(row)
            return pd.DataFrame(rows)
        if api_name == "daily_basic":
            return pd.DataFrame(
                [
                    self._daily_basic("000063.SZ", 35, 3.0, 400, 1.1),
                    self._daily_basic("300308.SZ", 45, 6.0, 600, 1.4),
                    self._daily_basic("000001.SZ", 7, 0.8, 2_000, 1.0),
                    self._daily_basic("600000.SH", 8, 0.7, 1_500, 1.2),
                    self._daily_basic("600001.SH", 15, 2.0, 100, 2.0),
                ]
            )
        if api_name == "fina_indicator":
            financials = {
                "000063.SZ": (10.0, -5.0, 6.0),
                "300308.SZ": (30.0, 40.0, 15.0),
                "000001.SZ": (5.0, 6.0, 8.0),
                "600000.SH": (10.0, 12.0, 7.0),
                "600001.SH": (-10.0, -20.0, -5.0),
            }
            revenue, profit, roe = financials[params["ts_code"]]
            return pd.DataFrame(
                [
                    {
                        "ts_code": params["ts_code"],
                        "ann_date": "20260429",
                        "end_date": "20260331",
                        "tr_yoy": revenue,
                        "netprofit_yoy": profit,
                        "roe": roe,
                        "grossprofit_margin": 30.0,
                        "netprofit_margin": 8.0,
                        "debt_to_assets": 55.0,
                    }
                ]
            )
        raise AssertionError(f"unexpected API: {api_name}")

    @staticmethod
    def _basic(ts_code: str, name: str, industry: str, market: str) -> dict:
        return {
            "ts_code": ts_code,
            "symbol": ts_code.split(".")[0],
            "name": name,
            "area": "测试",
            "industry": industry,
            "market": market,
            "list_date": "20100101",
            "exchange": ts_code.split(".")[1],
        }

    def _daily_basic(
        self, ts_code: str, pe: float, pb: float, total_mv_yi: float, volume_ratio: float
    ) -> dict:
        return {
            "ts_code": ts_code,
            "trade_date": self.latest,
            "turnover_rate": 2.0,
            "volume_ratio": volume_ratio,
            "pe_ttm": pe,
            "pb": pb,
            "ps_ttm": 3.0,
            "total_mv": total_mv_yi * 10_000,
            "circ_mv": total_mv_yi * 8_000,
        }


class TransientFinanceFailureClient(FakeTushareClient):
    def __init__(self) -> None:
        super().__init__()
        self.failed_once: set[str] = set()

    def query(self, api_name: str, **params):
        if api_name == "fina_indicator" and params["ts_code"] == "300308.SZ":
            if params["ts_code"] not in self.failed_once:
                self.failed_once.add(params["ts_code"])
                raise RuntimeError("temporary throttle")
        return super().query(api_name, **params)


def test_quality_screen_is_transparent_and_has_separate_data_dates():
    fake = FakeTushareClient()
    service = StockScreenerService(fake, snapshot_ttl_seconds=600)

    result = service.screen(profile="quality", max_results=3)

    assert result["status"] == "ready"
    assert result["profile"]["key"] == "quality"
    assert result["data_meta"]["latest_completed_trade_date"] == "2026-07-21"
    assert result["data_meta"]["financial_report_periods"] == ["2026-03-31"]
    assert result["items"][0]["name"] == "中际旭创"
    assert "中兴通讯" not in {item["name"] for item in result["items"]}
    assert all("score" not in item for item in result["items"])
    assert result["items"][0]["matched_reasons"]
    assert "不构成推荐" in result["boundary"]

    cached = service.screen(profile="value", max_results=2)
    assert cached["data_meta"]["cache_hit"] is True
    assert fake.calls["trade_cal"] == 1


def test_stock_screener_api_requires_user_and_returns_deterministic_candidates(app):
    fake = FakeTushareClient()
    app.state.stock_screener.client = fake
    client = TestClient(app)

    unauthenticated = client.post(
        "/me/stock-screener", json={"profile": "trend"}
    )
    assert unauthenticated.status_code == 401

    assert client.post("/users", json={"name": "Screener User"}).status_code == 201
    response = client.post(
        "/me/stock-screener",
        json={
            "profile": "trend",
            "max_results": 3,
            "filters": {"min_market_cap_yi": 100},
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["type"] == "stock_screen"
    assert payload["rules"]
    assert payload["universe"]["matched"] <= 3
    assert all(item["internal_symbol"] for item in payload["items"])


def test_stock_screener_profiles_expose_rules_without_recommendation_language(app):
    response = TestClient(app).get("/stock-screener/profiles")
    assert response.status_code == 200
    payload = response.json()
    assert {item["key"] for item in payload["items"]} == {
        "quality",
        "trend",
        "value",
        "pullback",
    }
    assert "不构成推荐" in payload["boundary"]


def test_agent_routes_natural_language_screening_to_deterministic_service(app):
    fake = FakeTushareClient()
    app.state.stock_screener.client = fake
    client = TestClient(app)
    assert client.post("/users", json={"name": "Agent Screener"}).status_code == 201

    response = client.post(
        "/me/chat",
        json={
            "message": "帮我选5只PE低于10倍、市值超过100亿的低估值股票",
            "execute_agent": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"] == "stock_screen"
    assert payload["evidence"]["profile"]["key"] == "value"
    assert payload["evidence"]["effective_filters"]["max_pe_ttm"] == 10
    assert payload["evidence"]["effective_filters"]["min_market_cap_yi"] == 100
    assert "研究候选" in payload["answer"]
    assert payload["evidence_sources"]


def test_transient_financial_failure_is_retried_instead_of_becoming_a_gap():
    fake = TransientFinanceFailureClient()
    service = StockScreenerService(fake, finance_workers=4)

    result = service.screen(profile="quality", max_results=3)

    item = next(value for value in result["items"] if value["name"] == "中际旭创")
    assert item["financials"]["status"] == "available"
    assert item["financials"]["report_period"] == "2026-03-31"
    assert "revenue_yoy" not in item["missing_fields"]


def test_stock_screen_knowledge_drops_unrelated_stock_archives():
    context = {
        "items": [
            {
                "title": "中兴通讯长期研究档案",
                "source_key": "research-report:000063.SZ",
                "scope": "common",
            },
            {
                "title": "个人投资者的研究工作流",
                "source_key": "builtin:research-workflows.md",
                "scope": "common",
            },
            {
                "title": "我的筛选偏好",
                "source_key": "user:screening-note",
                "scope": "user",
            },
        ],
        "coverage": {"matched_documents": 3},
    }

    filtered = _filter_knowledge_context(
        context, intent="stock_screen", symbol=None, evidence={}
    )

    assert [item["title"] for item in filtered["items"]] == [
        "个人投资者的研究工作流",
        "我的筛选偏好",
    ]
    assert filtered["coverage"]["matched_documents"] == 2
