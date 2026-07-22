from __future__ import annotations

from dataclasses import replace
from io import StringIO
import json
from pathlib import Path

import app.services.agent as agent_module
from app.db import Database
from app.services.agent import AgentService


class _FakeStreamingProcess:
    def __init__(self, lines: list[str], return_code: int = 0, stderr: str = ""):
        self.stdout = iter(lines)
        self.stderr = StringIO(stderr)
        self.return_code = return_code
        self.terminated = False

    def poll(self):
        return None if not self.terminated else self.return_code

    def wait(self, timeout=None):
        self.terminated = True
        return self.return_code

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.terminated = True


def test_numeric_guard_accepts_evidence_rounding_and_rejects_new_targets():
    evidence = {
        "type": "stock_research",
        "valuation": {"total_market_cap": 4_943_263_890_000.0, "pe_ttm": 31.17},
        "probability": None,
    }
    valid = AgentService._validate_model_output(
        "总市值约4.94万亿美元，TTM市盈率31.17；不提供目标价。", evidence
    )
    invalid = AgentService._validate_model_output(
        "目标价9999元，未来上涨概率80%。", evidence
    )

    assert valid["passed"] is True
    assert invalid["passed"] is False
    assert "9999" in invalid["unsupported_numbers"]
    assert invalid["prohibited_patterns"]


def test_stock_research_number_precision_is_limited_to_two_decimals():
    answer = (
        "2026-04-25 中兴通讯 000063.SZ：营收同比 +6.126696%，"
        "经营现金流/净利润 0.755，毛利影响 -20.975 亿元；"
        "MA20 为 37.2805，60日收益 -6.5881%。"
    )

    normalized = agent_module._normalize_stock_research_number_precision(answer)

    assert normalized == (
        "2026-04-25 中兴通讯 000063.SZ：营收同比 +6.13%，"
        "经营现金流/净利润 0.76，毛利影响 -20.98 亿元；"
        "MA20 为 37.28，60日收益 -6.59%。"
    )


def test_numeric_guard_understands_directional_percentage_language():
    evidence = {
        "type": "market_brief",
        "generated_at": "2026-07-20T19:21:56+00:00",
        "indices": [
            {
                "metrics": {
                    "return_1d_pct": -5.3957,
                    "return_20d_pct": -14.4961,
                    "max_drawdown_60d_pct": -16.2811,
                }
            }
        ],
    }
    valid = AgentService._validate_model_output(
        "1. 深证成指一日跌 5.40%，近20日跌 14.50%，"
        "60日最大回撤已超16%。证据生成于 2026-07-20 19:21。",
        evidence,
    )
    reversed_direction = AgentService._validate_model_output(
        "深证成指一日上涨 5.40%。", evidence
    )
    historical_decline = AgentService._validate_model_output(
        "深证成指当日下跌 5.40%。", evidence
    )

    assert valid["passed"] is True
    assert valid["method"] == "deterministic_numeric_and_policy_guard_v2"
    assert historical_decline["passed"] is True
    assert historical_decline["prohibited_patterns"] == []
    assert reversed_direction["passed"] is False
    assert "5.40%" in reversed_direction["unsupported_numbers"]


def test_numeric_guard_does_not_carry_drawdown_direction_across_list_separator():
    evidence = {
        "type": "stock_research",
        "metrics": {
            "max_drawdown_60d_pct": -16.78,
            "volatility_20d_annualized_pct": 69.0637,
        },
    }

    guarded = AgentService._validate_model_output(
        "60日最大回撤 -16.78%、20日年化波动率 69.06%。",
        evidence,
    )

    assert guarded["passed"] is True
    assert guarded["unsupported_numbers"] == []


def test_numeric_guard_treats_arrow_ratios_as_absolute_values():
    evidence = {
        "type": "financial_drivers",
        "expense_analysis": [
            {
                "label": "销售费用",
                "current_ratio_pct": 5.768,
                "comparable_ratio_pct": 6.983,
                "ratio_change_pp": -1.215,
            }
        ],
    }

    valid = AgentService._validate_model_output(
        "销售费用减少，费用率 6.983%→5.768%，下降 1.215 个百分点。",
        evidence,
    )
    invented = AgentService._validate_model_output(
        "销售费用减少，费用率 6.983%→4.000%。",
        evidence,
    )

    assert valid["passed"] is True
    assert invented["passed"] is False
    assert "4.000%" in invented["unsupported_numbers"]


def test_numeric_guard_understands_english_direction_in_news_titles():
    evidence = {
        "type": "market_brief",
        "market_drivers": {
            "items": [
                {
                    "title": (
                        "U.S. stocks lower at close of trade; "
                        "Dow Jones Industrial Average down 0.59%"
                    )
                }
            ]
        },
    }

    valid = AgentService._validate_model_output(
        "资讯标题显示道指约 -0.59%。", evidence
    )
    reversed_direction = AgentService._validate_model_output(
        "资讯标题显示道指约 +0.59%。", evidence
    )

    assert valid["passed"] is True
    assert reversed_direction["passed"] is False
    assert "+0.59%" in reversed_direction["unsupported_numbers"]


def test_numeric_guard_accepts_one_decimal_percentage_rounding():
    evidence = {
        "type": "market_brief",
        "indices": [
            {"name": "标普500", "metrics": {"return_60d_pct": 4.2783}}
        ],
    }

    valid = AgentService._validate_model_output(
        "标普500近60日约 +4.3%。", evidence
    )
    invalid = AgentService._validate_model_output(
        "标普500近60日约 +4.4%。", evidence
    )

    assert valid["passed"] is True
    assert invalid["passed"] is False
    assert "+4.4%" in invalid["unsupported_numbers"]


def test_numeric_guard_accepts_integer_range_derived_from_evidence():
    evidence = {
        "type": "market_brief",
        "indices": [
            {"name": "上证综指", "metrics": {"return_20d_pct": -6.6582}},
            {"name": "深证成指", "metrics": {"return_20d_pct": -10.6591}},
        ],
    }

    valid = AgentService._validate_model_output(
        "两指数20日跌幅仍达6%—11%，趋势反转尚未确认。", evidence
    )
    invented = AgentService._validate_model_output(
        "两指数20日跌幅仍达3%—15%，趋势反转尚未确认。", evidence
    )

    assert valid["passed"] is True
    assert invented["passed"] is False
    assert set(invented["unsupported_numbers"]) == {"3%", "15%"}


def test_numeric_only_guard_failure_keeps_question_specific_model_answer(
    tmp_path: Path, settings, monkeypatch
):
    guarded_settings = replace(
        settings,
        database_path=tmp_path / "guard-repair.db",
        workspace_root=tmp_path / "workspaces-guard-repair",
        hermes_enabled=True,
    )
    database = Database(guarded_settings.database_path, guarded_settings.workspace_root)
    database.initialize()
    user = database.create_user("Guard Repair User")
    service = AgentService(database, guarded_settings)
    model_answer = (
        "结论：这更像超跌后的短期修复，中期反转还没有确认。\n\n"
        "- 上证综指近20日下跌6.66%，仍位于20日均线下方。\n"
        "- 传闻中的资金规模为9999亿元，这一行没有证据支持。\n"
        "- 后续应观察指数能否重新站上20日均线，以及量能能否连续。\n\n"
        "以上只解释已经发生的市场结构，不预测下一交易日方向。"
    )
    monkeypatch.setattr(
        service,
        "_execute_hermes",
        lambda **kwargs: (model_answer, {"model": "fake"}),
    )
    evidence = {
        "type": "market_brief",
        "question_focus": {"key": "trend_reversal"},
        "indices": [
            {
                "name": "上证综指",
                "status": "available",
                "metrics": {"return_20d_pct": -6.6582},
            }
        ],
    }
    progress = []

    run = service.run(
        user=user,
        intent="market_brief",
        message="A股这次是反弹还是反转？",
        evidence=evidence,
        model_tier="economy",
        execute_agent=True,
        pre_run_timings={"routing_and_evidence_seconds": 1.25},
        progress_callback=progress.append,
    )

    assert run["status"] == "completed"
    assert "短期修复" in run["answer"]
    assert "9999" not in run["answer"]
    assert "本次问题焦点" not in run["answer"]
    assert run["usage"]["output_guard"]["repair"]["method"] == (
        "drop_unsupported_numeric_lines_v1"
    )
    timings = run["usage"]["timings"]
    assert timings["routing_and_evidence_seconds"] == 1.25
    assert timings["model_seconds"] >= 0
    assert timings["guard_seconds"] >= 0
    assert timings["request_total_seconds"] >= 1.25
    assert [item["phase"] for item in progress] == [
        "model_started",
        "guard_started",
        "completed",
    ]
    run_dir = Path(run["workspace_path"]) / "runs" / run["id"]
    assert (run_dir / "answer.rejected.md").is_file()
    assert (run_dir / "answer.repaired.md").is_file()


def test_output_guard_accepts_numbers_from_prior_guarded_assistant_answer():
    evidence = {
        "type": "market_brief",
        "generated_at": "2026-07-21T04:43:15+00:00",
        "indices": [
            {"name": "上证综指", "metrics": {"return_1d_pct": 0.62}}
        ],
    }
    answer = (
        "上证综指当日上涨 0.62%。市场资讯沿用上一轮已核验时点："
        "2026-07-21T04:41Z。"
    )
    prior_assistant_answer = (
        "市场资讯截至 2026-07-21T04:41Z；以上只描述当前截面。"
    )

    without_history = AgentService._validate_model_output(answer, evidence)
    with_history = AgentService._validate_model_output(
        answer,
        evidence,
        trusted_context=[prior_assistant_answer],
    )

    assert without_history["passed"] is False
    assert "41" in without_history["unsupported_numbers"]
    assert with_history["passed"] is True


def test_run_guard_does_not_trust_numeric_claims_from_user_history(
    tmp_path: Path, settings, monkeypatch
):
    guarded_settings = replace(
        settings,
        database_path=tmp_path / "guard-user-history.db",
        workspace_root=tmp_path / "workspaces-guard-user-history",
        hermes_enabled=True,
    )
    database = Database(guarded_settings.database_path, guarded_settings.workspace_root)
    database.initialize()
    user = database.create_user("Guarded History User")
    service = AgentService(database, guarded_settings)
    monkeypatch.setattr(
        service,
        "_execute_hermes",
        lambda **kwargs: ("目标价9999元。", {"model": "fake"}),
    )

    run = service.run(
        user=user,
        intent="memory_candidate",
        message="继续分析",
        evidence={"type": "memory_candidate", "memory": {"content": "关注回撤"}},
        model_tier="economy",
        execute_agent=True,
        conversation_history=[
            {"role": "user", "content": "我认为目标价是9999元", "run_id": None}
        ],
    )

    assert run["status"] == "guarded"
    assert "9999" not in run["answer"]


def test_run_guard_does_not_trust_numeric_claims_from_assistant_history(
    tmp_path: Path, settings, monkeypatch
):
    guarded_settings = replace(
        settings,
        database_path=tmp_path / "guard-assistant-history.db",
        workspace_root=tmp_path / "workspaces-guard-assistant-history",
        hermes_enabled=True,
    )
    database = Database(guarded_settings.database_path, guarded_settings.workspace_root)
    database.initialize()
    user = database.create_user("Guarded Assistant History User")
    service = AgentService(database, guarded_settings)
    monkeypatch.setattr(
        service,
        "_execute_hermes",
        lambda **kwargs: ("盘中曾达到9999元。", {"model": "fake"}),
    )

    run = service.run(
        user=user,
        intent="memory_candidate",
        message="继续分析",
        evidence={"type": "memory_candidate", "memory": {"content": "关注回撤"}},
        model_tier="economy",
        execute_agent=True,
        conversation_history=[
            {
                "role": "assistant",
                "content": "上一轮误写盘中高点为9999元",
                "run_id": "prior-run",
            }
        ],
    )

    assert run["status"] == "guarded"
    assert "9999" not in run["answer"]


def test_output_guard_rejects_reversed_community_sentiment_direction():
    evidence = {
        "type": "stock_research",
        "a_share_information": {
            "sentiment": {
                "band": "轻微偏多",
                "score": 0.1713,
                "sample_size": 21,
                "positive_count": 6,
                "negative_count": 3,
                "neutral_count": 12,
            }
        },
    }

    valid = AgentService._validate_model_output(
        "股吧社区情绪为轻微偏多，但只能作为弱证据。", evidence
    )
    invalid = AgentService._validate_model_output(
        "社区讨论情绪转负，这解释了下跌。", evidence
    )

    assert valid["passed"] is True
    assert valid["semantic_conflicts"] == []
    assert invalid["passed"] is False
    assert invalid["semantic_conflicts"] == [
        "社区情绪方向与证据不一致：证据为轻微偏多"
    ]


def test_market_preview_hides_internal_degradation_language():
    evidence = {
        "type": "market_brief",
        "market_state": {"label": "承压"},
        "indices": [
            {
                "name": "上证综指",
                "status": "available",
                "metrics": {"return_1d_pct": -1.23},
            }
        ],
        "hot_sectors": {
            "sectors": [{"name": "电力行业", "pct_change": 2.34}]
        },
        "warnings": ["主数据源请求失败，已切换备用源"],
    }

    answer = AgentService._render_preview(evidence)

    assert "preview" not in answer
    assert "数据正在更新" not in answer
    assert "数据源" not in answer
    assert "不构成下一交易日方向预测" in answer


def test_li_zong_partial_preview_does_not_claim_full_market_has_no_candidates():
    evidence = {
        "type": "stock_screen",
        "status": "partial",
        "profile": {"key": "li_zong", "label": "李总策略"},
        "selection_mode": "candidate_pool",
        "items": [],
        "data_meta": {
            "latest_completed_trade_date": "2026-07-22",
            "universe_count": 5530,
            "evaluated_symbols": 4400,
            "remaining_symbols": 1130,
            "coverage_ratio": 4400 / 5530,
            "full_market_coverage": False,
            "deep_check_eligible_count": 1200,
            "deep_processed_symbols": 70,
            "deep_remaining_symbols": 1130,
            "deep_processing_ratio": 70 / 1200,
            "history_insufficient_count": 180,
            "history_unknown_count": 20,
            "deep_check_complete": False,
            "actionable_candidate_count": 0,
        },
        "boundary": "只生成研究候选和人工复核触发，不构成买卖建议。",
    }

    answer = AgentService._render_preview(evidence)

    assert "全市场名单为 5530 只" in answer
    assert "4400/5530 只已形成市值预筛或规则状态" in answer
    assert "不是深度规则完成率" in answer
    assert "可深度核验 1200 只" in answer
    assert "已深度处理 70/1200 只" in answer
    assert "上市后量价历史不足" in answer
    assert "财务历史已经完整" in answer
    assert "当前已深度处理范围内尚无" in answer
    assert "不能推断尚待深度处理" in answer
    assert "这个0只只代表当前已深度处理范围" in answer
    assert "不构成买卖建议" in answer
    assert "全市场深度规则计算已经完成" not in answer


def test_li_zong_guard_rejects_invented_review_cycle_and_rule_bottleneck():
    evidence = {
        "type": "stock_screen",
        "status": "partial",
        "profile": {"key": "li_zong", "label": "李总策略"},
        "selection_mode": "candidate_pool",
        "items": [],
        "data_meta": {
            "latest_completed_trade_date": "2026-07-22",
            "universe_count": 5530,
            "evaluated_symbols": 4464,
            "remaining_symbols": 1066,
            "coverage_ratio": 4464 / 5530,
            "full_market_coverage": False,
            "deep_check_eligible_count": 1200,
            "deep_processed_symbols": 134,
            "deep_remaining_symbols": 1066,
            "deep_processing_ratio": 134 / 1200,
            "history_insufficient_count": 180,
            "history_unknown_count": 20,
            "deep_check_complete": False,
            "actionable_candidate_count": 0,
        },
    }
    answer = (
        "截至2026-07-22，当前已评估4464/5530只，仍有1066只待处理。"
        "当前已评估范围内没有候选，未处理股票不能推断为通过或不通过。"
        "该策略只生成研究候选和人工复核触发，不构成推荐、评级或交易建议。\n"
        "尤其连续五年ROE与近十日涨停同时满足的股票极少。\n"
        "下一步按T+3周期复核候选池。"
    )
    answer = AgentService._normalize_li_zong_scope_answer(answer, evidence)

    guard = AgentService._validate_model_output(answer, evidence)

    assert guard["passed"] is False
    assert agent_module._LI_ZONG_RULE_BOTTLENECK_LABEL in guard[
        "unsupported_market_inferences"
    ]
    assert agent_module._STOCK_OBSERVATION_WINDOW_LABEL in guard[
        "unsupported_market_inferences"
    ]
    repaired = AgentService._repair_guard_failure(answer, evidence, guard)
    assert repaired is not None
    repaired_answer, repaired_guard = repaired
    assert repaired_guard["passed"] is True
    assert "当前已评估范围内没有候选" in repaired_answer
    assert "极少" not in repaired_answer
    assert "T+3" not in repaired_answer


def test_li_zong_scope_normalization_replaces_legacy_coverage_with_deep_progress():
    evidence = {
        "type": "stock_screen",
        "status": "partial",
        "profile": {"key": "li_zong", "label": "李总策略"},
        "selection_mode": "candidate_pool",
        "items": [],
        "data_meta": {
            "latest_completed_trade_date": "2026-07-22",
            "universe_count": 5530,
            "evaluated_symbols": 5090,
            "remaining_symbols": 440,
            "coverage_ratio": 5090 / 5530,
            "full_market_coverage": False,
            "deep_check_eligible_count": 1016,
            "deep_processed_symbols": 576,
            "deep_remaining_symbols": 440,
            "deep_processing_ratio": 576 / 1016,
            "history_insufficient_count": 200,
            "history_unknown_count": 154,
            "deep_check_complete": False,
            "actionable_candidate_count": 0,
        },
    }
    legacy = (
        "李总策略数据交易日为 2026-07-22；当前已评估 5090/5530 只"
        "（92.0%），仍有 440 只待处理。\n\n"
        "当前已评估范围内尚无股票进入候选池或触发池。"
    )

    normalized = AgentService._normalize_li_zong_scope_answer(legacy, evidence)

    assert "全市场名单为 5530 只" in normalized
    assert "已深度处理 576/1016 只" in normalized
    assert "上市后量价历史不足" in normalized
    assert "154 只股票不能仅凭上市日期确认五年ROE是否可得" in normalized
    assert "当前已评估 5090/5530" not in normalized
    assert "不是深度规则完成率" in normalized
    assert "这个0只只代表当前已深度处理范围" in normalized


def test_prompt_evidence_and_output_guard_hide_provider_operations():
    evidence = {
        "type": "market_brief",
        "market_state": {"label": "承压", "coverage_ratio": 1.0},
        "source": "东方财富",
        "source_url": "https://example.invalid",
        "warnings": ["主源不可用，已降级到新浪口径"],
        "hot_sectors": {
            "degraded_from": "东方财富",
            "sectors": [{"name": "电力行业", "pct_change": 2.34}],
        },
    }

    public_evidence = AgentService._evidence_for_prompt(evidence)
    guarded = AgentService._validate_model_output(
        "A股板块数据已从东方财富降级到新浪口径。", evidence
    )

    assert public_evidence["market_state"]["label"] == "承压"
    assert public_evidence["hot_sectors"]["sectors"][0]["pct_change"] == 2.34
    assert "source" not in public_evidence
    assert "source_url" not in public_evidence
    assert "warnings" not in public_evidence
    assert "degraded_from" not in public_evidence["hot_sectors"]
    assert guarded["passed"] is False
    assert guarded["private_operational_patterns"]


def test_failed_model_guard_falls_back_to_deterministic_preview(
    tmp_path: Path, settings, monkeypatch
):
    guarded_settings = replace(
        settings,
        database_path=tmp_path / "guard.db",
        workspace_root=tmp_path / "workspaces-guard",
        hermes_enabled=True,
    )
    database = Database(guarded_settings.database_path, guarded_settings.workspace_root)
    database.initialize()
    user = database.create_user("Guarded User")
    service = AgentService(database, guarded_settings)
    monkeypatch.setattr(
        service,
        "_execute_hermes",
        lambda **kwargs: ("目标价9999元，未来上涨概率80%。", {"model": "fake"}),
    )
    evidence = {
        "type": "memory_candidate",
        "memory": {"content": "我更关注最大回撤"},
    }

    run = service.run(
        user=user,
        intent="memory_candidate",
        message="记住：我更关注最大回撤",
        evidence=evidence,
        model_tier="economy",
        execute_agent=True,
    )

    assert run["status"] == "guarded"
    assert "目标价9999" not in run["answer"]
    assert "尚未进入长期记忆" in run["answer"]
    assert "确定性证据守卫" in run["error"]
    guard_path = (
        Path(run["workspace_path"]) / "runs" / run["id"] / "output_guard.json"
    )
    assert guard_path.is_file()
    assert (
        Path(run["workspace_path"]) / "runs" / run["id"] / "answer.rejected.md"
    ).is_file()


def test_vision_chat_output_keeps_only_final_answer():
    raw = (
        "\x1b[32m推理过程：这是内部内容\x1b[0m\r\n"
        "session_id: 20260721_041018_example\r\n"
        "图片中的线条整体向右上方延伸。\r\n"
    )

    answer = AgentService._extract_chat_answer(raw)

    assert answer == "图片中的线条整体向右上方延伸。"
    assert "内部内容" not in answer
    assert "session_id" not in answer


def test_vision_chat_output_prefers_last_explicit_final_block():
    raw = (
        "┌─ Reasoning ─┐\n"
        "The prompt requests <<<QINGSHU_FINAL>>> visible text "
        "<<<QINGSHU_END>>> after private reasoning.\n"
        "<<<QINGSHU_FINAL>>>\n"
        "图片中的折线整体向右上方延伸，期间伴随回落。\n"
        "<<<QINGSHU_END>>>\n"
    )

    answer = AgentService._extract_chat_answer(raw)

    assert answer == "图片中的折线整体向右上方延伸，期间伴随回落。"
    assert "Reasoning" not in answer


def test_vision_prompt_requires_a_machine_readable_final_block():
    prompt = AgentService._with_vision_output_protocol("原始任务")

    assert "原始任务" in prompt
    assert "<<<QINGSHU_FINAL>>>" in prompt
    assert "<<<QINGSHU_END>>>" in prompt
    assert "思考过程" in prompt


