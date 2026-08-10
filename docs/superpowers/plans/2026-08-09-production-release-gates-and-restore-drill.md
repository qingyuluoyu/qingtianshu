# Production Release Gates and Restore Drill Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add fail-closed production configuration checks and actionable data-health freshness reporting, then prove the existing PostgreSQL backup/restore path and full production build against isolated targets.

**Architecture:** Keep local development behavior compatible. Production-only checks live at the typed settings boundary, while data-quality health is exposed through the existing operations report instead of container liveness to avoid restart loops during upstream vendor outages. Reuse the existing atomic backup and random temporary-database restore drill; do not introduce a second maintenance path.

**Tech Stack:** Python 3.11+, FastAPI, PostgreSQL/psycopg, pytest, React/Vite/Vitest, Playwright, Docker Compose.

---

### Task 1: Production configuration fail-closed gate

**Files:**
- Modify: `app/config.py`
- Modify: `tests/test_portability.py`
- Modify: `.env.example`
- Modify: `staging.env.example`
- Modify: `docker-compose.yml`
- Modify: `README.md`

- [x] Add failing tests for accepted development settings and rejected staging/production placeholder database credentials, insecure cookies, default SEC contact, and weak optional admin tokens.
- [x] Run the focused tests and confirm they fail for the missing gate.
- [x] Add an explicit deployment-environment setting and a pure validation function that reports field names without secret values.
- [x] Wire Compose and example environments to explicit development/staging/production modes; document the startup failure contract.
- [x] Re-run focused portability and deployment tests.

### Task 2: Data-health freshness in operational reporting

**Files:**
- Modify: `app/operations.py`
- Modify: `scripts/check_operations.py`
- Modify: `app/main.py`
- Modify: `tests/test_operations.py`
- Modify: `README.md`

- [x] Add failing tests for missing, stale, degraded, attention, and fresh data-health snapshots.
- [x] Run the focused tests and confirm the new assertions fail.
- [x] Add opt-in snapshot freshness/status evaluation to the operations report and CLI, with thresholds in the response.
- [x] Enable it on the authenticated admin operations endpoint only; keep `/ready` and Docker liveness infrastructure-focused.
- [x] Re-run focused operations/API tests and verify no private snapshot details are exposed.

### Task 3: Isolated PostgreSQL backup and restore drill

**Files:**
- Verify: `scripts/postgres_backup.py`
- Verify: `scripts/postgres_restore_drill.py`
- Verify: `app/postgres_maintenance.py`
- Modify only if a reproducible defect is found.

- [x] Confirm `pg_dump`, `pg_restore`, and database connectivity without printing credentials.
- [x] Create a uniquely named temporary backup directory and back up `qingshu_auth_test`.
- [x] Verify manifest/checksum, restore into the script-generated `qingshu_restore_<random>` database, and run schema/table checks.
- [x] Confirm the temporary restore database is removed even after the drill and report the exact non-sensitive evidence.

### Task 4: Production build and release regression

**Files:**
- Verify: `Dockerfile`
- Verify: `docker-compose.yml`
- Verify: affected backend/frontend code and tests.

- [x] Run the full backend pytest suite with the isolated PostgreSQL test database.
- [x] Run the full frontend unit test suite and production build.
- [x] Validate local and staging Compose configurations without revealing interpolated secrets.
- [x] Build the production Docker image and run a container-level startup/health smoke test with non-placeholder ephemeral credentials when feasible.
- [x] Record passes, failures, skipped checks, compatibility, cost impact, and remaining release risks.
