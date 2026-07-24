from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from app.main import (
    ChatRequest,
    _build_stock_market_context,
    _build_visible_evidence_sources,
    _filter_knowledge_context,
    _question_price_direction,
    create_app,
)
from app.providers.market import ProviderError


def create_user(client, name: str):
    response = client.post("/users", json={"name": name})
    assert response.status_code == 201
    cookie = response.headers.get("set-cookie", "")
    assert "qingshu_session=" in cookie
    assert "httponly" in cookie.lower()
    assert "samesite=strict" in cookie.lower()
    payload = response.json()
    assert "workspace_path" not in payload
    return payload


def test_chat_requests_execute_live_agent_by_default():
    assert ChatRequest(message="分析中兴通讯").execute_agent is True


def test_stock_move_question_direction_understands_colloquial_why_up_or_down():
    assert _question_price_direction("中兴通讯今天为什么跌") == -1
    assert _question_price_direction("中兴通讯今天为什么涨") == 1
    assert (
        _question_price_direction(
            "中兴通讯7月20日为什么跌？给出行业成分上涨、下跌、平盘家数"
        )
        == -1
    )
    assert _question_price_direction("分析中兴通讯的涨跌因素") == 0


def test_visible_evidence_sources_include_structured_stock_evidence():
    sources = _build_visible_evidence_sources(
        {
            "display_name": "中兴通讯",
            "generated_at": "2026-07-22T10:00:00+00:00",
            "current_quote": {
                "name": "中兴通讯",
                "price": 37.5,
                "currency": "CNY",
                "pct_change": 7.51,
                "quote_label": "收盘后最新报价",
                "market_timestamp": "2026-07-22T16:14:09+08:00",
            },
            "metrics": {
                "latest_close": 34.88,
                "trend_state": "中期偏弱",
                "return_20d_pct": -8.2347,
                "volatility_20d_annualized_pct": 69.6932,
            },
            "provenance": {
                "market_timestamp": "2026-07-21T01:30:00+00:00"
            },
            "earnings_quality": {
                "status": "available",
                "summary": "营收增长但净利润下降。",
                "latest_report": {
                    "report_date_name": "2026一季报",
                    "report_date": "2026-03-31",
                    "notice_date": "2026-04-25",
                },
            },
            "financial_drivers": {
                "status": "available",
                "summary": "利润与经营现金流双重承压。",
                "latest_period": {
                    "report_date_name": "2026一季报",
                    "report_date": "2026-03-31",
                },
            },
            "a_share_information": {
                "announcements": [
                    {
                        "title": "关于回购A股股份实施结果暨股份变动的公告",
                        "published_at": "2026-07-20T18:00:00+08:00",
                        "url": "https://example.invalid/announcement",
                    }
                ],
                "news": [
                    {
                        "title": "超节点概念持续走高 中兴通讯封涨停",
                        "published_at": "2026-07-22T11:22:00+08:00",
                        "url": "https://example.invalid/news",
                    }
                ],
            },
        }
    )

    assert [item["kind"] for item in sources] == [
        "行情事实",
        "历史行情",
        "财务证据",
        "财务拆解",
        "公司公告",
        "新闻线索",
    ]
    assert sources[0]["summary"] == "收盘后最新报价 37.5 CNY；涨跌幅 +7.51%"
    assert sources[-1]["url"] == "https://example.invalid/news"


def test_visible_evidence_sources_expose_li_zong_history_event_and_benchmark():
    sources = _build_visible_evidence_sources(
        {
            "type": "stock_screen",
            "profile": {"key": "li_zong"},
            "history": {
                "benchmark": {"symbol": "000300.SH", "name": "沪深300"},
                "items": [
                    {
                        "name": "株冶集团",
                        "internal_symbol": "600961.SS",
                        "signal_date": "2026-07-01",
                        "signal_type": "triggered",
                        "performance": {
                            "horizons": {
                                "5": {
                                    "status": "available",
                                    "stock_return_pct": -25.3012,
                                    "benchmark_return_pct": -4.1049,
                                    "excess_return_pct": -21.1963,
                                },
                                "10": {
                                    "status": "available",
                                    "stock_return_pct": -29.86,
                                    "benchmark_return_pct": -3.47,
                                    "excess_return_pct": -26.39,
                                },
                                "20": {"status": "pending"},
                            }
                        },
                    }
                ],
            },
        }
    )

    assert sources == [
        {
            "kind": "历史回放",
            "title": "株冶集团（600961.SS）｜2026-07-01信号",
            "summary": (
                "已触发人工复核；"
                "5日个股 -25.30% / 沪深300 -4.10% / 超额 -21.20%；"
                "10日个股 -29.86% / 沪深300 -3.47% / 超额 -26.39%；"
                "20日观察尚未完整"
            ),
            "as_of": "2026-07-01",
            "source": "李总策略点时历史回放与沪深300复权日线",
        }
    ]


def test_stock_market_context_rejects_multi_session_gap_as_one_day_index_return():
    context = _build_stock_market_context(
        "中兴通讯今天为什么上涨",
        {
            "symbol": "000063.SZ",
            "current_quote": {
                "market_timestamp": "2026-07-22T15:06:00+08:00",
                "pct_change": 7.51,
                "quote_basis": "post_close_snapshot",
                "quote_label": "收盘后最新报价",
            },
            "metrics": {"return_1d_pct": 3.41},
            "provenance": {"market_timestamp": "2026-07-21T01:30:00+00:00"},
        },
        {
            "generated_at": "2026-07-22T15:10:00+08:00",
            "hot_sectors": {"sectors": []},
            "indices": [
                {
                    "symbol": "000300.SS",
                    "name": "沪深300",
                    "status": "available",
                    "recent_bars": [
                        {"timestamp": "2026-07-17T01:30:00+00:00", "close": 100},
                        {"timestamp": "2026-07-22T01:30:00+00:00", "close": 104},
                    ],
                }
            ],
            "market_breadth": {"status": "unavailable"},
        },
    )

    index = context["indices"][0]
    assert index["comparison_status"] == "missing_previous_session"
    assert index["return_1d_pct"] is None


def test_stock_market_context_aligns_official_industry_index_to_target_date():
    context = _build_stock_market_context(
        "中兴通讯今天为什么跌",
        {
            "symbol": "000063.SZ",
            "analyst_expectations": {"industry": "通信设备"},
            "current_quote": {
                "market_timestamp": "2026-07-21T16:14:00+08:00",
                "pct_change": 3.41,
            },
            "metrics": {"return_1d_pct": -6.31},
            "provenance": {
                "market_timestamp": "2026-07-20T15:00:00+08:00"
            },
        },
        {
            "generated_at": "2026-07-21T16:20:00+08:00",
            "hot_sectors": {
                "market_timestamp": "2026-07-21T15:00:00+08:00",
                "sectors": [{"name": "电子器件", "pct_change": 2.0}],
            },
            "indices": [
                {
                    "symbol": "000001.SS",
                    "name": "上证综指",
                    "status": "available",
                    "recent_bars": [
                        {"timestamp": "2026-07-17T15:00:00+08:00", "close": 100},
                        {"timestamp": "2026-07-20T15:00:00+08:00", "close": 100.85},
                    ],
                }
            ],
            "market_breadth": {
                "status": "available",
                "market_date": "2026-07-21",
                "breadth": {"advancers": 3000, "decliners": 2000},
            },
        },
        {
            "status": "available",
            "industry_name": "通信设备",
            "index_code": "931160",
            "index_name": "通信设备",
            "index_full_name": "中证全指通信设备指数",
            "index_description": "反映通信设备行业上市公司证券的整体表现。",
            "source_url": "https://example.invalid/931160",
            "constituent_source_url": "https://example.invalid/931160cons.xls",
            "constituents_as_of": "2026-07-21",
            "weights_as_of": "2026-06-30",
            "industry_mapping": {
                "input_name": "通信设备",
                "match_type": "exact_name",
                "official_index_name": "通信设备",
            },
            "coverage": {"constituents": 50},
            "constituents": [
                {
                    "symbol": "000063.SZ",
                    "name": "中兴通讯",
                    "weight_pct": 3.741,
                }
            ],
            "points": [
                {
                    "market_date": "2026-07-20",
                    "close": 19546.69,
                    "pct_change": -1.42,
                },
                {
                    "market_date": "2026-07-21",
                    "close": 21147.25,
                    "pct_change": 8.19,
                },
            ],
            "component_analysis": {
                "status": "available",
                "market_date": "2026-07-20",
                "coverage": {
                    "constituents": 50,
                    "available_returns": 50,
                    "missing_returns": 0,
                    "fallback_unadjusted_returns": 1,
                },
                "breadth": {
                    "status": "available",
                    "market_date": "2026-07-20",
                    "total_constituents": 50,
                    "available_returns": 50,
                    "advancers": 12,
                    "decliners": 36,
                    "unchanged": 2,
                    "median_pct_change": -1.88,
                    "state": "普跌",
                },
                "contribution": {
                    "status": "available",
                    "market_date": "2026-07-20",
                    "weights_as_of": "2026-06-30",
                    "estimated_total_contribution_pp": -1.36,
                    "official_index_return_pct": -1.42,
                    "reconciliation_gap_pp": -0.06,
                },
                "components": [
                    {
                        "symbol": "000063.SZ",
                        "name": "中兴通讯",
                        "pct_change": -6.31,
                        "weight_pct": 3.741,
                        "estimated_contribution_pp": -0.2361,
                        "adjustment": "qfq",
                    },
                    {
                        "symbol": "920185.BJ",
                        "name": "贝特瑞",
                        "pct_change": -3.75,
                        "weight_pct": 0.503,
                        "estimated_contribution_pp": -0.0189,
                        "adjustment": "unadjusted",
                        "fallback_reason": "腾讯前复权历史未返回",
                    }
                ],
                "failures": [],
                "boundary": "其中1只成分使用未复权日线降级。",
            },
        },
    )

    assert context["analysis_target"]["market_date"] == "2026-07-20"
    assert context["exact_industry_match_available"] is True
    industry = context["exact_industry_index"]
    assert industry["status"] == "same_market_date"
    assert industry["return_1d_pct"] == -1.42
    assert industry["stock_return_1d_pct"] == -6.31
    assert industry["stock_minus_industry_pct"] == -4.89
    assert industry["constituent_count"] == 50
    assert industry["subject_is_constituent"] is True
    assert industry["subject_weight_pct"] == 3.741
    assert industry["industry_mapping"]["match_type"] == "exact_name"
    assert industry["component_breadth"]["status"] == "available"
    assert industry["component_breadth"]["advancers"] == 12
    assert industry["component_breadth"]["decliners"] == 36
    assert industry["component_breadth"]["state"] == "普跌"
    assert industry["component_breadth"]["coverage"][
        "fallback_unadjusted_returns"
    ] == 1
    assert industry["component_breadth"]["failures"] == []
    assert "未复权日线降级" in industry["component_breadth"]["boundary"]
    assert industry["component_breadth"]["source_fallbacks"] == [
        {
            "symbol": "920185.BJ",
            "name": "贝特瑞",
            "public_source_label": "新浪公开日线",
            "adjustment": "unadjusted",
            "fallback_reason": "腾讯前复权历史未返回",
        }
    ]
    assert industry["component_contribution"]["subject"][
        "estimated_contribution_pp"
    ] == -0.2361


