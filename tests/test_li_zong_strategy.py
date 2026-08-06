from __future__ import annotations

from copy import deepcopy

import pandas as pd
import pytest

from app.services.strategies import strategy_registry
from app.services.strategies.li_zong import deterministic_li_zong_v1


AS_OF = "2026-07-21"


def _qualified_packet() -> dict:
    dates = pd.bdate_range(end=AS_OF, periods=400)
    daily_rows = []
    limit_indices = {-200, -199, -150, -100, -50, -5}
    for position, trade_date in enumerate(dates):
        relative = position - len(dates)
        pre_close = 100.0 + position * 0.05
        close = pre_close + 0.5
        up_limit = pre_close + 10.0
        if relative in limit_indices:
            close = up_limit
        daily_rows.append(
            {
                "trade_date": trade_date.strftime("%Y%m%d"),
                "open": close - 0.4,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "pre_close": pre_close,
                "pct_chg": (close / pre_close - 1.0) * 100.0,
                "volume": 100.0,
                "up_limit": up_limit,
                "has_price_limit": True,
                "adjusted_high": 100.0 + position * 0.1,
                "source": "fixture.daily+stk_limit",
            }
        )
    for relative in (-30, -29, -28):
        daily_rows[relative]["volume"] = 200.0

    roe_history = [
        {
            "end_date": f"{year}1231",
            "ann_date": f"{year + 1}0430",
            "roe": 10.0 + (year - 2021),
            "source": "fixture.fina_indicator",
        }
        for year in range(2021, 2026)
    ]
    shareholders = [
        {
            "report_period": "20260331",
            "ann_date": "20260430",
            "holder_name": name,
            "holder_type": holder_type,
            "classification_reason": reason,
            "source": "fixture.holders",
        }
        for name, holder_type, reason in (
            ("甲公司", "company", "工商登记法人"),
            ("乙基金", "fund", "基金产品"),
            ("丙保险", "insurance", "保险机构"),
            ("丁银行", "bank", "银行机构"),
            ("戊资管计划", "asset_management", "资管计划"),
            ("甲 公 司", "institution", "流通股东表重复名称"),
            ("张三", "natural_person", "自然人"),
            ("未分类主体", "unknown", "资料未明确"),
        )
    ]
    return {
        "symbol": "000001.SZ",
        "as_of_date": AS_OF,
        "daily": pd.DataFrame(daily_rows),
        "roe_history": pd.DataFrame(roe_history),
        "shareholders": pd.DataFrame(shareholders),
        "daily_basic": pd.DataFrame(
            [
                {
                    "trade_date": "20260721",
                    "total_mv": 1_510_000.0,
                    "source": "fixture.daily_basic",
                }
            ]
        ),
    }


def _evaluate(packet: dict | None = None, **parameters) -> dict:
    return deterministic_li_zong_v1(
        packet or _qualified_packet(), parameters=parameters or None
    )


def _rules(result: dict) -> dict[str, dict]:
    return {item["rule_id"]: item for item in result["rule_results"]}


def _daily_copy(packet: dict) -> pd.DataFrame:
    return packet["daily"].copy(deep=True)


def test_registry_and_result_contract_are_versioned_and_auditable():
    assert strategy_registry.get("li_zong").method == "deterministic_li_zong_v1"
    assert strategy_registry.list() == [
        {
            "strategy_id": "li_zong",
            "strategy_version": "li_zong_v1",
            "method": "deterministic_li_zong_v1",
        }
    ]

    result = _evaluate()

    assert result["status"] == "qualified"
    assert result["candidate_qualified"] is True
    assert result["strategy_version"] == "li_zong_v1"
    assert result["parameter_version"] == "li_zong_v1_default"
    assert len(result["rule_results"]) == 12
    for rule in result["rule_results"]:
        assert {
            "rule_id",
            "status",
            "actual_value",
            "threshold",
            "evidence_date",
            "report_period",
            "source",
            "formula_version",
            "limitations",
        } <= set(rule)
        assert rule["status"] in {"passed", "failed", "data_incomplete"}
        assert rule["evidence_date"] or rule["report_period"]
        assert rule["source"]
        assert rule["formula_version"] == "deterministic_li_zong_v1"
    assert "不构成买卖建议" in result["boundary"]


