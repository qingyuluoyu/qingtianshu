from __future__ import annotations

from app.db import Database


class FakeRedis:
    def __init__(self) -> None:
        self.messages: list[dict[str, str]] = []

    def xadd(self, stream_name: str, fields: dict[str, str]) -> str:
        assert stream_name == "qingshu:data-refresh"
        self.messages.append(fields)
        return "1-0"

    def xgroup_create(self, *_args, **_kwargs) -> None:
        return None

    def xreadgroup(self, *_args, **_kwargs):
        if not self.messages:
            return []
        message = self.messages.pop(0)
        return [("qingshu:data-refresh", [("1-0", message)])]

    def xack(self, *_args, **_kwargs) -> int:
        return 1


def build_database(tmp_path) -> Database:
    database = Database(tmp_path / "app.db", tmp_path / "workspaces")
    database.initialize()
    return database


def test_data_refresh_task_is_idempotent_while_active(tmp_path):
    database = build_database(tmp_path)

    first, first_reused = database.create_data_refresh_task(
        kind="stock_quote",
        idempotency_key="stock-quote:300750.SZ:2026-07-25",
        payload={"symbol": "300750.SZ"},
        request_id="request-1",
        trace_id="trace-1",
    )
    second, second_reused = database.create_data_refresh_task(
        kind="stock_quote",
        idempotency_key="stock-quote:300750.SZ:2026-07-25",
        payload={"symbol": "300750.SZ"},
        request_id="request-2",
        trace_id="trace-2",
    )

    assert first_reused is False
    assert second_reused is True
    assert second["id"] == first["id"]
    assert database.pending_data_refresh_outbox_count() == 1


def test_only_one_worker_can_claim_data_refresh_task(tmp_path):
    database = build_database(tmp_path)
    task, _ = database.create_data_refresh_task(
        kind="stock_kline",
        idempotency_key="stock-kline:300750.SZ:1d:qfq:2026-07-25",
        payload={"symbol": "300750.SZ", "period": "1d", "adjust": "qfq"},
    )

    first = database.claim_data_refresh_task(task["id"], "worker-a", 60)
    second = database.claim_data_refresh_task(task["id"], "worker-b", 60)

    assert first is not None
    assert first["status"] == "leased"
    assert first["lease_owner"] == "worker-a"
    assert second is None


def test_data_refresh_queue_publishes_and_worker_completes(tmp_path):
    from app.services.data_refresh_queue import DataRefreshQueue, DataRefreshWorker

    database = build_database(tmp_path)
    task, _ = database.create_data_refresh_task(
        kind="industry_score",
        idempotency_key="industry-score:801737.SI:2025-12-31:v1",
        payload={"symbol": "300750.SZ"},
    )
    redis = FakeRedis()
    queue = DataRefreshQueue(database, redis)
    executed: list[str] = []
    worker = DataRefreshWorker(
        database,
        queue,
        redis,
        "worker-a",
        lambda claimed: executed.append(claimed["id"]),
    )

    assert worker.run_once() == 1
    assert executed == [task["id"]]
    assert database.get_data_refresh_task(task["id"])["status"] == "completed"


def test_stock_snapshot_read_returns_stale_data_and_deduplicates_refresh(tmp_path):
    from app.services.stock_snapshot_refresh import StockSnapshotRefreshService

    class Dashboard:
        def score_card(self, symbol, *, allow_remote):
            assert allow_remote is False
            return {
                "symbol": symbol,
                "cache": {"state": "stale"},
                "quote": {"price": 262.0},
            }

    service = StockSnapshotRefreshService(
        build_database(tmp_path),
        Dashboard(),
        market_provider=None,
        industry_comparison=None,
    )

    first = service.read_score_card("300750.SZ")
    second = service.read_score_card("300750.SZ")

    assert first["quote"]["price"] == 262.0
    assert first["refresh"]["status"] == "queued"
    assert second["refresh"]["taskId"] == first["refresh"]["taskId"]
