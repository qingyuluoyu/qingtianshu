from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from app.services.li_zong_portfolio_backtest import LiZongPortfolioBacktestService
from app.services.li_zong_strategy_service import LiZongStrategyService
from app.services.tushare_snapshots import TushareSnapshotService


def _price_rows(dates: list[str]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    a_prices = [100.0, 100.0, 110.0, 121.0, 121.0, 121.0]
    b_prices = [50.0, 50.0, 50.0, 50.0, 55.0, 60.5]
    for index, trade_date in enumerate(dates):
        for symbol, prices in (("000001.SZ", a_prices), ("000002.SZ", b_prices)):
            rows.append(
                {
                    "trade_date": trade_date,
                    "symbol": symbol,
                    "adjusted_open": prices[index],
                    "adjusted_close": prices[index],
                }
            )
    return rows


def test_equal_weight_backtest_rebalances_on_next_open_without_lookahead():
    dates = [
        "2026-01-05",
        "2026-01-06",
        "2026-01-07",
        "2026-01-08",
        "2026-01-09",
        "2026-01-12",
    ]
    candidate_rows = [
        {"trade_date": dates[0], "symbol": "000001.SZ"},
        {"trade_date": dates[1], "symbol": "000001.SZ"},
        {"trade_date": dates[2], "symbol": "000002.SZ"},
        {"trade_date": dates[3], "symbol": "000002.SZ"},
        {"trade_date": dates[4], "symbol": "000002.SZ"},
        {"trade_date": dates[5], "symbol": "000002.SZ"},
    ]
    benchmark = [{"trade_date": value, "close": 100.0} for value in dates]

    result = LiZongPortfolioBacktestService.calculate_portfolio(
        period="3m",
        candidate_rows=candidate_rows,
        price_rows=_price_rows(dates),
        benchmark_rows=benchmark,
        names={"000001.SZ": "甲公司", "000002.SZ": "乙公司"},
        eligible_symbol_count=2,
    )

    assert result["selection_update_count"] == 2
    assert result["rebalances"][0]["signal_date"] == dates[0]
    assert result["rebalances"][0]["trade_date"] == dates[1]
    assert result["rebalances"][0]["symbols"] == ["000001.SZ"]
    assert result["rebalances"][1]["signal_date"] == dates[2]
    assert result["rebalances"][1]["trade_date"] == dates[3]
    assert result["rebalances"][1]["symbols"] == ["000002.SZ"]
    assert result["points"][0]["return_pct"] == 0.0
    assert result["period_return_pct"] > 20.0
    assert result["total_cost_pct_of_initial_nav"] > 0.0
    assert result["benchmark_return_pct"] == 0.0


def test_backtest_holds_cash_when_strategy_never_selects_a_stock():
    dates = ["2026-01-05", "2026-01-06", "2026-01-07"]
    result = LiZongPortfolioBacktestService.calculate_portfolio(
        period="3m",
        candidate_rows=[],
        price_rows=[],
        benchmark_rows=[
            {"trade_date": dates[0], "close": 100.0},
            {"trade_date": dates[1], "close": 101.0},
            {"trade_date": dates[2], "close": 102.0},
        ],
        names={},
        eligible_symbol_count=8,
    )

    assert result["period_return_pct"] == 0.0
    assert result["annualized_return_pct"] == 0.0
    assert result["selection_update_count"] == 0
    assert result["ever_selected_symbol_count"] == 0
    assert result["benchmark_return_pct"] == 2.0


def test_backtest_result_discloses_incomplete_input_coverage():
    dates = ["2026-01-05", "2026-01-06", "2026-01-07"]
    result = LiZongPortfolioBacktestService.calculate_portfolio(
        period="3m",
        candidate_rows=[],
        price_rows=[],
        benchmark_rows=[
            {"trade_date": dates[0], "close": 100.0},
            {"trade_date": dates[1], "close": 101.0},
            {"trade_date": dates[2], "close": 102.0},
        ],
        names={},
        eligible_symbol_count=8,
        complete_symbol_count=7,
        incomplete_symbols=["000008.SZ"],
    )

    assert result["complete_symbol_count"] == 7
    assert result["incomplete_symbol_count"] == 1
    assert result["data_coverage_ratio"] == 0.875
    assert result["incomplete_symbols"] == ["000008.SZ"]
    assert "不会被当作候选" in result["data_coverage_boundary"]


def test_backtest_api_and_frontend_expose_three_periods(app, client, monkeypatch):
    assert client.post("/users", json={"name": "Backtest User"}).status_code == 201
    monkeypatch.setattr(
        app.state.li_zong_backtest,
        "packet",
        lambda **kwargs: {
            "status": "ready",
            "selected_period": kwargs["period"],
            "result": {"period_return_pct": 8.2},
            "periods": {"3m": {}, "1y": {}, "3y": {}},
        },
    )

    response = client.get("/v1/stock-strategies/li-zong/backtest?period=3y")
    page = client.get("/demo")

    assert response.status_code == 200
    assert response.json()["selected_period"] == "3y"
    assert page.status_code == 200
    assert 'id="liZongBacktestPanel"' in page.text
    assert 'data-li-zong-backtest-period="3m"' in page.text
    assert 'data-li-zong-backtest-period="1y"' in page.text
    assert 'data-li-zong-backtest-period="3y"' in page.text


def test_backtest_tables_and_long_history_window_are_initialized(app):
    database = app.state.database
    with database.connect() as connection:
        rows = connection.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = current_schema()
              AND table_name IN (
                'strategy_backtest_market_cap_days',
                'strategy_backtest_market_caps',
                'strategy_backtest_symbol_states',
                'strategy_backtest_symbol_coverage'
              )
            """
        ).fetchall()

    assert {str(item["table_name"]) for item in rows} == {
        "strategy_backtest_market_cap_days",
        "strategy_backtest_market_caps",
        "strategy_backtest_symbol_states",
        "strategy_backtest_symbol_coverage",
    }
    assert database.schema_status()["schema_version"] >= 3
    assert TushareSnapshotService.SYMBOL_HISTORY_MARKET_DAYS >= 1136
    assert LiZongStrategyService.PRICE_HISTORY_WINDOW_VERSION == "market_days_1150_v1"


def test_refresh_only_evaluates_the_largest_market_cap_window_that_is_ready(
    monkeypatch,
):
    class FakeDatabase:
        def start_tushare_sync_run(self, **_kwargs):
            return {"id": "run-1"}

        def finish_tushare_sync_run(self, *_args, **_kwargs):
            return None

        def list_strategy_backtest_eligible_symbols(self, **_kwargs):
            return ["000001.SZ"]

    snapshot_service = type("SnapshotService", (), {"client": object()})()
    service = LiZongPortfolioBacktestService(
        FakeDatabase(), snapshot_service, object()
    )
    trade_dates = [
        value.date().isoformat()
        for value in pd.bdate_range(end="2026-07-24", periods=756)
    ]
    captured: dict[str, object] = {}
    monkeypatch.setattr(service, "_target_trade_dates", lambda _value: trade_dates)
    monkeypatch.setattr(service, "_save_calendar", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        service, "_refresh_market_cap_days", lambda *_args, **_kwargs: 0
    )
    monkeypatch.setattr(
        service,
        "_ready_period_windows",
        lambda _dates: {"3m": (trade_dates[-63], trade_dates[-1])},
    )
    monkeypatch.setattr(
        service, "_market_cap_window_version", lambda _dates: "market-cap-v1"
    )

    def capture_advance(_symbols, **kwargs):
        captured.update(kwargs)
        return [], []

    monkeypatch.setattr(service, "_advance_symbol_states", capture_advance)
    monkeypatch.setattr(service, "_ensure_benchmark", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        service, "_publish_period_if_complete", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        service,
        "_progress_packet",
        lambda: {"periods": {"3m": {"status": "building"}}},
    )

    result = service.refresh()

    assert result["status"] == "partial"
    assert captured["required_start"] == trade_dates[-63]
    assert captured["market_cap_data_version"] == "market-cap-v1"
    assert captured["trade_dates"] == trade_dates[-63:]
    assert captured["priority_windows"] == [
        {
            "period": "3m",
            "start_date": trade_dates[-63],
            "end_date": trade_dates[-1],
            "symbols": {"000001.SZ"},
        }
    ]


def test_backtest_prioritizes_the_earliest_incomplete_visible_period():
    symbols = ["000003.SZ", "000004.SZ", "000001.SZ", "000002.SZ"]
    coverage = {
        "000001.SZ": {
            "start_date": "2026-04-23",
            "end_date": "2026-07-24",
        },
        "000003.SZ": {
            "start_date": "2025-07-11",
            "end_date": "2026-07-24",
        },
    }
    windows = [
        {
            "period": "3m",
            "start_date": "2026-04-23",
            "end_date": "2026-07-24",
            "symbols": {"000001.SZ", "000002.SZ"},
        },
        {
            "period": "1y",
            "start_date": "2025-07-11",
            "end_date": "2026-07-24",
            "symbols": {"000001.SZ", "000002.SZ", "000003.SZ"},
        },
        {
            "period": "3y",
            "start_date": "2023-06-12",
            "end_date": "2026-07-24",
            "symbols": set(symbols),
        },
    ]

    ordered = LiZongPortfolioBacktestService._prioritize_symbols_for_windows(
        symbols,
        coverage=coverage,
        current_symbols={"000001.SZ", "000003.SZ"},
        priority_windows=windows,
    )

    assert ordered == ["000002.SZ", "000001.SZ", "000003.SZ", "000004.SZ"]


def test_backtest_reapplies_period_priority_to_late_sync_queue_entries():
    batch = LiZongPortfolioBacktestService._ordered_sync_batch(
        ["000003.SZ", "000004.SZ", "000001.SZ", "000002.SZ", "000001.SZ"],
        ordered_symbols=["000001.SZ", "000002.SZ", "000003.SZ", "000004.SZ"],
        limit=3,
    )

    assert batch == ["000001.SZ", "000002.SZ", "000003.SZ"]


def test_backtest_coverage_requires_current_snapshot_and_market_cap_versions():
    trade_dates = ["2026-07-22", "2026-07-23", "2026-07-24"]

    class FakeDatabase:
        market_versions = {
            "2026-07-22": "cap-1",
            "2026-07-23": "cap-2",
            "2026-07-24": "cap-3",
        }

        def latest_tushare_dataset_snapshot(self, *_args, **_kwargs):
            return {"payload": {"trade_dates": trade_dates}}

        def list_strategy_backtest_market_cap_days(self, **_kwargs):
            return [
                {"trade_date": value, "data_version": self.market_versions[value]}
                for value in trade_dates
            ]

    database = FakeDatabase()
    service = LiZongPortfolioBacktestService(database, object(), object())
    market_version = service._market_cap_window_version(trade_dates)
    source_version = service._state_source_version(
        snapshot_data_version="snapshot-v2",
        market_cap_data_version=market_version,
        start_date=trade_dates[0],
        end_date=trade_dates[-1],
    )
    coverage = {
        "start_date": trade_dates[0],
        "end_date": trade_dates[-1],
        "source_data_version": source_version,
    }

    assert service._coverage_is_current(
        coverage,
        {"data_version": "snapshot-v2"},
        market_cap_version_cache={},
    )
    assert not service._coverage_is_current(
        coverage,
        {"data_version": "snapshot-v3"},
        market_cap_version_cache={},
    )

    database.market_versions["2026-07-24"] = "corrected-cap-3"
    assert not service._coverage_is_current(
        coverage,
        {"data_version": "snapshot-v2"},
        market_cap_version_cache={},
    )


def test_backtest_accepts_an_inactive_stock_snapshot_queried_through_window_end():
    snapshot = {
        "as_of_date": "2024-02-05",
        "payload": {
            "as_of_date": "2024-02-05",
            "requested_as_of_date": "2026-07-24",
        },
    }

    assert LiZongPortfolioBacktestService._snapshot_requested_through(
        snapshot, "2026-07-24"
    )
    assert not LiZongPortfolioBacktestService._snapshot_requested_through(
        snapshot, "2026-07-25"
    )

    metadata_only_snapshot = {
        "as_of_date": "2024-02-05",
        "requested_as_of_date": "2026-07-24",
    }
    assert LiZongPortfolioBacktestService._snapshot_requested_through(
        metadata_only_snapshot, "2026-07-24"
    )


def test_backtest_uses_best_available_history_after_current_extension_attempt():
    snapshot = {
        "as_of_date": "2026-07-24",
        "payload": {
            "requested_as_of_date": "2026-07-24",
            "sync_profile": "market_history_extension_v1",
        },
    }

    assert LiZongPortfolioBacktestService._history_extension_attempted(
        snapshot, end_date="2026-07-24"
    )
    assert not LiZongPortfolioBacktestService._history_extension_attempted(
        snapshot, end_date="2026-07-25"
    )


def test_backtest_prefers_current_incomplete_input_over_stale_stable_input():
    class FakeDatabase:
        def list_latest_tushare_dataset_snapshots(
            self, dataset, **_kwargs
        ):
            if dataset == "li_zong_inputs":
                return [
                    {
                        "dataset": dataset,
                        "scope_key": "000001.SZ",
                        "as_of_date": "2026-07-21",
                        "requested_as_of_date": "2026-07-21",
                        "created_at": "2026-07-21T16:00:00+00:00",
                    },
                    {
                        "dataset": dataset,
                        "scope_key": "000002.SZ",
                        "as_of_date": "2026-07-24",
                        "requested_as_of_date": "2026-07-24",
                        "created_at": "2026-07-24T16:00:00+00:00",
                    },
                ]
            return [
                {
                    "dataset": dataset,
                    "scope_key": "000001.SZ",
                    "as_of_date": "2026-07-24",
                    "requested_as_of_date": "2026-07-24",
                    "created_at": "2026-07-24T17:00:00+00:00",
                },
                {
                    "dataset": dataset,
                    "scope_key": "000002.SZ",
                    "as_of_date": "2026-07-24",
                    "requested_as_of_date": "2026-07-24",
                    "created_at": "2026-07-24T17:00:00+00:00",
                },
            ]

    service = LiZongPortfolioBacktestService(FakeDatabase(), object(), object())
    metadata = service._snapshot_metadata()

    assert metadata["000001.SZ"]["dataset"] == "li_zong_inputs_incomplete"
    assert metadata["000002.SZ"]["dataset"] == "li_zong_inputs"


def test_backtest_creates_explicit_incomplete_states_for_unusable_input():
    states = LiZongPortfolioBacktestService._incomplete_states(
        ["2026-07-23", "2026-07-24"]
    )

    assert [item["trade_date"] for item in states] == ["2026-07-23", "2026-07-24"]
    assert all(item["status"] == "data_incomplete" for item in states)
    assert all(item["candidate_qualified"] is False for item in states)


def test_backtest_forces_delisted_candidate_out_at_last_available_close_proxy():
    previous = {
        "trade_date": "2024-02-05",
        "status": "qualified",
        "candidate_qualified": True,
        "adjusted_open": 1.42,
        "adjusted_close": 1.38,
        "raw_open": 1.42,
        "raw_close": 1.38,
    }

    carried = LiZongPortfolioBacktestService._carried_state(
        previous,
        trade_date="2024-02-06",
        forced_exit=True,
    )

    assert carried["status"] == "not_qualified"
    assert carried["candidate_qualified"] is False
    assert carried["adjusted_open"] == 1.38
    assert carried["adjusted_close"] == 1.38


def test_vectorized_historical_states_match_reference_strategy_evaluation():
    all_dates = [
        value.date().isoformat()
        for value in pd.bdate_range(end="2026-07-24", periods=450)
    ]
    limit_indices = {250, 300, 350, 400, 442, 443, 449}
    daily = []
    for index, trade_date in enumerate(all_dates):
        close = 11.0 if index in limit_indices else 10.0
        daily.append(
            {
                "trade_date": trade_date,
                "open": 10.0,
                "high": 10.5 + index * 0.01,
                "low": 9.5,
                "close": close,
                "pre_close": 10.0,
                "pct_chg": 10.0 if index in limit_indices else 0.0,
                "volume": 300.0 if index >= len(all_dates) - 3 else 100.0,
                "adj_factor": 1.0,
                "up_limit": 11.0,
                "down_limit": 9.0,
                "source": "synthetic point-in-time fixture",
            }
        )
    roe = [
        {
            "end_date": f"{year}-12-31",
            "ann_date": f"{year + 1}-03-31",
            "roe": 12.0,
        }
        for year in range(2019, 2025)
    ]
    shareholders = [
        {
            "report_period": "2025-12-31",
            "ann_date": "2026-03-31",
            "holder_name": f"机构股东{index}",
            "holder_type": "institution",
        }
        for index in range(6)
    ]
    strategy_input = {
        "symbol": "000001.SZ",
        "as_of_date": all_dates[-1],
        "daily": pd.DataFrame(daily),
        "roe_history": pd.DataFrame(roe),
        "shareholders": pd.DataFrame(shareholders),
        "daily_basic": pd.DataFrame(),
    }

    class FakeDatabase:
        def strategy_backtest_market_caps_for_symbol(self, **kwargs):
            return {
                value: 200.0
                for value in all_dates
                if kwargs["start_date"] <= value <= kwargs["end_date"]
            }

        def latest_strategy_candidate_snapshot(self, **_kwargs):
            return None

    class FakeStrategyService:
        def _build_input(self, *_args, **_kwargs):
            return strategy_input

    service = LiZongPortfolioBacktestService(
        FakeDatabase(), object(), FakeStrategyService()
    )
    target = all_dates[-252:]
    snapshot = {"data_version": "fixture-v1", "payload": {}}

    optimized = service._evaluate_symbol(
        "000001.SZ", snapshot, trade_dates=target
    )
    reference = service._evaluate_symbol_reference(
        "000001.SZ", snapshot, trade_dates=target
    )

    assert optimized == reference
    assert optimized[-1]["candidate_qualified"] is True
    assert optimized[-1]["status"] == "triggered"


def test_backtest_default_as_of_excludes_an_open_session_before_close():
    shanghai = ZoneInfo("Asia/Shanghai")
    assert LiZongPortfolioBacktestService._default_as_of_date(
        datetime(2026, 7, 27, 0, 5, tzinfo=shanghai)
    ).isoformat() == "2026-07-26"
    assert LiZongPortfolioBacktestService._default_as_of_date(
        datetime(2026, 7, 27, 16, 30, tzinfo=shanghai)
    ).isoformat() == "2026-07-27"


def test_backtest_does_not_publish_empty_market_cap_cross_section():
    class FakeDatabase:
        def list_strategy_backtest_market_cap_days(self, **_kwargs):
            return []

        def save_strategy_backtest_market_cap_day(self, **_kwargs):
            raise AssertionError("empty market data must not be persisted")

    class FakeClient:
        def daily_basic(self, **_kwargs):
            return pd.DataFrame()

    snapshot_service = type("SnapshotService", (), {"client": FakeClient()})()
    service = LiZongPortfolioBacktestService(FakeDatabase(), snapshot_service, object())

    assert service._refresh_market_cap_days(["2026-07-27"], batch_size=1) == 0
