from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from app.db import Database


MONEY = Decimal("0.01")


def _decimal(value: Any) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    return Decimal(str(value))


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY, rounding=ROUND_HALF_UP)


class TradeReviewService:
    """Deterministic trade review calculations; no model-generated finance math."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def summary(self, user_id: str) -> dict[str, Any]:
        positions = self.database.list_positions(user_id)
        trades = self.database.list_trades(user_id)
        open_positions = [item for item in positions if item["status"] == "open"]
        public_open_positions = []
        for item in open_positions:
            quantity = _decimal(item["quantity"])
            cost_price = _decimal(item["cost_price"])
            current_price = (
                _decimal(item["current_price"])
                if item.get("current_price") is not None
                else None
            )
            public_open_positions.append(
                {
                    **item,
                    "currentMarketValueCny": (
                        _money(current_price * quantity)
                        if current_price is not None
                        else None
                    ),
                    "unrealizedPnlCny": (
                        _money((current_price - cost_price) * quantity)
                        if current_price is not None
                        else None
                    ),
                }
            )
        realized_trades = [
            item
            for item in trades
            if item["side"] == "sell" and item.get("realized_pnl") is not None
        ]
        realized_by_position: dict[str, Decimal] = {}
        for item in realized_trades:
            position_id = str(item.get("position_id") or "")
            if position_id:
                realized_by_position[position_id] = (
                    realized_by_position.get(position_id, Decimal("0"))
                    + _decimal(item["realized_pnl"])
                )
        closed_trades = []
        for item in realized_trades:
            legacy_closed = item.get("position_id") is None
            if not bool(item.get("position_closed")) and not legacy_closed:
                continue
            position_id = str(item.get("position_id") or "")
            position_realized = (
                realized_by_position.get(position_id, _decimal(item["realized_pnl"]))
                if position_id
                else _decimal(item["realized_pnl"])
            )
            closed_trades.append(
                {
                    **item,
                    "position_closed": True,
                    "position_realized_pnl": _money(position_realized),
                }
            )
        realized = sum(
            (_decimal(item["realized_pnl"]) for item in realized_trades),
            Decimal("0"),
        )
        unrealized = sum(
            (
                (_decimal(item.get("current_price")) - _decimal(item["cost_price"]))
                * _decimal(item["quantity"])
                for item in open_positions
                if item.get("current_price") is not None
            ),
            Decimal("0"),
        )
        fees = sum((_decimal(item.get("fee")) for item in trades), Decimal("0"))
        winning = sum(
            1
            for item in closed_trades
            if _decimal(item["position_realized_pnl"]) > 0
        )
        losing = sum(
            1
            for item in closed_trades
            if _decimal(item["position_realized_pnl"]) < 0
        )
        closed_count = len(closed_trades)
        win_rate = (
            (Decimal(winning) / Decimal(closed_count) * Decimal("100")).quantize(
                MONEY, rounding=ROUND_HALF_UP
            )
            if closed_count
            else None
        )
        return {
            "methodVersion": "moving_weighted_average_v1",
            "tradeHistory": [
                {**item, "position_closed": bool(item.get("position_closed"))}
                for item in trades
            ],
            "closedTrades": closed_trades,
            "openPositions": public_open_positions,
            "summary": {
                "closedTradeCount": closed_count,
                "openPositionCount": len(open_positions),
                "winningClosedTradeCount": winning,
                "losingClosedTradeCount": losing,
                "realizedPnlCny": _money(realized),
                "unrealizedPnlCny": _money(unrealized),
                "feesCny": _money(fees),
                "netPnlCny": _money(realized + unrealized - fees),
                "winRatePct": win_rate,
            },
        }
