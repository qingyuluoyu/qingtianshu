-- Expand-only investment lifecycle model. Legacy watchlist columns remain
-- readable until all callers migrate to these independent domain objects.
CREATE TABLE watchlist_items (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    name TEXT,
    priority TEXT NOT NULL CHECK(priority IN ('high', 'normal', 'low')),
    reason TEXT NOT NULL,
    catalyst_condition TEXT,
    invalidation_condition TEXT,
    tracking_frequency TEXT NOT NULL,
    tracking_status TEXT NOT NULL CHECK(tracking_status IN ('active', 'paused')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(user_id, symbol)
);

CREATE TABLE research_cases (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    watchlist_item_id TEXT REFERENCES watchlist_items(id) ON DELETE SET NULL,
    symbol TEXT NOT NULL,
    research_status TEXT NOT NULL CHECK(research_status IN (
        'draft', 'researching', 'concluded', 'expired', 'invalidated'
    )),
    question TEXT NOT NULL,
    evidence_snapshot_json TEXT NOT NULL DEFAULT '{}',
    conclusion TEXT,
    valid_from TEXT,
    valid_until TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE positions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    name TEXT,
    account_type TEXT NOT NULL CHECK(account_type IN ('simulated', 'live')),
    status TEXT NOT NULL CHECK(status IN ('open', 'closed')),
    quantity TEXT NOT NULL,
    cost_price TEXT NOT NULL,
    current_price TEXT,
    data_as_of TEXT,
    opened_at TEXT NOT NULL,
    closed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE trades (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    position_id TEXT REFERENCES positions(id) ON DELETE SET NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL CHECK(side IN ('buy', 'sell')),
    status TEXT NOT NULL CHECK(status IN ('executed', 'cancelled')),
    executed_at TEXT NOT NULL,
    price TEXT NOT NULL,
    quantity TEXT NOT NULL,
    fee TEXT NOT NULL DEFAULT '0',
    realized_pnl TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX idx_watchlist_items_user_updated
    ON watchlist_items(user_id, updated_at DESC);
CREATE INDEX idx_research_cases_user_status
    ON research_cases(user_id, research_status, updated_at DESC);
CREATE INDEX idx_positions_user_status
    ON positions(user_id, status, updated_at DESC);
CREATE INDEX idx_trades_user_executed
    ON trades(user_id, executed_at DESC);
