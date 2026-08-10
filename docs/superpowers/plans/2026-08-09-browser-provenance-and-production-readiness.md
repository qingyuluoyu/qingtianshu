# Browser, Provenance, and Production Readiness Implementation Plan

> **Execution note:** Run this plan in the current authorized workspace using the executing-plans workflow, with test-driven changes and verification after every work package.

**Goal:** Restore repeatable browser acceptance, expose the provenance already present in public market/research contracts, and add production-grade request correlation without changing financial formulas or breaking existing clients.

**Architecture:** Keep the current FastAPI modular monolith, React query/adapters, and Docker Compose topology. Browser selection remains a test-runtime concern. Provenance fields are additive from existing provider/snapshot metadata. Request correlation is implemented once at the FastAPI middleware boundary and returned on every HTTP response.

**Tech Stack:** FastAPI/Starlette, pytest, React 19, TypeScript, Vitest, Playwright 1.62, Docker Compose.

---

## Work package 1: Browser runtime recovery and real-chain acceptance

**Files:**
- Modify: `frontend/playwright.config.ts`
- Modify: `frontend/playwright.real.config.ts`
- Test: `frontend/e2e/today.spec.ts`
- Test: `frontend/e2e-real/today-real.spec.ts`

1. Lock a failing reproduction showing bundled Chromium crashes before `newPage` with `Error loading V8 startup snapshot file`.
2. Add a shared, environment-controlled Playwright channel (`PLAYWRIGHT_BROWSER_CHANNEL`) to both configs so CI can keep bundled Chromium while damaged local runtimes can explicitly use installed Edge.
3. Run one simulated Today E2E with `PLAYWRIGHT_BROWSER_CHANNEL=msedge`.
4. Run the isolated real FastAPI/PostgreSQL/cookie/Today E2E with the same channel and the bundled healthy Python runtime.
5. Keep failures attributable to assertions separate from environment failures; do not weaken E2E assertions.

## Work package 2: Public market and research provenance vertical slice

**Files:**
- Modify: `app/services/analyst_expectations.py`
- Modify: `tests/test_api.py`
- Modify: `frontend/src/features/today/adapters.ts`
- Modify: `frontend/src/features/today/adapters.test.ts`
- Modify: `frontend/src/features/today/TodayComponents.tsx`
- Modify: `frontend/src/features/today/TodayPage.test.tsx`

1. Add failing backend assertions that latest research reports retain snapshot source names and source fetch time.
2. Add failing adapter tests for index/global/live/report source and timestamp passthrough.
3. Add additive source metadata to each aggregated report from the exact snapshot payload; do not synthesize a provider name.
4. Preserve `source` and `fetched_at` on China indices, global indices, live markets, and reports in frontend types/adapters.
5. Render compact provenance in the three public modules, including mixed-provider labels and actual data time.
6. Run focused backend and frontend tests, then the full frontend suite.

## Work package 3: Request correlation and production health audit

**Files:**
- Modify: `app/main.py`
- Modify: `tests/test_operations.py`
- Modify: `tests/test_auth_contract.py` if authentication log redaction coverage is needed
- Inspect: `docker-compose.yml`
- Inspect: `Dockerfile`
- Inspect: `.env.example`
- Inspect: `staging.env.example`

1. Add failing API tests for an accepted safe `X-Request-ID`, generated IDs for absent/invalid input, and response header propagation.
2. Implement a single HTTP middleware that binds a validated request ID, measures duration, returns `X-Request-ID`, and emits one access-log record without cookies, tokens, request bodies, or position details.
3. Verify `/health` remains a liveness-style public summary and `/ready` continues to enforce operational dependencies.
4. Validate Compose configuration and document any deployment blockers without exposing secrets.
5. Run affected backend tests, health/readiness probes, frontend build, `git diff --check`, and retain the existing 8020/5174 local services for manual verification.

## Compatibility, rollback, and cost

- API changes are additive only; existing clients can ignore provenance and `X-Request-ID`.
- No database migration or financial calculation change is required.
- Browser override is opt-in and can be rolled back by unsetting `PLAYWRIGHT_BROWSER_CHANNEL`.
- Middleware rollback is one code removal and has no persistent-data impact.
- Runtime cost is limited to one UUID/timer/log event per HTTP request and a few short strings in public responses.
