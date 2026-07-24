from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def _create_user(client: TestClient, name: str) -> dict:
    response = client.post("/users", json={"name": name})
    assert response.status_code == 201
    return response.json()


def _add_stock(
    client: TestClient,
    symbol: str,
    name: str,
    thesis: str,
) -> dict:
    response = client.post(
        "/me/watchlist",
        json={
            "symbol": symbol,
            "name": name,
            "market": "A股",
            "thesis": thesis,
        },
    )
    assert response.status_code == 200
    return response.json()


def _update_relation(
    client: TestClient,
    symbol: str,
    *,
    relation_type: str,
    tracking_status: str = "active",
    workflow_status: str = "idle",
    priority: str | None = None,
    attention_tags: list[str] | None = None,
) -> dict:
    current = client.get(f"/v1/stocks/{symbol}/relation")
    assert current.status_code == 200
    response = client.patch(
        f"/v1/stocks/{symbol}/relation",
        json={
            "base_version": current.json()["version"],
            "relation_type": relation_type,
            "priority": priority,
            "tracking_status": tracking_status,
            "workflow_status": workflow_status,
            "attention_tags": attention_tags or [],
        },
    )
    assert response.status_code == 200
    return response.json()


def _save_quote_and_change(app, user_id: str) -> None:
    report = app.state.database.create_research_report(
        symbol="000063.SZ",
        name="中兴通讯",
        title="中兴通讯研究快照",
        summary="需要继续核验利润和现金流。",
        body="研究正文",
        status="completed",
        fingerprint=f"stock-assets-{user_id}",
        evidence={
            "display_name": "中兴通讯",
            "current_quote": {
                "name": "中兴通讯",
                "price": 41.2,
                "pct_change": -1.5,
                "currency": "CNY",
                "quote_label": "最新报价",
                "market_timestamp": "2026-07-23T14:55:00+08:00",
            },
            "metrics": {"latest_close": 41.8, "return_1d_pct": -0.8},
            "provenance": {"market_timestamp": "2026-07-22T15:00:00+08:00"},
        },
        run_id=None,
        market_timestamp="2026-07-22T15:00:00+08:00",
    )
    app.state.database.save_research_change_event(
        symbol="000063.SZ",
        report_id=report["id"],
        previous_report_id=None,
        event_type="evidence_change",
        severity="attention",
        summary="利润和现金流的背离需要复核。",
        payload={"data_as_of": "2026-07-22T15:00:00+08:00"},
    )


def test_stock_workspaces_requires_session_and_has_honest_empty_state(app):
    anonymous = TestClient(app)
    assert anonymous.get("/v1/stock-workspaces").status_code == 401

    client = TestClient(app)
    _create_user(client, "Empty Stock Assets")
    response = client.get("/v1/stock-workspaces")

    assert response.status_code == 200
    assert response.json() == {
        "contract_version": "stock_asset_list_v1",
        "status": "empty",
        "items": [],
        "summary": {
            "total": 0,
            "watching": 0,
            "holding": 0,
            "ended": 0,
            "paused": 0,
            "waiting_data": 0,
        },
        "boundary": (
            "该列表组织用户的长期股票研究资产；已结束空间仍保留"
            "判断、任务和历史。持仓数量、成本和盈亏事实链尚未建立时，"
            "不生成伪精确持仓数据。"
        ),
    }


