from __future__ import annotations

from fastapi.testclient import TestClient


def _create_user(client: TestClient, name: str) -> dict:
    response = client.post("/users", json={"name": name})
    assert response.status_code == 201
    return response.json()


def _add_stock(client: TestClient, symbol: str = "000063") -> None:
    response = client.post(
        "/me/watchlist",
        json={
            "symbol": symbol,
            "name": "中兴通讯",
            "market": "A股",
            "thesis": "核验订单、利润和经营现金流能否同步改善",
        },
    )
    assert response.status_code == 200


def _opening(
    client: TestClient,
    *,
    key: str = "opening-position-001",
    fees: str | None = "5",
) -> dict:
    response = client.post(
        "/v1/stocks/000063/position/opening",
        headers={"Idempotency-Key": key},
        json={
            "as_of_date": "2026-07-01",
            "quantity": "100",
            "cost_price": "10",
            "fees": fees,
            "note": "手工录入期初持仓",
        },
    )
    assert response.status_code == 201
    return response.json()


def _operation(
    client: TestClient,
    *,
    operation_type: str,
    operated_at: str,
    price: str,
    quantity: str,
    fees: str | None,
    key: str,
) -> dict:
    response = client.post(
        "/v1/stocks/000063/operations",
        headers={"Idempotency-Key": key},
        json={
            "operation_type": operation_type,
            "operated_at": operated_at,
            "price": price,
            "quantity": quantity,
            "fees": fees,
            "reason_text": "记录已发生的人工操作，不代表系统建议",
        },
    )
    assert response.status_code == 201
    return response.json()


def test_position_opening_is_unique_idempotent_and_enters_workspace(app):
    client = TestClient(app)
    _create_user(client, "Position Opening")
    _add_stock(client)

    empty = client.get("/v1/stocks/000063/position")
    assert empty.status_code == 200
    assert empty.json()["status"] == "not_configured"

    created = _opening(client)
    assert created["opening"]["quantity"] == "100.000000"
    assert created["current"]["quantity"] == "100.000000"
    assert created["current"]["cost_basis"] == "1005.0000"
    assert created["current"]["average_cost"] == "10.050000"
    assert created["current"]["realized_net_pnl"] == "0.0000"
    assert created["current"]["data_status"] == "complete"
    assert len(created["snapshots"]) == 1

    repeated = _opening(client)
    assert repeated["opening"]["id"] == created["opening"]["id"]
    assert len(repeated["snapshots"]) == 1

    duplicate = client.post(
        "/v1/stocks/000063/position/opening",
        headers={"Idempotency-Key": "opening-position-002"},
        json={
            "as_of_date": "2026-07-01",
            "quantity": "100",
            "cost_price": "10",
        },
    )
    assert duplicate.status_code == 409

    relation = client.get("/v1/stocks/000063/relation").json()
    assert relation["relation_type"] == "holding"
    workspace = client.get("/v1/stocks/000063/workspace").json()
    assert workspace["position_snapshot"]["available"] is True
    assert workspace["position_snapshot"]["current"]["quantity"] == "100.000000"
    assert workspace["completeness"]["has_position_opening"] is True


def test_moving_weighted_average_partial_sale_and_net_result(app):
    client = TestClient(app)
    _create_user(client, "Position Average")
    _add_stock(client)
    _opening(client)

    after_buy = _operation(
        client,
        operation_type="add",
        operated_at="2026-07-10T10:00:00+08:00",
        price="12",
        quantity="100",
        fees="5",
        key="position-add-001",
    )
    assert after_buy["current"]["quantity"] == "200.000000"
    assert after_buy["current"]["cost_basis"] == "2210.0000"
    assert after_buy["current"]["average_cost"] == "11.050000"

    repeated_buy = _operation(
        client,
        operation_type="add",
        operated_at="2026-07-10T10:00:00+08:00",
        price="12",
        quantity="100",
        fees="5",
        key="position-add-001",
    )
    assert len(repeated_buy["operations"]) == 1
    assert len(repeated_buy["snapshots"]) == 2

    after_sale = _operation(
        client,
        operation_type="reduce",
        operated_at="2026-07-15T14:30:00+08:00",
        price="15",
        quantity="50",
        fees="5",
        key="position-reduce-001",
    )
    assert after_sale["current"]["quantity"] == "150.000000"
    assert after_sale["current"]["cost_basis"] == "1657.5000"
    assert after_sale["current"]["average_cost"] == "11.050000"
    assert after_sale["current"]["realized_gross_pnl"] == "197.5000"
    assert after_sale["current"]["realized_net_pnl"] == "192.5000"
    assert after_sale["current"]["known_fees"] == "15.0000"
    assert len(after_sale["operations"]) == 2
    assert len(after_sale["snapshots"]) == 3


def test_missing_fees_never_become_precise_zero(app):
    client = TestClient(app)
    _create_user(client, "Position Missing Fees")
    _add_stock(client)
    opening = _opening(client, fees=None)

    assert opening["current"]["data_status"] == "partial"
    assert opening["current"]["realized_net_pnl"] is None
    assert opening["completeness"]["can_show_precise_net_result"] is False
    assert "费用尚未录入" in opening["current"]["warnings"][0]


