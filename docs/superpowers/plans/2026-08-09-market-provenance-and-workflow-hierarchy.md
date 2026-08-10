# Market Provenance and Workflow Hierarchy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make public market modules traceable, align the screening and research-center pages with the Today information hierarchy, and verify the real frontend/backend path on the requested backend port 8020.

**Architecture:** Add only additive provenance fields to existing market responses, normalize them through the current adapters, and render a reusable metadata line without changing values, units, formulas, or endpoint versions. Keep each page's existing business components and URL state, adding semantic workflow landmarks and visual hierarchy around them. Use the existing isolated real-E2E runner before starting the local 8020/5174 pair.

**Tech Stack:** FastAPI, Python, React 19, TypeScript, TanStack Query, CSS Modules, Pytest, Vitest, Playwright.

## Global Constraints

- Do not change market formulas, A-share red/green semantics, units, provider selection, query enablement, or authentication contracts.
- Provenance labels must come from response data; do not invent a provider name in the UI.
- Backend response changes must be additive and remain compatible with old frontend payloads.
- Keep personal research queries disabled for anonymous users.
- Do not commit or reset the current dirty worktree.

### Task 1: Add traceable market provenance to public Today modules

**Files:**
- Modify: `tests/test_api.py`
- Modify: `app/services/analysis.py`
- Modify: `frontend/src/features/today/adapters.test.ts`
- Modify: `frontend/src/features/today/adapters.ts`
- Modify: `frontend/src/features/today/TodayPage.test.tsx`
- Modify: `frontend/src/features/today/TodayComponents.tsx`
- Modify: `frontend/src/features/today/TodayPage.module.css`

**Interfaces:**
- Backend adds `source: str | None` to `/markets/anomalies`; breadth and capital-flow retain their existing `source` fields.
- Frontend `Breadth`, `MarketAnomalies`, and `CapitalFlow` gain `source: string | null`; breadth also gains `fetchedAt: string | null`.
- UI renders `来源：<source> · 数据时间 <Asia/Shanghai time>` only when values are present, and retains explicit unavailable/stale states.

- [x] Add backend tests asserting the real breadth source passes through and anomalies inherit the breadth snapshot source.
- [x] Run the focused backend tests and confirm the anomaly source assertion fails. The project virtualenv used a damaged system Python, so the test was executed with the bundled Python plus the existing project site-packages.
- [x] Add the anomaly `source` field to both available and unavailable response shapes, taking available provenance from the provider payload.
- [x] Add adapter tests asserting source/time passthrough for breadth, anomalies, and capital flow.
- [x] Run the focused adapter test and confirm the new fields fail.
- [x] Parse only response-provided source/time fields; default missing provenance to `null`.
- [x] Add a Today rendering assertion that the three public modules show response-provided provenance.
- [x] Run the focused Today test and confirm it fails before rendering metadata.
- [x] Render compact provenance rows with no fabricated fallback provider.
- [x] Re-run the focused Python and frontend tests — backend 2 passed; frontend 25 passed.

### Task 2: Align screening and research workflows with the Today hierarchy

**Files:**
- Modify: `frontend/src/features/screening/ScreeningPage.test.tsx`
- Modify: `frontend/src/features/screening/ScreeningPage.tsx`
- Modify: `frontend/src/features/screening/ScreeningPage.module.css`
- Modify: `frontend/src/features/research-center/ResearchCenterPage.test.tsx`
- Modify: `frontend/src/features/research-center/ResearchCenterPage.tsx`
- Modify: `frontend/src/features/research-center/ResearchCenterPage.module.css`

**Interfaces:**
- Screening exposes named regions `选择方法` and `候选研究` while preserving mode and filter URL parameters.
- Research center exposes named regions `研究概览` and `研究工作区` while preserving all existing queries and mutations.

- [x] Add accessibility tests for the four named workflow regions and their existing core content.
- [x] Run both focused page tests and confirm they fail because the landmarks do not exist.
- [x] Wrap existing content in semantic sections with visible eyebrow/title/description leads; do not move business components between query branches.
- [x] Replace the pale gradient headers with the same white surface and brand-side accent used on Today.
- [x] Add responsive section-lead styles without changing tables, financial values, or action behavior.
- [x] Re-run both focused tests — screening 12 passed; research center 9 passed.

### Task 3: Verify isolated and local frontend/backend execution

**Files:**
- Modify only if a reproducible configuration or runtime defect is found, with a failing test first.

**Interfaces:**
- Isolated real E2E continues to use its temporary PostgreSQL schema and backend port 8011.
- Local product runtime uses backend `http://127.0.0.1:8020` and frontend `http://127.0.0.1:5174` with `VITE_PROXY_TARGET=http://127.0.0.1:8020`.

- [x] Run the real E2E. The isolated PostgreSQL schema was created and removed and both servers started, but Chromium crashed at `browserContext.newPage`; both browser tests failed before business assertions.
- [x] Run the full frontend unit suite and production build — 32 files / 177 tests passed; TypeScript and Vite build passed.
- [x] Start FastAPI on 127.0.0.1:8020 and Vite on 127.0.0.1:5174 with the matching proxy target; both ports are listening.
- [x] Check `/health`, `/session/status`, `/markets/breadth`, `/markets/anomalies`, and `/markets/capital-flow` — all returned HTTP 200; market payload statuses were `available` and exposed their real source fields.
- [x] Run `git diff --check` — passed; existing CRLF normalization warnings remain outside this task's scope.
