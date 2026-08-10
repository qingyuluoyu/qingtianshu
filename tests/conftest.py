from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.static_assets import STATIC_ASSET_MEDIA_TYPES

os.environ["QINGSHU_APP_FACTORY_ONLY"] = "1"

from app.main import create_app


@pytest.fixture(autouse=True)
def isolated_postgres_schema(monkeypatch):
    """Run every test against PostgreSQL in its own disposable schema."""

    import psycopg

    # Local operator paths must not change the deterministic Hermes runtime
    # selected by individual tests.
    monkeypatch.setenv("HERMES_PYTHON_BIN", "")
    base_url = os.getenv(
        "QINGSHU_TEST_POSTGRES_URL",
        "postgresql://chr@localhost/qingshu_test",
    ).strip()
    schema = "test_" + uuid4().hex
    try:
        with psycopg.connect(base_url) as connection:
            connection.execute(f'CREATE SCHEMA "{schema}"')
    except Exception as exc:
        pytest.fail(f"PostgreSQL test database is unavailable: {exc}")
    separator = "&" if "?" in base_url else "?"
    schema_url = f"{base_url}{separator}options={quote(f'-csearch_path={schema}')}"
    monkeypatch.setenv("QINGSHU_DATABASE_URL", schema_url)
    monkeypatch.setenv("QINGSHU_TEST_POSTGRES_URL", base_url)
    try:
        yield schema_url
    finally:
        with psycopg.connect(base_url) as connection:
            connection.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


class FakeMarketProvider:
    def fetch_history(
        self, symbol: str, range_name: str = "1y", interval: str = "1d"
    ) -> dict[str, Any]:
        start = datetime(2025, 1, 1, tzinfo=timezone.utc)
        bias = sum(ord(char) for char in symbol) % 7
        points = []
        for index in range(100):
            close = 100 + bias + index * 0.35 + ((index % 5) - 2) * 0.08
            timestamp = (start + timedelta(days=index)).isoformat(timespec="seconds")
            points.append(
                {
                    "timestamp": timestamp,
                    "open": close - 0.2,
                    "high": close + 0.5,
                    "low": close - 0.5,
                    "close": close,
                    "adjusted_close": close,
                    "volume": 1_000_000 + index,
                }
            )
        return {
            "symbol": symbol,
            "display_name": f"Fake {symbol}",
            "currency": "CNY" if symbol.endswith((".SS", ".SZ")) else "USD",
            "exchange": "FAKE",
            "timezone": "Asia/Shanghai",
            "previous_close": points[0]["close"],
            "regular_market_price": points[-1]["close"],
            "data_granularity": interval,
            "source": "Fake deterministic provider",
            "source_url": "https://example.invalid",
            "market_timestamp": points[-1]["timestamp"],
            "fetched_at": "2026-07-20T00:00:00+00:00",
            "is_stale": False,
            "cache_hit": False,
            "coverage": {
                "requested_range": range_name,
                "interval": interval,
                "points": len(points),
                "first_timestamp": points[0]["timestamp"],
                "last_timestamp": points[-1]["timestamp"],
            },
            "warnings": [],
            "points": points,
        }


class FakeSectorProvider:
    def fetch_hot_sectors(self, limit: int = 20) -> dict[str, Any]:
        rows = [
            {
                "code": f"BK{index:04d}",
                "name": name,
                "latest": 1000 + index,
                "pct_change": round(3.5 - index * 0.3, 2),
                "main_net_inflow": 100_000_000 - index * 1_000_000,
                "advancers": 20 - index,
                "decliners": 3 + index,
                "unchanged": 1,
            }
            for index, name in enumerate(
                ["算力", "机器人", "证券", "白酒", "医药", "电力"]
            )
        ][:limit]
        return {
            "source": "Fake sector provider",
            "source_url": "https://example.invalid",
            "market_timestamp": "2025-04-10T07:00:00+00:00",
            "fetched_at": "2025-04-10T07:00:05+00:00",
            "is_stale": False,
            "cache_hit": False,
            "coverage": {"returned": len(rows), "total_available": 6},
            "warnings": [],
            "sectors": rows,
        }


