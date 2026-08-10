# A-share Metric Contracts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make public A-share indicators explicit about their data basis and prevent non-comparable or non-executable values from being presented as precise trading metrics.

**Architecture:** Preserve existing API paths and add only compatible metadata and presentation changes. Financial quality screening will use the latest announced annual report; market-price indicators remain raw close-to-close price changes but are renamed accordingly. When the source lacks information needed for an exact statistic, return an explicit unavailable state instead of an approximation.

**Tech Stack:** Python/FastAPI/Pandas/pytest; React/TypeScript/TanStack Query/Vitest.

## Global Constraints

- Do not use synthetic market values or silently substitute missing A-share data.
- Keep existing API fields compatible; add metadata and adjust presentation before removing no fields.
- A zero-cost backtest remains research-only and must not be usable as execution, performance marketing, or suitability evidence.
- Use TDD: every behavior change gets a failing focused test before production code.

---

### Task 1: Comparable annual financial-quality screen

**Files:**

- Modify: `app/services/stock_screener.py:22-35, 1179-1227, 1393-1459`
- Modify: `tests/test_stock_screener.py:82-108, 282-325`

**Produces:** Quality profile packets with `financial_period_basis="latest_announced_full_year"`; all revenue, profit and ROE filters operate on the latest announced annual report rather than mixed quarterly periods.

- [ ] **Step 1: Write failing tests**

```python
def test_financial_packet_uses_latest_announced_full_year_for_quality_metrics():
    packet = StockScreenerService._financial_packet(pd.DataFrame([
        {"end_date": "20260331", "ann_date": "20260430", "roe": 2.0},
        {"end_date": "20251231", "ann_date": "20260328", "roe": 12.0},
    ]), period_basis="latest_announced_full_year")
    assert packet["report_period"] == "2025-12-31"
    assert packet["roe"] == 12.0
    assert packet["period_basis"] == "latest_announced_full_year"
```

- [ ] **Step 2: Run the focused test and verify it fails because `period_basis` is unsupported.**

Run: `.venv\\Scripts\\python.exe -m pytest tests/test_stock_screener.py::test_financial_packet_uses_latest_announced_full_year_for_quality_metrics -q`

- [ ] **Step 3: Implement the smallest compatible selector.**

```python
def _financial_packet(cls, frame, *, period_basis="latest_report"):
    data = cls._dated_financial_rows(frame)
    if period_basis == "latest_announced_full_year":
        data = data[data["_end_date"].str.endswith("-12-31", na=False)]
    row = data.sort_values(["_end_date", "_ann_date"], ascending=False).iloc[0]
    return {"period_basis": period_basis, ...}
```

Pass `period_basis="latest_announced_full_year"` for the quality profile and expose it in `data_meta` and item financial metadata. Rename user-facing “最新财报” labels to “最近已公告年报”.

- [ ] **Step 4: Run focused tests and the stock screener suite.**

Run: `.venv\\Scripts\\python.exe -m pytest tests/test_stock_screener.py -q`

### Task 2: Price-return and all-A-share turnover semantics

**Files:**

- Modify: `app/services/stock_screener.py:1422-1459`
- Modify: `frontend/src/features/screening/ScreeningPage.tsx:169-176`
- Modify: `frontend/src/features/screening/ScreeningResults.tsx:20-48`
- Modify: `frontend/src/features/today/TodayComponents.tsx:48`
- Test: `tests/test_stock_screener.py`
- Test: `frontend/src/features/screening/ScreeningPage.test.tsx`
- Test: `frontend/src/features/today/TodayPage.test.tsx`

**Produces:** Raw `daily.close` performance is labelled as “价格涨跌幅”, never total return; the turnover card scope matches its `all_a_shares_including_beijing` source.

- [ ] **Step 1: Write failing UI/source assertions.**

```python
assert "价格涨跌幅" in item["limitations"][0]
```

```tsx
expect(screen.getByRole("columnheader", { name: "近 5 日价格涨跌" })).toBeInTheDocument();
expect(screen.getByRole("region", { name: "全市场 A 股成交额（含北交所）" })).toBeInTheDocument();
```

- [ ] **Step 2: Run tests and verify the labels are absent.**

Run: `npm run test -- ScreeningPage.test.tsx TodayPage.test.tsx`

- [ ] **Step 3: Change copy and metadata only.**

Add `price_return_basis: "unadjusted_close_to_close_excluding_cash_dividends"` to screener metadata; update labels and matched reasons to “价格涨跌幅”. Rename the turnover card to “全市场 A 股成交额（含北交所）”.

