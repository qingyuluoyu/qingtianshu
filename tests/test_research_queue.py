from __future__ import annotations

from app.db import Database


class FakeRedis:
    def __init__(self) -> None:
        self.fail_next_add = False
        self.messages: list[dict[str, str]] = []

    def xadd(self, stream_name: str, fields: dict[str, str]) -> str:
        assert stream_name == "qingshu:research"
        if self.fail_next_add:
            self.fail_next_add = False
            raise ConnectionError("redis unavailable")
        self.messages.append(fields)
        return "1-0"

    def xgroup_create(self, *args, **kwargs) -> None:
        return None

    def xreadgroup(self, *args, **kwargs):
        if not self.messages:
            return []
        message = self.messages.pop(0)
        return [("qingshu:research", [("1-0", message)])]

    def xack(self, stream_name: str, group_name: str, message_id: str) -> int:
        assert (stream_name, group_name, message_id) == (
            "qingshu:research",
            "qingshu-research-workers",
            "1-0",
        )
        return 1


def test_research_submission_replays_same_idempotency_key(tmp_path):
    database = Database(tmp_path / "app.db", tmp_path / "workspaces")
    database.initialize()
    user = database.create_user("research queue user")
    conversation = database.create_conversation(user["id"], "research")
    payload = {
        "user_id": user["id"],
        "conversation_id": conversation["id"],
        "idempotency_key": "key-000000000001",
        "request_fingerprint": "same-request",
        "targets": [],
        "question": "research question",
        "snapshot": {},
        "dimensions": {},
        "workspace_path": user["workspace_path"],
    }

    first, first_replay = database.create_ai_research_submission(**payload)
    second, second_replay = database.create_ai_research_submission(**payload)

    assert first["run_id"] == second["run_id"]
    assert first_replay is False
    assert second_replay is True


def test_research_run_transition_requires_expected_version(tmp_path):
    database = Database(tmp_path / "app.db", tmp_path / "workspaces")
    database.initialize()
    user = database.create_user("research cas user")
    conversation = database.create_conversation(user["id"], "research")
    run, _ = database.create_ai_research_submission(
        user_id=user["id"],
        conversation_id=conversation["id"],
        idempotency_key="key-000000000002",
        request_fingerprint="cas-request",
        targets=[],
        question="research question",
        snapshot={},
        dimensions={},
        workspace_path=user["workspace_path"],
    )

    updated = database.transition_ai_research_run(
        user_id=user["id"],
        run_id=run["run_id"],
        expected_version=run["version"],
        allowed_execution_statuses=("pending",),
        execution_status="running",
    )
    stale = database.transition_ai_research_run(
        user_id=user["id"],
        run_id=run["run_id"],
        expected_version=run["version"],
        allowed_execution_statuses=("pending",),
        execution_status="cancelled",
    )

    assert updated is not None
    assert updated["execution_status"] == "running"
    assert stale is None


def test_outbox_is_republished_after_redis_failure(tmp_path):
    from app.services.research_queue import ResearchQueue

    database = Database(tmp_path / "app.db", tmp_path / "workspaces")
    database.initialize()
    user = database.create_user("outbox user")
    conversation = database.create_conversation(user["id"], "research")
    run, _ = database.create_ai_research_submission(
        user_id=user["id"],
        conversation_id=conversation["id"],
        idempotency_key="key-000000000003",
        request_fingerprint="outbox-request",
        targets=[],
        question="research question",
        snapshot={},
        dimensions={},
        workspace_path=user["workspace_path"],
    )
    fake_redis = FakeRedis()
    queue = ResearchQueue(database, fake_redis)
    fake_redis.fail_next_add = True

    assert queue.publish_pending() == 0
    assert database.pending_research_outbox_count() == 1
    assert queue.publish_pending() == 1
    assert fake_redis.messages == [{"task_id": run["task_id"]}]


def test_outbox_handles_redis_py_connection_errors(tmp_path):
    from redis.exceptions import ConnectionError as RedisConnectionError

    from app.services.research_queue import ResearchQueue

    database = Database(tmp_path / "app.db", tmp_path / "workspaces")
    database.initialize()
    user = database.create_user("redis error user")
    conversation = database.create_conversation(user["id"], "research")
    database.create_ai_research_submission(
        user_id=user["id"],
        conversation_id=conversation["id"],
        idempotency_key="key-redis-error-0001",
        request_fingerprint="redis-error-request",
        targets=[],
        question="research question",
        snapshot={},
        dimensions={},
        workspace_path=user["workspace_path"],
    )

    class BrokenRedis:
        def xadd(self, *_args, **_kwargs):
            raise RedisConnectionError("redis unavailable")

    assert ResearchQueue(database, BrokenRedis()).publish_pending() == 0
    assert database.pending_research_outbox_count() == 1


