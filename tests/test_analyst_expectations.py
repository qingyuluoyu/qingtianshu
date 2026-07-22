from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from app.providers.analyst_expectations import AShareAnalystExpectationsProvider
from app.services.agent import AgentService
from app.services.analysis import build_research_analysis_board
from app.services.research_reports import ResearchReportService
from app.services.research_tracking import build_research_change_payload


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_provider_parses_consensus_and_reports_without_target_prices():
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs["params"]))
        if "datacenter-web" in url:
            return FakeResponse(
                {
                    "result": {
                        "data": [
                            {
                                "SECURITY_CODE": "000063",
                                "SECURITY_NAME_ABBR": "中兴通讯",
                                "INDUSTRY_BOARD": "通信设备",
                                "RATING_ORG_NUM": "11",
                                "RATING_BUY_NUM": "9",
                                "RATING_ADD_NUM": "2",
                                "RATING_NEUTRAL_NUM": "0",
                                "RATING_REDUCE_NUM": "0",
                                "RATING_SALE_NUM": "0",
                                "YEAR1": "2025",
                                "YEAR_MARK1": "A",
                                "EPS1": "1.174391978465",
                                "YEAR2": "2026",
                                "YEAR_MARK2": "E",
                                "EPS2": "1.417363636364",
                                "YEAR3": "2027",
                                "YEAR_MARK3": "E",
                                "EPS3": "1.664545454545",
                                "TARGET_PRICE": "58.88",
                            }
                        ]
                    }
                }
            )
        return FakeResponse(
            {
                "currentYear": 2026,
                "data": [
                    {
                        "infoCode": "AN202607180001",
                        "title": "算力业务打开新空间",
                        "stockName": "中兴通讯",
                        "orgSName": "测试证券",
                        "publishDate": "2026-07-18 00:00:00",
                        "emRatingName": "买入",
                        "lastEmRatingName": "增持",
                        "indvInduName": "通信设备",
                        "researcher": "测试分析师",
                        "predictThisYearEps": "1.42",
                        "predictNextYearEps": "1.66",
                        "predictNextTwoYearEps": "1.78",
                        "predictThisYearPe": "31.2",
                        "indvAimPriceT": "60.00",
                    }
                ],
            }
        )

    packet = AShareAnalystExpectationsProvider(
        http_get=fake_get,
        today_fn=lambda: date(2026, 7, 21),
    ).fetch("000063")

    assert packet["symbol"] == "000063.SZ"
    assert packet["rating_organization_count"] == 11
    assert packet["rating_counts"] == {
        "buy": 9,
        "add": 2,
        "neutral": 0,
        "reduce": 0,
        "sell": 0,
    }
    assert packet["forecast_eps"][0] == {
        "year": 2025,
        "value": pytest.approx(1.174392),
        "kind": "actual",
    }
    assert packet["forecast_eps"][1]["kind"] == "estimate"
    report = packet["reports"][0]
    assert report["published_at"] == "2026-07-18"
    assert report["forecast_eps"][0] == {"year": 2026, "value": 1.42}
    assert not any("target" in key.casefold() or "aim" in key.casefold() for key in report)
    report_call = next(params for url, params in calls if "reportapi" in url)
    assert report_call["beginTime"] == "2025-01-17"
    assert report_call["endTime"] == "2026-07-22"


def test_service_persists_revisions_and_long_term_knowledge(app):
    service = app.state.analyst_expectations
    provider = service.provider

    first = service.refresh_symbol("000063.SZ")
    repeated = service.refresh_symbol("000063.SZ")

    assert first["status"] == "available"
    assert first["revision"]["available"] is False
    assert repeated["revision"]["available"] is False
    with app.state.database.connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM analyst_expectation_snapshots WHERE symbol = ?",
            ("000063.SZ",),
        ).fetchone()[0] == 1

    provider.estimate_2026 = 1.54
    provider.organization_count = 12
    second = service.refresh_symbol("000063.SZ")

    assert second["revision"]["available"] is True
    assert second["revision"]["organization_count_delta"] == 1
    revision = next(
        item
        for item in second["revision"]["eps_revisions"]
        if item["year"] == 2026
    )
    assert revision["direction"] == "up"
    assert revision["change"] == pytest.approx(0.14)
    assert revision["change_pct"] == pytest.approx(10.0)
    assert "2026E EPS较上一快照上修 10.00%" in second["revision"]["summary"]

    snapshots = app.state.database.list_analyst_expectation_snapshots(
        "000063.SZ", limit=10
    )
    assert len(snapshots) == 2
    document = next(
        item
        for item in app.state.database.list_knowledge_documents(
            None, include_content=True
        )
        if item["source_key"] == "analyst-expectations:000063.SZ"
    )
    assert "2025A：每股收益 1.17" in document["content"]
    assert "2026E：每股收益 1.54" in document["content"]
    assert "预测值不是公司正式指引" in document["content"]
    assert "2026E EPS较上一快照上修 10.00%" in document["content"]


