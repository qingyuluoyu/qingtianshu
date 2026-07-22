from __future__ import annotations

from collections import defaultdict

import pandas as pd

from app.providers.tushare import TushareClient
from app.services.tushare_snapshots import TushareSnapshotService


class FakeSnapshotTushareClient:
    def __init__(self) -> None:
        self.calls: dict[str, int] = defaultdict(int)
        self.missing: set[str] = set()
        self.fail_trade_cal = False
        self.empty_daily_basic_dates: set[str] = set()
        self.trade_dates = [
            value.strftime("%Y%m%d")
            for value in pd.bdate_range(end="2026-07-21", periods=620)
        ]
        self.stock_basic_rows = [
            {
                "ts_code": "000063.SZ",
                "symbol": "000063",
                "name": "中兴通讯",
                "area": "深圳",
                "industry": "通信设备",
                "market": "主板",
                "list_date": "19971118",
                "exchange": "SZSE",
                "list_status": "L",
            }
        ]
        self.daily_basic_rows = [
            {
                "ts_code": "000063.SZ",
                "trade_date": self.trade_dates[-1],
                "turnover_rate": 2.5,
                "volume_ratio": 1.2,
                "pe_ttm": 35.0,
                "pb": 2.2,
                "total_mv": 1_800_000,
                "circ_mv": 1_500_000,
            }
        ]

    @staticmethod
    def to_tushare_symbol(symbol: str) -> str:
        return symbol[:-3] + ".SH" if symbol.endswith(".SS") else symbol

    def query(self, api_name: str, **params):
        self.calls[api_name] += 1
        if api_name in self.missing:
            return pd.DataFrame()
        if api_name == "trade_cal":
            if self.fail_trade_cal:
                raise RuntimeError("temporary calendar error")
            return pd.DataFrame(
                {"cal_date": self.trade_dates, "is_open": [1] * len(self.trade_dates)}
            )
        if api_name == "stock_basic":
            return pd.DataFrame(self.stock_basic_rows)
        if api_name == "daily":
            start_date = str(params.get("start_date") or self.trade_dates[0])
            end_date = str(params.get("end_date") or self.trade_dates[-1])
            dates = [
                value
                for value in self.trade_dates
                if start_date <= value <= end_date
            ]
            return pd.DataFrame(
                [
                    {
                        "ts_code": "000063.SZ",
                        "trade_date": trade_date,
                        "open": 30 + index * 0.02,
                        "high": 30.8 + index * 0.02,
                        "low": 29.5 + index * 0.02,
                        "close": 30.4 + index * 0.02,
                        "pre_close": 30.0 + index * 0.02,
                        "change": 0.4,
                        "pct_chg": 1.33,
                        "vol": 1_000_000 + index * 1000,
                        "amount": 50_000 + index * 100,
                    }
                    for index, trade_date in enumerate(dates)
                ]
            )
        if api_name == "daily_basic":
            requested_date = str(
                params.get("trade_date")
                or params.get("start_date")
                or self.trade_dates[-1]
            )
            if requested_date in self.empty_daily_basic_dates:
                return pd.DataFrame()
            rows = []
            for item in self.daily_basic_rows:
                row = dict(item)
                row["trade_date"] = requested_date
                rows.append(row)
            return pd.DataFrame(rows)
        if api_name == "fina_indicator":
            return pd.DataFrame(
                [
                    {
                        "ts_code": "000063.SZ",
                        "ann_date": f"{year + 1}0429",
                        "end_date": f"{year}1231",
                        "roe": 10.0 + (year % 3),
                        "roe_waa": 10.0 + (year % 3),
                        "update_flag": "1",
                    }
                    for year in range(2021, 2026)
                ]
            )
        if api_name == "adj_factor":
            start_date = str(params.get("start_date") or self.trade_dates[0])
            end_date = str(params.get("end_date") or self.trade_dates[-1])
            return pd.DataFrame(
                [
                    {
                        "ts_code": "000063.SZ",
                        "trade_date": trade_date,
                        "adj_factor": 1.0,
                    }
                    for trade_date in self.trade_dates
                    if start_date <= trade_date <= end_date
                ]
            )
        if api_name == "stk_limit":
            start_date = str(params.get("start_date") or self.trade_dates[0])
            end_date = str(params.get("end_date") or self.trade_dates[-1])
            return pd.DataFrame(
                [
                    {
                        "ts_code": "000063.SZ",
                        "trade_date": trade_date,
                        "pre_close": 30.0,
                        "up_limit": 33.0,
                        "down_limit": 27.0,
                    }
                    for trade_date in self.trade_dates
                    if start_date <= trade_date <= end_date
                ]
            )
        if api_name in {"top10_holders", "top10_floatholders"}:
            return pd.DataFrame(
                [
                    {
                        "ts_code": "000063.SZ",
                        "ann_date": "20260429",
                        "end_date": "20260331",
                        "holder_name": f"测试机构{index}",
                        "hold_amount": 1_000_000 - index * 10_000,
                        "hold_ratio": 5.0 - index * 0.2,
                    }
                    for index in range(1, 7)
                ]
            )
        if api_name in {"income", "balancesheet", "cashflow"}:
            return pd.DataFrame(
                [
                    {
                        "ts_code": "000063.SZ",
                        "ann_date": "20260429",
                        "f_ann_date": "20260429",
                        "end_date": "20251231",
                        "total_revenue": 120_000_000_000,
                        "n_income_attr_p": 8_000_000_000,
                        "total_assets": 220_000_000_000,
                        "total_liab": 140_000_000_000,
                        "n_cashflow_act": 10_000_000_000,
                    }
                ]
            )
        if api_name in {"forecast", "express"}:
            return pd.DataFrame(
                [
                    {
                        "ts_code": "000063.SZ",
                        "ann_date": "20260415",
                        "end_date": "20260331",
                        "type": "预增",
                        "summary": "测试业绩信息",
                    }
                ]
            )
        if api_name == "disclosure_date":
            return pd.DataFrame(
                [
                    {
                        "ts_code": "000063.SZ",
                        "ann_date": "20260401",
                        "end_date": "20260331",
                        "pre_date": "20260429",
                        "actual_date": "20260428",
                        "modify_date": None,
                    }
                ]
            )
        raise AssertionError(f"unexpected dataset: {api_name}")


