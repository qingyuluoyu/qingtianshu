# Personal Research Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the personal center's fictional membership/account content with a user-isolated research asset and todo workbench that follows the existing HTML visual language.

**Architecture:** Extend the existing profile summary endpoint compatibly with a bounded `workbench` aggregate assembled from current watchlist, AI research, position, and trade tables. Keep the current single-page application and visual system, but replace the static personal-center markup with stable loading containers and small rendering functions rather than swapping an entire page after load.

**Tech Stack:** Python 3.12, FastAPI, SQLite repository abstraction, vanilla JavaScript, HTML/CSS, pytest, in-app browser validation.

## Global Constraints

- Preserve the current blue/white visual system, card proportions, rounded corners, spacing, and desktop two-column layout.
- Show only current-user persisted data; never insert example membership, points, API usage, holdings, or returns.
- Remove all personal-center account, phone, payment draft, membership, points, and self-hosted API controls.
- Keep `GET /api/v1/me/profile-summary` backward compatible by adding `workbench`; do not delete `research_assets`.
- Return at most five items in each recent/todo list.
- Do not show review-pending counts unless an existing persisted review state proves them.
- At 1440×900 show the four overview cards and priority todos without overflow.
- At 390×844 use a safe single-column/card layout with no page-level horizontal scrolling and 44px action targets.

---

### Task 1: User-isolated workbench aggregate

**Files:**
- Modify: `app/db.py`
- Modify: `app/services/profile_summary.py`
- Modify: `app/main.py`
- Test: `tests/test_stock_domain.py`

**Interfaces:**
- Produces: `Database.get_profile_workbench_snapshot(user_id: str, recent_limit: int = 5) -> dict[str, Any]`
- Produces: `ProfileSummaryService.get(user_id)["workbench"]`
- Consumes: existing `watchlist`, `ai_research_runs`, `research_tasks`, `positions`, and `trades` tables.

- [ ] **Step 1: Write failing isolation and status-mapping tests**

Add tests that create two users, give only the owner a watchlist item, queued/failed research tasks, an open position, and an executed trade, then assert:

```python
workbench = owner.get("/api/v1/me/profile-summary").json()["workbench"]
assert workbench["summary"]["watchlist_count"] == 1
assert workbench["summary"]["research_total"] == 2
assert workbench["summary"]["position_count"] == 1
assert workbench["summary"]["trade_count"] == 1
assert workbench["summary"]["review_pending_count"] is None
assert len(workbench["todos"]) == 2
assert all(item["href"].startswith("#") for item in workbench["todos"])
assert other.get("/api/v1/me/profile-summary").json()["workbench"]["summary"][
    "watchlist_count"
] == 0
```

- [ ] **Step 2: Run tests and verify the missing contract failure**

Run:

```powershell
pytest tests/test_stock_domain.py -k "profile_workbench" -v
```

Expected: FAIL because the response has no `workbench` key.

- [ ] **Step 3: Add one bounded repository aggregate**

Implement `get_profile_workbench_snapshot` with parameterized `user_id` queries and `LIMIT ?` for recent lists. Return:

```python
{
    "generated_at": utc_now(),
    "summary": {
        "pending_count": len(todos),
        "watchlist_count": watchlist_count,
        "research_total": research_total,
        "research_running": research_running,
        "position_count": open_position_count,
        "trade_count": executed_trade_count,
        "review_pending_count": None,
    },
    "todos": todos[:recent_limit],
    "recent_research": recent_research[:recent_limit],
    "recent_watchlist": recent_watchlist[:recent_limit],
    "lifecycle": [
        {"key": "watch", "label": "关注", "count": watchlist_count, "href": "#watch"},
        {"key": "research", "label": "研究", "count": research_total, "href": "#research"},
        {"key": "position", "label": "持仓", "count": open_position_count, "href": "#review"},
        {"key": "review", "label": "复盘", "count": executed_trade_count, "href": "#review"},
    ],
}
```

Map `pending`, `running`, `leased`, and `retry_wait` to ongoing todos. Map `failed` to a retry todo. Do not turn completed/cancelled/expired tasks into todos.

- [ ] **Step 4: Attach the aggregate without removing compatibility fields**

Update `ProfileSummaryService.get`:

```python
return {
    "research_assets": existing_assets,
    "workbench": self._database.get_profile_workbench_snapshot(user_id),
    "membership": existing_membership,
    "data_status": "available",
}
```

Keep the endpoint's existing `account` response temporarily for other callers, but the personal center must not render it.

- [ ] **Step 5: Run backend tests**

Run:

```powershell
pytest tests/test_stock_domain.py -k "profile" -v
pytest tests/test_db_migrations.py tests/test_trade_review.py -q
```