def test_api_chat_followup_skill_and_frontend_entry(client, app):
    user_response = client.post("/users", json={"name": "Analyst Expectations User"})
    assert user_response.status_code == 201
    user = user_response.json()

    endpoint = client.get("/a-share/000063.SZ/analyst-expectations")
    assert endpoint.status_code == 200
    assert endpoint.json()["rating_organization_count"] == 11

    first = client.post(
        "/me/chat",
        json={"message": "中兴通讯一致预期怎么样？", "execute_agent": False},
    )
    assert first.status_code == 200
    payload = first.json()
    assert payload["intent"] == "analyst_expectations"
    assert payload["status"] == "preview"
    assert "2025A" in payload["answer"]
    assert "2026E" in payload["answer"]
    assert "尚不能判断上修或下修" in payload["answer"]
    assert "不是公司正式指引" in payload["answer"]

    prompt = (
        Path(app.state.database.get_user(user["id"])["workspace_path"])
        / "runs"
        / payload["run_id"]
        / "prompt.md"
    ).read_text()
    assert "# 分析师一致预期与研报跟踪" in prompt
    assert "只有 `revision.available=true` 时才能说一致预期上修或下修" in prompt

    followup = client.post(
        "/me/chat",
        json={
            "message": "最近上修了吗？",
            "conversation_id": payload["conversation_id"],
            "execute_agent": False,
        },
    )
    assert followup.status_code == 200
    assert followup.json()["intent"] == "analyst_expectations"
    assert followup.json()["evidence"]["symbol"] == "000063.SZ"
    assert "尚不能判断上修或下修" in followup.json()["answer"]

    advice_followup = client.post(
        "/me/chat",
        json={
            "message": "那这些评级能当买入建议吗？",
            "conversation_id": payload["conversation_id"],
            "execute_agent": False,
        },
    )
    assert advice_followup.status_code == 200
    assert advice_followup.json()["intent"] == "analyst_expectations"
    assert "不构成交易建议" in advice_followup.json()["answer"]

    clarification = client.post(
        "/me/chat",
        json={"message": "最新研报有哪些？", "execute_agent": False},
    )
    assert clarification.status_code == 200
    assert clarification.json()["intent"] == "clarification"
    assert "具体 A 股公司" in clarification.json()["answer"]

    page = client.get("/demo")
    assert page.status_code == 200
    assert "分析师预期" in page.text
    assert 'id="analystExpectationsAction"' in page.text
    assert '"analyst_expectations"' in page.text

    stock = client.post(
        "/me/chat",
        json={"message": "中兴通讯现在值得继续研究什么？", "execute_agent": False},
    )
    assert stock.status_code == 200
    assert stock.json()["intent"] == "stock_research"
    assert stock.json()["evidence"]["analyst_expectations"]["status"] == "available"
    assert "分析师预期" in stock.json()["answer"]


