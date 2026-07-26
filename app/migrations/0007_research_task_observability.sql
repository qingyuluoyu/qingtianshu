-- Expand-only task observability fields. Existing workers can continue reading
-- the original columns during a rolling deployment.
ALTER TABLE research_tasks ADD COLUMN request_id TEXT;
ALTER TABLE research_tasks ADD COLUMN trace_id TEXT;
ALTER TABLE research_tasks ADD COLUMN heartbeat_at TEXT;
ALTER TABLE research_tasks ADD COLUMN last_error_type TEXT;
ALTER TABLE research_tasks ADD COLUMN timeout_seconds INTEGER NOT NULL DEFAULT 900;
ALTER TABLE research_tasks ADD COLUMN budget_limit_usd REAL;

CREATE INDEX idx_research_tasks_request_id
    ON research_tasks(request_id);
CREATE INDEX idx_research_tasks_trace_id
    ON research_tasks(trace_id);
