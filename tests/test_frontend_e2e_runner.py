from __future__ import annotations

import importlib.util
from pathlib import Path


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


def test_real_e2e_rejects_file_database_configuration(monkeypatch):
    runner = _load_runner()
    monkeypatch.setenv("QINGSHU_TEST_POSTGRES_URL", "/tmp/qingshu_auth_test")

    try:
        runner.test_database_url()
    except RuntimeError as exc:
        assert "完整 PostgreSQL 测试库 URL" in str(exc)
    else:
        raise AssertionError("file database configuration must be rejected")
