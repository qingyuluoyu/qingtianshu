# High-fidelity 前端后端对齐 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 high-fidelity 页面只呈现可追溯的真实后端数据、明确空状态或“暂未开放”状态。

**Architecture:** 继续采用 FastAPI 路由到服务层的现有结构。`/api/v1` 路由只适配页面契约；市场、证券和用户资源的确定性计算与权限边界留在既有服务中。新增资讯和个人中心聚合使用小型、可单测的服务，避免把业务写进 `app/main.py`。

**Tech Stack:** Python 3.11、FastAPI、Pydantic、SQLite、pytest、Ruff、原生 HTML/CSS/JavaScript。

## Global Constraints

- 不删除既有路由、数据库字段或旧页面功能；新页面使用 `/api/v1` 适配层。
- 所有金融字段必须返回来源、数据时点或明确不可用状态，禁止前端演示数字回退。
- 私人资源只从 HttpOnly 会话的用户身份读取，并按所有者过滤。
- 不输出买卖建议、目标价、仓位、收益承诺或虚构额度、余额和支付状态。
- 未建立订单、支付回调、对账、退款与合规链路前，禁止创建支付订单或展示支付保障。
- 每个生产行为均遵循 Red → Green → Refactor：先运行新增测试确认预期失败，再写最小实现。
- 当前目录不是 Git 仓库；每项的提交命令仅在之后迁入 Git 工作区时执行。

---

## File Structure

- Modify: `app/services/today_dashboard.py` — 保持市场总览服务的时点、来源和空状态契约。
- Modify: `app/services/stock_dashboard.py` — 保持股票搜索、评分卡、K 线的真实数据契约。
- Create: `app/services/stock_intelligence.py` — 读取已落库、已授权的证券资讯；不调用任意 URL。
- Create: `app/services/profile_summary.py` — 聚合当前用户的真实研究资产与会话安全摘要。
- Modify: `app/main.py` — 注册窄的 `/api/v1` 适配路由，映射现有受控错误。
- Modify: `app/db.py` — 仅在精选内容需要持久化时增加可重复执行的 SQLite 表和所有者索引。
- Modify: `app/static/high-fidelity-demo.js` — 删除市场演示回退、伪支付流程，接入资讯和个人中心真实接口与空状态。
- Modify: `app/static/high-fidelity-demo.html` — 为资讯、个人中心与未开放会员状态提供语义容器。
- Modify: `tests/test_today_dashboard.py` — 覆盖市场接口的元数据和不伪造数据。
- Modify: `tests/test_stock_dashboard.py` — 覆盖新页面股票/资讯接口的契约。
- Create: `tests/test_stock_intelligence.py` — 覆盖资讯来源、URL 白名单与空状态。
- Create: `tests/test_profile_summary.py` — 覆盖用户隔离和个人中心真实计数。
- Modify: `tests/test_api.py` — 覆盖路由权限、页面不再包含演示支付文字与接口装配。

### Task 1: 固化今日观察的真实数据契约

**Files:**
- Modify: `tests/test_today_dashboard.py`
- Modify: `app/services/today_dashboard.py`
- Modify: `app/static/high-fidelity-demo.js`

**Interfaces:**
- Consumes: `TodayDashboardService.market_overview() -> dict[str, Any]` 与现有市场适配路由。
- Produces: 每个今日观察加载器只接受真实服务响应；失败时调用 `renderTodayUnavailable(section)`，不读取 `todayDemo`。

- [ ] **Step 1: Write the failing test**

```python
def test_market_overview_exposes_data_timestamps_and_source():
    overview = make_service().market_overview()

    assert overview["status"] == "available"
    assert overview["market_date"] == "2026-07-22"
    assert overview["source"] == "Fake breadth"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_today_dashboard.py::test_market_overview_exposes_data_timestamps_and_source -q`

Expected: FAIL because `market_overview()` does not yet expose all three metadata fields.

- [ ] **Step 3: Write minimal implementation**

```python
return {
    "status": "available",
    "market_date": packet["market_date"],
    "market_timestamp": packet["market_timestamp"],
    "fetched_at": packet["fetched_at"],
    "source": packet["source"],
    **calculated_overview,
}
```

Replace client-side `todayDemo` use in each `todayLoaders` method with a rejection handler that renders `真实数据暂不可用` and leaves numeric widgets blank.

- [ ] **Step 4: Run tests to verify it passes**

Run: `pytest tests/test_today_dashboard.py -q`

Expected: PASS.

- [ ] **Step 5: Run static checks**

Run: `ruff check app/services/today_dashboard.py tests/test_today_dashboard.py`

Expected: `All checks passed!`

### Task 2: 以已落库内容实现证券资讯读取

**Files:**
- Create: `app/services/stock_intelligence.py`
- Create: `tests/test_stock_intelligence.py`
- Modify: `app/main.py`
- Modify: `app/static/high-fidelity-demo.js`

