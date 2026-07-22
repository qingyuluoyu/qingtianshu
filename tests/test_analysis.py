from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.analysis import (
    _current_quote_snapshot,
    _validated_index_metrics,
    MarketAnalysisService,
    analyze_history,
    annualized_volatility,
    build_conditional_outlook,
    build_evidence_debate,
    build_research_analysis_board,
    maximum_drawdown,
    moving_average,
    period_return,
)


class _DatedMarketProvider:
    def fetch_history(self, symbol: str, range_name: str = "3mo"):
        end_date = datetime(2026, 7, 20 if symbol == "399006.SZ" else 21, tzinfo=timezone.utc)
        points = []
        for index in range(70):
            close = 100 + index
            if symbol == "399006.SZ" and index == 69:
                close = 50
            elif index == 69:
                close = 171
            points.append(
                {
                    "timestamp": (end_date - timedelta(days=69 - index)).isoformat(),
                    "open": close - 0.5,
                    "high": close + 1,
                    "low": close - 1,
                    "close": close,
                    "volume": 1_000_000 + index,
                }
            )
        return {
            "points": points,
            "source": "dated test provider",
            "market_timestamp": points[-1]["timestamp"],
            "fetched_at": "2026-07-22T01:00:00+00:00",
            "coverage": {
                "requested_range": range_name,
                "interval": "1d",
                "points": len(points),
                "first_timestamp": points[0]["timestamp"],
                "last_timestamp": points[-1]["timestamp"],
            },
            "warnings": [],
        }


class _CurrentSessionMarketProvider(_DatedMarketProvider):
    def fetch_history(self, symbol: str, range_name: str = "3mo"):
        packet = super().fetch_history(symbol, range_name)
        last_timestamp = datetime.fromisoformat(packet["points"][-1]["timestamp"])
        target_timestamp = datetime(2026, 7, 22, tzinfo=timezone.utc)
        shift = target_timestamp - last_timestamp
        for point in packet["points"]:
            point["timestamp"] = (
                datetime.fromisoformat(point["timestamp"]) + shift
            ).isoformat()
        packet["market_timestamp"] = packet["points"][-1]["timestamp"]
        packet["coverage"]["first_timestamp"] = packet["points"][0]["timestamp"]
        packet["coverage"]["last_timestamp"] = packet["points"][-1]["timestamp"]
        return packet


class _NextDaySectorProvider:
    def fetch_hot_sectors(self, limit: int = 20):
        return {
            "status": "available",
            "market_timestamp": "2026-07-22T01:24:00+00:00",
            "fetched_at": "2026-07-22T01:24:05+00:00",
            "coverage": {"returned": 1},
            "warnings": [],
            "sectors": [{"name": "盘前占位板块", "pct_change": 9.9}],
        }


class _PreviousSessionBreadthProvider:
    def fetch_breadth(self):
        return {
            "status": "available",
            "market_date": "2026-07-21",
            "served_as_previous_close": True,
            "scope": "all_a_shares_including_beijing",
            "coverage": {"returned": 5528, "coverage_ratio": 1.0},
            "breadth": {
                "total": 5528,
                "advancers": 3107,
                "decliners": 2300,
                "unchanged": 121,
                "advance_ratio": 0.562,
                "state": "上涨家数占优",
            },
            "turnover": {"status": "available", "total_amount_cny": 1},
            "distribution": {"status": "available", "median_pct_change": 0.5},
            "warnings": [],
        }


class _StaleIndexHistoryProvider:
    def fetch_history(self, symbol: str, range_name: str = "1y"):
        return {
            "symbol": symbol,
            "points": [
                {
                    "timestamp": "2026-07-16T01:30:00+00:00",
                    "open": 4600.0,
                    "high": 4650.0,
                    "low": 4550.0,
                    "close": 4610.0,
                    "volume": 1,
                },
                {
                    "timestamp": "2026-07-17T01:30:00+00:00",
                    "open": 4610.0,
                    "high": 4660.0,
                    "low": 4500.0,
                    "close": 4529.1,
                    "volume": 1,
                },
            ],
            "source": "stale primary",
            "market_timestamp": "2026-07-17T01:30:00+00:00",
            "fetched_at": "2026-07-22T03:00:00+00:00",
            "coverage": {"points": 2},
            "warnings": [],
        }


