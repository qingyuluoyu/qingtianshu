from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Callable

from app.catalog import LIVE_MARKET_CATALOG, RESEARCH_TARGETS
from app.db import Database
from app.services.live_market import market_session_details
from app.utils import utc_now


class TodayOverviewService:
    """Aggregate the first-screen market facts and one user's research worklist."""

    CONTRACT_VERSION = "today_overview_v1"
    METHOD_VERSION = "deterministic_today_overview_v1"
    INDEX_SYMBOLS = ("000001.SS", "399001.SZ", "399006.SZ", "000688.SS")
    _CATEGORY_RANK = {
        "risk_review": 0,
        "user_task": 1,
        "change_event": 2,
        "trade_review": 3,
        "draft_confirmation": 4,
        "evidence_gap": 5,
        "research_task": 6,
    }
    _PRIORITY_RANK = {"high": 0, "normal": 1, "low": 2}
    _CHANGE_FRESHNESS_DAYS = {
        "daily_price_anomaly": 5,
        "official_financial_disclosure": 45,
    }

    def __init__(
        self,
        database: Database,
        analysis: Any,
        observation_tasks: Any,
        research_actions: Any,
        research_tracking: Any,
        structured_ai: Any,
        *,
        trade_workflow: Any | None = None,
        change_events: Any | None = None,
        session_provider: Callable[[], dict[str, Any]] | None = None,
    ):
        self.database = database
        self.analysis = analysis
        self.observation_tasks = observation_tasks
        self.research_actions = research_actions
        self.research_tracking = research_tracking
        self.structured_ai = structured_ai
        self.trade_workflow = trade_workflow
        self.change_events = change_events
        self.session_provider = session_provider or self._default_session

    def get_overview(self, user_id: str) -> dict[str, Any]:
        calls: dict[str, Callable[[], dict[str, Any]]] = {
            "indices": lambda: self.analysis.get_indices(scope="all", group="china"),
            "breadth": self.analysis.market_breadth,
            "industries": lambda: self.analysis.hot_sectors(limit=5),
            "tasks": lambda: self.observation_tasks.list_tasks(
                user_id=user_id, limit=100
            ),
            "actions": lambda: self.research_actions.get_packet(user_id, persist=False),
            "changes": lambda: self.research_tracking.get_packet(user_id, limit=20),
            "writebacks": lambda: self.structured_ai.list_writebacks(
                user_id=user_id, status="pending_confirmation", limit=20
            ),
        }
        if self.trade_workflow is not None:
            calls["trade_reviews"] = lambda: (
                self.trade_workflow.list_user_trade_reviews(user_id, limit=100)
            )
        if self.change_events is not None:
            calls["whitelist_changes"] = lambda: self.change_events.get_user_packet(
                user_id, limit=50
            )
        results, component_status = self._collect(calls)
        session = self.session_provider()
        watchlist = self.database.list_watchlist(user_id)
        whitelist_changes = self._dedupe_whitelist_changes(
            results.get("whitelist_changes") or {}
        )
        watchlist_names = {
            str(item.get("symbol")): str(
                item.get("name")
                or (RESEARCH_TARGETS.get(str(item.get("symbol"))) or {}).get("name")
                or item.get("symbol")
            )
            for item in watchlist
        }
        priority_items = self._priority_items(
            tasks=results.get("tasks") or {},
            actions=results.get("actions") or {},
            writebacks=results.get("writebacks") or {},
            trade_reviews=results.get("trade_reviews") or {},
            whitelist_changes=whitelist_changes,
            names=watchlist_names,
        )
        selected_change_links = {
            str(item.get("source_ref_id") or "")
            for item in priority_items
            if item.get("source_type") == "verified_change_event"
        }
        priority_change_keys = {
            self._canonical_change_key(event)
            for event in whitelist_changes.get("pending_unread_items") or []
            if str(event.get("link_id") or "") in selected_change_links
        }
        market = self._market_packet(
            results.get("indices") or {},
            results.get("breadth") or {},
            results.get("industries") or {},
            whitelist_changes,
        )
        personalized = self._personalized_packet(
            changes=results.get("changes") or {},
            whitelist_changes=whitelist_changes,
            actions=results.get("actions") or {},
            watchlist=watchlist,
            exclude_change_keys=priority_change_keys,
        )
        warnings = [
            label
            for key, label in (
                ("indices", "指数数据暂未完整返回"),
                ("breadth", "市场广度暂未完整返回"),
                ("industries", "行业结构暂未完整返回"),
                ("tasks", "个人观察任务暂未完整返回"),
                ("actions", "研究行动暂未完整返回"),
                ("changes", "与我相关的研究变化暂未完整返回"),
                ("writebacks", "待确认判断草稿暂未完整返回"),
                ("trade_reviews", "个人交易复盘暂未完整返回"),
                ("whitelist_changes", "已验收的重要变化暂未完整返回"),
            )
            if key in calls and component_status.get(key) != "ready"
        ]
        return {
            "contract_version": self.CONTRACT_VERSION,
            "method_version": self.METHOD_VERSION,
            "generated_at": utc_now(),
            "session": session,
            "summary": self._summary(session, priority_items, market, personalized),
            "priority_items": {
                "items": priority_items,
                "total_visible": len(priority_items),
                "ranking_method": (
                    "先按高风险、用户已保存任务、已验收变化、判断草稿确认、证据缺口排序，"
                    "同类再按用户优先级和更新时间排序；最多展示5项。"
                ),
                "empty_message": (
                    "当前没有需要立即处理的个人研究事项。"
                    if not priority_items
                    else None
                ),
            },
            "market": market,
            "personalized": personalized,
            "coverage": {
                "components": component_status,
                "watchlist_symbols": len(watchlist),
                "status": "ready" if not warnings else "partial",
            },
            "warnings": warnings,
            "boundary": (
                "今日观察只聚合已确认的市场事实、用户任务和研究变化；"
                "未冻结事件白名单的类别不会伪装成自动事件提醒，"
                "所有事项均不构成买卖、仓位或收益建议。"
            ),
        }

    @staticmethod
    def _collect(
        calls: dict[str, Callable[[], dict[str, Any]]],
    ) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
        results: dict[str, dict[str, Any]] = {}
        statuses: dict[str, str] = {}
        with ThreadPoolExecutor(max_workers=len(calls)) as executor:
            futures = {executor.submit(call): key for key, call in calls.items()}
            for future in as_completed(futures):
                key = futures[future]
                try:
                    results[key] = future.result()
                    statuses[key] = "ready"
                except Exception:
                    results[key] = {}
                    statuses[key] = "unavailable"
        return results, statuses

    @classmethod
    def _priority_items(
        cls,
        *,
        tasks: dict[str, Any],
        actions: dict[str, Any],
        writebacks: dict[str, Any],
        trade_reviews: dict[str, Any],
        whitelist_changes: dict[str, Any],
        names: dict[str, str],
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        now = datetime.now(timezone.utc)
        for event in whitelist_changes.get("pending_unread_items") or []:
            if not cls._change_event_is_fresh(event, now=now):
                continue
            symbol = str(event.get("symbol") or "")
            name = str(event.get("name") or names.get(symbol) or symbol)
            event_type = str(event.get("event_type") or "")
            items.append(
                {
                    "id": f"change-event:{event.get('link_id')}",
                    "kind": "change_event",
                    "category": "change_event",
                    "title": event.get("title") or f"{name}出现重要变化",
                    "detail": event.get("fact_summary"),
                    "symbol": symbol or None,
                    "name": name or None,
                    "status": event.get("relevance_status"),
                    "status_label": "待确认相关性",
                    "priority": (
                        "high" if event.get("severity") == "high" else "normal"
                    ),
                    "due_at": None,
                    "overdue": False,
                    "rank_reason": (
                        "完整日线价格异常等待核验"
                        if event_type == "daily_price_anomaly"
                        else "官方财务披露等待阅读原文"
                    ),
                    "source_type": "verified_change_event",
                    "source_ref_id": event.get("link_id"),
                    "updated_at": event.get("detected_at") or event.get("occurred_at"),
                    "action": {
                        "type": "open_change_event",
                        "link_id": event.get("link_id"),
                    },
                }
            )
        for review in trade_reviews.get("items") or []:
            status = str(review.get("status") or "")
            if status not in {"ready", "draft"}:
                continue
            symbol = str(review.get("symbol") or "")
            name = str(review.get("name") or names.get(symbol) or symbol)
            observation = review.get("price_observation") or {}
            operation = review.get("operation") or {}
            ready_at = review.get("ready_at") or review.get("updated_at")
            items.append(
                {
                    "id": f"trade-review:{review.get('id')}",
                    "kind": "trade_review",
                    "category": "trade_review",
                    "title": (
                        f"确认{name}的交易复盘草稿"
                        if status == "draft"
                        else f"复盘{name}的已记录操作"
                    ),
                    "detail": (
                        (review.get("current_version") or {}).get("logic_result")
                        if status == "draft"
                        else observation.get("summary")
                    ),
                    "symbol": symbol or None,
                    "name": name or None,
                    "status": status,
                    "status_label": "待确认" if status == "draft" else "可生成",
                    "priority": "high" if status == "draft" else "normal",
                    "due_at": ready_at,
                    "overdue": True,
                    "rank_reason": (
                        "交易复盘草稿等待用户确认"
                        if status == "draft"
                        else "后续交易日数据已经齐备"
                    ),
                    "source_type": "trade_review_workflow",
                    "source_ref_id": review.get("id"),
                    "updated_at": review.get("updated_at") or ready_at,
                    "action": {
                        "type": "open_trade_review",
                        "review_id": review.get("id"),
                        "symbol": symbol,
                    },
                    "operation_type": operation.get("operation_type"),
                }
            )

        for task in tasks.get("items") or []:
            if task.get("status") not in {"pending", "in_progress", "waiting_data"}:
                continue
            due_at = cls._parse_time(task.get("due_at"))
            overdue = bool(due_at and due_at < now)
            category = (
                "risk_review" if task.get("priority") == "high" else "user_task"
            )
            reason = (
                "高优先级用户任务"
                if category == "risk_review"
                else "任务已经到期"
                if overdue
                else "任务设置了截止时间"
                if due_at
                else "用户保存的观察任务"
            )
            symbol = str(task.get("symbol") or "")
            items.append(
                {
                    "id": f"observation-task:{task.get('id')}",
                    "kind": "observation_task",
                    "category": category,
                    "title": task.get("title") or "待处理观察任务",
                    "detail": task.get("description"),
                    "symbol": symbol or None,
                    "name": names.get(symbol) or symbol or None,
                    "status": task.get("status"),
                    "status_label": task.get("status_label"),
                    "priority": task.get("priority") or "normal",
                    "due_at": task.get("due_at"),
                    "overdue": overdue,
                    "rank_reason": reason,
                    "source_type": "user_observation_task",
                    "source_ref_id": task.get("id"),
                    "updated_at": task.get("updated_at"),
                    "action": {"type": "open_stock_tasks", "symbol": symbol},
                }
            )

        for candidate in writebacks.get("items") or []:
            symbol = str(candidate.get("symbol") or "")
            payload = candidate.get("payload") or {}
            items.append(
                {
                    "id": f"writeback:{candidate.get('id')}",
                    "kind": "draft_confirmation",
                    "category": "draft_confirmation",
                    "title": f"确认{names.get(symbol) or symbol}的判断草稿",
                    "detail": payload.get("reason_text")
                    or "Agent 已生成判断草稿，等待逐项确认。",
                    "symbol": symbol or None,
                    "name": names.get(symbol) or symbol or None,
                    "status": candidate.get("status"),
                    "status_label": "待确认",
                    "priority": "normal",
                    "due_at": None,
                    "overdue": False,
                    "rank_reason": "正式判断写回前必须由用户确认",
                    "source_type": "ai_writeback_candidate",
                    "source_ref_id": candidate.get("id"),
                    "updated_at": candidate.get("created_at"),
                    "action": {"type": "open_stock_research", "symbol": symbol},
                }
            )

        for stock in actions.get("items") or []:
            symbol = str(stock.get("symbol") or "")
            name = str(stock.get("name") or names.get(symbol) or symbol)
            for action in stock.get("actions") or []:
                status = action.get("status")
                if status not in {"triggered", "pending_data"}:
                    continue
                severity = str(action.get("severity") or "medium")
                category = (
                    "risk_review"
                    if status == "triggered" and severity == "high"
                    else "evidence_gap"
                    if status == "pending_data"
                    else "research_task"
                )
                items.append(
                    {
                        "id": f"research-action:{symbol}:{action.get('id')}",
                        "kind": "research_action",
                        "category": category,
                        "title": action.get("title") or f"复核{name}最新变化",
                        "detail": action.get("next_step")
                        or action.get("current_evidence"),
                        "symbol": symbol or None,
                        "name": name,
                        "status": status,
                        "status_label": "需要复核"
                        if status == "triggered"
                        else "待补证",
                        "priority": "high" if severity == "high" else "normal",
                        "due_at": None,
                        "overdue": False,
                        "rank_reason": (
                            "高风险研究条件已经触发"
                            if category == "risk_review"
                            else "完成判断所需证据仍有缺口"
                            if category == "evidence_gap"
                            else "确定性研究条件已经触发"
                        ),
                        "source_type": "deterministic_research_action",
                        "source_ref_id": action.get("id"),
                        "updated_at": stock.get("latest_report_at")
                        or stock.get("data_as_of")
                        or actions.get("generated_at"),
                        "action": {"type": "open_stock_research", "symbol": symbol},
                    }
                )

        deduped: dict[str, dict[str, Any]] = {}
        for item in items:
            deduped.setdefault(str(item.get("id")), item)
        output = list(deduped.values())
        output.sort(key=cls._priority_sort_key)
        return output[:5]

    @classmethod
    def _dedupe_whitelist_changes(
        cls, packet: dict[str, Any]
    ) -> dict[str, Any]:
        if not packet:
            return {}

        items = cls._dedupe_change_events(list(packet.get("items") or []))
        pending_items = cls._dedupe_change_events(
            list(packet.get("pending_unread_items") or [])
        )
        counts = {
            "total": len(items),
            "pending": sum(
                item.get("relevance_status") == "pending" for item in items
            ),
            "pending_unread": len(pending_items),
            "relevant": sum(
                item.get("relevance_status") == "relevant" for item in items
            ),
            "irrelevant": sum(
                item.get("relevance_status") == "irrelevant" for item in items
            ),
        }
        return {
            **packet,
            "items": items,
            "pending_unread_items": pending_items,
            "counts": counts,
        }

    @classmethod
    def _dedupe_change_events(
        cls, events: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        selected: dict[tuple[str, ...], dict[str, Any]] = {}
        for event in events:
            selected.setdefault(cls._canonical_change_key(event), event)
        return list(selected.values())

    @staticmethod
    def _canonical_change_key(event: dict[str, Any]) -> tuple[str, ...]:
        symbol = str(event.get("symbol") or "").strip().upper()
        event_type = str(event.get("event_type") or "").strip()
        event_time = str(
            event.get("occurred_at") or event.get("market_date") or ""
        ).strip()
        rule_version = str(event.get("rule_version") or "").strip()
        if symbol and event_type and event_time:
            return "business_event", symbol, event_type, event_time, rule_version
        record_id = str(
            event.get("event_id") or event.get("link_id") or event.get("id") or ""
        ).strip()
        return "event_record", record_id or repr(sorted(event.items()))

    @classmethod
    def _priority_sort_key(cls, item: dict[str, Any]) -> tuple[Any, ...]:
        due = cls._parse_time(item.get("due_at"))
        updated = cls._parse_time(item.get("updated_at"))
        return (
            cls._CATEGORY_RANK.get(str(item.get("category")), 99),
            0 if item.get("overdue") else 1,
            due.timestamp() if due else float("inf"),
            cls._PRIORITY_RANK.get(str(item.get("priority")), 9),
            -(updated.timestamp() if updated else 0),
            str(item.get("id") or ""),
        )

    @classmethod
    def _market_packet(
        cls,
        indices: dict[str, Any],
        breadth: dict[str, Any],
        industries: dict[str, Any],
        whitelist_changes: dict[str, Any],
    ) -> dict[str, Any]:
        by_symbol = {
            str(item.get("symbol")): item for item in indices.get("indices") or []
        }
        index_cards = []
        for symbol in cls.INDEX_SYMBOLS:
            item = by_symbol.get(symbol)
            if item is None:
                index_cards.append(
                    {
                        "symbol": symbol,
                        "name": symbol,
                        "status": "unavailable",
                        "latest_close": None,
                        "return_1d_pct": None,
                        "market_timestamp": None,
                        "recent_bars": [],
                    }
                )
                continue
            metrics = item.get("metrics") or {}
            index_cards.append(
                {
                    "symbol": symbol,
                    "name": item.get("name") or symbol,
                    "status": item.get("status") or "unavailable",
                    "latest_close": metrics.get("latest_close"),
                    "return_1d_pct": metrics.get("return_1d_pct"),
                    "market_timestamp": item.get("market_timestamp")
                    or (item.get("latest_bar") or {}).get("timestamp"),
                    "recent_bars": list(item.get("recent_bars") or [])[-5:],
                    "source": item.get("source"),
                }
            )
        breadth_packet = {
            "status": breadth.get("status") or "unavailable",
            "market_date": breadth.get("market_date"),
            "market_timestamp": breadth.get("market_timestamp"),
            "breadth": breadth.get("breadth") or {},
            "turnover": breadth.get("turnover") or {},
            "distribution": breadth.get("distribution") or {},
            "source": breadth.get("source"),
        }
        sector_items = []
        for sector in industries.get("sectors") or []:
            total = sum(
                int(sector.get(key) or 0)
                for key in ("advancers", "decliners", "unchanged")
            )
            sector_items.append(
                {
                    "code": sector.get("code"),
                    "name": sector.get("name"),
                    "pct_change": sector.get("pct_change"),
                    "advance_ratio": (
                        round(int(sector.get("advancers") or 0) / total, 4)
                        if total
                        else None
                    ),
                    "main_net_inflow": sector.get("main_net_inflow"),
                }
            )
        current_change_items = [
            item
            for item in whitelist_changes.get("items") or []
            if cls._change_event_is_fresh(item)
        ]
        return {
            "indices": index_cards,
            "breadth": breadth_packet,
            "industries": {
                "status": "available" if sector_items else "unavailable",
                "items": sector_items,
                "market_timestamp": industries.get("market_timestamp"),
                "source": industries.get("source"),
                "period": "1d",
            },
            "styles": {
                "status": "not_available",
                "message": "正式风格指数和冻结口径尚未接入，当前不生成风格结论。",
            },
            "risk_agenda": {
                "status": (
                    "available"
                    if current_change_items
                    else "empty"
                    if whitelist_changes
                    else "not_available"
                ),
                "pending_unread": sum(
                    item.get("relevance_status") == "pending"
                    and item.get("read_at") is None
                    and item.get("handled_at") is None
                    for item in current_change_items
                ),
                "items": current_change_items[:5],
                "message": (
                    whitelist_changes.get("empty_message")
                    or "当前只展示已完成来源与规则验收的事件类型。"
                ),
            },
        }

    @classmethod
    def _personalized_packet(
        cls,
        *,
        changes: dict[str, Any],
        whitelist_changes: dict[str, Any],
        actions: dict[str, Any],
        watchlist: list[dict[str, Any]],
        exclude_change_keys: set[tuple[str, ...]] | None = None,
    ) -> dict[str, Any]:
        selected_events: dict[tuple[str, str], dict[str, Any]] = {}
        for event in changes.get("events") or []:
            event_time = str(event.get("data_as_of") or event.get("created_at") or "")
            identity = (str(event.get("symbol") or ""), event_time[:10])
            current = selected_events.get(identity)
            if current is None or TodayOverviewService._change_priority(
                event
            ) > TodayOverviewService._change_priority(current):
                selected_events[identity] = event

        ordered_events = sorted(
            selected_events.values(),
            key=lambda item: str(
                item.get("created_at") or item.get("data_as_of") or ""
            ),
            reverse=True,
        )
        events = []
        excluded = exclude_change_keys or set()
        for event in whitelist_changes.get("items") or []:
            if cls._canonical_change_key(event) in excluded:
                continue
            if not cls._change_event_is_fresh(event):
                continue
            events.append(
                {
                    "id": event.get("event_id"),
                    "link_id": event.get("link_id"),
                    "symbol": event.get("symbol"),
                    "name": event.get("name"),
                    "event_type": event.get("event_type"),
                    "event_type_label": event.get("event_type_label"),
                    "severity": event.get("severity"),
                    "title": event.get("title"),
                    "summary": event.get("fact_summary"),
                    "event_time": event.get("occurred_at"),
                    "discovered_at": event.get("detected_at"),
                    "source_type": "verified_change_event",
                    "source_name": event.get("source_name"),
                    "source_url": event.get("source_url"),
                    "data_status": event.get("data_status"),
                    "data_status_label": event.get("data_status_label"),
                    "rule_version": event.get("rule_version"),
                    "relevance_status": event.get("relevance_status"),
                    "relevance_status_label": event.get("relevance_status_label"),
                    "read_at": event.get("read_at"),
                    "handled_at": event.get("handled_at"),
                    "boundary": event.get("boundary"),
                }
            )
            if len(events) == 5:
                break
        for event in ordered_events:
            if len(events) == 5:
                break
            event_time = str(event.get("data_as_of") or event.get("created_at") or "")
            events.append(
                {
                    "id": event.get("id"),
                    "symbol": event.get("symbol"),
                    "event_type": event.get("event_type"),
                    "severity": event.get("severity"),
                    "summary": event.get("summary"),
                    "event_time": event_time or None,
                    "discovered_at": event.get("created_at"),
                    "source_type": "research_report_comparison",
                    "rule_version": "research_change_tracking_v1",
                    "relevance_status": "related_by_watchlist",
                    "boundary": event.get("boundary"),
                }
            )
        action_items = [
            {
                "symbol": item.get("symbol"),
                "name": item.get("name"),
                "research_status": item.get("research_status"),
                "research_status_label": item.get("research_status_label"),
                "headline": item.get("headline"),
                "latest_report_at": item.get("latest_report_at"),
            }
            for item in actions.get("items") or []
        ]
        return {
            "status": "available" if watchlist else "empty",
            "watchlist_count": len(watchlist),
            "changes": events,
            "stock_overview": action_items,
            "coverage": {
                "event_whitelist_complete": False,
                **(changes.get("coverage") or {}),
                **(whitelist_changes.get("coverage") or {}),
                "event_scope": (
                    "已验收的重要变化优先，连续研究报告的确定性比较作为补充"
                ),
            },
            "empty_message": (
                "添加关注股票后，这里会展示与个人判断相关的研究变化。"
                if not watchlist
                else None
            ),
            "boundary": (
                whitelist_changes.get("boundary")
                or "未完成来源与规则验收的事件类型不会进入用户提醒。"
            ),
        }

    @classmethod
    def _change_event_is_fresh(
        cls, event: dict[str, Any], *, now: datetime | None = None
    ) -> bool:
        event_type = str(event.get("event_type") or "")
        freshness_days = cls._CHANGE_FRESHNESS_DAYS.get(event_type)
        if freshness_days is None:
            return True
        raw_time = str(event.get("occurred_at") or event.get("detected_at") or "")
        if not raw_time:
            return False
        try:
            event_time = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
        except ValueError:
            return False
        if event_time.tzinfo is None:
            event_time = event_time.replace(tzinfo=timezone.utc)
        age = (now or datetime.now(timezone.utc)) - event_time.astimezone(timezone.utc)
        return age.total_seconds() >= -86400 and age.days <= freshness_days

    @staticmethod
    def _change_priority(event: dict[str, Any]) -> tuple[int, int, int]:
        severity = {"high": 3, "attention": 2, "medium": 2, "notice": 1}.get(
            str(event.get("severity") or ""), 0
        )
        evidence_count = len(event.get("changes") or []) * 2 + len(
            event.get("new_evidence") or []
        )
        substantive = int("暂未出现实质变化" not in str(event.get("summary") or ""))
        return substantive, evidence_count, severity

    @staticmethod
    def _summary(
        session: dict[str, Any],
        priority_items: list[dict[str, Any]],
        market: dict[str, Any],
        personalized: dict[str, Any],
    ) -> dict[str, Any]:
        breadth = (market.get("breadth") or {}).get("breadth") or {}
        market_copy = (
            f"A股{breadth.get('state')}，上涨{breadth.get('advancers')}家、"
            f"下跌{breadth.get('decliners')}家。"
            if breadth.get("state") and breadth.get("advancers") is not None
            else "A股市场广度正在更新。"
        )
        return {
            "headline": (
                f"今天有{len(priority_items)}项优先研究事项。{market_copy}"
                if priority_items
                else f"当前没有必须立即处理的研究事项。{market_copy}"
            ),
            "session_label": session.get("label"),
            "priority_count": len(priority_items),
            "related_change_count": len(personalized.get("changes") or []),
            "market_date": (market.get("breadth") or {}).get("market_date"),
        }

    @staticmethod
    def _parse_time(value: Any) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _default_session() -> dict[str, Any]:
        china_market = next(
            item for item in LIVE_MARKET_CATALOG if item.get("key") == "china"
        )
        details = market_session_details(china_market)
        session_status = str(details.get("session_status") or "")
        key = {
            "pre_open": "pre_market",
            "open": "intraday",
            "break": "intraday",
            "closed": "post_market",
            "holiday": "non_trading_day",
        }.get(session_status, "unknown")
        label = {
            "pre_market": "盘前",
            "intraday": "盘中",
            "post_market": "盘后",
            "non_trading_day": "非交易日",
            "unknown": "状态待确认",
        }[key]
        return {
            "key": key,
            "label": label,
            "exchange_status": session_status or None,
            "exchange_label": details.get("session_label"),
            "market_local_time": details.get("market_local_time"),
            "calendar_status": details.get("calendar_status"),
            "method": details.get("session_method"),
        }
