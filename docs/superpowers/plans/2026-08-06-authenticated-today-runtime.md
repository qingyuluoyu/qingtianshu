# Authenticated Today Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make local Today-page verification use one explicit backend target and a real authenticated browser session, so an invalid session or wrong proxy cannot be mistaken for a page-data failure.

**Architecture:** Keep browser requests same-origin through Vite. Extract the Vite proxy target default into a shared, testable resolver that accepts an explicit environment value and otherwise matches the backend's documented local port. Make screenshot setup establish its session through the same frontend origin used by the page, then assert the public `/session/status` contract before capturing. Preserve the existing backend turnover-history contract and its empty-history display behavior.

**Tech Stack:** Vite 6, TypeScript, Vitest, Playwright, FastAPI integration tests.

## Global Constraints

- Do not expose session values, passwords, tokens, or database URLs in output, snapshots, or committed fixtures.
- Retain same-origin browser requests and the backend's host-only, `HttpOnly`, `SameSite=Strict` session cookie policy.
- Do not re-enable Today modules whose availability contract is not part of this repair.
- Treat fewer than two stored turnover history points as a valid no-chart state.

---

### Task 1: Make the Vite proxy target explicit and regression-tested

**Files:**
- Create: `frontend/src/config/runtime.ts`
- Create: `frontend/src/config/runtime.test.ts`
- Modify: `frontend/vite.config.ts:1-31`
- Modify: `frontend/.env.example` (or create it if no frontend environment example exists)

**Interfaces:**
- Consumes: `VITE_PROXY_TARGET?: string`.
- Produces: `resolveProxyTarget(value?: string): string`, returning a normalized local development API origin.
- Consumers: Vite proxy setup and local developer documentation.

- [ ] **Step 1: Write the failing test**

```ts
import { describe, expect, it } from "vitest";
import { resolveProxyTarget } from "./runtime";

describe("resolveProxyTarget", () => {
  it("uses the documented backend port when no target is supplied", () => {
    expect(resolveProxyTarget()).toBe("http://127.0.0.1:8000");
  });

  it("keeps an explicit development backend target", () => {
    expect(resolveProxyTarget("http://127.0.0.1:8011")).toBe("http://127.0.0.1:8011");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/config/runtime.test.ts`

Expected: FAIL because `./runtime` does not exist.

- [ ] **Step 3: Write the minimal implementation**

```ts
export function resolveProxyTarget(value = process.env.VITE_PROXY_TARGET): string {
  const target = value?.trim();
  return target || "http://127.0.0.1:8000";
}
```

Change `frontend/vite.config.ts` to import this function and assign `const backend = resolveProxyTarget();`. Document that `VITE_PROXY_TARGET=http://127.0.0.1:8001` is an explicit local override when FastAPI does not use the standard port.

- [ ] **Step 4: Run test and type/build verification**

Run: `npx vitest run src/config/runtime.test.ts && npm run build`

Expected: both commands exit 0.

### Task 2: Establish screenshot sessions through the frontend origin

**Files:**
- Modify: `frontend/capture_screenshots_v3.mjs:1-63`
- Create: `frontend/e2e/runtime-authentication.spec.ts`
- Modify: `frontend/playwright.config.ts` only if the new test needs an existing project entrypoint.

**Interfaces:**
- Consumes: `FRONTEND` URL and a test-only account supplied through environment variables.
- Produces: an authenticated Playwright context only after `/session/status` returns `{ authenticated: true }`.
- Consumers: screenshot capture and Playwright runtime smoke test.

- [ ] **Step 1: Write the failing browser regression**

```ts
test("an authenticated browser session activates Today data requests", async ({ page }) => {
  await registerThroughFrontendOrigin(page);
  await expect.poll(async () => page.evaluate(async () => {
    const response = await fetch("/session/status", { credentials: "same-origin" });
    return (await response.json()).authenticated;
  })).toBe(true);
  await page.goto("/today");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByText("正在读取…")).toHaveCount(0);
});
```

- [ ] **Step 2: Run the test to verify it fails with the old screenshot setup**

Run: `npx playwright test e2e/runtime-authentication.spec.ts`

Expected: FAIL because the session helper has not been implemented or the old setup only injects a stale cookie.

