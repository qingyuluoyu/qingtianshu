from __future__ import annotations

from collections import Counter
from concurrent.futures import Future, ThreadPoolExecutor, wait
from datetime import datetime, timedelta
from statistics import mean
import re
import threading
import time
from typing import Any
from zoneinfo import ZoneInfo

from app.utils import utc_now


_INDEXES = {
    "000001.SH": {
        "internal_symbol": "000001.SS",
        "name": "上证主板",
        "board": "sh_main",
    },
    "399001.SZ": {
        "internal_symbol": "399001.SZ",
        "name": "深证主板",
        "board": "sz_main",
    },
    "399006.SZ": {
        "internal_symbol": "399006.SZ",
        "name": "创业板",
        "board": "chinext",
    },
    "000688.SH": {
        "internal_symbol": "000688.SS",
        "name": "科创板",
        "board": "star",
    },
}


class TodayDashboardService:
    """Adapt audited backend data to the high-fidelity dashboard contract."""

    LIMIT_CACHE_KEY = "today-dashboard:limit-snapshot"
    DASHBOARD_CACHE_KEY = "today-dashboard:latest"

    def __init__(
        self,
        database: Any,
        analysis: Any,
        *,
        intraday_index_provider: Any | None = None,
        tushare_client: Any | None = None,
        cache_seconds: int = 60,
        background_refresh: bool = False,
    ) -> None:
        self.database = database
        self.analysis = analysis
        self.intraday_index_provider = intraday_index_provider
        self.tushare_client = tushare_client
        self.cache_seconds = max(20, cache_seconds)
        self._lock = threading.Lock()
        self._dashboard_lock = threading.Lock()
        self._limit_cache: tuple[float, dict[str, Any]] | None = None
        self._activity_cache: dict[
            int, tuple[float, dict[str, Any]]
        ] = {}
        self._dashboard_cache: tuple[float, dict[str, Any]] | None = None
        self._dashboard_refreshing = False
        self._limit_refreshing = False
        self._limit_executor = (
            ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix="qingshu-limit-refresh",
            )
            if background_refresh
            else None
        )
        self._prewarm_executor = (
            ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix="qingshu-today-prewarm",
            )
            if background_refresh
            else None
        )

    def prewarm(self) -> None:
        self._schedule_dashboard_refresh()

    def close(self) -> None:
        if self._limit_executor is not None:
            self._limit_executor.shutdown(wait=False, cancel_futures=True)
        if self._prewarm_executor is not None:
            self._prewarm_executor.shutdown(wait=False, cancel_futures=True)

    def dashboard(self) -> dict[str, Any]:
        now = time.monotonic()
        if self._dashboard_cache and self._dashboard_cache[0] > now:
            return self._dashboard_cache[1]
        if self._dashboard_cache is None and hasattr(self.database, "get_cache"):
            persistent = self.database.get_cache(
                self.DASHBOARD_CACHE_KEY,
                allow_stale=True,
            )
            if persistent is not None:
                self._dashboard_cache = (now + 20, persistent)
                self._schedule_dashboard_refresh()
                result = self._with_date_alignment(persistent)
                result["cache"] = {
                    "state": "persistent",
                    "refreshing": self._prewarm_executor is not None,
                }
                return result
        if self._dashboard_cache and self._prewarm_executor is not None:
            self._schedule_dashboard_refresh()
            stale = self._with_date_alignment(self._dashboard_cache[1])
            stale["cache"] = {
                "state": "stale",
                "refreshing": True,
            }
            return stale
        return self._refresh_dashboard()

    def _schedule_dashboard_refresh(self) -> None:
        if self._prewarm_executor is None:
            return
        with self._lock:
            if self._dashboard_refreshing:
                return
            self._dashboard_refreshing = True
        self._prewarm_executor.submit(self._dashboard_refresh_job)

    def _dashboard_refresh_job(self) -> None:
        try:
            result = self._refresh_dashboard(force=True)
            activity = self.trading_activity(days=7, allow_remote=True)
            if activity.get("points"):
                result = {**result, "tradingActivity": activity}
                result = self._with_date_alignment(result)
                self._dashboard_cache = (
                    time.monotonic() + self.cache_seconds,
                    result,
                )
                if hasattr(self.database, "put_cache"):
                    self.database.put_cache(
                        self.DASHBOARD_CACHE_KEY,
                        result,
                        ttl_seconds=259_200,
                    )
        except Exception:
            pass
        finally:
            with self._lock:
                self._dashboard_refreshing = False

    def _refresh_dashboard(self, *, force: bool = False) -> dict[str, Any]:
        now = time.monotonic()
        if not force and self._dashboard_cache and self._dashboard_cache[0] > now:
            return self._dashboard_cache[1]
        with self._dashboard_lock:
            now = time.monotonic()
            if (
                not force
                and self._dashboard_cache
                and self._dashboard_cache[0] > now
            ):
                return self._dashboard_cache[1]
            executor = ThreadPoolExecutor(
                max_workers=7,
                thread_name_prefix="qingshu-today-io",
            )
            empty_limits = {"boards": {}}
            futures: dict[str, Future[Any]] = {
                "breadth": executor.submit(self._breadth),
                "sectors": executor.submit(self.analysis.hot_sectors, 100),
                "limits": executor.submit(self._limit_snapshot),
            }
            for code in _INDEXES:
                futures[f"index:{code}"] = executor.submit(
                    self.index_quote,
                    code,
                    limit_snapshot=empty_limits,
                )
            done, pending = wait(futures.values(), timeout=2)
            executor.shutdown(wait=False, cancel_futures=False)
            values: dict[str, Any] = {}
            errors: dict[str, str] = {}
            for key, future in futures.items():
                if future in pending:
                    errors[key] = "timeout"
                    continue
                try:
                    values[key] = future.result()
                except Exception as exc:
                    errors[key] = type(exc).__name__

            breadth = values.get("breadth")
            sectors = values.get("sectors")
            limits = values.get("limits") or empty_limits
            indices = []
            for code, config in _INDEXES.items():
                item = values.get(f"index:{code}")
                if item is None:
                    continue
                board_limits = (limits.get("boards") or {}).get(
                    config["board"], {}
                )
                item["limitUp"] = board_limits.get("up")
                item["limitDown"] = board_limits.get("down")
                item["limitDataAsOf"] = limits.get("market_date")
                indices.append(item)
            result = {
                "indices": indices,
                "generatedAt": utc_now(),
                "moduleErrors": errors,
            }
            if breadth is not None:
                result.update(
                    {
                        "marketOverview": self.market_overview(
                            breadth_packet=breadth,
                            limit_snapshot=limits,
                        ),
                        "riseFallDistribution": self.rise_fall_distribution(
                            breadth_packet=breadth
                        ),
                        "tradingActivity": self.trading_activity(
                            days=7,
                            breadth_packet=breadth,
                            allow_remote=False,
                        ),
                    }
                )
            if sectors is not None:
                result.update(
                    {
                        "industryRotation": self.industry_rotation(
                            limit=5,
                            packet=sectors,
                            allow_remote=False,
                        ),
                        "hotThemes": self.hot_themes(
                            limit=5, packet=sectors
                        ),
                        "sectorFundFlow": self.sector_fund_flow(
                            limit=10, packet=sectors
                        ),
                    }
                )
            result = self._with_date_alignment(result)
            self._dashboard_cache = (
                time.monotonic() + self.cache_seconds,
                result,
            )
            if (
                hasattr(self.database, "put_cache")
                and (result.get("indices") or result.get("marketOverview"))
            ):
                self.database.put_cache(
                    self.DASHBOARD_CACHE_KEY,
                    result,
                    ttl_seconds=259_200,
                )
            return result

    @staticmethod
    def _market_date_from_timestamp(value: Any) -> str | None:
        text = str(value or "").strip()
        if not text:
            return None
        if re.fullmatch(r"20\d{2}-\d{2}-\d{2}", text):
            return text
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
        return parsed.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()

    @classmethod
    def _with_date_alignment(
        cls, payload: dict[str, Any]
    ) -> dict[str, Any]:
        result = dict(payload)
        module_dates: dict[str, str] = {}

        def add_date(module: str, value: Any) -> None:
            market_date = cls._market_date_from_timestamp(value)
            if market_date:
                module_dates[module] = market_date

        indices = list(result.get("indices") or [])
        index_dates = {
            cls._market_date_from_timestamp(
                item.get("marketDate") or item.get("marketTimestamp")
            )
            for item in indices
        }
        index_dates.discard(None)
        if len(index_dates) == 1:
            module_dates["indices"] = next(iter(index_dates))

        overview = result.get("marketOverview") or {}
        add_date(
            "marketOverview",
            overview.get("marketDate") or overview.get("marketTimestamp"),
        )
        add_date("limits", overview.get("limitDataAsOf"))

        distribution = result.get("riseFallDistribution") or {}
        add_date(
            "riseFallDistribution",
            distribution.get("marketDate") or distribution.get("marketTimestamp"),
        )

        activity_points = list(
            (result.get("tradingActivity") or {}).get("points") or []
        )
        if activity_points:
            add_date(
                "tradingActivity",
                activity_points[-1].get("marketDate")
                or activity_points[-1].get("market_date"),
            )

        for module in ("industryRotation", "hotThemes"):
            items = list(result.get(module) or [])
            dates = {
                cls._market_date_from_timestamp(
                    item.get("marketDate") or item.get("marketTimestamp")
                )
                for item in items
            }
            dates.discard(None)
            if len(dates) == 1:
                module_dates[module] = next(iter(dates))

        flow = result.get("sectorFundFlow") or {}
        add_date(
            "sectorFundFlow",
            flow.get("marketDate") or flow.get("marketTimestamp"),
        )

        anchor = module_dates.get("marketOverview")
        if anchor is None and module_dates:
            anchor = Counter(module_dates.values()).most_common(1)[0][0]
        mismatches = sorted(
            module
            for module, market_date in module_dates.items()
            if anchor is not None and market_date != anchor
        )
        status = "partial" if anchor is None else ("mixed" if mismatches else "aligned")
        result["asOfMarketDate"] = anchor
        result["dateAlignment"] = {
            "status": status,
            "anchorMarketDate": anchor,
            "moduleMarketDates": module_dates,
            "mismatchedModules": mismatches,
        }
        return result

    def index_quote(
        self,
        code: str,
        *,
        limit_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        config = _INDEXES.get(code.strip().upper())
        if config is None:
            raise ValueError("暂不支持该指数")
        if self.intraday_index_provider is None:
            raise RuntimeError("指数分钟行情尚未配置")

        if hasattr(self.intraday_index_provider, "fetch_intraday"):
            packet = self.intraday_index_provider.fetch_intraday(
                config["internal_symbol"]
            )
        else:
            packet = self.intraday_index_provider.fetch_history(
                config["internal_symbol"],
                range_name="1d",
                interval="1m",
            )
        points = packet.get("points") or []
        latest_price = packet.get("latest_price")
        if latest_price is None and points:
            latest_price = points[-1].get("close")
        previous_close = packet.get("previous_close")
        change_pct = packet.get("pct_change")
        if (
            change_pct is None
            and latest_price is not None
            and previous_close not in (None, 0)
        ):
            change_pct = round(
                (float(latest_price) / float(previous_close) - 1) * 100, 4
            )

        amounts = [
            float(point["amount"])
            for point in points
            if point.get("amount") is not None
        ]
        turnover = round(sum(amounts) / 100_000_000, 2) if amounts else None
        limit_snapshot = limit_snapshot or self._limit_snapshot()
        board_limits = (limit_snapshot.get("boards") or {}).get(
            config["board"], {}
        )
        trend = [
            float(point["close"])
            for point in points[-60:]
            if point.get("close") is not None
        ]
        return {
            "code": code.strip().upper(),
            "name": config["name"],
            "value": latest_price,
            "changePct": change_pct,
            "turnover": turnover,
            "limitUp": board_limits.get("up"),
            "limitDown": board_limits.get("down"),
            "trend": trend,
            "marketDate": self._market_date_from_timestamp(
                packet.get("market_timestamp")
            ),
            "marketTimestamp": packet.get("market_timestamp"),
            "fetchedAt": packet.get("fetched_at"),
            "source": packet.get("source"),
            "limitDataAsOf": limit_snapshot.get("market_date"),
            "warnings": packet.get("warnings") or [],
        }

    def market_overview(
        self,
        *,
        breadth_packet: dict[str, Any] | None = None,
        limit_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        packet = breadth_packet or self._breadth()
        breadth = packet.get("breadth") or {}
        total = int(breadth.get("total") or 0)
        rising = int(breadth.get("advancers") or 0)
        flat = int(breadth.get("unchanged") or 0)
        falling = int(breadth.get("decliners") or 0)
        limits = limit_snapshot or self._limit_snapshot()
        market_date = str(packet.get("market_date") or "") or None
        limit_market_date = str(limits.get("market_date") or "") or None
        limit_data_status = (
            "aligned"
            if market_date and limit_market_date == market_date
            else ("date_mismatch" if limit_market_date else "unavailable")
        )
        limit_up = (
            limits.get("limit_up") if limit_data_status == "aligned" else None
        )
        limit_down = (
            limits.get("limit_down") if limit_data_status == "aligned" else None
        )
        return {
            "total": total,
            "rising": rising,
            "risingRate": round(
                float(breadth.get("advance_ratio") or 0) * 100,
                2,
            ),
            "flat": flat,
            "flatRate": round(
                float(breadth.get("unchanged_ratio") or 0) * 100,
                2,
            ),
            "falling": falling,
            "fallingRate": round(
                float(breadth.get("decline_ratio") or 0) * 100,
                2,
            ),
            "limitUp": limit_up,
            "limitUpRate": (
                round(float(limit_up) / total * 100, 2)
                if total and limit_up is not None
                else None
            ),
            "limitDown": limit_down,
            "limitDownRate": (
                round(float(limit_down) / total * 100, 2)
                if total and limit_down is not None
                else None
            ),
            "marketDate": market_date,
            "marketTimestamp": packet.get("market_timestamp"),
            "fetchedAt": packet.get("fetched_at"),
            "source": packet.get("source"),
            "limitDataAsOf": limit_market_date,
            "limitDataStatus": limit_data_status,
        }

    def rise_fall_distribution(
        self,
        *,
        breadth_packet: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        packet = breadth_packet or self._breadth()
        breadth = packet.get("breadth") or {}
        distribution = packet.get("distribution") or {}
        bins = distribution.get("bins") or {}
        total = float(breadth.get("total") or 0)

        def rate(value: Any) -> float:
            return round(float(value or 0) / total * 100, 2) if total else 0.0

        return {
            "rising": breadth.get("advancers"),
            "risingRate": round(float(breadth.get("advance_ratio") or 0) * 100, 2),
            "flat": breadth.get("unchanged"),
            "flatRate": round(float(breadth.get("unchanged_ratio") or 0) * 100, 2),
            "falling": breadth.get("decliners"),
            "fallingRate": round(float(breadth.get("decline_ratio") or 0) * 100, 2),
            "bins": [
                {
                    "label": "≥3%",
                    "count": bins.get("strong_advancers_ge_3", 0),
                    "rate": rate(bins.get("strong_advancers_ge_3")),
                    "type": "up",
                },
                {
                    "label": "0~3%",
                    "count": bins.get("mild_advancers_gt_0_lt_3", 0),
                    "rate": rate(bins.get("mild_advancers_gt_0_lt_3")),
                    "type": "up",
                },
                {
                    "label": "平盘",
                    "count": bins.get("unchanged", breadth.get("unchanged", 0)),
                    "rate": rate(
                        bins.get("unchanged", breadth.get("unchanged", 0))
                    ),
                    "type": "flat",
                },
                {
                    "label": "0~-3%",
                    "count": bins.get("mild_decliners_lt_0_gt_neg3", 0),
                    "rate": rate(bins.get("mild_decliners_lt_0_gt_neg3")),
                    "type": "down",
                },
                {
                    "label": "≤-3%",
                    "count": bins.get("strong_decliners_le_neg3", 0),
                    "rate": rate(bins.get("strong_decliners_le_neg3")),
                    "type": "down",
                },
            ],
            "marketDate": packet.get("market_date"),
            "fetchedAt": packet.get("fetched_at"),
            "source": packet.get("source"),
        }

    def industry_rotation(
        self,
        limit: int = 5,
        *,
        packet: dict[str, Any] | None = None,
        allow_remote: bool = True,
    ) -> list[dict[str, Any]]:
        packet = packet or self.analysis.hot_sectors(limit=max(limit, 20))
        sectors = list(packet.get("sectors") or [])[:limit]

        def load_history(item: dict[str, Any]) -> dict[str, Any]:
            code = str(item.get("code") or "")
            if not code or not hasattr(self.analysis, "sector_history"):
                return {"status": "unavailable", "points": []}
            try:
                return self.analysis.sector_history(
                    code,
                    days=5,
                    allow_remote=allow_remote,
                )
            except Exception as exc:
                return {
                    "status": "unavailable",
                    "points": [],
                    "warnings": [type(exc).__name__],
                }

        histories: list[dict[str, Any]] = []
        if sectors:
            with ThreadPoolExecutor(
                max_workers=min(3, len(sectors)),
                thread_name_prefix="qingshu-sector-history",
            ) as executor:
                histories = list(executor.map(load_history, sectors))

        items = []
        packet_market_date = self._market_date_from_timestamp(
            packet.get("market_timestamp")
        )
        for index, item in enumerate(sectors, start=1):
            history = histories[index - 1] if index <= len(histories) else {}
            raw_points = list(history.get("points") or [])
            points = [
                {
                    "market_date": str(point.get("market_date") or ""),
                    "close": float(point["close"]),
                }
                for point in raw_points
                if point.get("market_date") and point.get("close") is not None
            ]
            points = sorted(points, key=lambda point: point["market_date"])[-5:]
            available = history.get("status") == "available" and len(points) >= 3
            trend = [point["close"] for point in points] if available else []
            trend_dates = (
                [point["market_date"] for point in points] if available else []
            )
            first = trend[0] if trend else None
            last = trend[-1] if trend else None
            five_day_change = (
                round((last / first - 1) * 100, 2)
                if first not in (None, 0) and last is not None
                else None
            )
            items.append(
                {
                "rank": index,
                "code": item.get("code"),
                "name": item.get("name"),
                "changePct": item.get("pct_change"),
                "fiveDayChangePct": five_day_change,
                "turnover": _yuan_to_100m(item.get("turnover")),
                "trend": trend,
                "trendMarketDates": trend_dates,
                "trendStatus": "available" if available else "unavailable",
                "historySource": history.get("source"),
                "advancers": item.get("advancers"),
                "decliners": item.get("decliners"),
                "marketDate": (
                    trend_dates[-1] if trend_dates else packet_market_date
                ),
                "marketTimestamp": packet.get("market_timestamp"),
                "source": packet.get("source"),
            }
            )
        return items

    def hot_themes(
        self,
        limit: int = 5,
        *,
        packet: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        packet = packet or self.analysis.hot_sectors(limit=max(limit, 20))
        items = []
        for index, item in enumerate(
            (packet.get("sectors") or [])[:limit], start=1
        ):
            tags = []
            if item.get("advancers") is not None:
                tags.append(f"{item['advancers']}家上涨")
            if item.get("decliners") is not None:
                tags.append(f"{item['decliners']}家下跌")
            items.append(
                {
                    "rank": index,
                    "name": item.get("name"),
                    "changePct": item.get("pct_change"),
                    "leader": "",
                    "tags": tags,
                    "marketDate": self._market_date_from_timestamp(
                        packet.get("market_timestamp")
                    ),
                    "marketTimestamp": packet.get("market_timestamp"),
                    "source": packet.get("source"),
                }
            )
        return items

    def sector_fund_flow(
        self,
        limit: int = 10,
        *,
        packet: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        packet = packet or self.analysis.hot_sectors(limit=100)
        sectors = [
            item
            for item in packet.get("sectors") or []
            if item.get("main_net_inflow") is not None
        ]
        positives = sorted(
            (item for item in sectors if float(item["main_net_inflow"]) >= 0),
            key=lambda item: float(item["main_net_inflow"]),
            reverse=True,
        )
        negatives = sorted(
            (item for item in sectors if float(item["main_net_inflow"]) < 0),
            key=lambda item: float(item["main_net_inflow"]),
        )
        positive_count = max(1, limit // 2)
        negative_count = max(0, limit - positive_count)
        selected = positives[:positive_count] + negatives[:negative_count]
        if len(selected) < limit:
            selected_ids = {id(item) for item in selected}
            remaining = sorted(
                (item for item in sectors if id(item) not in selected_ids),
                key=lambda item: abs(float(item["main_net_inflow"])),
                reverse=True,
            )
            selected.extend(remaining[: limit - len(selected)])
        selected = sorted(
            (item for item in selected if float(item["main_net_inflow"]) >= 0),
            key=lambda item: float(item["main_net_inflow"]),
            reverse=True,
        ) + sorted(
            (item for item in selected if float(item["main_net_inflow"]) < 0),
            key=lambda item: float(item["main_net_inflow"]),
        )
        items = [
            {
                "name": item.get("name"),
                "value": round(float(item["main_net_inflow"]) / 100_000_000, 2),
                "changePct": item.get("pct_change"),
                "marketTimestamp": packet.get("market_timestamp"),
                "source": packet.get("source"),
            }
            for item in selected
        ]
        positive = [item["value"] for item in items if item["value"] >= 0]
        negative = [item["value"] for item in items if item["value"] < 0]
        return {
            "items": items,
            "metric": "main_net_inflow_estimate_100m_cny",
            "metric_label": "主力净流入估算（亿元）",
            "data_status": "available" if items else "empty",
            "summary": {
                "positive_count": len(positive),
                "negative_count": len(negative),
                "selected_net_total": round(sum(positive) + sum(negative), 2),
            },
            "marketDate": self._market_date_from_timestamp(
                packet.get("market_timestamp")
            ),
            "marketTimestamp": packet.get("market_timestamp"),
            "source": packet.get("source"),
        }

    def trading_activity(
        self,
        days: int = 7,
        *,
        breadth_packet: dict[str, Any] | None = None,
        allow_remote: bool = True,
    ) -> dict[str, Any]:
        days = max(1, min(days, 14))
        now = time.monotonic()
        with self._lock:
            cached = self._activity_cache.get(days)
            if cached and cached[0] > now:
                cached_points = list(cached[1].get("points") or [])
                if not (
                    allow_remote
                    and self.tushare_client is not None
                    and len(cached_points) < min(days, 3)
                ):
                    return cached[1]
            result = self._build_trading_activity(
                days,
                breadth_packet=breadth_packet,
                allow_remote=allow_remote,
            )
            self._activity_cache[days] = (now + 300, result)
            return result

    def _build_trading_activity(
        self,
        days: int,
        *,
        breadth_packet: dict[str, Any] | None = None,
        allow_remote: bool = True,
    ) -> dict[str, Any]:
        snapshots = self.database.list_market_breadth_snapshots(limit=days)
        by_date: dict[str, float] = {}
        for snapshot in snapshots:
            market_date = str(snapshot.get("market_date") or "")
            value = (snapshot.get("turnover") or {}).get(
                "total_amount_100m_cny"
            )
            if market_date and value is not None:
                by_date[market_date] = float(value)

        if (
            allow_remote
            and len(by_date) < days
            and self.tushare_client is not None
        ):
            by_date.update(self._tushare_turnover_history(days))

        current = breadth_packet or self._breadth()
        current_date = str(current.get("market_date") or "")
        current_value = (current.get("turnover") or {}).get(
            "total_amount_100m_cny"
        )
        if current_date and current_value is not None:
            by_date[current_date] = float(current_value)

        selected = sorted(by_date.items())[-days:]
        points = [
            {
                "date": datetime.strptime(day, "%Y-%m-%d").strftime("%m/%d"),
                "value": round(value, 2),
                "marketDate": day,
            }
            for day, value in selected
        ]
        average = round(mean(item["value"] for item in points), 2) if points else None
        latest = points[-1]["value"] if points else None
        previous_values = [item["value"] for item in points[:-1]]
        previous_average = (
            round(mean(previous_values), 2) if previous_values else None
        )
        shanghai_now = datetime.now(ZoneInfo("Asia/Shanghai"))
        latest_market_date = (
            str(points[-1].get("marketDate") or "") if points else ""
        )
        latest_is_intraday = bool(
            latest_market_date == shanghai_now.date().isoformat()
            and shanghai_now.strftime("%H:%M") < "15:05"
        )
        if latest_is_intraday and previous_average is not None:
            average = previous_average
        change_pct = (
            round((latest / previous_average - 1) * 100, 2)
            if (
                not latest_is_intraday
                and latest is not None
                and previous_average not in (None, 0)
            )
            else None
        )
        relative_to_average_pct = (
            round((latest / average - 1) * 100, 2)
            if (
                not latest_is_intraday
                and latest is not None
                and average not in (None, 0)
            )
            else None
        )
        activity_label = (
            "盘中累计，收盘后比较"
            if latest_is_intraday
            else "成交额数据不足"
        )
        if relative_to_average_pct is not None:
            if relative_to_average_pct >= 5:
                activity_label = f"较近{days}日均值放量"
            elif relative_to_average_pct <= -5:
                activity_label = f"较近{days}日均值缩量"
            else:
                activity_label = f"较近{days}日均值持平"
        return {
            "period": f"近{days}日",
            "average": average,
            "latest": latest,
            "previous_average": previous_average,
            "changePct": change_pct,
            "change_pct": change_pct,
            "relative_to_average_pct": relative_to_average_pct,
            "activity_label": activity_label,
            "latest_is_intraday": latest_is_intraday,
            "data_status": "available" if points else "empty",
            "marketDate": points[-1]["marketDate"] if points else None,
            "points": points,
            "source": "Tushare Pro 日线成交额 + 全市场实时成交额",
            "fetchedAt": utc_now(),
        }

    def _tushare_turnover_history(self, days: int) -> dict[str, float]:
        end = datetime.now(ZoneInfo("Asia/Shanghai")).date()
        start = end - timedelta(days=days * 3 + 10)
        try:
            calendar = self.tushare_client.trade_cal(
                exchange="",
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
                is_open="1",
                fields="cal_date,is_open",
            )
        except Exception:
            return {}
        dates = sorted(
            {
                str(value)
                for value in calendar.get("cal_date", []).tolist()
                if re.fullmatch(r"\d{8}", str(value))
            }
        )[-days:]

        def fetch_one(trade_date: str) -> tuple[str, float] | None:
            try:
                frame = self.tushare_client.query(
                    "daily",
                    trade_date=trade_date,
                    fields="trade_date,ts_code,amount",
                )
                if len(frame) >= 3000 and "amount" in frame:
                    amount = float(frame["amount"].fillna(0).sum())
                    return (
                        datetime.strptime(
                            trade_date, "%Y%m%d"
                        ).date().isoformat(),
                        round(amount / 100_000, 2),
                    )
            except Exception:
                return None
            return None

        results: dict[str, float] = {}
        with ThreadPoolExecutor(
            max_workers=min(3, max(1, len(dates))),
            thread_name_prefix="qingshu-turnover-history",
        ) as executor:
            for item in executor.map(fetch_one, dates):
                if item is not None:
                    results[item[0]] = item[1]
        return results

    def _breadth(self) -> dict[str, Any]:
        packet = self.analysis.market_breadth()
        if packet.get("status") != "available":
            raise RuntimeError("全市场广度暂不可用")
        return packet

    def _limit_snapshot(self) -> dict[str, Any]:
        if self.tushare_client is None:
            return self._empty_limit_snapshot()
        now = time.monotonic()
        with self._lock:
            if self._limit_cache and self._limit_cache[0] > now:
                return self._limit_cache[1]
        if self._limit_executor is None:
            return self._refresh_limit_snapshot()
        persistent = self.database.get_cache(self.LIMIT_CACHE_KEY)
        if persistent is not None:
            with self._lock:
                self._limit_cache = (now + 300, persistent)
            if persistent.get("data_status") == "available":
                return persistent
            self._schedule_limit_refresh()
            return persistent
        if self._limit_executor is not None:
            stale = self.database.get_cache(
                self.LIMIT_CACHE_KEY,
                allow_stale=True,
            )
            self._schedule_limit_refresh()
            return stale or self._empty_limit_snapshot(refreshing=True)
        return self._refresh_limit_snapshot()

    def _schedule_limit_refresh(self) -> None:
        if self._limit_executor is None:
            return
        with self._lock:
            if self._limit_refreshing:
                return
            self._limit_refreshing = True
        self._limit_executor.submit(self._limit_refresh_job)

    def _limit_refresh_job(self) -> None:
        try:
            self._refresh_limit_snapshot()
        except Exception:
            pass
        finally:
            with self._lock:
                self._limit_refreshing = False

    def _refresh_limit_snapshot(self) -> dict[str, Any]:
        result = self._fetch_limit_snapshot()
        with self._lock:
            ttl = 300 if result.get("data_status") == "available" else 30
            self._limit_cache = (time.monotonic() + ttl, result)
        if (
            hasattr(self.database, "put_cache")
            and result.get("data_status") == "available"
        ):
            self.database.put_cache(self.LIMIT_CACHE_KEY, result, 300)
        return result

    @staticmethod
    def _empty_limit_snapshot(
        *,
        refreshing: bool = False,
    ) -> dict[str, Any]:
        return {
            "market_date": None,
            "limit_up": None,
            "limit_down": None,
            "boards": {},
            "data_status": "warming" if refreshing else "unavailable",
            "refreshing": refreshing,
        }

    def _fetch_limit_snapshot(self) -> dict[str, Any]:
        current = datetime.now(ZoneInfo("Asia/Shanghai")).date()
        for offset in range(0, 12):
            candidate = current - timedelta(days=offset)
            if candidate.weekday() >= 5:
                continue
            trade_date = candidate.strftime("%Y%m%d")
            try:
                up = self.tushare_client.query(
                    "limit_list_d", trade_date=trade_date, limit_type="U"
                )
                down = self.tushare_client.query(
                    "limit_list_d", trade_date=trade_date, limit_type="D"
                )
            except Exception:
                continue
            if up.empty and down.empty:
                continue
            boards = {
                key: {"up": 0, "down": 0}
                for key in ("sh_main", "sz_main", "chinext", "star")
            }
            for direction, frame in (("up", up), ("down", down)):
                if "ts_code" not in frame:
                    continue
                for symbol in frame["ts_code"].astype(str):
                    board = _board_for_symbol(symbol)
                    if board:
                        boards[board][direction] += 1
            return {
                "market_date": candidate.isoformat(),
                "limit_up": int(len(up)),
                "limit_down": int(len(down)),
                "boards": boards,
                "data_status": "available",
                "source": "Tushare limit_list_d",
                "fetched_at": utc_now(),
            }
        return self._empty_limit_snapshot()


def _board_for_symbol(symbol: str) -> str | None:
    value = symbol.strip().upper()
    code = value.split(".", 1)[0]
    if value.endswith(".SH") and code.startswith(("600", "601", "603", "605")):
        return "sh_main"
    if value.endswith(".SH") and code.startswith(("688", "689")):
        return "star"
    if value.endswith(".SZ") and code.startswith(("300", "301")):
        return "chinext"
    if value.endswith(".SZ") and code.startswith(("000", "001", "002", "003")):
        return "sz_main"
    return None


def _yuan_to_100m(value: Any) -> float | None:
    if value is None:
        return None
    return round(float(value) / 100_000_000, 2)


def _two_point_trend(latest: Any, change_pct: Any) -> list[float]:
    if latest is None:
        return []
    latest_value = float(latest)
    if change_pct is None or float(change_pct) == -100:
        return [latest_value, latest_value]
    previous = latest_value / (1 + float(change_pct) / 100)
    return [round(previous, 4), latest_value]