def test_stock_market_context_honors_explicit_date_after_newer_daily_bar():
    context = _build_stock_market_context(
        "中兴通讯7月20日为什么跌？给出行业成分上涨、下跌、平盘家数",
        {
            "symbol": "000063.SZ",
            "analyst_expectations": {"industry": "通信设备"},
            "current_quote": {
                "market_timestamp": "2026-07-21T16:14:00+08:00",
                "price": 34.88,
                "pct_change": 3.41,
            },
            "metrics": {
                "latest_close": 34.88,
                "return_1d_pct": 3.4094,
            },
            "recent_bars": [
                {"timestamp": "2026-07-17T15:00:00+08:00", "close": 36.0},
                {"timestamp": "2026-07-20T15:00:00+08:00", "close": 33.73},
                {"timestamp": "2026-07-21T15:00:00+08:00", "close": 34.88},
            ],
            "provenance": {
                "market_timestamp": "2026-07-21T15:00:00+08:00",
                "source": "test history",
            },
        },
        {
            "generated_at": "2026-07-21T16:20:00+08:00",
            "hot_sectors": {"sectors": []},
            "indices": [
                {
                    "symbol": "000001.SS",
                    "name": "上证综指",
                    "status": "available",
                    "recent_bars": [
                        {"timestamp": "2026-07-17T15:00:00+08:00", "close": 100},
                        {"timestamp": "2026-07-20T15:00:00+08:00", "close": 100.85},
                        {"timestamp": "2026-07-21T15:00:00+08:00", "close": 101.2},
                    ],
                }
            ],
            "market_breadth": {
                "status": "available",
                "market_date": "2026-07-21",
                "breadth": {"advancers": 3000, "decliners": 2000},
            },
        },
        {
            "status": "available",
            "industry_name": "通信设备",
            "index_code": "931160",
            "index_name": "通信设备",
            "coverage": {"constituents": 50},
            "constituents": [
                {
                    "symbol": "000063.SZ",
                    "name": "中兴通讯",
                    "weight_pct": 3.741,
                }
            ],
            "points": [
                {"market_date": "2026-07-20", "close": 19546.69, "pct_change": -1.42},
                {"market_date": "2026-07-21", "close": 21147.25, "pct_change": 8.19},
            ],
            "component_analysis": {
                "status": "available",
                "market_date": "2026-07-20",
                "breadth": {
                    "status": "available",
                    "market_date": "2026-07-20",
                    "advancers": 16,
                    "decliners": 34,
                    "unchanged": 0,
                    "advance_ratio": 0.32,
                    "decline_ratio": 0.68,
                    "state": "普跌",
                },
                "contribution": {
                    "status": "available",
                    "market_date": "2026-07-20",
                },
                "components": [
                    {
                        "symbol": "000063.SZ",
                        "name": "中兴通讯",
                        "pct_change": -6.3056,
                        "weight_pct": 3.741,
                        "estimated_contribution_pp": -0.2359,
                    }
                ],
            },
        },
    )

    assert context["analysis_target"]["market_date"] == "2026-07-20"
    assert context["analysis_target"]["basis"] == "explicit_question_date"
    assert context["stock_target"]["status"] == "same_market_date"
    assert context["stock_target"]["close"] == 33.73
    assert context["stock_target"]["return_1d_pct"] == -6.3056
    assert context["exact_industry_index"]["market_date"] == "2026-07-20"
    assert context["indices"][0]["stock_minus_index_pct"] == -7.1556
    assert context["exact_industry_index"]["component_breadth"][
        "decliners"
    ] == 34
    assert context["exact_industry_index"]["component_breadth"][
        "decline_ratio_pct"
    ] == 68.0


def test_stock_market_context_does_not_treat_partial_daily_bars_as_intraday_breadth():
    context = _build_stock_market_context(
        "中兴通讯今天为什么涨",
        {
            "symbol": "000063.SZ",
            "analyst_expectations": {"industry": "通信设备"},
            "current_quote": {
                "market_timestamp": "2026-07-22T11:10:15+08:00",
                "price": 37.86,
                "pct_change": 8.54,
            },
            "metrics": {"latest_close": 34.88, "return_1d_pct": 3.41},
            "recent_bars": [
                {"timestamp": "2026-07-21T15:00:00+08:00", "close": 34.88}
            ],
            "provenance": {
                "market_timestamp": "2026-07-21T15:00:00+08:00",
                "source": "test history",
            },
        },
        {
            "generated_at": "2026-07-22T11:11:00+08:00",
            "hot_sectors": {
                "market_timestamp": "2026-07-22T11:10:00+08:00",
                "sectors": [],
            },
            "indices": [],
            "market_breadth": {
                "status": "available",
                "market_date": "2026-07-21",
            },
        },
        {
            "status": "available",
            "industry_name": "通信设备",
            "index_code": "931160",
            "index_name": "通信设备",
            "coverage": {"constituents": 50},
            "points": [],
            "component_analysis": {
                "status": "partial",
                "market_date": "2026-07-22",
                "coverage": {
                    "constituents": 50,
                    "available_returns": 1,
                    "missing_returns": 49,
                },
                "breadth": {
                    "status": "partial",
                    "market_date": "2026-07-22",
                    "total_constituents": 50,
                    "available_returns": 1,
                    "advancers": 0,
                    "decliners": 1,
                    "unchanged": 0,
                },
                "contribution": {
                    "status": "partial",
                    "market_date": "2026-07-22",
                },
            },
        },
    )

    assert context["stock_target"]["price_label"] == "盘中/最新报价快照"
    assert context["stock_target"]["is_complete_daily_close"] is False
    industry = context["exact_industry_index"]
    assert industry["status"] == "intraday_not_supported"
    assert industry["component_breadth"]["status"] == "intraday_not_supported"
    assert "failures" not in industry["component_breadth"]
    assert industry["component_contribution"]["status"] == "intraday_not_supported"


def test_time_sensitive_stock_question_excludes_stale_snapshot_documents():
    filtered = _filter_knowledge_context(
        {
            "items": [
                {
                    "scope": "common",
                    "source_key": "research-report:000063.SZ",
                    "title": "中兴通讯长期研究档案",
                },
                {
                    "scope": "common",
                    "source_key": "research-outcome:000063.SZ",
                    "title": "中兴通讯研究结果复盘",
                },
                {
                    "scope": "user",
                    "source_key": "research-actions:user-1",
                    "title": "我的最新研究行动与观察条件",
                },
                {
                    "scope": "common",
                    "source_key": "earnings-quality:000063.SZ",
                    "title": "中兴通讯最新财报质量分析",
                },
                {
                    "scope": "user",
                    "source_key": "upload:user-note",
                    "title": "我的中兴通讯调研笔记",
                },
            ]
        },
        intent="stock_research",
        symbol="000063.SZ",
        evidence={
            "user_question": "中兴通讯今天为什么上涨？",
            "current_quote": {"price": 38.37},
        },
    )

    source_keys = {item["source_key"] for item in filtered["items"]}
    assert "research-report:000063.SZ" not in source_keys
    assert "research-outcome:000063.SZ" not in source_keys
    assert "research-actions:user-1" not in source_keys
    assert "earnings-quality:000063.SZ" in source_keys
    assert "upload:user-note" in source_keys


