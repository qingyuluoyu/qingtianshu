from __future__ import annotations

from datetime import datetime
import re
from typing import Any, Callable
from zoneinfo import ZoneInfo

import requests

from app.catalog import normalize_symbol
from app.providers.market import ProviderError
from app.utils import utc_now


_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

_STATEMENT_REPORTS = {
    "income": "RPT_DMSK_FN_INCOME",
    "balance": "RPT_DMSK_FN_BALANCE",
    "cashflow": "RPT_DMSK_FN_CASHFLOW",
}

_STATEMENT_FIELDS = {
    "income": {
        "revenue": "TOTAL_OPERATE_INCOME",
        "total_operating_cost": "TOTAL_OPERATE_COST",
        "operating_cost": "OPERATE_COST",
        "sales_expense": "SALE_EXPENSE",
        "management_expense": "MANAGE_EXPENSE",
        "finance_expense": "FINANCE_EXPENSE",
        "operating_tax_surcharges": "OPERATE_TAX_ADD",
        "operating_profit": "OPERATE_PROFIT",
        "total_profit": "TOTAL_PROFIT",
        "income_tax": "INCOME_TAX",
        "investment_income": "INVEST_INCOME",
        "parent_net_profit": "PARENT_NETPROFIT",
        "deducted_parent_net_profit": "DEDUCT_PARENT_NETPROFIT",
    },
    "balance": {
        "accounts_receivable": "ACCOUNTS_RECE",
        "inventory": "INVENTORY",
        "accounts_payable": "ACCOUNTS_PAYABLE",
        "cash_and_equivalents": "MONETARYFUNDS",
        "short_term_borrowings": "SHORT_LOAN",
        "fixed_assets": "FIXED_ASSET",
        "total_assets": "TOTAL_ASSETS",
        "total_liabilities": "TOTAL_LIABILITIES",
        "total_equity": "TOTAL_EQUITY",
        "debt_asset_ratio_pct": "DEBT_ASSET_RATIO",
    },
    "cashflow": {
        "operating_cashflow": "NETCASH_OPERATE",
        "investing_cashflow": "NETCASH_INVEST",
        "financing_cashflow": "NETCASH_FINANCE",
        "cash_received_from_sales": "SALES_SERVICES",
        "cash_paid_to_employees": "PAY_STAFF_CASH",
        "cash_received_from_investments": "RECEIVE_INVEST_INCOME",
        "capital_expenditure_proxy": "CONSTRUCT_LONG_ASSET",
        "cash_change": "CCE_ADD",
        "ending_cash_equivalents": "END_CCE",
        "beginning_cash_equivalents": "BEGIN_CCE",
    },
}


def _a_share_identity(symbol: str) -> tuple[str, str, str, str]:
    canonical = normalize_symbol(symbol)
    code = canonical.split(".")[0]
    if canonical.endswith(".SS"):
        return canonical, code, f"sh{code}", f"{code}.SH"
    if canonical.endswith(".SZ"):
        return canonical, code, f"sz{code}", f"{code}.SZ"
    raise ProviderError("结构化财务与估值目前只支持 A 股证券")


def _number(value: Any, scale: float = 1.0) -> float | None:
    if value in (None, "", "--"):
        return None
    try:
        result = float(value) * scale
    except (TypeError, ValueError):
        return None
    return round(result, 6)


def _date(value: Any) -> str | None:
    if not value:
        return None
    return str(value).split(" ", 1)[0]


def _a_share_period_meta(report_date: str) -> tuple[str, str, str]:
    month_day = report_date[5:]
    if month_day == "03-31":
        return "一季报", f"{report_date[:4]}一季报", "Q1"
    if month_day == "06-30":
        return "中报", f"{report_date[:4]}中报", "H1"
    if month_day == "09-30":
        return "三季报", f"{report_date[:4]}三季报", "Q3"
    if month_day == "12-31":
        return "年报", f"{report_date[:4]}年报", "FY"
    return "定期报告", report_date, month_day


def _valid_notice_date(value: Any, report_date: str, fiscal_period: str) -> str | None:
    notice_date = _date(value)
    if notice_date is None:
        return None
    try:
        report_year = int(report_date[:4])
        notice_year = int(notice_date[:4])
    except (TypeError, ValueError):
        return None
    latest_valid_year = report_year + (1 if fiscal_period == "FY" else 0)
    return notice_date if report_year <= notice_year <= latest_valid_year else None


