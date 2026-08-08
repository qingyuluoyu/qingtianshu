from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import socket

import psycopg

from app.operational_db import OperationalDatabase
from app.services.background import EventBroker


def store_for(tmp_path: Path) -> OperationalDatabase:
    del tmp_path
    store = OperationalDatabase(os.environ["QINGSHU_DATABASE_URL"])
    store.initialize()
    return store


def execute_raw(store: OperationalDatabase, sql: str, parameters: tuple = ()) -> None:
    url = store.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    if url.startswith("postgres://"):
        url = "postgresql://" + url.removeprefix("postgres://")
    with psycopg.connect(url) as connection:
        connection.execute(sql, parameters)


def test_enqueue_is_idempotent_and_survives_reopen(tmp_path: Path):
    store = store_for(tmp_path)
    first = store.enqueue(
        "refresh",
        {"symbol": "000063.SZ"},
        idempotency_key="refresh-zte-20260724",
    )
    repeated = store.enqueue(
        "refresh",
        {"symbol": "DIFFERENT"},
        idempotency_key="refresh-zte-20260724",
    )
    assert repeated["id"] == first["id"]
    assert repeated["payload"] == {"symbol": "000063.SZ"}
    store.close()

    reopened = store_for(tmp_path)
    jobs = reopened.list_jobs()
    assert len(jobs) == 1
    assert jobs[0]["id"] == first["id"]
    assert reopened.health()["schema_version"] == 4


def test_two_workers_cannot_claim_the_same_job(tmp_path: Path):
    store = store_for(tmp_path)
    store.enqueue("refresh", {"symbol": "NVDA"})

    def claim(worker_id: str):
        return store.claim(worker_id, lease_seconds=30)

    with ThreadPoolExecutor(max_workers=2) as executor:
        claims = list(executor.map(claim, ("worker-a", "worker-b")))

    claimed = [item for item in claims if item is not None]
    assert len(claimed) == 1
    assert claimed[0].job_name == "refresh"
    assert store.health()["counts"]["running"] == 1


def test_expired_lease_is_requeued_and_claimed_by_another_worker(tmp_path: Path):
    store = store_for(tmp_path)
    job = store.enqueue("refresh")
    claimed = store.claim("worker-a", lease_seconds=30)
    assert claimed is not None

    past = datetime.now(timezone.utc) - timedelta(minutes=5)
    execute_raw(
        store,
        """
        UPDATE persistent_jobs
        SET lease_expires_at = %s, heartbeat_at = %s
        WHERE id = %s
        """,
        (past, past, job["id"]),
    )

    recovered = store.recover_expired_leases()
    assert recovered == {"requeued": 1, "failed": 0}
    reclaimed = store.claim("worker-b", lease_seconds=30)
    assert reclaimed is not None
    assert reclaimed.id == job["id"]
    assert reclaimed.attempts == 2


def test_dead_local_worker_is_recovered_without_waiting_for_lease(tmp_path: Path):
    store = store_for(tmp_path)
    store.enqueue("refresh")
    owner = f"{socket.gethostname()}-99999999-dead-t1"
    claimed = store.claim(owner, lease_seconds=3600)
    assert claimed is not None

    recovered = store.recover_dead_local_workers()
    assert recovered == {"requeued": 1, "failed": 0}
    reclaimed = store.claim("replacement-worker", lease_seconds=30)
    assert reclaimed is not None
    assert reclaimed.id == claimed.id
    assert store.health()["counters"]["lease_recoveries_total"] == 1
    assert store.health()["counters"]["dead_local_worker_recoveries_total"] == 1


def test_worker_registry_tracks_heartbeat_jobs_and_stale_processes(tmp_path: Path):
    store = store_for(tmp_path)
    worker = store.register_worker(
        "worker-observable",
        queue_name="background",
        metadata={"mode": "external"},
    )
    assert worker["status"] == "active"
    assert worker["metadata"]["mode"] == "external"
    assert store.mark_worker_job_started("worker-observable", "job-1") is True
    assert store.mark_worker_job_finished("worker-observable", succeeded=True) is True
    current = store.list_workers()[0]
    assert current["jobs_claimed"] == 1
    assert current["jobs_succeeded"] == 1
    assert current["current_job_id"] is None

    stale = datetime.now(timezone.utc) - timedelta(minutes=5)
    execute_raw(
        store,
        """
        UPDATE persistent_workers
        SET last_heartbeat_at = %s
        WHERE worker_id = 'worker-observable'
        """,
        (stale,),
    )
    assert store.reconcile_stale_workers(stale_after_seconds=30) == 1
    assert store.list_workers()[0]["status"] == "offline"


