from __future__ import annotations

from collections import Counter

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.main import (
    _build_visible_evidence_sources,
    _filter_knowledge_context,
    _is_stock_screen_query,
    _stock_screen_parameters,
)
from app.services.agent import AgentService
from app.services.stock_screener import StockScreenerService, StockScreenerUnavailable


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
        self,
        ts_code: str,
        pe: float,
        pb: float,
        total_mv_yi: float,
        volume_ratio: float,
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


class MissingValuationFieldClient(FakeTushareClient):
    def query(self, api_name: str, **params):
        result = super().query(api_name, **params)
        if api_name == "daily_basic":
            result.loc[result["ts_code"] == "300308.SZ", "pb"] = None
        return result


class FakePersistedSnapshotDatabase:
    def __init__(self) -> None:
        self.trade_dates = [
            value.strftime("%Y%m%d")
            for value in pd.bdate_range(end="2026-07-24", periods=25)
        ]
        self.codes = ["000063.SZ", "300308.SZ", "000001.SZ", "600000.SH"]
        self.names = ["中兴通讯", "中际旭创", "平安银行", "浦发银行"]
        self.industries = ["通信设备", "通信设备", "银行", "银行"]
        self.latest_closes = [120.0, 100.0, 12.0, 11.0]
        self.base_5 = [100.0, 95.0, 11.5, 10.0]
        self.base_20 = [80.0, 90.0, 10.0, 9.0]

    def list_latest_tushare_dataset_snapshots(self, dataset: str, **_kwargs):
        if dataset == "stock_basic":
            return [
                self._record(
                    code,
                    [
                        {
                            "ts_code": code,
                            "name": name,
                            "industry": industry,
                            "market": "主板",
                            "list_date": "20100101",
                            "exchange": code.split(".")[1],
                        }
                    ],
                )
                for code, name, industry in zip(
                    self.codes, self.names, self.industries, strict=True
                )
            ]
        if dataset == "daily_basic":
            return [
                self._record(
                    code,
                    [
                        {
                            "ts_code": code,
                            "trade_date": self.trade_dates[-1],
                            "turnover_rate": 2.0,
                            "volume_ratio": 1.2,
                            "pe_ttm": 20.0 + index,
                            "pb": 2.0,
                            "total_mv_yi": 200.0 + index * 20,
                            "circ_mv_yi": 160.0 + index * 20,
                        }
                    ],
                )
                for index, code in enumerate(self.codes)
            ]
        if dataset == "daily":
            records = []
            for index, code in enumerate(self.codes):
                rows = []
                for offset, trade_date in enumerate(self.trade_dates):
                    close = 90.0 + index + offset
                    if offset == 4:
                        close = self.base_20[index]
                    elif offset == 19:
                        close = self.base_5[index]
                    elif offset == 24:
                        close = self.latest_closes[index]
                    rows.append(
                        {
                            "ts_code": code,
                            "trade_date": trade_date,
                            "open": close - 0.2,
                            "high": close + 0.5,
                            "low": close - 0.5,
                            "close": close,
                            "pct_chg": 1.0,
                            "vol": 1_000_000 + index,
                            "amount": 50_000 - index * 1_000,
                        }
                    )
                records.append(self._record(code, list(reversed(rows))))
            return records
        if dataset == "fina_indicator":
            return [
                self._record(
                    code,
                    [
                        {
                            "ts_code": code,
                            "ann_date": "20260429",
                            "end_date": "20260331",
                            "roe": 8.0 + index,
                        }
                    ],
                )
                for index, code in enumerate(self.codes)
            ]
        return []

    def latest_tushare_dataset_snapshot(self, dataset: str, scope_key: str):
        if dataset == "a_share_universe" and scope_key == "all":
            return {"payload": {"coverage": {"listed": len(self.codes)}}}
        return None

    @staticmethod
    def _record(scope_key: str, rows: list[dict]) -> dict:
        internal = scope_key[:-3] + ".SS" if scope_key.endswith(".SH") else scope_key
        return {"scope_key": internal, "payload": {"rows": rows}}


class UndercoveredPersistedSnapshotDatabase(FakePersistedSnapshotDatabase):
    def latest_tushare_dataset_snapshot(self, dataset: str, scope_key: str):
        if dataset == "a_share_universe" and scope_key == "all":
            return {"payload": {"coverage": {"listed": 100}}}
        return super().latest_tushare_dataset_snapshot(dataset, scope_key)


