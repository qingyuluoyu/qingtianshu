# Data Health Critical Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Stop incomplete A-share market and filing-source data from being treated as usable production evidence.

**Architecture:** The Sina provider now requires each represented exchange to have complete positive turnover before it marks a snapshot available. The Eastmoney filing provider walks a bounded number of announcement pages and excludes disclosure-schedule notices unless the upstream marks a record as full report text.

**Tech Stack:** Python 3.11, FastAPI, PostgreSQL, pytest, requests.

## Global Constraints

- Preserve existing public response shapes and cache keys.
- Do not manufacture values, delete historical snapshots, or conceal upstream failures.
- Bound announcement fetching to eight pages and stop after the requested count.

---

### Task 1: Validate exchange-level turnover completeness

**Files:**

- Modify: `app/providers/market.py`
- Test: `tests/test_providers.py`

- [x] **Step 1: Add a regression case**

```python
assert result["turnover"]["status"] == "incomplete"
assert result["turnover"]["coverage"]["complete_exchanges"] is False
assert database.list_market_breadth_snapshots() == []
```

- [x] **Step 2: Verify the unmodified provider fails**

Run: `.venv-release-test\Scripts\python.exe -m pytest tests/test_providers.py::test_sina_market_breadth_rejects_exchange_with_all_zero_turnover -q`

Observed: failed because the zero-turnover Shenzhen exchange was marked `available`.

- [x] **Step 3: Implement source validation**

```python
exchange_turnover_complete = all(
    item["valid_amount"] == item["total"] and item["amount_cny"] > 0
    for item in exchanges.values()
    if item["total"] > 0
)
```

The value is now required by `turnover_complete` and exposed at `turnover.coverage.complete_exchanges`.

- [x] **Step 4: Run provider regression tests**

Run: `.venv-release-test\Scripts\python.exe -m pytest tests/test_providers.py -q`

Observed: passed (no test failure output).

### Task 2: Retrieve and select full A-share reports correctly

**Files:**

- Modify: `app/providers/filings.py`
- Test: `tests/test_filings.py`

- [x] **Step 1: Add a later-page report regression**

```python
assert [report["article_code"] for report in reports] == ["AN2026Q1"]
assert requested_pages == [1, 2]
```

- [x] **Step 2: Verify the old one-page implementation fails**

Run: `.venv-release-test\Scripts\python.exe -m pytest tests/test_filings.py::test_provider_scans_later_announcement_page_for_financial_report -q`

Observed: failed because page 1 contained no eligible report.

- [x] **Step 3: Implement bounded paging and de-duplication**

```python
for page_index in range(1, self.max_announcement_pages + 1):
    # fetch page, retain the existing report mapping, return at requested limit
```

`max_announcement_pages` defaults to 8. A later regression excludes `预约披露时间` records with no full-report column.

- [x] **Step 4: Verify real upstream selection**

Run: `.venv-release-test\Scripts\python.exe -c "...list_financial_reports('300308.SZ', limit=3)..."`

Observed: returned `AN202604161821269635` for report period `2026-03-31`, plus 2025 annual and third-quarter reports.

### Task 3: Refresh runtime cache and release verification

**Files:**

- Modify: no additional source files.
- Test: backend health endpoints, full backend suite, frontend tests and build.

- [x] **Step 1: Restart the local backend on port 8020 and wait for scheduled refreshes.**
- [x] **Step 2: Check `/system/data-health`, `/markets/breadth`, and `/a-share/300308/filings`.**
- [x] **Step 3: Run full backend, frontend, and build gates; record actual outcomes.**

Observed: `/health` returned `ok`; `/system/data-health` reported 0 critical and 5 attention. The 300308 endpoint returned the 2026-03-31 filing from `pdf.dfcfw.com` with a content hash and 38,374 extracted characters. `npm test -- --run` passed 34 files and 190 tests; `npm run build` passed. The complete backend suite was started but could not complete because the local PostgreSQL instance exhausted available connection slots while tests were using the same configured database as the running local backend. Focused provider, filing, and data-health tests passed after the code changes.

- [ ] **Step 4: Push verified commits to `origin/react-04-chang`.**

### Task 4: Recover official PDF text when the content API is unavailable

**Files:**

- Modify: `app/providers/filings.py`
- Test: `tests/test_filings.py`

- [x] **Step 1: Add a proxy-failure regression test.**

The test forces `CONTENT_URL` to raise `ProxyError`, supplies a valid PDF response, and asserts a converted full-text document with the official PDF URL and an explicit fallback warning.

- [x] **Step 2: Implement the bounded official-PDF fallback.**

`fetch_document()` now tries `CONTENT_URL` first. On request or content-provider failure it fetches `https://pdf.dfcfw.com/pdf/H2_{article_code}_1.pdf`, passes bytes through `DocumentConversionService`, checks a 100-character minimum, and stores a SHA-256 content hash.

- [x] **Step 3: Verify the real 300308 refresh.**

Observed: three official reports were stored; the 2026-03-31 report contained 38,374 characters and five explicit company explanations. No fallback warning was lost and no synthetic filing was created.