class _FreshChinaIndexHistoryProvider:
    def supports(self, symbol: str) -> bool:
        return symbol == "000300.SS"

    def fetch_history(self, symbol: str, range_name: str = "1y"):
        return {
            "symbol": symbol,
            "points": [
                {
                    "timestamp": "2026-07-20T01:30:00+00:00",
                    "open": 4575.67,
                    "high": 4628.8,
                    "low": 4521.18,
                    "close": 4598.32,
                    "volume": 1,
                },
                {
                    "timestamp": "2026-07-21T01:30:00+00:00",
                    "open": 4630.85,
                    "high": 4739.23,
                    "low": 4566.28,
                    "close": 4739.23,
                    "volume": 1,
                },
            ],
            "source": "fresh fallback",
            "market_timestamp": "2026-07-21T01:30:00+00:00",
            "fetched_at": "2026-07-22T03:00:00+00:00",
            "coverage": {"points": 2},
            "warnings": [],
        }


def test_deterministic_metrics():
    closes = [100.0, 102.0, 101.0, 105.0, 103.0]
    assert period_return(closes, 1) == pytest.approx(-1.9048)
    assert moving_average(closes, 3) == pytest.approx(103.0)
    assert maximum_drawdown(closes) == pytest.approx(-1.9048)
    assert annualized_volatility(closes, 3) is not None


def test_analyze_history_reports_insufficient_long_windows():
    history = {"points": [{"close": float(value)} for value in range(100, 110)]}
    metrics = analyze_history(history)
    assert metrics["latest_close"] == 109
    assert metrics["return_5d_pct"] > 0
    assert metrics["return_20d_pct"] is None
    assert metrics["ma20"] is None
    assert metrics["trend_state"] == "数据不足"


def test_analyze_history_builds_auditable_technical_panel():
    points = []
    for index in range(80):
        close = 100 + index * 0.4 + ((index % 6) - 3) * 0.25
        points.append(
            {
                "close": close,
                "high": close + 1.2,
                "low": close - 1.0,
                "volume": 1_000_000 + index * 10_000,
            }
        )

    metrics = analyze_history({"points": points})

    assert metrics["rsi_14"] is not None
    assert metrics["macd_12_26"] is not None
    assert metrics["macd_signal_9"] is not None
    assert metrics["bollinger_upper_20"] > metrics["bollinger_lower_20"]
    assert metrics["atr_14_pct"] > 0
    assert metrics["volume_ratio_5_20"] > 0
    assert metrics["technical_state"] in {
        "短期偏热",
        "短期超跌观察",
        "动量改善",
        "动量转弱",
        "技术分化",
    }
    assert "不生成买卖信号" in metrics["technical_method"]


def test_index_history_prefers_fresher_china_fallback():
    service = MarketAnalysisService(
        None,
        _StaleIndexHistoryProvider(),
        _NextDaySectorProvider(),
        china_index_provider=_FreshChinaIndexHistoryProvider(),
    )

    history = service.get_index_history("000300.SS", range_name="3mo")

    assert history["source"] == "fresh fallback"
    assert history["market_timestamp"] == "2026-07-21T01:30:00+00:00"
    assert history["metrics"]["latest_close"] == 4739.23


def test_index_history_prefers_complete_same_day_history_over_one_point_quote():
    class OnePointProvider:
        def fetch_history(self, symbol: str, range_name: str = "1y"):
            return {
                "symbol": symbol,
                "points": [
                    {
                        "timestamp": "2026-07-22T07:00:00+00:00",
                        "open": 1860.0,
                        "high": 1861.0,
                        "low": 1850.0,
                        "close": 1860.0,
                        "volume": 1,
                    }
                ],
                "source": "single point quote",
                "market_timestamp": "2026-07-22T07:00:00+00:00",
                "fetched_at": "2026-07-22T07:01:00+00:00",
                "coverage": {"points": 1},
                "warnings": [],
            }

    class CompleteChinaProvider:
        def supports(self, symbol: str) -> bool:
            return symbol == "000688.SS"

        def fetch_history(self, symbol: str, range_name: str = "1y"):
            return {
                "symbol": symbol,
                "points": [
                    {
                        "timestamp": "2026-07-21T01:30:00+00:00",
                        "open": 1800.0,
                        "high": 1830.0,
                        "low": 1790.0,
                        "close": 1820.0,
                        "volume": 1,
                    },
                    {
                        "timestamp": "2026-07-22T01:30:00+00:00",
                        "open": 1840.0,
                        "high": 1870.0,
                        "low": 1830.0,
                        "close": 1860.0,
                        "volume": 1,
                    },
                ],
                "source": "complete daily history",
                "market_timestamp": "2026-07-22T01:30:00+00:00",
                "fetched_at": "2026-07-22T07:01:00+00:00",
                "coverage": {"points": 2},
                "warnings": [],
            }

    service = MarketAnalysisService(
        None,
        OnePointProvider(),
        _NextDaySectorProvider(),
        china_index_provider=CompleteChinaProvider(),
    )

    history = service.get_index_history("000688.SS", range_name="3mo")

    assert history["source"] == "complete daily history"
    assert history["metrics"]["return_1d_pct"] == 2.1978


