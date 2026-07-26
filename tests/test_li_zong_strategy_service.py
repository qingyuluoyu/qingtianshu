from __future__ import annotations

from collections import Counter
from copy import deepcopy
import json
import threading
import time

import pandas as pd

from app.services.li_zong_strategy_service import LiZongStrategyService
from app.services.strategies.li_zong import LiZongParameters


AS_OF = "2026-07-21"


class SnapshotStub:
    def __init__(self, packets: dict[str, dict]):
        self.packets = packets
        self.calls: Counter[str] = Counter()

    def get_symbol_snapshot(self, symbol: str) -> dict:
        self.calls[symbol] += 1
        return deepcopy(self.packets[symbol])


class UniverseSnapshotStub(SnapshotStub):
    def __init__(
        self,
        packets: dict[str, dict],
        items: list[dict],
        *,
        as_of_date: str = AS_OF,
        status: str = "stable",
        data_version: str = "universe-v1",
    ):
        super().__init__(packets)
        self.items = items
        self.as_of_date = as_of_date
        self.status = status
        self.data_version = data_version
        self.universe_sync_calls = 0
        self.symbol_sync_calls: list[str] = []
        self.strategy_sync_items: list[dict] = []
        self.failed_symbols: set[str] = set()

    def sync_a_share_universe(self, *, as_of_date: str | None = None) -> dict:
        self.universe_sync_calls += 1
        if as_of_date:
            self.as_of_date = as_of_date
        return {
            "run": {"status": self.status, "data_version": self.data_version},
            "snapshot": self._snapshot(),
            "published": self.status == "stable",
            "previous_stable_retained": False,
        }

    def get_a_share_universe(self) -> dict:
        return {
            "status": self.status,
            "data_version": self.data_version,
            "snapshot": self._snapshot(),
        }

    def sync_symbol(self, symbol: str, *, as_of_date: str | None = None) -> dict:
        self.symbol_sync_calls.append(symbol)
        if symbol in self.failed_symbols:
            raise RuntimeError("temporary symbol sync failure")
        return {
            "run": {"status": "stable"},
            "published": True,
            "previous_stable_retained": False,
        }

    def sync_strategy_symbol(
        self,
        symbol: str,
        *,
        as_of_date: str | None = None,
        universe_item: dict | None = None,
    ) -> dict:
        self.strategy_sync_items.append(deepcopy(universe_item or {}))
        return self.sync_symbol(symbol, as_of_date=as_of_date)

    def _snapshot(self) -> dict:
        with_market_cap = sum(
            item.get("total_mv_yi") is not None for item in self.items
        )
        return {
            "as_of_date": self.as_of_date,
            "items": deepcopy(self.items),
            "coverage": {
                "listed": len(self.items),
                "with_market_cap": with_market_cap,
                "missing_market_cap": len(self.items) - with_market_cap,
                "market_cap_coverage_ratio": (
                    with_market_cap / len(self.items) if self.items else 0.0
                ),
            },
        }


class ConcurrentUniverseSnapshotStub(UniverseSnapshotStub):
    def __init__(self, packets: dict[str, dict], items: list[dict]):
        super().__init__(packets, items)
        self._active_lock = threading.Lock()
        self.active_syncs = 0
        self.max_active_syncs = 0

    def sync_strategy_symbol(
        self,
        symbol: str,
        *,
        as_of_date: str | None = None,
        universe_item: dict | None = None,
    ) -> dict:
        with self._active_lock:
            self.active_syncs += 1
            self.max_active_syncs = max(self.max_active_syncs, self.active_syncs)
        try:
            time.sleep(0.03)
            return super().sync_strategy_symbol(
                symbol,
                as_of_date=as_of_date,
                universe_item=universe_item,
            )
        finally:
            with self._active_lock:
                self.active_syncs -= 1


def _snapshot_packet(
    symbol: str = "000063.SZ",
    *,
    data_version: str = "stable-v1",
    triggered: bool = False,
    market_cap_yi: float = 180.0,
    stock_name: str = "中兴通讯",
    industry: str = "通信设备",
    market: str = "主板",
    list_date: str = "19971118",
) -> dict:
    dates = pd.bdate_range(end=AS_OF, periods=400)
    limit_indices = {-200, -199, -150, -100, -50, -5}
    daily = []
    adj_factor = []
    stk_limit = []
    for position, trade_date in enumerate(dates):
        relative = position - len(dates)
        date_text = trade_date.strftime("%Y%m%d")
        pre_close = 100.0 + position * 0.01
        close = pre_close + 0.3
        up_limit = pre_close + 10.0
        if relative in limit_indices:
            close = up_limit
        open_price = close - 0.2
        high = close + 0.5
        low = close - 0.5
        if relative == -1 and triggered:
            close = up_limit
            open_price = close
            high = close
            low = close - 0.5
        daily.append(
            {
                "ts_code": symbol,
                "trade_date": date_text,
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "pre_close": pre_close,
                "pct_chg": (close / pre_close - 1.0) * 100.0,
                "vol": 100.0,
            }
        )
        adj_factor.append(
            {
                "ts_code": symbol,
                "trade_date": date_text,
                "adj_factor": 1.0 + position * 0.001,
            }
        )
        stk_limit.append(
            {
                "ts_code": symbol,
                "trade_date": date_text,
                "up_limit": up_limit,
                "down_limit": pre_close - 10.0,
            }
        )
    for relative in (-30, -29, -28):
        daily[relative]["vol"] = 200.0

    datasets = {
        "trade_cal": _dataset(
            "trade_cal", [{"cal_date": row.strftime("%Y%m%d")} for row in dates]
        ),
        "stock_basic": _dataset(
            "stock_basic",
            [
                {
                    "ts_code": symbol,
                    "name": stock_name,
                    "industry": industry,
                    "market": market,
                    "list_date": list_date,
                }
            ],
        ),
        "daily": _dataset("daily", daily),
        "daily_basic": _dataset(
            "daily_basic",
            [
                {
                    "ts_code": symbol,
                    "trade_date": "20260721",
                    "total_mv": market_cap_yi * 10_000.0,
                }
            ],
        ),
        "fina_indicator": _dataset(
            "fina_indicator",
            [
                {
                    "ts_code": symbol,
                    "ann_date": f"{year + 1}0429",
                    "end_date": f"{year}1231",
                    "roe": 10.0 + (year - 2021),
                }
                for year in range(2021, 2026)
            ],
        ),
        "adj_factor": _dataset("adj_factor", adj_factor),
        "stk_limit": _dataset("stk_limit", stk_limit),
        "top10_holders": _dataset(
            "top10_holders",
            [
                {
                    "ts_code": symbol,
                    "ann_date": "20260429",
                    "end_date": "20260331",
                    "holder_name": name,
                }
                for name in ("甲公司", "乙基金", "丙保险", "丁银行")
            ],
        ),
        "top10_floatholders": _dataset(
            "top10_floatholders",
            [
                {
                    "ts_code": symbol,
                    "ann_date": "20260429",
                    "end_date": "20260331",
                    "holder_name": name,
                }
                for name in ("甲 公司", "戊资管计划", "张三")
            ],
        ),
    }
    return {
        "symbol": symbol,
        "status": "stable",
        "data_version": data_version,
        "snapshot": {
            "symbol": symbol,
            "as_of_date": AS_OF,
            "data_status": "stable",
            "datasets": datasets,
            "coverage": {"required": 9, "available": 9, "missing": []},
        },
    }


