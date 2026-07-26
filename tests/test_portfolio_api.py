from __future__ import annotations

from fastapi.testclient import TestClient


def _login(client: TestClient, name: str = "portfolio api user") -> dict:
    response = client.post("/users", json={"name": name})
    assert response.status_code == 201
    return response.json()


def _watch_payload() -> dict:
    return {
        "symbol": "000063",
        "name": "中兴通讯",
        "priority": "high",
        "reason": "验证订单、利润和现金流能否同步改善",
        "catalyst_condition": "运营商资本开支上修",
        "invalidation_condition": "现金流持续背离利润",
        "tracking_frequency": "weekly",
        "tracking_status": "active",
    }


def _position_payload(key: str = "zte-position-001") -> dict:
    return {
        "symbol": "000063.SZ",
        "name": "中兴通讯",
        "account_type": "simulated",
        "quantity": "100",
        "price": "20",
        "fee": "5",
        "executed_at": "2026-07-01T10:00:00+08:00",
        "current_price": "25",
        "data_as_of": "2026-07-25T15:00:00+08:00",
        "idempotency_key": key,
    }


def test_watchlist_position_trade_and_review_form_a_real_vertical_slice(client):
    _login(client)

    watched = client.post("/api/v1/me/watchlist", json=_watch_payload())
    assert watched.status_code == 201
    assert watched.json()["symbol"] == "000063.SZ"
    assert watched.json()["position_status"] == "none"

    opened = client.post("/api/v1/me/positions", json=_position_payload())
    assert opened.status_code == 201
    position = opened.json()["position"]
    assert position["quantity"] == "100"
    assert position["version"] == 1

    watchlist = client.get("/api/v1/me/watchlist")
    assert watchlist.status_code == 200
    assert watchlist.json()["items"][0]["position_status"] == "open"

    partial = client.post(
        f"/api/v1/me/positions/{position['id']}/trades",
        json={
            "side": "sell",
            "quantity": "40",
            "price": "25",
            "fee": "2",
            "executed_at": "2026-07-02T10:00:00+08:00",
            "idempotency_key": "zte-sell-partial-001",
            "base_version": 1,
        },
    )
    assert partial.status_code == 201
    assert partial.json()["position"]["quantity"] == "60"
    assert partial.json()["trade"]["position_closed"] is False

    partial_review = client.get("/api/v1/me/trade-reviews")
    assert partial_review.status_code == 200
    assert partial_review.json()["summary"]["closedTradeCount"] == 0
    assert partial_review.json()["summary"]["realizedPnlCny"] == "200.00"
    assert partial_review.json()["summary"]["winRatePct"] is None
    assert [item["side"] for item in partial_review.json()["tradeHistory"]] == [
        "sell",
        "buy",
    ]

    closed = client.post(
        f"/api/v1/me/positions/{position['id']}/trades",
        json={
            "side": "sell",
            "quantity": "60",
            "price": "15",
            "fee": "3",
            "executed_at": "2026-07-03T10:00:00+08:00",
            "idempotency_key": "zte-sell-close-001",
            "base_version": 2,
        },
    )
    assert closed.status_code == 201
    assert closed.json()["position"]["status"] == "closed"
    assert closed.json()["trade"]["position_closed"] is True

    review = client.get("/api/v1/me/trade-reviews")
    assert review.status_code == 200
    assert review.json()["summary"] == {
        "closedTradeCount": 1,
        "openPositionCount": 0,
        "winningClosedTradeCount": 0,
        "losingClosedTradeCount": 1,
        "realizedPnlCny": "-100.00",
        "unrealizedPnlCny": "0.00",
        "feesCny": "10.00",
        "netPnlCny": "-110.00",
        "winRatePct": "0.00",
    }
    assert review.json()["methodVersion"] == "moving_weighted_average_v1"
    assert len(review.json()["tradeHistory"]) == 3
    assert client.get("/me/trade-reviews").json() == review.json()


