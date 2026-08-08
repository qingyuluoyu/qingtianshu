from __future__ import annotations

from fastapi.testclient import TestClient


def test_stock_page_requires_session(app):
    with TestClient(app) as anonymous:
        response = anonymous.get("/v1/stocks/000063/page")

    assert response.status_code == 401


def test_stock_page_aggregates_user_workspace_and_financial_modules(client):
    assert client.post("/users", json={"name": "stock-page-user"}).status_code == 201
    response = client.get("/v1/stocks/000063/page?range=1y")

    assert response.status_code == 200
    payload = response.json()
    assert payload["contract_version"] == "stock_page_v1"
    assert payload["symbol"] == "000063.SZ"
    assert payload["status"] == "ready"
    assert payload["summary"] == {
        "total": 9,
        "available": 9,
        "failed": 0,
        "required_failed": [],
    }
    assert payload["modules"]["workspace"]["data"]["symbol"] == "000063.SZ"
    assert payload["modules"]["history"]["data"]["coverage"]["points"] == 100
    assert payload["modules"]["fundamentals"]["status"] == "available"


def test_stock_page_keeps_other_modules_when_one_optional_module_fails(
    app, client, monkeypatch
):
    assert (
        client.post("/users", json={"name": "partial-stock-page-user"}).status_code
        == 201
    )

    def unavailable(_: str):
        raise RuntimeError("private provider detail")

    monkeypatch.setattr(app.state.shareholders, "get_packet", unavailable)

    response = client.get("/v1/stocks/000063/page")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "partial"
    assert payload["summary"]["required_failed"] == []
    assert payload["modules"]["workspace"]["status"] == "available"
    assert payload["modules"]["history"]["status"] == "available"
    shareholder_module = payload["modules"]["shareholders"]
    assert shareholder_module["status"] == "unavailable"
    assert shareholder_module["data"] is None
    assert "private provider detail" not in str(shareholder_module)


def test_stock_page_refreshes_fundamentals_once(app, client, monkeypatch):
    assert client.post("/users", json={"name": "single-refresh-user"}).status_code == 201
    original = app.state.fundamentals.get_packet
    calls: list[str] = []

    def counted(symbol: str):
        calls.append(symbol)
        return original(symbol)

    monkeypatch.setattr(app.state.fundamentals, "get_packet", counted)

    response = client.get("/v1/stocks/000063/page")

    assert response.status_code == 200
    assert calls == ["000063.SZ"]
