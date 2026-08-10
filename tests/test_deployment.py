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
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    staging = (PROJECT_ROOT / "staging.env.example").read_text(encoding="utf-8")
    assert "postgresql-client-17" in dockerfile
    assert "ARG HERMES_COMMIT=" in dockerfile
    assert "COPY --from=hermes-runtime /opt/hermes /opt/hermes" in dockerfile
    assert "COPY --from=hermes-runtime /opt/hermes-agent /opt/hermes-agent" in dockerfile
    assert "--editable /opt/hermes-agent" in dockerfile
    assert 'HERMES_ENABLED: "${HERMES_ENABLED:-true}"' in compose
    assert 'HERMES_ECONOMY_MODEL: "${HERMES_ECONOMY_MODEL:-step-3.7-flash}"' in compose
    assert 'HERMES_DEEP_MODEL: "${HERMES_DEEP_MODEL:-step-3.7-flash}"' in compose
    assert 'STEPFUN_API_KEY: "${STEPFUN_API_KEY:-}"' in compose
    assert (
        'QINGSHU_DEPLOYMENT_ENV: "${QINGSHU_DEPLOYMENT_ENV:-production}"'
        in compose
    )
    assert 'SESSION_COOKIE_SECURE: "${SESSION_COOKIE_SECURE:-true}"' in compose
    assert "HERMES_BIN: /opt/hermes/bin/hermes" in compose
    assert "HERMES_PYTHON_BIN: /opt/hermes/bin/python" in compose
    assert "COMPOSE_PROJECT_NAME=qingshu-staging" in staging
    assert "QINGSHU_DEPLOYMENT_ENV=staging" in staging
    assert "QINGSHU_HTTP_BIND=127.0.0.1" in staging
    assert "QINGSHU_HTTP_PORT=18000" in staging
    assert "SESSION_COOKIE_SECURE=true" in staging
    assert "SEC_USER_AGENT=" in staging
    assert "HERMES_ENABLED=false" in staging
    assert "TUSHARE_ENABLED=false" in staging
    assert "COPY pyproject.toml uv.lock ./" in dockerfile
    assert "uv sync --frozen --no-dev" in dockerfile
    assert '"--no-access-log"' in dockerfile
    cli = (PROJECT_ROOT / "app" / "cli.py").read_text(encoding="utf-8")
    assert "access_log=False" in cli
