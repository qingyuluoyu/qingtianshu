from __future__ import annotations

import ast
from pathlib import Path

from app.domain_schema import DOMAIN_SCHEMA_SQL


ROOT = Path(__file__).resolve().parents[1]


def test_domain_schema_keeps_required_product_tables() -> None:
    for table in (
        "users",
        "runs",
        "conversations",
        "stock_workspaces",
        "observation_tasks",
        "position_operations",
        "trade_reviews",
        "research_reports",
        "evidence_tasks",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in DOMAIN_SCHEMA_SQL


def test_database_initialize_stays_a_migration_orchestrator() -> None:
    tree = ast.parse((ROOT / "app" / "db.py").read_text(encoding="utf-8"))
    initialize = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "initialize"
    )

    assert initialize.end_lineno - initialize.lineno + 1 <= 170