def _dataset(name: str, rows: list[dict]) -> dict:
    return {
        "dataset": name,
        "source": "Tushare Pro",
        "rows": rows,
        "row_count": len(rows),
    }


def _with_transient_issue(
    packet: dict,
    *,
    dataset: str = "daily",
    generated_at: str = "2026-07-21T10:00:00+00:00",
) -> dict:
    value = deepcopy(packet)
    value["status"] = "incomplete"
    value["snapshot"]["generated_at"] = generated_at
    value["snapshot"]["data_status"] = "incomplete"
    value["snapshot"]["coverage"]["available"] = 8
    value["snapshot"]["coverage"]["missing"] = [dataset]
    value["snapshot"]["datasets"][dataset] = _dataset(dataset, [])
    value["snapshot"]["issues"] = [
        {"dataset": dataset, "error_type": "TushareProviderError"}
    ]
    return value


def _table_count(database, table: str) -> int:
    with database.connect() as connection:
        return int(
            connection.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()[
                "count"
            ]
        )


def test_service_bootstraps_all_strategy_tables_and_versioned_definition(app):
    service = LiZongStrategyService(
        app.state.database,
        SnapshotStub({"000063.SZ": _snapshot_packet()}),
    )

    with app.state.database.connect() as connection:
        tables = {
            row["table_name"]
            for row in connection.execute(
                """
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = current_schema()
                """
            ).fetchall()
        }
    assert {
        "strategy_definitions",
        "strategy_versions",
        "strategy_parameter_versions",
        "strategy_screen_runs",
        "strategy_candidate_snapshots",
        "strategy_rule_results",
        "strategy_trigger_events",
    } <= tables

    definition = service.get_definition()
    assert definition["strategy_id"] == "li_zong"
    assert definition["current_version"] == "li_zong_v1"
    assert definition["version"]["method"] == "deterministic_li_zong_v1"
    assert len(definition["version"]["rules"]) == 12
    assert definition["default_parameter_version"]["parameters"]["roe_min_pct"] == 10.0
    assert definition["subscriptions_enabled"] is False
    assert "暂未" in definition["subscription_boundary"]
    assert service.list_strategies()[0]["name"] == "李总策略"


def test_process_restart_repairs_stale_background_and_strategy_runs(app):
    database = app.state.database
    database.start_background_job("stale-background-job")
    tushare_run = database.start_tushare_sync_run(
        job_scope="symbol:000063.SZ",
        as_of_date=AS_OF,
        datasets=["daily_basic"],
    )
    strategy_run = database.start_strategy_screen_run(
        strategy_id="li_zong",
        strategy_version="li_zong_v1",
        parameter_version="li_zong_v1_default",
        data_version="stale-run-v1",
        data_versions={},
        as_of_date=AS_OF,
        requested_count=1,
    )

    repaired = database.repair_interrupted_background_runs()

    assert repaired == {
        "background_job_runs": 1,
        "tushare_sync_runs": 1,
        "strategy_screen_runs": 1,
    }
    assert database.latest_background_jobs()[0]["status"] == "failed"
    assert database.get_tushare_sync_run(tushare_run["id"])["status"] == "failed"
    assert database.get_strategy_screen_run(strategy_run["id"])["status"] == "failed"
    assert database.repair_interrupted_background_runs() == {
        "background_job_runs": 0,
        "tushare_sync_runs": 0,
        "strategy_screen_runs": 0,
    }


def test_snapshot_datasets_are_merged_with_adjustment_limit_and_holder_sources(app):
    packet = _snapshot_packet()
    service = LiZongStrategyService(
        app.state.database, SnapshotStub({"000063.SZ": packet})
    )

    inputs = service._build_input("000063.SZ", packet)

    daily = inputs["daily"]
    assert {"adj_factor", "up_limit", "down_limit"} <= set(daily.columns)
    assert daily.iloc[-1]["source"] == (
        "Tushare Pro:daily+Tushare Pro:adj_factor+Tushare Pro:stk_limit"
    )
    holders = inputs["shareholders"]
    assert set(holders["source"]) == {
        "Tushare Pro:top10_holders+Tushare Pro:top10_floatholders"
    }
    assert len(holders[holders["holder_type"] == "institution"]) == 6
    assert holders.loc[holders["holder_name"] == "张三", "holder_type"].iloc[0] == (
        "unknown"
    )


def test_run_persists_candidate_rules_and_one_non_duplicate_trigger(app):
    packet = _snapshot_packet(triggered=True)
    snapshots = SnapshotStub({"000063.SZ": packet})
    service = LiZongStrategyService(app.state.database, snapshots)

    first = service.run_symbols(["000063", "000063.SZ"])
    second = service.run_symbols(["000063.SZ"])

    assert first["run"]["status"] == "completed"
    assert first["run"]["requested_count"] == 1
    assert first["items"][0]["status"] == "triggered"
    assert first["items"][0]["idempotent_reused"] is False
    assert len(first["items"][0]["rule_results"]) == 12
    assert first["items"][0]["result"]["stock_basic"] == {
        "name": "中兴通讯",
        "industry": "通信设备",
        "market": "主板",
        "list_date": "1997-11-18",
    }
    assert first["items"][0]["new_trigger_event_ids"]
    assert second["items"][0]["id"] == first["items"][0]["id"]
    assert second["items"][0]["idempotent_reused"] is True
    assert second["items"][0]["new_trigger_event_ids"] == []
    assert snapshots.calls["000063.SZ"] == 2

    database = app.state.database
    assert _table_count(database, "strategy_screen_runs") == 2
    assert _table_count(database, "strategy_candidate_snapshots") == 1
    assert _table_count(database, "strategy_rule_results") == 12
    assert _table_count(database, "strategy_trigger_events") == 1

    candidate = service.get_candidate("000063")
    assert candidate is not None
    assert len(candidate["rule_results"]) == 12
    assert len(candidate["trigger_events"]) == 1
    assert service.list_candidates(status="triggered")[0]["symbol"] == "000063.SZ"
    assert service.get_triggers()[0]["rule_id"] == "LZ-T-01"


def test_new_failed_data_version_invalidates_previous_qualified_snapshot(app):
    packets = {"000063.SZ": _snapshot_packet(data_version="stable-v1")}
    snapshots = SnapshotStub(packets)
    service = LiZongStrategyService(app.state.database, snapshots)
    first = service.run_symbols(["000063"])
    assert first["items"][0]["status"] == "qualified"

    packets["000063.SZ"] = _snapshot_packet(
        data_version="stable-v2", market_cap_yi=100.0
    )
    second = service.run_symbols(["000063"])

    item = second["items"][0]
    assert item["status"] == "invalidated"
    assert item["evaluation_status"] == "not_qualified"
    assert item["previous_status"] == "qualified"
    assert item["invalidated_at"]
    assert second["counts"]["invalidated"] == 1
    assert service.list_candidates(status="qualified") == []
    assert service.list_candidates(status="invalidated")[0]["id"] == item["id"]
    assert service.get_candidate("000063")["status"] == "invalidated"