def test_economy_stock_prompt_compacts_large_event_and_fundamental_payloads():
    evidence = {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "metrics": {"return_1d_pct": -6.31},
        "current_quote": {
            "price": 34.88,
            "pct_change": 3.41,
            "market_timestamp": "2026-07-21T16:14:42+08:00",
        },
        "stock_market_context": {
            "company_industry": "通信设备",
            "exact_industry_match_available": False,
            "indices": [{"name": "上证综指", "metrics": {"return_1d_pct": 1.79}}],
            "boundary": "精确行业口径待补证。",
        },
        "recent_bars": [{"close": 1}] * 60,
        "a_share_information": {
            "announcements": [
                {"title": f"公告{i}", "published_at": "2026-07-20", "body": "x" * 1000}
                for i in range(8)
            ],
            "news": [{"title": f"新闻{i}", "body": "x" * 1000} for i in range(8)],
            "social_posts": [{"title": "社区", "body": "x" * 1000}],
            "sentiment": {
                "band": "轻微偏多",
                "score": 0.17,
                "sample_size": 21,
                "evidence": {"caveat": "只是弱证据", "positive_examples": ["x"]},
            },
        },
        "fundamentals": {
            "valuation": {"pe_ttm": 36.06},
            "financial_periods": [{"raw": "x" * 3000}],
            "summary": {"latest_report": {"net_profit_yoy_pct": -46.58}},
        },
        "peer_comparison": {
            "group_label": "通信设备固定同行",
            "selection_basis": "固定小样本",
            "coverage": {"available_peers": 3},
            "metrics": {"pe_ttm": {"peer_median": 50.0}},
            "peers": [{"symbol": "600498.SS", "name": "烽火通信"}],
            "operating_comparison": {
                "status": "available",
                "anchor_report_date": "2026-03-31",
                "subject": {
                    "business_profile": {"anchor_report_date": "2025-12-31"}
                },
                "metrics": {
                    "gross_margin_pct": {
                        "subject_value": 28.0,
                        "peer_median": 30.0,
                        "peer_sample_size": 3,
                    }
                },
                "peers": [
                    {
                        "symbol": "600498.SS",
                        "name": "烽火通信",
                        "status": "comparable",
                        "business_profile": {
                            "anchor_report_date": "2025-12-31"
                        },
                    }
                ],
            },
        },
    }

    compact = AgentService._compact_stock_research_evidence(evidence)

    assert "recent_bars" not in compact
    assert compact["current_quote"]["price"] == 34.88
    assert compact["stock_market_context"]["company_industry"] == "通信设备"
    assert "social_posts" not in compact["a_share_information"]
    assert len(compact["a_share_information"]["announcements"]) == 4
    assert compact["a_share_information"]["sentiment"]["band"] == "轻微偏多"
    assert "financial_periods" not in compact["fundamentals"]
    assert compact["fundamentals"]["summary"]["latest_report"][
        "net_profit_yoy_pct"
    ] == -46.58
    assert compact["peer_comparison"]["group_label"] == "通信设备固定同行"
    assert compact["peer_comparison"]["operating_comparison"]["metrics"][
        "gross_margin_pct"
    ]["peer_sample_size"] == 3
    assert compact["peer_comparison"]["operating_comparison"]["peers"][0][
        "business_profile"
    ]["anchor_report_date"] == "2025-12-31"


def test_peer_operating_guard_rejects_rankings_and_false_business_period_claims():
    evidence = {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "peer_comparison": {
            "operating_comparison": {
                "subject": {
                    "financial": {
                        "name": "中兴通讯",
                        "net_profit_yoy_pct": -46.58,
                        "parent_net_profit": 1_310_444_000,
                        "notice_date": "2026-04-25",
                    },
                    "business_profile": {"anchor_report_date": "2025-12-31"},
                },
                "metrics": {
                    "net_profit_yoy_pct": {
                        "subject_value": -46.58,
                        "peer_median": 14.59,
                        "peer_sample_size": 3,
                    }
                },
                "peers": [
                        {
                            "name": "烽火通信",
                            "financial": {
                                "name": "烽火通信",
                                "net_profit_yoy_pct": -30.44,
                                "parent_net_profit": 38_392_482.56,
                                "notice_date": "2026-04-30",
                            },
                        "business_profile": {
                            "anchor_report_date": "2025-12-31"
                        },
                    },
                        {
                            "name": "紫光股份",
                            "financial": {
                                "name": "紫光股份",
                                "net_profit_yoy_pct": 126.06,
                                "parent_net_profit": 787_908_617.19,
                                "notice_date": "2026-04-29",
                            },
                        "business_profile": {
                            "anchor_report_date": "2025-12-31"
                        },
                    },
                        {
                            "name": "锐捷网络",
                            "financial": {
                                "name": "锐捷网络",
                                "net_profit_yoy_pct": 14.59,
                                "parent_net_profit": 122_924_259.41,
                                "notice_date": "2026-04-21",
                            },
                        "business_profile": {
                            "anchor_report_date": "2025-12-31"
                        },
                    },
                ],
            }
        },
    }

    ranking = AgentService._validate_model_output(
        "中兴通讯在样本中最低，因此经营表现更差。", evidence
    )
    assert ranking["passed"] is False
    assert "固定同行经营比较不得输出公司排名或优劣评级" in ranking[
        "unsupported_market_inferences"
    ]

    wrong_period = AgentService._validate_model_output(
        "四家公司主营构成不是统一报告期，只能分别观察。", evidence
    )
    assert wrong_period["passed"] is False
    assert "主营构成报告期必须与证据逐家公司一致" in wrong_period[
        "unsupported_market_inferences"
    ]

    unsupported_cause = AgentService._validate_model_output(
        "紫光股份的低毛利率主要受IT分销业务拖累。", evidence
    )
    assert unsupported_cause["passed"] is False
    assert "同行业务结构差异不能自动改写为经营指标差异的原因" in unsupported_cause[
        "unsupported_market_inferences"
    ]

    wrong_ratio_logic = AgentService._validate_model_output(
        "中兴和烽火负利润增速会放大经营现金流/净利润的比值负数。",
        evidence,
    )
    assert wrong_ratio_logic["passed"] is False
    assert "净利润同比方向不能解释经营现金流比值" in wrong_ratio_logic[
        "unsupported_market_inferences"
    ]

    wrong_money_unit = AgentService._validate_model_output(
        "烽火通信本期净利润0.038亿元。", evidence
    )
    assert wrong_money_unit["passed"] is False
    assert "同行净利润亿元换算必须与结构化财务一致" in wrong_money_unit[
        "unsupported_market_inferences"
    ]
    repaired_money = AgentService._repair_guard_failure(
        "烽火通信本期净利润0.038亿元。", evidence, wrong_money_unit
    )
    assert repaired_money is not None
    assert "0.38亿元" in repaired_money[0]
    assert repaired_money[1]["passed"] is True

    multi_company_line = (
        "中兴-19.79亿元（净利润13.10亿元）、"
        "紫光-30.93亿元（净利润7.88亿元）、"
        "锐捷-14.68亿元（净利润1.23亿元）、"
        "烽火-7.88亿元（净利润0.038亿元）。"
    )
    replacements = AgentService._peer_net_profit_unit_replacements(
        multi_company_line, evidence
    )
    repaired_line = multi_company_line
    for start, end, replacement in reversed(replacements):
        repaired_line = repaired_line[:start] + replacement + repaired_line[end:]
    assert "紫光-30.93亿元" in repaired_line
    assert "锐捷-14.68亿元" in repaired_line
    assert "烽火-7.88亿元（净利润0.38亿元）" in repaired_line

    wrong_notice_date = AgentService._validate_model_output(
        "来源：财务数据均为2026一季报（2026-04-25公告）。", evidence
    )
    assert wrong_notice_date["passed"] is False
    assert "同行公告日期不能用单一日期概括" in wrong_notice_date[
        "unsupported_market_inferences"
    ]

    composition_math = AgentService._validate_model_output(
        "紫光股份应收账款加销售方和合并抵消后占比超过100%。", evidence
    )
    assert composition_math["passed"] is False
    assert "主营构成不得自行加总或混入非分部字段" in composition_math[
        "unsupported_market_inferences"
    ]

    wrong_margin_source = AgentService._validate_model_output(
        "中兴通讯分部毛利率在三表中未披露。", evidence
    )
    assert wrong_margin_source["passed"] is False
    assert "主营构成毛利率必须使用年报或中报口径" in wrong_margin_source[
        "unsupported_market_inferences"
    ]

    answer = (
        "### 净利润同比\n\n"
        "中兴通讯-46.58%，同行中位数14.59%。紫光股份+126.06%，"
        "锐捷网络+14.59%，烽火通信-30.44%。中兴降幅最大。"
        "以上只说明同一报告期的数值差异，不能改写成公司质量或投资评级。"
    )
    answer_guard = AgentService._validate_model_output(answer, evidence)
    repaired = AgentService._repair_guard_failure(answer, evidence, answer_guard)
    assert repaired is not None
    repaired_answer, repaired_guard = repaired
    assert repaired_guard["passed"] is True
    assert "中兴通讯-46.58%" in repaired_answer
    assert "紫光股份+126.06%" in repaired_answer
    assert "降幅最大" not in repaired_answer


def test_peer_operating_guard_hides_internal_method_id():
    guard = AgentService._validate_model_output(
        "来源方法是 fixed_peer_operating_comparison_v1。",
        {"type": "stock_research", "symbol": "000063.SZ"},
    )

    assert guard["passed"] is False
    assert guard["private_operational_patterns"]


def test_market_prompt_keeps_only_the_requested_market_and_relevant_material():
    evidence = {
        "type": "market_brief",
        "generated_at": "2026-07-21T04:50:00+00:00",
        "user_question": "美股为什么跌",
        "question_focus": {"key": "market_cause", "label": "涨跌原因"},
        "market_state": {"label": "分化"},
        "indices": [
            {
                "symbol": "000001.SS",
                "name": "上证综指",
                "region": "中国",
                "group": "china",
                "metrics": {"return_1d_pct": 0.62},
                "source": "private provider name",
            },
            {
                "symbol": "^GSPC",
                "name": "标普500",
                "status": "available",
                "region": "美国",
                "group": "us",
                "market_timestamp": "2026-07-21T13:30:00+00:00",
                "coverage": {
                    "interval": "1d",
                    "points": 62,
                    "first_timestamp": "2026-04-21T13:30:00+00:00",
                    "last_timestamp": "2026-07-21T13:30:00+00:00",
                },
                "metrics": {
                    "return_1d_pct": -0.19,
                    "return_5d_pct": -0.7,
                    "rsi_14": 43.0,
                    "bollinger_upper_20": 7000.0,
                },
            },
        ],
        "hot_sectors": {"sectors": [{"name": "镍", "pct_change": 6.13}]},
        "market_drivers": {
            "market_key": "us",
            "market_label": "美股",
            "question_focus": "market_cause",
            "items": [
                {"title": f"资讯{i}", "published_at": "2026-07-21"}
                for i in range(10)
            ],
        },
        "knowledge_context": {
            "query": "美股为什么跌",
            "items": [
                {"title": "市场涨跌原因的证据规则", "scope": "common", "excerpt": "规则"},
                {"title": "用户的美股笔记", "scope": "user", "excerpt": "笔记"},
                {"title": "多余资料", "scope": "common", "excerpt": "多余"},
                {"title": "第四份资料", "scope": "common", "excerpt": "多余"},
            ],
        },
    }

    public = AgentService._evidence_for_prompt(evidence)
    compact = AgentService._compact_market_brief_evidence(public)

    assert [item["symbol"] for item in compact["indices"]] == ["^GSPC"]
    assert "hot_sectors" not in compact
    assert len(compact["market_drivers"]["items"]) == 6
    assert len(compact["knowledge_context"]["items"]) == 3
    assert "source" not in compact["indices"][0]
    assert compact["indices"][0]["metrics"] == {
        "return_1d_pct": -0.19,
        "return_5d_pct": -0.7,
    }
    assert compact["indices"][0]["market_date"] == "2026-07-21"
    assert compact["indices"][0]["coverage"]["last_date"] == "2026-07-21"
    assert "market_timestamp" not in compact["indices"][0]


def test_guard_rejects_daily_bar_anchor_as_a_share_close_time():
    evidence = {
        "type": "market_brief",
        "indices": [
            {
                "market_timestamp": "2026-07-21T01:30:00+00:00",
                "coverage": {"interval": "1d"},
            }
        ],
    }

    guard = AgentService._validate_model_output(
        "指数数据截至北京时间09:30收盘。",
        evidence,
    )

    assert guard["passed"] is False
    assert guard["unsupported_market_inferences"] == [
        "A股日线的09:30日期锚点不能写成收盘或数据截止时间"
    ]


def test_guard_repair_removes_empty_section_heading():
    lines = [
        "**风险提醒（根据用户偏好）**",
        "",
        "**数据时间**",
        "日线日期为2026-07-21。",
    ]

    cleaned = AgentService._drop_empty_answer_sections(lines)

    assert "**风险提醒（根据用户偏好）**" not in cleaned
    assert "**数据时间**" in cleaned


def test_repaired_numbered_sections_restart_from_one():
    repaired = AgentService._renumber_repaired_sections(
        "**二、板块结构**\n半导体领涨。\n\n**三、反方证据**\n中期条件未确认。"
    )

    assert repaired.startswith("**一、板块结构**")
    assert "**二、反方证据**" in repaired


def test_guard_repair_renumbers_lists_after_dropping_unsupported_lines():
    repaired = AgentService._repair_guard_failure(
        "## 核验清单\n"
        "1. 不受支持的数字是99。\n"
        "2. 保留10，并说明这是证据包已经确认的事实，不能据此外推未来方向。\n"
        "3. 继续保留10，同时明确下一步仍需要取得新的原始资料进行核验，并保留数据时间与口径边界。",
        {"confirmed_value": 10},
        {
            "unsupported_numbers": ["99"],
            "unsupported_market_inferences": [],
            "private_operational_patterns": [],
            "prohibited_patterns": [],
            "semantic_conflicts": [],
        },
    )

    assert repaired is not None
    repaired_answer, repaired_guard = repaired
    assert "1. 保留10" in repaired_answer
    assert "2. 继续保留10" in repaired_answer
    assert "3. 继续保留10" not in repaired_answer
    assert repaired_guard["passed"] is True


def test_market_sector_prompt_keeps_breadth_evidence_but_drops_unrelated_metrics():
    evidence = {
        "type": "market_brief",
        "user_question": "今天哪些板块领涨，是普涨吗",
        "question_focus": {"key": "sector_rotation", "label": "板块轮动"},
        "market_state": {
            "label": "分化",
            "advance_ratio": 0.57,
            "breadth_scope": "representative_indices",
            "whole_market_breadth_available": False,
        },
        "indices": [
            {
                "symbol": "000001.SS",
                "name": "上证综指",
                "region": "中国",
                "group": "china",
                "metrics": {
                    "return_1d_pct": 0.73,
                    "return_5d_pct": -3.61,
                    "return_20d_pct": -6.88,
                    "volume_ratio_5_20": 3.99,
                    "trend_state": "中期偏弱",
                    "rsi_14": 28.64,
                    "macd_12_26": -66.04,
                },
            }
        ],
        "hot_sectors": {
            "market_timestamp": "2026-07-21T06:57:00+00:00",
            "sectors": [
                {
                    "code": f"BK{i}",
                    "name": f"板块{i}",
                    "pct_change": 10 - i,
                    "main_net_inflow": 1000 + i,
                    "advancers": 20,
                    "decliners": 1,
                    "unchanged": 0,
                    "latest": 9999,
                }
                for i in range(10)
            ]
        },
        "market_breadth": {
            "status": "available",
            "scope": "all_a_shares_including_beijing",
            "fetched_at": "2026-07-21T07:00:00+00:00",
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
                "state": "上涨家数占优",
                "classification_method": "固定阈值",
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
                "history_comparison": {"status": "building_history"},
                "interpretation": "成交额不是资金净流入。",
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
                "method": "固定分档",
            },
        },
        "market_drivers": {
            "market_key": "china",
            "market_label": "A股",
            "question_focus": "sector_rotation",
            "items": [{"title": f"资讯{i}"} for i in range(10)],
        },
    }

    compact = AgentService._compact_market_brief_evidence(evidence)

    assert len(compact["hot_sectors"]["sectors"]) == 6
    assert "latest" not in compact["hot_sectors"]["sectors"][0]
    assert "advancers" in compact["hot_sectors"]["sectors"][0]
    assert compact["hot_sectors"]["market_local_time"] == "2026-07-21 14:57"
    assert "market_timestamp" not in compact["hot_sectors"]
    assert "rsi_14" not in compact["indices"][0]["metrics"]
    assert "macd_12_26" not in compact["indices"][0]["metrics"]
    assert len(compact["market_drivers"]["items"]) == 4
    assert compact["market_state"]["advance_ratio"] == 1.0
    assert compact["market_state"]["breadth_scope"] == "china_representative_indices"
    assert compact["market_breadth"]["breadth"]["advancers"] == 3107
    assert compact["market_breadth"]["turnover"]["total_amount_100m_cny"] == (
        12_340.0
    )
    assert compact["market_breadth"]["distribution"]["median_pct_change"] == (
        0.72
    )
    assert compact["market_breadth"]["snapshot_local_time"] == "2026-07-21 15:00"


def test_market_volume_prompt_keeps_turnover_date_and_tick_time():
    evidence = {
        "type": "market_brief",
        "market_key": "china",
        "user_question": "A股成交额是多少，请给出证据时间",
        "question_focus": {"key": "volume_flows", "label": "量能与资金线索"},
        "indices": [],
        "market_breadth": {
            "status": "available",
            "scope": "all_a_shares_including_beijing",
            "market_date": "2026-07-21",
            "fetched_at": "2026-07-21T19:31:10+00:00",
            "coverage": {
                "expected": 5528,
                "returned": 5528,
                "valid_change": 5528,
                "coverage_ratio": 1.0,
                "latest_tick_time": "15:36:00",
            },
            "breadth": {"total": 5528, "state": "上涨家数占优"},
            "turnover": {
                "status": "available",
                "currency": "CNY",
                "total_amount_cny": 2_973_449_426_676,
                "total_amount_100m_cny": 29_734.49,
                "history_comparison": {"status": "building_history"},
                "interpretation": "成交额不是资金净流入。",
            },
            "distribution": {"status": "available"},
        },
    }

    compact = AgentService._compact_market_brief_evidence(evidence)
    preview = AgentService._render_preview(evidence)

    assert compact["market_breadth"]["market_date"] == "2026-07-21"
    assert compact["market_breadth"]["coverage"]["latest_tick_time"] == "15:36:00"
    assert compact["market_breadth"]["turnover"]["total_amount_100m_cny"] == 29_734.49
    assert "市场日期 2026-07-21" in preview
    assert "快照内最新成交时点 15:36:00" in preview
    assert "不是资金净流入" in preview


def test_market_prompt_excludes_cross_date_index_and_sector_snapshots():
    evidence = {
        "type": "market_brief",
        "user_question": "今天A股为什么上涨",
        "question_focus": {"key": "market_cause"},
        "analysis_target": {
            "market_date": "2026-07-21",
            "date_basis": "a_share_previous_completed_session",
            "market_key": "china",
        },
        "date_alignment": {
            "status": "partial_alignment",
            "sector_status": "cross_date_excluded",
        },
        "indices": [
            {
                "symbol": "000001.SS",
                "name": "上证综指",
                "group": "china",
                "status": "available",
                "market_date": "2026-07-21",
                "same_date_as_analysis_target": True,
                "metrics": {"return_1d_pct": 1.8},
            },
            {
                "symbol": "399006.SZ",
                "name": "创业板指",
                "group": "china",
                "status": "available",
                "market_date": "2026-07-20",
                "same_date_as_analysis_target": False,
                "metrics": {"return_1d_pct": -8.0},
            },
        ],
        "market_state": {"label": "偏强"},
        "hot_sectors": {
            "market_date": "2026-07-22",
            "same_date_as_analysis_target": False,
            "sectors": [{"name": "盘前占位板块", "pct_change": 9.9}],
        },
        "market_breadth": {
            "status": "available",
            "market_date": "2026-07-21",
            "same_date_as_analysis_target": True,
            "breadth": {"total": 5528, "state": "上涨家数占优"},
        },
        "market_drivers": {"market_key": "china", "items": []},
    }

    compact = AgentService._compact_market_brief_evidence(evidence)

    assert [item["symbol"] for item in compact["indices"]] == ["000001.SS"]
    assert compact["market_state"]["label"] == "偏强"
    assert compact["analysis_target"]["market_date"] == "2026-07-21"
    assert "hot_sectors" not in compact
    assert compact["market_breadth"]["market_date"] == "2026-07-21"


def test_market_answer_removes_internal_routing_preamble():
    cleaned = AgentService._clean_user_facing_model_language(
        "## 来龙去脉\n\n"
        "用户询问两个问题：昨天为什么涨，以及今天关注什么。"
        "根据 `question_focus.key=market_cause` 组织回答。\n\n"
        "### 事件线索\n\n市场先跌后涨。"
    )

    assert "用户询问" not in cleaned
    assert "question_focus" not in cleaned
    assert "market_cause" not in cleaned
    assert "来龙去脉" not in cleaned
    assert cleaned.startswith("### 事件线索")


def test_market_repair_restores_same_date_price_facts_after_bad_line_is_removed():
    evidence = {
        "type": "market_brief",
        "user_question": "A股昨天为什么上涨？",
        "question_focus": {"key": "market_cause"},
        "analysis_target": {"market_date": "2026-07-21"},
        "indices": [
            {
                "name": "上证综指",
                "status": "available",
                "same_date_as_analysis_target": True,
                "metrics": {"return_1d_pct": 1.7935},
            }
        ],
        "market_state": {
            "whole_market_breadth_available": True,
            "whole_market_advancers": 3107,
            "whole_market_decliners": 2300,
            "whole_market_unchanged": 121,
            "whole_market_breadth_state": "上涨家数占优",
        },
    }
    answer = (
        "### 价格事实\n上涨约3070家，指数明显修复。\n\n"
        "### 事件线索\n资讯标题提到盘中V型反转，但标题不能证明唯一因果。\n\n"
        "### 盘前观察\n继续核验消息与价格是否一致，不预测下一交易日方向。"
    )
    guard = AgentService._validate_model_output(answer, evidence)

    repaired = AgentService._repair_guard_failure(answer, evidence, guard)

    assert repaired is not None
    repaired_answer, repaired_guard = repaired
    assert repaired_guard["passed"] is True
    assert "3070" not in repaired_answer
    assert "上证综指在2026-07-21上涨 1.79%" in repaired_answer
    assert "上涨 3107 家、下跌 2300 家、平盘 121 家" in repaired_answer


def test_market_guard_rejects_news_absorption_and_coverage_overclaims():
    evidence = {
        "type": "market_brief",
        "question_focus": {"key": "market_cause"},
        "indices": [
            {
                "name": "上证综指",
                "status": "available",
                "metrics": {"return_1d_pct": 1.79},
            }
        ],
        "market_drivers": {
            "items": [{"title": "多家机构发布A股观点"}]
        },
    }
    absorption = AgentService._validate_model_output(
        "上证综指上涨1.79%。机构唱多消息已被市场消化。",
        evidence,
    )
    missing_events = AgentService._validate_model_output(
        "上证综指上涨1.79%。当前没有新的宏观数据、政策公告或外部事件。",
        evidence,
    )
    future_catalyst = AgentService._validate_model_output(
        "上证综指上涨1.79%。今天能否延续取决于是否出现新增催化剂。",
        evidence,
    )

    assert absorption["passed"] is False
    assert missing_events["passed"] is False
    assert future_catalyst["passed"] is False


