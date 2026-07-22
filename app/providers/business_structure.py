from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

import requests

from app.catalog import normalize_symbol
from app.providers.market import ProviderError
from app.utils import utc_now


_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
_CLASSIFICATION = {"1": "industry", "2": "product", "3": "region"}


class AShareBusinessStructureProvider:
    URL = "https://emweb.securities.eastmoney.com/PC_HSF10/BusinessAnalysis/PageAjax"

    def __init__(self, http_get: Callable[..., Any] = requests.get):
        self.http_get = http_get

    def fetch(self, symbol: str) -> dict[str, Any]:
        canonical, provider_symbol = _identity(symbol)
        source_url = (
            "https://emweb.securities.eastmoney.com/PC_HSF10/"
            f"BusinessAnalysis/Index?type=web&code={provider_symbol}"
        )
        response = self.http_get(
            self.URL,
            params={"code": provider_symbol},
            headers={"User-Agent": _UA, "Referer": source_url},
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        raw_rows = payload.get("zygcfx") or []
        rows = []
        for item in raw_rows:
            classification = _CLASSIFICATION.get(str(item.get("MAINOP_TYPE") or ""))
            report_date = _date(item.get("REPORT_DATE"))
            item_name = str(item.get("ITEM_NAME") or "").strip()
            if classification is None or report_date is None or not item_name:
                continue
            rows.append(
                {
                    "symbol": canonical,
                    "report_date": report_date,
                    "classification": classification,
                    "item_name": item_name,
                    "revenue": _number(item.get("MAIN_BUSINESS_INCOME")),
                    "revenue_share_pct": _percent(item.get("MBI_RATIO")),
                    "cost": _number(item.get("MAIN_BUSINESS_COST")),
                    "cost_share_pct": _percent(item.get("MBC_RATIO")),
                    "gross_profit": _number(item.get("MAIN_BUSINESS_RPOFIT")),
                    "gross_profit_share_pct": _percent(item.get("MBR_RATIO")),
                    "gross_margin_pct": _percent(item.get("GROSS_RPOFIT_RATIO")),
                    "source": "company_business_composition",
                    "source_url": source_url,
                    "fetched_at": utc_now(),
                }
            )
        if not rows:
            raise ProviderError("主营构成数据为空")
        return {
            "symbol": canonical,
            "rows": rows,
            "source": "company_business_composition",
            "source_url": source_url,
            "fetched_at": utc_now(),
            "coverage": {
                "rows": len(rows),
                "report_periods": len({item["report_date"] for item in rows}),
                "classifications": sorted(
                    {item["classification"] for item in rows}
                ),
            },
        }


def _identity(symbol: str) -> tuple[str, str]:
    canonical = normalize_symbol(symbol)
    if canonical.endswith(".SS"):
        return canonical, "SH" + canonical[:-3]
    if canonical.endswith(".SZ"):
        return canonical, "SZ" + canonical[:-3]
    raise ValueError("A股主营构成只支持 .SS/.SZ 证券")


def _date(value: Any) -> str | None:
    if not value:
        return None
    text = str(value).strip()[:10]
    try:
        return datetime.fromisoformat(text).date().isoformat()
    except ValueError:
        return None


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def _percent(value: Any) -> float | None:
    number = _number(value)
    if number is None:
        return None
    if abs(number) <= 1.5:
        number *= 100.0
    return round(number, 6)
