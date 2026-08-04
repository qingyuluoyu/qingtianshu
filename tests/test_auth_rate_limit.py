from __future__ import annotations

import pytest

from app.auth_rate_limit import AuthRateLimiter


def _limiter(clock, **overrides) -> AuthRateLimiter:
    values = {
        "per_source_limit": 2,
        "per_principal_limit": 1,
        "window_seconds": 60,
        "max_keys": 4,
        "password_hash_concurrency": 1,
        "clock": clock,
    }
    values.update(overrides)
    return AuthRateLimiter(**values)


def test_source_and_principal_buckets_are_independent_and_expire():
    now = [0.0]
    limiter = _limiter(lambda: now[0])

    assert limiter.check(action="login", source="one", principal="alice").allowed
    assert not limiter.check(action="login", source="two", principal="alice").allowed
    assert limiter.check(action="login", source="one", principal="bob").allowed
    assert not limiter.check(action="login", source="one", principal="carol").allowed

    now[0] = 61.0
    assert limiter.check(action="login", source="one", principal="alice").allowed


def test_random_principals_cannot_grow_limiter_memory_without_bound():
    limiter = _limiter(
        lambda: 0.0,
        per_source_limit=100,
        per_principal_limit=100,
        max_keys=6,
    )

    for index in range(100):
        assert limiter.check(
            action="login", source=f"source-{index}", principal=f"principal-{index}"
        ).allowed
    assert limiter.key_count <= 6


def test_rotating_principals_cannot_evict_the_active_source_bucket():
    limiter = _limiter(
        lambda: 0.0,
        per_source_limit=2,
        per_principal_limit=100,
        max_keys=4,
    )

    assert limiter.check(action="login", source="one", principal="alice").allowed
    assert limiter.check(action="login", source="one", principal="bob").allowed
    assert not limiter.check(action="login", source="one", principal="carol").allowed


def test_password_slot_is_non_blocking_and_released_after_exception():
    limiter = _limiter(lambda: 0.0)

    with pytest.raises(RuntimeError):
        with limiter.password_slot() as first:
            assert first is True
            with limiter.password_slot() as second:
                assert second is False
            raise RuntimeError("simulated password verification failure")

    with limiter.password_slot() as acquired_after_failure:
        assert acquired_after_failure is True
