# Stock Score Performance and Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the stock score page return existing public snapshots without waiting for upstream providers, refresh data through the existing PostgreSQL/Redis/Worker topology, and improve the five-factor comparison layout and chart readability.

**Architecture:** Add a durable public-data refresh task contract that follows the existing research outbox and Redis Stream pattern while remaining semantically separate from AI research runs. Web endpoints read the latest persisted snapshot, enqueue one idempotent refresh when data is missing or stale, and return immediately; the existing Worker container consumes both research and public-data streams. The frontend renders each module independently and uses a larger radar plus explanatory factor cards.

**Tech Stack:** Python 3.12, FastAPI, existing `Database` abstraction, PostgreSQL/SQLite-compatible migrations, Redis Streams, pytest, vanilla JavaScript, Canvas, CSS.

## Global Constraints

- Do not change the five-factor formula or `financial_factor_v1.0`.
- Do not add a second Worker container or a second cache implementation.
- Preserve existing response fields and add compatible `cache` and `refresh` metadata.
- Web requests must not wait for Yahoo, Tushare, or a full industry rebuild.
- Public market and score snapshots may be shared across users; private research and position data may not use these keys.
- Missing snapshots return `warming`; they must not return zeroes or fabricated values.
- Cache-hit server response target is 300ms; this is a validation target, not an unverified production SLO.
- Use versioned migrations and expand-only schema changes.

---

## File Map

- `app/migrations/0008_public_data_refresh_tasks.sql`: durable refresh task and outbox schema.
- `app/db.py`: atomic idempotent task creation, claim, retry, completion, and outbox access.
- `app/services/data_refresh_queue.py`: Redis Stream publisher and worker using the existing outbox pattern.
- `app/services/stock_snapshot_refresh.py`: quote, K-line, and industry refresh handlers plus cache-state response helpers.
- `app/research_worker_main.py`: run research and public-data consumers in the same Worker process.
- `app/main.py`: construct the refresh service and expose nonblocking score-page refresh behavior.
- `app/services/stock_dashboard.py`: cached-only score-card and K-line read path.
- `app/services/industry_comparison.py`: expose cached packet reads and queue-oriented refresh entrypoint.
- `app/static/high-fidelity-demo.html`: factor-card explanatory structure.
- `app/static/high-fidelity-demo.js`: module states, refresh polling, chart label positioning.
- `app/static/high-fidelity-demo.css`: larger radar, two-column factor cards, responsive layout.
- `tests/test_data_refresh_queue.py`: durable task, idempotency, lease, retry, and worker tests.
- `tests/test_stock_dashboard.py`: cached-only and warming response tests.
- `tests/test_industry_comparison.py`: nonblocking refresh contract tests.
- `tests/test_stock_score_frontend.py`: layout and copy contract tests.

### Task 1: Durable public-data refresh task

**Files:**
- Create: `app/migrations/0008_public_data_refresh_tasks.sql`
- Create: `app/services/data_refresh_queue.py`
- Modify: `app/db.py`
- Create: `tests/test_data_refresh_queue.py`

**Interfaces:**
- Produces: `Database.create_data_refresh_task(kind, key, payload, request_id, trace_id) -> tuple[dict, bool]`
- Produces: `Database.claim_data_refresh_task(task_id, worker_id, lease_seconds) -> dict | None`
- Produces: `DataRefreshQueue.publish_pending(limit=100) -> int`
- Produces: `DataRefreshWorker.run_once() -> int`

- [ ] **Step 1: Write migration and database failing tests**

