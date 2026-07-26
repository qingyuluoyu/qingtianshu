# 今日观察交易日对齐与图表修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让今日观察在周末和部分接口失败时仍展示同一最近交易日的真实数据，并恢复清晰成交柱图与真实行业历史折线。

**Architecture:** 保留现有快速聚合接口，将市场日期对齐作为聚合响应的兼容扩展；缺失模块由前端调用现有独立接口补齐。行业历史沿用现有东方财富板块代码和缓存体系，由数据提供层获取真实日线，业务层只负责确定性计算。

**Tech Stack:** Python 3.12、FastAPI、现有 Database 缓存、requests、原生 JavaScript、Canvas、pytest。

## Global Constraints

- `generatedAt` 只能表示处理时间，不能作为交易日。
- 所有市场时间转换到 `Asia/Shanghai` 后确定日期。
- 不生成行业两点反推曲线，不把缺失五日涨跌显示为 `0.00%`。
- 不增加数据库表，不增加第三方依赖，不创建第二套行业数据体系。
- 聚合接口继续快速返回，外部历史请求使用有限并发、超时和缓存。

---

### Task 1: 交易日对齐契约

**Files:**
- Modify: `app/services/today_dashboard.py`
- Test: `tests/test_today_dashboard.py`

**Interfaces:**
- Produces: `TodayDashboardService._with_date_alignment(payload: dict[str, Any]) -> dict[str, Any]`
- Produces response fields: `asOfMarketDate`, `dateAlignment`
- Adds module `marketDate` fields without deleting existing fields.

- [ ] **Step 1: Write failing weekend and mixed-date tests**

Add tests asserting:

```python
payload = service._with_date_alignment(
    {
        "generatedAt": "2026-07-25T10:00:00+00:00",
        "marketOverview": {"marketDate": "2026-07-24"},
        "tradingActivity": {
            "points": [{"marketDate": "2026-07-24", "value": 10000}]
        },
        "industryRotation": [{"marketDate": "2026-07-24"}],
    }
)
assert payload["asOfMarketDate"] == "2026-07-24"
assert payload["dateAlignment"]["status"] == "aligned"
```

and a second case where industry is `2026-07-23` and appears in `mismatchedModules`.

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
pytest tests/test_today_dashboard.py -k "date_alignment" -v
```

Expected: FAIL because `_with_date_alignment` and response fields do not exist.

- [ ] **Step 3: Implement market-date normalization and alignment**

Add a Shanghai-time timestamp parser, derive module dates from actual payload fields, choose `marketOverview` as anchor when present and otherwise choose the date mode, then attach:

```python
{
    "asOfMarketDate": anchor,
    "dateAlignment": {
        "status": "aligned" | "mixed" | "partial",
        "anchorMarketDate": anchor,
        "moduleMarketDates": module_dates,
        "mismatchedModules": mismatches,
    },
}
```

Call it before saving dashboard cache and when reading an older persistent cache.

- [ ] **Step 4: Run tests and verify GREEN**

Run:

```powershell
pytest tests/test_today_dashboard.py -k "date_alignment or dashboard_reuses" -v
```

- [ ] **Step 5: Commit**

```powershell
git add app/services/today_dashboard.py tests/test_today_dashboard.py
git commit -m "fix: align today dashboard market dates"
```

### Task 2: 真实行业五日历史

**Files:**
- Modify: `app/providers/market.py`
- Modify: `app/services/analysis.py`
- Modify: `app/services/today_dashboard.py`
- Test: `tests/test_providers.py`
- Test: `tests/test_today_dashboard.py`

**Interfaces:**
- Produces: `EastmoneySectorProvider.fetch_sector_history(code: str, days: int = 5, allow_remote: bool = True) -> dict[str, Any]`
- Produces: `AnalysisService.sector_history(code: str, days: int = 5, allow_remote: bool = True) -> dict[str, Any]`
- `industry_rotation(..., allow_remote: bool = True)` returns `trend`, `trendMarketDates`, `trendStatus`, `fiveDayChangePct`, `marketDate`.

- [ ] **Step 1: Write failing provider parsing test**

Use the existing fake HTTP pattern with an upstream payload:

```python
{
    "data": {
        "klines": [
            "2026-07-20,100,101,102,99,1,2,3,4,5,6",
            "2026-07-21,101,103,104,100,1,2,3,4,5,6",
            "2026-07-22,103,102,105,101,1,2,3,4,5,6",
            "2026-07-23,102,106,107,101,1,2,3,4,5,6",
            "2026-07-24,106,108,109,105,1,2,3,4,5,6"
        ]
    }
}
```

Assert five ordered points, code isolation, source metadata and cached second call.

- [ ] **Step 2: Verify provider test RED**

Run:

```powershell
pytest tests/test_providers.py -k "sector_history" -v
```

- [ ] **Step 3: Implement bounded cached provider**

Use `https://push2his.eastmoney.com/api/qt/stock/kline/get` with `secid=90.<code>`, `klt=101`, `fqt=1`, `lmt=days`. Validate `BK`-style sector code, parse date and close, set six-second timeout, store in existing database cache, and use stale cache on transient failure.