def test_tushare_client_exposes_li_zong_and_financial_dataset_wrappers():
    client = object.__new__(TushareClient)
    captured = []

    def fake_query(api_name: str, **params):
        captured.append((api_name, params))
        return pd.DataFrame()

    client.query = fake_query  # type: ignore[method-assign]
    client.adj_factor(ts_code="600519.SS", start_date="20260101")
    client.stk_limit(ts_code="600519.SS", trade_date="20260721")
    client.top10_holders(ts_code="600519.SS", period="20260331")
    client.top10_floatholders(ts_code="600519.SS", period="20260331")
    client.income(ts_code="600519.SS", period="20260331")
    client.balancesheet(ts_code="600519.SS", period="20260331")
    client.cashflow(ts_code="600519.SS", period="20260331")
    client.forecast(ts_code="600519.SS", period="20260331")
    client.express(ts_code="600519.SS", period="20260331")
    client.disclosure_date(ts_code="600519.SS", end_date="20261231")
    client.index_daily(ts_code="000300.SS", start_date="20260101")

    assert [name for name, _ in captured] == [
        "adj_factor",
        "stk_limit",
        "top10_holders",
        "top10_floatholders",
        "income",
        "balancesheet",
        "cashflow",
        "forecast",
        "express",
        "disclosure_date",
        "index_daily",
    ]
    assert all(params["ts_code"].endswith((".SH", ".SZ")) for _, params in captured)