class AShareFundamentalsProvider:
    """Fetch deterministic A-share valuation and main financial indicators."""

    TENCENT_QUOTE_URL = "https://qt.gtimg.cn/q={quote_symbol}"
    EASTMONEY_FINANCIAL_URL = (
        "https://datacenter.eastmoney.com/securities/api/data/v1/get"
    )

    def __init__(self, http_get: Callable[..., Any] = requests.get):
        self.http_get = http_get

    def fetch_valuation(self, symbol: str) -> dict[str, Any]:
        canonical, code, quote_symbol, _ = _a_share_identity(symbol)
        url = self.TENCENT_QUOTE_URL.format(quote_symbol=quote_symbol)
        response = self.http_get(
            url,
            headers={"User-Agent": _UA, "Referer": "https://gu.qq.com/"},
            timeout=15,
        )
        response.raise_for_status()
        content = response.content.decode("gb18030", errors="replace").strip()
        match = re.search(r'=\s*"(.*)";?$', content)
        if not match:
            raise ProviderError("腾讯估值行情格式无法识别")
        fields = match.group(1).split("~")
        if len(fields) <= 53 or fields[2] != code:
            raise ProviderError("腾讯估值行情字段不完整")

        market_timestamp = None
        if re.fullmatch(r"\d{14}", fields[30] or ""):
            market_timestamp = (
                datetime.strptime(fields[30], "%Y%m%d%H%M%S")
                .replace(tzinfo=ZoneInfo("Asia/Shanghai"))
                .isoformat(timespec="seconds")
            )
        if market_timestamp is None:
            raise ProviderError("腾讯估值行情缺少市场时间")

        fetched_at = utc_now()
        valuation = {
            "symbol": canonical,
            "name": fields[1] or code,
            "currency": fields[82] if len(fields) > 82 and fields[82] else "CNY",
            "price": _number(fields[3]),
            "previous_close": _number(fields[4]),
            "pct_change": _number(fields[32]),
            "turnover_rate_pct": _number(fields[38]),
            # Tencent full-quote schema: 39=TTM, 52=dynamic annualized,
            # 53=last-annual-report static PE. These are deliberately kept
            # separate because mixing the three creates misleading conclusions.
            "pe_ttm": _number(fields[39]),
            "pe_dynamic": _number(fields[52]),
            "pe_static": _number(fields[53]),
            "pb": _number(fields[46]),
            # Tencent reports market capitalisation in CNY 100 million.
            "float_market_cap": _number(fields[44], 100_000_000.0),
            "total_market_cap": _number(fields[45], 100_000_000.0),
            "market_timestamp": market_timestamp,
            "source": "Tencent Finance Realtime Quote",
            "source_url": url,
            "fetched_at": fetched_at,
            "field_mapping": "tencent_qt_full_v1",
            "warnings": [
                "市盈率分为 TTM、动态年化和静态口径，三者不可混用。",
                "估值倍数是事实快照，不代表便宜或昂贵；仍需行业可比与历史分位。",
            ],
        }
        available = sum(
            valuation[key] is not None
            for key in (
                "price",
                "pe_ttm",
                "pe_dynamic",
                "pe_static",
                "pb",
                "float_market_cap",
                "total_market_cap",
            )
        )
        if valuation["price"] is None or available < 4:
            raise ProviderError("腾讯估值行情关键字段不足")
        valuation["coverage"] = {"available_metrics": available, "expected_metrics": 7}
        return valuation

    def fetch_financial_periods(
        self, symbol: str, limit: int = 8
    ) -> dict[str, Any]:
        canonical, code, _, secucode = _a_share_identity(symbol)
        params = {
            "reportName": "RPT_F10_FINANCE_MAINFINADATA",
            "columns": "ALL",
            "quoteColumns": "",
            "filter": f'(SECUCODE="{secucode}")',
            "pageNumber": 1,
            "pageSize": max(1, min(limit, 20)),
            "sortTypes": -1,
            "sortColumns": "REPORT_DATE",
            "source": "HSF10",
            "client": "PC",
        }
        response = self.http_get(
            self.EASTMONEY_FINANCIAL_URL,
            params=params,
            headers={"User-Agent": _UA, "Referer": "https://emweb.securities.eastmoney.com/"},
            timeout=20,
        )
        response.raise_for_status()
        try:
            payload = response.json()
        except Exception as exc:
            raise ProviderError("东方财富 F10 财务数据不是有效 JSON") from exc
        rows = (payload.get("result") or {}).get("data") or []
        if not rows:
            raise ProviderError("东方财富 F10 未返回财务报告期")

        fetched_at = utc_now()
        periods = []
        for row in rows[:limit]:
            report_date = _date(row.get("REPORT_DATE"))
            if not report_date:
                continue
            periods.append(
                {
                    "symbol": canonical,
                    "name": row.get("SECURITY_NAME_ABBR") or code,
                    "report_date": report_date,
                    "report_type": row.get("REPORT_TYPE") or "未知报告",
                    "report_date_name": row.get("REPORT_DATE_NAME") or report_date,
                    "notice_date": _date(row.get("NOTICE_DATE")),
                    "currency": row.get("CURRENCY") or "CNY",
                    "eps_basic": _number(row.get("EPSJB")),
                    "book_value_per_share": _number(row.get("BPS")),
                    "revenue": _number(row.get("TOTALOPERATEREVE")),
                    "revenue_yoy_pct": _number(row.get("TOTALOPERATEREVETZ")),
                    "parent_net_profit": _number(row.get("PARENTNETPROFIT")),
                    "net_profit_yoy_pct": _number(row.get("PARENTNETPROFITTZ")),
                    "roe_weighted_pct": _number(row.get("ROEJQ")),
                    "gross_margin_pct": _number(row.get("XSMLL")),
                    "net_margin_pct": _number(row.get("XSJLL")),
                    "debt_asset_ratio_pct": _number(row.get("ZCFZL")),
                    "operating_cashflow": _number(row.get("NETCASH_OPERATE_PK")),
                    "operating_cashflow_per_share": _number(row.get("MGJYXJJE")),
                    "total_assets": _number(row.get("TOTAL_ASSETS_PK")),
                    "total_equity": _number(row.get("TOTAL_EQUITY_PK")),
                    "period_basis": "year_to_date_cumulative",
                    "source": "Eastmoney F10 Main Financial Data",
                    "source_url": self.EASTMONEY_FINANCIAL_URL,
                    "fetched_at": fetched_at,
                    "warnings": [
                        "一季报、中报和三季报为年初至报告期累计口径，不能直接当作单季度值。"
                    ],
                }
            )
        if not periods:
            raise ProviderError("东方财富 F10 财务报告期均无法解析")
        return {
            "symbol": canonical,
            "name": periods[0]["name"],
            "periods": periods,
            "source": "Eastmoney F10 Main Financial Data",
            "source_url": self.EASTMONEY_FINANCIAL_URL,
            "fetched_at": fetched_at,
            "coverage": {"returned": len(periods), "requested": limit},
            "warnings": [
                "财务指标以公告报告期为准；累计口径与单季度口径必须分开解释。"
            ],
        }

    def fetch_statement_details(
        self, symbol: str, limit: int = 12
    ) -> dict[str, Any]:
        canonical, code, _, secucode = _a_share_identity(symbol)
        fetched_at = utc_now()
        statements: list[dict[str, Any]] = []
        coverage: dict[str, int] = {}
        for statement_type, report_name in _STATEMENT_REPORTS.items():
            params = {
                "reportName": report_name,
                "columns": "ALL",
                "quoteColumns": "",
                "filter": f'(SECUCODE="{secucode}")',
                "pageNumber": 1,
                "pageSize": max(1, min(limit, 20)),
                "sortTypes": -1,
                "sortColumns": "REPORT_DATE",
                "source": "HSF10",
                "client": "PC",
            }
            response = self.http_get(
                self.EASTMONEY_FINANCIAL_URL,
                params=params,
                headers={
                    "User-Agent": _UA,
                    "Referer": "https://emweb.securities.eastmoney.com/",
                },
                timeout=20,
            )
            response.raise_for_status()
            try:
                payload = response.json()
            except Exception as exc:
                raise ProviderError("东方财富详细财务报表不是有效 JSON") from exc
            rows = (payload.get("result") or {}).get("data") or []
            coverage[statement_type] = len(rows)
            for row in rows[:limit]:
                report_date = _date(row.get("REPORT_DATE"))
                if not report_date:
                    continue
                report_type, report_date_name, fiscal_period = _a_share_period_meta(
                    report_date
                )
                fields = {
                    target: _number(row.get(source))
                    for target, source in _STATEMENT_FIELDS[statement_type].items()
                }
                statements.append(
                    {
                        "symbol": canonical,
                        "name": row.get("SECURITY_NAME_ABBR") or code,
                        "report_date": report_date,
                        "report_type": report_type,
                        "report_date_name": report_date_name,
                        "notice_date": _valid_notice_date(
                            row.get("NOTICE_DATE"), report_date, fiscal_period
                        ),
                        "currency": "CNY",
                        "fiscal_period": fiscal_period,
                        "period_basis": (
                            "annual"
                            if fiscal_period == "FY"
                            else "year_to_date_cumulative"
                        ),
                        "statement_type": statement_type,
                        "fields": fields,
                        "source": "Eastmoney F10 Detailed Financial Statements",
                        "source_url": self.EASTMONEY_FINANCIAL_URL,
                        "fetched_at": fetched_at,
                        "warnings": [
                            "一季报、中报和三季报为年初至报告期累计口径，只与上一年度同类报告期比较。",
                            "科目变化可用于机械拆解和定位线索，不能单独证明业务因果。",
                        ],
                    }
                )
        if not statements:
            raise ProviderError("东方财富未返回可解析的详细财务报表")
        return {
            "symbol": canonical,
            "name": statements[0]["name"],
            "statements": statements,
            "source": "Eastmoney F10 Detailed Financial Statements",
            "source_url": self.EASTMONEY_FINANCIAL_URL,
            "fetched_at": fetched_at,
            "coverage": {
                "requested_periods_per_statement": limit,
                "returned_statements": len(statements),
                "rows_by_statement": coverage,
            },
            "warnings": [
                "详细三表用于确定性同比拆解；精确经营原因仍需回看公告原文与附注。"
            ],
        }
