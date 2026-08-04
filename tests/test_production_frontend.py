from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import app.frontend as frontend_contract
from app.frontend import react_asset
from app.main import create_app


ROOT = Path(__file__).resolve().parents[1]


def _production_client(settings, tmp_path: Path) -> TestClient:
    dist = tmp_path / "frontend-dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text(
        '<!doctype html><html><body><div id="root"></div>'
        '<script type="module" src="/assets/app-test.js"></script></body></html>',
        encoding="utf-8",
    )
    (assets / "app-test.js").write_text("window.__QINGSHU_REACT__ = true;", encoding="utf-8")
    return TestClient(create_app(replace(settings, frontend_dist_dir=dist)))


def test_formal_routes_and_unknown_pages_return_react_spa(settings, tmp_path):
    client = _production_client(settings, tmp_path)

    for path in (
        "/today",
        "/screening",
        "/watchlist",
        "/stocks/600519.SS",
        "/advisor",
        "/advisor/conversation-1",
        "/research-center",
    ):
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.headers["content-type"].startswith("text/html"), path
        assert 'src="/assets/app-test.js"' in response.text, path
        assert response.headers["cache-control"] == "no-cache, no-store, must-revalidate"

    unknown = client.get("/not-a-real-page", headers={"accept": "text/html"})
    assert unknown.status_code == 200
    assert 'src="/assets/app-test.js"' in unknown.text


def test_spa_index_has_minimum_security_headers(settings, tmp_path):
    client = _production_client(settings, tmp_path)

    response = client.get("/today")

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert response.headers["x-frame-options"] == "DENY"


def test_react_assets_are_served_with_immutable_cache(settings, tmp_path):
    client = _production_client(settings, tmp_path)

    response = client.get("/assets/app-test.js")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/javascript")
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "__QINGSHU_REACT__" in response.text
    assert client.get("/assets/missing.js").status_code == 404


