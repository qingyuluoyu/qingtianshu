# Formal Six-Page UI V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring the six authenticated React routes to the approved 11.pptx-derived financial-workbench hierarchy without changing financial contracts or introducing fake data.

**Architecture:** Retain the existing page adapters, query keys, authentication boundary, writeback state machines and real data rules. Change page composition through stable empty/loading/error scaffolds and shared shell primitives; each feature remains independently queryable so secondary failures cannot blank a page.

**Tech Stack:** React 19, TypeScript 5.7, React Router 7, TanStack Query 5, Vitest, Testing Library, Playwright, FastAPI.

## Global Constraints

- Execute visible work in the user-requested order 5 → 4 → 3 → 2 → 1; the safety snapshot and isolated worktree are prerequisite Task 0.
- Do not copy prices, scores, returns, funding flow or conclusions from 11.pptx.
- Do not change backend financial formulas, authentication contracts, database schema, SSE framing or `app/static`.
- Preserve `null`, empty, partial, stale, unavailable, 403, 404 and 409 as distinct states.
- Use red/green only with textual or signed financial meaning.
- Root layout must not overflow at 1440, 1280, 820 or 390; only dense tables may scroll horizontally.
- Every private query remains disabled until `authenticated === true`.
- No frontend fixture or Playwright `route.fulfill` may substitute for real release acceptance.

---

### Task 0: Protect Current State And Establish Isolation

**Files:**
- Existing snapshot commit: `17b713979c0e561a70e81cb77c941ef9fc4d5339`
- Worktree: `.worktrees/formal-six-page-ui`
- Branch: `codex/formal-six-page-ui-v1`

**Interfaces:**
- Consumes all nine uncommitted Today files from `codex/today-runtime-fix`.
- Produces a clean isolated branch without altering the source snapshot.

- [x] Export the pre-snapshot binary diff outside the repository.
- [x] Create `snapshot/formal-six-page-before-ui-20260807` and commit the preserved state.
- [x] Create the isolated worktree and verify `git status --short --branch` is clean.

### Task 5: Keep Advisor And Research Center Workbench Structure In Empty States

**Files:**
- Modify: `frontend/src/features/advisor/AdvisorPage.tsx`
- Modify: `frontend/src/features/advisor/AdvisorPage.module.css`
- Modify: `frontend/src/features/advisor/AdvisorPage.test.tsx`
- Modify: `frontend/src/features/research-center/ResearchCenterPage.tsx`
- Modify: `frontend/src/features/research-center/ResearchCenterPage.module.css`
- Modify: `frontend/src/features/research-center/ResearchCenterPage.test.tsx`

**Interfaces:**
- Advisor always produces `conversation sidebar | message column | evidence column` on desktop; evidence content remains `StructuredAnswer | ModuleState(empty)`.
- Research Center always produces `stock list | decision/change chain | next step` plus report/progress/outcome sections; empty data produces guidance, never synthetic records.

- [ ] **Step 1: Write failing advisor empty-layout assertions**

```tsx
expect(screen.getByRole("complementary", { name: "证据与候选写回" })).toBeVisible();
expect(screen.getByText("尚未形成可追溯的结构化分析")).toBeVisible();
```

- [ ] **Step 2: Write failing research-center stable-scaffold assertions**

```tsx
expect(screen.getByRole("region", { name: "研究股票" })).toBeVisible();
expect(screen.getByRole("region", { name: "判断、变化与处理" })).toBeVisible();
expect(screen.getByRole("region", { name: "下一步" })).toBeVisible();
expect(screen.getByText("尚未选择研究股票")).toBeVisible();
```

- [ ] **Step 3: Run focused tests and confirm the current conditional columns fail**

Run: `npm test -- --run src/features/advisor/AdvisorPage.test.tsx src/features/research-center/ResearchCenterPage.test.tsx`

- [ ] **Step 4: Render stable columns and true empty states**

Advisor must remove the `showDrawer` layout collapse. Research Center must replace the `stockEntries.length > 0` whole-workspace guard with per-module empty states. Existing queries, writes and 409 handling remain unchanged.

- [ ] **Step 5: Verify and commit**

Run: `npm test -- --run src/features/advisor src/features/research-center && npm run build`

Commit: `feat(workbench): stabilize advisor and research layouts`

### Task 4: Stabilize Watchlist And Stock Research Scaffolds

