from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.db import Database
from app.services.li_zong_history import LiZongHistoryService
from app.services.li_zong_strategy_service import LiZongStrategyService


AS_OF = "2026-07-21"


def _strategy_packet() -> dict:
    dates = pd.bdate_range(end=AS_OF, periods=420)
    daily_rows = []
    limit_indices = {-200, -199, -150, -100, -50, -30}
    for position, trade_date in enumerate(dates):
        relative = position - len(dates)
        pre_close = 100.0 + position * 0.05
        close = pre_close + 0.5
        up_limit = pre_close + 10.0
        if relative in limit_indices:
            close = up_limit
        daily_rows.append(
            {
                "ts_code": "000001.SZ",
                "trade_date": trade_date.strftime("%Y%m%d"),
                "open": close - 0.4,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "pre_close": pre_close,
                "pct_chg": (close / pre_close - 1.0) * 100.0,
                "volume": 100.0,
                "up_limit": up_limit,
                "has_price_limit": True,
                "adjusted_high": 100.0 + position * 0.1,
            }
        )
    for relative in (-60, -59, -58):
        daily_rows[relative]["volume"] = 200.0
    roe = [
        {
            "ts_code": "000001.SZ",
            "end_date": f"{year}1231",
            "ann_date": f"{year + 1}0430",
            "roe": 12.0,
        }
        for year in range(2021, 2026)
    ]
    holders = [
        {
            "ts_code": "000001.SZ",
            "end_date": "20260331",
            "ann_date": "20260430",
            "holder_name": name,
            "holder_type": holder_type,
        }
        for name, holder_type in (
            ("甲公司", "company"),
            ("乙基金", "fund"),
            ("丙保险", "insurance"),
            ("丁银行", "bank"),
            ("戊资管计划", "asset_management"),
        )
    ]

    def dataset(name: str, rows: list[dict]) -> dict:
        return {
            "dataset": name,
            "rows": rows,
            "row_count": len(rows),
            "source": "fixture",
            "as_of_date": AS_OF,
        }

    return {
        "symbol": "000001.SZ",
        "as_of_date": AS_OF,
        "data_status": "stable",
        "generated_at": "2026-07-21T16:00:00+08:00",
        "datasets": {
            "daily": dataset("daily", daily_rows),
            "adj_factor": dataset("adj_factor", []),
            "stk_limit": dataset("stk_limit", []),
            "fina_indicator": dataset("fina_indicator", roe),
            "top10_holders": dataset("top10_holders", holders),
            "top10_floatholders": dataset("top10_floatholders", []),
            "daily_basic": dataset(
                "daily_basic",
                [{"trade_date": "20260721", "total_mv": 5_000_000.0}],
            ),
            "stock_basic": dataset(
                "stock_basic",
                [
                    {
                        "ts_code": "000001.SZ",
                        "name": "平安银行",
                        "industry": "银行",
                        "market": "主板",
                        "list_date": "19910403",
                    }
                ],
            ),
        },
    }


class HistoryClientStub:
    def __init__(self, dates: list[str], *, market_cap_wan: float = 2_000_000.0):
        self.dates = dates
        self.market_cap_wan = market_cap_wan

    def daily_basic(self, **params: object) -> pd.DataFrame:
        start = str(params.get("start_date") or "")
        end = str(params.get("end_date") or "99999999")
        dates = [value for value in self.dates if start <= value <= end]
        return pd.DataFrame(
            [
                {
                    "ts_code": "000001.SZ",
                    "trade_date": value,
                    "total_mv": self.market_cap_wan,
                    "circ_mv": self.market_cap_wan,
                }
                for value in reversed(dates)
            ]
        )

    def index_daily(self, **params: object) -> pd.DataFrame:
        start = str(params.get("start_date") or "")
        end = str(params.get("end_date") or "99999999")
        dates = [value for value in self.dates if start <= value <= end]
        return pd.DataFrame(
            [
                {
                    "ts_code": "000300.SH",
                    "trade_date": value,
                    "open": 100.0 + index * 0.1,
                    "high": 100.3 + index * 0.1,
                    "low": 99.7 + index * 0.1,
                    "close": 100.0 + index * 0.1,
                    "pre_close": 99.9 + index * 0.1,
                    "pct_chg": 0.1,
                }
                for index, value in reversed(list(enumerate(dates)))
            ]
        )


class SnapshotServiceStub:
    def __init__(self, client: HistoryClientStub):
        self.client = client


