from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from app.providers.shareholders import AShareShareholderProvider
from app.services.research_reports import ResearchReportService


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_provider_parses_holder_history_and_falls_back_to_latest_top10_report():
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs["params"]))
        if url.endswith("/api/data/v1/get"):
            return FakeResponse(
                {
                    "result": {
                        "data": [
                            {
                                "SECURITY_CODE": "000063",
                                "SECURITY_NAME_ABBR": "中兴通讯",
                                "END_DATE": "2026-07-10 00:00:00",
                                "PRE_END_DATE": "2026-06-30 00:00:00",
                                "HOLD_NOTICE_DATE": "2026-07-13 00:00:00",
                                "HOLDER_NUM": "575136",
                                "PRE_HOLDER_NUM": "635176",
                                "HOLDER_NUM_CHANGE": "-60040",
                                "HOLDER_NUM_RATIO": "-9.452498205222",
                                "AVG_HOLD_NUM": "7003.61714968286",
                                "AVG_MARKET_CAP": "283856.603076646",
                                "INTERVAL_CHRATE": "11.99226306",
                                "TOTAL_MARKET_CAP": "163256151267.09",
                                "TOTAL_A_SHARES": "4028032353",
                            }
                        ]
                    }
                }
            )
        if kwargs["params"]["date"] == "2026-06-30":
            return FakeResponse({"sdgd": []})
        return FakeResponse(
            {
                "sdgd": [
                    {
                        "END_DATE": "2026-03-31 00:00:00",
                        "HOLDER_RANK": 1,
                        "HOLDER_NAME": "中兴新通讯有限公司",
                        "SHARES_TYPE": "流通A股,流通H股",
                        "HOLD_NUM": 960978400,
                        "HOLD_NUM_RATIO": 20.09,
                        "HOLD_NUM_CHANGE": "不变",
                        "CHANGE_RATIO": None,
                    },
                    {
                        "END_DATE": "2026-03-31 00:00:00",
                        "HOLDER_RANK": 2,
                        "HOLDER_NAME": "香港中央结算代理人有限公司",
                        "SHARES_TYPE": "流通H股",
                        "HOLD_NUM": 752419722,
                        "HOLD_NUM_RATIO": 15.73,
                        "HOLD_NUM_CHANGE": "30547",
                        "CHANGE_RATIO": 0.00406,
                    },
                ]
            }
        )

    packet = AShareShareholderProvider(
        http_get=fake_get,
        today_fn=lambda: date(2026, 7, 21),
    ).fetch("000063")

    assert packet["symbol"] == "000063.SZ"
    assert packet["holder_history"][0]["holder_count"] == 575136
    assert packet["holder_history"][0]["holder_count_change_pct"] == pytest.approx(
        -9.452498205222
    )
    assert packet["top10_report_date"] == "2026-03-31"
    assert packet["top_holders"][0]["holding_ratio_pct"] == pytest.approx(20.09)
    attempted = [params.get("date") for _, params in calls if params.get("date")]
    assert attempted[:2] == ["2026-06-30", "2026-03-31"]


def test_shareholder_service_persists_snapshot_and_long_term_knowledge(app):
    packet = app.state.shareholders.refresh_symbol("000063.SZ")

    assert packet["status"] == "available"
    assert packet["holder_count_signal"] == "concentration_clue"
    assert packet["holder_count_streak_direction"] == "decrease"
    assert packet["holder_count_streak_count"] == 3
    assert packet["recent_pattern"] == "最近 3 次披露的股东户数连续下降。"
    assert packet["top10_ratio_pct"] == pytest.approx(36.96)
    assert packet["top3_ratio_pct"] == pytest.approx(36.96)
    assert packet["top10_historical_comparison_available"] is False
    assert "不能证明机构吸筹" in packet["holder_count_statement"]
    assert any("不能自动等同北向资金" in item for item in packet["special_name_notes"])

    with app.state.database.connect() as connection:
        row = connection.execute(
            """
            SELECT holder_count, change_pct, top10_report_date, top10_ratio
            FROM shareholder_structure_snapshots WHERE symbol = ?
            """,
            ("000063.SZ",),
        ).fetchone()
    assert tuple(row) == (575136, -9.452498, "2026-03-31", 36.96)

    document = next(
        item
        for item in app.state.database.list_knowledge_documents(
            None, include_content=True
        )
        if item["source_key"] == "shareholder-structure:000063.SZ"
    )
    assert "股东户数历史" in document["content"]
    assert "中兴新通讯有限公司" in document["content"]
    assert "不能自动等同北向资金" in document["content"]
    assert "不等于机构吸筹" in document["content"]


def test_shareholder_api_chat_routing_followup_and_skill(client, app):
    user = client.post("/users", json={"name": "Shareholder User"})
    assert user.status_code == 201

    endpoint = client.get("/a-share/000063.SZ/shareholders")
    assert endpoint.status_code == 200
    assert endpoint.json()["holder_count_as_of"] == "2026-07-10"

    first = client.post(
        "/me/chat",
        json={"message": "中兴通讯股东户数怎么变了", "execute_agent": False},
    )
    assert first.status_code == 200
    payload = first.json()
    assert payload["intent"] == "shareholder_structure"
    assert "575136" in payload["answer"] or "575,136" in payload["answer"]
    assert "机构吸筹" in payload["answer"]
    assert "不能证明" in payload["answer"]

    followup = client.post(
        "/me/chat",
        json={
            "message": "那十大股东是谁？",
            "conversation_id": payload["conversation_id"],
            "execute_agent": False,
        },
    )
    assert followup.status_code == 200
    assert followup.json()["intent"] == "shareholder_structure"
    assert "中兴新通讯有限公司" in followup.json()["answer"]
    assert "2026-03-31" in followup.json()["answer"]

    run = app.state.database.get_run(payload["run_id"], user.json()["id"])
    assert run is not None
    prompt = (
        Path(app.state.database.get_user(user.json()["id"])["workspace_path"])
        / "runs"
        / payload["run_id"]
        / "prompt.md"
    ).read_text(encoding="utf-8")
    assert "# Shareholder Structure" in prompt
    assert "股东户数历史" in prompt
    assert "中兴新通讯有限公司" in prompt


def test_non_a_share_shareholder_request_is_honestly_scoped(client):
    assert client.post("/users", json={"name": "US Holder User"}).status_code == 201

    response = client.post(
        "/me/chat",
        json={"message": "英伟达机构持仓有什么变化", "execute_agent": False},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"] == "clarification"
    assert "13F" in payload["answer"]


def test_research_report_fingerprint_changes_with_shareholder_structure():
    base = {
        "symbol": "000063.SZ",
        "provenance": {"market_timestamp": "2026-07-20T15:00:00+08:00"},
        "shareholder_structure": {
            "holder_count_as_of": "2026-07-10",
            "holder_count": 575136,
            "holder_count_change_pct": -9.452498,
            "top10_report_date": "2026-03-31",
            "top10_ratio_pct": 36.96,
            "top_holders": [],
        },
    }
    changed = {
        **base,
        "shareholder_structure": {
            **base["shareholder_structure"],
            "holder_count": 600000,
        },
    }

    assert ResearchReportService._fingerprint(base) != ResearchReportService._fingerprint(
        changed
    )