class FakeGoldProvider:
    def fetch_intraday(self, symbol: str = "XAU") -> dict[str, Any]:
        history = FakeMarketProvider().fetch_history(
            symbol, range_name="1d", interval="5m"
        )
        history["display_name"] = (
            "伦敦金（测试）" if symbol == "XAU" else f"{symbol}（测试）"
        )
        history["source"] = "Fake gold provider"
        history["previous_close"] = 100.0
        history["coverage"]["interval"] = "5m"
        return history


class FakeChinaInfoProvider:
    def fetch_announcements(self, symbol: str, limit: int = 20):
        return [
            {
                "symbol": symbol,
                "category": "announcement",
                "title": "公司发布重大事项公告",
                "summary": "测试公告",
                "source": "Fake announcements",
                "url": f"https://example.invalid/{symbol}/announcement",
                "published_at": "2026-07-20T10:00:00+08:00",
                "engagement": None,
                "fetched_at": "2026-07-20T10:01:00+08:00",
            }
        ]

    def fetch_company_news(self, symbol: str, limit: int = 30):
        return [
            {
                "symbol": symbol,
                "category": "news",
                "title": "公司产品价格调整",
                "summary": None,
                "source": "Fake news",
                "url": f"https://example.invalid/{symbol}/news",
                "published_at": "2026-07-20T11:00:00+08:00",
                "engagement": None,
                "fetched_at": "2026-07-20T11:01:00+08:00",
            }
        ]

    def fetch_guba_posts(self, symbol: str, limit: int = 30):
        return [
            {
                "symbol": symbol,
                "category": "social",
                "title": "提价利好，继续看多",
                "summary": "测试帖子",
                "source": "Fake social",
                "url": f"https://example.invalid/{symbol}/social",
                "published_at": "2026-07-20T12:00:00+08:00",
                "engagement": 100.0,
                "fetched_at": "2026-07-20T12:01:00+08:00",
            }
        ]


class FakeBusinessStructureProvider:
    def fetch(self, symbol: str):
        source_url = f"https://example.invalid/{symbol}/business-structure"
        fetched_at = "2026-07-20T18:40:00+00:00"
        rows = []

        def add(
            report_date: str,
            classification: str,
            item_name: str,
            revenue_share_pct: float,
            revenue: float,
            gross_margin_pct: float | None,
        ) -> None:
            gross_profit = (
                revenue * gross_margin_pct / 100
                if gross_margin_pct is not None
                else None
            )
            rows.append(
                {
                    "symbol": symbol,
                    "report_date": report_date,
                    "classification": classification,
                    "item_name": item_name,
                    "revenue": revenue,
                    "revenue_share_pct": revenue_share_pct,
                    "cost": revenue - gross_profit
                    if gross_profit is not None
                    else None,
                    "cost_share_pct": None,
                    "gross_profit": gross_profit,
                    "gross_profit_share_pct": None,
                    "gross_margin_pct": gross_margin_pct,
                    "source": "Fake business composition",
                    "source_url": source_url,
                    "fetched_at": fetched_at,
                }
            )

        for values in (
            ("2025-12-31", "product", "运营商网络", 46.0, 46e9, None),
            ("2025-12-31", "product", "政企业务", 29.0, 29e9, None),
            ("2025-12-31", "product", "消费者业务", 25.0, 25e9, None),
            ("2024-12-31", "product", "运营商网络", 58.0, 58e9, 51.0),
            ("2024-12-31", "product", "政企业务", 15.0, 15e9, 15.0),
            ("2024-12-31", "product", "消费者业务", 27.0, 27e9, 23.0),
            ("2025-06-30", "product", "运营商网络", 49.0, 25e9, 53.0),
            ("2025-06-30", "product", "政企业务", 27.0, 14e9, 8.0),
            ("2025-06-30", "product", "消费者业务", 24.0, 12e9, 18.0),
            ("2024-06-30", "product", "运营商网络", 59.0, 29e9, 50.0),
            ("2024-06-30", "product", "政企业务", 16.0, 8e9, 14.0),
            ("2024-06-30", "product", "消费者业务", 25.0, 12e9, 22.0),
            ("2025-12-31", "region", "中国", 67.0, 67e9, 31.0),
            ("2025-12-31", "region", "亚洲(不包括中国)", 13.0, 13e9, 29.0),
            ("2025-12-31", "region", "欧美及大洋洲", 15.0, 15e9, 24.0),
            ("2025-12-31", "region", "非洲", 5.0, 5e9, 36.0),
            ("2024-12-31", "region", "中国", 68.0, 68e9, 43.0),
            ("2024-12-31", "region", "亚洲(不含中国)", 13.0, 13e9, 29.0),
            ("2024-12-31", "region", "欧美及大洋洲", 14.0, 14e9, 22.0),
            ("2024-12-31", "region", "非洲", 5.0, 5e9, 34.0),
            ("2025-12-31", "industry", "通信设备制造业", 100.0, 100e9, 30.0),
            ("2024-12-31", "industry", "通信设备制造业", 100.0, 100e9, 41.0),
        ):
            add(*values)
        return {
            "symbol": symbol,
            "rows": rows,
            "source": "Fake business composition",
            "source_url": source_url,
            "fetched_at": fetched_at,
            "coverage": {
                "rows": len(rows),
                "report_periods": 4,
                "classifications": ["industry", "product", "region"],
            },
        }