def test_worker_claims_task_executes_handler_and_acks_stream(tmp_path):
    from app.services.research_queue import ResearchQueue
    from app.services.research_worker import ResearchWorker

    database = Database(tmp_path / "app.db", tmp_path / "workspaces")
    database.initialize()
    user = database.create_user("worker user")
    conversation = database.create_conversation(user["id"], "research")
    run, _ = database.create_ai_research_submission(
        user_id=user["id"],
        conversation_id=conversation["id"],
        idempotency_key="key-000000000004",
        request_fingerprint="worker-request",
        targets=[],
        question="research question",
        snapshot={},
        dimensions={},
        workspace_path=user["workspace_path"],
    )
    fake_redis = FakeRedis()
    queue = ResearchQueue(database, fake_redis)
    executed: list[str] = []
    worker = ResearchWorker(
        database, queue, fake_redis, "worker-1", lambda task: executed.append(task["id"])
    )

    assert worker.run_once() == 1
    assert executed == [run["task_id"]]
    assert database.get_research_task(run["task_id"])["status"] == "completed"


def test_worker_retries_recoverable_failure_then_completes(tmp_path):
    from app.services.research_queue import ResearchQueue
    from app.services.research_worker import RecoverableResearchError, ResearchWorker

    database = Database(tmp_path / "app.db", tmp_path / "workspaces")
    database.initialize()
    user = database.create_user("retry worker user")
    conversation = database.create_conversation(user["id"], "research")
    run, _ = database.create_ai_research_submission(
        user_id=user["id"],
        conversation_id=conversation["id"],
        idempotency_key="key-000000000005",
        request_fingerprint="retry-request",
        targets=[],
        question="research question",
        snapshot={},
        dimensions={},
        workspace_path=user["workspace_path"],
    )
    fake_redis = FakeRedis()
    queue = ResearchQueue(database, fake_redis)
    attempts = 0

    def handler(task):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RecoverableResearchError("temporary provider failure")

    worker = ResearchWorker(
        database,
        queue,
        fake_redis,
        "worker-retry",
        handler,
        retry_base_seconds=0,
    )

    assert worker.run_once() == 1
    retrying = database.get_research_task(run["task_id"])
    assert retrying["status"] == "retry_wait"
    assert retrying["attempt_count"] == 1
    assert retrying["last_error"] == "temporary provider failure"
    assert database.pending_research_outbox_count() == 1

    assert worker.run_once() == 1
    completed = database.get_research_task(run["task_id"])
    assert completed["status"] == "completed"
    assert completed["attempt_count"] == 2


def test_expired_lease_is_requeued_and_can_be_reclaimed(tmp_path):
    database = Database(tmp_path / "app.db", tmp_path / "workspaces")
    database.initialize()
    user = database.create_user("lease recovery user")
    conversation = database.create_conversation(user["id"], "research")
    run, _ = database.create_ai_research_submission(
        user_id=user["id"],
        conversation_id=conversation["id"],
        idempotency_key="key-000000000006",
        request_fingerprint="lease-recovery-request",
        targets=[],
        question="research question",
        snapshot={},
        dimensions={},
        workspace_path=user["workspace_path"],
    )
    claimed = database.claim_research_task(
        run["task_id"], "crashed-worker", lease_seconds=-1
    )

    assert claimed is not None
    assert database.reclaim_expired_research_tasks() == 1
    recovered = database.get_research_task(run["task_id"])
    assert recovered["status"] == "retry_wait"
    assert recovered["lease_owner"] is None
    assert database.pending_research_outbox_count() == 1
    assert database.claim_research_task(run["task_id"], "worker-2") is not None


