from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
from typing import Any, Callable

from app.catalog import INDEX_BY_SYMBOL, normalize_symbol


logger = logging.getLogger(__name__)


class StockPageService:
    """Build the stock page contract behind one browser request.

    The page used to fan out into many independent HTTP calls.  That made the
    browser responsible for joining financial modules and turned one transient
    failure into a confusing collection of placeholders.  This service keeps
    module isolation, but moves orchestration and failure accounting to the
    backend where it can be tested and observed.
    """

    CONTRACT_VERSION = "stock_page_v1"
    REQUIRED_MODULES = frozenset({"workspace", "history"})

    def __init__(
        self,
        *,
        stock_workspace: Any,
        analysis: Any,
        fundamentals: Any,
        us_fundamentals: Any,
        earnings_quality: Any,
        financial_drivers: Any,
        shareholders: Any,
        analyst_expectations: Any,
        event_timeline: Any,
        china_info: Any,
    ) -> None:
        self.stock_workspace = stock_workspace
        self.analysis = analysis
        self.fundamentals = fundamentals
        self.us_fundamentals = us_fundamentals
        self.earnings_quality = earnings_quality
        self.financial_drivers = financial_drivers
        self.shareholders = shareholders
        self.analyst_expectations = analyst_expectations
        self.event_timeline = event_timeline
        self.china_info = china_info

    def get_page(
        self,
        user_id: str,
        symbol: str,
        *,
        range_name: str = "1y",
    ) -> dict[str, Any]:
        canonical = normalize_symbol(symbol)
        if canonical in INDEX_BY_SYMBOL or canonical.startswith("^"):
            raise ValueError("个股页面不接受指数代码")
        is_a_share = canonical.endswith((".SS", ".SZ"))

        primary_loaders: dict[str, Callable[[], dict[str, Any]]] = {
            "workspace": lambda: self.stock_workspace.get_workspace(user_id, canonical),
            "history": lambda: self.analysis.get_index_history(
                canonical, range_name=range_name
            ),
            "fundamentals": lambda: self._fundamentals_packet(canonical, is_a_share),
            "event_timeline": lambda: self.event_timeline.get_packet(canonical),
        }
        if is_a_share:
            primary_loaders.update(
                {
                    "shareholders": lambda: self.shareholders.get_packet(canonical),
                    "analyst_expectations": lambda: (
                        self.analyst_expectations.get_packet(canonical)
                    ),
                    "information": lambda: self.china_info.get_packet(canonical),
                }
            )
        dependent_loaders: dict[str, Callable[[], dict[str, Any]]] = {
            "earnings_quality": lambda: self.earnings_quality.get_packet(canonical),
            "financial_drivers": lambda: self.financial_drivers.get_packet(canonical),
        }

        modules: dict[str, dict[str, Any]] = {}
        self._run_loaders(canonical, primary_loaders, modules)
        # Earnings quality and driver analysis read the financial snapshot that
        # the first phase has just refreshed. This prevents three concurrent
        # calls to the same upstream fundamentals provider.
        self._run_loaders(canonical, dependent_loaders, modules)

        ordered_names = [*primary_loaders, *dependent_loaders]
        ordered_modules = {
            module_name: modules[module_name] for module_name in ordered_names
        }
        failed = [
            name
            for name, packet in ordered_modules.items()
            if packet["status"] != "available"
        ]
        required_failed = [name for name in failed if name in self.REQUIRED_MODULES]
        status = "ready" if not failed else "degraded" if required_failed else "partial"
        return {
            "contract_version": self.CONTRACT_VERSION,
            "symbol": canonical,
            "market": "a_share" if is_a_share else "us_equity",
            "status": status,
            "modules": ordered_modules,
            "summary": {
                "total": len(ordered_modules),
                "available": len(ordered_modules) - len(failed),
                "failed": len(failed),
                "required_failed": required_failed,
            },
        }

    def _run_loaders(
        self,
        canonical: str,
        loaders: dict[str, Callable[[], dict[str, Any]]],
        modules: dict[str, dict[str, Any]],
    ) -> None:
        with ThreadPoolExecutor(
            max_workers=min(8, len(loaders)),
            thread_name_prefix="stock-page",
        ) as executor:
            futures = {
                executor.submit(loader): module_name
                for module_name, loader in loaders.items()
            }
            for future in as_completed(futures):
                module_name = futures[future]
                try:
                    modules[module_name] = {
                        "status": "available",
                        "data": future.result(),
                    }
                except Exception:  # modules are deliberately isolated
                    logger.exception(
                        "stock page module failed",
                        extra={
                            "stock_page_module": module_name,
                            "stock_symbol": canonical,
                        },
                    )
                    modules[module_name] = {
                        "status": "unavailable",
                        "data": None,
                        "message": self._public_failure_message(module_name),
                    }

    def _fundamentals_packet(self, canonical: str, is_a_share: bool) -> dict[str, Any]:
        if is_a_share:
            return self.fundamentals.get_packet(canonical)
        return self.us_fundamentals.get_packet(canonical)

    @staticmethod
    def _public_failure_message(module_name: str) -> str:
        labels = {
            "workspace": "研究空间暂时没有完整返回",
            "history": "日线行情暂时没有完整返回",
            "fundamentals": "财务数据暂时没有完整返回",
            "earnings_quality": "盈利质量分析暂时没有完整返回",
            "financial_drivers": "财务驱动分析暂时没有完整返回",
            "shareholders": "股东数据暂时没有完整返回",
            "analyst_expectations": "分析师预期暂时没有完整返回",
            "event_timeline": "事件脉络暂时没有完整返回",
            "information": "公司资讯暂时没有完整返回",
        }
        return labels.get(module_name, "该研究模块暂时没有完整返回")
