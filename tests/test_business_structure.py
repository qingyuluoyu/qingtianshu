from __future__ import annotations

from pathlib import Path

import pytest

from app.providers.business_structure import AShareBusinessStructureProvider
from app.services.research_reports import ResearchReportService


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_provider_parses_business_composition_and_percent_units():
    seen = {}

    def fake_get(url, **kwargs):
        seen["url"] = url
        seen.update(kwargs)
        return FakeResponse(
            {
                "zygcfx": [
                    {
                        "REPORT_DATE": "2025-12-31 00:00:00",
                        "MAINOP_TYPE": "2",
                        "ITEM_NAME": "运营商网络",
                        "MAIN_BUSINESS_INCOME": "46944800000",
                        "MBI_RATIO": "0.469448",
                        "MAIN_BUSINESS_COST": "22000000000",
                        "MBC_RATIO": "0.44",
                        "MAIN_BUSINESS_RPOFIT": "24944800000",
                        "MBR_RATIO": "0.7",
                        "GROSS_RPOFIT_RATIO": "0.53137",
                    },
                    {
                        "REPORT_DATE": "bad-date",
                        "MAINOP_TYPE": "2",
                        "ITEM_NAME": "无效行",
                    },
                ]
            }
        )

    packet = AShareBusinessStructureProvider(http_get=fake_get).fetch("000063")

    assert seen["url"].endswith("/BusinessAnalysis/PageAjax")
    assert seen["params"] == {"code": "SZ000063"}
    assert seen["timeout"] == 20
    assert packet["coverage"]["rows"] == 1
    row = packet["rows"][0]
    assert row["symbol"] == "000063.SZ"
    assert row["classification"] == "product"
    assert row["revenue_share_pct"] == pytest.approx(46.9448)
    assert row["gross_margin_pct"] == pytest.approx(53.137)


def test_service_separates_latest_revenue_and_margin_reference(app):
    refreshed = app.state.business_structure.refresh_symbol("000063.SZ")
    packet = app.state.business_structure.get_packet("000063.SZ")

    assert refreshed["rows_saved"] == 22
    assert packet["status"] == "available"
    assert packet["anchor_report_date"] == "2025-12-31"
    assert packet["latest_fetched_at"] == "2026-07-20T18:40:00+00:00"
    assert packet["sources"][0]["source"] == "Fake business composition"

    product = next(
        item for item in packet["dimensions"] if item["classification"] == "product"
    )
    assert product["current_report_date"] == "2025-12-31"
    assert product["comparable_report_date"] == "2024-12-31"
    assert product["segments"][0]["item_name"] == "运营商网络"
    assert product["segments"][0]["revenue_share_change_pp"] == pytest.approx(-12.0)
    assert product["margin_coverage"] == {"available": 0, "total": 3}
    assert product["margin_reference"]["current_report_date"] == "2025-06-30"
    assert product["margin_reference"]["comparable_report_date"] == "2024-06-30"
    assert product["margin_reference"]["report_basis"] == "half_year_cumulative"
    assert product["margin_reference"]["segments"][0][
        "gross_margin_pct"
    ] == pytest.approx(53.0)
    assert any(
        item.get("report_date") == "2025-06-30"
        and "毛利率参考期" in item["statement"]
        for item in packet["key_changes"]
    )

    region = next(
        item for item in packet["dimensions"] if item["classification"] == "region"
    )
    asia = next(
        item for item in region["segments"] if item["item_name"] == "亚洲(不包括中国)"
    )
    assert asia["comparison_status"] == "matched"
    assert asia["comparable_revenue_share_pct"] == pytest.approx(13.0)
    assert {item["key"] for item in packet["coverage_limits"]} == {
        "regional_product_breakdown",
        "order_backlog",
        "external_policy_exposure",
    }
    assert all(item["next_evidence"] for item in packet["coverage_limits"])


