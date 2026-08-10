# Production Contract Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent transport failures from being misreported as anonymous or empty data, make local authentication defaults safe, and make production contracts reproducible and explicit.

**Architecture:** The browser client will preserve transport failures for React Query rather than translating them into data states. Backend defaults will deny legacy anonymous access unless deliberately enabled; the deployment path stays explicitly configured. OpenAPI multipart generation will be treated as the source of frontend upload typing, while the service records the current zero-cost backtest as a non-production baseline.

**Tech Stack:** FastAPI/Pydantic, React/TypeScript, TanStack Query, Vitest, pytest, Docker, uv.

## Global Constraints

- Do not convert provider, network, or contract failures into empty data.
- Preserve registered-user isolation and the existing `GET /session/status` 200-only anonymous contract.
- Do not claim that a zero-cost backtest is execution-ready.
- Do not expose credentials in code, logs, fixtures, or documentation.

---

### Task 1: Preserve session transport failures

**Files:**
- Modify: `frontend/src/api/session.ts`
- Modify: `frontend/src/api/session.test.ts`
- Modify: `frontend/src/app/App.tsx`

- [ ] Write tests proving anonymous 200 returns `null`, while non-200 and fetch rejection reject the query function.
- [ ] Run `npm test -- src/api/session.test.ts` and observe the two transport-failure assertions fail because the implementation returns `null`.
- [ ] Remove the error-to-null fallback from `getSession`; retain only an explicit anonymous 200 response as `null`.
- [ ] Keep a session query error out of the login flow in `App.tsx`, so only a successful anonymous response opens authentication.
- [ ] Run the focused Vitest tests and relevant app tests.

### Task 2: Preserve fund endpoint failures

**Files:**
- Modify: `frontend/src/features/funds/api.ts`
- Create: `frontend/src/features/funds/api.test.ts`

- [ ] Write tests proving a valid empty API result returns `[]` and a failed response rejects.
- [ ] Run `npm test -- src/features/funds/api.test.ts` and observe failure because failed responses return `[]`.
- [ ] Throw a descriptive API error for a failed response and leave an actual empty `items` array unchanged.
- [ ] Run the focused Vitest test and Funds-page tests.

### Task 3: Make configuration and generated upload contracts explicit

**Files:**
- Modify: `app/config.py`
- Modify: `tests/test_auth.py`
- Modify: `frontend/src/features/knowledge/api.ts`
- Modify: `Dockerfile`
- Modify: `tests/test_deployment.py`

- [ ] Write tests proving a no-environment settings load disables legacy anonymous access and the Dockerfile installs from `uv.lock`.
- [ ] Run focused pytest and observe the defaults assertion fail.
- [ ] Change only the local defaults, retain Docker's explicit production values, remove the multipart type bypass, and use the locked Python dependency export during image construction.
- [ ] Regenerate the frontend OpenAPI type after validating the backend schema; do not hand-edit generated output.
- [ ] Run focused pytest, frontend typecheck/build, and Docker compose config validation.

### Task 4: Mark the no-cost backtest boundary in its result contract

**Files:**
- Modify: `app/services/li_zong_portfolio_backtest.py`
- Modify: `tests/test_li_zong_portfolio_backtest.py`

- [ ] Write a test requiring the returned assumptions to label a zero-cost run as a research baseline that is not execution-ready.
- [ ] Run the focused pytest and observe it fail because the current result does not carry the formal eligibility boundary.
- [ ] Add the minimum immutable output metadata and bump the result version so cached results cannot be mistaken for the new contract.
- [ ] Run focused backtest tests.
