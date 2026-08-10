# Today Public Market Composition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Today page load public market data independently of authentication and unrelated requests, while keeping user-private panels behind an explicit access boundary.

**Architecture:** Move Today query ownership from the page into public-market and private-dashboard hooks. Public modules query immediately and independently; private modules retain the existing authenticated gate. Add a small reusable access component and use it for the private Today composition rather than encoding access decisions inside public module cards.

**Tech Stack:** React 18, TypeScript, TanStack React Query, Vitest, React Testing Library, Vite.

## Global Constraints

- Do not alter financial formulas, data units, provider selection, or API response contracts in this slice.
- Keep personal research, positions, and data-health requests authenticated and user isolated.
- Do not replace public-data failures with empty values; preserve each module's error state and retry action.
- Do not change the current route-level session semantics or refactor unrelated feature pages.

---

### Task 1: Verify public modules are not locked for anonymous users

**Files:**
- Modify: `frontend/src/features/today/TodayPage.test.tsx`

**Interfaces:**
- Consumes: `TodayPage({ authenticated })` and prepared React Query data keyed by `todayQueryKeys`.
- Produces: regression coverage that anomalies and latest research reports render their supplied public data when `authenticated` is false.

- [ ] **Step 1: Write the failing test**

```tsx
it("renders public anomaly and research-report data without authentication", () => {
  page(client(), false);
  expect(screen.getByRole("region", { name: "异动机会 / 风险提示" })).toHaveTextContent("中科曙光");
  expect(screen.getByRole("region", { name: "今日研究报告" })).toHaveTextContent("中兴通讯：算力基建加速");
});
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `npm run test -- TodayPage.test.tsx`

Expected: FAIL because the two cards render the login-required state.

- [ ] **Step 3: Implement the smallest public/private query split**

Move public Today queries into a `useTodayPublicMarket` hook and remove authentication-based `enabled` and `locked` flags from anomaly and research-report modules. Keep `ChangesCard`, personal research, data health, and positions private.

- [ ] **Step 4: Run the focused test to verify it passes**

Run: `npm run test -- TodayPage.test.tsx`

Expected: PASS.

### Task 2: Remove the public-data waterfall and preserve immediate index history

**Files:**
- Create: `frontend/src/features/today/useTodayPublicMarket.ts`
- Modify: `frontend/src/features/today/TodayPage.tsx`
- Modify: `frontend/src/features/today/TodayPage.test.tsx`

**Interfaces:**
- Consumes: `todayQueries` public query option factories.
- Produces: `useTodayPublicMarket()` returning `indices`, `breadth`, `sectors`, `capitalFlow`, `anomalies`, `reports`, `globalIndices`, and `liveMarkets` query results.

- [ ] **Step 1: Write the failing test**

```tsx
it("keeps index history available for anonymous public-market users", () => {
  page(client(true), false);
  expect(screen.getByText("近日成交额（亿元）")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `npm run test -- TodayPage.test.tsx`

Expected: FAIL because `loadHistory` is coupled to `authenticated`.

- [ ] **Step 3: Implement immediate public queries**

```tsx
export function useTodayPublicMarket() {
  return {
    indices: useQuery(todayQueries.indices()),
    breadth: useQuery(todayQueries.breadth()),
    sectors: useQuery(todayQueries.sectors()),
    capitalFlow: useQuery(todayQueries.capitalFlow()),
    anomalies: useQuery(todayQueries.anomalies()),
    reports: useQuery(todayQueries.researchReports()),
    globalIndices: useQuery(todayQueries.globalIndices()),
    liveMarkets: useQuery(todayQueries.liveMarkets()),
  };
}
```

Pass `loadHistory={true}` to `IndexSection`; remove `publicSettled` entirely.

- [ ] **Step 4: Run the focused test to verify it passes**

Run: `npm run test -- TodayPage.test.tsx`

Expected: PASS.

### Task 3: Make the private Today composition explicit

**Files:**
- Create: `frontend/src/components/AccessGate.tsx`
- Create: `frontend/src/components/AccessGate.test.tsx`
- Create: `frontend/src/features/today/useTodayPrivateDashboard.ts`
- Modify: `frontend/src/features/today/TodayPage.tsx`

**Interfaces:**
- Consumes: `authenticated: boolean`, private `todayQueries`, and an access-denied fallback.
- Produces: `AccessGate({ allowed, fallback, children })` and `useTodayPrivateDashboard(authenticated)`.

- [ ] **Step 1: Write the failing component test**

```tsx
it("does not mount protected content when access is denied", () => {
  render(<AccessGate allowed={false} fallback={<p>登录后查看个人研究</p>}><p>private content</p></AccessGate>);
  expect(screen.getByText("登录后查看个人研究")).toBeInTheDocument();
  expect(screen.queryByText("private content")).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `npm run test -- AccessGate.test.tsx`

Expected: FAIL because the component does not exist.

- [ ] **Step 3: Implement the gate and private hook**

Use the gate only around the personal-research and data-health composition. The private hook must set `enabled: authenticated` for overview, watchlist, actions, changes, positions, and data health.

- [ ] **Step 4: Run focused and Today tests**

Run: `npm run test -- AccessGate.test.tsx TodayPage.test.tsx`

Expected: PASS.

### Task 4: Verify the complete frontend boundary

**Files:**
- Modify: `docs/superpowers/plans/2026-08-09-today-public-market-composition.md` (mark actual verification results)

- [ ] **Step 1: Run frontend tests**

Run: `npm run test`

Expected: all frontend tests pass.

- [ ] **Step 2: Run the production build**

Run: `npm run build`

Expected: TypeScript and Vite build complete successfully.

- [ ] **Step 3: Run whitespace validation**

Run: `git diff --check`

Expected: no whitespace errors.

## Self-Review

- Public anomaly, research-report, global-market, and index-history queries are covered by Tasks 1 and 2.
- Private data remains enabled only for authenticated users in Task 3.
- No backend, database, financial calculation, or provider behavior changes are in scope.
- No placeholders or unresolved interface names remain.

## Verification Results

- [x] `npm run test -- TodayPage.test.tsx` passed after the public-query split (7 tests).
- [x] `npm run test -- AccessGate.test.tsx TodayPage.test.tsx` passed (9 tests).
- [x] `npm run test` passed (23 files, 159 tests).
- [x] `npm run build` passed; Vite reported the pre-existing single JavaScript bundle exceeds its 500 kB advisory threshold.
- [x] `git diff --check` passed without whitespace errors; Git emitted Windows LF-to-CRLF conversion advisories for existing working-tree files.
