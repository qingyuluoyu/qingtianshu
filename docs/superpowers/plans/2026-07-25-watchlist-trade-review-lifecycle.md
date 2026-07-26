# Watchlist Trade Review Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect watchlist actions to real user-scoped positions, immutable trades, deterministic review calculations, and safe session behavior.

**Architecture:** Keep the existing modular monolith and SQLite-compatible database abstraction. Add an expand-only migration and a focused portfolio ledger service; expose typed `/api/v1/me` endpoints while retaining compatibility aliases. The frontend writes watchlist research fields separately from position and trade data.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, SQLite/PostgreSQL-compatible SQL migration conventions, vanilla JavaScript, pytest.

## Global Constraints

- A 股 only; reject unsupported markets explicitly.
- Keep legacy watchlist columns readable but stop new consumer writes.
- Trade records are immutable and user scoped.
- Use moving weighted average cost method version `moving_weighted_average_v1`.
- Never accept caller-computed realized P&L.
- Do not silently create a user when session recovery fails.
- All schema changes are expand-only and versioned.

---

### Task 1: Durable Portfolio Ledger

**Files:**
- Create: `app/migrations/0009_portfolio_ledger_contract.sql`
- Create: `app/services/portfolio_ledger.py`
- Modify: `app/db.py`
- Test: `tests/test_portfolio_ledger.py`
- Test: `tests/test_db_migrations.py`

**Interfaces:**
- Produces: `PortfolioLedger.create_position(...)`, `PortfolioLedger.record_trade(...)`, `PortfolioLedger.list_positions(...)`.
- Produces: database transaction helpers that enforce user ownership, idempotency and version compare-and-set.

- [ ] **Step 1: Write failing ledger tests**

```python
def test_create_position_records_initial_buy_and_reuses_idempotency_key(client):
    first = client.post("/api/v1/me/positions", json=POSITION)
    second = client.post("/api/v1/me/positions", json=POSITION)
    assert first.json()["id"] == second.json()["id"]

def test_partial_sell_realizes_profit_without_counting_as_closed(client):
    result = client.post(f"/api/v1/me/positions/{position_id}/trades", json=SELL_40)
    assert result.json()["position"]["quantity"] == "60"
    assert result.json()["trade"]["position_closed"] is False
```

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest tests/test_portfolio_ledger.py tests/test_db_migrations.py -q`

Expected: missing migration, service or endpoint failures.

- [ ] **Step 3: Add expand-only migration and transaction methods**

```sql
ALTER TABLE positions ADD COLUMN version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE positions ADD COLUMN method_version TEXT NOT NULL
    DEFAULT 'moving_weighted_average_v1';
