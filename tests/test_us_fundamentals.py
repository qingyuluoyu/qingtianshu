from __future__ import annotations

import sqlite3
from pathlib import Path

from app.db import Database
from app.providers.us_fundamentals import USEquityFundamentalsProvider


class FakeResponse:
    def __init__(self, *, payload=None, content: bytes | None = None):
        self.payload = payload
        self.content = content or b""

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def _duration_row(
    *, start: str, end: str, value: float, accession: str, fy: int, fp: str, form: str
):
    return {
        "start": start,
        "end": end,
        "val": value,
        "accn": accession,
        "fy": fy,
        "fp": fp,
        "form": form,
        "filed": "2026-05-20" if fy == 2027 else "2025-05-28",
        "frame": f"CY{end[:4]}{fp}" if fp != "FY" else f"CY{int(end[:4]) - 1}",
    }


def _instant_row(*, end: str, value: float, accession: str, fy: int, fp: str, form: str):
    return {
        "end": end,
        "val": value,
        "accn": accession,
        "fy": fy,
        "fp": fp,
        "form": form,
        "filed": "2026-05-20" if fy == 2027 else "2025-05-28",
    }


def _companyfacts_payload():
    current = {
        "start": "2026-01-26",
        "end": "2026-04-26",
        "accession": "0001045810-26-000052",
        "fy": 2027,
        "fp": "Q1",
        "form": "10-Q",
    }
    previous = {
        "start": "2025-01-27",
        "end": "2025-04-27",
        "accession": "0001045810-25-000100",
        "fy": 2026,
        "fp": "Q1",
        "form": "10-Q",
    }
    annual = {
        "start": "2025-01-27",
        "end": "2026-01-25",
        "accession": "0001045810-26-000021",
        "fy": 2026,
        "fp": "FY",
        "form": "10-K",
    }

    def durations(current_value, previous_value, annual_value, unit="USD"):
        rows = [
            _duration_row(
                start=current["start"],
                end=current["end"],
                value=current_value,
                accession=current["accession"],
                fy=current["fy"],
                fp=current["fp"],
                form=current["form"],
            ),
            _duration_row(
                start=previous["start"],
                end=previous["end"],
                value=previous_value,
                accession=previous["accession"],
                fy=previous["fy"],
                fp=previous["fp"],
                form=previous["form"],
            ),
            _duration_row(
                start=annual["start"],
                end=annual["end"],
                value=annual_value,
                accession=annual["accession"],
                fy=annual["fy"],
                fp=annual["fp"],
                form=annual["form"],
            ),
        ]
        return {"units": {unit: rows}}

    def instants(current_value, previous_value, annual_value):
        return {
            "units": {
                "USD": [
                    _instant_row(
                        end=current["end"],
                        value=current_value,
                        accession=current["accession"],
                        fy=current["fy"],
                        fp=current["fp"],
                        form=current["form"],
                    ),
                    _instant_row(
                        end=previous["end"],
                        value=previous_value,
                        accession=previous["accession"],
                        fy=previous["fy"],
                        fp=previous["fp"],
                        form=previous["form"],
                    ),
                    _instant_row(
                        end=annual["end"],
                        value=annual_value,
                        accession=annual["accession"],
                        fy=annual["fy"],
                        fp=annual["fp"],
                        form=annual["form"],
                    ),
                ]
            }
        }

    return {
        "entityName": "NVIDIA CORP",
        "facts": {
            "us-gaap": {
                "Revenues": durations(81_615_000_000, 44_062_000_000, 215_938_000_000),
                "NetIncomeLoss": durations(58_321_000_000, 18_775_000_000, 120_067_000_000),
                "EarningsPerShareDiluted": durations(2.39, 0.76, 4.90, "USD/shares"),
                "GrossProfit": durations(61_157_000_000, 26_668_000_000, 153_463_000_000),
                "NetCashProvidedByUsedInOperatingActivities": durations(
                    50_344_000_000, 27_414_000_000, 102_718_000_000
                ),
                "Assets": instants(259_474_000_000, 95_520_000_000, 206_803_000_000),
                "Liabilities": instants(64_000_000_000, 31_677_000_000, 49_510_000_000),
                "StockholdersEquity": instants(
                    195_474_000_000, 63_843_000_000, 157_293_000_000
                ),
            }
        },
    }


def test_tencent_us_valuation_mapping_uses_usd_market_cap_units():
    fields = [""] * 70
    fields[1] = "英伟达"
    fields[2] = "NVDA.OQ"
    fields[3] = "204.65"
    fields[4] = "202.81"
    fields[30] = "2026-07-20 14:21:00"
    fields[32] = "0.91"
    fields[39] = "31.34"
    fields[44] = "47608.24000"
    fields[45] = "49567.33188"
    fields[47] = "6.53"
    content = ('v_usNVDA="' + "~".join(fields) + '";').encode("gb18030")
    provider = USEquityFundamentalsProvider(
        "Qingshu tests test@example.com",
        http_get=lambda *args, **kwargs: FakeResponse(content=content),
    )

    result = provider.fetch_valuation("NVDA")

    assert result["currency"] == "USD"
    assert result["pe_ttm"] == 31.34
    assert result["pb"] == 6.53
    assert result["total_market_cap"] == 4_956_733_188_000.0
    assert result["market_timestamp"] == "2026-07-20T14:21:00-04:00"