def test_observation_pool_derives_8_of_9_and_6_to_7_without_relaxing_candidates(
    app,
):
    near_packet = _snapshot_packet(
        symbol="000063.SZ",
        data_version="near-8-v1",
        market_cap_yi=100.0,
    )
    watch_packet = _snapshot_packet(
        symbol="000001.SZ",
        data_version="watch-7-v1",
        market_cap_yi=100.0,
        stock_name="平安银行",
        industry="银行",
    )
    watch_packet["snapshot"]["datasets"]["fina_indicator"]["rows"][0]["roe"] = 5.0
    incomplete_packet = _with_transient_issue(
        _snapshot_packet(
            symbol="300308.SZ",
            data_version="incomplete-near-v1",
            market_cap_yi=100.0,
            stock_name="中际旭创",
            industry="通信设备",
        ),
        dataset="fina_indicator",
    )
    service = LiZongStrategyService(
        app.state.database,
        SnapshotStub(
            {
                "000063.SZ": near_packet,
                "000001.SZ": watch_packet,
                "300308.SZ": incomplete_packet,
            }
        ),
    )

    service.run_symbols(["000063.SZ", "000001.SZ", "300308.SZ"])
    packet = service.observation_pool_packet()

    assert service.list_actionable_candidates() == []
    assert packet["counts"] == {
        "near_8_of_9": 1,
        "watch_6_7_of_9": 1,
    }
    assert [item["symbol"] for item in packet["items"]] == [
        "000063.SZ",
        "000001.SZ",
    ]
    near, watch = packet["items"]
    assert near["candidate_rule_pass_count"] == 8
    assert near["failed_candidate_rule_ids"] == ["LZ-F-01"]
    assert watch["candidate_rule_pass_count"] == 7
    assert watch["failed_candidate_rule_ids"] == ["LZ-F-01", "LZ-F-02"]
    assert "不是候选" in packet["boundary"]
    assert "300308.SZ" not in {item["symbol"] for item in packet["items"]}


def test_missing_dataset_is_always_data_incomplete_even_with_known_failed_rule(app):
    packet = _snapshot_packet(market_cap_yi=100.0, data_version="partial-v1")
    packet["status"] = "incomplete"
    packet["snapshot"]["data_status"] = "incomplete"
    packet["snapshot"]["coverage"] = {
        "required": 9,
        "available": 8,
        "missing": ["fina_indicator"],
    }
    packet["snapshot"]["datasets"]["fina_indicator"] = _dataset("fina_indicator", [])
    service = LiZongStrategyService(
        app.state.database, SnapshotStub({"000063.SZ": packet})
    )

    result = service.run_symbols(["000063"])
    item = result["items"][0]

    assert item["status"] == "data_incomplete"
    assert item["evaluation_status"] == "data_incomplete"
    assert item["result"]["candidate_qualified"] is False
    assert item["result"]["triggered_rule_ids"] == []
    assert result["counts"]["data_incomplete"] == 1
    assert _table_count(app.state.database, "strategy_trigger_events") == 0


def test_custom_parameter_version_is_immutable_and_separate_from_default(app):
    service = LiZongStrategyService(
        app.state.database,
        SnapshotStub({"000063.SZ": _snapshot_packet()}),
    )

    default = service.run_symbols(["000063"])
    custom = service.run_symbols(
        ["000063"],
        parameters={
            "parameter_version": "li_zong_v1_roe_12",
            "roe_min_pct": 12.0,
        },
    )

    assert default["items"][0]["parameter_version"] == "li_zong_v1_default"
    assert custom["items"][0]["parameter_version"] == "li_zong_v1_roe_12"
    stored = app.state.database.get_strategy_parameter_version(
        "li_zong", "li_zong_v1", "li_zong_v1_roe_12"
    )
    assert stored["parameters"]["roe_min_pct"] == 12.0
    assert _table_count(app.state.database, "strategy_candidate_snapshots") == 2

    try:
        service.run_symbols(
            ["000063"],
            parameters={
                "parameter_version": "li_zong_v1_roe_12",
                "roe_min_pct": 11.0,
            },
        )
    except ValueError as exc:
        assert "不能覆盖历史口径" in str(exc)
    else:
        raise AssertionError("a parameter version must be immutable")


def test_non_a_share_and_empty_runs_are_rejected(app):
    service = LiZongStrategyService(app.state.database, SnapshotStub({}))

    for values in ([], ["NVDA"]):
        try:
            service.run_symbols(values)
        except ValueError as exc:
            assert str(exc)
        else:
            raise AssertionError("invalid symbol list should be rejected")


def test_universe_batch_prefilters_limits_deep_sync_and_is_idempotent(app):
    items = [
        {
            "symbol": "000001.SZ",
            "name": "平安银行",
            "industry": "银行",
            "market": "主板",
            "total_mv_yi": 150.0,
        },
        {
            "symbol": "000063.SZ",
            "name": "中兴通讯",
            "industry": "通信设备",
            "market": "主板",
            "total_mv_yi": 220.0,
        },
        {
            "symbol": "300308.SZ",
            "name": "中际旭创",
            "industry": "通信设备",
            "market": "创业板",
            "total_mv_yi": 180.0,
        },
        {
            "symbol": "830799.BJ",
            "name": "艾融软件",
            "industry": "软件服务",
            "market": "北交所",
            "total_mv_yi": None,
        },
    ]
    snapshots = UniverseSnapshotStub(
        {
            "600519.SS": _snapshot_packet(
                symbol="600519.SS",
                market_cap_yi=2000.0,
                stock_name="贵州茅台",
                industry="白酒",
            ),
            "000063.SZ": _snapshot_packet(symbol="000063.SZ", market_cap_yi=220.0),
            "300308.SZ": _snapshot_packet(
                symbol="300308.SZ",
                market_cap_yi=180.0,
                stock_name="中际旭创",
                market="创业板",
            ),
        },
        items,
    )
    service = LiZongStrategyService(app.state.database, snapshots)
    service.run_symbols(["600519"])

    first = service.run_universe_batch(batch_size=1)
    second = service.run_universe_batch(batch_size=1)
    third = service.run_universe_batch(batch_size=1)

    assert first["selected_symbols"] == ["000063.SZ"]
    assert first["coverage"]["evaluated_symbols"] == 3
    assert first["coverage"]["coverage_ratio"] == 0.75
    assert first["coverage"]["full_market_coverage"] is False
    assert first["coverage"]["counts"]["total"] == 3
    assert service.get_candidate("000001")["status"] == "not_qualified"
    assert service.get_candidate("830799.BJ")["status"] == "data_incomplete"
    assert second["selected_symbols"] == ["300308.SZ"]
    assert second["coverage"]["full_market_coverage"] is True
    assert second["coverage"]["coverage_ratio"] == 1.0
    assert second["coverage"]["counts"]["total"] == 4
    assert third["status"] == "completed"
    assert third["selected_symbols"] == []
    assert snapshots.symbol_sync_calls == ["000063.SZ", "300308.SZ"]
    assert snapshots.calls["000001.SZ"] == 0
    assert snapshots.calls["830799.BJ"] == 0
    assert _table_count(app.state.database, "strategy_candidate_snapshots") == 5


