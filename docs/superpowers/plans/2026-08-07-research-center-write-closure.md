# Research Center Write Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect the existing Research Center trade-review UI to its existing guarded draft, writeback, edit, confirmation, archive, and followup contracts.

**Architecture:** Keep the existing three-column `ResearchCenterPage` and its `TradeReviewCenterSection`. Add typed API adapters and one user-scoped pending-writeback query. Every mutation invalidates the existing aggregate queries; 409 clears any optimistic success notice and refreshes server state. AI generation is only initiated by an explicit button and returns a pending candidate that requires a second user confirmation.

**Tech Stack:** React 18, TypeScript, TanStack Query, openapi-fetch, Vitest, Testing Library, FastAPI/OpenAPI generated types.

## Global Constraints

- Do not change FastAPI routes, database schema, financial calculations, authentication contract, or `app/static`.
- Do not invoke an AI model during page load, query refresh, retry, or browser test setup.
- Do not use localStorage or sessionStorage for drafts, candidates, authentication, or write state.
- All draft/confirm/archive writes must carry the current server `base_version`.
- A 409 must refresh server state; it must not re-send a write or overwrite local/server content.
- `economy` is the default generation tier; `deep` is only sent after explicit user selection.

---

### Task 1: Add typed Research Center write-contract adapters

**Files:**
- Modify: `frontend/src/features/research-center/adapters.ts`
- Modify: `frontend/src/features/research-center/api.ts`
- Modify: `frontend/src/features/research-center/adapters.test.ts`
- Create: `frontend/src/features/research-center/api.test.ts`

**Interfaces:**
- Produces `PendingWriteback`, `parsePendingWritebacks`, `generateTradeReviewDraft`, `confirmWriteback`, `rejectWriteback`, `updateTradeReviewDraft`, and `createTradeReviewFollowup`.
- Consumes existing generated OpenAPI paths `/v1/ai-writebacks`, `/v1/ai-writebacks/{candidate_id}/confirm`, `/reject`, `/v1/trade-reviews/{review_id}/generate-draft`, `/draft`, and `/followups`.

- [ ] **Step 1: Write failing parsing and payload tests**

```ts
it("keeps only pending review-draft writebacks with their originating review", () => {
  const parsed = parsePendingWritebacks({
    items: [{ id: "candidate-1", candidate_type: "review_draft", status: "pending_confirmation", review_id: "review-1", payload: { logic_result: "需要复核", bias_tags: ["锚定"] } }],
  });
  expect(parsed.items[0]).toMatchObject({ id: "candidate-1", reviewId: "review-1", logicResult: "需要复核", biasTags: ["锚定"] });
});

it("sends the explicit model tier and base version when generating", async () => {
  await generateTradeReviewDraft("review-1", 3, "deep");
  expect(mockPost).toHaveBeenCalledWith("/v1/trade-reviews/{review_id}/generate-draft", expect.objectContaining({ body: { base_version: 3, model_tier: "deep" } }));
});

it("maps a 409 write response to ResearchCenterApiError", async () => {
  mockPost.mockResolvedValue(response(409));
  await expect(updateTradeReviewDraft("review-1", payload)).rejects.toMatchObject({ status: 409 });
});
```

- [ ] **Step 2: Run the focused tests and confirm RED**

Run: `npm test -- --run src/features/research-center/adapters.test.ts src/features/research-center/api.test.ts`

Expected: failures because the pending-writeback parser and mutation functions do not exist.

- [ ] **Step 3: Implement the minimal view model and requests**

```ts
export type PendingWriteback = {
  id: string;
  reviewId: string | null;
  logicResult: string | null;
  planDeviation: string | null;
  improvementText: string | null;
  biasTags: string[];
  createdAt: string | null;
};

export async function updateTradeReviewDraft(reviewId: string, body: TradeReviewDraftInput) {
  return mutationRequest("PATCH", "/v1/trade-reviews/{review_id}/draft", reviewId, body);
}
```

Use the existing `ResearchCenterApiError` for 401, 404, 409, 422, and server errors. Extend `TradeReview.currentVersion` with `biasTags`, preserving `null` separately from an empty list.

- [ ] **Step 4: Run focused tests and confirm GREEN**

Run: `npm test -- --run src/features/research-center/adapters.test.ts src/features/research-center/api.test.ts`

Expected: all focused tests pass.

- [ ] **Step 5: Commit contract layer**

