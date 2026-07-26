from __future__ import annotations

import time
from typing import Any

from app.services.agent_stream import AgentStreamBroker
from app.services.background import EventBroker
from app.utils import utc_now


class ChatStreamPublisher:
    """Publish one chat request's progress and private streaming protocol."""

    _PROGRESS_LABELS = {
        "model_started": "证据与资料已准备，AI 正在生成回答…",
        "guard_started": "回答已生成，正在校验数字、来源与证据边界…",
        "fallback_started": "正在整理当前可确认的证据摘要…",
        "completed": "校验完成，正在保存回答与研究记录…",
    }

    def __init__(
        self,
        *,
        event_broker: EventBroker,
        agent_streams: AgentStreamBroker,
        request_id: str | None,
        user_id: str,
        execute_agent: bool,
        started_at: float,
    ) -> None:
        self.event_broker = event_broker
        self.agent_streams = agent_streams
        self.request_id = request_id
        self.user_id = user_id
        self.execute_agent = execute_agent
        self.started_at = started_at

    @property
    def enabled(self) -> bool:
        return bool(self.request_id and self.execute_agent)

    def progress(self, phase: str, label: str, **details: Any) -> None:
        if not self.enabled or self.request_id is None:
            return
        event = {
            "type": "agent_progress",
            "request_id": self.request_id,
            "phase": phase,
            "label": label,
            "elapsed_seconds": round(time.perf_counter() - self.started_at, 3),
            "time": utc_now(),
            **details,
        }
        self.event_broker.publish(event)
        self.agent_streams.publish(self.request_id, self.user_id, event)

    def forward_agent_progress(self, update: dict[str, Any]) -> None:
        phase = str(update.get("phase") or "")
        label = self._PROGRESS_LABELS.get(phase)
        if label is None:
            return
        self.progress(
            phase,
            label,
            timings={key: value for key, value in update.items() if key != "phase"},
        )

    def forward_agent_stream(self, update: dict[str, Any]) -> None:
        if not self.enabled or self.request_id is None:
            return
        event_type = str(update.get("type") or "")
        if event_type == "delta":
            self.agent_streams.publish(
                self.request_id,
                self.user_id,
                {
                    "type": "agent_delta",
                    "draft": str(update.get("draft") or ""),
                    "elapsed_seconds": update.get("elapsed_seconds"),
                    "event_index": update.get("event_index"),
                    "withheld_segments": update.get("withheld_segments", 0),
                    "is_unverified": update.get("is_unverified", True),
                    "is_final": update.get("is_final", False),
                },
            )
        elif event_type == "reset":
            self.agent_streams.publish(
                self.request_id,
                self.user_id,
                {
                    "type": "agent_stream_status",
                    "label": str(
                        update.get("label")
                        or "实时生成连接已中断，正在恢复完整回答…"
                    ),
                },
            )

    def publish_structured(
        self,
        structured_answer: dict[str, Any] | None,
        *,
        failed: bool,
    ) -> None:
        if not self.enabled or self.request_id is None:
            return
        if structured_answer:
            for citation in structured_answer.get("citations") or []:
                self.agent_streams.publish(
                    self.request_id,
                    self.user_id,
                    {"type": "agent_citation", "citation": citation},
                )
            for candidate in structured_answer.get("candidate_writebacks") or []:
                self.agent_streams.publish(
                    self.request_id,
                    self.user_id,
                    {
                        "type": "agent_writeback_candidate",
                        "candidate": candidate,
                    },
                )
            if structured_answer.get("status") != "complete":
                self.agent_streams.publish(
                    self.request_id,
                    self.user_id,
                    {
                        "type": "agent_structured_partial",
                        "status": structured_answer.get("status"),
                    },
                )
        elif failed:
            self.agent_streams.publish(
                self.request_id,
                self.user_id,
                {"type": "agent_structured_failed", "status": "failed"},
            )

    def complete(self, *, status: str, run_id: str) -> None:
        if not self.enabled or self.request_id is None:
            return
        self.agent_streams.publish(
            self.request_id,
            self.user_id,
            {
                "type": "agent_stream_complete",
                "status": status,
                "run_id": run_id,
            },
        )


__all__ = ("ChatStreamPublisher",)
