# 后端生产可靠性 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 AI 研究改造为 Redis 驱动、SQLite 持久化且可恢复的异步工作流，并完成会话、运维接口、追踪和 schema 加固。

**Architecture:** SQLite 是任务状态、幂等性、预算、审计和 outbox 的权威存储；Redis Stream 只负责派发。API 在事务内写 run、task 与 outbox；worker 使用 CAS 领取并执行任务，启动时补投递 outbox 和恢复过期租约。

**Tech Stack:** Python 3.11+, FastAPI, SQLite WAL, Redis Streams, Docker Compose, pytest。

## Global Constraints

- 所有 schema 变更使用前向 SQL migration；不删除既有列或表。
- 审计不记录 API key、session token、完整 prompt、上传内容或完整持仓。
- 模型调用前必须检查取消、运行时限、尝试次数和预算。
- 读取 API 保持兼容；创建研究任务新增 `Idempotency-Key`。
- 每项生产代码先有失败测试，再实现最小行为。

## File Structure

- `app/migrations/0005_research_task_reliability.sql`：run 扩展、任务、outbox、审计和限流表。
- `app/services/research_queue.py`：Redis 发布、outbox 补发、租约领取和恢复。
- `app/services/research_worker.py`：worker 进程入口与 AI 研究任务分派。
- `app/services/ai_research.py`：CAS 状态机、取消、预算与任务处理器。
- `app/db.py`：原子提交、CAS、会话轮换、限流和审计数据访问。
- `app/main.py`：请求追踪、运维权限、研究 API 与会话策略。
- `app/config.py`、`.env.example`、`docker-compose.yml`：Redis/worker 配置。
- `tests/test_research_queue.py`、`tests/test_ai_research.py`、`tests/test_api.py`、`tests/test_db_migrations.py`：对应的行为和升级测试。

---

### Task 1: 持久化任务和 CAS 契约

**Files:**
- Create: `app/migrations/0005_research_task_reliability.sql`
- Modify: `app/db.py`
- Modify: `tests/test_db_migrations.py`
- Create: `tests/test_research_queue.py`

**Interfaces:**
- Produces `Database.create_ai_research_submission(...) -> tuple[dict[str, Any], bool]`。
- Produces `Database.transition_ai_research_run(..., expected_version, allowed_execution_statuses) -> dict[str, Any] | None`。

- [ ] **Step 1: Write the failing tests**

```python
def test_research_submission_replays_same_idempotency_key(database, user, conversation):
    first, replay = database.create_ai_research_submission(
        user_id=user["id"], conversation_id=conversation["id"],
        idempotency_key="key-1", request_fingerprint="same", targets=[],
        question="q", snapshot={}, dimensions={}, workspace_path=user["workspace_path"],
    )
    second, replay_again = database.create_ai_research_submission(
        user_id=user["id"], conversation_id=conversation["id"],
        idempotency_key="key-1", request_fingerprint="same", targets=[],
        question="q", snapshot={}, dimensions={}, workspace_path=user["workspace_path"],
    )
    assert first["run_id"] == second["run_id"]
    assert replay is False and replay_again is True
```

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_research_queue.py::test_research_submission_replays_same_idempotency_key -v`

Expected: FAIL because the database method does not exist.

- [ ] **Step 3: Implement minimal migration and database API**

```sql
ALTER TABLE ai_research_runs ADD COLUMN execution_status TEXT NOT NULL DEFAULT 'pending';
ALTER TABLE ai_research_runs ADD COLUMN version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE ai_research_runs ADD COLUMN idempotency_key TEXT;
ALTER TABLE ai_research_runs ADD COLUMN request_fingerprint TEXT;
ALTER TABLE ai_research_runs ADD COLUMN cancel_requested_at TEXT;
ALTER TABLE ai_research_runs ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 0;
CREATE UNIQUE INDEX idx_ai_research_idempotency
ON ai_research_runs(user_id, idempotency_key) WHERE idempotency_key IS NOT NULL;
```

Create `research_tasks`, `research_task_outbox`, `provider_call_audits` and `rate_limit_windows`. Submit generic run, research run, task and outbox in one SQLite transaction. CAS SQL must include `version=?` and allowed old `execution_status` values, then increment version. The existing `status` enum remains compatible and terminal states are mirrored only when representable.

- [ ] **Step 4: Verify GREEN**

Run: `pytest tests/test_db_migrations.py tests/test_research_queue.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add app/db.py app/migrations/0005_research_task_reliability.sql tests/test_db_migrations.py tests/test_research_queue.py && git commit -m "feat: persist research task state and CAS transitions"`

### Task 2: Redis outbox and worker recovery

**Files:**
- Create: `app/services/research_queue.py`
- Create: `app/services/research_worker.py`
- Modify: `app/config.py`, `docker-compose.yml`, `.env.example`, `tests/test_research_queue.py`

**Interfaces:**
- Consumes pending outbox records from Task 1.
- Produces `ResearchQueue.publish_pending(limit: int) -> int` and `ResearchWorker.run_once() -> int`.

- [ ] **Step 1: Write the failing test**

```python
def test_outbox_is_republished_after_redis_failure(database, fake_redis):
    task = create_pending_task(database)
    queue = ResearchQueue(database, fake_redis)
    fake_redis.fail_next_add = True
    assert queue.publish_pending() == 0
    assert database.pending_research_outbox_count() == 1
    assert queue.publish_pending() == 1
    assert fake_redis.messages == [{"task_id": task["id"]}]
