from __future__ import annotations

import app.services.agent as agent_module
from app.services.agent import AgentService
from app.services.agent_evidence_compaction import (
    compact_market_brief_evidence,
    compact_market_conversation_history,
    compact_stock_knowledge_context,
    compact_stock_research_evidence,
    compact_stock_specialist_evidence,
    evidence_for_prompt,
)


def test_market_compaction_preserves_explicit_session_alignment() -> None:
    compact = compact_market_brief_evidence(
        {
            "type": "market_brief",
            "user_question": "美股为什么收盘跌了",
            "analysis_target": {
                "market_date": "2025-04-09",
                "market_key": "us",
            },
            "question_focus": {"key": "market_cause"},
            "market_drivers": {
                "market_key": "us",
                "question_focus": "market_cause",
            },
            "indices": [
                {
                    "symbol": "^GSPC",
                    "name": "标普500",
                    "group": "us",
                    "market_date": "2025-04-09",
                    "market_timestamp": "2025-04-10T00:00:00+00:00",
                    "same_date_as_analysis_target": True,
                    "coverage": {"interval": "1d"},
                    "metrics": {"return_1d_pct": 0.313},
                }
            ],
        }
    )

    assert compact["indices"] == [
        {
            "symbol": "^GSPC",
            "name": "标普500",
            "same_date_as_analysis_target": True,
            "market_date": "2025-04-09",
            "metrics": {"return_1d_pct": 0.313},
        }
    ]


def test_market_compaction_keeps_newer_breadth_for_explicit_today_vs_yesterday() -> None:
    compact = compact_market_brief_evidence(
        {
            "type": "market_brief",
            "user_question": "今天A股普涨，但昨天指数很弱，怎么理解？",
            "analysis_target": {"market_date": "2026-07-30", "market_key": "china"},
            "question_focus": {"key": "market_risk"},
            "market_drivers": {"market_key": "china", "question_focus": "market_risk"},
            "market_breadth": {
                "status": "available",
                "market_date": "2026-07-31",
                "same_date_as_analysis_target": False,
                "coverage": {"valid_change": 5533, "coverage_ratio": 1.0},
                "breadth": {
                    "total": 5533,
                    "advancers": 4517,
                    "decliners": 902,
                    "unchanged": 114,
                    "state": "普涨",
                },
            },
        }
    )

    assert compact["market_breadth"]["market_date"] == "2026-07-31"
    assert compact["market_breadth"]["same_date_as_analysis_target"] is False
    assert compact["market_breadth"]["breadth"] == {
        "total": 5533,
        "advancers": 4517,
        "decliners": 902,
        "unchanged": 114,
        "state": "普涨",
    }


def test_agent_service_delegates_market_compaction_to_pure_module(
    monkeypatch,
) -> None:
    evidence = {"type": "market_brief"}
    captured = {}

    def fake_compact(value):
        captured["evidence"] = value
        return {"delegated": True}

    monkeypatch.setattr(agent_module, "compact_market_brief_evidence", fake_compact)

    assert AgentService._compact_market_brief_evidence(evidence) == {"delegated": True}
    assert captured["evidence"] is evidence


def test_public_prompt_evidence_removes_private_fields_recursively() -> None:
    evidence = {
        "type": "market_brief",
        "source": "private-provider",
        "nested": {
            "url": "https://internal.example",
            "value": 3,
            "rows": [
                {"provider": "private", "label": "公开事实"},
            ],
        },
    }

    assert evidence_for_prompt(evidence) == {
        "type": "market_brief",
        "nested": {
            "value": 3,
            "rows": [{"label": "公开事实"}],
        },
    }


def test_market_history_keeps_only_recent_user_questions() -> None:
    history = [
        {"role": "user", "content": f"问题{i}"}
        if i % 2 == 0
        else {"role": "assistant", "content": f"旧回答{i}"}
        for i in range(12)
    ]

    assert compact_market_conversation_history(history) == [
        {"role": "user", "content": "问题4"},
        {"role": "user", "content": "问题6"},
        {"role": "user", "content": "问题8"},
        {"role": "user", "content": "问题10"},
    ]


