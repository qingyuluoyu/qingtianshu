-- Durable AI research state linked to the existing conversation and generic run.
CREATE TABLE IF NOT EXISTS ai_research_runs (
    run_id TEXT PRIMARY KEY REFERENCES runs(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    targets_json TEXT NOT NULL,
    question TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('running', 'completed', 'failed')),
    detail_status TEXT NOT NULL DEFAULT 'idle'
        CHECK(detail_status IN ('idle', 'running', 'completed', 'failed')),
    snapshot_json TEXT NOT NULL,
    dimensions_json TEXT NOT NULL DEFAULT '{}',
    main_answer TEXT,
    detailed_answer TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_ai_research_user_created
    ON ai_research_runs(user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_ai_research_conversation_created
    ON ai_research_runs(conversation_id, created_at DESC);