class UnavailableLiveClient:
    def query(self, api_name: str, **_params):
        raise RuntimeError(f"{api_name} unavailable")


def test_quality_screen_is_transparent_and_has_separate_data_dates():
    fake = FakeTushareClient()
    service = StockScreenerService(fake, snapshot_ttl_seconds=600)

    result = service.screen(profile="quality", max_results=3)

    assert result["status"] == "ready"
    assert result["profile"]["key"] == "quality"
    assert result["data_meta"]["latest_completed_trade_date"] == "2026-07-21"
    assert result["data_meta"]["financial_report_periods"] == ["2026-03-31"]
    assert result["data_contract"]["contract_version"] == "stock_screen_data_v1"
    assert result["data_contract"]["data_version"].startswith("stock-screen-v1-")
    assert result["data_contract"]["as_of"]["market_date"] == "2026-07-21"
    assert result["data_contract"]["coverage"]["market_snapshot"] == {
        "available": 5,
        "expected": 5,
        "missing": 0,
        "ratio": 1.0,
    }
    assert result["data_contract"]["representation"] == {
        "actual_scope_label": "全部A股",
        "coverage_status": "complete",
        "represents_requested_scope": True,
        "represents_full_market": True,
        "minimum_coverage_ratio": 0.95,
        "note": "本轮数据足以代表所选范围的确定性规则计算。",
    }
    assert result["universe"]["financial_candidate_pool"] == 4
    assert result["universe"]["financials_checked"] == 4
    assert result["items"][0]["name"] == "中际旭创"
    assert result["items"][0]["evidence_times"] == {
        "market_date": "2026-07-21",
        "financial_report_period": "2026-03-31",
        "financial_announcement_date": "2026-04-29",
    }
    assert result["items"][0]["source_contract"]["valuation"] == (
        "Tushare Pro:daily_basic"
    )
    assert "中兴通讯" not in {item["name"] for item in result["items"]}
    assert all("score" not in item for item in result["items"])
    assert result["items"][0]["matched_reasons"]
    assert "不构成推荐" in result["boundary"]

    cached = service.screen(profile="value", max_results=2)
    assert cached["data_meta"]["cache_hit"] is True
    assert fake.calls["trade_cal"] == 1


def test_persisted_database_snapshot_keeps_screener_usable_without_live_provider():
    service = StockScreenerService(
        None,
        database=FakePersistedSnapshotDatabase(),
        snapshot_ttl_seconds=600,
    )

    result = service.screen(max_results=3)

    assert result["status"] == "ready"
    assert result["profile"]["key"] == "trend"
    assert result["data_meta"]["source_mode"] == "persisted"
    assert result["data_meta"]["latest_completed_trade_date"] == "2026-07-24"
    assert result["data_contract"]["data_version"].startswith("stock-screen-db-v1-")
    assert result["data_contract"]["coverage"]["market_snapshot"] == {
        "available": 4,
        "expected": 4,
        "missing": 0,
        "ratio": 1.0,
    }
    assert {item["name"] for item in result["items"]} == {"中兴通讯", "浦发银行"}
    assert all(
        item["financials"]["report_period"] == "2026-03-31" for item in result["items"]
    )
    assert "生产数据库" in result["warnings"][0]


def test_published_market_snapshot_keeps_screener_usable_without_live_provider(app):
    publisher = StockScreenerService(
        FakeTushareClient(), database=app.state.database, snapshot_ttl_seconds=600
    )

    published = publisher.refresh_persisted_market_snapshot()

    assert published["published"] is True
    reader = StockScreenerService(
        None, database=app.state.database, snapshot_ttl_seconds=600
    )
    result = reader.screen(profile="trend", max_results=3)
    assert result["status"] == "ready"
    assert result["data_meta"]["source_mode"] == "persisted"
    assert result["data_contract"]["data_version"].startswith(
        "stock-screen-market-v1-"
    )


def test_incomplete_market_snapshot_cannot_replace_previously_published_snapshot(app):
    publisher = StockScreenerService(
        FakeTushareClient(), database=app.state.database, snapshot_ttl_seconds=600
    )
    stable = publisher.refresh_persisted_market_snapshot()
    assert stable["published"] is True

    original_build_snapshot = publisher._build_snapshot

    def under_covered_snapshot():
        frame, metadata = original_build_snapshot()
        incomplete = frame.head(2).copy()
        return incomplete, {
            **metadata,
            "market_coverage_ratio": 0.4,
            "listed_stock_count": 5,
        }

    publisher._build_snapshot = under_covered_snapshot  # type: ignore[method-assign]
    refresh = publisher.refresh_persisted_market_snapshot()

    assert refresh["published"] is False
    assert refresh["previous_stable_retained"] is True
    reader = StockScreenerService(None, database=app.state.database)
    result = reader.screen(profile="trend", max_results=3)
    assert result["status"] == "ready"
    assert result["data_contract"]["data_version"] == stable["data_version"]


