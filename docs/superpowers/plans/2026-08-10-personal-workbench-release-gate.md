# Personal Workbench Release Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the personal research workbench legible at desktop and mobile widths while preserving real financial data, account boundaries, and write-confirmation semantics.

**Architecture:** Keep all existing query keys, routes, API payloads, and financial display values. Improve hierarchy through feature-local layout primitives and semantic landmarks; convert `/risk-profile` into a formal personal center only by rendering the already-authenticated session and the existing `/me/risk-profile` contract. The release gate uses the existing Playwright mock contracts plus the isolated real authentication suite; it does not add fake market/account data.

**Tech Stack:** React 19, TypeScript, React Query, React Router, CSS Modules, Vitest, Playwright.

## Global Constraints

- All prices, percent changes, evidence, risk scores, timestamps and source states remain backend passthrough values.
- A-share convention remains red for factual rises and green for factual falls; no color is a recommendation.
- Protected data queries are disabled for unauthenticated users; no personal data placeholders are fabricated.
- Relation changes, AI writeback and review transitions retain their existing server-confirmed and base-version behavior.
- No new frontend dependency is introduced for visual or accessibility checks.

---

### Task 1: Watchlist triage layout

**Files:**
- Modify: `frontend/src/features/watchlist/WatchlistPage.tsx`
- Modify: `frontend/src/features/watchlist/WatchlistPage.module.css`
- Modify: `frontend/src/features/watchlist/WatchlistPage.test.tsx`
- Modify: `frontend/e2e/watchlist.spec.ts`

**Interfaces:**
- Consumes `WatchlistAssets`, selected symbol URL state, `patchStockRelation` and existing `RelationPatch` semantics.
- Produces the same filter/sort/symbol URL parameters and the same relation mutation requests.

- [x] **Step 1: Write a failing layout-semantic test**

```tsx
const table = await screen.findByRole("table", { name: "关注资产表" });
expect(within(table).getByRole("columnheader", { name: "标的" })).toBeInTheDocument();
expect(screen.getByRole("complementary", { name: /快速预览/ })).toBeInTheDocument();
```

- [x] **Step 2: Run the focused test**

Run: `npm test -- WatchlistPage.test.tsx`

Expected: FAIL because the semantic table label and preview landmark do not exist.

- [x] **Step 3: Consolidate table columns without changing values**

```tsx
<table aria-label="关注资产表" className={styles.table}>
  <th>标的</th><th>行情</th><th>研究判断</th><th>最新变化</th><th>待办与状态</th><th>操作</th>
</table>
<aside aria-label={`${asset.name ?? asset.symbol} 快速预览`} className={styles.previewColumn}>…</aside>
```

- [x] **Step 4: Add responsive CSS and run green checks**

Run: `npm test -- WatchlistPage.test.tsx && npx playwright test e2e/watchlist.spec.ts --workers=1`

Expected: existing URL filtering, base-version mutation behavior and mobile overflow checks remain green.

### Task 2: Advisor workspace hierarchy

**Files:**
- Modify: `frontend/src/features/advisor/AdvisorPage.tsx`
- Modify: `frontend/src/features/advisor/AdvisorPage.module.css`
- Modify: `frontend/src/features/advisor/AdvisorPage.test.tsx`
- Modify: `frontend/e2e/advisor.spec.ts`

**Interfaces:**
- Consumes existing conversations, evidence records and `WritebackCandidate` data.
- Produces the same chat request, streaming fallback and confirm/reject writeback calls.

- [x] **Step 1: Write a failing test for the primary research action**

```tsx
const composer = await screen.findByRole("region", { name: "提出研究问题" });
expect(within(composer).getByLabelText("向顾问提问")).toBeInTheDocument();
expect(screen.getByRole("complementary", { name: "证据与候选写回" })).toBeInTheDocument();
```

- [x] **Step 2: Run the focused test**

Run: `npm test -- AdvisorPage.test.tsx`

Expected: FAIL because the composer is not a named primary-action region.

- [x] **Step 3: Introduce feature-local conversation and evidence landmarks**

```tsx
<section aria-label="提出研究问题" className={styles.composerPanel}>…</section>
<aside aria-label="证据与候选写回" className={styles.drawerColumn}>…</aside>
```

- [x] **Step 4: Run green checks**

Run: `npm test -- AdvisorPage.test.tsx && npx playwright test e2e/advisor.spec.ts --workers=1`

Expected: conversation context, candidate confirmation and 409 conflict behavior remain unchanged.

### Task 3: Research-center density and action zones

**Files:**
- Modify: `frontend/src/features/research-center/ResearchCenterPage.tsx`
- Modify: `frontend/src/features/research-center/ResearchCenterPage.module.css`
- Modify: `frontend/src/features/research-center/ResearchCenterPage.test.tsx`
- Modify: `frontend/e2e/research-center.spec.ts`

**Interfaces:**
- Consumes existing changes, outcomes, actions, timelines and trade-review contracts.
- Produces the same `focus` and `symbol` URL state and existing review mutation payloads.

- [x] **Step 1: Write a failing named-action-region test**

