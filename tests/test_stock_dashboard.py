from __future__ import annotations

import pandas as pd

from app.db import Database
from app.services.stock_dashboard import StockDashboardService


class FakeTushareClient:
    def stock_basic(self, **params):
        assert "ts_code" in params["fields"]
        return pd.DataFrame(
            [
                {
                    "ts_code": "300750.SZ",
                    "symbol": "300750",
                    "name": "宁德时代",
                    "area": "深圳",
                    "industry": "电气设备",
                    "market": "创业板",
                    "list_date": "20180611",
                    "exchange": "SZSE",
                    "cnspell": "ndsd",
                },
                {
                    "ts_code": "600519.SH",
                    "symbol": "600519",
                    "name": "贵州茅台",
                    "area": "贵州",
                    "industry": "白酒",
                    "market": "主板",
                    "list_date": "20010827",
                    "exchange": "SSE",
                    "cnspell": "gzmt",
                },
                {
                    "ts_code": "830799.BJ",
                    "symbol": "830799",
                    "name": "艾融软件",
                    "area": "上海",
                    "industry": "软件服务",
                    "market": "北交所",
                    "list_date": "20200727",
                    "exchange": "BSE",
                    "cnspell": "arrj",
                },
                {
                    "ts_code": "900901.SH",
                    "symbol": "900901",
                    "name": "云赛B股",
                    "area": "上海",
                    "industry": "软件服务",
                    "market": "主板",
                    "list_date": "19931231",
                    "exchange": "SSE",
                    "cnspell": "ysbg",
                },
            ]
        )


class FakeMarketProvider:
    def read_cached_history(
        self, symbol, range_name="1y", interval="1d", **_kwargs
    ):
        return self.fetch_history(symbol, range_name, interval)

    def fetch_history(self, symbol, range_name="1y", interval="1d"):
        assert symbol in {"300750.SZ", "600519.SS", "830799.BJ"}
        if interval == "1m":
            return {
                "symbol": symbol,
                "previous_close": 100.0,
                "source": "Fake minute",
                "market_timestamp": "2026-07-23T01:32:00+00:00",
                "fetched_at": "2026-07-23T01:33:00+00:00",
                "points": [
                    {
                        "timestamp": "2026-07-23T01:30:00+00:00",
                        "open": 100.0,
                        "high": 102.0,
                        "low": 99.0,
                        "close": 101.0,
                        "adjusted_close": None,
                        "volume": 1000,
                    },
                    {
                        "timestamp": "2026-07-23T01:32:00+00:00",
                        "open": 101.0,
                        "high": 104.0,
                        "low": 100.0,
                        "close": 103.0,
                        "adjusted_close": None,
                        "volume": 2000,
                    },
                ],
            }
        return {
            "symbol": symbol,
            "source": "Fake daily",
            "fetched_at": "2026-07-23T01:33:00+00:00",
            "warnings": [],
            "points": [
                {
                    "timestamp": "2026-01-05T01:30:00+00:00",
                    "open": 10.0,
                    "high": 12.0,
                    "low": 9.0,
                    "close": 11.0,
                    "adjusted_close": 5.5,
                    "volume": 100,
                },
                {
                    "timestamp": "2026-01-09T01:30:00+00:00",
                    "open": 11.0,
                    "high": 13.0,
                    "low": 10.0,
                    "close": 12.0,
                    "adjusted_close": 6.0,
                    "volume": 200,
                },
                {
                    "timestamp": "2026-01-12T01:30:00+00:00",
                    "open": 12.0,
                    "high": 14.0,
                    "low": 11.0,
                    "close": 13.0,
                    "adjusted_close": 6.5,
                    "volume": 300,
                },
            ],
        }


class FakeFundamentals:
    def get_packet(self, symbol):
        return {
            "valuation": {
                "name": "宁德时代",
                "price": 103.0,
                "previous_close": 100.0,
                "pct_change": 3.0,
                "turnover_rate_pct": 1.2,
                "pe_ttm": 22.27,
                "pb": 5.38,
                "total_market_cap": 1_580_000_000_000,
                "market_timestamp": "2026-07-23T09:32:00+08:00",
                "source": "Tencent",
            },
            "financial_periods": [
                {
                    "report_date": "2026-03-31",
                    "report_date_name": "2026一季报",
                    "period_basis": "year_to_date_cumulative",
                    "roe_weighted_pct": 5.98,
                    "revenue_yoy_pct": 52.45,
                    "net_profit_yoy_pct": 48.52,
                    "source": "Eastmoney F10",
                }
            ],
            "warnings": [],
        }


