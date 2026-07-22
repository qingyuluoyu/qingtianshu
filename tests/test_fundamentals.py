from __future__ import annotations

from pathlib import Path

from app.db import Database
from app.providers.fundamentals import AShareFundamentalsProvider
from app.services.fundamentals import FundamentalsService


class FakeResponse:
    def __init__(self, *, content: bytes | None = None, payload=None):
        self.content = content or b""
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_tencent_valuation_field_mapping_distinguishes_market_caps_and_pe_types():
    fields = [""] * 88
    fields[1] = "测试公司"
    fields[2] = "000333"
    fields[3] = "84.30"
    fields[4] = "82.71"
    fields[30] = "20260720161409"
    fields[32] = "1.92"
    fields[38] = "0.80"
    fields[39] = "14.54"
    fields[44] = "5790.98"
    fields[45] = "6425.91"
    fields[46] = "3.15"
    fields[52] = "12.67"
    fields[53] = "14.62"
    fields[82] = "CNY"
    content = ('v_sz000333="' + "~".join(fields) + '";').encode("gb18030")
    provider = AShareFundamentalsProvider(
        http_get=lambda *args, **kwargs: FakeResponse(content=content)
    )

    result = provider.fetch_valuation("000333")

    assert result["symbol"] == "000333.SZ"
    assert result["pe_ttm"] == 14.54
    assert result["pe_dynamic"] == 12.67
    assert result["pe_static"] == 14.62
    assert result["float_market_cap"] == 579_098_000_000.0
    assert result["total_market_cap"] == 642_591_000_000.0
    assert result["market_timestamp"] == "2026-07-20T16:14:09+08:00"


def test_eastmoney_financial_periods_are_structured_and_persisted(tmp_path: Path):
    payload = {
        "result": {
            "data": [
                {
                    "SECUCODE": "600519.SH",
                    "SECURITY_NAME_ABBR": "贵州茅台",
                    "REPORT_DATE": "2026-03-31 00:00:00",
                    "REPORT_TYPE": "一季报",
                    "REPORT_DATE_NAME": "2026一季报",
                    "NOTICE_DATE": "2026-04-25 00:00:00",
                    "CURRENCY": "CNY",
                    "EPSJB": 21.76,
                    "BPS": 216.32,
                    "TOTALOPERATEREVE": 54_702_912_385.23,
                    "TOTALOPERATEREVETZ": 6.336,
                    "PARENTNETPROFIT": 27_242_512_886.45,
                    "PARENTNETPROFITTZ": 1.471,
                    "ROEJQ": 10.57,
                    "XSMLL": 89.759,
                    "XSJLL": 52.224,
                    "ZCFZL": 12.123,
                    "NETCASH_OPERATE_PK": 26_909_891_269.13,
                    "MGJYXJJE": 21.489,
                    "TOTAL_ASSETS_PK": 319_918_844_905.58,
                    "TOTAL_EQUITY_PK": 281_135_886_435.69,
                }
            ]
        }
    }

    def http_get(url, **kwargs):
        return FakeResponse(payload=payload)

    provider = AShareFundamentalsProvider(http_get=http_get)
    result = provider.fetch_financial_periods("600519.SS", limit=4)
    period = result["periods"][0]
    assert period["report_date_name"] == "2026一季报"
    assert period["revenue_yoy_pct"] == 6.336
    assert period["period_basis"] == "year_to_date_cumulative"

    database = Database(tmp_path / "db.sqlite", tmp_path / "workspaces")
    database.initialize()
    assert database.upsert_financial_periods(result["periods"]) == 1
    stored = database.list_financial_periods("600519.SS")
    assert stored[0]["parent_net_profit"] == 27_242_512_886.45