def _service(tmp_path: Path, *, market_cap_wan: float = 2_000_000.0):
    database = Database(tmp_path / "workspaces")
    database.initialize()
    payload = _strategy_packet()
    dates = [row["trade_date"] for row in payload["datasets"]["daily"]["rows"]]
    snapshots = SnapshotServiceStub(
        HistoryClientStub(dates, market_cap_wan=market_cap_wan)
    )
    strategy = LiZongStrategyService(database, snapshots)
    history = LiZongHistoryService(database, snapshots, strategy)
    run = database.start_tushare_sync_run(
        job_scope="fixture", as_of_date=AS_OF, datasets=["li_zong_inputs"]
    )
    database.save_tushare_dataset_snapshot(
        dataset="li_zong_inputs",
        scope_key="000001.SZ",
        as_of_date=AS_OF,
        report_period=None,
        source_updated_at=payload["generated_at"],
        sync_run_id=run["id"],
        data_version="base-v1",
        data_status="stable",
        payload=payload,
    )
    database.finish_tushare_sync_run(
        run["id"], status="stable", data_version="base-v1", summary={}
    )
    return database, history, dates


def test_recent_replay_publishes_real_signal_and_5_10_20_day_benchmark_returns(
    tmp_path: Path,
):
    _, service, _ = _service(tmp_path)

    result = service.run_batch(symbols=["000001.SZ"], lookback_days=80)
    packet = service.history_packet()

    assert result["status"] == "completed"
    assert packet["coverage"]["completed_symbols"] == 1
    assert packet["items"]
    event = packet["items"][0]
    assert event["signal_type"] == "triggered"
    assert "LZ-T-01" in event["triggered_rule_ids"]
    assert event["rule_summary"]["passed_candidate_rules"] == 9
    for horizon in ("5", "10", "20"):
        outcome = event["performance"]["horizons"][horizon]
        assert outcome["status"] == "available"
        assert isinstance(outcome["stock_return_pct"], float)
        assert isinstance(outcome["benchmark_return_pct"], float)
        assert outcome["excess_return_pct"] == round(
            outcome["stock_return_pct"] - outcome["benchmark_return_pct"], 4
        )
        assert outcome["max_upside_date"] <= outcome["target_date"]
        assert outcome["max_drawdown_date"] <= outcome["target_date"]
    assert len(event["performance"]["path"]) == 21
    assert "信号日当时已公告" in packet["boundary"]


def test_replay_uses_historical_market_cap_instead_of_current_snapshot(tmp_path: Path):
    _, service, _ = _service(tmp_path, market_cap_wan=1_400_000.0)

    service.run_batch(symbols=["000001.SZ"], lookback_days=80)
    packet = service.history_packet()

    assert packet["coverage"]["completed_symbols"] == 1
    assert packet["items"] == []


def test_replay_slices_price_history_and_deduplicates_signal_phases(
    tmp_path: Path, monkeypatch
):
    _, service, dates = _service(tmp_path)
    selected = dates[-20:]
    state_by_date = {
        selected[-6]: "qualified",
        selected[-5]: "qualified",
        selected[-4]: "triggered",
        selected[-3]: "triggered",
        selected[-2]: "qualified",
        selected[-1]: "triggered",
    }

    def fake_evaluate(data, *, parameters=None):
        del parameters
        as_of = str(data["as_of_date"])
        observed = pd.DataFrame(data["daily"])
        assert all(
            str(value).replace("-", "") <= as_of.replace("-", "")
            for value in observed["trade_date"]
        )
        assert len(pd.DataFrame(data["daily_basic"])) == 20
        status = state_by_date.get(as_of.replace("-", ""), "not_qualified")
        return {
            "status": status,
            "candidate_qualified": status in {"qualified", "triggered"},
            "triggered_rule_ids": ["LZ-T-01"] if status == "triggered" else [],
            "rule_results": [],
        }

    monkeypatch.setattr(
        "app.services.li_zong_history.deterministic_li_zong_v1", fake_evaluate
    )

    service.run_batch(symbols=["000001.SZ"], lookback_days=20)
    events = list(reversed(service.history_packet()["items"]))

    assert [item["signal_type"] for item in events] == [
        "qualified",
        "triggered",
        "triggered",
    ]
    assert [item["signal_date"].replace("-", "") for item in events] == [
        selected[-6],
        selected[-4],
        selected[-1],
    ]


def test_history_api_exposes_coverage_and_requires_admin_for_manual_run(
    app, client, monkeypatch
):
    assert client.post("/users", json={"name": "History API User"}).status_code == 201
    monkeypatch.setattr(
        app.state.li_zong_history,
        "history_packet",
        lambda **_: {
            "status": "ready",
            "items": [{"symbol": "000001.SZ", "signal_date": "2026-05-01"}],
            "coverage": {"completed_symbols": 1, "expected_symbols": 10},
            "boundary": "历史回放边界",
        },
    )

    response = client.get("/v1/stock-strategies/li-zong/history")
    denied = client.post(
        "/v1/stock-strategies/li-zong/history/runs", json={"batch_size": 1}
    )

    assert response.status_code == 200
    assert response.json()["items"][0]["signal_date"] == "2026-05-01"
    assert denied.status_code == 403