```python
def test_data_refresh_task_is_idempotent(database):
    first, reused = database.create_data_refresh_task(
        kind="stock_quote",
        key="stock-quote:300750.SZ:2026-07-25",
        payload={"symbol": "300750.SZ"},
        request_id="req-1",
        trace_id="trace-1",
    )
    second, second_reused = database.create_data_refresh_task(
        kind="stock_quote",
        key="stock-quote:300750.SZ:2026-07-25",
        payload={"symbol": "300750.SZ"},
        request_id="req-2",
        trace_id="trace-2",
    )
    assert reused is False
    assert second_reused is True
    assert second["id"] == first["id"]


def test_only_one_worker_can_claim_refresh_task(database):
    task, _ = create_task(database)
    assert database.claim_data_refresh_task(task["id"], "worker-a", 60)
    assert database.claim_data_refresh_task(task["id"], "worker-b", 60) is None
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
pytest tests/test_data_refresh_queue.py -q
```

Expected: FAIL because the migration, database methods, queue, and worker do not exist.

- [ ] **Step 3: Add expand-only schema**

Create `data_refresh_tasks` with:

```sql
CREATE TABLE data_refresh_tasks (
    id TEXT PRIMARY KEY,
    task_kind TEXT NOT NULL CHECK(task_kind IN ('stock_quote', 'stock_kline', 'industry_score')),
    idempotency_key TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('pending', 'leased', 'retry_wait', 'completed', 'failed')),
    payload_json TEXT NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    available_at TEXT NOT NULL,
    lease_owner TEXT,
    lease_expires_at TEXT,
    request_id TEXT,
    trace_id TEXT,
    last_error_type TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE UNIQUE INDEX idx_data_refresh_active_key
ON data_refresh_tasks(idempotency_key)
WHERE status IN ('pending', 'leased', 'retry_wait');
```

Add `data_refresh_task_outbox` with one row per task and stream name `qingshu:data-refresh`.

- [ ] **Step 4: Implement atomic task and outbox methods**

Use one database transaction to:

1. Return an existing active task for the same idempotency key.
2. Insert the task and outbox row when no active task exists.
3. Claim only `pending` or due `retry_wait` tasks whose lease is absent or expired.
4. Apply bounded exponential retry and final failure.
5. Store structured error type separately from the summary.

The method must return decoded `payload`, never raw `payload_json`.

- [ ] **Step 5: Implement the queue and worker**

```python
class DataRefreshQueue:
    STREAM_NAME = "qingshu:data-refresh"

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
                    delay = min(
                        self.retry_max_seconds,
                        self.retry_base_seconds
                        * (2 ** max(0, int(task["attempt_count"]) - 1)),
                    )
                    self.database.retry_data_refresh_task(
                        task_id, type(exc).__name__, str(exc), delay
                    )
                except Exception as exc:
                    self.database.finish_data_refresh_task(
                        task_id, "failed", type(exc).__name__, str(exc)
                    )
                else:
                    self.database.finish_data_refresh_task(
                        task_id, "completed", None, None
                    )
                self.redis_client.xack(
                    stream_name, self.GROUP_NAME, message_id
                )
                processed += 1
        return processed
```

Use the same Redis exception handling and lease semantics as `ResearchQueue` and `ResearchWorker`. Do not import AI research models into this module.

- [ ] **Step 6: Run focused tests and verify GREEN**

Run:

```powershell
pytest tests/test_data_refresh_queue.py tests/test_db_migrations.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add app/migrations/0008_public_data_refresh_tasks.sql app/db.py app/services/data_refresh_queue.py tests/test_data_refresh_queue.py tests/test_db_migrations.py
git commit -m "feat(queue): add durable public data refresh tasks"
```

### Task 2: Cached-only stock snapshots and Worker refresh handlers

**Files:**
- Create: `app/services/stock_snapshot_refresh.py`
- Modify: `app/providers/market.py`
- Modify: `app/services/stock_dashboard.py`
- Modify: `app/services/industry_comparison.py`
- Modify: `tests/test_stock_dashboard.py`
- Modify: `tests/test_industry_comparison.py`