def test_eastmoney_detailed_three_statements_map_profit_working_capital_and_cash():
    rows = {
        "RPT_DMSK_FN_INCOME": {
            "SECURITY_NAME_ABBR": "中兴通讯",
            "REPORT_DATE": "2026-03-31 00:00:00",
            "NOTICE_DATE": "2026-04-25 00:00:00",
            "TOTAL_OPERATE_INCOME": 34_988_057_000,
            "OPERATE_COST": 25_094_779_000,
            "SALE_EXPENSE": 2_018_281_000,
            "PARENT_NETPROFIT": 1_310_444_000,
        },
        "RPT_DMSK_FN_BALANCE": {
            "SECURITY_NAME_ABBR": "中兴通讯",
            "REPORT_DATE": "2026-03-31 00:00:00",
            "NOTICE_DATE": "2026-04-25 00:00:00",
            "ACCOUNTS_RECE": 24_848_541_000,
            "INVENTORY": 51_959_114_000,
            "ACCOUNTS_PAYABLE": 23_305_330_000,
        },
        "RPT_DMSK_FN_CASHFLOW": {
            "SECURITY_NAME_ABBR": "中兴通讯",
            "REPORT_DATE": "2026-03-31 00:00:00",
            "NOTICE_DATE": "2026-04-25 00:00:00",
            "NETCASH_OPERATE": -1_978_648_000,
            "SALES_SERVICES": 33_574_651_000,
            "CONSTRUCT_LONG_ASSET": 1_107_496_000,
        },
    }

    def http_get(url, **kwargs):
        report_name = kwargs["params"]["reportName"]
        return FakeResponse(payload={"result": {"data": [rows[report_name]]}})

    packet = AShareFundamentalsProvider(http_get=http_get).fetch_statement_details(
        "000063.SZ", limit=4
    )
    statements = {item["statement_type"]: item for item in packet["statements"]}

    assert set(statements) == {"income", "balance", "cashflow"}
    assert statements["income"]["fiscal_period"] == "Q1"
    assert statements["income"]["report_date_name"] == "2026一季报"
    assert statements["income"]["fields"]["sales_expense"] == 2_018_281_000.0
    assert statements["balance"]["fields"]["inventory"] == 51_959_114_000.0
    assert statements["cashflow"]["fields"][
        "operating_cashflow"
    ] == -1_978_648_000.0


def test_fundamentals_service_uses_stored_data_when_refresh_sources_fail(tmp_path: Path):
    database = Database(tmp_path / "db.sqlite", tmp_path / "workspaces")
    database.initialize()
    database.save_valuation_snapshot(
        {
            "symbol": "600519.SS",
            "name": "贵州茅台",
            "currency": "CNY",
            "price": 1300.0,
            "pe_ttm": 20.0,
            "pb": 7.0,
            "market_timestamp": "2026-07-20T15:00:00+08:00",
            "source": "stored",
            "source_url": "https://example.invalid",
            "field_mapping": "stored_v1",
            "warnings": [],
            "fetched_at": "2026-07-20T07:00:00+00:00",
        }
    )
    database.upsert_financial_periods(
        [
            {
                "symbol": "600519.SS",
                "name": "贵州茅台",
                "report_date": "2026-03-31",
                "report_type": "一季报",
                "report_date_name": "2026一季报",
                "revenue_yoy_pct": 6.3,
                "net_profit_yoy_pct": 1.5,
                "parent_net_profit": 10.0,
                "operating_cashflow": 8.0,
                "source": "stored",
                "source_url": "https://example.invalid",
                "warnings": [],
            }
        ]
    )

    class FailingProvider:
        def fetch_valuation(self, symbol):
            raise RuntimeError("offline")

        def fetch_financial_periods(self, symbol):
            raise RuntimeError("offline")

    service = FundamentalsService(database, FailingProvider())
    packet = service.get_packet("600519.SS", refresh_max_age_seconds=-1)
    assert packet["valuation"]["pe_ttm"] == 20.0
    assert packet["summary"]["operating_cashflow_to_net_profit"] == 0.8
    assert any("数据源失败" in warning for warning in packet["warnings"])