def test_universe_batch_skips_recent_listing_and_reports_real_deep_progress(app):
    items = [
        {
            "symbol": "301626.SZ",
            "name": "近期上市大市值样本",
            "industry": "测试行业",
            "market": "创业板",
            "list_date": "20250701",
            "total_mv_yi": 5_000.0,
        },
        {
            "symbol": "000063.SZ",
            "name": "中兴通讯",
            "industry": "通信设备",
            "market": "主板",
            "list_date": "19971118",
            "total_mv_yi": 220.0,
        },
    ]
    snapshots = UniverseSnapshotStub(
        {"000063.SZ": _snapshot_packet(symbol="000063.SZ")}, items
    )
    service = LiZongStrategyService(app.state.database, snapshots)

    result = service.run_universe_batch(batch_size=1)

    assert result["selected_symbols"] == ["000063.SZ"]
    assert snapshots.symbol_sync_calls == ["000063.SZ"]
    assert snapshots.calls["301626.SZ"] == 0
    recent = service.get_candidate("301626.SZ")
    assert recent["status"] == "data_incomplete"
    assert recent["result"]["evaluation_depth"] == "history_precheck"
    assert recent["result"]["history_precheck"]["status"] == "insufficient"
    assert "上市后量价历史预判未达到" in " ".join(recent["result"]["limitations"])
    coverage = result["coverage"]
    assert coverage["universe_count"] == 2
    assert coverage["history_insufficient_count"] == 1
    assert coverage["deep_check_eligible_count"] == 1
    assert coverage["deep_processed_symbols"] == 1
    assert coverage["deep_remaining_symbols"] == 0
    assert coverage["deep_check_complete"] is True


def test_universe_batch_uses_two_bounded_workers_for_deep_sync(app):
    items = [
        {
            "symbol": "000063.SZ",
            "name": "中兴通讯",
            "industry": "通信设备",
            "market": "主板",
            "list_date": "19971118",
            "total_mv_yi": 220.0,
        },
        {
            "symbol": "300308.SZ",
            "name": "中际旭创",
            "industry": "通信设备",
            "market": "创业板",
            "list_date": "20120410",
            "total_mv_yi": 180.0,
        },
    ]
    snapshots = ConcurrentUniverseSnapshotStub(
        {
            "000063.SZ": _snapshot_packet(symbol="000063.SZ"),
            "300308.SZ": _snapshot_packet(
                symbol="300308.SZ", stock_name="中际旭创", market="创业板"
            ),
        },
        items,
    )
    service = LiZongStrategyService(app.state.database, snapshots)

    result = service.run_universe_batch(batch_size=2)

    assert result["selected_symbols"] == ["000063.SZ", "300308.SZ"]
    assert snapshots.max_active_syncs == 2
    assert set(snapshots.symbol_sync_calls) == {"000063.SZ", "300308.SZ"}
    assert [item["symbol"] for item in result["sync_results"]] == [
        "000063.SZ",
        "300308.SZ",
    ]


def test_transient_sync_issue_retries_three_times_without_false_completion(app):
    item = {
        "symbol": "000063.SZ",
        "name": "中兴通讯",
        "industry": "通信设备",
        "market": "主板",
        "list_date": "19971118",
        "total_mv_yi": 220.0,
    }
    snapshots = UniverseSnapshotStub(
        {"000063.SZ": _with_transient_issue(_snapshot_packet(symbol="000063.SZ"))},
        [item],
    )
    service = LiZongStrategyService(app.state.database, snapshots)

    attempts = [service.run_universe_batch(batch_size=1) for _ in range(4)]

    assert [result["selected_symbols"] for result in attempts] == [
        ["000063.SZ"],
        ["000063.SZ"],
        ["000063.SZ"],
        [],
    ]
    candidate = service.get_candidate("000063.SZ")
    assert candidate["status"] == "data_incomplete"
    assert candidate["result"]["evaluation_depth"] == "sync_incomplete"
    assert candidate["result"]["sync_retry_count"] == 3
    assert candidate["result"]["sync_retry_exhausted"] is True
    assert "本交易日停止自动重试" in " ".join(candidate["result"]["limitations"])
    coverage = attempts[-1]["coverage"]
    assert coverage["deep_processed_symbols"] == 0
    assert coverage["deep_remaining_symbols"] == 1
    assert coverage["deep_check_complete"] is False
    assert snapshots.symbol_sync_calls == ["000063.SZ"] * 3
    assert _table_count(app.state.database, "strategy_candidate_snapshots") == 3

    snapshots.as_of_date = "2026-07-22"
    snapshots.packets["000063.SZ"]["snapshot"]["as_of_date"] = "2026-07-22"
    snapshots.packets["000063.SZ"]["snapshot"]["generated_at"] = (
        "2026-07-22T10:00:00+00:00"
    )
    next_day = service.run_universe_batch(batch_size=1, as_of_date="2026-07-22")

    assert next_day["selected_symbols"] == ["000063.SZ"]
    candidate = service.get_candidate("000063.SZ")
    assert candidate["as_of_date"] == "2026-07-22"
    assert candidate["result"]["sync_retry_count"] == 1
    assert candidate["result"]["sync_retry_exhausted"] is False


def test_real_empty_dataset_does_not_trigger_transient_retry_loop(app):
    item = {
        "symbol": "000063.SZ",
        "name": "中兴通讯",
        "industry": "通信设备",
        "market": "主板",
        "list_date": "19971118",
        "total_mv_yi": 220.0,
    }
    packet = _with_transient_issue(_snapshot_packet(symbol="000063.SZ"))
    packet["snapshot"]["issues"] = []
    snapshots = UniverseSnapshotStub({"000063.SZ": packet}, [item])
    service = LiZongStrategyService(app.state.database, snapshots)

    first = service.run_universe_batch(batch_size=1)
    second = service.run_universe_batch(batch_size=1)

    assert first["selected_symbols"] == ["000063.SZ"]
    assert second["selected_symbols"] == []
    candidate = service.get_candidate("000063.SZ")
    assert candidate["status"] == "data_incomplete"
    assert candidate["result"]["evaluation_depth"] == "full_rules"
    assert candidate["result"]["sync_retry_count"] == 0
    assert snapshots.symbol_sync_calls == ["000063.SZ"]


def test_legacy_full_rules_incomplete_requeues_when_transient_issue_appears(app):
    item = {
        "symbol": "000063.SZ",
        "name": "中兴通讯",
        "industry": "通信设备",
        "market": "主板",
        "list_date": "19971118",
        "total_mv_yi": 220.0,
    }
    packet = _with_transient_issue(_snapshot_packet(symbol="000063.SZ"))
    packet["snapshot"]["issues"] = []
    snapshots = UniverseSnapshotStub({"000063.SZ": packet}, [item])
    service = LiZongStrategyService(app.state.database, snapshots)
    first = service.run_universe_batch(batch_size=1)
    assert first["selected_symbols"] == ["000063.SZ"]
    assert (
        service.get_candidate("000063.SZ")["result"]["evaluation_depth"] == "full_rules"
    )

    snapshots.packets["000063.SZ"]["snapshot"]["issues"] = [
        {"dataset": "daily", "error_type": "TushareProviderError"}
    ]
    retried = service.run_universe_batch(batch_size=1)

    assert retried["selected_symbols"] == ["000063.SZ"]
    candidate = service.get_candidate("000063.SZ")
    assert candidate["result"]["evaluation_depth"] == "sync_incomplete"
    assert candidate["result"]["sync_retry_count"] == 1


def test_newer_incomplete_snapshot_overrides_retained_stable_for_retry_state(app):
    stable = _snapshot_packet(symbol="000063.SZ")
    stable["snapshot"]["generated_at"] = "2026-07-21T09:00:00+00:00"
    incomplete = _with_transient_issue(
        _snapshot_packet(symbol="000063.SZ", data_version="incomplete-v1"),
        generated_at="2026-07-21T10:00:00+00:00",
    )["snapshot"]
    packet = {
        **stable,
        "status": "stable",
        "latest_incomplete": incomplete,
    }
    service = LiZongStrategyService(
        app.state.database, SnapshotStub({"000063.SZ": packet})
    )

    result = service.run_symbols(["000063.SZ"])

    candidate = result["items"][0]
    assert candidate["status"] == "data_incomplete"
    assert candidate["as_of_date"] == AS_OF
    assert candidate["result"]["evaluation_depth"] == "sync_incomplete"
    assert candidate["result"]["sync_retry_count"] == 1
    assert candidate["result"]["sync_retry_exhausted"] is False