def test_queue_health_exposes_delay_retry_and_recent_failure_metrics(tmp_path: Path):
    store = store_for(tmp_path)
    store.register_worker("worker-health")
    first = store.enqueue("refresh", max_attempts=1)
    claim = store.claim("worker-health", lease_seconds=30)
    assert claim is not None
    store.fail(first["id"], "worker-health", "permanent")
    store.enqueue(
        "later",
        available_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    health = store.health()
    assert health["queue"]["failed_24h"] == 1
    assert health["queue"]["failure_rate_24h"] == 1.0
    assert health["queue"]["delayed"] == 1
    assert health["workers"]["active"] == 1


def test_terminal_job_retention_prunes_by_status_without_touching_active_jobs(
    tmp_path: Path,
):
    store = store_for(tmp_path)
    succeeded = store.enqueue("succeeded")
    claimed = store.claim("worker-a", lease_seconds=30)
    assert claimed is not None
    assert store.complete(claimed.id, "worker-a", {"ok": True})

    failed = store.enqueue("failed", max_attempts=1)
    claimed = store.claim("worker-a", lease_seconds=30)
    assert claimed is not None
    store.fail(claimed.id, "worker-a", "failed")

    cancelled = store.enqueue("cancelled")
    assert store.cancel(cancelled["id"])
    active = store.enqueue("active")
    old = datetime.now(timezone.utc) - timedelta(days=60)
    execute_raw(
        store,
        """
        UPDATE persistent_jobs
        SET finished_at = %s, updated_at = %s
        WHERE id IN (%s, %s, %s)
        """,
        (
            old,
            old,
            succeeded["id"],
            failed["id"],
            cancelled["id"],
        ),
    )
    removed = store.prune_terminal_jobs(
        succeeded_retention_hours=1,
        failed_retention_hours=1,
        cancelled_retention_hours=1,
    )
    assert removed == {"succeeded": 1, "failed": 1, "cancelled": 1}
    assert [item["id"] for item in store.list_jobs()] == [active["id"]]


def test_domain_background_history_retention_preserves_running_audit(client):
    database = client.app.state.database
    completed = database.start_background_job("old-completed")
    database.finish_background_job(completed, "completed", summary={"ok": True})
    failed = database.start_background_job("old-failed")
    database.finish_background_job(failed, "failed", error="old")
    running = database.start_background_job("still-running")
    snapshot = database.save_data_health_snapshot(
        {
            "status": "healthy",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "summary": {"total": 1},
        }
    )
    old = (datetime.now(timezone.utc) - timedelta(days=120)).isoformat()
    with database.connect() as connection:
        connection.execute(
            """
            UPDATE background_job_runs
            SET finished_at = ?, started_at = ?
            WHERE id IN (?, ?)
            """,
            (old, old, completed, failed),
        )
        connection.execute(
            "UPDATE data_health_snapshots SET created_at = ? WHERE id = ?",
            (old, snapshot["id"]),
        )
    removed = database.prune_background_history(
        completed_retention_hours=1,
        failed_retention_hours=1,
        data_health_retention_hours=1,
    )
    assert removed == {
        "completed_background_runs": 1,
        "failed_background_runs": 1,
        "data_health_snapshots": 1,
    }
    with database.connect() as connection:
        row = connection.execute(
            "SELECT status FROM background_job_runs WHERE id = ?", (running,)
        ).fetchone()
    assert row["status"] == "running"


def test_failure_uses_backoff_then_archives_after_max_attempts(tmp_path: Path):
    store = store_for(tmp_path)
    job = store.enqueue("refresh", max_attempts=2)
    first = store.claim("worker-a", lease_seconds=30)
    assert first is not None
    retried = store.fail(
        first.id,
        "worker-a",
        "temporary provider error",
        retry_base_seconds=10,
        retry_max_seconds=60,
    )
    assert retried is not None
    assert retried["status"] == "queued"
    assert retried["attempts"] == 1
    assert datetime.fromisoformat(retried["available_at"]) > datetime.now(timezone.utc)

    execute_raw(
        store,
        "UPDATE persistent_jobs SET available_at = %s WHERE id = %s",
        (datetime.now(timezone.utc) - timedelta(seconds=1), job["id"]),
    )
    second = store.claim("worker-b", lease_seconds=30)
    assert second is not None
    archived = store.fail(second.id, "worker-b", "still broken")
    assert archived is not None
    assert archived["status"] == "failed"
    assert archived["finished_at"] is not None

    assert store.retry(job["id"]) is True
    manual_retry = store.list_jobs()[0]
    assert manual_retry["status"] == "queued"
    assert manual_retry["attempts"] == 0
    assert manual_retry["last_error"] is None


def test_persistent_schedule_coalesces_overlapping_runs(tmp_path: Path):
    store = store_for(tmp_path)
    store.register_schedule("market", "market_refresh", 30)
    assert store.enqueue_due_schedules() == 1
    assert store.enqueue_due_schedules() == 0
    claimed = store.claim("worker-a", lease_seconds=30)
    assert claimed is not None

    execute_raw(
        store,
        "UPDATE persistent_schedules SET next_run_at = %s WHERE name = 'market'",
        (datetime.now(timezone.utc) - timedelta(seconds=1),),
    )
    assert store.enqueue_due_schedules() == 0
    assert store.complete(claimed.id, "worker-a", {"status": "ok"}) is True
    execute_raw(
        store,
        "UPDATE persistent_schedules SET next_run_at = %s WHERE name = 'market'",
        (datetime.now(timezone.utc) - timedelta(seconds=1),),
    )
    assert store.enqueue_due_schedules() == 1
    assert store.health()["counts"]["queued"] == 1


def test_manual_schedule_pause_survives_registration_and_resume(tmp_path: Path):
    store = store_for(tmp_path)
    store.register_schedule("market", "market_refresh", 30)
    paused = store.pause_schedule("market")
    assert paused is not None
    assert paused["enabled"] is False
    assert paused["manually_paused"] is True
    assert store.enqueue_due_schedules() == 0

    store.register_schedule("market", "market_refresh", 30, enabled=True)
    persisted = store.list_schedules()[0]
    assert persisted["configured_enabled"] is True
    assert persisted["enabled"] is False
    assert persisted["manually_paused"] is True
    assert store.health()["manually_paused_schedules"] == 1

    resumed = store.resume_schedule("market")
    assert resumed is not None
    assert resumed["enabled"] is True
    assert resumed["manually_paused"] is False
    assert resumed["paused_at"] is None
    assert store.enqueue_due_schedules() == 1


def test_cancel_only_accepts_queued_jobs(tmp_path: Path):
    store = store_for(tmp_path)
    queued = store.enqueue("queued")
    assert store.cancel(queued["id"]) is True
    assert store.cancel(queued["id"]) is False

    running = store.enqueue("running")
    assert store.claim("worker-a", lease_seconds=30) is not None
    assert store.cancel(running["id"]) is False


def test_events_cross_process_boundary_through_operational_database(tmp_path: Path):
    publisher_store = store_for(tmp_path)
    listener_store = OperationalDatabase(publisher_store.database_url)
    listener_store.initialize()
    publisher = EventBroker()
    publisher.attach_store(publisher_store)
    listener = EventBroker()
    listener.attach_store(listener_store)
    stream = listener.stream()
    assert "connected" in next(stream)

    publisher.publish({"type": "market_updated", "coverage": {"available": 7}})
    message = next(stream)
    assert "market_updated" in message
    assert '"available": 7' in message
    stream.close()


def test_admin_api_can_enqueue_inspect_and_cancel_jobs(client):
    object.__setattr__(
        client.app.state.settings, "admin_api_token", "test-admin-secret"
    )
    assert client.post("/users", json={"name": "queue-admin"}).status_code == 201
    headers = {"x-qingshu-admin-token": "test-admin-secret"}

    created = client.post(
        "/admin/job-queue/enqueue",
        headers=headers,
        json={
            "job_name": "data_quality_audit",
            "payload": {"reason": "manual-check"},
            "idempotency_key": "manual-data-quality-20260724",
        },
    )
    assert created.status_code == 202
    job = created.json()
    assert job["status"] == "queued"

    listing = client.get("/admin/job-queue?status=queued", headers=headers)
    assert listing.status_code == 200
    assert listing.json()["queue"]["backend"] == "postgresql"
    assert [item["id"] for item in listing.json()["jobs"]] == [job["id"]]

    cancelled = client.post(f"/admin/job-queue/{job['id']}/cancel", headers=headers)
    assert cancelled.status_code == 200
    retried = client.post(f"/admin/job-queue/{job['id']}/retry", headers=headers)
    assert retried.status_code == 202
    operations = client.get("/admin/operations/health", headers=headers)
    assert operations.status_code == 200
    assert operations.json()["queue"]["schema_version"] == 4
    assert operations.json()["backups"]["status"] == "ok"
    schedules = client.get("/admin/job-schedules", headers=headers)
    assert schedules.status_code == 200
    assert any(
        item["name"] == "data_quality_audit" for item in schedules.json()["schedules"]
    )
    paused = client.post(
        "/admin/job-schedules/data_quality_audit/pause",
        headers=headers,
    )
    assert paused.status_code == 200
    assert paused.json()["manually_paused"] is True
    resumed = client.post(
        "/admin/job-schedules/data_quality_audit/resume",
        headers=headers,
    )
    assert resumed.status_code == 200
    assert resumed.json()["manually_paused"] is False
    assert (
        client.post("/admin/job-schedules/missing/pause", headers=headers).status_code
        == 404
    )


def test_job_admin_api_requires_session_and_admin_token(client):
    assert client.get("/admin/job-queue").status_code == 401
    assert client.get("/admin/operations/health").status_code == 401
    assert client.get("/admin/job-schedules").status_code == 401
    assert client.post("/users", json={"name": "not-admin"}).status_code == 201
    assert client.get("/admin/job-queue").status_code == 403
    assert client.get("/admin/operations/health").status_code == 403
    assert client.get("/admin/job-schedules").status_code == 403


def test_background_service_executes_registered_job_through_persistent_queue(client):
    background = client.app.state.background
    queued = background.enqueue(
        "data_quality_audit",
        idempotency_key="integration-data-quality-20260724",
    )
    assert background.run_once("integration-worker") is True

    completed = {item["id"]: item for item in background.list_jobs(status="succeeded")}
    assert completed[queued["id"]]["result"]["status"] in {
        "healthy",
        "degraded",
        "critical",
    }
    latest = client.app.state.database.latest_background_jobs()
    assert any(
        item["job_name"] == "data_quality_audit" and item["status"] == "completed"
        for item in latest
    )


def test_background_audit_reconciles_when_queue_lease_is_lost(client):
    background = client.app.state.background
    queued = background.job_store.enqueue(
        "data_quality_audit",
        queue_name="background",
    )
    claimed = background.job_store.claim(
        "crashed-worker",
        queue_name="background",
        lease_seconds=30,
    )
    assert claimed is not None
    run_id = client.app.state.database.start_background_job(
        "data_quality_audit",
        queue_job_id=queued["id"],
        worker_id="crashed-worker",
    )
    assert client.app.state.database.repair_background_job_runs_from_queue() == 0

    failed = background.job_store.fail(
        claimed.id,
        "crashed-worker",
        "worker exited",
    )
    assert failed["status"] == "queued"
    assert client.app.state.database.repair_background_job_runs_from_queue() == 1
    row = next(
        item
        for item in client.app.state.database.latest_background_jobs()
        if item["id"] == run_id
    )
    assert row["status"] == "failed"
    assert row["error"] == "queue_lease_no_longer_active"
