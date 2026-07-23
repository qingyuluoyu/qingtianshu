from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.catalog import normalize_symbol
from app.db import Database
from app.providers.fundamentals import AShareFundamentalsProvider
from app.services.live_market import market_quote_semantics
from app.utils import utc_now


def _is_older_than(value: str | None, seconds: int) -> bool:
    if not value:
        return True
    try:
        timestamp = datetime.fromisoformat(value).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return True
    return datetime.now(timezone.utc) - timestamp > timedelta(seconds=seconds)


def _ratio(numerator: Any, denominator: Any) -> float | None:
    if not isinstance(numerator, (int, float)) or not isinstance(
        denominator, (int, float)
    ):
        return None
    if denominator == 0:
        return None
    return round(float(numerator) / float(denominator), 3)


def _period_basis_label(period: dict[str, Any]) -> str:
    basis = period.get("period_basis")
    if basis == "annual":
        return "完整财政年度口径"
    if basis == "single_quarter":
        return "单季度口径"
    if basis == "year_to_date_cumulative":
        if str(period.get("report_date_name") or "").upper().find(" Q1 ") >= 0:
            return "财政年度累计口径（Q1 与单季度相同）"
        return "财政年度累计口径"
    return "报告期口径"


def summarize_fundamentals(
    valuation: dict[str, Any] | None, periods: list[dict[str, Any]]
) -> dict[str, Any]:
    latest = (
        {**periods[0], "period_basis_label": _period_basis_label(periods[0])}
        if periods
        else None
    )
    latest_annual = next(
        (
            {**item, "period_basis_label": _period_basis_label(item)}
            for item in periods
            if item.get("report_type") in {"年报", "10-K"}
        ),
        None,
    )
    cashflow_to_profit = None
    if latest:
        cashflow_to_profit = _ratio(
            latest.get("operating_cashflow"), latest.get("parent_net_profit")
        )
    facts = []
    if valuation:
        facts.append(
            {
                "kind": "valuation",
                "statement": (
                    f"TTM市盈率 {valuation.get('pe_ttm')}，"
                    f"市净率 {valuation.get('pb')}"
                ),
                "source": valuation.get("source"),
                "as_of": valuation.get("market_timestamp"),
            }
        )
    if latest:
        facts.extend(
            [
                {
                    "kind": "growth",
                    "statement": (
                        f"{latest.get('report_date_name')}营收同比 "
                        f"{latest.get('revenue_yoy_pct')}%，净利润同比 "
                        f"{latest.get('net_profit_yoy_pct')}%"
                    ),
                    "source": latest.get("source"),
                    "as_of": latest.get("report_date"),
                },
                {
                    "kind": "profitability",
                    "statement": (
                        f"加权ROE {latest.get('roe_weighted_pct')}%，"
                        f"毛利率 {latest.get('gross_margin_pct')}%，"
                        f"净利率 {latest.get('net_margin_pct')}%"
                    ),
                    "source": latest.get("source"),
                    "as_of": latest.get("report_date"),
                },
            ]
        )
    missing = []
    if valuation is None:
        missing.append("实时估值快照不可用")
    if latest is None:
        missing.append("结构化财务报告期不可用")
    missing.extend(["行业可比估值分位尚未接入", "分析师一致预期尚未接入"])
    return {
        "latest_report": latest,
        "latest_annual_report": latest_annual,
        "operating_cashflow_to_net_profit": cashflow_to_profit,
        "facts": facts,
        "missing_context": missing,
        "interpretation_rules": [
            "估值倍数只描述当前口径，不据此单独判断便宜或昂贵。",
            "同比增长、ROE、利润率和现金流必须结合报告期口径解释。",
            "结构化财务是较强证据，但不能替代公司公告或监管文件原文与行业供需验证。",
        ],
    }


