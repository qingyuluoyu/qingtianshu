# Stock Screen Market Snapshot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist and refresh a traceable market snapshot used by the transparent stock screener.

**Architecture:** `StockScreenerService` owns the canonical snapshot format because it owns the consuming calculation. `BackgroundScheduler` invokes a daily refresh only when the configured Tushare client exists. Existing legacy per-dataset snapshot reads remain a compatibility fallback.

**Tech Stack:** Python 3.11, pandas, PostgreSQL/SQLite Database abstraction, FastAPI background scheduler, pytest.

## Global Constraints

- No mock market data, no new frontend features, no database schema change.
- Preserve the `/me/stock-screener` API contract and existing legacy snapshot compatibility.
- Do not overwrite a stable snapshot after a failed or under-covered refresh.
- Do not expose provider credentials or raw provider exceptions to users.

---

### Task 1: Publish and read canonical screener snapshots

**Files:**
- Modify: `app/services/stock_screener.py`
- Test: `tests/test_stock_screener.py`

**Interfaces:**
- Produces: `StockScreenerService.refresh_persisted_market_snapshot()`.
- Consumes: `Database.start_tushare_sync_run`, `save_tushare_dataset_snapshot`, and `finish_tushare_sync_run`.

- [ ] **Step 1: Write failing tests**

```python
def test_published_market_snapshot_keeps_screener_usable_without_live_provider():
    publisher = StockScreenerService(FakeTushareClient(), database=app.state.database)
    assert publisher.refresh_persisted_market_snapshot()["published"] is True
    reader = StockScreenerService(None, database=app.state.database)
    assert reader.screen(profile="trend")["data_meta"]["source_mode"] == "persisted"
```

- [ ] **Step 2: Run the test and verify it fails because the method does not exist.**

Run: `python -m pytest -q tests/test_stock_screener.py -k published_market_snapshot`

- [ ] **Step 3: Implement the minimal publisher and canonical reader.**

```python
def refresh_persisted_market_snapshot(self) -> dict[str, Any]:
    frame, meta = self._build_snapshot()
    # Save only a complete `stock_screen_market/all` stable version.
```

- [ ] **Step 4: Run the focused tests and verify the persisted reader returns a stable contract.**

### Task 2: Schedule the refresh with bounded cost

**Files:**
- Modify: `app/config.py`
- Modify: `app/services/background.py`
- Modify: `app/main.py`
- Test: `tests/test_background.py`

**Interfaces:**
- Consumes: `StockScreenerService.refresh_persisted_market_snapshot()`.
- Produces: `stock_screener_market_snapshot_refresh` durable background job.

- [ ] **Step 1: Write failing scheduler tests**

```python
def test_stock_screener_snapshot_job_is_enabled_only_with_configured_provider():
    scheduler = build_scheduler(stock_screener=stub_with_client)
    assert "stock_screener_market_snapshot_refresh" in scheduler._job_functions()
```

- [ ] **Step 2: Run the focused scheduler test and verify it fails.**

- [ ] **Step 3: Add a daily bounded interval setting and schedule the task only when a client exists.**

- [ ] **Step 4: Run focused background tests.**

### Task 3: Verify production behavior and document deployment gate

**Files:**
- Modify: `docs/superpowers/specs/2026-08-07-stock-screen-market-snapshot-design.md`
- Test: `tests/test_stock_screener.py`, `tests/test_background.py`

- [ ] **Step 1: Run compile, affected tests, frontend build, and Docker production smoke.**
- [ ] **Step 2: Verify a real empty database returns 503 and an injected stable snapshot returns 200 without invoking a live full-market scan.**
- [ ] **Step 3: Record the required deployment variables: `TUSHARE_ENABLED=true`, a licensed `TUSHARE_TOKEN`, and enabled background workers.**
- [ ] **Step 4: Commit after all verification is green.**
