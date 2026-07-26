from __future__ import annotations

from collections.abc import Callable
import time
from typing import Any

from redis.exceptions import RedisError

from app.db import Database


class RecoverableDataRefreshError(RuntimeError):
    """A temporary provider or infrastructure failure."""


class DataRefreshQueue:
    STREAM_NAME = "qingshu:data-refresh"

    def __init__(self, database: Database, redis_client: Any) -> None:
        self.database = database
        self.redis_client = redis_client

    def publish_pending(self, limit: int = 100) -> int:
        published = 0
        for item in self.database.list_pending_data_refresh_outbox(limit):
            try:
                self.redis_client.xadd(
                    self.STREAM_NAME, {"task_id": str(item["task_id"])}
                )
            except (RedisError, ConnectionError, OSError, TimeoutError) as exc:
                self.database.record_data_refresh_outbox_failure(
                    str(item["outbox_id"]), type(exc).__name__
                )
                continue
            self.database.mark_data_refresh_outbox_published(
                str(item["outbox_id"])
            )
            published += 1
        return published


class DataRefreshWorker:
    GROUP_NAME = "qingshu-data-refresh-workers"

    def __init__(
        self,
        database: Database,
        queue: DataRefreshQueue,
        redis_client: Any,
        worker_id: str,
        handler: Callable[[dict[str, Any]], None],
        *,
        retry_base_seconds: int = 5,
        retry_max_seconds: int = 300,
        lease_seconds: int = 300,
    ) -> None:
        self.database = database
        self.queue = queue
        self.redis_client = redis_client
        self.worker_id = worker_id
        self.handler = handler
        self.retry_base_seconds = max(0, retry_base_seconds)
        self.retry_max_seconds = max(self.retry_base_seconds, retry_max_seconds)
        self.lease_seconds = max(1, lease_seconds)

    def run_once(self) -> int:
        self.database.reclaim_expired_data_refresh_tasks()
        self.queue.publish_pending()
        try:
            self.redis_client.xgroup_create(
                self.queue.STREAM_NAME, self.GROUP_NAME, id="0", mkstream=True
            )
        except Exception:
            pass
        records = self.redis_client.xreadgroup(
            self.GROUP_NAME,
            self.worker_id,
            {self.queue.STREAM_NAME: ">"},
            count=1,
            block=1,
        )
        processed = 0
        for stream_name, messages in records or []:
            for message_id, fields in messages:
                task_id = str(fields.get("task_id") or "")
                task = self.database.claim_data_refresh_task(
                    task_id, self.worker_id, self.lease_seconds
                )
                if task is None:
                    self.redis_client.xack(
                        stream_name, self.GROUP_NAME, message_id
                    )
                    continue
                try:
                    self.handler(task)
                except RecoverableDataRefreshError as exc:
                    exponent = max(0, int(task["attempt_count"]) - 1)
                    delay = min(
                        self.retry_max_seconds,
                        self.retry_base_seconds * (2**exponent),
                    )
                    self.database.retry_data_refresh_task(
                        task_id, type(exc).__name__, str(exc), delay
                    )
                except Exception as exc:
                    self.database.finish_data_refresh_task(
                        task_id, "failed", type(exc).__name__, str(exc)
                    )
                else:
                    self.database.finish_data_refresh_task(task_id, "completed")
                self.redis_client.xack(
                    stream_name, self.GROUP_NAME, message_id
                )
                processed += 1
        return processed

    def run_forever(self, *, idle_sleep_seconds: float = 0.1) -> None:
        while True:
            if self.run_once() == 0 and idle_sleep_seconds > 0:
                time.sleep(idle_sleep_seconds)