def test_stock_workspaces_return_all_relations_and_stable_contract(app):
    client = TestClient(app)
    user = _create_user(client, "Stock Asset Owner")
    _add_stock(client, "000063", "中兴通讯", "关注利润和经营现金流")
    _add_stock(client, "300308", "中际旭创", "关注光模块需求和产能利用率")
    _add_stock(client, "600519", "贵州茅台", "关注需求和现金流")
    _update_relation(
        client,
        "300308",
        relation_type="holding",
        workflow_status="waiting_data",
        attention_tags=["report_due"],
    )
    ended = _update_relation(
        client,
        "600519",
        relation_type="ended",
        tracking_status="paused",
    )
    _save_quote_and_change(app, user["id"])
    task = client.post(
        "/v1/stocks/000063/observation-tasks",
        json={
            "title": "复核经营现金流",
            "description": "下一份财报披露后核对经营现金流与利润是否同步。",
            "priority": "high",
        },
    )
    assert task.status_code == 201

    response = client.get("/v1/stock-workspaces")

    assert response.status_code == 200
    payload = response.json()
    assert payload["contract_version"] == "stock_asset_list_v1"
    assert payload["summary"] == {
        "total": 3,
        "watching": 1,
        "holding": 1,
        "ended": 1,
        "paused": 1,
        "waiting_data": 1,
    }
    by_symbol = {item["symbol"]: item for item in payload["items"]}
    assert set(by_symbol) == {"000063.SZ", "300308.SZ", "600519.SS"}

    watching = by_symbol["000063.SZ"]
    assert watching["relation_type"] == "watching"
    assert watching["relation_label"] == "关注"
    assert watching["active_thesis"] == {
        "summary": "关注利润和经营现金流",
        "version": 1,
        "watch_items": [],
        "recheck_conditions": [],
    }
    assert watching["latest_change"]["summary"] == "利润和现金流的背离需要复核。"
    assert watching["report_meta"] == {
        "id": watching["report_meta"]["id"],
        "symbol": "000063.SZ",
        "name": "中兴通讯",
        "title": "中兴通讯研究快照",
        "summary": "需要继续核验利润和现金流。",
        "status": "completed",
        "generated_at": watching["report_meta"]["generated_at"],
        "market_timestamp": "2026-07-22T15:00:00+08:00",
        "source_scope": "server_evidence_snapshot",
        "source_scope_label": "服务器公共证据快照",
    }
    assert watching["report_freshness"] == {
        "status": "today",
        "label": "今日已更新",
        "is_today": True,
    }
    assert watching["next_action"] == {
        "title": "复核经营现金流",
        "next_step": "下一份财报披露后核对经营现金流与利润是否同步。",
        "status": "pending",
    }
    assert watching["open_task_count"] == 1
    assert watching["quote"] == {
        "price": 41.2,
        "pct_change": -1.5,
        "label": "最新报价",
        "market_timestamp": "2026-07-23T14:55:00+08:00",
        "status": "available",
        "currency": "CNY",
    }
    assert watching["position_snapshot"] == {
        "available": False,
        "status": "not_configured",
    }

    holding = by_symbol["300308.SZ"]
    assert holding["relation_type"] == "holding"
    assert holding["relation_label"] == "持仓"
    assert holding["priority"] is None
    assert holding["workflow_status"] == "waiting_data"
    assert holding["attention_tags"] == ["report_due"]

    ended_item = by_symbol["600519.SS"]
    assert ended_item["workspace_id"] == ended["id"]
    assert ended_item["relation_type"] == "ended"
    assert ended_item["relation_label"] == "已结束"
    assert ended_item["tracking_status"] == "paused"
    assert ended_item["active_thesis"]["summary"] == "关注需求和现金流"
    assert client.get("/me/watchlist").json()["items"] != payload["items"]


def test_stock_workspaces_are_user_isolated(app):
    owner = TestClient(app)
    _create_user(owner, "Stock Asset Private Owner")
    _add_stock(owner, "000063", "中兴通讯", "仅属于甲用户的判断")

    other = TestClient(app)
    _create_user(other, "Stock Asset Other")
    _add_stock(other, "300308", "中际旭创", "仅属于乙用户的判断")

    owner_payload = owner.get("/v1/stock-workspaces").json()
    other_payload = other.get("/v1/stock-workspaces").json()

    assert [item["symbol"] for item in owner_payload["items"]] == ["000063.SZ"]
    assert [item["symbol"] for item in other_payload["items"]] == ["300308.SZ"]
    assert "仅属于乙用户" not in str(owner_payload)
    assert "仅属于甲用户" not in str(other_payload)


def test_stock_workspaces_reports_are_scoped_without_global_top_limit_or_generation(
    app, monkeypatch
):
    client = TestClient(app)
    _create_user(client, "Scoped Report Owner")
    _add_stock(client, "000063", "中兴通讯", "仅跟踪自己的股票空间")
    app.state.database.create_research_report(
        symbol="000063.SZ",
        name="中兴通讯",
        title="我的关注股票快照",
        summary="当前用户范围内必须稳定出现。",
        body="证据正文",
        status="completed",
        fingerprint="scoped-report",
        evidence={},
        run_id=None,
        market_timestamp="2026-07-23T15:00:00+08:00",
    )
    for index in range(25):
        app.state.database.create_research_report(
            symbol=f"NOISE{index:02d}",
            name=f"非自选{index:02d}",
            title=f"非自选报告{index:02d}",
            summary="不应进入当前用户资产列表。",
            body="公共报告正文",
            status="completed",
            fingerprint=f"noise-{index}",
            evidence={},
            run_id=None,
            market_timestamp="2026-07-23T15:00:00+08:00",
        )

    def unexpected_generate(*args, **kwargs):
        raise AssertionError("GET /v1/stock-workspaces must not generate reports")

    monkeypatch.setattr(app.state.research_reports, "generate", unexpected_generate)
    response = client.get("/v1/stock-workspaces")

    assert response.status_code == 200
    payload = response.json()
    assert [item["symbol"] for item in payload["items"]] == ["000063.SZ"]
    assert payload["items"][0]["report_meta"]["title"] == "我的关注股票快照"
    assert "非自选" not in str(payload)