def test_agent_service_delegates_stock_research_compaction(
    monkeypatch,
) -> None:
    evidence = {"type": "stock_research", "symbol": "000063.SZ"}
    captured = {}

    def fake_compact(value):
        captured["evidence"] = value
        return {"symbol": "000063.SZ", "delegated": True}

    monkeypatch.setattr(agent_module, "compact_stock_research_evidence", fake_compact)

    assert AgentService._compact_stock_research_evidence(evidence) == {
        "symbol": "000063.SZ",
        "delegated": True,
    }
    assert captured["evidence"] is evidence


def test_stock_knowledge_prioritizes_user_material_and_caps_excerpts() -> None:
    context = {
        "query": "中兴通讯",
        "items": [
            {"title": "通用资料一", "scope": "common", "excerpt": "甲" * 600},
            {"title": "用户资料", "scope": "user", "excerpt": "乙" * 600},
            {"title": "通用资料二", "scope": "common", "excerpt": "丙" * 600},
            {"title": "通用资料三", "scope": "common", "excerpt": "丁" * 600},
        ],
    }

    compact = compact_stock_knowledge_context(context)

    assert [item["title"] for item in compact["items"]] == [
        "用户资料",
        "通用资料一",
        "通用资料二",
    ]
    assert all(len(item["excerpt"]) == 500 for item in compact["items"])


def test_stock_specialist_compaction_keeps_root_business_payload() -> None:
    compact = compact_stock_specialist_evidence(
        {
            "type": "business_structure",
            "symbol": "000065.SZ",
            "name": "000065.SZ",
            "user_question": "北方国际靠什么业务赚钱？",
            "summary": "最大业务为工程建设与服务。",
            "coverage_limits": [
                {
                    "key": "regional_product_breakdown",
                    "boundary": "当前地区分部不能继续拆出地区内产品构成。",
                    "next_evidence": "年报分部附注。",
                }
            ],
            "dimensions": [
                {
                    "classification": "product",
                    "label": "按产品",
                    "current_report_date": "2025-12-31",
                    "segments": [
                        {"item_name": "工程建设与服务", "revenue_share_pct": 46.6}
                    ],
                }
            ],
            "stock_workspace_context": {
                "name": "北方国际",
                "research_entry": {
                    "attention_flags": ["最新财报净利润同比 -37.54%"]
                },
                "important_changes": [
                    {"summary": "保留第一条"},
                    {"summary": "不发送第二条"},
                ],
            },
        }
    )

    assert compact["display_name"] == "北方国际"
    assert compact["business_structure"]["summary"] == "最大业务为工程建设与服务。"
    assert compact["business_structure"]["dimensions"][0]["segments"] == [
        {"item_name": "工程建设与服务", "revenue_share_pct": 46.6}
    ]
    assert compact["business_structure"]["coverage_limits"] == [
        {
            "key": "regional_product_breakdown",
            "boundary": "当前地区分部不能继续拆出地区内产品构成。",
            "next_evidence": "年报分部附注。",
        }
    ]
    assert compact["stock_workspace_context"] == {"name": "北方国际"}
    assert "-37.54%" not in str(compact)


def test_business_specialist_boundary_wording_does_not_drop_business_payload() -> None:
    compact = compact_stock_specialist_evidence(
        {
            "type": "business_structure",
            "symbol": "000065.SZ",
            "name": "北方国际",
            "user_question": (
                "请继续分析北方国际的主营业务，说明收入来源、结构变化、"
                "反方证据和当前不能确认的内容。"
            ),
            "research_plan": {
                "focus": "business",
                "focus_label": "主营业务与收入结构",
            },
            "dimensions": [
                {
                    "classification": "product",
                    "label": "按产品",
                    "current_report_date": "2025-12-31",
                    "segments": [
                        {
                            "item_name": "工程建设与服务",
                            "revenue_share_pct": 46.629,
                        },
                        {
                            "item_name": "资源设备供应链",
                            "revenue_share_pct": 40.166,
                        },
                    ],
                }
            ],
        }
    )

    assert "price_move_event_evidence" not in compact
    assert compact["business_structure"]["dimensions"][0]["segments"] == [
        {"item_name": "工程建设与服务", "revenue_share_pct": 46.629},
        {"item_name": "资源设备供应链", "revenue_share_pct": 40.166},
    ]