- [ ] **Step 3: Implement the smallest shared browser setup**

Replace manual parsing and `document.cookie` injection in `capture_screenshots_v3.mjs` with an API request made to `${FRONTEND}/auth/register` (or `/auth/login` when supplied credentials already exist), retain the returned browser context cookie, then request `${FRONTEND}/session/status` through the context. Throw an error before any screenshot if the response is not authenticated. Use unique test account fields or an explicit login mode so re-runs are idempotent and do not publish credentials.

- [ ] **Step 4: Run the focused browser test**

Run: `npx playwright test e2e/runtime-authentication.spec.ts`

Expected: PASS; the browser receives a host-only `localhost` cookie from the frontend origin and Today does not show the authentication modal.

### Task 3: Verify the production-equivalent contract without reviving removed modules

**Files:**
- Modify: `frontend/scripts/run_real_today_e2e.py:80-121`
- Modify: `frontend/e2e-real/today.real.spec.ts` (or existing real Today spec discovered during implementation)
- Modify: `frontend/src/features/today/real-api-adapter.test.ts:5-14`

**Interfaces:**
- Consumes: isolated FastAPI backend at `BACKEND_PORT=8011` and Vite proxy target injected by the runner.
- Produces: a real E2E assertion that session bootstrap is authenticated and `/markets/breadth` either provides valid history or explicitly has fewer than two valid points.

- [ ] **Step 1: Write the failing contract assertions**

```ts
expect(session.authenticated).toBe(true);
expect(Array.isArray(breadth.turnover_history)).toBe(true);
expect(breadth.turnover_history.every((point) =>
  typeof point.date === "string" && typeof point.amount_100m_cny === "number",
)).toBe(true);
```

Update the old fixture test name to identify it as a historical response without stored snapshots, preserving `turnoverHistory === []` as the expected degraded state.

- [ ] **Step 2: Run the affected test to verify it fails**

Run: `npm run test:e2e:real`

Expected: FAIL until the real E2E bootstrap asserts and waits for the authenticated session.

- [ ] **Step 3: Implement the assertion and controlled fixture wording**

Use the existing isolated backend runner's `VITE_PROXY_TARGET=http://127.0.0.1:8011`. Authenticate through the frontend origin; assert session status before navigating. Do not add a false turnover history fallback or change backend financial data behavior.

- [ ] **Step 4: Run all relevant verification**

Run: `npx vitest run src/config/runtime.test.ts src/api/session.test.ts src/features/today && npm run build && npm run test:e2e:real && uv run --isolated --frozen pytest tests/test_auth_contract.py tests/test_api.py -q`

Expected: each command exits 0. If provider/network-dependent backend tests are excluded by the project suite, report the exact omitted test selection and reason.

### Task 4: Document the runnable local verification path

**Files:**
- Modify: `README.md` or the existing local-development document discovered during implementation.

**Interfaces:**
- Consumes: FastAPI port, `VITE_PROXY_TARGET`, and the screenshot command.
- Produces: reproducible ordered commands for backend, frontend, authenticated screenshot capture, and failure interpretation.

- [ ] **Step 1: Write a documentation assertion checklist**

```text
1. /session/status through localhost:5173 returns authenticated:true after browser login.
2. /markets/breadth through localhost:5173 returns a JSON object and, when snapshots exist, valid turnover_history points.
3. Screenshots are rejected rather than saved when authentication is false.
```

- [ ] **Step 2: Add the exact commands and failure diagnostics**

Document `VITE_PROXY_TARGET` matching the running backend, the `curl`/browser status check, and the command to run the capture script. State that port mismatch and expired test session fail the preflight instead of creating a misleading skeleton screenshot.

- [ ] **Step 3: Verify documentation commands against an isolated run**

Run: `npm run test:e2e:real`

Expected: exit 0 and the runner removes its isolated database schema.

- [ ] **Step 4: Commit**

```bash
git add frontend/vite.config.ts frontend/src/config frontend/capture_screenshots_v3.mjs frontend/e2e frontend/scripts/run_real_today_e2e.py frontend/src/features/today/real-api-adapter.test.ts README.md docs/superpowers/plans/2026-08-06-authenticated-today-runtime.md
git commit -m "fix(frontend): make authenticated today runtime reproducible"
```
