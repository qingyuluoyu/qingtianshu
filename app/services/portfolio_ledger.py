from __future__ import annotations

from decimal import Decimal, InvalidOperation
from hashlib import sha256
import re
from typing import Any

from app.catalog import normalize_symbol
from app.db import Database
from app.utils import json_dumps


METHOD_VERSION = "moving_weighted_average_v1"
_A_SHARE_SYMBOL = re.compile(r"^\d{6}\.(?:SS|SZ|BJ)$")


class PortfolioLedgerError(ValueError):
    pass


class InvalidTrade(PortfolioLedgerError):
    pass


class PositionNotFound(PortfolioLedgerError):
    pass


class VersionConflict(PortfolioLedgerError):
    pass


class IdempotencyConflict(PortfolioLedgerError):
    pass


def _decimal(value: Any, *, field: str, positive: bool = False) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise InvalidTrade(f"{field}格式无效") from exc
    if not result.is_finite():
        raise InvalidTrade(f"{field}格式无效")
    if positive and result <= 0:
        raise InvalidTrade(f"{field}必须大于0")
    if not positive and result < 0:
        raise InvalidTrade(f"{field}不得小于0")
    return result


def _text(value: Decimal) -> str:
    normalized = value.normalize()
    if normalized == normalized.to_integral():
        return str(normalized.quantize(Decimal("1")))
    return format(normalized, "f")


def _fingerprint(payload: dict[str, Any]) -> str:
    return sha256(json_dumps(payload).encode("utf-8")).hexdigest()


def _public_trade(item: dict[str, Any]) -> dict[str, Any]:
    return {**item, "position_closed": bool(item.get("position_closed"))}


class PortfolioLedger:
    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _a_share_symbol(symbol: str) -> str:
        try:
            canonical = normalize_symbol(symbol)
        except ValueError as exc:
            raise InvalidTrade(str(exc)) from exc
        if not _A_SHARE_SYMBOL.fullmatch(canonical):
            raise InvalidTrade("仅支持中国 A 股证券")
        return canonical

    def create_position(
        self,
        *,
        user_id: str,
        symbol: str,
        name: str | None,
        account_type: str,
        quantity: Any,
        price: Any,
        fee: Any,
        executed_at: str,
        current_price: Any | None,
        data_as_of: str | None,
        idempotency_key: str,
    ) -> dict[str, Any]:
        canonical = self._a_share_symbol(symbol)
        if account_type not in {"simulated", "live"}:
            raise InvalidTrade("持仓账户类型无效")
        quantity_value = _decimal(quantity, field="数量", positive=True)
        price_value = _decimal(price, field="成交价", positive=True)
        fee_value = _decimal(fee, field="交易费用")
        current_price_value = (
            _decimal(current_price, field="当前价", positive=True)
            if current_price is not None
            else None
        )
        normalized = {
            "operation": "create_position",
            "symbol": canonical,
            "account_type": account_type,
            "quantity": _text(quantity_value),
            "price": _text(price_value),
            "fee": _text(fee_value),
            "executed_at": str(executed_at),
            "current_price": (
                _text(current_price_value) if current_price_value is not None else None
            ),
            "data_as_of": data_as_of,
        }
        result = self.database.create_position_with_initial_trade(
            user_id=user_id,
            symbol=canonical,
            name=name,
            account_type=account_type,
            quantity=normalized["quantity"],
            price=normalized["price"],
            fee=normalized["fee"],
            executed_at=str(executed_at),
            current_price=normalized["current_price"],
            data_as_of=data_as_of,
            idempotency_key=idempotency_key,
            request_fingerprint=_fingerprint(normalized),
            method_version=METHOD_VERSION,
        )
        if result["status"] == "idempotency_conflict":
            raise IdempotencyConflict("幂等键已用于不同的持仓请求")
        return {
            "position": result["position"],
            "trade": _public_trade(result["trade"]),
            "reused": result["status"] == "reused",
        }

    def record_trade(
        self,
        *,
        user_id: str,
        position_id: str,
        side: str,
        quantity: Any,
        price: Any,
        fee: Any,
        executed_at: str,
        idempotency_key: str,
        base_version: int,
    ) -> dict[str, Any]:
        if side not in {"buy", "sell"}:
            raise InvalidTrade("成交方向无效")
        quantity_value = _decimal(quantity, field="数量", positive=True)
        price_value = _decimal(price, field="成交价", positive=True)
        fee_value = _decimal(fee, field="交易费用")
        normalized = {
            "operation": "record_trade",
            "position_id": position_id,
            "side": side,
            "quantity": _text(quantity_value),
            "price": _text(price_value),
            "fee": _text(fee_value),
            "executed_at": str(executed_at),
        }
        request_fingerprint = _fingerprint(normalized)
        existing = self.database.get_trade_by_idempotency(
            user_id, idempotency_key
        )
        if existing is not None:
            if existing.get("request_fingerprint") != request_fingerprint:
                raise IdempotencyConflict("幂等键已用于不同的成交请求")
            position = self.database.get_position(user_id, str(existing["position_id"]))
            if position is None:
                raise PositionNotFound("持仓不存在")
            return {
                "position": position,
                "trade": _public_trade(existing),
                "reused": True,
            }

        position = self.database.get_position(user_id, position_id)
        if position is None:
            raise PositionNotFound("持仓不存在")
        if int(position.get("version") or 1) != int(base_version):
            raise VersionConflict("持仓版本已变化，请刷新后重试")
        if position["status"] != "open":
            raise VersionConflict("已关闭持仓不能继续记录成交")

        old_quantity = _decimal(position["quantity"], field="持仓数量")
        old_cost = _decimal(position["cost_price"], field="持仓成本")
        if side == "buy":
            new_quantity = old_quantity + quantity_value
            new_cost = (
                old_quantity * old_cost + quantity_value * price_value
            ) / new_quantity
            realized_pnl = None
            position_closed = False
        else:
            if quantity_value > old_quantity:
                raise InvalidTrade("卖出数量不得超过当前持仓")
            new_quantity = old_quantity - quantity_value
            new_cost = old_cost
            realized_pnl = (price_value - old_cost) * quantity_value
            position_closed = new_quantity == 0

        result = self.database.append_position_trade_cas(
            user_id=user_id,
            position_id=position_id,
            symbol=str(position["symbol"]),
            side=side,
            quantity=normalized["quantity"],
            price=normalized["price"],
            fee=normalized["fee"],
            realized_pnl=(
                _text(realized_pnl) if realized_pnl is not None else None
            ),
            executed_at=str(executed_at),
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
            base_version=int(base_version),
            new_quantity=_text(new_quantity),
            new_cost_price=_text(new_cost),
            position_closed=position_closed,
        )
        if result["status"] == "not_found":
            raise PositionNotFound("持仓不存在")
        if result["status"] == "version_conflict":
            raise VersionConflict("持仓版本已变化，请刷新后重试")
        if result["status"] == "idempotency_conflict":
            raise IdempotencyConflict("幂等键已用于不同的成交请求")
        return {
            "position": result["position"],
            "trade": _public_trade(result["trade"]),
            "reused": result["status"] == "reused",
        }

    def list_positions(self, user_id: str) -> list[dict[str, Any]]:
        return self.database.list_positions(user_id)