def test_current_quote_snapshot_uses_latest_complete_close_as_intraday_base():
    history = {
        "timezone": "Asia/Shanghai",
        "currency": "CNY",
        "regular_market_price": 110.0,
        "regular_market_timestamp": "2026-07-22T03:00:00+00:00",
        "points": [
            {
                "timestamp": "2026-07-21T01:30:00+00:00",
                "close": 100.0,
            }
        ],
    }

    quote = _current_quote_snapshot(history, {"return_1d_pct": 2.0})

    assert quote["price"] == 110.0
    assert quote["pct_change"] == 10.0
    assert quote["market_date"] == "2026-07-22"
    assert quote["basis"] == "intraday_snapshot"
    assert quote["label"] == "盘中最新报价"
    assert quote["is_intraday"] is True
    assert quote["complete_daily_bar_confirmed"] is False


def test_current_quote_snapshot_does_not_call_post_close_quote_intraday():
    history = {
        "timezone": "Asia/Shanghai",
        "currency": "CNY",
        "regular_market_price": 107.51,
        "regular_market_timestamp": "2026-07-22T15:06:30+08:00",
        "points": [
            {
                "timestamp": "2026-07-21T01:30:00+00:00",
                "close": 100.0,
            }
        ],
    }

    quote = _current_quote_snapshot(history, {"return_1d_pct": 2.0})

    assert quote["basis"] == "post_close_snapshot"
    assert quote["label"] == "收盘后最新报价"
    assert quote["is_intraday"] is False


def test_index_one_day_return_is_withheld_when_previous_session_is_missing():
    history = {
        "timezone": "Asia/Shanghai",
        "points": [
            {"timestamp": "2026-07-17T01:30:00+00:00", "close": 100.0},
            {"timestamp": "2026-07-22T01:30:00+00:00", "close": 104.0},
        ],
    }

    metrics = _validated_index_metrics(history, "000300.SS")

    assert metrics["return_1d_pct"] is None
    assert metrics["return_1d_status"] == "missing_previous_session"
    assert metrics["return_1d_expected_previous_market_date"] == "2026-07-21"


def test_market_brief_excludes_cross_date_indices_and_sectors_from_state():
    service = MarketAnalysisService(
        None,
        _DatedMarketProvider(),
        _NextDaySectorProvider(),
        _PreviousSessionBreadthProvider(),
    )

    brief = service.market_brief(market_key="china")

    assert brief["analysis_target"] == {
        "market_date": "2026-07-21",
        "date_basis": "representative_index_session",
        "market_key": "china",
    }
    assert brief["date_alignment"]["status"] == "partial_alignment"
    assert brief["date_alignment"]["aligned_indices"] == 5
    assert brief["date_alignment"]["sector_status"] == "cross_date_excluded"
    assert brief["hot_sectors"]["same_date_as_analysis_target"] is False
    mismatched = next(
        item for item in brief["indices"] if item["symbol"] == "399006.SZ"
    )
    assert mismatched["market_date"] == "2026-07-20"
    assert mismatched["analysis_eligibility"] == "cross_date_excluded"
    assert brief["market_state"]["label"] == "偏强"
    assert brief["market_state"]["aligned_index_count"] == 5
    assert brief["market_state"]["whole_market_breadth_available"] is True


def test_market_brief_uses_newer_index_session_before_previous_day_breadth():
    service = MarketAnalysisService(
        None,
        _CurrentSessionMarketProvider(),
        _NextDaySectorProvider(),
        _PreviousSessionBreadthProvider(),
    )

    brief = service.market_brief(market_key="china")

    assert brief["analysis_target"] == {
        "market_date": "2026-07-22",
        "date_basis": "representative_index_session",
        "market_key": "china",
    }
    assert brief["date_alignment"]["status"] == "same_market_date"
    assert brief["date_alignment"]["aligned_indices"] == 6
    assert brief["date_alignment"]["sector_status"] == "same_market_date"
    assert brief["date_alignment"]["breadth_status"] == "cross_date_excluded"
    assert brief["hot_sectors"]["analysis_eligibility"] == "same_market_date"
    assert brief["market_breadth"]["same_date_as_analysis_target"] is False
    assert brief["market_state"]["whole_market_breadth_available"] is False