def test_stock_events_are_aligned_to_requested_price_windows() -> None:
    compact = compact_stock_research_evidence(
        {
            "type": "stock_research",
            "symbol": "000065.SZ",
            "user_question": "这次回撤和近5日走平与哪些公告有关？",
            "metrics": {
                "return_5d_base_date": "2026-07-21T01:30:00+00:00",
                "return_5d_end_date": "2026-07-28T01:30:00+00:00",
                "return_20d_base_date": "2026-06-30T01:30:00+00:00",
                "return_20d_end_date": "2026-07-28T01:30:00+00:00",
            },
            "stock_workspace_context": {
                "research_entry": {
                    "research_focus": "近20日回撤原因是什么？",
                    "matched_reasons": ["近20日收益-8.04%"],
                }
            },
            "event_timeline": {
                "events": [
                    {
                        "title": "投资者关系活动记录",
                        "event_date": "2026-07-16",
                        "evidence_level": "official_disclosure",
                        "source": "深交所",
                        "url": "https://example.invalid/ir",
                        "direct_excerpt": "公司表示二季度出货量环比增长。",
                    },
                    {
                        "title": "向控股股东申请借款",
                        "event_date": "2026-06-15",
                        "evidence_level": "official_disclosure",
                    },
                ]
            },
        }
    )

    assert compact["requested_price_windows"]["return_20d"] == {
        "start_date": "2026-06-30",
        "end_date": "2026-07-28",
        "definition": "最近20个交易日累计收益对应的价格窗口",
    }
    inside, before = compact["event_timeline"]["events"]
    assert inside["price_window_alignment"]["return_20d"]["relation"] == (
        "inside_window"
    )
    assert before["price_window_alignment"]["return_20d"]["relation"] == (
        "before_window"
    )
    assert inside["price_window_alignment"]["return_5d"]["relation"] == (
        "before_window"
    )
    assert inside["source"] == "深交所"
    assert inside["url"] == "https://example.invalid/ir"
    assert inside["direct_excerpt"] == "公司表示二季度出货量环比增长。"