def test_market_guard_requires_turnover_snapshot_date_when_user_asks_time(settings):
    database = Database(settings.database_path, settings.workspace_root)
    database.initialize()
    service = AgentService(database, settings)
    evidence = {
        "type": "market_brief",
        "user_question": "A股成交额是多少，请给出证据时间",
        "market_state": {"whole_market_breadth_available": True},
        "market_breadth": {
            "market_date": "2026-07-21",
            "turnover": {
                "status": "available",
                "total_amount_100m_cny": 29_734.49,
            },
        },
        "indices": [],
    }

    missing_date = service._validate_model_output(
        "沪深京A股全市场成交额为29734.49亿元，成交额不等于资金净流入。",
        evidence,
        trusted_context=None,
    )
    safe = service._validate_model_output(
        "2026-07-21沪深京A股全市场成交额为29734.49亿元，成交额不等于资金净流入。",
        evidence,
        trusted_context=None,
    )
    false_missing = service._validate_model_output(
        "全市场成交额为29734.49亿元，但成交额未单独标注市场日期。",
        evidence,
        trusted_context=None,
    )

    assert "全市场成交额时间必须引用市场快照日期" in missing_date[
        "semantic_conflicts"
    ]
    assert "全市场成交额时间必须引用市场快照日期" not in safe[
        "semantic_conflicts"
    ]
    assert "已有全市场快照日期时不能声称成交额日期缺失" in false_missing[
        "unsupported_market_inferences"
    ]


def test_market_guard_accepts_natural_turnover_time_and_negative_boundary(settings):
    database = Database(settings.database_path, settings.workspace_root)
    database.initialize()
    service = AgentService(database, settings)
    evidence = {
        "type": "market_brief",
        "user_question": "A股成交额是多少，请给出证据时间和不能确认的部分",
        "market_state": {"whole_market_breadth_available": True},
        "market_breadth": {
            "market_date": "2026-07-21",
            "turnover": {
                "status": "available",
                "total_amount_100m_cny": 29_734.49,
            },
        },
        "indices": [],
    }
    answer = AgentService._clean_user_facing_model_language(
        "根据 2026 年 7 月 21 日的全市场快照，全市场当日累计成交金额为"
        "29734.49亿元。成交额不能说明资金净流入，也不能证明增量资金入场。"
        "同口径历史比较仍处于 building_history 状态，当前无法判断放量或缩量。"
    )

    guard = service._validate_model_output(answer, evidence, trusted_context=None)

    assert "building_history" not in answer
    assert "同口径历史仍在积累" in answer
    assert guard["passed"] is True


def test_market_trend_prompt_drops_intraday_volume_and_sector_distractions():
    evidence = {
        "type": "market_brief",
        "user_question": "这更像单日反弹还是趋势反转",
        "question_focus": {"key": "trend_reversal"},
        "indices": [
            {
                "symbol": "000001.SS",
                "name": "上证综指",
                "region": "中国",
                "group": "china",
                "coverage": {"interval": "1d"},
                "metrics": {
                    "latest_close": 3864.37,
                    "return_1d_pct": 1.79,
                    "return_5d_pct": -2.59,
                    "return_20d_pct": -5.89,
                    "ma20": 3989.52,
                    "ma60": 4066.93,
                    "volume_ratio_5_20": 3.927,
                    "trend_state": "中期偏弱",
                },
                "latest_bar": {
                    "open": 3812.16,
                    "high": 3864.60,
                    "low": 3743.36,
                    "close": 3864.37,
                    "volume": 487748468,
                },
            }
        ],
        "hot_sectors": {
            "market_timestamp": "2026-07-21T06:57:00+00:00",
            "sectors": [{"name": "半导体设备", "pct_change": 14.76}],
        },
        "market_drivers": {
            "market_key": "china",
            "market_label": "A股",
            "items": [{"title": "市场资讯"}],
        },
    }

    compact = AgentService._compact_market_brief_evidence(evidence)

    assert "latest_bar" not in compact["indices"][0]
    assert "volume_ratio_5_20" not in compact["indices"][0]["metrics"]
    assert "hot_sectors" not in compact
    assert compact["market_drivers"]["items"] == []


def test_market_guard_rejects_missing_available_distribution_detail():
    evidence = {
        "type": "market_brief",
        "user_question": "请结合成交额和个股涨跌幅分布说明",
        "market_state": {"whole_market_breadth_available": True},
        "market_breadth": {
            "turnover": {
                "status": "available",
                "total_amount_100m_cny": 12_340.0,
            },
            "distribution": {
                "status": "available",
                "median_pct_change": 0.72,
                "bins": {"strong_advancers_ge_3": 1200},
            },
        },
    }
    answer = (
        "全市场成交额为12340亿元。\n"
        "个股涨跌幅中位数为0.72%，但现有证据缺少±3%分档分布数据。"
    )

    guard = AgentService._validate_model_output(answer, evidence)

    assert guard["passed"] is False
    assert guard["unsupported_market_inferences"] == [
        "已有全市场个股涨跌幅分布时不能声称该数据缺失"
    ]


def test_market_guard_requires_explicitly_requested_available_turnover():
    evidence = {
        "type": "market_brief",
        "user_question": "请结合成交额和个股涨跌幅分布说明",
        "market_state": {"whole_market_breadth_available": True},
        "market_breadth": {
            "turnover": {
                "status": "available",
                "total_amount_100m_cny": 12_340.0,
            },
            "distribution": {
                "status": "available",
                "median_pct_change": 0.72,
            },
        },
    }
    answer = "个股涨跌幅中位数为0.72%，当前上涨家数占优。"

    guard = AgentService._validate_model_output(answer, evidence)

    assert guard["passed"] is False
    assert guard["semantic_conflicts"] == [
        "用户明确询问成交额时必须引用可用的全市场成交额"
    ]


def test_market_guard_rejects_unevidenced_contribution_and_repair_space():
    evidence = {
        "type": "market_brief",
        "market_state": {},
        "indices": [
            {
                "name": "深证成指",
                "metrics": {"return_1d_pct": 4.81, "ma20_distance_pct": -6.1},
            },
            {
                "name": "沪深300",
                "metrics": {"return_1d_pct": 4.64, "ma20_distance_pct": -1.8},
            },
        ],
    }
    answer = (
        "深证成指上涨4.81%、沪深300上涨4.64%，深市和权重股贡献突出。\n"
        "两者仍在MA20下方，短期修复空间较大。"
    )

    guard = AgentService._validate_model_output(answer, evidence)

    assert guard["passed"] is False
    assert set(guard["unsupported_market_inferences"]) == {
        "代表性指数涨幅不能直接证明市场或风格贡献",
        "均线位置不能直接外推反弹或修复空间",
    }


def test_numeric_guard_accepts_parenthesized_distribution_ratios():
    evidence = {
        "type": "market_brief",
        "market_state": {"whole_market_breadth_available": True},
        "market_breadth": {
            "distribution": {
                "status": "available",
                "bins": {
                    "strong_decliners_le_neg3": 444,
                    "mild_decliners_lt_0_gt_neg3": 1856,
                },
                "bin_ratios": {
                    "strong_decliners_le_neg3": 0.0803,
                    "mild_decliners_lt_0_gt_neg3": 0.3357,
                },
                "method": "固定±3%分档只用于描述当日分布",
            }
        },
    }
    answer = (
        "尾部下跌个股444家（8.0%），"
        "温和下跌个股1856家（33.6%）。"
    )

    guard = AgentService._validate_model_output(answer, evidence)

    assert guard["passed"] is True
    assert guard["unsupported_numbers"] == []


def test_market_guard_accepts_explicit_turnover_non_causality_boundary():
    evidence = {
        "type": "market_brief",
        "market_state": {},
        "market_breadth": {
            "turnover": {
                "status": "available",
                "total_amount_100m_cny": 29_734.49,
            }
        },
    }
    answer = (
        "全市场成交额为29734.49亿元；"
        "成交额是当日累计金额，不证明资金净流入或机构买入意图。"
    )

    guard = AgentService._validate_model_output(answer, evidence)

    assert guard["passed"] is True
    assert guard["unsupported_market_inferences"] == []


def test_market_guard_rejects_turnover_double_count_explanation():
    evidence = {
        "type": "market_brief",
        "market_state": {},
        "market_breadth": {
            "turnover": {
                "status": "available",
                "total_amount_100m_cny": 29_734.49,
            }
        },
    }
    answer = (
        "全市场成交额为29734.49亿元。"
        "同一笔交易同时计入买卖双方，所以成交额会翻倍。"
    )

    guard = AgentService._validate_model_output(answer, evidence)

    assert guard["passed"] is False
    assert guard["unsupported_market_inferences"] == [
        "成交额按每笔成交金额计一次，不能解释为买卖双方双重计数"
    ]


def test_market_guard_rejects_volume_as_market_participation_evidence():
    evidence = {"type": "market_brief", "market_state": {}}

    unsupported = AgentService._validate_model_output(
        "成交量未放大，说明上涨参与面较窄。",
        evidence,
    )
    reverse_cause = AgentService._validate_model_output(
        "上涨覆盖面有限，主要是由于量比偏低。",
        evidence,
    )
    cautious = AgentService._validate_model_output(
        "成交量未放大，但这不能证明上涨参与面较窄；市场广度需要看涨跌家数。",
        evidence,
    )

    label = "成交量或量比不能直接证明上涨参与面或市场覆盖范围"
    assert unsupported["passed"] is False
    assert unsupported["unsupported_market_inferences"] == [label]
    assert reverse_cause["passed"] is False
    assert reverse_cause["unsupported_market_inferences"] == [label]
    assert cautious["passed"] is True


def test_market_guard_repairs_volume_participation_inference():
    evidence = {"type": "market_brief", "market_state": {}}
    answer = (
        "结论：美股盘中主要指数正在上涨。\n"
        "- 纳斯达克指数涨幅居前。\n"
        "- 成交量未放大，说明上涨参与面较窄。\n"
        "- 当前只能确认指数价格表现，市场广度仍需涨跌家数验证。\n"
        "- 现有证据适合描述已经发生的价格变化，不足以判断全市场股票的同步程度。\n"
        "- 后续应结合上涨、下跌和平盘家数，再判断上涨是否具有广泛覆盖。"
    )

    guard = AgentService._validate_model_output(answer, evidence)
    repaired = AgentService._repair_guard_failure(answer, evidence, guard)

    assert repaired is not None
    repaired_answer, repaired_guard = repaired
    assert "上涨参与面较窄" not in repaired_answer
    assert "市场广度仍需涨跌家数验证" in repaired_answer
    assert repaired_guard["passed"] is True


def test_user_facing_cleanup_normalizes_decline_magnitude_bins():
    answer = "跌幅0~-3%的有1856只，跌幅≥-3%的有444只。"

    cleaned = AgentService._clean_user_facing_model_language(answer)

    assert cleaned == "跌幅0—3%的有1856只，跌幅≥3%的有444只。"


def test_market_guard_repairs_unsupported_style_flow_and_history_inferences(
    tmp_path: Path, settings, monkeypatch
):
    guarded_settings = replace(
        settings,
        database_path=tmp_path / "market-inference-guard.db",
        workspace_root=tmp_path / "workspaces-market-inference-guard",
        hermes_enabled=True,
    )
    database = Database(guarded_settings.database_path, guarded_settings.workspace_root)
    database.initialize()
    user = database.create_user("Market Inference Repair User")
    service = AgentService(database, guarded_settings)
    answer = (
        "结论：今天更接近半导体主导的结构性行情，全市场广度仍待补证。\n"
        "- 半导体设备与半导体材料位居领涨板块前列。\n"
        "- 深证波动高于上证，说明中盘成长股风险高于大盘权重股。\n"
        "- 成交量明显放大，说明增量资金入场并集中在深市。\n"
        "- 历史回溯中此类急涨后波动往往加剧。\n"
        "- 当前证据不含全市场涨跌家数，不能声称普涨。\n"
        "以上只描述已发生的市场结构，不预测下一交易日方向。"
    )
    monkeypatch.setattr(
        service,
        "_execute_hermes",
        lambda **kwargs: (answer, {"model": "fake"}),
    )
    evidence = {
        "type": "market_brief",
        "question_focus": {"key": "sector_rotation"},
        "market_state": {
            "label": "偏强",
            "whole_market_breadth_available": False,
        },
        "indices": [],
        "hot_sectors": {
            "sectors": [
                {"name": "半导体设备", "pct_change": 12.0},
                {"name": "半导体材料", "pct_change": 9.0},
            ]
        },
    }

    run = service.run(
        user=user,
        intent="market_brief",
        message="今天是普涨还是结构性行情？",
        evidence=evidence,
        model_tier="economy",
        execute_agent=True,
    )

    assert run["status"] == "completed"
    assert "结构性行情" in run["answer"]
    assert "全市场广度仍待补证" in run["answer"]
    assert "中盘成长股风险高于大盘权重股" not in run["answer"]
    assert "增量资金入场" not in run["answer"]
    assert "历史回溯" not in run["answer"]
    assert run["usage"]["output_guard"]["repair"]["method"] == (
        "drop_unsupported_evidence_lines_v1"
    )


def test_market_guard_flags_invented_tolerance_pressure_and_systemic_claims():
    evidence = {"type": "market_brief", "market_state": {}}
    answer = (
        "很多人能承受的回撤区间是10%至15%。\n"
        "指数触及盘中低点，说明抛压尚未释放。\n"
        "风险报道说明系统性风险警示信号已经出现。"
    )

    guard = AgentService._validate_model_output(answer, evidence)

    assert guard["passed"] is False
    assert set(guard["unsupported_market_inferences"]) == {
        "没有用户确认或规则证据时不能发明典型投资者回撤承受区间",
        "盘中低点本身不能证明抛压或卖压尚未释放",
        "单一媒体标题不能证明系统性风险信号",
    }


def test_market_guard_rejects_whole_market_breadth_overclaim_without_breadth_data():
    evidence = {
        "type": "market_brief",
        "market_state": {"whole_market_breadth_available": False},
    }

    cautious = AgentService._validate_model_output(
        "从领涨板块集中度看，更接近结构性行情；全市场广度仍待补证。",
        evidence,
    )
    overclaim = AgentService._validate_model_output(
        "今天是结构性行情，并非全市场普涨。",
        evidence,
    )

    assert cautious["passed"] is True
    assert overclaim["passed"] is False
    assert overclaim["unsupported_market_inferences"] == [
        "缺少全市场涨跌家数时不能确认是否普涨"
    ]


def test_market_guard_rejects_positive_whole_market_breadth_claim():
    evidence = {
        "type": "market_brief",
        "market_state": {"whole_market_breadth_available": False},
    }

    safe = AgentService._validate_model_output(
        "当前不能确认是否普涨；全市场广度仍待补证。",
        evidence,
    )
    overclaim = AgentService._validate_model_output(
        "今天的A股是普涨兼强烈修复的一天。",
        evidence,
    )

    assert safe["passed"] is True
    assert overclaim["passed"] is False
    assert overclaim["unsupported_market_inferences"] == [
        "缺少全市场涨跌家数时不能确认是否普涨"
    ]


def test_market_guard_rejects_majority_stock_claim_without_same_day_breadth():
    evidence = {
        "type": "market_brief",
        "market_state": {"whole_market_breadth_available": False},
    }

    overclaim = AgentService._validate_model_output(
        "今日代表A股全市场的主要指数和大多数个股是下跌的。",
        evidence,
    )
    cautious = AgentService._validate_model_output(
        "资讯标题称大多数个股下跌，但尚未由同日全市场快照核验。",
        evidence,
    )

    assert overclaim["passed"] is False
    assert overclaim["unsupported_market_inferences"] == [
        "缺少同日全市场广度时不能声称多数个股涨跌"
    ]
    assert cautious["passed"] is True


def test_market_guard_repairs_majority_stock_claim_without_same_day_breadth():
    evidence = {
        "type": "market_brief",
        "market_state": {"whole_market_breadth_available": False},
    }
    answer = (
        "今日上证综指微涨，深证成指下跌；这只能确认代表性指数之间存在分化。\n"
        "今日代表A股全市场的主要指数和大多数个股是下跌的。\n"
        "同日全市场涨跌家数仍待核验，不能仅凭指数表现判断全部股票的上涨或下跌参与面；"
        "资讯标题只能作为线索，不能替代同日全市场快照。"
    )

    guard = AgentService._validate_model_output(answer, evidence)
    repaired = AgentService._repair_guard_failure(answer, evidence, guard)

    assert repaired is not None
    repaired_answer, repaired_guard = repaired
    assert "大多数个股是下跌" not in repaired_answer
    assert "同日全市场涨跌家数仍待核验" in repaired_answer
    assert repaired_guard["passed"] is True


def test_market_guard_requires_fixed_breadth_classification_when_data_exists():
    evidence = {
        "type": "market_brief",
        "market_state": {
            "whole_market_breadth_available": True,
            "whole_market_breadth_state": "上涨家数占优",
            "whole_market_advancers": 3107,
            "whole_market_decliners": 2300,
            "whole_market_unchanged": 121,
        },
    }

    safe = AgentService._validate_model_output(
        "上涨3107家、下跌2300家、平盘121家，固定分类为上涨家数占优，"
        "未达到普涨阈值。",
        evidence,
    )
    overclaim = AgentService._validate_model_output(
        "上涨3107家、下跌2300家，因此今天属于普涨。",
        evidence,
    )
    missing_state = AgentService._validate_model_output(
        "上涨3107家、下跌2300家、平盘121家。",
        {
            **evidence,
            "user_question": "请给出涨跌家数和固定分类",
        },
    )
    invented_attribution = AgentService._validate_model_output(
        "上涨3107家、下跌2300家、平盘121家，固定分类为上涨家数占优。"
        "上涨比例与指数涨幅分化，说明少数权重股带动，而且多数股票涨幅温和。",
        evidence,
    )

    assert safe["passed"] is True
    assert overclaim["passed"] is False
    assert overclaim["unsupported_market_inferences"] == [
        "全市场广度结论必须沿用固定分类"
    ]
    assert missing_state["passed"] is False
    assert missing_state["unsupported_market_inferences"] == [
        "用户询问全市场广度时回答必须给出涨跌家数和固定分类"
    ]
    assert invented_attribution["passed"] is False
    assert set(invented_attribution["unsupported_market_inferences"]) == {
        "全市场涨跌家数不能直接证明少数权重或集中板块拉动",
        "缺少个股涨幅分布时不能声称多数股票涨幅温和",
    }


def test_market_guard_accepts_evidenced_breadth_ratios_and_classification_rule():
    evidence = {
        "type": "market_brief",
        "market_state": {
            "whole_market_breadth_available": True,
            "whole_market_breadth_state": "上涨家数占优",
            "whole_market_advancers": 3107,
            "whole_market_decliners": 2300,
            "whole_market_unchanged": 121,
        },
        "market_breadth": {
            "status": "available",
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
        },
    }
    answer = (
        "上涨3107家（56.2%）、下跌2300家（41.6%）、平盘121家（2.2%）。"
        "固定分类方法要求上涨或下跌比例至少达到65%，且净差至少500；"
        "当前固定分类为上涨家数占优，不能称为普涨。"
    )

    guard = AgentService._validate_model_output(answer, evidence)

    assert guard["passed"] is True

    detailed_rule_answer = (
        "固定分类方法为：普涨/普跌要求上涨或下跌比例至少65%，且净差至少500。"
        "当前上涨比例56.2%未达到65%门槛，因此固定分类是上涨家数占优，"
        "不是普涨。"
    )
    detailed_guard = AgentService._validate_model_output(
        detailed_rule_answer, evidence
    )

    assert detailed_guard["passed"] is True

    coordinated_ratio_answer = (
        "固定分类标准为普涨/普跌要求上涨或下跌比例至少65%，且净差至少500家。"
        "当前上涨占比约56.2%、下跌约41.6%，未达到普涨阈值；"
        "因此结论是上涨家数占优，而非全市场普涨。"
    )
    coordinated_guard = AgentService._validate_model_output(
        coordinated_ratio_answer, evidence
    )

    assert coordinated_guard["passed"] is True

    rounded_count_guard = AgentService._validate_model_output(
        "上涨3107家、下跌2300家、平盘121家，净多约800家，"
        "固定分类为上涨家数占优；无法确认是否属于结构性行情。",
        evidence,
    )
    invented_rounded_count = AgentService._validate_model_output(
        "上涨3107家、下跌2300家、平盘121家，净多约900家，"
        "固定分类为上涨家数占优；无法确认是否属于结构性行情。",
        evidence,
    )

    assert rounded_count_guard["passed"] is True
    assert "900" in invented_rounded_count["unsupported_numbers"]


def test_market_guard_rejects_relabeling_fixed_breadth_as_structural_market():
    evidence = {
        "type": "market_brief",
        "user_question": "今天是普涨还是结构性行情？说明不能确认的部分。",
        "market_state": {
            "whole_market_breadth_available": True,
            "whole_market_breadth_state": "上涨家数占优",
            "whole_market_advancers": 3107,
            "whole_market_decliners": 2300,
            "whole_market_unchanged": 121,
        },
    }

    overclaim = AgentService._validate_model_output(
        "今天属于上涨家数占优的结构性行情。上涨3107家、下跌2300家、"
        "平盘121家；不能确认具体由哪些股票贡献。",
        evidence,
    )
    cautious = AgentService._validate_model_output(
        "上涨3107家、下跌2300家、平盘121家，固定分类为上涨家数占优。"
        "当前无法确认是否属于结构性行情。",
        evidence,
    )

    assert overclaim["passed"] is False
    assert (
        "固定广度分类和热门板块不能直接确认结构性行情"
        in overclaim["unsupported_market_inferences"]
    )
    assert cautious["passed"] is True


def test_market_guard_rejects_sector_ranking_as_concentration_proof():
    evidence = {
        "type": "market_brief",
        "market_state": {
            "whole_market_breadth_available": True,
            "whole_market_breadth_state": "上涨家数占优",
        },
        "hot_sectors": {
            "sectors": [
                {"name": "次新股", "pct_change": 8.53},
                {"name": "电子器件", "pct_change": 7.74},
            ]
        },
    }

    guard = AgentService._validate_model_output(
        "从领涨板块看，次新股和电子器件排名靠前，板块集中度较高。",
        evidence,
    )

    assert guard["passed"] is False
    assert "热门板块排序不能证明板块集中度较高" in guard[
        "unsupported_market_inferences"
    ]