def test_universe_batch_requeues_same_day_legacy_history_precheck_for_deep_rules(
    app,
):
    item = {
        "symbol": "601728.SS",
        "name": "中国电信",
        "industry": "通信服务",
        "market": "主板",
        "list_date": "20250701",
        "total_mv_yi": 5_000.0,
    }
    snapshots = UniverseSnapshotStub({}, [item])
    service = LiZongStrategyService(app.state.database, snapshots)

    first = service.run_universe_batch(batch_size=1)
    assert first["selected_symbols"] == []
    assert service.get_candidate("601728.SS")["result"]["evaluation_depth"] == (
        "history_precheck"
    )

    item["list_date"] = "20210820"
    snapshots.packets["601728.SS"] = _snapshot_packet(
        symbol="601728.SS",
        data_version="telecom-full-history",
        stock_name="中国电信",
    )
    second = service.run_universe_batch(batch_size=1)

    check = service._history_precheck(
        item,
        as_of_date=AS_OF,
        parameters=LiZongParameters(),
    )
    assert check["status"] == "unknown"
    assert "上市日期不能证明上市前年度ROE不可得" in check["reasons"][0]
    assert second["selected_symbols"] == ["601728.SS"]
    assert snapshots.symbol_sync_calls == ["601728.SS"]
    assert service.get_candidate("601728.SS")["result"]["evaluation_depth"] == (
        "full_rules"
    )


def test_listing_age_does_not_assume_pre_listing_roe_is_unavailable(app):
    items = [
        {
            "symbol": "601728.SS",
            "name": "中国电信",
            "industry": "通信服务",
            "market": "主板",
            "list_date": "20210820",
            "total_mv_yi": 5_000.0,
        }
    ]
    snapshots = UniverseSnapshotStub(
        {
            "601728.SS": _snapshot_packet(
                symbol="601728.SS",
                stock_name="中国电信",
                industry="通信服务",
                market_cap_yi=5_000.0,
            )
        },
        items,
    )
    service = LiZongStrategyService(app.state.database, snapshots)

    result = service.run_universe_batch(batch_size=1, as_of_date="2026-07-22")

    assert result["selected_symbols"] == ["601728.SS"]
    assert snapshots.symbol_sync_calls == ["601728.SS"]
    coverage = result["coverage"]
    assert coverage["history_insufficient_count"] == 0
    assert coverage["history_unknown_count"] == 1
    assert coverage["deep_check_eligible_count"] == 1
    candidate = service.get_candidate("601728.SS")
    assert candidate["result"]["evaluation_depth"] == "full_rules"


def test_history_precheck_uses_a_share_calendar_buffer_for_380_rows(app):
    service = LiZongStrategyService(app.state.database, SnapshotStub({}))
    item = {
        "symbol": "001391.SZ",
        "list_date": "20241230",
        "total_mv_yi": 528.0,
    }

    check = service._history_precheck(
        item,
        as_of_date="2026-07-22",
        parameters=LiZongParameters(),
    )

    assert check["status"] == "insufficient"
    assert check["listing_age_days"] == 569
    assert check["required_trading_calendar_days"] > check["listing_age_days"]


def test_universe_batch_replaces_same_day_full_result_after_history_recheck(app):
    item = {
        "symbol": "001391.SZ",
        "name": "国货航",
        "industry": "仓储物流",
        "market": "主板",
        "list_date": "19971118",
        "total_mv_yi": 528.0,
    }
    snapshots = UniverseSnapshotStub(
        {"001391.SZ": _snapshot_packet(symbol="001391.SZ")},
        [item],
        as_of_date="2026-07-22",
    )
    service = LiZongStrategyService(app.state.database, snapshots)
    first = service.run_universe_batch(batch_size=1, as_of_date="2026-07-22")
    assert first["selected_symbols"] == ["001391.SZ"]

    item["list_date"] = "20241230"
    second = service.run_universe_batch(batch_size=1, as_of_date="2026-07-22")

    assert second["selected_symbols"] == []
    assert snapshots.symbol_sync_calls == ["001391.SZ"]
    candidate = service.get_candidate("001391.SZ")
    assert candidate["result"]["evaluation_depth"] == "history_precheck"
    assert candidate["result"]["history_precheck"]["status"] == "insufficient"


def test_price_history_incomplete_detection_is_limited_to_price_rules(app):
    service = LiZongStrategyService(app.state.database, SnapshotStub({}))

    assert service._price_history_rule_incomplete(
        {"rule_results": [{"rule_id": "LZ-VP-01", "status": "data_incomplete"}]}
    )
    assert not service._price_history_rule_incomplete(
        {"rule_results": [{"rule_id": "LZ-F-02", "status": "data_incomplete"}]}
    )


def test_force_incomplete_rewrites_conflicting_not_qualified_limitation(app):
    service = LiZongStrategyService(app.state.database, SnapshotStub({}))

    result = service._force_incomplete(
        {
            "status": "not_qualified",
            "candidate_qualified": False,
            "triggered_rule_ids": [],
            "limitations": [
                "已存在明确不通过规则，同时仍有数据缺口；当前状态按 not_qualified 处理。"
            ],
        },
        "关键数据集或规则窗口不完整。",
    )

    assert result["status"] == "data_incomplete"
    assert "not_qualified" not in " ".join(result["limitations"])
    assert "按数据不完整处理" in result["limitations"][0]
    assert len(result["limitations"]) == 1


def test_enforce_incomplete_boundary_uses_public_limitation_text(app):
    service = LiZongStrategyService(app.state.database, SnapshotStub({}))
    packet = {
        "status": "partial",
        "snapshot": {"data_status": "partial", "coverage": {"missing": ["daily"]}},
    }
    evaluation = {
        "status": "not_qualified",
        "candidate_qualified": False,
        "triggered_rule_ids": [],
        "limitations": [],
        "rule_results": [],
    }

    result = service._enforce_incomplete_boundary(evaluation, packet)

    assert result["status"] == "data_incomplete"
    assert result["limitations"] == [
        "关键数据集或规则窗口不完整，当前暂不能形成完整判断。"
    ]
    assert "data_incomplete" not in " ".join(result["limitations"])