def test_quality_review_compaction_keeps_business_cashflow_and_filings_without_price():
    compact = compact_stock_research_evidence(
        {
            "type": "stock_research",
            "symbol": "601138.SS",
            "display_name": "工业富联",
            "user_question": "经营改善候选的改善是否有质量？",
            "research_plan": {
                "focus": "quality_review",
                "focus_label": "经营改善质量核验",
            },
            "current_quote": {"price": 55.3},
            "metrics": {"return_20d_pct": 7.1, "ma20": 52.0},
            "price_levels": {"support": 50.0},
            "stock_market_context": {"market_state": "上涨"},
            "fundamentals": {
                "valuation": {"pe_ttm": 31.2},
                "summary": {
                    "latest_report": {
                        "report_date": "2026-03-31",
                        "revenue_yoy_pct": 35.0,
                        "net_profit_yoy_pct": 24.0,
                        "debt_asset_ratio_pct": 63.0,
                        "operating_cashflow": 120.0,
                    }
                },
                "regulatory_filings": [
                    {"title": "2026年第一季度报告", "notice_date": "2026-04-30"}
                ],
            },
            "earnings_quality": {
                "latest_report": {
                    "report_date": "2026-03-31",
                    "operating_cashflow": 120.0,
                },
                "contradictions": ["资产负债率上升，负债结构仍需核验。"],
            },
            "financial_drivers": {
                "latest_period": {"report_date": "2026-03-31"},
                "cashflow_analysis": {
                    "operating_cashflow": 120.0,
                    "comparable_operating_cashflow": 80.0,
                },
                "confirmed_mechanical_drivers": [
                    {
                        "key": "gross_profit_bridge",
                        "statement": "按报表数据静态测算",
                        "calculation_nature": "static_counterfactual",
                    },
                    {
                        "key": "gross_profit_revenue_scale_effect",
                        "statement": "收入规模变化对应毛利增加",
                        "calculation_nature": "static_counterfactual",
                    }
                ],
                "filing_evidence": {
                    "status": "available",
                    "document": {
                        "title": "2026年第一季度报告",
                        "report_period": "2026-03-31",
                    },
                    "unresolved_themes": ["增长来源仍需公司原文解释"],
                },
            },
            "business_structure": {
                "anchor_report_date": "2025-12-31",
                "dimensions": [
                    {
                        "classification": "product",
                        "segments": [
                            {"item_name": "云计算产品", "revenue_share_pct": 50.0}
                        ],
                    },
                    {
                        "classification": "industry",
                        "segments": [
                            {"item_name": "电子设备制造业", "gross_margin_pct": 8.0}
                        ],
                    }
                ],
                "coverage_limits": [
                    {"boundary": "年报分部不能证明一季报增长来源。"}
                ],
            },
            "a_share_information": {
                "announcements": [
                    {
                        "title": "2026年第一季度报告",
                        "notice_date": "2026-04-30",
                        "summary": "公司公告原文摘录：经营情况说明。",
                    },
                    {
                        "title": "2026年投资者关系活动记录表",
                        "published_at": "2026-07-26",
                        "summary": (
                            "公司公告原文摘录：" + "经营情况。" * 90
                            + "库存增加主要是为下半年市场需求而提前备货。"
                        ),
                    }
                ]
            },
            "event_timeline": {
                "events": [
                    {
                        "title": "2026年第一季度报告",
                        "event_date": "2026-04-30",
                        "evidence_level": "official_disclosure",
                    }
                ]
            },
            "analyst_expectations": {"status": "available"},
            "peer_comparison": {"peers": [{"symbol": "000001.SZ"}]},
        }
    )

    assert "current_quote" not in compact
    assert "metrics" not in compact
    assert "price_levels" not in compact
    assert "stock_market_context" not in compact
    assert "analyst_expectations" not in compact
    assert "peer_comparison" not in compact
    assert "fundamentals" not in compact
    assert compact["financial_drivers"]["cashflow_analysis"][
        "operating_cashflow"
    ] == 120.0
    assert compact["business_structure"]["dimensions"][0]["segments"][0][
        "item_name"
    ] == "云计算产品"
    assert len(compact["business_structure"]["dimensions"]) == 1
    assert "不等于结构优化" in compact["business_structure"][
        "quality_review_boundary"
    ]
    assert all(
        item["key"] != "gross_profit_revenue_scale_effect"
        for item in compact["financial_drivers"]["confirmed_mechanical_drivers"]
    )
    assert "event_timeline" not in compact
    announcements = compact["a_share_information"]["announcements"]
    assert announcements[0]["title"] == "2026年投资者关系活动记录表"
    assert "库存增加主要是为下半年市场需求而提前备货" in (
        announcements[0]["summary"]
    )
    assert announcements[1]["title"] == "2026年第一季度报告"
    assert announcements[1]["summary"] == "公司公告原文摘录：经营情况说明。"


