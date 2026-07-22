from __future__ import annotations

from datetime import date, datetime
import re
from typing import Any, Callable, Iterable
from zoneinfo import ZoneInfo

import requests

from app.catalog import normalize_symbol
from app.providers.market import ProviderError
from app.utils import utc_now


_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
_SEC_FORMS = {"10-Q", "10-K"}
_FILING_FORMS = {"10-Q", "10-K", "8-K"}

_DURATION_CONCEPTS = {
    "revenue": (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
    ),
    "net_income": ("NetIncomeLoss",),
    "eps_diluted": ("EarningsPerShareDiluted",),
    "gross_profit": ("GrossProfit",),
    "operating_cashflow": ("NetCashProvidedByUsedInOperatingActivities",),
}
_INSTANT_CONCEPTS = {
    "total_assets": ("Assets",),
    "total_liabilities": ("Liabilities",),
    "total_equity": ("StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"),
}

_DETAIL_DURATION_CONCEPTS = {
    "revenue": _DURATION_CONCEPTS["revenue"],
    "cost_of_revenue": (
        "CostOfRevenue",
        "CostOfGoodsAndServiceExcludingDepreciationDepletionAndAmortization",
    ),
    "gross_profit": _DURATION_CONCEPTS["gross_profit"],
    "operating_profit": ("OperatingIncomeLoss",),
    "selling_general_admin_expense": ("SellingGeneralAndAdministrativeExpense",),
    "research_expense": ("ResearchAndDevelopmentExpense",),
    "finance_expense": ("InterestExpenseNonOperating", "InterestExpense"),
    "total_profit": (
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
    ),
    "income_tax": ("IncomeTaxExpenseBenefit",),
    "parent_net_profit": _DURATION_CONCEPTS["net_income"],
    "operating_cashflow": _DURATION_CONCEPTS["operating_cashflow"],
    "investing_cashflow": ("NetCashProvidedByUsedInInvestingActivities",),
    "financing_cashflow": ("NetCashProvidedByUsedInFinancingActivities",),
    "capital_expenditure_proxy": ("PaymentsToAcquirePropertyPlantAndEquipment",),
}

_DETAIL_INSTANT_CONCEPTS = {
    "accounts_receivable": (
        "AccountsReceivableNetCurrent",
        "AccountsNotesAndLoansReceivableNetCurrent",
    ),
    "inventory": ("InventoryNet",),
    "accounts_payable": ("AccountsPayableCurrent",),
    "cash_and_equivalents": (
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ),
    "short_term_borrowings": ("ShortTermBorrowings", "ShortTermDebtCurrent"),
    "fixed_assets": ("PropertyPlantAndEquipmentNet",),
    "total_assets": _INSTANT_CONCEPTS["total_assets"],
    "total_liabilities": _INSTANT_CONCEPTS["total_liabilities"],
    "total_equity": _INSTANT_CONCEPTS["total_equity"],
}


def _number(value: Any, scale: float = 1.0) -> float | None:
    if value in (None, "", "--"):
        return None
    try:
        return round(float(value) * scale, 6)
    except (TypeError, ValueError):
        return None


def _parse_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _pct_change(current: Any, previous: Any) -> float | None:
    if not isinstance(current, (int, float)) or not isinstance(previous, (int, float)):
        return None
    if previous == 0:
        return None
    return round((float(current) / float(previous) - 1.0) * 100.0, 3)


def _ratio_pct(numerator: Any, denominator: Any) -> float | None:
    if not isinstance(numerator, (int, float)) or not isinstance(
        denominator, (int, float)
    ):
        return None
    if denominator == 0:
        return None
    return round(float(numerator) / float(denominator) * 100.0, 3)


def _fact_rows(payload: dict[str, Any], concept: str, unit: str) -> list[dict[str, Any]]:
    fact = ((payload.get("facts") or {}).get("us-gaap") or {}).get(concept) or {}
    units = fact.get("units") or {}
    rows = units.get(unit) or []
    return [row for row in rows if row.get("form") in _SEC_FORMS]


def _duration_days(row: dict[str, Any]) -> int:
    start = _parse_date(row.get("start"))
    end = _parse_date(row.get("end"))
    if start is None or end is None:
        return -1
    return (end - start).days


