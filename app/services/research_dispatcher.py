from __future__ import annotations

import hashlib
import json
from typing import Any

from app.db import Database


class ResearchDispatcher:
    """Persist a research request before asking a worker to execute it."""

    def __init__(
        self,
        database: Database,
        queue: Any,
        max_concurrent_per_user: int = 2,
        task_timeout_seconds: int = 900,
        task_budget_usd: float | None = None,
    ) -> None:
        self.database = database
        self.queue = queue
        self.max_concurrent_per_user = max(1, max_concurrent_per_user)
        self.task_timeout_seconds = max(1, task_timeout_seconds)
        self.task_budget_usd = task_budget_usd

    def submit(
        self,
        *,
        user_id: str,
        conversation_id: str,
        targets: list[dict[str, str]],
        question: str,
        idempotency_key: str,
        request_id: str | None = None,
        trace_id: str | None = None,
        workflow: str = "lao_li_diagnosis_v1",
        snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        user = self.database.get_user(user_id)
        if user is None:
            raise ValueError("research user does not exist")
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "conversation_id": conversation_id,
                    "targets": targets,
                    "question": question.strip(),
                    "workflow": workflow,
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        dimension_keys = (
            ("fundamental", "industry", "valuation", "technical", "risk")
            if workflow == "five_dimension_v7"
            else ("financial", "market", "industry", "event", "risk")
        )
        dimensions = {
            key: {"key": key, "status": "idle", "result": None, "error": None}
            for key in dimension_keys
        }
        run, duplicate = self.database.create_ai_research_submission(
            user_id=user_id,
            conversation_id=conversation_id,
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
            targets=targets,
            question=question,
            snapshot=snapshot or {},
            dimensions=dimensions,
            workspace_path=user["workspace_path"],
            max_concurrent_per_user=self.max_concurrent_per_user,
            request_id=request_id,
            trace_id=trace_id,
            timeout_seconds=self.task_timeout_seconds,
            budget_limit_usd=self.task_budget_usd,
            workflow=workflow,
        )
        if not duplicate:
            self.queue.publish_pending(limit=1)
        return run