def make_service():
    return StockDashboardService(
        market_provider=FakeMarketProvider(),
        fundamentals_service=FakeFundamentals(),
        tushare_client=FakeTushareClient(),
    )


def test_search_supports_name_code_spelling_and_filters_b_shares():
    service = make_service()

    assert service.search("宁德")[0]["symbol"] == "300750.SZ"
    assert service.search("600519")[0]["name"] == "贵州茅台"
    assert service.search("gzmt")[0]["symbol"] == "600519.SH"
    assert service.search("艾融")[0]["symbol"] == "830799.BJ"
    assert service.search("云赛B股") == []


def test_profile_exposes_industry_and_board_from_stock_catalog():
    profile = make_service().profile("300750")

    assert profile["industry"] == "电气设备"
    assert profile["market"] == "创业板"


def test_stock_catalog_survives_service_restart(tmp_path):
    database = Database(tmp_path / "app.db", tmp_path / "workspaces")
    database.initialize()

    class PersistentMarket(FakeMarketProvider):
        def __init__(self):
            self.database = database

    class CountingTushare(FakeTushareClient):
        calls = 0

        def stock_basic(self, **params):
            self.calls += 1
            return super().stock_basic(**params)

    tushare = CountingTushare()
    first = StockDashboardService(
        market_provider=PersistentMarket(),
        fundamentals_service=FakeFundamentals(),
        tushare_client=tushare,
    )
    second = StockDashboardService(
        market_provider=PersistentMarket(),
        fundamentals_service=FakeFundamentals(),
        tushare_client=tushare,
    )

    assert first.search("300750")
    assert second.search("300750")
    assert tushare.calls == 1


def test_score_card_uses_real_contract_without_claiming_ttm_roe():
    packet = make_service().score_card("300750")

    assert packet["identity"]["market"] == "创业板"
    assert packet["quote"]["price"] == 103.0
    assert packet["quote"]["volumeShares"] == 3000
    assert packet["quote"]["amountCny"] == 307000.0
    assert packet["metrics"]["peTtm"] == 22.27
    assert packet["metrics"]["pbLf"] == 5.38
    assert packet["metrics"]["roeWeightedReport"] == 5.98
    assert packet["metrics"]["roeTtmAvailable"] is False
    assert packet["metrics"]["parentNetProfitYoy"] == 48.52
    assert packet["dataStatus"]["quote"] == "available"
    assert packet["dataStatus"]["financials"] == "available"
    assert packet["officialSearch"]["cninfoQuery"] == "宁德时代"


def test_score_card_cached_only_does_not_call_remote_market_provider():
    class CachedOnlyMarketProvider(FakeMarketProvider):
        calls = 0

        def fetch_history(self, *_args, **_kwargs):
            self.calls += 1
            raise AssertionError("score-card performed a synchronous remote request")

        def read_cached_history(self, symbol, range_name, interval, **_kwargs):
            assert (symbol, range_name, interval) == ("300750.SZ", "1d", "1m")
            return super().fetch_history(symbol, range_name, interval)

    provider = CachedOnlyMarketProvider()
    service = StockDashboardService(
        market_provider=provider,
        fundamentals_service=FakeFundamentals(),
        tushare_client=FakeTushareClient(),
    )

    packet = service.score_card("300750.SZ", allow_remote=False)

    assert provider.calls == 0
    assert packet["quote"]["price"] == 103.0
    assert packet["cache"]["state"] == "fresh"