def _report_candidates(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for concept in _DURATION_CONCEPTS["revenue"]:
        rows.extend(_fact_rows(payload, concept, "USD"))

    by_accession: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        accession = str(row.get("accn") or "")
        if accession and row.get("end") and row.get("filed"):
            by_accession.setdefault(accession, []).append(row)

    candidates = []
    for accession, accession_rows in by_accession.items():
        report_end = max(str(row["end"]) for row in accession_rows)
        primary = [row for row in accession_rows if row.get("end") == report_end]
        if not primary:
            continue
        representative = max(primary, key=_duration_days)
        candidates.append(
            {
                "accession": accession,
                "end": report_end,
                "filed": str(representative.get("filed")),
                "form": str(representative.get("form")),
                "fy": representative.get("fy"),
                "fp": str(representative.get("fp") or ""),
            }
        )

    latest_by_period: dict[tuple[str, str, str], dict[str, Any]] = {}
    for item in candidates:
        key = (item["form"], item["end"], item["fp"])
        previous = latest_by_period.get(key)
        if previous is None or (item["filed"], item["accession"]) > (
            previous["filed"],
            previous["accession"],
        ):
            latest_by_period[key] = item
    return sorted(
        latest_by_period.values(),
        key=lambda item: (item["end"], item["filed"], item["accession"]),
        reverse=True,
    )


def _select_fact(
    payload: dict[str, Any],
    concepts: Iterable[str],
    unit: str,
    report: dict[str, Any],
    *,
    duration: bool,
) -> float | None:
    for concept in concepts:
        matching = [
            row
            for row in _fact_rows(payload, concept, unit)
            if row.get("accn") == report["accession"]
            and row.get("end") == report["end"]
        ]
        if not matching:
            continue
        selected = max(matching, key=_duration_days) if duration else matching[-1]
        value = _number(selected.get("val"))
        if value is not None:
            return value
    return None


def _find_comparable(
    current: dict[str, Any], periods: list[dict[str, Any]]
) -> dict[str, Any] | None:
    current_end = _parse_date(current.get("report_date"))
    if current_end is None:
        return None
    matches = []
    for item in periods:
        if item is current or item.get("_fiscal_period") != current.get("_fiscal_period"):
            continue
        older_end = _parse_date(item.get("report_date"))
        if older_end is None or older_end >= current_end:
            continue
        delta = (current_end - older_end).days
        if 300 <= delta <= 430:
            matches.append((abs(delta - 365), item))
    return min(matches, key=lambda pair: pair[0])[1] if matches else None


class USEquityFundamentalsProvider:
    COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
    SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
    TENCENT_QUOTE_URL = "https://qt.gtimg.cn/q=us{symbol}"

    def __init__(
        self,
        sec_user_agent: str,
        http_get: Callable[..., Any] = requests.get,
    ):
        self.sec_user_agent = sec_user_agent.strip()
        self.http_get = http_get

    def _sec_headers(self) -> dict[str, str]:
        if not self.sec_user_agent:
            raise ProviderError("SEC_USER_AGENT 未配置")
        return {
            "User-Agent": self.sec_user_agent,
            "Accept": "application/json",
            "Accept-Encoding": "gzip, deflate",
        }

    @staticmethod
    def _identity(symbol: str) -> str:
        canonical = normalize_symbol(symbol)
        if canonical.endswith((".SS", ".SZ")):
            raise ProviderError("SEC 与美股估值源不用于 A 股证券")
        return canonical

    def fetch_valuation(self, symbol: str) -> dict[str, Any]:
        canonical = self._identity(symbol)
        url = self.TENCENT_QUOTE_URL.format(symbol=canonical)
        response = self.http_get(
            url,
            headers={"User-Agent": _BROWSER_UA, "Referer": "https://gu.qq.com/"},
            timeout=15,
        )
        response.raise_for_status()
        content = response.content.decode("gb18030", errors="replace").strip()
        match = re.search(r'=\s*"(.*)";?$', content)
        if not match:
            raise ProviderError("腾讯美股估值行情格式无法识别")
        fields = match.group(1).split("~")
        if len(fields) <= 63 or canonical not in str(fields[2]).upper():
            raise ProviderError("腾讯美股估值行情字段不完整")

        market_timestamp = None
        try:
            market_timestamp = (
                datetime.strptime(fields[30], "%Y-%m-%d %H:%M:%S")
                .replace(tzinfo=ZoneInfo("America/New_York"))
                .isoformat(timespec="seconds")
            )
        except (TypeError, ValueError):
            pass
        if market_timestamp is None:
            raise ProviderError("腾讯美股估值行情缺少市场时间")

        fetched_at = utc_now()
        valuation = {
            "symbol": canonical,
            "name": fields[1] or canonical,
            "currency": "USD",
            "price": _number(fields[3]),
            "previous_close": _number(fields[4]),
            "pct_change": _number(fields[32]),
            "turnover_rate_pct": None,
            "pe_ttm": _number(fields[39]),
            "pe_dynamic": None,
            "pe_static": None,
            "pb": _number(fields[47]),
            "float_market_cap": _number(fields[44], 100_000_000.0),
            "total_market_cap": _number(fields[45], 100_000_000.0),
            "market_timestamp": market_timestamp,
            "source": "Tencent Finance US Realtime Quote",
            "source_url": url,
            "fetched_at": fetched_at,
            "field_mapping": "tencent_qt_us_full_v1",
            "warnings": [
                "美股市值字段按亿美元换算为美元后入库。",
                "估值倍数是事实快照，不代表便宜或昂贵；仍需行业可比与历史分位。",
            ],
        }
        available = sum(
            valuation[key] is not None
            for key in ("price", "pe_ttm", "pb", "float_market_cap", "total_market_cap")
        )
        if valuation["price"] is None or available < 4:
            raise ProviderError("腾讯美股估值行情关键字段不足")
        valuation["coverage"] = {"available_metrics": available, "expected_metrics": 5}
        return valuation

    def fetch_financial_periods(
        self, symbol: str, cik: str, limit: int = 8
    ) -> dict[str, Any]:
        canonical = self._identity(symbol)
        padded_cik = str(cik).zfill(10)
        url = self.COMPANYFACTS_URL.format(cik=padded_cik)
        response = self.http_get(url, headers=self._sec_headers(), timeout=30)
        response.raise_for_status()
        try:
            payload = response.json()
        except Exception as exc:
            raise ProviderError("SEC Companyfacts 不是有效 JSON") from exc

        candidates = _report_candidates(payload)
        if not candidates:
            raise ProviderError("SEC Companyfacts 未返回可识别的 10-Q/10-K 报告期")
        fetched_at = utc_now()
        name = str(payload.get("entityName") or canonical).strip()
        periods: list[dict[str, Any]] = []
        for report in candidates[: max(limit * 3, 12)]:
            revenue = _select_fact(
                payload, _DURATION_CONCEPTS["revenue"], "USD", report, duration=True
            )
            if revenue is None:
                continue
            net_income = _select_fact(
                payload, _DURATION_CONCEPTS["net_income"], "USD", report, duration=True
            )
            eps_diluted = _select_fact(
                payload,
                _DURATION_CONCEPTS["eps_diluted"],
                "USD/shares",
                report,
                duration=True,
            )
            gross_profit = _select_fact(
                payload, _DURATION_CONCEPTS["gross_profit"], "USD", report, duration=True
            )
            operating_cashflow = _select_fact(
                payload,
                _DURATION_CONCEPTS["operating_cashflow"],
                "USD",
                report,
                duration=True,
            )
            total_assets = _select_fact(
                payload, _INSTANT_CONCEPTS["total_assets"], "USD", report, duration=False
            )
            total_liabilities = _select_fact(
                payload,
                _INSTANT_CONCEPTS["total_liabilities"],
                "USD",
                report,
                duration=False,
            )
            total_equity = _select_fact(
                payload, _INSTANT_CONCEPTS["total_equity"], "USD", report, duration=False
            )
            fiscal_period = report.get("fp") or ("FY" if report["form"] == "10-K" else "Q")
            fiscal_year = report.get("fy")
            period_basis = "annual" if report["form"] == "10-K" else "year_to_date_cumulative"
            report_name = (
                f"FY{fiscal_year} (10-K)"
                if report["form"] == "10-K"
                else f"FY{fiscal_year} {fiscal_period} (10-Q)"
            )
            periods.append(
                {
                    "symbol": canonical,
                    "name": name,
                    "report_date": report["end"],
                    "report_type": report["form"],
                    "report_date_name": report_name,
                    "notice_date": report["filed"],
                    "currency": "USD",
                    "eps_basic": None,
                    "eps_diluted": eps_diluted,
                    "book_value_per_share": None,
                    "revenue": revenue,
                    "revenue_yoy_pct": None,
                    "parent_net_profit": net_income,
                    "net_profit_yoy_pct": None,
                    "roe_weighted_pct": None,
                    "gross_margin_pct": _ratio_pct(gross_profit, revenue),
                    "net_margin_pct": _ratio_pct(net_income, revenue),
                    "debt_asset_ratio_pct": _ratio_pct(total_liabilities, total_assets),
                    "operating_cashflow": operating_cashflow,
                    "operating_cashflow_per_share": None,
                    "total_assets": total_assets,
                    "total_liabilities": total_liabilities,
                    "total_equity": total_equity,
                    "period_basis": period_basis,
                    "source": "SEC EDGAR Companyfacts",
                    "source_url": url,
                    "fetched_at": fetched_at,
                    "warnings": [
                        "10-Q 数值按财政年度累计口径对齐；10-K 为完整财政年度口径。",
                        "SEC XBRL 为结构化申报事实，重要结论仍应回看对应监管文件原文。",
                    ],
                    "_fiscal_period": fiscal_period,
                }
            )

        for period in periods:
            comparable = _find_comparable(period, periods)
            if comparable:
                period["revenue_yoy_pct"] = _pct_change(
                    period.get("revenue"), comparable.get("revenue")
                )
                period["net_profit_yoy_pct"] = _pct_change(
                    period.get("parent_net_profit"), comparable.get("parent_net_profit")
                )
        public_periods = []
        for period in periods[:limit]:
            item = dict(period)
            item.pop("_fiscal_period", None)
            public_periods.append(item)
        if not public_periods:
            raise ProviderError("SEC Companyfacts 财务报告期均无法解析")
        return {
            "symbol": canonical,
            "name": name,
            "periods": public_periods,
            "source": "SEC EDGAR Companyfacts",
            "source_url": url,
            "fetched_at": fetched_at,
            "coverage": {"returned": len(public_periods), "requested": limit},
            "warnings": [
                "财务指标以 SEC 申报报告期为准；10-Q 累计口径与 10-K 年度口径必须分开解释。"
            ],
        }

    def fetch_statement_details(
        self, symbol: str, cik: str, limit: int = 8
    ) -> dict[str, Any]:
        canonical = self._identity(symbol)
        padded_cik = str(cik).zfill(10)
        url = self.COMPANYFACTS_URL.format(cik=padded_cik)
        response = self.http_get(url, headers=self._sec_headers(), timeout=30)
        response.raise_for_status()
        try:
            payload = response.json()
        except Exception as exc:
            raise ProviderError("SEC Companyfacts 不是有效 JSON") from exc
        candidates = _report_candidates(payload)
        if not candidates:
            raise ProviderError("SEC Companyfacts 未返回可识别的详细报告期")

        fetched_at = utc_now()
        name = str(payload.get("entityName") or canonical).strip()
        statements: list[dict[str, Any]] = []
        for report in candidates[: max(limit * 3, 12)]:
            fiscal_period = str(
                report.get("fp")
                or ("FY" if report.get("form") == "10-K" else "Q")
            )
            fiscal_year = report.get("fy")
            report_name = (
                f"FY{fiscal_year} (10-K)"
                if report["form"] == "10-K"
                else f"FY{fiscal_year} {fiscal_period} (10-Q)"
            )
            common = {
                "symbol": canonical,
                "name": name,
                "report_date": report["end"],
                "report_type": report["form"],
                "report_date_name": report_name,
                "notice_date": report["filed"],
                "currency": "USD",
                "fiscal_period": fiscal_period,
                "period_basis": (
                    "annual"
                    if report["form"] == "10-K"
                    else "year_to_date_cumulative"
                ),
                "source": "SEC EDGAR Companyfacts Detailed Statements",
                "source_url": url,
                "fetched_at": fetched_at,
                "warnings": [
                    "10-Q 采用财政年度累计口径，只与上一财年同类季度比较。",
                    "XBRL 科目命名可能因发行人而异，缺失科目不以模型推断补齐。",
                ],
            }
            income_fields = {
                key: _select_fact(payload, concepts, "USD", report, duration=True)
                for key, concepts in _DETAIL_DURATION_CONCEPTS.items()
                if key
                not in {
                    "operating_cashflow",
                    "investing_cashflow",
                    "financing_cashflow",
                    "capital_expenditure_proxy",
                }
            }
            cashflow_fields = {
                key: _select_fact(payload, concepts, "USD", report, duration=True)
                for key, concepts in _DETAIL_DURATION_CONCEPTS.items()
                if key
                in {
                    "operating_cashflow",
                    "investing_cashflow",
                    "financing_cashflow",
                    "capital_expenditure_proxy",
                }
            }
            balance_fields = {
                key: _select_fact(payload, concepts, "USD", report, duration=False)
                for key, concepts in _DETAIL_INSTANT_CONCEPTS.items()
            }
            for statement_type, fields in (
                ("income", income_fields),
                ("balance", balance_fields),
                ("cashflow", cashflow_fields),
            ):
                if not any(value is not None for value in fields.values()):
                    continue
                statements.append(
                    {
                        **common,
                        "statement_type": statement_type,
                        "fields": fields,
                    }
                )
            if len(
                {
                    (item["report_date"], item["report_type"])
                    for item in statements
                }
            ) >= limit:
                break
        if not statements:
            raise ProviderError("SEC Companyfacts 详细财务科目均无法解析")
        return {
            "symbol": canonical,
            "name": name,
            "statements": statements,
            "source": "SEC EDGAR Companyfacts Detailed Statements",
            "source_url": url,
            "fetched_at": fetched_at,
            "coverage": {
                "returned_statements": len(statements),
                "returned_periods": len(
                    {
                        (item["report_date"], item["report_type"])
                        for item in statements
                    }
                ),
                "requested_periods": limit,
            },
            "warnings": [
                "详细三表仅使用 SEC 已申报的 XBRL 事实，不补写缺失科目。"
            ],
        }

    def fetch_filings(
        self, symbol: str, cik: str, limit: int = 12
    ) -> list[dict[str, Any]]:
        canonical = self._identity(symbol)
        padded_cik = str(cik).zfill(10)
        url = self.SUBMISSIONS_URL.format(cik=padded_cik)
        response = self.http_get(url, headers=self._sec_headers(), timeout=30)
        response.raise_for_status()
        try:
            payload = response.json()
        except Exception as exc:
            raise ProviderError("SEC submissions 不是有效 JSON") from exc
        recent = ((payload.get("filings") or {}).get("recent") or {})
        forms = recent.get("form") or []
        fetched_at = utc_now()
        items = []
        for index, form in enumerate(forms):
            if form not in _FILING_FORMS:
                continue
            try:
                accession = str(recent["accessionNumber"][index])
                document = str(recent["primaryDocument"][index])
                filing_date = str(recent["filingDate"][index])
            except (IndexError, KeyError, TypeError):
                continue
            if not accession or not document or not filing_date:
                continue
            accession_path = accession.replace("-", "")
            filing_url = (
                "https://www.sec.gov/Archives/edgar/data/"
                f"{int(padded_cik)}/{accession_path}/{document}"
            )
            report_date = None
            try:
                report_date = recent.get("reportDate", [])[index] or None
            except (IndexError, TypeError):
                pass
            description = None
            try:
                description = recent.get("primaryDocDescription", [])[index] or None
            except (IndexError, TypeError):
                pass
            try:
                published_at = (
                    datetime.strptime(filing_date, "%Y-%m-%d")
                    .replace(tzinfo=ZoneInfo("America/New_York"))
                    .isoformat(timespec="seconds")
                )
            except ValueError:
                published_at = filing_date
            items.append(
                {
                    "symbol": canonical,
                    "category": "regulatory_filing",
                    "title": f"{canonical} SEC {form}｜{filing_date}",
                    "summary": (
                        f"{description or form}；报告期 {report_date}。"
                        if report_date
                        else description or f"SEC {form} 官方监管文件"
                    ),
                    "source": "SEC EDGAR",
                    "url": filing_url,
                    "published_at": published_at,
                    "engagement": None,
                    "fetched_at": fetched_at,
                }
            )
            if len(items) >= limit:
                break
        if not items:
            raise ProviderError("SEC submissions 未返回 10-Q、10-K 或 8-K 文件")
        return items
