from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta

from app.operations import build_operations_report


def test_http_request_id_is_validated_propagated_and_logged_without_query_secrets(
    client, caplog
):
    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        accepted = client.get(
            "/health?api_key=must-not-reach-access-log",
            headers={"X-Request-ID": "request-ops-001"},
        )
        generated = client.get("/health", headers={"X-Request-ID": "short"})

    assert accepted.headers["X-Request-ID"] == "request-ops-001"
    assert generated.headers["X-Request-ID"] != "short"
    assert re.fullmatch(r"[0-9a-f]{32}", generated.headers["X-Request-ID"])
    assert "request_id=request-ops-001" in caplog.text
    assert "method=GET" in caplog.text
    assert "path=/health" in caplog.text
    assert "status=200" in caplog.text
    assert "must-not-reach-access-log" not in caplog.text


def test_operations_report_requires_an_active_worker_on_postgres(client):
    report = build_operations_report(
        client.app.state.database,
        client.app.state.background.job_store,
        client.app.state.settings,
        require_postgres=True,
        minimum_active_workers=1,
        check_backup=False,
    )
    assert report["status"] == "degraded"
    assert "domain_database_not_postgresql" not in report["failures"]
    assert "active_worker_count_below_minimum" in report["failures"]
    assert report["storage"]["domain_database"]["backend"] == "postgresql"
    assert report["storage"]["operational_database"]["backend"] == "postgresql"


def test_operations_report_passes_with_registered_worker_in_local_mode(client):
    store = client.app.state.background.job_store
    store.register_worker(
        "operations-probe",
        queue_name="background",
        metadata={"source": "test"},
    )
    report = build_operations_report(
        client.app.state.database,
        store,
        client.app.state.settings,
        minimum_active_workers=1,
    )
    assert report["status"] == "ok"
    assert report["failures"] == []
    assert report["backups"]["status"] == "ok"
    assert report["workers"][0]["worker_id"] == "operations-probe"


def _operations_report_with_data_health(client, snapshot=None):
    if snapshot is not None:
        client.app.state.database.save_data_health_snapshot(snapshot)
    return build_operations_report(
        client.app.state.database,
        client.app.state.background.job_store,
        client.app.state.settings,
        minimum_active_workers=0,
        check_backup=False,
        check_data_health=True,
        max_data_health_age_seconds=300,
    )


def test_operations_report_fails_when_data_health_snapshot_is_missing(client):
    report = _operations_report_with_data_health(client)

    assert report["status"] == "degraded"
    assert "data_health_snapshot_missing" in report["failures"]
    assert report["data_health"] == {
        "status": "missing",
        "snapshot_status": None,
        "created_at": None,
        "age_seconds": None,
    }


def test_operations_report_fails_on_stale_or_degraded_data_health(client):
    stale = _operations_report_with_data_health(
        client,
        {
            "status": "healthy",
            "created_at": (
                datetime.now(UTC) - timedelta(seconds=301)
            ).isoformat(),
            "summary": {"total": 1, "healthy": 1},
            "checks": [{"private": "must-not-leak"}],
        },
    )
    assert "data_health_snapshot_stale" in stale["failures"]
    assert "checks" not in stale["data_health"]

    degraded = _operations_report_with_data_health(
        client,
        {
            "status": "degraded",
            "created_at": datetime.now(UTC).isoformat(),
            "summary": {"critical": 1},
            "checks": [{"private": "must-not-leak"}],
        },
    )
    assert "data_health_degraded" in degraded["failures"]
    assert "checks" not in degraded["data_health"]


def test_operations_report_warns_on_attention_and_passes_fresh_health(client):
    attention = _operations_report_with_data_health(
        client,
        {
            "status": "attention",
            "created_at": datetime.now(UTC).isoformat(),
            "summary": {"attention": 1},
        },
    )
    assert attention["status"] == "ok"
    assert "data_health_attention" in attention["warnings"]
    assert attention["data_health"]["status"] == "attention"

    healthy = _operations_report_with_data_health(
        client,
        {
            "status": "healthy",
            "created_at": datetime.now(UTC).isoformat(),
            "summary": {"healthy": 1},
        },
    )
    assert healthy["status"] == "ok"
    assert healthy["failures"] == []
    assert healthy["data_health"]["status"] == "ok"
    assert healthy["thresholds"]["data_health_checked"] is True
    assert healthy["thresholds"]["max_data_health_age_seconds"] == 300


def test_readiness_distinguishes_live_web_from_missing_required_worker(client):
    assert client.get("/health").status_code == 200
    assert client.get("/ready").status_code == 200
    settings = client.app.state.settings
    object.__setattr__(settings, "background_jobs_enabled", True)
    object.__setattr__(settings, "background_worker_mode", "external")
    try:
        response = client.get("/ready")
        assert response.status_code == 503
        assert "active_worker_count_below_minimum" in response.json()["failures"]
        assert client.get("/health").status_code == 200
    finally:
        object.__setattr__(settings, "background_jobs_enabled", False)
        object.__setattr__(settings, "background_worker_mode", "disabled")
