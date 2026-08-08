from __future__ import annotations

from collections import defaultdict
from typing import Any, Protocol

from app.catalog import RESEARCH_TARGETS, normalize_symbol
from app.utils import utc_now


class StockComparisonEvidenceBuilder(Protocol):
    def build(self, user_id: str, symbol: str) -> dict[str, Any]: ...


class StockComparisonService:
    """Build a 2-5 stock packet without mixing incompatible financial periods."""

    CONTRACT_VERSION = "stock_comparison_v1"
    MIN_TARGETS = 2
    MAX_TARGETS = 5

    def __init__(self, evidence_service: StockComparisonEvidenceBuilder):
        self.evidence_service = evidence_service

    def build(
        self,
        user_id: str,
        symbols: list[str],
        *,
        question: str | None = None,
    ) -> dict[str, Any]:
        canonical_symbols = self._canonical_symbols(symbols)
        if len(canonical_symbols) < self.MIN_TARGETS:
            raise ValueError("多股比较至少需要 2 只股票")
        if len(canonical_symbols) > self.MAX_TARGETS:
            raise ValueError("多股比较一次最多支持 5 只股票")

        items: list[dict[str, Any]] = []
        unavailable_symbols: list[str] = []
        for symbol in canonical_symbols:
            try:
                evidence = self.evidence_service.build(user_id, symbol)
            except Exception:
                unavailable_symbols.append(symbol)
                items.append(
                    {
                        "symbol": symbol,
                        "name": self._display_name(symbol, {}),
                        "market": self._market_label(symbol),
                        "status": "unavailable",
                        "snapshot": {},
                        "evidence": {},
                        "limitations": ["该标的本轮未形成可比较的确定性证据。"],
                    }
                )
                continue

            items.append(
                {
                    "symbol": symbol,
                    "name": self._display_name(symbol, evidence),
                    "market": self._market_label(symbol),
                    "status": "available",
                    "snapshot": self._comparison_snapshot(evidence),
                    "evidence": self._compact_evidence(evidence),
                    "limitations": self._item_limitations(evidence),
                }
            )

        available = [item for item in items if item["status"] == "available"]
        basis = self._comparison_basis(available)
        warnings = []
        if unavailable_symbols:
            warnings.append(
                "以下标的本轮证据未完整形成："
                + "、".join(
                    self._display_name(symbol, {}) for symbol in unavailable_symbols
                )
                + "。其余标的仍保留可用结果。"
            )
        if basis["financial"]["status"] != "exact_common_period":
            warnings.append(
                "各公司最新财务披露未形成完全相同的报告期，经营指标只能在明确列出的同口径组内比较。"
            )
        if basis["currency"]["status"] != "single_currency":
            warnings.append(
                "标的包含不同币种；股价、市值和绝对金额不得直接横向排序。"
            )

        return {
            "contract_version": self.CONTRACT_VERSION,
            "type": "stock_comparison",
            "status": (
                "available"
                if len(available) == len(canonical_symbols)
                else "partial"
                if available
                else "unavailable"
            ),
            "generated_at": utc_now(),
            "user_question": str(question or "").strip(),
            "symbols": canonical_symbols,
            "targets": [
                {"symbol": item["symbol"], "name": item["name"]} for item in items
            ],
            "available_symbols": [item["symbol"] for item in available],
            "unavailable_symbols": unavailable_symbols,
            "comparison_focus": self._comparison_focus(question),
            "comparison_basis": basis,
            "items": items,
            "warnings": warnings,
            "boundary": (
                "该比较用于统一整理已披露事实、差异、反方证据和核验缺口；"
                "不构成公司排名、目标价或买卖建议。"
            ),
        }

    @staticmethod
    def _canonical_symbols(symbols: list[str]) -> list[str]:
        output: list[str] = []
        for raw in symbols:
            canonical = normalize_symbol(raw)
            if canonical not in output:
                output.append(canonical)
        return output

    @staticmethod
    def _market_label(symbol: str) -> str:
        if symbol.endswith((".SS", ".SZ")):
            return "A股"
        if symbol.endswith(".HK"):
            return "港股"
        return "美股/海外市场"

    @staticmethod
    def _display_name(symbol: str, evidence: dict[str, Any]) -> str:
        configured = str((RESEARCH_TARGETS.get(symbol) or {}).get("name") or "")
        valuation = (evidence.get("fundamentals") or {}).get("valuation") or {}
        return str(
            configured
            or evidence.get("display_name")
            or valuation.get("name")
            or symbol
        )

    @staticmethod
    def _comparison_snapshot(evidence: dict[str, Any]) -> dict[str, Any]:
        fundamentals = evidence.get("fundamentals") or {}
        valuation = fundamentals.get("valuation") or evidence.get("current_quote") or {}
        summary = fundamentals.get("summary") or {}
        latest_report = summary.get("latest_report") or {}
        earnings_quality = evidence.get("earnings_quality") or {}
        financial_drivers = evidence.get("financial_drivers") or {}
        debate = evidence.get("evidence_debate") or {}
        outlook = evidence.get("conditional_outlook") or {}
        return {
            "quote": {
                key: valuation.get(key)
                for key in (
                    "price",
                    "currency",
                    "pct_change",
                    "market_timestamp",
                    "quote_basis",
                    "quote_label",
                )
                if valuation.get(key) is not None
            },
            "valuation": {
                key: valuation.get(key)
                for key in (
                    "pe_ttm",
                    "pb",
                    "ps_ttm",
                    "total_market_cap",
                    "currency",
                    "market_timestamp",
                )
                if valuation.get(key) is not None
            },
            "financial": {
                key: latest_report.get(key)
                for key in (
                    "report_date",
                    "report_date_name",
                    "report_type",
                    "period_basis",
                    "period_basis_label",
                    "notice_date",
                    "currency",
                    "revenue_yoy_pct",
                    "net_profit_yoy_pct",
                    "roe_weighted_pct",
                    "gross_margin_pct",
                    "net_margin_pct",
                    "operating_cashflow",
                    "parent_net_profit",
                )
                if latest_report.get(key) is not None
            }
            | {
                "operating_cashflow_to_net_profit": summary.get(
                    "operating_cashflow_to_net_profit"
                )
            },
            "earnings_quality": {
                key: earnings_quality.get(key)
                for key in (
                    "status",
                    "overall_label",
                    "confidence",
                    "summary",
                    "supports",
                    "contradictions",
                    "review_points",
                    "boundary",
                )
                if earnings_quality.get(key) not in (None, [], {}, "")
            },
            "financial_drivers": {
                key: financial_drivers.get(key)
                for key in (
                    "status",
                    "overall_label",
                    "summary",
                    "confirmed_mechanical_drivers",
                    "plausible_clues",
                    "unresolved_causes",
                    "review_points",
                    "boundary",
                )
                if financial_drivers.get(key) not in (None, [], {}, "")
            },
            "counter_evidence": [
                *list(debate.get("bear_case") or [])[:4],
                *list(debate.get("risk_committee") or [])[:3],
            ],
            "invalidation": outlook.get("invalidation"),
        }

    @staticmethod
    def _compact_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
        def compact_events(items: list[dict[str, Any]] | None, limit: int) -> list[dict[str, Any]]:
            return [
                {
                    key: item.get(key)
                    for key in (
                        "category",
                        "title",
                        "summary",
                        "published_at",
                        "notice_date",
                        "form",
                        "filing_date",
                        "source_url",
                        "url",
                    )
                    if item.get(key) is not None
                }
                for item in (items or [])[:limit]
                if isinstance(item, dict)
            ]

        fundamentals = evidence.get("fundamentals") or {}
        information = evidence.get("a_share_information") or {}
        global_information = evidence.get("global_information") or {}
        business = evidence.get("business_structure") or {}
        expectations = evidence.get("analyst_expectations") or {}
        events = evidence.get("event_timeline") or {}
        return {
            key: evidence.get(key)
            for key in (
                "type",
                "generated_at",
                "symbol",
                "display_name",
                "current_quote",
                "metrics",
                "provenance",
                "user_thesis",
                "evidence_debate",
                "conditional_outlook",
            )
            if evidence.get(key) not in (None, [], {}, "")
        } | {
            "fundamentals": {
                "valuation": fundamentals.get("valuation"),
                "summary": fundamentals.get("summary"),
                "regulatory_filings": compact_events(
                    fundamentals.get("regulatory_filings"), 3
                ),
            },
            "earnings_quality": evidence.get("earnings_quality") or {},
            "financial_drivers": evidence.get("financial_drivers") or {},
            "business_structure": {
                key: business.get(key)
                for key in (
                    "status",
                    "anchor_report_date",
                    "summary",
                    "dimensions",
                    "key_changes",
                    "review_points",
                    "boundary",
                )
                if business.get(key) not in (None, [], {}, "")
            },
            "analyst_expectations": {
                key: expectations.get(key)
                for key in (
                    "status",
                    "as_of_date",
                    "rating_statement",
                    "forecast_statement",
                    "revision",
                    "review_points",
                    "boundary",
                )
                if expectations.get(key) not in (None, [], {}, "")
            },
            "event_timeline": {
                "status": events.get("status"),
                "as_of_date": events.get("as_of_date"),
                "events": list(events.get("events") or [])[:8],
                "risk_events": list(events.get("risk_events") or [])[:4],
                "boundary": events.get("boundary"),
            },
            "company_information": {
                "announcements": compact_events(information.get("announcements"), 3),
                "news": compact_events(information.get("news"), 3),
                "global_news": compact_events(global_information.get("news"), 4),
            },
        }

    @staticmethod
    def _item_limitations(evidence: dict[str, Any]) -> list[str]:
        limitations: list[str] = []
        fundamentals = evidence.get("fundamentals") or {}
        summary = fundamentals.get("summary") or {}
        limitations.extend(str(item) for item in (summary.get("missing_context") or []))
        limitations.extend(str(item) for item in (evidence.get("warnings") or []))
        output: list[str] = []
        for item in limitations:
            cleaned = " ".join(item.split())
            if any(
                term in cleaned
                for term in (
                    "数据源",
                    "刷新未完成",
                    "Provider",
                    "Error",
                    "Exception",
                    "接口",
                    "缓存",
                )
            ):
                cleaned = "对应研究维度本轮未完整形成，不能据此横向比较。"
            if cleaned and cleaned not in output:
                output.append(cleaned)
        return output[:8]

    @staticmethod
    def _comparison_basis(items: list[dict[str, Any]]) -> dict[str, Any]:
        financial_groups: dict[tuple[str, str], list[str]] = defaultdict(list)
        currency_groups: dict[str, list[str]] = defaultdict(list)
        valuation_times: dict[str, str | None] = {}
        missing_financial: list[str] = []
        for item in items:
            symbol = str(item["symbol"])
            snapshot = item.get("snapshot") or {}
            financial = snapshot.get("financial") or {}
            report_date = str(financial.get("report_date") or "").strip()
            period_basis = str(financial.get("period_basis") or "").strip()
            if report_date and period_basis:
                financial_groups[(report_date, period_basis)].append(symbol)
            else:
                missing_financial.append(symbol)
            quote = snapshot.get("quote") or {}
            valuation = snapshot.get("valuation") or {}
            currency = str(
                quote.get("currency") or valuation.get("currency") or "unknown"
            )
            currency_groups[currency].append(symbol)
            valuation_times[symbol] = valuation.get("market_timestamp") or quote.get(
                "market_timestamp"
            )

        group_rows = [
            {
                "report_date": report_date,
                "period_basis": period_basis,
                "symbols": symbols,
                "comparable_count": len(symbols),
            }
            for (report_date, period_basis), symbols in sorted(financial_groups.items())
        ]
        available_count = len(items)
        exact_common = (
            group_rows[0]
            if available_count
            and len(group_rows) == 1
            and group_rows[0]["comparable_count"] == available_count
            and not missing_financial
            else None
        )
        financial_status = (
            "exact_common_period"
            if exact_common
            else "partial_exact_groups"
            if any(row["comparable_count"] >= 2 for row in group_rows)
            else "not_aligned"
        )
        return {
            "financial": {
                "status": financial_status,
                "exact_common_period": exact_common,
                "groups": group_rows,
                "missing_symbols": missing_financial,
                "rule": (
                    "营收增速、利润增速、利润率、ROE 与现金流只在 report_date 和 period_basis 同时一致时横向比较。"
                ),
            },
            "valuation": {
                "status": (
                    "same_timestamp"
                    if valuation_times
                    and len({value for value in valuation_times.values() if value}) == 1
                    and all(valuation_times.values())
                    else "latest_snapshot_by_market"
                ),
                "timestamps": valuation_times,
                "rule": "估值使用各市场最新可用快照，必须逐只标注时间，不冒充同一成交时刻。",
            },
            "currency": {
                "status": (
                    "single_currency" if len(currency_groups) <= 1 else "mixed_currency"
                ),
                "groups": [
                    {"currency": currency, "symbols": symbols}
                    for currency, symbols in sorted(currency_groups.items())
                ],
                "rule": "不同币种的股价、市值与绝对金额不直接排序；跨市场优先比较无量纲比例和业务证据。",
            },
        }

    @staticmethod
    def _comparison_focus(question: str | None) -> list[str]:
        text = str(question or "").casefold()
        focus: list[str] = []
        rules = (
            ("盈利质量", ("盈利质量", "财报质量", "利润含金量", "现金流")),
            ("估值", ("估值", "市盈率", "市净率", "pe", "pb")),
            ("经营增长", ("营收", "利润增长", "增速", "roe", "毛利率")),
            ("行业与业务", ("行业", "业务结构", "主营", "竞争力")),
            ("事件与风险", ("风险", "反方", "事件", "公告", "催化")),
        )
        for label, terms in rules:
            if any(term in text for term in terms):
                focus.append(label)
        return focus or ["经营增长", "盈利质量", "估值", "事件与风险"]
