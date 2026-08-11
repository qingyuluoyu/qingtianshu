from __future__ import annotations

import pytest

from app.services.stock_comparison import StockComparisonService


def packet(
    symbol: str,
    name: str,
    *,
    report_date: str,
    report_name: str,
    currency: str,
    pe_ttm: float,
) -> dict:
    return {
        "type": "stock_research",
        "symbol": symbol,
        "display_name": name,
        "generated_at": "2026-07-23T01:00:00+00:00",
        "current_quote": {
            "name": name,
            "price": 100.0,
            "currency": currency,
            "pct_change": 1.2,
            "market_timestamp": "2026-07-23T09:45:00+08:00",
        },
        "fundamentals": {
            "valuation": {
                "name": name,
                "price": 100.0,
                "currency": currency,
                "pe_ttm": pe_ttm,
                "pb": 3.2,
                "market_timestamp": "2026-07-23T09:45:00+08:00",
            },
            "summary": {
                "latest_report": {
                    "report_date": report_date,
                    "report_date_name": report_name,
                    "report_type": "一季报" if currency == "CNY" else "10-Q",
                    "period_basis": "year_to_date_cumulative",
                    "period_basis_label": "财政年度累计口径",
                    "revenue_yoy_pct": 15.0,
                    "net_profit_yoy_pct": 12.0,
                    "gross_margin_pct": 40.0,
                    "operating_cashflow": 12.0,
                    "parent_net_profit": 10.0,
                },
                "operating_cashflow_to_net_profit": 1.2,
                "missing_context": [],
            },
        },
        "earnings_quality": {
            "status": "available",
            "summary": f"{name}盈利质量摘要",
            "contradictions": ["现金流与利润仍需继续核验"],
        },
        "financial_drivers": {
            "status": "available",
            "summary": f"{name}利润驱动摘要",
        },
        "evidence_debate": {
            "bear_case": [{"claim": f"{name}反方证据"}],
            "risk_committee": [],
        },
        "conditional_outlook": {"invalidation": f"{name}失效条件"},
        "warnings": [],
    }


class FakeEvidenceService:
    def __init__(self, packets: dict[str, dict], failing: set[str] | None = None):
        self.packets = packets
        self.failing = failing or set()

    def build(self, user_id: str, symbol: str) -> dict:
        assert user_id
        if symbol in self.failing:
            raise RuntimeError("provider detail must stay private")
        return self.packets[symbol]


def test_comparison_groups_exact_financial_periods_and_mixed_currencies():
    packets = {
        "000063.SZ": packet(
            "000063.SZ",
            "中兴通讯",
            report_date="2026-03-31",
            report_name="2026一季报",
            currency="CNY",
            pe_ttm=22.0,
        ),
        "300308.SZ": packet(
            "300308.SZ",
            "中际旭创",
            report_date="2026-03-31",
            report_name="2026一季报",
            currency="CNY",
            pe_ttm=35.0,
        ),
        "NVDA": packet(
            "NVDA",
            "英伟达",
            report_date="2026-04-26",
            report_name="FY2027 Q1 (10-Q)",
            currency="USD",
            pe_ttm=31.0,
        ),
    }
    result = StockComparisonService(FakeEvidenceService(packets)).build(
        "user-1",
        ["000063", "300308", "NVDA"],
        question="比较盈利质量、估值和风险",
    )

    assert result["status"] == "available"
    assert result["symbols"] == ["000063.SZ", "300308.SZ", "NVDA"]
    assert result["comparison_focus"] == ["盈利质量", "估值", "事件与风险"]
    financial = result["comparison_basis"]["financial"]
    assert financial["status"] == "partial_exact_groups"
    assert financial["exact_common_period"] is None
    a_share_group = next(
        item for item in financial["groups"] if item["report_date"] == "2026-03-31"
    )
    assert a_share_group["symbols"] == ["000063.SZ", "300308.SZ"]
    assert result["comparison_basis"]["currency"]["status"] == "mixed_currency"
    assert any("不同币种" in item for item in result["warnings"])


def test_comparison_keeps_partial_result_when_one_symbol_fails():
    packets = {
        "000063.SZ": packet(
            "000063.SZ",
            "中兴通讯",
            report_date="2026-03-31",
            report_name="2026一季报",
            currency="CNY",
            pe_ttm=22.0,
        ),
        "300308.SZ": packet(
            "300308.SZ",
            "中际旭创",
            report_date="2026-03-31",
            report_name="2026一季报",
            currency="CNY",
            pe_ttm=35.0,
        ),
    }
    result = StockComparisonService(
        FakeEvidenceService(packets, failing={"300308.SZ"})
    ).build("user-1", ["000063", "300308"])

    assert result["status"] == "partial"
    assert result["available_symbols"] == ["000063.SZ"]
    assert result["unavailable_symbols"] == ["300308.SZ"]
    assert "RuntimeError" not in str(result)


def test_comparison_rejects_out_of_range_target_count():
    service = StockComparisonService(FakeEvidenceService({}))

    with pytest.raises(ValueError, match="至少需要 2"):
        service.build("user-1", ["000063"])
    with pytest.raises(ValueError, match="最多支持 5"):
        service.build(
            "user-1",
            ["000063", "300308", "600519", "300750", "000001", "600000"],
        )