def test_sec_companyfacts_are_aligned_by_filing_period_and_compute_yoy():
    provider = USEquityFundamentalsProvider(
        "Qingshu tests test@example.com",
        http_get=lambda *args, **kwargs: FakeResponse(payload=_companyfacts_payload()),
    )

    packet = provider.fetch_financial_periods("NVDA", "0001045810", limit=8)
    current = packet["periods"][0]
    annual = next(item for item in packet["periods"] if item["report_type"] == "10-K")

    assert current["report_date"] == "2026-04-26"
    assert current["report_date_name"] == "FY2027 Q1 (10-Q)"
    assert current["revenue"] == 81_615_000_000.0
    assert current["revenue_yoy_pct"] == 85.228
    assert current["net_profit_yoy_pct"] == 210.631
    assert current["eps_diluted"] == 2.39
    assert current["gross_margin_pct"] == 74.934
    assert current["debt_asset_ratio_pct"] == 24.665
    assert current["period_basis"] == "year_to_date_cumulative"
    assert annual["period_basis"] == "annual"


def test_sec_companyfacts_build_detailed_statement_rows_without_inference():
    provider = USEquityFundamentalsProvider(
        "Qingshu tests test@example.com",
        http_get=lambda *args, **kwargs: FakeResponse(payload=_companyfacts_payload()),
    )

    packet = provider.fetch_statement_details("NVDA", "0001045810", limit=3)
    current = [
        item for item in packet["statements"] if item["report_date"] == "2026-04-26"
    ]
    by_type = {item["statement_type"]: item for item in current}

    assert set(by_type) == {"income", "balance", "cashflow"}
    assert by_type["income"]["fields"]["revenue"] == 81_615_000_000.0
    assert by_type["income"]["fields"]["gross_profit"] == 61_157_000_000.0
    assert by_type["income"]["fields"]["research_expense"] is None
    assert by_type["balance"]["fields"]["total_assets"] == 259_474_000_000.0
    assert by_type["cashflow"]["fields"][
        "operating_cashflow"
    ] == 50_344_000_000.0


def test_sec_submissions_build_official_edgar_urls():
    submissions = {
        "filings": {
            "recent": {
                "form": ["8-K", "10-Q", "4"],
                "filingDate": ["2026-07-02", "2026-05-20", "2026-05-01"],
                "reportDate": ["2026-06-28", "2026-04-26", "2026-04-30"],
                "accessionNumber": [
                    "0001045810-26-000060",
                    "0001045810-26-000052",
                    "0001045810-26-000040",
                ],
                "primaryDocument": [
                    "nvda-20260628.htm",
                    "nvda-20260426.htm",
                    "ownership.xml",
                ],
                "primaryDocDescription": ["8-K", "10-Q", "FORM 4"],
            }
        }
    }
    provider = USEquityFundamentalsProvider(
        "Qingshu tests test@example.com",
        http_get=lambda *args, **kwargs: FakeResponse(payload=submissions),
    )

    items = provider.fetch_filings("NVDA", "0001045810", limit=10)

    assert [item["category"] for item in items] == [
        "regulatory_filing",
        "regulatory_filing",
    ]
    assert items[0]["url"] == (
        "https://www.sec.gov/Archives/edgar/data/1045810/"
        "000104581026000060/nvda-20260628.htm"
    )


def test_database_migrates_existing_financial_table_for_us_fields(tmp_path: Path):
    database_path = tmp_path / "legacy.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE financial_periods (
                symbol TEXT NOT NULL,
                report_date TEXT NOT NULL,
                report_type TEXT NOT NULL,
                report_date_name TEXT NOT NULL,
                notice_date TEXT,
                name TEXT NOT NULL,
                currency TEXT NOT NULL,
                eps_basic REAL,
                book_value_per_share REAL,
                revenue REAL,
                revenue_yoy_pct REAL,
                parent_net_profit REAL,
                net_profit_yoy_pct REAL,
                roe_weighted_pct REAL,
                gross_margin_pct REAL,
                net_margin_pct REAL,
                debt_asset_ratio_pct REAL,
                operating_cashflow REAL,
                operating_cashflow_per_share REAL,
                total_assets REAL,
                total_equity REAL,
                period_basis TEXT NOT NULL,
                source TEXT NOT NULL,
                source_url TEXT NOT NULL,
                warnings_json TEXT NOT NULL,
                fetched_at TEXT NOT NULL,
                PRIMARY KEY(symbol, report_date, report_type)
            )
            """
        )
    database = Database(database_path, tmp_path / "workspaces")

    database.initialize()

    with database.connect() as connection:
        columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(financial_periods)")
        }
    assert {"eps_diluted", "total_liabilities"}.issubset(columns)
