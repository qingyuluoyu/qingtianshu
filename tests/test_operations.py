from __future__ import annotations

from app.operations import build_operations_report


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
