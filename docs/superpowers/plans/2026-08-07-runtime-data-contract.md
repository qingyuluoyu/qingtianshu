# 正式前端运行与数据合同收口 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the formal frontend run from one reproducible baseline, distinguish live/EOD/snapshot financial data, and prevent slow or unsafe user-triggered market scans before visual work resumes.

**Architecture:** The backend owns provider normalization, freshness semantics, and published market snapshots. The React client owns cancellation, bounded request states, and module-level presentation of the backend contract. A dedicated runtime manifest records the only candidate server/build used for verification.

**Tech Stack:** FastAPI, Python, pandas, PostgreSQL, React, TypeScript, TanStack Query, Vite, Vitest, Playwright.

## Global Constraints

- Do not use the old `5173` Vite process as verification evidence.
- TeaJoin credentials and StepFun credentials remain process-environment secrets only.
- Do not add mock financial data or convert missing values to zero.
- Do not start visual redesign until Tasks 1–4 pass their verification gates.
- Preserve existing authentication, user isolation, SSE and API paths.

---

### Task 1: Candidate runtime identity

**Files:**
- Create: `scripts/runtime_identity.py`
- Create: `tests/test_runtime_identity.py`
- Modify: runtime startup documentation only if an existing command needs the manifest.

**Produces:** a JSON-safe manifest with worktree path, commit, branch, frontend build marker, backend bind address and database schema name; no connection strings or secrets.

- [ ] Write a failing test proving secret-like environment values are excluded and the commit is recorded.
- [ ] Run `pytest -q tests/test_runtime_identity.py` and observe failure.
- [ ] Implement the smallest manifest writer/validator.
- [ ] Re-run the focused test and record the isolated runtime manifest.

### Task 2: Provider freshness contract

**Files:**
- Modify: `app/providers/tushare.py`
- Modify: `app/providers/market.py`
- Modify: `app/services/analysis.py`
- Test: `tests/test_tushare_provider.py`
- Test: `tests/test_market_provider.py`
- Test: `tests/test_analysis.py`

**Produces:** normalized metadata for source, market timestamp, fetched timestamp, granularity and status. TeaJoin calls have a real timeout and error classification. Cached provider fallbacks are marked stale.

- [ ] Write failing tests for a TeaJoin timeout classification and a stale cached response.
- [ ] Run each new focused test and confirm the expected failure.
- [ ] Implement timeout/error normalization without logging credentials.
- [ ] Implement one shared freshness normalizer used by live quotes, daily bars and snapshots.
- [ ] Run focused provider and analysis tests.

### Task 3: Read-only transparent-screener lifecycle

**Files:**
- Modify: `app/services/stock_screener.py`
- Modify: `app/services/background.py`
- Modify: `frontend/src/features/screening/api.ts`
- Modify: `frontend/src/features/screening/queries.ts`
- Test: `tests/test_stock_screener.py`
- Test: `tests/test_background.py`
- Test: `frontend/src/features/screening/queries.test.ts`

**Produces:** `/me/stock-screener` consumes only a published snapshot. It fails quickly with a typed unavailable status when no stable snapshot exists; only the durable background job performs a full TeaJoin refresh. The frontend cancels abandoned work and does not retry non-retryable failures.

- [ ] Write a failing backend test proving a user screen call does not invoke `_build_snapshot`.
- [ ] Run it and observe the current regression.
- [ ] Implement the minimal read-only behavior and typed `snapshot_not_ready` error.
- [ ] Write/execute frontend tests for timeout abort and no retry on the typed unavailable response.
- [ ] Run affected Python and Vitest suites.

### Task 4: Old-Li coverage and presentation contract

**Files:**
- Modify: `app/services/li_zong_strategy_service.py` only if coverage status is missing from the public response.
- Modify: `frontend/src/features/screening/adapters.ts`
- Modify: `frontend/src/features/screening/ScreeningPage.tsx`
- Test: `tests/test_li_zong_strategy.py`
- Test: `frontend/src/features/screening/adapters.test.ts`
- Test: `frontend/src/features/screening/ScreeningPage.test.tsx`

**Produces:** partial coverage cannot be visually represented as a completed full-market strategy outcome. All statuses expose latest market day and snapshot coverage.

- [ ] Write a failing API/adapter test for a partial run rendered as “not complete”.
- [ ] Run it and observe the failure.
- [ ] Implement the smallest compatible status mapping.
- [ ] Run the targeted backend and frontend tests.

### Task 5: Runtime validation gate

**Files:**
- Create outside Git: isolated runtime evidence directory.
- Modify: no product code unless a blocker from Tasks 1–4 is found.

- [ ] Run `python -m compileall -q app`.
- [ ] Run all affected backend tests and `npm test`, then `npm run build`.
- [ ] Start only the candidate backend/frontend with a disposable schema and write a runtime identity manifest.
- [ ] Verify TeaJoin EOD labeling, Tencent quote labeling, screener no-snapshot fast failure, and no user-triggered full-market scan.
- [ ] Mark UI work permitted only if every preceding gate has fresh evidence.
