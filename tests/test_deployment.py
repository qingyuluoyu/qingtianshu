from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_compose_declares_separate_web_worker_backup_and_postgres_services():
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    for service in (
        "  postgres:",
        "  qingshu-agent:",
        "  qingshu-worker:",
        "  qingshu-backup:",
    ):
        assert service in compose
    assert "scripts/check_operations.py" in compose
    assert "scripts/postgres_backup.py" in compose
    assert "http://127.0.0.1:8000/ready" in compose
    assert "qingshu-backups:/backups" in compose
    assert "${QINGSHU_HTTP_BIND:-0.0.0.0}" in compose
    assert "${QINGSHU_HTTP_PORT:-8000}" in compose


def test_deployment_uses_matching_postgres_17_client_and_isolated_staging():
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")
    staging = (PROJECT_ROOT / "staging.env.example").read_text(encoding="utf-8")
    assert "postgresql-client-17" in dockerfile
    assert "COMPOSE_PROJECT_NAME=qingshu-staging" in staging
    assert "QINGSHU_HTTP_BIND=127.0.0.1" in staging
    assert "QINGSHU_HTTP_PORT=18000" in staging
    assert "HERMES_ENABLED=false" in staging
    assert "TUSHARE_ENABLED=false" in staging