class FundamentalsService:
    def __init__(self, database: Database, provider: AShareFundamentalsProvider):
        self.database = database
        self.provider = provider

    def refresh_symbol(self, symbol: str) -> dict[str, Any]:
        canonical = normalize_symbol(symbol)
        if not canonical.endswith((".SS", ".SZ", ".BJ")):
            raise ValueError("结构化财务与估值只支持 A 股证券")
        warnings = []
        valuation_saved = False
        periods_saved = 0
        statement_details_saved = 0
        try:
            valuation = self.provider.fetch_valuation(canonical)
            self.database.save_valuation_snapshot(valuation)
            valuation_saved = True
        except Exception as exc:
            warnings.append(f"valuation 数据源失败：{type(exc).__name__}")
        try:
            financials = self.provider.fetch_financial_periods(canonical)
            periods_saved = self.database.upsert_financial_periods(
                financials["periods"]
            )
        except Exception as exc:
            warnings.append(f"financial 数据源失败：{type(exc).__name__}")
        fetch_details = getattr(self.provider, "fetch_statement_details", None)
        if callable(fetch_details):
            try:
                details = fetch_details(canonical)
                statement_details_saved = self.database.upsert_financial_statement_details(
                    details["statements"]
                )
            except Exception as exc:
                warnings.append(f"detailed financial 数据源失败：{type(exc).__name__}")
        return {
            "symbol": canonical,
            "refreshed_at": utc_now(),
            "valuation_saved": valuation_saved,
            "financial_periods_saved": periods_saved,
            "financial_statement_details_saved": statement_details_saved,
            "warnings": warnings,
        }

    def get_packet(
        self, symbol: str, refresh_max_age_seconds: int = 600
    ) -> dict[str, Any]:
        canonical = normalize_symbol(symbol)
        valuation = self.database.latest_valuation_snapshot(canonical)
        periods = self.database.list_financial_periods(canonical, limit=8)
        statement_details = self.database.list_financial_statement_details(
            canonical, limit=36
        )
        supports_details = callable(
            getattr(self.provider, "fetch_statement_details", None)
        )
        should_refresh = (
            valuation is None
            or not periods
            or (supports_details and not statement_details)
            or _is_older_than(valuation.get("fetched_at") if valuation else None, refresh_max_age_seconds)
        )
        refresh_result = None
        if should_refresh:
            refresh_result = self.refresh_symbol(canonical)
            valuation = self.database.latest_valuation_snapshot(canonical)
            periods = self.database.list_financial_periods(canonical, limit=8)
            statement_details = self.database.list_financial_statement_details(
                canonical, limit=36
            )
        warnings = list(refresh_result.get("warnings", [])) if refresh_result else []
        if valuation:
            valuation = {
                **valuation,
                **market_quote_semantics(
                    "china", valuation.get("market_timestamp")
                ),
            }
            warnings.extend(valuation.get("warnings", []))
        if periods:
            warnings.extend(periods[0].get("warnings", []))
        return {
            "symbol": canonical,
            "generated_at": utc_now(),
            "valuation": valuation,
            "financial_periods": periods,
            "statement_detail_coverage": {
                "rows": len(statement_details),
                "periods": len(
                    {
                        (item["report_date"], item["report_type"])
                        for item in statement_details
                    }
                ),
                "statement_types": sorted(
                    {item["statement_type"] for item in statement_details}
                ),
            },
            "summary": summarize_fundamentals(valuation, periods),
            "refresh": refresh_result,
            "warnings": list(dict.fromkeys(warnings)),
            "methodology": [
                "实时估值来自腾讯完整行情字段，并保留 TTM、动态和静态三种市盈率口径。",
                "主要财务指标来自东方财富 F10 结构化报告期数据。",
                "所有数值先由确定性代码解析和存储，再交给 Agent 解释。",
            ],
        }

    def refresh_symbols(self, symbols: list[str]) -> dict[str, Any]:
        results = []
        for symbol in sorted(set(symbols)):
            try:
                result = self.refresh_symbol(symbol)
                status = (
                    "ok"
                    if result["valuation_saved"] or result["financial_periods_saved"]
                    or result["financial_statement_details_saved"]
                    else "failed"
                )
                results.append({"status": status, **result})
            except Exception as exc:
                results.append(
                    {
                        "symbol": symbol,
                        "status": "failed",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
        return {
            "requested": len(set(symbols)),
            "completed": sum(item["status"] == "ok" for item in results),
            "results": results,
        }
