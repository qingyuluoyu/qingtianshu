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


def test_stock_compaction_only_keeps_component_fallbacks_for_source_questions():
    base = {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "display_name": "中兴通讯",
        "research_plan": {"focus": "mixed", "selected_modules": ["market"]},
        "stock_market_context": {
            "exact_industry_index": {
                "status": "same_market_date",
                "name": "通信设备",
                "component_breadth": {
                    "status": "available",
                    "advancers": 44,
                    "decliners": 6,
                    "coverage": {"fallback_unadjusted_returns": 3},
                    "source_fallbacks": [
                        {
                            "symbol": "000063.SZ",
                            "name": "中兴通讯",
                            "public_source_label": "新浪公开日线",
                            "adjustment": "unadjusted",
                            "internal_reason": "provider_error",
                        }
                    ],
                },
            }
        },
    }

    ordinary = compact_stock_research_evidence(
        {
            **base,
            "user_question": "结合通信设备行业分析中兴通讯今天为什么上涨？",
        }
    )
    source_question = compact_stock_research_evidence(
        {**base, "user_question": "行业成分行情用了什么数据口径？"}
    )

    ordinary_breadth = ordinary["stock_market_context"]["exact_industry_index"][
        "component_breadth"
    ]
    source_breadth = source_question["stock_market_context"][
        "exact_industry_index"
    ]["component_breadth"]
    assert "source_fallbacks" not in ordinary_breadth
    assert source_breadth["source_fallbacks"] == [
        {
            "symbol": "000063.SZ",
            "name": "中兴通讯",
            "public_source_label": "新浪公开日线",
            "adjustment": "unadjusted",
        }
    ]


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


