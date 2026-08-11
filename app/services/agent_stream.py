from __future__ import annotations

from dataclasses import dataclass, field
import json
from queue import Empty, Full, Queue
import threading
import time
from typing import Any, Iterator

from app.utils import utc_now


_TERMINAL_TYPES = {"agent_stream_complete", "agent_stream_error"}


@dataclass
class _RequestStream:
    user_id: str
    subscribers: set[Queue[dict[str, Any]]] = field(default_factory=set)
    latest_draft: dict[str, Any] | None = None
    latest_status: dict[str, Any] | None = None
    latest_structured: list[dict[str, Any]] = field(default_factory=list)
    terminal: bool = False
    updated_at: float = field(default_factory=time.monotonic)


class AgentStreamBroker:
    """Private, resumable per-request event streams for Agent draft text."""

    def __init__(self, ttl_seconds: int = 300):
        self.ttl_seconds = ttl_seconds
        self._requests: dict[str, _RequestStream] = {}
        self._lock = threading.Lock()

    def open(self, request_id: str, user_id: str) -> None:
        with self._lock:
            self._prune_locked()
            state = self._requests.get(request_id)
            if state is None:
                self._requests[request_id] = _RequestStream(user_id=user_id)
                return
            if state.user_id != user_id:
                raise PermissionError("Agent stream does not belong to this user")
            state.updated_at = time.monotonic()

    def publish(
        self, request_id: str, user_id: str, event: dict[str, Any]
    ) -> None:
        with self._lock:
            self._prune_locked()
            state = self._requests.get(request_id)
            if state is None:
                state = _RequestStream(user_id=user_id)
                self._requests[request_id] = state
            if state.user_id != user_id:
                raise PermissionError("Agent stream does not belong to this user")
            payload = {**event, "request_id": request_id, "time": utc_now()}
            if payload.get("type") == "agent_delta":
                state.latest_draft = payload
            elif payload.get("type") in {
                "agent_citation",
                "agent_writeback_candidate",
                "agent_structured_partial",
                "agent_structured_failed",
            }:
                state.latest_structured.append(payload)
                state.latest_structured = state.latest_structured[-20:]
            else:
                state.latest_status = payload
            if payload.get("type") in _TERMINAL_TYPES:
                state.terminal = True
            state.updated_at = time.monotonic()
            subscribers = list(state.subscribers)
        for subscriber in subscribers:
            self._put_latest(subscriber, payload)

    def stream(self, request_id: str, user_id: str) -> Iterator[str]:
        subscriber: Queue[dict[str, Any]] = Queue(maxsize=20)
        with self._lock:
            state = self._requests.get(request_id)
            if state is None or state.user_id != user_id:
                raise PermissionError("Agent stream does not belong to this user")
            state.subscribers.add(subscriber)
            snapshots = [
                state.latest_draft,
                *state.latest_structured,
                state.latest_status,
            ]
            terminal = state.terminal
        try:
            yield self._encode({"type": "agent_stream_connected", "time": utc_now()})
            for event in snapshots:
                if event is not None:
                    yield self._encode(event)
            if terminal:
                return
            while True:
                try:
                    event = subscriber.get(timeout=15)
                    yield self._encode(event)
                    if event.get("type") in _TERMINAL_TYPES:
                        return
                except Empty:
                    yield ": heartbeat\n\n"
        finally:
            with self._lock:
                state = self._requests.get(request_id)
                if state is not None:
                    state.subscribers.discard(subscriber)

    def _prune_locked(self) -> None:
        cutoff = time.monotonic() - self.ttl_seconds
        expired = [
            request_id
            for request_id, state in self._requests.items()
            if state.updated_at < cutoff and not state.subscribers
        ]
        for request_id in expired:
            self._requests.pop(request_id, None)

    @staticmethod
    def _put_latest(
        subscriber: Queue[dict[str, Any]], event: dict[str, Any]
    ) -> None:
        try:
            subscriber.put_nowait(event)
        except Full:
            try:
                subscriber.get_nowait()
                subscriber.put_nowait(event)
            except (Empty, Full):
                return

    @staticmethod
    def _encode(event: dict[str, Any]) -> str:
        return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