```tsx
expect(await screen.findByRole("region", { name: "个人研究行动" })).toHaveTextContent("下一步");
expect(screen.getByRole("region", { name: "复盘结果与市场事实" })).toBeInTheDocument();
```

- [x] **Step 2: Run the focused test**

Run: `npm test -- ResearchCenterPage.test.tsx`

Expected: FAIL because the two density/action landmarks do not exist.

- [x] **Step 3: Group existing cards into semantic density zones**

```tsx
<section aria-label="个人研究行动" className={styles.actionsColumn}>…existing action cards…</section>
<section aria-label="复盘结果与市场事实" className={styles.outcomeColumn}>…existing results and review cards…</section>
```

- [x] **Step 4: Run green checks**

Run: `npm test -- ResearchCenterPage.test.tsx && npx playwright test e2e/research-center.spec.ts --workers=1`

Expected: action filtering, outcome anchors and base-version writes remain green.

### Task 4: Formal personal center backed only by account and risk contracts

**Files:**
- Modify: `frontend/src/app/App.tsx`
- Modify: `frontend/src/features/risk-profile/RiskProfilePage.tsx`
- Modify: `frontend/src/features/risk-profile/RiskProfilePage.module.css`
- Create: `frontend/src/features/risk-profile/RiskProfilePage.test.tsx`
- Modify: `frontend/e2e/risk-profile.spec.ts`

**Interfaces:**
- Consumes `AuthSession` from `getSession` and `RiskProfile | null` from `GET /me/risk-profile`.
- Produces unchanged draft `PUT /me/risk-profile/draft` and confirm `POST /me/risk-profile/confirm` requests.

- [x] **Step 1: Write failing tests for real-account rendering and anonymous query gate**

```tsx
renderPage({ authenticated: true, session: formalSession });
expect(await screen.findByText("正式账户")).toBeInTheDocument();
expect(screen.getByText(formalSession.maskedPhone!)).toBeInTheDocument();

renderPage({ authenticated: false, session: null });
expect(mockGetRiskProfile).not.toHaveBeenCalled();
```

- [x] **Step 2: Run the focused test**

Run: `npm test -- RiskProfilePage.test.tsx`

Expected: FAIL because account data is not passed to the page and the query is not gated.

- [x] **Step 3: Pass the actual session and render truthful profile states**

```tsx
<RiskProfilePage authenticated={formal} session={formal ? session.data ?? null : null} />
const profile = useQuery({ ...riskProfileQueries.profile(), enabled: authenticated });
```

- [x] **Step 4: Run green checks**

Run: `npm test -- RiskProfilePage.test.tsx App.test.tsx && npx playwright test e2e/risk-profile.spec.ts --workers=1`

Expected: anonymous route remains locked, no risk request is made before account authentication, and confirmed/draft API values remain passthrough.

### Task 5: Six-page visual/accessibility release gate

**Files:**
- Modify: `frontend/e2e/today.spec.ts`
- Modify: `frontend/e2e/stock-research.spec.ts`
- Modify: `frontend/e2e/watchlist.spec.ts`
- Modify: `frontend/e2e/advisor.spec.ts`
- Modify: `frontend/e2e/research-center.spec.ts`
- Modify: `frontend/e2e/risk-profile.spec.ts`

**Interfaces:**
- Consumes each suite's existing route mocks and formal account session fixture.
- Produces no API or product contract change.

- [x] **Step 1: Add failing desktop landmark and mobile overflow assertions**

```ts
await expect(page.getByRole("main")).toBeVisible();
const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
expect(overflow).toBeLessThanOrEqual(1);
```

- [x] **Step 2: Run the targeted suites**

Run: `$env:PLAYWRIGHT_BROWSER_CHANNEL='chrome'; npx playwright test e2e/today.spec.ts e2e/stock-research.spec.ts e2e/watchlist.spec.ts e2e/advisor.spec.ts e2e/research-center.spec.ts e2e/risk-profile.spec.ts --workers=1`

Expected: initially FAIL for missing personal-center route coverage and any missing landmark.

- [x] **Step 3: Complete only the required page semantics and rerun**

Run: `npm test && npm run build && $env:PLAYWRIGHT_BROWSER_CHANNEL='chrome'; npx playwright test e2e/today.spec.ts e2e/stock-research.spec.ts e2e/watchlist.spec.ts e2e/advisor.spec.ts e2e/research-center.spec.ts e2e/risk-profile.spec.ts --workers=1`

Expected: all frontend tests, production build and the six-page release gate pass.

## Review Checklist

- [x] Watchlist keeps every relation action and query parameter intact while reducing visual column count.
- [x] Advisor still requires explicit candidate confirmation before any write.
- [x] Research center retains outcome anchor/data-availability wording and review base-version safeguards.
- [x] Personal center displays only authenticated session fields and risk endpoint values.
- [x] Every protected query is disabled for anonymous visitors.
- [x] Six-page suites cover desktop semantic landmarks and 390px overflow.
- [x] Full frontend tests, build, isolated real authentication E2E and local 8020/5174 health checks are run.
