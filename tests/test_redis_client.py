from __future__ import annotations

from app.config import Settings


def test_redis_factory_returns_unavailable_client_without_url(monkeypatch) -> None:
    monkeypatch.delenv("REDIS_URL", raising=False)

    from app.services.redis_client import create_redis_client

    client = create_redis_client(Settings.from_env())

    assert client.is_available is False
    assert client.client is None