def test_market_guard_rejects_return_assigned_to_unavailable_index():
    evidence = {
        "type": "market_brief",
        "market_state": {"whole_market_breadth_available": False},
        "indices": [
            {
                "symbol": "399006.SZ",
                "name": "创业板指",
                "status": "unavailable",
                "metrics": {},
            },
            {
                "symbol": "000300.SS",
                "name": "沪深300",
                "status": "available",
                "metrics": {"return_1d_pct": 4.64},
            },
        ],
    }

    guard = AgentService._validate_model_output(
        "创业板和沪深300涨幅更大，约4.6%—4.8%。", evidence
    )
    cautious = AgentService._validate_model_output(
        "创业板一日涨幅数据缺失；沪深300上涨4.64%。", evidence
    )

    assert guard["passed"] is False
    assert "缺失收益的指数不能引用其他指数的涨跌幅" in guard[
        "unsupported_market_inferences"
    ]
    assert cautious["passed"] is True


def test_market_guard_uses_available_turnover_and_distribution_evidence():
    evidence = {
        "type": "market_brief",
        "market_state": {
            "whole_market_breadth_available": True,
            "whole_market_breadth_state": "上涨家数占优",
        },
        "market_breadth": {
            "turnover": {
                "status": "available",
                "total_amount_100m_cny": 12_340.0,
            },
            "distribution": {
                "status": "available",
                "median_pct_change": 0.72,
            },
        },
    }

    missing = AgentService._validate_model_output(
        "当前缺少全市场成交额，也没有个股涨幅分布。", evidence
    )
    false_flow = AgentService._validate_model_output(
        "全市场成交额12340亿元，说明机构资金净流入。", evidence
    )
    safe = AgentService._validate_model_output(
        "全市场成交额12340亿元，个股涨跌幅中位数0.72%。"
        "成交额不是资金净流入。",
        evidence,
    )

    assert missing["passed"] is False
    assert set(missing["unsupported_market_inferences"]) == {
        "已有全市场个股涨跌幅分布时不能声称该数据缺失",
        "已有全市场成交额时不能声称该数据缺失",
    }
    assert false_flow["passed"] is False
    assert "成交量或量比不能直接证明增量资金入场或资金流向" in false_flow[
        "unsupported_market_inferences"
    ]
    assert safe["passed"] is True


def test_market_guard_rejects_invented_windows_thresholds_and_scenario_odds():
    evidence = {
        "type": "market_brief",
        "market_state": {"whole_market_breadth_available": False},
        "indices": [
            {
                "name": "上证综指",
                "metrics": {
                    "ma20": 3989.5233,
                    "volume_ratio_5_20": 3.927,
                    "max_drawdown_60d_pct": -11.2766,
                },
            }
        ],
    }
    answer = (
        "未来2-3个交易日能否回补MA20是关键分水岭。\n"
        "后续量能至少维持1.5-2倍才算有效。\n"
        "如果回撤扩大至-20%以上，进入熊市的概率上升。\n"
        "历史上这种组合经常再次探底。"
    )

    guard = AgentService._validate_model_output(answer, evidence)

    assert guard["passed"] is False
    assert set(guard["unsupported_market_inferences"]) == {
        "证据包没有历史回溯时不能声称历史上通常如此",
        "缺少校准证据时不能声称后续情景的概率或高频规律",
        "证据包没有给出观察窗口时不能发明未来交易日数量",
        "证据包没有给出阈值时不能发明量能或回撤验证门槛",
    }


def test_market_guard_rejects_unproven_first_repair_and_low_price_zone():
    evidence = {
        "type": "market_brief",
        "indices": [
            {
                "name": "上证综指",
                "metrics": {
                    "return_1d_pct": 1.79,
                    "return_5d_pct": -2.59,
                    "return_20d_pct": -5.89,
                },
            }
        ],
    }
    answer = (
        "这是近5日内首次出现的明显修复。\n"
        "20日累计下跌5.89%，说明指数处于低价区间。"
    )

    guard = AgentService._validate_model_output(answer, evidence)

    assert guard["passed"] is False
    assert set(guard["unsupported_market_inferences"]) == {
        "没有历史序列时不能声称这是第一次反弹或需要二次验证",
        "区间收益不能直接证明指数处于低价或低位区间",
    }


def test_market_guard_rejects_approximate_index_count_style_proxy_and_vague_window():
    evidence = {
        "type": "market_brief",
        "indices": [
            {"name": "上证综指", "metrics": {"return_1d_pct": 1.79}},
            {"name": "深证成指", "metrics": {"return_1d_pct": 4.81}},
        ],
    }
    answer = (
        "从近百只代表性指数看，市场偏强。\n"
        "深证涨幅高于上证，说明中小市值品种弹性更强。\n"
        "至少需要后续几个交易日确认。"
    )

    guard = AgentService._validate_model_output(answer, evidence)

    assert guard["passed"] is False
    assert set(guard["unsupported_market_inferences"]) == {
        "代表性指数数量与当前问题证据不一致",
        "不能仅用上证与深证的差异替代大小盘风格指数",
        "证据包没有给出观察窗口时不能发明未来交易日数量",
    }


def test_market_guard_rejects_continuous_weekly_decline_from_interval_return():
    evidence = {
        "type": "market_brief",
        "indices": [
            {
                "name": "上证综指",
                "metrics": {"return_20d_pct": -5.89},
            }
        ],
    }

    guard = AgentService._validate_model_output(
        "市场从前几周的持续回落中明显反弹，此前连续数周走弱。",
        evidence,
    )

    assert guard["passed"] is False
    assert guard["unsupported_market_inferences"] == [
        "区间收益不能声称市场连续数周持续回落"
    ]


def test_market_guard_rejects_generic_prior_continuous_decline_claim():
    evidence = {
        "type": "market_brief",
        "indices": [
            {
                "name": "上证综指",
                "metrics": {"return_5d_pct": -2.59},
            }
        ],
    }

    guard = AgentService._validate_model_output(
        "这是此前一段连续下跌后的单日修复。",
        evidence,
    )

    assert guard["passed"] is False
    assert guard["unsupported_market_inferences"] == [
        "区间收益不能声称此前一段行情连续下跌"
    ]


def test_market_guard_rejects_daily_windows_as_weekly_monthly_and_style_proxy():
    evidence = {
        "type": "market_brief",
        "indices": [
            {"name": "上证综指", "metrics": {"return_5d_pct": -2.59}},
            {"name": "深证成指", "metrics": {"return_20d_pct": -10.03}},
        ],
    }
    answer = (
        "上证和深证的5日、20日累计收益仍为负，周线和月线尚未转正。\n"
        "深证涨幅高于上证，成长类板块是主要拉动力。"
    )

    guard = AgentService._validate_model_output(answer, evidence)

    assert guard["passed"] is False
    assert set(guard["unsupported_market_inferences"]) == {
        "5日和20日累计收益不能直接改写成周线或月线",
        "不能仅用上证与深证的差异替代大小盘风格指数",
    }


def test_market_guard_rejects_single_index_advance_ratio_attribution():
    evidence = {
        "type": "market_brief",
        "market_state": {
            "advance_ratio": 1.0,
            "breadth_scope": "china_representative_indices",
        },
        "indices": [
            {"name": "上证综指", "metrics": {"return_1d_pct": 1.79}},
            {"name": "深证成指", "metrics": {"return_1d_pct": 4.81}},
        ],
    }

    guard = AgentService._validate_model_output(
        "上证综指上涨比例1.0，可以确认价格修复。",
        evidence,
    )

    assert guard["passed"] is False
    assert guard["unsupported_market_inferences"] == [
        "代表性指数上涨比例不能归到单一指数名下"
    ]


def test_market_prompt_history_keeps_user_questions_but_drops_prior_answers():
    history = [
        {"role": "user", "content": "A股为什么涨"},
        {"role": "assistant", "content": "上一轮模型回答和其中的数字"},
        {"role": "user", "content": "那主要风险是什么"},
    ]

    compact = AgentService._compact_market_conversation_history(history)

    assert compact == [
        {"role": "user", "content": "A股为什么涨"},
        {"role": "user", "content": "那主要风险是什么"},
    ]


def test_market_guard_rejects_max_drawdown_position_and_loss_overclaims():
    evidence = {
        "type": "market_brief",
        "indices": [
            {"metrics": {"max_drawdown_60d_pct": -11.2766}}
        ],
    }
    answer = (
        "近60日最大回撤为-11.28%，当前处于60日低位区间。\n"
        "这段回撤代表过去两个月的累计损失。"
    )

    guard = AgentService._validate_model_output(answer, evidence)

    assert guard["passed"] is False
    assert set(guard["unsupported_market_inferences"]) == {
        "最大回撤不能直接改写为当前处于低位区间",
        "最大回撤不能直接改写为累计损失",
    }


def test_model_language_cleanup_hides_internal_evidence_packet_wording():
    cleaned = AgentService._clean_user_facing_model_language(
        "根据证据包中的 data，证据包未披露该原因。\n\n**因果边界**"
    )

    assert cleaned == "根据当前可验证数据，当前证据未披露该原因。"


def test_market_guard_rejects_misreading_five_twenty_volume_ratio_as_today():
    evidence = {
        "type": "market_brief",
        "indices": [
            {"metrics": {"volume_ratio_5_20": 3.927}}
        ],
    }

    valid = AgentService._validate_model_output(
        "近5日日均成交量约为近20日日均的3.93倍，近期交易活跃度抬升。",
        evidence,
    )
    invalid = AgentService._validate_model_output(
        "5日量比约3.93，显示今日成交显著放量。",
        evidence,
    )
    indirect = AgentService._validate_model_output(
        "量比约3.93，显示近期活跃度提高，契合今日的放量反弹。",
        evidence,
    )

    assert valid["passed"] is True
    assert invalid["passed"] is False
    assert indirect["passed"] is False
    assert invalid["unsupported_market_inferences"] == [
        "5日与20日均量比不能改写为今日成交量显著放大"
    ]
    assert indirect["unsupported_market_inferences"] == [
        "5日与20日均量比不能改写为今日成交量显著放大"
    ]


def test_model_language_cleanup_translates_raw_market_field_names():
    cleaned = AgentService._clean_user_facing_model_language(
        "两者technical_state均为动量转弱，volume_ratio_5_20为3.9，"
        "板块按pct_change排序。"
    )

    assert cleaned == (
        "两者的技术状态均为动量转弱，5/20日均量比为3.9，"
        "板块按涨跌幅排序。"
    )


def test_model_language_cleanup_hides_internal_ingestion_wording():
    cleaned = AgentService._clean_user_facing_model_language(
        "根据当前确定性证据包，当前已接入资料未披露全市场涨跌家数，"
        "北向数据尚未接入。"
    )

    assert "当前当前" not in cleaned
    assert "接入" not in cleaned
    assert cleaned == (
        "根据当前可验证证据，现有证据没有提供全市场涨跌家数，"
        "北向数据当前证据未提供。"
    )


def test_model_language_cleanup_hides_raw_label_assignment():
    cleaned = AgentService._clean_user_facing_model_language(
        "中期趋势仍确认不足（label = 偏弱）。"
    )

    assert cleaned == "中期趋势仍确认不足（偏弱）。"


def test_market_guard_hides_stale_utc_and_raw_field_status_from_users():
    evidence = {
        "type": "market_brief",
        "generated_at": "2026-07-21T07:00:00+00:00",
    }
    answer = (
        "板块数据标记为已过时（06:57 UTC）。\n"
        "technical_state字段显示动量转弱。"
    )

    guard = AgentService._validate_model_output(answer, evidence)

    assert guard["passed"] is False
    assert guard["private_operational_patterns"]


def test_market_guard_rejects_unproven_trend_sequence_and_fund_behavior():
    evidence = {
        "type": "market_brief",
        "indices": [
            {
                "metrics": {
                    "return_5d_pct": -4.4,
                    "max_drawdown_60d_pct": -16.87,
                    "trend_state": "中期偏弱",
                }
            }
        ],
    }
    answer = (
        "趋势依然向下。\n"
        "60日最大回撤继续扩大，资金将进一步降低风险敞口。\n"
        "市场仍在持续缩量。\n"
        "深证连续5日下跌4.4%，这是第一次较大反弹，还缺二次验证。"
    )

    guard = AgentService._validate_model_output(answer, evidence)

    assert guard["passed"] is False
    assert set(guard["unsupported_market_inferences"]) == {
        "单期最大回撤不能声称正在继续扩大",
        "缺少连续成交序列时不能声称持续放量或缩量",
        "市场指标不能推断资金将主动降低风险敞口",
        "区间收益不能写成连续多个交易日每天同向变化",
        "没有历史序列时不能声称这是第一次反弹或需要二次验证",
        "中期偏弱不能直接改写为已确认的下行趋势",
    }


def test_market_risk_prompt_keeps_focused_news_and_metric_meanings():
    evidence = {
        "type": "market_brief",
        "question_focus": {"key": "market_risk"},
        "indices": [
            {
                "name": "上证综指",
                "group": "china",
                "metrics": {
                    "return_5d_pct": -4.4,
                    "return_60d_pct": 3.2,
                    "max_drawdown_60d_pct": -11.2,
                    "volatility_20d_annualized_pct": 18.6,
                    "atr_14_pct": 1.6,
                    "trend_state": "中期偏弱",
                },
            }
        ],
        "market_drivers": {
            "market_key": "china",
            "items": [{"title": "用于反方核验的市场资讯"}],
        },
        "hot_sectors": {
            "sectors": [{"name": "不应进入风险提示词的板块"}]
        },
    }

    compact = AgentService._compact_market_brief_evidence(evidence)

    assert compact["market_drivers"]["items"] == [
        {"title": "用于反方核验的市场资讯"}
    ]
    assert "hot_sectors" not in compact
    assert "最近5个交易日累计收益" in compact["metric_definitions"]["return_5d_pct"]
    assert compact["indices"][0]["metrics"]["return_60d_pct"] == 3.2
    assert "最近60个交易日累计收益" in compact["metric_definitions"][
        "return_60d_pct"
    ]
    assert "不能与路径最大回撤直接比较" in compact["metric_definitions"][
        "volatility_20d_annualized_pct"
    ]
    assert "不能乘以天数累积" in compact["metric_definitions"]["atr_14_pct"]


def test_market_overview_prompt_keeps_explicitly_requested_60d_return():
    evidence = {
        "type": "market_brief",
        "user_question": "纳指20日和60日收益都为负吗？",
        "question_focus": {"key": "market_overview"},
        "indices": [
            {
                "symbol": "^IXIC",
                "name": "纳斯达克综合",
                "group": "us",
                "metrics": {
                    "return_20d_pct": -1.22,
                    "return_60d_pct": 5.76,
                },
            }
        ],
        "market_drivers": {"market_key": "us", "items": []},
    }

    compact = AgentService._compact_market_brief_evidence(evidence)

    assert compact["indices"][0]["metrics"]["return_20d_pct"] == -1.22
    assert compact["indices"][0]["metrics"]["return_60d_pct"] == 5.76
    assert "最近60个交易日累计收益" in compact["metric_definitions"][
        "return_60d_pct"
    ]


def test_market_guard_rejects_intraday_claim_from_annualized_volatility():
    evidence = {
        "type": "market_brief",
        "indices": [
            {
                "metrics": {
                    "volatility_20d_annualized_pct": 41.82,
                    "max_drawdown_60d_pct": -16.87,
                }
            }
        ],
    }
    answer = (
        "20日年化波动率为41.82%，说明近期出现多次较大日内摆动。\n"
        "60日最大回撤尚未进一步扩大，也仍未出现止跌。\n"
        "当前跌幅是否已构建新的60日路径低位，还需要确认。\n"
        "最大回撤为-16.87%，尚未超出此前波动区间。\n"
        "标普60日最大回撤-4.5%属于近期正常波动范围。\n"
        "三种指数60日最大回撤尚处于近60日路径的波动容忍度内。\n"
        "标普和纳指单日跌幅在近期正常波动范围内。\n"
        "这些下跌不是大阴线或恐慌性下跌，纯从价格看更像窄幅回调。\n"
        "盘中出现价格修复，说明前半段存在承接买盘。\n"
        "跌幅更深意味着已经经历更大的估值压缩，也更接近均值回归。\n"
        "四个代表性指数日均收盘价为-0.37%。\n"
        "重新站上MA20且伴随成交量确认，才算修复。\n"
        "标普20日年化波动率尚可，也没有明显的恐慌扩散迹象。\n"
        "标普60日路径最大调整幅度并不极端。\n"
        "标普60日最大回撤-4.5%，纳指-7.1%也小于14日平均真实波幅乘以天数的累积值。\n"
        "突发地缘事件驱动的下跌通常伴随放量。\n"
        "20日年化波动率显示三个指数中两个仍处于中等偏低波动区间。\n"
        "三大指数悉数转弱，标普、纳指、道指和罗素2000均跌破均线。\n"
        "道指若在连续数日内跌破均线，风险判断需要升级。\n"
        "如果MA20持续压制且无法快速收复，弱势会累积成更持续的承压格局。\n"
        "若下一期5日累计收益继续走低，说明压制已延续超过一周。"
    )

    guard = AgentService._validate_model_output(answer, evidence)

    assert guard["passed"] is False
    assert set(guard["unsupported_market_inferences"]) == {
        "年化波动率不能直接证明多次日内大幅摆动",
        "单期最大回撤不能声称尚未进一步扩大或已经止跌",
        "单日跌幅不能写成已经构建新的路径低位",
        "最大回撤不能直接写成尚未超出既有波动区间",
        "最大回撤不能直接定义为正常或合理波动范围",
        "单日涨跌不能直接定义为近期正常波动范围",
        "单日跌幅不能单独证明非恐慌或窄幅回调",
        "盘中反弹或价格修复不能直接证明承接买盘",
        "价格跌幅或回撤不能直接改写为估值压缩",
        "缺少历史校准时不能用跌幅越深支持均值回归",
        "代表性指数平均收益不能写成日均收盘价",
        "没有确定性阈值时不能把成交量写成均线确认条件",
        "缺少分位或阈值时不能评价年化波动率高低",
        "单一波动率或跌幅不能证明没有恐慌扩散",
        "缺少分位或阈值时不能把最大回撤定义为极端或不极端",
        "最大回撤不能与单期ATR按天数累积比较",
        "缺少历史校准时不能声称事件驱动下跌通常伴随放量",
        "缺少分位或阈值时不能把波动率划分为高低区间",
        "三大指数表述不能同时覆盖第四个代表性指数",
        "证据包没有给出观察窗口时不能发明连续数日确认条件",
        "均线压制不能直接外推为更持续的承压格局",
        "5日累计收益不能改写为趋势已延续超过一周",
    }


def test_market_guard_rejects_wrong_index_leader_ranking():
    evidence = {
        "type": "market_brief",
        "indices": [
            {
                "symbol": "^DJI",
                "name": "道琼斯工业指数",
                "status": "available",
                "metrics": {"return_1d_pct": -0.59},
            },
            {
                "symbol": "^RUT",
                "name": "罗素2000",
                "metrics": {"return_1d_pct": -0.67},
            },
        ],
    }

    wrong = AgentService._validate_model_output(
        "道琼斯工业指数日线收跌0.59%，是当日跌幅最大的指数。", evidence
    )
    correct = AgentService._validate_model_output(
        "罗素2000日线收跌0.67%，在这两个代表性指数中跌幅最大。", evidence
    )

    assert wrong["passed"] is False
    assert wrong["unsupported_market_inferences"] == [
        "指数领涨领跌或最大涨跌幅必须与当前证据排序一致"
    ]
    assert correct["passed"] is True


def test_market_guard_rejects_wrong_volatility_ranking():
    evidence = {
        "type": "market_brief",
        "indices": [
            {
                "symbol": "^GSPC",
                "name": "标普500",
                "metrics": {"volatility_20d_annualized_pct": 10.37},
            },
            {
                "symbol": "^DJI",
                "name": "道琼斯工业指数",
                "metrics": {"volatility_20d_annualized_pct": 7.78},
            },
        ],
    }

    guard = AgentService._validate_model_output(
        "标普500的20日年化波动率为10.37%，是两个指数中最低。", evidence
    )

    assert guard["passed"] is False
    assert guard["unsupported_market_inferences"] == [
        "指数波动率最高最低表述必须与当前证据排序一致"
    ]


def test_market_guard_rejects_three_major_indices_heading_for_four_index_packet():
    evidence = {
        "type": "market_brief",
        "indices": [
            {"symbol": "^GSPC", "name": "标普500", "metrics": {}},
            {"symbol": "^IXIC", "name": "纳斯达克综合", "metrics": {}},
            {"symbol": "^DJI", "name": "道琼斯工业指数", "metrics": {}},
            {"symbol": "^RUT", "name": "罗素2000", "metrics": {}},
        ],
    }
    answer = "三大指数（标普500、纳斯达克综合、道琼斯工业指数和罗素2000）均下跌。"

    guard = AgentService._validate_model_output(answer, evidence)

    assert guard["passed"] is False
    assert "三大指数表述不能与四个代表性指数混用" in guard[
        "unsupported_market_inferences"
    ]


def test_market_guard_allows_news_title_three_indices_and_factual_atr_value():
    evidence = {
        "type": "market_brief",
        "indices": [
            {
                "symbol": "^GSPC",
                "name": "标普500",
                "status": "available",
                "metrics": {"atr_14_pct": 0.97},
            },
            {
                "symbol": "^IXIC",
                "name": "纳斯达克综合",
                "status": "available",
                "metrics": {"atr_14_pct": 1.56},
            },
            {
                "symbol": "^DJI",
                "name": "道琼斯工业指数",
                "status": "available",
                "metrics": {"atr_14_pct": 1.06},
            },
            {
                "symbol": "^RUT",
                "name": "罗素2000",
                "status": "available",
                "metrics": {"atr_14_pct": 1.30},
            },
        ],
    }
    answer = (
        "资讯标题提到‘三大指数由涨转跌’，这里只把它作为背景线索。\n"
        "本次证据另行列出罗素2000，不把新闻标题改写为四指数结论。\n"
        "纳斯达克14日平均真实波幅占比达到1.56%，这是当前指标事实。"
    )

    guard = AgentService._validate_model_output(answer, evidence)

    assert guard["passed"] is True
    assert guard["unsupported_market_inferences"] == []


def test_market_guard_rejects_missing_available_news_and_wrong_return_direction():
    evidence = {
        "type": "market_brief",
        "indices": [
            {
                "symbol": "^GSPC",
                "name": "标普500",
                "status": "available",
                "metrics": {"max_drawdown_60d_pct": -4.5},
            },
            {
                "symbol": "^IXIC",
                "name": "纳斯达克综合",
                "status": "available",
                "metrics": {"return_20d_pct": -1.21, "return_60d_pct": 5.82},
            },
        ],
        "market_drivers": {
            "items": [{"title": "US stocks retreat after an early rally"}]
        },
    }
    answer = (
        "纳斯达克20日、60日累计收益均为负。\n"
        "标普500的60日最大回撤为-4.5%，因此反弹空间有限。\n"
        "当前证据中未提供市场广度和消息面驱动资讯。"
    )

    guard = AgentService._validate_model_output(answer, evidence)

    assert guard["passed"] is False
    assert set(guard["unsupported_market_inferences"]) == {
        "已有市场资讯时不能声称消息面驱动资讯缺失",
        "指数区间收益正负方向必须与当前证据一致",
        "区间收益或回撤不能证明后续上涨空间有限",
    }