@pytest.mark.parametrize(
    ("market_cap_yi", "expected"),
    [(150.0, "failed"), (150.0001, "passed")],
)
def test_market_cap_is_strictly_greater_than_150_yi(market_cap_yi, expected):
    packet = _qualified_packet()
    packet["daily_basic"] = {
        "trade_date": "20260721",
        "total_mv_yi": market_cap_yi,
        "source": "fixture.market_cap_yi",
    }

    assert _rules(_evaluate(packet))["LZ-F-01"]["status"] == expected


def test_five_annual_roe_requires_every_year_and_respects_parameter_version():
    packet = _qualified_packet()
    roe = packet["roe_history"].copy()
    roe.loc[roe["end_date"] == "20231231", "roe"] = 9.99
    packet["roe_history"] = roe
    failed = _evaluate(
        packet,
        roe_min_pct=10.0,
        parameter_version="li_zong_v1_roe_10",
    )
    assert _rules(failed)["LZ-F-02"]["status"] == "failed"
    assert failed["parameter_version"] == "li_zong_v1_roe_10"

    packet["roe_history"] = roe[roe["end_date"] != "20231231"]
    incomplete = _rules(_evaluate(packet))["LZ-F-02"]
    assert incomplete["status"] == "data_incomplete"
    assert "2023-12-31" in incomplete["limitations"][0]


def test_future_roe_announcement_cannot_repair_as_of_failure():
    packet = _qualified_packet()
    roe = packet["roe_history"].copy()
    roe.loc[roe["end_date"] == "20251231", "roe"] = 5.0
    future_revision = roe.iloc[-1].copy()
    future_revision["ann_date"] = "20260722"
    future_revision["roe"] = 50.0
    packet["roe_history"] = pd.concat(
        [roe, pd.DataFrame([future_revision])], ignore_index=True
    )

    rule = _rules(_evaluate(packet))["LZ-F-02"]

    assert rule["status"] == "failed"
    newest = next(
        item for item in rule["actual_value"] if item["report_period"] == "2025-12-31"
    )
    assert newest["roe_pct"] == 5.0


def test_shareholders_are_explicitly_classified_and_deduplicated():
    rule = _rules(_evaluate())["LZ-F-04"]

    assert rule["status"] == "passed"
    assert rule["actual_value"]["non_natural_holder_count"] == 5
    assert rule["actual_value"]["unknown_holder_count"] == 1
    institutions = [
        item
        for item in rule["actual_value"]["holders"]
        if item["classification"] == "institution"
    ]
    assert len(institutions) == 5
    assert next(item for item in institutions if item["normalized_name"] == "甲公司")[
        "raw_names"
    ] == ["甲公司", "甲 公 司"]
    assert "无法可靠分类" in rule["limitations"][0]


@pytest.mark.parametrize(("limit_count", "expected"), [(5, "failed"), (6, "passed")])
def test_annual_limit_up_count_boundary(limit_count, expected):
    packet = _qualified_packet()
    daily = _daily_copy(packet)
    daily["up_limit"] = daily["close"] + 1.0
    for index in range(limit_count):
        row_index = daily.index[-10 - index * 20]
        daily.loc[row_index, "up_limit"] = daily.loc[row_index, "close"]
    packet["daily"] = daily

    assert _rules(_evaluate(packet))["LZ-C-01"]["status"] == expected


def test_two_limit_days_separated_by_suspension_are_not_consecutive():
    packet = _qualified_packet()
    daily = _daily_copy(packet)
    daily["up_limit"] = daily["close"] + 1.0
    daily["is_suspended"] = False
    left, middle, right = daily.index[-100], daily.index[-99], daily.index[-98]
    daily.loc[[left, right], "up_limit"] = daily.loc[[left, right], "close"]
    daily.loc[middle, "is_suspended"] = True
    daily.loc[middle, "volume"] = 0.0
    packet["daily"] = daily

    assert _rules(_evaluate(packet))["LZ-C-02"]["status"] == "failed"


@pytest.mark.parametrize(
    ("board", "up_limit"),
    [
        ("主板", 110.0),
        ("ST", 105.0),
        ("创业板", 120.0),
        ("科创板", 120.0),
        ("北交所", 130.0),
    ],
)
def test_limit_trigger_uses_real_daily_limit_not_board_guess(board, up_limit):
    packet = _qualified_packet()
    daily = _daily_copy(packet)
    latest = daily.index[-1]
    daily.loc[latest, ["board", "pre_close", "up_limit", "close", "open"]] = [
        board,
        100.0,
        up_limit,
        up_limit,
        up_limit - 1.0,
    ]
    packet["daily"] = daily

    assert _rules(_evaluate(packet))["LZ-T-01"]["status"] == "passed"