def test_stock_asset_latest_change_keeps_user_read_and_relevance_state(app):
    client = TestClient(app)
    user = _create_user(client, "Daily Change Owner")
    _add_stock(client, "000063", "中兴通讯", "核验价格异常")
    app.state.database.upsert_change_event(
        symbol="000063.SZ",
        event_type="daily_price_anomaly",
        title="中兴通讯完整日线变化",
        fact_summary="最近完整日线变化达到白名单阈值。",
        occurred_at="2026-07-23T15:00:00+08:00",
        detected_at="2026-07-24T01:00:00+00:00",
        source_name="Test verified daily source",
        source_url="https://example.invalid/daily",
        data_status="confirmed_daily_bar",
        rule_version=app.state.change_events.PRICE_RULE_VERSION,
        dedupe_hash="stock-asset-user-state",
        payload={
            "name": "中兴通讯",
            "daily_date": "2026-07-23",
            "return_1d_pct": 5.5,
        },
    )
    app.state.database.ensure_user_change_links(user["id"], "000063.SZ")

    first = client.get("/v1/stock-workspaces").json()["items"][0]["latest_change"]
    assert first["link_id"]
    assert first["read_at"] is None
    assert first["relevance_status"] == "pending"

    assert client.post(f"/v1/user-changes/{first['link_id']}/read").status_code == 200
    relevant = client.post(
        f"/v1/user-changes/{first['link_id']}/relevance",
        json={"relevance_status": "relevant"},
    )
    assert relevant.status_code == 200
    refreshed = client.get("/v1/stock-workspaces").json()["items"][0]["latest_change"]
    assert refreshed["read_at"]
    assert refreshed["handled_at"]
    assert refreshed["relevance_status"] == "relevant"


def test_daily_watchlist_chat_uses_rich_scoped_evidence_and_time_contract(app):
    client = TestClient(app)
    user = _create_user(client, "Daily Hermes Contract")
    _add_stock(client, "000063", "中兴通讯", "关注利润兑现与经营现金流")
    app.state.database.create_research_report(
        symbol="000063.SZ",
        name="中兴通讯",
        title="中兴通讯服务器快照",
        summary="服务器证据摘要",
        body="服务器报告正文不应被直接回放。",
        status="degraded",
        fingerprint="daily-hermes-contract",
        evidence={
            "display_name": "中兴通讯",
            "current_quote": {
                "name": "中兴通讯",
                "price": 35.49,
                "pct_change": -1.2,
                "currency": "CNY",
                "quote_label": "盘中最新报价",
                "quote_basis": "intraday_snapshot",
                "market_timestamp": "2026-07-24T09:44:21+08:00",
            },
            "metrics": {"latest_close": 35.92, "return_1d_pct": -4.21},
            "fundamentals": {
                "summary": {
                    "latest_report": {
                        "report_date": "2026-03-31",
                        "revenue_yoy_pct": 6.13,
                    }
                }
            },
            "provenance": {"market_timestamp": "2026-07-23T15:00:00+08:00"},
        },
        run_id=None,
        market_timestamp="2026-07-23T15:00:00+08:00",
    )

    response = client.post(
        "/me/chat",
        json={
            "message": (
                "请生成我的自选股每日研究摘要，并列出今天要复核的研究任务。"
            ),
            "execute_agent": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"] == "watchlist_brief"
    assert payload["evidence"]["answer_contract"]["report_scope"] == (
        "server_public_evidence_snapshot_only"
    )
    assert len(payload["evidence"]["research_assets"]) == 1
    asset = payload["evidence"]["research_assets"][0]
    assert asset["symbol"] == "000063.SZ"
    assert asset["report_meta"]["status"] == "degraded"
    assert asset["report_meta"]["source_scope"] == "server_evidence_snapshot"
    assert asset["data_times"]["financial_report_period"] == "2026-03-31"
    prompt_path = (
        Path(app.state.database.get_user(user["id"])["workspace_path"])
        / "runs"
        / payload["run_id"]
        / "prompt.md"
    )
    prompt = prompt_path.read_text(encoding="utf-8")
    assert "自选股每日研究摘要的时间与证据合同" in prompt
    assert "不得用单一“数据截止时间”代替多个时间字段" in prompt


def test_one_stock_workspace_failure_does_not_break_the_asset_list(app, monkeypatch):
    client = TestClient(app)
    _create_user(client, "Stock Asset Partial")
    _add_stock(client, "000063", "中兴通讯", "关注利润质量")
    _add_stock(client, "300308", "中际旭创", "关注需求变化")

    original = app.state.stock_workspace.get_workspace

    def flaky_workspace(user_id: str, symbol: str):
        if symbol == "300308.SZ":
            raise RuntimeError("one stock failed")
        return original(user_id, symbol)

    monkeypatch.setattr(app.state.stock_workspace, "get_workspace", flaky_workspace)
    response = client.get("/v1/stock-workspaces")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "partial"
    assert payload["summary"]["total"] == 2
    by_symbol = {item["symbol"]: item for item in payload["items"]}
    assert by_symbol["300308.SZ"]["data_status"] == "partial"
    assert by_symbol["300308.SZ"]["quote"]["status"] == "unavailable"
    assert by_symbol["300308.SZ"]["warnings"] == [
        "该股票的行情或研究摘要暂未完整返回"
    ]
    assert by_symbol["000063.SZ"]["warnings"] == []