- [ ] **Step 4: Write failing industry-rotation test**

Extend the fake analysis service:

```python
def sector_history(self, code, days=5, allow_remote=True):
    return {
        "status": "available",
        "points": [
            {"market_date": "2026-07-20", "close": 100},
            {"market_date": "2026-07-21", "close": 101},
            {"market_date": "2026-07-22", "close": 103},
            {"market_date": "2026-07-23", "close": 104},
            {"market_date": "2026-07-24", "close": 110},
        ],
        "source": "Fake sector history",
    }
```

Assert `trend == [100, 101, 103, 104, 110]`, `fiveDayChangePct == 10.0`, and missing history returns `trendStatus == "unavailable"` with no synthetic points.

- [ ] **Step 5: Implement service integration**

Preserve sector `code` in ranking results. Fetch histories with at most three workers when `allow_remote=True`; the aggregate path calls `allow_remote=False` for fast cached reads. Calculate percentage from first and last close only when at least three valid points exist.

- [ ] **Step 6: Run provider and dashboard tests**

Run:

```powershell
pytest tests/test_providers.py -k "sector_history" -v
pytest tests/test_today_dashboard.py -k "industry or sector_cards" -v
```

- [ ] **Step 7: Commit**

```powershell
git add app/providers/market.py app/services/analysis.py app/services/today_dashboard.py tests/test_providers.py tests/test_today_dashboard.py
git commit -m "fix: use real sector history for rotation"
```

### Task 3: 前端缺失补拉和图表可读性

**Files:**
- Modify: `app/static/high-fidelity-demo.html`
- Modify: `app/static/high-fidelity-demo.js`
- Modify: `app/static/high-fidelity-demo.css`
- Create: `tests/test_today_dashboard_frontend.py`

**Interfaces:**
- Produces: `todayModuleNeedsRefresh(key, payload) -> boolean`
- Produces: `renderTodayDataStatus(payload, fallbackResults?)`
- Continues using existing `todayLoaders`.

- [ ] **Step 1: Write failing frontend contract tests**

Assert source contains:

```python
assert "asOfMarketDate" in JS
assert "dateAlignment" in JS
assert "todayModuleNeedsRefresh" in JS
assert "Promise.allSettled" in JS
assert "generatedAt||" not in JS
assert ".bar-chart div{height:100%" in CSS
assert "trendStatus" in JS
```

Also assert null five-day values are guarded with `Number.isFinite` before rendering.

- [ ] **Step 2: Verify frontend tests RED**

Run:

```powershell
pytest tests/test_today_dashboard_frontend.py -v
```

- [ ] **Step 3: Implement module recovery**

After aggregate rendering, inspect every module. Missing market overview, distribution, themes, flow or activity triggers its existing loader. Industry data with fewer than three real points triggers the industry loader. Recompute status after all fallback requests settle.

- [ ] **Step 4: Implement honest date labels**

Header text becomes:

```text
数据截止 2026-07-24（最近交易日） · 页面更新 07/25 18:20
```

Mixed data becomes:

```text
数据日期未完全对齐 · 正在补齐：行业轮动
```

Never derive market date from `generatedAt`.

- [ ] **Step 5: Fix chart layout**

Give each bar a fixed plot area and apply percentage height inside that area. Keep zero baseline and use the actual values as labels. Increase industry canvas width; draw only when `trendStatus=available` and at least three points exist, otherwise show an explicit status cell.

- [ ] **Step 6: Run frontend tests and syntax check**

Run:

```powershell
pytest tests/test_today_dashboard_frontend.py tests/test_today_dashboard.py -v
node --check app/static/high-fidelity-demo.js
```

- [ ] **Step 7: Commit**

```powershell
git add app/static/high-fidelity-demo.html app/static/high-fidelity-demo.js app/static/high-fidelity-demo.css tests/test_today_dashboard_frontend.py
git commit -m "fix: recover and clarify today dashboard cards"
```

### Task 4: 发布前验证

**Files:**
- Verify only.

**Interfaces:**
- Consumes all earlier tasks.

- [ ] **Step 1: Run affected backend and API tests**

```powershell
pytest tests/test_today_dashboard.py tests/test_providers.py tests/test_stock_dashboard.py -q
pytest tests/test_api.py -q
```

- [ ] **Step 2: Run compile and diff checks**

```powershell
python -m compileall -q app tests
node --check app/static/high-fidelity-demo.js
git diff --check
```

- [ ] **Step 3: Restart Web and check health**

Restart the exact local Uvicorn process and verify `/ready` and `/health` both return 200.

- [ ] **Step 4: Browser verification**

At 1440×900 and 390×844 verify:

- header market date equals the latest bar, overview and industry market date;
- market overview contains nonzero total/rising/falling values;
- seven turnover bars have visible differentiated heights;
- every available industry row has a visible line with at least three points;
- unavailable history has explicit text rather than `0.00%`;
- no horizontal overflow or overlapping mobile navigation.

- [ ] **Step 5: Run full regression**

```powershell
pytest -q --ignore=tests/test_api.py
```

Expected: all collected tests pass; report existing deprecation warnings separately.