**Interfaces:**
- Consumes: `Database.create_data_refresh_task(kind, key, payload, request_id, trace_id)`
- Produces: `YahooMarketProvider.read_cached_history(symbol, range_name, interval, allow_stale=True) -> dict | None`
- Produces: `StockSnapshotRefreshService.read_score_card(symbol) -> dict`
- Produces: `StockSnapshotRefreshService.read_kline(symbol, period, limit, adjust) -> dict`
- Produces: `StockSnapshotRefreshService.execute(task) -> None`

- [ ] **Step 1: Write failing cached-read tests**

```python
def test_score_card_does_not_call_upstream_when_stale_snapshot_exists(
    snapshot_service, blocking_market_provider
):
    started = time.monotonic()
    packet = snapshot_service.read_score_card("300750.SZ")
    assert time.monotonic() - started < 0.3
    assert blocking_market_provider.calls == 0
    assert packet["cache"]["state"] == "stale"
    assert packet["refresh"]["status"] == "queued"


def test_score_card_without_snapshot_returns_warming(empty_snapshot_service):
    packet = empty_snapshot_service.read_score_card("300750.SZ")
    assert packet["status"] == "warming"
    assert packet["quote"]["price"] is None
    assert packet["refresh"]["status"] == "queued"
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
pytest tests/test_stock_dashboard.py tests/test_industry_comparison.py -q
```

Expected: the new cached-only behavior tests fail because current methods call providers synchronously.

- [ ] **Step 3: Add provider cached-read API**

```python
def read_cached_history(
    self,
    symbol: str,
    range_name: str = "1y",
    interval: str = "1d",
    *,
    allow_stale: bool = True,
) -> dict[str, Any] | None:
    cache_key = f"yahoo:{symbol}:{range_name}:{interval}"
    cached = self.database.get_cache(cache_key, allow_stale=allow_stale)
    if cached is None:
        return None
    sanitized, _ = self._sanitize_history(cached, symbol=symbol, interval=interval)
    return sanitized
```

This method must never call `http_get`.

- [ ] **Step 4: Implement snapshot reads**

`read_score_card()` reads stored fundamentals and cached quote history only. `read_kline()` reads the provider’s persistent history cache before the process-local cache.

Both responses add:

```python
"cache": {
    "state": "fresh" | "stale" | "warming" | "refresh_failed",
    "refreshing": bool,
    "generatedAt": str | None,
    "dataAsOf": str | None,
},
"refresh": {
    "taskId": str | None,
    "status": "idle" | "queued" | "running" | "failed",
    "lastErrorType": str | None,
}
```

If a refresh is required, create an idempotent task and return immediately.

- [ ] **Step 5: Implement Worker handlers**

```python
def execute(self, task: dict[str, Any]) -> None:
    kind = task["task_kind"]
    payload = task["payload"]
    if kind == "stock_quote":
        self.market_provider.fetch_history(payload["symbol"], "1d", "1m")
    elif kind == "stock_kline":
        self.market_provider.fetch_history(
            payload["symbol"], payload["range"], payload["interval"]
        )
    elif kind == "industry_score":
        self.industry_comparison.refresh_packet(payload["symbol"])
    else:
        raise ValueError("unsupported_data_refresh_kind")
```

Classify provider/network/timeouts as recoverable; classify unsupported symbols and payload validation as deterministic failures.

- [ ] **Step 6: Run focused tests and verify GREEN**

Run:

```powershell
pytest tests/test_stock_dashboard.py tests/test_industry_comparison.py tests/test_providers.py -q
```

Expected: PASS with no synchronous provider calls in cached-read tests.

- [ ] **Step 7: Commit**

```powershell
git add app/providers/market.py app/services/stock_dashboard.py app/services/industry_comparison.py app/services/stock_snapshot_refresh.py tests/test_stock_dashboard.py tests/test_industry_comparison.py tests/test_providers.py
git commit -m "feat(score): serve stock snapshots with background refresh"
```

### Task 3: Wire Web and the existing Worker container