def test_missing_tushare_annual_roe_uses_reported_eastmoney_fallback(app):
    packet = _snapshot_packet(symbol="300033.SZ", stock_name="同花顺")
    packet["snapshot"]["datasets"]["fina_indicator"]["rows"] = [
        row
        for row in packet["snapshot"]["datasets"]["fina_indicator"]["rows"]
        if row["end_date"] != "20221231"
    ]

    class FundamentalsStub:
        def __init__(self):
            self.calls = 0

        def fetch_financial_periods(self, symbol: str, limit: int = 8):
            self.calls += 1
            assert symbol == "300033.SZ"
            assert limit == 20
            return {
                "source": "Eastmoney F10 Main Financial Data",
                "periods": [
                    {
                        "report_date": "2022-12-31",
                        "notice_date": "2023-02-28",
                        "roe_weighted_pct": 25.55,
                        "source": "Eastmoney F10 Main Financial Data",
                        "source_url": "https://example.test/eastmoney-f10",
                    },
                    {
                        "report_date": "2023-12-31",
                        "notice_date": "2024-02-27",
                        "roe_weighted_pct": 999.0,
                        "source": "Eastmoney F10 Main Financial Data",
                    },
                ],
            }

    provider = FundamentalsStub()
    service = LiZongStrategyService(
        app.state.database,
        SnapshotStub({"300033.SZ": packet}),
        fundamentals_provider=provider,
    )

    result = service.run_symbols(["300033.SZ"])

    assert provider.calls == 1
    candidate = result["items"][0]
    rule = next(
        item for item in candidate["rule_results"] if item["rule_id"] == "LZ-F-02"
    )
    assert rule["status"] == "passed"
    assert "Eastmoney F10 Main Financial Data" in rule["source"]
    actual = {item["report_period"]: item for item in rule["actual_value"]}
    assert actual["2022-12-31"]["roe_pct"] == 25.55
    assert actual["2022-12-31"]["source"] == "Eastmoney F10 Main Financial Data"
    assert actual["2022-12-31"]["source_url"] == "https://example.test/eastmoney-f10"
    assert (
        actual["2022-12-31"]["fallback_reason"]
        == "Tushare fina_indicator 缺少该年度ROE"
    )
    assert actual["2023-12-31"]["roe_pct"] == 12.0
    assert candidate["result"]["roe_fallback_version"] == service.ROE_FALLBACK_VERSION
    assert candidate["result"]["roe_fallback_rows"] == 1


def test_universe_batch_prefers_prior_complete_data_before_larger_market_cap(app):
    items = [
        {
            "symbol": "300308.SZ",
            "name": "中际旭创",
            "industry": "通信设备",
            "market": "创业板",
            "list_date": "20120921",
            "total_mv_yi": 1_000.0,
        },
        {
            "symbol": "000063.SZ",
            "name": "中兴通讯",
            "industry": "通信设备",
            "market": "主板",
            "list_date": "19971118",
            "total_mv_yi": 220.0,
        },
    ]
    snapshots = UniverseSnapshotStub(
        {
            "000063.SZ": _snapshot_packet(
                symbol="000063.SZ", data_version="prior-complete"
            ),
            "300308.SZ": _snapshot_packet(
                symbol="300308.SZ",
                data_version="new-large-cap",
                stock_name="中际旭创",
                market="创业板",
            ),
        },
        items,
    )
    service = LiZongStrategyService(app.state.database, snapshots)
    service.run_symbols(["000063.SZ"])
    snapshots.as_of_date = "2026-07-22"
    snapshots.data_version = "universe-v2"
    snapshots.packets["000063.SZ"]["data_version"] = "refreshed-complete"
    snapshots.packets["000063.SZ"]["snapshot"]["as_of_date"] = "2026-07-22"
    snapshots.packets["300308.SZ"]["snapshot"]["as_of_date"] = "2026-07-22"

    result = service.run_universe_batch(batch_size=1, as_of_date="2026-07-22")

    assert result["selected_symbols"] == ["000063.SZ"]
    assert snapshots.symbol_sync_calls == ["000063.SZ"]


def test_universe_batch_sync_failure_keeps_previous_stable_candidate(app):
    items = [
        {
            "symbol": "000063.SZ",
            "name": "中兴通讯",
            "industry": "通信设备",
            "market": "主板",
            "total_mv_yi": 220.0,
        }
    ]
    snapshots = UniverseSnapshotStub(
        {
            "000063.SZ": _snapshot_packet(
                symbol="000063.SZ", data_version="stable-before-failure"
            )
        },
        items,
    )
    service = LiZongStrategyService(app.state.database, snapshots)
    first = service.run_universe_batch(batch_size=1)
    previous = service.get_candidate("000063")

    snapshots.as_of_date = "2026-07-22"
    snapshots.data_version = "universe-v2"
    snapshots.failed_symbols.add("000063.SZ")
    failed = service.run_universe_batch(batch_size=1, as_of_date="2026-07-22")
    retained = service.get_candidate("000063")

    assert first["coverage"]["full_market_coverage"] is True
    assert failed["sync_results"] == [
        {
            "symbol": "000063.SZ",
            "status": "unavailable",
            "error_type": "RuntimeError",
        }
    ]
    assert failed["coverage"]["full_market_coverage"] is False
    assert failed["coverage"]["evaluated_symbols"] == 0
    assert retained["id"] == previous["id"]
    assert retained["data_version"] == previous["data_version"]
    assert _table_count(app.state.database, "strategy_candidate_snapshots") == 1


def test_unstable_universe_never_publishes_prefilter_candidates(app):
    items = [
        {
            "symbol": "000063.SZ",
            "name": "中兴通讯",
            "industry": "通信设备",
            "market": "主板",
            "total_mv_yi": None,
        },
        {
            "symbol": "300308.SZ",
            "name": "中际旭创",
            "industry": "通信设备",
            "market": "创业板",
            "total_mv_yi": None,
        },
    ]
    snapshots = UniverseSnapshotStub({}, items, status="incomplete")
    service = LiZongStrategyService(app.state.database, snapshots)

    result = service.run_universe_batch(batch_size=2)

    assert result["status"] == "not_ready"
    assert result["coverage"]["universe_count"] == 2
    assert result["coverage"]["evaluated_symbols"] == 0
    assert result["coverage"]["counts"]["total"] == 0
    assert snapshots.symbol_sync_calls == []
    assert _table_count(app.state.database, "strategy_candidate_snapshots") == 0


def test_legacy_all_missing_prefilter_run_is_quarantined(app):
    items = [
        {
            "symbol": "000063.SZ",
            "name": "中兴通讯",
            "industry": "通信设备",
            "market": "主板",
            "total_mv_yi": None,
        }
    ]
    snapshots = UniverseSnapshotStub({}, items, status="incomplete")
    service = LiZongStrategyService(app.state.database, snapshots)
    stored = service._publish_universe_prefilter(
        items,
        universe_data_version="unstable-universe-v1",
        as_of_date=AS_OF,
        parameters=LiZongParameters(),
        universe_count=1,
        prefiltered_count=0,
    )
    assert stored is not None
    assert len(service.list_candidates()) == 1

    repaired = LiZongStrategyService(app.state.database, snapshots)

    assert repaired.list_candidates() == []
    latest_run = app.state.database.latest_strategy_screen_run(
        strategy_id="li_zong", run_scope="universe_prefilter"
    )
    assert latest_run["status"] == "failed"
    assert latest_run["error"] == "unstable_universe_market_cap_snapshot"


def test_strategy_api_exposes_published_candidates_rules_and_triggers(app, client):
    user = client.post("/users", json={"name": "Li Zong API User"})
    assert user.status_code == 201
    app.state.li_zong_strategy.snapshot_service = SnapshotStub(
        {"000063.SZ": _snapshot_packet(triggered=True)}
    )
    app.state.li_zong_strategy.run_symbols(["000063"])

    definition = client.get("/v1/stock-strategies/li-zong")
    assert definition.status_code == 200
    assert definition.json()["current_version"] == "li_zong_v1"

    response = client.get("/v1/stock-strategies/li-zong/candidates")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["counts"]["triggered"] == 1
    assert payload["funnel"]["starting_count"] == 1
    assert payload["funnel"]["steps"][-1]["remaining_count"] == 1
    assert payload["data_meta"]["full_market_coverage"] is False
    item = payload["items"][0]
    assert item["symbol"] == "000063.SZ"
    assert item["name"] == "中兴通讯"
    assert item["summary"]["annual_limit_up_count"] == 7
    assert len(item["rule_results"]) == 12

    detail = client.get("/v1/stock-strategies/li-zong/candidates/000063")
    assert detail.status_code == 200
    assert detail.json()["trigger_events"][0]["rule_id"] == "LZ-T-01"

    triggers = client.get("/v1/stock-strategies/li-zong/triggers")
    assert triggers.status_code == 200
    assert len(triggers.json()["items"]) == 1