def test_demo_contract_contains_history_replay_and_agent_entry(
    app, client, frontend_source
):
    page = client.get("/demo")
    source = frontend_source

    assert page.status_code == 200
    assert 'id="liZongHistoryPanel"' in page.text
    assert "历史真实命中与后续表现" in page.text
    assert 'id="liZongFunnel"' in page.text
    assert 'id="liZongHistoryToggle"' in page.text
    assert 'data-screening-jump="general"' in page.text
    assert 'data-screening-jump="li_zong"' in page.text
    assert 'liZongHistoryExpanded: false' in source
    assert 'container.hidden = !state.liZongHistoryExpanded' in source
    assert '$("stockScreenerPanel").appendChild($("liZongPanel"))' in source
    assert "/v1/stock-strategies/li-zong/history?limit=30" in source
    assert "让 Agent 复盘" in source
    assert "{agentQuestion}" in source
    assert "context?.agentQuestion" in source
    assert "请基于李总策略的真实历史回放" in source
    assert "continueDeepStockConversation(question, session)" in source
    assert (
        "targetSession || state.deepStock || await startDeepStockSession()" in source
    )


def test_screening_sections_are_mutually_exclusive_and_general_screen_is_explicit(
    app, client, frontend_source
):
    page = client.get("/demo")
    source = frontend_source

    assert page.status_code == 200
    assert 'id="generalScreenerPanel"' in page.text
    assert 'screeningSection: "general"' in source
    assert "function syncScreeningSection(options = {})" in source
    assert '$("generalScreenerPanel").hidden = section !== "general"' in source
    assert '$("liZongPanel").hidden = section !== "li_zong"' in source
    assert 'data-load-state="idle"' in page.text
    assert 'renderLiZongLoadState("loading", "正在读取最新策略结果")' in source
    assert 'renderLiZongLoadState("error", "暂时没有取得最新策略结果")' in source
    assert "重新加载策略结果" in source
    assert 'role="tab" aria-selected="true" data-screening-jump="general"' in page.text
    assert 'if (!state.stockScreener) void loadStockScreener();' not in source
    assert 'params.set("section", "li_zong")' in source


def test_history_replay_agent_question_reuses_the_exact_event_evidence(
    app, client, monkeypatch
):
    assert client.post("/users", json={"name": "History Agent User"}).status_code == 201
    event = {
        "symbol": "000001.SZ",
        "internal_symbol": "000001.SZ",
        "name": "平安银行",
        "signal_date": "2026-05-01",
        "signal_type": "qualified",
        "rule_results": [{"rule_id": "LZ-C-01", "status": "passed"}],
        "performance": {
            "horizons": {
                "5": {
                    "status": "available",
                    "stock_return_pct": 3.2,
                    "benchmark_return_pct": 1.1,
                    "excess_return_pct": 2.1,
                }
            }
        },
    }
    history_calls = []

    def history_packet(**kwargs):
        history_calls.append(kwargs)
        return {
            "status": "ready",
            "items": [event],
            "coverage": {"completed_symbols": 1, "expected_symbols": 1},
            "boundary": "历史回放边界",
        }

    monkeypatch.setattr(app.state.li_zong_history, "history_packet", history_packet)
    monkeypatch.setattr(app.state.li_zong_strategy, "get_candidate", lambda _: None)

    response = client.post(
        "/me/chat",
        json={
            "message": (
                "请基于李总策略的真实历史回放，复盘平安银行（000001.SZ）"
                "在2026-05-01的信号及后续相对沪深300走势。"
            ),
            "execute_agent": False,
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["intent"] == "stock_screen"
    assert payload["evidence"]["history"]["items"] == [event]
    assert history_calls == [{"symbol": "000001.SZ", "limit": 12}]

    followup = client.post(
        "/me/chat",
        json={
            "message": (
                "请再次用同一个2026-05-01历史事件回答，但这次只需用三句话概括"
                "5/10/20日相对沪深300走势、最重要的反方证据和不可外推边界，"
                "并保留本轮历史回放引用。"
            ),
            "conversation_id": payload["conversation_id"],
            "execute_agent": False,
        },
    )

    assert followup.status_code == 200, followup.text
    followup_payload = followup.json()
    assert followup_payload["intent"] == "stock_screen"
    assert followup_payload["evidence"]["requested_symbol"] == "000001.SZ"
    assert followup_payload["evidence"]["history"]["items"] == [event]
    assert history_calls == [
        {"symbol": "000001.SZ", "limit": 12},
        {"symbol": "000001.SZ", "limit": 12},
    ]
