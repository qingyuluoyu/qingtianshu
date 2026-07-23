from __future__ import annotations

from datetime import date

import pandas as pd
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.industry_comparison import IndustryComparisonService


class FakeIndustryTushareClient:
    def __init__(self) -> None:
        self.codes = ["300750.SZ", *[f"{index:06d}.SZ" for index in range(1, 21)]]

    def query(self, api_name: str, **params):
        if api_name == "index_member_all":
            if params.get("ts_code"):
                return pd.DataFrame([self._member("300750.SZ", 0)])
            return pd.DataFrame(
                [self._member(code, index) for index, code in enumerate(self.codes)]
            )
        if api_name == "trade_cal":
            return pd.DataFrame(
                [{"cal_date": date.today().strftime("%Y%m%d"), "is_open": "1"}]
            )
        if api_name == "daily_basic":
            if params.get("ts_code"):
                return self._history()
            return pd.DataFrame(
                [
                    {
                        "ts_code": code,
                        "trade_date": params.get("trade_date"),
                        "pe_ttm": 15.0 + index,
                        "pb": 1.2 + index * 0.08,
                        "ps_ttm": 2.0 + index * 0.05,
                        "total_mv": 10_000_000 + index * 500_000,
                    }
                    for index, code in enumerate(self.codes)
                ]
            )
        if api_name.endswith("_vip"):
            period = str(params["period"])
            if period == _current_quarter_end():
                return pd.DataFrame()
            if api_name == "fina_indicator_vip":
                return pd.DataFrame(
                    [
                        self._fina(code, index, period)
                        for index, code in enumerate(self.codes)
                    ]
                )
            if api_name == "income_vip":
                return pd.DataFrame(
                    [
                        self._income(code, index, period)
                        for index, code in enumerate(self.codes)
                    ]
                )
            if api_name == "balancesheet_vip":
                return pd.DataFrame(
                    [
                        self._balance(code, index, period)
                        for index, code in enumerate(self.codes)
                    ]
                )
            if api_name == "cashflow_vip":
                return pd.DataFrame(
                    [
                        self._cashflow(code, index, period)
                        for index, code in enumerate(self.codes)
                    ]
                )
        raise AssertionError(f"unexpected query: {api_name} {params}")

    @staticmethod
    def _member(code: str, index: int) -> dict:
        return {
            "l1_code": "801730.SI",
            "l1_name": "电力设备",
            "l2_code": "801737.SI",
            "l2_name": "电池",
            "l3_code": "850000.SI",
            "l3_name": "锂电池",
            "ts_code": code,
            "name": "宁德时代" if code == "300750.SZ" else f"同行{index}",
            "in_date": "20100101",
            "out_date": None,
            "is_new": "Y",
        }

    @staticmethod
    def _period_fraction(period: str) -> float:
        return {
            "0331": 0.25,
            "0630": 0.50,
            "0930": 0.75,
            "1231": 1.00,
        }[period[4:8]]

    def _revenue(self, index: int, period: str) -> float:
        year = int(period[:4])
        annual = (1_000_000_000 + index * 20_000_000) * (
            1.10 + index * 0.001
        ) ** (year - 2022)
        return annual * self._period_fraction(period)

    def _fina(self, code: str, index: int, period: str) -> dict:
        return {
            "ts_code": code,
            "ann_date": period,
            "end_date": period,
            "update_flag": "1",
            "profit_dedt": self._revenue(index, period) * (0.075 + index * 0.0005),
            "q_sales_yoy": 8.0 + index * 0.35 + (2.0 if period.endswith("0331") else 0),
            "roe": 8.0 + index * 0.3,
            "roic": 7.0 + index * 0.25,
            "current_ratio": 1.1 + index * 0.03,
            "quick_ratio": 0.9 + index * 0.025,
            "debt_to_assets": 62.0 - index * 1.1,
            "assets_turn": 0.5 + index * 0.015,
        }

    def _income(self, code: str, index: int, period: str) -> dict:
        revenue = self._revenue(index, period)
        return {
            "ts_code": code,
            "ann_date": period,
            "end_date": period,
            "report_type": "1",
            "update_flag": "1",
            "revenue": revenue,
            "oper_cost": revenue * (0.72 - index * 0.002),
            "operate_profit": revenue * (0.14 + index * 0.001),
            "total_profit": revenue * (0.13 + index * 0.001),
            "income_tax": revenue * 0.02,
            "n_income_attr_p": revenue * (0.10 + index * 0.001),
            "fin_exp_int_exp": revenue * 0.005,
        }

    def _balance(self, code: str, index: int, period: str) -> dict:
        year_growth = 1 + (int(period[:4]) - 2022) * 0.08
        assets = (1_800_000_000 + index * 35_000_000) * year_growth
        liabilities = assets * (0.62 - index * 0.01)
        current_liabilities = liabilities * 0.55
        return {
            "ts_code": code,
            "ann_date": period,
            "end_date": period,
            "report_type": "1",
            "update_flag": "1",
            "money_cap": assets * (0.18 + index * 0.002),
            "accounts_receiv": assets * (0.08 - index * 0.001),
            "inventories": assets * (0.12 - index * 0.0015),
            "total_cur_assets": assets * 0.55,
            "total_assets": assets,
            "st_borr": assets * (0.08 - index * 0.001),
            "st_bonds_payable": 0.0,
            "non_cur_liab_due_1y": assets * 0.01,
            "total_cur_liab": current_liabilities,
            "bond_payable": assets * 0.03,
            "lt_borr": assets * (0.07 - index * 0.001),
            "lease_liab": assets * 0.01,
            "total_liab": liabilities,
            "total_hldr_eqy_exc_min_int": assets - liabilities,
        }

    def _cashflow(self, code: str, index: int, period: str) -> dict:
        revenue = self._revenue(index, period)
        return {
            "ts_code": code,
            "ann_date": period,
            "end_date": period,
            "report_type": "1",
            "update_flag": "1",
            "c_fr_sale_sg": revenue * (0.92 + index * 0.004),
            "n_cashflow_act": revenue * (0.085 + index * 0.001),
            "c_pay_acq_const_fiolta": revenue * 0.025,
        }

    @staticmethod
    def _history() -> pd.DataFrame:
        dates = pd.bdate_range(end=date.today(), periods=600)
        return pd.DataFrame(
            [
                {
                    "ts_code": "300750.SZ",
                    "trade_date": item.strftime("%Y%m%d"),
                    "pe_ttm": 12.0 + index % 24,
                    "pb": 1.0 + (index % 20) * 0.1,
                    "ps_ttm": 1.5 + (index % 16) * 0.08,
                    "total_mv": 10_000_000,
                }
                for index, item in enumerate(dates)
            ]
        )


