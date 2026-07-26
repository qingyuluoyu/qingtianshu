from __future__ import annotations

from collections.abc import Callable
from threading import Event, Thread
import time
from typing import Any

from app.db import Database
from app.services.research_queue import ResearchQueue


class RecoverableResearchError(RuntimeError):
    """A transient failure that can be retried within the task attempt budget."""


class ResearchWorker:
    STREAM_NAME = "qingshu:research"
    GROUP_NAME = "qingshu-research-workers"

    def __init__(
        self,
        database: Database,
        queue: ResearchQueue,
        redis_client: Any,
        worker_id: str,
        handler: Callable[[dict[str, Any]], None],
        retry_base_seconds: int = 5,
        retry_max_seconds: int = 300,
        lease_seconds: int = 300,
        heartbeat_interval_seconds: int = 60,
        poll_callback: Callable[[], None] | None = None,
    ) -> None:
        self.database = database
        self.queue = queue
        self.redis_client = redis_client
        self.worker_id = worker_id
        self.handler = handler
        self.retry_base_seconds = max(0, retry_base_seconds)
        self.retry_max_seconds = max(self.retry_base_seconds, retry_max_seconds)
        self.lease_seconds = max(1, lease_seconds)
        self.heartbeat_interval_seconds = max(1, heartbeat_interval_seconds)
        self.poll_callback = poll_callback

    def run_once(self) -> int:
        self.database.expire_timed_out_research_tasks()
        self.database.reclaim_expired_research_tasks()
        self.queue.publish_pending()
        try:
            self.redis_client.xgroup_create(
                self.STREAM_NAME, self.GROUP_NAME, id="0", mkstream=True
            )
        except Exception:
            pass
        records = self.redis_client.xreadgroup(
            self.GROUP_NAME,
            self.worker_id,
            {self.STREAM_NAME: ">"},
            count=1,
            block=1,
        )
        processed = 0
        for stream_name, messages in records or []:
            for message_id, fields in messages:
                task_id = str(fields.get("task_id") or "")
                task = self.database.claim_research_task(
                    task_id, self.worker_id, self.lease_seconds
                )
                if task is None:
                    self.redis_client.xack(stream_name, self.GROUP_NAME, message_id)
                    continue
                if self.database.is_research_task_cancel_requested(task_id):
                    self.database.finish_research_task(task_id, "cancelled")
                    self.redis_client.xack(stream_name, self.GROUP_NAME, message_id)
                    processed += 1
                    continue
                heartbeat_stop = Event()

                def heartbeat() -> None:
                    while not heartbeat_stop.wait(self.heartbeat_interval_seconds):
                        if not self.database.heartbeat_research_task(
                            task_id, self.worker_id, self.lease_seconds
                        ):
                            return

                heartbeat_thread = Thread(target=heartbeat, daemon=True)
                heartbeat_thread.start()
                try:
                    self.handler(task)
                except RecoverableResearchError as exc:
                    exponent = max(0, int(task["attempt_count"]) - 1)
                    delay_seconds = min(
                        self.retry_max_seconds,
                        self.retry_base_seconds * (2**exponent),
                    )
                    self.database.retry_research_task(
                        task_id, str(exc) or type(exc).__name__, delay_seconds
                    )
                except Exception as exc:
                    self.database.finish_research_task(
                        task_id, "failed", str(exc) or type(exc).__name__
                    )
                else:
                    if self.database.is_research_task_cancel_requested(task_id):
                        self.database.finish_research_task(task_id, "cancelled")
                    else:
                        self.database.finish_research_task(task_id, "completed")
                finally:
                    heartbeat_stop.set()
                    heartbeat_thread.join(timeout=1)
                self.redis_client.xack(stream_name, self.GROUP_NAME, message_id)
                processed += 1
        return processed

    def run_forever(self, *, idle_sleep_seconds: float = 0.1) -> None:
        while True:
            processed = self.run_once()
            if self.poll_callback is not None:
                self.poll_callback()
            if processed == 0 and idle_sleep_seconds > 0:
                time.sleep(idle_sleep_seconds)