def test_formal_no_limit_day_is_failed_trigger_but_missing_limit_is_incomplete():
    no_limit_packet = _qualified_packet()
    daily = _daily_copy(no_limit_packet)
    latest = daily.index[-1]
    daily.loc[latest, "has_price_limit"] = False
    daily.loc[latest, "up_limit"] = float("nan")
    no_limit_packet["daily"] = daily
    assert _rules(_evaluate(no_limit_packet))["LZ-T-01"]["status"] == "failed"

    missing_packet = _qualified_packet()
    daily = _daily_copy(missing_packet).drop(columns=["has_price_limit"])
    daily.loc[daily.index[-1], "up_limit"] = float("nan")
    missing_packet["daily"] = daily
    result = _evaluate(missing_packet)
    assert _rules(result)["LZ-T-01"]["status"] == "data_incomplete"
    assert result["status"] == "data_incomplete"


def test_recent_limit_and_bearish_five_percent_candle_boundaries():
    packet = _qualified_packet()
    rules = _rules(_evaluate(packet))
    assert rules["LZ-C-03"]["status"] == "passed"
    assert rules["LZ-C-04"]["status"] == "passed"

    bearish = _qualified_packet()
    daily = _daily_copy(bearish)
    latest = daily.index[-1]
    daily.loc[latest, ["open", "close", "pct_chg"]] = [100.0, 95.0, -5.0]
    bearish["daily"] = daily
    assert _rules(_evaluate(bearish))["LZ-C-04"]["status"] == "failed"

    for open_price, close_price, pct_chg in (
        (95.0, 96.0, -5.0),
        (100.0, 95.01, -4.99),
    ):
        safe = _qualified_packet()
        daily = _daily_copy(safe)
        latest = daily.index[-1]
        daily.loc[latest, ["open", "close", "pct_chg"]] = [
            open_price,
            close_price,
            pct_chg,
        ]
        safe["daily"] = daily
        assert _rules(_evaluate(safe))["LZ-C-04"]["status"] == "passed"


@pytest.mark.parametrize(("relative_index", "expected"), [(-20, "passed"), (-21, "failed")])
def test_adjusted_new_high_must_occur_inside_latest_twenty_days(relative_index, expected):
    packet = _qualified_packet()
    daily = _daily_copy(packet)
    daily["adjusted_high"] = 100.0
    daily.loc[daily.index[relative_index], "adjusted_high"] = 101.0
    packet["daily"] = daily

    assert _rules(_evaluate(packet))["LZ-VP-01"]["status"] == expected


def test_new_high_uses_adjustment_factor_instead_of_raw_high():
    packet = _qualified_packet()
    daily = _daily_copy(packet).drop(columns=["adjusted_high"])
    daily["high"] = 100.0
    daily["adj_factor"] = 1.0
    daily.loc[daily.index[-20:], "high"] = 99.0
    daily.loc[daily.index[-1], ["high", "adj_factor"]] = [200.0, 0.25]
    packet["daily"] = daily

    assert _rules(_evaluate(packet))["LZ-VP-01"]["status"] == "failed"


@pytest.mark.parametrize(
    ("volumes", "expected"),
    [
        ((200.0, 200.0, 200.0), "passed"),
        ((200.0, 200.0, 199.0), "failed"),
        ((200.0, 200.0, 100.0), "failed"),
    ],
)
def test_three_day_volume_expansion_requires_every_day_at_two_times(volumes, expected):
    packet = _qualified_packet()
    daily = _daily_copy(packet)
    daily["volume"] = 100.0
    daily.loc[daily.index[-3:], "volume"] = list(volumes)
    packet["daily"] = daily

    assert _rules(_evaluate(packet))["LZ-VP-02"]["status"] == expected


def test_volume_history_or_suspension_gap_is_data_incomplete():
    short = _qualified_packet()
    short["daily"] = _daily_copy(short).tail(379)
    assert _rules(_evaluate(short))["LZ-VP-02"]["status"] == "data_incomplete"

    suspended = _qualified_packet()
    daily = _daily_copy(suspended)
    daily["is_suspended"] = False
    daily.loc[daily.index[-200], "is_suspended"] = True
    daily.loc[daily.index[-200], "volume"] = 0.0
    suspended["daily"] = daily
    assert _rules(_evaluate(suspended))["LZ-VP-02"]["status"] == "data_incomplete"


