from __future__ import annotations

from pathlib import Path
from typing import Any

from app.services.chat_market_evidence import ChatMarketEvidenceService


class FakeAnalysis:
    def __init__(self) -> None:
        self.market_keys: list[str | None] = []
        self.industry_calls: list[tuple[str, str | None]] = []

    def market_brief(self, *, market_key: str | None) -> dict[str, Any]:
        self.market_keys.append(market_key)
        return {
            "type": "market_brief",
            "analysis_target": {"market_date": "2026-07-24"},
        }

    def industry_snapshot(
        self, industry_name: str, *, market_date: str | None
    ) -> dict[str, Any]:
        self.industry_calls.append((industry_name, market_date))
        return {"industry_name": industry_name, "market_date": market_date}


class FakeMarketNews:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def get_packet(self, message: str, **payload: Any) -> dict[str, Any]:
        self.calls.append({"message": message, **payload})
        return {"market_key": payload.get("market_key"), "items": []}


class FakeLiveMarkets:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    def snapshot(self) -> dict[str, Any]:
        if self.fail:
            raise RuntimeError("live market unavailable")
        return {
            "markets": [
                {
                    "key": "us",
                    "name": "美国股市",
                    "timezone": "America/New_York",
                    "market_timestamp": "2026-07-25T03:59:00+00:00",
                    "pct_change": 0.05,
                },
                {
                    "key": "london_gold",
                    "name": "伦敦金",
                    "timezone": "Europe/London",
                    "market_timestamp": "2026-07-24T20:59:00+00:00",
                    "price": 2400.0,
                },
            ]
        }


def build_service(
    *, live_fail: bool = False
) -> tuple[ChatMarketEvidenceService, FakeAnalysis, FakeMarketNews]:
    analysis = FakeAnalysis()
    news = FakeMarketNews()
    return (
        ChatMarketEvidenceService(
            analysis=analysis,
            market_news=news,
            live_markets=FakeLiveMarkets(fail=live_fail),
        ),
        analysis,
        news,
    )


def test_chat_market_evidence_module_does_not_import_main() -> None:
    source = Path(__file__).parents[1] / "app/services/chat_market_evidence.py"
    content = source.read_text(encoding="utf-8")
    assert "from app.main import" not in content
    assert "import app.main" not in content


def test_explicit_market_question_uses_inferred_market_and_target_date() -> None:
    service, analysis, news = build_service()

    evidence = service.build(
        message="美股为什么收盘跌了",
        history=[],
        explicit_market_query=True,
        explicit_industry_topic=None,
    )

    assert analysis.market_keys == ["us"]
    assert news.calls[0]["market_key"] == "us"
    assert news.calls[0]["focus_key"] == evidence["question_focus"]["key"]
    assert news.calls[0]["target_market_date"] == "2026-07-24"
    assert evidence["user_question"] == "美股为什么收盘跌了"
    assert evidence["focused_live_market"]["key"] == "us"
    assert evidence["live_alignment"] == {
        "status": "same_market_date",
        "target_market_date": "2026-07-24",
        "live_market_date": "2026-07-24",
        "rule": (
            "分钟行情与完整日线日期不一致时只作为更新提示，"
            "不得并入目标交易日的涨跌原因和市场状态判断。"
        ),
    }


def test_market_followup_inherits_gold_and_adds_live_snapshot() -> None:
    service, analysis, _ = build_service()
    history = [
        {
            "role": "assistant",
            "intent": "market_brief",
            "metadata": {"market_key": "gold"},
        }
    ]

    evidence = service.build(
        message="那现在最需要核验什么",
        history=history,
        explicit_market_query=False,
        explicit_industry_topic=None,
    )

    assert analysis.market_keys == ["gold"]
    assert evidence["market_drivers"]["market_key"] == "gold"
    assert evidence["focused_live_market"]["key"] == "london_gold"


def test_industry_topic_uses_same_market_date_and_gold_failure_is_nonfatal() -> None:
    service, analysis, _ = build_service(live_fail=True)

    industry = service.build(
        message="A股通信设备行业今天怎么样",
        history=[],
        explicit_market_query=True,
        explicit_industry_topic="通信设备",
    )
    assert analysis.industry_calls == [("通信设备", "2026-07-24")]
    assert industry["industry_focus"]["requested_by_user"] is True

    gold = service.build(
        message="伦敦金现在怎么样",
        history=[],
        explicit_market_query=True,
        explicit_industry_topic=None,
    )
    assert gold["market_drivers"]["market_key"] == "gold"
    assert gold["focused_live_market"] is None
    assert gold["live_alignment"]["status"] == "unavailable"
