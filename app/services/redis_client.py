from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.config import Settings


@dataclass(frozen=True)
class RedisClient:
    client: Any | None
    is_available: bool


def create_redis_client(settings: Settings) -> RedisClient:
    """Create the shared Redis client only when this runtime is configured for it."""
    if not settings.redis_url:
        return RedisClient(client=None, is_available=False)
    try:
        import redis
    except ImportError as exc:  # pragma: no cover - guarded by production dependency install
        raise RuntimeError("redis package is required when REDIS_URL is configured") from exc
    return RedisClient(
        client=redis.Redis.from_url(settings.redis_url, decode_responses=True),
        is_available=True,
    )
