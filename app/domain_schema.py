from __future__ import annotations

# Declarative PostgreSQL bootstrap schema. Incremental compatibility
# migrations remain in Database.initialize so data backfills stay explicit.
DOMAIN_SCHEMA_SQL = r"""
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    workspace_path TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS user_sessions (
                    id TEXT PRIMARY KEY,
                    token_hash TEXT NOT NULL UNIQUE,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    revoked_at TEXT
                );

                CREATE TABLE IF NOT EXISTS user_uploads (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    kind TEXT NOT NULL,
                    original_name TEXT NOT NULL,
                    mime_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    width INTEGER NOT NULL,
                    height INTEGER NOT NULL,
                    workspace_path TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    used_at TEXT
                );

                CREATE TABLE IF NOT EXISTS watchlist (
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    symbol TEXT NOT NULL,
                    name TEXT,
                    market TEXT,
                    thesis TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, symbol)
                );

                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    kind TEXT NOT NULL,
                    content TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('candidate', 'confirmed', 'rejected')),
                    created_at TEXT NOT NULL,
                    confirmed_at TEXT
                );

                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    intent TEXT NOT NULL,
                    model_tier TEXT NOT NULL,
                    status TEXT NOT NULL,
                    input_json TEXT NOT NULL,
                    evidence_json TEXT,
                    answer TEXT,
                    usage_json TEXT,
                    error TEXT,
                    workspace_path TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    finished_at TEXT
                );

                CREATE TABLE IF NOT EXISTS stock_workspaces (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    symbol TEXT NOT NULL,
                    name TEXT,
                    market TEXT,
                    relation_type TEXT NOT NULL
                        CHECK(relation_type IN ('watching', 'holding', 'ended')),
                    priority TEXT
                        CHECK(priority IS NULL OR priority IN ('high', 'normal', 'low')),
                    tracking_status TEXT NOT NULL
                        CHECK(tracking_status IN ('active', 'paused')),
                    workflow_status TEXT NOT NULL
                        CHECK(workflow_status IN ('idle', 'researching', 'waiting_data')),
                    attention_tags_json TEXT NOT NULL DEFAULT '[]',
                    version INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    ended_at TEXT,
                    UNIQUE(user_id, symbol)
                );

                CREATE TABLE IF NOT EXISTS stock_relation_history (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL
                        REFERENCES stock_workspaces(id) ON DELETE CASCADE,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    relation_type TEXT NOT NULL
                        CHECK(relation_type IN ('watching', 'holding', 'ended')),
                    priority TEXT
                        CHECK(priority IS NULL OR priority IN ('high', 'normal', 'low')),
                    tracking_status TEXT NOT NULL
                        CHECK(tracking_status IN ('active', 'paused')),
                    source TEXT NOT NULL,
                    effective_at TEXT NOT NULL,
                    ended_at TEXT
                );

                CREATE TABLE IF NOT EXISTS thesis_versions (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL
                        REFERENCES stock_workspaces(id) ON DELETE CASCADE,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    symbol TEXT NOT NULL,
                    version_no INTEGER NOT NULL,
                    status TEXT NOT NULL CHECK(status IN (
                        'draft', 'pending_confirmation', 'active',
                        'superseded', 'invalidated', 'rejected'
                    )),
                    reason_text TEXT NOT NULL,
                    watch_items_json TEXT NOT NULL DEFAULT '[]',
                    recheck_conditions_json TEXT NOT NULL DEFAULT '[]',
                    source TEXT NOT NULL,
                    source_run_id TEXT REFERENCES runs(id) ON DELETE SET NULL,
                    base_version INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    confirmed_at TEXT,
                    superseded_at TEXT,
                    UNIQUE(workspace_id, version_no)
                );

                CREATE TABLE IF NOT EXISTS ai_citations (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
                    claim_id TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    source_key TEXT,
                    source_url TEXT,
                    evidence_type TEXT NOT NULL,
                    data_time TEXT,
                    report_period TEXT,
                    excerpt TEXT NOT NULL,
                    limitations_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    UNIQUE(user_id, run_id, claim_id)
                );

                CREATE TABLE IF NOT EXISTS ai_writeback_candidates (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
                    conversation_id TEXT
                        REFERENCES conversations(id) ON DELETE SET NULL,
                    workspace_id TEXT NOT NULL
                        REFERENCES stock_workspaces(id) ON DELETE CASCADE,
                    symbol TEXT NOT NULL,
                    candidate_type TEXT NOT NULL
                        CHECK(candidate_type IN (
                            'thesis', 'observation_task',
                            'action_plan', 'review_draft'
                        )),
                    status TEXT NOT NULL CHECK(status IN (
                        'pending_confirmation', 'confirmed', 'rejected', 'stale'
                    )),
                    payload_json TEXT NOT NULL,
                    citation_ids_json TEXT NOT NULL DEFAULT '[]',
                    base_version INTEGER NOT NULL,
                    target_object_id TEXT,
                    created_at TEXT NOT NULL,
                    resolved_at TEXT,
                    UNIQUE(user_id, run_id, candidate_type)
                );

                CREATE TABLE IF NOT EXISTS observation_tasks (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    workspace_id TEXT
                        REFERENCES stock_workspaces(id) ON DELETE SET NULL,
                    symbol TEXT NOT NULL,
                    thesis_id TEXT REFERENCES thesis_versions(id) ON DELETE SET NULL,
                    change_ref TEXT,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN (
                        'pending', 'in_progress', 'waiting_data',
                        'completed', 'ignored', 'cancelled'
                    )),
                    priority TEXT NOT NULL
                        CHECK(priority IN ('high', 'normal', 'low')),
                    source_type TEXT NOT NULL
                        CHECK(source_type IN ('user', 'research_action')),
                    source_ref_id TEXT,
                    dedupe_key TEXT,
                    due_at TEXT,
                    result_text TEXT,
                    completion_evidence_json TEXT NOT NULL DEFAULT '[]',
                    version INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT,
                    ignored_at TEXT,
                    cancelled_at TEXT,
                    UNIQUE(user_id, dedupe_key)
                );

                CREATE TABLE IF NOT EXISTS observation_task_history (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL
                        REFERENCES observation_tasks(id) ON DELETE CASCADE,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    version INTEGER NOT NULL,
                    event_type TEXT NOT NULL CHECK(event_type IN (
                        'created', 'updated', 'status_changed', 'reopened'
                    )),
                    from_status TEXT,
                    to_status TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(task_id, version)
                );

                CREATE UNIQUE INDEX IF NOT EXISTS uq_stock_workspaces_scope
                ON stock_workspaces(id, user_id);

                CREATE TABLE IF NOT EXISTS action_plans (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    workspace_id TEXT NOT NULL,
                    action_type TEXT NOT NULL CHECK(action_type IN (
                        'buy', 'add', 'reduce', 'sell', 'hold'
                    )),
                    trigger_text TEXT NOT NULL,
                    target_quantity TEXT,
                    target_amount TEXT,
                    target_position_percent TEXT,
                    thesis_version_id TEXT
                        REFERENCES thesis_versions(id) ON DELETE SET NULL,
                    check_result_json TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN (
                        'draft', 'checked', 'saved', 'partially_executed',
                        'executed', 'cancelled', 'expired'
                    )),
                    expires_at TEXT,
                    idempotency_key TEXT,
                    version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(id, user_id, workspace_id),
                    FOREIGN KEY(workspace_id, user_id)
                        REFERENCES stock_workspaces(id, user_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS action_plan_history (
                    id TEXT PRIMARY KEY,
                    plan_id TEXT NOT NULL,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    workspace_id TEXT NOT NULL,
                    version INTEGER NOT NULL CHECK(version > 0),
                    event_type TEXT NOT NULL,
                    from_status TEXT CHECK(
                        from_status IS NULL OR from_status IN (
                            'draft', 'checked', 'saved', 'partially_executed',
                            'executed', 'cancelled', 'expired'
                        )
                    ),
                    to_status TEXT NOT NULL CHECK(to_status IN (
                        'draft', 'checked', 'saved', 'partially_executed',
                        'executed', 'cancelled', 'expired'
                    )),
                    snapshot_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    UNIQUE(plan_id, version),
                    FOREIGN KEY(plan_id, user_id, workspace_id)
                        REFERENCES action_plans(id, user_id, workspace_id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS position_openings (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL UNIQUE
                        REFERENCES stock_workspaces(id) ON DELETE CASCADE,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    symbol TEXT NOT NULL,
                    as_of_date TEXT NOT NULL,
                    quantity TEXT NOT NULL,
                    cost_price TEXT NOT NULL,
                    fees TEXT,
                    note TEXT,
                    idempotency_key TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(user_id, idempotency_key)
                );

                CREATE TABLE IF NOT EXISTS position_operations (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL
                        REFERENCES stock_workspaces(id) ON DELETE CASCADE,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    symbol TEXT NOT NULL,
                    operation_type TEXT NOT NULL CHECK(operation_type IN (
                        'buy', 'add', 'reduce', 'sell'
                    )),
                    operated_at TEXT NOT NULL,
                    price TEXT NOT NULL,
                    quantity TEXT NOT NULL,
                    fees TEXT,
                    reason_text TEXT NOT NULL,
                    plan_id TEXT,
                    idempotency_key TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(user_id, idempotency_key)
                );

                CREATE TABLE IF NOT EXISTS operation_revisions (
                    id TEXT PRIMARY KEY,
                    operation_id TEXT NOT NULL
                        REFERENCES position_operations(id) ON DELETE CASCADE,
                    workspace_id TEXT NOT NULL
                        REFERENCES stock_workspaces(id) ON DELETE CASCADE,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    revision_no INTEGER NOT NULL,
                    price TEXT NOT NULL,
                    quantity TEXT NOT NULL,
                    fees TEXT,
                    reason_text TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(operation_id, revision_no),
                    UNIQUE(user_id, idempotency_key)
                );

                CREATE TABLE IF NOT EXISTS position_adjustments (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL
                        REFERENCES stock_workspaces(id) ON DELETE CASCADE,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    symbol TEXT NOT NULL,
                    adjustment_type TEXT NOT NULL CHECK(adjustment_type IN (
                        'quantity_correction', 'cost_correction',
                        'corporate_action', 'other'
                    )),
                    effective_at TEXT NOT NULL,
                    quantity_delta TEXT NOT NULL,
                    cost_delta TEXT NOT NULL,
                    reason_text TEXT NOT NULL,
                    evidence_text TEXT,
                    idempotency_key TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(user_id, idempotency_key)
                );

                CREATE TABLE IF NOT EXISTS position_snapshots (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL
                        REFERENCES stock_workspaces(id) ON DELETE CASCADE,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    symbol TEXT NOT NULL,
                    snapshot_at TEXT NOT NULL,
                    source_event_type TEXT NOT NULL CHECK(source_event_type IN (
                        'opening', 'operation', 'operation_revision', 'adjustment'
                    )),
                    source_event_id TEXT NOT NULL,
                    quantity TEXT NOT NULL,
                    cost_basis TEXT NOT NULL,
                    average_cost TEXT,
                    realized_gross_pnl TEXT NOT NULL,
                    realized_net_pnl TEXT,
                    known_fees TEXT NOT NULL,
                    fees_complete INTEGER NOT NULL CHECK(fees_complete IN (0, 1)),
                    data_status TEXT NOT NULL CHECK(data_status IN (
                        'complete', 'partial', 'conflict'
                    )),
                    warnings_json TEXT NOT NULL DEFAULT '[]',
                    calculation_version TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(
                        workspace_id, source_event_type, source_event_id,
                        calculation_version
                    )
                );

                CREATE INDEX IF NOT EXISTS idx_position_operations_workspace_time
                ON position_operations(workspace_id, operated_at, created_at);

                CREATE INDEX IF NOT EXISTS idx_position_adjustments_workspace_time
                ON position_adjustments(workspace_id, effective_at, created_at);

                CREATE INDEX IF NOT EXISTS idx_position_snapshots_workspace_time
                ON position_snapshots(workspace_id, snapshot_at DESC, created_at DESC);

                CREATE UNIQUE INDEX IF NOT EXISTS uq_position_operations_scope
                ON position_operations(id, user_id, workspace_id);

                CREATE TABLE IF NOT EXISTS operation_context_snapshots (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    workspace_id TEXT NOT NULL,
                    operation_id TEXT NOT NULL,
                    plan_id TEXT,
                    thesis_version_id TEXT
                        REFERENCES thesis_versions(id) ON DELETE SET NULL,
                    snapshot_json TEXT NOT NULL DEFAULT '{}',
                    data_time TEXT NOT NULL,
                    snapshot_version TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(operation_id),
                    FOREIGN KEY(operation_id, user_id, workspace_id)
                        REFERENCES position_operations(id, user_id, workspace_id),
                    FOREIGN KEY(plan_id, user_id, workspace_id)
                        REFERENCES action_plans(id, user_id, workspace_id)
                );

                CREATE TABLE IF NOT EXISTS trade_reviews (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    workspace_id TEXT NOT NULL,
                    operation_id TEXT,
                    plan_id TEXT,
                    status TEXT NOT NULL DEFAULT 'waiting_data' CHECK(status IN (
                        'waiting_data', 'ready', 'draft', 'confirmed',
                        'archived', 'revised'
                    )),
                    horizon_sessions INTEGER NOT NULL CHECK(horizon_sessions > 0),
                    data_status TEXT NOT NULL DEFAULT 'missing' CHECK(data_status IN (
                        'fresh', 'delayed', 'stale', 'missing', 'failed',
                        'conflict', 'not_applicable'
                    )),
                    current_version_id TEXT
                        REFERENCES trade_review_versions(id) ON DELETE SET NULL,
                    ready_at TEXT,
                    confirmed_at TEXT,
                    archived_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(id, user_id, workspace_id),
                    UNIQUE(user_id, workspace_id, operation_id, horizon_sessions),
                    FOREIGN KEY(workspace_id, user_id)
                        REFERENCES stock_workspaces(id, user_id) ON DELETE CASCADE,
                    FOREIGN KEY(operation_id, user_id, workspace_id)
                        REFERENCES position_operations(id, user_id, workspace_id),
                    FOREIGN KEY(plan_id, user_id, workspace_id)
                        REFERENCES action_plans(id, user_id, workspace_id)
                );

                CREATE TABLE IF NOT EXISTS trade_review_versions (
                    id TEXT PRIMARY KEY,
                    review_id TEXT NOT NULL,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    workspace_id TEXT NOT NULL,
                    version_no INTEGER NOT NULL CHECK(version_no > 0),
                    price_result TEXT,
                    logic_result TEXT,
                    plan_deviation TEXT,
                    bias_tags_json TEXT NOT NULL DEFAULT '[]',
                    improvement_text TEXT,
                    created_source TEXT NOT NULL CHECK(created_source IN ('ai', 'user')),
                    source_run_id TEXT REFERENCES runs(id) ON DELETE SET NULL,
                    status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN (
                        'draft', 'confirmed', 'revised'
                    )),
                    created_at TEXT NOT NULL,
                    UNIQUE(review_id, version_no),
                    FOREIGN KEY(review_id, user_id, workspace_id)
                        REFERENCES trade_reviews(id, user_id, workspace_id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_action_plans_scope_status
                ON action_plans(user_id, workspace_id, status, updated_at DESC);

                CREATE INDEX IF NOT EXISTS idx_action_plan_history_scope_version
                ON action_plan_history(
                    user_id, workspace_id, plan_id, version DESC
                );

                CREATE INDEX IF NOT EXISTS idx_operation_context_scope_time
                ON operation_context_snapshots(
                    user_id, workspace_id, data_time DESC
                );

                CREATE INDEX IF NOT EXISTS idx_trade_reviews_scope_status
                ON trade_reviews(user_id, workspace_id, status, updated_at DESC);

                CREATE INDEX IF NOT EXISTS idx_trade_reviews_operation_horizon
                ON trade_reviews(operation_id, horizon_sessions, updated_at DESC);

                CREATE INDEX IF NOT EXISTS idx_trade_review_versions_scope_version
                ON trade_review_versions(
                    user_id, workspace_id, review_id, version_no DESC
                );

                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    title TEXT NOT NULL,
                    quality_scope TEXT NOT NULL DEFAULT 'user',
                    status TEXT NOT NULL DEFAULT 'active'
                        CHECK(status IN ('active', 'archived')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    archived_at TEXT
                );

                CREATE TABLE IF NOT EXISTS conversation_messages (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL
                        REFERENCES conversations(id) ON DELETE CASCADE,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    intent TEXT,
                    run_id TEXT REFERENCES runs(id) ON DELETE SET NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS knowledge_documents (
                    id TEXT PRIMARY KEY,
                    owner_user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
                    scope TEXT NOT NULL CHECK(scope IN ('common', 'user')),
                    title TEXT NOT NULL,
                    original_name TEXT NOT NULL,
                    mime_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    source_key TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(scope, owner_user_id, source_key)
                );

                CREATE TABLE IF NOT EXISTS market_cache (
                    cache_key TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    source TEXT NOT NULL,
                    market_at TEXT,
                    fetched_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS market_breadth_snapshots (
                    market_date TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    source TEXT NOT NULL,
                    fetched_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS articles (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    kind TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    body TEXT NOT NULL,
                    status TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    run_id TEXT REFERENCES runs(id) ON DELETE SET NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS market_bars (
                    symbol TEXT NOT NULL,
                    interval TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    open REAL,
                    high REAL,
                    low REAL,
                    close REAL NOT NULL,
                    adjusted_close REAL,
                    volume INTEGER,
                    source TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    PRIMARY KEY (symbol, interval, timestamp)
                );

                CREATE TABLE IF NOT EXISTS background_job_runs (
                    id TEXT PRIMARY KEY,
                    job_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    summary_json TEXT,
                    error TEXT,
                    started_at TEXT NOT NULL,
                    finished_at TEXT
                );

                CREATE TABLE IF NOT EXISTS data_health_snapshots (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tushare_sync_runs (
                    id TEXT PRIMARY KEY,
                    job_scope TEXT NOT NULL,
                    status TEXT NOT NULL
                        CHECK(status IN ('running', 'stable', 'partial', 'failed')),
                    as_of_date TEXT,
                    data_version TEXT,
                    datasets_json TEXT NOT NULL,
                    summary_json TEXT,
                    error TEXT,
                    started_at TEXT NOT NULL,
                    finished_at TEXT
                );

                CREATE TABLE IF NOT EXISTS tushare_dataset_snapshots (
                    id TEXT PRIMARY KEY,
                    dataset TEXT NOT NULL,
                    scope_key TEXT NOT NULL,
                    as_of_date TEXT,
                    report_period TEXT,
                    source_updated_at TEXT,
                    sync_run_id TEXT NOT NULL
                        REFERENCES tushare_sync_runs(id) ON DELETE CASCADE,
                    data_version TEXT NOT NULL,
                    data_status TEXT NOT NULL
                        CHECK(data_status IN ('stable', 'incomplete')),
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(dataset, scope_key, data_version)
                );

                CREATE TABLE IF NOT EXISTS strategy_definitions (
                    strategy_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    status TEXT NOT NULL
                        CHECK(status IN ('active', 'paused', 'retired')),
                    owner_type TEXT NOT NULL DEFAULT 'system',
                    current_version TEXT NOT NULL,
                    boundary TEXT NOT NULL,
                    subscriptions_enabled INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS strategy_versions (
                    id TEXT PRIMARY KEY,
                    strategy_id TEXT NOT NULL
                        REFERENCES strategy_definitions(strategy_id) ON DELETE CASCADE,
                    version TEXT NOT NULL,
                    method TEXT NOT NULL,
                    rules_json TEXT NOT NULL,
                    formulas_json TEXT NOT NULL,
                    change_notes TEXT NOT NULL,
                    published_at TEXT NOT NULL,
                    UNIQUE(strategy_id, version)
                );

                CREATE TABLE IF NOT EXISTS strategy_parameter_versions (
                    id TEXT PRIMARY KEY,
                    strategy_id TEXT NOT NULL
                        REFERENCES strategy_definitions(strategy_id) ON DELETE CASCADE,
                    strategy_version TEXT NOT NULL,
                    parameter_version TEXT NOT NULL,
                    parameters_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(strategy_id, strategy_version, parameter_version)
                );

                CREATE TABLE IF NOT EXISTS strategy_screen_runs (
                    id TEXT PRIMARY KEY,
                    strategy_id TEXT NOT NULL
                        REFERENCES strategy_definitions(strategy_id) ON DELETE CASCADE,
                    strategy_version TEXT NOT NULL,
                    parameter_version TEXT NOT NULL,
                    data_version TEXT NOT NULL,
                    data_versions_json TEXT NOT NULL,
                    as_of_date TEXT,
                    run_scope TEXT NOT NULL DEFAULT 'symbol_batch',
                    universe_count INTEGER NOT NULL DEFAULT 0,
                    prefiltered_count INTEGER NOT NULL DEFAULT 0,
                    coverage_ratio REAL NOT NULL DEFAULT 0,
                    warnings_json TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL
                        CHECK(status IN ('running', 'completed', 'partial', 'failed')),
                    requested_count INTEGER NOT NULL,
                    processed_count INTEGER NOT NULL DEFAULT 0,
                    qualified_count INTEGER NOT NULL DEFAULT 0,
                    triggered_count INTEGER NOT NULL DEFAULT 0,
                    incomplete_count INTEGER NOT NULL DEFAULT 0,
                    invalidated_count INTEGER NOT NULL DEFAULT 0,
                    error TEXT,
                    started_at TEXT NOT NULL,
                    finished_at TEXT
                );

                CREATE TABLE IF NOT EXISTS strategy_candidate_snapshots (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL
                        REFERENCES strategy_screen_runs(id) ON DELETE CASCADE,
                    strategy_id TEXT NOT NULL
                        REFERENCES strategy_definitions(strategy_id) ON DELETE CASCADE,
                    strategy_version TEXT NOT NULL,
                    parameter_version TEXT NOT NULL,
                    data_version TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    as_of_date TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN (
                        'qualified', 'triggered', 'not_qualified',
                        'data_incomplete', 'invalidated'
                    )),
                    evaluation_status TEXT NOT NULL CHECK(evaluation_status IN (
                        'qualified', 'triggered', 'not_qualified', 'data_incomplete'
                    )),
                    previous_status TEXT,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    invalidated_at TEXT,
                    UNIQUE(
                        strategy_id, strategy_version, parameter_version,
                        data_version, symbol
                    )
                );

                CREATE TABLE IF NOT EXISTS strategy_rule_results (
                    id TEXT PRIMARY KEY,
                    candidate_snapshot_id TEXT NOT NULL
                        REFERENCES strategy_candidate_snapshots(id) ON DELETE CASCADE,
                    rule_id TEXT NOT NULL,
                    status TEXT NOT NULL
                        CHECK(status IN ('passed', 'failed', 'data_incomplete')),
                    actual_value_json TEXT,
                    threshold_json TEXT NOT NULL,
                    evidence_date TEXT,
                    report_period TEXT,
                    source TEXT NOT NULL,
                    formula_version TEXT NOT NULL,
                    limitations_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(candidate_snapshot_id, rule_id)
                );

                CREATE TABLE IF NOT EXISTS strategy_trigger_events (
                    id TEXT PRIMARY KEY,
                    candidate_snapshot_id TEXT NOT NULL
                        REFERENCES strategy_candidate_snapshots(id) ON DELETE CASCADE,
                    strategy_id TEXT NOT NULL
                        REFERENCES strategy_definitions(strategy_id) ON DELETE CASCADE,
                    strategy_version TEXT NOT NULL,
                    parameter_version TEXT NOT NULL,
                    data_version TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    rule_id TEXT NOT NULL,
                    evidence_date TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(
                        strategy_id, strategy_version, parameter_version,
                        symbol, rule_id, evidence_date
                    )
                );

                CREATE TABLE IF NOT EXISTS strategy_backtest_market_cap_days (
                    strategy_id TEXT NOT NULL
                        REFERENCES strategy_definitions(strategy_id) ON DELETE CASCADE,
                    backtest_version TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    universe_count INTEGER NOT NULL,
                    eligible_count INTEGER NOT NULL,
                    data_version TEXT NOT NULL,
                    source TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(strategy_id, backtest_version, trade_date)
                );

                CREATE TABLE IF NOT EXISTS strategy_backtest_market_caps (
                    strategy_id TEXT NOT NULL
                        REFERENCES strategy_definitions(strategy_id) ON DELETE CASCADE,
                    backtest_version TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    total_mv_yi REAL NOT NULL,
                    data_version TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(
                        strategy_id, backtest_version, trade_date, symbol
                    )
                );

                CREATE TABLE IF NOT EXISTS strategy_backtest_symbol_states (
                    strategy_id TEXT NOT NULL
                        REFERENCES strategy_definitions(strategy_id) ON DELETE CASCADE,
                    strategy_version TEXT NOT NULL,
                    parameter_version TEXT NOT NULL,
                    backtest_version TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN (
                        'qualified', 'triggered', 'not_qualified',
                        'data_incomplete'
                    )),
                    candidate_qualified INTEGER NOT NULL DEFAULT 0,
                    adjusted_open REAL,
                    adjusted_close REAL,
                    raw_open REAL,
                    raw_close REAL,
                    source_data_version TEXT NOT NULL,
                    data_version TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(
                        strategy_id, strategy_version, parameter_version,
                        backtest_version, symbol, trade_date
                    )
                );

                CREATE TABLE IF NOT EXISTS strategy_backtest_symbol_coverage (
                    strategy_id TEXT NOT NULL
                        REFERENCES strategy_definitions(strategy_id) ON DELETE CASCADE,
                    strategy_version TEXT NOT NULL,
                    parameter_version TEXT NOT NULL,
                    backtest_version TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    start_date TEXT,
                    end_date TEXT,
                    evaluated_days INTEGER NOT NULL DEFAULT 0,
                    source_data_version TEXT NOT NULL,
                    data_version TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('stable', 'incomplete')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(
                        strategy_id, strategy_version, parameter_version,
                        backtest_version, symbol
                    )
                );

                CREATE TABLE IF NOT EXISTS news_items (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    category TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT,
                    source TEXT NOT NULL,
                    url TEXT NOT NULL,
                    published_at TEXT,
                    engagement REAL,
                    fetched_at TEXT NOT NULL,
                    UNIQUE(symbol, source, url)
                );

                CREATE TABLE IF NOT EXISTS sentiment_snapshots (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    score REAL NOT NULL,
                    band TEXT NOT NULL,
                    confidence TEXT NOT NULL,
                    sample_size INTEGER NOT NULL,
                    positive_count INTEGER NOT NULL,
                    negative_count INTEGER NOT NULL,
                    neutral_count INTEGER NOT NULL,
                    method TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS valuation_snapshots (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    name TEXT NOT NULL,
                    currency TEXT NOT NULL,
                    price REAL,
                    previous_close REAL,
                    pct_change REAL,
                    turnover_rate_pct REAL,
                    pe_ttm REAL,
                    pe_dynamic REAL,
                    pe_static REAL,
                    pb REAL,
                    float_market_cap REAL,
                    total_market_cap REAL,
                    market_timestamp TEXT NOT NULL,
                    source TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    field_mapping TEXT NOT NULL,
                    warnings_json TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    UNIQUE(symbol, source, market_timestamp)
                );

                CREATE TABLE IF NOT EXISTS financial_periods (
                    symbol TEXT NOT NULL,
                    report_date TEXT NOT NULL,
                    report_type TEXT NOT NULL,
                    report_date_name TEXT NOT NULL,
                    notice_date TEXT,
                    name TEXT NOT NULL,
                    currency TEXT NOT NULL,
                    eps_basic REAL,
                    eps_diluted REAL,
                    book_value_per_share REAL,
                    revenue REAL,
                    revenue_yoy_pct REAL,
                    parent_net_profit REAL,
                    net_profit_yoy_pct REAL,
                    roe_weighted_pct REAL,
                    gross_margin_pct REAL,
                    net_margin_pct REAL,
                    debt_asset_ratio_pct REAL,
                    operating_cashflow REAL,
                    operating_cashflow_per_share REAL,
                    total_assets REAL,
                    total_liabilities REAL,
                    total_equity REAL,
                    period_basis TEXT NOT NULL,
                    source TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    warnings_json TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    PRIMARY KEY(symbol, report_date, report_type)
                );

                CREATE TABLE IF NOT EXISTS earnings_quality_snapshots (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    report_date TEXT NOT NULL,
                    method TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(symbol, report_date, method)
                );

                CREATE TABLE IF NOT EXISTS financial_statement_details (
                    symbol TEXT NOT NULL,
                    report_date TEXT NOT NULL,
                    report_type TEXT NOT NULL,
                    report_date_name TEXT NOT NULL,
                    notice_date TEXT,
                    name TEXT NOT NULL,
                    currency TEXT NOT NULL,
                    fiscal_period TEXT NOT NULL,
                    period_basis TEXT NOT NULL,
                    statement_type TEXT NOT NULL
                        CHECK(statement_type IN ('income', 'balance', 'cashflow')),
                    fields_json TEXT NOT NULL,
                    source TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    warnings_json TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    PRIMARY KEY(symbol, report_date, report_type, statement_type)
                );

                CREATE TABLE IF NOT EXISTS financial_driver_snapshots (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    report_date TEXT NOT NULL,
                    method TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(symbol, report_date, method)
                );

                CREATE TABLE IF NOT EXISTS filing_documents (
                    symbol TEXT NOT NULL,
                    article_code TEXT NOT NULL,
                    title TEXT NOT NULL,
                    document_type TEXT NOT NULL,
                    report_period TEXT,
                    notice_date TEXT,
                    published_at TEXT,
                    content_text TEXT NOT NULL,
                    attach_url TEXT,
                    content_hash TEXT NOT NULL,
                    source TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    warnings_json TEXT NOT NULL DEFAULT '[]',
                    fetched_at TEXT NOT NULL,
                    PRIMARY KEY(symbol, article_code)
                );

                CREATE TABLE IF NOT EXISTS filing_evidence_snapshots (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    article_code TEXT NOT NULL,
                    report_period TEXT,
                    method TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(symbol, article_code, method),
                    FOREIGN KEY(symbol, article_code)
                        REFERENCES filing_documents(symbol, article_code)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS business_segment_rows (
                    symbol TEXT NOT NULL,
                    report_date TEXT NOT NULL,
                    classification TEXT NOT NULL
                        CHECK(classification IN ('industry', 'product', 'region')),
                    item_name TEXT NOT NULL,
                    revenue REAL,
                    revenue_share_pct REAL,
                    cost REAL,
                    cost_share_pct REAL,
                    gross_profit REAL,
                    gross_profit_share_pct REAL,
                    gross_margin_pct REAL,
                    source TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    PRIMARY KEY(symbol, report_date, classification, item_name)
                );

                CREATE TABLE IF NOT EXISTS business_structure_snapshots (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    anchor_report_date TEXT NOT NULL,
                    method TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(symbol, anchor_report_date, method)
                );

                CREATE TABLE IF NOT EXISTS peer_operating_snapshots (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    anchor_report_date TEXT NOT NULL,
                    method TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(symbol, fingerprint)
                );

                CREATE TABLE IF NOT EXISTS shareholder_structure_snapshots (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    name TEXT NOT NULL,
                    holder_count_as_of TEXT NOT NULL,
                    announced_at TEXT,
                    holder_count INTEGER,
                    previous_holder_count INTEGER,
                    holder_count_change INTEGER,
                    change_pct REAL,
                    average_holding REAL,
                    average_market_cap REAL,
                    interval_price_change_pct REAL,
                    top10_report_date TEXT,
                    top10_ratio REAL,
                    top3_ratio REAL,
                    top_holders_json TEXT NOT NULL,
                    method TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(symbol, holder_count_as_of, method)
                );

                CREATE TABLE IF NOT EXISTS analyst_expectation_snapshots (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    name TEXT NOT NULL,
                    as_of_date TEXT NOT NULL,
                    latest_report_date TEXT,
                    rating_organization_count INTEGER,
                    method TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(symbol, fingerprint)
                );

                CREATE TABLE IF NOT EXISTS event_timeline_snapshots (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    name TEXT NOT NULL,
                    as_of_date TEXT NOT NULL,
                    method TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(symbol, fingerprint)
                );

                CREATE TABLE IF NOT EXISTS change_events (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    fact_summary TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    detected_at TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    source_url TEXT,
                    data_status TEXT NOT NULL,
                    rule_version TEXT NOT NULL,
                    dedupe_hash TEXT NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS user_change_links (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    change_event_id TEXT NOT NULL
                        REFERENCES change_events(id) ON DELETE CASCADE,
                    symbol TEXT NOT NULL,
                    relevance_status TEXT NOT NULL DEFAULT 'pending'
                        CHECK(relevance_status IN ('pending', 'relevant', 'irrelevant')),
                    read_at TEXT,
                    handled_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(user_id, change_event_id)
                );

                CREATE TABLE IF NOT EXISTS research_reports (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    name TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    body TEXT NOT NULL,
                    status TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    run_id TEXT REFERENCES runs(id) ON DELETE SET NULL,
                    market_timestamp TEXT,
                    generated_at TEXT NOT NULL,
                    UNIQUE(symbol, fingerprint)
                );

                CREATE TABLE IF NOT EXISTS deep_stock_sessions (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    symbol TEXT NOT NULL,
                    name TEXT NOT NULL,
                    conversation_id TEXT NOT NULL
                        REFERENCES conversations(id) ON DELETE CASCADE,
                    workflow_version TEXT NOT NULL,
                    status TEXT NOT NULL
                        CHECK(status IN ('active', 'completed')),
                    stages_json TEXT NOT NULL,
                    evidence_modules_json TEXT NOT NULL DEFAULT '{}',
                    unresolved_json TEXT NOT NULL DEFAULT '[]',
                    next_question TEXT NOT NULL,
                    latest_run_id TEXT REFERENCES runs(id) ON DELETE SET NULL,
                    latest_report_id TEXT
                        REFERENCES research_reports(id) ON DELETE SET NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT,
                    UNIQUE(user_id, symbol)
                );

                CREATE TABLE IF NOT EXISTS research_change_events (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    report_id TEXT NOT NULL
                        REFERENCES research_reports(id) ON DELETE CASCADE,
                    previous_report_id TEXT
                        REFERENCES research_reports(id) ON DELETE SET NULL,
                    event_type TEXT NOT NULL
                        CHECK(event_type IN ('baseline', 'evidence_change')),
                    severity TEXT NOT NULL
                        CHECK(severity IN ('stable', 'notice', 'attention')),
                    summary TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(symbol, report_id)
                );

                CREATE TABLE IF NOT EXISTS research_priority_snapshots (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    fingerprint TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(user_id, fingerprint)
                );

                CREATE TABLE IF NOT EXISTS research_action_snapshots (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    fingerprint TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(user_id, fingerprint)
                );

                CREATE TABLE IF NOT EXISTS conversation_quality_snapshots (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    fingerprint TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(user_id, fingerprint)
                );

                CREATE TABLE IF NOT EXISTS evidence_tasks (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    conversation_id TEXT REFERENCES conversations(id) ON DELETE SET NULL,
                    run_id TEXT REFERENCES runs(id) ON DELETE SET NULL,
                    subject_kind TEXT NOT NULL
                        CHECK(subject_kind IN ('stock', 'market', 'general')),
                    symbol TEXT,
                    market_key TEXT,
                    intent TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    gap_key TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    query TEXT NOT NULL,
                    status TEXT NOT NULL
                        CHECK(status IN (
                            'pending', 'collecting', 'resolved',
                            'pending_external', 'failed'
                        )),
                    priority INTEGER NOT NULL DEFAULT 50,
                    fingerprint TEXT NOT NULL UNIQUE,
                    resolution_document_id TEXT
                        REFERENCES knowledge_documents(id) ON DELETE SET NULL,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    max_retries INTEGER NOT NULL DEFAULT 3,
                    last_error TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    started_at TEXT,
                    resolved_at TEXT
                );

                CREATE TABLE IF NOT EXISTS research_outcomes (
                    id TEXT PRIMARY KEY,
                    report_id TEXT NOT NULL
                        REFERENCES research_reports(id) ON DELETE CASCADE,
                    symbol TEXT NOT NULL,
                    name TEXT NOT NULL,
                    anchor_timestamp TEXT NOT NULL,
                    horizon_sessions INTEGER NOT NULL
                        CHECK(horizon_sessions IN (3, 5, 10)),
                    result_status TEXT NOT NULL
                        CHECK(result_status IN ('pending', 'available', 'unavailable')),
                    observed_sessions INTEGER NOT NULL,
                    anchor_close REAL,
                    target_timestamp TEXT,
                    target_close REAL,
                    close_return_pct REAL,
                    maximum_favorable_excursion_pct REAL,
                    maximum_adverse_excursion_pct REAL,
                    scenario_result TEXT,
                    review_conclusion TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    calculated_at TEXT NOT NULL,
                    UNIQUE(symbol, anchor_timestamp, horizon_sessions)
                );

                CREATE TABLE IF NOT EXISTS outlook_calibrations (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    method TEXT NOT NULL,
                    history_first TEXT,
                    history_last TEXT NOT NULL,
                    history_points INTEGER NOT NULL,
                    source TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(symbol, method, history_last)
                );

                CREATE INDEX IF NOT EXISTS idx_memories_user_status
                    ON memories(user_id, status);
                CREATE INDEX IF NOT EXISTS idx_user_sessions_user_expiry
                    ON user_sessions(user_id, expires_at DESC);
                CREATE INDEX IF NOT EXISTS idx_user_uploads_user_created
                    ON user_uploads(user_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_runs_user_created
                    ON runs(user_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_stock_workspaces_user_updated
                    ON stock_workspaces(user_id, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_relation_history_workspace_time
                    ON stock_relation_history(workspace_id, effective_at DESC);
                CREATE INDEX IF NOT EXISTS idx_thesis_versions_workspace_status
                    ON thesis_versions(workspace_id, status, version_no DESC);
                CREATE INDEX IF NOT EXISTS idx_ai_citations_user_run
                    ON ai_citations(user_id, run_id, created_at ASC);
                CREATE INDEX IF NOT EXISTS idx_ai_writebacks_user_status
                    ON ai_writeback_candidates(
                        user_id, status, created_at DESC
                    );
                CREATE INDEX IF NOT EXISTS idx_ai_writebacks_workspace
                    ON ai_writeback_candidates(
                        workspace_id, status, created_at DESC
                    );
                CREATE INDEX IF NOT EXISTS idx_observation_tasks_user_status
                    ON observation_tasks(
                        user_id, status, priority, updated_at DESC
                    );
                CREATE INDEX IF NOT EXISTS idx_observation_tasks_user_symbol
                    ON observation_tasks(user_id, symbol, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_observation_task_history_task
                    ON observation_task_history(task_id, version DESC);
                CREATE INDEX IF NOT EXISTS idx_conversations_user_updated
                    ON conversations(user_id, status, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_conversation_messages_conversation_created
                    ON conversation_messages(conversation_id, created_at ASC);
                CREATE INDEX IF NOT EXISTS idx_knowledge_documents_owner_updated
                    ON knowledge_documents(owner_user_id, scope, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_articles_user_created
                    ON articles(user_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_market_bars_symbol_time
                    ON market_bars(symbol, interval, timestamp DESC);
                CREATE INDEX IF NOT EXISTS idx_background_jobs_name_time
                    ON background_job_runs(job_name, started_at DESC);
                CREATE INDEX IF NOT EXISTS idx_data_health_time
                    ON data_health_snapshots(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_tushare_sync_scope_time
                    ON tushare_sync_runs(job_scope, started_at DESC);
                CREATE INDEX IF NOT EXISTS idx_tushare_snapshot_lookup
                    ON tushare_dataset_snapshots(
                        dataset, scope_key, data_status, created_at DESC
                    );
                CREATE INDEX IF NOT EXISTS idx_strategy_runs_time
                    ON strategy_screen_runs(strategy_id, started_at DESC);
                CREATE INDEX IF NOT EXISTS idx_strategy_candidates_current
                    ON strategy_candidate_snapshots(
                        strategy_id, strategy_version, parameter_version,
                        symbol, created_at DESC
                    );
                CREATE INDEX IF NOT EXISTS idx_strategy_candidates_status
                    ON strategy_candidate_snapshots(
                        strategy_id, strategy_version, parameter_version,
                        status, as_of_date DESC
                    );
                CREATE INDEX IF NOT EXISTS idx_strategy_rules_candidate
                    ON strategy_rule_results(candidate_snapshot_id, rule_id);
                CREATE INDEX IF NOT EXISTS idx_strategy_triggers_time
                    ON strategy_trigger_events(
                        strategy_id, evidence_date DESC, created_at DESC
                    );
                CREATE INDEX IF NOT EXISTS idx_strategy_backtest_cap_date
                    ON strategy_backtest_market_caps(
                        strategy_id, backtest_version, trade_date, symbol
                    );
                CREATE INDEX IF NOT EXISTS idx_strategy_backtest_cap_symbol
                    ON strategy_backtest_market_caps(
                        strategy_id, backtest_version, symbol, trade_date
                    );
                CREATE INDEX IF NOT EXISTS idx_strategy_backtest_states_date
                    ON strategy_backtest_symbol_states(
                        strategy_id, strategy_version, parameter_version,
                        backtest_version, trade_date, candidate_qualified
                    );
                CREATE INDEX IF NOT EXISTS idx_strategy_backtest_coverage
                    ON strategy_backtest_symbol_coverage(
                        strategy_id, strategy_version, parameter_version,
                        backtest_version, status, start_date, end_date
                    );
                CREATE INDEX IF NOT EXISTS idx_news_symbol_time
                    ON news_items(symbol, published_at DESC, fetched_at DESC);
                CREATE INDEX IF NOT EXISTS idx_sentiment_symbol_time
                    ON sentiment_snapshots(symbol, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_valuation_symbol_time
                    ON valuation_snapshots(symbol, market_timestamp DESC, fetched_at DESC);
                CREATE INDEX IF NOT EXISTS idx_financial_symbol_report
                    ON financial_periods(symbol, report_date DESC);
                CREATE INDEX IF NOT EXISTS idx_earnings_quality_symbol_report
                    ON earnings_quality_snapshots(symbol, report_date DESC);
                CREATE INDEX IF NOT EXISTS idx_financial_statement_symbol_report
                    ON financial_statement_details(symbol, report_date DESC, statement_type);
                CREATE INDEX IF NOT EXISTS idx_financial_driver_symbol_report
                    ON financial_driver_snapshots(symbol, report_date DESC);
                CREATE INDEX IF NOT EXISTS idx_filing_documents_symbol_period
                    ON filing_documents(symbol, report_period DESC, published_at DESC);
                CREATE INDEX IF NOT EXISTS idx_filing_evidence_symbol_period
                    ON filing_evidence_snapshots(symbol, report_period DESC, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_business_segments_symbol_report
                    ON business_segment_rows(symbol, report_date DESC, classification);
                CREATE INDEX IF NOT EXISTS idx_business_structure_symbol_report
                    ON business_structure_snapshots(symbol, anchor_report_date DESC, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_peer_operating_symbol_report
                    ON peer_operating_snapshots(symbol, anchor_report_date DESC, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_shareholder_structure_symbol_report
                    ON shareholder_structure_snapshots(symbol, holder_count_as_of DESC, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_analyst_expectations_symbol_time
                    ON analyst_expectation_snapshots(symbol, as_of_date DESC, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_event_timeline_symbol_time
                    ON event_timeline_snapshots(symbol, as_of_date DESC, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_change_events_symbol_time
                    ON change_events(symbol, occurred_at DESC, detected_at DESC);
                CREATE INDEX IF NOT EXISTS idx_user_change_links_user_status
                    ON user_change_links(
                        user_id, relevance_status, read_at, handled_at, updated_at DESC
                    );
                CREATE INDEX IF NOT EXISTS idx_user_change_links_symbol
                    ON user_change_links(user_id, symbol, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_research_reports_symbol_time
                    ON research_reports(symbol, generated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_deep_stock_user_time
                    ON deep_stock_sessions(user_id, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_deep_stock_conversation
                    ON deep_stock_sessions(conversation_id);
                CREATE INDEX IF NOT EXISTS idx_research_change_events_symbol_time
                    ON research_change_events(symbol, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_research_priority_user_time
                    ON research_priority_snapshots(user_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_research_actions_user_time
                    ON research_action_snapshots(user_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_evidence_tasks_user_status
                    ON evidence_tasks(user_id, status, priority DESC, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_evidence_tasks_pending
                    ON evidence_tasks(status, priority DESC, updated_at ASC);
                CREATE INDEX IF NOT EXISTS idx_research_outcomes_symbol_anchor
                    ON research_outcomes(symbol, anchor_timestamp DESC, horizon_sessions);
                CREATE INDEX IF NOT EXISTS idx_outlook_calibration_symbol_time
                    ON outlook_calibrations(symbol, created_at DESC);
"""