def test_oversell_rolls_back_without_creating_operation_or_snapshot(app):
    client = TestClient(app)
    _create_user(client, "Position Oversell")
    _add_stock(client)
    _opening(client, fees="0")

    response = client.post(
        "/v1/stocks/000063/operations",
        headers={"Idempotency-Key": "position-oversell-001"},
        json={
            "operation_type": "sell",
            "operated_at": "2026-07-10T10:00:00+08:00",
            "price": "12",
            "quantity": "101",
            "fees": "1",
            "reason_text": "错误的超量卖出测试",
        },
    )
    assert response.status_code == 422
    assert "超过当时可用持仓" in response.json()["detail"]

    current = client.get("/v1/stocks/000063/position").json()
    assert current["operations"] == []
    assert len(current["snapshots"]) == 1
    assert current["current"]["quantity"] == "100.000000"


def test_operation_revision_preserves_original_and_recalculates(app):
    client = TestClient(app)
    _create_user(client, "Position Revision")
    _add_stock(client)
    _opening(client, fees="5")
    created = _operation(
        client,
        operation_type="add",
        operated_at="2026-07-10T10:00:00+08:00",
        price="12",
        quantity="100",
        fees="5",
        key="position-revision-source",
    )
    operation_id = created["operations"][0]["id"]

    revised = client.patch(
        f"/v1/operations/{operation_id}",
        headers={"Idempotency-Key": "position-revision-001"},
        json={
            "base_revision": 0,
            "price": "11",
            "quantity": "100",
            "fees": "5",
            "reason_text": "按成交回单修正录入价格",
        },
    )
    assert revised.status_code == 200
    payload = revised.json()
    assert payload["operations"][0]["price"] == "11.000000"
    assert payload["operations"][0]["current_revision"] == 1
    assert payload["operations"][0]["latest_revision"]["reason_text"] == (
        "按成交回单修正录入价格"
    )
    assert payload["current"]["cost_basis"] == "2110.0000"
    assert payload["current"]["average_cost"] == "10.550000"

    with app.state.database.connect() as connection:
        original = connection.execute(
            "SELECT price FROM position_operations WHERE id = ?", (operation_id,)
        ).fetchone()
    assert original["price"] == "12.000000"

    stale = client.patch(
        f"/v1/operations/{operation_id}",
        headers={"Idempotency-Key": "position-revision-002"},
        json={
            "base_revision": 0,
            "price": "10.5",
            "quantity": "100",
            "fees": "5",
            "reason_text": "基于旧版本再次修正",
        },
    )
    assert stale.status_code == 409


def test_adjustment_replays_cost_and_cross_user_access_is_hidden(app):
    owner = TestClient(app)
    _create_user(owner, "Position Owner")
    _add_stock(owner)
    _opening(owner, fees="0")

    adjusted = owner.post(
        "/v1/stocks/000063/position-adjustments",
        headers={"Idempotency-Key": "position-adjustment-001"},
        json={
            "adjustment_type": "corporate_action",
            "effective_at": "2026-07-20T09:00:00+08:00",
            "quantity_delta": "100",
            "cost_delta": "0",
            "reason_text": "手工确认送转后数量变化",
            "evidence_text": "公司公告链接由用户留存",
        },
    )
    assert adjusted.status_code == 201
    assert adjusted.json()["current"]["quantity"] == "200.000000"
    assert adjusted.json()["current"]["cost_basis"] == "1000.0000"
    assert adjusted.json()["current"]["average_cost"] == "5.000000"

    other = TestClient(app)
    _create_user(other, "Position Other")
    assert other.get("/v1/stocks/000063/position").status_code == 404
    operation_id = _operation(
        owner,
        operation_type="add",
        operated_at="2026-07-21T10:00:00+08:00",
        price="6",
        quantity="10",
        fees="1",
        key="position-owner-operation",
    )["operations"][0]["id"]
    forbidden = other.patch(
        f"/v1/operations/{operation_id}",
        headers={"Idempotency-Key": "position-other-revision"},
        json={
            "base_revision": 0,
            "price": "1",
            "quantity": "1",
            "fees": "0",
            "reason_text": "不应允许跨用户修正",
        },
    )
    assert forbidden.status_code == 404


def test_position_list_requires_session_and_starts_empty(app):
    client = TestClient(app)
    assert client.get("/v1/positions").status_code == 401

    _create_user(client, "Position List Empty")
    payload = client.get("/v1/positions").json()
    assert payload["contract_version"] == "position_ledger_v1"
    assert payload["status"] == "empty"
    assert payload["items"] == []
    assert payload["warnings"]


def test_position_list_matches_single_stock_snapshot_and_is_user_isolated(app):
    owner = TestClient(app)
    _create_user(owner, "Position List Owner")
    _add_stock(owner)

    # 仅关注未录持仓时不进入持仓列表。
    watching = owner.get("/v1/positions").json()
    assert watching["status"] == "empty"
    assert watching["items"] == []

    _opening(owner)
    payload = owner.get("/v1/positions").json()
    assert payload["status"] == "ready"
    assert payload["warnings"] == []
    assert "moving_weighted_average_v1" in payload["method"]
    assert "直通不缩放" in payload["method"]
    assert len(payload["items"]) == 1
    item = payload["items"][0]
    assert item["symbol"] == "000063.SZ"
    assert item["name"] == "中兴通讯"
    assert item["status"] == "ready"
    single = owner.get("/v1/stocks/000063/position").json()
    assert item["current"] == single["current"]
    # 数量与金额（元）直通锁：与单股端点同一快照、同一文本精度。
    assert item["current"]["quantity"] == "100.000000"
    assert item["current"]["cost_basis"] == "1005.0000"
    assert item["current"]["average_cost"] == "10.050000"

    other = TestClient(app)
    _create_user(other, "Position List Other")
    other_payload = other.get("/v1/positions").json()
    assert other_payload["status"] == "empty"
    assert other_payload["items"] == []