def test_failed_market_snapshot_refresh_keeps_previously_published_snapshot(app):
    publisher = StockScreenerService(
        FakeTushareClient(), database=app.state.database, snapshot_ttl_seconds=600
    )
    stable = publisher.refresh_persisted_market_snapshot()
    assert stable["published"] is True

    def unavailable_snapshot():
        raise RuntimeError("provider_unavailable")

    publisher._build_snapshot = unavailable_snapshot  # type: ignore[method-assign]
    refresh = publisher.refresh_persisted_market_snapshot()

    assert refresh == {
        "status": "failed",
        "published": False,
        "data_version": None,
        "snapshot_stock_count": 0,
        "market_coverage_ratio": 0.0,
        "previous_stable_retained": True,
    }
    reader = StockScreenerService(None, database=app.state.database)
    assert reader.screen(profile="trend", max_results=3)["data_contract"][
        "data_version"
    ] == stable["data_version"]


def test_background_does_not_register_market_snapshot_without_tushare(app):
    app.state.stock_screener.client = None

    assert "stock_screener_market_snapshot_refresh" not in app.state.background._job_functions()


def test_background_registers_market_snapshot_refresh_when_tushare_is_configured(app):
    app.state.stock_screener.client = FakeTushareClient()

    jobs = app.state.background._job_functions()

    assert "stock_screener_market_snapshot_refresh" in jobs
    assert jobs["stock_screener_market_snapshot_refresh"]()["published"] is True


def test_pullback_candidates_prioritize_samples_closest_to_stabilizing():
    frame = pd.DataFrame(
        [
            {"ts_code": "000001.SZ", "return_5d_pct": 30.0},
            {"ts_code": "000002.SZ", "return_5d_pct": 2.0},
            {"ts_code": "000003.SZ", "return_5d_pct": 12.0},
        ]
    )

    sorted_frame = StockScreenerService._sort_frame(frame, "pullback")

    assert sorted_frame["return_5d_pct"].tolist() == [2.0, 12.0, 30.0]
    profile = next(
        item for item in StockScreenerService.profiles() if item["key"] == "pullback"
    )
    assert "从低到高" in profile["sort_rule"]
    assert "刚转正" in profile["sort_rule"]


def test_screen_candidate_builds_research_focus_and_real_metric_attention_flags():
    service = StockScreenerService(None)
    item = service._build_item(
        pd.Series(
            {
                "ts_code": "000063.SZ",
                "internal_symbol": "000063.SZ",
                "name": "中兴通讯",
                "industry": "通信设备",
                "market": "主板",
                "list_date": "19851118",
                "trade_date": "20260728",
                "latest_close": 40.0,
                "pct_change": -9.2,
                "return_5d_pct": 8.0,
                "return_20d_pct": 30.0,
                "industry_avg_return_20d_pct": 10.0,
                "industry_excess_20d_pct": 20.0,
                "pe_ttm": 120.0,
                "pb": 9.0,
                "ps_ttm": 5.0,
                "total_mv_yi": 800.0,
                "circ_mv_yi": 700.0,
                "turnover_rate": 4.0,
                "volume_ratio": 1.5,
            }
        ),
        "trend",
        {
            "status": "available",
            "coverage_status": "sufficient",
            "report_period": "2026-03-31",
            "announcement_date": "2026-04-29",
            "revenue_yoy": 5.0,
            "net_profit_yoy": -12.5,
            "roe": 5.0,
            "gross_margin": 30.0,
            "net_margin": 8.0,
            "debt_to_assets": 55.0,
        },
    )

    assert "近 20 日" in item["research_focus"]
    assert "相对行业" in item["research_focus"]
    assert any("当日下跌 9.20%" in value for value in item["attention_flags"])
    assert any("净利润同比 -12.50%" in value for value in item["attention_flags"])
    assert any("反方线索" in value for value in item["attention_flags"])
    assert any("PE TTM 120.00" in value for value in item["attention_flags"])
    assert len(item["attention_flags"]) <= 4