def test_strategy_api_uses_snapshot_name_for_unconfigured_symbol(app, client):
    assert client.post("/users", json={"name": "Snapshot Name User"}).status_code == 201
    packet = _snapshot_packet(
        symbol="000001.SZ",
        stock_name="平安银行",
        industry="银行",
    )
    app.state.li_zong_strategy.snapshot_service = SnapshotStub({"000001.SZ": packet})
    app.state.li_zong_strategy.run_symbols(["000001"])

    response = client.get("/v1/stock-strategies/li-zong/candidates")

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["symbol"] == "000001.SZ"
    assert item["name"] == "平安银行"
    assert item["industry"] == "银行"
    assert item["market"] == "主板"


def test_strategy_api_backfills_snapshot_name_for_legacy_candidate(app, client):
    assert (
        client.post("/users", json={"name": "Legacy Candidate User"}).status_code == 201
    )
    packet = _snapshot_packet(
        symbol="000001.SZ",
        stock_name="平安银行",
        industry="银行",
    )
    snapshots = SnapshotStub({"000001.SZ": packet})
    app.state.li_zong_strategy.snapshot_service = snapshots
    result = app.state.li_zong_strategy.run_symbols(["000001"])
    candidate = result["items"][0]
    legacy_result = dict(candidate["result"])
    legacy_result.pop("stock_basic")
    with app.state.database.connect() as connection:
        connection.execute(
            "UPDATE strategy_candidate_snapshots SET result_json = ? WHERE id = ?",
            (json.dumps(legacy_result, ensure_ascii=False), candidate["id"]),
        )

    response = client.get("/v1/stock-strategies/li-zong/candidates")

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["name"] == "平安银行"
    assert item["industry"] == "银行"