- [ ] **Step 4: Run focused frontend and backend tests.**

Run: `npm run test -- ScreeningPage.test.tsx TodayPage.test.tsx`

### Task 3: Remove approximate limit-up/down facts from the breadth contract

**Files:**

- Modify: `app/providers/market.py:2199-2260, 2390-2397`
- Modify: `tests/test_providers.py:780-823, 899-978`

**Produces:** `limit_up_count` and `limit_down_count` are `None` unless an exact per-security limit-price source is wired; response text explains that the Sina snapshot cannot identify ST and special no-limit rules.

- [ ] **Step 1: Write failing provider assertions.**

```python
assert result["breadth"]["limit_up_count"] is None
assert result["breadth"]["limit_down_count"] is None
assert "不提供精确涨跌停家数" in result["breadth"]["limit_method"]
```

- [ ] **Step 2: Run the focused test and verify current threshold counts fail it.**

Run: `.venv\\Scripts\\python.exe -m pytest tests/test_providers.py -k "sina_market_breadth" -q`

- [ ] **Step 3: Stop deriving limit counts from percentage thresholds.**

Keep the full-market advance/decline and turnover calculations unchanged. Return `None` for both limit counts and retain only an explicit unavailable-method description.

- [ ] **Step 4: Run provider tests.**

Run: `.venv\\Scripts\\python.exe -m pytest tests/test_providers.py -k "sina_market_breadth" -q`

### Task 4: Block mixed-adjustment industry attribution and surface the backtest safety boundary

**Files:**

- Modify: `app/providers/market.py:1304-1410`
- Modify: `tests/test_providers.py:639-728`
- Modify: `app/services/agent_output_guard_stock.py:913-925`
- Modify: `tests/test_agent_guard.py`
- Modify: `frontend/src/features/screening/adapters.ts:630-723`
- Modify: `frontend/src/features/screening/ScreeningPage.tsx:789-855`
- Modify: `frontend/src/features/screening/adapters.test.ts`
- Modify: `frontend/src/features/screening/ScreeningPage.test.tsx`

**Produces:** A fallback raw-price component prevents aggregate industry contribution and rankings; the frontend displays an unmissable research-only notice whenever the server returns a non-executable backtest; `.BJ` quotes use the same limit-status validation path as Shanghai/Shenzhen symbols.

- [ ] **Step 1: Write failing tests.**

```python
assert analysis["contribution"]["status"] == "incomplete_adjustment_basis"
assert analysis["contribution"]["estimated_total_contribution_pp"] is None
assert analysis["contribution"]["top_positive"] == []
```

```tsx
expect(screen.getByText("研究基线，不可用于执行或绩效宣传")).toBeInTheDocument();
```

- [ ] **Step 2: Run focused tests and verify the current aggregate/notice behavior fails.**

Run: `.venv\\Scripts\\python.exe -m pytest tests/test_providers.py -k "component_analysis" -q`

Run: `npm run test -- ScreeningPage.test.tsx adapters.test.ts`

- [ ] **Step 3: Implement exact gates.**

When `fallback_unadjusted_returns > 0`, set contribution status to `incomplete_adjustment_basis`, null total/reconciliation and return empty contribution rankings. Parse `execution_readiness` and `execution_boundary` in the frontend adapter, then display a warning before metric cards. Include `.BJ` in the quote guard’s A-share symbol set.

- [ ] **Step 4: Run focused suites.**

Run: `.venv\\Scripts\\python.exe -m pytest tests/test_providers.py tests/test_agent_guard.py -q`

Run: `npm run test -- ScreeningPage.test.tsx adapters.test.ts`

### Task 5: Integrated verification and manual path

**Files:** No source changes expected.

- [ ] **Step 1: Run static checks and focused test suites.**

Run: `git diff --check`

Run: `npm run test`

Run: `npm run build`

- [ ] **Step 2: Run backend suites when the Python 3.11 environment is available.**

Run: `py -3.11 -m pytest tests/test_stock_screener.py tests/test_providers.py tests/test_agent_guard.py tests/test_li_zong_portfolio_backtest.py -q`

- [ ] **Step 3: Manual verification.**

Open `/screening?mode=screen`, confirm quality candidates say “最近已公告年报” and price changes say “价格涨跌幅”; open `/screening?mode=backtest`, confirm the research-only warning precedes all returns; open `/today`, confirm the turnover title says “全市场 A 股成交额（含北交所）”.