def test_a_share_universe_publishes_traceable_stable_snapshot(app):
    fake = FakeSnapshotTushareClient()
    fake.stock_basic_rows = [
        {
            "ts_code": "600519.SH",
            "symbol": "600519",
            "name": "贵州茅台",
            "industry": "白酒",
            "market": "主板",
            "list_date": "20010827",
            "exchange": "SSE",
            "list_status": "L",
        },
        {
            "ts_code": "000063.SZ",
            "symbol": "000063",
            "name": "中兴通讯",
            "industry": "通信设备",
            "market": "主板",
            "list_date": "19971118",
            "exchange": "SZSE",
            "list_status": "L",
        },
        {
            "ts_code": "830799.BJ",
            "symbol": "830799",
            "name": "艾融软件",
            "industry": "软件服务",
            "market": "北交所",
            "list_date": "20200727",
            "exchange": "BSE",
            "list_status": "L",
        },
    ]
    fake.daily_basic_rows = [
        {
            "ts_code": "600519.SH",
            "trade_date": fake.trade_dates[-1],
            "total_mv": 20_000_000,
            "circ_mv": 20_000_000,
        },
        {
            "ts_code": "000063.SZ",
            "trade_date": fake.trade_dates[-1],
            "total_mv": 1_800_000,
            "circ_mv": 1_500_000,
        },
        {
            "ts_code": "830799.BJ",
            "trade_date": fake.trade_dates[-1],
            "total_mv": 120_000,
            "circ_mv": 100_000,
        },
    ]
    service = TushareSnapshotService(app.state.database, fake)

    first = service.sync_a_share_universe(as_of_date="2026-07-21")
    second = service.sync_a_share_universe(as_of_date="2026-07-21")
    published = service.get_a_share_universe()

    assert first["published"] is True
    assert first["reused"] is False
    assert second["reused"] is True
    assert first["run"]["status"] == "stable"
    assert first["run"]["data_version"] == second["run"]["data_version"]
    assert fake.calls["trade_cal"] == 1
    assert fake.calls["stock_basic"] == 1
    assert fake.calls["daily_basic"] == 1
    assert published["status"] == "stable"
    assert published["snapshot"]["coverage"] == {
        "listed": 3,
        "with_market_cap": 3,
        "missing_market_cap": 0,
        "market_cap_coverage_ratio": 1.0,
    }
    items = {item["ts_code"]: item for item in published["snapshot"]["items"]}
    assert items["600519.SH"]["symbol"] == "600519.SS"
    assert items["830799.BJ"]["symbol"] == "830799.BJ"
    assert items["000063.SZ"]["total_mv_yi"] == 180.0
    assert items["830799.BJ"]["circ_mv_yi"] == 10.0


def test_incomplete_universe_refresh_retains_previous_stable_snapshot(app):
    fake = FakeSnapshotTushareClient()
    fake.stock_basic_rows = [
        {
            "ts_code": code,
            "symbol": code[:6],
            "name": name,
            "industry": "测试行业",
            "market": "主板",
            "list_date": "20200101",
            "exchange": "SSE" if code.endswith(".SH") else "SZSE",
            "list_status": "L",
        }
        for code, name in (
            ("600519.SH", "贵州茅台"),
            ("000063.SZ", "中兴通讯"),
            ("300308.SZ", "中际旭创"),
        )
    ]
    fake.daily_basic_rows = [
        {
            "ts_code": item["ts_code"],
            "trade_date": fake.trade_dates[-1],
            "total_mv": 1_800_000,
            "circ_mv": 1_500_000,
        }
        for item in fake.stock_basic_rows
    ]
    service = TushareSnapshotService(app.state.database, fake)
    stable = service.sync_a_share_universe(as_of_date="2026-07-21")

    fake.daily_basic_rows = fake.daily_basic_rows[:1]
    incomplete = service.sync_a_share_universe(
        as_of_date="2026-07-21", force=True
    )
    published = service.get_a_share_universe()

    assert stable["published"] is True
    assert incomplete["published"] is False
    assert incomplete["run"]["status"] == "partial"
    assert incomplete["previous_stable_retained"] is True
    assert published["status"] == "stable"
    assert published["data_version"] == stable["run"]["data_version"]
    assert published["snapshot"]["coverage"]["market_cap_coverage_ratio"] == 1.0
    assert published["latest_incomplete"]["coverage"] == {
        "listed": 3,
        "with_market_cap": 1,
        "missing_market_cap": 2,
        "market_cap_coverage_ratio": 0.333333,
    }


