from __future__ import annotations

from collections import Counter
from copy import deepcopy
import json

import pandas as pd

from app.services.li_zong_strategy_service import LiZongStrategyService


AS_OF = "2026-07-21"


class SnapshotStub:
    def __init__(self, packets: dict[str, dict]):
        self.packets = packets
        self.calls: Counter[str] = Counter()

    def get_symbol_snapshot(self, symbol: str) -> dict:
        self.calls[symbol] += 1
        return deepcopy(self.packets[symbol])


def _snapshot_packet(
    symbol: str = "000063.SZ",
    *,
    data_version: str = "stable-v1",
    triggered: bool = False,
    market_cap_yi: float = 180.0,
    stock_name: str = "中兴通讯",
    industry: str = "通信设备",
    market: str = "主板",
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
        "trade_cal": _dataset("trade_cal", [{"cal_date": row.strftime("%Y%m%d")} for row in dates]),
        "stock_basic": _dataset(
            "stock_basic",
            [
                {
                    "ts_code": symbol,
                    "name": stock_name,
                    "industry": industry,
                    "market": market,
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


def _table_count(database, table: str) -> int:
    with database.connect() as connection:
        return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def test_service_bootstraps_all_strategy_tables_and_versioned_definition(app):
    service = LiZongStrategyService(
        app.state.database,
        SnapshotStub({"000063.SZ": _snapshot_packet()}),
    )

    with app.state.database.connect() as connection:
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
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
    assert definition["default_parameter_version"]["parameters"][
        "roe_min_pct"
    ] == 10.0
    assert definition["subscriptions_enabled"] is False
    assert "暂未" in definition["subscription_boundary"]
    assert service.list_strategies()[0]["name"] == "李总策略"


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


def test_missing_dataset_is_always_data_incomplete_even_with_known_failed_rule(app):
    packet = _snapshot_packet(market_cap_yi=100.0, data_version="partial-v1")
    packet["status"] = "incomplete"
    packet["snapshot"]["data_status"] = "incomplete"
    packet["snapshot"]["coverage"] = {
        "required": 9,
        "available": 8,
        "missing": ["fina_indicator"],
    }
    packet["snapshot"]["datasets"]["fina_indicator"] = _dataset(
        "fina_indicator", []
    )
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
    app.state.li_zong_strategy.snapshot_service = SnapshotStub(
        {"000001.SZ": packet}
    )
    app.state.li_zong_strategy.run_symbols(["000001"])

    response = client.get("/v1/stock-strategies/li-zong/candidates")

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["symbol"] == "000001.SZ"
    assert item["name"] == "平安银行"
    assert item["industry"] == "银行"
    assert item["market"] == "主板"


def test_strategy_api_backfills_snapshot_name_for_legacy_candidate(app, client):
    assert client.post("/users", json={"name": "Legacy Candidate User"}).status_code == 201
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


def test_strategy_run_api_uses_published_snapshot_and_versions_custom_roe(app, client):
    assert client.post("/users", json={"name": "Li Zong Runner"}).status_code == 201
    app.state.li_zong_strategy.snapshot_service = SnapshotStub(
        {"000063.SZ": _snapshot_packet(data_version="api-v1")}
    )

    response = client.post(
        "/v1/stock-strategies/li-zong/runs",
        json={
            "symbols": ["000063"],
            "refresh_data": False,
            "roe_min_pct": 11,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["items"][0]["parameter_version"] == "li_zong_v1_roe_11"
    assert payload["sync_results"] == []
    assert payload["items"][0]["status"] in {"qualified", "not_qualified"}

    rejected = client.post(
        "/v1/stock-strategies/li-zong/runs",
        json={"symbols": ["NVDA"], "refresh_data": False},
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


def test_trigger_enters_stock_workspace_and_agent_uses_strategy_evidence(app, client):
    assert client.post("/users", json={"name": "Strategy Workspace User"}).status_code == 201
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