def test_score_card_cached_only_prefers_cached_fundamentals_reader():
    class CachedFundamentals(FakeFundamentals):
        remote_calls = 0
        cached_calls = 0

        def get_packet(self, symbol):
            self.remote_calls += 1
            return super().get_packet(symbol)

        def get_cached_packet(self, symbol):
            self.cached_calls += 1
            return super().get_packet(symbol)

    fundamentals = CachedFundamentals()
    service = StockDashboardService(
        market_provider=FakeMarketProvider(),
        fundamentals_service=fundamentals,
        tushare_client=FakeTushareClient(),
    )

    service.score_card("300750.SZ", allow_remote=False)

    assert fundamentals.cached_calls == 1
    assert fundamentals.remote_calls == 0


def test_kline_uses_real_points_and_aggregates_weekly():
    service = make_service()

    daily = service.kline("300750.SZ", period="1d", limit=10)
    weekly = service.kline("300750.SZ", period="1w", limit=10)
    intraday = service.kline("300750.SZ", period="1m", limit=10)

    assert daily["data"][0]["close"] == 5.5
    assert weekly["data"] == [
        {
            "time": "2026-01-09T01:30:00+00:00",
            "open": 5.0,
            "high": 6.5,
            "low": 4.5,
            "close": 6.0,
            "volume": 300,
        },
        {
            "time": "2026-01-12T01:30:00+00:00",
            "open": 6.0,
            "high": 7.0,
            "low": 5.5,
            "close": 6.5,
            "volume": 300,
        },
    ]
    assert intraday["adjustment"] == "不复权"
    assert intraday["data"][-1]["close"] == 103.0


def test_kline_cached_only_does_not_call_remote_market_provider():
    class CachedDailyProvider(FakeMarketProvider):
        calls = 0

        def fetch_history(self, *_args, **_kwargs):
            self.calls += 1
            raise AssertionError("K-line performed a synchronous remote request")

        def read_cached_history(self, symbol, range_name, interval, **_kwargs):
            return super().fetch_history(symbol, range_name, interval)

    provider = CachedDailyProvider()
    service = StockDashboardService(
        market_provider=provider,
        fundamentals_service=FakeFundamentals(),
        tushare_client=FakeTushareClient(),
    )

    packet = service.kline(
        "300750.SZ", period="1d", limit=10, allow_remote=False
    )

    assert provider.calls == 0
    assert packet["data"][-1]["close"] == 6.5
    assert packet["cache"]["state"] == "fresh"


def test_kline_reuses_short_server_cache():
    class CountingMarketProvider(FakeMarketProvider):
        def __init__(self):
            self.calls = 0

        def fetch_history(self, symbol, range_name="1y", interval="1d"):
            self.calls += 1
            return super().fetch_history(symbol, range_name, interval)

    provider = CountingMarketProvider()
    service = StockDashboardService(
        market_provider=provider,
        fundamentals_service=FakeFundamentals(),
        tushare_client=FakeTushareClient(),
    )

    first = service.kline("300750.SZ", period="1d", limit=80)
    second = service.kline("300750.SZ", period="1d", limit=80)

    assert provider.calls == 1
    assert first["cache"]["state"] == "fresh"
    assert second["cache"]["state"] == "hit"
    assert second["data"] == first["data"]


def test_high_fidelity_stock_routes_are_available(client):
    search = client.get("/api/v1/stocks/search", params={"q": "宁德时代"})
    score = client.get("/api/v1/stocks/300750.SZ/score-card")
    kline = client.get(
        "/api/v1/market/kline",
        params={"symbol": "300750.SZ", "period": "1w", "limit": 20},
    )

    assert search.status_code == 200
    assert search.json()["items"][0]["symbol"] == "300750.SZ"
    assert score.status_code == 200
    assert score.json()["metrics"]["roeTtmAvailable"] is False
    assert kline.status_code == 200
    assert kline.json()["period"] == "1w"
    assert kline.json()["data"]