**Interfaces:**
- Consumes: `Database.list_news(symbol, limit, categories)` 的已持久化新闻记录。
- Produces: `StockIntelligenceService.list_news(symbol: str, limit: int = 10) -> dict[str, Any]`，其中 `items` 只包含 `id`、`title`、`source`、`category`、`publishedAt`、`url`、`symbol`、`data_status`。

- [ ] **Step 1: Write the failing test**

```python
def test_list_news_returns_only_allowed_https_records(database):
    database.upsert_news_items([
        {"id": "a", "symbol": "300750.SZ", "title": "公告", "source": "Eastmoney",
         "category": "news", "published_at": "2026-07-23T09:00:00+08:00", "url": "https://example.com/a"},
        {"id": "b", "symbol": "300750.SZ", "title": "unsafe", "source": "x",
         "category": "news", "published_at": "2026-07-23T09:01:00+08:00", "url": "javascript:alert(1)"},
    ])

    result = StockIntelligenceService(database).list_news("300750.SZ")

    assert [item["id"] for item in result["items"]] == ["a"]
    assert result["data_status"] == "available"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_stock_intelligence.py::test_list_news_returns_only_allowed_https_records -q`

Expected: FAIL because `StockIntelligenceService` does not exist.

- [ ] **Step 3: Write minimal implementation**

```python
class StockIntelligenceService:
    def __init__(self, database: Database) -> None:
        self._database = database

    def list_news(self, symbol: str, limit: int = 10) -> dict[str, Any]:
        rows = self._database.list_news(normalize_symbol(symbol), limit=limit, categories=("news", "global_news"))
        items = [self._to_item(row) for row in rows if self._is_allowed_url(row.get("url"))]
        return {"symbol": normalize_symbol(symbol), "items": items,
                "data_status": "available" if items else "empty"}
```

Add `GET /api/v1/stocks/{symbol}/news?limit=10`; it returns the service response, maps invalid symbols to 422, and unexpected provider/database failures to a generic 503. Configure `QSStockIntelConfig.baseURL` to `window.location.origin` and render a server-provided empty state.

- [ ] **Step 4: Run tests to verify it passes**

Run: `pytest tests/test_stock_intelligence.py tests/test_stock_dashboard.py -q`

Expected: PASS.

- [ ] **Step 5: Run static checks**

Run: `ruff check app/services/stock_intelligence.py app/main.py tests/test_stock_intelligence.py`

Expected: `All checks passed!`

### Task 3: 以可追溯事实替换 AI 精选占位

**Files:**
- Modify: `app/services/stock_intelligence.py`
- Modify: `app/main.py`
- Modify: `app/static/high-fidelity-demo.js`
- Modify: `tests/test_stock_intelligence.py`

**Interfaces:**
- Consumes: 当前用户已完成且可见的 Agent Run 摘要。
- Produces: `list_curated_insights(user_id: str, symbol: str, limit: int = 5) -> dict[str, Any]`；每项有 `id`、`type`、`title`、`summary`、`source`、`publishedAt`、`priority`、`isTop`、`data_status`。

- [ ] **Step 1: Write the failing test**

```python
def test_curated_insights_do_not_leak_another_users_research(database):
    owner_id = database.create_user("owner")["id"]
    other_id = database.create_user("other")["id"]
    run = database.create_run(owner_id, "stock_research", "economy", {"symbol": "300750.SZ"}, Path("/tmp/owner"))
    database.finish_run(run["id"], owner_id, "completed", {}, "可复核结论")

    result = StockIntelligenceService(database).list_curated_insights(other_id, "300750.SZ")

    assert result["items"] == []
    assert result["data_status"] == "empty"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_stock_intelligence.py::test_curated_insights_do_not_leak_another_users_research -q`

Expected: FAIL because the method does not exist.

- [ ] **Step 3: Write minimal implementation**

```python
def list_curated_insights(self, user_id: str, symbol: str, limit: int = 5) -> dict[str, Any]:
    canonical = normalize_symbol(symbol)
    rows = [row for row in self._database.list_user_runs(user_id, limit=100)
            if row["status"] == "completed" and row.get("input", {}).get("symbol") == canonical]
    return {"symbol": canonical, "items": [self._run_to_insight(row) for row in rows[:limit]],
            "data_status": "available" if rows else "empty"}
```

Add `GET /api/v1/stocks/{symbol}/curated-insights`, obtain `user_id` from `require_current_user`, and remove the unused `adminPush` front-end endpoint. Render only the server response and the existing empty state.

- [ ] **Step 4: Run tests to verify it passes**

Run: `pytest tests/test_stock_intelligence.py -q`

Expected: PASS.

- [ ] **Step 5: Run API regression tests**

Run: `pytest tests/test_api.py -q`

Expected: PASS.

### Task 4: 补齐研究复盘与个人中心真实聚合