**Files:**
- Modify: `app/main.py`
- Modify: `app/research_worker_main.py`
- Modify: `tests/test_api.py`
- Modify: `tests/test_runtime_configuration.py`

**Interfaces:**
- Consumes: `StockSnapshotRefreshService.read_score_card`, `read_kline`, `execute`
- Produces: existing score-card, K-line, and industry endpoints with compatible refresh metadata

- [ ] **Step 1: Write failing API tests**

```python
def test_score_page_endpoint_returns_before_blocking_provider(
    score_client_with_blocking_provider,
):
    started = time.monotonic()
    response = score_client_with_blocking_provider.get(
        "/api/v1/stocks/300750.SZ/score-card"
    )
    assert time.monotonic() - started < 0.3
    assert response.status_code == 200
    assert response.json()["refresh"]["status"] in {"idle", "queued"}


def test_manual_refresh_enqueues_instead_of_rebuilding(
    score_client_with_fake_tushare, fake_tushare
):
    response = score_client_with_fake_tushare.get(
        "/api/v1/stocks/300750.SZ/industry-comparison?refresh=true"
    )
    assert response.status_code in {200, 202}
    assert fake_tushare.calls == 0
    assert response.json()["refresh"]["status"] == "queued"
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
pytest tests/test_api.py -k "score_page or manual_refresh" -q
```

Expected: FAIL because the routes still invoke synchronous services.

- [ ] **Step 3: Wire services and routes**

- Construct `DataRefreshQueue` and `StockSnapshotRefreshService` from the existing database and Redis runtime.
- Store them on `app.state`.
- Route score-card and K-line reads through cached-only methods.
- Keep existing field names and exception mappings.
- When Redis is unavailable in local development, persist the outbox and return `queued`; production readiness already requires Redis.

- [ ] **Step 4: Consume both streams in one Worker process**

Create one `DataRefreshWorker` beside the existing `ResearchWorker`. The outer loop calls each worker’s `run_once()` and touches the same heartbeat file after both polls.

Do not create another Docker Compose service.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run:

```powershell
pytest tests/test_api.py tests/test_runtime_configuration.py tests/test_research_queue.py tests/test_data_refresh_queue.py -q
```

Expected: PASS; existing research task behavior remains unchanged.

- [ ] **Step 6: Commit**

```powershell
git add app/main.py app/research_worker_main.py tests/test_api.py tests/test_runtime_configuration.py
git commit -m "feat(runtime): process score refreshes in shared worker"
```

### Task 4: Five-factor layout and chart readability

**Files:**
- Modify: `app/static/high-fidelity-demo.html`
- Modify: `app/static/high-fidelity-demo.css`
- Modify: `app/static/high-fidelity-demo.js`
- Create: `tests/test_stock_score_frontend.py`

**Interfaces:**
- Consumes: existing factor objects with `label`, `score`, `state`, `coveragePct`
- Produces: `industryFactorDescription(key) -> string`
- Produces: `industryFactorBand(score) -> string`

- [ ] **Step 1: Write failing frontend contract tests**

```python
def test_five_factor_layout_has_descriptions_and_two_column_grid():
    js = JS_PATH.read_text(encoding="utf-8")
    css = CSS_PATH.read_text(encoding="utf-8")
    assert "function industryFactorDescription" in js
    assert "function industryFactorBand" in js
    assert "grid-template-columns:repeat(2,minmax(0,1fr))" in css
    assert "grid-template-columns:minmax(360px,420px) minmax(0,1fr)" in css


def test_comparison_chart_clamps_positive_and_negative_labels():
    js = JS_PATH.read_text(encoding="utf-8")
    assert "clampChartLabelY" in js
    assert "zeroY" in js
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
pytest tests/test_stock_score_frontend.py -q
```

Expected: FAIL because descriptions, bands, and the new layout do not exist.

- [ ] **Step 3: Implement explanatory cards**

Add deterministic mappings:

```javascript
function industryFactorBand(score){
  if(score>=80)return '行业领先';
  if(score>=65)return '相对较强';
  if(score>=35)return '行业中游';
  if(score>=20)return '相对较弱';
  return '行业靠后';
}

function industryFactorDescription(key){
  return {
    growth:'收入与利润增长相对同行的位置',
    valuation:'PE、PB等估值指标相对同行的位置',
    profitability:'ROE、ROIC和利润表现相对同行的位置',
    stability:'偿债能力、负债结构和盈利波动相关指标',
    efficiency:'资产周转、现金回收和经营投入效率'
  }[key] || '基于当前公式计算的同行相对位置';
}
```

Each rendered factor card contains a visible band, coverage, and description.

- [ ] **Step 4: Implement the desktop and mobile grid**

Desktop:

```css
.industry-factor-overview{
  grid-template-columns:minmax(360px,420px) minmax(0,1fr);
  align-items:stretch;
}
.industry-factor-radar canvas{height:320px}
.industry-factor-cards{
  grid-template-columns:repeat(2,minmax(0,1fr));
  align-content:stretch;
}
```

Mobile uses one column and a minimum 280px effective radar plot. Reduce radar axis and value fonts through chart options or the existing `radar()` implementation.

- [ ] **Step 5: Fix grouped-bar label placement**

Add `clampChartLabelY(value, min, max)` and apply it to both positive and negative labels. Keep a visible zero baseline and continue scaling each metric group independently.

- [ ] **Step 6: Run focused tests and syntax checks**

Run:

```powershell
pytest tests/test_stock_score_frontend.py tests/test_stock_dashboard.py -q
node --check app/static/high-fidelity-demo.js
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add app/static/high-fidelity-demo.html app/static/high-fidelity-demo.css app/static/high-fidelity-demo.js tests/test_stock_score_frontend.py
git commit -m "feat(ui): improve stock score comparison layout"
```

### Task 5: Performance, concurrency, regression, and visual verification

**Files:**
- Modify only when a failing verification identifies an in-scope defect.

**Interfaces:**
- Verifies all interfaces produced by Tasks 1–4.

- [ ] **Step 1: Run affected tests**

```powershell
pytest tests/test_data_refresh_queue.py tests/test_stock_dashboard.py tests/test_industry_comparison.py tests/test_providers.py tests/test_stock_score_frontend.py -q
```

Expected: PASS.

- [ ] **Step 2: Run API and full regressions**

```powershell
pytest tests/test_api.py -q
pytest -q --ignore=tests/test_api.py
```

Expected: PASS. Record any warning separately; do not suppress it.

- [ ] **Step 3: Run static validation**

```powershell
python -m compileall -q app tests
node --check app/static/high-fidelity-demo.js
git diff --check
```

Expected: exit code 0 for each command.

- [ ] **Step 4: Measure latency and deduplication**

Measure:

- fresh score snapshot;
- stale score snapshot;
- no snapshot;
- 20 concurrent requests for the same symbol;
- Worker completion followed by a fresh read.

Acceptance:

- all Web reads return without waiting for the 15-second provider timeout;
- fresh and stale local responses are below the 300ms target;
- 20 concurrent requests create one active idempotency task;
- provider call audit shows one refresh execution for the shared key.

- [ ] **Step 5: Browser verification**

At 1440×900 verify:

- radar plot is materially larger than the previous 310×245 area;
- all five cards include band, coverage, and definition;
- no empty 3+2 centered gap;
- grouped bars and labels remain inside the canvas.

At 390×844 verify:

- radar and cards form one column;
- no horizontal overflow;
- labels and descriptions are readable;
- refresh state does not cover existing data.

- [ ] **Step 6: Final commit if verification required fixes**

Stage only the concrete files changed while fixing a failed verification, then
run `git commit -m "fix(score): close performance and layout regressions"`.
Do not create an empty commit and do not stage unrelated dirty files.
