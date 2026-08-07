from __future__ import annotations

import importlib.util
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest


ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "frontend" / "scripts" / "run_real_today_e2e.py"


def _load_runner():
    spec = importlib.util.spec_from_file_location("run_real_today_e2e", RUNNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_playwright_executable_is_cross_platform():
    runner = _load_runner()

    assert runner.playwright_executable("posix").name == "playwright"
    assert runner.playwright_executable("nt").name == "playwright.cmd"
    assert runner.npm_executable("posix") == "npm"
    assert runner.npm_executable("nt") == "npm.cmd"


def test_runner_selects_vite_or_production_playwright_config():
    runner = _load_runner()

    assert runner.playwright_command(production_dist=False)[-1] == (
        "--config=playwright.real.config.ts"
    )
    assert runner.playwright_command(production_dist=True)[-1] == (
        "--config=playwright.production.config.ts"
    )
    assert runner.playwright_command(
        production_dist=True,
        spec="e2e-production/production.spec.ts",
    )[-1] == "e2e-production/production.spec.ts"


def test_real_e2e_rejects_file_database_configuration(monkeypatch):
    runner = _load_runner()
    monkeypatch.setenv("QINGSHU_TEST_POSTGRES_URL", "/tmp/qingshu_auth_test")

    try:
        runner.test_database_url()
    except RuntimeError as exc:
        assert "完整 PostgreSQL 测试库 URL" in str(exc)
    else:
        raise AssertionError("file database configuration must be rejected")


def test_market_snapshot_url_defaults_to_prod_and_forces_read_only(monkeypatch):
    runner = _load_runner()
    monkeypatch.delenv("QINGSHU_E2E_MARKET_SNAPSHOT_URL", raising=False)

    url = runner.market_snapshot_database_url(
        "postgresql://chr@localhost/qingshu_auth_test?connect_timeout=5"
    )

    parsed = urlsplit(url)
    assert parsed.path == "/qingshu_prod"
    assert parse_qs(parsed.query) == {
        "connect_timeout": ["5"],
        "options": ["-cdefault_transaction_read_only=on"],
    }


def test_market_snapshot_url_accepts_explicit_postgres_and_forces_read_only(
    monkeypatch,
):
    runner = _load_runner()
    monkeypatch.setenv(
        "QINGSHU_E2E_MARKET_SNAPSHOT_URL",
        "postgresql+psycopg://reader@db.internal/market_snapshots"
        "?sslmode=require&options=-csearch_path%3Dmarket",
    )

    url = runner.market_snapshot_database_url(
        "postgresql://chr@localhost/qingshu_auth_test"
    )

    parsed = urlsplit(url)
    assert parsed.scheme == "postgresql"
    assert parsed.netloc == "reader@db.internal"
    assert parsed.path == "/market_snapshots"
    assert parse_qs(parsed.query) == {
        "sslmode": ["require"],
        "options": [
            "-csearch_path=market -cdefault_transaction_read_only=on"
        ],
    }


def test_market_snapshot_url_rejects_non_postgres_configuration(monkeypatch):
    runner = _load_runner()
    monkeypatch.setenv(
        "QINGSHU_E2E_MARKET_SNAPSHOT_URL",
        "/tmp/market-snapshots.sqlite3",
    )

    with pytest.raises(RuntimeError, match="完整 PostgreSQL URL"):
        runner.market_snapshot_database_url(
            "postgresql://chr@localhost/qingshu_auth_test"
        )
