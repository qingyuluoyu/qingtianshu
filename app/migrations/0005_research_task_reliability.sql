-- Expand-only durable research task state. The legacy status column is retained
-- because its original CHECK constraint cannot be widened without a table rebuild.
ALTER TABLE ai_research_runs ADD COLUMN execution_status TEXT NOT NULL DEFAULT 'pending'
    CHECK(execution_status IN ('pending', 'running', 'retry_wait', 'completed', 'failed', 'cancelled', 'expired'));
ALTER TABLE ai_research_runs ADD COLUMN version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE ai_research_runs ADD COLUMN idempotency_key TEXT;
ALTER TABLE ai_research_runs ADD COLUMN request_fingerprint TEXT;
ALTER TABLE ai_research_runs ADD COLUMN cancel_requested_at TEXT;
ALTER TABLE ai_research_runs ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE ai_research_runs ADD COLUMN max_attempts INTEGER NOT NULL DEFAULT 3;
ALTER TABLE ai_research_runs ADD COLUMN next_attempt_at TEXT;
ALTER TABLE ai_research_runs ADD COLUMN started_at TEXT;
ALTER TABLE ai_research_runs ADD COLUMN cost_usd REAL NOT NULL DEFAULT 0;
ALTER TABLE ai_research_runs ADD COLUMN expires_at TEXT;

UPDATE ai_research_runs
SET execution_status = CASE status
    WHEN 'completed' THEN 'completed'
    WHEN 'failed' THEN 'failed'
    ELSE 'running'
END;

CREATE UNIQUE INDEX idx_ai_research_idempotency
    ON ai_research_runs(user_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;

CREATE INDEX idx_ai_research_execution_status
    ON ai_research_runs(user_id, execution_status, updated_at DESC);

CREATE TABLE research_tasks (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL UNIQUE REFERENCES ai_research_runs(run_id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    task_kind TEXT NOT NULL CHECK(task_kind IN ('main', 'dimension', 'detail')),
    status TEXT NOT NULL CHECK(status IN ('pending', 'leased', 'retry_wait', 'completed', 'failed', 'cancelled', 'expired')),
    payload_json TEXT NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    available_at TEXT NOT NULL,
    lease_owner TEXT,
    lease_expires_at TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE INDEX idx_research_tasks_available
    ON research_tasks(status, available_at, created_at);
CREATE INDEX idx_research_tasks_user_status
    ON research_tasks(user_id, status, updated_at DESC);

CREATE TABLE research_task_outbox (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL UNIQUE REFERENCES research_tasks(id) ON DELETE CASCADE,
    stream_name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    published_at TEXT,
    publish_attempt_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT
);

CREATE INDEX idx_research_outbox_pending
    ON research_task_outbox(published_at, created_at);

CREATE TABLE provider_call_audits (
    id TEXT PRIMARY KEY,
    trace_id TEXT,
    run_id TEXT REFERENCES runs(id) ON DELETE SET NULL,
    provider TEXT NOT NULL,
    operation TEXT NOT NULL,
    model TEXT,
    status TEXT NOT NULL,
    duration_ms INTEGER,
    usage_json TEXT,
    cost_usd REAL,
    error_code TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX idx_provider_call_audits_run_created
    ON provider_call_audits(run_id, created_at DESC);

CREATE TABLE rate_limit_windows (
    subject_key TEXT NOT NULL,
    action TEXT NOT NULL,
    window_started_at TEXT NOT NULL,
    used_count INTEGER NOT NULL,
    PRIMARY KEY(subject_key, action, window_started_at)
);
