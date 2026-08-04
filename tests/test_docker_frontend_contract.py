from __future__ import annotations

from pathlib import Path

import pytest

from scripts.export_openapi import require_test_database_url


ROOT = Path(__file__).resolve().parents[1]


def test_dockerfile_builds_and_copies_locked_react_bundle():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "FROM node:22-bookworm-slim AS frontend-build" in dockerfile
    assert "COPY frontend/package.json frontend/package-lock.json ./" in dockerfile
    assert "RUN npm ci" in dockerfile
    assert "RUN npm run generate:api:file && npm run build" in dockerfile
    assert "COPY --from=frontend-build /frontend/dist /app/frontend/dist" in dockerfile
    assert "QINGSHU_FRONTEND_DIST_DIR=/app/frontend/dist" in dockerfile
    assert "frontend/node_modules" not in dockerfile


def test_docker_context_excludes_local_frontend_outputs():
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()

    assert "frontend/node_modules" in dockerignore
    assert "frontend/dist" in dockerignore
    assert "frontend/test-results" in dockerignore
    assert "frontend/playwright-report" in dockerignore


def test_compose_disables_legacy_anonymous_mode_by_default():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert (
        'QINGSHU_LEGACY_ANONYMOUS_MODE: "${QINGSHU_LEGACY_ANONYMOUS_MODE:-false}"'
        in compose
    )


def test_compose_requires_secure_session_cookie_by_default():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert 'SESSION_COOKIE_SECURE: "${SESSION_COOKIE_SECURE:-true}"' in compose


def test_compose_pins_linux_frontend_path_without_host_interpolation():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "QINGSHU_FRONTEND_DIST_DIR: /app/frontend/dist" in compose
    assert "${QINGSHU_FRONTEND_DIST_DIR" not in compose


def test_openapi_export_refuses_non_test_database():
    with pytest.raises(RuntimeError, match="qingshu_auth_test"):
        require_test_database_url("postgresql://user:secret@example.invalid/qingshu")

    accepted = require_test_database_url(
        "postgresql://user:secret@example.invalid/qingshu_auth_test"
    )
    assert accepted.endswith("/qingshu_auth_test")