def test_new_demo_wires_real_stock_data_without_kline_demo_fallback(client):
    page = client.get("/new-demo")
    primary_page = client.get("/demo")

    assert page.status_code == 200
    assert primary_page.status_code == 200
    assert primary_page.text == page.text
    page_js = client.get("/static/high-fidelity-demo.js")
    assert page_js.status_code == 200
    page_css = client.get("/static/high-fidelity-demo.css")
    assert page_css.status_code == 200
    frontend_text = page.text + page_js.text
    assert "window.QSStockConfig" in frontend_text
    assert "/api/v1/stocks/search" in frontend_text
    assert "/api/v1/stocks/{symbol}/score-card" in frontend_text
    assert "/api/v1/stocks/{symbol}/industry-comparison" in frontend_text
    assert 'id="industryFactorRadar"' in frontend_text
    assert 'id="industryMetricRows"' not in frontend_text
    assert 'id="topMetricComparisonChart"' in frontend_text
    assert "真实数据口径" not in frontend_text
    assert "行业上四分位" in frontend_text
    assert "申万二级同行相对排名" in frontend_text
    assert "行业历史分位与同行估值对比" not in frontend_text
    assert "makeDemoKlines" not in frontend_text
    assert "接口暂不可用，已显示演示数据" not in frontend_text
    assert 'data-kline-zoom="in"' in frontend_text
    assert "visibleKlineRows" in frontend_text
    assert "正在并行加载" in frontend_text
    assert "loadStock(initialStockSymbol,{force:true})" not in frontend_text
    assert "TUSHARE_TOKEN" not in frontend_text
    assert 'id="watchSearchInput"' in frontend_text
    assert 'id="watchAddForm"' in frontend_text
    assert 'id="batchDeleteWatch"' in frontend_text
    assert 'id="addWatch"' not in frontend_text
    assert 'class="star' not in frontend_text
    assert "watch-operate" not in frontend_text
    assert 'data-watch-delete' in frontend_text
    assert "ensureWatchlistSession()" in frontend_text
    assert "watchRequest('/api/v1/me/watchlist')" in frontend_text
    assert "watchRequest('/api/v1/me/watchlist',{method:'POST'" in frontend_text
    assert "watchRequest('/api/v1/me/watchlist/'+encodeURIComponent(symbol),{method:'DELETE'})" in frontend_text
    assert 'id="stockWatchButton"' in frontend_text
    assert 'data-watch-detail-index="' in frontend_text
    assert "saveCurrentStockToWatchlist" in frontend_text
    assert "openWatchStockDetail" in frontend_text
    assert "<h3>数据状态</h3>" not in page.text
    assert "<h3>口径说明</h3>" not in page.text
    assert 'class="score-side"' not in page.text
    assert ".score-layout{display:block}" in page_css.text
    assert "grid-template-columns:repeat(6,minmax(0,1fr))" in page_css.text
    assert ".industry-factor-score:nth-child(4){grid-column:2 / span 2}" in page_css.text
    assert ".industry-factor-score:nth-child(5){grid-column:4 / span 2}" in page_css.text
    assert "focus_status" not in frontend_text
    assert "<th>关注状态</th>" in frontend_text
    assert "<th>研究状态</th>" in frontend_text
    assert "<th>持仓状态</th>" in frontend_text
    assert "<th>下一动作</th>" not in frontend_text
    assert 'id="watchAddPriority"' in frontend_text
    assert 'id="watchAddCatalyst"' in frontend_text
    assert 'id="watchAddInvalidation"' in frontend_text
    assert "legacy_position_hint" in frontend_text
    assert "holding_quantity" not in frontend_text
    assert "dataStatus" in frontend_text
    assert "cninfo.com.cn" in frontend_text
    assert "巨潮资讯检索" in frontend_text
    assert "后台准备中 · 自动补齐" in frontend_text
    assert "className:'xueqiu'" in frontend_text
    assert "className:'lixinger'" in frontend_text
    assert "className:'sina'" in frontend_text
    assert 'id="dimensionList"' in frontend_text
    assert "selectEvidenceDimensions" in frontend_text
    assert "五大分析维度" not in frontend_text
    assert "/api/v1/me/profile-summary" in frontend_text
    assert "loadProfileSummary" in frontend_text
    assert 'id="profileSummaryCards"' in frontend_text
    assert "renderProfileWorkbench" in frontend_text
    assert '<div class="logo" aria-hidden="true"><i></i><i></i><i></i></div>' in frontend_text
    assert "qingshu-app-icon.png" not in frontend_text
    assert "QSPaymentAPI" not in frontend_text
    assert "/me/payment-orders/draft" not in frontend_text
    assert 'style="visibility:hidden"' not in page.text