def test_undercovered_persisted_snapshot_never_triggers_a_live_full_market_scan():
    live = FakeTushareClient()
    service = StockScreenerService(
        live,
        database=UndercoveredPersistedSnapshotDatabase(),
        snapshot_ttl_seconds=600,
    )

    with pytest.raises(StockScreenerUnavailable) as raised:
        service.screen(profile="trend", max_results=3)

    assert raised.value.code == "snapshot_not_ready"
    assert live.calls["stock_basic"] == 0
    assert live.calls["daily"] == 0


def test_undercovered_persisted_snapshot_is_not_presented_as_a_constrained_result():
    service = StockScreenerService(
        UnavailableLiveClient(),
        database=UndercoveredPersistedSnapshotDatabase(),
        snapshot_ttl_seconds=600,
    )

    with pytest.raises(StockScreenerUnavailable) as raised:
        service.screen(
            profile="value",
            max_results=3,
            filters={"min_market_cap_yi": 10_000},
        )

    assert raised.value.code == "snapshot_not_ready"


def test_stock_screener_api_requires_user_and_returns_deterministic_candidates(app):
    fake = FakeTushareClient()
    app.state.stock_screener.client = fake
    assert app.state.stock_screener.refresh_persisted_market_snapshot()["published"] is True
    client = TestClient(app)

    unauthenticated = client.post("/me/stock-screener", json={"profile": "trend"})
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


def test_stock_screener_api_reports_typed_snapshot_not_ready_without_live_scan(app):
    fake = FakeTushareClient()
    app.state.stock_screener.client = fake
    client = TestClient(app)
    assert client.post("/users", json={"name": "Snapshot Pending User"}).status_code == 201

    response = client.post("/me/stock-screener", json={"profile": "trend"})

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "snapshot_not_ready"
    assert fake.calls["stock_basic"] == 0


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