def test_market_guard_allows_mixed_return_direction_and_cautious_space_boundary():
    evidence = {
        "type": "market_brief",
        "indices": [
            {
                "symbol": "^IXIC",
                "name": "纳斯达克综合",
                "status": "available",
                "metrics": {"return_20d_pct": -1.21, "return_60d_pct": 5.82},
            }
        ],
        "market_drivers": {
            "items": [{"title": "US stocks retreat after an early rally"}]
        },
    }
    answer = (
        "纳斯达克20日收益-1.21%，60日收益5.82%，两个周期方向分化。\n"
        "当前已有市场资讯标题，但标题只能作为线索，不能证明唯一因果。\n"
        "区间收益和回撤不能证明后续上涨空间有限。"
    )

    guard = AgentService._validate_model_output(answer, evidence)

    assert guard["passed"] is True
    assert guard["unsupported_market_inferences"] == []


def test_market_guard_rejects_missing_claim_for_available_return_metric():
    evidence = {
        "type": "market_brief",
        "indices": [
            {
                "symbol": "^IXIC",
                "name": "纳斯达克综合",
                "status": "available",
                "metrics": {"return_60d_pct": 5.76},
            }
        ],
    }
    missing = AgentService._validate_model_output(
        "纳指当前证据中未直接提供60日累计收益字段。", evidence
    )
    safe = AgentService._validate_model_output(
        "纳指60日累计收益为5.76%，该周期为正。", evidence
    )

    assert missing["passed"] is False
    assert missing["unsupported_market_inferences"] == [
        "已有指数区间收益时不能声称该字段缺失"
    ]
    assert safe["passed"] is True


def test_market_guard_rejects_index_trend_state_mismatch():
    evidence = {
        "type": "market_brief",
        "indices": [
            {
                "symbol": "^IXIC",
                "name": "纳斯达克综合",
                "status": "available",
                "metrics": {"trend_state": "趋势分化"},
            }
        ],
    }
    wrong = AgentService._validate_model_output(
        "纳指的中期趋势状态为偏弱。", evidence
    )
    safe = AgentService._validate_model_output(
        "纳指的趋势状态为趋势分化。", evidence
    )

    assert wrong["passed"] is False
    assert wrong["unsupported_market_inferences"] == [
        "指数趋势状态必须与当前证据一致"
    ]
    assert safe["passed"] is True


def test_market_trend_preview_includes_explicitly_requested_60d_return():
    evidence = {
        "type": "market_brief",
        "user_question": "纳指20日收益、60日收益、趋势状态分别是什么？",
        "question_focus": {"key": "trend_reversal", "label": "反弹与趋势确认"},
        "market_state": {"label": "偏强"},
        "market_drivers": {"market_key": "us", "market_label": "美国股市"},
        "indices": [
            {
                "symbol": "^IXIC",
                "name": "纳斯达克综合",
                "group": "us",
                "status": "available",
                "metrics": {
                    "return_1d_pct": 1.32,
                    "return_5d_pct": -1.0,
                    "return_20d_pct": -1.23,
                    "return_60d_pct": 5.76,
                    "trend_state": "中期偏弱",
                    "latest_close": 25844.95,
                    "ma20": 25846.5,
                },
            }
        ],
    }

    preview = AgentService._render_preview(evidence)

    assert "纳斯达克综合：20日 -1.23%，60日 5.76%" in preview
    assert "趋势状态 中期偏弱" in preview


def test_model_language_cleanup_translates_raw_return_field_names():
    cleaned = AgentService._clean_user_facing_model_language(
        "return_20d_pct为负，return_60d_pct为正。"
    )

    assert cleaned == "20日累计收益为负，60日累计收益为正。"


def test_market_guard_rejects_moving_average_status_conflict():
    evidence = {
        "type": "market_brief",
        "indices": [
            {
                "symbol": "^GSPC",
                "name": "标普500",
                "status": "available",
                "metrics": {
                    "latest_close": 7443.0,
                    "ma20": 7476.0,
                    "ma60": 7422.0,
                },
            },
            {
                "symbol": "^RUT",
                "name": "罗素2000",
                "metrics": {
                    "latest_close": 2942.0,
                    "ma20": 2986.0,
                    "ma60": 2902.0,
                },
            },
        ],
    }

    guard = AgentService._validate_model_output(
        "标普500距离MA20约-0.4%，距离MA60约+0.3%，两条均线均未被有效跌破。\n"
        "罗素2000已经在60日线下方。",
        evidence,
    )

    assert guard["passed"] is False
    assert guard["unsupported_market_inferences"] == [
        "均线是否跌破的表述必须与最新收盘和均线位置一致"
    ]


def test_market_guard_requires_explicit_failure_conditions_when_asked():
    evidence = {
        "type": "market_brief",
        "user_question": "这段判断的反方证据和失效条件是什么？",
        "indices": [],
    }

    guard = AgentService._validate_model_output("这里只回答了反方证据。", evidence)

    assert guard["passed"] is False
    assert guard["unsupported_market_inferences"] == [
        "用户明确询问失效条件时回答必须包含失效条件"
    ]


def test_stock_guard_rejects_invented_failure_thresholds_and_report_windows():
    evidence = {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "user_question": "中兴通讯的证据缺口和失效条件是什么？",
        "price_levels": {"recent_20d_low": 32.39, "ma20": 37.2805},
        "conditional_outlook": {
            "horizon": "未来 5—20 个交易日",
            "scenarios": [
                {
                    "name": "下行风险",
                    "condition": "收盘跌破关键参考位 32.39，同时20日收益继续恶化",
                    "meaning": "当前判断需要重算。",
                }
            ],
            "invalidation": "价格跨越关键参考位后必须重算。",
        },
        "analysis_board": {
            "tracking_plan": [
                {"horizon_sessions": 5, "checks": ["复核价格和公告证据"]}
            ]
        },
    }
    answer = (
        "### 失效条件\n"
        "1. 毛利率继续向25%以下收缩，且经营现金流连续两个报告期为负。\n"
        "2. 存货增速持续高于收入10个百分点以上。\n"
        "3. 政企业务增速放缓至个位数。"
    )

    guard = AgentService._validate_model_output(answer, evidence)

    assert guard["passed"] is False
    assert "个股失效条件只能使用证据包已有阈值和观察周期" in guard[
        "unsupported_market_inferences"
    ]


def test_stock_guard_accepts_deterministic_failure_condition_from_outlook():
    evidence = {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "user_question": "中兴通讯的失效条件是什么？",
        "price_levels": {"recent_20d_low": 32.39, "ma20": 37.2805},
        "conditional_outlook": {
            "horizon": "未来 5—20 个交易日",
            "scenarios": [
                {
                    "name": "下行风险",
                    "condition": "收盘跌破关键参考位 32.39，同时20日收益继续恶化",
                    "meaning": "当前判断需要重算。",
                }
            ],
            "invalidation": "价格跨越关键参考位后必须重算。",
        },
        "analysis_board": {"tracking_plan": []},
    }

    guard = AgentService._validate_model_output(
        "### 失效条件\n- 收盘跌破关键参考位32.39，同时20日收益继续恶化。",
        evidence,
    )

    assert guard["passed"] is True


def test_stock_guard_rejects_invented_observation_window_and_report_month():
    evidence = {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "user_question": "下一步应该补什么证据？",
        "conditional_outlook": {
            "horizon": "未来 5—20 个交易日",
            "scenarios": [],
        },
        "analysis_board": {
            "tracking_plan": [
                {"horizon_sessions": 3},
                {"horizon_sessions": 5},
                {"horizon_sessions": 10},
            ]
        },
    }
    answer = (
        "下一份中报预计8月披露。\n"
        "1. 2—3个交易日内观察价格。\n"
        "2. 5个交易日内按既定计划复核。"
    )

    guard = AgentService._validate_model_output(answer, evidence)

    assert guard["passed"] is False
    assert "个股观察周期只能使用研究计划已有交易日窗口" in guard[
        "unsupported_market_inferences"
    ]
    assert "缺少披露日历证据时不能预测下一份报告日期" in guard[
        "unsupported_market_inferences"
    ]


def test_model_language_cleanup_repairs_wireless_access_typo():
    cleaned = AgentService._clean_user_facing_model_language(
        "需要确认无钱接入产品毛利率是否下降。"
    )

    assert cleaned == "需要确认无线接入产品毛利率是否下降。"


def test_stock_guard_rejects_report_date_and_drawdown_window_conflicts():
    evidence = {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "metrics": {"max_drawdown_60d_pct": -16.7777},
        "fundamentals": {
            "summary": {
                "latest_report": {
                    "report_date": "2026-03-31",
                    "report_date_name": "2026一季报",
                    "notice_date": "2026-04-25",
                }
            }
        },
    }
    answer = (
        "2026一季报（公告日2025-04-25）营收增长。\n"
        "6月30日公告的Q1利润同比下降46.58%。\n"
        "20日最大回撤为-16.7777%。"
    )

    guard = AgentService._validate_model_output(answer, evidence)

    assert guard["passed"] is False
    assert "财报公告日期必须与结构化报告一致" in guard[
        "unsupported_market_inferences"
    ]
    assert "最大回撤观察窗口必须与确定性指标一致" in guard[
        "unsupported_market_inferences"
    ]


def test_stock_guard_does_not_treat_percentage_near_announcement_as_notice_date():
    evidence = {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "fundamentals": {
            "summary": {
                "latest_report": {
                    "report_date": "2026-03-31",
                    "report_date_name": "2026一季报",
                    "report_type": "一季报",
                    "notice_date": "2026-04-25",
                    "net_profit_yoy_pct": -46.58,
                }
            }
        },
    }

    guard = AgentService._validate_model_output(
        "2026一季报利润同比下降46.58%，目前没有新的公告或财务数据改变这一事实。",
        evidence,
    )

    assert guard["passed"] is True
    assert "财报公告日期必须与结构化报告一致" not in guard[
        "unsupported_market_inferences"
    ]


def test_stock_guard_rejects_relabeling_stale_daily_bar_as_today():
    evidence = {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "user_question": "中兴通讯今天为什么跌？",
        "metrics": {"latest_close": 33.73, "return_1d_pct": -6.31},
        "provenance": {"market_timestamp": "2026-07-20T01:30:00+00:00"},
        "current_quote": {
            "price": 34.88,
            "pct_change": 3.41,
            "market_timestamp": "2026-07-21T16:14:42+08:00",
        },
    }

    guard = AgentService._validate_model_output(
        "中兴通讯今日下跌，最新收盘价33.73元，单日下跌6.31%。",
        evidence,
    )

    assert guard["passed"] is False
    assert "今日涨跌方向必须与更新的当前报价一致" in guard[
        "unsupported_market_inferences"
    ]
    assert "今日或当前价格必须优先使用更新的报价快照" in guard[
        "unsupported_market_inferences"
    ]


def test_stock_guard_accepts_current_quote_with_prior_daily_bar_distinction():
    evidence = {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "user_question": "中兴通讯今天为什么跌？",
        "metrics": {"latest_close": 33.73, "return_1d_pct": -6.31},
        "provenance": {"market_timestamp": "2026-07-20T01:30:00+00:00"},
        "current_quote": {
            "price": 34.88,
            "pct_change": 3.41,
            "market_timestamp": "2026-07-21T16:14:42+08:00",
        },
    }

    guard = AgentService._validate_model_output(
        "按2026-07-21 16:14报价快照，当前不是下跌，而是上涨3.41%，报34.88元。\n"
        "上一交易日完整日线收于33.73元，当日跌幅为6.31%。",
        evidence,
    )

    assert guard["passed"] is True


def test_stock_guard_rejects_current_quote_relabelled_as_today_close():
    evidence = {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "user_question": "中兴通讯今天为什么涨？",
        "metrics": {"latest_close": 34.88, "return_1d_pct": 3.41},
        "provenance": {"market_timestamp": "2026-07-21T01:30:00+00:00"},
        "current_quote": {
            "price": 37.86,
            "pct_change": 8.54,
            "market_timestamp": "2026-07-22T11:10:15+08:00",
        },
        "stock_market_context": {
            "analysis_target": {
                "market_date": "2026-07-22",
                "basis": "current_quote",
            }
        },
    }
    answer = (
        "中兴通讯今日以37.86元收盘，涨幅8.54%。\n"
        "上一完整日线收盘34.88元，当日上涨3.41%。"
    )

    guard = AgentService._validate_model_output(answer, evidence)

    assert guard["passed"] is False
    assert "更新的报价快照不能写成当日收盘" in guard[
        "unsupported_market_inferences"
    ]


def test_current_quote_semantics_normalizer_preserves_history_close():
    evidence = {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "provenance": {"market_timestamp": "2026-07-21T01:30:00+00:00"},
        "current_quote": {
            "price": 37.86,
            "pct_change": 8.54,
            "market_timestamp": "2026-07-22T11:10:15+08:00",
        },
        "stock_market_context": {
            "analysis_target": {"basis": "current_quote"}
        },
    }

    normalized = agent_module._normalize_current_quote_semantics(
        "中兴通讯今日以37.86元收盘，涨幅8.54%。\n"
        "上一完整日线收盘34.88元。",
        evidence,
    )

    assert "最新报价为 37.86元" in normalized
    assert "今日以37.86元收盘" not in normalized
    assert "上一完整日线收盘34.88元" in normalized


def test_current_quote_semantics_preserves_intraday_boundary_language():
    evidence = {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "provenance": {"market_timestamp": "2026-07-21T01:30:00+00:00"},
        "current_quote": {
            "price": 38.37,
            "pct_change": 10.01,
            "market_timestamp": "2026-07-22T13:00:06+08:00",
        },
        "stock_market_context": {
            "analysis_target": {"basis": "current_quote"}
        },
    }
    answer = (
        "目前是盘中上涨，尚未收盘。"
        "这是带时间戳的最新报价，不是收盘价。"
        "盘中状态仍可能变化，收盘位置尚未形成。"
        "最终应以完整日线收盘价为准，收盘后再核对均线位置。"
    )

    normalized = agent_module._normalize_current_quote_semantics(answer, evidence)
    guard = AgentService._validate_model_output(answer, evidence)

    assert normalized == answer
    assert "尚未最新报价" not in normalized
    assert "不是最新报价" not in normalized
    assert "最新报价位置尚未形成" not in normalized
    assert guard["passed"] is True


def test_post_close_quote_semantics_remove_false_intraday_boundary():
    evidence = {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "provenance": {"market_timestamp": "2026-07-21T01:30:00+00:00"},
        "current_quote": {
            "price": 37.5,
            "pct_change": 7.51,
            "market_timestamp": "2026-07-22T15:06:30+08:00",
            "quote_basis": "post_close_snapshot",
            "quote_label": "收盘后最新报价",
            "complete_daily_bar_confirmed": False,
        },
        "stock_market_context": {
            "analysis_target": {"basis": "current_quote"}
        },
    }
    answer = "该报价属于盘中报价，尚未收盘，收盘前仍可能变化。"

    normalized = agent_module._normalize_current_quote_session_semantics(
        answer, evidence
    )
    guard = AgentService._validate_model_output(answer, evidence)

    assert "收盘后最新报价" in normalized
    assert "市场已经收盘" in normalized
    assert "当日交易已经结束" in normalized
    assert guard["passed"] is False
    assert "收盘后报价不能继续描述为盘中或尚未收盘" in guard[
        "unsupported_market_inferences"
    ]


def test_current_quote_close_normalizer_preserves_market_status_and_repairs_price():
    evidence = {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "provenance": {"market_timestamp": "2026-07-21T01:30:00+00:00"},
        "current_quote": {
            "price": 37.5,
            "pct_change": 7.51,
            "market_timestamp": "2026-07-22T15:06:30+08:00",
            "quote_basis": "post_close_snapshot",
        },
        "stock_market_context": {
            "analysis_target": {"basis": "current_quote"}
        },
    }

    market_status = agent_module._normalize_current_quote_semantics(
        "A股今日已经收盘。", evidence
    )
    price_claim = agent_module._normalize_current_quote_semantics(
        "今日收盘价37.50元已站上均线，但此前完整日线收盘34.88元。",
        evidence,
    )

    assert market_status == "A股今日已经收盘。"
    assert "最新报价37.50元" in price_claim
    assert "此前完整日线收盘34.88元" in price_claim


def test_history_close_mislabeled_as_latest_quote_is_normalized():
    evidence = {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "metrics": {"latest_close": 34.88},
        "provenance": {"market_timestamp": "2026-07-21T01:30:00+00:00"},
        "current_quote": {
            "price": 37.5,
            "previous_close": 34.88,
            "pct_change": 7.51,
            "market_timestamp": "2026-07-22T15:06:30+08:00",
        },
        "stock_market_context": {
            "analysis_target": {"basis": "current_quote"}
        },
    }
    answer = (
        "A股已收盘，当前为2026年7月22日收盘后最新报价。"
        "中兴通讯最新报价37.50元，较前一交易日最新报价34.88元上涨7.51%。"
        "最新完整日线截止7月21日，最新报价34.88元。"
    )

    normalized = agent_module._normalize_history_price_mislabeled_as_current_quote(
        answer, evidence
    )
    session_guard = AgentService._validate_model_output(
        "A股已收盘，当前为2026年7月22日收盘后最新报价。", evidence
    )

    assert "收盘价34.88元" in normalized
    assert "最新报价34.88元" not in normalized
    assert "A股已收盘" in normalized
    assert session_guard["passed"] is True


def test_current_quote_ma20_relation_is_normalized_and_guarded():
    evidence = {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "metrics": {"ma20": 37.28},
        "price_levels": {"ma20": 37.28},
        "provenance": {"market_timestamp": "2026-07-21T01:30:00+00:00"},
        "current_quote": {
            "price": 37.5,
            "pct_change": 7.51,
            "market_timestamp": "2026-07-22T15:06:30+08:00",
        },
        "stock_market_context": {
            "analysis_target": {"basis": "current_quote"}
        },
    }
    answer = "最新报价仍低于 MA20（37.28元）。"

    normalized = agent_module._normalize_stock_current_quote_ma20_relation(
        answer, evidence
    )
    guard = AgentService._validate_model_output(answer, evidence)

    assert "最新报价已高于 MA20" in normalized
    assert guard["passed"] is False
    assert "当前报价与MA20关系必须与确定性数据一致" in guard[
        "unsupported_market_inferences"
    ]


def test_current_limit_status_is_rewritten_after_price_falls_off_limit():
    evidence = {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "user_question": "中兴通讯现在还涨停吗？",
        "provenance": {"market_timestamp": "2026-07-21T01:30:00+00:00"},
        "current_quote": {
            "price": 38.2,
            "pct_change": 9.52,
            "market_timestamp": "2026-07-22T13:20:03+08:00",
        },
        "a_share_information": {
            "news": [{"title": "中兴通讯盘中触及涨停后成交放大"}]
        },
    }
    answer = "最新报价38.2元，涨幅9.52%，盘中涨停。"

    rejected = AgentService._validate_model_output(answer, evidence)
    normalized = agent_module._normalize_current_limit_status(answer, evidence)
    accepted = AgentService._validate_model_output(normalized, evidence)

    assert rejected["passed"] is False
    assert "当前涨跌停状态必须与最新报价涨跌幅一致" in rejected[
        "unsupported_market_inferences"
    ]
    assert "盘中曾触及涨停后回落" in normalized
    assert "盘中涨停" not in normalized
    assert accepted["passed"] is True


def test_relative_event_date_normalizer_prefers_absolute_dates():
    normalized = agent_module._normalize_relative_event_dates(
        "公告为2026-07-20（昨日）发布。昨日（7月21日）还有媒体报道；"
        "昨日公司也披露了回购结果。"
    )

    assert "2026-07-20发布" in normalized
    assert "7月21日还有媒体报道" in normalized
    assert "此前公司也披露了回购结果" in normalized
    assert "昨日" not in normalized


def test_stock_move_preview_understands_why_up_wording_and_stays_concise():
    evidence = {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "display_name": "中兴通讯",
        "user_question": "中兴通讯今天为什么上涨？",
        "metrics": {
            "latest_close": 34.88,
            "return_1d_pct": 3.41,
        },
        "provenance": {"market_timestamp": "2026-07-21T01:30:00+00:00"},
        "current_quote": {
            "price": 38.37,
            "pct_change": 10.01,
            "currency": "CNY",
            "market_timestamp": "2026-07-22T11:21:06+08:00",
        },
        "stock_market_context": {
            "analysis_target": {
                "market_date": "2026-07-22",
                "basis": "current_quote",
            },
            "stock_target": {"status": "current_quote"},
            "market_state": {
                "summary": "目标交易日的代表性指数对照仍待补证。"
            },
            "market_breadth": {"same_date_as_target": False},
            "company_industry": "通信设备",
            "exact_industry_match_available": False,
        },
        "a_share_information": {},
    }

    answer = AgentService._render_preview(evidence)

    assert answer.startswith("中兴通讯涨跌证据核对")
    assert "当前报价" in answer
    assert "38.37" in answer
    assert "固定同行" not in answer
    assert len(answer) < 1200


def test_stock_move_preview_labels_post_close_quote_and_daily_bar_date():
    evidence = {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "display_name": "中兴通讯",
        "user_question": (
            "请分析中兴通讯今天上涨的事实、可能解释、反方证据和不能确认的部分。"
            "第一句先说明A股现在是否已经收盘。"
        ),
        "metrics": {"latest_close": 34.88, "return_1d_pct": 3.41},
        "provenance": {"market_timestamp": "2026-07-21T01:30:00+00:00"},
        "current_quote": {
            "price": 37.5,
            "pct_change": 7.51,
            "currency": "CNY",
            "market_timestamp": "2026-07-22T15:06:30+08:00",
            "quote_basis": "post_close_snapshot",
            "quote_label": "收盘后最新报价",
            "complete_daily_bar_confirmed": False,
        },
        "stock_market_context": {
            "analysis_target": {
                "market_date": "2026-07-22",
                "basis": "current_quote",
            },
            "stock_target": {"status": "current_quote"},
            "market_breadth": {"same_date_as_target": False},
            "company_industry": "通信设备",
            "exact_industry_match_available": False,
        },
        "a_share_information": {},
    }

    answer = AgentService._render_preview(evidence)

    assert answer.startswith("A股已经收盘。")
    assert "收盘后最新报价（2026-07-22 15:06）" in answer
    assert "A股已经收盘" in answer
    assert "最近完整日线（2026-07-21）" in answer
    assert "2026-07-21 09:30" not in answer
    assert len(answer) < 1200


