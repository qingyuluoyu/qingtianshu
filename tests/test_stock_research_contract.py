from __future__ import annotations

from pathlib import Path
from typing import Any

from app.services.agent import AgentService
from app.services.agent_prompt_contracts import append_prompt_contracts
from app.services.stock_research_contract import (
    ONLINE_PATH,
    WATCHLIST_PATH,
    build_stock_research_contract,
)
from app.utils import utc_now


def _minimal_evidence(symbol: str, plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "stock_research",
        "generated_at": utc_now(),
        "symbol": symbol,
        "metrics": {
            "latest_close": 1500.0,
            "return_1d_pct": -1.0,
            "return_20d_pct": 2.0,
            "return_60d_pct": 3.0,
            "trend_state": "区间震荡",
            "volatility_20d_annualized_pct": 18.0,
            "max_drawdown_60d_pct": -8.0,
        },
        "research_plan": plan,
        "module_statuses": {
            "market": {
                "module": "market",
                "label": "价格与技术结构",
                "status": "fresh",
                "required": True,
            }
        },
        "provenance": {"market_timestamp": "2026-07-28T07:00:00+00:00"},
    }


def _saved_report_evidence() -> dict[str, Any]:
    return {
        "type": "stock_research",
        "symbol": "600519.SS",
        "metrics": {"latest_close": 1500.0},
        "provenance": {"market_timestamp": "2026-07-25T07:00:00+00:00"},
        "earnings_quality": {"status": "available"},
    }


def test_contract_selects_watchlist_preanalysis_or_online_research() -> None:
    report = {"id": "report-1", "evidence": _saved_report_evidence()}

    watchlist = build_stock_research_contract(
        watchlist_item={"symbol": "600519.SS"},
        latest_report=report,
    )
    online = build_stock_research_contract(
        watchlist_item=None,
        latest_report=report,
    )

    assert watchlist["path"] == WATCHLIST_PATH
    assert watchlist["skill_name"] == "watchlist-stock-research"
    assert watchlist["precomputed_report_reuse_allowed"] is True
    assert watchlist["force_online_refresh"] is False
    assert online["path"] == ONLINE_PATH
    assert online["skill_name"] == "online-stock-research"
    assert online["precomputed_report_reuse_allowed"] is False
    assert online["precomputed_report_available"] is False
    assert online["force_online_refresh"] is True
    assert online["precomputed_report_body_allowed"] is False


def test_non_watchlist_never_loads_existing_server_report(app, monkeypatch) -> None:
    user = app.state.database.create_user("Online stock research user")
    app.state.database.create_research_report(
        symbol="600519.SS",
        name="贵州茅台",
        title="贵州茅台服务器报告",
        summary="服务器摘要",
        body="这段预生成正文绝不能成为当前回答。",
        status="completed",
        fingerprint="online-path-report",
        evidence=_saved_report_evidence(),
        run_id=None,
        market_timestamp="2026-07-25T07:00:00+00:00",
    )
    captured: dict[str, Any] = {}

    def fake_build(user_id: str, symbol: str, **kwargs: Any) -> dict[str, Any]:
        captured.update({"user_id": user_id, "symbol": symbol, **kwargs})
        return _minimal_evidence(symbol, kwargs["plan"])

    monkeypatch.setattr(app.state.research_evidence, "build", fake_build)

    evidence = app.state.chat_stock_research_evidence.build(
        user_id=user["id"],
        symbol="600519.SS",
        message="分析贵州茅台",
        history=[],
        publish_progress=lambda *args, **kwargs: None,
    )

    contract = evidence["research_evidence_contract"]
    assert captured["reusable_evidence"] is None
    assert captured["reusable_generated_at"] is None
    assert captured["force_online_refresh"] is True
    assert captured["plan"]["evidence_path"] == ONLINE_PATH
    assert "online-stock-research" in captured["plan"]["selected_skills"]
    assert contract["path"] == ONLINE_PATH
    assert contract["precomputed_report_reference"] is None
    assert "precomputed_report" not in evidence
    assert "这段预生成正文" not in str(evidence)


def test_watchlist_path_can_reuse_versioned_modules_but_not_report_body(
    app, monkeypatch
) -> None:
    user = app.state.database.create_user("Watchlist stock research user")
    app.state.database.upsert_watchlist(
        user["id"],
        "600519.SS",
        "贵州茅台",
        "A股",
        "只关注现金流与渠道变化",
    )
    report = app.state.database.create_research_report(
        symbol="600519.SS",
        name="贵州茅台",
        title="贵州茅台服务器报告",
        summary="服务器摘要",
        body="这段预生成正文只能留在服务器报告中。",
        status="completed",
        fingerprint="watchlist-path-report",
        evidence=_saved_report_evidence(),
        run_id=None,
        market_timestamp="2026-07-25T07:00:00+00:00",
    )
    captured: dict[str, Any] = {}

    def fake_build(user_id: str, symbol: str, **kwargs: Any) -> dict[str, Any]:
        captured.update({"user_id": user_id, "symbol": symbol, **kwargs})
        packet = _minimal_evidence(symbol, kwargs["plan"])
        packet["earnings_quality"] = kwargs["reusable_evidence"][
            "earnings_quality"
        ]
        packet["module_statuses"]["earnings_quality"] = {
            "module": "earnings_quality",
            "label": "财报质量",
            "status": "reused",
            "required": False,
        }
        return packet

    monkeypatch.setattr(app.state.research_evidence, "build", fake_build)

    evidence = app.state.chat_stock_research_evidence.build(
        user_id=user["id"],
        symbol="600519.SS",
        message="分析贵州茅台",
        history=[],
        publish_progress=lambda *args, **kwargs: None,
    )

    contract = evidence["research_evidence_contract"]
    assert captured["reusable_evidence"] == report["evidence"]
    assert captured["force_online_refresh"] is False
    assert captured["plan"]["evidence_path"] == WATCHLIST_PATH
    assert "watchlist-stock-research" in captured["plan"]["selected_skills"]
    assert captured["plan"]["module_max_age_hours"]["event_timeline"] == 0
    assert contract["path"] == WATCHLIST_PATH
    assert contract["reused_modules"] == ["earnings_quality"]
    assert contract["precomputed_report_reference"]["report_id"] == report["id"]
    assert contract["precomputed_report_body_allowed"] is False
    assert "这段预生成正文" not in str(evidence)