def test_guard_blocks_revision_claim_without_history():
    evidence = {
        "type": "analyst_expectations",
        "rating_organization_count": 11,
        "rating_counts": {"buy": 9, "add": 2},
        "forecast_eps": [
            {"year": 2026, "value": 1.4, "kind": "estimate"},
        ],
        "revision": {"available": False},
    }

    safe = AgentService._validate_model_output(
        "是否上修？当前没有历史快照，尚不能判断EPS上修或下修。"
        "不同机构的预测差异不能混用为上修或下修证据。"
        "样本中买入评级9家，但不构成交易建议。",
        evidence,
    )
    invalid = AgentService._validate_model_output(
        "2026E EPS已经上修至1.4。",
        evidence,
    )

    assert safe["passed"] is True
    assert invalid["passed"] is False
    assert invalid["unsupported_market_inferences"] == [
        "缺少历史一致预期快照时不能声称EPS已经上修或下修"
    ]

    unsafe_rating = AgentService._validate_model_output(
        "清数智算给予买入评级。",
        evidence,
    )
    assert unsafe_rating["passed"] is False
    assert unsafe_rating["prohibited_patterns"] == [
        "无研报样本语境的买入或卖出评级"
    ]


def test_analysis_board_and_report_fingerprint_include_analyst_expectations():
    base = {
        "symbol": "000063.SZ",
        "metrics": {"latest_close": 42.0},
        "fundamentals": {"summary": {"latest_report": {"report_date": "2025-12-31"}}},
        "analyst_expectations": {
            "status": "available",
            "as_of_date": "2026-07-18",
            "rating_organization_count": 11,
            "rating_counts": {"buy": 9, "add": 2},
            "forecast_eps": [
                {"year": 2026, "value": 1.4, "kind": "estimate"}
            ],
            "latest_reports": [
                {
                    "title": "算力业务打开新空间",
                    "institution": "测试证券",
                    "published_at": "2026-07-18",
                    "rating": "买入",
                }
            ],
            "revision": {"available": False},
        },
    }
    changed = {
        **base,
        "analyst_expectations": {
            **base["analyst_expectations"],
            "forecast_eps": [
                {"year": 2026, "value": 1.54, "kind": "estimate"}
            ],
            "revision": {
                "available": True,
                "organization_count_delta": 1,
                "eps_revisions": [
                    {
                        "year": 2026,
                        "current": 1.54,
                        "previous": 1.4,
                        "direction": "up",
                    }
                ],
            },
        },
    }

    board = build_research_analysis_board(base)
    module = next(
        item for item in board["modules"] if item["key"] == "analyst_expectations"
    )
    assert module["status"] == "ready"
    assert module["evidence_count"] == 3
    assert any(
        "同财年EPS一致预期" in item
        for item in board["tracking_plan"][2]["checks"]
    )
    assert ResearchReportService._fingerprint(base) != ResearchReportService._fingerprint(
        changed
    )


def test_research_tracking_records_expectation_revision_and_dynamic_module_count():
    previous = {
        "id": "previous-report",
        "symbol": "000063.SZ",
        "name": "中兴通讯",
        "generated_at": "2026-07-20T08:00:00+00:00",
        "evidence": {
            "metrics": {},
            "analyst_expectations": {
                "forecast_eps": [
                    {"year": 2026, "value": 1.4, "kind": "estimate"}
                ]
            },
            "analysis_board": {
                "ready_modules": 5,
                "total_modules": 7,
                "tracking_plan": [],
            },
        },
    }
    current = {
        "id": "current-report",
        "symbol": "000063.SZ",
        "name": "中兴通讯",
        "generated_at": "2026-07-21T08:00:00+00:00",
        "evidence": {
            "metrics": {},
            "analyst_expectations": {
                "forecast_eps": [
                    {"year": 2026, "value": 1.54, "kind": "estimate"}
                ],
                "revision": {
                    "summary": "2026E EPS较上一快照上修 10.00%",
                    "organization_count_delta": 1,
                },
            },
            "analysis_board": {
                "ready_modules": 6,
                "total_modules": 7,
                "tracking_plan": [],
            },
        },
    }

    payload = build_research_change_payload(current, previous)

    expectation_change = next(
        item
        for item in payload["changes"]
        if item["dimension"] == "analyst_expectations"
    )
    assert "2026E EPS较上一快照上修 10.00%" in expectation_change["detail"]
    assert "覆盖机构数较上一快照增加1家" in expectation_change["detail"]
    coverage_change = next(
        item for item in payload["changes"] if item["dimension"] == "coverage"
    )
    assert "5/7变为6/7" in coverage_change["detail"]