class FakeShareholderProvider:
    def fetch(self, symbol: str, history_limit: int = 12):
        name = "中兴通讯" if symbol == "000063.SZ" else "测试公司"
        history = [
            {
                "as_of": "2026-07-10",
                "previous_as_of": "2026-06-30",
                "announced_at": "2026-07-13",
                "holder_count": 575136,
                "previous_holder_count": 635176,
                "holder_count_change": -60040,
                "holder_count_change_pct": -9.452498,
                "average_holding": 7003.61715,
                "average_market_cap": 283856.60308,
                "interval_price_change_pct": 11.992263,
                "total_market_cap": 163256151267.09,
                "total_a_shares": 4028032353.0,
            },
            {
                "as_of": "2026-06-30",
                "previous_as_of": "2026-06-18",
                "announced_at": "2026-07-08",
                "holder_count": 635176,
                "previous_holder_count": 640272,
                "holder_count_change": -5096,
                "holder_count_change_pct": -0.795912,
                "average_holding": 6341.60036,
                "average_market_cap": 229502.51718,
                "interval_price_change_pct": -4.486672,
                "total_market_cap": 145774490855.07,
                "total_a_shares": 4028032353.0,
            },
            {
                "as_of": "2026-06-18",
                "previous_as_of": "2026-06-10",
                "announced_at": "2026-06-30",
                "holder_count": 640272,
                "previous_holder_count": 657418,
                "holder_count_change": -17146,
                "holder_count_change_pct": -2.608082,
                "average_holding": 6291.12682,
                "average_market_cap": 238370.79531,
                "interval_price_change_pct": -1.37949,
                "total_market_cap": 152622145855.17,
                "total_a_shares": 4028032353.0,
            },
        ][:history_limit]
        top_holders = [
            {
                "rank": 1,
                "name": "中兴新通讯有限公司",
                "share_type": "流通A股,流通H股",
                "holding": 960978400.0,
                "holding_ratio_pct": 20.09,
                "holding_change": "不变",
                "holding_change_ratio_pct": None,
            },
            {
                "rank": 2,
                "name": "香港中央结算代理人有限公司",
                "share_type": "流通H股",
                "holding": 752419722.0,
                "holding_ratio_pct": 15.73,
                "holding_change": "30547",
                "holding_change_ratio_pct": 0.00406,
            },
            {
                "rank": 3,
                "name": "香港中央结算有限公司",
                "share_type": "流通A股",
                "holding": 54577719.0,
                "holding_ratio_pct": 1.14,
                "holding_change": "-8875428",
                "holding_change_ratio_pct": -13.987372,
            },
        ]
        return {
            "symbol": symbol,
            "name": name,
            "holder_history": history,
            "top10_report_date": "2026-03-31",
            "top_holders": top_holders,
            "sources": [
                {
                    "source": "Fake shareholder count",
                    "source_url": f"https://example.invalid/{symbol}/holder-count",
                },
                {
                    "source": "Fake top shareholders",
                    "source_url": f"https://example.invalid/{symbol}/top-holders",
                },
            ],
            "fetched_at": "2026-07-20T18:45:00+00:00",
            "coverage": {
                "holder_history_points": len(history),
                "top_holders": len(top_holders),
                "attempted_top10_report_dates": ["2026-06-30", "2026-03-31"],
            },
        }