def test_pending_task_can_be_cancelled_without_execution(tmp_path):
    from app.services.research_queue import ResearchQueue
    from app.services.research_worker import ResearchWorker

    database = Database(tmp_path / "app.db", tmp_path / "workspaces")
    database.initialize()
    user = database.create_user("cancel queued user")
    conversation = database.create_conversation(user["id"], "research")
    run, _ = database.create_ai_research_submission(
        user_id=user["id"],
        conversation_id=conversation["id"],
        idempotency_key="key-000000000007",
        request_fingerprint="cancel-request",
        targets=[],
        question="research question",
        snapshot={},
        dimensions={},
        workspace_path=user["workspace_path"],
    )
    cancelled = database.request_ai_research_cancellation(user["id"], run["run_id"])
    fake_redis = FakeRedis()
    executed: list[str] = []
    worker = ResearchWorker(
        database,
        ResearchQueue(database, fake_redis),
        fake_redis,
        "worker-cancel",
        lambda task: executed.append(task["id"]),
    )

    assert cancelled is not None
    assert cancelled["execution_status"] == "cancelled"
    assert database.get_research_task(run["task_id"])["status"] == "cancelled"
    assert worker.run_once() == 0
    assert executed == []


def test_cancellation_requested_during_handler_wins_over_success(tmp_path):
    from app.services.research_queue import ResearchQueue
    from app.services.research_worker import ResearchWorker

    database = Database(tmp_path / "app.db", tmp_path / "workspaces")
    database.initialize()
    user = database.create_user("cooperative cancel user")
    conversation = database.create_conversation(user["id"], "research")
    run, _ = database.create_ai_research_submission(
        user_id=user["id"],
        conversation_id=conversation["id"],
        idempotency_key="key-000000000008",
        request_fingerprint="cooperative-cancel-request",
        targets=[],
        question="research question",
        snapshot={},
        dimensions={},
        workspace_path=user["workspace_path"],
    )
    fake_redis = FakeRedis()

    def request_cancel(_task):
        database.request_ai_research_cancellation(user["id"], run["run_id"])

    worker = ResearchWorker(
        database,
        ResearchQueue(database, fake_redis),
        fake_redis,
        "worker-cancel-running",
        request_cancel,
    )

    assert worker.run_once() == 1
    assert database.get_research_task(run["task_id"])["status"] == "cancelled"
    assert database.get_ai_research_run(user["id"], run["run_id"])[
        "execution_status"
    ] == "cancelled"


def test_only_lease_owner_can_heartbeat_task(tmp_path):
    database = Database(tmp_path / "app.db", tmp_path / "workspaces")
    database.initialize()
    user = database.create_user("heartbeat user")
    conversation = database.create_conversation(user["id"], "research")
    run, _ = database.create_ai_research_submission(
        user_id=user["id"],
        conversation_id=conversation["id"],
        idempotency_key="key-000000000009",
        request_fingerprint="heartbeat-request",
        targets=[],
        question="research question",
        snapshot={},
        dimensions={},
        workspace_path=user["workspace_path"],
    )
    database.claim_research_task(run["task_id"], "worker-owner", lease_seconds=2)

    assert database.heartbeat_research_task(
        run["task_id"], "worker-owner", lease_seconds=30
    )
    assert not database.heartbeat_research_task(
        run["task_id"], "worker-other", lease_seconds=30
    )
    task = database.get_research_task(run["task_id"])
    assert task["heartbeat_at"]
    assert task["lease_owner"] == "worker-owner"


def test_absolute_task_timeout_prevents_late_execution(tmp_path):
    database = Database(tmp_path / "app.db", tmp_path / "workspaces")
    database.initialize()
    user = database.create_user("timeout user")
    conversation = database.create_conversation(user["id"], "research")
    run, _ = database.create_ai_research_submission(
        user_id=user["id"],
        conversation_id=conversation["id"],
        idempotency_key="key-000000000010",
        request_fingerprint="timeout-request",
        targets=[],
        question="research question",
        snapshot={},
        dimensions={},
        workspace_path=user["workspace_path"],
        timeout_seconds=1,
    )
    with database.connect() as connection:
        connection.execute(
            "UPDATE research_tasks SET created_at = ? WHERE id = ?",
            ("2000-01-01T00:00:00+00:00", run["task_id"]),
        )

    assert database.expire_timed_out_research_tasks() == 1
    assert database.get_research_task(run["task_id"])["status"] == "expired"
    assert (
        database.get_ai_research_run(user["id"], run["run_id"])[
            "execution_status"
        ]
        == "expired"
    )
    assert database.claim_research_task(run["task_id"], "late-worker") is None
