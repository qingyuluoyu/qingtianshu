from __future__ import annotations

from collections import OrderedDict, deque
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import math
from threading import BoundedSemaphore, Lock
import time
from typing import Callable, Iterator


@dataclass(frozen=True)
class AuthRateLimitDecision:
    allowed: bool
    retry_after_seconds: int = 0


class AuthRateLimiter:
    """Bound per-process auth work without retaining raw login identifiers."""

    def __init__(
        self,
        *,
        per_source_limit: int,
        per_principal_limit: int,
        window_seconds: int,
        max_keys: int,
        password_hash_concurrency: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.per_source_limit = max(1, per_source_limit)
        self.per_principal_limit = max(1, per_principal_limit)
        self.window_seconds = max(1, window_seconds)
        self.max_keys = max(2, max_keys)
        self._clock = clock
        self._events: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = Lock()
        self._password_slots = BoundedSemaphore(max(1, password_hash_concurrency))

    def check(self, *, action: str, source: str, principal: str) -> AuthRateLimitDecision:
        now = self._clock()
        source_key = f"source:{action}:{source or 'unknown'}"
        principal_digest = hashlib.sha256(principal.casefold().encode("utf-8")).hexdigest()
        principal_key = f"principal:{action}:{principal_digest}"
        keys = (
            (source_key, self.per_source_limit),
            (principal_key, self.per_principal_limit),
        )
        with self._lock:
            self._make_capacity(now, {key for key, _ in keys})
            retry_after = 0
            for key, limit in keys:
                events = self._trimmed_events(key, now)
                if len(events) >= limit:
                    retry_after = max(
                        retry_after,
                        max(1, math.ceil(events[0] + self.window_seconds - now)),
                    )
            if retry_after:
                return AuthRateLimitDecision(False, retry_after)
            for key, _ in keys:
                events = self._events.setdefault(key, deque())
                events.append(now)
                self._events.move_to_end(key)
        return AuthRateLimitDecision(True)

    @contextmanager
    def password_slot(self) -> Iterator[bool]:
        acquired = self._password_slots.acquire(blocking=False)
        try:
            yield acquired
        finally:
            if acquired:
                self._password_slots.release()

    @property
    def key_count(self) -> int:
        with self._lock:
            return len(self._events)

    def _trimmed_events(self, key: str, now: float) -> deque[float]:
        events = self._events.setdefault(key, deque())
        cutoff = now - self.window_seconds
        while events and events[0] <= cutoff:
            events.popleft()
        self._events.move_to_end(key)
        return events

    def _make_capacity(self, now: float, requested_keys: set[str]) -> None:
        missing = sum(key not in self._events for key in requested_keys)
        if len(self._events) + missing <= self.max_keys:
            return
        cutoff = now - self.window_seconds
        for key in list(self._events):
            events = self._events[key]
            while events and events[0] <= cutoff:
                events.popleft()
            if not events and key not in requested_keys:
                del self._events[key]
        while len(self._events) + missing > self.max_keys:
            eviction_key = next(
                (key for key in self._events if key not in requested_keys),
                None,
            )
            if eviction_key is None:
                break
            del self._events[eviction_key]
