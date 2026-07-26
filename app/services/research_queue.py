from __future__ import annotations

from typing import Any

from redis.exceptions import RedisError

from app.db import Database


class ResearchQueue:
    """Redis Stream publisher backed by the durable database outbox."""

    def __init__(self, database: Database, redis_client: Any) -> None:
        self.database = database
        self.redis_client = redis_client

    def publish_pending(self, limit: int = 100) -> int:
        published = 0
        for item in self.database.list_pending_research_outbox(limit):
            try:
                self.redis_client.xadd(
                    str(item["stream_name"]), {"task_id": str(item["task_id"])}
                )
            except (RedisError, ConnectionError, OSError, TimeoutError) as exc:
                self.database.record_research_outbox_failure(
                    str(item["outbox_id"]), type(exc).__name__
                )
                continue
            self.database.mark_research_outbox_published(str(item["outbox_id"]))
            published += 1
        return published
