from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import os
import time

import pytest

from app.operational_db import OperationalDatabase


@pytest.fixture()
def postgres_store():
    url = os.getenv("QINGSHU_TEST_POSTGRES_URL", "").strip()
    if not url:
        pytest.skip("QINGSHU_TEST_POSTGRES_URL is not configured")
    store = OperationalDatabase(url)
    store.initialize()
    import psycopg

    with psycopg.connect(url) as connection:
        connection.execute("DELETE FROM persistent_jobs")
        connection.execute("DELETE FROM persistent_schedules")
        connection.execute("DELETE FROM persistent_workers")
        connection.execute("DELETE FROM operational_counters")
    try:
        yield store
    finally:
        store.close()


def test_postgres_skip_locked_claims_once(postgres_store: OperationalDatabase):
    assert postgres_store.health()["connection_pool"]["pool_max"] == int(
        os.getenv("QINGSHU_OPERATIONAL_DB_POOL_MAX_SIZE", "4")
    )
    postgres_store.enqueue("refresh")

    def claim(worker_id: str):
        return postgres_store.claim(worker_id, lease_seconds=30)

    with ThreadPoolExecutor(max_workers=4) as executor:
        claims = list(
            executor.map(claim, ("worker-a", "worker-b", "worker-c", "worker-d"))
        )
    claimed = [item for item in claims if item is not None]
    assert len(claimed) == 1
    assert postgres_store.health()["counts"]["running"] == 1


def test_postgres_lease_recovery_survives_store_restart(
    postgres_store: OperationalDatabase,
):
    job = postgres_store.enqueue("refresh")
    claimed = postgres_store.claim("worker-a", lease_seconds=30)
    assert claimed is not None
    url = postgres_store.database_url
    postgres_store.close()

    import psycopg

    past = datetime.now(timezone.utc) - timedelta(minutes=5)
    with psycopg.connect(url) as connection:
        connection.execute(
            """
            UPDATE persistent_jobs
            SET lease_expires_at = %s, heartbeat_at = %s
            WHERE id = %s
            """,
            (past, past, job["id"]),
        )
    reopened = OperationalDatabase(url)
    reopened.initialize()
    try:
        assert reopened.recover_expired_leases() == {"requeued": 1, "failed": 0}
        reclaimed = reopened.claim("worker-b", lease_seconds=30)
        assert reclaimed is not None
        assert reclaimed.id == job["id"]
        assert reclaimed.attempts == 2
    finally:
        reopened.close()


def test_postgres_schedule_and_failure_archive(
    postgres_store: OperationalDatabase,
):
    postgres_store.register_schedule("market", "market_refresh", 30)
    paused = postgres_store.pause_schedule("market")
    assert paused is not None and paused["manually_paused"] is True
    postgres_store.register_schedule("market", "market_refresh", 30)
    assert postgres_store.enqueue_due_schedules() == 0
    resumed = postgres_store.resume_schedule("market")
    assert resumed is not None and resumed["enabled"] is True
    assert postgres_store.enqueue_due_schedules() == 1
    claim = postgres_store.claim("worker-a", lease_seconds=30)
    assert claim is not None
    failed = postgres_store.fail(claim.id, "worker-a", "provider down")
    assert failed is not None
    assert failed["status"] == "queued"


def test_postgres_worker_registry_and_queue_metrics(
    postgres_store: OperationalDatabase,
):
    postgres_store.register_worker(
        "postgres-worker",
        queue_name="background",
        metadata={"deployment": "integration"},
    )
    job = postgres_store.enqueue(
        "refresh",
        queue_name="background",
        max_attempts=1,
    )
    claim = postgres_store.claim(
        "postgres-worker",
        queue_name="background",
        lease_seconds=30,
    )
    assert claim is not None
    assert postgres_store.mark_worker_job_started(
        "postgres-worker", job["id"]
    )
    postgres_store.fail(claim.id, "postgres-worker", "test failure")
    assert postgres_store.mark_worker_job_finished(
        "postgres-worker", succeeded=False
    )
    health = postgres_store.health()
    assert health["schema_version"] == 4
    assert health["workers"]["active"] == 1
    assert health["queue"]["failed_24h"] == 1
    worker = postgres_store.list_workers()[0]
    assert worker["metadata"]["deployment"] == "integration"
    assert worker["jobs_claimed"] == 1
    assert worker["jobs_failed"] == 1

    import psycopg

    old = datetime.now(timezone.utc) - timedelta(days=60)
    with psycopg.connect(postgres_store.database_url) as connection:
        connection.execute(
            "UPDATE persistent_jobs SET finished_at = %s WHERE id = %s",
            (old, job["id"]),
        )
    removed = postgres_store.prune_terminal_jobs(failed_retention_hours=1)
    assert removed["failed"] == 1


def test_postgres_schema_initialization_uses_cross_process_advisory_lock(
    postgres_store: OperationalDatabase,
):
    class SlowStore(OperationalDatabase):
        def _apply_migrations(self, connection):
            connection.execute("SELECT pg_sleep(0.1)")
            return super()._apply_migrations(connection)

    def initialize(_: int) -> int:
        store = SlowStore(postgres_store.database_url)
        try:
            store.initialize()
            return store.health()["schema_version"]
        finally:
            store.close()

    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=3) as executor:
        versions = list(executor.map(initialize, range(3)))
    elapsed = time.monotonic() - started
    assert versions == [4, 4, 4]
    assert elapsed >= 0.25
