from __future__ import annotations

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
