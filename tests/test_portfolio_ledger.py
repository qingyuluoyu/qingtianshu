from __future__ import annotations

from decimal import Decimal

import pytest

from app.db import Database
from app.services.portfolio_ledger import (
    IdempotencyConflict,
    InvalidTrade,
    PortfolioLedger,
    PositionNotFound,
    VersionConflict,
)


def _ledger(tmp_path):
    database = Database(tmp_path / "app.db", tmp_path / "workspaces")
    database.initialize()
    user = database.create_user("portfolio owner")
    return database, user, PortfolioLedger(database)


def test_create_position_records_initial_buy_and_reuses_idempotency_key(tmp_path):
    database, user, ledger = _ledger(tmp_path)

    first = ledger.create_position(
        user_id=user["id"],
        symbol="300750",
        name="宁德时代",
        account_type="simulated",
        quantity="100",
        price="200",
        fee="5",
        executed_at="2026-07-25T10:00:00+08:00",
        current_price="210",
        data_as_of="2026-07-25T15:00:00+08:00",
        idempotency_key="create-catl-001",
    )
    second = ledger.create_position(
        user_id=user["id"],
        symbol="300750.SZ",
        name="宁德时代",
        account_type="simulated",
        quantity="100",
        price="200",
        fee="5",
        executed_at="2026-07-25T10:00:00+08:00",
        current_price="210",
        data_as_of="2026-07-25T15:00:00+08:00",
        idempotency_key="create-catl-001",
    )

    assert first["position"]["id"] == second["position"]["id"]
    assert first["trade"]["id"] == second["trade"]["id"]
    assert first["position"]["symbol"] == "300750.SZ"
    assert first["position"]["version"] == 1
    assert len(database.list_trades(user["id"])) == 1


def test_reusing_idempotency_key_with_different_payload_is_rejected(tmp_path):
    _, user, ledger = _ledger(tmp_path)
    payload = {
        "user_id": user["id"],
        "symbol": "300750.SZ",
        "name": "宁德时代",
        "account_type": "simulated",
        "quantity": "100",
        "price": "200",
        "fee": "5",
        "executed_at": "2026-07-25T10:00:00+08:00",
        "current_price": "210",
        "data_as_of": "2026-07-25T15:00:00+08:00",
        "idempotency_key": "create-catl-002",
    }
    ledger.create_position(**payload)

    with pytest.raises(IdempotencyConflict):
        ledger.create_position(**{**payload, "quantity": "101"})


def test_weighted_buy_partial_sell_and_full_close_have_correct_financial_semantics(
    tmp_path,
):
    _, user, ledger = _ledger(tmp_path)
    created = ledger.create_position(
        user_id=user["id"],
        symbol="000063.SZ",
        name="中兴通讯",
        account_type="live",
        quantity="100",
        price="20",
        fee="5",
        executed_at="2026-07-01T10:00:00+08:00",
        current_price="25",
        data_as_of="2026-07-25T15:00:00+08:00",
        idempotency_key="zte-open-001",
    )
    position_id = created["position"]["id"]

    bought = ledger.record_trade(
        user_id=user["id"],
        position_id=position_id,
        side="buy",
        quantity="100",
        price="30",
        fee="5",
        executed_at="2026-07-02T10:00:00+08:00",
        idempotency_key="zte-buy-002",
        base_version=1,
    )
    assert Decimal(bought["position"]["quantity"]) == Decimal("200")
    assert Decimal(bought["position"]["cost_price"]) == Decimal("25")
    assert bought["position"]["version"] == 2

    partial = ledger.record_trade(
        user_id=user["id"],
        position_id=position_id,
        side="sell",
        quantity="40",
        price="35",
        fee="3",
        executed_at="2026-07-03T10:00:00+08:00",
        idempotency_key="zte-sell-003",
        base_version=2,
    )
    assert Decimal(partial["position"]["quantity"]) == Decimal("160")
    assert Decimal(partial["trade"]["realized_pnl"]) == Decimal("400")
    assert partial["trade"]["position_closed"] is False
    assert partial["position"]["status"] == "open"

    closed = ledger.record_trade(
        user_id=user["id"],
        position_id=position_id,
        side="sell",
        quantity="160",
        price="20",
        fee="4",
        executed_at="2026-07-04T10:00:00+08:00",
        idempotency_key="zte-sell-004",
        base_version=3,
    )
    assert Decimal(closed["position"]["quantity"]) == Decimal("0")
    assert Decimal(closed["trade"]["realized_pnl"]) == Decimal("-800")
    assert closed["trade"]["position_closed"] is True
    assert closed["position"]["status"] == "closed"
    assert closed["position"]["version"] == 4


def test_ledger_rejects_oversell_stale_version_and_cross_user_position(tmp_path):
    database, user, ledger = _ledger(tmp_path)
    other = database.create_user("other")
    created = ledger.create_position(
        user_id=user["id"],
        symbol="600519.SS",
        name="贵州茅台",
        account_type="simulated",
        quantity="10",
        price="1500",
        fee="5",
        executed_at="2026-07-01T10:00:00+08:00",
        current_price=None,
        data_as_of=None,
        idempotency_key="moutai-open-001",
    )
    position_id = created["position"]["id"]

    with pytest.raises(InvalidTrade):
        ledger.record_trade(
            user_id=user["id"],
            position_id=position_id,
            side="sell",
            quantity="11",
            price="1510",
            fee="5",
            executed_at="2026-07-02T10:00:00+08:00",
            idempotency_key="moutai-sell-too-much",
            base_version=1,
        )

    with pytest.raises(VersionConflict):
        ledger.record_trade(
            user_id=user["id"],
            position_id=position_id,
            side="buy",
            quantity="1",
            price="1510",
            fee="1",
            executed_at="2026-07-02T10:00:00+08:00",
            idempotency_key="moutai-stale-version",
            base_version=99,
        )

    with pytest.raises(PositionNotFound):
        ledger.record_trade(
            user_id=other["id"],
            position_id=position_id,
            side="buy",
            quantity="1",
            price="1510",
            fee="1",
            executed_at="2026-07-02T10:00:00+08:00",
            idempotency_key="moutai-cross-user",
            base_version=1,
        )


def test_ledger_rejects_non_a_share_symbol(tmp_path):
    _, user, ledger = _ledger(tmp_path)

    with pytest.raises(InvalidTrade):
        ledger.create_position(
            user_id=user["id"],
            symbol="NVDA",
            name="NVIDIA",
            account_type="simulated",
            quantity="1",
            price="100",
            fee="0",
            executed_at="2026-07-01T10:00:00+08:00",
            current_price=None,
            data_as_of=None,
            idempotency_key="reject-us-stock",
        )