class FakeFilingProvider:
    def list_financial_reports(self, symbol: str, limit: int = 3):
        return [
            {
                "symbol": symbol,
                "article_code": f"TEST-{symbol}-2026Q1",
                "title": "测试公司:2026年一季度报告",
                "document_type": "first_quarter",
                "report_period": "2026-03-31",
                "notice_date": "2026-04-25",
                "published_at": "2026-04-25T00:00:00+08:00",
                "source": "company_filing",
                "source_url": f"https://example.invalid/{symbol}/2026-q1",
            }
        ][:limit]

    def fetch_document(self, report):
        content = """
测试公司 2026 年第一季度报告

项目名称 2026年1-3月 2025年1-3月 同比变化 原因分析

财务费用 100,000 50,000 100.00% 主要因本期汇率波动产生汇兑损失及净利息收入减少。

资产减值损失 30,000 10,000 200.00% 主要因本期存货跌价准备计提增加。

经营活动产生的现金流量净额 1,500,000 2,000,000 -25.00%。
""".strip()
        import hashlib

        return {
            **report,
            "content_text": content,
            "attach_url": f"https://example.invalid/{report['article_code']}.pdf",
            "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "warnings": [],
            "fetched_at": "2026-07-20T18:30:00+00:00",
        }


class FakeFundamentalsProvider:
    def fetch_valuation(self, symbol: str):
        return {
            "symbol": symbol,
            "name": "测试公司",
            "currency": "CNY",
            "price": 120.0,
            "previous_close": 118.0,
            "pct_change": 1.69,
            "turnover_rate_pct": 1.2,
            "pe_ttm": 18.5,
            "pe_dynamic": 17.2,
            "pe_static": 19.1,
            "pb": 3.2,
            "float_market_cap": 80_000_000_000.0,
            "total_market_cap": 100_000_000_000.0,
            "market_timestamp": "2026-07-20T15:00:00+08:00",
            "source": "Fake valuation",
            "source_url": "https://example.invalid/valuation",
            "fetched_at": "2026-07-20T07:01:00+00:00",
            "field_mapping": "fake_v1",
            "warnings": ["估值需要行业可比。"],
        }

    def fetch_financial_periods(self, symbol: str, limit: int = 8):
        period = {
            "symbol": symbol,
            "name": "测试公司",
            "report_date": "2026-03-31",
            "report_type": "一季报",
            "report_date_name": "2026一季报",
            "notice_date": "2026-04-25",
            "currency": "CNY",
            "eps_basic": 1.2,
            "book_value_per_share": 12.0,
            "revenue": 12_000_000_000.0,
            "revenue_yoy_pct": 8.5,
            "parent_net_profit": 2_000_000_000.0,
            "net_profit_yoy_pct": 6.2,
            "roe_weighted_pct": 10.0,
            "gross_margin_pct": 35.0,
            "net_margin_pct": 16.7,
            "debt_asset_ratio_pct": 40.0,
            "operating_cashflow": 1_500_000_000.0,
            "operating_cashflow_per_share": 0.9,
            "total_assets": 80_000_000_000.0,
            "total_equity": 48_000_000_000.0,
            "period_basis": "year_to_date_cumulative",
            "source": "Fake financials",
            "source_url": "https://example.invalid/financials",
            "fetched_at": "2026-07-20T07:01:00+00:00",
            "warnings": ["累计口径。"],
        }
        return {
            "symbol": symbol,
            "name": "测试公司",
            "periods": [period],
            "source": "Fake financials",
            "source_url": "https://example.invalid/financials",
            "fetched_at": "2026-07-20T07:01:00+00:00",
            "coverage": {"returned": 1, "requested": limit},
            "warnings": [],
        }

    def fetch_statement_details(self, symbol: str, limit: int = 12):
        common = {
            "symbol": symbol,
            "name": "测试公司",
            "report_type": "一季报",
            "currency": "CNY",
            "fiscal_period": "Q1",
            "period_basis": "year_to_date_cumulative",
            "source": "Fake detailed statements",
            "source_url": "https://example.invalid/detailed-financials",
            "fetched_at": "2026-07-20T07:01:00+00:00",
            "warnings": [],
        }
        periods = (
            (
                "2026-03-31",
                "2026一季报",
                {
                    "income": {
                        "revenue": 12_000_000_000.0,
                        "total_operating_cost": 9_800_000_000.0,
                        "operating_cost": 7_800_000_000.0,
                        "sales_expense": 1_000_000_000.0,
                        "management_expense": 600_000_000.0,
                        "finance_expense": 100_000_000.0,
                        "operating_profit": 2_200_000_000.0,
                        "total_profit": 2_150_000_000.0,
                        "income_tax": 150_000_000.0,
                        "parent_net_profit": 2_000_000_000.0,
                        "deducted_parent_net_profit": 1_850_000_000.0,
                    },
                    "balance": {
                        "accounts_receivable": 3_000_000_000.0,
                        "inventory": 2_500_000_000.0,
                        "accounts_payable": 1_800_000_000.0,
                        "cash_and_equivalents": 5_000_000_000.0,
                        "total_assets": 80_000_000_000.0,
                        "total_liabilities": 32_000_000_000.0,
                        "total_equity": 48_000_000_000.0,
                    },
                    "cashflow": {
                        "operating_cashflow": 1_500_000_000.0,
                        "cash_received_from_sales": 11_500_000_000.0,
                        "investing_cashflow": -800_000_000.0,
                        "financing_cashflow": 300_000_000.0,
                        "capital_expenditure_proxy": 500_000_000.0,
                    },
                },
            ),
            (
                "2025-03-31",
                "2025一季报",
                {
                    "income": {
                        "revenue": 11_000_000_000.0,
                        "total_operating_cost": 8_000_000_000.0,
                        "operating_cost": 6_600_000_000.0,
                        "sales_expense": 800_000_000.0,
                        "management_expense": 550_000_000.0,
                        "finance_expense": 50_000_000.0,
                        "operating_profit": 3_000_000_000.0,
                        "total_profit": 2_900_000_000.0,
                        "income_tax": 800_000_000.0,
                        "parent_net_profit": 2_100_000_000.0,
                        "deducted_parent_net_profit": 2_000_000_000.0,
                    },
                    "balance": {
                        "accounts_receivable": 2_200_000_000.0,
                        "inventory": 2_000_000_000.0,
                        "accounts_payable": 1_600_000_000.0,
                        "cash_and_equivalents": 4_800_000_000.0,
                        "total_assets": 75_000_000_000.0,
                        "total_liabilities": 30_000_000_000.0,
                        "total_equity": 45_000_000_000.0,
                    },
                    "cashflow": {
                        "operating_cashflow": 2_000_000_000.0,
                        "cash_received_from_sales": 11_300_000_000.0,
                        "investing_cashflow": -600_000_000.0,
                        "financing_cashflow": 100_000_000.0,
                        "capital_expenditure_proxy": 400_000_000.0,
                    },
                },
            ),
        )
        statements = []
        for report_date, report_date_name, by_type in periods:
            for statement_type, fields in by_type.items():
                statements.append(
                    {
                        **common,
                        "report_date": report_date,
                        "report_date_name": report_date_name,
                        "notice_date": f"{report_date[:4]}-04-25",
                        "statement_type": statement_type,
                        "fields": fields,
                    }
                )
        return {
            "symbol": symbol,
            "name": "测试公司",
            "statements": statements[: limit * 3],
            "source": common["source"],
            "source_url": common["source_url"],
            "fetched_at": common["fetched_at"],
            "coverage": {"returned_statements": len(statements)},
            "warnings": [],
        }