def test_demo_page_is_the_default_human_facing_entry(client):
    root = client.get("/", follow_redirects=False)
    assert root.status_code in {302, 307}
    assert root.headers["location"] == "/today"
    page = client.get("/demo")
    assert page.status_code == 200
    assert page.headers["cache-control"] == "no-store, max-age=0"
    assert page.headers["pragma"] == "no-cache"
    assert "清数智算" in page.text
    assert "金融研究 Agent" in page.text
    assert 'id="useHermesLabel" class="model-toggle" hidden' in page.text
    assert "研究深度" in page.text
    assert "按时间从新到旧" in page.text
    assert "当前交易中" in page.text
    assert "当前估算开盘" not in page.text
    assert "article-feed" in page.text
    assert "后台自动更新" not in page.text
    assert "最新后台文章" not in page.text
    assert "开发者接口" not in page.text
    assert "数据源不可用" not in page.text
    assert "盘中数据暂不可用" not in page.text
    assert "板块数据暂不可用" not in page.text
    assert "暂时无法读取个人待处理事项" not in page.text
    assert "暂时无法读取个人研究变化" not in page.text
    assert "首批快照准备中" not in page.text
    assert "系统正在准备可追溯策略快照" not in page.text
    assert "系统正在为当前研究池建立可追溯数据快照" not in page.text
    assert "完整市场截面正在准备" not in page.text
    assert "完整市场数据仍在准备" not in page.text
    assert "市场数据正在准备" not in page.text
    assert 'id="todayOverviewGrid" class="today-overview-grid"' in page.text
    assert page.text.index('id="liveSection"') < page.text.index(
        'id="marketDashboard"'
    ) < page.text.index('id="insightSection"') < page.text.index(
        'id="insightAsk"'
    ) < page.text.index('id="todayOverviewGrid"')
    assert "我的研究待办" in page.text
    assert "与我相关的重要变化" in page.text
    assert "不会在这里伪装上线" not in page.text
    assert "priority.ranking_method" not in page.text
    assert "需要你处理的变化已经归入左侧待办" in page.text
    assert 'id="liZongPanel" class="li-zong-panel"' in page.text
    assert '$("todayOverviewGrid").hidden = true' in page.text
    assert '$("liZongPanel").hidden = true' in page.text
    assert 'api("/session")' in page.text
    assert 'api("/me/watchlist/brief")' in page.text
    assert 'api("/me/chat"' in page.text
    assert "void loadHealth().catch(() =>" in page.text
    assert page.text.index('connectServerEvents();') < page.text.index(
        'await Promise.all([loadHealth(), ensureUser()]);'
    )
    assert 'api("/me/memories?status=candidate")' in page.text
    assert "memory-card" in page.text
    assert "确认保存" in page.text
    assert "暂不保存" in page.text
    assert "李总策略" in page.text
    assert (
        "candidates?status=${encodeURIComponent(filter)}&limit=200"
        in page.text
    )
    assert "const loadToken = ++state.liZongLoadToken" in page.text
    assert 'data-li-zong-filter="data_incomplete"' in page.text
    assert "function enterScreenCandidateResearch(" in page.text
    assert "entry_context: entryContext" in page.text
    assert "保存线索并研究" in page.text
    assert "本次研究入口" in page.text
    assert "筛选线索待确认" in page.text
    assert "error?.status === 503" in page.text
    assert "服务器尚未配置选股数据" in page.text
    assert "⊕ 添加图片" in page.text
    assert "AI 图像研究" in page.text
    assert 'api("/me/uploads/images"' in page.text
    assert 'api("/me/conversations?limit=100")' in page.text
    assert "function diagnosisResearchTargets(data)" in page.text
    assert "多股比较" in page.text
    assert "function visibleConversationItems(items = [])" in page.text
    assert 'item.quality_scope !== "evaluation"' in page.text
    assert 'api("/me/knowledge")' in page.text
    assert 'conversation_id: state.conversationId' in page.text
    assert "研究类型" in page.text
    assert "个股分析" in page.text
    assert "行业研究" in page.text
    assert "关注组合" in page.text
    assert "公告财报" in page.text
    assert "操作前检查" in page.text
    assert "公司对比" in page.text
    assert "市场环境" in page.text
    assert 'aria-label="今日观察"' in page.text
    assert 'aria-label="AI研究"' in page.text
    assert 'aria-label="我的关注"' in page.text
    assert 'aria-label="个股研究"' in page.text
    assert 'aria-label="复盘中心"' in page.text
    assert 'aria-label="个人中心"' in page.text
    assert 'id="todayOverviewGrid"' in page.text
    assert "#todayOverviewGrid[hidden]" in page.text
    assert 'api("/v1/today/overview")' in page.text
    assert 'api("/v1/stock-workspaces")' in page.text
    assert "function renderTodayOverview(data)" in page.text
    assert '$("todayOverviewGrid").hidden = !insightsVisible' in page.text
    priority_open = page.text[
        page.text.index("async function openPriorityItem(item)") :
        page.text.index("function renderNotificationCenter(priority)")
    ]
    assert (
        'action.type === "open_stock_tasks" ? "tasks" : "overview"'
        in priority_open
    )
    open_stock = page.text[page.text.index("async function openDeepStockSymbol(symbol") :]
    assert "state.pendingDeepStockSymbol = symbol" in open_stock
    assert open_stock.index("select.value = symbol") < open_stock.index(
        'activateWorkspace("deep_stock", {historyMode: "none"})'
    )
    assert 'const order = ["000001.SS", "399001.SZ", "399006.SZ", "000688.SS"]' in page.text
    assert "error.status = response.status" in page.text
    thesis_editor = page.text[
        page.text.index('const editThesis = document.createElement("button")') :
        page.text.index('const researchMap = document.createElement("section")')
    ]
    assert '/v1/stocks/${encodeURIComponent(symbol)}/theses' in thesis_editor
    assert "base_version: editBaseVersion" in thesis_editor
    assert "正式判断已在其他页面更新" in thesis_editor
    assert page.text.count('class="nav-item') == 6
    assert page.text.index('data-page="watchlist"') < page.text.index(
        'data-page="deep_stock"'
    ) < page.text.index('data-page="agent"')
    assert 'data-page="screening" aria-label="选股研究"' not in page.text
    assert 'data-open-page="screening"' in page.text
    assert 'id="accountPanel"' in page.text
    assert 'data-watchlist-filter="holding"' in page.text
    assert 'data-watchlist-filter="watching"' in page.text
    assert 'data-watchlist-filter="ended"' in page.text
    assert 'id="watchlistSecondaryFilter"' in page.text
    assert "async function updateStockAssetRelation(" in page.text
    assert "base_version: item.version" in page.text
    assert "结束跟踪不会删除判断和历史" in page.text
    assert 'deleteButton.textContent = "删除"' not in page.text
    assert "function renderAccountCenter()" in page.text
    assert 'year: "numeric", month: "2-digit", day: "2-digit"' in page.text
    assert "内部 MVP 暂未启用计费" in page.text
    assert 'data.type === "stock_strategy_updated"' in page.text
    assert "财务历史待实查" in page.text
    assert ".sidebar .nav-text { display: inline; }" in page.text
    assert 'data-page="knowledge"' in page.text
    assert 'aria-label="资料库"' in page.text
    assert 'id="knowledgePanel"' in page.text
    assert "研究资料库" in page.text
    assert '<div class="nav-label">资料库</div>' not in page.text
    assert 'class="knowledge-box"' not in page.text
    assert "body.agent-page .workspace-header { display: none; }" in page.text
    assert "分析师预期" in page.text
    assert "事件脉络" in page.text
    assert "财报质量" in page.text
    assert "股东结构" in page.text
    assert 'id="shareholderAction"' in page.text
    assert 'id="eventTimelineAction"' in page.text
    assert "AI 实时研究" in page.text
    assert "image_id" in page.text
    assert "localStorage.setItem" not in page.text
    assert 'event.key === "Enter"' in page.text
    assert "!event.shiftKey" in page.text
    assert "!event.isComposing" in page.text
    assert "event.keyCode !== 229" in page.text
    assert '$("chatForm").requestSubmit()' in page.text
    assert "function finalizeStreamingMessage(" in page.text
    assert "function appendFinalMessageMetadata(" in page.text
    assert "function renderStreamingProgress(" in page.text
    assert "回答草稿已生成，正在核对行情、数字和证据" in page.text
    assert 'data.is_unverified === false && data.is_final === true' in page.text
    assert 'node.dataset.finalAnswerVisible === "true"' in page.text
    assert "if (pending?.isConnected && data.label) renderStreamingProgress(pending, data.label);" in page.text
    assert "renderStreamingDraft(" not in page.text
    assert "AI 实时生成中（草稿）" not in page.text
    assert "return {source, ready, context};" in page.text
    assert "pending.remove();\n        state.conversationId" not in page.text
    assert "responseNode = finalizeStreamingMessage(pending, data.answer" in page.text
    assert "诊大盘" not in page.text
    assert "诊个股" not in page.text
    assert 'data-page="insights"' in page.text
    assert 'data-page="agent"' in page.text
    assert 'data-page="deep_stock"' in page.text
    assert 'aria-label="个股研究"' in page.text
    assert 'id="deepStockPanel"' in page.text
    assert "股票研究空间" in page.text
    assert "stock-thesis-editor" in page.text
    assert "deep-quote-tags" in page.text
    assert "stock-system-observation-list" in page.text
    assert 'stock-workspace-item${interactive ? " interactive" : ""}' in page.text
    assert "保存当前判断" in page.text
    assert "保存会创建正式判断版本" in page.text
    assert "系统不会静默覆盖" in page.text
    assert 'data-stock-space-tab="overview"' in page.text
    assert 'data-stock-space-tab="ai"' in page.text
    assert 'data-stock-space-tab="evidence"' in page.text
    assert 'data-stock-space-tab="tasks"' in page.text
    assert 'data-stock-space-tab="history"' in page.text
    assert 'id="deepStockEvidence"' in page.text
    assert 'id="deepStockTasks"' in page.text
    assert 'id="deepStockHistory"' in page.text
    assert 'id="deepStockAgent" class="btn" type="button" disabled hidden' in page.text
    assert "function researchActionDetail(action)" in page.text
    assert "查看任务依据" in page.text
    assert 'function openReader(title, body, meta = "", sourceUrl = "")' in page.text
    assert "打开原始公告或信息源" in page.text
    assert 'api("/me/deep-stock?limit=50")' in page.text
    assert 'api("/me/deep-stock", {' in page.text
    assert "deepStockLoaded: false" in page.text
    assert "deepStockLoadPromise: null" in page.text
    assert "正在恢复绑定对话" in page.text
    assert "不会新建重复会话" in page.text
    assert "if (state.deepStockLoadPromise)" in page.text
    assert "if (!force && state.deepStockLoaded)" in page.text
    assert "await loadDeepStock({force: true})" in page.text
    assert "七阶段研究进度" in page.text
    assert 'data-page="watchlist"' in page.text
    assert 'id="watchlistAddForm"' in page.text
    assert 'api(`/stocks/${encodeURIComponent(item.symbol)}/intraday`)' in page.text
    assert 'api(`/me/watchlist/${encodeURIComponent(item.symbol)}`' in page.text
    assert "function aggregateWeekly(points = [])" in page.text
    assert "分时" in page.text
    assert "周线" in page.text
    assert 'data-page="review"' in page.text
    assert 'id="homeFocus"' in page.text
    assert 'data-home-focus="markets"' in page.text
    assert 'data-home-focus="watchlist"' in page.text
    assert 'data-home-focus="ashare"' in page.text
    assert 'id="homeAShareStepMeta"' in page.text
    assert "function renderHomeFocus()" in page.text
    assert "function prepareAgentQuestion(question)" in page.text
    assert "function dedupeInsightItems(items = [])" in page.text
    assert 'id="insightAskForm"' in page.text
    assert 'id="insightQuestion"' in page.text
    assert 'data-insight-filter="market"' in page.text
    assert 'data-insight-filter="stock"' in page.text
    assert 'data-insight-filter="opportunity"' in page.text
    assert 'id="agentHistoryList"' in page.text
    assert 'id="conversationSwitcher"' in page.text
    assert 'id="agentProcessToggle"' in page.text
    assert 'id="agentContextToggle"' in page.text
    assert "function setAgentContextCollapsed(collapsed)" in page.text
    assert "const chineseHeading = line.match" in page.text
    assert "复盘中心" in page.text
    assert 'id="reviewOutcomesPanel"' in page.text
    assert 'api("/me/research-outcomes?limit=120")' in page.text
    assert "function renderResearchOutcomes(data)" in page.text
    assert "让 Agent 复核这次研究" in page.text
    assert "研究行动" in page.text
    assert "overflow-y: auto; overscroll-behavior: contain" in page.text
    assert 'id="diagnosisContext"' in page.text
    assert 'id="workspaceTitle"' in page.text
    assert 'api(`/stocks/${encodeURIComponent(symbol)}/history?range=3mo`)' in page.text
    assert 'api(`/a-share/${encodeURIComponent(symbol)}/fundamentals`)' in page.text
    assert "async function loadDeepStockOverview(symbol)" in page.text
    assert 'className = "stock-primary-grid"' in page.text
    assert 'setAttribute("aria-label", "K线区间")' in page.text
    assert "function readableResearchPreview(value)" in page.text
    assert "当前研究摘要" in page.text
    assert 'optionalApi(`/a-share/${encoded}/shareholders`)' in page.text
    assert 'optionalApi(`/a-share/${encoded}/analyst-expectations`)' in page.text
    assert 'optionalApi(`/stocks/${encoded}/event-timeline`)' in page.text
    assert 'optionalApi(`/a-share/${encoded}/information`)' in page.text
    assert "const quoteLabel = quote?.quote_label" in page.text
    assert "maybeUpdateDiagnosis" in page.text
    assert "const symbol = inferDiagnosisSymbol(data, question)" in page.text
    assert "const marketKey = inferDiagnosisMarketKey(data, question)" in page.text
    assert 'const marketTerms = new Set(["A", "AI", "ETF"' in page.text
    assert 'activateWorkspace("agent")' in page.text
    assert '$("chatInput").value = "";' in page.text
    assert "body.agent-page #agentSection" in page.text
    assert 'api("/research-method?limit=4")' in page.text
    assert 'api("/me/research-actions")' in page.text
    assert 'api("/me/chat/refine"' in page.text
    assert "const directHermes = Boolean(state.health?.hermes_enabled);" in page.text
    assert "execute_agent: attachedImage ? true : directHermes" in page.text
    assert "prefer_precomputed: false" in page.text
    assert "AI 正在检索实时证据、资料库和金融研究工具" in page.text
    assert "function renderMarkdown(text)" in page.text
    assert "navigator.clipboard.writeText(text)" in page.text
    assert "AI 正在补充深度解读" in page.text
    assert 'id="toggleQuickActions"' in page.text
    assert "data-quick-secondary" in page.text
    assert 'container.classList.toggle("expanded", expanded)' in page.text
    assert "研究行动与结果回填" in page.text
    assert 'id="conversationQualitySummary"' in page.text
    assert 'id="conversationQualityIssues"' in page.text
    assert 'api("/me/conversation-quality")' in page.text
    assert "普通用户样本不足，暂不评分" in page.text
    assert "验收审计" in page.text
    assert "首片段" in page.text
    assert "首个安全可见" in page.text
    assert 'new URLSearchParams(window.location.search).get("qa") === "1"' in page.text
    assert 'quality_scope: state.evaluationMode ? "evaluation" : "user"' in page.text
    send_chat = page.text[page.text.index("async function sendChat(message)") :]
    assert "setAgentProcessExpanded(true)" not in send_chat
    assert send_chat.index('$("sendButton").disabled = true') < send_chat.index(
        "privateStream = connectPrivateAgentStream(requestId, pending)"
    )


def test_today_overview_requires_session_and_returns_independent_components(client):
    assert client.get("/v1/today/overview").status_code == 401
    create_user(client, "Today Alice")

    response = client.get("/v1/today/overview")

    assert response.status_code == 200
    payload = response.json()
    assert payload["contract_version"] == "today_overview_v1"
    assert payload["session"]["key"] in {
        "pre_market",
        "intraday",
        "post_market",
        "non_trading_day",
        "unknown",
    }
    assert len(payload["market"]["indices"]) == 4
    assert payload["priority_items"]["total_visible"] <= 5
    assert payload["personalized"]["coverage"]["event_whitelist_complete"] is False
    assert payload["coverage"]["status"] in {"ready", "partial"}
    assert "不构成买卖" in payload["boundary"]


def test_conversation_quality_endpoint_is_user_isolated(app):
    alice_client = TestClient(app)
    bob_client = TestClient(app)
    alice = create_user(alice_client, "Quality Alice")
    bob = create_user(bob_client, "Quality Bob")
    alice_conversation = app.state.database.create_conversation(
        alice["id"], "Alice 对话"
    )
    app.state.database.create_conversation(bob["id"], "Bob 对话一")
    app.state.database.create_conversation(bob["id"], "Bob 对话二")
    app.state.database.add_conversation_message(
        alice["id"],
        alice_conversation["id"],
        "user",
        "只属于 Alice 的问题",
    )

    alice_quality = alice_client.get("/me/conversation-quality")
    bob_quality = bob_client.get("/me/conversation-quality")

    assert alice_quality.status_code == 200
    assert bob_quality.status_code == 200
    assert alice_quality.json()["summary"]["conversations"] == 1
    assert alice_quality.json()["summary"]["messages"] == 1
    assert bob_quality.json()["summary"]["conversations"] == 2
    assert bob_quality.json()["summary"]["messages"] == 0


def test_live_markets_include_five_regions_and_persist_intraday_bars(client, app):
    response = client.get("/markets/live")
    assert response.status_code == 200
    payload = response.json()
    assert payload["coverage"]["requested"] == 5
    assert payload["coverage"]["available"] == 5
    assert {item["key"] for item in payload["markets"]} == {
        "china",
        "japan",
        "korea",
        "us",
        "london_gold",
    }
    for item in payload["markets"]:
        assert item["points"]
        assert item["session_label"] in {
            "交易中",
            "未开盘",
                "午间休市",
                "已收盘",
                "休市",
                "每日维护",
            }
        assert item["session_status"] in {
            "open",
            "pre_open",
            "break",
            "closed",
            "holiday",
        }
        assert item["source"]
    stocks = [item for item in payload["markets"] if item["key"] != "london_gold"]
    assert all(item["calendar_status"] == "verified" for item in stocks)
    assert "交易所日历" in payload["session_method"]
    stored = app.state.database.get_market_bars("000001.SS", "1m", limit=200)
    assert len(stored) == 100
    assert stored[-1]["close"] is not None


