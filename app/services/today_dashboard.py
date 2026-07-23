from __future__ import annotations

from datetime import datetime, timedelta
from statistics import mean
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

    def __init__(
        self,
        database: Any,
        analysis: Any,
        *,
        intraday_index_provider: Any | None = None,
        tushare_client: Any | None = None,
        cache_seconds: int = 60,
    ) -> None:
        self.database = database
        self.analysis = analysis
        self.intraday_index_provider = intraday_index_provider
        self.tushare_client = tushare_client
        self.cache_seconds = max(20, cache_seconds)
        self._lock = threading.Lock()
        self._limit_cache: tuple[float, dict[str, Any]] | None = None
        self._activity_cache: tuple[float, dict[str, Any]] | None = None

    def index_quote(self, code: str) -> dict[str, Any]:
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
        limit_snapshot = self._limit_snapshot()
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
            "marketTimestamp": packet.get("market_timestamp"),
            "fetchedAt": packet.get("fetched_at"),
            "source": packet.get("source"),
            "limitDataAsOf": limit_snapshot.get("market_date"),
            "warnings": packet.get("warnings") or [],
        }

    def market_overview(self) -> dict[str, Any]:
        packet = self._breadth()
        breadth = packet.get("breadth") or {}
        total = int(breadth.get("total") or 0)
        rising = int(breadth.get("advancers") or 0)
        flat = int(breadth.get("unchanged") or 0)
        falling = int(breadth.get("decliners") or 0)
        limits = self._limit_snapshot()
        limit_up = limits.get("limit_up")
        limit_down = limits.get("limit_down")
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
            "marketDate": packet.get("market_date"),
            "marketTimestamp": packet.get("market_timestamp"),
            "fetchedAt": packet.get("fetched_at"),
            "source": packet.get("source"),
            "limitDataAsOf": limits.get("market_date"),
        }

    def rise_fall_distribution(self) -> dict[str, Any]:
        packet = self._breadth()
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

    def industry_rotation(self, limit: int = 5) -> list[dict[str, Any]]:
        packet = self.analysis.hot_sectors(limit=max(limit, 20))
        return [
            {
                "rank": index,
                "name": item.get("name"),
                "changePct": item.get("pct_change"),
                "fiveDayChangePct": None,
                "turnover": _yuan_to_100m(item.get("turnover")),
                "trend": _two_point_trend(
                    item.get("latest"), item.get("pct_change")
                ),
                "advancers": item.get("advancers"),
                "decliners": item.get("decliners"),
                "marketTimestamp": packet.get("market_timestamp"),
                "source": packet.get("source"),
            }
            for index, item in enumerate(
                (packet.get("sectors") or [])[:limit], start=1
            )
        ]

    def hot_themes(self, limit: int = 5) -> list[dict[str, Any]]:
        packet = self.analysis.hot_sectors(limit=max(limit, 20))
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
                    "marketTimestamp": packet.get("market_timestamp"),
                    "source": packet.get("source"),
                }
            )
        return items

    def sector_fund_flow(self, limit: int = 10) -> list[dict[str, Any]]:
        packet = self.analysis.hot_sectors(limit=100)
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
        return [
            {
                "name": item.get("name"),
                "value": round(float(item["main_net_inflow"]) / 100_000_000, 2),
                "changePct": item.get("pct_change"),
                "marketTimestamp": packet.get("market_timestamp"),
                "source": packet.get("source"),
            }
            for item in selected
        ]

    def trading_activity(self, days: int = 7) -> dict[str, Any]:
        days = max(1, min(days, 14))
        now = time.monotonic()
        with self._lock:
            if self._activity_cache and self._activity_cache[0] > now:
                return self._activity_cache[1]
            result = self._build_trading_activity(days)
            self._activity_cache = (now + 300, result)
            return result

    def _build_trading_activity(self, days: int) -> dict[str, Any]:
        snapshots = self.database.list_market_breadth_snapshots(limit=days)
        by_date: dict[str, float] = {}
        for snapshot in snapshots:
            market_date = str(snapshot.get("market_date") or "")
            value = (snapshot.get("turnover") or {}).get(
                "total_amount_100m_cny"
            )
            if market_date and value is not None:
                by_date[market_date] = float(value)

        if len(by_date) < days and self.tushare_client is not None:
            by_date.update(self._tushare_turnover_history(days))

        current = self._breadth()
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
        return {
            "period": f"近{days}日",
            "average": average,
            "changePct": None,
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
        dates = [
            str(value)
            for value in calendar.get("cal_date", []).tolist()
            if str(value)
        ][-days:]
        results: dict[str, float] = {}
        for trade_date in dates:
            try:
                frame = self.tushare_client.query(
                    "daily",
                    trade_date=trade_date,
                    fields="trade_date,amount",
                )
                if not frame.empty and "amount" in frame:
                    amount = float(frame["amount"].fillna(0).sum())
                    results[
                        datetime.strptime(trade_date, "%Y%m%d").date().isoformat()
                    ] = round(amount / 100_000, 2)
            except Exception:
                continue
            time.sleep(0.2)
        return results

    def _breadth(self) -> dict[str, Any]:
        packet = self.analysis.market_breadth()
        if packet.get("status") != "available":
            raise RuntimeError("全市场广度暂不可用")
        return packet

    def _limit_snapshot(self) -> dict[str, Any]:
        if self.tushare_client is None:
            return {
                "market_date": None,
                "limit_up": None,
                "limit_down": None,
                "boards": {},
            }
        now = time.monotonic()
        with self._lock:
            if self._limit_cache and self._limit_cache[0] > now:
                return self._limit_cache[1]
            result = self._fetch_limit_snapshot()
            self._limit_cache = (now + 300, result)
            return result

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
            }
        return {
            "market_date": None,
            "limit_up": None,
            "limit_down": None,
            "boards": {},
        }


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