class FakeGlobalInfoProvider:
    def fetch_company_news(self, symbol: str, limit: int = 20):
        return [
            {
                "symbol": symbol,
                "category": "global_news",
                "title": "NVIDIA announces new data-center platform",
                "summary": "Deterministic test news",
                "source": "Fake Nasdaq news",
                "url": "https://example.invalid/nvda-news",
                "published_at": "2026-07-20T12:00:00-04:00",
                "engagement": None,
                "fetched_at": "2026-07-20T16:01:00+00:00",
            }
        ]


class FakeMarketNewsProvider:
    def fetch(self, market_key: str, limit: int = 12):
        label = {
            "us": "美国股市",
            "china": "A股",
            "hong_kong": "港股",
            "japan": "日本股市",
            "korea": "韩国股市",
            "europe": "欧洲股市",
            "gold": "伦敦金",
        }[market_key]
        items = [
            {
                "id": f"{market_key}-driver-1",
                "symbol": f"__MARKET_{market_key.upper()}__",
                "category": "market_news",
                "title": "投资者在财报季前获利了结，主要指数冲高回落",
                "summary": None,
                "source": "Fake market wire",
                "url": f"https://example.invalid/{market_key}/driver-1",
                "published_at": "2026-07-20T20:30:00+00:00",
                "engagement": None,
                "fetched_at": "2026-07-20T20:31:00+00:00",
            },
            {
                "id": f"{market_key}-driver-2",
                "symbol": f"__MARKET_{market_key.upper()}__",
                "category": "market_news",
                "title": "能源价格上行与长端利率压力反复出现在市场复盘中",
                "summary": None,
                "source": "Fake market wire",
                "url": f"https://example.invalid/{market_key}/driver-2",
                "published_at": "2026-07-20T20:20:00+00:00",
                "engagement": None,
                "fetched_at": "2026-07-20T20:31:00+00:00",
            },
        ][:limit]
        return {
            "market_key": market_key,
            "market_label": label,
            "items": items,
            "fetched_at": "2026-07-20T20:31:00+00:00",
        }