class MissingLatestCashflowClient(FakeIndustryTushareClient):
    def __init__(self) -> None:
        super().__init__()
        current = pd.Period(_current_quarter_end(), freq="Q")
        self.incomplete_period = (current - 1).end_time.strftime("%Y%m%d")

    def query(self, api_name: str, **params):
        frame = super().query(api_name, **params)
        if (
            api_name == "cashflow_vip"
            and str(params.get("period")) == self.incomplete_period
            and not frame.empty
        ):
            return frame[frame["ts_code"] != "300750.SZ"].reset_index(drop=True)
        return frame


def _current_quarter_end() -> str:
    today = date.today()
    month = ((today.month - 1) // 3 + 1) * 3
    if month == 3:
        day = 31
    elif month in {6, 9}:
        day = 30
    else:
        day = 31
    candidate = date(today.year, month, day)
    if candidate <= today:
        return candidate.strftime("%Y%m%d")
    previous_month = month - 3
    previous_year = today.year
    if previous_month == 0:
        previous_month = 12
        previous_year -= 1
    previous_day = 31 if previous_month in {3, 12} else 30
    return date(previous_year, previous_month, previous_day).strftime("%Y%m%d")


def test_five_factor_packet_uses_sw2_and_v1_formula_policy():
    packet = IndustryComparisonService(FakeIndustryTushareClient()).get_packet(
        "300750.SZ"
    )

    assert packet["status"] == "available"
    assert packet["industry"]["code"] == "801737.SI"
    assert packet["industry"]["name"] == "电池"
    assert packet["coverage"]["industryMembers"] == 21
    assert packet["formulaPolicy"]["minimumOperatingCashRatio"] == 0.05
    assert packet["formulaPolicy"]["leaseLiabilityIncluded"] is True
    assert [factor["key"] for factor in packet["factors"]] == [
        "growth",
        "valuation",
        "profitability",
        "stability",
        "efficiency",
    ]
    assert all(factor["score"] is not None for factor in packet["factors"])
    stability = next(
        factor for factor in packet["factors"] if factor["key"] == "stability"
    )
    assert stability["coveragePct"] == 85.0
    volatility = next(
        metric
        for metric in stability["metrics"]
        if metric["key"] == "earnings_volatility"
    )
    assert volatility["status"] == "subject_missing"
    assert packet["radar"]["industryMedian"] == [50.0] * 5
    comparison = packet["topMetricComparison"]
    assert comparison["industryCode"] == "801737.SI"
    assert [item["key"] for item in comparison["series"]] == [
        "peTtm",
        "pbLf",
        "roeWeightedReport",
        "revenueYoy",
        "parentNetProfitYoy",
    ]
    assert all(item["status"] == "available" for item in comparison["series"])
    assert all(item["sampleSize"] == 21 for item in comparison["series"])
    assert all(item["industryMedian"] is not None for item in comparison["series"])


def test_anchor_rolls_back_when_latest_cashflow_cannot_support_ttm():
    source = MissingLatestCashflowClient()
    packet = IndustryComparisonService(source).get_packet("300750.SZ")

    assert packet["reportPeriod"].replace("-", "") != source.incomplete_period
    assert all(factor["score"] is not None for factor in packet["factors"])
    assert any("自动回退" in warning for warning in packet["warnings"])


def test_industry_comparison_route_returns_real_contract(settings):
    app = create_app(
        settings=settings,
        tushare_client=FakeIndustryTushareClient(),
    )
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/stocks/300750.SZ/industry-comparison"
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["method"] == "sw2_five_factor_comparison_v1"
    assert payload["formulaVersion"] == "financial_factor_v1.0"
    assert payload["coverage"]["availableFactors"] == 5