def test_agent_routes_product_screening_language_to_stock_screen(app):
    fake = FakeTushareClient()
    app.state.stock_screener.client = fake
    client = TestClient(app)
    assert client.post("/users", json={"name": "Product Screener"}).status_code == 201

    response = client.post(
        "/me/chat",
        json={
            "message": (
                "用经营改善模板筛选A股，并明确说明股票池覆盖、数据版本、"
                "行情日、财务报告期和关键数据缺口。"
            ),
            "execute_agent": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"] == "stock_screen"
    assert payload["evidence"]["profile"]["key"] == "quality"
    assert payload["evidence"]["data_contract"]["contract_version"] == (
        "stock_screen_data_v1"
    )
    assert "股票池覆盖 5/5 只（100.0%）" in payload["answer"]
    assert "数据版本 stock-screen-v1-" in payload["answer"]
    assert "行情日 2026-07-21" in payload["answer"]
    assert "财务报告期 2026-03-31" in payload["answer"]


def test_stock_screen_product_terms_route_to_expected_profiles():
    cases = {
        "查看经营改善候选": "quality",
        "给我相对行业增强候选": "trend",
        "按估值约束筛选": "value",
        "查看回撤后待复核": "pullback",
    }

    for message, expected_profile in cases.items():
        assert _is_stock_screen_query(message) is True
        assert _stock_screen_parameters(message)["profile"] == expected_profile


def test_transient_financial_failure_is_retried_instead_of_becoming_a_gap():
    fake = TransientFinanceFailureClient()
    service = StockScreenerService(fake, finance_workers=4)

    result = service.screen(profile="quality", max_results=3)

    item = next(value for value in result["items"] if value["name"] == "中际旭创")
    assert item["financials"]["status"] == "available"
    assert item["financials"]["report_period"] == "2026-03-31"
    assert "revenue_yoy" not in item["missing_fields"]


def test_stock_screen_explains_field_level_missing_reason():
    service = StockScreenerService(MissingValuationFieldClient())

    result = service.screen(profile="trend", max_results=3)

    item = next(value for value in result["items"] if value["name"] == "中际旭创")
    assert "pb" in item["missing_fields"]
    reason = next(value for value in item["missing_reasons"] if value["field"] == "pb")
    assert reason == {
        "field": "pb",
        "code": "daily_basic_field_missing",
        "reason": "最近完整交易日的估值或市值截面未返回该字段",
    }


def test_stock_screen_agent_contract_keeps_scope_dates_and_readable_gaps():
    service = StockScreenerService(MissingValuationFieldClient())
    result = service.screen(profile="trend", max_results=3)

    compact = AgentService._compact_stock_screen_evidence(result)
    preview = AgentService._render_preview(compact)
    sources = _build_visible_evidence_sources(result)

    assert compact["candidate_count_total"] == len(result["items"])
    assert compact["items_in_prompt"] == len(result["items"])
    assert compact["data_contract"]["data_version"].startswith("stock-screen-v1-")
    assert compact["data_contract"]["coverage"]["market_snapshot"]["expected"] == 5
    assert all("ts_code" not in item for item in compact["items"])
    assert all(item.get("research_focus") for item in compact["items"])
    assert "股票池覆盖 5/5 只（100.0%）" in preview
    assert "数据版本 stock-screen-v1-" in preview
    assert "行情日 2026-07-21" in preview
    assert "财务报告期 2026-03-31" in preview
    assert "财报公告日 2026-04-29" in preview
    assert "最近完整交易日的估值或市值截面未返回该字段" in preview
    assert sources[0]["kind"] == "选股范围"
    assert "股票池覆盖 5/5 只" in sources[0]["summary"]
    assert "数据版本 stock-screen-v1-" in sources[0]["summary"]


def test_stock_screen_guard_rejects_full_market_claim_when_snapshot_is_incomplete():
    evidence = {
        "type": "stock_screen",
        "profile": {"key": "trend", "label": "相对行业增强候选"},
        "data_contract": {
            "coverage": {
                "market_snapshot": {
                    "available": 5526,
                    "expected": 5530,
                    "missing": 4,
                    "ratio": 0.999277,
                }
            }
        },
        "items": [],
    }

    overclaim = AgentService._validate_model_output(
        "A股全市场没有股票满足本轮条件。", evidence
    )
    scoped = AgentService._validate_model_output(
        "股票池覆盖5526/5530只；本轮已覆盖范围内没有股票满足全部条件，不能外推全市场。",
        evidence,
    )

    assert overclaim["passed"] is False
    assert (
        "通用选股覆盖不足时不能外推为全市场结论"
        in (overclaim["unsupported_market_inferences"])
    )
    assert scoped["passed"] is True


def test_stock_screen_guard_uses_financial_representation_not_only_market_rows():
    evidence = {
        "type": "stock_screen",
        "profile": {"key": "quality", "label": "经营改善候选"},
        "data_contract": {
            "coverage": {
                "market_snapshot": {
                    "available": 5530,
                    "expected": 5530,
                    "missing": 0,
                    "ratio": 1.0,
                }
            },
            "representation": {
                "represents_full_market": False,
                "actual_scope_label": "A股完整行情范围，财务或规则字段部分覆盖",
            },
        },
        "items": [],
    }

    result = AgentService._validate_model_output("全部A股没有经营改善候选。", evidence)

    assert result["passed"] is False
    assert (
        "通用选股覆盖不足时不能外推为全市场结论"
        in (result["unsupported_market_inferences"])
    )


def test_stock_screen_guard_rejects_candidate_count_conflict():
    evidence = {
        "type": "stock_screen",
        "profile": {"key": "quality", "label": "经营改善候选"},
        "universe": {"matched": 2},
        "items": [
            {"name": "甲公司", "internal_symbol": "000001.SZ"},
            {"name": "乙公司", "internal_symbol": "000002.SZ"},
        ],
    }

    conflict = AgentService._validate_model_output(
        "本轮筛选出 10 只研究候选。", evidence
    )
    aligned = AgentService._validate_model_output("本轮筛选出 2 只研究候选。", evidence)

    assert conflict["passed"] is False
    assert (
        "通用选股候选数量必须与确定性结果一致"
        in (conflict["unsupported_market_inferences"])
    )
    assert aligned["passed"] is True


def test_stock_screen_guard_keeps_provider_named_listed_company():
    evidence = {
        "type": "stock_screen",
        "profile": {"key": "quality", "label": "经营改善候选"},
        "universe": {"matched": 1},
        "items": [
            {
                "name": "东方财富",
                "internal_symbol": "300059.SZ",
                "matched_reasons": ["最新财报营收同比为正"],
            }
        ],
    }

    result = AgentService._validate_model_output(
        "本轮筛选出 1 只研究候选：东方财富（300059.SZ）。",
        evidence,
    )

    assert result["passed"] is True
    assert result["private_operational_patterns"] == []


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