class FakeUSFundamentalsProvider:
    def fetch_valuation(self, symbol: str):
        return {
            "symbol": symbol,
            "name": "英伟达",
            "currency": "USD",
            "price": 204.65,
            "previous_close": 202.81,
            "pct_change": 0.91,
            "turnover_rate_pct": None,
            "pe_ttm": 31.34,
            "pe_dynamic": None,
            "pe_static": None,
            "pb": 6.53,
            "float_market_cap": 4_760_824_000_000.0,
            "total_market_cap": 4_956_733_188_000.0,
            "market_timestamp": "2026-07-20T14:21:00-04:00",
            "source": "Fake US valuation",
            "source_url": "https://example.invalid/us-valuation",
            "fetched_at": "2026-07-20T18:22:00+00:00",
            "field_mapping": "fake_us_v1",
            "warnings": ["估值需要行业可比。"],
        }

    def fetch_financial_periods(self, symbol: str, cik: str, limit: int = 8):
        period = {
            "symbol": symbol,
            "name": "NVIDIA CORP",
            "report_date": "2026-04-26",
            "report_type": "10-Q",
            "report_date_name": "FY2027 Q1 (10-Q)",
            "notice_date": "2026-05-20",
            "currency": "USD",
            "eps_basic": None,
            "eps_diluted": 2.39,
            "book_value_per_share": None,
            "revenue": 81_615_000_000.0,
            "revenue_yoy_pct": 85.22,
            "parent_net_profit": 58_321_000_000.0,
            "net_profit_yoy_pct": 210.63,
            "roe_weighted_pct": None,
            "gross_margin_pct": 74.93,
            "net_margin_pct": 71.46,
            "debt_asset_ratio_pct": 24.66,
            "operating_cashflow": 50_344_000_000.0,
            "operating_cashflow_per_share": None,
            "total_assets": 259_474_000_000.0,
            "total_liabilities": 64_000_000_000.0,
            "total_equity": 195_474_000_000.0,
            "period_basis": "year_to_date_cumulative",
            "source": "Fake SEC Companyfacts",
            "source_url": "https://example.invalid/companyfacts",
            "fetched_at": "2026-07-20T18:22:00+00:00",
            "warnings": ["SEC 累计口径。"],
        }
        return {
            "symbol": symbol,
            "name": "NVIDIA CORP",
            "periods": [period],
            "source": "Fake SEC Companyfacts",
            "source_url": "https://example.invalid/companyfacts",
            "fetched_at": "2026-07-20T18:22:00+00:00",
            "coverage": {"returned": 1, "requested": limit},
            "warnings": [],
        }

    def fetch_statement_details(self, symbol: str, cik: str, limit: int = 8):
        common = {
            "symbol": symbol,
            "name": "NVIDIA CORP",
            "report_type": "10-Q",
            "currency": "USD",
            "fiscal_period": "Q1",
            "period_basis": "year_to_date_cumulative",
            "source": "Fake SEC detailed statements",
            "source_url": "https://example.invalid/companyfacts",
            "fetched_at": "2026-07-20T18:22:00+00:00",
            "warnings": [],
        }
        periods = (
            (
                "2026-04-26",
                "FY2027 Q1 (10-Q)",
                {
                    "income": {
                        "revenue": 81_615_000_000.0,
                        "cost_of_revenue": 20_460_000_000.0,
                        "gross_profit": 61_155_000_000.0,
                        "operating_profit": 53_000_000_000.0,
                        "selling_general_admin_expense": 3_200_000_000.0,
                        "research_expense": 4_400_000_000.0,
                        "income_tax": 6_500_000_000.0,
                        "parent_net_profit": 58_321_000_000.0,
                    },
                    "balance": {
                        "accounts_receivable": 30_000_000_000.0,
                        "inventory": 22_000_000_000.0,
                        "accounts_payable": 8_000_000_000.0,
                        "cash_and_equivalents": 70_000_000_000.0,
                        "fixed_assets": 9_000_000_000.0,
                        "total_assets": 259_474_000_000.0,
                        "total_liabilities": 64_000_000_000.0,
                        "total_equity": 195_474_000_000.0,
                    },
                    "cashflow": {
                        "operating_cashflow": 50_344_000_000.0,
                        "investing_cashflow": -12_000_000_000.0,
                        "financing_cashflow": -18_000_000_000.0,
                        "capital_expenditure_proxy": 3_000_000_000.0,
                    },
                },
            ),
            (
                "2025-04-27",
                "FY2026 Q1 (10-Q)",
                {
                    "income": {
                        "revenue": 44_062_000_000.0,
                        "cost_of_revenue": 10_900_000_000.0,
                        "gross_profit": 33_162_000_000.0,
                        "operating_profit": 27_500_000_000.0,
                        "selling_general_admin_expense": 2_200_000_000.0,
                        "research_expense": 3_400_000_000.0,
                        "income_tax": 4_200_000_000.0,
                        "parent_net_profit": 18_775_000_000.0,
                    },
                    "balance": {
                        "accounts_receivable": 21_000_000_000.0,
                        "inventory": 12_000_000_000.0,
                        "accounts_payable": 6_500_000_000.0,
                        "cash_and_equivalents": 55_000_000_000.0,
                        "fixed_assets": 7_500_000_000.0,
                        "total_assets": 180_000_000_000.0,
                        "total_liabilities": 50_000_000_000.0,
                        "total_equity": 130_000_000_000.0,
                    },
                    "cashflow": {
                        "operating_cashflow": 27_414_000_000.0,
                        "investing_cashflow": -8_000_000_000.0,
                        "financing_cashflow": -10_000_000_000.0,
                        "capital_expenditure_proxy": 2_000_000_000.0,
                    },
                },
            ),
        )
        statements = []
        for report_date, report_date_name, by_type in periods:
            for statement_type, fields in by_type.items():
                statements.append(
                    {
                        **common,
                        "report_date": report_date,
                        "report_date_name": report_date_name,
                        "notice_date": f"{report_date[:4]}-05-20",
                        "statement_type": statement_type,
                        "fields": fields,
                    }
                )
        return {
            "symbol": symbol,
            "name": "NVIDIA CORP",
            "statements": statements[: limit * 3],
            "source": common["source"],
            "source_url": common["source_url"],
            "fetched_at": common["fetched_at"],
            "coverage": {"returned_statements": len(statements)},
            "warnings": [],
        }

    def fetch_filings(self, symbol: str, cik: str, limit: int = 12):
        return [
            {
                "symbol": symbol,
                "category": "regulatory_filing",
                "title": "NVDA SEC 8-K｜2026-07-02",
                "summary": "8-K；报告期 2026-06-28。",
                "source": "SEC EDGAR",
                "url": "https://www.sec.gov/Archives/edgar/data/1045810/filing.htm",
                "published_at": "2026-07-02T00:00:00-04:00",
                "engagement": None,
                "fetched_at": "2026-07-20T18:22:00+00:00",
            }
        ]


