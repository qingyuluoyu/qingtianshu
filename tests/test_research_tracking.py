from __future__ import annotations

from app.db import Database
from app.services.research_tracking import build_research_change_payload


def _report(report_id: str, evidence: dict, generated_at: str) -> dict:
    return {
        "id": report_id,
        "symbol": "000063.SZ",
        "name": "中兴通讯",
        "generated_at": generated_at,
        "market_timestamp": generated_at,
        "evidence": evidence,
    }


def test_research_change_payload_detects_risk_and_new_evidence():
    previous = _report(
        "old",
        {
            "metrics": {
                "trend_state": "趋势分化",
                "technical_state": "技术分化",
                "return_20d_pct": 2.0,
                "volatility_20d_annualized_pct": 25.0,
                "max_drawdown_60d_pct": -8.0,
            },
            "a_share_information": {
                "announcements": [{"title": "旧公告", "url": "old"}],
                "sentiment": {"band": "中性"},
            },
            "conditional_outlook": {"label": "震荡观察", "confidence": "medium"},
            "analysis_board": {"ready_modules": 5, "tracking_plan": []},
        },
        "2026-07-18T00:00:00+00:00",
    )
    current = _report(
        "new",
        {
            "metrics": {
                "latest_close": 42.0,
                "trend_state": "中期偏弱",
                "technical_state": "动量转弱",
                "return_20d_pct": -6.0,
                "volatility_20d_annualized_pct": 36.0,
                "max_drawdown_60d_pct": -13.0,
                "rsi_14": 34.0,
            },
            "a_share_information": {
                "announcements": [
                    {"title": "新一期业绩预告", "url": "new"},
                    {"title": "旧公告", "url": "old"},
                ],
                "news": [
                    {"title": "某公募基金季度净值大涨", "url": "irrelevant"},
                    {"title": "中兴通讯发布新一代核心网产品", "url": "relevant"},
                ],
                "sentiment": {"band": "轻微偏空"},
            },
            "conditional_outlook": {"label": "偏弱观察", "confidence": "low"},
            "analysis_board": {
                "ready_modules": 6,
                "tracking_plan": [
                    {"horizon_sessions": 3, "checks": ["复核公告与价格结构"]}
                ],
            },
        },
        "2026-07-21T00:00:00+00:00",
    )

    payload = build_research_change_payload(current, previous)

    assert payload["event_type"] == "evidence_change"
    assert payload["severity"] == "attention"
    assert any(item["label"] == "60日最大回撤" for item in payload["changes"])
    assert any(item["title"] == "新一期业绩预告" for item in payload["new_evidence"])
    assert any("中兴通讯" in item["title"] for item in payload["new_evidence"])
    assert all("公募基金" not in item["title"] for item in payload["new_evidence"])
    assert payload["next_review"]["horizon_sessions"] == 3
    assert "交易指令" in payload["boundary"]


def test_generated_report_enters_change_archive_and_common_knowledge(client, app):
    user = client.post("/users", json={"name": "网页体验用户"}).json()

    report_response = client.get("/research-reports/000063")
    assert report_response.status_code == 200

    changes = client.get(
        "/me/research-changes", params={"symbol": "000063", "limit": 10}
    )
    assert changes.status_code == 200
    packet = changes.json()
    assert packet["type"] == "research_tracking"
    assert packet["symbol"] == "000063.SZ"
    assert packet["coverage"]["with_report"] == 1
    assert packet["coverage"]["with_change_archive"] == 1
    assert packet["events"][0]["event_type"] == "baseline"

    watchlist = client.get("/me/watchlist/brief").json()
    item = next(item for item in watchlist["items"] if item["symbol"] == "000063.SZ")
    assert item["latest_change"]["summary"]
    assert item["metrics"]["rsi_14"] is not None
    assert item["metrics"]["macd_histogram"] is not None

    chat = client.post(
        "/me/chat",
        json={"message": "中兴通讯最近有什么变化", "execute_agent": False},
    )
    assert chat.status_code == 200
    payload = chat.json()
    assert payload["intent"] == "research_tracking"
    assert payload["evidence"]["symbol"] == "000063.SZ"
    assert "长期研究" in payload["answer"] or "研究基线" in payload["answer"]

    coverage_chat = client.post(
        "/me/chat",
        json={
            "message": (
                "请更新中兴通讯的六维证据覆盖，重点说明新增证据、"
                "反方证据、失效条件和下一步核验，不给出买卖建议。"
            ),
            "execute_agent": False,
        },
    )
    assert coverage_chat.status_code == 200
    coverage_payload = coverage_chat.json()
    assert coverage_payload["intent"] == "stock_research"
    coverage = coverage_payload["evidence"]["deep_stock_coverage"]
    assert coverage["summary"]["total"] == 6
    assert {item["label"] for item in coverage["dimensions"]} == {
        "公司经营",
        "财务质量",
        "行业与相对表现",
        "估值",
        "技术状态",
        "风险事件",
    }
    for heading in ("六维证据覆盖", "反方证据", "失效条件", "下一步核验"):
        assert heading in coverage_payload["answer"]
    for label in ("公司经营", "财务质量", "行业与相对表现", "估值", "技术状态", "风险事件"):
        assert label in coverage_payload["answer"]
    assert "+00:00" not in coverage_payload["answer"]

    documents = app.state.database.list_knowledge_documents(
        user["id"], include_content=True
    )
    archive = next(
        item for item in documents if item["source_key"] == "research-report:000063.SZ"
    )
    assert "中兴通讯长期研究档案" in archive["title"]
    assert "最新证据变化" in archive["content"]
    assert "研究边界" in archive["content"]


def test_research_refresh_ignores_editor_pollution_but_keeps_user_targets(
    client, app, monkeypatch
):
    database = app.state.database
    service = app.state.research_reports
    user = client.post("/users", json={"name": "真实自选股用户"}).json()

    database.upsert_watchlist(
        Database.SYSTEM_EDITOR_ID,
        "T",
        "错误路由遗留标的",
        "US",
        "不应进入后台长期研究",
    )
    database.upsert_watchlist(
        user["id"],
        "600000.SS",
        "浦发银行",
        "CN",
        "普通用户真实关注",
    )

    requested: list[str] = []

    def fake_generate(symbol: str, execute_agent: bool = False, force: bool = False):
        requested.append(symbol)
        return {
            "decision": "unchanged",
            "report": {"id": f"report-{symbol}"},
        }

    monkeypatch.setattr(service, "generate", fake_generate)
    result = service.refresh_targets()

    assert "T" not in requested
    assert "600000.SS" in requested
    assert set(app.state.settings.default_research_symbols).issubset(requested)
    assert result["requested"] == len(requested)


def test_ad_hoc_report_does_not_turn_into_editor_watchlist_target(app):
    database = app.state.database
    service = app.state.research_reports

    assert database.get_watchlist_item(Database.SYSTEM_EDITOR_ID, "T") is None

    service.generate("T", execute_agent=False)

    assert database.get_watchlist_item(Database.SYSTEM_EDITOR_ID, "T") is None