```

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_research_queue.py::test_outbox_is_republished_after_redis_failure -v`

Expected: FAIL because `ResearchQueue` does not exist.

- [ ] **Step 3: Implement minimal queue and worker**

`publish_pending` sends `{"task_id": task_id}` with Redis `XADD` and marks outbox published only after success. `run_once` republishes outbox, recovers expired SQLite leases, reads one consumer-group record, atomically claims it, dispatches a handler, and ACKs only after terminal SQLite update. Add `redis_url`, worker poll and lease settings. Compose adds `redis:7-alpine` with AOF and a `qingshu-worker` service.

- [ ] **Step 4: Verify GREEN**

Run: `pytest tests/test_research_queue.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add app/services/research_queue.py app/services/research_worker.py app/config.py docker-compose.yml .env.example tests/test_research_queue.py && git commit -m "feat: add recoverable Redis research worker"`

### Task 3: Idempotent AI research API, limits and cancellation

**Files:**
- Modify: `app/services/ai_research.py`, `app/main.py`, `tests/test_ai_research.py`, `tests/test_research_queue.py`

**Interfaces:**
- Consumes Task 1 database submission/CAS and Task 2 queue.
- Produces `POST /me/ai-research/runs/{run_id}/cancel`.

- [ ] **Step 1: Write the failing tests**

```python
def test_create_research_requires_idempotency_key(client):
    response = client.post("/me/ai-research/runs", json=valid_research_payload())
    assert response.status_code == 400

def test_cancelled_research_is_never_executed(client, app):
    created = client.post("/me/ai-research/runs", headers={"Idempotency-Key": "key-1"}, json=valid_research_payload())
    cancelled = client.post(f"/me/ai-research/runs/{created.json()['run_id']}/cancel")
    assert cancelled.json()["status"] == "cancelled"
```

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_ai_research.py -k "idempotency or cancelled" -v`

Expected: FAIL because the header and cancellation endpoint are absent.

- [ ] **Step 3: Implement minimal queued lifecycle**

Remove `BackgroundTasks` from AI research routes. Require 16-128 ASCII `Idempotency-Key`, derive a SHA-256 fingerprint from user, question, targets and conversation, and return replayed run on same fingerprint. A different payload for the same key returns 409. Worker-only handlers enforce one running run per user, max three attempts, cancellation, elapsed-time and budget checks before each model call. Retryable gateway timeout/429/5xx moves to `retry_wait`; policy, validation, permission and budget errors fail without retry.

- [ ] **Step 4: Verify GREEN**

Run: `pytest tests/test_ai_research.py tests/test_research_queue.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add app/services/ai_research.py app/main.py tests/test_ai_research.py tests/test_research_queue.py && git commit -m "feat: queue idempotent AI research runs"`

### Task 4: Session, operations authorization and trace audit

**Files:**
- Modify: `app/config.py`, `app/db.py`, `app/main.py`, `tests/test_api.py`, `tests/test_research_queue.py`

**Interfaces:**
- Produces `require_operations_token(request) -> None`, `Database.rotate_user_session(...)`, `Database.consume_rate_limit(...)`, and `Database.record_provider_call_audit(...)`.

- [ ] **Step 1: Write the failing tests**

```python
def test_system_diagnostics_require_operations_token(client):
    assert client.get("/system/background").status_code == 401
    assert client.get("/system/background", headers={"Authorization": "Bearer test-ops"}).status_code == 200

