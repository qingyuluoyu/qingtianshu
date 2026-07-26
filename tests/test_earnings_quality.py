from __future__ import annotations

import pytest

from app.db import Database
from app.services.agent import AgentService
from app.services.earnings_quality import EarningsQualityService


def financial_period(
    symbol: str,
    report_date: str,
    report_type: str,
    report_date_name: str,
    *,
    revenue_yoy_pct: float,
    net_profit_yoy_pct: float,
    gross_margin_pct: float,
    net_margin_pct: float,
    operating_cashflow: float,
    parent_net_profit: float,
    debt_asset_ratio_pct: float,
    revenue: float = 10_000_000_000.0,
) -> dict:
    return {
        "symbol": symbol,
        "name": symbol,
        "report_date": report_date,
        "report_type": report_type,
        "report_date_name": report_date_name,
        "notice_date": report_date,
        "currency": "USD" if symbol == "NVDA" else "CNY",
        "revenue": revenue,
        "revenue_yoy_pct": revenue_yoy_pct,
        "parent_net_profit": parent_net_profit,
        "net_profit_yoy_pct": net_profit_yoy_pct,
        "roe_weighted_pct": 8.0,
        "gross_margin_pct": gross_margin_pct,
        "net_margin_pct": net_margin_pct,
        "debt_asset_ratio_pct": debt_asset_ratio_pct,
        "operating_cashflow": operating_cashflow,
        "total_assets": 100_000_000_000.0,
        "total_liabilities": 50_000_000_000.0,
        "total_equity": 50_000_000_000.0,
        "period_basis": "year_to_date_cumulative",
        "source": "test",
        "source_url": "https://example.invalid/financials",
        "warnings": [],
        "fetched_at": "2026-07-21T00:00:00+00:00",
    }


def test_zte_revenue_profit_and_cashflow_contradictions_are_explicit(settings):
    database = Database(settings.workspace_root)
    database.initialize()
    database.upsert_financial_periods(
        [
            financial_period(
                "000063.SZ",
                "2026-03-31",
                "一季报",
                "2026一季报",
                revenue_yoy_pct=6.13,
                net_profit_yoy_pct=-46.58,
                gross_margin_pct=28.28,
                net_margin_pct=3.77,
                operating_cashflow=-1_978_648_000.0,
                parent_net_profit=1_310_444_000.0,
                debt_asset_ratio_pct=65.87,
                revenue=34_988_000_000.0,
            ),
            financial_period(
                "000063.SZ",
                "2025-03-31",
                "一季报",
                "2025一季报",
                revenue_yoy_pct=7.82,
                net_profit_yoy_pct=-10.5,
                gross_margin_pct=34.27,
                net_margin_pct=7.47,
                operating_cashflow=1_851_253_000.0,
                parent_net_profit=2_453_172_000.0,
                debt_asset_ratio_pct=66.7,
            ),
        ]
    )

    packet = EarningsQualityService(database).get_packet("000063.SZ")

    assert packet["overall_label"] == "盈利质量承压"
    assert packet["comparable_report"]["report_date_name"] == "2025一季报"
    assert packet["latest_report"]["operating_cashflow_to_net_profit"] == pytest.approx(
        -1.51, abs=0.001
    )
    assert any("营收增长但净利润下降" in item for item in packet["contradictions"])
    assert any("方向相反" in item for item in packet["contradictions"])
    gross_margin = next(
        item for item in packet["factors"] if item["key"] == "gross_margin"
    )
    assert gross_margin["current_revenue_per_margin_point"] == 349_880_000.0
    guard = AgentService._validate_model_output(
        "按本期营收静态测算，毛利率每变化 1 个百分点对应约 3.5 亿元；这不是实际利润归因。",
        packet,
    )
    assert guard["passed"] is True


def test_positive_growth_with_weak_cash_conversion_is_not_called_fully_consistent(
    settings,
):
    database = Database(settings.workspace_root)
    database.initialize()
    database.upsert_financial_periods(
        [
            financial_period(
                "300308.SZ",
                "2026-03-31",
                "一季报",
                "2026一季报",
                revenue_yoy_pct=192.12,
                net_profit_yoy_pct=262.28,
                gross_margin_pct=46.06,
                net_margin_pct=32.4,
                operating_cashflow=3_367_573_676.62,
                parent_net_profit=5_734_501_526.83,
                debt_asset_ratio_pct=32.64,
            ),
            financial_period(
                "300308.SZ",
                "2025-03-31",
                "一季报",
                "2025一季报",
                revenue_yoy_pct=37.82,
                net_profit_yoy_pct=56.83,
                gross_margin_pct=36.7,
                net_margin_pct=25.33,
                operating_cashflow=2_164_459_570.16,
                parent_net_profit=1_582_876_128.67,
                debt_asset_ratio_pct=30.39,
            ),
        ]
    )

    packet = EarningsQualityService(database).get_packet("300308.SZ")

    assert packet["overall_label"] == "增长为正但质量仍需复核"
    assert any("覆盖低于 0.8" in item for item in packet["contradictions"])
    assert any("毛利率与净利率" in item for item in packet["supports"])


def test_us_quarter_matches_previous_fiscal_quarter_and_snapshot_is_idempotent(
    settings,
):
    database = Database(settings.workspace_root)
    database.initialize()
    database.upsert_financial_periods(
        [
            financial_period(
                "NVDA",
                "2026-04-26",
                "10-Q",
                "FY2027 Q1 (10-Q)",
                revenue_yoy_pct=85.23,
                net_profit_yoy_pct=210.63,
                gross_margin_pct=74.93,
                net_margin_pct=71.46,
                operating_cashflow=50_344_000_000.0,
                parent_net_profit=58_321_000_000.0,
                debt_asset_ratio_pct=24.67,
            ),
            financial_period(
                "NVDA",
                "2025-04-27",
                "10-Q",
                "FY2026 Q1 (10-Q)",
                revenue_yoy_pct=69.18,
                net_profit_yoy_pct=26.17,
                gross_margin_pct=60.52,
                net_margin_pct=42.61,
                operating_cashflow=27_414_000_000.0,
                parent_net_profit=18_775_000_000.0,
                debt_asset_ratio_pct=33.06,
            ),
        ]
    )
    service = EarningsQualityService(database)

    first = service.get_packet("NVDA")
    second = service.get_packet("NVDA")

    assert first["comparable_report"]["report_date_name"] == "FY2026 Q1 (10-Q)"
    assert first["overall_label"] == "增长与盈利兑现较一致"
    assert first["snapshot_id"] == second["snapshot_id"]
    with database.connect() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) AS count FROM earnings_quality_snapshots WHERE symbol = 'NVDA'"
            ).fetchone()["count"]
            == 1
        )
    documents = database.list_knowledge_documents(None, include_content=True)
    document = next(
        item for item in documents if item["source_key"] == "earnings-quality:NVDA"
    )
    assert "最新财报质量分析" in document["title"]
    assert "增长与盈利兑现较一致" in document["content"]
    preview = AgentService._render_preview(first)
    assert "FY2027 Q1" in preview
    assert "目标价" not in preview
    assert "BUY" not in preview
