from __future__ import annotations

import pytest

from app.config import Settings


def test_production_settings_require_secure_session_cookie(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRODUCTION_MODE", "true")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "false")

    with pytest.raises(ValueError, match="SESSION_COOKIE_SECURE"):
        Settings.from_env()


def test_production_settings_require_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRODUCTION_MODE", "true")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "true")
    monkeypatch.delenv("REDIS_URL", raising=False)

    with pytest.raises(ValueError, match="REDIS_URL"):
        Settings.from_env()


def test_readiness_checks_database_schema_and_local_redis_policy(client) -> None:
    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {"database": True, "schema": True, "redis": True},
    }
