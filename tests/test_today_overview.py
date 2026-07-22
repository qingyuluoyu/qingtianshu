from __future__ import annotations

from typing import Any

from app.services.today_overview import TodayOverviewService


class FakeDatabase:
    def list_watchlist(self, user_id: str) -> list[dict[str, Any]]:
        assert user_id == "user-1"
        return [
            {"symbol": "000063.SZ", "name": "中兴通讯"},
            {"symbol": "NVDA", "name": "英伟达"},
        ]


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