def test_gap_open_exactly_3_5_percent_with_bullish_candle_triggers():
    packet = _qualified_packet()
    daily = _daily_copy(packet)
    latest = daily.index[-1]
    daily.loc[latest, ["pre_close", "open", "close", "high", "low", "up_limit"]] = [
        100.0,
        103.5,
        104.0,
        104.2,
        100.0,
        110.0,
    ]
    packet["daily"] = daily

    result = _evaluate(packet)

    assert result["status"] == "triggered"
    assert "LZ-T-02" in result["triggered_rule_ids"]
    assert _rules(result)["LZ-T-02"]["status"] == "passed"


@pytest.mark.parametrize(
    ("low", "expected"),
    [(95.2, "failed"), (95.19, "passed")],
)
def test_amplitude_must_be_strictly_greater_than_9_8_percent(low, expected):
    packet = _qualified_packet()
    daily = _daily_copy(packet)
    latest = daily.index[-1]
    daily.loc[latest, ["pre_close", "open", "close", "high", "low", "up_limit"]] = [
        100.0,
        100.0,
        101.0,
        105.0,
        low,
        110.0,
    ]
    packet["daily"] = daily

    assert _rules(_evaluate(packet))["LZ-T-03"]["status"] == expected


def test_failed_rule_wins_over_incomplete_and_trigger_shape_does_not_enter_pool():
    packet = _qualified_packet()
    packet["daily_basic"] = {}
    roe = packet["roe_history"].copy()
    roe.loc[roe.index[-1], "roe"] = 1.0
    packet["roe_history"] = roe
    daily = _daily_copy(packet)
    latest = daily.index[-1]
    daily.loc[latest, "up_limit"] = daily.loc[latest, "close"]
    packet["daily"] = daily

    result = _evaluate(packet)

    assert result["status"] == "not_qualified"
    assert result["candidate_qualified"] is False
    assert result["triggered_rule_ids"] == []
    assert "数据缺口" in result["limitations"][0]
    assert "不会进入触发池" in result["limitations"][1]


def test_missing_trigger_evidence_cannot_be_reported_as_qualified():
    packet = _qualified_packet()
    daily = _daily_copy(packet)
    daily.loc[daily.index[-1], "pre_close"] = float("nan")
    packet["daily"] = daily

    result = _evaluate(packet)

    assert result["candidate_qualified"] is True
    assert result["status"] == "data_incomplete"
    assert result["triggered_rule_ids"] == []
    assert _rules(result)["LZ-T-02"]["status"] == "data_incomplete"
    assert _rules(result)["LZ-T-03"]["status"] == "data_incomplete"
    assert "不能判定为 qualified" in result["limitations"][0]


def test_pure_evaluation_is_repeatable_and_does_not_mutate_frames():
    packet = _qualified_packet()
    original = deepcopy(packet)

    first = _evaluate(packet)
    second = _evaluate(packet)

    assert first == second
    pd.testing.assert_frame_equal(packet["daily"], original["daily"])
    pd.testing.assert_frame_equal(packet["roe_history"], original["roe_history"])
    pd.testing.assert_frame_equal(packet["shareholders"], original["shareholders"])


def test_future_daily_row_is_ignored_by_as_of_snapshot():
    packet = _qualified_packet()
    daily = _daily_copy(packet)
    future = daily.iloc[-1].copy()
    future["trade_date"] = "20260722"
    future["close"] = future["up_limit"]
    packet["daily"] = pd.concat([daily, pd.DataFrame([future])], ignore_index=True)

    result = _evaluate(packet)

    assert result["as_of_date"] == AS_OF
    assert _rules(result)["LZ-T-01"]["status"] == "failed"


def test_three_qualified_three_failed_and_three_incomplete_fixed_samples():
    qualified = [_qualified_packet() for _ in range(3)]
    failed = [_qualified_packet() for _ in range(3)]
    incomplete = [_qualified_packet() for _ in range(3)]
    for index, packet in enumerate(qualified):
        packet["symbol"] = f"Q{index}"
    for index, packet in enumerate(failed):
        packet["symbol"] = f"F{index}"
        packet["daily_basic"] = {"trade_date": "20260721", "total_mv_yi": 100.0}
    for index, packet in enumerate(incomplete):
        packet["symbol"] = f"I{index}"
        packet["roe_history"] = pd.DataFrame()

    assert [_evaluate(packet)["status"] for packet in qualified] == ["qualified"] * 3
    assert [_evaluate(packet)["status"] for packet in failed] == ["not_qualified"] * 3
    assert [_evaluate(packet)["status"] for packet in incomplete] == [
        "data_incomplete"
    ] * 3