def test_stock_limit_query_preview_states_current_and_prior_touch_separately():
    evidence = {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "display_name": "中兴通讯",
        "user_question": "中兴通讯现在还处于涨停吗？",
        "metrics": {"latest_close": 34.88, "return_1d_pct": 3.41},
        "provenance": {"market_timestamp": "2026-07-21T01:30:00+00:00"},
        "current_quote": {
            "price": 37.88,
            "pct_change": 8.6,
            "currency": "CNY",
            "market_timestamp": "2026-07-22T13:26:03+08:00",
        },
        "stock_market_context": {
            "analysis_target": {"basis": "current_quote"},
            "market_breadth": {"same_date_as_target": False},
            "exact_industry_match_available": False,
        },
        "a_share_information": {
            "news": [{"title": "中兴通讯盘中触及涨停后回落"}],
            "announcements": [],
            "social_posts": [],
        },
        "research_frame": {"missing_information": []},
    }

    answer = AgentService._render_preview(evidence)

    assert answer.startswith("不是。")
    assert "当前已不在涨停价" in answer
    assert "盘中曾触及涨停" in answer
    assert "8.6%" in answer


def test_stock_guard_requires_current_quote_when_user_asks_about_today():
    evidence = {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "user_question": "中兴通讯今天为什么跌？",
        "metrics": {"latest_close": 33.73, "return_1d_pct": -6.31},
        "provenance": {"market_timestamp": "2026-07-20T01:30:00+00:00"},
        "current_quote": {
            "price": 34.88,
            "pct_change": 3.41,
            "market_timestamp": "2026-07-21T16:14:42+08:00",
        },
    }

    guard = AgentService._validate_model_output(
        "最近完整日线收于33.73元，当日跌幅为6.31%。",
        evidence,
    )

    assert guard["passed"] is False
    assert "用户询问今日时必须给出更新报价并区分历史日线" in guard[
        "unsupported_market_inferences"
    ]


def test_stock_guard_rejects_cross_date_breadth_as_systemic_explanation():
    evidence = {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "stock_market_context": {
            "analysis_target": {"market_date": "2026-07-20"},
            "market_breadth": {
                "market_date": "2026-07-21",
                "same_date_as_target": False,
                "breadth": {
                    "advancers": 3107,
                    "decliners": 2300,
                    "unchanged": 121,
                },
                "turnover": {"total_amount_100m_cny": 29734.49},
            },
        },
    }

    guard = AgentService._validate_model_output(
        "上证与深证涨跌互现，因此没有全市场系统性拖累。",
        evidence,
    )

    assert guard["passed"] is False
    assert "跨日期市场广度不能用于排除目标日的系统性拖累" in guard[
        "unsupported_market_inferences"
    ]


def test_stock_guard_requires_component_breadth_for_industry_participation_claims():
    evidence = {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "stock_market_context": {
            "exact_industry_index": {
                "status": "same_market_date",
                "name": "通信设备",
                "return_1d_pct": -1.42,
                "component_breadth": {
                    "status": "unavailable_for_target_date"
                },
            }
        },
    }

    unsafe = AgentService._validate_model_output(
        "通信设备行业当日普跌，参与面较广。", evidence
    )
    cautious = AgentService._validate_model_output(
        "通信设备指数当日下跌1.42%，但尚未取得成分涨跌家数，不能判断行业是否普跌。",
        evidence,
    )
    available_evidence = {
        **evidence,
        "stock_market_context": {
            "exact_industry_index": {
                **evidence["stock_market_context"]["exact_industry_index"],
                "component_breadth": {
                    "status": "available",
                    "advancers": 8,
                    "decliners": 40,
                    "unchanged": 2,
                    "state": "普跌",
                },
            }
        },
    }
    supported = AgentService._validate_model_output(
        "通信设备行业当日普跌，40只成分下跌、8只上涨、2只平盘。",
        available_evidence,
    )
    causal = AgentService._validate_model_output(
        "中兴通讯下跌是通信设备行业普跌与个股分化共同作用的结果。",
        available_evidence,
    )

    assert unsafe["passed"] is False
    assert "缺少行业成分涨跌家数时不能确认行业普涨普跌或参与面" in unsafe[
        "unsupported_market_inferences"
    ]
    assert cautious["passed"] is True
    assert supported["passed"] is True
    assert causal["passed"] is False
    assert "行业成分广度只能描述同步性不能证明个股涨跌因果" in causal[
        "unsupported_market_inferences"
    ]


def test_stock_guard_does_not_let_indices_alone_exclude_systemic_drag():
    evidence = {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "stock_market_context": {
            "analysis_target": {"market_date": "2026-07-20"},
            "stock_target": {
                "market_date": "2026-07-20",
                "close": 33.73,
                "return_1d_pct": -6.31,
            },
            "indices": [
                {"name": "上证综指", "return_1d_pct": 0.85},
                {"name": "深证成指", "return_1d_pct": -0.71},
            ],
            "market_breadth": {
                "market_date": "2026-07-21",
                "same_date_as_target": False,
                "breadth": {
                    "advancers": 3107,
                    "decliners": 2300,
                    "unchanged": 121,
                },
                "turnover": {"total_amount_100m_cny": 29734.49},
            },
            "exact_industry_index": {
                "status": "same_market_date",
                "name": "通信设备",
                "return_1d_pct": -1.42,
            },
        },
    }

    guard = AgentService._validate_model_output(
        "当日上证综指上涨，因此排除系统性拖累。", evidence
    )

    assert guard["passed"] is False
    assert "跨日期市场广度不能用于排除目标日的系统性拖累" in guard[
        "unsupported_market_inferences"
    ]

    real_model_wording = (
        "7月20日中兴通讯收盘33.73元，跌幅6.31%。"
        "同日上证综指上涨0.85%，深证成指下跌0.71%。"
        "上证上涨、深证小幅下跌，说明当日市场未形成系统性拖累。\n\n"
        "通信设备指数同日下跌1.42%，只能说明行业样本同步承压；"
        "现有证据仍不能把个股下跌锁定为单一市场、行业或公司事件。"
    )
    real_wording_guard = AgentService._validate_model_output(
        real_model_wording,
        evidence,
    )
    repaired = AgentService._repair_guard_failure(
        real_model_wording,
        evidence,
        real_wording_guard,
    )

    assert real_wording_guard["passed"] is False
    assert "跨日期市场广度不能用于排除目标日的系统性拖累" in (
        real_wording_guard["unsupported_market_inferences"]
    )
    assert repaired is not None
    repaired_answer, repaired_guard = repaired
    assert "中兴通讯收盘33.73元" in repaired_answer
    assert "上证综指上涨0.85%" in repaired_answer
    assert "未形成系统性拖累" not in repaired_answer
    assert repaired_guard["passed"] is True

    independent_guard = AgentService._validate_model_output(
        "中兴通讯下跌6.31%，属于个股独立下跌，非大盘或行业系统性拖累所致。",
        evidence,
    )
    relative_index_guard = AgentService._validate_model_output(
        "中兴通讯相对两大指数分别跑输7.16和5.60个百分点，不属于系统性拖累。",
        evidence,
    )
    assert independent_guard["passed"] is False
    assert "跨日期市场广度不能用于排除目标日的系统性拖累" in (
        independent_guard["unsupported_market_inferences"]
    )
    assert relative_index_guard["passed"] is False
    assert "跨日期市场广度不能用于排除目标日的系统性拖累" in (
        relative_index_guard["unsupported_market_inferences"]
    )

    mislabeled_breadth = AgentService._validate_model_output(
        "当日全市场广度（7月20日）：全A股上涨3107只、下跌2300只、"
        "平盘121只，沪深京成交额约29734.49亿元。市场并非全面下跌。",
        evidence,
    )
    safely_labeled_breadth = AgentService._validate_model_output(
        "7月21日全A股上涨3107只、下跌2300只、平盘121只，"
        "但与目标日不一致，不能用于解释7月20日中兴通讯下跌。",
        evidence,
    )
    assert mislabeled_breadth["passed"] is False
    assert "跨日期市场广度不能用于排除目标日的系统性拖累" in (
        mislabeled_breadth["unsupported_market_inferences"]
    )
    assert safely_labeled_breadth["passed"] is True

    flexible_turnover_wording = AgentService._validate_model_output(
        "7月20日A股全市场成交约29734.49亿元，"
        "上涨家数占优（3107家涨、2300家跌、121家平盘）。",
        evidence,
    )
    assert flexible_turnover_wording["passed"] is False
    assert "跨日期市场广度不能用于排除目标日的系统性拖累" in (
        flexible_turnover_wording["unsupported_market_inferences"]
    )

    section_answer = (
        "### 同日指数事实\n"
        "中兴通讯下跌6.31%，上证上涨0.85%，深证下跌0.71%。\n\n"
        "**当日全市场广度（7月20日**\n"
        "）\n"
        "- 全A股上涨3107只、下跌2300只、平盘121只\n"
        "- 成交额约29734.49亿元\n"
        "- 市场并非全面下跌\n\n"
        "### 证据边界\n"
        "现有证据缺少同日全市场广度，不能确认目标日的系统性拖累。"
    )
    section_guard = AgentService._validate_model_output(
        section_answer,
        evidence,
    )
    section_repaired = AgentService._repair_guard_failure(
        section_answer,
        evidence,
        section_guard,
    )
    assert section_repaired is not None
    assert "### 同日指数事实" in section_repaired[0]
    assert "### 证据边界" in section_repaired[0]
    assert "全A股上涨3107只" not in section_repaired[0]
    assert "成交额约29734.49亿元" not in section_repaired[0]
    assert "\n）\n" not in section_repaired[0]
    assert section_repaired[1]["passed"] is True

    causal_hypothesis_answer = (
        "现有证据不能确认7月20日中兴通讯下跌的指定原因；"
        "已确认的只是当日价格、同日指数和行业成分涨跌横截面。"
        "该跌幅可能包含公司特定因素，例如前期5日收益转弱、价格运行在MA20下方；"
        "也可能是行业内部轮动中中兴业务结构未受益。"
        "中兴跌幅远高于行业中位数，说明其跌幅有自身原因。"
        "最常见的情况是基本面疑虑、持有人分散和市场提前定价。"
        "具体驱动仍需核对同日公告、盘中消息和正式交易资料；"
        "在取得原始证据之前只能保留因果未知的边界。"
    )
    causal_hypothesis_guard = AgentService._validate_model_output(
        causal_hypothesis_answer,
        evidence,
    )
    causal_hypothesis_repaired = AgentService._repair_guard_failure(
        causal_hypothesis_answer,
        evidence,
        causal_hypothesis_guard,
    )
    assert causal_hypothesis_guard["passed"] is False
    assert "缺少事件或业务证据时不能用技术指标行业轮动或业务结构解释个股涨跌" in (
        causal_hypothesis_guard["unsupported_market_inferences"]
    )
    assert causal_hypothesis_repaired is not None
    assert "MA20" not in causal_hypothesis_repaired[0]
    assert "自身原因" not in causal_hypothesis_repaired[0]
    assert "提前定价" not in causal_hypothesis_repaired[0]
    assert "具体驱动仍需核对" in causal_hypothesis_repaired[0]
    assert causal_hypothesis_repaired[1]["passed"] is True

    absorption_answer = (
        "2026一季报营收同比6.13%、净利润同比下降46.58%；"
        "这些数值只描述已披露报告期，不能自动解释7月20日的价格变化。\n"
        "这些基本面压力已在市场消化，情绪驱动的短期超跌需要继续复盘。\n"
        "一季报盈利质量承压不构成新信息。\n"
        "这些基本面压力是此前已存在的信息，不是7月20日新出现的驱动。\n"
        "公司最新季报并不是7月20日的新信息，不能作为当日上涨原因。\n"
        "现有证据只能确认财报数值，不能确认它对7月20日价格的因果；"
        "后续仍需核对同日公告、正式新闻和盘中交易证据。"
    )
    absorption_evidence = {
        **evidence,
        "fundamentals": {
            "summary": {
                "latest_report": {
                    "report_date_name": "2026一季报",
                    "revenue_yoy_pct": 6.13,
                    "parent_net_profit_yoy_pct": -46.58,
                }
            }
        },
    }
    absorption_guard = AgentService._validate_model_output(
        absorption_answer,
        absorption_evidence,
    )
    absorption_repaired = AgentService._repair_guard_failure(
        absorption_answer,
        absorption_evidence,
        absorption_guard,
    )

    assert absorption_guard["passed"] is False
    assert "缺少事件研究证据时不能声称基本面已被市场消化或情绪驱动超跌" in (
        absorption_guard["unsupported_market_inferences"]
    )
    assert absorption_repaired is not None
    assert "已在市场消化" not in absorption_repaired[0]
    assert "不构成新信息" not in absorption_repaired[0]
    assert "此前已存在的信息" not in absorption_repaired[0]
    assert "最新季报并不是" not in absorption_repaired[0]
    assert "只能确认财报数值" in absorption_repaired[0]
    assert absorption_repaired[1]["passed"] is True

    event_sentiment_answer = (
        "7月20日公司披露回购实施完成，按规定属于中性/偏正面披露。"
        "同日媒体报道合作协议，属于中性事件，未构成明显催化剂。"
        "这些标题只能用于定位原文，不能证明7月20日涨跌因果。"
    )
    event_sentiment_guard = AgentService._validate_model_output(
        event_sentiment_answer,
        evidence,
    )
    assert event_sentiment_guard["passed"] is False
    assert "公告或媒体线索不能在缺少事件研究时评为正面负面或催化" in (
        event_sentiment_guard["unsupported_market_inferences"]
    )


def test_stock_guard_requires_public_boundary_for_unadjusted_component_fallback():
    evidence = {
        "type": "stock_research",
        "symbol": "300750.SZ",
        "display_name": "宁德时代",
        "user_question": "说明贝特瑞的数据源降级口径",
        "stock_market_context": {
            "exact_industry_index": {
                "status": "same_market_date",
                "name": "CS电池",
                "component_breadth": {
                    "status": "available",
                    "advancers": 20,
                    "decliners": 30,
                    "unchanged": 0,
                    "coverage": {
                        "constituents": 50,
                        "available_returns": 50,
                        "primary_adjusted_returns": 49,
                        "fallback_unadjusted_returns": 1,
                    },
                    "source_fallbacks": [
                        {
                            "symbol": "920185.BJ",
                            "name": "贝特瑞",
                            "public_source_label": "新浪公开日线",
                            "adjustment": "unadjusted",
                        }
                    ],
                },
            }
        },
    }
    answer = "电池指数50只成分中上涨20只、下跌30只、平盘0只。"

    guard = AgentService._validate_model_output(answer, evidence)
    repaired = AgentService._repair_guard_failure(answer, evidence, guard)
    safe = AgentService._validate_model_output(
        "贝特瑞（920185.BJ）使用新浪公开未复权日线补充；"
        "若目标日前后存在除权除息，其单日收益和静态贡献需要重新核对。",
        evidence,
    )
    raw_internal = AgentService._validate_model_output(
        "贝特瑞使用新浪公开未复权日线补充，fallback_unadjusted_returns=1；"
        "若存在除权除息需要复核。",
        evidence,
    )
    unsafe_source_wording = (
        "### 贝特瑞数据源说明\n"
        "贝特瑞因当前数据源未返回历史，使用新浪公开未复权日线补充。\n"
        "若目标日前后存在除权除息，其收益和贡献需要重新核对。"
    )
    unsafe_source_guard = AgentService._validate_model_output(
        unsafe_source_wording,
        evidence,
    )
    unsafe_source_repaired = AgentService._repair_guard_failure(
        unsafe_source_wording,
        evidence,
        unsafe_source_guard,
    )
    combined_unsafe_source_wording = (
        "50只成分股中有1只（贝特瑞，920185.BJ）使用新浪公开未复权日线补充，"
        "而非标准复权行情源。原因是当前行情源未返回目标日前日线历史。"
        "若该股在目标日前后"
        "存在除权除息，未复权日线涨跌幅可能与实际复权收益存在口径偏差。"
    )
    combined_unsafe_guard = AgentService._validate_model_output(
        combined_unsafe_source_wording,
        evidence,
    )
    combined_unsafe_repaired = AgentService._repair_guard_failure(
        combined_unsafe_source_wording,
        evidence,
        combined_unsafe_guard,
    )

    assert guard["passed"] is False
    assert "行业成分使用未复权补充行情时必须说明证券来源和除权边界" in guard[
        "semantic_conflicts"
    ]
    assert repaired is not None
    assert "成分行情口径补充" in repaired[0]
    assert "贝特瑞（920185.BJ）使用新浪公开未复权日线补充" in repaired[0]
    assert "其余 49 只使用前复权日线" in repaired[0]
    assert "除权除息" in repaired[0]
    assert repaired[1]["passed"] is True
    assert safe["passed"] is True
    assert raw_internal["passed"] is False
    assert raw_internal["private_operational_patterns"]
    assert unsafe_source_guard["passed"] is False
    assert unsafe_source_guard["private_operational_patterns"]
    assert unsafe_source_repaired is not None
    assert "当前数据源未返回" not in unsafe_source_repaired[0]
    assert "贝特瑞（920185.BJ）使用新浪公开未复权日线补充" in (
        unsafe_source_repaired[0]
    )
    assert unsafe_source_repaired[1]["passed"] is True
    assert combined_unsafe_guard["passed"] is False
    assert combined_unsafe_repaired is not None
    assert "当前行情源未返回" not in combined_unsafe_repaired[0]
    assert "贝特瑞（920185.BJ）使用新浪公开未复权日线补充" in (
        combined_unsafe_repaired[0]
    )
    assert combined_unsafe_repaired[1]["passed"] is True


def test_stock_guard_requires_requested_subject_contribution_and_binds_60d_return():
    evidence = {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "display_name": "中兴通讯",
        "user_question": "说明中兴对行业指数的估算贡献及口径限制",
        "metrics": {
            "return_60d_pct": -4.18,
            "max_drawdown_60d_pct": -16.78,
        },
        "stock_market_context": {
            "exact_industry_index": {
                "status": "same_market_date",
                "component_breadth": {
                    "status": "available",
                    "advancers": 16,
                    "decliners": 34,
                    "unchanged": 0,
                },
                "component_contribution": {
                    "status": "available",
                    "subject": {
                        "symbol": "000063.SZ",
                        "name": "中兴通讯",
                        "estimated_contribution_pp": -0.2359,
                    },
                },
            }
        },
    }

    missing = AgentService._validate_model_output(
        "行业估算合计贡献为-1.81个百分点。", evidence
    )
    complete = AgentService._validate_model_output(
        "中兴通讯对行业指数的估算贡献：\n"
        "- 当日估算贡献约-0.236个百分点；按权重快照静态估算，不是中证官方逐日归因。",
        evidence,
    )
    wrong_metric = AgentService._validate_model_output(
        "中兴通讯估算贡献约-0.236个百分点；按权重快照静态估算，不是中证官方逐日归因。"
        "60日收益为-16.78%。",
        evidence,
    )

    assert missing["passed"] is False
    assert "用户明确询问成分贡献时必须给出标的估算贡献和口径边界" in missing[
        "semantic_conflicts"
    ]
    assert complete["passed"] is True
    assert wrong_metric["passed"] is False
    assert "60日累计收益不能误用最大回撤数值" in wrong_metric[
        "unsupported_market_inferences"
    ]


def test_stock_guard_requires_and_repairs_requested_industry_counts():
    evidence = {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "display_name": "中兴通讯",
        "user_question": "请给出通信设备成分上涨、下跌、平盘家数",
        "stock_market_context": {
            "exact_industry_index": {
                "status": "same_market_date",
                "name": "通信设备",
                "market_date": "2026-07-20",
                "constituent_count": 50,
                "component_breadth": {
                    "status": "available",
                    "market_date": "2026-07-20",
                    "total_constituents": 50,
                    "advancers": 16,
                    "decliners": 34,
                    "unchanged": 0,
                    "advance_ratio": 0.32,
                    "decline_ratio": 0.68,
                    "advance_ratio_pct": 32.0,
                    "decline_ratio_pct": 68.0,
                    "median_pct_change": -3.3537,
                    "state": "普跌",
                },
            }
        },
    }
    answer = (
        "通信设备官方样本共50只，上涨16只（占32%），平盘0只。\n\n"
        "该横截面只描述同日同步性，不能证明中兴通讯下跌的原因。"
    )

    guard = AgentService._validate_model_output(answer, evidence)
    repaired = AgentService._repair_guard_failure(answer, evidence, guard)
    ratio_guard = AgentService._validate_model_output(
        "通信设备50只成分中，上涨16只（占32%）、"
        "下跌34只（占68%）、平盘0只。",
        evidence,
    )
    direction_ratio_guard = AgentService._validate_model_output(
        "通信设备50只成分中，上涨16只、下跌34只、平盘0只；"
        "固定分类为普跌，下跌方向占比达到68%。",
        evidence,
    )
    flexible_ratio_guard = AgentService._validate_model_output(
        "通信设备50只成分中，上涨16只、下跌34只、平盘0只；"
        "下跌方向占有效样本68%，即68%成分下跌。",
        evidence,
    )
    component_stock_ratio_guard = AgentService._validate_model_output(
        "7月20日通信设备行业普跌（68%成分股下跌）。",
        evidence,
    )

    assert guard["passed"] is False
    assert "用户明确询问行业成分涨跌家数时必须给出上涨下跌平盘家数" in (
        guard["semantic_conflicts"]
    )
    assert repaired is not None
    repaired_answer, repaired_guard = repaired
    assert repaired_answer.startswith("通信设备官方样本共50只")
    assert "### 行业成分广度补充" in repaired_answer
    assert "上涨 16 只、下跌 34 只、平盘 0 只" in repaired_answer
    assert repaired_guard["passed"] is True
    assert ratio_guard["passed"] is True
    assert direction_ratio_guard["passed"] is True
    assert flexible_ratio_guard["passed"] is True
    assert "68%" not in component_stock_ratio_guard["unsupported_numbers"]