class FakeAnalystExpectationsProvider:
    def __init__(self):
        self.estimate_2026 = 1.4
        self.estimate_2027 = 1.65
        self.organization_count = 11

    def fetch(self, symbol: str, report_limit: int = 20):
        return {
            "symbol": symbol,
            "name": "中兴通讯",
            "industry": "通信设备",
            "rating_window": "近六个月",
            "rating_organization_count": self.organization_count,
            "rating_counts": {
                "buy": 9,
                "add": 2,
                "neutral": 0,
                "reduce": 0,
                "sell": 0,
            },
            "forecast_eps": [
                {"year": 2025, "value": 1.17, "kind": "actual"},
                {
                    "year": 2026,
                    "value": self.estimate_2026,
                    "kind": "estimate",
                },
                {
                    "year": 2027,
                    "value": self.estimate_2027,
                    "kind": "estimate",
                },
            ],
            "reports": [
                {
                    "title": "算力业务打开新空间",
                    "stock_name": "中兴通讯",
                    "institution": "测试证券",
                    "published_at": "2026-07-18",
                    "rating": "买入",
                    "previous_rating": "增持",
                    "industry": "通信设备",
                    "researchers": "测试分析师",
                    "forecast_eps": [
                        {"year": 2026, "value": self.estimate_2026},
                        {"year": 2027, "value": self.estimate_2027},
                    ],
                    "report_url": "https://example.invalid/report.pdf",
                }
            ][:report_limit],
            "report_current_year": 2026,
            "fetched_at": "2026-07-21T08:00:00+00:00",
            "sources": [
                {
                    "name": "Fake analyst expectations",
                    "url": "https://example.invalid/expectations",
                    "scope": "券商研报统计与盈利预测汇总",
                }
            ],
        }


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_file = backup_dir / "qingshu-test.dump"
    backup_file.write_bytes(b"isolated test backup")
    (backup_dir / "latest.json").write_text(
        json.dumps(
            {
                "status": "complete",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "database": "qingshu_test",
                "server": "localhost:5432",
                "backup_file": backup_file.name,
                "format": "postgresql_custom",
                "archive_verified": True,
                "size_bytes": backup_file.stat().st_size,
                "sha256": "test-only",
            }
        ),
        encoding="utf-8",
    )
    return Settings(
        data_dir=tmp_path,
        backup_dir=backup_dir,
        database_url=os.environ["QINGSHU_DATABASE_URL"],
        workspace_root=tmp_path / "workspaces",
        hermes_bin=Path("/nonexistent/hermes"),
        hermes_enabled=False,
        hermes_timeout_seconds=5,
        market_cache_seconds=60,
        sector_cache_seconds=60,
        intraday_cache_seconds=20,
        article_min_interval_hours=4,
        article_max_per_24h=3,
        background_jobs_enabled=False,
        background_market_refresh_seconds=30,
        background_article_check_seconds=1800,
        background_info_refresh_seconds=600,
        background_fundamentals_refresh_seconds=3600,
        background_research_refresh_seconds=1800,
        background_calibration_refresh_seconds=21600,
        background_use_hermes=False,
        legacy_anonymous_mode=True,
        default_a_share_symbols=("600519.SS",),
        default_research_symbols=("000063.SZ", "300308.SZ", "NVDA"),
    )


@pytest.fixture()
def app(settings: Settings):
    return create_app(
        settings,
        FakeMarketProvider(),
        FakeSectorProvider(),
        FakeGoldProvider(),
        FakeChinaInfoProvider(),
        FakeFundamentalsProvider(),
        FakeGlobalInfoProvider(),
        FakeUSFundamentalsProvider(),
        FakeMarketNewsProvider(),
        FakeFilingProvider(),
        FakeBusinessStructureProvider(),
        FakeShareholderProvider(),
        FakeAnalystExpectationsProvider(),
    )


@pytest.fixture()
def client(app) -> TestClient:
    return TestClient(app)


@pytest.fixture()
def frontend_source(client: TestClient) -> str:
    page = client.get("/demo")
    assert page.status_code == 200
    assets = [client.get(f"/static/{name}") for name in STATIC_ASSET_MEDIA_TYPES]
    assert all(asset.status_code == 200 for asset in assets)
    return "\n".join([page.text, *(asset.text for asset in assets)])