def test_react_asset_path_cannot_escape_dist_assets(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("not an asset", encoding="utf-8")

    with pytest.raises(HTTPException) as error:
        react_asset(dist, "../index.html")

    assert getattr(error.value, "status_code", None) == 404


def test_legacy_frontend_is_confined_to_legacy_paths(settings, tmp_path):
    client = _production_client(settings, tmp_path)

    legacy = client.get("/legacy")
    nested = client.get("/legacy/watchlist")
    advisor_lab = client.get("/legacy/advisor-lab")
    demo = client.get("/demo", follow_redirects=False)
    old_lab = client.get("/advisor-lab", follow_redirects=False)

    assert legacy.status_code == 200
    assert nested.status_code == 200
    assert "demo-boot.js" in legacy.text
    assert "demo-boot.js" in nested.text
    assert advisor_lab.status_code == 200
    assert "advisor-lab" in advisor_lab.text
    assert demo.status_code in {302, 307}
    assert demo.headers["location"] == "/legacy"
    assert old_lab.status_code in {302, 307}
    assert old_lab.headers["location"] == "/legacy/advisor-lab"


def test_api_paths_are_never_swallowed_by_spa_fallback(settings, tmp_path):
    client = _production_client(settings, tmp_path)

    cases = (
        ("get", "/auth/not-a-route"),
        ("get", "/session/not-a-route"),
        ("get", "/v1/not-a-route"),
        ("get", "/me/not-a-route"),
        ("get", "/events/not-a-route"),
        ("get", "/research-reports/not-a-route/extra"),
        ("get", "/openapi.json/not-a-route"),
        ("get", "/health/not-a-route"),
        ("get", "/docs/not-a-route"),
    )
    for method, path in cases:
        response = client.request(method, path)
        assert response.status_code >= 400, path
        assert response.headers["content-type"].startswith("application/json"), path
        assert "app-test.js" not in response.text, path

    assert any(
        getattr(route, "path", None) == "/stocks/{symbol}/history"
        and "GET" in getattr(route, "methods", set())
        for route in client.app.routes
    )
    overview = client.get("/v1/today/overview")
    assert overview.status_code == 401
    assert overview.headers["content-type"].startswith("application/json")


def test_registered_backend_routes_drive_spa_protection(settings, tmp_path):
    client = _production_client(settings, tmp_path)
    build_prefixes = getattr(frontend_contract, "registered_backend_prefixes", None)
    assert callable(build_prefixes), "backend protection must be derived from app.routes"

    prefixes = build_prefixes(client.app.routes)
    fallback_index = next(
        index
        for index, route in enumerate(client.app.routes)
        if getattr(route, "name", None) == "react_router_fallback"
    )
    backend_routes = [
        (index, route)
        for index, route in enumerate(client.app.routes)
        if getattr(route, "path", "").startswith("/")
        and getattr(route, "name", None) not in {"react_page", "react_router_fallback"}
        and getattr(route, "methods", None)
    ]

    assert backend_routes
    assert all(index < fallback_index for index, _ in backend_routes)
    for _, route in backend_routes:
        first = next(
            (part for part in route.path.split("/") if part and not part.startswith("{")),
            None,
        )
        if first:
            assert f"/{first}" in prefixes, route.path


def test_every_registered_backend_prefix_rejects_html_fallback(settings, tmp_path):
    client = _production_client(settings, tmp_path)
    build_prefixes = getattr(frontend_contract, "registered_backend_prefixes", None)
    allows_spa = getattr(frontend_contract, "should_serve_spa", None)
    assert callable(build_prefixes)
    assert callable(allows_spa)

    prefixes = build_prefixes(client.app.routes)
    for prefix in prefixes:
        assert not allows_spa(
            method="GET",
            path=f"{prefix}/__missing_spa_contract__",
            accept="text/html",
            backend_prefixes=prefixes,
        ), prefix


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_unknown_mutations_return_json_404(settings, tmp_path, method):
    client = _production_client(settings, tmp_path)

    response = client.request(
        method,
        "/not-a-real-page",
        headers={"accept": "text/html", "content-type": "application/json"},
        json={},
    )

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert "app-test.js" not in response.text


@pytest.mark.parametrize(
    "path,accept",
    [
        ("/not-a-real-api", "application/json"),
        ("/api-future/unknown", "text/html"),
        ("/missing.js", "text/html"),
        ("/missing.css", "text/html"),
        ("/missing.png", "text/html"),
        ("/missing.woff2", "text/html"),
        ("/assets/missing.js", "text/html"),
    ],
)
def test_non_page_fallback_requests_return_json_404(settings, tmp_path, path, accept):
    client = _production_client(settings, tmp_path)

    response = client.get(path, headers={"accept": accept})

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert "app-test.js" not in response.text


def test_html_head_can_use_spa_fallback(settings, tmp_path):
    client = _production_client(settings, tmp_path)

    response = client.head("/not-a-real-page", headers={"accept": "text/html"})

    assert response.status_code == 200
    assert response.text == ""


@pytest.mark.parametrize(
    "path",
    [
        "/today",
        "/screening",
        "/watchlist",
        "/advisor/conversation-1",
        "/research-center",
        "/not-a-real-page",
    ],
)
def test_react_page_paths_are_not_classified_as_backend(path):
    allows_spa = getattr(frontend_contract, "should_serve_spa", None)
    assert callable(allows_spa)
    assert allows_spa(
        method="GET",
        path=path,
        accept="text/html",
        backend_prefixes=frozenset(),
    )


def test_missing_react_build_fails_closed_instead_of_serving_legacy(settings, tmp_path):
    missing = tmp_path / "missing-dist"
    client = TestClient(create_app(replace(settings, frontend_dist_dir=missing)))

    response = client.get("/today")

    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["detail"] == "React frontend build is unavailable"
    assert client.get("/legacy").status_code == 200


def test_checked_in_openapi_snapshot_matches_backend_contract(settings, tmp_path):
    client = _production_client(settings, tmp_path)
    snapshot = json.loads(
        (ROOT / "frontend" / "openapi.json").read_text(encoding="utf-8")
    )

    assert snapshot == client.app.openapi()
