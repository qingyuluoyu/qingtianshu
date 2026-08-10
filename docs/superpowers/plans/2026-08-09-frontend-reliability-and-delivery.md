# Frontend Reliability and Delivery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make authentication failures, data-source failures, private-data access, and route loading distinguishable to users without changing financial calculations or API contracts.

**Architecture:** Preserve the existing React Query + feature API structure, but make each API adapter distinguish a valid empty response from a failed request. Keep public market data independent of authentication and introduce route-level lazy loading only after behavior is covered. Large feature pages are decomposed by page-specific sections, not by a repository-wide component rewrite.

**Tech Stack:** React 19, TypeScript, TanStack React Query 5, React Router 7, Vite 6, Vitest, React Testing Library.

## Global Constraints

- Do not change provider selection, financial formulas, units, historical-data semantics, or backend API field names.
- A successful response with a valid empty collection or absent optional resource must remain distinct from HTTP, transport, or malformed-response failures.
- Private queries must stay disabled until a formal authenticated session is established; public-market queries must not wait for private queries.
- Do not add dependencies, change database schema, or change generated `openapi.generated.ts` by hand.
- Retain all existing retry and error messages unless the task explicitly adds a more precise one.

---

## File Structure

- `frontend/src/app/App.tsx`: session state and route registration.
- `frontend/src/app/App.test.tsx`: session-error and route-loading regression coverage.
- `frontend/src/api/requestError.ts`: a small shared error factory for typed API request failures.
- `frontend/src/features/{knowledge,strategies,risk-profile,articles}/api.ts`: normalize valid data only and throw on failed requests.
- `frontend/src/features/{knowledge,strategies,risk-profile,articles}/api.test.ts`: verify success-empty and failed response behavior separately.
- `frontend/src/components/AccessGate.tsx`: reusable access boundary already introduced; expand only through focused consumers.
- `frontend/src/features/today/*` and `frontend/src/features/market-data/*`: retain public market query ownership and remove duplicated component-state decisions in a bounded slice.
- `frontend/src/features/screening/*`, `frontend/src/features/stock-research/*`, `frontend/src/features/research-center/*`: later page-specific section extraction targets.
- `frontend/vite.config.ts`: explicit route chunk boundaries and build validation.

### Task 1: Preserve session-error behavior while removing unreachable logic

**Files:**
- Modify: `frontend/src/app/App.tsx:35-51`
- Modify: `frontend/src/app/App.test.tsx`

**Interfaces:**
- Consumes: `getSession(): Promise<Session | null>` and `session.isError` from TanStack React Query.
- Produces: an error state that does not mutate the session cache or open the authentication modal while `/session/status` is unavailable.

- [ ] **Step 1: Add the session-error regression test**

```tsx
it("does not open the login dialog when the session-status request fails", async () => {
  vi.mocked(getSession).mockRejectedValueOnce(new Error("会话状态请求失败 (503)"));
  render(<App />);
  expect(await screen.findByRole("alert")).toHaveTextContent("会话状态暂不可用");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run the focused test to establish the preserved behavior**

Run: `npm run test -- src/app/App.test.tsx`

Expected: PASS; the session alert renders and no authentication dialog opens.

- [ ] **Step 3: Implement the state split**

```tsx
useEffect(() => {
  if (session.isLoading || session.isError || formal || !isProtectedPath(location.pathname)) return;
  if (promptedLocationRef.current === location.key) return;
  promptedLocationRef.current = location.key;
  setAuthOpen(true);
}, [formal, location.key, location.pathname, session.isError, session.isLoading]);
```

Delete the unreachable `if (session.isError)` cache mutation. Leave the existing alert rendering in place so a transport failure is never recast as anonymous access.

- [ ] **Step 4: Run the focused test to verify it passes**

Run: `npm run test -- src/app/App.test.tsx`

Expected: PASS.

### Task 2: Complete the failed-request versus valid-empty API contract

**Files:**
- Create: `frontend/src/api/requestError.ts`
- Create: `frontend/src/api/requestError.test.ts`
- Modify: `frontend/src/features/knowledge/api.ts`
- Create: `frontend/src/features/knowledge/api.test.ts`
- Modify: `frontend/src/features/strategies/api.ts`
- Create: `frontend/src/features/strategies/api.test.ts`
- Modify: `frontend/src/features/risk-profile/api.ts`
- Modify: `frontend/src/features/articles/api.ts`

**Interfaces:**
- Consumes: OpenAPI-fetch results with `response.ok`, `response.status`, `data`, and `error`.
- Produces: `requestError(operation: string, status: number): Error`; successful `[]`/`null` only for documented empty resource responses, and rejected promises for failed transport or HTTP responses.

- [ ] **Step 1: Write the failing shared-helper test**

```ts
it("records an operation and response status without response details", () => {
  expect(requestError("策略列表", 502).message).toBe("策略列表请求失败 (502)");
});
```

- [ ] **Step 2: Write failing adapter tests**

```ts
await expect(listKnowledgeDocuments()).resolves.toEqual([]);
await expect(listKnowledgeDocuments()).rejects.toThrow("知识库列表请求失败 (502)");

