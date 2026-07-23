from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import secrets
import sqlite3
from typing import Any
from uuid import uuid4

from app.utils import json_dumps, utc_now, write_json


class Database:
    SYSTEM_EDITOR_ID = "system-market-editor"

    def __init__(self, path: Path, workspace_root: Path):
        self.path = Path(path)
        self.workspace_root = Path(workspace_root)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(
                """
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
                    focus_status TEXT NOT NULL DEFAULT 'watching'
                        CHECK(focus_status IN ('holding', 'watching', 'researching', 'cleared')),
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
            )
            self._ensure_column(connection, "market_bars", "adjusted_close", "REAL")
            self._ensure_column(
                connection,
                "conversations",
                "quality_scope",
                "TEXT NOT NULL DEFAULT 'user'",
            )
            self._ensure_column(connection, "financial_periods", "eps_diluted", "REAL")
            self._ensure_column(
                connection, "financial_periods", "total_liabilities", "REAL"
            )
            self._ensure_column(
                connection,
                "watchlist",
                "focus_status",
                "TEXT NOT NULL DEFAULT 'watching' "
                "CHECK(focus_status IN ('holding', 'watching', 'researching', 'cleared'))",
            )
            self._backfill_stock_domains(connection)

    @staticmethod
    def _ensure_column(
        connection: sqlite3.Connection, table: str, column: str, definition: str
    ) -> None:
        columns = {
            str(row["name"])
            for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        return dict(row) if row is not None else None

    @staticmethod
    def _stock_workspace_row(
        row: sqlite3.Row | None,
    ) -> dict[str, Any] | None:
        if row is None:
            return None
        item = dict(row)
        item["attention_tags"] = json.loads(
            item.pop("attention_tags_json") or "[]"
        )
        return item

    @staticmethod
    def _thesis_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        item = dict(row)
        item["watch_items"] = json.loads(item.pop("watch_items_json") or "[]")
        item["recheck_conditions"] = json.loads(
            item.pop("recheck_conditions_json") or "[]"
        )
        return item

    def _backfill_stock_domains(self, connection: sqlite3.Connection) -> None:
        rows = connection.execute(
            "SELECT * FROM watchlist ORDER BY created_at ASC"
        ).fetchall()
        for row in rows:
            self._sync_stock_domain_from_watchlist(
                connection,
                user_id=str(row["user_id"]),
                symbol=str(row["symbol"]),
                name=row["name"],
                market=row["market"],
                thesis=row["thesis"],
                source="watchlist_migration",
                observed_at=str(row["updated_at"] or row["created_at"]),
            )

    def _sync_stock_domain_from_watchlist(
        self,
        connection: sqlite3.Connection,
        *,
        user_id: str,
        symbol: str,
        name: str | None,
        market: str | None,
        thesis: str | None,
        source: str,
        observed_at: str,
    ) -> dict[str, Any]:
        workspace_row = connection.execute(
            "SELECT * FROM stock_workspaces WHERE user_id = ? AND symbol = ?",
            (user_id, symbol),
        ).fetchone()
        if workspace_row is None:
            workspace_id = str(uuid4())
            connection.execute(
                """
                INSERT INTO stock_workspaces(
                    id, user_id, symbol, name, market, relation_type, priority,
                    tracking_status, workflow_status, attention_tags_json,
                    version, created_at, updated_at, ended_at
                ) VALUES (?, ?, ?, ?, ?, 'watching', 'normal', 'active',
                          'idle', '[]', 1, ?, ?, NULL)
                """,
                (
                    workspace_id,
                    user_id,
                    symbol,
                    name,
                    market,
                    observed_at,
                    observed_at,
                ),
            )
            connection.execute(
                """
                INSERT INTO stock_relation_history(
                    id, workspace_id, user_id, relation_type, priority,
                    tracking_status, source, effective_at, ended_at
                ) VALUES (?, ?, ?, 'watching', 'normal', 'active', ?, ?, NULL)
                """,
                (str(uuid4()), workspace_id, user_id, source, observed_at),
            )
        else:
            workspace_id = str(workspace_row["id"])
            if workspace_row["relation_type"] == "ended":
                connection.execute(
                    """
                    UPDATE stock_relation_history SET ended_at = ?
                    WHERE workspace_id = ? AND ended_at IS NULL
                    """,
                    (observed_at, workspace_id),
                )
                connection.execute(
                    """
                    UPDATE stock_workspaces
                    SET name = COALESCE(?, name), market = COALESCE(?, market),
                        relation_type = 'watching', priority = 'normal',
                        tracking_status = 'active', workflow_status = 'idle',
                        version = version + 1, updated_at = ?, ended_at = NULL
                    WHERE id = ?
                    """,
                    (name, market, observed_at, workspace_id),
                )
                connection.execute(
                    """
                    INSERT INTO stock_relation_history(
                        id, workspace_id, user_id, relation_type, priority,
                        tracking_status, source, effective_at, ended_at
                    ) VALUES (?, ?, ?, 'watching', 'normal', 'active', ?, ?, NULL)
                    """,
                    (str(uuid4()), workspace_id, user_id, source, observed_at),
                )
            elif name != workspace_row["name"] or market != workspace_row["market"]:
                connection.execute(
                    """
                    UPDATE stock_workspaces
                    SET name = COALESCE(?, name), market = COALESCE(?, market),
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (name, market, observed_at, workspace_id),
                )

        clean_thesis = str(thesis or "").strip()
        if clean_thesis:
            active = connection.execute(
                """
                SELECT * FROM thesis_versions
                WHERE workspace_id = ? AND status = 'active'
                ORDER BY version_no DESC LIMIT 1
                """,
                (workspace_id,),
            ).fetchone()
            if active is None or str(active["reason_text"]).strip() != clean_thesis:
                current_version = int(active["version_no"]) if active else 0
                if active is not None:
                    connection.execute(
                        """
                        UPDATE thesis_versions
                        SET status = 'superseded', superseded_at = ?
                        WHERE id = ? AND status = 'active'
                        """,
                        (observed_at, active["id"]),
                    )
                next_version_row = connection.execute(
                    """
                    SELECT COALESCE(MAX(version_no), 0) + 1 AS next_version
                    FROM thesis_versions WHERE workspace_id = ?
                    """,
                    (workspace_id,),
                ).fetchone()
                next_version = int(next_version_row["next_version"])
                connection.execute(
                    """
                    INSERT INTO thesis_versions(
                        id, workspace_id, user_id, symbol, version_no, status,
                        reason_text, watch_items_json, recheck_conditions_json,
                        source, source_run_id, base_version, created_at,
                        confirmed_at, superseded_at
                    ) VALUES (?, ?, ?, ?, ?, 'active', ?, '[]', '[]', ?, NULL,
                              ?, ?, ?, NULL)
                    """,
                    (
                        str(uuid4()),
                        workspace_id,
                        user_id,
                        symbol,
                        next_version,
                        clean_thesis,
                        source,
                        current_version,
                        observed_at,
                        observed_at,
                    ),
                )
        row = connection.execute(
            "SELECT * FROM stock_workspaces WHERE id = ?", (workspace_id,)
        ).fetchone()
        return self._stock_workspace_row(row)  # type: ignore[return-value]

    def create_user(self, name: str) -> dict[str, Any]:
        user_id = str(uuid4())
        workspace = (self.workspace_root / user_id).resolve()
        workspace.mkdir(parents=True, exist_ok=False)
        created_at = utc_now()
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO users(id, name, workspace_path, created_at) VALUES (?, ?, ?, ?)",
                (user_id, name.strip(), str(workspace), created_at),
            )
        user = self.get_user(user_id)  # type: ignore[assignment]
        write_json(workspace / "profile.json", user)
        write_json(workspace / "memory" / "confirmed.json", [])
        write_json(workspace / "watchlist.json", [])
        return user  # type: ignore[return-value]

    def ensure_system_editor(self) -> dict[str, Any]:
        workspace = (self.workspace_root / "_system_market_editor").resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO users(id, name, workspace_path, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (self.SYSTEM_EDITOR_ID, "清数智算系统编辑", str(workspace), utc_now()),
            )
        return self.get_user(self.SYSTEM_EDITOR_ID)  # type: ignore[return-value]

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            return self._row(connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())

    @staticmethod
    def _session_token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def create_user_session(self, user_id: str, ttl_days: int = 365) -> dict[str, Any]:
        token = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        created_at = now.isoformat(timespec="seconds")
        expires_at = (now + timedelta(days=ttl_days)).isoformat(timespec="seconds")
        session_id = str(uuid4())
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO user_sessions(
                    id, token_hash, user_id, created_at, expires_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    self._session_token_hash(token),
                    user_id,
                    created_at,
                    expires_at,
                    created_at,
                ),
            )
        return {
            "id": session_id,
            "token": token,
            "user_id": user_id,
            "created_at": created_at,
            "expires_at": expires_at,
        }

    def get_user_by_session(self, token: str | None) -> dict[str, Any] | None:
        if not token:
            return None
        token_hash = self._session_token_hash(token)
        now = utc_now()
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT users.*, user_sessions.expires_at AS session_expires_at
                FROM user_sessions
                JOIN users ON users.id = user_sessions.user_id
                WHERE user_sessions.token_hash = ?
                  AND user_sessions.revoked_at IS NULL
                  AND user_sessions.expires_at > ?
                """,
                (token_hash, now),
            ).fetchone()
            if row is not None:
                connection.execute(
                    "UPDATE user_sessions SET last_seen_at = ? WHERE token_hash = ?",
                    (now, token_hash),
                )
        return self._row(row)

    def revoke_user_session(self, token: str | None) -> None:
        if not token:
            return
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE user_sessions SET revoked_at = ?
                WHERE token_hash = ? AND revoked_at IS NULL
                """,
                (utc_now(), self._session_token_hash(token)),
            )

    def user_has_session_history(self, user_id: str) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM user_sessions WHERE user_id = ? LIMIT 1", (user_id,)
            ).fetchone()
        return row is not None

    def create_user_upload(
        self,
        upload_id: str,
        user_id: str,
        kind: str,
        original_name: str,
        mime_type: str,
        size_bytes: int,
        width: int,
        height: int,
        workspace_path: Path,
    ) -> dict[str, Any]:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO user_uploads(
                    id, user_id, kind, original_name, mime_type, size_bytes,
                    width, height, workspace_path, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    upload_id,
                    user_id,
                    kind,
                    original_name,
                    mime_type,
                    size_bytes,
                    width,
                    height,
                    str(Path(workspace_path).resolve()),
                    utc_now(),
                ),
            )
        return self.get_user_upload(user_id, upload_id)  # type: ignore[return-value]

    def get_user_upload(self, user_id: str, upload_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            return self._row(
                connection.execute(
                    "SELECT * FROM user_uploads WHERE user_id = ? AND id = ?",
                    (user_id, upload_id),
                ).fetchone()
            )

    def mark_user_upload_used(self, user_id: str, upload_id: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE user_uploads SET used_at = ?
                WHERE user_id = ? AND id = ?
                """,
                (utc_now(), user_id, upload_id),
            )

    def upsert_watchlist(
        self,
        user_id: str,
        symbol: str,
        name: str | None,
        market: str | None,
        thesis: str | None,
        focus_status: str | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO watchlist(
                    user_id, symbol, name, market, thesis, focus_status,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, COALESCE(?, 'watching'), ?, ?)
                ON CONFLICT(user_id, symbol) DO UPDATE SET
                    name = excluded.name,
                    market = excluded.market,
                    thesis = COALESCE(excluded.thesis, watchlist.thesis),
                    focus_status = COALESCE(?, watchlist.focus_status),
                    updated_at = excluded.updated_at
                """,
                (
                    user_id,
                    symbol,
                    name,
                    market,
                    thesis,
                    focus_status,
                    now,
                    now,
                    focus_status,
                ),
            )
            row = connection.execute(
                "SELECT * FROM watchlist WHERE user_id = ? AND symbol = ?", (user_id, symbol)
            ).fetchone()
            self._sync_stock_domain_from_watchlist(
                connection,
                user_id=user_id,
                symbol=symbol,
                name=row["name"],
                market=row["market"],
                thesis=row["thesis"],
                source="legacy_watchlist_confirmed",
                observed_at=now,
            )
        result = dict(row)
        self._sync_watchlist_file(user_id)
        return result

    def list_watchlist(self, user_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM watchlist WHERE user_id = ? ORDER BY updated_at DESC", (user_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def list_distinct_watchlist_symbols(
        self, *, exclude_user_id: str | None = None
    ) -> list[str]:
        with self.connect() as connection:
            if exclude_user_id is None:
                rows = connection.execute(
                    "SELECT DISTINCT symbol FROM watchlist ORDER BY symbol"
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT DISTINCT symbol
                    FROM watchlist
                    WHERE user_id <> ?
                    ORDER BY symbol
                    """,
                    (exclude_user_id,),
                ).fetchall()
        return [str(row["symbol"]) for row in rows]

    def get_watchlist_item(self, user_id: str, symbol: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            return self._row(
                connection.execute(
                    "SELECT * FROM watchlist WHERE user_id = ? AND symbol = ?", (user_id, symbol)
                ).fetchone()
            )

    def delete_watchlist_item(self, user_id: str, symbol: str) -> bool:
        now = utc_now()
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT * FROM watchlist WHERE user_id = ? AND symbol = ?",
                (user_id, symbol),
            ).fetchone()
            if existing is None:
                return False
            workspace = connection.execute(
                "SELECT * FROM stock_workspaces WHERE user_id = ? AND symbol = ?",
                (user_id, symbol),
            ).fetchone()
            if workspace is not None and workspace["relation_type"] != "ended":
                connection.execute(
                    """
                    UPDATE stock_relation_history SET ended_at = ?
                    WHERE workspace_id = ? AND ended_at IS NULL
                    """,
                    (now, workspace["id"]),
                )
                connection.execute(
                    """
                    UPDATE stock_workspaces
                    SET relation_type = 'ended', priority = NULL,
                        tracking_status = 'paused', workflow_status = 'idle',
                        version = version + 1, updated_at = ?, ended_at = ?
                    WHERE id = ?
                    """,
                    (now, now, workspace["id"]),
                )
                connection.execute(
                    """
                    INSERT INTO stock_relation_history(
                        id, workspace_id, user_id, relation_type, priority,
                        tracking_status, source, effective_at, ended_at
                    ) VALUES (?, ?, ?, 'ended', NULL, 'paused',
                              'legacy_watchlist_delete', ?, NULL)
                    """,
                    (str(uuid4()), workspace["id"], user_id, now),
                )
            cursor = connection.execute(
                "DELETE FROM watchlist WHERE user_id = ? AND symbol = ?",
                (user_id, symbol),
            )
        if cursor.rowcount:
            self._sync_watchlist_file(user_id)
            return True
        return False

    def get_stock_workspace(
        self, user_id: str, symbol: str
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM stock_workspaces
                WHERE user_id = ? AND symbol = ?
                """,
                (user_id, symbol),
            ).fetchone()
        return self._stock_workspace_row(row)

    def list_stock_workspaces(self, user_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM stock_workspaces
                WHERE user_id = ?
                ORDER BY updated_at DESC, rowid DESC
                """,
                (user_id,),
            ).fetchall()
        return [
            self._stock_workspace_row(row)  # type: ignore[misc]
            for row in rows
        ]

    def list_stock_relation_history(
        self, user_id: str, workspace_id: str
    ) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM stock_relation_history
                WHERE user_id = ? AND workspace_id = ?
                ORDER BY effective_at ASC, rowid ASC
                """,
                (user_id, workspace_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_active_thesis(
        self, user_id: str, workspace_id: str
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM thesis_versions
                WHERE user_id = ? AND workspace_id = ? AND status = 'active'
                ORDER BY version_no DESC LIMIT 1
                """,
                (user_id, workspace_id),
            ).fetchone()
        return self._thesis_row(row)

    def get_thesis_version(
        self, user_id: str, thesis_id: str
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM thesis_versions WHERE user_id = ? AND id = ?",
                (user_id, thesis_id),
            ).fetchone()
        return self._thesis_row(row)

    def list_thesis_versions(
        self, user_id: str, workspace_id: str
    ) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM thesis_versions
                WHERE user_id = ? AND workspace_id = ?
                ORDER BY version_no DESC, rowid DESC
                """,
                (user_id, workspace_id),
            ).fetchall()
        return [
            self._thesis_row(row)  # type: ignore[misc]
            for row in rows
        ]

    def create_memory(self, user_id: str, kind: str, content: str) -> dict[str, Any]:
        memory_id = str(uuid4())
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO memories(id, user_id, kind, content, status, created_at)
                VALUES (?, ?, ?, ?, 'candidate', ?)
                """,
                (memory_id, user_id, kind, content.strip(), utc_now()),
            )
        return self.get_memory(user_id, memory_id)  # type: ignore[return-value]

    def get_memory(self, user_id: str, memory_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            return self._row(
                connection.execute(
                    "SELECT * FROM memories WHERE user_id = ? AND id = ?", (user_id, memory_id)
                ).fetchone()
            )

    def confirm_memory(self, user_id: str, memory_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE memories SET status = 'confirmed', confirmed_at = ?
                WHERE user_id = ? AND id = ? AND status = 'candidate'
                """,
                (utc_now(), user_id, memory_id),
            )
            if cursor.rowcount == 0:
                return None
        memory = self.get_memory(user_id, memory_id)
        self._sync_confirmed_memory_file(user_id)
        return memory

    def reject_memory(self, user_id: str, memory_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE memories SET status = 'rejected'
                WHERE user_id = ? AND id = ? AND status = 'candidate'
                """,
                (user_id, memory_id),
            )
            if cursor.rowcount == 0:
                return None
        return self.get_memory(user_id, memory_id)

    def list_memories(self, user_id: str, status: str = "confirmed") -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM memories WHERE user_id = ? AND status = ? ORDER BY created_at DESC",
                (user_id, status),
            ).fetchall()
        return [dict(row) for row in rows]

    def _sync_watchlist_file(self, user_id: str) -> None:
        user = self.get_user(user_id)
        if user is None:
            return
        write_json(Path(user["workspace_path"]) / "watchlist.json", self.list_watchlist(user_id))

    def _sync_confirmed_memory_file(self, user_id: str) -> None:
        user = self.get_user(user_id)
        if user is None:
            return
        memories = [
            {
                "id": item["id"],
                "kind": item["kind"],
                "content": item["content"],
                "confirmed_at": item["confirmed_at"],
            }
            for item in self.list_memories(user_id, status="confirmed")
        ]
        write_json(Path(user["workspace_path"]) / "memory" / "confirmed.json", memories)

    def create_conversation(
        self,
        user_id: str,
        title: str = "新的研究对话",
        quality_scope: str = "user",
    ) -> dict[str, Any]:
        if quality_scope not in {"user", "evaluation"}:
            raise ValueError("Unsupported conversation quality scope")
        conversation_id = str(uuid4())
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO conversations(
                    id, user_id, title, quality_scope, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'active', ?, ?)
                """,
                (
                    conversation_id,
                    user_id,
                    title.strip() or "新的研究对话",
                    quality_scope,
                    now,
                    now,
                ),
            )
        return self.get_conversation(user_id, conversation_id)  # type: ignore[return-value]

    def get_conversation(
        self, user_id: str, conversation_id: str
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT conversations.*,
                    (SELECT COUNT(*) FROM conversation_messages
                     WHERE conversation_id = conversations.id) AS message_count
                FROM conversations
                WHERE id = ? AND user_id = ?
                """,
                (conversation_id, user_id),
            ).fetchone()
        return self._row(row)

    def list_conversations(
        self, user_id: str, include_archived: bool = False, limit: int = 100
    ) -> list[dict[str, Any]]:
        status_clause = "" if include_archived else "AND conversations.status = 'active'"
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT conversations.*,
                    (SELECT COUNT(*) FROM conversation_messages
                     WHERE conversation_id = conversations.id) AS message_count,
                    (SELECT substr(content, 1, 120) FROM conversation_messages
                     WHERE conversation_id = conversations.id
                     ORDER BY created_at DESC, rowid DESC LIMIT 1) AS last_message_preview
                FROM conversations
                WHERE user_id = ? {status_clause}
                ORDER BY updated_at DESC, rowid DESC LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def rename_conversation(
        self, user_id: str, conversation_id: str, title: str
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE conversations SET title = ?, updated_at = ?
                WHERE id = ? AND user_id = ? AND status = 'active'
                """,
                (title.strip(), utc_now(), conversation_id, user_id),
            )
            if cursor.rowcount == 0:
                return None
        return self.get_conversation(user_id, conversation_id)

    def set_conversation_quality_scope(
        self, user_id: str, conversation_id: str, quality_scope: str
    ) -> dict[str, Any] | None:
        if quality_scope not in {"user", "evaluation"}:
            raise ValueError("Unsupported conversation quality scope")
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE conversations SET quality_scope = ?, updated_at = ?
                WHERE id = ? AND user_id = ? AND status = 'active'
                """,
                (quality_scope, utc_now(), conversation_id, user_id),
            )
            if cursor.rowcount == 0:
                return None
        return self.get_conversation(user_id, conversation_id)

    def archive_conversation(self, user_id: str, conversation_id: str) -> bool:
        now = utc_now()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE conversations
                SET status = 'archived', archived_at = ?, updated_at = ?
                WHERE id = ? AND user_id = ? AND status = 'active'
                """,
                (now, now, conversation_id, user_id),
            )
        return cursor.rowcount > 0

    def add_conversation_message(
        self,
        user_id: str,
        conversation_id: str,
        role: str,
        content: str,
        intent: str | None = None,
        run_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        message_id = str(uuid4())
        now = utc_now()
        with self.connect() as connection:
            owner = connection.execute(
                """
                SELECT 1 FROM conversations
                WHERE id = ? AND user_id = ? AND status = 'active'
                """,
                (conversation_id, user_id),
            ).fetchone()
            if owner is None:
                raise ValueError("对话不存在或已归档")
            connection.execute(
                """
                INSERT INTO conversation_messages(
                    id, conversation_id, user_id, role, content, intent,
                    run_id, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message_id,
                    conversation_id,
                    user_id,
                    role,
                    content,
                    intent,
                    run_id,
                    json_dumps(metadata or {}),
                    now,
                ),
            )
            connection.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (now, conversation_id),
            )
        return self.get_conversation_message(user_id, message_id)  # type: ignore[return-value]

    def get_conversation_message(
        self, user_id: str, message_id: str
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM conversation_messages
                WHERE id = ? AND user_id = ?
                """,
                (message_id, user_id),
            ).fetchone()
        item = self._row(row)
        if item is not None:
            item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
        return item

    def update_assistant_conversation_message(
        self,
        *,
        user_id: str,
        conversation_id: str,
        message_id: str,
        content: str,
        intent: str,
        run_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        now = utc_now()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE conversation_messages
                SET content = ?, intent = ?, run_id = ?, metadata_json = ?
                WHERE id = ? AND conversation_id = ? AND user_id = ?
                  AND role = 'assistant'
                """,
                (
                    content,
                    intent,
                    run_id,
                    json_dumps(metadata or {}),
                    message_id,
                    conversation_id,
                    user_id,
                ),
            )
            if cursor.rowcount == 0:
                return None
            connection.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ? AND user_id = ?",
                (now, conversation_id, user_id),
            )
        return self.get_conversation_message(user_id, message_id)

    def list_conversation_messages(
        self, user_id: str, conversation_id: str, limit: int = 200
    ) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT conversation_messages.*
                FROM conversation_messages
                JOIN conversations ON conversations.id = conversation_messages.conversation_id
                WHERE conversation_messages.conversation_id = ?
                  AND conversations.user_id = ?
                ORDER BY conversation_messages.created_at ASC,
                    conversation_messages.rowid ASC LIMIT ?
                """,
                (conversation_id, user_id, limit),
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
            items.append(item)
        return items

    def save_deep_stock_session(
        self,
        *,
        user_id: str,
        symbol: str,
        name: str,
        conversation_id: str,
        workflow_version: str,
        status: str,
        stages: list[dict[str, Any]],
        evidence_modules: dict[str, Any],
        unresolved_items: list[str],
        next_question: str,
        latest_run_id: str | None = None,
        latest_report_id: str | None = None,
        completed_at: str | None = None,
    ) -> dict[str, Any]:
        existing = self.get_deep_stock_session(user_id, symbol)
        session_id = str(existing["id"]) if existing else str(uuid4())
        created_at = str(existing["created_at"]) if existing else utc_now()
        updated_at = utc_now()
        with self.connect() as connection:
            owner = connection.execute(
                """
                SELECT 1 FROM conversations
                WHERE id = ? AND user_id = ? AND status = 'active'
                """,
                (conversation_id, user_id),
            ).fetchone()
            if owner is None:
                raise ValueError("个股研究绑定的研究对话不存在或已归档")
            connection.execute(
                """
                INSERT INTO deep_stock_sessions(
                    id, user_id, symbol, name, conversation_id,
                    workflow_version, status, stages_json,
                    evidence_modules_json, unresolved_json, next_question,
                    latest_run_id, latest_report_id, created_at, updated_at,
                    completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, symbol) DO UPDATE SET
                    name = excluded.name,
                    conversation_id = excluded.conversation_id,
                    workflow_version = excluded.workflow_version,
                    status = excluded.status,
                    stages_json = excluded.stages_json,
                    evidence_modules_json = excluded.evidence_modules_json,
                    unresolved_json = excluded.unresolved_json,
                    next_question = excluded.next_question,
                    latest_run_id = excluded.latest_run_id,
                    latest_report_id = excluded.latest_report_id,
                    updated_at = excluded.updated_at,
                    completed_at = excluded.completed_at
                """,
                (
                    session_id,
                    user_id,
                    symbol,
                    name,
                    conversation_id,
                    workflow_version,
                    status,
                    json_dumps(stages),
                    json_dumps(evidence_modules),
                    json_dumps(unresolved_items),
                    next_question,
                    latest_run_id,
                    latest_report_id,
                    created_at,
                    updated_at,
                    completed_at,
                ),
            )
        session = self.get_deep_stock_session(user_id, symbol)
        if session is not None:
            self._sync_deep_stock_session_file(user_id, session)
        return session  # type: ignore[return-value]

    def get_deep_stock_session(
        self, user_id: str, symbol: str
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM deep_stock_sessions
                WHERE user_id = ? AND symbol = ?
                """,
                (user_id, symbol),
            ).fetchone()
        return self._deep_stock_session_row(row)

    def get_deep_stock_session_by_conversation(
        self, user_id: str, conversation_id: str
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM deep_stock_sessions
                WHERE user_id = ? AND conversation_id = ?
                """,
                (user_id, conversation_id),
            ).fetchone()
        return self._deep_stock_session_row(row)

    def list_deep_stock_sessions(
        self, user_id: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM deep_stock_sessions
                WHERE user_id = ?
                ORDER BY updated_at DESC, rowid DESC LIMIT ?
                """,
                (user_id, max(1, min(limit, 200))),
            ).fetchall()
        return [
            self._deep_stock_session_row(row)  # type: ignore[misc]
            for row in rows
        ]

    @staticmethod
    def _deep_stock_session_row(
        row: sqlite3.Row | None,
    ) -> dict[str, Any] | None:
        if row is None:
            return None
        item = dict(row)
        item["stages"] = json.loads(item.pop("stages_json") or "[]")
        item["evidence_modules"] = json.loads(
            item.pop("evidence_modules_json") or "{}"
        )
        item["unresolved_items"] = json.loads(
            item.pop("unresolved_json") or "[]"
        )
        return item

    def _sync_deep_stock_session_file(
        self, user_id: str, session: dict[str, Any]
    ) -> None:
        user = self.get_user(user_id)
        if user is None:
            return
        write_json(
            Path(user["workspace_path"])
            / "deep-stock"
            / f"{session['symbol'].replace('.', '_')}.json",
            session,
        )

    def upsert_knowledge_document(
        self,
        document_id: str,
        scope: str,
        title: str,
        original_name: str,
        mime_type: str,
        content: str,
        source_key: str,
        owner_user_id: str | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO knowledge_documents(
                    id, owner_user_id, scope, title, original_name, mime_type,
                    content, source_key, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title = excluded.title,
                    original_name = excluded.original_name,
                    mime_type = excluded.mime_type,
                    content = excluded.content,
                    source_key = excluded.source_key,
                    updated_at = excluded.updated_at
                """,
                (
                    document_id,
                    owner_user_id,
                    scope,
                    title.strip(),
                    original_name,
                    mime_type,
                    content,
                    source_key,
                    now,
                    now,
                ),
            )
        return self.get_knowledge_document(owner_user_id, document_id)  # type: ignore[return-value]

    def get_knowledge_document(
        self, user_id: str | None, document_id: str
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM knowledge_documents
                WHERE id = ? AND (
                    scope = 'common' OR (scope = 'user' AND owner_user_id = ?)
                )
                """,
                (document_id, user_id),
            ).fetchone()
        return self._row(row)

    def list_knowledge_documents(
        self, user_id: str | None, include_content: bool = False
    ) -> list[dict[str, Any]]:
        fields = "*" if include_content else (
            "id, owner_user_id, scope, title, original_name, mime_type, "
            "source_key, length(content) AS content_chars, created_at, updated_at"
        )
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT {fields} FROM knowledge_documents
                WHERE scope = 'common' OR (scope = 'user' AND owner_user_id = ?)
                ORDER BY scope ASC, updated_at DESC
                """,
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_user_knowledge_document(self, user_id: str, document_id: str) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM knowledge_documents
                WHERE id = ? AND owner_user_id = ? AND scope = 'user'
                """,
                (document_id, user_id),
            )
        return cursor.rowcount > 0

    def create_run(
        self,
        user_id: str,
        intent: str,
        model_tier: str,
        input_data: dict[str, Any],
        workspace_path: Path,
    ) -> dict[str, Any]:
        run_id = str(uuid4())
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO runs(
                    id, user_id, intent, model_tier, status, input_json,
                    workspace_path, created_at
                ) VALUES (?, ?, ?, ?, 'running', ?, ?, ?)
                """,
                (run_id, user_id, intent, model_tier, json_dumps(input_data), str(workspace_path), utc_now()),
            )
        return self.get_run(run_id, user_id)  # type: ignore[return-value]

    def finish_run(
        self,
        run_id: str,
        user_id: str,
        status: str,
        evidence: dict[str, Any],
        answer: str,
        usage: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE runs SET status = ?, evidence_json = ?, answer = ?, usage_json = ?,
                    error = ?, finished_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (
                    status,
                    json_dumps(evidence),
                    answer,
                    json_dumps(usage) if usage is not None else None,
                    error,
                    utc_now(),
                    run_id,
                    user_id,
                ),
            )

    def get_run(self, run_id: str, user_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM runs WHERE id = ? AND user_id = ?", (run_id, user_id)
            ).fetchone()
        item = self._row(row)
        if item is None:
            return None
        for key in ("input_json", "evidence_json", "usage_json"):
            raw = item.pop(key)
            item[key.removesuffix("_json")] = json.loads(raw) if raw else None
        return item

    def list_user_runs(
        self, user_id: str, limit: int = 500
    ) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM runs
                WHERE user_id = ?
                ORDER BY created_at DESC, rowid DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            for key in ("input_json", "evidence_json", "usage_json"):
                raw = item.pop(key)
                item[key.removesuffix("_json")] = json.loads(raw) if raw else None
            items.append(item)
        return items

    def save_conversation_quality_snapshot(
        self,
        user_id: str,
        fingerprint: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        snapshot_id = str(uuid4())
        created_at = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO conversation_quality_snapshots(
                    id, user_id, fingerprint, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id, fingerprint) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    created_at = excluded.created_at
                """,
                (
                    snapshot_id,
                    user_id,
                    fingerprint,
                    json_dumps(payload),
                    created_at,
                ),
            )
            row = connection.execute(
                """
                SELECT * FROM conversation_quality_snapshots
                WHERE user_id = ? AND fingerprint = ?
                """,
                (user_id, fingerprint),
            ).fetchone()
        item = dict(row)
        item["payload"] = json.loads(item.pop("payload_json"))
        return item

    def latest_conversation_quality_snapshot(
        self, user_id: str
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM conversation_quality_snapshots
                WHERE user_id = ?
                ORDER BY created_at DESC, rowid DESC LIMIT 1
                """,
                (user_id,),
            ).fetchone()
        item = self._row(row)
        if item is not None:
            item["payload"] = json.loads(item.pop("payload_json"))
        return item

    def create_article(
        self,
        user_id: str,
        kind: str,
        title: str,
        summary: str,
        body: str,
        status: str,
        fingerprint: str,
        evidence: dict[str, Any],
        run_id: str | None,
    ) -> dict[str, Any]:
        article_id = str(uuid4())
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO articles(
                    id, user_id, kind, title, summary, body, status,
                    fingerprint, evidence_json, run_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    article_id,
                    user_id,
                    kind,
                    title,
                    summary,
                    body,
                    status,
                    fingerprint,
                    json_dumps(evidence),
                    run_id,
                    utc_now(),
                ),
            )
        return self.get_article(user_id, article_id)  # type: ignore[return-value]

    def get_article(self, user_id: str, article_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM articles WHERE user_id = ? AND id = ?", (user_id, article_id)
            ).fetchone()
        item = self._row(row)
        if item is not None:
            item["evidence"] = json.loads(item.pop("evidence_json"))
        return item

    def list_articles(self, user_id: str, limit: int = 20) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM articles WHERE user_id = ?
                ORDER BY created_at DESC LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["evidence"] = json.loads(item.pop("evidence_json"))
            items.append(item)
        return items

    def latest_article(self, user_id: str, kind: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM articles WHERE user_id = ? AND kind = ?
                ORDER BY created_at DESC LIMIT 1
                """,
                (user_id, kind),
            ).fetchone()
        item = self._row(row)
        if item is not None:
            item["evidence"] = json.loads(item.pop("evidence_json"))
        return item

    def count_articles_since(self, user_id: str, kind: str, since: str) -> int:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS count FROM articles
                WHERE user_id = ? AND kind = ? AND created_at >= ?
                """,
                (user_id, kind, since),
            ).fetchone()
        return int(row["count"])

    def put_cache(self, cache_key: str, payload: dict[str, Any], ttl_seconds: int) -> None:
        fetched_at = payload.get("fetched_at") or utc_now()
        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)).isoformat(timespec="seconds")
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO market_cache(
                    cache_key, payload_json, source, market_at, fetched_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    source = excluded.source,
                    market_at = excluded.market_at,
                    fetched_at = excluded.fetched_at,
                    expires_at = excluded.expires_at
                """,
                (
                    cache_key,
                    json_dumps(payload),
                    payload.get("source", "unknown"),
                    payload.get("market_timestamp"),
                    fetched_at,
                    expires_at,
                ),
            )

    def update_cache_payload_preserving_expiry(
        self, cache_key: str, payload: dict[str, Any]
    ) -> bool:
        """Replace a cached payload without turning a read into a TTL renewal."""
        fetched_at = payload.get("fetched_at") or utc_now()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE market_cache
                SET payload_json = ?, source = ?, market_at = ?, fetched_at = ?
                WHERE cache_key = ?
                """,
                (
                    json_dumps(payload),
                    payload.get("source", "unknown"),
                    payload.get("market_timestamp"),
                    fetched_at,
                    cache_key,
                ),
            )
        return cursor.rowcount > 0

    def upsert_market_breadth_snapshot(self, payload: dict[str, Any]) -> None:
        market_date = str(payload.get("market_date") or "").strip()
        if not market_date:
            return
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO market_breadth_snapshots(
                    market_date, payload_json, source, fetched_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(market_date) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    source = excluded.source,
                    fetched_at = excluded.fetched_at
                """,
                (
                    market_date,
                    json_dumps(payload),
                    payload.get("source") or "unknown",
                    payload.get("fetched_at") or utc_now(),
                ),
            )

    def list_market_breadth_snapshots(
        self, limit: int = 21
    ) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT market_date, payload_json, source, fetched_at
                FROM market_breadth_snapshots
                ORDER BY market_date DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        items = []
        for row in rows:
            payload = json.loads(row["payload_json"])
            payload.setdefault("market_date", row["market_date"])
            payload.setdefault("source", row["source"])
            payload.setdefault("fetched_at", row["fetched_at"])
            items.append(payload)
        return items

    def get_cache(self, cache_key: str, allow_stale: bool = False) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM market_cache WHERE cache_key = ?", (cache_key,)
            ).fetchone()
        if row is None:
            return None
        expired = datetime.fromisoformat(row["expires_at"]) <= datetime.now(timezone.utc)
        if expired and not allow_stale:
            return None
        payload = json.loads(row["payload_json"])
        payload["cache_hit"] = True
        payload["is_stale"] = expired
        if expired:
            payload.setdefault("warnings", []).append("实时上游不可用，当前返回已过期缓存。")
        return payload

    def upsert_market_bars(
        self,
        symbol: str,
        interval: str,
        points: list[dict[str, Any]],
        source: str,
        fetched_at: str,
    ) -> int:
        rows = [
            (
                symbol,
                interval,
                point["timestamp"],
                point.get("open"),
                point.get("high"),
                point.get("low"),
                point["close"],
                point.get("adjusted_close"),
                point.get("volume"),
                source,
                fetched_at,
            )
            for point in points
            if point.get("timestamp") and point.get("close") is not None
        ]
        if not rows:
            return 0
        with self.connect() as connection:
            connection.executemany(
                """
                INSERT INTO market_bars(
                    symbol, interval, timestamp, open, high, low, close,
                    adjusted_close, volume, source, fetched_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, interval, timestamp) DO UPDATE SET
                    open = excluded.open,
                    high = excluded.high,
                    low = excluded.low,
                    close = excluded.close,
                    adjusted_close = excluded.adjusted_close,
                    volume = excluded.volume,
                    source = excluded.source,
                    fetched_at = excluded.fetched_at
                """,
                rows,
            )
        return len(rows)

    def get_market_bars(
        self, symbol: str, interval: str, limit: int = 1000
    ) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT symbol, interval, timestamp, open, high, low, close,
                    adjusted_close, volume, source, fetched_at
                FROM market_bars
                WHERE symbol = ? AND interval = ?
                ORDER BY timestamp DESC LIMIT ?
                """,
                (symbol, interval, limit),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def delete_market_bars(
        self, symbol: str, interval: str, timestamps: list[str]
    ) -> int:
        values = [str(value).strip() for value in timestamps if str(value).strip()]
        if not values:
            return 0
        placeholders = ",".join("?" for _ in values)
        with self.connect() as connection:
            cursor = connection.execute(
                f"""
                DELETE FROM market_bars
                WHERE symbol = ? AND interval = ?
                    AND timestamp IN ({placeholders})
                """,
                (symbol, interval, *values),
            )
        return cursor.rowcount

    def start_background_job(self, job_name: str) -> str:
        job_id = str(uuid4())
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO background_job_runs(id, job_name, status, started_at)
                VALUES (?, ?, 'running', ?)
                """,
                (job_id, job_name, utc_now()),
            )
        return job_id

    def finish_background_job(
        self,
        job_id: str,
        status: str,
        summary: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE background_job_runs
                SET status = ?, summary_json = ?, error = ?, finished_at = ?
                WHERE id = ?
                """,
                (
                    status,
                    json_dumps(summary) if summary is not None else None,
                    error,
                    utc_now(),
                    job_id,
                ),
            )

    def latest_background_jobs(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM background_job_runs AS runs
                WHERE id = (
                    SELECT inner_runs.id
                    FROM background_job_runs AS inner_runs
                    WHERE inner_runs.job_name = runs.job_name
                    ORDER BY inner_runs.started_at DESC, inner_runs.rowid DESC
                    LIMIT 1
                )
                ORDER BY job_name
                """
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            raw_summary = item.pop("summary_json")
            item["summary"] = json.loads(raw_summary) if raw_summary else None
            items.append(item)
        return items

    def save_data_health_snapshot(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        snapshot_id = str(uuid4())
        created_at = snapshot.get("created_at") or utc_now()
        payload = dict(snapshot)
        payload["id"] = snapshot_id
        payload["created_at"] = created_at
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO data_health_snapshots(id, status, payload_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    snapshot["status"],
                    json_dumps(payload),
                    created_at,
                ),
            )
        return payload

    def latest_data_health_snapshot(self) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT payload_json FROM data_health_snapshots
                ORDER BY created_at DESC, rowid DESC LIMIT 1
                """
            ).fetchone()
        return json.loads(row["payload_json"]) if row is not None else None

    def start_tushare_sync_run(
        self,
        *,
        job_scope: str,
        as_of_date: str | None,
        datasets: list[str],
    ) -> dict[str, Any]:
        run_id = str(uuid4())
        started_at = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO tushare_sync_runs(
                    id, job_scope, status, as_of_date, data_version,
                    datasets_json, summary_json, error, started_at, finished_at
                ) VALUES (?, ?, 'running', ?, NULL, ?, NULL, NULL, ?, NULL)
                """,
                (run_id, job_scope, as_of_date, json_dumps(datasets), started_at),
            )
        return self.get_tushare_sync_run(run_id)  # type: ignore[return-value]

    def finish_tushare_sync_run(
        self,
        run_id: str,
        *,
        status: str,
        data_version: str | None,
        summary: dict[str, Any] | None,
        error: str | None = None,
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE tushare_sync_runs
                SET status = ?, data_version = ?, summary_json = ?, error = ?,
                    finished_at = ?
                WHERE id = ?
                """,
                (
                    status,
                    data_version,
                    json_dumps(summary) if summary is not None else None,
                    error,
                    utc_now(),
                    run_id,
                ),
            )
        return self.get_tushare_sync_run(run_id)

    def get_tushare_sync_run(self, run_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM tushare_sync_runs WHERE id = ?", (run_id,)
            ).fetchone()
        if row is None:
            return None
        item = dict(row)
        item["datasets"] = json.loads(item.pop("datasets_json") or "[]")
        raw_summary = item.pop("summary_json")
        item["summary"] = json.loads(raw_summary) if raw_summary else None
        return item

    def save_tushare_dataset_snapshot(
        self,
        *,
        dataset: str,
        scope_key: str,
        as_of_date: str | None,
        report_period: str | None,
        source_updated_at: str | None,
        sync_run_id: str,
        data_version: str,
        data_status: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        snapshot_id = str(uuid4())
        created_at = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO tushare_dataset_snapshots(
                    id, dataset, scope_key, as_of_date, report_period,
                    source_updated_at, sync_run_id, data_version, data_status,
                    payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    dataset,
                    scope_key,
                    as_of_date,
                    report_period,
                    source_updated_at,
                    sync_run_id,
                    data_version,
                    data_status,
                    json_dumps(payload),
                    created_at,
                ),
            )
            row = connection.execute(
                """
                SELECT * FROM tushare_dataset_snapshots
                WHERE dataset = ? AND scope_key = ? AND data_version = ?
                """,
                (dataset, scope_key, data_version),
            ).fetchone()
        return self._tushare_snapshot_row(row)  # type: ignore[return-value]

    def latest_tushare_dataset_snapshot(
        self,
        dataset: str,
        scope_key: str,
        *,
        stable_only: bool = True,
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                f"""
                SELECT * FROM tushare_dataset_snapshots
                WHERE dataset = ? AND scope_key = ?
                    {"AND data_status = 'stable'" if stable_only else ""}
                ORDER BY created_at DESC, rowid DESC LIMIT 1
                """,
                (dataset, scope_key),
            ).fetchone()
        return self._tushare_snapshot_row(row)

    @staticmethod
    def _tushare_snapshot_row(
        row: sqlite3.Row | None,
    ) -> dict[str, Any] | None:
        if row is None:
            return None
        item = dict(row)
        item["payload"] = json.loads(item.pop("payload_json") or "{}")
        return item

    def upsert_strategy_definition(
        self, definition: dict[str, Any]
    ) -> dict[str, Any]:
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO strategy_definitions(
                    strategy_id, name, description, status, owner_type,
                    current_version, boundary, subscriptions_enabled,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(strategy_id) DO UPDATE SET
                    name = excluded.name,
                    description = excluded.description,
                    status = excluded.status,
                    owner_type = excluded.owner_type,
                    current_version = excluded.current_version,
                    boundary = excluded.boundary,
                    subscriptions_enabled = excluded.subscriptions_enabled,
                    updated_at = excluded.updated_at
                """,
                (
                    definition["strategy_id"],
                    definition["name"],
                    definition["description"],
                    definition.get("status", "active"),
                    definition.get("owner_type", "system"),
                    definition["current_version"],
                    definition["boundary"],
                    int(bool(definition.get("subscriptions_enabled", False))),
                    now,
                    now,
                ),
            )
        return self.get_strategy_definition(str(definition["strategy_id"]))  # type: ignore[return-value]

    def save_strategy_version(self, version: dict[str, Any]) -> dict[str, Any]:
        version_id = str(uuid4())
        published_at = version.get("published_at") or utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO strategy_versions(
                    id, strategy_id, version, method, rules_json,
                    formulas_json, change_notes, published_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    version_id,
                    version["strategy_id"],
                    version["version"],
                    version["method"],
                    json_dumps(version.get("rules") or []),
                    json_dumps(version.get("formulas") or {}),
                    version.get("change_notes") or "",
                    published_at,
                ),
            )
            row = connection.execute(
                """
                SELECT * FROM strategy_versions
                WHERE strategy_id = ? AND version = ?
                """,
                (version["strategy_id"], version["version"]),
            ).fetchone()
        return self._strategy_version_row(row)  # type: ignore[return-value]

    def save_strategy_parameter_version(
        self, parameter: dict[str, Any]
    ) -> dict[str, Any]:
        parameter_id = str(uuid4())
        created_at = parameter.get("created_at") or utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO strategy_parameter_versions(
                    id, strategy_id, strategy_version, parameter_version,
                    parameters_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    parameter_id,
                    parameter["strategy_id"],
                    parameter["strategy_version"],
                    parameter["parameter_version"],
                    json_dumps(parameter.get("parameters") or {}),
                    created_at,
                ),
            )
            row = connection.execute(
                """
                SELECT * FROM strategy_parameter_versions
                WHERE strategy_id = ? AND strategy_version = ?
                    AND parameter_version = ?
                """,
                (
                    parameter["strategy_id"],
                    parameter["strategy_version"],
                    parameter["parameter_version"],
                ),
            ).fetchone()
        return self._strategy_parameter_row(row)  # type: ignore[return-value]

    def list_strategy_definitions(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM strategy_definitions
                ORDER BY name ASC, strategy_id ASC
                """
            ).fetchall()
        return [self._strategy_definition_row(row) for row in rows]  # type: ignore[misc]

    def get_strategy_definition(
        self, strategy_id: str
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM strategy_definitions WHERE strategy_id = ?",
                (strategy_id,),
            ).fetchone()
        return self._strategy_definition_row(row)

    def get_strategy_version(
        self, strategy_id: str, version: str
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM strategy_versions
                WHERE strategy_id = ? AND version = ?
                """,
                (strategy_id, version),
            ).fetchone()
        return self._strategy_version_row(row)

    def get_strategy_parameter_version(
        self,
        strategy_id: str,
        strategy_version: str,
        parameter_version: str,
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM strategy_parameter_versions
                WHERE strategy_id = ? AND strategy_version = ?
                    AND parameter_version = ?
                """,
                (strategy_id, strategy_version, parameter_version),
            ).fetchone()
        return self._strategy_parameter_row(row)

    def start_strategy_screen_run(
        self,
        *,
        strategy_id: str,
        strategy_version: str,
        parameter_version: str,
        data_version: str,
        data_versions: dict[str, str],
        as_of_date: str | None,
        requested_count: int,
    ) -> dict[str, Any]:
        run_id = str(uuid4())
        started_at = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO strategy_screen_runs(
                    id, strategy_id, strategy_version, parameter_version,
                    data_version, data_versions_json, as_of_date, status,
                    requested_count, started_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'running', ?, ?)
                """,
                (
                    run_id,
                    strategy_id,
                    strategy_version,
                    parameter_version,
                    data_version,
                    json_dumps(data_versions),
                    as_of_date,
                    requested_count,
                    started_at,
                ),
            )
        return self.get_strategy_screen_run(run_id)  # type: ignore[return-value]

    def finish_strategy_screen_run(
        self,
        run_id: str,
        *,
        status: str,
        counts: dict[str, int],
        error: str | None = None,
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE strategy_screen_runs
                SET status = ?, processed_count = ?, qualified_count = ?,
                    triggered_count = ?, incomplete_count = ?,
                    invalidated_count = ?, error = ?, finished_at = ?
                WHERE id = ?
                """,
                (
                    status,
                    counts.get("processed", 0),
                    counts.get("qualified", 0),
                    counts.get("triggered", 0),
                    counts.get("data_incomplete", 0),
                    counts.get("invalidated", 0),
                    error,
                    utc_now(),
                    run_id,
                ),
            )
        return self.get_strategy_screen_run(run_id)

    def get_strategy_screen_run(self, run_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM strategy_screen_runs WHERE id = ?", (run_id,)
            ).fetchone()
        return self._strategy_run_row(row)

    def save_strategy_candidate_snapshot(
        self,
        *,
        run_id: str,
        strategy_id: str,
        strategy_version: str,
        parameter_version: str,
        data_version: str,
        symbol: str,
        as_of_date: str,
        status: str,
        evaluation: dict[str, Any],
        previous_status: str | None,
    ) -> tuple[dict[str, Any], bool]:
        candidate_id = str(uuid4())
        created_at = utc_now()
        invalidated_at = created_at if status == "invalidated" else None
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO strategy_candidate_snapshots(
                    id, run_id, strategy_id, strategy_version,
                    parameter_version, data_version, symbol, as_of_date,
                    status, evaluation_status, previous_status, result_json,
                    created_at, invalidated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate_id,
                    run_id,
                    strategy_id,
                    strategy_version,
                    parameter_version,
                    data_version,
                    symbol,
                    as_of_date,
                    status,
                    evaluation["status"],
                    previous_status,
                    json_dumps(evaluation),
                    created_at,
                    invalidated_at,
                ),
            )
            created = cursor.rowcount > 0
            row = connection.execute(
                """
                SELECT * FROM strategy_candidate_snapshots
                WHERE strategy_id = ? AND strategy_version = ?
                    AND parameter_version = ? AND data_version = ?
                    AND symbol = ?
                """,
                (
                    strategy_id,
                    strategy_version,
                    parameter_version,
                    data_version,
                    symbol,
                ),
            ).fetchone()
            if created:
                rule_rows = []
                for rule in evaluation.get("rule_results") or []:
                    rule_rows.append(
                        (
                            str(uuid4()),
                            candidate_id,
                            rule["rule_id"],
                            rule["status"],
                            json_dumps(rule.get("actual_value")),
                            json_dumps(rule.get("threshold")),
                            rule.get("evidence_date"),
                            rule.get("report_period"),
                            rule["source"],
                            rule["formula_version"],
                            json_dumps(rule.get("limitations") or []),
                            created_at,
                        )
                    )
                connection.executemany(
                    """
                    INSERT INTO strategy_rule_results(
                        id, candidate_snapshot_id, rule_id, status,
                        actual_value_json, threshold_json, evidence_date,
                        report_period, source, formula_version,
                        limitations_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    rule_rows,
                )
        candidate = self._strategy_candidate_row(row)  # type: ignore[assignment]
        candidate["rule_results"] = self.list_strategy_rule_results(
            str(candidate["id"])
        )
        return candidate, created

    def latest_strategy_candidate_snapshot(
        self,
        *,
        strategy_id: str,
        strategy_version: str,
        parameter_version: str,
        symbol: str,
        exclude_data_version: str | None = None,
    ) -> dict[str, Any] | None:
        exclude_clause = (
            "AND data_version <> ?" if exclude_data_version is not None else ""
        )
        params: list[Any] = [
            strategy_id,
            strategy_version,
            parameter_version,
            symbol,
        ]
        if exclude_data_version is not None:
            params.append(exclude_data_version)
        with self.connect() as connection:
            row = connection.execute(
                f"""
                SELECT * FROM strategy_candidate_snapshots
                WHERE strategy_id = ? AND strategy_version = ?
                    AND parameter_version = ? AND symbol = ?
                    {exclude_clause}
                ORDER BY created_at DESC, rowid DESC LIMIT 1
                """,
                params,
            ).fetchone()
        item = self._strategy_candidate_row(row)
        if item is not None:
            item["rule_results"] = self.list_strategy_rule_results(str(item["id"]))
        return item

    def list_strategy_candidate_snapshots(
        self,
        *,
        strategy_id: str,
        strategy_version: str,
        parameter_version: str,
        status: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        status_clause = "AND candidates.status = ?" if status is not None else ""
        params: list[Any] = [strategy_id, strategy_version, parameter_version]
        if status is not None:
            params.append(status)
        params.append(max(1, min(int(limit), 1000)))
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT candidates.*
                FROM strategy_candidate_snapshots AS candidates
                WHERE candidates.strategy_id = ?
                    AND candidates.strategy_version = ?
                    AND candidates.parameter_version = ?
                    {status_clause}
                    AND candidates.id = (
                        SELECT current.id
                        FROM strategy_candidate_snapshots AS current
                        WHERE current.strategy_id = candidates.strategy_id
                            AND current.strategy_version = candidates.strategy_version
                            AND current.parameter_version = candidates.parameter_version
                            AND current.symbol = candidates.symbol
                        ORDER BY current.created_at DESC, current.rowid DESC
                        LIMIT 1
                    )
                ORDER BY candidates.as_of_date DESC, candidates.symbol ASC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._strategy_candidate_row(row) for row in rows]  # type: ignore[misc]

    def list_strategy_rule_results(
        self, candidate_snapshot_id: str
    ) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM strategy_rule_results
                WHERE candidate_snapshot_id = ?
                ORDER BY rowid ASC
                """,
                (candidate_snapshot_id,),
            ).fetchall()
        return [self._strategy_rule_row(row) for row in rows]  # type: ignore[misc]

    def save_strategy_trigger_event(
        self, event: dict[str, Any]
    ) -> tuple[dict[str, Any], bool]:
        event_id = str(uuid4())
        created_at = utc_now()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO strategy_trigger_events(
                    id, candidate_snapshot_id, strategy_id, strategy_version,
                    parameter_version, data_version, symbol, rule_id,
                    evidence_date, evidence_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    event["candidate_snapshot_id"],
                    event["strategy_id"],
                    event["strategy_version"],
                    event["parameter_version"],
                    event["data_version"],
                    event["symbol"],
                    event["rule_id"],
                    event["evidence_date"],
                    json_dumps(event.get("evidence") or {}),
                    created_at,
                ),
            )
            created = cursor.rowcount > 0
            row = connection.execute(
                """
                SELECT * FROM strategy_trigger_events
                WHERE strategy_id = ? AND strategy_version = ?
                    AND parameter_version = ? AND symbol = ?
                    AND rule_id = ? AND evidence_date = ?
                """,
                (
                    event["strategy_id"],
                    event["strategy_version"],
                    event["parameter_version"],
                    event["symbol"],
                    event["rule_id"],
                    event["evidence_date"],
                ),
            ).fetchone()
        return self._strategy_trigger_row(row), created  # type: ignore[return-value]

    def list_strategy_trigger_events(
        self,
        *,
        strategy_id: str,
        strategy_version: str,
        parameter_version: str,
        symbol: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        symbol_clause = "AND symbol = ?" if symbol is not None else ""
        params: list[Any] = [strategy_id, strategy_version, parameter_version]
        if symbol is not None:
            params.append(symbol)
        params.append(max(1, min(int(limit), 1000)))
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM strategy_trigger_events
                WHERE strategy_id = ? AND strategy_version = ?
                    AND parameter_version = ? {symbol_clause}
                ORDER BY evidence_date DESC, created_at DESC, rowid DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._strategy_trigger_row(row) for row in rows]  # type: ignore[misc]

    @staticmethod
    def _strategy_definition_row(
        row: sqlite3.Row | None,
    ) -> dict[str, Any] | None:
        if row is None:
            return None
        item = dict(row)
        item["subscriptions_enabled"] = bool(item["subscriptions_enabled"])
        return item

    @staticmethod
    def _strategy_version_row(
        row: sqlite3.Row | None,
    ) -> dict[str, Any] | None:
        if row is None:
            return None
        item = dict(row)
        item["rules"] = json.loads(item.pop("rules_json") or "[]")
        item["formulas"] = json.loads(item.pop("formulas_json") or "{}")
        return item

    @staticmethod
    def _strategy_parameter_row(
        row: sqlite3.Row | None,
    ) -> dict[str, Any] | None:
        if row is None:
            return None
        item = dict(row)
        item["parameters"] = json.loads(item.pop("parameters_json") or "{}")
        return item

    @staticmethod
    def _strategy_run_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        item = dict(row)
        item["data_versions"] = json.loads(item.pop("data_versions_json") or "{}")
        return item

    @staticmethod
    def _strategy_candidate_row(
        row: sqlite3.Row | None,
    ) -> dict[str, Any] | None:
        if row is None:
            return None
        item = dict(row)
        item["result"] = json.loads(item.pop("result_json") or "{}")
        return item

    @staticmethod
    def _strategy_rule_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        item = dict(row)
        item["actual_value"] = json.loads(item.pop("actual_value_json") or "null")
        item["threshold"] = json.loads(item.pop("threshold_json") or "{}")
        item["limitations"] = json.loads(item.pop("limitations_json") or "[]")
        return item

    @staticmethod
    def _strategy_trigger_row(
        row: sqlite3.Row | None,
    ) -> dict[str, Any] | None:
        if row is None:
            return None
        item = dict(row)
        item["evidence"] = json.loads(item.pop("evidence_json") or "{}")
        return item

    def upsert_news_items(self, items: list[dict[str, Any]]) -> int:
        rows = []
        for item in items:
            rows.append(
                (
                    item.get("id") or str(uuid4()),
                    item["symbol"],
                    item["category"],
                    item["title"],
                    item.get("summary"),
                    item["source"],
                    item["url"],
                    item.get("published_at"),
                    item.get("engagement"),
                    item.get("fetched_at") or utc_now(),
                )
            )
        if not rows:
            return 0
        with self.connect() as connection:
            connection.executemany(
                """
                INSERT INTO news_items(
                    id, symbol, category, title, summary, source, url,
                    published_at, engagement, fetched_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT DO UPDATE SET
                    title = excluded.title,
                    summary = excluded.summary,
                    category = excluded.category,
                    symbol = excluded.symbol,
                    source = excluded.source,
                    url = excluded.url,
                    published_at = excluded.published_at,
                    engagement = excluded.engagement,
                    fetched_at = excluded.fetched_at
                """,
                rows,
            )
        return len(rows)

    def list_news(
        self,
        symbol: str | None = None,
        limit: int = 30,
        categories: tuple[str, ...] | None = None,
    ) -> list[dict[str, Any]]:
        clauses = []
        parameters: list[Any] = []
        if symbol:
            clauses.append("symbol = ?")
            parameters.append(symbol)
        if categories:
            placeholders = ",".join("?" for _ in categories)
            clauses.append(f"category IN ({placeholders})")
            parameters.extend(categories)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        parameters.append(limit)
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM news_items{where}
                ORDER BY COALESCE(published_at, fetched_at) DESC LIMIT ?
                """,
                parameters,
            ).fetchall()
        return [dict(row) for row in rows]

    def save_sentiment_snapshot(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        snapshot_id = str(uuid4())
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO sentiment_snapshots(
                    id, symbol, score, band, confidence, sample_size,
                    positive_count, negative_count, neutral_count, method,
                    evidence_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    snapshot["symbol"],
                    snapshot["score"],
                    snapshot["band"],
                    snapshot["confidence"],
                    snapshot["sample_size"],
                    snapshot["positive_count"],
                    snapshot["negative_count"],
                    snapshot["neutral_count"],
                    snapshot["method"],
                    json_dumps(snapshot.get("evidence", {})),
                    snapshot.get("created_at") or utc_now(),
                ),
            )
        return self.latest_sentiment(snapshot["symbol"])  # type: ignore[return-value]

    def latest_sentiment(self, symbol: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM sentiment_snapshots
                WHERE symbol = ? ORDER BY created_at DESC LIMIT 1
                """,
                (symbol,),
            ).fetchone()
        item = self._row(row)
        if item is not None:
            item["evidence"] = json.loads(item.pop("evidence_json"))
        return item

    def save_valuation_snapshot(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        snapshot_id = str(uuid4())
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO valuation_snapshots(
                    id, symbol, name, currency, price, previous_close, pct_change,
                    turnover_rate_pct, pe_ttm, pe_dynamic, pe_static, pb,
                    float_market_cap, total_market_cap, market_timestamp, source,
                    source_url, field_mapping, warnings_json, fetched_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, source, market_timestamp) DO UPDATE SET
                    name = excluded.name,
                    currency = excluded.currency,
                    price = excluded.price,
                    previous_close = excluded.previous_close,
                    pct_change = excluded.pct_change,
                    turnover_rate_pct = excluded.turnover_rate_pct,
                    pe_ttm = excluded.pe_ttm,
                    pe_dynamic = excluded.pe_dynamic,
                    pe_static = excluded.pe_static,
                    pb = excluded.pb,
                    float_market_cap = excluded.float_market_cap,
                    total_market_cap = excluded.total_market_cap,
                    source_url = excluded.source_url,
                    field_mapping = excluded.field_mapping,
                    warnings_json = excluded.warnings_json,
                    fetched_at = excluded.fetched_at
                """,
                (
                    snapshot_id,
                    snapshot["symbol"],
                    snapshot["name"],
                    snapshot.get("currency") or "CNY",
                    snapshot.get("price"),
                    snapshot.get("previous_close"),
                    snapshot.get("pct_change"),
                    snapshot.get("turnover_rate_pct"),
                    snapshot.get("pe_ttm"),
                    snapshot.get("pe_dynamic"),
                    snapshot.get("pe_static"),
                    snapshot.get("pb"),
                    snapshot.get("float_market_cap"),
                    snapshot.get("total_market_cap"),
                    snapshot["market_timestamp"],
                    snapshot["source"],
                    snapshot["source_url"],
                    snapshot.get("field_mapping") or "unknown",
                    json_dumps(snapshot.get("warnings", [])),
                    snapshot.get("fetched_at") or utc_now(),
                ),
            )
        return self.latest_valuation_snapshot(snapshot["symbol"])  # type: ignore[return-value]

    def latest_valuation_snapshot(self, symbol: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM valuation_snapshots
                WHERE symbol = ?
                ORDER BY market_timestamp DESC, fetched_at DESC LIMIT 1
                """,
                (symbol,),
            ).fetchone()
        item = self._row(row)
        if item is not None:
            item["warnings"] = json.loads(item.pop("warnings_json"))
        return item

    def upsert_financial_periods(self, periods: list[dict[str, Any]]) -> int:
        rows = []
        for item in periods:
            rows.append(
                (
                    item["symbol"],
                    item["report_date"],
                    item["report_type"],
                    item.get("report_date_name") or item["report_date"],
                    item.get("notice_date"),
                    item.get("name") or item["symbol"],
                    item.get("currency") or "CNY",
                    item.get("eps_basic"),
                    item.get("eps_diluted"),
                    item.get("book_value_per_share"),
                    item.get("revenue"),
                    item.get("revenue_yoy_pct"),
                    item.get("parent_net_profit"),
                    item.get("net_profit_yoy_pct"),
                    item.get("roe_weighted_pct"),
                    item.get("gross_margin_pct"),
                    item.get("net_margin_pct"),
                    item.get("debt_asset_ratio_pct"),
                    item.get("operating_cashflow"),
                    item.get("operating_cashflow_per_share"),
                    item.get("total_assets"),
                    item.get("total_liabilities"),
                    item.get("total_equity"),
                    item.get("period_basis") or "year_to_date_cumulative",
                    item["source"],
                    item["source_url"],
                    json_dumps(item.get("warnings", [])),
                    item.get("fetched_at") or utc_now(),
                )
            )
        if not rows:
            return 0
        with self.connect() as connection:
            connection.executemany(
                """
                INSERT INTO financial_periods(
                    symbol, report_date, report_type, report_date_name, notice_date,
                    name, currency, eps_basic, eps_diluted, book_value_per_share, revenue,
                    revenue_yoy_pct, parent_net_profit, net_profit_yoy_pct,
                    roe_weighted_pct, gross_margin_pct, net_margin_pct,
                    debt_asset_ratio_pct, operating_cashflow,
                    operating_cashflow_per_share, total_assets, total_liabilities, total_equity,
                    period_basis, source, source_url, warnings_json, fetched_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, report_date, report_type) DO UPDATE SET
                    report_date_name = excluded.report_date_name,
                    notice_date = excluded.notice_date,
                    name = excluded.name,
                    currency = excluded.currency,
                    eps_basic = excluded.eps_basic,
                    eps_diluted = excluded.eps_diluted,
                    book_value_per_share = excluded.book_value_per_share,
                    revenue = excluded.revenue,
                    revenue_yoy_pct = excluded.revenue_yoy_pct,
                    parent_net_profit = excluded.parent_net_profit,
                    net_profit_yoy_pct = excluded.net_profit_yoy_pct,
                    roe_weighted_pct = excluded.roe_weighted_pct,
                    gross_margin_pct = excluded.gross_margin_pct,
                    net_margin_pct = excluded.net_margin_pct,
                    debt_asset_ratio_pct = excluded.debt_asset_ratio_pct,
                    operating_cashflow = excluded.operating_cashflow,
                    operating_cashflow_per_share = excluded.operating_cashflow_per_share,
                    total_assets = excluded.total_assets,
                    total_liabilities = excluded.total_liabilities,
                    total_equity = excluded.total_equity,
                    period_basis = excluded.period_basis,
                    source = excluded.source,
                    source_url = excluded.source_url,
                    warnings_json = excluded.warnings_json,
                    fetched_at = excluded.fetched_at
                """,
                rows,
            )
        return len(rows)

    def list_financial_periods(
        self, symbol: str, limit: int = 8
    ) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM financial_periods
                WHERE symbol = ?
                ORDER BY report_date DESC LIMIT ?
                """,
                (symbol, limit),
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["warnings"] = json.loads(item.pop("warnings_json"))
            items.append(item)
        return items

    def save_earnings_quality_snapshot(
        self, snapshot: dict[str, Any], fingerprint: str
    ) -> dict[str, Any]:
        snapshot_id = str(uuid4())
        created_at = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO earnings_quality_snapshots(
                    id, symbol, report_date, method, fingerprint,
                    payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, report_date, method) DO UPDATE SET
                    fingerprint = excluded.fingerprint,
                    payload_json = excluded.payload_json,
                    created_at = excluded.created_at
                """,
                (
                    snapshot_id,
                    snapshot["symbol"],
                    snapshot["latest_report"]["report_date"],
                    snapshot["method"],
                    fingerprint,
                    json_dumps(snapshot),
                    created_at,
                ),
            )
        return self.latest_earnings_quality_snapshot(snapshot["symbol"])  # type: ignore[return-value]

    def latest_earnings_quality_snapshot(
        self, symbol: str
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM earnings_quality_snapshots
                WHERE symbol = ?
                ORDER BY report_date DESC, created_at DESC, rowid DESC LIMIT 1
                """,
                (symbol,),
            ).fetchone()
        item = self._row(row)
        if item is not None:
            item["payload"] = json.loads(item.pop("payload_json") or "{}")
        return item

    def upsert_financial_statement_details(
        self, statements: list[dict[str, Any]]
    ) -> int:
        rows = []
        for item in statements:
            rows.append(
                (
                    item["symbol"],
                    item["report_date"],
                    item["report_type"],
                    item.get("report_date_name") or item["report_date"],
                    item.get("notice_date"),
                    item.get("name") or item["symbol"],
                    item.get("currency") or "CNY",
                    item.get("fiscal_period") or "UNKNOWN",
                    item.get("period_basis") or "year_to_date_cumulative",
                    item["statement_type"],
                    json_dumps(item.get("fields") or {}),
                    item["source"],
                    item["source_url"],
                    json_dumps(item.get("warnings") or []),
                    item.get("fetched_at") or utc_now(),
                )
            )
        if not rows:
            return 0
        with self.connect() as connection:
            connection.executemany(
                """
                INSERT INTO financial_statement_details(
                    symbol, report_date, report_type, report_date_name, notice_date,
                    name, currency, fiscal_period, period_basis, statement_type,
                    fields_json, source, source_url, warnings_json, fetched_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, report_date, report_type, statement_type) DO UPDATE SET
                    report_date_name = excluded.report_date_name,
                    notice_date = excluded.notice_date,
                    name = excluded.name,
                    currency = excluded.currency,
                    fiscal_period = excluded.fiscal_period,
                    period_basis = excluded.period_basis,
                    fields_json = excluded.fields_json,
                    source = excluded.source,
                    source_url = excluded.source_url,
                    warnings_json = excluded.warnings_json,
                    fetched_at = excluded.fetched_at
                """,
                rows,
            )
        return len(rows)

    def list_financial_statement_details(
        self, symbol: str, limit: int = 36
    ) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM financial_statement_details
                WHERE symbol = ?
                ORDER BY report_date DESC,
                    CASE statement_type
                        WHEN 'income' THEN 1
                        WHEN 'balance' THEN 2
                        ELSE 3
                    END
                LIMIT ?
                """,
                (symbol, limit),
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["fields"] = json.loads(item.pop("fields_json") or "{}")
            item["warnings"] = json.loads(item.pop("warnings_json") or "[]")
            items.append(item)
        return items

    def save_financial_driver_snapshot(
        self, snapshot: dict[str, Any], fingerprint: str
    ) -> dict[str, Any]:
        snapshot_id = str(uuid4())
        created_at = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO financial_driver_snapshots(
                    id, symbol, report_date, method, fingerprint,
                    payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, report_date, method) DO UPDATE SET
                    fingerprint = excluded.fingerprint,
                    payload_json = excluded.payload_json,
                    created_at = excluded.created_at
                """,
                (
                    snapshot_id,
                    snapshot["symbol"],
                    snapshot["latest_period"]["report_date"],
                    snapshot["method"],
                    fingerprint,
                    json_dumps(snapshot),
                    created_at,
                ),
            )
        return self.latest_financial_driver_snapshot(snapshot["symbol"])  # type: ignore[return-value]

    def latest_financial_driver_snapshot(
        self, symbol: str
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM financial_driver_snapshots
                WHERE symbol = ?
                ORDER BY report_date DESC, created_at DESC, rowid DESC LIMIT 1
                """,
                (symbol,),
            ).fetchone()
        item = self._row(row)
        if item is not None:
            item["payload"] = json.loads(item.pop("payload_json") or "{}")
        return item

    def upsert_filing_document(self, document: dict[str, Any]) -> dict[str, Any]:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO filing_documents(
                    symbol, article_code, title, document_type, report_period,
                    notice_date, published_at, content_text, attach_url,
                    content_hash, source, source_url, warnings_json, fetched_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, article_code) DO UPDATE SET
                    title = excluded.title,
                    document_type = excluded.document_type,
                    report_period = excluded.report_period,
                    notice_date = excluded.notice_date,
                    published_at = excluded.published_at,
                    content_text = excluded.content_text,
                    attach_url = excluded.attach_url,
                    content_hash = excluded.content_hash,
                    source = excluded.source,
                    source_url = excluded.source_url,
                    warnings_json = excluded.warnings_json,
                    fetched_at = excluded.fetched_at
                """,
                (
                    document["symbol"],
                    document["article_code"],
                    document["title"],
                    document["document_type"],
                    document.get("report_period"),
                    document.get("notice_date"),
                    document.get("published_at"),
                    document.get("content_text") or "",
                    document.get("attach_url"),
                    document["content_hash"],
                    document.get("source") or "company_filing",
                    document["source_url"],
                    json_dumps(document.get("warnings") or []),
                    document.get("fetched_at") or utc_now(),
                ),
            )
        return self.get_filing_document(
            document["symbol"], document["article_code"]
        )  # type: ignore[return-value]

    def get_filing_document(
        self, symbol: str, article_code: str
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM filing_documents
                WHERE symbol = ? AND article_code = ?
                """,
                (symbol, article_code),
            ).fetchone()
        item = self._row(row)
        if item is not None:
            item["warnings"] = json.loads(item.pop("warnings_json") or "[]")
        return item

    def list_filing_documents(
        self,
        symbol: str,
        limit: int = 6,
        *,
        include_content: bool = False,
    ) -> list[dict[str, Any]]:
        fields = "*" if include_content else """
            symbol, article_code, title, document_type, report_period,
            notice_date, published_at, attach_url, content_hash, source,
            source_url, warnings_json, fetched_at,
            LENGTH(content_text) AS content_chars
        """
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT {fields} FROM filing_documents
                WHERE symbol = ?
                ORDER BY COALESCE(report_period, notice_date, published_at) DESC,
                    published_at DESC
                LIMIT ?
                """,
                (symbol, limit),
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["warnings"] = json.loads(item.pop("warnings_json") or "[]")
            items.append(item)
        return items

    def save_filing_evidence_snapshot(
        self, snapshot: dict[str, Any], fingerprint: str
    ) -> dict[str, Any]:
        snapshot_id = str(uuid4())
        created_at = utc_now()
        document = snapshot.get("document") or {}
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO filing_evidence_snapshots(
                    id, symbol, article_code, report_period, method,
                    fingerprint, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, article_code, method) DO UPDATE SET
                    report_period = excluded.report_period,
                    fingerprint = excluded.fingerprint,
                    payload_json = excluded.payload_json,
                    created_at = excluded.created_at
                """,
                (
                    snapshot_id,
                    snapshot["symbol"],
                    document["article_code"],
                    document.get("report_period"),
                    snapshot["method"],
                    fingerprint,
                    json_dumps(snapshot),
                    created_at,
                ),
            )
        return self.latest_filing_evidence_snapshot(
            snapshot["symbol"], article_code=document["article_code"]
        )  # type: ignore[return-value]

    def latest_filing_evidence_snapshot(
        self,
        symbol: str,
        *,
        report_period: str | None = None,
        article_code: str | None = None,
    ) -> dict[str, Any] | None:
        clauses = ["symbol = ?"]
        params: list[Any] = [symbol]
        if report_period is not None:
            clauses.append("report_period = ?")
            params.append(report_period)
        if article_code is not None:
            clauses.append("article_code = ?")
            params.append(article_code)
        with self.connect() as connection:
            row = connection.execute(
                f"""
                SELECT * FROM filing_evidence_snapshots
                WHERE {' AND '.join(clauses)}
                ORDER BY COALESCE(report_period, created_at) DESC,
                    created_at DESC, rowid DESC LIMIT 1
                """,
                params,
            ).fetchone()
        item = self._row(row)
        if item is not None:
            item["payload"] = json.loads(item.pop("payload_json") or "{}")
        return item

    def upsert_business_segment_rows(self, rows: list[dict[str, Any]]) -> int:
        values = [
            (
                item["symbol"],
                item["report_date"],
                item["classification"],
                item["item_name"],
                item.get("revenue"),
                item.get("revenue_share_pct"),
                item.get("cost"),
                item.get("cost_share_pct"),
                item.get("gross_profit"),
                item.get("gross_profit_share_pct"),
                item.get("gross_margin_pct"),
                item.get("source") or "business_composition",
                item["source_url"],
                item.get("fetched_at") or utc_now(),
            )
            for item in rows
        ]
        if not values:
            return 0
        with self.connect() as connection:
            connection.executemany(
                """
                INSERT INTO business_segment_rows(
                    symbol, report_date, classification, item_name,
                    revenue, revenue_share_pct, cost, cost_share_pct,
                    gross_profit, gross_profit_share_pct, gross_margin_pct,
                    source, source_url, fetched_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, report_date, classification, item_name)
                DO UPDATE SET
                    revenue = excluded.revenue,
                    revenue_share_pct = excluded.revenue_share_pct,
                    cost = excluded.cost,
                    cost_share_pct = excluded.cost_share_pct,
                    gross_profit = excluded.gross_profit,
                    gross_profit_share_pct = excluded.gross_profit_share_pct,
                    gross_margin_pct = excluded.gross_margin_pct,
                    source = excluded.source,
                    source_url = excluded.source_url,
                    fetched_at = excluded.fetched_at
                """,
                values,
            )
        return len(values)

    def list_business_segment_rows(
        self, symbol: str, limit: int = 500
    ) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM business_segment_rows
                WHERE symbol = ?
                ORDER BY report_date DESC,
                    CASE classification
                        WHEN 'product' THEN 1
                        WHEN 'region' THEN 2
                        ELSE 3
                    END,
                    revenue_share_pct DESC,
                    item_name ASC
                LIMIT ?
                """,
                (symbol, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def save_business_structure_snapshot(
        self, snapshot: dict[str, Any], fingerprint: str
    ) -> dict[str, Any]:
        snapshot_id = str(uuid4())
        created_at = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO business_structure_snapshots(
                    id, symbol, anchor_report_date, method, fingerprint,
                    payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, anchor_report_date, method) DO UPDATE SET
                    fingerprint = excluded.fingerprint,
                    payload_json = excluded.payload_json,
                    created_at = excluded.created_at
                """,
                (
                    snapshot_id,
                    snapshot["symbol"],
                    snapshot["anchor_report_date"],
                    snapshot["method"],
                    fingerprint,
                    json_dumps(snapshot),
                    created_at,
                ),
            )
        return self.latest_business_structure_snapshot(
            snapshot["symbol"]
        )  # type: ignore[return-value]

    def latest_business_structure_snapshot(
        self, symbol: str
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM business_structure_snapshots
                WHERE symbol = ?
                ORDER BY anchor_report_date DESC, created_at DESC, rowid DESC
                LIMIT 1
                """,
                (symbol,),
            ).fetchone()
        item = self._row(row)
        if item is not None:
            item["payload"] = json.loads(item.pop("payload_json") or "{}")
        return item

    def save_peer_operating_snapshot(
        self, snapshot: dict[str, Any], fingerprint: str
    ) -> dict[str, Any]:
        snapshot_id = str(uuid4())
        created_at = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO peer_operating_snapshots(
                    id, symbol, anchor_report_date, method, fingerprint,
                    payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, fingerprint) DO UPDATE SET
                    anchor_report_date = excluded.anchor_report_date,
                    payload_json = excluded.payload_json,
                    created_at = excluded.created_at
                """,
                (
                    snapshot_id,
                    snapshot["symbol"],
                    snapshot["anchor_report_date"],
                    snapshot["method"],
                    fingerprint,
                    json_dumps(snapshot),
                    created_at,
                ),
            )
        return self.latest_peer_operating_snapshot(
            snapshot["symbol"]
        )  # type: ignore[return-value]

    def latest_peer_operating_snapshot(
        self, symbol: str
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM peer_operating_snapshots
                WHERE symbol = ?
                ORDER BY anchor_report_date DESC, created_at DESC, rowid DESC
                LIMIT 1
                """,
                (symbol,),
            ).fetchone()
        item = self._row(row)
        if item is not None:
            item["payload"] = json.loads(item.pop("payload_json") or "{}")
        return item

    def save_shareholder_structure_snapshot(
        self, snapshot: dict[str, Any], fingerprint: str
    ) -> dict[str, Any]:
        snapshot_id = str(uuid4())
        created_at = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO shareholder_structure_snapshots(
                    id, symbol, name, holder_count_as_of, announced_at,
                    holder_count, previous_holder_count, holder_count_change,
                    change_pct, average_holding, average_market_cap,
                    interval_price_change_pct, top10_report_date, top10_ratio,
                    top3_ratio, top_holders_json, method, fingerprint,
                    payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, holder_count_as_of, method) DO UPDATE SET
                    name = excluded.name,
                    announced_at = excluded.announced_at,
                    holder_count = excluded.holder_count,
                    previous_holder_count = excluded.previous_holder_count,
                    holder_count_change = excluded.holder_count_change,
                    change_pct = excluded.change_pct,
                    average_holding = excluded.average_holding,
                    average_market_cap = excluded.average_market_cap,
                    interval_price_change_pct = excluded.interval_price_change_pct,
                    top10_report_date = excluded.top10_report_date,
                    top10_ratio = excluded.top10_ratio,
                    top3_ratio = excluded.top3_ratio,
                    top_holders_json = excluded.top_holders_json,
                    fingerprint = excluded.fingerprint,
                    payload_json = excluded.payload_json,
                    created_at = excluded.created_at
                """,
                (
                    snapshot_id,
                    snapshot["symbol"],
                    snapshot["name"],
                    snapshot["holder_count_as_of"],
                    snapshot.get("announced_at"),
                    snapshot.get("holder_count"),
                    snapshot.get("previous_holder_count"),
                    snapshot.get("holder_count_change"),
                    snapshot.get("holder_count_change_pct"),
                    snapshot.get("average_holding"),
                    snapshot.get("average_market_cap"),
                    snapshot.get("interval_price_change_pct"),
                    snapshot.get("top10_report_date"),
                    snapshot.get("top10_ratio_pct"),
                    snapshot.get("top3_ratio_pct"),
                    json_dumps(snapshot.get("top_holders") or []),
                    snapshot["method"],
                    fingerprint,
                    json_dumps(snapshot),
                    created_at,
                ),
            )
        return self.latest_shareholder_structure_snapshot(
            snapshot["symbol"]
        )  # type: ignore[return-value]

    def latest_shareholder_structure_snapshot(
        self, symbol: str
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM shareholder_structure_snapshots
                WHERE symbol = ?
                ORDER BY holder_count_as_of DESC, created_at DESC, rowid DESC
                LIMIT 1
                """,
                (symbol,),
            ).fetchone()
        item = self._row(row)
        if item is not None:
            item["top_holders"] = json.loads(
                item.pop("top_holders_json") or "[]"
            )
            item["payload"] = json.loads(item.pop("payload_json") or "{}")
        return item

    def save_analyst_expectation_snapshot(
        self, snapshot: dict[str, Any], fingerprint: str
    ) -> dict[str, Any]:
        snapshot_id = str(uuid4())
        created_at = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO analyst_expectation_snapshots(
                    id, symbol, name, as_of_date, latest_report_date,
                    rating_organization_count, method, fingerprint,
                    payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, fingerprint) DO UPDATE SET
                    name = excluded.name,
                    as_of_date = excluded.as_of_date,
                    latest_report_date = excluded.latest_report_date,
                    rating_organization_count = excluded.rating_organization_count,
                    payload_json = excluded.payload_json,
                    created_at = excluded.created_at
                """,
                (
                    snapshot_id,
                    snapshot["symbol"],
                    snapshot["name"],
                    snapshot["as_of_date"],
                    snapshot.get("latest_report_date"),
                    snapshot.get("rating_organization_count"),
                    snapshot["method"],
                    fingerprint,
                    json_dumps(snapshot),
                    created_at,
                ),
            )
        return self.latest_analyst_expectation_snapshot(
            snapshot["symbol"]
        )  # type: ignore[return-value]

    def save_event_timeline_snapshot(
        self, snapshot: dict[str, Any], fingerprint: str
    ) -> dict[str, Any]:
        snapshot_id = str(uuid4())
        created_at = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO event_timeline_snapshots(
                    id, symbol, name, as_of_date, method, fingerprint,
                    payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    snapshot["symbol"],
                    snapshot["name"],
                    snapshot["as_of_date"],
                    snapshot["method"],
                    fingerprint,
                    json_dumps(snapshot),
                    created_at,
                ),
            )
            row = connection.execute(
                """
                SELECT * FROM event_timeline_snapshots
                WHERE symbol = ? AND fingerprint = ?
                """,
                (snapshot["symbol"], fingerprint),
            ).fetchone()
        return self._event_timeline_row(row)  # type: ignore[return-value]

    def latest_event_timeline_snapshot(
        self, symbol: str
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM event_timeline_snapshots
                WHERE symbol = ?
                ORDER BY created_at DESC, rowid DESC LIMIT 1
                """,
                (symbol,),
            ).fetchone()
        return self._event_timeline_row(row)

    @staticmethod
    def _event_timeline_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        item = dict(row)
        item["payload"] = json.loads(item.pop("payload_json") or "{}")
        return item

    def latest_analyst_expectation_snapshot(
        self, symbol: str
    ) -> dict[str, Any] | None:
        items = self.list_analyst_expectation_snapshots(symbol, limit=1)
        return items[0] if items else None

    def list_analyst_expectation_snapshots(
        self, symbol: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM analyst_expectation_snapshots
                WHERE symbol = ?
                ORDER BY created_at DESC, rowid DESC
                LIMIT ?
                """,
                (symbol, max(1, min(limit, 100))),
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json") or "{}")
            items.append(item)
        return items

    def create_research_report(
        self,
        symbol: str,
        name: str,
        title: str,
        summary: str,
        body: str,
        status: str,
        fingerprint: str,
        evidence: dict[str, Any],
        run_id: str | None,
        market_timestamp: str | None,
    ) -> dict[str, Any]:
        report_id = str(uuid4())
        generated_at = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO research_reports(
                    id, symbol, name, title, summary, body, status, fingerprint,
                    evidence_json, run_id, market_timestamp, generated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report_id,
                    symbol,
                    name,
                    title,
                    summary,
                    body,
                    status,
                    fingerprint,
                    json_dumps(evidence),
                    run_id,
                    market_timestamp,
                    generated_at,
                ),
            )
        return self.latest_research_report(symbol)  # type: ignore[return-value]

    def latest_research_report(self, symbol: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM research_reports
                WHERE symbol = ? ORDER BY generated_at DESC LIMIT 1
                """,
                (symbol,),
            ).fetchone()
        item = self._row(row)
        if item is not None:
            item["evidence"] = json.loads(item.pop("evidence_json"))
        return item

    def list_research_reports(
        self, symbol: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM research_reports
                WHERE symbol = ?
                ORDER BY generated_at DESC, rowid DESC LIMIT ?
                """,
                (symbol, limit),
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["evidence"] = json.loads(item.pop("evidence_json"))
            items.append(item)
        return items

    def list_latest_research_reports(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM research_reports AS reports
                WHERE id = (
                    SELECT inner_reports.id
                    FROM research_reports AS inner_reports
                    WHERE inner_reports.symbol = reports.symbol
                    ORDER BY inner_reports.generated_at DESC, inner_reports.rowid DESC
                    LIMIT 1
                )
                ORDER BY generated_at DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["evidence"] = json.loads(item.pop("evidence_json"))
            items.append(item)
        return items

    def save_research_change_event(
        self,
        *,
        symbol: str,
        report_id: str,
        previous_report_id: str | None,
        event_type: str,
        severity: str,
        summary: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        event_id = str(uuid4())
        created_at = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO research_change_events(
                    id, symbol, report_id, previous_report_id, event_type,
                    severity, summary, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    symbol,
                    report_id,
                    previous_report_id,
                    event_type,
                    severity,
                    summary,
                    json_dumps(payload),
                    created_at,
                ),
            )
            row = connection.execute(
                """
                SELECT * FROM research_change_events
                WHERE symbol = ? AND report_id = ?
                """,
                (symbol, report_id),
            ).fetchone()
        return self._research_change_row(row)  # type: ignore[return-value]

    def research_change_event_for_report(
        self, symbol: str, report_id: str
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM research_change_events
                WHERE symbol = ? AND report_id = ?
                """,
                (symbol, report_id),
            ).fetchone()
        return self._research_change_row(row)

    def latest_research_change_event(self, symbol: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM research_change_events
                WHERE symbol = ? ORDER BY created_at DESC, rowid DESC LIMIT 1
                """,
                (symbol,),
            ).fetchone()
        return self._research_change_row(row)

    def list_research_change_events(
        self, symbols: list[str], limit: int = 20
    ) -> list[dict[str, Any]]:
        if not symbols:
            return []
        placeholders = ",".join("?" for _ in symbols)
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM research_change_events
                WHERE symbol IN ({placeholders})
                ORDER BY created_at DESC, rowid DESC LIMIT ?
                """,
                (*symbols, limit),
            ).fetchall()
        return [self._research_change_row(row) for row in rows]  # type: ignore[misc]

    @staticmethod
    def _research_change_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        item = dict(row)
        item["payload"] = json.loads(item.pop("payload_json") or "{}")
        return item

    def save_research_priority_snapshot(
        self, user_id: str, fingerprint: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        snapshot_id = str(uuid4())
        created_at = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO research_priority_snapshots(
                    id, user_id, fingerprint, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    user_id,
                    fingerprint,
                    json_dumps(payload),
                    created_at,
                ),
            )
            row = connection.execute(
                """
                SELECT * FROM research_priority_snapshots
                WHERE user_id = ? AND fingerprint = ?
                """,
                (user_id, fingerprint),
            ).fetchone()
        return self._research_priority_row(row)  # type: ignore[return-value]

    def latest_research_priority_snapshot(
        self, user_id: str
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM research_priority_snapshots
                WHERE user_id = ?
                ORDER BY created_at DESC, rowid DESC LIMIT 1
                """,
                (user_id,),
            ).fetchone()
        return self._research_priority_row(row)

    @staticmethod
    def _research_priority_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        item = dict(row)
        item["payload"] = json.loads(item.pop("payload_json") or "{}")
        return item

    def save_research_action_snapshot(
        self, user_id: str, fingerprint: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        snapshot_id = str(uuid4())
        created_at = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO research_action_snapshots(
                    id, user_id, fingerprint, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    user_id,
                    fingerprint,
                    json_dumps(payload),
                    created_at,
                ),
            )
            row = connection.execute(
                """
                SELECT * FROM research_action_snapshots
                WHERE user_id = ? AND fingerprint = ?
                """,
                (user_id, fingerprint),
            ).fetchone()
        return self._research_action_row(row)  # type: ignore[return-value]

    def latest_research_action_snapshot(
        self, user_id: str
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM research_action_snapshots
                WHERE user_id = ?
                ORDER BY created_at DESC, rowid DESC LIMIT 1
                """,
                (user_id,),
            ).fetchone()
        return self._research_action_row(row)

    @staticmethod
    def _research_action_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        item = dict(row)
        item["payload"] = json.loads(item.pop("payload_json") or "{}")
        return item

    def upsert_evidence_task(self, task: dict[str, Any]) -> dict[str, Any]:
        task_id = str(task.get("id") or uuid4())
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO evidence_tasks(
                    id, user_id, conversation_id, run_id, subject_kind,
                    symbol, market_key, intent, task_type, gap_key, title,
                    description, query, status, priority, fingerprint,
                    retry_count, max_retries, metadata_json, created_at,
                    updated_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?)
                ON CONFLICT(fingerprint) DO UPDATE SET
                    conversation_id = excluded.conversation_id,
                    run_id = excluded.run_id,
                    title = excluded.title,
                    description = excluded.description,
                    query = excluded.query,
                    priority = MAX(evidence_tasks.priority, excluded.priority),
                    metadata_json = excluded.metadata_json,
                    status = CASE
                        WHEN evidence_tasks.status = 'failed'
                             AND evidence_tasks.retry_count < evidence_tasks.max_retries
                        THEN 'pending'
                        ELSE evidence_tasks.status
                    END,
                    last_error = CASE
                        WHEN evidence_tasks.status = 'failed'
                             AND evidence_tasks.retry_count < evidence_tasks.max_retries
                        THEN NULL
                        ELSE evidence_tasks.last_error
                    END,
                    updated_at = excluded.updated_at,
                    last_seen_at = excluded.last_seen_at
                """,
                (
                    task_id,
                    task["user_id"],
                    task.get("conversation_id"),
                    task.get("run_id"),
                    task["subject_kind"],
                    task.get("symbol"),
                    task.get("market_key"),
                    task["intent"],
                    task["task_type"],
                    task["gap_key"],
                    task["title"],
                    task["description"],
                    task["query"],
                    task.get("status") or "pending",
                    int(task.get("priority") or 50),
                    task["fingerprint"],
                    int(task.get("max_retries") or 3),
                    json_dumps(task.get("metadata") or {}),
                    now,
                    now,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM evidence_tasks WHERE fingerprint = ?",
                (task["fingerprint"],),
            ).fetchone()
        return self._evidence_task_row(row)  # type: ignore[return-value]

    def get_evidence_task(
        self, user_id: str, task_id: str
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM evidence_tasks WHERE id = ? AND user_id = ?",
                (task_id, user_id),
            ).fetchone()
        return self._evidence_task_row(row)

    def list_evidence_tasks(
        self,
        user_id: str,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM evidence_tasks
                WHERE user_id = ? AND (? IS NULL OR status = ?)
                ORDER BY
                    CASE status
                        WHEN 'collecting' THEN 5
                        WHEN 'pending' THEN 4
                        WHEN 'failed' THEN 3
                        WHEN 'pending_external' THEN 2
                        ELSE 1
                    END DESC,
                    priority DESC, updated_at DESC, rowid DESC
                LIMIT ?
                """,
                (user_id, status, status, limit),
            ).fetchall()
        return [self._evidence_task_row(row) for row in rows]  # type: ignore[misc]

    def list_pending_evidence_tasks(
        self, user_id: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM evidence_tasks
                WHERE (? IS NULL OR user_id = ?)
                  AND (
                    status = 'pending'
                    OR (status = 'failed' AND retry_count < max_retries)
                  )
                ORDER BY priority DESC, updated_at ASC, rowid ASC
                LIMIT ?
                """,
                (user_id, user_id, limit),
            ).fetchall()
        return [self._evidence_task_row(row) for row in rows]  # type: ignore[misc]

    def claim_evidence_task(
        self, task_id: str, user_id: str | None = None
    ) -> dict[str, Any] | None:
        now = utc_now()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE evidence_tasks
                SET status = 'collecting', retry_count = retry_count + 1,
                    started_at = ?, updated_at = ?, last_error = NULL
                WHERE id = ? AND (? IS NULL OR user_id = ?)
                  AND (
                    status = 'pending'
                    OR (status = 'failed' AND retry_count < max_retries)
                  )
                """,
                (now, now, task_id, user_id, user_id),
            )
            if cursor.rowcount == 0:
                return None
            row = connection.execute(
                "SELECT * FROM evidence_tasks WHERE id = ?", (task_id,)
            ).fetchone()
        return self._evidence_task_row(row)

    def finish_evidence_task(
        self,
        task_id: str,
        status: str,
        *,
        resolution_document_id: str | None = None,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        now = utc_now()
        resolved_at = now if status == "resolved" else None
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE evidence_tasks
                SET status = ?, resolution_document_id = ?, last_error = ?,
                    metadata_json = COALESCE(?, metadata_json),
                    updated_at = ?, resolved_at = ?
                WHERE id = ?
                """,
                (
                    status,
                    resolution_document_id,
                    error,
                    json_dumps(metadata) if metadata is not None else None,
                    now,
                    resolved_at,
                    task_id,
                ),
            )
            row = connection.execute(
                "SELECT * FROM evidence_tasks WHERE id = ?", (task_id,)
            ).fetchone()
        return self._evidence_task_row(row)

    def evidence_task_summary(self, user_id: str) -> dict[str, int]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT status, COUNT(*) AS count
                FROM evidence_tasks WHERE user_id = ? GROUP BY status
                """,
                (user_id,),
            ).fetchall()
        counts = {str(row["status"]): int(row["count"]) for row in rows}
        return {
            "total": sum(counts.values()),
            "pending": counts.get("pending", 0),
            "collecting": counts.get("collecting", 0),
            "resolved": counts.get("resolved", 0),
            "pending_external": counts.get("pending_external", 0),
            "failed": counts.get("failed", 0),
        }

    @staticmethod
    def _evidence_task_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        item = dict(row)
        item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
        return item

    def list_research_anchor_reports(
        self, symbol: str | None = None, limit: int = 1000
    ) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                WITH ranked AS (
                    SELECT reports.*,
                        ROW_NUMBER() OVER (
                            PARTITION BY symbol,
                                COALESCE(market_timestamp, generated_at)
                            ORDER BY generated_at DESC, rowid DESC
                        ) AS anchor_rank
                    FROM research_reports AS reports
                    WHERE (? IS NULL OR symbol = ?)
                )
                SELECT * FROM ranked
                WHERE anchor_rank = 1
                ORDER BY COALESCE(market_timestamp, generated_at) DESC,
                    generated_at DESC
                LIMIT ?
                """,
                (symbol, symbol, limit),
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item.pop("anchor_rank", None)
            item["evidence"] = json.loads(item.pop("evidence_json"))
            items.append(item)
        return items

    def research_outcome_for_anchor(
        self, symbol: str, anchor_timestamp: str, horizon_sessions: int
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM research_outcomes
                WHERE symbol = ? AND anchor_timestamp = ?
                    AND horizon_sessions = ?
                """,
                (symbol, anchor_timestamp, horizon_sessions),
            ).fetchone()
        return self._research_outcome_row(row)

    def save_research_outcome(self, outcome: dict[str, Any]) -> dict[str, Any]:
        outcome_id = str(uuid4())
        calculated_at = outcome.get("calculated_at") or utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO research_outcomes(
                    id, report_id, symbol, name, anchor_timestamp,
                    horizon_sessions, result_status, observed_sessions,
                    anchor_close, target_timestamp, target_close,
                    close_return_pct, maximum_favorable_excursion_pct,
                    maximum_adverse_excursion_pct, scenario_result,
                    review_conclusion, payload_json, calculated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, anchor_timestamp, horizon_sessions) DO UPDATE SET
                    report_id = excluded.report_id,
                    name = excluded.name,
                    result_status = excluded.result_status,
                    observed_sessions = excluded.observed_sessions,
                    anchor_close = excluded.anchor_close,
                    target_timestamp = excluded.target_timestamp,
                    target_close = excluded.target_close,
                    close_return_pct = excluded.close_return_pct,
                    maximum_favorable_excursion_pct =
                        excluded.maximum_favorable_excursion_pct,
                    maximum_adverse_excursion_pct =
                        excluded.maximum_adverse_excursion_pct,
                    scenario_result = excluded.scenario_result,
                    review_conclusion = excluded.review_conclusion,
                    payload_json = excluded.payload_json,
                    calculated_at = excluded.calculated_at
                """,
                (
                    outcome_id,
                    outcome["report_id"],
                    outcome["symbol"],
                    outcome["name"],
                    outcome["anchor_timestamp"],
                    outcome["horizon_sessions"],
                    outcome["result_status"],
                    outcome["observed_sessions"],
                    outcome.get("anchor_close"),
                    outcome.get("target_timestamp"),
                    outcome.get("target_close"),
                    outcome.get("close_return_pct"),
                    outcome.get("maximum_favorable_excursion_pct"),
                    outcome.get("maximum_adverse_excursion_pct"),
                    outcome.get("scenario_result"),
                    outcome["review_conclusion"],
                    json_dumps(outcome.get("payload") or {}),
                    calculated_at,
                ),
            )
            row = connection.execute(
                """
                SELECT * FROM research_outcomes
                WHERE symbol = ? AND anchor_timestamp = ?
                    AND horizon_sessions = ?
                """,
                (
                    outcome["symbol"],
                    outcome["anchor_timestamp"],
                    outcome["horizon_sessions"],
                ),
            ).fetchone()
        return self._research_outcome_row(row)  # type: ignore[return-value]

    def list_research_outcomes(
        self, symbols: list[str] | None = None, limit: int = 200
    ) -> list[dict[str, Any]]:
        params: list[Any] = []
        where = ""
        if symbols:
            placeholders = ",".join("?" for _ in symbols)
            where = f"WHERE symbol IN ({placeholders})"
            params.extend(symbols)
        params.append(limit)
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM research_outcomes
                {where}
                ORDER BY anchor_timestamp DESC, horizon_sessions ASC,
                    calculated_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._research_outcome_row(row) for row in rows]  # type: ignore[misc]

    @staticmethod
    def _research_outcome_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        item = dict(row)
        item["payload"] = json.loads(item.pop("payload_json") or "{}")
        return item

    def save_outlook_calibration(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        calibration_id = str(uuid4())
        created_at = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO outlook_calibrations(
                    id, symbol, method, history_first, history_last,
                    history_points, source, payload_json, fetched_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, method, history_last) DO UPDATE SET
                    history_first = excluded.history_first,
                    history_points = excluded.history_points,
                    source = excluded.source,
                    payload_json = excluded.payload_json,
                    fetched_at = excluded.fetched_at,
                    created_at = excluded.created_at
                """,
                (
                    calibration_id,
                    snapshot["symbol"],
                    snapshot["method"],
                    snapshot.get("history_first"),
                    snapshot["history_last"],
                    snapshot["history_points"],
                    snapshot["source"],
                    json_dumps(snapshot["calibration"]),
                    snapshot.get("fetched_at") or created_at,
                    created_at,
                ),
            )
        return self.latest_outlook_calibration(snapshot["symbol"])  # type: ignore[return-value]

    def latest_outlook_calibration(self, symbol: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM outlook_calibrations
                WHERE symbol = ?
                ORDER BY created_at DESC, rowid DESC LIMIT 1
                """,
                (symbol,),
            ).fetchone()
        item = self._row(row)
        if item is not None:
            item["calibration"] = json.loads(item.pop("payload_json"))
        return item