**Files:**
- Modify: `frontend/src/features/watchlist/WatchlistPage.tsx`
- Modify: `frontend/src/features/watchlist/WatchlistPage.module.css`
- Modify: `frontend/src/features/watchlist/WatchlistPage.test.tsx`
- Modify: `frontend/src/features/stock-research/StockResearchPage.tsx`
- Modify: `frontend/src/features/stock-research/StockResearchPage.module.css`
- Modify: `frontend/src/features/stock-research/StockResearchPage.test.tsx`

**Interfaces:**
- Watchlist keeps category/list/detail structure even with zero assets.
- Stock Research independently renders header, price module and research modules; a quote failure does not remove the research workspace.

- [ ] Add failing tests for an empty watchlist table scaffold and stock quote failure isolation.
- [ ] Run `npm test -- --run src/features/watchlist src/features/stock-research` and confirm failures.
- [ ] Implement layout-only changes; do not invent positions, cost, P&L, target price or score.
- [ ] Run focused tests and `npm run build`.
- [ ] Commit as `feat(workbench): stabilize watchlist and stock layouts`.

### Task 3: Repair Today Core Loading And Recompose Screening

**Files:**
- Modify: `frontend/src/features/today/TodayPage.tsx`
- Modify: `frontend/src/features/today/TodayComponents.tsx`
- Modify: `frontend/src/features/today/TodayPage.module.css`
- Modify: `frontend/src/features/today/TodayPage.test.tsx`
- Modify: `frontend/src/features/today/queries.ts`
- Modify: `frontend/src/features/screening/ScreeningPage.tsx`
- Modify: `frontend/src/features/screening/ScreeningPage.module.css`
- Modify: `frontend/src/features/screening/ScreeningPage.test.tsx`

**Interfaces:**
- Five-index base cards render independently from per-symbol history.
- Screening desktop produces `FilterBuilder | result workspace | candidate detail`; modes remain URL-exclusive.

- [ ] Add failing tests for five-index order, finite loading/error state and three-column screening landmarks.
- [ ] Run focused Today and Screening tests to confirm failures.
- [ ] Remove six-column assumptions, prevent secondary history from blocking base indices, and keep module-level errors finite.
- [ ] Move `FilterBuilder` into the left column and preserve real table/detail contracts.
- [ ] Verify with `npm test -- --run src/features/today src/features/screening`, build, 1440 screenshot and 390 overflow assertion.
- [ ] Commit as `feat(workbench): align today and screening hierarchy`.

### Task 2: Close The Shared Shell And Mobile Navigation

**Files:**
- Modify: `frontend/src/components/AppShell.tsx`
- Modify: `frontend/src/components/AppShell.module.css`
- Modify: `frontend/src/app/App.test.tsx`
- Reuse or create: `frontend/src/components/workbench/*`

**Interfaces:**
- Formal navigation exposes exactly six entries.
- `/market-data` remains routable but is absent from formal navigation.
- Mobile menu uses one navigation tree with `aria-expanded`, Escape close and route-change close.
- Header exposes semantic route titles and masked account fallback.

- [ ] Add failing tests for six entries, semantic title, 390px menu and focus restoration.
- [ ] Run `npm test -- --run src/app/App.test.tsx src/components` and confirm failures.
- [ ] Implement the shell without changing feature query behavior.
- [ ] Verify focused tests, full unit tests and build.
- [ ] Commit as `feat(workbench): close formal shell and mobile navigation`.

### Task 1: Real Cross-Page Release Acceptance

**Files:**
- Modify: `frontend/e2e/today.spec.ts`
- Create or modify: `frontend/e2e/formal-six-page.spec.ts`
- Create outside repository: `F:/tools/qingshu-formal-six-page-evidence/`

**Interfaces:**
- Uses real registration/session and candidate backend; no route mocks for auth, `/v1`, `/me`, `/events` or stock endpoints.
- Produces screenshots, console/network summaries, route summary and exact Git commit.

- [ ] Run `npm test` and `npm run build`.
- [ ] Run `python -m compileall -q app` and affected backend contract tests.
- [ ] Start isolated PostgreSQL UUID schema, FastAPI and current frontend candidate.
- [ ] Verify six routes at 1440x900 and 390x844, one SSE connection, zero root overflow and no permanent core loading.
- [ ] Save evidence outside the repository and run `git diff --check`.
- [ ] Commit only source/tests/docs as `test(frontend): verify formal six-page workbench`.

## Self-Review

- The plan preserves the richer current feature adapters and avoids wholesale merging the smaller divergent branch.
- Every visual change has a focused failing test before implementation.
- Empty states retain structure without introducing fake financial data.
- Task 1 is the release gate and cannot convert external provider errors into successful empty data.