Expected: all selected tests PASS.

- [ ] **Step 6: Commit**

```powershell
git add app/db.py app/services/profile_summary.py app/main.py tests/test_stock_domain.py
git commit -m "feat: add personal research workbench aggregate"
```

### Task 2: Replace fictional static personal-center markup

**Files:**
- Modify: `app/static/high-fidelity-demo.html`
- Test: `tests/test_profile_workbench_frontend.py`

**Interfaces:**
- Produces stable containers: `profileSummaryCards`, `profileTodoList`, `profileRecentResearch`, `profileRecentWatchlist`, `profileLifecycle`, `profileDataTime`.
- Consumes no data directly; JavaScript in Task 3 populates these containers.

- [ ] **Step 1: Write a failing static-source test**

Create `tests/test_profile_workbench_frontend.py`:

```python
from pathlib import Path

HTML = Path("app/static/high-fidelity-demo.html").read_text(encoding="utf-8")


def test_profile_html_contains_workbench_containers_without_fake_capabilities():
    for element_id in (
        "profileSummaryCards",
        "profileTodoList",
        "profileRecentResearch",
        "profileRecentWatchlist",
        "profileLifecycle",
        "profileDataTime",
    ):
        assert f'id="{element_id}"' in HTML
    for forbidden in (
        "尊享会员",
        "积分余额",
        "API 自建",
        "支付宝订单",
        "实名认证",
        "138*****5628",
    ):
        assert forbidden not in HTML
```

- [ ] **Step 2: Run the test and verify it fails**

Run:

```powershell
pytest tests/test_profile_workbench_frontend.py -v
```

Expected: FAIL because the stable containers are absent and fictional content exists.

- [ ] **Step 3: Replace only the `page-profile` section**

Keep the existing page shell and insert:

```html
<section class="page profile-workbench-page" id="page-profile">
  <div class="page-title-row">
    <div>
      <h1>我的研究工作台</h1>
      <p class="muted">汇总当前用户的关注、研究、持仓与复盘进度</p>
    </div>
    <span class="profile-data-time" id="profileDataTime">正在更新</span>
  </div>
  <div class="profile-summary-grid" id="profileSummaryCards" aria-live="polite"></div>
  <div class="profile-workbench-grid">
    <div class="profile-workbench-main">
      <article class="card"><h2>优先待办</h2><div id="profileTodoList"></div></article>
      <article class="card"><h2>最近研究</h2><div id="profileRecentResearch"></div></article>
      <article class="card"><h2>最近关注变化</h2><div id="profileRecentWatchlist"></div></article>
    </div>
    <aside class="profile-workbench-side">
      <article class="card"><h2>投资闭环</h2><div id="profileLifecycle"></div></article>
      <article class="card profile-quick-actions">
        <h2>继续下一步</h2>
        <button data-page="watch">去关注</button>
        <button data-page="research">开始研究</button>
        <button data-page="review">查看持仓与复盘</button>
      </article>
    </aside>
  </div>
</section>
```

Use loading skeletons inside the containers; do not retain the old member page as fallback.

- [ ] **Step 4: Run the source test**

Run:

```powershell
pytest tests/test_profile_workbench_frontend.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add app/static/high-fidelity-demo.html tests/test_profile_workbench_frontend.py
git commit -m "refactor: replace fictional personal center markup"
```

### Task 3: Render real workbench data and responsive states

**Files:**
- Modify: `app/static/high-fidelity-demo.js`
- Modify: `app/static/high-fidelity-demo.css`
- Modify: `tests/test_profile_workbench_frontend.py`

**Interfaces:**
- Consumes: `GET /api/v1/me/profile-summary` and its `workbench` object.
- Produces: `renderProfileWorkbench(data)`, `renderProfileEmpty(container, text, page, action)`, and `loadProfileSummary()`.

- [ ] **Step 1: Add failing JS/CSS contract assertions**

Extend the frontend test:

```python
JS = Path("app/static/high-fidelity-demo.js").read_text(encoding="utf-8")
CSS = Path("app/static/high-fidelity-demo.css").read_text(encoding="utf-8")


def test_profile_frontend_renders_workbench_and_removes_account_actions():
    assert "renderProfileWorkbench" in JS
    assert "data.workbench" in JS
    assert "profile-workbench-grid" in CSS
    assert "@media(max-width:540px)" in CSS
    for forbidden in (
        "/me/contact-phone",
        "/me/payment-orders/draft",
        "profileOrderDraft",
        "saveProfilePhone",
        "后端聚合接口",
    ):
        assert forbidden not in JS
```

- [ ] **Step 2: Run and verify failure**

Run:

```powershell
pytest tests/test_profile_workbench_frontend.py -v
```