ALTER TABLE trades ADD COLUMN idempotency_key TEXT;
ALTER TABLE trades ADD COLUMN position_closed INTEGER NOT NULL DEFAULT 0;
CREATE UNIQUE INDEX uq_trades_user_idempotency
    ON trades(user_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;
```

Implement a single transaction for position creation plus initial buy, and compare-and-set updates for later trades.

- [ ] **Step 4: Implement deterministic ledger calculations**

```python
new_cost = (old_quantity * old_cost + buy_quantity * price) / new_quantity
realized_gross = (sell_price - old_cost) * sell_quantity
position_closed = remaining_quantity == 0
```

Reject over-selling, closed-position trades, cross-user position IDs and conflicting idempotency payloads.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run: `pytest tests/test_portfolio_ledger.py tests/test_db_migrations.py -q`

Expected: all pass.

### Task 2: Typed Position, Trade, Watchlist and Review APIs

**Files:**
- Modify: `app/main.py`
- Modify: `app/services/trade_review.py`
- Modify: `app/db.py`
- Test: `tests/test_portfolio_api.py`
- Modify: `tests/test_trade_review.py`

**Interfaces:**
- Consumes: `PortfolioLedger`.
- Produces: `GET/POST /api/v1/me/positions`, `GET /api/v1/me/positions/{id}`, `POST /api/v1/me/positions/{id}/trades`, `GET /api/v1/me/trade-reviews`.

- [ ] **Step 1: Write failing vertical API tests**

```python
def test_watchlist_to_position_to_trade_to_review(client):
    client.post("/api/v1/me/watchlist", json=WATCH)
    position = client.post("/api/v1/me/positions", json=POSITION).json()
    client.post(f"/api/v1/me/positions/{position['id']}/trades", json=SELL_ALL)
    review = client.get("/api/v1/me/trade-reviews").json()
    assert review["summary"]["closedTradeCount"] == 1
```

Also test 404 cross-user access, 409 version conflicts, 422 over-selling and A-share validation.

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest tests/test_portfolio_api.py tests/test_trade_review.py -q`

Expected: routes and response contracts missing.

- [ ] **Step 3: Add Pydantic request contracts and routes**

Define `PositionCreate`, `TradeCreate`, validate normalized A-share symbols, require the current session user and map domain exceptions to 404/409/422.

- [ ] **Step 4: Correct review semantics**

Only trades marked `position_closed` enter `closedTrades` and the win-rate denominator. Sum all sell-trade realized gross P&L, all explicit fees and open-position unrealized P&L. Return method version and data freshness metadata.

- [ ] **Step 5: Preserve compatibility aliases**

Route `/me/trade-reviews` to the same service. Keep legacy `/me/watchlist` readable and expose old price/quantity fields under `legacy_position_hint`; new `/api/v1/me/watchlist` rejects those write fields.

- [ ] **Step 6: Run focused tests and verify GREEN**

Run: `pytest tests/test_portfolio_api.py tests/test_trade_review.py tests/test_stock_domain.py -q`

Expected: all pass.

### Task 3: Frontend Watchlist-to-Review Workflow

**Files:**
- Modify: `app/static/high-fidelity-demo.html`
- Modify: `app/static/high-fidelity-demo.js`
- Modify: `app/static/high-fidelity-demo.css`
- Modify: `tests/test_trade_review_frontend.py`
- Create: `tests/test_watchlist_lifecycle_frontend.py`

**Interfaces:**
- Consumes: typed watchlist, position, trade and review APIs from Task 2.
- Produces: separated watchlist form, position modal/form and refreshed review display.

- [ ] **Step 1: Write failing frontend contract tests**

```python
assert "watchAddPurchasePrice" not in html
assert "watchAddHoldingQuantity" not in html
assert "focus_status" not in add_watch_payload
assert "/api/v1/me/positions" in script
assert "转为模拟持仓" in script
assert "记录实盘持仓" in script
```

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest tests/test_watchlist_lifecycle_frontend.py tests/test_trade_review_frontend.py -q`

Expected: old form and status model assertions fail.

- [ ] **Step 3: Replace watchlist controls**

Keep symbol, reason, priority, catalyst, invalidation and tracking frequency. Render separate watchlist, research and position status columns.

- [ ] **Step 4: Add position and trade forms**

Create explicit simulated/live position actions. Submit quantity, price, executed time, fee, idempotency key and base version to the typed endpoints; reload both watchlist and review after success.

- [ ] **Step 5: Show legacy migration hints**

When `legacy_position_hint` exists, display “发现历史持仓线索，待确认迁移”; do not count it in position status or review.

- [ ] **Step 6: Run frontend tests and syntax check**

Run: `pytest tests/test_watchlist_lifecycle_frontend.py tests/test_trade_review_frontend.py -q`

Run: `node --check app/static/high-fidelity-demo.js`

Expected: all pass and exit code 0.

### Task 4: Session Safety and Regression Verification

**Files:**
- Modify: `app/static/high-fidelity-demo.js`
- Modify: `app/main.py`
- Modify: `tests/test_api.py`
- Modify: `tests/test_watchlist_lifecycle_frontend.py`

**Interfaces:**
- Produces: explicit 401 session-expired behavior with no implicit identity creation.

- [ ] **Step 1: Write failing session behavior tests**

```python
assert "watchRequest('/users',{method:'POST'" not in script
assert "会话已失效" in script
assert anonymous.get("/api/v1/me/positions").status_code == 401
```

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest tests/test_watchlist_lifecycle_frontend.py tests/test_api.py -q`

Expected: implicit user creation assertion fails.

- [ ] **Step 3: Implement explicit session failure handling**

Do not catch all `/session` errors as onboarding. Preserve the public user-creation endpoint only for an explicit onboarding action, and never call it from watchlist or review loading.

- [ ] **Step 4: Run affected and full regression**

Run: `pytest tests/test_portfolio_ledger.py tests/test_portfolio_api.py tests/test_trade_review.py tests/test_stock_domain.py tests/test_watchlist_lifecycle_frontend.py tests/test_trade_review_frontend.py -q`

Run: `pytest tests/test_api.py -q`

Run: `pytest -q --ignore=tests/test_api.py`

Run: `python -m compileall -q app tests`

Run: `node --check app/static/high-fidelity-demo.js`

Run: `git diff --check`

Expected: all commands exit 0; existing dependency deprecation warnings are reported, not hidden.

- [ ] **Step 5: Manual browser verification**

At 1440×900 and 390×844 verify:

- Adding a watchlist item does not create a position.
- Creating a simulated or live position updates the independent position status.
- Partial sell changes quantity but not closed-trade win rate.
- Full sell creates one closed trade and updates realized P&L.
- Expired session shows an explicit error and does not create a new user.