def test_online_path_forces_dynamic_module_refresh(app, monkeypatch) -> None:
    service = app.state.research_evidence
    user = app.state.database.create_user("Online refresh user")
    captured: dict[str, Any] = {
        "china_refresh_ages": [],
        "fundamentals_refresh_ages": [],
    }
    original_china = service.china_info.get_packet
    original_fundamentals = service.fundamentals.get_packet
    original_events = service.event_timeline.get_packet

    def china_packet(symbol: str, refresh_max_age_seconds: int = 300):
        captured["china_refresh_ages"].append(refresh_max_age_seconds)
        return original_china(symbol, refresh_max_age_seconds)

    def fundamentals_packet(symbol: str, refresh_max_age_seconds: int = 600):
        captured["fundamentals_refresh_ages"].append(refresh_max_age_seconds)
        return original_fundamentals(symbol, refresh_max_age_seconds)

    def event_packet(symbol: str, *, refresh_sources: bool = True):
        captured["event_refresh_sources"] = refresh_sources
        return original_events(symbol, refresh_sources=refresh_sources)

    monkeypatch.setattr(service.china_info, "get_packet", china_packet)
    monkeypatch.setattr(service.fundamentals, "get_packet", fundamentals_packet)
    monkeypatch.setattr(service.event_timeline, "get_packet", event_packet)
    plan = {
        "focus": "price_action",
        "selected_modules": [
            "market",
            "company_information",
            "fundamentals",
            "event_timeline",
        ],
        "required_modules": [
            "market",
            "company_information",
            "fundamentals",
            "event_timeline",
        ],
        "module_max_age_hours": {},
    }

    evidence = service.build(
        user["id"],
        "600519.SS",
        plan=plan,
        force_online_refresh=True,
    )

    assert captured["china_refresh_ages"][0] == 0
    assert captured["fundamentals_refresh_ages"] == [0]
    assert captured["event_refresh_sources"] is True
    assert evidence["module_statuses"]["market"]["status"] == "fresh"
    assert evidence["module_statuses"]["company_information"]["status"] == "fresh"
    assert evidence["module_statuses"]["fundamentals"]["status"] == "fresh"
    assert evidence["module_statuses"]["event_timeline"]["status"] == "fresh"


def test_contract_reaches_compacted_prompt_and_persisted_run(app) -> None:
    user = app.state.database.create_user("Contract prompt user")
    contract = build_stock_research_contract(
        watchlist_item=None,
        latest_report=None,
    )
    plan = {
        "contract_version": "research_plan_v1",
        "focus": "price_action",
        "selected_modules": ["market"],
        "selected_skills": ["online-stock-research"],
        "evidence_contract_version": contract["contract_version"],
        "evidence_path": contract["path"],
    }
    evidence = {
        **_minimal_evidence("600519.SS", plan),
        "user_question": "贵州茅台为什么下跌",
        "research_evidence_contract": contract,
    }

    compact = AgentService._compact_stock_research_evidence(evidence)
    assert compact["research_evidence_contract"]["path"] == ONLINE_PATH
    assert compact["research_plan"]["evidence_path"] == ONLINE_PATH
    prompt = append_prompt_contracts(
        "基础提示",
        intent="stock_research",
        message=evidence["user_question"],
        evidence=evidence,
        prompt_evidence=compact,
        model_tier="economy",
        is_action_plan_request=False,
    )
    assert "非自选股在线研究要求" in prompt
    assert "禁止把数据库中碰巧存在的服务器预生成报告" in prompt

    run = app.state.agent.run(
        user=user,
        intent="stock_research",
        message=evidence["user_question"],
        evidence=evidence,
        model_tier="economy",
        execute_agent=False,
    )
    persisted = app.state.database.get_run(run["id"], user["id"])
    assert persisted["input"]["research_evidence_contract"]["path"] == ONLINE_PATH
    prompt_path = (
        Path(user["workspace_path"]) / "runs" / run["id"] / "prompt.md"
    )
    prompt_text = prompt_path.read_text(encoding="utf-8")
    assert "# Online Stock Research" in prompt_text
    assert "非自选股在线研究要求" in prompt_text
