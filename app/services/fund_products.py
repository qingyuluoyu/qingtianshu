from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any

from app.providers.market import ProviderError
from app.utils import utc_now


_FUND_TERMS = (
    "基金",
    "ETF",
    "etf",
    "联接",
    "债基",
    "货基",
    "场内",
    "场外",
)


def _fund_codes(message: str) -> list[str]:
    codes = re.findall(r"(?<!\d)(\d{6})(?!\d)", str(message or ""))
    return list(dict.fromkeys(codes))[:5]


def _is_fund_question(message: str, codes: list[str]) -> bool:
    if any(term in message for term in _FUND_TERMS):
        return True
    return bool(codes) and all(code.startswith(("1", "5")) for code in codes)


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class FundProductService:
    """Persist current fund facts and build same-window comparison evidence."""

    def __init__(
        self,
        database: Any,
        provider: Any,
        *,
        cache_seconds: int = 900,
    ) -> None:
        self.database = database
        self.provider = provider
        self.cache_seconds = max(30, int(cache_seconds))

    def search(self, query: str, *, limit: int = 8) -> dict[str, Any]:
        try:
            return self.provider.search(query, limit=limit)
        except Exception:
            items = self.database.search_fund_product_snapshots(query, limit=limit)
            return {
                "query": str(query or "").strip(),
                "items": [self.public_product(item) for item in items],
                "source": "Qingshu persisted fund snapshots",
                "source_url": None,
                "fetched_at": utc_now(),
                "warnings": [
                    "在线产品搜索暂未更新，当前只显示数据库中已经核验过的产品。"
                ],
            }

    def get_product(self, code: str, *, force_refresh: bool = False) -> dict[str, Any]:
        canonical = str(code or "").strip()
        if not re.fullmatch(r"\d{6}", canonical):
            raise ValueError("基金或ETF代码必须是6位数字")
        cached = self.database.latest_fund_product_snapshot(canonical)
        if cached is not None and not force_refresh and not self._stale(cached):
            return {**cached, "data_status": "current", "cache_hit": True}
        try:
            fresh = self.provider.fetch_product(canonical)
            stored = self.database.save_fund_product_snapshot(fresh)
            return {**stored, "data_status": "current", "cache_hit": False}
        except Exception as exc:
            if cached is not None:
                warnings = list(cached.get("warnings") or [])
                warnings.append(
                    "在线产品事实暂未更新，当前保留最近一次可核验快照并显示原数据时间。"
                )
                return {
                    **cached,
                    "data_status": "stale",
                    "cache_hit": True,
                    "warnings": list(dict.fromkeys(warnings)),
                }
            if isinstance(exc, (ProviderError, ValueError)):
                raise
            raise ProviderError("基金或ETF产品事实暂时不可用") from exc

    def compare(
        self,
        codes: list[str],
        *,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        canonical = list(
            dict.fromkeys(str(code or "").strip() for code in codes if code)
        )
        if not 2 <= len(canonical) <= 5:
            raise ValueError("基金或ETF比较需要2至5个不同产品代码")
        products = [
            self.get_product(code, force_refresh=force_refresh) for code in canonical
        ]
        nav_dates = sorted(
            {str(item.get("nav_date") or "") for item in products if item.get("nav_date")}
        )
        asset_classes = sorted(
            {str(item.get("asset_class") or "other") for item in products}
        )
        product_kinds = sorted(
            {str(item.get("product_kind") or "fund") for item in products}
        )
        warnings = [
            "同一收益窗口只保证字段口径一致；产品底层资产不同仍不能直接据此排名。",
            "历史收益和同类排名不代表未来表现，也不是适合性结论。",
        ]
        if len(nav_dates) > 1:
            warnings.append(
                "产品净值日期不完全一致；比较时必须保留各自日期，不能把它们当作同一收盘时点。"
            )
        if len(asset_classes) > 1:
            warnings.append(
                "这些产品的底层资产类别不同；收益、波动和流动性差异不能归结为管理能力高低。"
            )
        if len(product_kinds) > 1:
            warnings.append(
                "场内ETF成交价与场外基金净值不是同一种价格；已分字段展示，禁止直接混用。"
            )
        return {
            "contract_version": "fund_product_comparison_v1",
            "status": (
                "partial"
                if any(item.get("data_status") == "stale" for item in products)
                else "available"
            ),
            "products": [self.public_product(item) for item in products],
            "comparison_dimensions": [
                "底层资产类别",
                "产品形态与交易方式",
                "净值日期与最新净值",
                "同口径1月/3月/6月/1年历史收益",
                "规模",
                "申购赎回状态与页面费率边界",
                "上游风险等级与主要持仓线索",
            ],
            "as_of": {
                "nav_dates": nav_dates,
                "fetched_at": utc_now(),
            },
            "comparability": {
                "same_asset_class": len(asset_classes) == 1,
                "same_product_kind": len(product_kinds) == 1,
                "same_nav_date": len(nav_dates) <= 1,
            },
            "warnings": list(dict.fromkeys(warnings)),
            "boundary": (
                "这是当前产品事实的同口径整理，不是基金评级、推荐名单或买卖建议。"
            ),
        }

    def build_question_context(self, message: str) -> dict[str, Any] | None:
        codes = _fund_codes(message)
        if not _is_fund_question(message, codes) or not codes:
            return None
        if len(codes) == 1:
            return {
                "contract_version": "fund_product_research_v1",
                "mode": "single_product",
                "product": self.public_product(self.get_product(codes[0])),
                "boundary": (
                    "当前产品事实只用于解释产品，不自动形成适合性或推荐结论。"
                ),
            }
        return {
            "contract_version": "fund_product_research_v1",
            "mode": "comparison",
            "comparison": self.compare(codes),
        }

    def refresh_codes(self, codes: list[str]) -> dict[str, Any]:
        completed: list[str] = []
        failed: list[str] = []
        for code in list(dict.fromkeys(codes)):
            try:
                self.get_product(code, force_refresh=True)
                completed.append(code)
            except Exception:
                failed.append(code)
        return {
            "requested": len(list(dict.fromkeys(codes))),
            "completed": len(completed),
            "failed": len(failed),
            "codes": completed,
            "failed_codes": failed,
        }

    def _stale(self, item: dict[str, Any]) -> bool:
        fetched_at = _parse_time(item.get("fetched_at"))
        if fetched_at is None:
            return True
        age = datetime.now(timezone.utc) - fetched_at.astimezone(timezone.utc)
        return age.total_seconds() > self.cache_seconds

    @staticmethod
    def public_product(item: dict[str, Any]) -> dict[str, Any]:
        return {
            key: item.get(key)
            for key in (
                "code",
                "name",
                "product_kind",
                "asset_class",
                "fund_type",
                "nav",
                "accumulated_nav",
                "nav_date",
                "daily_return_pct",
                "returns",
                "return_ranks",
                "purchase_status",
                "redemption_status",
                "fees",
                "minimum_purchase_cny",
                "minimum_recurring_purchase_cny",
                "risk_level_upstream",
                "net_assets_cny",
                "fund_shares",
                "fund_company",
                "fund_manager",
                "inception_date",
                "top_holdings_summary",
                "live_quote",
                "source",
                "source_url",
                "fetched_at",
                "data_status",
                "warnings",
            )
            if item.get(key) is not None
        }


__all__ = ["FundProductService"]
