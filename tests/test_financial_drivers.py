from __future__ import annotations

import pytest

from app.services.financial_drivers import FinancialDriverAnalysisService


def test_a_share_profit_cashflow_and_working_capital_drivers_are_separated(app):
    refreshed = app.state.fundamentals.refresh_symbol("000063.SZ")
    assert refreshed["financial_statement_details_saved"] == 6

    packet = FinancialDriverAnalysisService(app.state.database).get_packet("000063.SZ")

    assert packet["status"] == "available"
    assert packet["overall_label"] == "利润与经营现金流双重承压"
    assert packet["confidence"] == "high"
    assert packet["latest_period"]["report_date_name"] == "2026一季报"
    assert packet["comparable_period"]["report_date_name"] == "2025一季报"
    assert packet["profit_bridge"]["gross_profit_change"] == pytest.approx(
        -200_000_000.0
    )
    assert packet["profit_bridge"]["gross_margin_change_pp"] == pytest.approx(-5.0)
    assert packet["profit_bridge"][
        "unexplained_operating_profit_change"
    ] == pytest.approx(-300_000_000.0)

    drivers = {item["key"]: item for item in packet["confirmed_mechanical_drivers"]}
    assert drivers["gross_profit_revenue_scale_effect"]["amount"] == pytest.approx(
        400_000_000.0
    )
    assert drivers["gross_profit_margin_effect"]["amount"] == pytest.approx(
        -600_000_000.0
    )
    assert all(
        item["attribution_level"] == "confirmed_mechanical_driver"
        for item in drivers.values()
    )

    clues = {item["key"]: item for item in packet["plausible_clues"]}
    assert "accounts_receivable" in clues
    assert "inventory" in clues
    assert "operating_cashflow_coverage" in clues
    assert packet["cashflow_analysis"][
        "cash_received_from_sales_ratio_change_pp"
    ] == pytest.approx(-6.894, abs=0.001)
    assert all(item["attribution_level"] == "plausible_clue" for item in clues.values())
    assert any("尚未由三表科目确认" in item for item in packet["unresolved_causes"])

    with app.state.database.connect() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) AS count FROM financial_statement_details WHERE symbol = ?",
                ("000063.SZ",),
            ).fetchone()["count"]
            == 6
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) AS count FROM financial_driver_snapshots WHERE symbol = ?",
                ("000063.SZ",),
            ).fetchone()["count"]
            == 1
        )
    documents = app.state.database.list_knowledge_documents(None)
    assert any(
        item["source_key"] == "financial-drivers:000063.SZ" for item in documents
    )


def test_us_companyfacts_details_support_same_driver_framework(app):
    refreshed = app.state.us_fundamentals.refresh_symbol("NVDA")
    assert refreshed["financial_statement_details_saved"] == 6

    packet = FinancialDriverAnalysisService(app.state.database).get_packet("NVDA")

    assert packet["status"] == "available"
    assert packet["overall_label"] == "利润与经营现金流共同改善"
    assert packet["latest_period"]["fiscal_period"] == "Q1"
    assert packet["comparable_period"]["fiscal_period"] == "Q1"
    assert packet["cashflow_analysis"]["operating_cashflow_change"] == pytest.approx(
        22_930_000_000.0
    )
    expense_keys = {item["key"] for item in packet["expense_analysis"]}
    assert "selling_general_admin_expense" in expense_keys
    assert "research_expense" in expense_keys


def test_driver_analysis_refuses_to_compare_non_matching_periods(settings):
    from app.db import Database

    database = Database(settings.workspace_root)
    database.initialize()
    database.upsert_financial_statement_details(
        [
            {
                "symbol": "000063.SZ",
                "name": "中兴通讯",
                "report_date": "2026-06-30",
                "report_type": "中报",
                "report_date_name": "2026中报",
                "notice_date": "2026-08-20",
                "currency": "CNY",
                "fiscal_period": "H1",
                "period_basis": "year_to_date_cumulative",
                "statement_type": "income",
                "fields": {"revenue": 10.0, "parent_net_profit": 1.0},
                "source": "test",
                "source_url": "https://example.invalid",
                "warnings": [],
                "fetched_at": "2026-08-20T00:00:00+00:00",
            },
            {
                "symbol": "000063.SZ",
                "name": "中兴通讯",
                "report_date": "2025-03-31",
                "report_type": "一季报",
                "report_date_name": "2025一季报",
                "notice_date": "2025-04-20",
                "currency": "CNY",
                "fiscal_period": "Q1",
                "period_basis": "year_to_date_cumulative",
                "statement_type": "income",
                "fields": {"revenue": 8.0, "parent_net_profit": 0.8},
                "source": "test",
                "source_url": "https://example.invalid",
                "warnings": [],
                "fetched_at": "2025-04-20T00:00:00+00:00",
            },
        ]
    )

    packet = FinancialDriverAnalysisService(database).get_packet(
        "000063.SZ", persist=False
    )

    assert packet["status"] == "insufficient"
    assert packet["comparable_period"] is None
    assert "上一年度同类报告期" in packet["summary"]