def test_stock_contribution_guard_repair_preserves_model_answer_and_appends_evidence(
    tmp_path: Path, settings, monkeypatch
):
    guarded_settings = replace(
        settings,
        database_path=tmp_path / "contribution-repair.db",
        workspace_root=tmp_path / "workspaces-contribution-repair",
        hermes_enabled=True,
    )
    database = Database(
        guarded_settings.database_path,
        guarded_settings.workspace_root,
    )
    database.initialize()
    user = database.create_user("Contribution Repair User")
    service = AgentService(database, guarded_settings)
    model_answer = (
        "结论：7月20日中兴通讯的跌幅明显大于通信设备指数，"
        "行业同步走弱只能说明同向性，不能单独证明个股下跌原因。\n\n"
        "同日通信设备指数下跌1.42%，50只成分中16只上涨、34只下跌，"
        "固定分类为普跌。这个横截面支持行业承压，但公司自身公告、交易结构"
        "与其他事件仍需分开核验。"
    )
    monkeypatch.setattr(
        service,
        "_execute_hermes",
        lambda **kwargs: (model_answer, {"model": "fake"}),
    )
    evidence = {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "display_name": "中兴通讯",
        "user_question": "中兴通讯7月20日对通信设备指数贡献多大，口径限制是什么？",
        "stock_market_context": {
            "exact_industry_index": {
                "status": "same_market_date",
                "name": "通信设备",
                "market_date": "2026-07-20",
                "return_1d_pct": -1.42,
                "constituent_count": 50,
                "subject_weight_pct": 3.741,
                "weights_as_of": "2026-06-30",
                "component_breadth": {
                    "status": "available",
                    "total_constituents": 50,
                    "advancers": 16,
                    "decliners": 34,
                    "unchanged": 0,
                    "state": "普跌",
                },
                "component_contribution": {
                    "status": "available",
                    "market_date": "2026-07-20",
                    "weights_as_of": "2026-06-30",
                    "estimated_total_contribution_pp": -1.8077,
                    "official_index_return_pct": -1.42,
                    "reconciliation_gap_pp": 0.3877,
                    "boundary": (
                        "贡献度按官方权重文件与目标日复权涨跌幅静态相乘估算，"
                        "不是中证官方逐日归因；权重漂移、公司行动和样本调整会形成对账差。"
                    ),
                    "subject": {
                        "symbol": "000063.SZ",
                        "name": "中兴通讯",
                        "market_date": "2026-07-20",
                        "weight_pct": 3.741,
                        "pct_change": -6.3056,
                        "estimated_contribution_pp": -0.2359,
                    },
                },
            }
        },
    }

    run = service.run(
        user=user,
        intent="stock_research",
        message=evidence["user_question"],
        evidence=evidence,
        model_tier="research",
        execute_agent=True,
    )

    assert run["status"] == "completed"
    assert run["answer"].startswith("结论：7月20日中兴通讯的跌幅明显大于")
    assert "行业同步走弱只能说明同向性" in run["answer"]
    assert "### 成分贡献口径补充" in run["answer"]
    assert "静态估算贡献 -0.24 个百分点" in run["answer"]
    assert "权重 3.74%" in run["answer"]
    assert "权重日期 2026-06-30" in run["answer"]
    assert "可用成分静态估算合计 -1.81 个百分点" in run["answer"]
    assert "对账差 0.39 个百分点" in run["answer"]
    assert "不是中证官方逐日归因" in run["answer"]
    assert run["usage"]["output_guard"]["repair"]["method"] == (
        "append_stock_component_contribution_v1"
    )
    assert run["usage"]["output_guard"]["passed"] is True
    run_dir = Path(run["workspace_path"]) / "runs" / run["id"]
    assert (run_dir / "answer.rejected.md").is_file()
    assert (run_dir / "answer.repaired.md").is_file()

    mixed_answer = (
        model_answer
        + "\n无证据传闻称当日资金规模为9999亿元，这一行应被删除。"
    )
    mixed_guard = AgentService._validate_model_output(
        mixed_answer,
        evidence,
    )
    mixed_repaired = AgentService._repair_guard_failure(
        mixed_answer,
        evidence,
        mixed_guard,
    )
    assert mixed_guard["unsupported_numbers"] == ["9999"]
    assert "用户明确询问成分贡献时必须给出标的估算贡献和口径边界" in (
        mixed_guard["semantic_conflicts"]
    )
    assert mixed_repaired is not None
    assert "9999" not in mixed_repaired[0]
    assert "静态估算贡献 -0.2359 个百分点" in mixed_repaired[0]
    assert mixed_repaired[1]["passed"] is True


def test_stock_guard_does_not_treat_explicit_date_as_current_quote_claim():
    evidence = {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "user_question": "中兴通讯7月20日为什么跌",
        "current_quote": {
            "market_timestamp": "2026-07-21T16:14:00+08:00",
            "price": 34.88,
            "pct_change": 3.41,
        },
        "provenance": {
            "market_timestamp": "2026-07-21T15:00:00+08:00"
        },
        "stock_market_context": {
            "analysis_target": {
                "market_date": "2026-07-20",
                "basis": "explicit_question_date",
            },
            "stock_target": {
                "status": "same_market_date",
                "market_date": "2026-07-20",
                "close": 33.73,
                "return_1d_pct": -6.31,
            },
        },
    }

    guard = AgentService._validate_model_output(
        "当前能确认的是：7月20日收盘33.73元，当日下跌6.31%。",
        evidence,
    )

    assert guard["passed"] is True


def test_peer_ranking_guard_does_not_block_index_contribution_ordering():
    evidence = {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "peer_comparison": {
            "operating_comparison": {
                "subject": {"name": "中兴通讯"},
                "peers": [{"name": "烽火通信"}],
            }
        },
        "stock_market_context": {
            "exact_industry_index": {
                "component_contribution": {
                    "status": "available",
                    "top_positive": [{"name": "新易盛"}],
                    "top_negative": [{"name": "光迅科技"}],
                }
            }
        },
    }

    guard = AgentService._validate_model_output(
        "中兴通讯所在指数的正向贡献最大成分是新易盛，负向贡献最大成分是光迅科技。",
        evidence,
    )

    assert guard["passed"] is True


def test_model_language_cleanup_hides_stock_market_context_fields():
    cleaned = AgentService._clean_user_facing_model_language(
        "行业匹配：证据中 `exact_industry_match_available=false`，"
        "且 `same_date_as_target=false`，置信度 low_to_medium。"
    )

    assert "exact_industry_match_available" not in cleaned
    assert "same_date_as_target" not in cleaned
    assert "未取得与公司行业精确匹配的同日板块序列" in cleaned
    assert "与目标交易日不一致" in cleaned
    assert "low_to_medium" not in cleaned
    assert "较低至中等" in cleaned


def test_model_language_cleanup_neutralizes_misleading_systemic_heading():
    cleaned = AgentService._clean_user_facing_model_language(
        '**二、能确认的"非系统性拖累"**\n\n全市场系统性拖累不能确认。'
    )

    assert '**二、市场与行业对照**' in cleaned
    assert '能确认的"非系统性拖累"' not in cleaned


def test_model_language_cleanup_softens_absolute_causality_wording():
    cleaned = AgentService._clean_user_facing_model_language(
        "全市场上涨家数占优，不存在系统性拖累。"
        '这被称为"当前最可能的市场解释"。'
    )

    assert "不存在系统性拖累" not in cleaned
    assert "当日事实不支持全市场普跌解释" in cleaned
    assert "当前最可能的市场解释" not in cleaned
    assert "市场资讯反复提及的解释" in cleaned


def test_model_language_cleanup_converts_markdown_tables_to_readable_bullets():
    cleaned = AgentService._clean_user_facing_model_language(
        "| 项目 | 数据 | 时间锚点 |\n"
        "|------|------|----------|\n"
        "| 当前报价 | 34.88元，+3.41% | 7月21日16:14 |\n"
        "| 最近完整日线 | 33.73元，-6.31% | 7月20日 |"
    )

    assert "|------" not in cleaned
    assert "- 项目：当前报价；数据：34.88元，+3.41%；时间锚点：7月21日16:14" in cleaned
    assert "- 项目：最近完整日线；数据：33.73元，-6.31%；时间锚点：7月20日" in cleaned


def test_stock_move_preview_is_focused_and_keeps_both_price_time_anchors():
    evidence = {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "display_name": "中兴通讯",
        "user_question": "中兴通讯今天为什么跌？",
        "metrics": {
            "latest_close": 33.73,
            "return_1d_pct": -6.31,
            "return_20d_pct": -14.46,
            "return_60d_pct": -4.18,
            "trend_state": "趋势分化",
            "volatility_20d_annualized_pct": 69.14,
            "max_drawdown_60d_pct": -16.78,
        },
        "provenance": {"market_timestamp": "2026-07-20T01:30:00+00:00"},
        "current_quote": {
            "price": 34.88,
            "pct_change": 3.41,
            "currency": "CNY",
            "market_timestamp": "2026-07-21T16:14:42+08:00",
        },
        "research_frame": {"missing_information": []},
        "stock_market_context": {
            "market_state": {"summary": "同日2个指数中1涨1跌。"},
            "indices": [
                {
                    "name": "上证综指",
                    "comparison_status": "same_market_date",
                    "return_1d_pct": 0.85,
                },
                {
                    "name": "深证成指",
                    "comparison_status": "same_market_date",
                    "return_1d_pct": -0.71,
                },
            ],
            "market_breadth": {"same_date_as_target": False},
            "company_industry": "通信设备",
            "exact_industry_match_available": False,
        },
        "a_share_information": {
            "announcements": [
                {"published_at": "2026-07-20", "title": "回购结果公告"}
            ],
            "news": [
                {
                    "published_at": "2026-07-21T21:56:00+08:00",
                    "title": "H股减持媒体报道",
                }
            ],
            "sentiment": {
                "band": "中性或混合",
                "sample_size": 24,
                "confidence": "low_to_medium",
            },
        },
    }

    answer = AgentService._render_preview(evidence)

    assert "当前报价（2026-07-21 16:14）：34.88 CNY，上涨 3.41%" in answer
    assert "最近完整日线（2026-07-20）：收盘 33.73" in answer
    assert "同日代表性指数：上证综指 0.85%；深证成指 -0.71%" in answer
    assert "同日全市场涨跌家数尚未取得" in answer
    assert "low_to_medium" not in answer
    assert len(answer) < 1200


def test_stock_move_preview_explains_partial_industry_component_coverage():
    evidence = {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "display_name": "中兴通讯",
        "user_question": "中兴通讯7月20日为什么跌？",
        "metrics": {"latest_close": 33.73, "return_1d_pct": -6.31},
        "provenance": {"market_timestamp": "2026-07-20T15:00:00+08:00"},
        "research_frame": {"missing_information": []},
        "stock_market_context": {
            "analysis_target": {
                "basis": "explicit_question_date",
                "market_date": "2026-07-20",
            },
            "stock_target": {
                "status": "same_market_date",
                "market_date": "2026-07-20",
                "close": 33.73,
                "return_1d_pct": -6.31,
            },
            "market_state": {"summary": "同日代表性指数方向分化。"},
            "indices": [],
            "market_breadth": {"same_date_as_target": False},
            "exact_industry_index": {
                "status": "same_market_date",
                "name": "通信设备",
                "return_1d_pct": -1.42,
                "stock_return_1d_pct": -6.31,
                "stock_minus_industry_pct": -4.89,
                "constituent_count": 50,
                "industry_mapping": {"match_type": "exact_name"},
                "component_breadth": {
                    "status": "partial",
                    "available_returns": 49,
                    "total_constituents": 50,
                    "advancers": 16,
                    "decliners": 33,
                    "unchanged": 0,
                    "coverage": {
                        "constituents": 50,
                        "available_returns": 49,
                        "fallback_unadjusted_returns": 1,
                    },
                    "failures": [
                        {
                            "symbol": "920185.BJ",
                            "name": "贝特瑞",
                            "reason": "两个公开行情源均未返回目标日可比日线",
                        }
                    ],
                },
            },
        },
        "a_share_information": {},
    }

    answer = AgentService._render_preview(evidence)

    assert "有效 49 / 50 只" in answer
    assert "上涨 16 只、下跌 33 只、平盘 0 只" in answer
    assert "不能称为完整行业普涨或普跌" in answer
    assert "贝特瑞（两个公开行情源均未返回目标日可比日线）" in answer
    assert "1 只使用新浪未复权日线降级" in answer


def test_model_language_cleanup_hides_internal_fields_and_repairs_list_numbers():
    cleaned = AgentService._clean_user_facing_model_language(
        "当前 evidence_readiness = ready，7个模块均处于 ready 状态。\n"
        "条件来自 `conditional_outlook`，`optional_gaps` 为空，"
        "可靠性为 `not_directionally_consistent`。\n\n"
        "## 待补证\n1. 毛利原因\n3. 现金流原因\n4. 股东变化"
    )

    assert "evidence_readiness" not in cleaned
    assert "conditional_outlook" not in cleaned
    assert "optional_gaps" not in cleaned
    assert "not_directionally_consistent" not in cleaned
    assert "2. 现金流原因" in cleaned
    assert "3. 股东变化" in cleaned


def test_stock_guard_rejects_reversed_scenario_failure_direction():
    evidence = {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "price_levels": {"recent_20d_low": 32.39, "recent_20d_high": 43.0},
    }
    answer = (
        "### 失效条件\n"
        "- 下行风险失效：收盘跌破32.39，且20日收益继续恶化。\n"
        "- 区间震荡失效：价格仍在32.39至43.0之间运行。"
    )

    guard = AgentService._validate_model_output(answer, evidence)

    assert guard["passed"] is False
    assert "个股情景触发与失效方向必须与确定性条件一致" in guard[
        "unsupported_market_inferences"
    ]


def test_model_language_cleanup_translates_confidence_status():
    cleaned = AgentService._clean_user_facing_model_language(
        "当前判断置信度 low，另一项置信度 medium。"
    )

    assert cleaned == "当前判断置信度较低，另一项置信度中等。"


def test_market_guard_falls_back_when_metric_conflicts_dominate(
    tmp_path: Path, settings, monkeypatch
):
    guarded_settings = replace(
        settings,
        database_path=tmp_path / "market-metric-consistency.db",
        workspace_root=tmp_path / "workspaces-market-metric-consistency",
        hermes_enabled=True,
    )
    database = Database(guarded_settings.database_path, guarded_settings.workspace_root)
    database.initialize()
    user = database.create_user("Market Metric Consistency User")
    service = AgentService(database, guarded_settings)
    answer = (
        "当前可确认的是四个代表性指数均收跌。\n"
        "标普500低于MA20、高于MA60，但两条均线均未被跌破。\n"
        "罗素2000已经在60日线下方。\n"
        "标普500的20日年化波动率为10.37%，是四个指数中最低。\n"
        "市场资讯仍需作为事件线索单独核对，不能证明唯一因果。"
    )
    monkeypatch.setattr(
        service,
        "_execute_hermes",
        lambda **kwargs: (answer, {"model": "fake"}),
    )
    evidence = {
        "type": "market_brief",
        "user_question": "这段判断的反方证据和失效条件是什么？",
        "question_focus": {"key": "market_risk"},
        "indices": [
            {
                "symbol": "^GSPC",
                "name": "标普500",
                "status": "available",
                "metrics": {
                    "latest_close": 7443.0,
                    "ma20": 7476.0,
                    "ma60": 7422.0,
                    "volatility_20d_annualized_pct": 10.37,
                },
            },
            {
                "symbol": "^DJI",
                "name": "道琼斯工业指数",
                "status": "available",
                "metrics": {"volatility_20d_annualized_pct": 7.78},
            },
            {
                "symbol": "^IXIC",
                "name": "纳斯达克综合",
                "status": "available",
                "metrics": {"volatility_20d_annualized_pct": 18.65},
            },
            {
                "symbol": "^RUT",
                "name": "罗素2000",
                "status": "available",
                "metrics": {
                    "latest_close": 2942.0,
                    "ma20": 2986.0,
                    "ma60": 2902.0,
                    "volatility_20d_annualized_pct": 10.28,
                },
            },
        ],
        "market_drivers": {
            "market_key": "us",
            "items": [{"title": "US stocks close lower as chip pressure persists"}],
        },
    }

    run = service.run(
        user=user,
        intent="market_brief",
        message="这段判断的反方证据和失效条件是什么？",
        evidence=evidence,
        model_tier="economy",
        execute_agent=True,
    )

    assert run["status"] == "guarded"
    assert "代表性指数可用 4/4 个" in run["answer"]
    assert "失效条件：" in run["answer"]
    assert "两条均线均未被跌破" not in run["answer"]
    assert "罗素2000已经在60日线下方" not in run["answer"]
    assert "四个指数中最低" not in run["answer"]
    assert set(run["usage"]["output_guard"]["unsupported_market_inferences"]) == {
        "指数波动率最高最低表述必须与当前证据排序一致",
        "均线是否跌破的表述必须与最新收盘和均线位置一致",
        "用户明确询问失效条件时回答必须包含失效条件",
    }


def test_model_language_cleanup_translates_market_driver_field_phrase():
    cleaned = AgentService._clean_user_facing_model_language(
        "当前证据中 market_drivers 的资讯项为空。"
    )

    assert cleaned == "当前没有与本问题直接相关的市场资讯。"


def test_market_guard_rejects_wrong_index_count_ma5_and_wave_label():
    evidence = {
        "type": "market_brief",
        "indices": [
            {
                "status": "available",
                "metrics": {"ma20": 3989.5, "return_5d_pct": -2.59},
            },
            {
                "status": "available",
                "metrics": {"ma20": 15186.8, "return_5d_pct": -4.43},
            },
        ],
    }
    answer = (
        "5个代表性指数全部上涨。\n"
        "如果跌破5日均线，B浪反弹将失效。"
    )

    guard = AgentService._validate_model_output(answer, evidence)

    assert guard["passed"] is False
    assert set(guard["unsupported_market_inferences"]) == {
        "代表性指数数量与当前问题证据不一致",
        "当前证据没有MA5或5日均线",
        "当前证据不支持A浪B浪C浪等浪型判断",
    }


def test_numeric_guard_uses_structural_numbers_only_from_evidence_keys():
    evidence = {
        "type": "market_brief",
        "indices": [
            {"metrics": {"return_5d_pct": -4.43, "ma20": 15186.8}}
        ],
    }

    valid = AgentService._validate_model_output(
        "近5日累计下跌4.43%，仍低于MA20。",
        evidence,
    )
    invented_ratio = AgentService._validate_model_output(
        "两项风险的强度比为1.9倍。",
        evidence,
    )

    assert valid["passed"] is True
    assert invented_ratio["passed"] is False
    assert "1.9" in invented_ratio["unsupported_numbers"]


def test_numeric_guard_accepts_market_ma_distance_derived_from_evidence():
    evidence = {
        "type": "market_brief",
        "indices": [
            {
                "symbol": "^DJI",
                "metrics": {
                    "latest_close": 52208.0,
                    "ma20": 52344.0,
                    "ma60": 50981.0,
                },
            }
        ],
    }

    valid = AgentService._validate_model_output(
        "道指低于MA20约0.3%，高于MA60约2.4%。", evidence
    )
    invented = AgentService._validate_model_output(
        "道指高于MA60约9.9%。", evidence
    )

    assert valid["passed"] is True
    assert invented["passed"] is False
    assert "9.9%" in invented["unsupported_numbers"]


def test_market_downtrend_guard_allows_explicit_negation():
    evidence = {
        "type": "market_brief",
        "indices": [{"metrics": {"trend_state": "中期偏弱"}}],
    }

    safe = AgentService._validate_model_output(
        "中期偏弱不等于已确认下行趋势。",
        evidence,
    )
    overclaim = AgentService._validate_model_output(
        "当前趋势依然向下。",
        evidence,
    )

    assert safe["passed"] is True
    assert overclaim["passed"] is False
    assert overclaim["unsupported_market_inferences"] == [
        "中期偏弱不能直接改写为已确认的下行趋势"
    ]


def test_market_risk_prompt_precomputes_ma_distance_and_volatility_ratio():
    evidence = {
        "type": "market_brief",
        "question_focus": {"key": "market_risk"},
        "indices": [
            {
                "name": "上证综指",
                "group": "china",
                "metrics": {
                    "latest_close": 3864.0,
                    "ma20": 3989.0,
                    "ma60": 4067.0,
                    "volatility_20d_annualized_pct": 22.42,
                },
            },
            {
                "name": "深证成指",
                "group": "china",
                "metrics": {
                    "latest_close": 14264.0,
                    "ma20": 15187.0,
                    "ma60": 15397.0,
                    "volatility_20d_annualized_pct": 41.82,
                },
            },
        ],
        "market_drivers": {"market_key": "china", "items": []},
    }

    compact = AgentService._compact_market_brief_evidence(evidence)

    assert compact["indices"][0]["metrics"]["ma20_gap_points"] == 125
    assert compact["indices"][0]["metrics"]["distance_to_ma20_pct"] == -3.1
    assert compact["indices"][1]["metrics"]["ma20_gap_points"] == 923
    assert compact["indices"][1]["metrics"]["distance_to_ma60_pct"] == -7.4
    comparison = compact["relative_comparisons"]["volatility_20d_annualized"]
    assert comparison["numerator_name"] == "深证成指"
    assert comparison["denominator_name"] == "上证综指"
    assert comparison["ratio"] == 1.9
    assert "不代表高低等级" in comparison["interpretation"]