def test_conditional_outlook_exposes_scenarios_without_fake_probability():
    metrics = {
        "latest_close": 110.0,
        "ma20": 105.0,
        "ma60": 100.0,
        "return_20d_pct": 8.0,
        "volatility_20d_annualized_pct": 25.0,
    }
    outlook = build_conditional_outlook(
        metrics,
        {"recent_20d_high": 112.0, "recent_20d_low": 96.0},
        {"score": 0.3, "sample_size": 20},
    )
    assert outlook["label"] == "偏强观察"
    assert outlook["probability"] is None
    assert len(outlook["scenarios"]) == 3
    assert "不提供胜率" in outlook["warning"]
    assert "112.0" in outlook["scenarios"][0]["condition"]
    assert "105.0" in outlook["scenarios"][2]["condition"]


def test_evidence_debate_keeps_bull_bear_and_risk_separate():
    debate = build_evidence_debate(
        {
            "metrics": {
                "latest_close": 110,
                "ma20": 105,
                "return_20d_pct": 8,
                "return_60d_pct": -5,
                "max_drawdown_60d_pct": -18,
                "volatility_20d_annualized_pct": 30,
            },
            "a_share_information": {
                "sentiment": {"score": 0.3, "sample_size": 20, "band": "轻微偏多", "confidence": "low_to_medium"}
            },
            "research_frame": {"missing_information": ["估值尚未接入"]},
        }
    )
    assert len(debate["bull_case"]) >= 2
    assert len(debate["bear_case"]) == 1
    assert len(debate["risk_committee"]) == 2
    assert "BUY" not in debate["manager_view"]


def test_evidence_debate_flags_failed_out_of_sample_direction():
    debate = build_evidence_debate(
        {
            "metrics": {
                "latest_close": 90,
                "ma20": 100,
                "return_20d_pct": -8,
                "return_60d_pct": -10,
                "max_drawdown_60d_pct": -12,
                "volatility_20d_annualized_pct": 25,
            },
            "conditional_outlook": {
                "calibration": {
                    "horizon": "10d",
                    "price_signal_label": "偏弱观察",
                    "reliability": "not_directionally_consistent",
                    "historical_analog": {
                        "sample_size": 14,
                        "direction_consistency": 0.31,
                    },
                }
            },
            "research_frame": {"missing_information": []},
        }
    )
    assert any(
        item["risk"] == "历史走查未支持当前价格方向"
        for item in debate["risk_committee"]
    )


def test_business_concentration_is_a_review_need_not_a_proven_failure():
    evidence = {
        "metrics": {},
        "research_frame": {"missing_information": []},
        "business_structure": {
            "status": "available",
            "dimensions": [
                {
                    "classification": "product",
                    "label": "按产品",
                    "current_report_date": "2025-12-31",
                    "concentration": {
                        "top1_item": "茅台酒",
                        "top1_revenue_share_pct": 86.77,
                    },
                }
            ],
            "key_changes": [{"statement": "茅台酒收入占比上升"}],
        },
    }

    debate = build_evidence_debate(evidence)
    review = next(
        item
        for item in debate["risk_committee"]
        if item["risk"] == "主营结构集中度需要复核"
    )
    assert "86.77%" in review["evidence"]
    assert "不能据此认定经营风险已经发生" in review["action"]

    evidence["evidence_debate"] = debate
    board = build_research_analysis_board(evidence)
    fundamentals = next(
        item for item in board["modules"] if item["key"] == "fundamentals"
    )
    assert fundamentals["status"] == "ready"
    assert fundamentals["evidence_count"] == 2
    assert any(
        "主营收入、毛利来源" in item
        for item in board["tracking_plan"][2]["checks"]
    )


def test_optional_industry_gap_does_not_override_ready_core_evidence():
    evidence = {
        "metrics": {"latest_close": 100, "return_20d_pct": 3, "ma20": 98},
        "a_share_information": {
            "announcements": [{"title": "公告"}],
            "sentiment": {"sample_size": 12},
        },
        "fundamentals": {"summary": {"latest_report": {"report_date": "2026-03-31"}}},
        "peer_comparison": {"metrics": {"pe_ttm": {}}, "peers": [{"symbol": "A"}]},
        "evidence_debate": {"bull_case": [{}], "bear_case": [{}], "risk_committee": []},
        "conditional_outlook": {"label": "震荡观察"},
        "price_levels": {"ma20": 98, "recent_20d_low": 90, "recent_20d_high": 110},
        "research_frame": {
            "missing_information": ["行业供需与一致预期尚未接入"]
        },
    }

    debate = build_evidence_debate(evidence)
    board = build_research_analysis_board(evidence)

    assert not any(
        item["risk"] == "证据覆盖不完整"
        for item in debate["risk_committee"]
    )
    assert board["readiness"]["status"] == "ready"
    assert board["readiness"]["optional_gaps"] == [
        "行业供需与一致预期尚未接入"
    ]
    assert "直接回答" in board["readiness"]["response_policy"]