def test_business_structure_persists_snapshot_and_long_term_knowledge(app):
    app.state.business_structure.refresh_symbol("000063.SZ")

    with app.state.database.connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM business_segment_rows WHERE symbol = ?",
            ("000063.SZ",),
        ).fetchone()[0] == 22
        assert connection.execute(
            "SELECT COUNT(*) FROM business_structure_snapshots WHERE symbol = ?",
            ("000063.SZ",),
        ).fetchone()[0] == 1

    document = next(
        item
        for item in app.state.database.list_knowledge_documents(
            None, include_content=True
        )
        if item["source_key"] == "business-structure:000063.SZ"
    )
    assert "毛利率独立参考期" in document["content"]
    assert "参考期：2025-06-30" in document["content"]
    assert "运营商网络：毛利率 53%" in document["content"]
    assert "53.000%" not in document["content"]
    assert "460 亿元" in document["content"]
    assert "仍待补证的研究维度" in document["content"]
    assert "主营收入构成不等于新增订单" in document["content"]


def test_business_structure_api_and_chat_routing(client, app):
    user = client.post("/users", json={"name": "Business Structure User"})
    assert user.status_code == 201

    endpoint = client.get("/a-share/000063.SZ/business-structure")
    assert endpoint.status_code == 200
    assert endpoint.json()["type"] == "business_structure"

    first = client.post(
        "/me/chat",
        json={"message": "中兴通讯靠什么业务赚钱", "execute_agent": False},
    )
    assert first.status_code == 200
    payload = first.json()
    assert payload["intent"] == "business_structure"
    assert payload["evidence"]["symbol"] == "000063.SZ"
    assert "运营商网络" in payload["answer"]
    assert "2025-06-30" in payload["answer"]
    assert "53%" in payload["answer"]
    assert "不能混写" in payload["answer"]

    followup = client.post(
        "/me/chat",
        json={
            "message": "那收入来自哪里",
            "conversation_id": payload["conversation_id"],
            "execute_agent": False,
        },
    )
    assert followup.status_code == 200
    assert followup.json()["intent"] == "business_structure"
    assert followup.json()["evidence"]["symbol"] == "000063.SZ"

    run = app.state.database.get_run(payload["run_id"], user.json()["id"])
    assert run is not None
    prompt = (
        Path(app.state.database.get_user(user.json()["id"])["workspace_path"])
        / "runs"
        / payload["run_id"]
        / "prompt.md"
    ).read_text()
    assert "# Business Structure" in prompt
    assert "2025-06-30" in prompt

    peer_comparison = client.post(
        "/me/chat",
        json={
            "message": (
                "中兴通讯与烽火通信、紫光股份、锐捷网络的同报告期经营差异是什么？"
                "请分别比较营收增速、利润增速、毛利率、经营现金流和主营构成。"
            ),
            "execute_agent": False,
        },
    )
    assert peer_comparison.status_code == 200
    comparison_payload = peer_comparison.json()
    assert comparison_payload["intent"] == "stock_research"
    operating = comparison_payload["evidence"]["peer_comparison"][
        "operating_comparison"
    ]
    assert operating["coverage"]["same_period_financial_peers"] == 3
    assert all(
        (item.get("business_profile") or {}).get("anchor_report_date")
        == "2025-12-31"
        for item in operating["peers"]
    )


def test_non_a_share_business_structure_requests_are_honestly_scoped(client):
    assert client.post("/users", json={"name": "US Segment User"}).status_code == 201

    response = client.post(
        "/me/chat",
        json={"message": "英伟达靠什么业务赚钱", "execute_agent": False},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"] == "clarification"
    assert "当前主营构成明细先覆盖 A 股" in payload["answer"]
    assert "SEC 分部披露" in payload["answer"]


def test_research_report_fingerprint_changes_with_business_structure():
    base = {
        "symbol": "000063.SZ",
        "provenance": {"market_timestamp": "2026-07-20T15:00:00+08:00"},
        "business_structure": {
            "anchor_report_date": "2025-12-31",
            "method": "deterministic_business_structure_v1",
            "dimensions": [{"classification": "product", "segments": []}],
            "key_changes": [],
        },
    }
    changed = {
        **base,
        "business_structure": {
            **base["business_structure"],
            "key_changes": [{"statement": "政企业务收入占比上升"}],
        },
    }

    assert ResearchReportService._fingerprint(base) != ResearchReportService._fingerprint(
        changed
    )
