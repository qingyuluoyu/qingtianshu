from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.services.today_overview import TodayOverviewService


class FakeDatabase:
    def list_watchlist(self, user_id: str) -> list[dict[str, Any]]:
        assert user_id == "user-1"
        return [
            {"symbol": "000063.SZ", "name": "中兴通讯"},
            {"symbol": "NVDA", "name": "英伟达"},
        ]

    def list_change_events(
        self, *, event_type: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        return []


class FakeAnalysis:
    def get_indices(self, *, scope: str, group: str) -> dict[str, Any]:
        assert scope == "all"
        assert group == "china"
        return {
            "indices": [
                {
                    "symbol": symbol,
                    "name": name,
                    "status": "available",
                    "metrics": {"latest_close": value, "return_1d_pct": change},
                    "market_timestamp": "2026-07-22T07:00:00+00:00",
                    "recent_bars": [{"timestamp": "2026-07-22", "close": value}],
                    "source": "fake index source",
                }
                for symbol, name, value, change in (
                    ("000001.SS", "上证综指", 3867.03, 0.07),
                    ("399001.SZ", "深证成指", 14061.44, -1.42),
                    ("399006.SZ", "创业板指", 3566.73, -1.0),
                    ("000688.SS", "科创50", 1200.0, -0.8),
                )
            ]
        }

    def market_breadth(self) -> dict[str, Any]:
        return {
            "status": "available",
            "market_date": "2026-07-22",
            "source": "fake breadth source",
            "breadth": {
                "state": "普跌",
                "advancers": 1530,
                "decliners": 3875,
                "unchanged": 124,
            },
            "turnover": {"status": "available", "total_amount_100m_cny": 26676.11},
            "distribution": {"status": "available", "median_pct_change": -1.27},
        }

    def hot_sectors(self, *, limit: int) -> dict[str, Any]:
        assert limit == 5
        return {
            "source": "fake sector source",
            "market_timestamp": "2026-07-22T07:00:00+00:00",
            "sectors": [
                {
                    "code": "BK1616",
                    "name": "白银",
                    "pct_change": 6.43,
                    "advancers": 3,
                    "decliners": 0,
                    "unchanged": 0,
                    "main_net_inflow": 5.0,
                }
            ],
        }

    def capital_flow(self) -> dict[str, Any]:
        return {
            "status": "available",
            "market_timestamp": "2026-07-22T07:00:00+00:00",
            "is_stale": False,
            "summary": {
                "main_net_inflow_100m_cny": -128.5,
                "unit": "CNY_100m_yuan",
                "scope": "fake capital flow scope",
            },
            "points": [],
            "method": "fake capital flow（亿元）",
            "warnings": [],
        }


class FakeTasks:
    def list_tasks(self, *, user_id: str, limit: int) -> dict[str, Any]:
        assert user_id == "user-1"
        assert limit == 100
        return {
            "items": [
                {
                    "id": "task-normal",
                    "symbol": "NVDA",
                    "title": "核验财报",
                    "description": "确认收入与现金流口径",
                    "status": "pending",
                    "status_label": "待处理",
                    "priority": "normal",
                    "due_at": "2099-07-23T08:00:00+00:00",
                    "updated_at": "2026-07-23T01:00:00+00:00",
                }
            ]
        }


class FakeActions:
    def get_packet(self, user_id: str, persist: bool) -> dict[str, Any]:
        assert user_id == "user-1"
        assert persist is False
        return {
            "generated_at": "2026-07-23T01:00:00+00:00",
            "items": [
                {
                    "symbol": "000063.SZ",
                    "name": "中兴通讯",
                    "research_status": "risk_review",
                    "research_status_label": "风险复核",
                    "headline": "存在需要复核的波动",
                    "latest_report_at": "2026-07-23T00:00:00+00:00",
                    "actions": [
                        {
                            "id": "risk-1",
                            "title": "核验波动与公告",
                            "status": "triggered",
                            "severity": "high",
                            "current_evidence": "波动扩大",
                            "next_step": "交叉核验公告和财务证据",
                        }
                    ],
                }
            ],
        }


class FakeTracking:
    def get_packet(self, user_id: str, limit: int) -> dict[str, Any]:
        assert user_id == "user-1"
        assert limit == 20
        return {
            "coverage": {"requested": 2, "with_change_archive": 1},
            "events": [
                {
                    "id": "change-1",
                    "symbol": "000063.SZ",
                    "event_type": "research_delta",
                    "severity": "attention",
                    "summary": "波动与技术状态发生变化",
                    "data_as_of": "2026-07-22",
                    "created_at": "2026-07-23T00:00:00+00:00",
                    "boundary": "研究变化不是交易信号",
                },
                {
                    "id": "change-duplicate",
                    "symbol": "000063.SZ",
                    "event_type": "research_delta",
                    "severity": "attention",
                    "summary": "波动与技术状态发生变化",
                    "data_as_of": "2026-07-22",
                    "created_at": "2026-07-23T00:10:00+00:00",
                    "boundary": "研究变化不是交易信号",
                },
                {
                    "id": "change-substantive",
                    "symbol": "000063.SZ",
                    "event_type": "research_delta",
                    "severity": "attention",
                    "summary": "20日波动率上升，需要重新核验风险边界",
                    "data_as_of": "2026-07-22",
                    "created_at": "2026-07-23T00:05:00+00:00",
                    "changes": [{"dimension": "risk"}],
                    "boundary": "研究变化不是交易信号",
                },
            ],
        }


class FakeWritebacks:
    def list_writebacks(
        self, *, user_id: str, status: str, limit: int
    ) -> dict[str, Any]:
        assert (user_id, status, limit) == ("user-1", "pending_confirmation", 20)
        return {
            "items": [
                {
                    "id": "draft-1",
                    "symbol": "000063.SZ",
                    "status": "pending_confirmation",
                    "payload": {"reason_text": "通信设备证据仍需继续核验"},
                    "created_at": "2026-07-23T02:00:00+00:00",
                }
            ]
        }


class FakeTradeWorkflow:
    def list_user_trade_reviews(self, user_id: str, *, limit: int) -> dict[str, Any]:
        assert (user_id, limit) == ("user-1", 100)
        return {
            "items": [
                {
                    "id": "review-1",
                    "symbol": "000063.SZ",
                    "name": "中兴通讯",
                    "status": "ready",
                    "horizon_sessions": 3,
                    "ready_at": "2026-07-23T00:30:00+00:00",
                    "updated_at": "2026-07-23T00:30:00+00:00",
                    "operation": {"operation_type": "reduce"},
                    "price_observation": {"summary": "三个后续交易日数据已经齐备。"},
                    "current_version": None,
                }
            ]
        }


class FakeChangeEvents:
    def get_user_packet(self, user_id: str, *, limit: int) -> dict[str, Any]:
        assert (user_id, limit) == ("user-1", 50)
        now = datetime.now(timezone.utc)
        occurred_at = (now - timedelta(days=1)).isoformat()
        duplicate_base = {
            "symbol": "000063.SZ",
            "name": "中兴通讯",
            "event_type": "daily_price_anomaly",
            "event_type_label": "完整日线价格异常",
            "title": "中兴通讯上一完整交易日上涨 7.51%",
            "fact_summary": "最近完整日线上涨 7.51%。",
            "occurred_at": occurred_at,
            "detected_at": now.isoformat(),
            "severity": "high",
            "relevance_status": "pending",
            "relevance_status_label": "待判断相关性",
            "read_at": None,
            "handled_at": None,
            "rule_version": "daily_move_abs_5pct_v1",
        }
        first = {
            **duplicate_base,
            "link_id": "duplicate-link-1",
            "event_id": "duplicate-event-1",
        }
        second = {
            **duplicate_base,
            "link_id": "duplicate-link-2",
            "event_id": "duplicate-event-2",
        }
        related = {
            "link_id": "related-link",
            "event_id": "related-event",
            "symbol": "NVDA",
            "name": "英伟达",
            "event_type": "official_financial_disclosure",
            "event_type_label": "官方财务披露",
            "title": "NVDA SEC 10-Q",
            "fact_summary": "新的监管财务披露已经发布。",
            "occurred_at": (now - timedelta(days=2)).isoformat(),
            "detected_at": now.isoformat(),
            "severity": "notice",
            "relevance_status": "relevant",
            "relevance_status_label": "与我有关",
            "read_at": now.isoformat(),
            "handled_at": now.isoformat(),
            "rule_version": "official_financial_disclosure_v1",
        }
        return {
            "items": [first, second, related],
            "pending_unread_items": [first, second],
            "counts": {"total": 3, "pending": 2, "pending_unread": 2},
            "coverage": {},
        }


def post_market_session() -> dict[str, Any]:
    return {
        "key": "post_market",
        "label": "盘后",
        "exchange_status": "closed",
        "exchange_label": "已收盘",
        "market_local_time": "2026-07-23T17:00:00+08:00",
        "calendar_status": "verified",
        "method": "test_calendar",
    }


def build_service(analysis: Any | None = None) -> TodayOverviewService:
    return TodayOverviewService(
        FakeDatabase(),
        analysis or FakeAnalysis(),
        FakeTasks(),
        FakeActions(),
        FakeTracking(),
        FakeWritebacks(),
        session_provider=post_market_session,
    )


def test_capital_flow_theme_does_not_expose_provider_exception_details() -> None:
    theme = TodayOverviewService._theme_capital_flow(
        {
            "status": "unavailable",
            "warnings": [
                "大盘资金流数据不可用：ConnectionError: RemoteDisconnected('connection closed')"
            ],
            "summary": {"main_net_inflow_100m_cny": None},
        }
    )

    assert theme["status"] == "unavailable"
    assert theme["summary"] == "大盘资金流向暂不可用，请稍后重试。"
    assert "ConnectionError" not in theme["summary"]


def test_today_overview_prioritizes_risk_and_keeps_traceable_boundaries():
    packet = build_service().get_overview("user-1")

    assert packet["contract_version"] == "today_overview_v1"
    assert packet["session"]["key"] == "post_market"
    assert packet["coverage"]["status"] == "ready"
    assert [item["kind"] for item in packet["priority_items"]["items"]] == [
        "research_action",
        "observation_task",
        "draft_confirmation",
    ]
    assert (
        packet["priority_items"]["items"][0]["rank_reason"] == "高风险研究条件已经触发"
    )
    assert packet["priority_items"]["items"][1]["category"] == "user_task"
    assert "用户已保存任务" in packet["priority_items"]["ranking_method"]
    assert [item["symbol"] for item in packet["market"]["indices"]] == list(
        TodayOverviewService.INDEX_SYMBOLS
    )
    assert packet["market"]["breadth"]["breadth"]["state"] == "普跌"
    assert (
        packet["personalized"]["changes"][0]["rule_version"]
        == "research_change_tracking_v1"
    )
    assert len(packet["personalized"]["changes"]) == 1
    assert (
        packet["personalized"]["changes"][0]["summary"]
        == "20日波动率上升，需要重新核验风险边界"
    )
    assert packet["personalized"]["coverage"]["event_whitelist_complete"] is False
    assert "不构成买卖" in packet["boundary"]


class FailingAnalysis(FakeAnalysis):
    def get_indices(self, *, scope: str, group: str) -> dict[str, Any]:
        raise RuntimeError("provider unavailable")


def test_today_overview_preserves_personal_items_when_one_market_component_fails():
    packet = build_service(FailingAnalysis()).get_overview("user-1")

    assert packet["coverage"]["status"] == "partial"
    assert packet["coverage"]["components"]["indices"] == "unavailable"
    assert packet["priority_items"]["total_visible"] == 3
    assert packet["market"]["indices"][0]["status"] == "unavailable"
    assert packet["warnings"] == ["指数数据暂未完整返回"]


def test_today_overview_surfaces_ready_trade_review_as_actionable_reminder():
    service = TodayOverviewService(
        FakeDatabase(),
        FakeAnalysis(),
        FakeTasks(),
        FakeActions(),
        FakeTracking(),
        FakeWritebacks(),
        trade_workflow=FakeTradeWorkflow(),
        session_provider=post_market_session,
    )

    packet = service.get_overview("user-1")
    reminder = next(
        item
        for item in packet["priority_items"]["items"]
        if item["kind"] == "trade_review"
    )
    assert reminder["status_label"] == "可生成"
    assert reminder["action"] == {
        "type": "open_trade_review",
        "review_id": "review-1",
        "symbol": "000063.SZ",
    }
    assert packet["coverage"]["components"]["trade_reviews"] == "ready"


def test_today_overview_keeps_stale_filings_in_history_but_out_of_today_scope():
    now = datetime.now(timezone.utc)
    fresh_price = {
        "link_id": "fresh-price",
        "event_id": "fresh-price-event",
        "symbol": "000063.SZ",
        "name": "中兴通讯",
        "event_type": "daily_price_anomaly",
        "event_type_label": "完整日线价格异常",
        "title": "中兴通讯上一完整交易日上涨 7.51%",
        "fact_summary": "最近完整日线出现价格异常。",
        "occurred_at": (now - timedelta(days=1)).isoformat(),
        "detected_at": now.isoformat(),
        "severity": "high",
        "relevance_status": "pending",
        "relevance_status_label": "待判断相关性",
        "read_at": None,
        "handled_at": None,
        "rule_version": "daily_move_abs_5pct_v1",
    }
    stale_filing = {
        "link_id": "stale-filing",
        "event_id": "stale-filing-event",
        "symbol": "NVDA",
        "name": "英伟达",
        "event_type": "official_financial_disclosure",
        "event_type_label": "官方财务披露",
        "title": "NVDA SEC 10-Q",
        "fact_summary": "历史财务披露已经发布。",
        "occurred_at": (now - timedelta(days=90)).isoformat(),
        "detected_at": (now - timedelta(days=89)).isoformat(),
        "severity": "notice",
        "relevance_status": "pending",
        "relevance_status_label": "待判断相关性",
        "read_at": None,
        "handled_at": None,
        "rule_version": "official_financial_disclosure_v1",
    }
    whitelist = {
        "items": [fresh_price, stale_filing],
        "pending_unread_items": [fresh_price, stale_filing],
        "counts": {"pending_unread": 2},
        "coverage": {},
    }

    priority = TodayOverviewService._priority_items(
        tasks={},
        actions={},
        writebacks={},
        trade_reviews={},
        whitelist_changes=whitelist,
        names={"000063.SZ": "中兴通讯", "NVDA": "英伟达"},
    )
    personalized = TodayOverviewService._personalized_packet(
        changes={},
        whitelist_changes=whitelist,
        actions={},
        watchlist=[{"symbol": "000063.SZ"}, {"symbol": "NVDA"}],
    )

    assert [item["source_ref_id"] for item in priority] == ["fresh-price"]
    assert [item["link_id"] for item in personalized["changes"]] == [
        "fresh-price"
    ]


def test_today_overview_dedupes_business_events_and_avoids_cross_section_repeat():
    service = TodayOverviewService(
        FakeDatabase(),
        FakeAnalysis(),
        FakeTasks(),
        FakeActions(),
        FakeTracking(),
        FakeWritebacks(),
        change_events=FakeChangeEvents(),
        session_provider=post_market_session,
    )

    packet = service.get_overview("user-1")

    priority_changes = [
        item
        for item in packet["priority_items"]["items"]
        if item["kind"] == "change_event"
    ]
    related_verified_changes = [
        item
        for item in packet["personalized"]["changes"]
        if item["source_type"] == "verified_change_event"
    ]

    assert len(priority_changes) == 1
    assert priority_changes[0]["source_ref_id"] == "duplicate-link-1"
    assert [item["link_id"] for item in related_verified_changes] == ["related-link"]
    assert packet["market"]["risk_agenda"]["pending_unread"] == 1
    assert [
        item["link_id"] for item in packet["market"]["risk_agenda"]["items"]
    ] == ["duplicate-link-1", "related-link"]