def test_stock_history_supports_diagnosis_kline_and_technical_metrics(client):
    response = client.get("/stocks/000063/history", params={"range": "3mo"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["symbol"] == "000063.SZ"
    assert payload["display_name"] == "中兴通讯"
    assert payload["points"]
    assert payload["metrics"]["rsi_14"] is not None
    assert payload["metrics"]["macd_histogram"] is not None
    assert payload["metrics"]["atr_14_pct"] is not None
    assert payload["metrics"]["technical_state"]
    assert client.get("/stocks/^GSPC/history").status_code == 422


def test_research_method_explains_real_pipeline_without_internal_failures(client):
    response = client.get("/research-method", params={"limit": 4})
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["pipeline"]) == 7
    assert len(payload["tools"]) == 16
    assert any(item["name"] == "A股财报全文证据器" for item in payload["tools"])
    assert any(item["name"] == "利润与现金流驱动拆解器" for item in payload["tools"])
    assert any(item["name"] == "技术结构计算器" for item in payload["tools"])
    assert any(item["name"] == "财报质量对比器" for item in payload["tools"])
    assert any(
        item["name"] == "主营业务与毛利来源拆解器"
        for item in payload["tools"]
    )
    assert any(item["name"] == "研究结果回填" for item in payload["tools"])
    assert any(item["name"] == "研究行动与观察条件" for item in payload["tools"])
    assert any(
        item["name"] == "分析师一致预期与研报跟踪器"
        for item in payload["tools"]
    )
    assert any(item["name"] == "重要事件脉络分析器" for item in payload["tools"])
    assert any("AI 引擎" in item["name"] for item in payload["tools"])
    assert any("不得由模型编造" in item for item in payload["boundaries"])
    serialized = str(payload)
    assert "API key" not in serialized
    assert "Traceback" not in serialized


def test_background_status_is_exposed_without_starting_jobs_in_tests(client):
    status = client.get("/system/background")
    assert status.status_code == 200
    payload = status.json()
    assert payload["enabled"] is False
    assert payload["running"] is False
    assert payload["li_zong_worker_running"] is False
    assert payload["li_zong_refresh_seconds"] == 30
    assert payload["latest_jobs"] == []


def test_data_health_has_internal_details_but_health_exposes_public_summary(client):
    detailed = client.get("/system/data-health")
    assert detailed.status_code == 200
    payload = detailed.json()
    assert payload["method"] == "deterministic_data_health_audit_v1"
    assert payload["checks"]
    assert payload["status"] == "degraded"

    public = client.get("/health").json()["data_health"]
    assert public["status"] == "degraded"
    assert public["user_label"] == "部分数据同步中"
    assert "checks" not in public


def test_user_workspace_watchlist_and_run_isolation(app):
    alice_client = TestClient(app)
    bob_client = TestClient(app)
    anonymous_client = TestClient(app)
    alice = create_user(alice_client, "Alice")
    bob = create_user(bob_client, "Bob")
    alice_record = app.state.database.get_user(alice["id"])
    bob_record = app.state.database.get_user(bob["id"])
    assert alice_record is not None and bob_record is not None
    assert alice_record["workspace_path"] != bob_record["workspace_path"]
    alice_workspace = Path(alice_record["workspace_path"])
    assert alice_workspace.is_dir()
    assert (alice_workspace / "profile.json").is_file()
    assert (alice_workspace / "memory" / "confirmed.json").is_file()
    assert alice_client.get("/session").json()["id"] == alice["id"]
    assert anonymous_client.get(f"/users/{alice['id']}").status_code == 401
    assert bob_client.get(f"/users/{alice['id']}").status_code == 404

    added = alice_client.post(
        f"/users/{alice['id']}/chat",
        json={"message": "把600519加入自选，因为我想验证高端白酒需求是否企稳"},
    )
    assert added.status_code == 200
    payload = added.json()
    assert payload["status"] == "preview"
    assert payload["intent"] == "watchlist_update"
    assert payload["evidence"]["item"]["symbol"] == "600519.SS"
    assert "需求是否企稳" in payload["evidence"]["item"]["thesis"]

    alice_list = alice_client.get(f"/users/{alice['id']}/watchlist").json()["items"]
    bob_list = bob_client.get(f"/users/{bob['id']}/watchlist").json()["items"]
    assert len(alice_list) == 1
    assert bob_list == []
    assert "600519.SS" in (alice_workspace / "watchlist.json").read_text()

    run_id = payload["run_id"]
    assert (
        alice_client.get(f"/runs/{run_id}", params={"user_id": alice["id"]}).status_code
        == 200
    )
    assert alice_client.get(f"/me/runs/{run_id}").status_code == 200
    assert (
        bob_client.get(f"/runs/{run_id}", params={"user_id": alice["id"]}).status_code
        == 404
    )
    assert bob_client.get(f"/me/runs/{run_id}").status_code == 404


def test_run_reviews_only_expose_user_runs_and_return_safe_detail(client):
    user = create_user(client, "Run Review Alice")
    database = client.app.state.database
    conversation = database.create_conversation(user["id"], "中兴通讯复盘")
    database.add_conversation_message(
        user["id"],
        conversation["id"],
        "user",
        "中兴通讯为什么大跌？",
        intent="stock_research",
    )
    run = database.create_run(
        user["id"],
        "stock_research",
        "economy",
        {"message": "中兴通讯为什么大跌？", "conversation_id": conversation["id"]},
        client.app.state.settings.workspace_root,
    )
    database.finish_run(
        run["id"],
        user["id"],
        "completed",
        {
            "symbol": "000063.SZ",
            "display_name": "中兴通讯",
            "user_question": "中兴通讯为什么大跌？",
            "current_quote": {
                "name": "中兴通讯",
                "price": 36.47,
                "currency": "CNY",
                "pct_change": 4.56,
                "market_timestamp": "2026-07-22T09:59:06+08:00",
                "source": "Realtime quote",
            },
            "metrics": {"latest_close": 34.88},
            "provenance": {"market_timestamp": "2026-07-21T01:30:00+00:00"},
            "analysis_board": {
                "ready_modules": 1,
                "total_modules": 1,
                "modules": [{"label": "行情结构", "evidence_count": 4}],
            },
            "knowledge_context": {
                "items": [{"title": "研究资料", "scope": "common"}],
                "coverage": {"matched_documents": 1},
            },
            "a_share_information": {
                "announcements": [{"title": "公告"}],
                "news": [],
                "social_posts": [],
            },
        },
        "最终用户可见回答",
        usage={
            "model": "test-model",
            "timings": {
                "routing_and_evidence_seconds": 0.2,
                "model_seconds": 1.1,
                "guard_seconds": 0.01,
                "request_total_seconds": 1.31,
            },
            "output_guard": {
                "passed": True,
                "repair": {"original_unsupported_market_inferences": ["时点"]},
            },
        },
    )
    evaluation_conversation = database.create_conversation(
        user["id"], "验收对话", quality_scope="evaluation"
    )
    evaluation_run = database.create_run(
        user["id"],
        "stock_research",
        "economy",
        {"message": "验收样本", "conversation_id": evaluation_conversation["id"]},
        client.app.state.settings.workspace_root,
    )
    database.finish_run(
        evaluation_run["id"], user["id"], "completed", {}, "不应展示", usage={}
    )

    listed = client.get("/me/run-reviews", params={"days": 7})
    assert listed.status_code == 200
    payload = listed.json()
    assert [item["id"] for item in payload["items"]] == [run["id"]]
    assert payload["items"][0]["guard"]["repaired"] is True
    assert payload["items"][0]["evidence"]["knowledge_documents"] == 1
    assert "不应展示" not in listed.text

    detail = client.get(f"/me/run-reviews/{run['id']}")
    assert detail.status_code == 200
    assert detail.json()["answer"] == "最终用户可见回答"
    assert client.get(f"/me/run-reviews/{evaluation_run['id']}").status_code == 404


def test_demo_user_is_seeded_with_three_research_targets_and_clickable_report(client):
    user = create_user(client, "网页体验用户")
    items = client.get(f"/users/{user['id']}/watchlist").json()["items"]
    assert {item["symbol"] for item in items} == {"000063.SZ", "300308.SZ", "NVDA"}
    assert {item["name"] for item in items} == {"中兴通讯", "中际旭创", "英伟达"}

    first = client.get("/research-reports/000063")
    assert first.status_code == 200
    report = first.json()
    assert report["symbol"] == "000063.SZ"
    assert report["name"] == "中兴通讯"
    assert "TTM市盈率" in report["body"]

    second = client.get("/research-reports/000063").json()
    assert second["id"] == report["id"]
    listed = client.get("/research-reports").json()["items"]
    assert listed[0]["symbol"] == "000063.SZ"

    nvda = client.get("/research-reports/NVDA")
    assert nvda.status_code == 200
    nvda_body = nvda.json()["body"]
    assert "NVIDIA announces new data-center platform" in nvda_body
    assert "NVDA SEC 8-K｜2026-07-02" in nvda_body
    assert "FY2027 Q1 (10-Q)" in nvda_body
    assert "4.96 万亿美元" in nvda_body
    assert "固定同行估值样本" in nvda_body
    assert "超威半导体、博通、台积电" in nvda_body


def test_chat_understands_default_company_names_and_price_move_questions(client, app):
    app.state.analysis.breadth_provider = None
    create_user(client, "网页体验用户")

    response = client.post(
        "/me/chat",
        json={"message": "中兴通讯为什么大跌", "execute_agent": False},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"] == "stock_research"
    assert payload["evidence"]["symbol"] == "000063.SZ"
    assert payload["evidence"]["current_quote"]["price"] == 120.0
    market_context = payload["evidence"]["stock_market_context"]
    assert market_context["company_industry"] == "通信设备"
    assert market_context["exact_industry_match_available"] is False
    assert market_context["indices"]
    assert market_context["market_breadth"]["status"] == "unavailable"
    assert "中兴通讯" in payload["answer"]


def test_chat_compares_two_to_five_named_stocks_and_preserves_context(client):
    create_user(client, "Multi Stock Research User")

    first = client.post(
        "/me/chat",
        json={
            "message": "比较中兴通讯、中际旭创和英伟达的盈利质量、估值和主要风险",
            "execute_agent": False,
        },
    )

    assert first.status_code == 200
    payload = first.json()
    assert payload["intent"] == "stock_comparison"
    assert payload["evidence"]["symbols"] == ["000063.SZ", "300308.SZ", "NVDA"]
    assert payload["research_targets"] == [
        {"symbol": "000063.SZ", "name": "中兴通讯"},
        {"symbol": "300308.SZ", "name": "中际旭创"},
        {"symbol": "NVDA", "name": "英伟达"},
    ]
    assert payload["evidence"]["comparison_basis"]["financial"]["status"] in {
        "exact_common_period",
        "partial_exact_groups",
        "not_aligned",
    }
    assert "关键差异" in payload["answer"]

    followup = client.post(
        "/me/chat",
        json={
            "message": "再重点比较盈利质量，并说明哪些项目当前不可比",
            "conversation_id": payload["conversation_id"],
            "execute_agent": False,
        },
    )

    assert followup.status_code == 200
    followup_payload = followup.json()
    assert followup_payload["intent"] == "stock_comparison"
    assert followup_payload["evidence"]["symbols"] == payload["evidence"]["symbols"]


def test_chat_returns_helpful_clarification_instead_of_http_error(client):
    create_user(client, "Natural Language User")

    response = client.post("/me/chat", json={"message": "帮我看看这只股票"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"] == "clarification"
    assert payload["status"] == "clarification"
    assert "证券代码" in payload["answer"]


def test_chat_understands_natural_language_market_questions(client):
    create_user(client, "Market Question User")

    for message in (
        "美股为什么收盘跌了",
        "昨夜纳指怎么了",
        "A股今天为什么涨",
        "伦敦金现在怎么样",
    ):
        response = client.post("/me/chat", json={"message": message})
        assert response.status_code == 200
        payload = response.json()
        assert payload["intent"] == "market_brief"
        assert payload["status"] != "clarification"
        assert payload["evidence"]["market_drivers"]["items"]
        assert payload["conversation_id"]


def test_chat_routes_named_industry_to_live_market_research(client, app, monkeypatch):
    create_user(client, "Industry Question User")
    captured = {}

    def fake_industry_snapshot(industry_name, market_date=None):
        captured.update({"industry_name": industry_name, "market_date": market_date})
        return {
            "status": "available",
            "industry_name": industry_name,
            "index_code": "H30184",
            "index_name": "半导体",
            "metrics": {
                "return_1d_pct": -1.17,
                "return_5d_pct": 2.35,
                "return_20d_pct": 5.42,
                "trend_state": "中期偏强",
            },
            "points": [
                {
                    "market_date": "2026-07-20",
                    "close": 14568.12,
                    "pct_change": -1.17,
                    "constituent_count": 87,
                }
            ],
            "component_analysis": {
                "status": "available",
                "market_date": "2026-07-20",
                "breadth": {"advancers": 22, "decliners": 63, "unchanged": 2},
            },
        }

    monkeypatch.setattr(app.state.analysis, "industry_snapshot", fake_industry_snapshot)

    response = client.post("/me/chat", json={"message": "半导体行业怎么样"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"] == "market_brief"
    assert payload["evidence"]["question_focus"]["key"] == "sector_rotation"
    assert payload["evidence"]["industry_focus"] == {
        "name": "半导体",
        "market_scope": "A股",
        "requested_by_user": True,
    }
    assert payload["evidence"]["industry_snapshot"]["index_code"] == "H30184"
    assert captured["industry_name"] == "半导体"
    assert captured["market_date"]


def test_market_questions_have_distinct_focus_and_direct_hermes_answers(
    client, app, monkeypatch
):
    create_user(client, "Focused Market User")
    object.__setattr__(app.state.settings, "hermes_enabled", True)

    def fake_hermes(**kwargs):
        prompt = kwargs["prompt"]
        if "A股这次是反弹了吗" in prompt:
            return (
                "这次应回答反弹与趋势确认，并说明尚未满足的确认条件。",
                {"backend": "test"},
            )
        return (
            "这次应回答板块轮动与市场广度，并区分指数和行业结构。",
            {"backend": "test"},
        )

    monkeypatch.setattr(app.state.agent, "_execute_hermes", fake_hermes)
    progress_events = []
    monkeypatch.setattr(app.state.event_broker, "publish", progress_events.append)

    rebound = client.post(
        "/me/chat",
        json={
            "message": "A股这次是反弹了吗",
            "execute_agent": True,
            "request_id": "progress-rebound-001",
        },
    )
    sectors = client.post(
        "/me/chat",
        json={"message": "今天哪些板块在领涨", "execute_agent": True},
    )

    assert rebound.status_code == 200
    assert sectors.status_code == 200
    rebound_payload = rebound.json()
    sector_payload = sectors.json()
    assert rebound_payload["status"] == "completed"
    assert sector_payload["status"] == "completed"
    assert rebound_payload["answer"] != sector_payload["answer"]
    assert rebound_payload["evidence"]["question_focus"]["key"] == "trend_reversal"
    assert sector_payload["evidence"]["question_focus"]["key"] == "sector_rotation"
    assert (
        rebound_payload["evidence"]["market_drivers"]["question_focus"]
        == "trend_reversal"
    )
    assert (
        sector_payload["evidence"]["market_drivers"]["question_focus"]
        == "sector_rotation"
    )
    rebound_progress = [
        item["phase"]
        for item in progress_events
        if item.get("request_id") == "progress-rebound-001"
    ]
    assert rebound_progress == [
        "routing_started",
        "evidence_ready",
        "model_started",
        "guard_started",
        "completed",
    ]


def test_market_risk_terms_take_priority_over_generic_trend_terms(client):
    create_user(client, "Market Risk Focus User")

    response = client.post(
        "/me/chat",
        json={
            "message": "A股趋势失效的主要风险是什么？",
            "execute_agent": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"] == "market_brief"
    assert payload["evidence"]["question_focus"]["key"] == "market_risk"
    assert payload["evidence"]["market_drivers"]["question_focus"] == "market_risk"


def test_market_sector_topic_outweighs_requested_counter_evidence_format(client):
    create_user(client, "Market Sector Compound Focus User")

    response = client.post(
        "/me/chat",
        json={
            "message": (
                "今天A股上涨主要由哪些板块驱动？请区分价格事实、可能解释、"
                "反方证据和不能确认的部分。"
            ),
            "execute_agent": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"] == "market_brief"
    assert payload["evidence"]["question_focus"]["key"] == "sector_rotation"
    assert payload["evidence"]["market_drivers"]["question_focus"] == "sector_rotation"
    assert payload["evidence"]["hot_sectors"]["sectors"]
    assert "算力" in payload["answer"]


def test_market_sector_answer_uses_complete_a_share_breadth(client, app):
    class FakeBreadthProvider:
        @staticmethod
        def fetch_breadth():
            return {
                "source": "Fake A-share breadth",
                "fetched_at": "2026-07-21T07:10:00+00:00",
                "market_timestamp": None,
                "is_stale": False,
                "status": "available",
                "scope": "all_a_shares_including_beijing",
                "coverage": {
                    "expected": 5528,
                    "returned": 5528,
                    "valid_change": 5528,
                    "coverage_ratio": 1.0,
                    "latest_tick_time": "15:30:02",
                },
                "breadth": {
                    "total": 5528,
                    "advancers": 3107,
                    "decliners": 2300,
                    "unchanged": 121,
                    "net_advancers": 807,
                    "advance_ratio": 0.562,
                    "decline_ratio": 0.4161,
                    "unchanged_ratio": 0.0219,
                    "state": "上涨家数占优",
                    "classification_method": (
                        "普涨/普跌要求上涨或下跌比例至少65%，且涨跌家数净差至少500；"
                        "否则只描述哪一方向家数占优。"
                    ),
                },
                "turnover": {
                    "status": "available",
                    "currency": "CNY",
                    "total_amount_cny": 1_234_000_000_000,
                    "total_amount_100m_cny": 12_340.0,
                    "coverage": {"coverage_ratio": 1.0},
                    "exchanges": {
                        "shanghai": {"amount_100m_cny": 5_000.0},
                        "shenzhen": {"amount_100m_cny": 7_000.0},
                        "beijing": {"amount_100m_cny": 340.0},
                    },
                },
                "distribution": {
                    "status": "available",
                    "coverage": {"coverage_ratio": 1.0},
                    "median_pct_change": 0.72,
                    "p25_pct_change": -0.45,
                    "p75_pct_change": 2.31,
                    "bins": {
                        "strong_advancers_ge_3": 1200,
                        "mild_advancers_gt_0_lt_3": 1907,
                        "unchanged": 121,
                        "mild_decliners_lt_0_gt_neg3": 1800,
                        "strong_decliners_le_neg3": 500,
                    },
                },
                "exchange_breakdown": {},
                "warnings": [],
            }

    app.state.analysis.breadth_provider = FakeBreadthProvider()
    create_user(client, "Market Breadth Available User")
    response = client.post(
        "/me/chat",
        json={"message": "今天A股是普涨还是结构性行情？", "execute_agent": False},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["evidence"]["market_state"]["whole_market_breadth_available"] is True
    assert payload["evidence"]["market_state"]["whole_market_breadth_state"] == (
        "上涨家数占优"
    )
    assert "上涨 3107 家" in payload["answer"]
    assert "下跌 2300 家" in payload["answer"]
    assert "固定广度分类为“上涨家数占优”" in payload["answer"]
    assert "全市场当日累计成交额 12340 亿元" in payload["answer"]
    assert "个股涨跌幅分布：中位数 0.72%" in payload["answer"]
    assert "当前仍缺少指数成分贡献度" in payload["answer"]
    assert "不能确认的部分" in payload["answer"]


def test_market_structure_question_takes_priority_over_turnover_keyword(client, app):
    create_user(client, "Market Structure Compound User")

    response = client.post(
        "/me/chat",
        json={
            "message": (
                "今天A股到底是普涨还是结构性行情？请结合上涨下跌家数、"
                "成交额和个股涨跌幅分布说明。"
            ),
            "execute_agent": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["evidence"]["question_focus"]["key"] == "sector_rotation"
    assert payload["evidence"]["market_drivers"]["question_focus"] == (
        "sector_rotation"
    )


def test_market_sector_preview_does_not_mislabel_index_ratio_as_stock_breadth(client):
    create_user(client, "Market Breadth Boundary User")

    response = client.post(
        "/me/chat",
        json={"message": "今天A股是普涨还是结构性行情？", "execute_agent": False},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"] == "market_brief"
    assert payload["evidence"]["market_state"]["breadth_scope"] == "representative_indices"
    assert payload["evidence"]["market_state"]["whole_market_breadth_available"] is False
    assert "不含全市场涨跌家数" in payload["answer"]
    assert "结构性行情" in payload["answer"]


def test_earnings_quality_api_and_chat_routing(client):
    create_user(client, "Earnings Quality User")

    endpoint = client.get("/stocks/000063.SZ/earnings-quality")
    assert endpoint.status_code == 200
    assert endpoint.json()["type"] == "earnings_quality"
    assert endpoint.json()["status"] == "available"

    response = client.post(
        "/me/chat",
        json={"message": "中兴通讯财报质量怎么样", "execute_agent": False},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"] == "earnings_quality"
    assert payload["status"] == "preview"
    assert payload["evidence"]["symbol"] == "000063.SZ"
    assert "财报质量" in payload["answer"]
    assert payload["assistant_message_id"]


def test_earnings_quality_followup_inherits_stock_context(client):
    create_user(client, "Earnings Followup User")
    stock = client.post(
        "/me/chat",
        json={"message": "分析英伟达", "execute_agent": False},
    ).json()

    response = client.post(
        "/me/chat",
        json={
            "message": "现金流质量怎么样",
            "conversation_id": stock["conversation_id"],
            "execute_agent": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"] == "earnings_quality"
    assert payload["evidence"]["symbol"] == "NVDA"
    assert "现金流覆盖" in payload["answer"]


def test_financial_driver_api_and_profit_why_chat_use_detailed_statements(client, app):
    create_user(client, "Financial Driver User")

    endpoint = client.get("/stocks/000063.SZ/financial-drivers")
    assert endpoint.status_code == 200
    packet = endpoint.json()
    assert packet["type"] == "financial_drivers"
    assert packet["status"] == "available"
    assert packet["profit_bridge"]["gross_profit_change"] == -200_000_000.0
    assert packet["confirmed_mechanical_drivers"]
    assert packet["plausible_clues"]
    assert packet["company_explanations"]
    assert packet["filing_evidence"]["document"]["report_period"] == "2026-03-31"
    assert any(
        "汇兑损失" in item["excerpt"]
        for item in packet["company_explanations"]
    )
    assert packet["unresolved_causes"]

    response = client.post(
        "/me/chat",
        json={
            "message": "中兴通讯利润为什么下降",
            "execute_agent": False,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"] == "financial_drivers"
    assert payload["status"] == "preview"
    assert payload["evidence"]["symbol"] == "000063.SZ"
    assert "已确认机械影响" in payload["answer"]
    assert "公司报告解释" in payload["answer"]
    assert "汇兑损失" in payload["answer"]
    assert "仍不能确认" in payload["answer"]

    app.state.database.upsert_knowledge_document(
        document_id="test-annual-filing-context",
        owner_user_id=None,
        scope="common",
        title="中兴通讯财报原文原因证据｜2025-12-31",
        original_name="zte-2025-annual.md",
        mime_type="text/markdown",
        content="中兴通讯 财务费用 公司报告解释 净利息收入",
        source_key="filing-evidence:000063.SZ:AN-ANNUAL",
    )
    focused = client.post(
        "/me/chat",
        json={
            "message": "中兴通讯财务费用为什么大幅上升？公司报告怎么解释",
            "execute_agent": False,
        },
    ).json()
    assert focused["intent"] == "financial_drivers"
    assert "财务费用较可比期变化" in focused["answer"]
    assert "汇兑损失" in focused["answer"]
    assert "存货、备货与跌价" not in focused["answer"]
    assert "投资收益" not in focused["answer"]
    assert all(
        "2025-12-31" not in item["title"]
        for item in focused["knowledge"]["items"]
    )


def test_a_share_filing_endpoint_returns_persisted_full_text_evidence(client):
    payload = client.get("/a-share/000063.SZ/filings").json()

    assert payload["symbol"] == "000063.SZ"
    assert payload["documents"][0]["report_period"] == "2026-03-31"
    assert payload["documents"][0]["content_chars"] > 100
    assert payload["cause_evidence"]["status"] == "available"
    assert any(
        "净利息收入减少" in item["excerpt"]
        for item in payload["cause_evidence"]["explicit_company_explanations"]
    )


def test_financial_driver_followup_inherits_symbol_context(client):
    create_user(client, "Financial Driver Followup User")
    first = client.post(
        "/me/chat",
        json={"message": "分析中兴通讯", "execute_agent": False},
    )
    assert first.status_code == 200

    followup = client.post(
        "/me/chat",
        json={
            "message": "为什么利润下降",
            "conversation_id": first.json()["conversation_id"],
            "execute_agent": False,
        },
    )
    assert followup.status_code == 200
    payload = followup.json()
    assert payload["intent"] == "financial_drivers"
    assert payload["evidence"]["symbol"] == "000063.SZ"
    assert payload["evidence"]["latest_period"]["report_date_name"] == "2026一季报"

    cashflow_followup = client.post(
        "/me/chat",
        json={
            "message": "那现金流为什么转负",
            "conversation_id": first.json()["conversation_id"],
            "execute_agent": False,
        },
    )
    assert cashflow_followup.status_code == 200
    cashflow_payload = cashflow_followup.json()
    assert cashflow_payload["intent"] == "financial_drivers"
    assert cashflow_payload["evidence"]["symbol"] == "000063.SZ"
    assert "待验证线索" in cashflow_payload["answer"]
    assert "经营现金流" in cashflow_payload["answer"]


def test_persistent_conversations_keep_history_and_resolve_stock_followups(
    client, app
):
    create_user(client, "Conversation User")
    created = client.post(
        "/me/conversations",
        json={"title": "中兴通讯持续研究", "quality_scope": "evaluation"},
    )
    assert created.status_code == 201
    assert created.json()["quality_scope"] == "evaluation"
    conversation_id = created.json()["id"]

    first = client.post(
        "/me/chat",
        json={
            "message": "中兴通讯为什么大跌",
            "conversation_id": conversation_id,
            "execute_agent": False,
        },
    )
    assert first.status_code == 200
    assert first.json()["intent"] == "stock_research"
    assert first.json()["conversation_id"] == conversation_id
    assert first.json()["evidence"]["analysis_board"]["ready_modules"] >= 4
    assert [
        item["horizon_sessions"]
        for item in first.json()["evidence"]["analysis_board"]["tracking_plan"]
    ] == [3, 5, 10]

    followup = client.post(
        "/me/chat",
        json={
            "message": "那它接下来最大的风险是什么？",
            "conversation_id": conversation_id,
            "execute_agent": False,
        },
    )
    assert followup.status_code == 200
    payload = followup.json()
    assert payload["intent"] == "stock_research"
    assert payload["evidence"]["symbol"] == "000063.SZ"

    conversation = client.get(f"/me/conversations/{conversation_id}")
    assert conversation.status_code == 200
    messages = conversation.json()["messages"]
    assert [item["role"] for item in messages] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert messages[-1]["metadata"]["symbol"] == "000063.SZ"
    assert conversation.json()["message_count"] == 4

    renamed = client.patch(
        f"/me/conversations/{conversation_id}", json={"title": "通信设备研究"}
    )
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "通信设备研究"
    scoped = client.patch(
        f"/me/conversations/{conversation_id}", json={"quality_scope": "user"}
    )
    assert scoped.status_code == 200
    assert scoped.json()["quality_scope"] == "user"
    listed = client.get("/me/conversations").json()["items"]
    assert listed[0]["id"] == conversation_id
    assert listed[0]["last_message_preview"]

    archived = client.delete(f"/me/conversations/{conversation_id}")
    assert archived.status_code == 204
    assert client.get(f"/me/conversations/{conversation_id}").status_code == 404

    other = TestClient(app)
    create_user(other, "Other Conversation User")
    assert other.get(f"/me/conversations/{conversation_id}").status_code == 404


def test_reanswer_previous_question_inherits_stock_target_from_conversation(client):
    create_user(client, "Reanswer Stock Conversation User")
    initial = client.post(
        "/me/chat",
        json={"message": "中兴通讯为什么大跌", "execute_agent": False},
    )
    assert initial.status_code == 200
    assert initial.json()["intent"] == "stock_research"

    followup = client.post(
        "/me/chat",
        json={
            "message": "请重新回答上一题，注意数字格式。",
            "conversation_id": initial.json()["conversation_id"],
            "execute_agent": False,
        },
    )

    assert followup.status_code == 200
    payload = followup.json()
    assert payload["intent"] == "stock_research"
    assert payload["evidence"]["symbol"] == "000063.SZ"
    assert payload["evidence"]["research_claims"]
    assert "贵州茅台" not in payload["answer"]


def test_guarded_reanswer_uses_stock_fallback_instead_of_general_knowledge(
    client, app, monkeypatch
):
    create_user(client, "Guarded Stock Reanswer User")
    initial = client.post(
        "/me/chat",
        json={"message": "中兴通讯为什么大跌", "execute_agent": False},
    )
    assert initial.status_code == 200

    object.__setattr__(app.state.settings, "hermes_enabled", True)
    monkeypatch.setattr(
        app.state.agent,
        "_execute_hermes",
        lambda **kwargs: (
            "中兴通讯目标价为987654321元，明天上涨99.99%。",
            {"backend": "test"},
        ),
    )
    followup = client.post(
        "/me/chat",
        json={
            "message": "请重新回答上一问，保持针对性。",
            "conversation_id": initial.json()["conversation_id"],
            "execute_agent": True,
        },
    )

    assert followup.status_code == 200
    payload = followup.json()
    assert payload["intent"] == "stock_research"
    assert payload["evidence"]["symbol"] == "000063.SZ"
    assert payload["status"] == "guarded"
    assert "中兴通讯" in payload["answer"]
    assert "贵州茅台" not in payload["answer"]
    assert "987654321" not in payload["answer"]


def test_chat_can_create_evaluation_conversation(client):
    create_user(client, "Evaluation Chat User")

    response = client.post(
        "/me/chat",
        json={
            "message": "今天A股是什么行情？",
            "execute_agent": False,
            "quality_scope": "evaluation",
        },
    )

    assert response.status_code == 200
    conversation_id = response.json()["conversation_id"]
    conversation = client.get(f"/me/conversations/{conversation_id}").json()
    assert conversation["quality_scope"] == "evaluation"


def test_chat_refinement_updates_preview_in_place_without_duplicate_messages(
    client, app, monkeypatch
):
    create_user(client, "Two Stage User")
    preview = client.post(
        "/me/chat",
        json={"message": "美股为什么收盘跌了", "execute_agent": False},
    )
    assert preview.status_code == 200
    preview_payload = preview.json()
    assert preview_payload["status"] == "preview"
    assert preview_payload["assistant_message_id"]
    sp500 = next(
        item
        for item in preview_payload["evidence"]["indices"]
        if item["symbol"] == "^GSPC"
    )
    sp500_return = sp500["metrics"]["return_1d_pct"]

    object.__setattr__(app.state.settings, "hermes_enabled", True)
    monkeypatch.setattr(
        app.state.agent,
        "_execute_hermes",
        lambda **kwargs: (
            f"标普500最近完整日线上涨{sp500_return}%。"
            "市场资讯线索与反方证据需要交叉核对，当前证据不能证明单一原因。",
            {"backend": "test"},
        ),
    )
    refined = client.post(
        "/me/chat/refine",
        json={
            "preview_run_id": preview_payload["run_id"],
            "conversation_id": preview_payload["conversation_id"],
            "assistant_message_id": preview_payload["assistant_message_id"],
            "model_tier": "economy",
        },
    )
    assert refined.status_code == 200
    assert refined.json()["status"] == "completed"

    conversation = client.get(
        f"/me/conversations/{preview_payload['conversation_id']}"
    ).json()
    assert conversation["message_count"] == 2
    assert [item["role"] for item in conversation["messages"]] == [
        "user",
        "assistant",
    ]
    assert conversation["messages"][1]["id"] == preview_payload["assistant_message_id"]
    assert conversation["messages"][1]["metadata"]["refined"] is True
    assert "单一原因" in conversation["messages"][1]["content"]


def test_contextual_quote_followup_keeps_the_previous_stock_target(client):
    create_user(client, "Contextual Quote Followup User")
    initial = client.post(
        "/me/chat",
        json={"message": "中兴通讯为什么大跌", "execute_agent": False},
    )
    assert initial.status_code == 200
    conversation_id = initial.json()["conversation_id"]

    followup = client.post(
        "/me/chat",
        json={
            "message": "现在最新报价是涨还是跌？请区分当前报价和上一完整日线。",
            "conversation_id": conversation_id,
            "execute_agent": False,
        },
    )

    assert followup.status_code == 200
    payload = followup.json()
    assert payload["intent"] == "stock_research"
    assert payload["evidence"]["symbol"] == "000063.SZ"
    assert payload["evidence"].get("current_quote", {}).get("symbol") in {
        None,
        "000063.SZ",
    }
    assert "中际旭创" not in payload["answer"]


def test_session_word_followup_does_not_switch_stock_conversation_to_market(client):
    create_user(client, "Stock Session Word Followup User")
    initial = client.post(
        "/me/chat",
        json={"message": "中兴通讯现在为什么上涨？", "execute_agent": False},
    )
    assert initial.status_code == 200

    followup = client.post(
        "/me/chat",
        json={
            "message": "现在仍在盘中吗？请说明尚未收盘的边界。",
            "conversation_id": initial.json()["conversation_id"],
            "execute_agent": False,
        },
    )

    assert followup.status_code == 200
    payload = followup.json()
    assert payload["intent"] == "stock_research"
    assert payload["evidence"]["symbol"] == "000063.SZ"
    assert "标普500" not in payload["answer"]


def test_market_conversation_followup_keeps_market_and_region_context(client, app):
    user = create_user(client, "Market Conversation User")
    app.state.database.upsert_knowledge_document(
        document_id="user-stock-report-that-must-not-enter-market-followup",
        owner_user_id=user["id"],
        scope="user",
        title="中兴通讯长期研究档案",
        original_name="zte-research.md",
        mime_type="text/markdown",
        content="反方证据 失效条件 美股 市场风险",
        source_key="research-report:000063.SZ",
    )

    first = client.post(
        "/me/chat",
        json={"message": "美股为什么收盘跌了", "execute_agent": False},
    )
    assert first.status_code == 200
    conversation_id = first.json()["conversation_id"]
    assert first.json()["intent"] == "market_brief"
    assert first.json()["evidence"]["market_drivers"]["market_key"] == "us"
    assert [
        item["symbol"] for item in first.json()["evidence"]["indices"]
    ] == ["^GSPC", "^IXIC", "^DJI", "^RUT"]
    assert "标普500" in first.json()["answer"]
    assert "上证综指" not in first.json()["answer"]
    assert all(
        "长期研究档案" not in item["title"]
        for item in first.json()["knowledge"]["items"]
    )
    assert all(
        item["scope"] == "user"
        or item["title"]
        in {
            "清数智算证据层级",
            "市场涨跌原因的证据规则",
            "市场趋势与风险分析规则",
        }
        for item in first.json()["knowledge"]["items"]
    )

    followup = client.post(
        "/me/chat",
        json={
            "message": "那主要风险是什么",
            "conversation_id": conversation_id,
            "execute_agent": False,
        },
    )
    assert followup.status_code == 200
    payload = followup.json()
    assert payload["intent"] == "market_brief"
    assert payload["evidence"]["market_drivers"]["market_key"] == "us"
    assert "标普500" in payload["answer"]

    prompt = (
        Path(app.state.database.get_user(user["id"])["workspace_path"])
        / "runs"
        / payload["run_id"]
        / "prompt.md"
    ).read_text()
    assert "连续追问“那主要风险是什么”" in prompt
    assert "不能喧宾夺主" in prompt
    assert "市场涨跌原因的证据规则" in prompt
    assert '"title": "市场趋势与风险分析规则"' in prompt
    assert "NVIDIA CORP利润与现金流驱动分析" not in prompt
    assert '"name": "上证综指"' not in prompt

    conversation = client.get(f"/me/conversations/{conversation_id}").json()
    assert conversation["messages"][-1]["metadata"]["market_key"] == "us"

    counterevidence = client.post(
        "/me/chat",
        json={
            "message": "这段判断的反方证据和失效条件是什么？",
            "conversation_id": conversation_id,
            "execute_agent": False,
        },
    )
    assert counterevidence.status_code == 200
    counter_payload = counterevidence.json()
    assert counter_payload["intent"] == "market_brief"
    assert counter_payload["evidence"]["market_drivers"]["market_key"] == "us"
    assert counter_payload["evidence"]["question_focus"]["key"] == "market_risk"
    assert all(
        item["title"] != "中兴通讯长期研究档案"
        for item in counter_payload["knowledge"]["items"]
    )
    counter_prompt = (
        Path(app.state.database.get_user(user["id"])["workspace_path"])
        / "runs"
        / counter_payload["run_id"]
        / "prompt.md"
    ).read_text()
    assert "中兴通讯长期研究档案" not in counter_prompt
    assert "美国股市" in counter_prompt
    assert "必须引用其中至少一条作为事件线索" in counter_prompt
    assert "最终回答必须包含标题“失效条件”" in counter_prompt


def test_market_trend_followup_refreshes_market_evidence(client):
    create_user(client, "Market Trend Followup User")

    first = client.post(
        "/me/chat",
        json={"message": "A股今天为什么上涨", "execute_agent": False},
    )
    assert first.status_code == 200
    conversation_id = first.json()["conversation_id"]
    assert first.json()["intent"] == "market_brief"

    followup = client.post(
        "/me/chat",
        json={
            "message": "这更像单日反弹还是趋势反转？只分析趋势确认条件。",
            "conversation_id": conversation_id,
            "execute_agent": False,
        },
    )
    assert followup.status_code == 200
    payload = followup.json()
    assert payload["intent"] == "market_brief"
    assert payload["evidence"]["question_focus"]["key"] == "trend_reversal"
    assert payload["evidence"]["market_drivers"]["market_key"] == "china"
    assert "反弹与趋势确认" in payload["answer"]


def test_explicit_market_question_overrides_prior_stock_context(client):
    create_user(client, "Market Override User")

    stock = client.post(
        "/me/chat",
        json={"message": "中兴通讯为什么大跌", "execute_agent": False},
    )
    assert stock.status_code == 200
    conversation_id = stock.json()["conversation_id"]
    assert stock.json()["intent"] == "stock_research"

    market = client.post(
        "/me/chat",
        json={
            "message": "美股为什么收盘跌了",
            "conversation_id": conversation_id,
            "execute_agent": False,
        },
    )
    assert market.status_code == 200
    payload = market.json()
    assert payload["intent"] == "market_brief"
    assert payload["evidence"]["market_drivers"]["market_key"] == "us"
    assert "标普500" in payload["answer"]
    assert "中兴通讯" not in payload["answer"]


def test_user_and_common_knowledge_are_retrieved_and_written_to_prompt(client, app):
    user = create_user(client, "Knowledge User")
    common = client.get("/me/knowledge")
    assert common.status_code == 200
    assert common.json()["summary"]["common"] >= 3

    uploaded = client.post(
        "/me/knowledge",
        files={
            "file": (
                "optical-module-notes.md",
                "# 光模块跟踪笔记\n重点检查 800G 订单兑现、客户集中度与毛利率变化。".encode(),
                "text/markdown",
            )
        },
    )
    assert uploaded.status_code == 201
    document = uploaded.json()
    assert document["scope"] == "user"
    detail = client.get(f"/me/knowledge/{document['id']}")
    assert detail.status_code == 200
    assert detail.json()["title"] == "光模块跟踪笔记"
    assert "800G 订单兑现" in detail.json()["content"]
    assert client.get("/me/knowledge/not-found").status_code == 404

    response = client.post(
        "/me/chat",
        json={"message": "我的资料里光模块订单要怎么跟踪？"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"] == "general_research"
    assert any(
        item["title"] == "光模块跟踪笔记" for item in payload["knowledge"]["items"]
    )
    run = app.state.database.get_run(payload["run_id"], user["id"])
    prompt_path = (
        Path(app.state.database.get_user(user["id"])["workspace_path"])
        / "runs"
        / run["id"]
        / "prompt.md"
    )
    prompt = prompt_path.read_text()
    assert "本对话最近上下文" in prompt
    assert "光模块跟踪笔记" in prompt
    assert "800G 订单兑现" in prompt

    stored = (
        Path(app.state.database.get_user(user["id"])["workspace_path"])
        / "knowledge"
        / f"{document['id']}.txt"
    )
    assert stored.is_file()
    assert client.delete(f"/me/knowledge/{document['id']}").status_code == 204
    assert not stored.exists()


def test_stock_chat_uses_latest_server_report_when_live_price_refresh_fails(
    client, app, monkeypatch
):
    user = create_user(client, "网页体验用户")
    report = client.get("/research-reports/000063")
    assert report.status_code == 200

    def fail_live_build(*args, **kwargs):
        raise ProviderError("temporary live failure")

    monkeypatch.setattr(app.state.research_evidence, "build", fail_live_build)
    response = client.post(
        "/me/chat",
        json={"message": "中兴通讯为什么大跌", "execute_agent": False},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"] == "stock_research"
    assert payload["evidence"]["symbol"] == "000063.SZ"
    assert payload["evidence"]["precomputed_report"]["title"].startswith("中兴通讯")
    assert payload["answer"]
    prompt = (
        Path(app.state.database.get_user(user["id"])["workspace_path"])
        / "runs"
        / payload["run_id"]
        / "prompt.md"
    ).read_text()
    assert "不能机械输出一份全景研究报告" in prompt
    assert "最多四个小标题" in prompt
    assert "不得解释内部行情为何未返回" in prompt
    assert "独立于大盘/行业" in prompt


def test_stock_chat_uses_saved_report_only_as_evidence_for_live_hermes_answer(
    client, app, monkeypatch
):
    create_user(client, "即时研究用户")
    report = client.get("/research-reports/000063")
    assert report.status_code == 200

    def fail_live_build(*args, **kwargs):
        raise ProviderError("temporary live failure")

    calls = []

    def fake_hermes(**kwargs):
        calls.append(kwargs)
        return (
            "这是针对‘中兴通讯为什么大跌’本轮问题即时生成的回答；"
            "历史报告只作为证据，不是直接返回的答案。",
            {"backend": "test-live"},
        )

    object.__setattr__(app.state.settings, "hermes_enabled", True)
    monkeypatch.setattr(app.state.research_evidence, "build", fail_live_build)
    monkeypatch.setattr(app.state.agent, "_execute_hermes", fake_hermes)

    response = client.post(
        "/me/chat",
        json={"message": "中兴通讯为什么大跌", "execute_agent": True},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["evidence"]["precomputed_report"]["title"].startswith("中兴通讯")
    assert "本轮问题即时生成" in payload["answer"]
    assert calls
    assert "中兴通讯为什么大跌" in calls[0]["prompt"]


def test_memory_requires_confirmation_and_is_user_scoped(app):
    alice_client = TestClient(app)
    bob_client = TestClient(app)
    alice = create_user(alice_client, "Alice")
    create_user(bob_client, "Bob")
    alice_record = app.state.database.get_user(alice["id"])
    assert alice_record is not None
    candidate = alice_client.post(
        f"/users/{alice['id']}/memories/candidates",
        json={"kind": "risk_preference", "content": "我更在意最大回撤"},
    ).json()
    assert candidate["status"] == "candidate"
    assert alice_client.get(f"/users/{alice['id']}/memories").json()["items"] == []
    before = alice_client.post(
        f"/users/{alice['id']}/chat", json={"message": "今天大盘怎么样？"}
    ).json()
    before_prompt = (
        Path(alice_record["workspace_path"]) / "runs" / before["run_id"] / "prompt.md"
    ).read_text()
    assert "我更在意最大回撤" not in before_prompt
    assert (
        bob_client.post(
            f"/users/{alice['id']}/memories/{candidate['id']}/confirm"
        ).status_code
        == 404
    )
    confirmed = alice_client.post(
        f"/users/{alice['id']}/memories/{candidate['id']}/confirm"
    ).json()
    assert confirmed["status"] == "confirmed"
    assert len(alice_client.get(f"/users/{alice['id']}/memories").json()["items"]) == 1
    after = alice_client.post(
        f"/users/{alice['id']}/chat", json={"message": "今天大盘怎么样？"}
    ).json()
    after_prompt = (
        Path(alice_record["workspace_path"]) / "runs" / after["run_id"] / "prompt.md"
    ).read_text()
    assert "我更在意最大回撤" in after_prompt
    confirmed_file = (
        Path(alice_record["workspace_path"]) / "memory" / "confirmed.json"
    ).read_text()
    assert "我更在意最大回撤" in confirmed_file


def test_session_logout_and_one_time_legacy_demo_workspace_claim(app):
    client = TestClient(app)
    user = create_user(client, "Session User")
    raw_token = client.cookies.get("qingshu_session")
    assert raw_token
    with app.state.database.connect() as connection:
        stored = connection.execute(
            "SELECT token_hash FROM user_sessions WHERE user_id = ?", (user["id"],)
        ).fetchone()
    assert stored is not None
    assert stored["token_hash"] == hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    assert stored["token_hash"] != raw_token
    assert client.get("/me").json()["id"] == user["id"]
    assert client.delete("/session").status_code == 204
    assert client.get("/session").status_code == 401

    legacy = app.state.database.create_user("网页体验用户")
    claim_client = TestClient(app)
    claimed = claim_client.post("/sessions/claim", json={"user_id": legacy["id"]})
    assert claimed.status_code == 200
    assert claimed.json()["id"] == legacy["id"]
    assert claim_client.get("/session").json()["id"] == legacy["id"]

    second_client = TestClient(app)
    second = second_client.post("/sessions/claim", json={"user_id": legacy["id"]})
    assert second.status_code == 409


def test_my_memory_confirmation_and_rejection_flow(app):
    client = TestClient(app)
    user = create_user(client, "Memory User")
    user_record = app.state.database.get_user(user["id"])
    assert user_record is not None

    candidate_run = client.post(
        "/me/chat", json={"message": "记住：我更重视最大回撤"}
    )
    assert candidate_run.status_code == 200
    candidate = candidate_run.json()["evidence"]["memory"]
    assert candidate["status"] == "candidate"
    pending = client.get("/me/memories", params={"status": "candidate"}).json()[
        "items"
    ]
    assert [item["id"] for item in pending] == [candidate["id"]]

    confirmed = client.post(f"/me/memories/{candidate['id']}/confirm")
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "confirmed"
    assert client.get("/me/memories").json()["items"][0]["content"] == "我更重视最大回撤"

    rejected_run = client.post(
        "/me/chat", json={"message": "记住：我不关心任何风险"}
    ).json()
    rejected = rejected_run["evidence"]["memory"]
    rejected_response = client.post(f"/me/memories/{rejected['id']}/reject")
    assert rejected_response.status_code == 200
    assert rejected_response.json()["status"] == "rejected"

    market = client.post("/me/chat", json={"message": "今天大盘怎么样？"}).json()
    prompt = (
        Path(user_record["workspace_path"])
        / "runs"
        / market["run_id"]
        / "prompt.md"
    ).read_text()
    assert "我更重视最大回撤" in prompt
    assert "我不关心任何风险" not in prompt


def test_private_image_upload_and_visual_research_routing(app):
    owner = TestClient(app)
    other = TestClient(app)
    user = create_user(owner, "Vision User")
    other_user = create_user(other, "Other Vision User")
    assert other_user["id"] != user["id"]

    buffer = BytesIO()
    Image.new("RGB", (32, 24), color=(20, 80, 120)).save(buffer, format="PNG")
    uploaded = owner.post(
        "/me/uploads/images",
        files={"file": ("chart.png", buffer.getvalue(), "image/png")},
    )
    assert uploaded.status_code == 201
    metadata = uploaded.json()
    assert metadata["mime_type"] == "image/png"
    assert metadata["width"] == 32
    assert metadata["height"] == 24
    assert "workspace_path" not in metadata

    stored = app.state.database.get_user_upload(user["id"], metadata["id"])
    assert stored is not None
    stored_path = Path(stored["workspace_path"])
    assert stored_path.is_file()
    assert stored_path.is_relative_to(Path(app.state.database.get_user(user["id"])["workspace_path"]))
    with Image.open(stored_path) as sanitized:
        assert sanitized.format == "PNG"
        assert sanitized.size == (32, 24)

    cross_user = other.post(
        "/me/chat",
        json={
            "message": "分析这张图",
            "model_tier": "vision",
            "image_id": metadata["id"],
        },
    )
    assert cross_user.status_code == 404

    preview = owner.post(
        "/me/chat",
        json={
            "message": "分析这张图",
            "model_tier": "economy",
            "execute_agent": False,
            "image_id": metadata["id"],
        },
    )
    assert preview.status_code == 200
    payload = preview.json()
    assert payload["intent"] == "visual_research"
    assert payload["model_tier"] == "vision"
    assert payload["status"] == "preview"
    assert "AI 图像研究" in payload["answer"]
    run = app.state.database.get_run(payload["run_id"], user["id"])
    assert run is not None and run["input"]["image_attached"] is True
    prompt = (
        Path(app.state.database.get_user(user["id"])["workspace_path"])
        / "runs"
        / payload["run_id"]
        / "prompt.md"
    ).read_text()
    assert "# Visual Research" in prompt

    invalid = owner.post(
        "/me/uploads/images",
        files={"file": ("not-an-image.png", b"not an image", "image/png")},
    )
    assert invalid.status_code == 422


def test_market_watchlist_and_stock_chat_flows(client):
    user = create_user(client, "Researcher")
    client.post(
        f"/users/{user['id']}/watchlist",
        json={"symbol": "600519", "name": "贵州茅台", "thesis": "需求可能企稳"},
    )

    market = client.post(
        f"/users/{user['id']}/chat", json={"message": "今天大盘和板块怎么样？"}
    )
    assert market.status_code == 200
    assert market.json()["intent"] == "market_brief"
    assert market.json()["evidence"]["market_state"]["label"] in {
        "偏强",
        "承压",
        "分化",
        "中性",
    }

    watchlist = client.get(f"/users/{user['id']}/watchlist/brief")
    assert watchlist.status_code == 200
    item = watchlist.json()["items"][0]
    assert item["metrics"]["ma20"] is not None
    assert item["metrics"]["volatility_20d_annualized_pct"] is not None

    stock = client.post(
        f"/users/{user['id']}/chat",
        json={
            "message": "贵州茅台现在值得继续研究什么？",
            "symbol": "600519",
            "model_tier": "deep",
        },
    )
    assert stock.status_code == 200
    result = stock.json()
    assert result["intent"] == "stock_research"
    assert result["model_tier"] == "deep"
    assert "不能证明" in result["answer"]
    assert result["evidence"]["provenance"]["source"] == "Fake deterministic provider"
    info = result["evidence"]["a_share_information"]
    assert info["announcements"][0]["title"] == "公司发布重大事项公告"
    assert info["sentiment"]["sample_size"] == 1
    assert "股吧关键词" in result["answer"]
    outlook = result["evidence"]["conditional_outlook"]
    assert outlook["probability"] is None
    assert len(outlook["scenarios"]) == 3
    assert outlook["method"] == "transparent_rule_based_outlook_v2"
    assert outlook["calibration"]["method"] == "fixed_rule_prequential_oos_v2"
    assert "条件展望" in result["answer"]
    assert "历史走查" in result["answer"]
    debate = result["evidence"]["evidence_debate"]
    assert debate["method"] == "deterministic_evidence_debate_v3"
    claim_ledger = result["evidence"]["research_claims"]
    assert claim_ledger["method"] == "structured_claim_ledger_v1"
    assert claim_ledger["claims"]
    assert all(item.get("source_name") for item in claim_ledger["claims"])
    assert any(item.get("data_time") for item in claim_ledger["claims"])
    assert "多方证据结论" in result["answer"]
    fundamentals = result["evidence"]["fundamentals"]
    assert fundamentals["valuation"]["pe_ttm"] == 18.5
    assert fundamentals["summary"]["latest_report"]["revenue_yoy_pct"] == 8.5
    assert "TTM市盈率" in result["answer"]
    assert "结构化财务与估值数据尚未接入" not in result["answer"]


def test_stock_claim_prompt_prioritizes_claims_and_blocks_raw_units(app, client):
    user = create_user(client, "Claim Prompt User")

    response = client.post(
        "/me/chat",
        json={
            "message": "中兴通讯最强的反方证据是什么？哪些只是价格波动？",
            "symbol": "000063",
            "model_tier": "deep",
            "execute_agent": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["evidence"]["research_claims"]["claims"]
    prompt = (
        Path(app.state.database.get_user(user["id"])["workspace_path"])
        / "runs"
        / payload["run_id"]
        / "prompt.md"
    ).read_text(encoding="utf-8")
    assert "结构化 Claim 使用要求" in prompt
    assert "不得从 fundamentals、financial_drivers 等深层结构拼接" in prompt
    assert "不得写成趋势反证已经" in prompt


def test_focused_plan_request_uses_claim_ledger_and_forbids_invented_plan_levels(
    app, client
):
    user = create_user(client, "Focused Plan Prompt User")
    response = client.post(
        "/me/chat",
        json={
            "message": (
                "分析中兴通讯并生成操作计划，核验条件：如果下一期经营现金流继续恶化，"
                "由我重新评估是否减仓；不要填写目标价、数量或仓位。"
            ),
            "symbol": "000063",
            "model_tier": "deep",
            "execute_agent": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"] == "earnings_quality"
    assert payload["evidence"]["research_claims"]["claims"]
    prompt = (
        Path(app.state.database.get_user(user["id"])["workspace_path"])
        / "runs"
        / payload["run_id"]
        / "prompt.md"
    ).read_text(encoding="utf-8")
    compact_prompt = " ".join(prompt.split())
    assert "用户确认式操作计划要求" in prompt
    assert "用户在本轮消息里明确给出的核验条件" in compact_prompt
    assert "不能改造成计划门槛" in compact_prompt
    assert "触发条件”必须逐字保留用户原句" in compact_prompt


def test_watchlist_can_be_managed_and_stock_intraday_is_available(client):
    create_user(client, "Watchlist UI User")
    created = client.post(
        "/me/watchlist",
        json={
            "symbol": "300750",
            "name": "宁德时代",
            "market": "A股",
            "thesis": "关注动力电池与储能业务",
        },
    )
    assert created.status_code == 200
    assert created.json()["symbol"] == "300750.SZ"

    intraday = client.get("/stocks/300750.SZ/intraday")
    assert intraday.status_code == 200
    assert intraday.json()["data_granularity"] == "1m"
    assert intraday.json()["points"]
    assert intraday.json()["latest_price"] is not None

    deleted = client.delete("/me/watchlist/300750.SZ")
    assert deleted.status_code == 204
    assert client.get("/me/watchlist").json()["items"] == []
    assert client.delete("/me/watchlist/300750.SZ").status_code == 404


def test_a_share_information_endpoint_returns_layered_sources(client):
    payload = client.get("/a-share/600519/information").json()
    assert payload["symbol"] == "600519.SS"
    assert payload["announcements"][0]["category"] == "announcement"
    assert payload["news"][0]["category"] == "news"
    assert payload["social_posts"][0]["category"] == "social"
    assert payload["sentiment"]["method"] == "keyword_engagement_weighted_v1"


def test_a_share_fundamentals_endpoint_returns_valuation_and_reports(client):
    payload = client.get("/a-share/600519/fundamentals").json()
    assert payload["symbol"] == "600519.SS"
    assert payload["valuation"]["pe_ttm"] == 18.5
    assert payload["valuation"]["total_market_cap"] == 100_000_000_000.0
    assert payload["financial_periods"][0]["report_date_name"] == "2026一季报"
    assert payload["summary"]["operating_cashflow_to_net_profit"] == 0.75


def test_us_equity_fundamentals_endpoint_returns_sec_and_valuation_evidence(client):
    payload = client.get("/us-equity/NVDA/fundamentals").json()
    assert payload["symbol"] == "NVDA"
    assert payload["valuation"]["pe_ttm"] == 31.34
    assert payload["valuation"]["currency"] == "USD"
    assert payload["financial_periods"][0]["report_type"] == "10-Q"
    assert payload["financial_periods"][0]["eps_diluted"] == 2.39
    assert payload["summary"]["latest_report"]["period_basis_label"].startswith(
        "财政年度累计"
    )
    assert payload["regulatory_filings"][0]["category"] == "regulatory_filing"


def test_peer_comparison_endpoint_returns_fixed_sample_and_medians(client):
    payload = client.get("/peer-comparisons/000063").json()
    assert payload["symbol"] == "000063.SZ"
    assert payload["coverage"] == {"requested_peers": 3, "available_peers": 3}
    assert payload["metrics"]["pe_ttm"]["peer_sample_size"] == 3
    assert payload["method"] == "fixed_peer_valuation_snapshot_v1"
    assert {item["name"] for item in payload["peers"]} == {
        "烽火通信",
        "紫光股份",
        "锐捷网络",
    }
    operating = payload["operating_comparison"]
    assert operating["method"] == "fixed_peer_operating_comparison_v1"
    assert operating["anchor_report_date"] == "2026-03-31"
    assert operating["coverage"]["same_period_financial_peers"] == 3
    assert operating["metrics"]["gross_margin_pct"]["peer_sample_size"] == 3


def test_outlook_calibration_endpoint_returns_chronological_holdout(client):
    payload = client.get("/outlook-calibrations/600519").json()
    assert payload["symbol"] == "600519.SS"
    assert payload["calibration"]["method"] == "fixed_rule_prequential_oos_v2"
    assert payload["calibration"]["horizons"]["10d"]["out_of_sample"][
        "sample_size"
    ] > 0


def test_market_pulse_article_is_quality_gated_and_rate_limited(client):
    create_user(client, "Editor")
    other_user = create_user(client, "Reader")
    first = client.post(
        "/articles/market-pulse",
        json={"model_tier": "economy"},
    )
    assert first.status_code == 200
    result = first.json()
    assert result["decision"] == "published"
    assert result["quality"]["score"] >= result["quality"]["threshold"]
    assert result["article"]["title"].startswith("市场脉冲｜")
    assert "数据边界" in result["article"]["body"]

    second = client.post(
        "/articles/market-pulse",
        json={"model_tier": "economy"},
    )
    assert second.status_code == 200
    assert second.json()["decision"] == "suppressed"
    assert "不足 4 小时" in second.json()["reason"]
    assert len(client.get("/articles").json()["items"]) == 1

    conversational = client.post(
        f"/users/{other_user['id']}/chat",
        json={"message": "生成一篇市场脉冲行情文章"},
    )
    assert conversational.status_code == 200
    assert conversational.json()["decision"] == "suppressed"
    assert len(client.get("/articles").json()["items"]) == 1


def test_market_pulse_is_withheld_when_index_evidence_is_missing(settings):
    class FailingMarketProvider:
        def fetch_history(self, *args, **kwargs):
            raise ProviderError("index source unavailable")

    class MinimalSectorProvider:
        def fetch_hot_sectors(self, limit=20):
            return {
                "source": "fake",
                "market_timestamp": None,
                "fetched_at": "2026-07-20T00:00:00+00:00",
                "is_stale": False,
                "coverage": {"returned": 1, "total_available": 1},
                "warnings": [],
                "sectors": [{"code": "BK1", "name": "板块", "pct_change": 1.0}],
            }

    local_client = TestClient(
        create_app(settings, FailingMarketProvider(), MinimalSectorProvider())
    )
    result = local_client.post("/articles/market-pulse", json={}).json()
    assert result["decision"] == "withheld"
    assert result["quality"]["score"] < result["quality"]["threshold"]
    assert local_client.get("/articles").json()["items"] == []
