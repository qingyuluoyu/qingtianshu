from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import os
import socket
from typing import Any, Iterator
from uuid import uuid4


UTC = timezone.utc
ACTIVE_JOB_STATUSES = ("queued", "running")
TERMINAL_JOB_STATUSES = ("succeeded", "failed", "cancelled")


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _as_datetime(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _local_process_is_alive(pid: int) -> bool:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        open_process = kernel32.OpenProcess
        open_process.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        open_process.restype = wintypes.HANDLE
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = (wintypes.HANDLE,)
        close_handle.restype = wintypes.BOOL

        handle = open_process(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if handle:
            close_handle(handle)
            return True
        error = ctypes.get_last_error()
        if error == 87:  # ERROR_INVALID_PARAMETER: the PID no longer exists.
            return False
        if error == 5:  # ERROR_ACCESS_DENIED: the process exists but is protected.
            return True
        raise OSError(error, ctypes.FormatError(error))

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@dataclass(frozen=True)
class ClaimedJob:
    id: str
    queue_name: str
    job_name: str
    payload: dict[str, Any]
    attempts: int
    max_attempts: int
    lease_owner: str
    lease_expires_at: datetime


class OperationalDatabase:
    """PostgreSQL control-plane database for durable jobs and schedules."""

    SCHEMA_VERSION = 4

    def __init__(self, database_url: str):
        self.database_url = str(database_url or "").strip()
        if not self.database_url.startswith(
            ("postgresql://", "postgres://", "postgresql+psycopg://")
        ):
            raise ValueError("QINGSHU_DATABASE_URL is required and must use PostgreSQL")
        self._pool: Any | None = None
        self._initialized = False

    def initialize(self) -> None:
        if self._initialized:
            return
        self._ensure_postgres_pool()
        with self._transaction() as connection:
            connection.execute(
                """
                SELECT pg_advisory_xact_lock(
                    hashtext('qingshu_operational_schema_migration')
                )
                """
            )
            self._apply_migrations(connection)
        self._initialized = True

    def close(self) -> None:
        if self._pool is not None:
            self._pool.close()
            self._pool = None
        self._initialized = False

    def _ensure_postgres_pool(self) -> None:
        if self._pool is not None:
            return
        try:
            from psycopg.rows import dict_row
            from psycopg_pool import ConnectionPool
        except ImportError as exc:  # pragma: no cover - exercised in deployment
            raise RuntimeError(
                "PostgreSQL requires the psycopg binary and pool dependencies"
            ) from exc
        url = self.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
        if url.startswith("postgres://"):
            url = "postgresql://" + url.removeprefix("postgres://")
        min_size = max(1, int(os.getenv("QINGSHU_OPERATIONAL_DB_POOL_MIN_SIZE", "1")))
        max_size = max(
            min_size,
            int(os.getenv("QINGSHU_OPERATIONAL_DB_POOL_MAX_SIZE", "4")),
        )
        self._pool = ConnectionPool(
            conninfo=url,
            min_size=min_size,
            max_size=max_size,
            kwargs={"autocommit": False, "row_factory": dict_row},
            open=True,
        )
        self._pool.wait(timeout=15)

    @contextmanager
    def _transaction(self) -> Iterator[Any]:
        self._ensure_postgres_pool()
        with self._pool.connection() as connection:
            with connection.transaction():
                yield connection

    def _apply_migrations(self, connection: Any) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS qingshu_schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS persistent_jobs (
                id UUID PRIMARY KEY,
                queue_name TEXT NOT NULL,
                job_name TEXT NOT NULL,
                payload_json JSONB NOT NULL,
                status TEXT NOT NULL
                    CHECK(status IN (
                        'queued', 'running', 'succeeded', 'failed', 'cancelled'
                    )),
                priority INTEGER NOT NULL DEFAULT 0,
                available_at TIMESTAMPTZ NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                max_attempts INTEGER NOT NULL,
                lease_owner TEXT,
                lease_expires_at TIMESTAMPTZ,
                heartbeat_at TIMESTAMPTZ,
                idempotency_key TEXT,
                result_json JSONB,
                last_error TEXT,
                created_at TIMESTAMPTZ NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL,
                started_at TIMESTAMPTZ,
                finished_at TIMESTAMPTZ,
                UNIQUE(queue_name, idempotency_key)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS persistent_schedules (
                name TEXT PRIMARY KEY,
                queue_name TEXT NOT NULL,
                job_name TEXT NOT NULL,
                payload_json JSONB NOT NULL,
                interval_seconds INTEGER NOT NULL,
                priority INTEGER NOT NULL DEFAULT 0,
                max_attempts INTEGER NOT NULL,
                enabled BOOLEAN NOT NULL DEFAULT TRUE,
                configured_enabled BOOLEAN NOT NULL DEFAULT TRUE,
                manually_paused BOOLEAN NOT NULL DEFAULT FALSE,
                paused_at TIMESTAMPTZ,
                next_run_at TIMESTAMPTZ NOT NULL,
                created_at TIMESTAMPTZ NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL
            )
            """
        )
        connection.execute(
            """
            ALTER TABLE persistent_schedules
            ADD COLUMN IF NOT EXISTS configured_enabled BOOLEAN NOT NULL DEFAULT TRUE
            """
        )
        connection.execute(
            """
            ALTER TABLE persistent_schedules
            ADD COLUMN IF NOT EXISTS manually_paused BOOLEAN NOT NULL DEFAULT FALSE
            """
        )
        connection.execute(
            """
            ALTER TABLE persistent_schedules
            ADD COLUMN IF NOT EXISTS paused_at TIMESTAMPTZ
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS persistent_events (
                sequence_id BIGSERIAL PRIMARY KEY,
                event_type TEXT NOT NULL,
                payload_json JSONB NOT NULL,
                created_at TIMESTAMPTZ NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS persistent_workers (
                worker_id TEXT PRIMARY KEY,
                hostname TEXT NOT NULL,
                process_id INTEGER NOT NULL,
                queue_name TEXT NOT NULL,
                status TEXT NOT NULL
                    CHECK(status IN ('active', 'offline', 'stopped')),
                current_job_id TEXT,
                started_at TIMESTAMPTZ NOT NULL,
                last_heartbeat_at TIMESTAMPTZ NOT NULL,
                stopped_at TIMESTAMPTZ,
                jobs_claimed BIGINT NOT NULL DEFAULT 0,
                jobs_succeeded BIGINT NOT NULL DEFAULT 0,
                jobs_failed BIGINT NOT NULL DEFAULT 0,
                metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS operational_counters (
                name TEXT PRIMARY KEY,
                value BIGINT NOT NULL DEFAULT 0,
                updated_at TIMESTAMPTZ NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_persistent_jobs_claim
            ON persistent_jobs(
                queue_name, status, available_at, priority DESC, created_at
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_persistent_jobs_lease
            ON persistent_jobs(status, lease_expires_at)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_persistent_jobs_name_created
            ON persistent_jobs(job_name, created_at DESC)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_persistent_schedules_due
            ON persistent_schedules(enabled, next_run_at)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_persistent_events_created
            ON persistent_events(created_at)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_persistent_workers_health
            ON persistent_workers(status, last_heartbeat_at)
            """
        )
        connection.execute(
            """
            INSERT INTO qingshu_schema_migrations(version, applied_at)
            VALUES (%s, %s)
            ON CONFLICT(version) DO NOTHING
            """,
            (self.SCHEMA_VERSION, _utc_now()),
        )

    def register_worker(
        self,
        worker_id: str,
        *,
        queue_name: str = "default",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.initialize()
        now = _utc_now()
        encoded = _json(metadata or {})
        hostname = socket.gethostname()
        process_id = os.getpid()
        with self._transaction() as connection:
            row = connection.execute(
                """
                INSERT INTO persistent_workers(
                    worker_id, hostname, process_id, queue_name, status,
                    current_job_id, started_at, last_heartbeat_at,
                    stopped_at, metadata_json
                ) VALUES (
                    %s, %s, %s, %s, 'active', NULL, %s, %s, NULL, %s::jsonb
                )
                ON CONFLICT(worker_id) DO UPDATE SET
                    hostname = EXCLUDED.hostname,
                    process_id = EXCLUDED.process_id,
                    queue_name = EXCLUDED.queue_name,
                    status = 'active',
                    current_job_id = NULL,
                    started_at = EXCLUDED.started_at,
                    last_heartbeat_at = EXCLUDED.last_heartbeat_at,
                    stopped_at = NULL,
                    metadata_json = EXCLUDED.metadata_json
                RETURNING *
                """,
                (
                    worker_id,
                    hostname,
                    process_id,
                    queue_name,
                    now,
                    now,
                    encoded,
                ),
            ).fetchone()
        return self._worker_row(row)

    def heartbeat_worker(
        self, worker_id: str, *, current_job_id: str | None = None
    ) -> bool:
        self.initialize()
        now = _utc_now()
        with self._transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE persistent_workers
                SET status = 'active',
                    current_job_id = %s,
                    last_heartbeat_at = %s,
                    stopped_at = NULL
                WHERE worker_id = %s
                """,
                (current_job_id, now, worker_id),
            )
        return cursor.rowcount == 1

    def mark_worker_job_started(self, worker_id: str, job_id: str) -> bool:
        self.initialize()
        now = _utc_now()
        with self._transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE persistent_workers
                SET status = 'active',
                    current_job_id = %s,
                    jobs_claimed = jobs_claimed + 1,
                    last_heartbeat_at = %s
                WHERE worker_id = %s
                """,
                (job_id, now, worker_id),
            )
        return cursor.rowcount == 1

    def mark_worker_job_finished(self, worker_id: str, *, succeeded: bool) -> bool:
        self.initialize()
        now = _utc_now()
        counter = "jobs_succeeded" if succeeded else "jobs_failed"
        with self._transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE persistent_workers
                SET current_job_id = NULL,
                    {counter} = {counter} + 1,
                    last_heartbeat_at = %s
                WHERE worker_id = %s
                """.format(counter=counter),
                (now, worker_id),
            )
        return cursor.rowcount == 1

    def stop_worker(self, worker_id: str) -> bool:
        self.initialize()
        now = _utc_now()
        with self._transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE persistent_workers
                SET status = 'stopped',
                    current_job_id = NULL,
                    last_heartbeat_at = %s,
                    stopped_at = %s
                WHERE worker_id = %s
                """,
                (now, now, worker_id),
            )
        return cursor.rowcount == 1

    def reconcile_stale_workers(self, *, stale_after_seconds: int = 60) -> int:
        self.initialize()
        now = _utc_now()
        cutoff = now - timedelta(seconds=max(1, stale_after_seconds))
        with self._transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE persistent_workers
                SET status = 'offline', current_job_id = NULL
                WHERE status = 'active' AND last_heartbeat_at < %s
                """,
                (cutoff,),
            )
        return int(cursor.rowcount)

    def list_workers(
        self, *, stale_after_seconds: int = 60, limit: int = 100
    ) -> list[dict[str, Any]]:
        self.reconcile_stale_workers(stale_after_seconds=stale_after_seconds)
        with self._transaction() as connection:
            rows = connection.execute(
                """
                SELECT * FROM persistent_workers
                ORDER BY last_heartbeat_at DESC
                LIMIT %s
                """,
                (max(1, min(500, int(limit))),),
            ).fetchall()
        return [self._worker_row(row) for row in rows]

    def prune_workers(self, *, retention_hours: int = 168) -> int:
        self.initialize()
        cutoff = _utc_now() - timedelta(hours=max(1, retention_hours))
        with self._transaction() as connection:
            cursor = connection.execute(
                """
                DELETE FROM persistent_workers
                WHERE status IN ('offline', 'stopped')
                    AND last_heartbeat_at < %s
                """,
                (cutoff,),
            )
        return int(cursor.rowcount)

    def prune_terminal_jobs(
        self,
        *,
        succeeded_retention_hours: int = 168,
        failed_retention_hours: int = 720,
        cancelled_retention_hours: int = 168,
    ) -> dict[str, int]:
        self.initialize()
        now = _utc_now()
        cutoffs = {
            "succeeded": now - timedelta(hours=max(1, succeeded_retention_hours)),
            "failed": now - timedelta(hours=max(1, failed_retention_hours)),
            "cancelled": now - timedelta(hours=max(1, cancelled_retention_hours)),
        }
        removed = {status: 0 for status in cutoffs}
        with self._transaction() as connection:
            for status, cutoff in cutoffs.items():
                cursor = connection.execute(
                    """
                    DELETE FROM persistent_jobs
                    WHERE status = %s
                        AND finished_at IS NOT NULL
                        AND finished_at < %s
                    """,
                    (status, cutoff),
                )
                removed[status] = int(cursor.rowcount)
        return removed

    def increment_counter(self, name: str, amount: int = 1) -> None:
        if not amount:
            return
        self.initialize()
        now = _utc_now()
        with self._transaction() as connection:
            connection.execute(
                """
                INSERT INTO operational_counters(name, value, updated_at)
                VALUES (%s, %s, %s)
                ON CONFLICT(name) DO UPDATE SET
                    value = operational_counters.value + EXCLUDED.value,
                    updated_at = EXCLUDED.updated_at
                """,
                (name, int(amount), now),
            )

    def enqueue(
        self,
        job_name: str,
        payload: dict[str, Any] | None = None,
        *,
        queue_name: str = "default",
        available_at: datetime | None = None,
        priority: int = 0,
        max_attempts: int = 3,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        self.initialize()
        job_id = str(uuid4())
        now = _utc_now()
        due = available_at or now
        encoded = _json(payload or {})
        with self._transaction() as connection:
            row = connection.execute(
                """
                INSERT INTO persistent_jobs(
                    id, queue_name, job_name, payload_json, status, priority,
                    available_at, attempts, max_attempts, idempotency_key,
                    created_at, updated_at
                ) VALUES (
                    %s, %s, %s, %s::jsonb, 'queued', %s, %s, 0, %s, %s, %s, %s
                )
                ON CONFLICT(queue_name, idempotency_key) DO UPDATE
                SET idempotency_key = EXCLUDED.idempotency_key
                RETURNING *
                """,
                (
                    job_id,
                    queue_name,
                    job_name,
                    encoded,
                    int(priority),
                    due,
                    int(max_attempts),
                    idempotency_key,
                    now,
                    now,
                ),
            ).fetchone()
            return self._job_row(row)

    def register_schedule(
        self,
        name: str,
        job_name: str,
        interval_seconds: int,
        *,
        payload: dict[str, Any] | None = None,
        queue_name: str = "default",
        priority: int = 0,
        max_attempts: int = 3,
        enabled: bool = True,
        run_immediately: bool = True,
    ) -> None:
        self.initialize()
        now = _utc_now()
        next_run = now if run_immediately else now + timedelta(seconds=interval_seconds)
        encoded = _json(payload or {})
        with self._transaction() as connection:
            connection.execute(
                """
                INSERT INTO persistent_schedules(
                    name, queue_name, job_name, payload_json, interval_seconds,
                    priority, max_attempts, enabled, configured_enabled,
                    next_run_at, created_at, updated_at
                ) VALUES (
                    %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s, %s
                )
                ON CONFLICT(name) DO UPDATE SET
                    queue_name = EXCLUDED.queue_name,
                    job_name = EXCLUDED.job_name,
                    payload_json = EXCLUDED.payload_json,
                    interval_seconds = EXCLUDED.interval_seconds,
                    priority = EXCLUDED.priority,
                    max_attempts = EXCLUDED.max_attempts,
                    configured_enabled = EXCLUDED.configured_enabled,
                    enabled = CASE
                        WHEN persistent_schedules.manually_paused THEN FALSE
                        ELSE EXCLUDED.enabled
                    END,
                    updated_at = EXCLUDED.updated_at
                """,
                (
                    name,
                    queue_name,
                    job_name,
                    encoded,
                    int(interval_seconds),
                    int(priority),
                    int(max_attempts),
                    enabled,
                    enabled,
                    next_run,
                    now,
                    now,
                ),
            )

    def list_schedules(self, *, limit: int = 100) -> list[dict[str, Any]]:
        self.initialize()
        with self._transaction() as connection:
            rows = connection.execute(
                """
                SELECT * FROM persistent_schedules
                ORDER BY name
                LIMIT %s
                """,
                (max(1, min(500, int(limit))),),
            ).fetchall()
        return [self._schedule_row(row) for row in rows]

    def pause_schedule(self, name: str) -> dict[str, Any] | None:
        self.initialize()
        now = _utc_now()
        with self._transaction() as connection:
            row = connection.execute(
                """
                UPDATE persistent_schedules
                SET enabled = FALSE,
                    manually_paused = TRUE,
                    paused_at = %s,
                    updated_at = %s
                WHERE name = %s
                RETURNING *
                """,
                (now, now, name),
            ).fetchone()
        return self._schedule_row(row) if row is not None else None

    def resume_schedule(self, name: str) -> dict[str, Any] | None:
        self.initialize()
        now = _utc_now()
        with self._transaction() as connection:
            row = connection.execute(
                """
                UPDATE persistent_schedules
                SET enabled = configured_enabled,
                    manually_paused = FALSE,
                    paused_at = NULL,
                    next_run_at = %s,
                    updated_at = %s
                WHERE name = %s
                RETURNING *
                """,
                (now, now, name),
            ).fetchone()
        return self._schedule_row(row) if row is not None else None

    def enqueue_due_schedules(self, *, limit: int = 100) -> int:
        self.initialize()
        now = _utc_now()
        enqueued = 0
        with self._transaction() as connection:
            rows = connection.execute(
                """
                SELECT * FROM persistent_schedules
                WHERE enabled = TRUE AND next_run_at <= %s
                ORDER BY next_run_at
                FOR UPDATE SKIP LOCKED
                LIMIT %s
                """,
                (now, int(limit)),
            ).fetchall()
            for raw in rows:
                row = dict(raw)
                due = _as_datetime(row["next_run_at"]) or now
                interval = max(1, int(row["interval_seconds"]))
                next_run = due
                while next_run <= now:
                    next_run += timedelta(seconds=interval)
                active = connection.execute(
                    """
                    SELECT id FROM persistent_jobs
                    WHERE queue_name = %s AND job_name = %s
                        AND status IN ('queued', 'running')
                    LIMIT 1
                    """,
                    (row["queue_name"], row["job_name"]),
                ).fetchone()
                if active is None:
                    inserted = connection.execute(
                        """
                        INSERT INTO persistent_jobs(
                            id, queue_name, job_name, payload_json, status,
                            priority, available_at, attempts, max_attempts,
                            idempotency_key, created_at, updated_at
                        ) VALUES (
                            %s, %s, %s, %s::jsonb, 'queued', %s, %s, 0, %s,
                            %s, %s, %s
                        )
                        ON CONFLICT(queue_name, idempotency_key) DO NOTHING
                        RETURNING id
                        """,
                        (
                            str(uuid4()),
                            row["queue_name"],
                            row["job_name"],
                            _json(row["payload_json"])
                            if isinstance(row["payload_json"], dict)
                            else row["payload_json"],
                            int(row["priority"]),
                            due,
                            int(row["max_attempts"]),
                            f"schedule:{row['name']}:{due.isoformat()}",
                            now,
                            now,
                        ),
                    ).fetchone()
                    enqueued += int(inserted is not None)
                connection.execute(
                    """
                    UPDATE persistent_schedules
                    SET next_run_at = %s, updated_at = %s
                    WHERE name = %s
                    """,
                    (next_run, now, row["name"]),
                )
        return enqueued

    def recover_expired_leases(self) -> dict[str, int]:
        self.initialize()
        now = _utc_now()
        with self._transaction() as connection:
            failed = connection.execute(
                """
                UPDATE persistent_jobs
                SET status = 'failed',
                    last_error = COALESCE(
                        last_error, 'lease_expired_after_max_attempts'
                    ),
                    lease_owner = NULL,
                    lease_expires_at = NULL,
                    heartbeat_at = NULL,
                    finished_at = %s,
                    updated_at = %s
                WHERE status = 'running'
                    AND lease_expires_at < %s
                    AND attempts >= max_attempts
                """,
                (now, now, now),
            ).rowcount
            queued = connection.execute(
                """
                UPDATE persistent_jobs
                SET status = 'queued',
                    available_at = %s,
                    last_error = COALESCE(last_error, 'lease_expired_requeued'),
                    lease_owner = NULL,
                    lease_expires_at = NULL,
                    heartbeat_at = NULL,
                    updated_at = %s
                WHERE status = 'running'
                    AND lease_expires_at < %s
                    AND attempts < max_attempts
                """,
                (now, now, now),
            ).rowcount
        recovered = int(queued) + int(failed)
        if recovered:
            self.increment_counter("lease_recoveries_total", recovered)
        return {"requeued": int(queued), "failed": int(failed)}

    def recover_dead_local_workers(self) -> dict[str, int]:
        """Immediately expire leases owned by dead processes on this host."""

        hostname = socket.gethostname()
        prefix = f"{hostname}-"
        dead_owners: set[str] = set()
        for job in self.list_jobs(status="running", limit=500):
            owner = str(job.get("lease_owner") or "")
            if not owner.startswith(prefix):
                continue
            raw_pid = owner[len(prefix) :].split("-", 1)[0]
            if not raw_pid.isdigit():
                continue
            if not _local_process_is_alive(int(raw_pid)):
                dead_owners.add(owner)
        if not dead_owners:
            return {"requeued": 0, "failed": 0}
        expired = _utc_now() - timedelta(seconds=1)
        with self._transaction() as connection:
            for owner in dead_owners:
                connection.execute(
                    """
                    UPDATE persistent_jobs
                    SET lease_expires_at = %s, updated_at = %s
                    WHERE status = 'running' AND lease_owner = %s
                    """,
                    (expired, _utc_now(), owner),
                )
        recovered = self.recover_expired_leases()
        total = recovered["requeued"] + recovered["failed"]
        if total:
            self.increment_counter("dead_local_worker_recoveries_total", total)
        return recovered

    def publish_event(self, event: dict[str, Any]) -> dict[str, Any]:
        self.initialize()
        now = _utc_now()
        event_type = str(event.get("type") or "event")
        encoded = _json(event)
        with self._transaction() as connection:
            row = connection.execute(
                """
                INSERT INTO persistent_events(
                    event_type, payload_json, created_at
                ) VALUES (%s, %s::jsonb, %s)
                RETURNING sequence_id
                """,
                (event_type, encoded, now),
            ).fetchone()
            sequence_id = int(row["sequence_id"])
        return {**event, "_sequence_id": sequence_id}

    def latest_event_sequence(self) -> int:
        self.initialize()
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT MAX(sequence_id) AS sequence_id FROM persistent_events"
            ).fetchone()
        return int(row["sequence_id"] or 0)

    def events_after(
        self, sequence_id: int, *, limit: int = 100
    ) -> list[dict[str, Any]]:
        self.initialize()
        with self._transaction() as connection:
            rows = connection.execute(
                """
                SELECT sequence_id, payload_json
                FROM persistent_events
                WHERE sequence_id > %s
                ORDER BY sequence_id
                LIMIT %s
                """,
                (int(sequence_id), max(1, min(500, int(limit)))),
            ).fetchall()
        events = []
        for row in rows:
            payload = row["payload_json"]
            event = json.loads(payload) if isinstance(payload, str) else dict(payload)
            event["_sequence_id"] = int(row["sequence_id"])
            events.append(event)
        return events

    def prune_events(self, *, retention_hours: int = 48) -> int:
        self.initialize()
        cutoff = _utc_now() - timedelta(hours=max(1, retention_hours))
        with self._transaction() as connection:
            cursor = connection.execute(
                "DELETE FROM persistent_events WHERE created_at < %s",
                (cutoff,),
            )
        return int(cursor.rowcount)

    def claim(
        self,
        worker_id: str,
        *,
        queue_name: str = "default",
        lease_seconds: int = 300,
    ) -> ClaimedJob | None:
        self.initialize()
        self.recover_expired_leases()
        now = _utc_now()
        lease_expires = now + timedelta(seconds=max(1, lease_seconds))
        with self._transaction() as connection:
            row = connection.execute(
                """
                SELECT * FROM persistent_jobs
                WHERE queue_name = %s
                    AND status = 'queued'
                    AND available_at <= %s
                ORDER BY priority DESC, available_at, created_at
                FOR UPDATE SKIP LOCKED
                LIMIT 1
                """,
                (queue_name, now),
            ).fetchone()
            if row is None:
                return None
            claimed = connection.execute(
                """
                UPDATE persistent_jobs
                SET status = 'running',
                    attempts = attempts + 1,
                    lease_owner = %s,
                    lease_expires_at = %s,
                    heartbeat_at = %s,
                    started_at = COALESCE(started_at, %s),
                    updated_at = %s
                WHERE id = %s AND status = 'queued'
                RETURNING *
                """,
                (worker_id, lease_expires, now, now, now, row["id"]),
            ).fetchone()
        item = self._job_row(claimed)
        return ClaimedJob(
            id=item["id"],
            queue_name=item["queue_name"],
            job_name=item["job_name"],
            payload=item["payload"],
            attempts=item["attempts"],
            max_attempts=item["max_attempts"],
            lease_owner=worker_id,
            lease_expires_at=_as_datetime(item["lease_expires_at"]) or lease_expires,
        )

    def heartbeat(self, job_id: str, worker_id: str, *, lease_seconds: int) -> bool:
        self.initialize()
        now = _utc_now()
        expires = now + timedelta(seconds=max(1, lease_seconds))
        with self._transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE persistent_jobs
                SET heartbeat_at = %s, lease_expires_at = %s, updated_at = %s
                WHERE id = %s AND status = 'running' AND lease_owner = %s
                """,
                (now, expires, now, job_id, worker_id),
            )
        return cursor.rowcount == 1

    def complete(self, job_id: str, worker_id: str, result: dict[str, Any]) -> bool:
        self.initialize()
        now = _utc_now()
        encoded = _json(result)
        with self._transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE persistent_jobs
                SET status = 'succeeded',
                    result_json = %s::jsonb,
                    lease_owner = NULL,
                    lease_expires_at = NULL,
                    heartbeat_at = NULL,
                    finished_at = %s,
                    updated_at = %s
                WHERE id = %s AND status = 'running' AND lease_owner = %s
                """,
                (encoded, now, now, job_id, worker_id),
            )
        return cursor.rowcount == 1

    def fail(
        self,
        job_id: str,
        worker_id: str,
        error: str,
        *,
        retry_base_seconds: int = 10,
        retry_max_seconds: int = 600,
    ) -> dict[str, Any] | None:
        self.initialize()
        now = _utc_now()
        with self._transaction() as connection:
            row = connection.execute(
                """
                SELECT * FROM persistent_jobs
                WHERE id = %s
                    AND status = 'running'
                    AND lease_owner = %s
                """,
                (job_id, worker_id),
            ).fetchone()
            if row is None:
                return None
            item = dict(row)
            exhausted = int(item["attempts"]) >= int(item["max_attempts"])
            delay = min(
                max(1, int(retry_max_seconds)),
                max(1, int(retry_base_seconds))
                * (2 ** max(0, int(item["attempts"]) - 1)),
            )
            status = "failed" if exhausted else "queued"
            available_at = now if exhausted else now + timedelta(seconds=delay)
            updated = connection.execute(
                """
                UPDATE persistent_jobs
                SET status = %s,
                    available_at = %s,
                    last_error = %s,
                    lease_owner = NULL,
                    lease_expires_at = NULL,
                    heartbeat_at = NULL,
                    finished_at = %s,
                    updated_at = %s
                WHERE id = %s AND status = 'running' AND lease_owner = %s
                RETURNING *
                """,
                (
                    status,
                    available_at,
                    str(error)[:4000],
                    now if exhausted else None,
                    now,
                    job_id,
                    worker_id,
                ),
            ).fetchone()
            return self._job_row(updated)

    def retry(self, job_id: str) -> bool:
        self.initialize()
        now = _utc_now()
        with self._transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE persistent_jobs
                SET status = 'queued',
                    attempts = 0,
                    available_at = %s,
                    last_error = NULL,
                    result_json = NULL,
                    lease_owner = NULL,
                    lease_expires_at = NULL,
                    heartbeat_at = NULL,
                    started_at = NULL,
                    finished_at = NULL,
                    updated_at = %s
                WHERE id = %s AND status IN ('failed', 'cancelled')
                """,
                (now, now, job_id),
            )
        return cursor.rowcount == 1

    def cancel(self, job_id: str) -> bool:
        self.initialize()
        now = _utc_now()
        with self._transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE persistent_jobs
                SET status = 'cancelled',
                    lease_owner = NULL,
                    lease_expires_at = NULL,
                    heartbeat_at = NULL,
                    finished_at = %s,
                    updated_at = %s
                WHERE id = %s AND status = 'queued'
                """,
                (now, now, job_id),
            )
        return cursor.rowcount == 1

    def list_jobs(
        self, *, status: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        self.initialize()
        limit = max(1, min(500, int(limit)))
        with self._transaction() as connection:
            if status:
                rows = connection.execute(
                    """
                    SELECT * FROM persistent_jobs
                    WHERE status = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (status, limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT * FROM persistent_jobs
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (limit,),
                ).fetchall()
        return [self._job_row(row) for row in rows]

    def health(self, *, worker_stale_seconds: int = 60) -> dict[str, Any]:
        self.initialize()
        self.reconcile_stale_workers(stale_after_seconds=worker_stale_seconds)
        now = _utc_now()
        recent_cutoff = now - timedelta(hours=24)
        with self._transaction() as connection:
            rows = connection.execute(
                """
                SELECT status, COUNT(*) AS count
                FROM persistent_jobs
                GROUP BY status
                """
            ).fetchall()
            schedule = connection.execute(
                """
                SELECT COUNT(*) AS count,
                       MIN(next_run_at) AS next_run_at,
                       (
                           SELECT COUNT(*)
                           FROM persistent_schedules
                           WHERE manually_paused = TRUE
                       ) AS manually_paused
                FROM persistent_schedules
                WHERE enabled = TRUE
                """
            ).fetchone()
            migration = connection.execute(
                "SELECT MAX(version) AS version FROM qingshu_schema_migrations"
            ).fetchone()
            queue_metrics = connection.execute(
                """
                SELECT
                    COUNT(*) FILTER (
                        WHERE status = 'queued' AND available_at <= %s
                    ) AS ready,
                    COUNT(*) FILTER (
                        WHERE status = 'queued' AND available_at > %s
                    ) AS delayed,
                    COUNT(*) FILTER (
                        WHERE status = 'queued' AND attempts > 0
                    ) AS retrying,
                    MIN(available_at) FILTER (
                        WHERE status = 'queued' AND available_at <= %s
                    ) AS oldest_ready_at,
                    COUNT(*) FILTER (
                        WHERE status = 'running' AND lease_expires_at < %s
                    ) AS expired_running,
                    COUNT(*) FILTER (
                        WHERE status = 'succeeded' AND finished_at >= %s
                    ) AS succeeded_24h,
                    COUNT(*) FILTER (
                        WHERE status = 'failed' AND finished_at >= %s
                    ) AS failed_24h
                FROM persistent_jobs
                """,
                (now, now, now, now, recent_cutoff, recent_cutoff),
            ).fetchone()
            workers = connection.execute(
                """
                SELECT status, COUNT(*) AS count
                FROM persistent_workers
                GROUP BY status
                """
            ).fetchall()
            counters = connection.execute(
                "SELECT name, value FROM operational_counters"
            ).fetchall()
        counts = {
            status: 0 for status in (*ACTIVE_JOB_STATUSES, *TERMINAL_JOB_STATUSES)
        }
        counts.update({str(row["status"]): int(row["count"]) for row in rows})
        worker_counts = {"active": 0, "offline": 0, "stopped": 0}
        worker_counts.update({str(row["status"]): int(row["count"]) for row in workers})
        counter_values = {str(row["name"]): int(row["value"]) for row in counters}
        oldest_ready = _as_datetime(queue_metrics["oldest_ready_at"])
        recent_succeeded = int(queue_metrics["succeeded_24h"] or 0)
        recent_failed = int(queue_metrics["failed_24h"] or 0)
        recent_terminal = recent_succeeded + recent_failed
        lag_seconds = (
            max(0.0, (now - oldest_ready).total_seconds()) if oldest_ready else 0.0
        )
        queue_status = "ok"
        if int(queue_metrics["expired_running"] or 0) > 0 or recent_failed > 0:
            queue_status = "attention"
        if int(queue_metrics["ready"] or 0) > 0 and worker_counts["active"] == 0:
            queue_status = "degraded"
        if lag_seconds > max(60, worker_stale_seconds * 2):
            queue_status = "degraded"
        return {
            "status": queue_status,
            "backend": "postgresql",
            "schema_version": int(migration["version"] or 0),
            "counts": counts,
            "queue": {
                "ready": int(queue_metrics["ready"] or 0),
                "delayed": int(queue_metrics["delayed"] or 0),
                "retrying": int(queue_metrics["retrying"] or 0),
                "oldest_ready_at": oldest_ready.isoformat() if oldest_ready else None,
                "oldest_ready_age_seconds": round(lag_seconds, 3),
                "expired_running": int(queue_metrics["expired_running"] or 0),
                "succeeded_24h": recent_succeeded,
                "failed_24h": recent_failed,
                "failure_rate_24h": round(recent_failed / recent_terminal, 6)
                if recent_terminal
                else 0.0,
            },
            "workers": worker_counts,
            "counters": {
                "lease_recoveries_total": counter_values.get(
                    "lease_recoveries_total", 0
                ),
                "dead_local_worker_recoveries_total": counter_values.get(
                    "dead_local_worker_recoveries_total", 0
                ),
            },
            "connection_pool": dict(self._pool.get_stats()) if self._pool else {},
            "enabled_schedules": int(schedule["count"] or 0),
            "manually_paused_schedules": int(schedule["manually_paused"] or 0),
            "next_run_at": (
                _as_datetime(schedule["next_run_at"]).isoformat()
                if schedule["next_run_at"]
                else None
            ),
            "checked_at": now.isoformat(),
        }

    @staticmethod
    def _job_row(row: Any) -> dict[str, Any]:
        item = dict(row)
        payload = item.pop("payload_json", {})
        result = item.pop("result_json", None)
        item["id"] = str(item["id"])
        item["payload"] = json.loads(payload) if isinstance(payload, str) else payload
        item["result"] = (
            json.loads(result) if isinstance(result, str) and result else result
        )
        for key in (
            "available_at",
            "lease_expires_at",
            "heartbeat_at",
            "created_at",
            "updated_at",
            "started_at",
            "finished_at",
        ):
            value = item.get(key)
            if isinstance(value, datetime):
                item[key] = value.isoformat()
        return item

    @staticmethod
    def _worker_row(row: Any) -> dict[str, Any]:
        item = dict(row)
        metadata = item.pop("metadata_json", {})
        item["metadata"] = (
            json.loads(metadata) if isinstance(metadata, str) else metadata
        )
        for key in (
            "started_at",
            "last_heartbeat_at",
            "stopped_at",
        ):
            value = item.get(key)
            if isinstance(value, datetime):
                item[key] = value.isoformat()
        return item

    @staticmethod
    def _schedule_row(row: Any) -> dict[str, Any]:
        item = dict(row)
        payload = item.pop("payload_json", {})
        item["payload"] = json.loads(payload) if isinstance(payload, str) else payload
        item["enabled"] = bool(item.get("enabled"))
        item["configured_enabled"] = bool(item.get("configured_enabled"))
        item["manually_paused"] = bool(item.get("manually_paused"))
        for key in ("next_run_at", "created_at", "updated_at", "paused_at"):
            value = item.get(key)
            if isinstance(value, datetime):
                item[key] = value.isoformat()
        return item


__all__ = ["ClaimedJob", "OperationalDatabase"]
