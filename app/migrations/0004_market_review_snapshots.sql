CREATE TABLE IF NOT EXISTS market_review_snapshots (
    id TEXT PRIMARY KEY,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('candidate', 'formal')),
    generation_mode TEXT NOT NULL,
    source_status_json TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    UNIQUE(period_start, period_end, status)
);

CREATE TABLE IF NOT EXISTS market_review_conclusions (
    id TEXT PRIMARY KEY,
    snapshot_id TEXT NOT NULL
        REFERENCES market_review_snapshots(id) ON DELETE CASCADE,
    section TEXT NOT NULL
        CHECK(section IN ('core_events', 'highlights', 'risks', 'watch_directions')),
    ordinal INTEGER NOT NULL,
    text TEXT NOT NULL,
    source TEXT NOT NULL,
    published_at TEXT,
    url TEXT NOT NULL,
    affected_sectors_json TEXT NOT NULL,
    evidence_ids_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(snapshot_id, section, ordinal)
);

CREATE INDEX IF NOT EXISTS idx_market_review_period
    ON market_review_snapshots(period_end DESC, status, generated_at DESC);

CREATE INDEX IF NOT EXISTS idx_market_review_conclusions_snapshot
    ON market_review_conclusions(snapshot_id, section, ordinal);