```bash
git add frontend/src/features/research-center/adapters.ts frontend/src/features/research-center/api.ts frontend/src/features/research-center/adapters.test.ts frontend/src/features/research-center/api.test.ts
git commit -m "feat: add research center write contracts"
```

### Task 2: Add pending-writeback query and guarded mutation controller

**Files:**
- Modify: `frontend/src/features/research-center/queries.ts`
- Modify: `frontend/src/features/research-center/ResearchCenterPage.tsx`
- Modify: `frontend/src/features/research-center/ResearchCenterPage.test.tsx`

**Interfaces:**
- Produces `researchCenterQueries.pendingWritebacks()` and page-level generation/confirmation/rejection mutations.
- Consumes `getPendingWritebacks`, `generateTradeReviewDraft`, `confirmWriteback`, `rejectWriteback`, and existing query keys.

- [ ] **Step 1: Write failing interaction tests**

```tsx
it("does not generate a candidate until the user explicitly selects a tier", async () => {
  renderPage();
  expect(mockGenerate).not.toHaveBeenCalled();
  fireEvent.click(await screen.findByRole("button", { name: "生成复盘候选" }));
  fireEvent.click(screen.getByRole("button", { name: "以经济档生成" }));
  await waitFor(() => expect(mockGenerate).toHaveBeenCalledWith("review-ready", 0, "economy"));
});

it("confirms a pending candidate before exposing an editable formal draft", async () => {
  renderPage();
  fireEvent.click(await screen.findByRole("button", { name: "确认候选并生成草稿" }));
  await waitFor(() => expect(mockConfirmWriteback).toHaveBeenCalledWith("candidate-1"));
  expect(mockGetTradeReviews.mock.calls.length).toBeGreaterThan(1);
});

it("refreshes server state instead of replaying after a candidate 409", async () => {
  mockConfirmWriteback.mockRejectedValue(new ResearchCenterApiError(409, "版本已更新"));
  renderPage();
  fireEvent.click(await screen.findByRole("button", { name: "确认候选并生成草稿" }));
  expect(await screen.findByText("版本已更新")).toBeInTheDocument();
  expect(mockGetTradeReviews.mock.calls.length).toBeGreaterThan(1);
});
```

- [ ] **Step 2: Run the page test and confirm RED**

Run: `npm test -- --run src/features/research-center/ResearchCenterPage.test.tsx`

Expected: failures because candidate actions and their controls are absent.

- [ ] **Step 3: Add query key and one mutation controller**

```ts
pendingWritebacks: () => ["research-center", "pending-writebacks"] as const,

const invalidateWriteViews = () => Promise.all([
  queryClient.invalidateQueries({ queryKey: researchCenterQueryKeys.tradeReviews() }),
  queryClient.invalidateQueries({ queryKey: researchCenterQueryKeys.pendingWritebacks() }),
  queryClient.invalidateQueries({ queryKey: researchCenterQueryKeys.actions() }),
  queryClient.invalidateQueries({ queryKey: researchCenterQueryKeys.changes() }),
  queryClient.invalidateQueries({ queryKey: researchCenterQueryKeys.outcomes() }),
]);
```

Render the candidate only beside its matching review. Before generation, show a small confirmation panel with `economy` and `deep` actions. Disable only the active mutation button, keep page navigation usable, and never create a candidate locally.

- [ ] **Step 4: Run the page test and confirm GREEN**

Run: `npm test -- --run src/features/research-center/ResearchCenterPage.test.tsx`

Expected: candidate generation, confirmation, rejection, and 409 tests pass.

- [ ] **Step 5: Commit candidate workflow**

```bash
git add frontend/src/features/research-center/queries.ts frontend/src/features/research-center/ResearchCenterPage.tsx frontend/src/features/research-center/ResearchCenterPage.test.tsx
git commit -m "feat: add guarded research review candidates"
```

### Task 3: Add draft editing and followup creation UI

**Files:**
- Modify: `frontend/src/features/research-center/ResearchCenterPage.tsx`
- Modify: `frontend/src/features/research-center/ResearchCenterPage.module.css`
- Modify: `frontend/src/features/research-center/ResearchCenterPage.test.tsx`

**Interfaces:**
- Produces an edit form for `draft` reviews and a followup form for `confirmed`/`archived` reviews.
- Consumes `TradeReview.currentVersion`, `updateTradeReviewDraft`, `createTradeReviewFollowup`, and the shared invalidation controller from Task 2.

