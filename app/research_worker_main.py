from __future__ import annotations

import os
from pathlib import Path
import socket
import time

import requests

from app.main import app as application
from app.providers.llm_gateway import LLMGatewayError
from app.providers.market import ProviderError
from app.services.data_refresh_queue import (
    DataRefreshWorker,
    RecoverableDataRefreshError,
)
from app.services.research_worker import RecoverableResearchError, ResearchWorker


def main() -> None:
    redis_runtime = application.state.redis
    queue = application.state.research_queue
    data_queue = application.state.data_refresh_queue
    if (
        not redis_runtime.is_available
        or redis_runtime.client is None
        or queue is None
        or data_queue is None
    ):
        raise RuntimeError("REDIS_URL is required by the research worker")
    redis_runtime.client.ping()

    worker_id = os.getenv("RESEARCH_WORKER_ID", "").strip() or (
        f"{socket.gethostname()}-{os.getpid()}"
    )

    def execute(task):
        try:
            completed = application.state.ai_research.execute_queued(task)
        except (
            LLMGatewayError,
            ProviderError,
            requests.RequestException,
            ConnectionError,
            TimeoutError,
            OSError,
        ) as exc:
            raise RecoverableResearchError(str(exc) or type(exc).__name__) from exc
        if not completed:
            raise RuntimeError("research execution failed validation")

    worker = ResearchWorker(
        application.state.database,
        queue,
        redis_runtime.client,
        worker_id,
        execute,
    )

    def execute_data_refresh(task):
        try:
            application.state.stock_snapshot_refresh.execute(task)
        except (
            ProviderError,
            requests.RequestException,
            ConnectionError,
            TimeoutError,
            OSError,
        ) as exc:
            raise RecoverableDataRefreshError(
                str(exc) or type(exc).__name__
            ) from exc

    data_worker = DataRefreshWorker(
        application.state.database,
        data_queue,
        redis_runtime.client,
        worker_id,
        execute_data_refresh,
    )
    heartbeat = Path("/tmp/qingshu-worker.heartbeat")
    while True:
        research_processed = worker.run_once()
        data_processed = data_worker.run_once()
        heartbeat.touch()
        if research_processed == 0 and data_processed == 0:
            time.sleep(0.1)


if __name__ == "__main__":
    main()
