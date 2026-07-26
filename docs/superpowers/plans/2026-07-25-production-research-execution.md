# Production Research Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move AI research from request-bound background work to a durable, multi-worker execution path with shared session/cache infrastructure and traceable bounded resource use.

**Architecture:** The web process writes an idempotent research run, task and outbox in one transaction and returns immediately. A dedicated worker consumes Redis Stream messages, leases tasks from the database, executes the existing research service and writes terminal state; Redis provides session cache, distributed coordination and cross-instance status events. PostgreSQL is the production database target while SQLite remains explicitly supported for local development tests.

**Tech Stack:** Python 3.11, FastAPI, Pydantic, PostgreSQL, Redis Streams/PubSub, Docker Compose, pytest.

## Global Constraints

- Never execute model, web-search, or evidence snapshot work in the HTTP request path.
- Preserve existing API routes and response fields while adding task status, idempotency and trace fields.
- All user-private cache keys include \`user_id\`; public market cache keys include source/data-version/freshness scope.
- State changes use an expected-version compare-and-set update; retries are only for explicitly recoverable failures.
- Production deployment must force secure cookies and must not expose system diagnostics without operations authorization.
- Do not add payment, brokerage, membership or US-equity capabilities.
- Database schema changes are forward-only migrations; no destructive migration in this release.

---

### Task 1: Runtime configuration and dependency boundaries

**Files:**
- Modify: \`pyproject.toml\`
- Modify: \`app/config.py\`
- Modify: \`.env.example\`
- Modify: \`docker-compose.yml\`
- Modify: \`Dockerfile\`
- Modify: \`app/db.py\`
- Create: \`app/db_postgres.py\`
- Create: \`scripts/migrate_sqlite_to_postgres.py\`
- Create: \`app/services/redis_client.py\`
- Test: \`tests/test_runtime_configuration.py\`
- Test: \`tests/test_database_backend_contract.py\`

**Interfaces:**
- Consumes: \`Settings.from_env()\` and the current single \`qingshu-agent\` Compose service.
- Produces: \`Settings.redis_url\`, \`Settings.database_url\`, \`Settings.research_worker_concurrency\`, \`Settings.session_cache_seconds\`, \`Settings.production_mode\`, \`create_database(settings)\`, and \`create_redis_client(settings)\`.

- [ ] **Step 1: Write the failing configuration tests**

\`\`\`python
def test_production_requires_secure_cookie_and_redis(monkeypatch):
    monkeypatch.setenv("PRODUCTION_MODE", "true")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "false")
    with pytest.raises(ValueError, match="SESSION_COOKIE_SECURE"):
        Settings.from_env()

def test_local_mode_uses_noop_redis_when_not_configured(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    settings = Settings.from_env()
    assert create_redis_client(settings).is_available is False
\`\`\`

- [ ] **Step 2: Run the tests to verify they fail**

Run: \`pytest tests/test_runtime_configuration.py -v\`

Expected: FAIL because the production checks and Redis client factory do not exist.

- [ ] **Step 3: Add configuration, Redis dependency and Compose services**

\`\`\`python
@dataclass(frozen=True)
class RedisClient:
    client: Any | None
    is_available: bool

def create_redis_client(settings: Settings) -> RedisClient:
    if not settings.redis_url:
        return RedisClient(client=None, is_available=False)
    return RedisClient(client=redis.Redis.from_url(settings.redis_url), is_available=True)
\`\`\`

Add pinned \`redis\` and \`psycopg\` dependencies, \`postgres\`, \`redis\`, \`web\`, and \`worker\` Compose services, and environment variables for URLs, worker concurrency, user concurrency, session cache TTL and production mode. Keep SQLite/no-Redis behavior for local test fixtures only.

- [ ] **Step 4: Run the configuration tests to verify they pass**

Run: \`pytest tests/test_runtime_configuration.py -v\`

Expected: PASS.

- [ ] **Step 5: Commit the isolated configuration change**

\`\`\`bash
git add pyproject.toml app/config.py app/services/redis_client.py .env.example docker-compose.yml Dockerfile tests/test_runtime_configuration.py
git commit -m "feat: add production runtime configuration"
\`\`\`

### Task 2: Durable submission and asynchronous worker execution

**Files:**
- Modify: \`app/db.py\`
- Modify: \`app/services/ai_research.py\`
- Modify: \`app/services/research_queue.py\`
- Modify: \`app/services/research_worker.py\`
- Create: \`app/services/research_dispatcher.py\`
- Create: \`app/worker.py\`
- Modify: \`app/main.py\`
- Test: \`tests/test_research_submission.py\`
- Test: \`tests/test_research_worker.py\`

**Interfaces:**
- Consumes: \`Database.create_ai_research_submission\`, \`ResearchQueue.publish_pending\`, existing \`AIResearchService\` prompt/execution methods.
- Produces: \`ResearchDispatcher.submit(...) -> dict[str, Any]\`, \`ResearchWorker.run_once() -> int\`, \`python -m app.worker\`, and \`POST /me/ai-research/runs\` returning a pending run without evidence-building in the route.

- [ ] **Step 1: Write failing submission tests**

\`\`\`python
def test_submit_returns_pending_without_building_evidence(dispatcher, service):
    service.create.assert_not_called()
    run = dispatcher.submit(user_id="u1", conversation_id="c1", targets=[{"symbol": "300750.SZ", "name": "宁德时代"}], question="研究问题", idempotency_key="k-00000001")
    assert run["execution_status"] == "pending"
    service.create.assert_not_called()

def test_duplicate_submission_returns_same_run(dispatcher):
    first = dispatcher.submit(..., idempotency_key="k-00000002")
    second = dispatcher.submit(..., idempotency_key="k-00000002")
    assert second["run_id"] == first["run_id"]
\`\`\`

- [ ] **Step 2: Run the submission tests to verify they fail**

Run: \`pytest tests/test_research_submission.py -v\`

Expected: FAIL because the route currently calls \`AIResearchService.create()\` and \`BackgroundTasks\` directly.

- [ ] **Step 3: Implement a dispatcher and worker task handler**

\`\`\`python
class ResearchDispatcher:
    def submit(self, *, user_id: str, conversation_id: str, targets: list[dict[str, str]], question: str, idempotency_key: str) -> dict[str, Any]:
        fingerprint = fingerprint_research_request(targets, question, conversation_id)
        run, duplicate = self.database.create_ai_research_submission(...)
        if not duplicate:
            self.queue.publish_pending(limit=1)
        return run

def handle_research_task(task: dict[str, Any]) -> None:
    run = database.transition_ai_research_run(... execution_status="running")
    if run is None:
        return
    ai_research.execute_main_from_task(task["user_id"], task["run_id"], task["id"])
\`\`\`

Move snapshot construction into \`execute_main_from_task\`; change the route to validate input, create/reuse a conversation, call the dispatcher and return 202. Start no Worker thread in the FastAPI process. \`app.worker\` owns consumer creation and its bounded loop.

- [ ] **Step 4: Run focused tests and the existing queue tests**

Run: \`pytest tests/test_research_submission.py tests/test_research_worker.py tests/test_research_queue.py -v\`

Expected: PASS.

- [ ] **Step 5: Commit the durable submission slice**

\`\`\`bash
git add app/db.py app/main.py app/services/ai_research.py app/services/research_queue.py app/services/research_worker.py app/services/research_dispatcher.py app/worker.py tests/test_research_submission.py tests/test_research_worker.py
git commit -m "feat: dispatch research through durable workers"
\`\`\`

### Task 3: Leases, retry, cancellation, per-user concurrency and budget admission

**Files:**
- Modify: \`app/db.py\`
- Modify: \`app/migrations/0005_research_task_reliability.sql\`
- Modify: \`app/services/research_worker.py\`
- Create: \`app/services/research_admission.py\`
- Modify: \`app/main.py\`
- Test: \`tests/test_research_admission.py\`
- Test: \`tests/test_research_task_state.py\`

**Interfaces:**
- Consumes: durable task rows and \`rate_limit_windows\`.
- Produces: \`ResearchAdmission.check(user_id, action)\`, \`Database.reclaim_expired_research_tasks()\`, \`Database.retry_research_task(...)\`, \`Database.request_research_cancel(...)\`, \`POST /me/ai-research/runs/{run_id}/cancel\`.

- [ ] **Step 1: Write failing state-machine tests**

\`\`\`python
def test_expired_lease_is_requeued_with_bounded_backoff(database):
    task = make_leased_task(database, lease_expires_at="2000-01-01T00:00:00+00:00", attempt_count=1, max_attempts=3)
    assert database.reclaim_expired_research_tasks() == 1
    refreshed = database.get_research_task(task["id"])
    assert refreshed["status"] == "retry_wait"

def test_running_limit_rejects_new_admission(database):
    make_active_tasks(database, user_id="u1", count=2)
    with pytest.raises(ResearchCapacityExceeded):
        ResearchAdmission(database, max_concurrent_per_user=2).check("u1", "ai_research")
\`\`\`

- [ ] **Step 2: Run them to verify they fail**

Run: \`pytest tests/test_research_task_state.py tests/test_research_admission.py -v\`

Expected: FAIL because there is no reclaim, bounded retry or admission service.

- [ ] **Step 3: Implement explicit transitions and cancellation checks**

\`\`\`python
RECOVERABLE_ERRORS = (TimeoutError, ConnectionError, ProviderRateLimited)

def retry_or_finish(task: dict[str, Any], error: Exception) -> None:
    if isinstance(error, RECOVERABLE_ERRORS) and task["attempt_count"] < task["max_attempts"]:
        database.retry_research_task(task["id"], retry_after_seconds=backoff(task["attempt_count"]))
    else:
        database.finish_research_task(task["id"], "failed", type(error).__name__)
\`\`\`

Implement task cancellation as a persisted request; check it before each expensive external call and before result writes. Use atomic SQL conditions for all task/run transitions. Enforce an active-task count plus rolling request/cost budget before task creation. Store retry failure reason, attempt count and next availability.

- [ ] **Step 4: Run focused state and concurrency tests**

Run: \`pytest tests/test_research_task_state.py tests/test_research_admission.py tests/test_research_worker.py -v\`

Expected: PASS.

- [ ] **Step 5: Commit the execution-control slice**

\`\`\`bash
git add app/db.py app/migrations/0005_research_task_reliability.sql app/services/research_worker.py app/services/research_admission.py app/main.py tests/test_research_task_state.py tests/test_research_admission.py tests/test_research_worker.py
git commit -m "feat: bound research execution and user concurrency"
\`\`\`

### Task 4: Session cache, secure session lifecycle and cross-instance events

**Files:**
- Modify: \`app/db.py\`
- Create: \`app/services/session_store.py\`
- Modify: \`app/main.py\`
- Modify: \`app/services/background.py\`
- Test: \`tests/test_session_store.py\`
- Test: \`tests/test_session_security.py\`

**Interfaces:**
- Consumes: existing opaque session token database table and optional Redis client.
- Produces: \`SessionStore.resolve(token)\`, \`SessionStore.rotate(user_id)\`, \`SessionStore.revoke(token)\`, \`SessionStore.touch_later(session_id)\` and a Redis Pub/Sub-backed research status event adapter.

- [ ] **Step 1: Write failing session-cache and rotation tests**

\`\`\`python
def test_second_session_lookup_uses_cache_without_touch_write(store, database):
    token = create_session(database)["token"]
    assert store.resolve(token)["id"]
    database.reset_call_history()
    assert store.resolve(token)["id"]
    assert database.call_count("get_user_by_session") == 0

def test_logout_evicts_cached_session(store, database):
    token = create_session(database)["token"]
    store.resolve(token)
    store.revoke(token)
    assert store.resolve(token) is None
\`\`\`

- [ ] **Step 2: Run them to verify they fail**

Run: \`pytest tests/test_session_store.py tests/test_session_security.py -v\`

Expected: FAIL because every request currently calls and writes through \`Database.get_user_by_session\`.

- [ ] **Step 3: Implement opaque-token cache and secure lifecycle**

\`\`\`python
class SessionStore:
    def resolve(self, token: str | None) -> dict[str, Any] | None:
        cached = self.cache.get(self._key(token))
        if cached is not None:
            return cached
        user = self.database.get_user_by_session(token, touch=False)
        if user is not None:
            self.cache.set(self._key(token), user, ttl=self.ttl_seconds)
            self.touch_later(user["session_id"])
        return user
\`\`\`

Cache only the opaque-token lookup and user/session public metadata; never cache raw token values in logs. Batch \`last_seen_at\` updates at a configured interval. Delete cache keys on logout/revoke; rotate session after authentication. Delete legacy claim route and require secure cookies in production. Replace in-process research-event delivery with Redis Pub/Sub while retaining a local fallback only for tests.

- [ ] **Step 4: Run focused session tests**

Run: \`pytest tests/test_session_store.py tests/test_session_security.py -v\`

Expected: PASS.

- [ ] **Step 5: Commit session and event infrastructure**

\`\`\`bash
git add app/db.py app/main.py app/services/session_store.py app/services/background.py tests/test_session_store.py tests/test_session_security.py
git commit -m "feat: cache secure sessions across web instances"
\`\`\`

### Task 5: Trace/audit wiring, protected operations endpoints and release verification

**Files:**
- Create: \`app/services/observability.py\`
- Modify: \`app/main.py\`
- Modify: \`app/services/ai_research.py\`
- Modify: \`app/services/research_worker.py\`
- Modify: \`app/services/research_queue.py\`
- Modify: \`README.md\`
- Test: \`tests/test_observability.py\`
- Test: \`tests/test_operations_auth.py\`

**Interfaces:**
- Consumes: \`provider_call_audits\`, research task lifecycle and HTTP requests.
- Produces: \`TraceContext\`, \`ProviderAuditRecorder\`, \`X-Request-Id\` response header, authenticated \`/ops/*\` diagnostics.

- [ ] **Step 1: Write failing observability tests**

\`\`\`python
def test_research_provider_call_is_audited_with_trace(database, worker):
    worker.handle(task_with_trace("trace-123"))
    audit = database.latest_provider_audit(run_id=task["run_id"])
    assert audit["trace_id"] == "trace-123"
    assert audit["operation"] == "llm_completion"

def test_system_diagnostics_require_operations_permission(client):
    assert client.get("/system/background").status_code == 404
    assert client.get("/ops/background", headers=ops_headers()).status_code == 200
\`\`\`

- [ ] **Step 2: Run the tests to verify they fail**

Run: \`pytest tests/test_observability.py tests/test_operations_auth.py -v\`

Expected: FAIL because there is no trace middleware/audit recorder and system endpoints are public.

- [ ] **Step 3: Implement trace propagation and audited external calls**

\`\`\`python
@app.middleware("http")
async def request_trace(request: Request, call_next):
    request.state.trace_id = request.headers.get("X-Request-Id") or str(uuid4())
    response = await call_next(request)
    response.headers["X-Request-Id"] = request.state.trace_id
    return response
\`\`\`

Add a trace id to task payloads, record provider/model duration, error type, token usage and cost in \`provider_call_audits\`, and propagate the id in task events. Remove public \`/system/*\`; expose only a minimal authenticated operations route with an explicit configured operations identity/role.

- [ ] **Step 4: Run focused tests and complete backend regression**

Run: \`pytest tests/test_observability.py tests/test_operations_auth.py tests/test_research_submission.py tests/test_research_task_state.py tests/test_session_store.py -v\`

Expected: PASS.

Run: \`pytest -q\`

Expected: all repository tests pass; investigate and fix any failures without skipping tests.

- [ ] **Step 5: Validate deployment artifacts and commit**

Run: \`docker compose config\`

Expected: Compose renders \`postgres\`, \`redis\`, \`web\`, and \`worker\` services without unresolved variables.

\`\`\`bash
git add app/services/observability.py app/main.py app/services/ai_research.py app/services/research_worker.py app/services/research_queue.py README.md tests/test_observability.py tests/test_operations_auth.py
git commit -m "feat: trace and protect research operations"
\`\`\`

## Self-review

Coverage: Task 1 supplies deployable runtime dependencies and safe production configuration. Task 2 removes slow work from HTTP and connects the durable queue. Task 3 supplies retries, CAS, cancellation and per-user concurrency/budget control. Task 4 removes per-request session writes and makes sessions/events multi-instance safe. Task 5 adds traceability, cost logging, protected diagnostics and full verification.

No placeholders: all changed modules, public interfaces, tests, commands and expected outcomes are specified. The plan intentionally does not claim an arbitrary throughput target; worker and per-user concurrency are configuration-driven and must be load-tested against the selected model/provider quotas.