Expected: FAIL because the renderer and styles do not exist and account/payment actions remain.

- [ ] **Step 3: Split rendering into bounded functions**

Implement:

```javascript
function renderProfileWorkbench(data) {
  var workbench = data.workbench || {};
  renderProfileSummary(workbench.summary || {});
  renderProfileTodos(workbench.todos || []);
  renderProfileResearch(workbench.recent_research || []);
  renderProfileWatchlist(workbench.recent_watchlist || []);
  renderProfileLifecycle(workbench.lifecycle || []);
  $('#profileDataTime').textContent =
    '数据更新于 ' + profileTime(workbench.generated_at);
}
```

Each list renderer must:

- escape server text with `escapeHTML`;
- use only hash routes supplied by a local route whitelist;
- render no more than five items;
- display a textual status label;
- show an empty action card when the list is empty.

Rewrite `loadProfileSummary` to update existing containers:

```javascript
function loadProfileSummary() {
  setProfileLoading();
  return ensureWatchlistSession()
    .then(function () { return watchRequest('/api/v1/me/profile-summary'); })
    .then(function (data) {
      renderProfileWorkbench(data);
      return data;
    })
    .catch(function (error) {
      renderProfileError(error);
      throw error;
    });
}
```

Delete all phone, order-draft, membership, API, and full-page `innerHTML` replacement logic.

- [ ] **Step 4: Add responsive CSS**

Use:

```css
.profile-summary-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:18px}
.profile-workbench-grid{display:grid;grid-template-columns:minmax(0,1fr) 360px;gap:18px;margin-top:18px}
.profile-workbench-main{display:grid;gap:18px}
.profile-workbench-side{display:grid;align-content:start;gap:18px}
.profile-action{min-height:44px}

@media(max-width:900px){
  .profile-summary-grid{grid-template-columns:repeat(2,minmax(0,1fr))}
  .profile-workbench-grid{grid-template-columns:1fr}
}
@media(max-width:540px){
  .profile-summary-grid{grid-template-columns:1fr}
  .profile-workbench-grid{display:block}
  .profile-workbench-side{margin-top:12px}
  .profile-list-row{grid-template-columns:minmax(0,1fr);gap:8px}
}
```

- [ ] **Step 5: Run frontend checks**

Run:

```powershell
node --check app/static/high-fidelity-demo.js
pytest tests/test_profile_workbench_frontend.py tests/test_stock_dashboard.py -q
```

Expected: JavaScript syntax check exits 0 and all tests PASS.

- [ ] **Step 6: Commit**

```powershell
git add app/static/high-fidelity-demo.js app/static/high-fidelity-demo.css tests/test_profile_workbench_frontend.py
git commit -m "feat: render personal research workbench"
```

### Task 4: End-to-end verification

**Files:**
- Modify if needed: files from Tasks 1–3 only.

**Interfaces:**
- Verifies the complete user flow from `profile-summary` to rendered desktop/mobile workbench.

- [ ] **Step 1: Run affected automated tests**

```powershell
pytest tests/test_stock_domain.py tests/test_profile_workbench_frontend.py tests/test_stock_dashboard.py tests/test_trade_review.py tests/test_ai_research.py -q
python -m compileall -q app
node --check app/static/high-fidelity-demo.js
```

Expected: all tests PASS and both syntax commands exit 0.

- [ ] **Step 2: Search for forbidden consumer content**

```powershell
rg -n "尊享会员|积分余额|API 自建|支付宝订单|创建订单草稿|实名认证|后端聚合接口" app/static
```

Expected: no matches.

- [ ] **Step 3: Reload the running local app**

Restart the existing Uvicorn process or reload it after code changes. Verify:

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/ready
```

Expected: HTTP 200 with database/schema readiness.

- [ ] **Step 4: Verify 1440×900**

Open `http://127.0.0.1:8000/demo#profile`, set viewport to 1440×900, and verify:

- four summary cards are in one row;
- priority todos are visible in the first screen;
- no old member page flashes during load;
- no overflow, overlap, broken image, or inaccessible action.

- [ ] **Step 5: Verify 390×844**

Set viewport to 390×844 and verify:

- navigation remains usable;
- cards render in one column;
- buttons are at least 44px high;
- long research questions are truncated safely;
- there is no page-level horizontal scroll.

- [ ] **Step 6: Run complete tests**

```powershell
pytest -q --ignore=tests/test_api.py
pytest tests/test_api.py -q
```

Expected: 419 non-API tests and 60 API tests PASS, adjusted upward by the new tests.

- [ ] **Step 7: Commit verification fixes if any**

```powershell
git add app tests
git commit -m "test: verify personal research workbench"
```
