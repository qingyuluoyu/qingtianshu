-- Expand-only baseline for databases created before versioned migrations.
-- This migration is intentionally idempotent and does not alter business tables.
CREATE TABLE IF NOT EXISTS schema_migrations (
    migration_id TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL
);

INSERT OR IGNORE INTO schema_migrations(migration_id, applied_at)
VALUES ('0001_schema_baseline', strftime('%Y-%m-%dT%H:%M:%f+00:00', 'now'));