await expect(listStrategies()).resolves.toEqual([]);
await expect(listStrategies()).rejects.toThrow("策略列表请求失败 (503)");
```

Each pair must use one `response.ok === true` empty payload and one `response.ok === false` payload from the existing `vi.mock("../../api/client")` pattern.

- [ ] **Step 3: Run adapter tests to verify they fail**

Run: `npm run test -- src/api/requestError.test.ts src/features/knowledge/api.test.ts src/features/strategies/api.test.ts`

Expected: FAIL because failed responses currently resolve as empty arrays or null.

- [ ] **Step 4: Implement the narrow contract helper and apply it**

```ts
export function requestError(operation: string, status: number): Error {
  return new Error(`${operation}请求失败 (${status})`);
}

if (!response.ok || error || data === undefined) {
  throw requestError("知识库列表", response.status);
}
```

For `getRiskProfile` and `listArticles`, preserve their current valid `profile: null` and `items: []` behavior after a successful response. For strategy mutations, throw on non-OK responses and update their existing page handlers to catch the error and set the present user-visible failure message.

- [ ] **Step 5: Run adapter and affected page tests**

Run: `npm run test -- src/api/requestError.test.ts src/features/knowledge/api.test.ts src/features/strategies/api.test.ts src/features/risk-profile/api.test.ts src/features/articles/api.test.ts src/features/knowledge/KnowledgePage.test.tsx src/features/strategies/StrategiesPage.test.tsx`

Expected: PASS; create the two missing page tests in this task if they do not exist before changing handlers.

### Task 3: Consolidate Today private access and public market composition

**Files:**
- Modify: `frontend/src/features/today/TodayPage.tsx`
- Modify: `frontend/src/features/today/TodayComponents.tsx`
- Modify: `frontend/src/features/today/TodayPage.test.tsx`
- Modify: `frontend/src/components/AccessGate.tsx`
- Modify: `frontend/src/components/AccessGate.test.tsx`

**Interfaces:**
- Consumes: `AccessGate({ allowed, fallback, children })`, `useTodayPublicMarket()`, and `useTodayPrivateDashboard(authenticated)`.
- Produces: private Today cards that are not mounted for anonymous visitors and public cards whose query state remains independent of authentication.

- [ ] **Step 1: Write the failing anonymous-page test**

```tsx
it("does not mount private change tabs for an anonymous visitor", () => {
  page(client(), false);
  expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
  expect(screen.getByText("登录后查看个人研究")).toBeInTheDocument();
  expect(screen.getByRole("region", { name: "异动机会 / 风险提示" })).toHaveTextContent("中科曙光");
});
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `npm run test -- src/features/today/TodayPage.test.tsx`

Expected: FAIL because `ChangesCard` mounts its tabs and embeds its own access decision.

- [ ] **Step 3: Extract a private-card fallback and gate the private composition**

```tsx
<AccessGate
  allowed={authenticated}
  fallback={<PrivateModuleNotice title="我的股票新变化" />}
>
  <ChangesCard
    changes={changes.data}
    changesError={changes.isError}
    changesPending={changes.isPending}
    onRetryChanges={() => void changes.refetch()}
    onRetryPositions={() => void positions.refetch()}
    positions={positions.data}
    positionsError={positions.isError}
    positionsPending={positions.isPending}
  />
</AccessGate>
```

Make `ChangesCard` accept only already-authorized data and remove its `authenticated` and `locked` props. `PrivateModuleNotice` must use the existing Today card CSS and the copy `登录后查看个人研究`; it must not start a query or render a skeleton.

- [ ] **Step 4: Run Today and gate tests**

Run: `npm run test -- src/components/AccessGate.test.tsx src/features/today/TodayPage.test.tsx`

Expected: PASS.

### Task 4: Split the two highest-risk page files by visual section

**Files:**
- Create: `frontend/src/features/screening/ScreeningFilters.tsx`
- Create: `frontend/src/features/screening/ScreeningResults.tsx`
- Modify: `frontend/src/features/screening/ScreeningPage.tsx`
- Modify: `frontend/src/features/screening/ScreeningPage.test.tsx`
- Create: `frontend/src/features/stock-research/StockResearchHeader.tsx`
- Create: `frontend/src/features/stock-research/StockResearchEvidence.tsx`
- Modify: `frontend/src/features/stock-research/StockResearchPage.tsx`
- Modify: `frontend/src/features/stock-research/StockResearchPage.test.tsx`

**Interfaces:**
- Consumes: page-level normalized query data, mutation callbacks, and existing CSS modules.
- Produces: section components that receive typed props and do not call APIs or mutate financial values.

- [ ] **Step 1: Write failing render-preservation tests**

```tsx
expect(screen.getByRole("heading", { name: "候选池" })).toBeInTheDocument();
expect(screen.getByText("不构成买卖建议")).toBeInTheDocument();
```

Add one assertion to each existing page test that requires a section to receive the existing normalized data and boundary text.