def test_preopen_sync_falls_back_to_latest_date_with_daily_basic_data(app):
    fake = FakeSnapshotTushareClient()
    latest_calendar_date = fake.trade_dates[-1]
    previous_completed_date = fake.trade_dates[-2]
    fake.empty_daily_basic_dates.add(latest_calendar_date)
    service = TushareSnapshotService(app.state.database, fake)

    universe = service.sync_a_share_universe(as_of_date="2026-07-21")
    symbol = service.sync_symbol("000063", as_of_date="2026-07-21")

    assert universe["published"] is True
    assert universe["snapshot"]["as_of_date"] == service._iso_date(
        previous_completed_date
    )
    assert symbol["published"] is True
    assert symbol["snapshot"]["as_of_date"] == service._iso_date(
        previous_completed_date
    )
    assert symbol["snapshot"]["datasets"]["daily"]["rows"][-1][
        "trade_date"
    ] == previous_completed_date
    assert fake.calls["daily_basic"] == 4


def test_symbol_snapshot_publishes_traceable_stable_version(app):
    fake = FakeSnapshotTushareClient()
    service = TushareSnapshotService(app.state.database, fake)

    result = service.sync_symbol("000063", as_of_date="2026-07-21")

    assert result["published"] is True
    assert result["run"]["status"] == "stable"
    snapshot = result["snapshot"]
    assert snapshot["symbol"] == "000063.SZ"
    assert snapshot["as_of_date"] == "2026-07-21"
    assert snapshot["coverage"] == {
        "required": 9,
        "available": 9,
        "missing": [],
        "optional": 6,
        "optional_available": 6,
        "optional_missing": [],
    }
    assert snapshot["datasets"]["daily"]["row_count"] == 620
    assert snapshot["datasets"]["fina_indicator"]["report_period"] == "2025-12-31"
    assert snapshot["datasets"]["stk_limit"]["source"] == "Tushare Pro"
    assert snapshot["datasets"]["income"]["report_period"] == "2025-12-31"
    stored = service.get_symbol_snapshot("000063")
    assert stored["status"] == "stable"
    assert stored["data_version"] == result["run"]["data_version"]
    assert stored["snapshot"]["datasets"]["daily_basic"]["rows"][0][
        "trade_date"
    ] == "20260721"


def test_same_snapshot_content_keeps_same_data_version(app):
    fake = FakeSnapshotTushareClient()
    service = TushareSnapshotService(app.state.database, fake)

    first = service.sync_symbol("000063", as_of_date="2026-07-21")
    second = service.sync_symbol("000063", as_of_date="2026-07-21")

    assert first["run"]["data_version"] == second["run"]["data_version"]
    assert service.get_symbol_snapshot("000063")["data_version"] == first["run"][
        "data_version"
    ]


def test_incomplete_or_failed_sync_never_overwrites_previous_stable_snapshot(app):
    fake = FakeSnapshotTushareClient()
    service = TushareSnapshotService(app.state.database, fake)
    stable = service.sync_symbol("000063", as_of_date="2026-07-21")
    stable_version = stable["run"]["data_version"]

    fake.missing.add("top10_floatholders")
    partial = service.sync_symbol("000063", as_of_date="2026-07-21")
    assert partial["published"] is False
    assert partial["run"]["status"] == "partial"
    assert partial["previous_stable_retained"] is True
    assert partial["snapshot"]["coverage"]["missing"] == ["top10_floatholders"]
    assert service.get_symbol_snapshot("000063")["data_version"] == stable_version

    fake.fail_trade_cal = True
    failed = service.sync_symbol("000063", as_of_date="2026-07-21")
    assert failed["published"] is False
    assert failed["run"]["status"] == "failed"
    assert failed["previous_stable_retained"] is True
    assert service.get_symbol_snapshot("000063")["data_version"] == stable_version
