-- Durable public-data refresh tasks.
CREATE TABLE data_refresh_tasks (
    id TEXT PRIMARY KEY,
    task_kind TEXT NOT NULL
        CHECK(task_kind IN ('stock_quote', 'stock_kline', 'industry_score')),
    idempotency_key TEXT NOT NULL,
    status TEXT NOT NULL
        CHECK(status IN ('pending', 'leased', 'retry_wait', 'completed', 'failed')),
    payload_json TEXT NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    available_at TEXT NOT NULL,
    lease_owner TEXT,
    lease_expires_at TEXT,
    request_id TEXT,
    trace_id TEXT,
    last_error_type TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE UNIQUE INDEX idx_data_refresh_active_key
    ON data_refresh_tasks(idempotency_key)
    WHERE status IN ('pending', 'leased', 'retry_wait');
CREATE INDEX idx_data_refresh_available
    ON data_refresh_tasks(status, available_at, created_at);

CREATE TABLE data_refresh_task_outbox (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL UNIQUE
        REFERENCES data_refresh_tasks(id) ON DELETE CASCADE,
    stream_name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    published_at TEXT,
    publish_attempt_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT
);

CREATE INDEX idx_data_refresh_outbox_pending
    ON data_refresh_task_outbox(published_at, created_at);