def test_position_api_enforces_user_scope_version_oversell_and_a_share(app):
    owner = TestClient(app)
    other = TestClient(app)
    _login(owner, "owner")
    _login(other, "other")
    opened = owner.post("/api/v1/me/positions", json=_position_payload())
    position = opened.json()["position"]

    assert (
        other.get(f"/api/v1/me/positions/{position['id']}").status_code == 404
    )
    stale = owner.post(
        f"/api/v1/me/positions/{position['id']}/trades",
        json={
            "side": "buy",
            "quantity": "1",
            "price": "21",
            "fee": "0",
            "executed_at": "2026-07-02T10:00:00+08:00",
            "idempotency_key": "stale-version",
            "base_version": 99,
        },
    )
    assert stale.status_code == 409

    oversell = owner.post(
        f"/api/v1/me/positions/{position['id']}/trades",
        json={
            "side": "sell",
            "quantity": "101",
            "price": "21",
            "fee": "0",
            "executed_at": "2026-07-02T10:00:00+08:00",
            "idempotency_key": "oversell",
            "base_version": 1,
        },
    )
    assert oversell.status_code == 422

    unsupported = owner.post(
        "/api/v1/me/positions",
        json={**_position_payload("reject-us"), "symbol": "NVDA"},
    )
    assert unsupported.status_code == 422


def test_position_creation_and_trade_submission_are_idempotent(client):
    _login(client)
    first = client.post("/api/v1/me/positions", json=_position_payload())
    second = client.post("/api/v1/me/positions", json=_position_payload())
    assert first.status_code == second.status_code == 201
    assert first.json()["position"]["id"] == second.json()["position"]["id"]
    assert second.json()["reused"] is True

    position = first.json()["position"]
    trade_payload = {
        "side": "buy",
        "quantity": "10",
        "price": "30",
        "fee": "1",
        "executed_at": "2026-07-02T10:00:00+08:00",
        "idempotency_key": "repeat-buy",
        "base_version": 1,
    }
    trade_first = client.post(
        f"/api/v1/me/positions/{position['id']}/trades", json=trade_payload
    )
    trade_second = client.post(
        f"/api/v1/me/positions/{position['id']}/trades", json=trade_payload
    )
    assert trade_first.status_code == trade_second.status_code == 201
    assert trade_first.json()["trade"]["id"] == trade_second.json()["trade"]["id"]
    assert trade_second.json()["reused"] is True


def test_new_watchlist_contract_rejects_legacy_position_fields(client):
    _login(client)

    response = client.post(
        "/api/v1/me/watchlist",
        json={**_watch_payload(), "holding_quantity": 100, "purchase_price": "20"},
    )

    assert response.status_code == 422


def test_legacy_a_share_watchlist_is_backfilled_without_creating_a_position(client):
    _login(client)
    legacy = client.post(
        "/me/watchlist",
        json={
            "symbol": "600519",
            "name": "贵州茅台",
            "market": "A股",
            "thesis": "跟踪渠道库存和经营现金流",
            "focus_status": "holding",
            "purchase_price": "1400",
            "holding_quantity": 10,
        },
    )
    assert legacy.status_code == 200

    watchlist = client.get("/api/v1/me/watchlist").json()["items"]
    assert len(watchlist) == 1
    assert watchlist[0]["symbol"] == "600519.SS"
    assert watchlist[0]["reason"] == "跟踪渠道库存和经营现金流"
    assert watchlist[0]["position_status"] == "none"
    assert watchlist[0]["legacy_position_hint"] == {
        "psychological_price": None,
        "purchase_price": "1400",
        "holding_quantity": 10,
        "sell_price": None,
    }
    assert client.get("/api/v1/me/positions").json()["items"] == []


def test_portfolio_endpoints_require_session(client):
    assert client.get("/api/v1/me/positions").status_code == 401
    assert client.get("/api/v1/me/trade-reviews").status_code == 401