def test_valuation_review_compaction_uses_same_day_peer_packet_without_report_dump():
    compact = compact_stock_research_evidence(
        {
            "type": "stock_research",
            "symbol": "600841.SS",
            "display_name": "动力新科",
            "user_question": "进入估值约束候选，是不是说明它便宜？",
            "research_plan": {"focus": "valuation_review"},
            "research_evidence_contract": {
                "contract_version": "v1",
                "answer_source": "fresh_model",
                "boundary": "只使用当前证据",
                "data_times": {"peer": "2026-07-29"},
                "fresh_modules": ["a", "b", "c"],
            },
            "fundamentals": {
                "valuation": {
                    "pe_ttm": 2.55,
                    "pb": 1.24,
                    "market_timestamp": "2026-07-30T14:00:00+08:00",
                }
            },
            "earnings_quality": {
                "overall_label": "仍需复核",
                "latest_report": {
                    "report_date": "2026-03-31",
                    "parent_net_profit": 36199600.85,
                    "debt_asset_ratio_pct": 42.4809,
                },
                "comparable_report": {"report_date": "2025-03-31"},
                "factors": [{"key": f"factor-{index}"} for index in range(8)],
                "contradictions": ["现金流与利润方向相反"],
                "boundary": "quality_boundary",
            },
            "financial_drivers": {
                "overall_label": "现金流待复核",
                "latest_period": {"report_date": "2026-03-31"},
                "comparable_period": {"report_date": "2025-03-31"},
                "cashflow_analysis": {
                    "operating_cashflow": -452997686.85,
                    "operating_cashflow_to_net_profit": -12.5139,
                },
                "confirmed_mechanical_drivers": [
                    {"key": f"driver-{index}", "statement": "重复机械拆解"}
                    for index in range(6)
                ],
                "boundary": "driver_boundary",
            },
            "business_structure": {
                "anchor_report_date": "2025-12-31",
                "summary": "主营集中",
                "dimensions": [
                    {
                        "classification": "product",
                        "segments": [
                            {"item_name": "发动机"},
                            {"item_name": "重卡"},
                            {"item_name": "其他"},
                        ],
                    },
                    {"classification": "region", "segments": []},
                ],
                "coverage_limits": ["很长的覆盖限制"],
                "key_changes": ["a", "b", "c"],
                "boundary": "business_boundary",
            },
            "analyst_expectations": {
                "forecast_eps": [{"year": 2026, "value": 0.24}],
            },
            "a_share_information": {
                "announcements": [{"title": "半年报业绩预告"}],
            },
            "event_timeline": {
                "events": [
                    {
                        "title": "半年报业绩预告",
                        "evidence_level": "official_disclosure",
                        "direct_excerpt": "正" * 900,
                    }
                ]
            },
            "stock_workspace_context": {
                "research_entry": {"source_label": "估值约束观察候选"},
                "data_meta": {"large": "x" * 500},
                "boundary": "workspace_boundary",
            },
            "peer_comparison": {
                "as_of": "2026-07-29",
                "subject": {"name": "动力新科", "pe_ttm": 2.5, "pb": 1.21},
                "metrics": {
                    "pe_ttm": {"subject_value": 2.5, "peer_median": 39.39},
                    "pb": {"subject_value": 1.21, "peer_median": 2.26},
                },
                "peers": [{"name": "沪光股份"}],
                "operating_comparison": {
                    "status": "unavailable",
                    "anchor_report_date": "2026-03-31",
                    "coverage": {"same_period_financial_peers": 0},
                    "subject": {"financial": {"duplicate": "x" * 1000}},
                    "peers": [{"financial": {"duplicate": "x" * 1000}}],
                    "missing_items": ["同行缺少同报告期财务"],
                    "warnings": ["不能直接比较经营质量"],
                },
            },
        }
    )

    assert "fundamentals" not in compact
    assert "analyst_expectations" not in compact
    assert "a_share_information" not in compact
    assert "fresh_modules" not in compact["research_evidence_contract"]
    assert "data_meta" not in compact["stock_workspace_context"]
    assert "confirmed_mechanical_drivers" not in compact["financial_drivers"]
    assert len(compact["business_structure"]["dimensions"]) == 1
    assert len(compact["business_structure"]["dimensions"][0]["segments"]) == 2
    assert len(compact["event_timeline"]["events"][0]["direct_excerpt"]) == 700
    operating = compact["peer_comparison"]["operating_comparison"]
    assert operating["status"] == "unavailable"
    assert "subject" not in operating
    assert "peers" not in operating