- [ ] **Step 1: Write failing edit and followup tests**

```tsx
it("edits the current draft with every required field and its version", async () => {
  renderPage();
  fireEvent.click(await screen.findByRole("button", { name: "编辑复盘草稿" }));
  fireEvent.change(screen.getByLabelText("逻辑结果"), { target: { value: "验证范围缩小，需要继续观察。" } });
  fireEvent.click(screen.getByRole("button", { name: "保存草稿版本" }));
  await waitFor(() => expect(mockUpdateDraft).toHaveBeenCalledWith("review-1", expect.objectContaining({ baseVersion: 2, logicResult: "验证范围缩小，需要继续观察。" })));
});

it("creates an observation followup only from a confirmed review", async () => {
  renderPage();
  fireEvent.click(await screen.findByRole("button", { name: "创建后续事项" }));
  fireEvent.change(screen.getByLabelText("后续事项类型"), { target: { value: "observation_task" } });
  fireEvent.click(screen.getByRole("button", { name: "创建观察任务" }));
  await waitFor(() => expect(mockCreateFollowup).toHaveBeenCalledWith("review-2", { target: "observation_task", title: null, priority: "normal" }));
});
```

- [ ] **Step 2: Run the page test and confirm RED**

Run: `npm test -- --run src/features/research-center/ResearchCenterPage.test.tsx`

Expected: edit and followup controls are not found.

- [ ] **Step 3: Implement controlled forms with no silent defaults**

```tsx
{review.status === "draft" && review.currentVersion ? <button type="button" onClick={() => setEditingReviewId(review.id)}>编辑复盘草稿</button> : null}
{["confirmed", "archived"].includes(review.status ?? "") ? <button type="button" onClick={() => setFollowupReviewId(review.id)}>创建后续事项</button> : null}
```

Require non-empty price and logic results before PATCH. Preserve optional plan deviation and improvement text as `null` when blank. Render bias tags as a comma-separated input and normalize only by trimming/removing empty user entries. On successful writes, close the relevant form only after query invalidation resolves.

- [ ] **Step 4: Add responsive style coverage and run GREEN**

Run: `npm test -- --run src/features/research-center/ResearchCenterPage.test.tsx`

Expected: all existing and new page interactions pass.

- [ ] **Step 5: Commit forms**

```bash
git add frontend/src/features/research-center/ResearchCenterPage.tsx frontend/src/features/research-center/ResearchCenterPage.module.css frontend/src/features/research-center/ResearchCenterPage.test.tsx
git commit -m "feat: add research review edits and followups"
```

### Task 4: Verify contracts, rendering, and production behavior

**Files:**
- Modify only if verification reveals a defect in the files from Tasks 1-3.
- Test: `frontend/src/features/research-center/*.test.ts`, backend trade-review/writeback tests, and existing Playwright configuration.

**Interfaces:**
- Verifies the existing FastAPI/OpenAPI contract without changing it.

- [ ] **Step 1: Run focused frontend and backend verification**

```bash
cd frontend
npm test -- --run src/features/research-center
npm run build
cd ..
python -m compileall -q app
python -m pytest -q tests/test_trade_workflow.py tests/test_structured_ai.py
```

Expected: all commands exit 0. If a backend test file does not exist, locate the actual contract test with `rg -l "trade-reviews|ai-writebacks" tests` and report the substituted file explicitly.

- [ ] **Step 2: Execute authenticated browser smoke without triggering an AI generation**

1. Start the candidate FastAPI + production React environment using the isolated test database.
2. Sign in with a disposable test account and open `/research-center` at 1440×900 and 390×844.
3. Verify no `generate-draft` request occurs before a user click.
4. Verify existing draft confirmation/archive still work against real endpoints when fixture state exposes them.
5. Verify page-root `scrollWidth <= innerWidth`, no console errors, and no JS/CSS 404.

- [ ] **Step 3: Commit only if a verification fix was required**

```bash
git add frontend/src/features/research-center/api.ts frontend/src/features/research-center/adapters.ts frontend/src/features/research-center/queries.ts frontend/src/features/research-center/ResearchCenterPage.tsx frontend/src/features/research-center/ResearchCenterPage.module.css frontend/src/features/research-center/api.test.ts frontend/src/features/research-center/adapters.test.ts frontend/src/features/research-center/ResearchCenterPage.test.tsx
git commit -m "fix: verify research center write closure"
```

If no fix was needed, do not create an empty commit.