def test_shareholder_guard_rejects_absorption_and_northbound_overclaims():
    evidence = {
        "type": "shareholder_structure",
        "holder_count_change_pct": -9.452498,
        "holder_count_statement": "股东户数下降只能作为持股集中度线索。",
        "holder_count_streak_direction": "decrease",
        "holder_count_streak_count": 3,
        "top10_historical_comparison_available": False,
        "top_holders": [
            {
                "name": "香港中央结算代理人有限公司",
                "holding_ratio_pct": 15.73,
            }
        ],
    }

    absorption = AgentService._validate_model_output(
        "股东户数下降9.45%，说明机构吸筹。",
        evidence,
    )
    northbound = AgentService._validate_model_output(
        "香港中央结算代理人有限公司就是北向资金。",
        evidence,
    )
    channel_label = AgentService._validate_model_output(
        "香港中央结算有限公司（北向 A 股通道）持股1.14%。",
        evidence,
    )
    land_connect_label = AgentService._validate_model_output(
        "香港中央结算有限公司（A 股陆股通通道）持股1.14%。",
        evidence,
    )
    generic_channel_label = AgentService._validate_model_output(
        "香港中央结算有限公司（A 股通道）持股1.14%。",
        evidence,
    )
    etf_motive = AgentService._validate_model_output(
        "两只ETF减持、新进通信ETF，构成指数被动减仓和行业主题主动建仓。",
        evidence,
    )
    filing_deadline = AgentService._validate_model_output(
        "等待2026年中报更新，通常在8月底前披露。",
        evidence,
    )
    holder_count_deadline = AgentService._validate_model_output(
        "等待下一期股东户数（约7—10天后）。",
        evidence,
    )
    wrong_streak = AgentService._validate_model_output(
        "股东户数连续4次披露下降。",
        evidence,
    )
    unsupported_top10_history = AgentService._validate_model_output(
        "十大股东前十名合计持股与之前各期基本持平。",
        evidence,
    )
    inferred_controller = AgentService._validate_model_output(
        "**控股股东**：中兴新通讯有限公司持股20.09%。",
        evidence,
    )
    etf_trading_label = AgentService._validate_model_output(
        "两只公募ETF均有显著调仓。",
        evidence,
    )
    foreign_intent = AgentService._validate_model_output(
        "香港中央结算有限公司持股变化可综合判断外资配置意愿。",
        evidence,
    )

    assert absorption["passed"] is False
    assert "股东户数下降不能直接写成机构或主力吸筹" in absorption[
        "unsupported_market_inferences"
    ]
    assert northbound["passed"] is False
    assert "香港中央结算代理人有限公司不能自动等同北向资金" in northbound[
        "unsupported_market_inferences"
    ]
    assert channel_label["passed"] is False
    assert "香港中央结算有限公司不能在缺少身份口径时直接标注为北向通道" in channel_label[
        "unsupported_market_inferences"
    ]
    assert land_connect_label["passed"] is False
    assert "香港中央结算有限公司不能在缺少身份口径时直接标注为北向通道" in land_connect_label[
        "unsupported_market_inferences"
    ]
    assert generic_channel_label["passed"] is False
    assert "香港中央结算有限公司不能在缺少身份口径时直接标注为北向通道" in generic_channel_label[
        "unsupported_market_inferences"
    ]
    assert etf_motive["passed"] is False
    assert "十大股东名单变化不能直接归因为ETF主动或被动调仓" in etf_motive[
        "unsupported_market_inferences"
    ]
    assert filing_deadline["passed"] is False
    assert "缺少披露日历证据时不能补写下一份报告的预计截止时间" in filing_deadline[
        "unsupported_market_inferences"
    ]
    assert holder_count_deadline["passed"] is False
    assert "缺少固定披露频率证据时不能补写下一次股东户数的预计天数" in holder_count_deadline[
        "unsupported_market_inferences"
    ]
    assert wrong_streak["passed"] is False
    assert "股东户数连续变化次数或方向与确定性证据不一致" in wrong_streak[
        "unsupported_market_inferences"
    ]
    assert unsupported_top10_history["passed"] is False
    assert "缺少历史十大股东合计序列时不能声称前十持股跨期持平或变化" in unsupported_top10_history[
        "unsupported_market_inferences"
    ]
    assert inferred_controller["passed"] is False
    assert "股东名单本身不能补写控股国资国家队等身份标签" in inferred_controller[
        "unsupported_market_inferences"
    ]
    assert etf_trading_label["passed"] is False
    assert "十大股东名单变化不能直接归因为ETF主动或被动调仓" in etf_trading_label[
        "unsupported_market_inferences"
    ]
    assert foreign_intent["passed"] is False
    assert "香港中央结算持股不能直接证明外资配置意愿" in foreign_intent[
        "unsupported_market_inferences"
    ]


def test_shareholder_guard_accepts_bounded_concentration_clue():
    evidence = {
        "type": "shareholder_structure",
        "holder_count_change_pct": -9.452498,
        "holder_count_streak_direction": "decrease",
        "holder_count_streak_count": 3,
        "holder_count_as_of": "2026-07-10",
        "top10_report_date": "2026-03-31",
    }

    guard = AgentService._validate_model_output(
        "截至2026-07-10，股东户数较上次下降9.45%，这是持股集中度线索；"
        "十大股东数据对应2026-03-31报告期，不是实时持仓。",
        evidence,
    )

    assert guard["passed"] is True

    explicit_boundary = AgentService._validate_model_output(
        "股东户数下降9.45%，但不能证明机构吸筹。",
        evidence,
    )
    assert explicit_boundary["passed"] is True


def test_shareholder_streak_guard_skips_migration_snapshot_without_streak_fields():
    evidence = {
        "type": "shareholder_structure",
        "holder_count_change_pct": -9.452498,
        "recent_pattern": "最近3次披露的股东户数连续下降。",
    }

    guard = AgentService._validate_model_output(
        "股东户数连续3次披露下降。",
        evidence,
    )

    assert guard["passed"] is True


def test_guard_repair_removes_empty_shareholder_heading_and_separator():
    lines = [
        "## 标题",
        "",
        "---",
        "",
        "**股东户数变化**",
        "",
        "**十大股东结构——值得核对的线索**",
        "",
        "当前最近可用报告期为2026-03-31。",
    ]

    cleaned = AgentService._drop_empty_answer_sections(lines)

    assert "---" not in cleaned
    assert "**股东户数变化**" not in cleaned
    assert "**十大股东结构——值得核对的线索**" in cleaned


def test_private_operational_line_can_be_removed_without_losing_answer():
    evidence = {
        "type": "shareholder_structure",
        "holder_count_as_of": "2026-07-10",
        "holder_count": 575136,
        "holder_count_change_pct": -9.452498,
        "top10_report_date": "2026-03-31",
        "review_points": ["等待下一份定期报告更新十大股东。"],
    }
    answer = (
        "截至2026-07-10，股东户数为575136户，较上次下降9.45%。\n"
        "当前最近可用十大股东报告期为2026-03-31。\n"
        "当前数据库已尝试获取2026-06-30数据但尚未成功。\n"
        "下一步等待下一份定期报告更新十大股东。"
    )

    guard = AgentService._validate_model_output(answer, evidence)
    repaired = AgentService._repair_guard_failure(answer, evidence, guard)

    assert guard["passed"] is False
    assert guard["private_operational_patterns"]
    assert repaired is not None
    repaired_answer, repaired_guard = repaired
    assert "数据库" not in repaired_answer
    assert "575136" in repaired_answer
    assert "2026-03-31" in repaired_answer
    assert repaired_guard["passed"] is True


def test_research_action_prompt_keeps_top_actions_per_status():
    actions = [
        {
            "key": f"triggered-{index}",
            "status": "triggered",
            "title": f"触发{index}",
            "current_evidence": "证据",
            "next_step": "复核",
        }
        for index in range(4)
    ] + [
        {
            "key": f"pending-{index}",
            "status": "pending_data",
            "title": f"补证{index}",
            "current_evidence": "缺口",
            "next_step": "补证",
        }
        for index in range(3)
    ] + [
        {
            "key": f"watching-{index}",
            "status": "watching",
            "title": f"观察{index}",
            "current_evidence": "未触发",
            "next_step": "观察",
        }
        for index in range(2)
    ]
    evidence = {
        "type": "research_actions",
        "summary": {"symbols": 1},
        "items": [
            {
                "symbol": "000063.SZ",
                "name": "中兴通讯",
                "actions": actions,
            }
        ],
    }

    compact = AgentService._compact_research_actions_evidence(evidence)

    selected = compact["items"][0]["actions"]
    assert sum(item["status"] == "triggered" for item in selected) == 3
    assert sum(item["status"] == "pending_data" for item in selected) == 2
    assert sum(item["status"] == "watching" for item in selected) == 1


def test_streaming_bridge_publishes_only_guarded_cumulative_sentences(
    tmp_path: Path, settings, monkeypatch
):
    bin_dir = tmp_path / "hermes" / "venv" / "bin"
    bin_dir.mkdir(parents=True)
    hermes_bin = bin_dir / "hermes"
    python_bin = bin_dir / "python"
    hermes_bin.touch()
    python_bin.touch()
    guarded_settings = replace(
        settings,
        database_path=tmp_path / "stream-protocol.db",
        workspace_root=tmp_path / "stream-protocol-workspaces",
        hermes_bin=hermes_bin,
        hermes_enabled=True,
    )
    database = Database(guarded_settings.database_path, guarded_settings.workspace_root)
    database.initialize()
    service = AgentService(database, guarded_settings)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "prompt.md").write_text("测试流式协议", encoding="utf-8")
    lines = [
        json.dumps(
            {
                "type": "delta",
                "text": "上证综指当日下跌1.23%。目标价9999",
            },
            ensure_ascii=False,
        )
        + "\n",
        json.dumps(
            {
                "type": "delta",
                "text": "元。\n现有证据不能确认唯一原因。\n",
            },
            ensure_ascii=False,
        )
        + "\n",
        json.dumps(
            {
                "type": "final",
                "answer": "上证综指当日下跌1.23%。目标价9999元。",
                "usage": {"model": "fake-stream"},
            },
            ensure_ascii=False,
        )
        + "\n",
    ]
    monkeypatch.setattr(
        "app.services.agent.subprocess.Popen",
        lambda *args, **kwargs: _FakeStreamingProcess(lines),
    )
    updates = []

    answer, usage = service._execute_hermes_streaming(
        model_tier="economy",
        run_dir=run_dir,
        user_workspace=tmp_path,
        evidence={
            "type": "market_brief",
            "indices": [
                {"name": "上证综指", "metrics": {"return_1d_pct": -1.23}}
            ],
        },
        trusted_context=None,
        stream_callback=updates.append,
    )

    assert answer.endswith("目标价9999元。")
    assert [item["draft"] for item in updates] == [
        "上证综指当日下跌1.23%。",
        "上证综指当日下跌1.23%。现有证据不能确认唯一原因。",
    ]
    assert all("9999" not in item["draft"] for item in updates)
    assert usage["streaming"]["raw_delta_events"] == 2
    assert usage["streaming"]["visible_events"] == 2
    assert usage["streaming"]["withheld_segments"] == 1


def test_streaming_bridge_defers_whole_answer_completeness_checks(
    tmp_path: Path, settings, monkeypatch
):
    bin_dir = tmp_path / "hermes" / "venv" / "bin"
    bin_dir.mkdir(parents=True)
    hermes_bin = bin_dir / "hermes"
    python_bin = bin_dir / "python"
    hermes_bin.touch()
    python_bin.touch()
    guarded_settings = replace(
        settings,
        database_path=tmp_path / "stream-completeness.db",
        workspace_root=tmp_path / "stream-completeness-workspaces",
        hermes_bin=hermes_bin,
        hermes_enabled=True,
    )
    database = Database(guarded_settings.database_path, guarded_settings.workspace_root)
    database.initialize()
    service = AgentService(database, guarded_settings)
    run_dir = tmp_path / "run-completeness"
    run_dir.mkdir()
    (run_dir / "prompt.md").write_text("测试完整回答要求", encoding="utf-8")
    lines = [
        json.dumps(
            {"type": "delta", "text": "当前反弹尚未扭转短期回落格局。"},
            ensure_ascii=False,
        )
        + "\n",
        json.dumps(
            {
                "type": "delta",
                "text": "失效条件：后续事实若与当前证据冲突，就需要重新评估。",
            },
            ensure_ascii=False,
        )
        + "\n",
        json.dumps(
            {
                "type": "final",
                "answer": (
                    "当前反弹尚未扭转短期回落格局。"
                    "失效条件：后续事实若与当前证据冲突，就需要重新评估。"
                ),
                "usage": {"model": "fake-stream"},
            },
            ensure_ascii=False,
        )
        + "\n",
    ]
    monkeypatch.setattr(
        "app.services.agent.subprocess.Popen",
        lambda *args, **kwargs: _FakeStreamingProcess(lines),
    )
    updates = []

    _, usage = service._execute_hermes_streaming(
        model_tier="economy",
        run_dir=run_dir,
        user_workspace=tmp_path,
        evidence={
            "type": "market_brief",
            "user_question": "这次回落的反方证据和失效条件是什么？",
            "indices": [],
        },
        trusted_context=None,
        stream_callback=updates.append,
    )

    assert [item["draft"] for item in updates] == [
        "当前反弹尚未扭转短期回落格局。",
        "当前反弹尚未扭转短期回落格局。失效条件：后续事实若与当前证据冲突，就需要重新评估。",
    ]
    assert usage["streaming"]["mode"] == "guarded_cumulative_stream_v3"
    assert usage["streaming"]["visible_events"] == 2
    assert usage["streaming"]["withheld_segments"] == 0


def test_streaming_bridge_defers_requested_industry_counts_and_contribution(
    tmp_path: Path, settings, monkeypatch
):
    bin_dir = tmp_path / "hermes" / "venv" / "bin"
    bin_dir.mkdir(parents=True)
    hermes_bin = bin_dir / "hermes"
    python_bin = bin_dir / "python"
    hermes_bin.touch()
    python_bin.touch()
    guarded_settings = replace(
        settings,
        database_path=tmp_path / "stream-stock-completeness.db",
        workspace_root=tmp_path / "stream-stock-completeness-workspaces",
        hermes_bin=hermes_bin,
        hermes_enabled=True,
    )
    database = Database(
        guarded_settings.database_path,
        guarded_settings.workspace_root,
    )
    database.initialize()
    service = AgentService(database, guarded_settings)
    run_dir = tmp_path / "run-stock-completeness"
    run_dir.mkdir()
    (run_dir / "prompt.md").write_text("测试个股必答字段流式显示", encoding="utf-8")
    lines = [
        json.dumps(
            {
                "type": "delta",
                "text": "7月20日中兴通讯收盘33.73元，下跌6.31%。",
            },
            ensure_ascii=False,
        )
        + "\n",
        json.dumps(
            {
                "type": "delta",
                "text": "上证上涨，因此没有系统性拖累。",
            },
            ensure_ascii=False,
        )
        + "\n",
        json.dumps(
            {
                "type": "delta",
                "text": "行业成分上涨16只、下跌34只（占68%）、平盘0只。",
            },
            ensure_ascii=False,
        )
        + "\n",
        json.dumps(
            {
                "type": "delta",
                "text": (
                    "中兴静态估算贡献-0.2359个百分点，"
                    "按权重快照估算，不是中证官方逐日归因。"
                ),
            },
            ensure_ascii=False,
        )
        + "\n",
        json.dumps(
            {
                "type": "final",
                "answer": (
                    "7月20日中兴通讯收盘33.73元，下跌6.31%。"
                    "上证上涨，因此没有系统性拖累。"
                    "行业成分上涨16只、下跌34只（占68%）、平盘0只。"
                    "中兴静态估算贡献-0.2359个百分点，"
                    "按权重快照估算，不是中证官方逐日归因。"
                ),
                "usage": {"model": "fake-stream"},
            },
            ensure_ascii=False,
        )
        + "\n",
    ]
    monkeypatch.setattr(
        "app.services.agent.subprocess.Popen",
        lambda *args, **kwargs: _FakeStreamingProcess(lines),
    )
    updates = []
    evidence = {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "display_name": "中兴通讯",
        "user_question": (
            "请给出行业成分上涨、下跌、平盘家数，并说明中兴贡献和口径限制"
        ),
        "stock_market_context": {
            "stock_target": {
                "market_date": "2026-07-20",
                "close": 33.73,
                "return_1d_pct": -6.31,
            },
            "market_breadth": {"same_date_as_target": False},
            "exact_industry_index": {
                "status": "same_market_date",
                "component_breadth": {
                    "status": "available",
                    "advancers": 16,
                    "decliners": 34,
                    "unchanged": 0,
                    "decline_ratio": 0.68,
                    "decline_ratio_pct": 68.0,
                },
                "component_contribution": {
                    "status": "available",
                    "subject": {
                        "name": "中兴通讯",
                        "estimated_contribution_pp": -0.2359,
                    },
                },
            },
        },
    }

    _, usage = service._execute_hermes_streaming(
        model_tier="economy",
        run_dir=run_dir,
        user_workspace=tmp_path,
        evidence=evidence,
        trusted_context=None,
        stream_callback=updates.append,
    )

    drafts = [item["draft"] for item in updates]
    assert drafts[0] == "7月20日中兴通讯收盘33.73元，下跌6.31%。"
    assert "上涨16只、下跌34只（占68%）、平盘0只" in drafts[-1]
    assert "静态估算贡献-0.2359个百分点" in drafts[-1]
    assert all("没有系统性拖累" not in draft for draft in drafts)
    assert usage["streaming"]["visible_events"] == 3
    assert usage["streaming"]["withheld_segments"] == 1


def test_streaming_bridge_waits_for_current_quote_then_keeps_growing(
    tmp_path: Path, settings, monkeypatch
):
    bin_dir = tmp_path / "hermes" / "venv" / "bin"
    bin_dir.mkdir(parents=True)
    hermes_bin = bin_dir / "hermes"
    python_bin = bin_dir / "python"
    hermes_bin.touch()
    python_bin.touch()
    guarded_settings = replace(
        settings,
        database_path=tmp_path / "stream-quote.db",
        workspace_root=tmp_path / "stream-quote-workspaces",
        hermes_bin=hermes_bin,
        hermes_enabled=True,
    )
    database = Database(guarded_settings.database_path, guarded_settings.workspace_root)
    database.initialize()
    service = AgentService(database, guarded_settings)
    run_dir = tmp_path / "run-quote"
    run_dir.mkdir()
    (run_dir / "prompt.md").write_text("测试当前报价优先流式显示", encoding="utf-8")
    lines = [
        json.dumps(
            {"type": "delta", "text": "最近完整日线下跌6.31%。"},
            ensure_ascii=False,
        )
        + "\n",
        json.dumps(
            {"type": "delta", "text": "最新报价34.88元，今日上涨3.41%。"},
            ensure_ascii=False,
        )
        + "\n",
        json.dumps(
            {"type": "delta", "text": "今天下跌6.31%。"},
            ensure_ascii=False,
        )
        + "\n",
        json.dumps(
            {"type": "delta", "text": "历史日线收盘33.73元。"},
            ensure_ascii=False,
        )
        + "\n",
        json.dumps(
            {
                "type": "final",
                "answer": (
                    "最近完整日线下跌6.31%。"
                    "最新报价34.88元，今日上涨3.41%。"
                    "今天下跌6.31%。"
                    "历史日线收盘33.73元。"
                ),
                "usage": {"model": "fake-stream"},
            },
            ensure_ascii=False,
        )
        + "\n",
    ]
    monkeypatch.setattr(
        "app.services.agent.subprocess.Popen",
        lambda *args, **kwargs: _FakeStreamingProcess(lines),
    )
    updates = []

    _, usage = service._execute_hermes_streaming(
        model_tier="economy",
        run_dir=run_dir,
        user_workspace=tmp_path,
        evidence={
            "type": "stock_research",
            "symbol": "000063.SZ",
            "user_question": "中兴通讯今天为什么跌？",
            "current_quote": {
                "market_timestamp": "2026-07-21T16:14:00+08:00",
                "price": 34.88,
                "pct_change": 3.41,
            },
            "provenance": {
                "market_timestamp": "2026-07-20T15:00:00+08:00"
            },
            "technical": {
                "latest_close": 33.73,
                "return_1d_pct": -6.31,
            },
        },
        trusted_context=None,
        stream_callback=updates.append,
    )

    assert [item["draft"] for item in updates] == [
        "最新报价34.88元，今日上涨3.41%。",
        "最新报价34.88元，今日上涨3.41%。历史日线收盘33.73元。",
    ]
    assert all("今天下跌6.31%" not in item["draft"] for item in updates)
    assert usage["streaming"]["mode"] == "guarded_cumulative_stream_v3"
    assert usage["streaming"]["visible_events"] == 2
    assert usage["streaming"]["withheld_segments"] == 1
    assert usage["streaming"]["deferred_segments"] == 1


def test_streamed_draft_is_replaced_by_final_guarded_answer(
    tmp_path: Path, settings, monkeypatch
):
    guarded_settings = replace(
        settings,
        database_path=tmp_path / "stream-final-guard.db",
        workspace_root=tmp_path / "stream-final-guard-workspaces",
        hermes_enabled=True,
    )
    database = Database(guarded_settings.database_path, guarded_settings.workspace_root)
    database.initialize()
    user = database.create_user("Stream Final Guard User")
    service = AgentService(database, guarded_settings)

    def fake_stream(**kwargs):
        kwargs["stream_callback"](
            {
                "type": "delta",
                "draft": "结论：这更像超跌后的短期修复，中期反转还没有确认。",
                "is_unverified": True,
            }
        )
        return (
            "结论：这更像超跌后的短期修复，中期反转还没有确认。\n\n"
            "- 上证综指近20日下跌6.66%，仍位于20日均线下方。\n"
            "- 传闻中的资金规模为9999亿元，这一行没有证据支持。\n"
            "- 后续应观察指数能否重新站上20日均线，以及量能能否连续。\n\n"
            "以上只解释已经发生的市场结构，不预测下一交易日方向。",
            {
                "model": "fake-stream",
                "streaming": {
                    "enabled": True,
                    "first_token_seconds": 0.25,
                    "first_visible_seconds": 0.75,
                },
            },
        )

    monkeypatch.setattr(service, "_execute_hermes_streaming", fake_stream)
    streamed = []
    run = service.run(
        user=user,
        intent="market_brief",
        message="A股这次是反弹还是反转？",
        evidence={
            "type": "market_brief",
            "question_focus": {"key": "trend_reversal"},
            "indices": [
                {
                    "name": "上证综指",
                    "status": "available",
                    "metrics": {"return_20d_pct": -6.6582},
                }
            ],
        },
        model_tier="economy",
        execute_agent=True,
        stream_callback=streamed.append,
    )

    assert streamed[0]["draft"] == "结论：这更像超跌后的短期修复，中期反转还没有确认。"
    assert run["status"] == "completed"
    assert "短期修复" in run["answer"]
    assert "9999" not in run["answer"]
    assert streamed[-1] == {
        "type": "delta",
        "draft": run["answer"],
        "is_unverified": False,
        "is_final": True,
    }
    assert run["usage"]["output_guard"]["passed"] is True
    assert run["usage"]["timings"]["first_token_seconds"] == 0.25
    assert run["usage"]["timings"]["first_visible_seconds"] == 0.75


def test_streaming_bridge_failure_falls_back_to_oneshot_cli(
    tmp_path: Path, settings, monkeypatch
):
    guarded_settings = replace(
        settings,
        database_path=tmp_path / "stream-fallback.db",
        workspace_root=tmp_path / "stream-fallback-workspaces",
        hermes_enabled=True,
    )
    database = Database(guarded_settings.database_path, guarded_settings.workspace_root)
    database.initialize()
    user = database.create_user("Stream Fallback User")
    service = AgentService(database, guarded_settings)
    monkeypatch.setattr(
        service,
        "_execute_hermes_streaming",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("bridge failed")),
    )
    monkeypatch.setattr(
        service,
        "_execute_hermes",
        lambda **kwargs: ("上证综指当日下跌1.23%。", {"model": "fake-oneshot"}),
    )
    streamed = []

    run = service.run(
        user=user,
        intent="market_brief",
        message="今天A股如何？",
        evidence={
            "type": "market_brief",
            "market_state": {"label": "承压"},
            "indices": [
                {
                    "name": "上证综指",
                    "status": "available",
                    "metrics": {"return_1d_pct": -1.23},
                }
            ],
        },
        model_tier="economy",
        execute_agent=True,
        stream_callback=streamed.append,
    )

    assert run["status"] == "completed"
    assert run["answer"] == "上证综指当日下跌1.23%。"
    assert streamed == [
        {
            "type": "reset",
            "label": "实时生成连接已中断，正在恢复完整回答…",
        },
        {
            "type": "delta",
            "draft": "上证综指当日下跌1.23%。",
            "is_unverified": False,
            "is_final": True,
        },
    ]
    assert run["usage"]["streaming"] == {
        "enabled": False,
        "fallback": "oneshot_cli",
        "bridge_error": "RuntimeError",
    }