def test_strategy_run_api_requires_admin_token_and_versions_custom_roe(app, client):
    assert client.post("/users", json={"name": "Li Zong Runner"}).status_code == 201
    app.state.li_zong_strategy.snapshot_service = SnapshotStub(
        {"000063.SZ": _snapshot_packet(data_version="api-v1")}
    )

    request_body = {
        "symbols": ["000063"],
        "refresh_data": False,
        "roe_min_pct": 11,
    }
    disabled = client.post(
        "/v1/stock-strategies/li-zong/runs",
        json=request_body,
    )
    assert disabled.status_code == 403
    assert (
        client.post(
            "/v1/stock-strategies/li-zong/universe-runs",
            json={"batch_size": 1},
        ).status_code
        == 403
    )

    latest = client.get("/v1/stock-strategies/li-zong/runs/latest")
    assert latest.status_code == 200
    assert latest.json()["coverage"]["full_market_coverage"] is False

    object.__setattr__(app.state.settings, "admin_api_token", "test-admin-token")
    wrong = client.post(
        "/v1/stock-strategies/li-zong/runs",
        json=request_body,
        headers={"X-Qingshu-Admin-Token": "wrong-token"},
    )
    assert wrong.status_code == 403

    response = client.post(
        "/v1/stock-strategies/li-zong/runs",
        json=request_body,
        headers={"X-Qingshu-Admin-Token": "test-admin-token"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["items"][0]["parameter_version"] == "li_zong_v1_roe_11"
    assert payload["sync_results"] == []
    assert payload["items"][0]["status"] in {"qualified", "not_qualified"}

    rejected = client.post(
        "/v1/stock-strategies/li-zong/runs",
        json={"symbols": ["NVDA"], "refresh_data": False},
        headers={"X-Qingshu-Admin-Token": "test-admin-token"},
    )
    assert rejected.status_code == 422


def test_tushare_snapshot_api_keeps_external_ts_code_and_neutral_empty_state(client):
    assert client.get("/v1/data/tushare/stocks/600519.SH/snapshot").status_code == 401
    assert client.post("/users", json={"name": "Snapshot API User"}).status_code == 201

    response = client.get("/v1/data/tushare/stocks/600519.SH/snapshot")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "not_ready"
    assert payload["symbol"] == "600519.SH"
    assert payload["internal_symbol"] == "600519.SS"
    assert "Token" not in response.text


def test_empty_li_zong_filter_is_ready_after_stable_universe_publish(
    app, client, monkeypatch
):
    assert (
        client.post("/users", json={"name": "Stable Empty Strategy"}).status_code == 201
    )
    monkeypatch.setattr(app.state.li_zong_strategy, "list_candidates", lambda **_: [])
    monkeypatch.setattr(
        app.state.li_zong_strategy,
        "coverage_packet",
        lambda: {
            "status": "stable",
            "as_of_date": "2026-07-22",
            "universe_count": 5530,
            "evaluated_symbols": 5530,
            "coverage_ratio": 1.0,
            "counts": {
                "total": 5530,
                "qualified": 0,
                "triggered": 0,
                "not_qualified": 5530,
                "data_incomplete": 0,
                "invalidated": 0,
            },
        },
    )

    response = client.get(
        "/v1/stock-strategies/li-zong/candidates?status=qualified&limit=200"
    )

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["items"] == []
    assert response.json()["counts"]["qualified"] == 0


def test_li_zong_observation_pool_api_keeps_bands_separate_from_candidates(app, client):
    assert (
        client.post(
            "/users", json={"name": "Li Zong Observation Pool User"}
        ).status_code
        == 201
    )
    near_packet = _snapshot_packet(
        symbol="000063.SZ",
        data_version="near-api-v1",
        market_cap_yi=100.0,
    )
    watch_packet = _snapshot_packet(
        symbol="000001.SZ",
        data_version="watch-api-v1",
        market_cap_yi=100.0,
        stock_name="平安银行",
        industry="银行",
    )
    watch_packet["snapshot"]["datasets"]["fina_indicator"]["rows"][0]["roe"] = 5.0
    app.state.li_zong_strategy.snapshot_service = SnapshotStub(
        {"000063.SZ": near_packet, "000001.SZ": watch_packet}
    )
    app.state.li_zong_strategy.run_symbols(["000063.SZ", "000001.SZ"])

    near = client.get(
        "/v1/stock-strategies/li-zong/observation-pool?band=near_8_of_9&limit=20"
    )
    strict = client.get(
        "/v1/stock-strategies/li-zong/candidates?status=qualified&limit=20"
    )

    assert near.status_code == 200, near.text
    payload = near.json()
    assert payload["status"] == "ready"
    assert payload["observation_counts"] == {
        "near_8_of_9": 1,
        "watch_6_7_of_9": 1,
    }
    assert len(payload["items"]) == 1
    assert payload["items"][0]["internal_symbol"] == "000063.SZ"
    assert payload["items"][0]["observation_band"] == "near_8_of_9"
    assert payload["items"][0]["candidate_rule_pass_count"] == 8
    assert payload["items"][0]["is_strict_candidate"] is False
    assert strict.status_code == 200
    assert strict.json()["items"] == []


def test_demo_exposes_strictly_separate_li_zong_observation_pool(
    app, client, frontend_source
):
    page = client.get("/demo")
    source = frontend_source

    assert page.status_code == 200
    assert 'data-li-zong-filter="near_8_of_9"' in page.text
    assert 'data-li-zong-filter="watch_6_7_of_9"' in page.text
    assert "/v1/stock-strategies/li-zong/observation-pool?band=" in source
    assert "limit=30" in source
    assert "只研究观察" in source
    assert "完整规则核验后的研究观察分层，不是候选" in source
    assert "严格9条候选规则和3条触发规则保持不变" in source


def test_trigger_enters_stock_workspace_and_agent_uses_strategy_evidence(app, client):
    assert (
        client.post("/users", json={"name": "Strategy Workspace User"}).status_code
        == 201
    )
    app.state.li_zong_strategy.snapshot_service = SnapshotStub(
        {"000063.SZ": _snapshot_packet(triggered=True, data_version="workspace-v1")}
    )
    app.state.li_zong_strategy.run_symbols(["000063"])

    workspace = client.get("/v1/stocks/000063.SZ/workspace")
    assert workspace.status_code == 200
    payload = workspace.json()
    assert payload["strategy_evidence"]["status"] == "triggered"
    assert payload["important_changes"][0]["event_type"] == "strategy_trigger"
    assert payload["pending_actions"][0]["source"] == "li_zong_strategy"

    chat = client.post(
        "/me/chat",
        json={
            "message": "李总策略里中兴通讯今天触发了吗？请说明证据。",
            "execute_agent": False,
        },
    )
    assert chat.status_code == 200
    evidence = chat.json()["evidence"]
    assert evidence["profile"]["key"] == "li_zong"
    assert evidence["items"][0]["status"] == "triggered"
    assert len(evidence["items"][0]["rule_results"]) == 12


def test_agent_li_zong_pool_excludes_failed_stocks_and_followup_keeps_context(
    app, client
):
    assert client.post("/users", json={"name": "Li Zong Chat User"}).status_code == 201
    app.state.li_zong_strategy.snapshot_service = SnapshotStub(
        {
            "000063.SZ": _snapshot_packet(
                triggered=True, data_version="chat-triggered"
            ),
            "000001.SZ": _snapshot_packet(
                symbol="000001.SZ",
                data_version="chat-rejected",
                market_cap_yi=100.0,
                stock_name="平安银行",
                industry="银行",
            ),
        }
    )
    app.state.li_zong_strategy.run_symbols(["000063", "000001"])

    pool = client.post(
        "/me/chat",
        json={
            "message": "用李总策略帮我选股，当前有哪些候选？",
            "execute_agent": False,
        },
    )
    assert pool.status_code == 200
    pool_payload = pool.json()
    assert pool_payload["evidence"]["selection_mode"] == "candidate_pool"
    assert "market_cap_eligible_count" not in pool_payload["evidence"]["data_meta"]
    assert [item["internal_symbol"] for item in pool_payload["evidence"]["items"]] == [
        "000063.SZ"
    ]
    assert pool_payload["evidence"]["items"][0]["status"] == "triggered"
    assert "平安银行" not in pool_payload["answer"]
    assert "1 只已发布研究候选" in pool_payload["answer"]

    rejected = client.post(
        "/me/chat",
        json={
            "message": "000001.SZ在李总策略里通过了吗？",
            "execute_agent": False,
        },
    )
    assert rejected.status_code == 200
    rejected_payload = rejected.json()
    assert rejected_payload["evidence"]["selection_mode"] == "symbol_check"
    assert rejected_payload["evidence"]["items"][0]["status"] == "not_qualified"
    assert "不是当前候选" in rejected_payload["answer"]

    followup = client.post(
        "/me/chat",
        json={
            "conversation_id": rejected_payload["conversation_id"],
            "message": "为什么没有进入候选？",
            "execute_agent": False,
        },
    )
    assert followup.status_code == 200
    followup_payload = followup.json()
    assert followup_payload["evidence"]["profile"]["key"] == "li_zong"
    assert followup_payload["evidence"]["requested_symbol"] == "000001.SZ"
    assert followup_payload["evidence"]["items"][0]["status"] == "not_qualified"
    assert "不是当前候选" in followup_payload["answer"]

    trigger_boundary = client.post(
        "/me/chat",
        json={
            "conversation_id": rejected_payload["conversation_id"],
            "message": (
                "如果未通过规则以后转为通过，是否还需要满足盘后触发规则才能进入候选？"
            ),
            "execute_agent": False,
        },
    )
    assert trigger_boundary.status_code == 200
    boundary_payload = trigger_boundary.json()
    assert boundary_payload["intent"] == "stock_screen"
    assert boundary_payload["evidence"]["profile"]["key"] == "li_zong"
    assert boundary_payload["evidence"]["selection_mode"] == "symbol_check"
    assert boundary_payload["evidence"]["requested_symbol"] == "000001.SZ"


def test_agent_li_zong_resolves_multiple_universe_company_names(app, client):
    assert (
        client.post("/users", json={"name": "Li Zong Multi Symbol User"}).status_code
        == 201
    )
    recent = {
        "symbol": "001391.SZ",
        "name": "国货航",
        "industry": "仓储物流",
        "market": "主板",
        "list_date": "20241230",
        "total_mv_yi": 528.0,
    }
    suspended = {
        "symbol": "600777.SS",
        "name": "新潮能源",
        "industry": "石油开采",
        "market": "主板",
        "list_date": "19961121",
        "total_mv_yi": 278.0,
    }
    packet = _snapshot_packet(
        symbol="600777.SS",
        stock_name="新潮能源",
        industry="石油开采",
    )
    for dataset in ("daily", "adj_factor", "stk_limit"):
        packet["snapshot"]["datasets"][dataset]["rows"] = packet["snapshot"][
            "datasets"
        ][dataset]["rows"][-350:]
    snapshots = UniverseSnapshotStub(
        {"600777.SS": packet},
        [recent, suspended],
        as_of_date="2026-07-22",
    )
    app.state.li_zong_strategy.snapshot_service = snapshots
    app.state.li_zong_strategy.run_universe_batch(batch_size=1, as_of_date="2026-07-22")

    response = client.post(
        "/me/chat",
        json={
            "message": (
                "李总策略为什么把国货航标记为量价历史不足？"
                "新潮能源为什么仍然数据不完整？"
            ),
            "execute_agent": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["evidence"]["selection_mode"] == "symbol_comparison"
    assert payload["evidence"]["requested_symbols"] == [
        "001391.SZ",
        "600777.SS",
    ]
    assert [item["name"] for item in payload["evidence"]["items"]] == [
        "国货航",
        "新潮能源",
    ]
    assert "国货航（001391.SZ）" in payload["answer"]
    assert "上市后量价历史预判未达到" in payload["answer"]
    assert "新潮能源（600777.SS）" in payload["answer"]
    assert "完整交易日不足" in payload["answer"]
    conversation = client.get(f"/me/conversations/{payload['conversation_id']}").json()
    assistant = next(
        item
        for item in reversed(conversation["messages"])
        if item["role"] == "assistant"
    )
    assert assistant["metadata"]["research_targets"] == [
        {"symbol": "001391.SZ", "name": "国货航"},
        {"symbol": "600777.SS", "name": "新潮能源"},
    ]