def test_market_followup_keeps_prior_cross_date_question_context() -> None:
    history = [
        {
            "role": "user",
            "content": "今天A股普涨，但昨天四个核心指数很弱，怎么理解？",
        },
        {"role": "assistant", "content": "更像情绪修复。"},
    ]
    question_context = agent_module._market_followup_question_context(
        "你刚才说更像情绪修复，最强反方证据是什么？",
        history,
    )
    compact = compact_market_brief_evidence(
        {
            "type": "market_brief",
            "user_question": "你刚才说更像情绪修复，最强反方证据是什么？",
            "_conversation_user_questions": question_context,
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

    assert compact["cross_date_comparison"] is True
    assert compact["market_breadth"]["breadth"]["advancers"] == 4517


def test_market_risk_cause_query_prefers_deduplicated_causal_candidates():
    compact = compact_market_brief_evidence(
        {
            "type": "market_brief",
            "user_question": "今天为什么和昨天反差这么大，什么时候重新判断？",
            "question_focus": {"key": "market_risk"},
            "analysis_target": {"market_date": "2026-07-31", "market_key": "china"},
            "market_state": {
                "label": "偏强",
                "whole_market_breadth_available": True,
                "whole_market_breadth_state": "普涨",
                "whole_market_advancers": 4690,
                "whole_market_decliners": 728,
                "whole_market_unchanged": 115,
            },
            "date_alignment": {
                "status": "aligned",
                "aligned_indices": 6,
                "available_indices": 6,
            },
            "indices": [
                    {
                        "name": "上证综指",
                        "group": "china",
                        "market_date": "2026-07-31",
                        "same_date_as_analysis_target": True,
                        "metrics": {
                        "latest_close": 3836.51,
                        "return_1d_pct": 0.84,
                        "return_20d_pct": -5.56,
                        "ma20": 3904.26,
                        "ma60": 4036.01,
                        "volatility_20d_annualized_pct": 20.89,
                        "max_drawdown_60d_pct": -11.28,
                        "trend_state": "中期偏弱",
                    },
                    "latest_bar": {
                        "timestamp": "2026-07-31",
                        "close": 3836.51,
                        "volume": 592298923,
                    },
                    "recent_bars": [
                        {"timestamp": "2026-07-29", "close": 3828.0},
                        {"timestamp": "2026-07-30", "close": 3804.69},
                        {"timestamp": "2026-07-31", "close": 3836.51},
                    ],
                    "coverage": {"interval": "1d"},
                }
            ],
            "market_drivers": {
                "market_key": "china",
                "question_focus": "market_risk",
                "items": [
                    {"title": "多家公司发布风险提示"},
                    {"title": "不应优先进入 Prompt 的泛标题"},
                ],
                "causal_evidence": {
                    "coverage_status": "same_date_multi_source",
                    "candidates": [
                        {"title": "CPO概念批量跌停，白酒股上涨", "source": "甲"},
                        {"title": "CPO概念批量跌停，白酒股上涨", "source": "乙"},
                        {"title": "银行板块午后走强", "source": "丙"},
                    ],
                },
            },
            "hot_sectors": {
                "same_date_as_analysis_target": True,
                "market_date": "2026-07-30",
                "sectors": [{"name": "白酒", "pct_change": 4.26}],
            },
            "industry_focus": {
                "name": "热门",
                "market_scope": "A股",
                "requested_by_user": True,
            },
            "industry_snapshot": {
                "status": "unavailable",
                "industry_name": "热门",
            },
            "market_breadth": {
                "status": "available",
                "same_date_as_analysis_target": True,
                "breadth": {
                    "total": 5533,
                    "advancers": 1767,
                    "decliners": 3635,
                    "unchanged": 131,
                    "advance_ratio": 0.3194,
                    "state": "普跌",
                    "classification_method": "内部分类说明",
                },
                "turnover": {
                    "status": "available",
                    "currency": "CNY",
                    "total_amount_100m_cny": 23574.95,
                    "exchanges": {"shanghai": {"amount": 1}},
                    "history_comparison": {
                        "status": "available",
                        "previous_market_date": "2026-07-29",
                        "change_vs_previous_pct": 2.01,
                        "available_prior_sessions": 4,
                    },
                },
                "distribution": {
                    "status": "available",
                    "median_pct_change": -1.15,
                    "bins": {"strong_decliners": 1711},
                },
            },
        }
    )

    assert compact["market_drivers"]["items"] == []
    assert [item["title"] for item in compact["causal_evidence"]["candidates"]] == [
        "CPO概念批量跌停，白酒股上涨",
        "银行板块午后走强",
    ]
    assert compact["hot_sectors"]["sectors"][0]["name"] == "白酒"
    assert compact["indices"][0]["metrics"] == {
        "latest_close": 3836.51,
        "return_1d_pct": 0.84,
        "ma20": 3904.26,
        "ma60": 4036.01,
        "trend_state": "中期偏弱",
    }
    assert compact["indices"][0]["previous_market_date"] == "2026-07-30"
    assert compact["indices"][0]["previous_return_1d_pct"] == -0.6089
    assert compact["market_state"] == {
        "label": "偏强",
        "whole_market_breadth_available": True,
        "whole_market_breadth_state": "普涨",
        "whole_market_advancers": 4690,
        "whole_market_decliners": 728,
        "whole_market_unchanged": 115,
    }
    assert compact["date_alignment"]["available_indices"] == 1
    assert compact["date_alignment"]["aligned_indices"] == 1
    assert "latest_bar" not in compact["indices"][0]
    assert "relative_comparisons" not in compact
    assert compact["market_breadth"]["breadth"] == {
        "total": 5533,
        "advancers": 1767,
        "decliners": 3635,
        "unchanged": 131,
        "state": "普跌",
    }
    assert "distribution" not in compact["market_breadth"]
    assert "exchanges" not in compact["market_breadth"]["turnover"]
    assert "industry_focus" not in compact
    assert "industry_snapshot" not in compact


def test_market_observation_followup_drops_old_stories_and_extra_metrics():
    compact = compact_market_brief_evidence(
        {
            "type": "market_brief",
            "user_question": "接下来最值得看什么？不要重复上一轮。",
            "_conversation_user_questions": [
                "今天为什么和昨天反差这么大？"
            ],
            "question_focus": {"key": "market_risk"},
            "analysis_target": {"market_date": "2026-07-30", "market_key": "china"},
            "indices": [
                    {
                        "name": "沪深300",
                        "group": "china",
                        "market_date": "2026-07-30",
                        "same_date_as_analysis_target": True,
                        "metrics": {
                        "latest_close": 4549.72,
                        "return_1d_pct": -1.1,
                        "ma20": 4712.458,
                        "ma60": 4820.0,
                        "volatility_20d_annualized_pct": 30.0,
                        "max_drawdown_60d_pct": -15.0,
                        "trend_state": "中期偏弱",
                    },
                    "latest_bar": {"close": 4549.72, "volume": 1},
                }
            ],
            "market_drivers": {
                "market_key": "china",
                "question_focus": "market_risk",
                "items": [{"title": "旧风险提示标题"}],
                "causal_evidence": {
                    "coverage_status": "same_date_multi_source",
                    "candidates": [{"title": "旧的CPO线索", "source": "甲"}],
                },
            },
            "hot_sectors": {
                "same_date_as_analysis_target": True,
                "sectors": [{"name": "白酒", "pct_change": 4.26}],
            },
        }
    )

    assert compact["market_drivers"]["items"] == []
    assert "causal_evidence" not in compact
    assert "hot_sectors" not in compact
    assert compact["indices"][0]["metrics"] == {
        "latest_close": 4549.72,
        "ma20": 4712.458,
        "ma60": 4820.0,
        "trend_state": "中期偏弱",
    }
    assert "latest_bar" not in compact["indices"][0]
    assert "ma20_gap_points" not in compact["indices"][0]["metrics"]
    assert "relative_comparisons" not in compact


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


def test_deep_price_move_compaction_keeps_requested_finance_and_sentiment_only():
    compact = compact_stock_research_evidence(
        {
            "type": "stock_research",
            "symbol": "000063.SZ",
            "display_name": "中兴通讯",
            "user_question": (
                "请深度分析最近这次下跌究竟更像行业拖累、公司基本面压力，"
                "还是市场情绪，并结合财报与现金流、公告和社区样本。"
            ),
            "research_plan": {"focus": "comprehensive"},
            "current_quote": {"price": 33.9, "pct_change": 1.8},
            "metrics": {
                "latest_close": 33.3,
                "return_1d_pct": -2.29,
                "return_60d_pct": -12.94,
            },
            "provenance": {"market_timestamp": "2026-07-30T01:30:00+00:00"},
            "stock_market_context": {
                "stock_target": {
                    "status": "same_market_date",
                    "market_date": "2026-07-30",
                    "close": 33.3,
                    "return_1d_pct": -2.29,
                    "previous_market_date": "2026-07-29",
                    "previous_return_1d_pct": 1.0,
                },
                "exact_industry_index": {
                    "name": "通信设备",
                    "return_1d_pct": -3.4,
                    "subject_weight_pct": 3.741,
                    "component_breadth": {
                        "advancers": 3,
                        "decliners": 47,
                        "coverage": {
                            "constituents": 50,
                            "available_returns": 50,
                            "weights_available": 50,
                            "fallback_unadjusted_returns": 30,
                        },
                    },
                },
            },
            "fundamentals": {
                "valuation": {"pe_ttm": 36.24},
                "summary": {
                    "latest_report": {
                        "report_date": "2026-03-31",
                        "report_type": "一季报",
                        "revenue_yoy_pct": 6.13,
                        "net_profit_yoy_pct": -46.58,
                        "operating_cashflow": -19.79,
                    }
                },
            },
            "earnings_quality": {
                "overall_label": "盈利质量承压",
                "latest_report": {"report_date": "2026-03-31"},
                "factors": [{"label": "利润与现金流方向相反"}],
            },
            "financial_drivers": {
                "overall_label": "利润与经营现金流双重承压",
                "cashflow_analysis": {
                    "operating_cashflow": -19.79,
                    "comparable_operating_cashflow": 18.51,
                },
                "confirmed_mechanical_drivers": [
                    {
                        "key": "gross_profit_margin_effect",
                        "label": "毛利率静态影响",
                        "calculation_nature": "static_counterfactual",
                        "statement": "不应保留的静态反事实。",
                    },
                    {
                        "key": "financial_expense",
                        "label": "财务费用变化",
                        "calculation_nature": "reported_statement_bridge",
                        "statement": "财务费用同比增加。",
                    }
                ],
                "plausible_clues": [
                    {"key": "inventory", "label": "存货", "evidence": "存货上升。"},
                    {
                        "key": "accounts_payable",
                        "label": "应付账款",
                        "evidence": "不应保留。",
                    },
                    {
                        "key": "sales_cash_collection",
                        "label": "销售收现率",
                        "evidence": "销售收现率下降。",
                    },
                    {
                        "key": "operating_cashflow_coverage",
                        "label": "现金流覆盖",
                        "evidence": "经营现金流转负。",
                    },
                ],
                "filing_evidence": {
                    "status": "available",
                    "explicit_company_explanations": [
                        {
                            "theme": "financial_expense_fx_interest",
                            "label": "财务费用、汇兑与利息",
                            "excerpt": (
                                "财务费用 340,974 (340,005) 200.28% "
                                "主要因本期汇率波动产生汇兑损失及净利息收入减少"
                            ),
                            "notice_date": "2026-04-25",
                        },
                        {
                            "theme": "operating_cashflow",
                            "label": "经营现金流与销售收现",
                            "excerpt": (
                                "经营活动现金流净额 主要因本期销售商品、提供劳务 "
                                "收到的现金减少及购买商品、接受劳务支付的现金增加"
                            ),
                            "notice_date": "2026-04-25",
                        }
                    ],
                },
            },
            "a_share_information": {
                "sentiment": {
                    "band": "中性或混合",
                    "sample_size": 28,
                    "neutral_count": 26,
                },
                "news": [{"title": "不应保留的泛新闻"}],
                "announcements": [{"title": "不应在此重复的公告"}],
            },
            "peer_comparison": {"peers": [{"name": "烽火通信"}]},
            "analysis_board": {"summary": "不应进入涨跌原因 Prompt"},
            "deep_stock_coverage": {"status": "sufficient"},
        }
    )

    assert compact["metrics"] == {
        "latest_close": 33.3,
        "return_1d_pct": -2.29,
    }
    assert compact["fundamentals"]["summary"]["latest_report"][
        "revenue_yoy_pct"
    ] == 6.13
    assert compact["financial_drivers"]["cashflow_analysis"] == {
        "operating_cashflow": -19.79,
        "comparable_operating_cashflow": 18.51,
    }
    assert "overall_label" not in compact["earnings_quality"]
    assert "overall_label" not in compact["financial_drivers"]
    assert "plausible_clues" not in compact["financial_drivers"]
    industry = compact["stock_market_context"]["exact_industry_index"]
    assert "subject_weight_pct" not in industry
    assert "weights_available" not in industry["component_breadth"]["coverage"]
    assert "fallback_unadjusted_returns" not in industry["component_breadth"][
        "coverage"
    ]
    assert "previous_return_1d_pct" not in compact["stock_market_context"][
        "stock_target"
    ]
    explanation = compact["financial_drivers"]["filing_evidence"][
        "explicit_company_explanations"
    ][0]
    assert explanation["theme"] == "operating_cashflow"
    assert explanation["company_statement"].startswith("主要因本期销售商品")
    assert "340,974" not in explanation["company_statement"]
    assert [
        item["key"]
        for item in compact["financial_drivers"]["confirmed_mechanical_drivers"]
    ] == ["financial_expense"]
    assert compact["a_share_information"] == {
        "sentiment": {
            "band": "中性或混合",
            "sample_size": 28,
            "neutral_count": 26,
        },
        "sentiment_caveat": None,
    }
    assert "peer_comparison" not in compact
    assert "analysis_board" not in compact
    assert "deep_stock_coverage" not in compact


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
