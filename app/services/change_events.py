from __future__ import annotations

import hashlib
import json
from typing import Any

from app.catalog import RESEARCH_TARGETS, normalize_symbol
from app.db import Database
from app.services.security_master import SecurityMasterService
from app.utils import utc_now


class ChangeEventNotFound(LookupError):
    pass


class ChangeEventService:
    """Build a small, source-verified event whitelist from persisted evidence."""

    CONTRACT_VERSION = "change_events_v1"
    PRICE_RULE_VERSION = "daily_move_abs_5pct_v1"
    DISCLOSURE_RULE_VERSION = "official_financial_disclosure_v1"
    PRICE_THRESHOLD_PCT = 5.0
    ENABLED_EVENT_TYPES = (
        "official_financial_disclosure",
        "daily_price_anomaly",
    )
    UNCOVERED_EVENT_TYPES = (
        "trading_halt_resume",
        "restricted_share_unlock",
        "shareholder_increase_decrease",
    )
    _FINANCIAL_DISCLOSURE_TERMS = (
        "年度报告",
        "半年度报告",
        "季度报告",
        "一季度报告",
        "三季度报告",
        "业绩预告",
        "业绩快报",
        "10-q",
        "10-k",
        "financial results",
        "earnings report",
    )
    _OFFICIAL_EVIDENCE_LEVELS = {
        "official_disclosure",
        "regulatory_filing",
    }

    def __init__(self, database: Database) -> None:
        self.database = database
        self.security_master = SecurityMasterService(database)

    def refresh_symbol(self, symbol: str) -> dict[str, Any]:
        canonical = normalize_symbol(symbol)
        events: list[dict[str, Any]] = []
        events.extend(self._refresh_official_financial_disclosures(canonical))
        price_event = self._refresh_daily_price_anomaly(canonical)
        if price_event is not None:
            events.append(price_event)
        return {
            "symbol": canonical,
            "events": events,
            "event_count": len(events),
            "enabled_event_types": list(self.ENABLED_EVENT_TYPES),
            "uncovered_event_types": list(self.UNCOVERED_EVENT_TYPES),
        }

    def refresh_symbols(self, symbols: list[str]) -> dict[str, Any]:
        canonical_symbols = sorted({normalize_symbol(symbol) for symbol in symbols})
        results: list[dict[str, Any]] = []
        for symbol in canonical_symbols:
            try:
                result = self.refresh_symbol(symbol)
                results.append(
                    {
                        "symbol": symbol,
                        "status": "ok",
                        "event_count": result["event_count"],
                    }
                )
            except Exception as exc:
                results.append(
                    {
                        "symbol": symbol,
                        "status": "failed",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
        return {
            "requested": len(canonical_symbols),
            "completed": sum(item["status"] == "ok" for item in results),
            "results": results,
        }

    def refresh_user(self, user_id: str) -> dict[str, Any]:
        watchlist = self.database.list_watchlist(user_id)
        symbols = [str(item.get("symbol") or "") for item in watchlist]
        refreshed = self.refresh_symbols([symbol for symbol in symbols if symbol])
        links_created = 0
        for symbol in symbols:
            if symbol:
                links_created += self.database.ensure_user_change_links(
                    user_id, normalize_symbol(symbol)
                )
        return {
            **refreshed,
            "watchlist_count": len(watchlist),
            "links_created": links_created,
        }

    def refresh_all_users(self) -> dict[str, Any]:
        user_ids = self.database.list_watchlist_user_ids()
        results = []
        for user_id in user_ids:
            try:
                result = self.refresh_user(user_id)
                results.append(
                    {
                        "user_id": user_id,
                        "status": "ok",
                        "event_count": sum(
                            int(item.get("event_count") or 0)
                            for item in result.get("results") or []
                        ),
                        "links_created": result["links_created"],
                    }
                )
            except Exception as exc:
                results.append(
                    {
                        "user_id": user_id,
                        "status": "failed",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
        return {
            "requested_users": len(user_ids),
            "completed_users": sum(item["status"] == "ok" for item in results),
            "results": results,
        }

    def get_user_packet(
        self,
        user_id: str,
        *,
        symbol: str | None = None,
        relevance_status: str | None = None,
        limit: int = 50,
        refresh: bool = True,
    ) -> dict[str, Any]:
        canonical = normalize_symbol(symbol) if symbol else None
        watchlist = self.database.list_watchlist(user_id)
        watchlist_symbols = {
            normalize_symbol(str(item.get("symbol") or ""))
            for item in watchlist
            if item.get("symbol")
        }
        if refresh:
            if canonical is None:
                self.refresh_user(user_id)
            elif canonical in watchlist_symbols:
                self.refresh_symbol(canonical)
                self.database.ensure_user_change_links(user_id, canonical)

        raw_limit = min(500, max(limit, limit * 3))
        items = self.database.list_user_change_links(
            user_id,
            symbol=canonical,
            relevance_status=relevance_status,
            limit=raw_limit,
        )
        active_symbols = watchlist_symbols
        if canonical is None:
            items = [item for item in items if item.get("symbol") in active_symbols]
        elif canonical not in active_symbols:
            items = []
        items = self._dedupe_user_links(items)[:limit]
        pending_unread = [
            item
            for item in items
            if item.get("relevance_status") == "pending"
            and item.get("read_at") is None
            and item.get("handled_at") is None
        ]
        public_items = [self._public_link(item) for item in items]
        public_pending = [self._public_link(item) for item in pending_unread]
        counts = {
            "total": len(public_items),
            "pending": sum(
                item.get("relevance_status") == "pending" for item in public_items
            ),
            "pending_unread": len(public_pending),
            "relevant": sum(
                item.get("relevance_status") == "relevant" for item in public_items
            ),
            "irrelevant": sum(
                item.get("relevance_status") == "irrelevant" for item in public_items
            ),
        }
        return {
            "contract_version": self.CONTRACT_VERSION,
            "generated_at": utc_now(),
            "status": "available" if watchlist else "empty",
            "symbol": canonical,
            "items": public_items,
            "pending_unread_items": public_pending,
            "counts": counts,
            "coverage": self._coverage(),
            "empty_message": (
                "添加关注股票后，已验收的重要变化会进入这里。"
                if not watchlist
                else "当前没有新的已验收变化。"
                if not public_items
                else None
            ),
            "boundary": self._boundary(),
        }

    @classmethod
    def _dedupe_user_links(cls, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Hide legacy duplicate events without rewriting a user's history.

        Older rule implementations could produce a new dedupe hash for the same
        semantic event. Keep one representative per stock, event type, rule and
        fact date. A link the user has already handled or read wins over a newer
        pending duplicate so the same fact is not surfaced again as unfinished.
        """

        grouped: dict[tuple[str, ...], dict[str, Any]] = {}
        order: list[tuple[str, ...]] = []
        for item in items:
            identity = cls._semantic_identity(item)
            current = grouped.get(identity)
            if current is None:
                grouped[identity] = item
                order.append(identity)
                continue
            if cls._user_link_state_rank(item) > cls._user_link_state_rank(current):
                grouped[identity] = item
        return [grouped[identity] for identity in order]

    @staticmethod
    def _semantic_identity(item: dict[str, Any]) -> tuple[str, ...]:
        event_type = str(item.get("event_type") or "")
        symbol = str(item.get("symbol") or "")
        rule_version = str(item.get("rule_version") or "")
        occurred_at = str(item.get("occurred_at") or "")
        payload = item.get("payload") or {}
        if event_type == "daily_price_anomaly":
            fact_date = str(payload.get("daily_date") or occurred_at[:10])
            return symbol, event_type, rule_version, fact_date
        if event_type == "official_financial_disclosure":
            source_identity = str(item.get("source_url") or "").strip().casefold()
            if not source_identity:
                source_identity = " ".join(
                    str(item.get("title") or "").split()
                ).casefold()
            return symbol, event_type, rule_version, occurred_at[:10], source_identity
        event_id = str(item.get("event_id") or item.get("link_id") or "")
        return symbol, event_type, rule_version, event_id

    @staticmethod
    def _user_link_state_rank(item: dict[str, Any]) -> tuple[int, int, str]:
        handled = int(
            bool(item.get("handled_at"))
            or item.get("relevance_status") in {"relevant", "irrelevant"}
        )
        read = int(bool(item.get("read_at")))
        updated_at = str(
            item.get("link_updated_at")
            or item.get("detected_at")
            or item.get("linked_at")
            or ""
        )
        return handled, read, updated_at

    def get_user_change(self, user_id: str, link_id: str) -> dict[str, Any]:
        item = self.database.get_user_change_link(user_id, link_id)
        if item is None:
            raise ChangeEventNotFound("变化事件不存在或不属于当前用户")
        return self._public_link(item)

    def mark_read(self, user_id: str, link_id: str) -> dict[str, Any]:
        item = self.database.mark_user_change_read(user_id, link_id)
        if item is None:
            raise ChangeEventNotFound("变化事件不存在或不属于当前用户")
        return self._public_link(item)

    def set_relevance(
        self, user_id: str, link_id: str, relevance_status: str
    ) -> dict[str, Any]:
        item = self.database.set_user_change_relevance(
            user_id, link_id, relevance_status
        )
        if item is None:
            raise ChangeEventNotFound("变化事件不存在或不属于当前用户")
        return self._public_link(item)

    def _refresh_official_financial_disclosures(
        self, symbol: str
    ) -> list[dict[str, Any]]:
        snapshot = self.database.latest_event_timeline_snapshot(symbol)
        if snapshot is None:
            return []
        payload = snapshot.get("payload") or {}
        output = []
        for item in payload.get("events") or []:
            title = " ".join(str(item.get("title") or "").split())
            if not title or not self._is_financial_disclosure(title):
                continue
            if item.get("evidence_level") not in self._OFFICIAL_EVIDENCE_LEVELS:
                continue
            occurred_at = str(
                item.get("published_at") or item.get("event_date") or ""
            ).strip()
            if not occurred_at:
                continue
            source_name = str(
                item.get("source") or item.get("evidence_label") or "公司或监管披露"
            ).strip()
            source_url = str(item.get("url") or "").strip() or None
            name = str(
                payload.get("name")
                or (RESEARCH_TARGETS.get(symbol) or {}).get("name")
                or symbol
            )
            event_payload = {
                "name": name,
                "event_date": item.get("event_date"),
                "published_at": item.get("published_at"),
                "category": item.get("category"),
                "evidence_level": item.get("evidence_level"),
                "evidence_label": item.get("evidence_label"),
                "event_status": item.get("event_status"),
                "timeline_snapshot_id": snapshot.get("id"),
                "impact_inference_excluded": True,
            }
            dedupe_hash = _dedupe_hash(
                {
                    "symbol": symbol,
                    "event_type": "official_financial_disclosure",
                    "rule_version": self.DISCLOSURE_RULE_VERSION,
                    "title": title,
                    "occurred_at": occurred_at,
                    "source_url": source_url,
                }
            )
            output.append(
                self.database.upsert_change_event(
                    symbol=symbol,
                    event_type="official_financial_disclosure",
                    title=title,
                    fact_summary=(
                        f"{name}于{_date_label(occurred_at)}发布《{title}》。"
                        "当前只确认披露已经发布；具体金额、口径和影响仍需阅读原文核验。"
                    ),
                    occurred_at=occurred_at,
                    detected_at=str(snapshot.get("created_at") or utc_now()),
                    source_name=source_name,
                    source_url=source_url,
                    data_status="confirmed_disclosure",
                    rule_version=self.DISCLOSURE_RULE_VERSION,
                    dedupe_hash=dedupe_hash,
                    payload=event_payload,
                )
            )
        return output

    def _refresh_daily_price_anomaly(self, symbol: str) -> dict[str, Any] | None:
        report = self.database.latest_research_report(symbol)
        if report is None:
            return None
        evidence = report.get("evidence") or {}
        metrics = evidence.get("metrics") or {}
        return_1d_pct = _finite_float(metrics.get("return_1d_pct"))
        latest_close = _finite_float(metrics.get("latest_close"))
        if return_1d_pct is None or abs(return_1d_pct) < self.PRICE_THRESHOLD_PCT:
            return None
        provenance = evidence.get("provenance") or {}
        daily_timestamp = str(
            provenance.get("market_timestamp") or report.get("market_timestamp") or ""
        ).strip()
        if not daily_timestamp:
            return None
        volume_ratio = _finite_float(metrics.get("volume_ratio_5_20"))
        name = str(
            report.get("name")
            or evidence.get("display_name")
            or (RESEARCH_TARGETS.get(symbol) or {}).get("name")
            or symbol
        )
        direction = "上涨" if return_1d_pct > 0 else "下跌"
        close_text = f"收于{latest_close:.2f}，" if latest_close is not None else ""
        volume_text = (
            f"；5日与20日平均成交量之比为{volume_ratio:.2f}"
            if volume_ratio is not None
            else ""
        )
        current_quote = evidence.get("current_quote") or {}
        event_payload = {
            "name": name,
            "daily_timestamp": daily_timestamp,
            "daily_date": _date_label(daily_timestamp),
            "latest_close": latest_close,
            "return_1d_pct": return_1d_pct,
            "volume_ratio_5_20": volume_ratio,
            "report_id": report.get("id"),
            "report_generated_at": report.get("generated_at"),
            "current_quote_excluded": True,
            "current_quote_timestamp": current_quote.get("market_timestamp"),
            "current_quote_pct_change": current_quote.get("pct_change"),
            "impact_inference_excluded": True,
        }
        dedupe_hash = _dedupe_hash(
            {
                "symbol": symbol,
                "event_type": "daily_price_anomaly",
                "rule_version": self.PRICE_RULE_VERSION,
                "daily_date": _date_label(daily_timestamp),
            }
        )
        return self.database.upsert_change_event(
            symbol=symbol,
            event_type="daily_price_anomaly",
            title=f"{name}上一完整交易日{direction} {abs(return_1d_pct):.2f}%",
            fact_summary=(
                f"{name}最近一根完整日线（{_date_label(daily_timestamp)}）"
                f"{close_text}单日{direction}{abs(return_1d_pct):.2f}%{volume_text}。"
                "这里只描述已经发生的价格与交易活跃度，不解释资金意图或长期基本面。"
            ),
            occurred_at=daily_timestamp,
            detected_at=str(report.get("generated_at") or utc_now()),
            source_name=str(provenance.get("source") or "研究报告日线数据"),
            source_url=str(provenance.get("source_url") or "").strip() or None,
            data_status="confirmed_daily_bar",
            rule_version=self.PRICE_RULE_VERSION,
            dedupe_hash=dedupe_hash,
            payload=event_payload,
        )

    @classmethod
    def _is_financial_disclosure(cls, title: str) -> bool:
        folded = title.casefold()
        return any(
            term.casefold() in folded for term in cls._FINANCIAL_DISCLOSURE_TERMS
        )

    def _public_link(self, item: dict[str, Any]) -> dict[str, Any]:
        payload = dict(item.get("payload") or {})
        event_type = str(item.get("event_type") or "")
        symbol = str(item.get("symbol") or "")
        original_name = str(payload.get("name") or "").strip()
        display_name = self.security_master.display_name(symbol, original_name)

        def localized(value: Any) -> Any:
            if not original_name or original_name == display_name:
                return value
            if isinstance(value, str):
                return value.replace(original_name, display_name)
            if isinstance(value, list):
                return [localized(child) for child in value]
            if isinstance(value, dict):
                return {key: localized(child) for key, child in value.items()}
            return value

        payload = localized(payload)
        daily_move = abs(_finite_float(payload.get("return_1d_pct")) or 0)
        severity = (
            "high"
            if event_type == "daily_price_anomaly" and daily_move >= 7
            else "notice"
        )
        return {
            "link_id": item.get("link_id"),
            "event_id": item.get("event_id"),
            "symbol": item.get("symbol"),
            "name": display_name,
            "event_type": event_type,
            "event_type_label": {
                "official_financial_disclosure": "官方财务披露",
                "daily_price_anomaly": "完整日线价格异常",
            }.get(event_type, "已验收变化"),
            "title": localized(item.get("title")),
            "fact_summary": localized(item.get("fact_summary")),
            "occurred_at": item.get("occurred_at"),
            "detected_at": item.get("detected_at"),
            "source_name": item.get("source_name"),
            "source_url": item.get("source_url"),
            "data_status": item.get("data_status"),
            "data_status_label": {
                "confirmed_disclosure": "已确认披露",
                "confirmed_daily_bar": "完整日线已确认",
            }.get(str(item.get("data_status") or ""), "事实已归档"),
            "rule_version": item.get("rule_version"),
            "relevance_status": item.get("relevance_status"),
            "relevance_status_label": {
                "pending": "待判断相关性",
                "relevant": "与我有关",
                "irrelevant": "与我无关",
            }.get(str(item.get("relevance_status") or ""), "待判断相关性"),
            "read_at": item.get("read_at"),
            "handled_at": item.get("handled_at"),
            "severity": severity,
            "payload": payload,
            "boundary": self._event_boundary(event_type),
        }

    @classmethod
    def _coverage(cls) -> dict[str, Any]:
        return {
            "event_whitelist_complete": False,
            "enabled_event_types": list(cls.ENABLED_EVENT_TYPES),
            "uncovered_event_types": list(cls.UNCOVERED_EVENT_TYPES),
            "source_policy": (
                "只接受已入库的公司/监管披露索引，以及研究报告中的最近完整日线；"
                "页面请求不临时联网拼接事件。"
            ),
        }

    @classmethod
    def _event_boundary(cls, event_type: str) -> str:
        if event_type == "official_financial_disclosure":
            return "只确认官方披露已经发布，不根据标题推断业绩好坏或股价影响。"
        if event_type == "daily_price_anomaly":
            return "使用最近一根完整日线，不混用盘中报价；价格异常不等于基本面变化或交易信号。"
        return cls._boundary()

    @classmethod
    def _boundary(cls) -> str:
        return (
            "当前白名单只启用官方财务披露和完整日线绝对涨跌达到5%的价格异常；"
            "停复牌、限售解禁、股东增减持仍待逐类完成来源与规则验收。"
        )


def _finite_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or abs(number) == float("inf"):
        return None
    return number


def _date_label(value: str) -> str:
    return value[:10] if len(value) >= 10 else value


def _dedupe_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
