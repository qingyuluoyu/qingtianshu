from __future__ import annotations

from app.services.research_claims import build_research_claim_ledger


def test_claim_ledger_links_relations_sources_times_and_invalidations():
    evidence = {
        "generated_at": "2026-07-22T16:00:00+08:00",
        "provenance": {
            "market_timestamp": "2026-07-21T15:00:00+08:00",
            "source": "历史日线源",
            "source_url": "https://example.invalid/daily",
        },
        "current_quote": {
            "market_timestamp": "2026-07-22T14:55:00+08:00",
            "source": "确定性行情源",
            "source_url": "https://example.invalid/quote",
            "fetched_at": "2026-07-22T14:55:05+08:00",
        },
        "fundamentals": {
            "generated_at": "2026-07-22T12:00:00+08:00",
            "summary": {
                "latest_report": {
                    "report_date": "2026-03-31",
                    "announcement_date": "2026-04-25",
                    "source_url": "https://example.invalid/report",
                }
            },
        },
        "event_timeline": {
            "generated_at": "2026-07-22T12:30:00+08:00",
            "risk_events": [
                {
                    "title": "季度报告风险事项",
                    "published_at": "2026-04-25T00:00:00+08:00",
                    "source": "交易所公告",
                    "url": "https://example.invalid/notice",
                }
            ],
        },
        "evidence_debate": {
            "bull_case": [
                {
                    "claim": "近20日价格动量为正",
                    "evidence": "20日收益 8.0%",
                    "source": "deterministic_price_metrics",
                }
            ],
            "bear_case": [
                {
                    "claim": "最新报告期净利润同比下降",
                    "evidence": "2026年一季度净利润同比 -12.0%",
                    "source": "structured_fundamentals",
                }
            ],
            "risk_committee": [
                {
                    "risk": "官方事件可能影响原研究假设",
                    "evidence": "2026-04-25｜风险事项｜季度报告风险事项",
                    "action": "阅读公告原文并交叉核验。",
                }
            ],
        },
        "research_frame": {
            "missing_information": ["核验下一报告期经营现金流是否改善"]
        },
        "conditional_outlook": {
            "invalidation": "价格跨越关键参考位后必须重算当前判断。",
            "scenarios": [
                {
                    "name": "下行风险",
                    "condition": "收盘跌破关键参考位且现金流继续恶化",
                    "meaning": "原判断需要失效处理，优先复核风险与仓位纪律。",
                }
            ],
        },
    }

    ledger = build_research_claim_ledger(evidence)
    repeated = build_research_claim_ledger(evidence)

    assert ledger["method"] == "structured_claim_ledger_v1"
    assert ledger["summary"] == {
        "supports": 1,
        "weakens": 1,
        "unresolved": 1,
        "information_gaps": 1,
        "invalidation_conditions": 2,
    }
    assert [item["id"] for item in ledger["claims"]] == [
        item["id"] for item in repeated["claims"]
    ]
    price = ledger["claims"][0]
    assert price["relation"] == "supports"
    assert price["source_name"] == "历史日线源"
    assert price["source_url"] == "https://example.invalid/daily"
    assert price["trade_date"] == "2026-07-21"
    assert price["coverage_status"] == "sufficient"
    financial = ledger["claims"][1]
    assert financial["relation"] == "weakens"
    assert financial["report_period"] == "2026-03-31"
    assert financial["source_url"] == "https://example.invalid/report"
    event = ledger["claims"][2]
    assert event["relation"] == "unresolved"
    assert event["source_name"] == "交易所公告"
    assert event["source_url"] == "https://example.invalid/notice"
    assert event["next_step"] == "阅读公告原文并交叉核验。"
    assert ledger["strongest_counterevidence"]["id"] == financial["id"]
    assert ledger["information_gaps"][0]["related_claim_ids"] == [event["id"]]
    assert ledger["invalidation_conditions"][0]["related_claim_ids"] == [
        price["id"]
    ]
    assert "仓位" not in str(ledger["invalidation_conditions"])
    assert "未来涨跌概率" in ledger["boundary"]
