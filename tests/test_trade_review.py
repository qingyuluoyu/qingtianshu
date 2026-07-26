from __future__ import annotations

from decimal import Decimal

from app.db import Database


def test_trade_review_separates_realized_unrealized_fees_and_win_rate(tmp_path):
    from app.services.trade_review import TradeReviewService

    database = Database(tmp_path / "app.db", tmp_path / "workspaces")
    database.initialize()
    user = database.create_user("trade review")
    position = database.create_position(
        user_id=user["id"],
        symbol="300750.SZ",
        name="宁德时代",
        account_type="simulated",
        quantity="100",
        cost_price="100",
        current_price="110",
        status="open",
        data_as_of="2026-07-25T15:00:00+08:00",
    )
    database.create_trade(
        user_id=user["id"],
        position_id=position["id"],
        symbol="300750.SZ",
        side="buy",
        executed_at="2026-07-01T10:00:00+08:00",
        price="100",
        quantity="100",
        fee="5",
        realized_pnl=None,
    )
    database.create_trade(
        user_id=user["id"],
        position_id=None,
        symbol="600519.SS",
        side="sell",
        executed_at="2026-07-10T10:00:00+08:00",
        price="1500",
        quantity="10",
        fee="8",
        realized_pnl="200",
    )
    database.create_trade(
        user_id=user["id"],
        position_id=None,
        symbol="000858.SZ",
        side="sell",
        executed_at="2026-07-11T10:00:00+08:00",
        price="130",
        quantity="100",
        fee="7",
        realized_pnl="-50",
    )

    packet = TradeReviewService(database).summary(user["id"])

    assert packet["summary"]["closedTradeCount"] == 2
    assert packet["summary"]["winningClosedTradeCount"] == 1
    assert packet["summary"]["winRatePct"] == Decimal("50.00")
    assert packet["summary"]["realizedPnlCny"] == Decimal("150.00")
    assert packet["summary"]["unrealizedPnlCny"] == Decimal("1000.00")
    assert packet["summary"]["feesCny"] == Decimal("20.00")
    assert packet["summary"]["netPnlCny"] == Decimal("1130.00")
    assert packet["openPositions"][0]["currentMarketValueCny"] == Decimal("11000.00")
    assert packet["openPositions"][0]["unrealizedPnlCny"] == Decimal("1000.00")


def test_open_position_does_not_count_as_closed_trade(tmp_path):
    from app.services.trade_review import TradeReviewService

    database = Database(tmp_path / "app.db", tmp_path / "workspaces")
    database.initialize()
    user = database.create_user("open only")
    database.create_position(
        user_id=user["id"],
        symbol="600519.SS",
        name="贵州茅台",
        account_type="live",
        quantity="10",
        cost_price="1400",
        current_price="1450",
        status="open",
        data_as_of="2026-07-25T15:00:00+08:00",
    )

    packet = TradeReviewService(database).summary(user["id"])

    assert packet["summary"]["closedTradeCount"] == 0
    assert packet["summary"]["winRatePct"] is None
    assert packet["summary"]["realizedPnlCny"] == Decimal("0.00")
    assert packet["summary"]["unrealizedPnlCny"] == Decimal("500.00")


def test_trade_review_api_is_user_scoped_and_empty_win_rate_is_null(client, app):
    first = client.post("/users", json={"name": "first review user"})
    assert first.status_code == 201
    first_user = first.json()
    app.state.database.create_position(
        user_id=first_user["id"],
        symbol="300750.SZ",
        name="宁德时代",
        account_type="simulated",
        quantity="10",
        cost_price="100",
        current_price="105",
        status="open",
        data_as_of="2026-07-25T15:00:00+08:00",
    )

    first_packet = client.get("/me/trade-reviews")
    assert first_packet.status_code == 200
    assert first_packet.json()["summary"]["openPositionCount"] == 1
    assert first_packet.json()["summary"]["winRatePct"] is None

    second = client.post("/users", json={"name": "second review user"})
    assert second.status_code == 201
    second_packet = client.get("/me/trade-reviews")
    assert second_packet.status_code == 200
    assert second_packet.json()["summary"]["openPositionCount"] == 0
    assert second_packet.json()["openPositions"] == []
