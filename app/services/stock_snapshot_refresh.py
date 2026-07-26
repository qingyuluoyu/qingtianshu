from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.catalog import normalize_symbol
from app.db import Database


class StockSnapshotRefreshService:
    """Fast snapshot reads plus durable, idempotent refresh submission."""

    def __init__(
        self,
        database: Database,
        stock_dashboard: Any,
        *,
        market_provider: Any,
        industry_comparison: Any,
    ) -> None:
        self.database = database
        self.stock_dashboard = stock_dashboard
        self.market_provider = market_provider
        self.industry_comparison = industry_comparison

    @staticmethod
    def _canonical(symbol: str) -> str:
        canonical = normalize_symbol(symbol)
        if not canonical.endswith((".SS", ".SZ", ".BJ")):
            raise ValueError("个股评分库目前只支持 A 股证券")
        return canonical

    @staticmethod
    def _time_bucket(minutes: int = 5) -> str:
        now = datetime.now(ZoneInfo("Asia/Shanghai"))
        minute = now.minute - now.minute % max(1, minutes)
        return now.replace(minute=minute, second=0, microsecond=0).isoformat()

    def _enqueue(
        self,
        *,
        kind: str,
        key: str,
        payload: dict[str, Any],
        request_id: str | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        task, _ = self.database.create_data_refresh_task(
            kind=kind,
            idempotency_key=key,
            payload=payload,
            request_id=request_id,
            trace_id=trace_id,
        )
        return {
            "taskId": task["id"],
            "status": (
                "running" if task["status"] == "leased" else "queued"
            ),
            "lastErrorType": task.get("last_error_type"),
        }

    def read_score_card(
        self,
        symbol: str,
        *,
        refresh: bool = False,
        request_id: str | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        canonical = self._canonical(symbol)
        packet = self.stock_dashboard.score_card(
            canonical, allow_remote=False
        )
        cache = dict(packet.get("cache") or {})
        if refresh or cache.get("state") != "fresh":
            packet["refresh"] = self._enqueue(
                kind="stock_quote",
                key=f"stock-quote:{canonical}:{self._time_bucket()}",
                payload={"symbol": canonical},
                request_id=request_id,
                trace_id=trace_id,
            )
            cache["refreshing"] = True
        else:
            packet["refresh"] = {
                "taskId": None,
                "status": "idle",
                "lastErrorType": None,
            }
        packet["cache"] = cache
        return packet

    def read_kline(
        self,
        symbol: str,
        *,
        period: str,
        limit: int,
        adjust: str,
        refresh: bool = False,
        request_id: str | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        canonical = self._canonical(symbol)
        packet = self.stock_dashboard.kline(
            canonical,
            period=period,
            limit=limit,
            adjust=adjust,
            allow_remote=False,
        )
        cache = dict(packet.get("cache") or {})
        if refresh or cache.get("state") != "fresh":
            packet["refresh"] = self._enqueue(
                kind="stock_kline",
                key=(
                    f"stock-kline:{canonical}:{period}:{adjust}:"
                    f"{self._time_bucket(30)}"
                ),
                payload={
                    "symbol": canonical,
                    "period": period,
                    "limit": limit,
                    "adjust": adjust,
                },
                request_id=request_id,
                trace_id=trace_id,
            )
            cache["refreshing"] = True
        else:
            packet["refresh"] = {
                "taskId": None,
                "status": "idle",
                "lastErrorType": None,
            }
        packet["cache"] = cache
        return packet

    def read_industry_comparison(
        self,
        symbol: str,
        *,
        refresh: bool = False,
        request_id: str | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        canonical = self._canonical(symbol)
        packet = self.industry_comparison.get_packet(canonical, force=False)
        cache = dict(packet.get("cache") or {})
        if refresh or packet.get("status") == "warming" or cache.get("state") != "fresh":
            period = packet.get("reportPeriod") or "pending"
            valuation_date = packet.get("valuationTradeDate") or "pending"
            packet["refresh"] = self._enqueue(
                kind="industry_score",
                key=(
                    f"industry-score:{canonical}:{period}:{valuation_date}:"
                    f"{self.industry_comparison.FORMULA_VERSION}"
                ),
                payload={"symbol": canonical},
                request_id=request_id,
                trace_id=trace_id,
            )
            cache["refreshing"] = True
        else:
            packet["refresh"] = {
                "taskId": None,
                "status": "idle",
                "lastErrorType": None,
            }
        packet["cache"] = cache
        return packet

    def execute(self, task: dict[str, Any]) -> None:
        kind = str(task["task_kind"])
        payload = dict(task.get("payload") or {})
        symbol = self._canonical(str(payload.get("symbol") or ""))
        if kind == "stock_quote":
            self.market_provider.fetch_history(symbol, "1d", "1m")
            return
        if kind == "stock_kline":
            period = str(payload.get("period") or "1d")
            config = self.stock_dashboard.period_config(period)
            self.market_provider.fetch_history(
                symbol, config["range"], config["interval"]
            )
            return
        if kind == "industry_score":
            self.industry_comparison.refresh_packet(symbol)
            return
        raise ValueError("unsupported_data_refresh_kind")
