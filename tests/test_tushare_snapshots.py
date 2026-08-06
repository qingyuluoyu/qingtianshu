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
        self.trade_dates = [
            value.strftime("%Y%m%d")
            for value in pd.bdate_range(end="2026-07-21", periods=420)
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
            return pd.DataFrame(
                [
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
            )
        if api_name == "daily":
            dates = self.trade_dates[-400:]
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
            return pd.DataFrame(
                [
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
            )
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
            return pd.DataFrame(
                [
                    {
                        "ts_code": "000063.SZ",
                        "trade_date": trade_date,
                        "adj_factor": 1.0,
                    }
                    for trade_date in self.trade_dates[-400:]
                ]
            )
        if api_name == "stk_limit":
            return pd.DataFrame(
                [
                    {
                        "ts_code": "000063.SZ",
                        "trade_date": trade_date,
                        "pre_close": 30.0,
                        "up_limit": 33.0,
                        "down_limit": 27.0,
                    }
                    for trade_date in self.trade_dates[-400:]
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
    assert snapshot["datasets"]["daily"]["row_count"] == 400
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
