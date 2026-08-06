# Formal Workbench Last Three Pages Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (\`- [ ]\`) syntax for tracking.

**Goal:** Deliver a shared formal workbench shell, a production-grade stock research page, a real advisor conversation surface, and a traceable research center without inventing financial data or changing existing contracts accidentally.

**Architecture:** Preserve the existing React + TypeScript + Vite feature layout and OpenAPI client. Build small shared presentational primitives first, then migrate the stock page to them while retaining its adapters and query keys. Add advisor and research-center as independently testable feature folders; the only backend change allowed in the advisor package is a separately reviewed, backward-compatible \`entry_context\` addition that is persisted with a run.

**Tech Stack:** React 19, TypeScript 5.7, React Router 7, TanStack Query 5, openapi-fetch, Vitest, Testing Library, Playwright, FastAPI/Pydantic.

## Global Constraints

- Use only real authenticated API responses; do not copy any price, score, return, target price, funding-flow number, or conclusion from the PPT.
- Do not add dependencies or replace the current SVG chart implementation in this plan.
- Preserve \`app/static\`, existing authentication routes, stock research APIs, SSE framing, and generated \`frontend/src/api/openapi.generated.ts\` unless a reviewed backend contract requires regeneration.
- Red/green must represent financial or risk facts and must have textual/sign markers; \`null\` is never rendered as \`0\`.
- Desktop targets are 1440 and 1280; responsive targets are 820 and 390. The application root must not horizontally overflow; only dense table containers may scroll horizontally.
- Every private query is disabled until \`authenticated === true\`; 401 is handled by the existing single unauthorized boundary; 403, 404, 409, stale, partial, empty, and provider failures remain distinguishable.
- Run \`npm test\` and \`npm run build\` after every completed work package. Use real FastAPI + Chromium E2E before accepting any package with authenticated writes or SSE.
- Do not expose admin-only strategy/backtest execution to normal users.

---

## File Structure

| Path | Responsibility |
| --- | --- |
| \`frontend/src/components/workbench/StatusBadge.tsx\` | Textual state tone and accessible label for available/partial/stale/unavailable/error states. |
| \`frontend/src/components/workbench/ModuleState.tsx\` | Loading, empty, unavailable, forbidden, conflict, and retry view shared by cards. |
| \`frontend/src/components/workbench/DataTimestamp.tsx\` | Render API-provided \`as_of\`/source without inventing a timestamp. |
| \`frontend/src/components/workbench/ChartContainer.tsx\` | Consistent chart title, description, fixed-height region, and no-data behavior around existing SVG charts. |
| \`frontend/src/components/workbench/OverlayDialog.tsx\` | Focus-managed drawer/confirmation primitive; used only for evidence and confirmed writebacks. |
| \`frontend/src/components/AppShell.tsx\` and \`.module.css\` | Six-page navigation, semantic route title, mobile navigation trigger, account controls. |
| \`frontend/src/features/search/GlobalSearch.tsx\` and \`.test.tsx\` | Debounced user-initiated search with active-result keyboard selection. |
| \`frontend/src/features/stock-research/components/*.tsx\` | Presentation-only stock header, chart, research workspace, fundamentals, peers, and section shell. |
| \`frontend/src/features/stock-research/StockResearchPage.tsx\` | Route param validation, existing query orchestration, tab and layout composition only. |
| \`frontend/src/features/advisor/{api,adapters,queries,AdvisorPage}.ts(x)\` | Typed API adapter, query keys, conversation/SSE state machine and layout. |
| \`frontend/src/features/advisor/components/*.tsx\` | Conversation sidebar, context, stream, evidence drawer, analysis and candidate-writeback UI. |
| \`frontend/src/features/research-center/{api,adapters,queries,ResearchCenterPage}.ts(x)\` | Typed read models, independent queries and page composition. |
| \`frontend/src/features/research-center/components/*.tsx\` | Priority, changes, actions, reviews, outcomes, report-diff cards. |
| \`frontend/src/app/App.tsx\` | Replace advisor/research placeholders with real pages and retain route-level auth locking. |
| \`app/api_models.py\`, \`app/main.py\`, service/repository files found through their call graph | Only the optional, compatible advisor run \`entry_context\` contract and persistence. |

## Task 1: Establish workbench tokens, module primitives, and tested mobile shell

**Files:**
- Create: \`frontend/src/components/workbench/StatusBadge.tsx\`
- Create: \`frontend/src/components/workbench/ModuleState.tsx\`
- Create: \`frontend/src/components/workbench/DataTimestamp.tsx\`
- Create: \`frontend/src/components/workbench/ChartContainer.tsx\`
- Create: \`frontend/src/components/workbench/OverlayDialog.tsx\`
- Create: \`frontend/src/components/workbench/workbench.module.css\`
- Create: \`frontend/src/components/workbench/OverlayDialog.test.tsx\`
- Modify: \`frontend/src/styles/global.css\`
- Modify: \`frontend/src/components/AppShell.tsx\`
- Modify: \`frontend/src/components/AppShell.module.css\`
- Modify: \`frontend/src/app/App.test.tsx\`

**Interfaces:**
- Produces \`ModuleState({ state, title, detail, onRetry })\`, where \`state\` is \`"loading" | "empty" | "partial" | "unavailable" | "forbidden" | "conflict" | "error"\`.
- Produces \`DataTimestamp({ asOf, source, status })\`, where all fields are nullable and absent fields are omitted rather than fabricated.
- Produces \`OverlayDialog({ open, title, children, onClose, returnFocusRef })\` with \`role="dialog"\`, Escape/backdrop close, focus entry and restoration.
- Produces \`ChartContainer({ title, description, hasData, children })\`; it renders its \`children\` only when \`hasData\` is true.

- [ ] **Step 1: Write the failing shell and dialog tests**

\`\`\`tsx
it("keeps all six formal routes reachable on a 390px viewport", () => {
  render(<AppShell {...shellProps} />);
  expect(screen.getByRole("button", { name: "打开主导航" })).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "打开主导航" }));
  expect(screen.getByRole("link", { name: "研究中心" })).toBeVisible();
});

it("moves focus into and back out of an evidence dialog", () => {
  const trigger = document.createElement("button");
  document.body.append(trigger); trigger.focus();
  render(<OverlayDialog open onClose={vi.fn()} returnFocusRef={{ current: trigger }} title="证据详情">正文</OverlayDialog>);
  expect(screen.getByRole("dialog")).toHaveFocus();
  fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
  expect(trigger).toHaveFocus();
});
\`\`\`

- [ ] **Step 2: Run the focused tests and verify they fail because the new components and navigation trigger do not exist**

Run: \`npm test -- --run frontend/src/components/workbench/OverlayDialog.test.tsx frontend/src/app/App.test.tsx\`  
Expected: FAIL mentioning missing \`OverlayDialog\` or \`打开主导航\`.

- [ ] **Step 3: Implement the primitives and shell without changing feature data requests**

\`\`\`tsx
export function ChartContainer({ title, description, hasData, children }: ChartContainerProps) {
  return <section aria-label={title} className={styles.chart}>
    <header><h2>{title}</h2>{description ? <p>{description}</p> : null}</header>
    {hasData ? children : <ModuleState state="empty" title="暂无可展示的图表数据" />}
  </section>;
}
\`\`\`

Use the established global CSS variables, replacing their values with the approved workbench token values. In \`AppShell\`, use a \`button\` with \`aria-expanded\` and \`aria-controls\` to reveal the same six \`NavLink\` entries on narrow screens; do not duplicate route labels in a second navigation list. Replace pathname text with a route-title map. Remove \`/market-data\` from \`navigation\` without deleting any legacy route.

- [ ] **Step 4: Run the package test and type/build validation**

Run: \`npm test -- --run frontend/src/components/workbench/OverlayDialog.test.tsx frontend/src/app/App.test.tsx && npm run build\`  
Expected: PASS; the build emits \`dist\` without TypeScript errors.

- [ ] **Step 5: Commit the independently reviewable shell package**

\`\`\`bash
git add frontend/src/components/workbench frontend/src/components/AppShell.tsx frontend/src/components/AppShell.module.css frontend/src/styles/global.css frontend/src/app/App.test.tsx
git commit -m "feat(frontend): establish formal workbench shell"
\`\`\`

## Task 2: Make global search selectable and accessible

**Files:**
- Create: \`frontend/src/features/search/GlobalSearch.test.tsx\`
- Modify: \`frontend/src/features/search/GlobalSearch.tsx\`
- Modify: \`frontend/src/components/AppShell.module.css\`

**Interfaces:**
- Consumes \`getGlobalSearch(query): Promise<GlobalSearchGroup[]>\` from \`frontend/src/api/search.ts\`.
- Produces a combobox with one active item identified by \`aria-activedescendant\`; Enter navigates only when an item was selected by ArrowUp/ArrowDown or pointer.

- [ ] **Step 1: Write the failing keyboard and request-boundary tests**

\`\`\`tsx
it("does not navigate on Enter until a result is selected", async () => {
  renderSearchWithResults();
  await userEvent.type(screen.getByRole("combobox"), "茅台{Enter}");
  expect(navigate).not.toHaveBeenCalled();
  await userEvent.keyboard("{ArrowDown}{Enter}");
  expect(navigate).toHaveBeenCalledWith("/stocks/600519.SS");
});

it("does not call search before non-whitespace user input", () => {
  renderSearchWithResults();
  expect(getGlobalSearch).not.toHaveBeenCalled();
});
\`\`\`

- [ ] **Step 2: Run the focused test and verify the existing Enter-to-first-result behavior fails it**

Run: \`npm test -- --run frontend/src/features/search/GlobalSearch.test.tsx\`  
Expected: FAIL because Enter currently selects \`groups[0]?.items[0]\`.

- [ ] **Step 3: Implement flattened result selection with stable DOM ids**

\`\`\`tsx
const items = groups.flatMap((group) => group.items.map((item) => ({ ...item, groupKey: group.key })));
const [activeIndex, setActiveIndex] = useState<number | null>(null);
const activeId = activeIndex === null ? undefined : \`global-search-option-\${items[activeIndex].id}\`;

if (event.key === "ArrowDown") setActiveIndex((index) => Math.min((index ?? -1) + 1, items.length - 1));
if (event.key === "ArrowUp") setActiveIndex((index) => Math.max((index ?? 0) - 1, 0));
if (event.key === "Enter" && activeIndex !== null) pick(items[activeIndex].url);
\`\`\`

Reset \`activeIndex\` when the debounced query changes, when the panel closes, and after \`pick\`. Give each result \`role="option"\`, \`aria-selected\`, and its stable id. Retain the 250ms debounce and \`retry: false\`.

- [ ] **Step 4: Run focused and full frontend tests**

Run: \`npm test -- --run frontend/src/features/search/GlobalSearch.test.tsx && npm test && npm run build\`  
Expected: PASS with no changed request endpoint or query key.

- [ ] **Step 5: Commit search behavior separately**

\`\`\`bash
git add frontend/src/features/search/GlobalSearch.tsx frontend/src/features/search/GlobalSearch.test.tsx frontend/src/components/AppShell.module.css
git commit -m "fix(search): require explicit result selection"
\`\`\`

## Task 3: Split and migrate the stock research presentation without changing its data contract

**Files:**
- Create: \`frontend/src/features/stock-research/components/StockHeader.tsx\`
- Create: \`frontend/src/features/stock-research/components/PriceChartSection.tsx\`
- Create: \`frontend/src/features/stock-research/components/ResearchWorkspacePanel.tsx\`
- Create: \`frontend/src/features/stock-research/components/StockModuleCard.tsx\`
- Create: \`frontend/src/features/stock-research/components/StockResearchSections.test.tsx\`
- Modify: \`frontend/src/features/stock-research/StockResearchPage.tsx\`
- Modify: \`frontend/src/features/stock-research/StockResearchPage.module.css\`
- Modify: \`frontend/src/features/stock-research/StockResearchPage.test.tsx\`

**Interfaces:**
- Consumes existing \`StockPage\`, \`StockHistory\`, \`Workspace\`, \`HistoryRange\`, \`stockResearchQueries\`, and adapters unchanged.
- \`PriceChartSection({ symbol, range, onRangeChange, history })\` renders \`CandlestickChart\` only when the parsed history has enough points.
- \`ResearchWorkspacePanel({ symbol, workspace, theses, tasks, authenticated })\` renders only persisted workspace/thesis/task state and routes the user to existing actions.

- [ ] **Step 1: Add failing presentation-contract tests before moving JSX**

\`\`\`tsx
it("shows stock facts when history fails and does not render an empty chart", async () => {
  mockStockPageSuccess(); mockHistoryFailure();
  renderPage("/stocks/600519.SS");
  expect(await screen.findByText("贵州茅台")).toBeVisible();
  expect(screen.queryByLabelText("价格走势")).not.toBeInTheDocument();
});

it("routes the advisor entry with the current standard symbol", async () => {
  mockStockPageSuccess();
  renderPage("/stocks/600519.SS");
  expect(await screen.findByRole("link", { name: "咨询金融顾问" })).toHaveAttribute("href", "/advisor?symbol=600519.SS");
});
\`\`\`

- [ ] **Step 2: Run focused tests and confirm the advisor entry/component boundary is not yet present**

Run: \`npm test -- --run frontend/src/features/stock-research/StockResearchPage.test.tsx frontend/src/features/stock-research/components/StockResearchSections.test.tsx\`  
Expected: FAIL due to the missing components and advisor link.

- [ ] **Step 3: Extract presentation-only components and retain all existing queries in the page**

\`\`\`tsx
export function PriceChartSection({ history, symbol, range, onRangeChange }: PriceChartSectionProps) {
  const hasSeries = (history?.points.length ?? 0) >= 2;
  return <ChartContainer description={history?.asOf ?? undefined} hasData={hasSeries} title="价格走势">
    <CandlestickChart points={history!.points} symbol={symbol} />
  </ChartContainer>;
}
\`\`\`

\`StockResearchPage\` remains responsible for \`useParams\`, range state, \`useQuery\`, tabs and layout. Do not alter \`getStockPage\`, \`getStockHistory\`, \`getPeerComparisons\`, existing query keys, retry policy, or adapter parsing. Put financial tables inside a \`table\` wrapper that is the only horizontal-scrollable element on small screens. The new advisor link carries only the standard symbol in its URL; it does not claim server-persisted source metadata.

- [ ] **Step 4: Validate page behavior and responsive layout**

Run: \`npm test -- --run frontend/src/features/stock-research && npm run build\`  
Expected: PASS. Then run the existing production browser harness against an isolated database and capture 1440x900 and 390x844 screenshots for \`/stocks/600519.SS\`; expected: no root horizontal overflow, no empty price axes, no console error.

- [ ] **Step 5: Commit the stock-research migration**

\`\`\`bash
git add frontend/src/features/stock-research
git commit -m "feat(stock): compose formal research workspace"
\`\`\`

## Task 4: Review and add the minimal persisted advisor entry context contract

**Files:**
- Modify: \`app/api_models.py\`
- Modify: \`app/main.py\`
- Modify: the exact conversation/run persistence service and repository located by \`rg -n "ChatRequest|request_id|conversation_id" app/services app/database.py\`
- Create: \`tests/test_chat_entry_context.py\`
- Regenerate: \`frontend/src/api/openapi.generated.ts\` only after the FastAPI OpenAPI export is verified.

**Interfaces:**
- Produces optional Pydantic model \`ChatEntryContext\` with \`source_page\`, \`module\`, \`as_of\`, and optional \`symbol\` subject to explicit length/enum validation.
- Extends \`ChatRequest\` with \`entry_context: ChatEntryContext | None = None\`.
- Persists an accepted context with the run and returns it on the run/detail response. Requests from old clients with no field retain the exact current behavior.

- [ ] **Step 1: Write contract tests for optional validation and persistence**

\`\`\`python
def test_chat_entry_context_is_optional_and_persisted(auth_client):
    response = auth_client.post("/me/chat", json={
        "message": "分析当前风险", "symbol": "600519.SS",
        "entry_context": {"source_page": "stock", "module": "price-chart", "as_of": "2026-08-06T09:30:00+08:00"},
    })
    assert response.status_code == 200
    run = auth_client.get(f"/me/runs/{response.json()['run_id']}")
    assert run.json()["entry_context"]["source_page"] == "stock"

def test_unknown_entry_context_field_is_rejected(auth_client):
    response = auth_client.post("/me/chat", json={"message": "x", "entry_context": {"source_page": "stock", "unexpected": True}})
    assert response.status_code == 422
\`\`\`

- [ ] **Step 2: Run the tests to prove the current model has no entry context**

Run: \`python -m pytest tests/test_chat_entry_context.py -q\`  
Expected: FAIL because \`entry_context\` is absent or not persisted.

- [ ] **Step 3: Trace the run persistence call graph before editing and apply the compatible schema/service/repository change**

\`\`\`python
class ChatEntryContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_page: Literal["today", "watchlist", "stock", "advisor", "research_center"]
    module: str = Field(min_length=1, max_length=80)
    as_of: str | None = Field(default=None, max_length=40)
    symbol: str | None = Field(default=None, max_length=24)

class ChatRequest(BaseModel):
    # retain every existing field
    entry_context: ChatEntryContext | None = None
\`\`\`

Use the existing schema version and idempotent migration helper if a new run metadata column/table field is required. Do not add a database default empty string; absent context remains \`NULL\`. Bind context to the authenticated user-owned run at creation, include it in the existing serialized run detail, and never merge it into the natural-language message.

- [ ] **Step 4: Run backend migration, permission, and OpenAPI checks**

Run: \`python -m compileall -q app && python -m pytest tests/test_chat_entry_context.py tests/test_conversations.py -q\`  
Expected: PASS. Export OpenAPI to a repository-external temporary file, compare the \`POST /me/chat\` request schema, then run \`npm run generate:api:file\` against a reviewed copied \`frontend/openapi.json\` and inspect only generated type changes.

- [ ] **Step 5: Commit the compatible contract independently**

\`\`\`bash
git add app/api_models.py app/main.py app/services app/database.py tests/test_chat_entry_context.py frontend/src/api/openapi.generated.ts
git commit -m "feat(advisor): persist request entry context"
\`\`\`

## Task 5: Implement real advisor conversation, streaming, and candidate-writeback UI

**Files:**
- Create: \`frontend/src/features/advisor/api.ts\`
- Create: \`frontend/src/features/advisor/adapters.ts\`
- Create: \`frontend/src/features/advisor/queries.ts\`
- Create: \`frontend/src/features/advisor/AdvisorPage.tsx\`
- Create: \`frontend/src/features/advisor/AdvisorPage.module.css\`
- Create: \`frontend/src/features/advisor/components/ConversationSidebar.tsx\`
- Create: \`frontend/src/features/advisor/components/ContextBar.tsx\`
- Create: \`frontend/src/features/advisor/components/MessageStream.tsx\`
- Create: \`frontend/src/features/advisor/components/EvidenceDrawer.tsx\`
- Create: \`frontend/src/features/advisor/components/WritebackCandidateCard.tsx\`
- Create: \`frontend/src/features/advisor/AdvisorPage.test.tsx\`
- Modify: \`frontend/src/app/App.tsx\`

**Interfaces:**
- \`advisorQueryKeys.conversations()\`, \`.conversation(id)\`, \`.run(id)\`, \`.writebacks()\` are stable user-private query keys.
- \`sendAdvisorMessage(request: ChatRequest): Promise<ChatAccepted>\` validates response presence and throws typed \`AdvisorApiError(status, message)\`; it does not swallow a 401/403/409.
- \`useAdvisorStream(requestId)\` opens at most one \`EventSource\` while the run is active and closes it on terminal status/unmount/request change.
- \`AdvisorPage\` reads \`symbol\` from URL search params, forms \`entry_context\` only after Task 4 is present, and never claims persistence before the run response returns it.

- [ ] **Step 1: Write failing real-state component tests**

\`\`\`tsx
it("submits one chat request and creates one SSE connection", async () => {
  renderAdvisor("/advisor?symbol=600519.SS");
  await userEvent.type(screen.getByLabelText("向金融顾问提问"), "分析主要风险");
  await userEvent.click(screen.getByRole("button", { name: "发送" }));
  expect(postChat).toHaveBeenCalledTimes(1);
  expect(MockEventSource.instances).toHaveLength(1);
});

it("requires explicit confirmation before a candidate writeback", async () => {
  renderAdvisorWithWritebackCandidate();
  await userEvent.click(screen.getByRole("button", { name: "确认写回" }));
  expect(confirmWriteback).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "确认" }));
  expect(confirmWriteback).toHaveBeenCalledWith("candidate-1");
});
\`\`\`

- [ ] **Step 2: Run the focused test and prove advisor is still a placeholder route**

Run: \`npm test -- --run frontend/src/features/advisor/AdvisorPage.test.tsx\`  
Expected: FAIL because the feature folder and real route do not exist.

- [ ] **Step 3: Implement adapters, query policies, and page state machine**

\`\`\`tsx
const chat = useMutation({
  mutationFn: sendAdvisorMessage,
  onSuccess: ({ requestId, runId }) => {
    setActiveRequest({ requestId, runId });
    void queryClient.invalidateQueries({ queryKey: advisorQueryKeys.conversations() });
  },
});

const canConfirm = candidate.status === "pending" && !confirm.isPending;
\`\`\`

All list/detail requests use \`enabled: authenticated\`, finite retry policies that do not retry 401/403/404/409, and query invalidation after confirmed/rejected writebacks. The right-hand analysis cards render only structured response evidence. If evidence is absent, render \`ModuleState state="empty"\`; do not manufacture a five-factor score. On 409, keep the candidate visible, show its conflict state and offer refetch; do not retry the write automatically.

- [ ] **Step 4: Wire the route and validate unit/build paths**

Run: \`npm test -- --run frontend/src/features/advisor frontend/src/app/App.test.tsx && npm test && npm run build\`  
Expected: PASS. \`/advisor/:conversationId?\` resolves to \`AdvisorPage\`, never \`PlaceholderPage\`.

- [ ] **Step 5: Run isolated authenticated browser verification**

Run: start the existing Docker/FastAPI production harness on an isolated test database, then run Playwright Chromium with a real registered user through create conversation, submit chat, receive stream, refresh, view evidence, reject a candidate, and observe a simulated 409 in the service-supported test path.  
Expected: one active SSE connection, no console error, no mocked auth/session/chat/SSE route, and no user B resource available to user A.

- [ ] **Step 6: Commit the advisor UI package**

\`\`\`bash
git add frontend/src/features/advisor frontend/src/app/App.tsx frontend/src/api/openapi.generated.ts
git commit -m "feat(advisor): add traceable conversation workspace"
\`\`\`

## Task 6: Implement the read-first research center

**Files:**
- Create: \`frontend/src/features/research-center/api.ts\`
- Create: \`frontend/src/features/research-center/adapters.ts\`
- Create: \`frontend/src/features/research-center/queries.ts\`
- Create: \`frontend/src/features/research-center/ResearchCenterPage.tsx\`
- Create: \`frontend/src/features/research-center/ResearchCenterPage.module.css\`
- Create: \`frontend/src/features/research-center/components/PriorityCard.tsx\`
- Create: \`frontend/src/features/research-center/components/ChangeTimeline.tsx\`
- Create: \`frontend/src/features/research-center/components/ActionList.tsx\`
- Create: \`frontend/src/features/research-center/components/ReviewAndOutcomePanel.tsx\`
- Create: \`frontend/src/features/research-center/components/ReportDiffReader.tsx\`
- Create: \`frontend/src/features/research-center/ResearchCenterPage.test.tsx\`
- Modify: \`frontend/src/app/App.tsx\`

**Interfaces:**
- Each adapter maps \`unknown\` to a declared display model and throws \`ResearchCenterApiError\` on malformed successful bodies; it never coalesces absent numbers to zero.
- Queries are independent: \`priority\`, \`changes\`, \`actions\`, \`runReviews\`, \`evidenceTasks\`, and \`outcomes\`; a failed report/outcome query cannot block priority/changes/actions.
- The page receives no synthetic action mutation. Existing evidence-task processing is not exposed until its existing input, permission, and confirmation semantics are inspected and separately tested.

- [ ] **Step 1: Write failing data-boundary tests**

\`\`\`tsx
it("keeps changes and actions visible when outcomes are unavailable", async () => {
  mockPrioritySuccess(); mockChangesSuccess(); mockActionsSuccess(); mockOutcomesFailure(502);
  renderResearchCenter();
  expect(await screen.findByText("研究变化")).toBeVisible();
  expect(screen.getByText("结果数据暂时不可用")).toBeVisible();
});

it("does not show a persisted decision label without a persisted record", async () => {
  mockActionsSuccessWithoutDecisionState();
  renderResearchCenter();
  expect(screen.queryByText("已复核")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "确认决策" })).not.toBeInTheDocument();
});
\`\`\`

- [ ] **Step 2: Run the focused tests and verify the route remains a placeholder**

Run: \`npm test -- --run frontend/src/features/research-center/ResearchCenterPage.test.tsx\`  
Expected: FAIL because the feature and route do not exist.

- [ ] **Step 3: Build adapter and page composition with isolated query failures**

\`\`\`tsx
const changes = useQuery({ ...researchCenterQueries.changes(), enabled: authenticated });
const outcomes = useQuery({ ...researchCenterQueries.outcomes(), enabled: authenticated });

<ChangeTimeline state={toModuleState(changes)} items={changes.data ?? []} />
<ReviewAndOutcomePanel state={toModuleState(outcomes)} outcomes={outcomes.data ?? []} />
\`\`\`

Link an action only to an existing route or an API-defined target. Render “维持”, “继续”, or “已复核” only if an adapter receives an explicit persisted status and timestamp. \`ReportDiffReader\` requires a selected symbol and actual report/calibration responses; otherwise it renders an empty/unavailable state, not a fabricated diff.

- [ ] **Step 4: Run focused, full, and browser validations**

Run: \`npm test -- --run frontend/src/features/research-center && npm test && npm run build\`  
Expected: PASS. Then run isolated Chromium at 1440x900 and 390x844 with a real account whose research data is either genuinely empty or created through existing authorized flows; expected: no root overflow, no fake state, and no console error.

- [ ] **Step 5: Commit the research center package**

\`\`\`bash
git add frontend/src/features/research-center frontend/src/app/App.tsx
git commit -m "feat(research): add traceable research center"
\`\`\`

## Task 7: Cross-page release verification and visual evidence

**Files:**
- Modify: \`frontend/src/tests/screenshots.spec.ts\`
- Create: \`frontend/src/tests/formal-workbench.real.spec.ts\`
- Create outside repository: \`F:/tools/qingshu-formal-workbench-evidence/\`

**Interfaces:**
- The real spec uses no \`page.route\`, \`route.fulfill\`, fake cookie, or mock for \`/auth\`, \`/session\`, \`/v1\`, \`/me\`, \`/stocks\`, or \`/events\`.
- Evidence directory contains desktop and mobile screenshots, browser console summary, failed-request summary, route summary, and the exact Git commit.

- [ ] **Step 1: Add failing cross-page navigation and request assertions**

\`\`\`tsx
test("formal routes use React while stock history remains JSON", async ({ page }) => {
  await page.goto("/stocks/600519.SS");
  await expect(page.locator("main")).toContainText("个股研究");
  const history = await page.request.get("/stocks/600519.SS/history?range=1y");
  expect(history.headers()["content-type"]).toContain("application/json");
});
\`\`\`

- [ ] **Step 2: Run the real browser suite against the isolated production image**

Run: \`npm run test:e2e:docker\` followed by \`npx playwright test frontend/src/tests/formal-workbench.real.spec.ts\` against the harness-provided URL.  
Expected: PASS with authenticated navigation \`/today -> /stocks/:symbol -> /advisor -> /research-center\`, refresh recovery, one active SSE during chat, zero JavaScript console errors, zero JS/CSS 404s, and no API response returned as React HTML.

- [ ] **Step 3: Inspect responsive evidence and record any non-blocking external provider errors**

\`\`\`text
F:/tools/qingshu-formal-workbench-evidence/
  screenshots/desktop-stock.png
  screenshots/desktop-advisor.png
  screenshots/desktop-research-center.png
  screenshots/mobile-stock.png
  screenshots/mobile-advisor.png
  screenshots/mobile-research-center.png
  console-summary.md
  network-summary.md
  acceptance-result.md
\`\`\`

The acceptance result must distinguish an external provider 502 JSON from a page failure. It must report the actual database name/schema and refuse to run if they refer to development or production data.

- [ ] **Step 4: Execute the release gate and create the final integration commit**

Run: \`npm test && npm run build && python -m compileall -q app && git diff --check\`  
Expected: all commands exit 0. Commit only source, tests, and documentation; never commit \`dist\`, \`node_modules\`, video, screenshots, logs, OpenAPI temporary exports, credentials, or test databases.

\`\`\`bash
git add frontend/src app tests docs
git commit -m "test(frontend): verify formal workbench routes"
\`\`\`

## Plan Self-Review

### Specification coverage

- Shared shell, six formal nav entries, search keyboard behavior, tokens, dialog focus, module states, chart state, responsive targets: Tasks 1–2.
- Stock page’s PPT-derived hierarchy with existing real stock APIs, no fake target/funding/price, history failure isolation: Task 3.
- Advisor conversations, SSE, evidence, candidate-only writebacks, 409 and user isolation, and the missing persisted entry context: Tasks 4–5.
- Research priority/change/action/review/outcome/report layout, partial failure isolation, and no unsupported saved action: Task 6.
- Production image, Chromium, 1440/390, route/API separation, error/network evidence: Task 7.

### Placeholder scan

No task contains an unresolved marker or a generic testing instruction. Every task names files, interfaces, a failing test, expected command result, implementation boundary, verification, and commit.

### Type consistency

\`ChartContainer\`, \`ModuleState\`, \`OverlayDialog\`, \`advisorQueryKeys\`, \`AdvisorApiError\`, \`ChatEntryContext\`, and research-center query names are defined before downstream use. The stock package preserves existing \`StockPage\`, \`StockHistory\`, \`Workspace\`, \`HistoryRange\`, and \`stockResearchQueries\` names rather than renaming their contract.