def test_legacy_claim_route_is_not_routable(client):
    assert client.post("/sessions/claim", json={"user_id": str(uuid4())}).status_code == 404
```

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_api.py -k "system_diagnostics or legacy_claim" -v`

Expected: FAIL because diagnostics are public and legacy claim still exists.

- [ ] **Step 3: Implement security controls**

Delete the legacy claim model and route. Use constant-time comparison for `OPERATIONS_BEARER_TOKEN` on `/system/*`. Add request middleware that propagates or creates UUID `X-Request-ID` and emits redacted structured JSON logs. In production, reject startup unless Secure cookie and operations token are configured. Rotate session token after sensitive contact updates. Use fixed SQLite windows for create/retry/cancel limits and return 429 with `Retry-After`; write provider/model audits with only metadata, duration, usage, cost and redacted error.

- [ ] **Step 4: Verify GREEN**

Run: `pytest tests/test_api.py tests/test_research_queue.py -k "system or session or rate or trace or audit" -v`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add app/config.py app/db.py app/main.py tests/test_api.py tests/test_research_queue.py && git commit -m "feat: secure operations and trace research execution"`

### Task 5: Authoritative migration baseline and release verification

**Files:**
- Modify: `app/db.py`, `app/migrations/0001_schema_baseline.sql`, `tests/test_db_migrations.py`, `README.md`, `VERIFICATION.md`

**Interfaces:**
- Produces `Database.initialize()` that only bootstraps `schema_migrations` and applies ordered SQL files.

- [ ] **Step 1: Write the failing migration test**

```python
def test_clean_database_schema_is_created_from_sql_migrations_only(tmp_path, monkeypatch):
    database = Database(tmp_path / "app.db", tmp_path / "workspaces")
    monkeypatch.setattr(database, "_legacy_schema_script", lambda: (_ for _ in ()).throw(AssertionError()))
    database.initialize()
    with database.connect() as connection:
        assert connection.execute("SELECT 1 FROM users").fetchone() is None
        assert connection.execute("SELECT 1 FROM research_tasks").fetchone() is None
```

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_db_migrations.py::test_clean_database_schema_is_created_from_sql_migrations_only -v`

Expected: FAIL because baseline tables are inline in `Database.initialize`.

- [ ] **Step 3: Implement authoritative SQL baseline**

Move the existing initial DDL exactly to `0001_schema_baseline.sql`. Retain only migration-ledger creation and ordered migration application in `Database.initialize`. Preserve upgraded databases: existing `0001_schema_baseline` records skip baseline; no destructive rollback migration is created. Document Compose, Redis, worker health and SQLite backup/forward-fix release procedure.

- [ ] **Step 4: Verify release slice**

Run: `pytest tests/test_db_migrations.py tests/test_research_queue.py tests/test_ai_research.py tests/test_api.py -v`

Expected: PASS. Run `docker compose config`; then start redis/API/worker, submit a task, restart worker, and verify a single terminal completion.

- [ ] **Step 5: Commit**

Run: `git add app/db.py app/migrations/0001_schema_baseline.sql tests/test_db_migrations.py README.md VERIFICATION.md && git commit -m "feat: make schema migrations authoritative"`

## Plan self-review

Task 1 covers migration, idempotency and CAS. Task 2 covers durable delivery and recovery. Task 3 covers queued, cancellable, bounded AI research. Task 4 covers session, operations access, limits and audit. Task 5 makes migrations authoritative and defines release verification. All destructive database changes are excluded; old read responses remain compatible.