- [ ] **Step 2: Run focused tests to establish current behavior**

Run: `npm run test -- src/features/screening/ScreeningPage.test.tsx src/features/stock-research/StockResearchPage.test.tsx`

Expected: PASS before extraction; commit this baseline test change separately.

- [ ] **Step 3: Extract presentation-only sections**

```tsx
export function ScreeningResults({ items, selectedSymbol, onSelect }: {
  items: ScreenItem[];
  selectedSymbol: string | null;
  onSelect: (symbol: string) => void;
}) {
  return <ScreenCandidateTable items={items} selectedSymbol={selectedSymbol} onSelect={onSelect} />;
}
```

Keep all `useQuery`, URL state, mutation setup, request parameters, financial labels, and data-source annotations in the page container. Move only contiguous JSX and its local presentation helpers.

- [ ] **Step 4: Run focused tests and build**

Run: `npm run test -- src/features/screening/ScreeningPage.test.tsx src/features/stock-research/StockResearchPage.test.tsx && npm run build`

Expected: PASS.

### Task 5: Introduce route-level code splitting and verify production output

**Files:**
- Modify: `frontend/src/app/App.tsx`
- Modify: `frontend/src/app/App.test.tsx`
- Modify: `frontend/vite.config.ts` only if chunk names need deterministic grouping

**Interfaces:**
- Consumes: `React.lazy`, `Suspense`, existing route components, and `ErrorBoundary`.
- Produces: lazily loaded heavy feature routes with a non-blocking loading fallback; `/today` remains eagerly available.

- [ ] **Step 1: Write the failing route fallback test**

```tsx
it("keeps the shell available while a lazily loaded route resolves", async () => {
  render(<App />);
  await userEvent.click(screen.getByRole("link", { name: "选股" }));
  expect(screen.getByText("页面加载中…")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `npm run test -- src/app/App.test.tsx`

Expected: FAIL because routes are statically imported and no route fallback exists.

- [ ] **Step 3: Convert only heavyweight routes to lazy imports**

```tsx
const ScreeningPage = lazy(() => import("../features/screening/ScreeningPage").then(({ ScreeningPage }) => ({ default: ScreeningPage })));

<Suspense fallback={<div role="status">页面加载中…</div>}>
  <Routes>
    <Route element={<ScreeningPage authenticated={formal} />} path="/screening" />
    <Route element={<StockResearchPage authenticated={formal} />} path="/stocks/:symbol" />
  </Routes>
</Suspense>
```

Start with `ScreeningPage`, `StockResearchPage`, `ResearchCenterPage`, and `AdvisorPage`. Keep `TodayPage`, `AppShell`, authentication, and the session query eagerly loaded to protect the primary entry path.

- [ ] **Step 4: Run build and inspect assets**

Run: `npm run build`

Expected: PASS with separate JavaScript assets for the four heavyweight routes. Record the generated gzip sizes in the pull-request or release note; do not set `chunkSizeWarningLimit` merely to silence the warning.

## Verification Matrix

- `npm run test`: all frontend tests pass.
- `npm run build`: TypeScript and Vite production build pass; route chunks exist for each lazily loaded heavyweight feature.
- `git diff --check`: no whitespace errors.
- Manual browser path: open `/today` while anonymous and verify public market cards load, personal cards remain gated, then search a known symbol and temporarily stop the backend to verify the error state is not labeled as empty data.

## Sequencing and Risk

1. Task 1 first: prevents a session transport failure from being misclassified as an authentication state.
2. Task 2 second: repairs truthfulness of data states without reshaping pages.
3. Task 3 third: removes the remaining Today access decision from a private content component.
4. Task 4 fourth: high-churn structural work only after state semantics are stable.
5. Task 5 last: performance optimization only after route behavior has stable tests.

The Python 3.11 test-runtime absence is a separate environment blocker for backend integration tests. It must be resolved before a production release, but it does not justify changing Python source or bypassing backend tests in this frontend plan.

## Self-Review

- Authentication behavior, request truthfulness, Today composition, large-page ownership, and bundle delivery each have a separate testable task.
- The plan does not treat successful empty data as an error.
- Financial calculation and provider behavior remain outside this frontend plan.
- The required API helper and all referenced section components have explicit names and file destinations.

## Execution Record

- Tasks 1 through 3 were executed on 2026-08-09.
- `npm run test` passed with 31 files and 169 tests.
- `npm run build` passed; the Vite single-entry bundle warning remains at 588.65 kB and is deliberately deferred to Task 5.
- `git diff --check` passed without whitespace errors; Git emitted existing Windows line-ending advisories.
- Tasks 4 and 5 were executed after the second approval. `ScreeningFilters`, `ScreeningResults`, `StockResearchHeader`, and `StockResearchEvidence` now own bounded presentation sections while their page containers retain query and financial-data ownership.
- `ScreeningPage`, `StockResearchPage`, `ResearchCenterPage`, and `AdvisorPage` are route-level lazy chunks. The entry JavaScript asset is 426.09 kB (131.08 kB gzip); the former Vite 500 kB advisory no longer appears.
