from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.catalog import RESEARCH_TARGETS, normalize_symbol
from app.db import Database
from app.providers.us_fundamentals import USEquityFundamentalsProvider
from app.services.fundamentals import summarize_fundamentals
from app.utils import utc_now


def _is_older_than(value: str | None, seconds: int) -> bool:
    if not value:
        return True
    try:
        timestamp = datetime.fromisoformat(value).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return True
    return datetime.now(timezone.utc) - timestamp > timedelta(seconds=seconds)


class USEquityFundamentalsService:
    def __init__(self, database: Database, provider: USEquityFundamentalsProvider):
        self.database = database
        self.provider = provider

    @staticmethod
    def _cik(symbol: str) -> str:
        target = RESEARCH_TARGETS.get(symbol) or {}
        cik = str(target.get("cik") or "").strip()
        if not cik:
            raise ValueError("该美股尚未配置 SEC CIK")
        return cik

    def refresh_symbol(self, symbol: str) -> dict[str, Any]:
        canonical = normalize_symbol(symbol)
        if canonical.endswith((".SS", ".SZ")):
            raise ValueError("美股官方财务服务不支持 A 股证券")
        cik = self._cik(canonical)
        warnings = []
        source_status: dict[str, dict[str, Any]] = {}
        valuation_saved = False
        periods_saved = 0
        filings_saved = 0
        statement_details_saved = 0
        try:
            valuation = self.provider.fetch_valuation(canonical)
            self.database.save_valuation_snapshot(valuation)
            valuation_saved = True
        except Exception as exc:
            warnings.append(f"美股估值刷新未完成：{type(exc).__name__}")
        try:
            financials = self.provider.fetch_financial_periods(canonical, cik)
            periods_saved = self.database.upsert_financial_periods(
                financials["periods"]
            )
        except Exception as exc:
            warnings.append(f"SEC 财务刷新未完成：{type(exc).__name__}")
        fetch_details = getattr(self.provider, "fetch_statement_details", None)
        if callable(fetch_details):
            try:
                details = fetch_details(canonical, cik)
                statement_details_saved = (
                    self.database.upsert_financial_statement_details(
                        details["statements"]
                    )
                )
            except Exception as exc:
                warnings.append(f"SEC 详细三表刷新未完成：{type(exc).__name__}")
        try:
            filings = self.provider.fetch_filings(canonical, cik)
            filings_saved = self.database.upsert_news_items(filings)
            source_status["regulatory_filing"] = {
                "status": "ok",
                "items": len(filings),
                "polled_at": utc_now(),
            }
        except Exception as exc:
            warnings.append(f"SEC 监管文件刷新未完成：{type(exc).__name__}")
            source_status["regulatory_filing"] = {
                "status": "failed",
                "items": 0,
                "polled_at": utc_now(),
                "error_type": type(exc).__name__,
            }
        return {
            "symbol": canonical,
            "refreshed_at": utc_now(),
            "valuation_saved": valuation_saved,
            "financial_periods_saved": periods_saved,
            "financial_statement_details_saved": statement_details_saved,
            "regulatory_filings_saved": filings_saved,
            "sources": source_status,
            "warnings": warnings,
        }

    def get_packet(
        self, symbol: str, refresh_max_age_seconds: int = 900
    ) -> dict[str, Any]:
        canonical = normalize_symbol(symbol)
        self._cik(canonical)
        valuation = self.database.latest_valuation_snapshot(canonical)
        periods = self.database.list_financial_periods(canonical, limit=8)
        statement_details = self.database.list_financial_statement_details(
            canonical, limit=36
        )
        filings = self.database.list_news(
            canonical, limit=12, categories=("regulatory_filing",)
        )
        should_refresh = (
            valuation is None
            or not periods
            or not filings
            or (
                callable(getattr(self.provider, "fetch_statement_details", None))
                and not statement_details
            )
            or _is_older_than(
                valuation.get("fetched_at") if valuation else None,
                refresh_max_age_seconds,
            )
        )
        refresh_result = None
        if should_refresh:
            refresh_result = self.refresh_symbol(canonical)
            valuation = self.database.latest_valuation_snapshot(canonical)
            periods = self.database.list_financial_periods(canonical, limit=8)
            statement_details = self.database.list_financial_statement_details(
                canonical, limit=36
            )
            filings = self.database.list_news(
                canonical, limit=12, categories=("regulatory_filing",)
            )
        warnings = list(refresh_result.get("warnings", [])) if refresh_result else []
        if valuation:
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
            "regulatory_filings": filings,
            "summary": summarize_fundamentals(valuation, periods),
            "refresh": refresh_result,
            "warnings": list(dict.fromkeys(warnings)),
            "methodology": [
                "实时估值来自腾讯美股完整行情字段，市值统一换算为美元后入库。",
                "主要财务指标来自 SEC EDGAR Companyfacts，并区分 10-Q 财年累计与 10-K 年度口径。",
                "10-Q、10-K 与 8-K 监管文件来自 SEC submissions，并保留官方原文链接。",
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
                    if result["valuation_saved"]
                    or result["financial_periods_saved"]
                    or result["financial_statement_details_saved"]
                    or result["regulatory_filings_saved"]
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