**Files:**
- Create: `app/services/profile_summary.py`
- Create: `tests/test_profile_summary.py`
- Modify: `app/main.py`
- Modify: `app/static/high-fidelity-demo.html`
- Modify: `app/static/high-fidelity-demo.js`

**Interfaces:**
- Consumes: 当前用户的 watchlist、conversations、research reports、agent runs 与 session。
- Produces: `ProfileSummaryService.get(user_id: str, session_id: str) -> dict[str, Any]`，返回 `research_assets`、`security`、`data_status`，不返回 token 或价格资产。

- [ ] **Step 1: Write the failing test**

```python
def test_profile_summary_counts_only_current_users_assets(database):
    alice = database.create_user("alice")["id"]
    bob = database.create_user("bob")["id"]
    database.upsert_watchlist(alice, "300750.SZ", "宁德时代", "A股", "观察", "watching")
    database.upsert_watchlist(bob, "600519.SH", "贵州茅台", "A股", "观察", "watching")

    summary = ProfileSummaryService(database).get(alice, "session-a")

    assert summary["research_assets"]["watchlist_count"] == 1
    assert "token" not in str(summary).lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_profile_summary.py::test_profile_summary_counts_only_current_users_assets -q`

Expected: FAIL because `ProfileSummaryService` does not exist.

- [ ] **Step 3: Write minimal implementation**

```python
class ProfileSummaryService:
    def __init__(self, database: Database) -> None:
        self._database = database

    def get(self, user_id: str, session_id: str) -> dict[str, Any]:
        return {"research_assets": {"watchlist_count": len(self._database.list_watchlist(user_id)),
                "conversation_count": len(self._database.list_conversations(user_id, include_archived=True)),
                "run_count": len(self._database.list_user_runs(user_id))},
                "security": {"session_id_suffix": session_id[-6:], "authentication": "anonymous_session"},
                "data_status": "available"}
```

Add `GET /api/v1/me/profile-summary`; derive both identifiers from the current session. Bind returned counts to the profile page. Replace the purchase card with a static “会员服务暂未开放” notice and do not expose any purchase control.

- [ ] **Step 4: Run tests to verify it passes**

Run: `pytest tests/test_profile_summary.py tests/test_api.py -q`

Expected: PASS.

- [ ] **Step 5: Run static checks**

Run: `ruff check app/services/profile_summary.py app/main.py tests/test_profile_summary.py`

Expected: `All checks passed!`

### Task 5: 以页面契约完成最终联调

**Files:**
- Modify: `tests/test_api.py`
- Modify: `tests/test_stock_dashboard.py`
- Modify: `app/static/high-fidelity-demo.js`
- Modify: `app/static/high-fidelity-demo.html`

**Interfaces:**
- Consumes: Tasks 1–4 的 `/api/v1` 接口。
- Produces: 高保真页面无需演示市场数据、伪支付或未绑定的资讯接口。

- [ ] **Step 1: Write the failing test**

```python
def test_high_fidelity_page_uses_real_endpoints_and_has_no_fake_purchase(client):
    page = client.get("/new-demo")
    script = client.get("/static/high-fidelity-demo.js")
    text = page.text + script.text

    assert "/api/v1/stocks/{symbol}/news" in text
    assert "/api/v1/me/profile-summary" in text
    assert "todayDemo" not in text
    assert "支付宝提供安全支付保障" not in text
    assert "立即购买" not in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_api.py::test_high_fidelity_page_uses_real_endpoints_and_has_no_fake_purchase -q`

Expected: FAIL because the page still contains the demo datasets and fake payment copy.

- [ ] **Step 3: Write minimal implementation**

```javascript
function renderTodayUnavailable(section) {
  document.querySelector(section).textContent = '真实数据暂不可用';
}

document.querySelector('#membershipStatus').textContent = '会员服务暂未开放';
```

Delete `todayDemo`, `QSPaymentAPI`, `purchaseNow` and all fixed payment amounts. Ensure each loader catches only its own failure so that a non-core widget cannot block the rest of its page.

- [ ] **Step 4: Run focused tests to verify it passes**

Run: `pytest tests/test_api.py tests/test_stock_dashboard.py tests/test_today_dashboard.py tests/test_stock_intelligence.py tests/test_profile_summary.py -q`

Expected: PASS.

- [ ] **Step 5: Run project verification**

Run: `pytest -q; ruff check app tests`

Expected: all tests pass and Ruff prints `All checks passed!`.

- [ ] **Step 6: Manually verify the UI**

Run: `python -m uvicorn app.main:app --port 8000`

Open: `http://127.0.0.1:8000/new-demo`

Expected: 今日观察展示后端时点；搜索股票后评分卡、K 线、资讯和精选均来自接口；我的关注和复盘仅显示当前会话数据；个人中心显示真实计数；会员区域没有购买操作。
