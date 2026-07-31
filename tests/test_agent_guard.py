from __future__ import annotations

from dataclasses import replace
from io import StringIO
import json
from pathlib import Path

import app.services.agent as agent_module
from app.db import Database
from app.services.agent import AgentService
from app.services.agent_output_guard import AgentOutputGuard
from app.services.agent_response_relevance import (
    _drop_redundant_valuation_summary,
    _normalize_valuation_review_language,
    build_quality_review_editor_prompt,
    normalize_quality_review_language,
    peer_valuation_required_fact_issue,
    quality_review_overclaim_issue,
    quality_review_required_fact_issue,
    relative_industry_required_fact_issue,
    repair_peer_valuation_answer,
    repair_quality_review_answer,
    repair_relative_industry_answer,
    repair_valuation_review_answer,
    stock_specialist_relevance_issue,
    valuation_review_required_fact_issue,
)


def test_peer_valuation_required_fact_check_keeps_compact_decision_facts():
    evidence = {
        "type": "stock_research",
        "user_question": "宁德时代的PE和PB相对同行处于什么位置？",
        "peer_comparison": {
            "subject": {
                "name": "宁德时代",
                "symbol": "300750.SZ",
                "pe_ttm": 21.27,
                "pb": 4.77,
            },
            "metrics": {
                "pe_ttm": {
                    "subject_value": 21.27,
                    "peer_median": 26.24,
                    "subject_to_peer_median": 0.811,
                },
                "pb": {
                    "subject_value": 4.77,
                    "peer_median": 1.71,
                    "subject_to_peer_median": 2.789,
                },
            },
            "peers": [
                {"name": "亿纬锂能", "pe_ttm": 26.24, "pb": 2.72},
                {"name": "国轩高科", "pe_ttm": 21.3, "pb": 1.71},
                {"name": "欣旺达", "pe_ttm": 42.32, "pb": 1.36},
            ],
            "operating_comparison": {"status": "unavailable"},
        },
    }
    incomplete = (
        "宁德时代PE 21.27，接近国轩高科；PB 4.77，同行中位数1.71。"
        "亿纬锂能PB 2.72，国轩高科PB 1.71，欣旺达PB 1.36。"
        "同报告期经营数据不足，不能把倍数差异解释为经营质量。"
    )
    complete = (
        "宁德时代TTM市盈率21.27，亿纬锂能26.24、国轩高科21.3、"
        "欣旺达42.32，同行中位数26.24；宁德时代/中位数比值0.811。"
        "宁德时代市净率4.77，亿纬锂能2.72、国轩高科1.71、"
        "欣旺达1.36，同行中位数1.71；宁德时代/中位数比值2.789。"
        "同报告期经营数据不足，不能把倍数差异解释为经营质量。"
    )
    compact_complete = (
        "宁德时代TTM市盈率21.27，同行亿纬锂能、国轩高科、欣旺达的"
        "中位数为26.24，宁德时代/中位数比值0.811；宁德时代市净率"
        "4.77，同行中位数1.71，宁德时代/中位数比值2.789。"
        "同报告期经营数据不足，不能把倍数差异解释为经营质量。"
    )

    assert "TTM市盈率" in peer_valuation_required_fact_issue(incomplete, evidence)
    assert peer_valuation_required_fact_issue(complete, evidence) is None
    assert peer_valuation_required_fact_issue(compact_complete, evidence) is None

    trailing_zero_complete = complete.replace("国轩高科21.3", "国轩高科21.30")
    assert peer_valuation_required_fact_issue(trailing_zero_complete, evidence) is None

    missing_ratio = complete.replace("；宁德时代/中位数比值0.811", "").replace(
        "；宁德时代/中位数比值2.789", ""
    )
    assert peer_valuation_required_fact_issue(missing_ratio, evidence) is None

    repaired = repair_peer_valuation_answer(incomplete, evidence)
    assert repaired is not None
    assert "固定同行估值截面（已核验数字）" in repaired
    assert "国轩高科：TTM市盈率 21.30，市净率 1.71" in repaired
    assert "本标的/同行中位数" not in repaired
    assert peer_valuation_required_fact_issue(repaired, evidence) is None


def test_valuation_review_rejects_unit_mismatch_dynamic_pe_bridge_and_hallucinated_event():
    evidence = {
        "type": "stock_research",
        "display_name": "动力新科",
        "user_question": "动力新科为什么进入估值约束候选？请结合同行、现金流和负债核验。",
        "research_plan": {"focus": "valuation_review"},
        "fundamentals": {"valuation": {"pe_ttm": 2.5, "pb": 1.21, "pe_dynamic": 53.77}},
        "financial_drivers": {
            "cashflow_analysis": {
                "operating_cashflow": -452_997_686.85,
                "operating_cashflow_to_net_profit": -12.514,
            },
            "filing_evidence": {"explicit_company_explanations": []},
        },
        "earnings_quality": {"latest_report": {"debt_asset_ratio_pct": 42.480874}},
        "peer_comparison": {
            "subject": {"name": "动力新科", "pe_ttm": 2.43, "pb": 1.18},
            "metrics": {
                "pe_ttm": {
                    "subject_value": 2.43,
                    "peer_median": 10.0,
                    "subject_to_peer_median": 0.243,
                },
                "pb": {
                    "subject_value": 1.18,
                    "peer_median": 1.5,
                    "subject_to_peer_median": 0.787,
                },
            },
            "peers": [
                {"name": "上汽集团", "pe_ttm": 8.0, "pb": 0.8},
                {"name": "潍柴动力", "pe_ttm": 10.0, "pb": 1.5},
                {"name": "长安汽车", "pe_ttm": 12.0, "pb": 1.9},
            ],
            "operating_comparison": {"status": "unavailable"},
        },
        "a_share_information": {"announcements": []},
        "event_timeline": {"events": []},
    }
    valid = (
        "命中估值约束不等于便宜。动力新科最新估值快照的PE TTM为2.50，PB为1.21。"
        "同日同行截面中，动力新科TTM市盈率2.43，上汽集团8.00、"
        "潍柴动力10.00、长安汽车12.00，同行中位数10.00，"
        "本标的/中位数比值0.243；动力新科市净率1.18，上汽集团0.80、"
        "潍柴动力1.50、长安汽车1.90，同行中位数1.50，"
        "本标的/中位数比值0.787。同报告期经营数据不足，不能把倍数差异"
        "直接解释为经营质量。最新报告期经营现金流为-4.53亿元，"
        "经营现金流/归母净利润为-12.514，资产负债率42.48%。"
    )

    assert valuation_review_required_fact_issue(valid, evidence) is None
    natural_opening = valid.replace(
        "命中估值约束不等于便宜。",
        "不能因为PE偏低就说有支撑，PB较高也不能直接说危险。",
    )
    assert valuation_review_required_fact_issue(natural_opening, evidence) is None
    assert "每股收益与利润金额单位" in valuation_review_required_fact_issue(
        valid + "2025年有29.7亿元的每股收益。", evidence
    )
    assert "动态市盈率" in valuation_review_required_fact_issue(
        valid + "按此计算，动态市盈率为53.77倍。", evidence
    )
    assert (
        valuation_review_required_fact_issue(
            valid + "因此不能将低PE、低PB直接解释为低估。", evidence
        )
        is None
    )
    assert "滚动十二个月市盈率" in valuation_review_required_fact_issue(
        valid + "PE TTM 2.50对应的是刚扭亏的低利润基数。", evidence
    )
    assert "滚动十二个月市盈率" in valuation_review_required_fact_issue(
        valid + "低利润基数导致TTM市盈率被压缩。", evidence
    )
    assert "历史利润错误解释低PE" in valuation_review_required_fact_issue(
        valid + "历史亏损可能在分母中残留，导致PE倍数被压得很低。", evidence
    )
    assert (
        valuation_review_required_fact_issue(
            valid + "当前极低的PE不能直接等同于便宜。", evidence
        )
        is None
    )
    assert (
        valuation_review_required_fact_issue(
            valid + "极低倍数需要结合现金流核验。", evidence
        )
        is None
    )
    assert (
        valuation_review_required_fact_issue(
            valid + "当前倍数在同行中处于极低位置，但不能据此确认低估。", evidence
        )
        is None
    )
    assert "确定性价值结论" in valuation_review_required_fact_issue(
        valid + "动力新科属于极低估值。", evidence
    )
    assert "确定性价值结论" in valuation_review_required_fact_issue(
        valid + "动力新科已经成为价值洼地。", evidence
    )
    assert "分母因素解释低PE" in valuation_review_required_fact_issue(
        valid + "如果包含大量非经常性损益，PE会被动拉低。", evidence
    )
    assert "分母因素解释低PE" in valuation_review_required_fact_issue(
        valid + "目前PE的低位更多源于分母端不透明。", evidence
    )
    assert "趋势延续" in valuation_review_required_fact_issue(
        valid + "半年度预告说明盈利改善趋势可能延续。", evidence
    )
    assert "盈利延续" in valuation_review_required_fact_issue(
        valid + "这份预告确实表明盈利方向在延续。", evidence
    )
    assert "盈利延续" in valuation_review_required_fact_issue(
        valid + "半年度业绩预告确认盈利延续。", evidence
    )
    assert "整体财务杠杆下降" in valuation_review_required_fact_issue(
        valid + "资产负债率下降说明整体财务杠杆明显下降。", evidence
    )
    assert "现金回收压力" in valuation_review_required_fact_issue(
        valid + "销售收现率下降印证了现金回收节奏存在压力。", evidence
    )
    assert "经营质量因素解释低倍数" in valuation_review_required_fact_issue(
        valid + "低倍数也可能来自一次性或不可持续因素。", evidence
    )
    assert "现金支撑结论" in valuation_review_required_fact_issue(
        valid + "盈利的现金兑现严重偏离，现金流尚不能为利润提供支撑。", evidence
    )
    assert "单一年度利润" in valuation_review_required_fact_issue(
        valid + "PE TTM是以2025年全年利润为基础计算的。", evidence
    )
    assert "股权处置" in valuation_review_required_fact_issue(
        valid + "利润来自股权处置。", evidence
    )
    assert (
        valuation_review_required_fact_issue(
            valid + "下一步需要核验非经常性收益明细。", evidence
        )
        is None
    )
    assert "确定性价值结论" in valuation_review_required_fact_issue(
        valid + "因此它就是财务陷阱。", evidence
    )


def test_natural_valuation_support_question_does_not_force_cashflow_and_debt_dump():
    evidence, _ = _same_day_valuation_review_case()
    evidence = {
        **evidence,
        "user_question": (
            "动力新科现在估值有没有支撑？把PE、PB和同行放在一起讲，"
            "但不要因为倍数低就说便宜。"
        ),
    }
    answer = (
        "不能因为PE偏低就说有支撑，PB较低也不能直接说便宜。"
        "2026-07-29收盘，动力新科PE TTM为2.50，同行沪光股份、美湖股份、"
        "旷达科技的中位数为39.39；动力新科PB为1.21，同行中位数为2.26。"
        "同报告期经营数据不足，不能把倍数差异直接解释为经营质量。"
    )

    assert valuation_review_required_fact_issue(answer, evidence) is None

    contradiction_evidence = json.loads(json.dumps(evidence))
    contradiction_evidence["peer_comparison"]["metrics"]["pb"][
        "peer_median"
    ] = 0.8
    contradiction_evidence["peer_comparison"]["metrics"]["pb"][
        "subject_to_peer_median"
    ] = 1.516
    natural_contradiction = (
        "动力新科当前PE TTM约2.61倍、PB约1.27倍。2026年7月29日收盘，"
        "同日PE TTM为2.50倍，低于沪光股份、美湖股份、旷达科技的同行中位数"
        "39.39倍；PB为1.21倍，高于同行中位数0.80倍，两者给出的方向相反，"
        "是需要解释的估值矛盾。这种分化本身就说明不能简单用便宜或贵来定性。"
        "同报告期经营数据不足，不能把倍数差异直接解释为经营质量。"
    )
    repaired = repair_valuation_review_answer(
        natural_contradiction,
        contradiction_evidence,
    )
    assert repaired is not None
    assert not repaired.startswith("动力新科进入估值约束候选")


def test_valuation_review_keeps_explicit_negation_of_cashflow_overclaim():
    evidence, answer = _same_day_valuation_review_case()
    evidence = {
        **evidence,
        "user_question": "动力新科估值怎么看？请比较PE、PB和同行。",
    }
    answer += (
        "销售收现率较可比期下降，但这不能直接等同于回款恶化或收入质量"
        "出问题，具体原因仍需核验。"
    )

    assert valuation_review_required_fact_issue(answer, evidence) is None
    assert stock_specialist_relevance_issue(answer, evidence) is None


def _same_day_valuation_review_case() -> tuple[dict, str]:
    evidence = {
        "type": "stock_research",
        "symbol": "600841.SS",
        "display_name": "动力新科",
        "user_question": "动力新科进入估值约束候选，是不是说明它便宜？",
        "research_plan": {"focus": "valuation_review"},
        "fundamentals": {"valuation": {"pe_ttm": 2.61, "pb": 1.27}},
        "financial_drivers": {
            "cashflow_analysis": {
                "operating_cashflow": -452_997_686.85,
                "operating_cashflow_to_net_profit": -12.5139,
            }
        },
        "earnings_quality": {"latest_report": {"debt_asset_ratio_pct": 42.4809}},
        "peer_comparison": {
            "method": "dynamic_same_day_peer_valuation_snapshot_v1",
            "as_of": "2026-07-29",
            "group_label": "汽车配件同日估值样本",
            "selection_basis": "在2026-07-29同一交易日选择同行估值样本。",
            "subject": {
                "name": "动力新科",
                "pe_ttm": 2.4967,
                "pb": 1.2128,
                "market_timestamp": "2026-07-29T15:00:00+08:00",
            },
            "metrics": {
                "pe_ttm": {
                    "subject_value": 2.4967,
                    "peer_median": 39.3922,
                    "subject_to_peer_median": 0.063,
                },
                "pb": {
                    "subject_value": 1.2128,
                    "peer_median": 2.2582,
                    "subject_to_peer_median": 0.537,
                },
            },
            "peers": [
                {
                    "name": "沪光股份",
                    "market_timestamp": "2026-07-29T15:00:00+08:00",
                },
                {
                    "name": "美湖股份",
                    "market_timestamp": "2026-07-29T15:00:00+08:00",
                },
                {
                    "name": "旷达科技",
                    "market_timestamp": "2026-07-29T15:00:00+08:00",
                },
            ],
            "operating_comparison": {"status": "unavailable"},
        },
    }
    answer = (
        "不是。数据日期为2026年7月29日收盘，动力新科PE TTM约2.50，"
        "PB约1.21；沪光股份、美湖股份和旷达科技的同行PE TTM中位数"
        "为39.39，PB中位数为2.26。本标的PE TTM约为同行中位数的6%，"
        "PB约为同行中位数的54%。同报告期经营数据不足，不能把倍数差异"
        "直接解释为经营质量。最新报告期经营现金流为-4.53亿元，"
        "经营现金流/归母净利润为-12.51，资产负债率42.48%。"
    )
    return evidence, answer


def _valuation_review_local_overclaim_draft() -> str:
    return (
        "动力新科进入估值约束候选不说明它便宜。当前PE TTM为2.61，PB为1.27，"
        "表面看起来估值极低；低倍数也可能是盈利恶化、资产质量差或一次性收益造成的，"
        "必须用正式财务报表核验才能判断。同行样本基于2026年7月29日，包含沪光股份、美湖股份"
        "和旷达科技，PE TTM中位数39.39，PB中位数2.26；本标的约为中位数的6%和54%。"
        "PE TTM只有2.61倍，这通常暗示市场认为盈利不可持续。最新报告期归母净利润"
        "3620万元，较上年同期亏损2,101万元实现扭亏；经营现金流-4.53亿元，"
        "经营现金流/归母净利润-12.51，资产负债率42.48%。这意味着利润尚未转化为现金，"
        "现金兑现质量存疑。TTM口径下盈利可能受到一次性因素影响，下一步应核验扣非利润。"
        "一致预期大幅下降，可能与上汽红岩出表带来的一次性会计因素有关。"
        "当前价格包含的盈利和净资产预期极低。"
        "它反映的更有可能是市场对盈利持续性持谨慎态度。"
    )


def test_valuation_review_accepts_dated_same_day_peer_values_and_percent_ratios():
    evidence, answer = _same_day_valuation_review_case()

    assert peer_valuation_required_fact_issue(answer, evidence) is None
    assert valuation_review_required_fact_issue(answer, evidence) is None
    assert stock_specialist_relevance_issue(answer, evidence) is None

    undated = answer.replace("数据日期为2026年7月29日收盘，", "")
    assert "带日期的同日同行口径" in valuation_review_required_fact_issue(
        undated, evidence
    )

    naturally_rounded = answer.replace("为39.39", "约39")
    assert peer_valuation_required_fact_issue(naturally_rounded, evidence) is None


def test_valuation_review_repair_keeps_first_draft_and_fixes_local_overclaims():
    evidence, _ = _same_day_valuation_review_case()
    repaired = repair_valuation_review_answer(
        _valuation_review_local_overclaim_draft(),
        evidence,
    )

    assert repaired is not None
    assert repaired.startswith("动力新科进入估值约束候选不说明它便宜")
    assert "估值极低" not in repaired
    assert "一次性收益造成" not in repaired
    assert "滚动盈利分母尚未拆解" in repaired
    assert "通常暗示市场认为盈利不可持续" not in repaired
    assert "2,101" not in repaired
    assert "可能与上汽红岩出表" not in repaired
    assert "不能据此归因于一次性会计因素" in repaired
    assert "盈利和净资产预期极低" not in repaired
    assert "市场对盈利持续性持谨慎态度" not in repaired
    assert "不能据此推断市场意图" in repaired
    assert "2026-07-29 收盘，动力新科 PE TTM 2.50、PB 1.21" in repaired
    assert stock_specialist_relevance_issue(repaired, evidence) is None
    assert AgentService._validate_model_output(repaired, evidence)["passed"] is True


def test_valuation_review_accepts_negative_cashflow_written_as_net_outflow():
    evidence, answer = _same_day_valuation_review_case()
    answer = answer.replace(
        "最新报告期经营现金流为-4.53亿元",
        "最新报告期经营活动现金净流出4.53亿元",
    )

    assert valuation_review_required_fact_issue(answer, evidence) is None


def test_valuation_review_repair_neutralizes_pricing_cash_and_debt_overclaims():
    evidence, answer = _same_day_valuation_review_case()
    draft = (
        f"{answer}低 PB 更多反映了市场对盈利差的定价，而非明确低估。"
        "盈利在持续，业务结构简单且方向明确。"
        "这意味着账面盈利还没有变成经营活动的现金净流入。"
        "综合来看，业绩扭亏和负债率下降是积极信号，但盈利的现金兑现能力弱。"
    )

    assert "市场定价意图" in valuation_review_required_fact_issue(draft, evidence)
    repaired = repair_valuation_review_answer(draft, evidence)

    assert repaired is not None
    assert "市场对盈利差的定价" not in repaired
    assert "现金兑现能力弱" not in repaired
    assert "负债率下降是积极信号" not in repaired
    assert "盈利在持续" not in repaired
    assert "业务结构简单且方向明确" not in repaired
    assert "还没有变成经营活动的现金净流入" not in repaired
    assert "不能据此推断市场意图" in repaired
    assert "经营现金流与利润方向相反，原因仍需核验" in repaired
    assert valuation_review_required_fact_issue(repaired, evidence) is None


def test_valuation_review_repair_handles_latest_real_failure_phrases():
    evidence, answer = _same_day_valuation_review_case()
    draft = (
        f"{answer}低倍数也可能是盈利恶化、资产质量差或一次性收益造成的，"
        "必须用正式财务报表核验才能判断。经营现金流/归母净利润为-12.51，"
        "说明账面利润在本期并未转化为正向经营现金流入。当前只能确认公司刚扭亏，"
        "历史基数可能包含亏损，这些都会让TTM盈利很低从而拉低PE倍数。"
        "PE低可能恰恰是因为过去四个季度总体赚得很少。"
        "一季度刚刚扭亏，历史亏损可能在分母中残留，导致PE倍数被压得很低。"
        "主营业务集中度虽然高但方向清晰。相比之下动力新科极低。"
        "如果盈利本身靠一次性收益支撑，低倍数反而可能提示风险。"
        "如果包含大量非经常性损益，PE会被动拉低。"
        "目前PE的低位更多源于分母端不透明和现金流异常。"
        "半年度预告说明盈利改善趋势可能延续。"
        "这份预告确实表明盈利方向在延续。"
        "半年度业绩预告确认盈利延续。"
        "利润变薄或者有一次性大额收益都可能让数字看起来很极端。"
        "半年度预告说明主业盈利修复，不是纯粹靠非经常项目维持。"
        "滚动四个季度盈利可能包含大额资产处置或受基数极低影响。"
        "资产负债率从上一季度的水平降到42.48%，整体财务杠杆明显下降，"
        "偿债压力的相对比例减少了。"
        "这表示利润尚未变成真实的现金流入，并印证了现金回收节奏存在压力。"
        "目前低倍数在同行中处于极低位置。"
        "当前只能确认倍数处在极低水平。"
        "综合来看，当前 PE TTM 极低。"
        "低倍数也可能来自盈利分母中隐含的一次性或不可持续因素。"
        "TTM分母包含多少历史亏损、是否有非经常性收益尚未拆解。"
        "盈利的现金兑现严重偏离，现金流尚不能为利润提供支撑。"
        "低倍数是否被一次性收益或低利润基数扭曲无法确认。"
    )

    repaired = repair_valuation_review_answer(draft, evidence)

    assert repaired is not None
    assert "一次性收益造成" not in repaired
    assert "并未转化为正向经营现金流入" not in repaired
    assert "TTM盈利很低从而拉低PE" not in repaired
    assert "过去四个季度总体赚得很少" not in repaired
    assert "历史亏损可能在分母中残留" not in repaired
    assert "方向清晰" not in repaired
    assert "动力新科极低" not in repaired
    assert "极低" not in repaired
    assert "靠一次性收益支撑" not in repaired
    assert "PE会被动拉低" not in repaired
    assert "低位更多源于" not in repaired
    assert "盈利改善趋势可能延续" not in repaired
    assert "盈利方向在延续" not in repaired
    assert "确认盈利延续" not in repaired
    assert "半年度业绩预告给出预计盈利区间" in repaired
    assert "一次性大额收益" not in repaired
    assert "非经常项目维持" not in repaired
    assert "基数极低" not in repaired
    assert "上一季度" not in repaired
    assert "整体财务杠杆明显下降" not in repaired
    assert "真实的现金流入" not in repaired
    assert "现金回收节奏存在压力" not in repaired
    assert "极低位置" not in repaired
    assert "极低水平" not in repaired
    assert "PE TTM 极低" not in repaired
    assert "低倍数也可能来自" not in repaired
    assert "非经常性收益尚未拆解" not in repaired
    assert "现金兑现严重偏离" not in repaired
    assert "不能为利润提供支撑" not in repaired
    assert "低倍数是否被" not in repaired
    assert "需核验扣非利润和非经常性损益明细" in repaired
    assert "不能直接解释为利润尚未兑现为现金" in repaired
    assert valuation_review_required_fact_issue(repaired, evidence) is None
    assert AgentService._validate_model_output(repaired, evidence)["passed"] is True


def test_valuation_review_accepts_opening_synonym_and_debt_boundary():
    evidence, answer = _same_day_valuation_review_case()
    evidence["earnings_quality"]["comparable_report"] = {
        "debt_asset_ratio_pct": 74.9
    }
    answer = answer.replace(
        "不是。",
        "命中估值约束候选≠便宜。",
        1,
    ) + (
        "资产负债率下降只表示资产结构变化，不能直接等同于负债总量或"
        "偿债压力已下降。"
    )

    assert valuation_review_required_fact_issue(answer, evidence) is None

    ratio_only = answer + (
        "资产负债率从74.90%降至42.48%，这是负债占资产的比例在下降。"
    )
    assert valuation_review_required_fact_issue(ratio_only, evidence) is None


def test_valuation_review_repair_does_not_force_peer_ratios_and_fixes_cash_shortcut():
    evidence, answer = _same_day_valuation_review_case()
    evidence["earnings_quality"]["comparable_report"] = {
        "debt_asset_ratio_pct": 74.9
    }
    draft = answer.replace(
        "本标的PE TTM约为同行中位数的6%，PB约为同行中位数的54%。",
        "",
    ).replace(
        "最新报告期经营现金流为-4.53亿元，经营现金流/归母净利润为-12.51，",
        "最新报告期经营现金流为-4.53亿元，经营现金流/归母净利润为-12.51，"
        "这说明报告期内的盈利还没有以现金形式回到公司，",
    )
    draft += (
        "低倍数也可能对应着盈利质量有问题，或利润里有大量一次性的非经常项目。"
        "资产负债率从74.90%降至42.48%，这是负债占资产的比例在下降。"
    )

    repaired = repair_valuation_review_answer(draft, evidence)

    assert repaired is not None
    assert "本标的/中位数比值分别为" not in repaired
    assert "盈利还没有以现金形式回到公司" not in repaired
    assert "低倍数也可能对应着" not in repaired
    assert repaired.count("**") % 2 == 0
    assert stock_specialist_relevance_issue(repaired, evidence) is None
    assert AgentService._validate_model_output(repaired, evidence)["passed"] is True


def test_valuation_review_repair_compacts_latest_real_readability_failure():
    evidence, _ = _same_day_valuation_review_case()
    evidence["financial_drivers"]["cashflow_analysis"].update(
        {
            "comparable_operating_cashflow_to_net_profit": 2.331,
        }
    )
    evidence["earnings_quality"]["latest_report"].update(
        {
            "report_date": "2026-03-31",
            "parent_net_profit": 36_199_600.85,
        }
    )
    evidence["earnings_quality"]["comparable_report"] = {
        "report_date": "2025-03-31",
        "parent_net_profit": -210_165_309.62,
        "debt_asset_ratio_pct": 74.9,
    }
    evidence["a_share_information"] = {
        "announcements": [
            {
                "published_at": "2026-07-14T00:00:00+08:00",
                "summary": "预计上半年归母净利润为7000万元至9000万元。",
            }
        ]
    }
    evidence["business_structure"] = {
        "anchor_report_date": "2025-12-31",
        "dimensions": [
            {
                "classification": "product",
                "segments": [
                    {
                        "item_name": "发动机",
                        "revenue_share_pct": 94.0752,
                        "gross_margin_pct": 12.4359,
                    },
                    {
                        "item_name": "重卡",
                        "revenue_share_pct": 5.9248,
                        "gross_margin_pct": -57.8053,
                    },
                ],
            }
        ],
    }
    draft = """命中估值约束不等于便宜。

动力新科当前 PE TTM 为 2.50 倍，PB 为 1.21 倍，相比同日市值相近的三个汽车配件样本（沪光股份、美湖股份、旷达科技），PE 中位数为 39.39 倍、PB 中位数为 2.26 倍，本标的数值明显偏低。但低倍数能确认的只是当前价格相对于滚动盈利和净资产的比值较低，不等于公司已经被低估。关键在于这个低倍数背后是真实的持续盈利支撑，还是由一次性收益、利润波动或资产质量隐患造成的数字假象。

**盈利已经扭亏，但现金兑现仍需复核**

2026 年一季报（2026 年 3 月 31 日）显示归母净利润约 3620 万元，而上一年同期为亏损约 2.1 亿元，同比扭亏。公司 2026 年 7 月 14 日披露的半年度业绩预告预计上半年归母净利润为 7000 万至 9000 万元，也已实现扭亏。这些是支持继续研究的事实：利润层面确实从亏损转向盈利。

但经营现金流与利润方向完全相反。2026 年一季报经营现金流净额为 -4.53 亿元，与归母净利润的覆盖比率为 -12.5 倍（去年同期为 2.33 倍）。经营现金流为负、与利润方向背离，意味着当季账面利润尚未转化为经营活动净现金流入，这是判断估值质量时必须优先复核的风险点。

**负债率下降，但现金流偿债能力仍需验证**

资产负债率从去年同期的 74.90% 降至当前的 42.48%，负债占资产的比例明显下降。这一变化是财务结构上的积极事实，但仅凭资产负债率本身不能确认偿债压力已经减轻，尤其是经营现金流净额仍然为负。负债率的下降能否转化为真实的财务安全，还需要核对总负债的绝对规模变化以及后续现金流改善。

**主营高度集中于发动机，但高集中度不等于方向明确**

最新主营构成来自 2025 年年报，发动机业务占总收入 94.08%，毛利率约 12.44%；重卡业务占比 5.92%，毛利率为 -57.81%。收入高度集中意味着公司盈利几乎完全依赖单一产品线的表现，一旦发动机需求或竞争格局变化，影响将被放大。重卡业务毛利为负也在拖累整体盈利。这些事实构成了待核验的经营风险，不能因为利润近期扭亏就忽略。

**尚不能确认低估，核心缺口在盈利质量核验**

当前证据无法确认低倍数是否合理。滚动十二个月盈利 TTM 的分母尚未拆解，无法判断低 PE 是否由一次性非经常性收益或利润低基数造成。同时，同报告期同行的经营数据（营收、利润率、现金流）均缺失，无法用经营质量截面验证倍数差异是否有业务基本面支撑。要判断估值约束是否对应真实低估，需要交叉核对扣非净利润与非经常性损益明细、经营现金流变化的附注解释、应收与存货周转的具体数字，以及下一份定期报告中经营现金流能否跟着利润一起转正。"""

    repaired = repair_valuation_review_answer(draft, evidence)

    assert repaired is not None
    paragraphs = [item for item in repaired.split("\n\n") if item.strip()]
    assert 4 <= len(paragraphs) <= 6
    assert repaired.count("**") % 2 == 0
    assert repaired.count("**") <= 6
    assert "**利润已扭亏，但经营现金流仍为负**" in repaired
    assert "**资产负债率下降，不等于负债总量减少**" in repaired
    assert "**主营集中于发动机，重卡业务仍亏损**" in repaired
    assert "积极事实" not in repaired
    assert "真实的财务安全" not in repaired
    assert "现金流偿债能力" not in repaired
    assert "经营现金流为负、与利润方向背离，经营现金流与利润方向相反" not in repaired
    assert repaired.count("当前估值截面偏低") == 1
    assert repaired.count("42.48%") == 1
    assert "较可比期下降约 32.42 个百分点" in repaired
    assert stock_specialist_relevance_issue(repaired, evidence) is None
    assert AgentService._validate_model_output(repaired, evidence)["passed"] is True


def test_valuation_review_markdown_cleanup_preserves_valid_heading_lines():
    repaired = _normalize_valuation_review_language(
        "**未闭合标题\n\n**有效标题**\n\n正文保持不变。"
    )

    assert repaired.startswith("未闭合标题")
    assert "**有效标题**" in repaired
    assert repaired.count("**") == 2


def test_valuation_review_readability_removes_pb_and_margin_causal_shortcuts():
    draft = """**命中估值约束不等于便宜。** 当前倍数低于同行。

**变动的负债率提醒我们，低 PB 来自高股东权益，不自动等于资产便宜。** 最新资产负债率从同期74.9%降至42.48%，这与资产总量或负债结构变动有关。PB只有1.24，本质上是因为每股净资产比同行高；而负债率骤降若来自一次性权益变动，PB就容易在事后被动抬升。

**刚扭亏的盈利还谈不上扎实，滚动 PE 的分母仍待拆解。** 这表示净利润虽已转正，但与同期经营活动净现金流入完全是两个方向；利润还没有被实实在在的经营现金流入覆盖。
**主营高度依赖发动机，毛利率刚回升但还很低。** 2026年一季报毛利率回升到10.37%，是利润率改善的关键驱动力，但 10% 的毛利率在制造业中仍属偏薄。
**综合判断**：仍需核验。"""

    repaired = _drop_redundant_valuation_summary(
        _normalize_valuation_review_language(draft)
    )

    paragraphs = [item for item in repaired.split("\n\n") if item.strip()]
    assert 4 <= len(paragraphs) <= 6
    assert repaired.count("**") <= 6
    assert "低 PB 来自高股东权益" not in repaired
    assert "本质上是因为每股净资产比同行高" not in repaired
    assert "被动抬升" not in repaired
    assert "实实在在的经营现金流入覆盖" not in repaired
    assert "关键驱动力" not in repaired
    assert "制造业中仍属偏薄" not in repaired
    assert "**资产负债率下降，不等于负债总量减少**" in repaired
    assert "**主营集中于发动机，重卡业务毛利仍为负**" in repaired


def test_valuation_review_repairs_only_hard_financial_math_errors():
    evidence, answer = _same_day_valuation_review_case()
    draft = answer + (
        "这个极低的PE（TTM）主要来自公司刚脱离巨亏、现在盈利还很薄。"
        "销售收现率从79.43%下降到67.95%，说明更多营收尚未转化为现金回款。"
        "资产负债率从74.90%下降到42.48%，表面上负债压力减轻，但仍需核验。"
    )
    evidence["earnings_quality"]["comparable_report"] = {
        "debt_asset_ratio_pct": 74.901016
    }
    evidence["financial_drivers"]["cashflow_analysis"].update(
        {
            "cash_received_from_sales_to_revenue_pct": 67.948,
            "comparable_cash_received_from_sales_to_revenue_pct": 79.429,
        }
    )

    repaired = repair_valuation_review_answer(draft, evidence)

    assert repaired is not None
    assert "主要来自公司刚脱离巨亏" not in repaired
    assert "更多营收尚未转化为现金回款" not in repaired
    assert "表面上负债压力减轻" not in repaired
    assert "不能用单季扭亏、历史亏损或利润规模直接解释当前倍数" in repaired
    assert "这一比率变化的原因尚未确认" in repaired
    assert valuation_review_required_fact_issue(repaired, evidence) is None
    assert AgentService._validate_model_output(repaired, evidence)["passed"] is True


def test_valuation_review_repairs_latest_natural_draft_without_duplicate_appendix():
    evidence, _ = _same_day_valuation_review_case()
    evidence["earnings_quality"]["comparable_report"] = {
        "debt_asset_ratio_pct": 74.9
    }
    draft = (
        "动力新科的PE TTM约2.50倍、PB约1.21倍，相比沪光股份、美湖股份和"
        "旷达科技的同行中位数39.39倍、2.26倍，倍数确实很低。但从目前证据看，"
        "这个低估值更像是盈利刚刚扭亏、现金流尚未跟上的阶段特征，还不能直接"
        "等同于便宜。\n\n"
        "经营现金流为-4.53亿元，经营现金流/归母净利润为-12.51。"
        "资产负债率42.48%。\n\n"
        "负债率下降也不宜简单视为财务结构改善。不能仅凭比例下降就得出负债压力"
        "减轻的结论。\n\n"
        "同报告期经营数据不足，不能把倍数差异直接解释为经营质量。"
    )

    assert "同日估值日期" in stock_specialist_relevance_issue(draft, evidence)
    repaired = repair_valuation_review_answer(draft, evidence)

    assert repaired is not None
    assert repaired.startswith("截至 2026-07-29 收盘，动力新科的PE TTM")
    assert "本标的/中位数比值分别为" not in repaired
    assert "同日同行口径：" not in repaired
    assert "更像是盈利刚刚扭亏" not in repaired
    assert "是否解释估值差异仍未确认" in repaired
    assert "不能据此认定便宜" in repaired
    assert "负债率下降也不宜简单视为资产负债率下降" not in repaired
    assert "资产负债率下降只说明负债占资产比例下降" in repaired
    assert stock_specialist_relevance_issue(repaired, evidence) is None


def test_valuation_review_repairs_v4_natural_draft_without_discarding_it():
    evidence, _ = _same_day_valuation_review_case()
    evidence["fundamentals"]["valuation"]["pe_dynamic"] = 55.11
    evidence["earnings_quality"]["comparable_report"] = {
        "debt_asset_ratio_pct": 74.9
    }
    evidence["financial_drivers"]["cashflow_analysis"].update(
        {
            "cash_received_from_sales_to_revenue_pct": 67.95,
            "comparable_cash_received_from_sales_to_revenue_pct": 79.43,
        }
    )
    evidence["business_structure"] = {
        "dimensions": [
            {
                "classification": "product",
                "segments": [
                    {
                        "item_name": "发动机",
                        "revenue_share_pct": 94.0,
                        "gross_margin_pct": 12.4,
                    }
                ],
            }
        ]
    }
    draft = """动力新科因为 PE TTM 2.50、PB 1.21 进入估值约束候选，这只能说明当前倍数在数字上处于很低的位置，并不能直接等同于“股票便宜”。

沪光股份、美湖股份和旷达科技的 PE TTM 中位数为39.39倍、PB中位数为2.26倍，动力新科的倍数明显更低，但同报告期经营数据不足，不能把倍数差异直接解释为经营质量。

公司一季报归母净利润已经扭亏。发动机业务收入占比94%、毛利率约12.4%，说明核心业务具备毛利产出能力，并非完全依赖非经常性项目。

经营现金流为-4.53亿元，经营现金流/归母净利润为-12.51。销售收现率从79.43%下降到67.95%。这组数据提示现金回款比例在走低，利润的“含金量”还不能认可，需要核验是否存在真实财务压力。

动态市盈率55.11倍侧面印证了市场对全年盈利体量的保守预期。TTM市盈率2.50倍的极低值，很可能与滚动十二个月盈利中仍包含历史亏损或大额非经常性损益有关，但当前证据尚未拆清具体构成。

资产负债率从74.90%下降到42.48%，是一个积极变化，但无法确认这一下降是来自负债减少还是资产扩张，还不能直接等同于偿债压力减轻。

综合来看，动力新科的低估值更像是一个需要交叉验证的信号，而不是一个已经确认的结论。交叉验证的信号，而不是一个已经确认的结论。在这些问题没有答案之前，它更像危险信号灯，而不是已确认的价值洼地。"""

    repaired = repair_valuation_review_answer(draft, evidence)

    assert repaired is not None
    assert repaired.startswith("动力新科因为 PE TTM")
    assert "截至 2026-07-29 收盘，沪光股份、美湖股份和旷达科技" in repaired
    assert "处于很低的位置" in repaired
    assert "市场对全年盈利体量的保守预期" not in repaired
    assert "历史亏损或大额非经常性损益有关" not in repaired
    assert "利润的“含金量”" not in repaired
    assert "真实财务压力" not in repaired
    assert "是一个积极变化" not in repaired
    assert "来自负债减少还是资产扩张" not in repaired
    assert "并非完全依赖非经常性项目" not in repaired
    assert repaired.count("交叉验证的信号，而不是一个已经确认的结论") == 1
    assert "危险信号灯" not in repaired
    assert "价值洼地" not in repaired
    assert "同日同行口径：" not in repaired
    assert stock_specialist_relevance_issue(repaired, evidence) is None
    assert AgentService._validate_model_output(repaired, evidence)["passed"] is True


def test_valuation_review_repairs_v5_hard_errors_without_duplicate_peer_snapshot():
    evidence, _ = _same_day_valuation_review_case()
    evidence["earnings_quality"]["comparable_report"] = {
        "debt_asset_ratio_pct": 74.9
    }
    evidence["financial_drivers"]["cashflow_analysis"].update(
        {
            "cash_received_from_sales_to_revenue_pct": 67.95,
            "comparable_cash_received_from_sales_to_revenue_pct": 79.43,
        }
    )
    draft = (
        "动力新科的PE TTM只有2.50倍、PB不到1.25倍，放在同行汽车配件公司里"
        "确实低得很突出。今天同一行业标签下，市值相近的沪光股份、美湖股份、"
        "旷达科技三家，PE TTM中位数为39.39倍，PB中位数约2.26倍。"
        "但这组倍数差距主要由利润极薄和近期刚扭亏造成，并不能直接得出便宜的结论。\n\n"
        "经营现金流为-4.53亿元，经营现金流/归母净利润为-12.51。销售收现率"
        "从79.43%下降到67.95%，说明销售回款与报表收入之间的差距在拉大，"
        "盈利转化成真金白银的能力依然很弱。\n\n"
        "PE TTM是按滚动十二个月利润计算，而动力新科刚告别亏损，滚动利润里很可能"
        "还夹杂着非经常性损益或前期亏损。资产负债率从74.90%下降到42.48%，"
        "不能据此确认偿债压力减轻。\n\n"
        "综合来看，现金流负向、卖货回款变慢、主营结构脆弱、盈利基数太薄这四条，"
        "意味着目前的低倍数还不能直接当成便宜。"
    )

    repaired = repair_valuation_review_answer(draft, evidence)

    assert repaired is not None
    assert repaired.startswith("截至 2026-07-29 收盘，动力新科的PE TTM约2.50倍")
    assert "PB约1.21倍" in repaired
    assert repaired.count("2026-07-29") == 1
    assert "同日同行口径：" not in repaired
    assert "利润极薄和近期刚扭亏造成" not in repaired
    assert "销售回款与报表收入之间的差距在拉大" not in repaired
    assert "真金白银" not in repaired
    assert "刚告别亏损" not in repaired
    assert "卖货回款变慢" not in repaired
    assert "盈利基数太薄" not in repaired
    assert "销售收现率下降但原因未确认" in repaired
    assert "滚动盈利分母仍待拆解" in repaired
    assert stock_specialist_relevance_issue(repaired, evidence) is None
    assert AgentService._validate_model_output(repaired, evidence)["passed"] is True


def test_valuation_review_repairs_v6_causal_cash_and_dynamic_pe_leaks():
    evidence, answer = _same_day_valuation_review_case()
    evidence["earnings_quality"]["comparable_report"] = {
        "debt_asset_ratio_pct": 74.9
    }
    evidence["earnings_quality"]["latest_report"]["parent_net_profit"] = (
        36_199_600.85
    )
    evidence["financial_drivers"]["cashflow_analysis"].update(
        {
            "cash_received_from_sales_to_revenue_pct": 67.95,
            "comparable_cash_received_from_sales_to_revenue_pct": 79.43,
        }
    )
    draft = answer + (
        "2026年一季报刚扭亏，归母净利润约3620万元，同比增长约1.17倍。"
        "经营现金流仍是净流出，利润增长尚未同步转化为现金回笼。"
        "销售商品收到的现金占营业收入的比例从79.43%下降到67.95%，"
        "显示当季现金回款比例在降低。"
        "当前低 PE TTM 主要是因为过去十二个月可能含有大额非经常性损益，"
        "动态市盈率55倍则反映了经常性盈利仍然偏薄。"
        "公司盈利在改善、资产负债率下降是积极线索，但仍需继续核验。"
    )

    repaired = repair_valuation_review_answer(draft, evidence)

    assert repaired is not None
    assert "同比增长约1.17倍" not in repaired
    assert "较上年同期实现扭亏" in repaired
    assert "尚未同步转化为现金回笼" not in repaired
    assert "经营现金流与利润方向相反" in repaired
    assert "显示当季现金回款比例在降低" not in repaired
    assert "这一比率变化的原因尚未确认" in repaired
    assert "主要是因为过去十二个月" not in repaired
    assert "动态市盈率55倍" not in repaired
    assert "资产负债率下降是积极线索" not in repaired
    assert "资产负债率下降则只是报表比率变化" in repaired
    assert "滚动盈利分母尚未拆解" in repaired
    assert stock_specialist_relevance_issue(repaired, evidence) is None
    assert AgentService._validate_model_output(repaired, evidence)["passed"] is True


def test_valuation_review_repairs_rich_first_draft_without_model_retry():
    evidence, answer = _same_day_valuation_review_case()
    draft = (
        "直接回答：进入估值约束候选不等于便宜。"
        "一季报扭亏，半年度预告延续盈利；这显示公司经营层面出现了方向性变化，"
        "而不仅是单季波动。资产负债率从74.90%降至42.48%，财务结构相较一年前"
        "有所收缩。"
        f"{answer}经营现金流/归母净利润为-12.51，说明本报告期净利润尚未转化为"
        "经营性现金净流入。低PE可能是利润基数偏低造成的。"
    )

    repaired = repair_valuation_review_answer(draft, evidence)

    assert repaired is not None
    assert "半年度预告延续盈利" not in repaired
    assert "方向性变化" not in repaired
    assert "财务结构相较一年前有所收缩" not in repaired
    assert "尚未转化为经营性现金净流入" not in repaired
    assert "低PE可能是利润基数偏低" not in repaired
    assert "持续性仍需核验" in repaired
    assert "不能据此判断负债绝对规模" in repaired
    assert "滚动盈利分母尚未拆解" in repaired
    assert "需核验扣非利润和非经常性损益明细" in repaired
    assert valuation_review_required_fact_issue(repaired, evidence) is None


def test_valuation_review_repair_adds_direct_answer_before_a_heading():
    evidence, _ = _same_day_valuation_review_case()
    draft = _valuation_review_local_overclaim_draft().replace(
        "动力新科进入估值约束候选不说明它便宜。",
        "**动力新科估值到底有多低**\n\n",
        1,
    )

    repaired = repair_valuation_review_answer(draft, evidence)

    assert repaired is not None
    assert repaired.startswith("动力新科进入估值约束候选，不等于它便宜。")
    assert valuation_review_required_fact_issue(repaired, evidence) is None
    assert AgentService._validate_model_output(repaired, evidence)["passed"] is True


def test_valuation_review_good_first_draft_completes_without_model_retry(
    tmp_path: Path, settings, monkeypatch
):
    evidence, _ = _same_day_valuation_review_case()
    answer = (
        _valuation_review_local_overclaim_draft()
        .replace("动力新科", "本标的")
        .replace("；本标的约为中位数的6%和54%。", "。")
        + "半年度业绩预告均预示扭亏持续。"
        "资产负债率下降，但未提供负债绝对额变化，尚不能确认财务结构是否真正改善。"
    )
    guarded_settings = replace(
        settings,
        workspace_root=tmp_path / "valuation-first-draft-workspaces",
        hermes_enabled=True,
    )
    database = Database(guarded_settings.workspace_root)
    database.initialize()
    user = database.create_user("Valuation First Draft User")
    service = AgentService(database, guarded_settings)
    calls = []

    def fake_stream(**kwargs):
        calls.append(kwargs.get("prompt_path"))
        return answer, {"model": "fake-deepseek", "streaming": {"enabled": True}}

    monkeypatch.setattr(service, "_execute_hermes_streaming", fake_stream)

    run = service.run(
        user=user,
        intent="stock_research",
        message=evidence["user_question"],
        evidence=evidence,
        model_tier="deep",
        execute_agent=True,
        stream_callback=lambda _event: None,
    )

    assert calls == [None]
    assert run["status"] == "completed"
    assert run["answer"].startswith("动力新科：")
    assert "预示扭亏持续" not in run["answer"]
    assert "本标的/中位数比值分别为" not in run["answer"]
    assert "relevance_retry" not in run["usage"]
    assert run["usage"]["relevance_repair"]["method"] == (
        "normalize_and_append_verified_valuation_facts_v1"
    )
    assert run["usage"]["output_guard"]["passed"] is True


def test_valuation_review_retry_failure_recovers_best_generated_draft(
    tmp_path: Path, settings, monkeypatch
):
    evidence, answer = _same_day_valuation_review_case()
    first_draft = answer.replace("数据日期为2026年7月29日收盘，", "") + (
        "低PE主要来自公司刚刚扭亏、利润规模很薄。"
    )
    guarded_settings = replace(
        settings,
        workspace_root=tmp_path / "valuation-best-draft-recovery-workspaces",
        hermes_enabled=True,
    )
    database = Database(guarded_settings.workspace_root)
    database.initialize()
    user = database.create_user("Valuation Best Draft Recovery User")
    service = AgentService(database, guarded_settings)
    calls = []
    real_repair = agent_module.repair_valuation_review_answer
    repair_calls = 0

    def fail_initial_local_repair(text, current_evidence):
        nonlocal repair_calls
        repair_calls += 1
        if repair_calls == 1:
            return None
        return real_repair(text, current_evidence)

    def fake_stream(**kwargs):
        calls.append(kwargs.get("prompt_path"))
        if len(calls) == 1:
            return first_draft, {
                "model": "fake-deepseek",
                "api_calls": 1,
                "streaming": {"enabled": True},
            }
        raise RuntimeError("retry transport failed")

    monkeypatch.setattr(
        agent_module,
        "repair_valuation_review_answer",
        fail_initial_local_repair,
    )
    monkeypatch.setattr(service, "_execute_hermes_streaming", fake_stream)

    run = service.run(
        user=user,
        intent="stock_research",
        message=evidence["user_question"],
        evidence=evidence,
        model_tier="deep",
        execute_agent=True,
        stream_callback=lambda _event: None,
    )

    assert len(calls) == 2
    assert calls[0] is None
    assert calls[1].name == "prompt.retry.md"
    assert run["status"] == "completed"
    assert "当前价格证据：" not in run["answer"]
    assert "低PE主要来自公司刚刚扭亏" not in run["answer"]
    assert run["usage"]["relevance_fallback"]["source"] == "initial"
    assert run["usage"]["relevance_fallback"]["passed"] is True
    assert run["usage"]["output_guard"]["passed"] is True
    run_dir = Path(run["workspace_path"]) / "runs" / run["id"]
    assert (run_dir / "answer.relevance_fallback.md").is_file()


def test_valuation_review_numeric_guard_repairs_only_the_bad_clause(
    tmp_path: Path, settings, monkeypatch
):
    evidence, answer = _same_day_valuation_review_case()
    evidence["earnings_quality"]["comparable_report"] = {
        "debt_asset_ratio_pct": 74.9
    }
    answer += (
        "资产负债率虽然下降但绝对水平仍在42%以上，仍需核对是否涉及资产重组或"
        "负债结构实质性变化。"
    )
    assert stock_specialist_relevance_issue(answer, evidence) is None
    assert AgentService._validate_model_output(answer, evidence)["passed"] is False

    guarded_settings = replace(
        settings,
        workspace_root=tmp_path / "valuation-final-normalization-workspaces",
        hermes_enabled=True,
    )
    database = Database(guarded_settings.workspace_root)
    database.initialize()
    user = database.create_user("Valuation Final Normalization User")
    service = AgentService(database, guarded_settings)
    calls = []

    def fake_stream(**kwargs):
        calls.append(kwargs.get("prompt_path"))
        return answer, {"model": "fake-deepseek", "streaming": {"enabled": True}}

    monkeypatch.setattr(service, "_execute_hermes_streaming", fake_stream)

    run = service.run(
        user=user,
        intent="stock_research",
        message=evidence["user_question"],
        evidence=evidence,
        model_tier="economy",
        execute_agent=True,
        stream_callback=lambda _event: None,
    )

    assert calls == [None]
    assert run["status"] == "completed"
    assert "42%以上" not in run["answer"]
    assert "资产重组" not in run["answer"]
    assert "valuation_normalization" not in run["usage"]
    assert run["usage"]["output_guard"]["repair"]["method"] == (
        "drop_unsupported_numeric_lines_v1"
    )
    assert run["usage"]["output_guard"]["passed"] is True


def test_valuation_review_preserves_a_valid_natural_first_draft(
    tmp_path: Path, settings, monkeypatch
):
    evidence, answer = _same_day_valuation_review_case()
    answer += "换句话说，低倍数值得继续研究，但现有证据还不能直接下低估结论。"
    guarded_settings = replace(
        settings,
        workspace_root=tmp_path / "valuation-natural-first-draft-workspaces",
        hermes_enabled=True,
    )
    database = Database(guarded_settings.workspace_root)
    database.initialize()
    user = database.create_user("Valuation Natural Draft User")
    service = AgentService(database, guarded_settings)

    monkeypatch.setattr(
        service,
        "_execute_hermes_streaming",
        lambda **_kwargs: (
            answer,
            {"model": "fake-deepseek", "streaming": {"enabled": True}},
        ),
    )

    run = service.run(
        user=user,
        intent="stock_research",
        message=evidence["user_question"],
        evidence=evidence,
        model_tier="economy",
        execute_agent=True,
        stream_callback=lambda _event: None,
    )

    assert run["status"] == "completed"
    assert run["answer"] == answer
    assert "valuation_normalization" not in run["usage"]
    assert "relevance_retry" not in run["usage"]
    assert run["usage"]["output_guard"]["passed"] is True


def test_valuation_review_repair_restores_dated_peer_context_after_local_cleanup():
    evidence, answer = _same_day_valuation_review_case()
    evidence["earnings_quality"]["comparable_report"] = {
        "debt_asset_ratio_pct": 74.901016
    }
    undated = answer.replace("不是。数据日期为2026年7月29日收盘，", "命中估值约束不等于便宜。")
    undated += (
        "资产负债率从上年同期74.9%下降。资产负债率虽然下降但绝对水平仍在42%以上，"
        "不能据此判断负债绝对规模。"
    )

    repaired = repair_valuation_review_answer(undated, evidence)

    assert repaired is not None
    assert "42%以上" not in repaired
    assert "74.90%" not in repaired
    assert "最新资产负债率为 42.48%，较可比期下降约 32.42 个百分点" in repaired
    assert repaired.startswith("截至 2026-07-29 收盘，")
    assert "同日同行口径：" not in repaired
    assert valuation_review_required_fact_issue(repaired, evidence) is None
    assert AgentService._validate_model_output(repaired, evidence)["passed"] is True


def test_numeric_guard_treats_from_ratio_as_absolute_transition_value():
    evidence = {
        "type": "stock_research",
        "earnings_quality": {
            "latest_report": {"debt_asset_ratio_pct": 42.480874},
            "comparable_report": {"debt_asset_ratio_pct": 74.901016},
            "drivers": [
                {
                    "key": "leverage",
                    "change_pp": -32.4201,
                }
            ],
        },
    }

    valid = AgentService._validate_model_output(
        "资产负债率从同期74.90%下降约32.42个百分点至42.48%。",
        evidence,
    )
    valid_after_heading = AgentService._validate_model_output(
        "**资产负债率下降，不等于负债减少** 最新资产负债率为42.48%，"
        "较可比期下降约32.42个百分点。",
        evidence,
    )
    invented = AgentService._validate_model_output(
        "资产负债率从同期76.90%下降约32.42个百分点至42.48%。",
        evidence,
    )

    assert valid["passed"] is True
    assert valid["unsupported_numbers"] == []
    assert valid_after_heading["passed"] is True
    assert valid_after_heading["unsupported_numbers"] == []
    assert invented["passed"] is False
    assert invented["unsupported_numbers"] == ["76.90%"]


def test_relative_industry_required_fact_check_uses_index_and_coverage():
    evidence = {
        "type": "stock_research",
        "user_question": "宁德时代相对电池行业是增强还是走弱？",
        "research_plan": {"focus": "relative_industry"},
        "stock_market_context": {
            "exact_industry_index": {
                "status": "same_market_date",
                "name": "中证电池产业指数",
                "return_1d_pct": -1.42,
                "stock_return_1d_pct": -2.29,
                "stock_minus_industry_pct": -0.87,
                "component_breadth": {
                    "status": "available",
                    "coverage": {"available_returns": 50, "constituents": 50},
                },
            }
        },
    }
    incomplete = (
        "宁德时代今天相对行业走弱，最重要的风险是中期价格仍弱，"
        "如果后续重新跑赢行业就会推翻当前判断。"
    )
    complete = (
        "中证电池产业指数同日收益-1.42%，宁德时代同日收益-2.29%，"
        "公司相对行业差值-0.87个百分点，属于相对走弱。行业成分有效收益覆盖"
        "50/50只。反方证据是单日差值不能代表中期趋势；如果后续同口径交易日"
        "相对差值反向并持续，当前判断将被推翻。"
    )

    assert "官方行业指数名称" in relative_industry_required_fact_issue(
        incomplete, evidence
    )
    assert relative_industry_required_fact_issue(complete, evidence) is None

    directional_wording = (
        complete.replace(
            "宁德时代同日收益-2.29%",
            "宁德时代同日下跌2.29%",
        )
        .replace(
            "中证电池产业指数同日收益-1.42%",
            "中证电池产业指数同日跌幅1.42%",
        )
        .replace(
            "公司相对行业差值-0.87个百分点",
            "公司跑输行业0.87个百分点",
        )
    )
    assert relative_industry_required_fact_issue(directional_wording, evidence) is None

    wrong_direction = directional_wording.replace(
        "宁德时代同日下跌2.29%",
        "宁德时代同日上涨2.29%",
    )
    assert "公司同日收益" in relative_industry_required_fact_issue(
        wrong_direction,
        evidence,
    )


def test_relative_industry_scope_cleanup_hides_unselected_module_gaps():
    evidence = {
        "display_name": "宁德时代",
        "research_plan": {"focus": "relative_industry"},
        "stock_market_context": {"exact_industry_index": {"subject_weight_pct": 9.477}},
    }
    answer = (
        "宁德时代相对CS电池指数增强0.54个百分点。\n"
        "宁德时代作为权重最大的第九个成分股表现出一定抗跌性。\n"
        "公司最新公告、结构化财务与估值数据尚未接入。\n"
        "反方证据是行业多数成分同日下跌。\n"
        "单纯一两日的反转不足以改变当前判断。\n"
        "若差值转负且持续多个交易日，就推翻当前判断。"
    )

    cleaned = AgentService._normalize_specialist_scope_language(answer, evidence)

    assert "增强0.54个百分点" in cleaned
    assert "尚未接入" not in cleaned
    assert "结构化财务" not in cleaned
    assert "反方证据" in cleaned
    assert "第九个成分股" not in cleaned
    assert "权重约9.48%" in cleaned
    assert "一两日" not in cleaned
    assert "持续多个交易日" not in cleaned
    assert "同日复权数据" in cleaned
    assert "后续交易日只形成新的同日判断" in cleaned


def test_relative_industry_prompt_evidence_keeps_index_and_drops_unrelated_bulk():
    evidence = {
        "type": "stock_research",
        "symbol": "300750.SZ",
        "display_name": "宁德时代",
        "user_question": "宁德时代相对电池行业是增强还是走弱？",
        "research_plan": {
            "focus": "relative_industry",
            "selected_modules": ["market", "analyst_expectations"],
            "selected_skills": ["online-stock-research"],
        },
        "metrics": {
            "latest_close": 390.86,
            "return_1d_pct": -2.285,
            "return_60d_pct": -12.1663,
            "volatility_20d_annualized_pct": 48.4048,
            "max_drawdown_60d_pct": -24.1826,
            "rsi_14": 59.7,
        },
        "research_frame": {"missing_information": ["公司最新公告尚未接入"]},
        "analyst_expectations": {
            "rating_counts": {"buy": 28},
            "forecast_eps": [{"fiscal_year": 2026, "value": 20.74}],
        },
        "fundamentals": {"summary": {"latest_report": {"revenue": 1}}},
        "stock_market_context": {
            "company_industry": "电池",
            "exact_industry_match_available": True,
            "exact_industry_index": {
                "status": "same_market_date",
                "index_code": "931719",
                "name": "CS电池",
                "return_1d_pct": -2.82,
                "stock_return_1d_pct": -2.285,
                "stock_minus_industry_pct": 0.535,
                "subject_weight_pct": 9.477,
                "component_breadth": {
                    "status": "available",
                    "advancers": 6,
                    "decliners": 44,
                    "unchanged": 0,
                    "median_pct_change": -2.2885,
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
                            "internal_reason": "provider_error",
                        }
                    ],
                },
            },
        },
    }

    compact = AgentService._compact_stock_research_evidence(evidence)

    index = compact["stock_market_context"]["exact_industry_index"]
    assert index["return_1d_pct"] == -2.82
    assert index["stock_return_1d_pct"] == -2.29
    assert index["stock_minus_industry_pct"] == 0.54
    assert index["subject_weight_pct"] == 9.48
    assert index["component_breadth"]["coverage"]["available_returns"] == 50
    assert index["component_breadth"]["source_fallbacks"][0]["name"] == "贝特瑞"
    assert "internal_reason" not in index["component_breadth"]["source_fallbacks"][0]
    assert "analyst_expectations" not in compact
    assert "fundamentals" not in compact
    assert "research_frame" not in compact
    assert "rsi_14" not in compact["metrics"]


def test_relative_industry_required_fact_accepts_index_name_spacing():
    evidence = {
        "type": "stock_research",
        "user_question": "宁德时代相对CS电池行业表现如何？",
        "research_plan": {"focus": "relative_industry"},
        "stock_market_context": {
            "exact_industry_index": {
                "status": "same_market_date",
                "name": "CS电池",
                "return_1d_pct": -2.82,
                "stock_return_1d_pct": -2.29,
                "stock_minus_industry_pct": 0.54,
                "component_breadth": {
                    "status": "available",
                    "coverage": {"available_returns": 50, "constituents": 50},
                },
            }
        },
    }
    answer = (
        "宁德时代相对 CS 电池增强：公司同日下跌2.29%，指数下跌2.82%，"
        "公司跑赢行业0.54个百分点，有效收益覆盖50/50只。"
        "反方证据是60日表现仍弱；若历史同日数据更正后差值转负，当前判断将被推翻。"
    )

    assert relative_industry_required_fact_issue(answer, evidence) is None


def test_relative_industry_near_miss_spread_is_repaired_without_regeneration():
    evidence = {
        "type": "stock_research",
        "display_name": "宁德时代",
        "user_question": "宁德时代相对CS电池行业表现如何？",
        "research_plan": {"focus": "relative_industry"},
        "stock_market_context": {
            "exact_industry_index": {
                "status": "same_market_date",
                "name": "CS电池",
                "return_1d_pct": -2.82,
                "stock_return_1d_pct": -2.29,
                "stock_minus_industry_pct": 0.54,
                "component_breadth": {
                    "status": "available",
                    "coverage": {"available_returns": 50, "constituents": 50},
                },
            }
        },
    }
    answer = (
        "宁德时代相对CS电池增强。公司同日下跌2.29%，指数下跌2.82%，"
        "个股跑赢行业0.53个百分点；成分有效收益覆盖50/50只。"
        "反方证据是60日表现仍弱，单日增强不能代表中期趋势。"
        "若历史同日数据更正后差值转负，当前判断将被推翻。"
    )

    repaired = repair_relative_industry_answer(answer, evidence)

    assert repaired is not None
    assert "跑赢行业0.54个百分点" in repaired
    assert relative_industry_required_fact_issue(repaired, evidence) is None


def test_relative_industry_unavailable_index_requires_honest_boundary():
    evidence = {
        "type": "stock_research",
        "display_name": "宁德时代",
        "user_question": "宁德时代相对CS电池行业是增强还是跟随？",
        "research_plan": {"focus": "relative_industry"},
        "stock_market_context": {
            "analysis_target": {"market_date": "2026-07-29"},
            "exact_industry_index": {
                "status": "unavailable_for_target_date",
                "name": "CS电池",
                "return_1d_pct": None,
                "stock_return_1d_pct": 1.53,
                "stock_minus_industry_pct": None,
                "component_breadth": {
                    "status": "available",
                    "market_date": "2026-07-29",
                    "median_pct_change": 2.0021,
                    "advancers": 41,
                    "decliners": 9,
                    "unchanged": 0,
                    "coverage": {"available_returns": 50, "constituents": 50},
                },
            },
        },
    }
    unsupported = (
        "宁德时代相对CS电池指数增强0.47个百分点，公司当日上涨1.53%。\n"
        "CS电池指数50只成分股全部取得有效收益，中位数上涨2.00%。\n"
        "反方证据是60日表现仍弱；若同日数据更正，当前判断需要改写。"
    )
    honest = (
        "宁德时代在2026年7月29日相对CS电池指数是增强还是走弱，当前不能确认："
        "公司当日上涨1.53%，但CS电池指数目标日官方收益尚未取得。"
        "行业成分有效收益覆盖50/50只，中位数上涨2.00%。"
        "反方边界是当前分布旁证不能直接等同于跑输行业；若复权数据更正，"
        "旁证需要改写。"
    )

    assert "不可用边界" in relative_industry_required_fact_issue(unsupported, evidence)
    assert relative_industry_required_fact_issue(honest, evidence) is None
    generated_style = (
        "目前不能确认宁德时代在2026年7月29日相对CS电池指数是增强还是走弱，"
        "公司当日上涨1.53%，指数官方收益尚未取得。"
        "同日50只成分股中41只上涨、9只下跌、0只平盘，中位数上涨2.00%；"
        "这只是分布旁证，不能直接等同于跑输行业。"
        "当前尚未形成正式的相对行业增强或走弱结论。"
        "反方边界是未复权数据可能影响分布；若复权数据更正，旁证需要改写。"
    )
    assert relative_industry_required_fact_issue(generated_style, evidence) is None
    natural_boundary_style = (
        "当前无法直接判定宁德时代相对CS电池指数是增强还是走弱，因为公司当日"
        "上涨1.53%，但CS电池指数目标日官方收益尚未取得。"
        "同日50只成分股中41只上涨、9只下跌、0只平盘，中位数上涨2.00%；"
        "这只是分布旁证，不能直接等同于跑输行业。"
        "反方边界是未复权数据可能影响分布；若复权数据更正，旁证需要改写。"
    )
    assert (
        relative_industry_required_fact_issue(natural_boundary_style, evidence) is None
    )
    conditional_completion_style = (
        natural_boundary_style + "若后续取得CS电池指数同日收益，且公司减指数差值为负，"
        "则当日判断应改为走弱。"
    )
    assert (
        relative_industry_required_fact_issue(conditional_completion_style, evidence)
        is None
    )
    distribution_boundary_style = (
        natural_boundary_style
        + "个股低于成分中位数只能描述分布位置，不能直接等同为相对指数走弱；"
        "在官方收益补齐前，无法升级为确切的相对增强、同步或走弱判断。"
    )
    assert (
        relative_industry_required_fact_issue(distribution_boundary_style, evidence)
        is None
    )
    zero_flat_may_be_omitted_style = (
        "当前不能确认宁德时代相对CS电池指数是增强还是走弱，公司上涨1.53%，"
        "但指数官方收益尚未取得。50只成分中41只上涨、9只下跌，"
        "中位数上涨2.00%；这只是分布旁证，不能直接等同为相对指数走弱。"
        "反方边界是未复权数据可能影响分布；若复权数据更正，旁证需要改写。"
    )
    assert (
        relative_industry_required_fact_issue(zero_flat_may_be_omitted_style, evidence)
        is None
    )
    natural_calculation_boundary_style = (
        zero_flat_may_be_omitted_style
        + "官方指数缺失时无法直接计算个股减指数差值，也不能据此断定相对指数走弱。"
    )
    assert (
        relative_industry_required_fact_issue(
            natural_calculation_boundary_style, evidence
        )
        is None
    )

    repaired = repair_relative_industry_answer(unsupported, evidence)
    assert repaired is not None
    assert repaired.startswith("宁德时代在2026-07-29相对CS电池")
    assert "当前不能确认" in repaired
    assert "目标日官方收益尚未取得" in repaired
    assert "0.47" not in repaired
    assert "相对CS电池指数增强" not in repaired
    assert relative_industry_required_fact_issue(repaired, evidence) is None


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


def test_hermes_text_routes_default_to_deepseek_v4_pro(monkeypatch):
    for tier in ("ECONOMY", "DEEP"):
        monkeypatch.delenv(f"HERMES_{tier}_PROVIDER", raising=False)
        monkeypatch.delenv(f"HERMES_{tier}_MODEL", raising=False)

    assert agent_module._resolve_hermes_route("economy") == (
        "deepseek",
        "deepseek-v4-pro",
    )
    assert agent_module._resolve_hermes_route("deep") == (
        "deepseek",
        "deepseek-v4-pro",
    )


def test_hermes_route_keeps_explicit_override_and_vision_route(monkeypatch):
    monkeypatch.setenv("HERMES_ECONOMY_PROVIDER", "custom-provider")
    monkeypatch.setenv("HERMES_ECONOMY_MODEL", "custom-model")
    monkeypatch.delenv("HERMES_VISION_PROVIDER", raising=False)
    monkeypatch.delenv("HERMES_VISION_MODEL", raising=False)

    assert agent_module._resolve_hermes_route("economy") == (
        "custom-provider",
        "custom-model",
    )
    assert agent_module._resolve_hermes_route("vision") == (None, None)


def test_hermes_output_budget_is_intent_aware_and_operator_tunable(monkeypatch):
    monkeypatch.delenv("HERMES_ECONOMY_MAX_TOKENS", raising=False)
    monkeypatch.delenv("HERMES_DEEP_MAX_TOKENS", raising=False)

    assert agent_module._hermes_max_tokens("market_brief", "economy") == 900
    assert agent_module._hermes_max_tokens("stock_research", "economy") == 1200
    assert agent_module._hermes_max_tokens("stock_research", "deep") == 2200

    monkeypatch.setenv("HERMES_ECONOMY_MAX_TOKENS", "700")
    assert agent_module._hermes_max_tokens("market_brief", "economy") == 700

    monkeypatch.setenv("HERMES_ECONOMY_MAX_TOKENS", "not-a-number")
    assert agent_module._hermes_max_tokens("market_brief", "economy") == 900


def test_hermes_reasoning_effort_keeps_standard_turns_faster(monkeypatch):
    monkeypatch.delenv("HERMES_ECONOMY_REASONING_EFFORT", raising=False)
    monkeypatch.delenv("HERMES_DEEP_REASONING_EFFORT", raising=False)

    assert agent_module._hermes_reasoning_effort("economy") == "low"
    assert agent_module._hermes_reasoning_effort("economy", "stock_research") == "none"
    assert agent_module._hermes_reasoning_effort("economy", "market_brief") == "none"
    assert (
        agent_module._hermes_reasoning_effort("economy", "business_structure") == "none"
    )
    assert agent_module._hermes_reasoning_effort("deep") == "medium"

    monkeypatch.setenv("HERMES_ECONOMY_REASONING_EFFORT", "none")
    assert agent_module._hermes_reasoning_effort("economy") == "none"

    monkeypatch.setenv("HERMES_ECONOMY_REASONING_EFFORT", "invalid")
    assert agent_module._hermes_reasoning_effort("economy") == "low"


def test_hermes_turn_budget_allows_completion_without_long_loops(monkeypatch):
    monkeypatch.delenv("HERMES_ECONOMY_MAX_ITERATIONS", raising=False)
    monkeypatch.delenv("HERMES_DEEP_MAX_ITERATIONS", raising=False)

    assert agent_module._hermes_max_iterations("economy") == 4
    assert agent_module._hermes_max_iterations("deep") == 6

    monkeypatch.setenv("HERMES_ECONOMY_MAX_ITERATIONS", "3")
    assert agent_module._hermes_max_iterations("economy") == 3

    monkeypatch.setenv("HERMES_ECONOMY_MAX_ITERATIONS", "1")
    assert agent_module._hermes_max_iterations("economy") == 2


def test_hermes_oneshot_fallback_disables_all_tools(
    tmp_path: Path, settings, monkeypatch
):
    hermes_bin = tmp_path / "hermes"
    hermes_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    hermes_bin.chmod(0o755)
    guarded_settings = replace(
        settings,
        workspace_root=tmp_path / "oneshot-no-tools-workspaces",
        hermes_bin=hermes_bin,
        hermes_enabled=True,
    )
    database = Database(guarded_settings.workspace_root)
    database.initialize()
    service = AgentService(database, guarded_settings)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    captured = {}

    class Result:
        returncode = 0
        stdout = "只返回研究文本"

    def fake_run(command, **kwargs):
        captured["command"] = command
        return Result()

    monkeypatch.setattr("app.services.agent_hermes_execution.subprocess.run", fake_run)

    answer, _ = service._execute_hermes(
        prompt="整理待确认任务，不要执行写入。",
        model_tier="economy",
        run_dir=run_dir,
        user_workspace=tmp_path,
        image_path=None,
    )

    assert answer == "只返回研究文本"
    toolsets_index = captured["command"].index("--toolsets")
    assert captured["command"][toolsets_index + 1] == "context_engine"


def test_market_brief_uses_compact_runtime_skill_without_removing_full_rules():
    skill_dir = agent_module.PROJECT_ROOT / "app" / "skills" / "market-brief"
    runtime_path = skill_dir / "PROMPT.md"
    full_path = skill_dir / "SKILL.md"

    assert runtime_path.exists()
    assert full_path.exists()
    assert AgentService._load_skill("market-brief") == runtime_path.read_text(
        encoding="utf-8"
    )
    assert runtime_path.stat().st_size < full_path.stat().st_size * 0.6


def test_market_knowledge_context_keeps_two_short_excerpts():
    compact = AgentService._compact_market_knowledge_context(
        {
            "query": "美股为什么跌",
            "coverage": {"count": 3},
            "items": [
                {
                    "title": f"资料{i}",
                    "excerpt": "证据" * 400,
                    "scope": "common",
                }
                for i in range(3)
            ],
        }
    )

    assert len(compact["items"]) == 2
    assert all(len(item["excerpt"]) <= 500 for item in compact["items"])


def test_market_knowledge_context_prefers_specific_market_rules():
    compact = AgentService._compact_market_knowledge_context(
        {
            "query": "那主要风险是什么",
            "items": [
                {"title": "清数智算证据层级", "excerpt": "通用"},
                {"title": "市场涨跌原因的证据规则", "excerpt": "原因"},
                {"title": "市场趋势与风险分析规则", "excerpt": "风险"},
            ],
        }
    )

    assert [item["title"] for item in compact["items"]] == [
        "市场涨跌原因的证据规则",
        "市场趋势与风险分析规则",
    ]


def test_stock_knowledge_context_prefers_user_material_and_limits_excerpts():
    compact = AgentService._compact_stock_knowledge_context(
        {
            "query": "中兴通讯为什么跌",
            "items": [
                {"title": "通用规则", "scope": "common", "excerpt": "甲" * 900},
                {"title": "用户研究", "scope": "user", "excerpt": "乙" * 900},
                {"title": "事件资料", "scope": "common", "excerpt": "丙" * 900},
                {"title": "多余资料", "scope": "common", "excerpt": "丁" * 900},
            ],
        }
    )

    assert len(compact["items"]) == 3
    assert compact["items"][0]["title"] == "用户研究"
    assert all(len(item["excerpt"]) <= 500 for item in compact["items"])


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


def test_numeric_guard_ignores_markdown_bold_list_ordinals() -> None:
    answer = (
        "跟你有直接关系的三点：\n\n"
        "**1. 购买渠道**\n场外基金通过销售渠道申赎。\n\n"
        "**2. 价格形成**\n场内ETF在交易时段有连续成交报价。\n\n"
        "- **3. 交易规则**\n到账与交收取决于具体产品和渠道。"
    )

    guard = AgentService._validate_model_output(
        answer,
        {"type": "general_research"},
    )

    assert guard["passed"] is True
    assert guard["unsupported_numbers"] == []


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


def test_streaming_stock_precision_matches_final_normalization(
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
        workspace_root=tmp_path / "stream-stock-precision-workspaces",
        hermes_bin=hermes_bin,
        hermes_enabled=True,
    )
    database = Database(guarded_settings.workspace_root)
    database.initialize()
    service = AgentService(database, guarded_settings)
    run_dir = tmp_path / "run-stock-precision"
    run_dir.mkdir()
    (run_dir / "prompt.md").write_text("测试个股数字精度", encoding="utf-8")
    raw_answer = (
        "宁德时代经营现金流/归母净利润从1.925降至1.391，"
        "销售收现率从124.618%降至94.773%。"
    )
    lines = [
        json.dumps(
            {"type": "delta", "text": raw_answer},
            ensure_ascii=False,
        )
        + "\n",
        json.dumps(
            {
                "type": "final",
                "answer": raw_answer,
                "usage": {"model": "fake-stream"},
            },
            ensure_ascii=False,
        )
        + "\n",
    ]
    monkeypatch.setattr(
        "app.services.agent_hermes_execution.subprocess.Popen",
        lambda *args, **kwargs: _FakeStreamingProcess(lines),
    )
    updates = []

    answer, usage = service._execute_hermes_streaming(
        model_tier="economy",
        run_dir=run_dir,
        user_workspace=tmp_path,
        evidence={
            "type": "stock_research",
            "symbol": "300750.SZ",
            "display_name": "宁德时代",
            "financial_drivers": {
                "cashflow_analysis": {
                    "operating_cashflow_to_net_profit": 1.391,
                    "comparable_operating_cashflow_to_net_profit": 1.925,
                    "cash_received_from_sales_to_revenue_pct": 94.773,
                    "comparable_cash_received_from_sales_to_revenue_pct": 124.618,
                }
            },
        },
        trusted_context=None,
        stream_callback=updates.append,
    )

    expected = (
        "宁德时代经营现金流/归母净利润从1.93降至1.39，销售收现率从124.62%降至94.77%。"
    )
    assert updates[-1]["draft"] == expected
    assert agent_module._normalize_stock_research_number_precision(answer) == expected
    assert usage["streaming"]["visible_events"] == 1


def test_quality_review_stream_guard_blocks_model_calculated_margin_range(
    tmp_path: Path, settings
):
    guarded_settings = replace(
        settings,
        workspace_root=tmp_path / "quality-margin-range-workspaces",
    )
    database = Database(guarded_settings.workspace_root)
    database.initialize()
    service = AgentService(database, guarded_settings)
    evidence = {
        "type": "stock_research",
        "symbol": "300750.SZ",
        "display_name": "宁德时代",
        "research_plan": {"focus": "quality_review"},
        "business_structure": {
            "dimensions": [
                {
                    "classification": "product",
                    "segments": [
                        {
                            "item_name": "动力电池系统",
                            "gross_margin_pct": 20.63,
                            "comparable_gross_margin_pct": 22.41,
                        },
                        {
                            "item_name": "储能电池系统",
                            "gross_margin_pct": 23.96,
                            "comparable_gross_margin_pct": 25.52,
                        },
                    ],
                }
            ]
        },
    }

    guard = service._validate_stream_output(
        "两个核心产品分部的毛利率同步下降约1.5至1.8个百分点。",
        evidence,
    )

    assert "1.5" in guard["unsupported_numbers"]
    assert service._stream_partial_guard_has_blocker(guard) is True


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

    valid = AgentService._validate_model_output("资讯标题显示道指约 -0.59%。", evidence)
    reversed_direction = AgentService._validate_model_output(
        "资讯标题显示道指约 +0.59%。", evidence
    )

    assert valid["passed"] is True
    assert reversed_direction["passed"] is False
    assert "+0.59%" in reversed_direction["unsupported_numbers"]


def test_numeric_guard_accepts_one_decimal_percentage_rounding():
    evidence = {
        "type": "market_brief",
        "indices": [{"name": "标普500", "metrics": {"return_60d_pct": 4.2783}}],
    }

    valid = AgentService._validate_model_output("标普500近60日约 +4.3%。", evidence)
    invalid = AgentService._validate_model_output("标普500近60日约 +4.4%。", evidence)

    assert valid["passed"] is True
    assert invalid["passed"] is False
    assert "+4.4%" in invalid["unsupported_numbers"]


def test_numeric_guard_accepts_approximate_integer_percentage_wording():
    evidence = {
        "type": "stock_research",
        "symbol": "000065.SZ",
        "fundamentals": {"summary": {"latest_report": {"revenue_yoy_pct": -35.564822}}},
    }

    valid = AgentService._validate_model_output(
        "北方国际一季度营收同比下滑超过35%。",
        evidence,
    )
    invented = AgentService._validate_model_output(
        "北方国际一季度营收同比下滑超过37%。",
        evidence,
    )

    assert valid["passed"] is True
    assert invented["passed"] is False
    assert invented["unsupported_numbers"] == ["37%"]


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
        workspace_root=tmp_path / "workspaces-guard-repair",
        hermes_enabled=True,
    )
    database = Database(guarded_settings.workspace_root)
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


def test_trade_review_json_drops_only_unsupported_numeric_clauses(
    tmp_path: Path, settings, monkeypatch
):
    guarded_settings = replace(
        settings,
        workspace_root=tmp_path / "workspaces-trade-review-guard-repair",
        hermes_enabled=True,
    )
    database = Database(guarded_settings.workspace_root)
    database.initialize()
    user = database.create_user("Trade Review Guard Repair User")
    service = AgentService(database, guarded_settings)
    model_answer = json.dumps(
        {
            "logic_result": (
                "操作前一日振幅约6.3%，这一计算没有直接写入冻结证据。"
                "关键经营证据在操作时仍待核验，后续价格变化不能单独证明逻辑正确。"
            ),
            "plan_deviation": "实际操作与计划方向一致，但证据核验步骤尚未完成。",
            "bias_tags": ["行动偏差"],
            "improvement_text": "下次先记录证据核验节点，再由用户确认复盘。",
        },
        ensure_ascii=False,
    )
    monkeypatch.setattr(
        service,
        "_execute_hermes",
        lambda **kwargs: (model_answer, {"model": "fake"}),
    )

    run = service.run(
        user=user,
        intent="trade_review",
        message="复盘这次操作",
        evidence={"type": "trade_review"},
        model_tier="economy",
        execute_agent=True,
    )

    assert run["status"] == "completed"
    assert "6.3%" not in run["answer"]
    assert "关键经营证据" in run["answer"]
    assert json.loads(run["answer"])["bias_tags"] == ["行动偏差"]
    assert run["usage"]["output_guard"]["repair"]["method"] == (
        "drop_unsupported_trade_review_clauses_v1"
    )


def test_output_guard_accepts_numbers_from_prior_guarded_assistant_answer():
    evidence = {
        "type": "market_brief",
        "generated_at": "2026-07-21T04:43:15+00:00",
        "indices": [{"name": "上证综指", "metrics": {"return_1d_pct": 0.62}}],
    }
    answer = "上证综指当日上涨 0.62%。市场资讯沿用上一轮已核验时点：2026-07-21T04:41Z。"
    prior_assistant_answer = "市场资讯截至 2026-07-21T04:41Z；以上只描述当前截面。"

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
        workspace_root=tmp_path / "workspaces-guard-user-history",
        hermes_enabled=True,
    )
    database = Database(guarded_settings.workspace_root)
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
        workspace_root=tmp_path / "workspaces-guard-assistant-history",
        hermes_enabled=True,
    )
    database = Database(guarded_settings.workspace_root)
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
                "sample_size": 26,
                "positive_count": 5,
                "negative_count": 0,
                "neutral_count": 21,
            }
        },
    }

    valid = AgentService._validate_model_output(
        "股吧社区情绪为轻微偏多，但只能作为弱证据。", evidence
    )
    invalid = AgentService._validate_model_output(
        "社区讨论情绪转负，这解释了下跌。", evidence
    )
    negated = AgentService._validate_model_output(
        "社区样本轻微偏多，无明确负面声音，但只能作为弱证据。", evidence
    )
    explicit_counts = AgentService._validate_model_output(
        "社区样本中5条偏多、0条偏空、21条中性，"
        "没有出现集中的负面声音，但仍只是弱证据。",
        evidence,
    )

    assert valid["passed"] is True
    assert valid["semantic_conflicts"] == []
    assert negated["passed"] is True
    assert negated["semantic_conflicts"] == []
    assert explicit_counts["passed"] is True
    assert explicit_counts["semantic_conflicts"] == []
    assert invalid["passed"] is False
    assert invalid["semantic_conflicts"] == ["社区情绪方向与证据不一致：证据为轻微偏多"]


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
        "hot_sectors": {"sectors": [{"name": "电力行业", "pct_change": 2.34}]},
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
    assert (
        agent_module._LI_ZONG_RULE_BOTTLENECK_LABEL
        in guard["unsupported_market_inferences"]
    )
    assert (
        agent_module._STOCK_OBSERVATION_WINDOW_LABEL
        in guard["unsupported_market_inferences"]
    )
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


def test_li_zong_multi_symbol_normalization_hides_provider_quota_error():
    evidence = {
        "type": "stock_screen",
        "profile": {"key": "li_zong", "label": "李总策略"},
        "selection_mode": "symbol_comparison",
        "requested_symbols": ["001391.SZ"],
        "items": [
            {
                "name": "国货航",
                "internal_symbol": "001391.SZ",
                "status": "data_incomplete",
                "as_of_date": "2026-07-22",
                "rule_results": [
                    {
                        "rule_id": "LZ-C-01",
                        "status": "data_incomplete",
                        "limitations": ["最近一年完整交易日不足。"],
                    }
                ],
                "limitations": ["上市后量价历史预判未达到策略最小窗口。"],
            }
        ],
        "strategy": {
            "version": {
                "rules": [{"rule_id": "LZ-C-01", "label": "近一年至少6次收盘涨停"}]
            }
        },
        "data_meta": {
            "latest_completed_trade_date": "2026-07-22",
            "universe_count": 5530,
            "evaluated_symbols": 5300,
            "coverage_ratio": 5300 / 5530,
            "deep_check_eligible_count": 1169,
            "deep_processed_symbols": 896,
            "deep_remaining_symbols": 273,
            "deep_processing_ratio": 896 / 1169,
            "history_insufficient_count": 47,
            "history_unknown_count": 153,
            "actionable_candidate_count": 0,
            "deep_check_complete": False,
        },
        "boundary": "不构成买卖建议。",
    }
    raw_error = (
        "HTTP 403: You've reached your usage limit for this billing cycle. "
        "Upgrade your plan: https://www.kimi.com/code/#pricing"
    )

    normalized = AgentService._normalize_li_zong_symbol_answer(raw_error, evidence)

    assert "国货航（001391.SZ）" in normalized
    assert "HTTP 403" not in normalized
    assert "kimi.com" not in normalized


def test_li_zong_normalization_repairs_candidate_trigger_conflation():
    evidence = {
        "type": "stock_screen",
        "profile": {"key": "li_zong", "label": "李总策略"},
        "selection_mode": "symbol_check",
    }
    answer = (
        "若近十日窗口内不再包含两根5%阴线，该规则可能转为通过，"
        "但能否重新进入候选还需同时满足盘后触发等条件。"
    )

    normalized = AgentService._normalize_li_zong_candidate_trigger_boundary(
        answer,
        evidence,
    )

    assert "还需同时满足盘后触发" not in normalized
    assert "9条候选规则在同一数据日全部通过" in normalized
    assert "触发规则只决定候选形成后的人工复核层级" in normalized
    assert "不是进入候选的附加条件" in normalized


def test_li_zong_normalization_repairs_trigger_before_candidate_wording():
    evidence = {
        "type": "stock_screen",
        "profile": {"key": "li_zong", "label": "李总策略"},
        "selection_mode": "symbol_check",
    }
    answer = (
        "是的。即使该规则转为通过，仍需同时满足盘后触发条件，"
        "才能被标记为候选。盘后触发是复核启动的必要前提。"
    )

    normalized = AgentService._normalize_li_zong_candidate_trigger_boundary(
        answer,
        evidence,
    )

    assert not normalized.startswith("是的")
    assert "仍需同时满足盘后触发" not in normalized
    assert "盘后触发是复核启动的必要前提" not in normalized
    assert normalized.count("不是进入候选的附加条件") == 1


def test_li_zong_normalization_does_not_publish_raw_trigger_shape_before_candidate():
    evidence = {
        "type": "stock_screen",
        "profile": {"key": "li_zong", "label": "李总策略"},
        "selection_mode": "symbol_check",
        "items": [
            {
                "status": "not_qualified",
                "candidate_qualified": False,
                "triggered_rule_ids": [],
            }
        ],
    }
    answer = "当日收盘涨停触发，但候选规则尚未全部通过，所以当前不会进入人工复核。"

    normalized = AgentService._normalize_li_zong_candidate_trigger_boundary(
        answer,
        evidence,
    )

    assert "当日收盘涨停触发" not in normalized
    assert "当日收盘涨停形态条件匹配" in normalized
    assert "不形成触发事件" in normalized


def test_li_zong_multi_symbol_preview_hides_internal_status_and_cleans_punctuation():
    evidence = {
        "type": "stock_screen",
        "profile": {"key": "li_zong", "label": "李总策略"},
        "selection_mode": "symbol_comparison",
        "requested_symbols": ["600777.SS"],
        "items": [
            {
                "name": "新潮能源",
                "internal_symbol": "600777.SS",
                "status": "data_incomplete",
                "rule_results": [],
                "limitations": [
                    "已存在明确不通过规则，同时仍有数据缺口；在关键缺口补齐前按数据不完整处理。",
                    "关键数据集或规则窗口不完整，服务层强制保持 data_incomplete。",
                ],
            }
        ],
        "strategy": {"version": {"rules": []}},
        "data_meta": {
            "latest_completed_trade_date": "2026-07-22",
            "universe_count": 5530,
            "evaluated_symbols": 5350,
            "coverage_ratio": 5350 / 5530,
            "deep_check_eligible_count": 1169,
            "deep_processed_symbols": 912,
            "deep_remaining_symbols": 257,
            "deep_processing_ratio": 912 / 1169,
            "history_insufficient_count": 47,
            "history_unknown_count": 153,
            "actionable_candidate_count": 0,
            "deep_check_complete": False,
        },
        "boundary": "不构成买卖建议。",
    }

    preview = AgentService._render_li_zong_preview(evidence)

    assert "新潮能源（600777.SS）" in preview
    assert "data_incomplete" not in preview
    assert "not_qualified" not in preview
    assert "服务层强制" not in preview
    assert "。；" not in preview
    assert preview.count("按数据不完整处理") == 1


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
    incomplete = AgentService._validate_model_output(
        "No reply: the maximum tool-iteration limit was reached.", evidence
    )

    assert public_evidence["market_state"]["label"] == "承压"
    assert public_evidence["hot_sectors"]["sectors"][0]["pct_change"] == 2.34
    assert "source" not in public_evidence
    assert "source_url" not in public_evidence
    assert "warnings" not in public_evidence
    assert "degraded_from" not in public_evidence["hot_sectors"]
    assert guarded["passed"] is False
    assert guarded["private_operational_patterns"]
    assert incomplete["passed"] is False
    assert incomplete["private_operational_patterns"]


def test_output_guard_preserves_financial_upstream_wording_but_blocks_ops_context():
    evidence = {"type": "stock_research", "symbol": "601138.SS"}

    financial = AgentService._validate_model_output(
        "反方证据是产业链上游的资金占用增加，仍需核验应付款与合同负债。",
        evidence,
    )
    operational = AgentService._validate_model_output(
        "上游接口不可用，系统已降级处理。",
        evidence,
    )

    assert financial["passed"] is True
    assert financial["private_operational_patterns"] == []
    assert operational["passed"] is False
    assert operational["private_operational_patterns"]


def test_failed_model_guard_falls_back_to_deterministic_preview(
    tmp_path: Path, settings, monkeypatch
):
    guarded_settings = replace(
        settings,
        workspace_root=tmp_path / "workspaces-guard",
        hermes_enabled=True,
    )
    database = Database(guarded_settings.workspace_root)
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
    guard_path = Path(run["workspace_path"]) / "runs" / run["id"] / "output_guard.json"
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
                "subject": {"business_profile": {"anchor_report_date": "2025-12-31"}},
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
                        "business_profile": {"anchor_report_date": "2025-12-31"},
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
    assert (
        compact["fundamentals"]["summary"]["latest_report"]["net_profit_yoy_pct"]
        == -46.58
    )
    assert compact["peer_comparison"]["group_label"] == "通信设备固定同行"
    assert (
        compact["peer_comparison"]["operating_comparison"]["metrics"][
            "gross_margin_pct"
        ]["peer_sample_size"]
        == 3
    )
    assert (
        compact["peer_comparison"]["operating_comparison"]["peers"][0][
            "business_profile"
        ]["anchor_report_date"]
        == "2025-12-31"
    )


def test_stock_cause_prompt_drops_noncausal_bulk_and_duplicate_provenance():
    evidence = {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "user_question": "中兴通讯7月24日为什么大跌？只使用同日公司公告和新闻。",
        "conditional_outlook": {
            "label": "偏弱观察",
            "calibration": {"samples": ["x" * 1000]},
        },
        "research_claims": {
            "status": "available",
            "claims": [
                {
                    "relation": relation,
                    "claim": f"主张{i}",
                    "evidence_summary": "摘要",
                    "source_url": "https://example.invalid/very-long",
                    "source_key": "internal-source",
                    "next_step": "核验原文",
                }
                for i, relation in enumerate(["supports", "weakens", "unresolved"] * 4)
            ],
        },
        "stock_market_context": {
            "analysis_target": {"market_date": "2026-07-24"},
            "indices": [{"name": f"指数{i}"} for i in range(8)],
            "exact_industry_index": {
                "status": "same_market_date",
                "name": "通信设备",
                "component_breadth": {
                    "status": "available",
                    "advancers": 3,
                    "decliners": 47,
                },
                "component_contribution": {"items": ["x" * 1000]},
                "source_url": "https://example.invalid/index",
            },
            "market_breadth": {
                "status": "available",
                "market_date": "2026-07-24",
                "same_date_as_target": True,
                "distribution": {
                    "median_pct_change": -0.5,
                    "bins": ["x" * 1000],
                    "bin_ratios": [0.5],
                }
            },
        },
        "a_share_information": {
            "announcements": [
                {
                    "title": "同日盘中公告",
                    "published_at": "2026-07-24T14:00:00+08:00",
                    "source": "深交所",
                    "summary": "公司公告原文摘录：公司披露本次合同金额及履约期限。",
                },
                {
                    "title": "前一日公告",
                    "published_at": "2026-07-23T18:00:00+08:00",
                    "source": "深交所",
                },
            ],
            "news": [
                {
                    "title": "同日盘中媒体线索",
                    "published_at": "2026-07-24T13:30:00+08:00",
                    "source": "媒体甲",
                },
                {
                    "title": "同日收盘后报道",
                    "published_at": "2026-07-24T19:30:00+08:00",
                    "source": "媒体甲",
                },
            ],
        },
        "event_timeline": {
            "events": [
                {
                    "title": "同日盘中媒体线索",
                    "event_date": "2026-07-24",
                    "published_at": "2026-07-24T13:30:00+08:00",
                    "source": "媒体甲",
                    "evidence_level": "media_report",
                }
            ]
        },
    }

    compact = AgentService._compact_stock_research_evidence(evidence)

    assert "conditional_outlook" not in compact
    assert "research_claims" not in compact
    assert "a_share_information" not in compact
    assert "event_timeline" not in compact
    assert len(compact["stock_market_context"]["indices"]) == 2
    assert (
        "component_contribution"
        not in compact["stock_market_context"]["exact_industry_index"]
    )
    assert "turnover" not in compact["stock_market_context"]["market_breadth"]
    assert "distribution" not in compact["stock_market_context"]["market_breadth"]
    packet = compact["price_move_event_evidence"]
    assert packet["target_market_date"] == "2026-07-24"
    assert packet["strict_same_date_only"] is True
    assert packet["coverage_status"] == "same_date_official_disclosure"
    assert [item["title"] for item in packet["same_date_official_disclosures"]] == [
        "同日盘中公告"
    ]
    assert packet["same_date_official_disclosures"][0]["direct_excerpt"] == (
        "公司披露本次合同金额及履约期限。"
    )
    assert [item["title"] for item in packet["same_date_media_clues"]] == [
        "同日盘中媒体线索"
    ]
    assert [item["title"] for item in packet["same_date_after_close_events"]] == [
        "同日收盘后报道"
    ]
    assert [item["title"] for item in packet["adjacent_date_events"]] == ["前一日公告"]
    assert packet["same_date_media_source_count"] == 1


def test_stock_price_move_prompt_drops_cross_date_market_breadth():
    compact = AgentService._compact_stock_research_evidence(
        {
            "type": "stock_research",
            "symbol": "000065.SZ",
            "user_question": "北方国际7月30日为什么跌？",
            "stock_market_context": {
                "analysis_target": {"market_date": "2026-07-30"},
                "indices": [
                    {
                        "symbol": "399001.SZ",
                        "name": "深证成指",
                        "comparison_status": "same_market_date",
                        "market_date": "2026-07-30",
                        "return_1d_pct": -2.73,
                    },
                    {
                        "symbol": "000688.SS",
                        "name": "科创50",
                        "comparison_status": "same_market_date",
                        "market_date": "2026-07-30",
                        "return_1d_pct": -5.38,
                    },
                    {
                        "symbol": "399006.SZ",
                        "name": "创业板指",
                        "comparison_status": "cross_date",
                        "market_date": "2026-07-31",
                        "return_1d_pct": 3.0,
                    },
                ],
                "exact_industry_match_available": False,
                "exact_industry_index": {
                    "status": "unavailable_for_target_date",
                },
                "market_breadth": {
                    "status": "available",
                    "market_date": "2026-07-31",
                    "same_date_as_target": False,
                    "breadth": {
                        "advancers": 700,
                        "decliners": 4700,
                    },
                },
            },
        }
    )

    context = compact["stock_market_context"]
    assert "market_breadth" not in context
    assert [item["symbol"] for item in context["indices"]] == [
        "399001.SZ",
        "000688.SS",
    ]


def test_mixed_stock_prompt_compacts_duplicate_financial_and_market_context():
    evidence = {
        "type": "stock_research",
        "symbol": "000065.SZ",
        "user_question": "回撤与财务、现金流和公司事件有什么关系？",
        "research_plan": {"focus": "mixed"},
        "stock_market_context": {
            "indices": [
                {"name": f"指数{i}", "metrics": {"latest_close": i}} for i in range(4)
            ],
            "market_breadth": {"breadth": {"total": 5000}},
        },
        "evidence_debate": {
            "bull_case": ["支持" * 100],
            "bear_case": ["反方" * 100],
        },
        "research_claims": {
            "status": "available",
            "claims": [
                {
                    "relation": "weakens",
                    "claim": "营收承压",
                    "evidence_summary": "同比下降",
                }
            ],
        },
        "fundamentals": {
            "valuation": {"pe_ttm": 15.98},
            "summary": {
                "latest_report": {
                    "report_date": "2026-03-31",
                    "revenue_yoy_pct": -35.56,
                    "operating_cashflow": 216477658.72,
                    "unused_field": "x" * 1000,
                },
                "latest_annual_report": {"unused_field": "y" * 1000},
                "facts": [{"statement": "z" * 1000}],
                "operating_cashflow_to_net_profit": 1.96,
            },
        },
        "earnings_quality": {
            "latest_report": {
                "report_date": "2026-03-31",
                "revenue_yoy_pct": -35.56,
                "unused_field": "x" * 1000,
            },
            "comparable_report": {
                "report_date": "2025-03-31",
                "revenue_yoy_pct": -27.22,
                "unused_field": "x" * 1000,
            },
            "factors": [
                {
                    "key": "cashflow",
                    "label": "现金流覆盖",
                    "status": "support",
                    "interpretation": "接近2倍",
                    "unused_field": "x" * 1000,
                }
            ],
        },
        "financial_drivers": {
            "latest_period": {
                "report_date": "2026-03-31",
                "revenue_growth_pct": -35.56,
                "unused_field": "x" * 1000,
            },
            "comparable_period": {
                "report_date": "2025-03-31",
                "unused_field": "x" * 1000,
            },
            "expense_analysis": [{"unused_field": "x" * 2000}],
            "working_capital_analysis": [{"unused_field": "x" * 2000}],
            "confirmed_mechanical_drivers": [
                {
                    "key": "finance_expense",
                    "label": "财务费用变化",
                    "amount": -96755056.24,
                    "direction": "negative",
                    "statement": "财务费用同比增加。",
                }
            ],
            "cashflow_analysis": {
                "operating_cashflow": 216477658.72,
                "operating_cashflow_to_net_profit": 1.96,
                "unused_field": "x" * 1000,
            },
        },
    }

    compact = AgentService._compact_stock_research_evidence(evidence)

    assert "stock_market_context" not in compact
    assert "evidence_debate" not in compact
    assert "valuation" not in compact["fundamentals"]
    assert "latest_annual_report" not in compact["fundamentals"]["summary"]
    assert "unused_field" not in compact["earnings_quality"]["latest_report"]
    assert "expense_analysis" not in compact["financial_drivers"]
    assert "working_capital_analysis" not in compact["financial_drivers"]
    assert compact["financial_drivers"]["cashflow_analysis"] == {
        "operating_cashflow": 216477658.72,
        "operating_cashflow_to_net_profit": 1.96,
    }


def test_stock_cause_prompt_limits_headlines_without_changing_full_ui_evidence():
    evidence = {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "user_question": "中兴通讯7月24日为什么下跌？只使用同日事实。",
        "stock_market_context": {"analysis_target": {"market_date": "2026-07-24"}},
        "a_share_information": {
            "news": [
                {
                    "title": f"同日媒体线索{i}",
                    "published_at": f"2026-07-24T{10 + i}:00:00+08:00",
                    "source": f"媒体{i}",
                }
                for i in range(5)
            ]
        },
    }

    compact = AgentService._compact_stock_research_evidence(evidence)

    assert len(compact["price_move_event_evidence"]["same_date_media_clues"]) == 3
    assert len(evidence["a_share_information"]["news"]) == 5


def test_stock_cause_prompt_excludes_low_signal_financing_and_record_date_headlines():
    evidence = {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "user_question": "中兴通讯今天为什么跌？",
        "stock_market_context": {"analysis_target": {"market_date": "2026-07-28"}},
        "a_share_information": {
            "news": [
                {
                    "title": "中兴通讯7月27日获融资买入5.41亿元，融资余额处于高位",
                    "published_at": "2026-07-28T09:06:00+08:00",
                    "source": "媒体甲",
                },
                {
                    "title": "12股今日股权登记，中兴通讯分红力度居前",
                    "published_at": "2026-07-28T08:05:00+08:00",
                    "source": "媒体甲",
                },
            ]
        },
    }

    compact = AgentService._compact_stock_research_evidence(evidence)
    packet = compact["price_move_event_evidence"]

    assert packet["same_date_media_clues"] == []
    assert packet["same_date_media_source_count"] == 0
    assert packet["same_date_low_signal_background_count"] == 2
    assert packet["coverage_status"] == "same_date_low_signal_background_only"
    assert len(evidence["a_share_information"]["news"]) == 2


def test_stock_cause_preview_uses_aligned_events_and_omits_unasked_bulk():
    evidence = {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "display_name": "中兴通讯",
        "user_question": (
            "中兴通讯7月24日为什么下跌？只使用同日公司公告、行业和市场事实。"
        ),
        "metrics": {"latest_close": 35.0, "return_1d_pct": -2.56},
        "current_quote": {
            "price": 35.0,
            "pct_change": -2.56,
            "currency": "CNY",
            "market_date": "2026-07-24",
            "market_timestamp": "2026-07-24T16:14:00+08:00",
        },
        "provenance": {"market_timestamp": "2026-07-24T01:30:00+00:00"},
        "stock_market_context": {
            "analysis_target": {
                "market_date": "2026-07-24",
                "basis": "explicit_question_date",
            },
            "stock_target": {
                "status": "same_market_date",
                "market_date": "2026-07-24",
                "close": 35.0,
                "return_1d_pct": -2.56,
            },
            "market_state": {"summary": "代表性指数全部下跌。"},
            "indices": [
                {
                    "name": "沪深300",
                    "comparison_status": "same_market_date",
                    "return_1d_pct": -1.67,
                }
            ],
            "market_breadth": {
                "same_date_as_target": True,
                "breadth": {
                    "advancers": 555,
                    "decliners": 4939,
                    "unchanged": 36,
                    "state": "普跌",
                },
            },
            "exact_industry_match_available": True,
            "exact_industry_index": {
                "status": "same_market_date",
                "name": "通信设备",
                "return_1d_pct": -3.54,
                "stock_return_1d_pct": -2.56,
                "stock_minus_industry_pct": 0.98,
                "constituent_count": 50,
                "component_breadth": {
                    "status": "available",
                    "advancers": 3,
                    "decliners": 47,
                    "unchanged": 0,
                    "state": "普跌",
                    "median_pct_change": -3.4,
                    "coverage": {},
                },
                "component_contribution": {
                    "status": "available",
                    "subject": {
                        "name": "中兴通讯",
                        "estimated_contribution_pp": -0.1,
                    },
                },
            },
        },
        "a_share_information": {
            "announcements": [
                {
                    "title": "前一日公司公告",
                    "published_at": "2026-07-23T18:00:00+08:00",
                    "source": "深交所",
                }
            ],
            "news": [
                {
                    "title": "盘中同日媒体线索",
                    "published_at": "2026-07-24T13:30:00+08:00",
                    "source": "媒体甲",
                },
                {
                    "title": "收盘后同日报道",
                    "published_at": "2026-07-24T19:30:00+08:00",
                    "source": "媒体甲",
                },
            ],
            "sentiment": {
                "band": "偏空",
                "sample_size": 20,
                "confidence": "low_to_medium",
            },
        },
    }

    preview = AgentService._render_preview(evidence)

    assert "盘中同日媒体线索" in preview
    assert "发布时间晚于当日收盘" in preview
    assert "前一日公司公告" not in preview
    assert "静态估算贡献" not in preview
    assert "社区情绪" not in preview
    assert "没有同日公司公告" in preview
    assert "具体驱动未确认" in preview


def test_stock_cause_guard_rejects_ruling_out_company_specific_driver():
    evidence = {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "user_question": "中兴通讯7月24日为什么跌？",
        "metrics": {"latest_close": 35.0, "return_1d_pct": -2.56},
        "stock_market_context": {
            "analysis_target": {"market_date": "2026-07-24"},
            "exact_industry_index": {
                "status": "same_market_date",
                "stock_minus_industry_pct": 0.98,
                "component_breadth": {"status": "available"},
            },
        },
    }

    guard = AgentService._validate_model_output(
        "中兴通讯当日下跌2.56%，但跑赢行业，这表明并没有独立于市场的个股驱动信号。",
        evidence,
    )

    assert guard["passed"] is False
    assert (
        "缺少事件或业务证据时不能用技术指标行业轮动或业务结构解释个股涨跌"
        in guard["unsupported_market_inferences"]
    )


def test_stock_cause_guard_rejects_media_sentiment_labels_and_unpublished_checks():
    evidence = {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "user_question": "中兴通讯7月24日为什么跌？",
        "metrics": {"latest_close": 35.0, "return_1d_pct": -2.56},
        "stock_market_context": {
            "analysis_target": {"market_date": "2026-07-24"},
            "exact_industry_index": {"component_breadth": {"status": "available"}},
        },
    }

    guard = AgentService._validate_model_output(
        "媒体标题涉及正面或中性话题。仍需核验当日是否有未公开订单或机构仓位变动。",
        evidence,
    )

    assert guard["passed"] is False
    assert (
        "公告或媒体线索不能在缺少事件研究时评为正面负面或催化"
        in guard["unsupported_market_inferences"]
    )
    assert (
        "缺少事件或业务证据时不能用技术指标行业轮动或业务结构解释个股涨跌"
        in guard["unsupported_market_inferences"]
    )


def test_stock_cause_guard_rejects_indirect_media_sentiment_wording():
    evidence = {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "user_question": "中兴通讯7月24日为什么跌？",
        "metrics": {"latest_close": 35.0, "return_1d_pct": -2.56},
        "stock_market_context": {
            "analysis_target": {"market_date": "2026-07-24"},
            "exact_industry_index": {"component_breadth": {"status": "available"}},
        },
    }
    answer = (
        "中兴通讯7月24日收盘35元，跌2.56%。"
        "个股与行业同日下跌，但相对表现只能确认同步或分化，不能证明具体原因。"
        "已确认的是价格下跌，具体公司驱动仍未取得同日官方披露确认。"
        "一条媒体报道可能被市场视为负面，但仍需核验。"
        "其余媒体线索方向不一，无法构成一致的解释方向。"
        "公司层面未出现同日公告或可确认的利空事件。"
        "后续只核验交易所公告、监管文件、公司原文和公开行情。"
    )

    guard = AgentService._validate_model_output(answer, evidence)
    repaired = AgentService._repair_guard_failure(answer, evidence, guard)

    assert guard["passed"] is False
    assert (
        "公告或媒体线索不能在缺少事件研究时评为正面负面或催化"
        in guard["unsupported_market_inferences"]
    )
    assert repaired is not None
    assert repaired[1]["passed"] is True
    assert "视为负面" not in repaired[0]
    assert "方向不一" not in repaired[0]
    assert "解释方向" not in repaired[0]
    assert "未出现同日公告或可确认的利空事件" in repaired[0]


def test_stock_cause_guard_rejects_generic_positive_report_label():
    evidence = {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "user_question": "中兴通讯7月24日为什么跌？",
        "metrics": {"latest_close": 35.0, "return_1d_pct": -2.56},
        "stock_market_context": {
            "analysis_target": {"market_date": "2026-07-24"},
            "exact_industry_index": {"component_breadth": {"status": "available"}},
        },
    }
    answer = (
        "中兴通讯7月24日收盘35元，跌2.56%。"
        "个股与行业同日下跌，但相对表现只能确认同步或分化，不能证明具体原因。"
        "已确认的是价格下跌，具体公司驱动仍未取得同日官方披露确认。"
        "午间正面产品报道与当日价格走势方向不匹配。"
        "后续只核验交易所公告、监管文件、公司原文和公开行情。"
    )

    guard = AgentService._validate_model_output(answer, evidence)
    repaired = AgentService._repair_guard_failure(answer, evidence, guard)

    assert guard["passed"] is False
    assert (
        "公告或媒体线索不能在缺少事件研究时评为正面负面或催化"
        in guard["unsupported_market_inferences"]
    )
    assert repaired is not None
    assert repaired[1]["passed"] is True
    assert "正面产品报道" not in repaired[0]


def test_stock_event_repair_preserves_confirmed_disclosure_titles():
    evidence = {
        "type": "stock_research",
        "symbol": "000065.SZ",
        "display_name": "北方国际",
        "user_question": "哪些公司事件与这次回撤有关？",
        "event_timeline": {
            "events": [
                {
                    "title": "000065北方国际投资者关系管理信息20260716",
                    "event_date": "2026-07-16",
                    "category": "announcement",
                    "evidence_level": "official_disclosure",
                },
                {
                    "title": "关于向控股股东申请借款暨关联交易的公告",
                    "event_date": "2026-06-15",
                    "category": "announcement",
                    "evidence_level": "official_disclosure",
                },
            ]
        },
    }
    answer = (
        "公司已经披露7月投资者关系记录和6月借款公告，"
        "这些都是中性或常规事项，没有明显催化。\n\n"
        "财务变化仍需结合公告原文核对，不能只凭标题判断股价原因。"
    )

    guard = AgentService._validate_model_output(answer, evidence)
    repaired = AgentService._repair_guard_failure(answer, evidence, guard)

    assert guard["passed"] is False
    assert repaired is not None
    assert repaired[1]["passed"] is True
    assert "000065北方国际投资者关系管理信息20260716" in repaired[0]
    assert "关于向控股股东申请借款暨关联交易的公告" in repaired[0]
    assert "这些正式披露确实存在" in repaired[0]
    assert "中性或常规事项" not in repaired[0]


def test_stock_cause_guard_allows_explicit_media_sentiment_boundary():
    evidence = {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "user_question": "中兴通讯7月24日为什么跌？",
        "metrics": {"latest_close": 35.0, "return_1d_pct": -2.56},
        "stock_market_context": {
            "analysis_target": {"market_date": "2026-07-24"},
            "exact_industry_index": {"component_breadth": {"status": "available"}},
        },
    }

    guard = AgentService._validate_model_output(
        "媒体报道不能据此评价为正面或负面，具体公司驱动仍未确认。",
        evidence,
    )

    assert (
        "公告或媒体线索不能在缺少事件研究时评为正面负面或催化"
        not in guard["unsupported_market_inferences"]
    )


def test_stock_cause_guard_allows_negated_event_labels_and_unconfirmed_examples():
    evidence = {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "user_question": "中兴通讯今天为什么涨？",
        "metrics": {"latest_close": 33.81, "return_1d_pct": 1.53},
        "stock_market_context": {
            "analysis_target": {"market_date": "2026-07-31"},
            "exact_industry_index": {"component_breadth": {"status": "available"}},
        },
    }
    answer = (
        "近期直接驱动尚未找到同日公司事件，所以无法确认是某个具体利好推动。"
        "今天上涨的直接原因并非来自明确的公司层面正面事件。"
        "近期价格上涨的直接驱动，如具体订单、政策利好或业绩预告，"
        "尚未找到同日公告或媒体确证。"
    )

    guard = AgentService._validate_model_output(answer, evidence)

    assert guard["passed"] is True
    assert (
        "公告或媒体线索不能在缺少事件研究时评为正面负面或催化"
        not in guard["unsupported_market_inferences"]
    )
    assert (
        "缺少事件或业务证据时不能用技术指标行业轮动或业务结构解释个股涨跌"
        not in guard["unsupported_market_inferences"]
    )


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
                        "business_profile": {"anchor_report_date": "2025-12-31"},
                    },
                    {
                        "name": "紫光股份",
                        "financial": {
                            "name": "紫光股份",
                            "net_profit_yoy_pct": 126.06,
                            "parent_net_profit": 787_908_617.19,
                            "notice_date": "2026-04-29",
                        },
                        "business_profile": {"anchor_report_date": "2025-12-31"},
                    },
                    {
                        "name": "锐捷网络",
                        "financial": {
                            "name": "锐捷网络",
                            "net_profit_yoy_pct": 14.59,
                            "parent_net_profit": 122_924_259.41,
                            "notice_date": "2026-04-21",
                        },
                        "business_profile": {"anchor_report_date": "2025-12-31"},
                    },
                ],
            }
        },
    }

    ranking = AgentService._validate_model_output(
        "中兴通讯在样本中最低，因此经营表现更差。", evidence
    )
    assert ranking["passed"] is False
    assert (
        "固定同行经营比较不得输出公司排名或优劣评级"
        in ranking["unsupported_market_inferences"]
    )

    wrong_period = AgentService._validate_model_output(
        "四家公司主营构成不是统一报告期，只能分别观察。", evidence
    )
    assert wrong_period["passed"] is False
    assert (
        "主营构成报告期必须与证据逐家公司一致"
        in wrong_period["unsupported_market_inferences"]
    )

    unsupported_cause = AgentService._validate_model_output(
        "紫光股份的低毛利率主要受IT分销业务拖累。", evidence
    )
    assert unsupported_cause["passed"] is False
    assert (
        "同行业务结构差异不能自动改写为经营指标差异的原因"
        in unsupported_cause["unsupported_market_inferences"]
    )

    wrong_ratio_logic = AgentService._validate_model_output(
        "中兴和烽火负利润增速会放大经营现金流/净利润的比值负数。",
        evidence,
    )
    assert wrong_ratio_logic["passed"] is False
    assert (
        "净利润同比方向不能解释经营现金流比值"
        in wrong_ratio_logic["unsupported_market_inferences"]
    )

    wrong_money_unit = AgentService._validate_model_output(
        "烽火通信本期净利润0.038亿元。", evidence
    )
    assert wrong_money_unit["passed"] is False
    assert (
        "同行净利润亿元换算必须与结构化财务一致"
        in wrong_money_unit["unsupported_market_inferences"]
    )
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
    assert (
        "同行公告日期不能用单一日期概括"
        in wrong_notice_date["unsupported_market_inferences"]
    )

    composition_math = AgentService._validate_model_output(
        "紫光股份应收账款加销售方和合并抵消后占比超过100%。", evidence
    )
    assert composition_math["passed"] is False
    assert (
        "主营构成不得自行加总或混入非分部字段"
        in composition_math["unsupported_market_inferences"]
    )

    ordinary_cashflow_check = AgentService._validate_model_output(
        "经营现金流为负，需要继续核验应收账款账龄和回款节奏。", evidence
    )
    assert (
        "主营构成不得自行加总或混入非分部字段"
        not in ordinary_cashflow_check["unsupported_market_inferences"]
    )

    explicit_field_mix = AgentService._validate_model_output(
        "主营构成中还加入了应收账款字段。", evidence
    )
    assert (
        "主营构成不得自行加总或混入非分部字段"
        in explicit_field_mix["unsupported_market_inferences"]
    )

    wrong_margin_source = AgentService._validate_model_output(
        "中兴通讯分部毛利率在三表中未披露。", evidence
    )
    assert wrong_margin_source["passed"] is False
    assert (
        "主营构成毛利率必须使用年报或中报口径"
        in wrong_margin_source["unsupported_market_inferences"]
    )

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
                {"title": f"资讯{i}", "published_at": "2026-07-21"} for i in range(10)
            ],
        },
        "knowledge_context": {
            "query": "美股为什么跌",
            "items": [
                {
                    "title": "市场涨跌原因的证据规则",
                    "scope": "common",
                    "excerpt": "规则",
                },
                {"title": "用户的美股笔记", "scope": "user", "excerpt": "笔记"},
                {"title": "多余资料", "scope": "common", "excerpt": "多余"},
                {"title": "第四份资料", "scope": "common", "excerpt": "多余"},
            ],
        },
    }

    public = AgentService._evidence_for_prompt(evidence)
    compact = AgentService._compact_market_brief_evidence(public)
    compact_knowledge = AgentService._compact_market_knowledge_context(
        public["knowledge_context"]
    )

    assert [item["symbol"] for item in compact["indices"]] == ["^GSPC"]
    assert "hot_sectors" not in compact
    assert len(compact["market_drivers"]["items"]) == 4
    assert "knowledge_context" not in compact
    assert [item["title"] for item in compact_knowledge["items"]] == [
        "用户的美股笔记",
        "多余资料",
    ]
    assert "source" not in compact["indices"][0]
    assert compact["indices"][0]["metrics"] == {
        "return_1d_pct": -0.19,
    }
    assert compact["indices"][0]["market_date"] == "2026-07-21"
    assert "coverage" not in compact["indices"][0]
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


def test_guard_repair_drops_only_bad_sentence_in_market_paragraph():
    repaired = AgentService._repair_guard_failure(
        "此前主要指数同步下跌，最大跌幅4.12%。"
        "触发今天上涨的直接原因仍未确认，现有资讯标题只能作为待核验线索。\n\n"
        "今天主要指数全部上涨，价格和方向的反差已经确认。"
        "但在取得同日政策、宏观或行业事件之前，不能把讨论热度改写成直接原因。",
        {
            "type": "market_brief",
            "indices": [
                {"name": "上证综指", "metrics": {"return_1d_pct": 0.72}},
                {"name": "深证成指", "metrics": {"return_1d_pct": 2.21}},
            ],
        },
        {
            "unsupported_numbers": ["4.12%"],
            "unsupported_market_inferences": [],
            "private_operational_patterns": [],
            "prohibited_patterns": [],
            "semantic_conflicts": [],
        },
    )

    assert repaired is not None
    repaired_answer, repaired_guard = repaired
    assert "4.12%" not in repaired_answer
    assert "触发今天上涨的直接原因仍未确认" in repaired_answer
    assert "今天主要指数全部上涨" in repaired_answer
    assert repaired_guard["passed"] is True


def test_general_research_guard_keeps_common_named_index_label():
    guard = AgentService._validate_model_output(
        "可以比较宽基指数ETF，例如沪深 300 等产品，但不能据此承诺收益。",
        {
            "type": "general_research",
            "financial_advisor_context": {"status": "ready_for_conditional_guidance"},
        },
    )

    assert guard["passed"] is True
    assert guard["unsupported_numbers"] == []


def test_general_research_guard_keeps_explicit_no_guarantee_boundary():
    safe = AgentService._validate_model_output(
        "这些产品都不是存款，净值会波动，不能保证收益，也不建议买入任何具体产品。",
        {"type": "general_research"},
    )
    unsafe = AgentService._validate_model_output(
        "这类产品保证收益，建议买入。",
        {"type": "general_research"},
    )

    assert safe["passed"] is True
    assert safe["prohibited_patterns"] == []
    assert unsafe["passed"] is False
    assert unsafe["prohibited_patterns"]


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
            ],
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
    assert compact["market_breadth"]["turnover"]["total_amount_100m_cny"] == (12_340.0)
    assert compact["market_breadth"]["distribution"]["median_pct_change"] == (0.72)
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


def test_market_cause_prompt_keeps_structured_causal_evidence():
    evidence = {
        "type": "market_brief",
        "user_question": "美股为什么跌",
        "question_focus": {"key": "market_cause", "label": "涨跌原因"},
        "analysis_target": {
            "market_date": "2026-07-24",
            "market_key": "us",
        },
        "indices": [],
        "market_drivers": {
            "market_key": "us",
            "market_label": "美国股市",
            "items": [],
            "causal_evidence": {
                "target_market_date": "2026-07-24",
                "coverage_status": "same_date_multi_source",
                "candidate_count": 2,
                "same_date_candidate_count": 2,
                "source_count": 2,
                "corroborated_categories": [
                    {
                        "category": "monetary_policy",
                        "category_label": "货币政策与央行表态",
                        "same_date_sources": 2,
                    }
                ],
                "boundary": "同日多来源线索不能自动证明唯一因果。",
                "candidates": [
                    {
                        "category_label": "货币政策与央行表态",
                        "source": "Example Wire",
                        "title": "Fed signals rates may stay high",
                        "published_at": "2026-07-24T20:10:00+00:00",
                        "published_market_date": "2026-07-24",
                        "date_relation": "same_date",
                        "independent_sources": 2,
                        "same_date_sources": 2,
                        "support_level": "same_date_multi_source",
                    }
                ],
            },
        },
    }

    compact = AgentService._compact_market_brief_evidence(evidence)

    assert compact["causal_evidence"]["coverage_status"] == ("same_date_multi_source")
    assert compact["causal_evidence"]["corroborated_categories"][0] == {
        "category": "monetary_policy",
        "category_label": "货币政策与央行表态",
        "same_date_sources": 2,
    }
    assert compact["causal_evidence"]["candidates"][0]["title"] == (
        "Fed signals rates may stay high"
    )
    assert compact["causal_evidence"]["candidates"][0]["source"] == ("Example Wire")


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
        "market_drivers": {"items": [{"title": "多家机构发布A股观点"}]},
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
    evidence_scoped = AgentService._validate_model_output(
        "上证综指上涨1.79%。当前证据里并没有可以核验的政策公告或宏观数据"
        "来解释今天为何触发上涨，因此直接原因仍未确认。",
        evidence,
    )

    assert absorption["passed"] is False
    assert missing_events["passed"] is False
    assert future_catalyst["passed"] is False
    assert evidence_scoped["passed"] is True


def test_market_guard_requires_turnover_snapshot_date_when_user_asks_time(settings):
    database = Database(settings.workspace_root)
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

    assert "全市场成交额时间必须引用市场快照日期" in missing_date["semantic_conflicts"]
    assert "全市场成交额时间必须引用市场快照日期" not in safe["semantic_conflicts"]
    assert (
        "已有全市场快照日期时不能声称成交额日期缺失"
        in false_missing["unsupported_market_inferences"]
    )


def test_market_guard_accepts_natural_turnover_time_and_negative_boundary(settings):
    database = Database(settings.workspace_root)
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
    natural_boundary = (
        "2026年7月21日全市场成交额为29734.49亿元，"
        "但不能解读为增量资金集中入场。"
    )

    guard = service._validate_model_output(answer, evidence, trusted_context=None)
    natural_guard = service._validate_model_output(
        natural_boundary,
        evidence,
        trusted_context=None,
    )

    assert "building_history" not in answer
    assert "同口径历史仍在积累" in answer
    assert guard["passed"] is True
    assert natural_guard["passed"] is True


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
    answer = "尾部下跌个股444家（8.0%），温和下跌个股1856家（33.6%）。"

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
        "全市场成交额为29734.49亿元。同一笔交易同时计入买卖双方，所以成交额会翻倍。"
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


def test_guard_repair_renumbers_chinese_prose_ordinals_after_dropping_a_line():
    repaired = AgentOutputGuard._renumber_repaired_sections(
        "第一，价格事实。\n第二，波动仍高。\n第四，事件驱动尚未确认。"
    )

    assert repaired == (
        "第一，价格事实。\n第二，波动仍高。\n第三，事件驱动尚未确认。"
    )


def test_market_guard_repairs_unsupported_style_flow_and_history_inferences(
    tmp_path: Path, settings, monkeypatch
):
    guarded_settings = replace(
        settings,
        workspace_root=tmp_path / "workspaces-market-inference-guard",
        hermes_enabled=True,
    )
    database = Database(guarded_settings.workspace_root)
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


def test_market_guard_keeps_negated_breadth_language_without_breadth_data():
    evidence = {
        "type": "market_brief",
        "market_state": {"whole_market_breadth_available": False},
    }

    cautious = AgentService._validate_model_output(
        "从领涨板块集中度看，更接近结构性行情；全市场广度仍待补证。",
        evidence,
    )
    negated = AgentService._validate_model_output(
        "今天是结构性行情，并非全市场普涨。",
        evidence,
    )

    assert cautious["passed"] is True
    assert negated["passed"] is True


def test_market_guard_accepts_date_bound_cross_date_breadth_evidence():
    evidence = {
        "type": "market_brief",
        "user_question": "今天A股普涨，但昨天指数很弱，怎么理解？",
        "analysis_target": {"market_date": "2026-07-30"},
        "market_state": {"whole_market_breadth_available": False},
        "market_breadth": {
            "status": "available",
            "market_date": "2026-07-31",
            "same_date_as_analysis_target": False,
            "breadth": {
                "total": 5533,
                "advancers": 4517,
                "decliners": 902,
                "unchanged": 114,
                "state": "普涨",
            },
        },
    }

    current_day = AgentService._validate_model_output(
        "7月31日午间上涨4517家、下跌902家，固定分类确实是普涨。",
        evidence,
    )
    wrong_day = AgentService._validate_model_output(
        "7月30日上涨4517家、下跌902家，因此当天是普涨。",
        evidence,
    )
    anaphoric_reference = AgentService._validate_model_output(
        "7月31日午间属于普涨。这个普涨快照只能说明今天盘中发生了什么。",
        evidence,
    )

    assert current_day["passed"] is True
    assert anaphoric_reference["passed"] is True
    assert wrong_day["passed"] is False
    assert "缺少全市场涨跌家数时不能确认是否普涨" in wrong_day[
        "unsupported_market_inferences"
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
        "上涨3107家、下跌2300家、平盘121家，固定分类为上涨家数占优，未达到普涨阈值。",
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
    natural_counts = AgentService._validate_model_output(
        "上涨3107家、下跌2300家，固定分类为上涨家数占优。",
        {
            **evidence,
            "user_question": "请给出涨跌家数和固定分类",
        },
    )
    missing_explicit_flat_count = AgentService._validate_model_output(
        "上涨3107家、下跌2300家，固定分类为上涨家数占优。",
        {
            **evidence,
            "user_question": "请给出上涨、下跌、平盘家数和固定分类",
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
    assert natural_counts["passed"] is True
    assert missing_explicit_flat_count["passed"] is False
    assert missing_explicit_flat_count["unsupported_market_inferences"] == [
        "用户询问全市场广度时回答必须给出涨跌家数和固定分类"
    ]
    assert invented_attribution["passed"] is False
    assert set(invented_attribution["unsupported_market_inferences"]) == {
        "全市场涨跌家数不能直接证明少数权重或集中板块拉动",
        "缺少个股涨幅分布时不能声称多数股票涨幅温和",
    }


def test_market_cause_question_does_not_require_unchanged_count():
    evidence = {
        "type": "market_brief",
        "user_question": "A股今天为什么普跌？请说明价格事实和反方证据。",
        "market_state": {
            "whole_market_breadth_available": True,
            "whole_market_breadth_state": "普跌",
            "whole_market_advancers": 555,
            "whole_market_decliners": 4939,
            "whole_market_unchanged": 36,
        },
    }

    guard = AgentService._validate_model_output(
        "全市场555只上涨、4939只下跌，确认普跌。",
        evidence,
    )

    assert guard["passed"] is True


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
    detailed_guard = AgentService._validate_model_output(detailed_rule_answer, evidence)

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
    assert (
        "热门板块排序不能证明板块集中度较高" in guard["unsupported_market_inferences"]
    )


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
    assert (
        "缺失收益的指数不能引用其他指数的涨跌幅"
        in guard["unsupported_market_inferences"]
    )
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
        "全市场成交额12340亿元，个股涨跌幅中位数0.72%。成交额不是资金净流入。",
        evidence,
    )
    direct_boundary = AgentService._validate_model_output(
        "全市场成交额12340亿元，不能直接证明资金净流入。",
        evidence,
    )

    assert missing["passed"] is False
    assert set(missing["unsupported_market_inferences"]) == {
        "已有全市场个股涨跌幅分布时不能声称该数据缺失",
        "已有全市场成交额时不能声称该数据缺失",
    }
    assert false_flow["passed"] is False
    assert (
        "成交量或量比不能直接证明增量资金入场或资金流向"
        in false_flow["unsupported_market_inferences"]
    )
    assert safe["passed"] is True
    assert direct_boundary["passed"] is True


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
        "这是近5日内首次出现的明显修复。\n20日累计下跌5.89%，说明指数处于低价区间。"
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


def test_stock_prompt_history_keeps_questions_but_drops_saved_reports():
    history = [
        {"role": "user", "content": "北方国际为什么进入候选"},
        {
            "role": "assistant",
            "content": "北方国际 当前价格证据：\n- 一整份服务器确定性报告正文",
        },
        {"role": "user", "content": "那现金流和借款公告说明什么"},
        {
            "role": "assistant",
            "content": "上一轮DeepSeek回答，其中可能有需要重新核验的数字。",
        },
        {"role": "user", "content": "近5日走平能叫企稳吗"},
    ]

    compact = AgentService._compact_stock_conversation_history(history)

    assert compact == [
        {"role": "user", "content": "北方国际为什么进入候选"},
        {"role": "user", "content": "那现金流和借款公告说明什么"},
        {"role": "user", "content": "近5日走平能叫企稳吗"},
    ]


def test_stock_prompt_history_deduplicates_repeated_questions():
    repeated = "请基于最新数据重新回答北方国际现金流和公告问题"
    history = [
        {"role": "user", "content": "北方国际为什么进入候选"},
        {"role": "assistant", "content": "旧回答"},
        {"role": "user", "content": repeated},
        {"role": "assistant", "content": "另一份旧回答"},
        {"role": "user", "content": repeated},
    ]

    compact = AgentService._compact_stock_conversation_history(history)

    assert compact == [
        {"role": "user", "content": "北方国际为什么进入候选"},
        {"role": "user", "content": repeated},
    ]


def test_stock_guard_keeps_explicit_rejection_of_disclosure_as_direct_cause():
    evidence = {
        "type": "stock_research",
        "symbol": "000065.SZ",
        "user_question": "借款公告是不是这次回撤的直接原因？",
        "research_plan": {"focus": "price_cause"},
    }
    answer = (
        "这些公告确实存在，但仅凭标题无法确认它们是本次回撤的直接原因，"
        "其中借款类公告也不能直接解读为资金链紧张或股价下跌驱动。"
    )

    guard = AgentService._validate_model_output(answer, evidence)

    assert guard["passed"] is True
    assert (
        "缺少事件或业务证据时不能用技术指标行业轮动或业务结构解释个股涨跌"
        not in guard["unsupported_market_inferences"]
    )


def test_market_guard_rejects_max_drawdown_position_and_loss_overclaims():
    evidence = {
        "type": "market_brief",
        "indices": [{"metrics": {"max_drawdown_60d_pct": -11.2766}}],
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
        "indices": [{"metrics": {"volume_ratio_5_20": 3.927}}],
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
        "两者的技术状态均为动量转弱，5/20日均量比为3.9，板块按涨跌幅排序。"
    )


def test_model_language_cleanup_hides_internal_ingestion_wording():
    cleaned = AgentService._clean_user_facing_model_language(
        "根据当前确定性证据包，当前已接入资料未披露全市场涨跌家数，北向数据尚未接入。"
    )

    assert "当前当前" not in cleaned
    assert "接入" not in cleaned
    assert cleaned == (
        "根据当前可验证证据，现有证据没有提供全市场涨跌家数，北向数据当前证据未提供。"
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
    answer = "板块数据标记为已过时（06:57 UTC）。\ntechnical_state字段显示动量转弱。"

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
        "hot_sectors": {"sectors": [{"name": "不应进入风险提示词的板块"}]},
    }

    compact = AgentService._compact_market_brief_evidence(evidence)

    assert compact["market_drivers"]["items"] == [{"title": "用于反方核验的市场资讯"}]
    assert "hot_sectors" not in compact
    assert "最近5个交易日累计收益" in compact["metric_definitions"]["return_5d_pct"]
    assert compact["indices"][0]["metrics"]["return_60d_pct"] == 3.2
    assert "最近60个交易日累计收益" in compact["metric_definitions"]["return_60d_pct"]
    assert (
        "不能与路径最大回撤直接比较"
        in compact["metric_definitions"]["volatility_20d_annualized_pct"]
    )
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
    assert "最近60个交易日累计收益" in compact["metric_definitions"]["return_60d_pct"]


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
    assert (
        "三大指数表述不能与四个代表性指数混用" in guard["unsupported_market_inferences"]
    )


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
    wrong = AgentService._validate_model_output("纳指的中期趋势状态为偏弱。", evidence)
    safe = AgentService._validate_model_output("纳指的趋势状态为趋势分化。", evidence)

    assert wrong["passed"] is False
    assert wrong["unsupported_market_inferences"] == ["指数趋势状态必须与当前证据一致"]
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


def test_model_language_cleanup_explains_invalidation_as_reassessment():
    cleaned = AgentService._clean_user_facing_model_language(
        "### 失效条件\n- 后续事实与当前证据冲突时，需要重新评估。"
    )

    assert cleaned == (
        "### 什么时候需要重新判断\n"
        "- 后续事实与当前证据冲突时，需要重新评估。"
    )


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
        "user_question": "这段判断的反方证据是什么？什么时候需要重新判断？",
        "indices": [],
    }

    guard = AgentService._validate_model_output("这里只回答了反方证据。", evidence)

    assert guard["passed"] is False
    assert guard["unsupported_market_inferences"] == [
        "用户明确询问何时需要重新判断时回答必须说明对应情况"
    ]


def test_market_guard_accepts_natural_reassessment_language():
    evidence = {
        "type": "market_brief",
        "user_question": "今天为什么和昨天反差这么大，什么时候需要重新判断？",
        "indices": [],
    }

    guard = AgentService._validate_model_output(
        "后续要判断这个反差能否延续，接下来主要看两个观察点：广度和均线。",
        evidence,
    )

    assert guard["passed"] is True


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
            "tracking_plan": [{"horizon_sessions": 5, "checks": ["复核价格和公告证据"]}]
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
    assert (
        "个股失效条件只能使用证据包已有阈值和观察周期"
        in guard["unsupported_market_inferences"]
    )


def test_stock_guard_accepts_deterministic_failure_condition_from_outlook():
    evidence = {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "user_question": "中兴通讯什么时候需要重新判断？",
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
        "stock_market_context": {"analysis_target": {"market_date": "2026-07-29"}},
    }

    guard = AgentService._validate_model_output(
        "### 什么时候需要重新判断\n"
        "- 收盘跌破关键参考位32.39，同时20日收益继续恶化。\n"
        "**注意**：以上情况仅针对2026-07-29同日判断。",
        evidence,
    )

    assert guard["passed"] is True


def test_stock_guard_does_not_treat_inline_failure_condition_as_section_heading():
    evidence = {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "user_question": "今天的下跌是否改变原判断？",
        "price_levels": {"ma20": 37.28, "ma60": 37.3},
        "conditional_outlook": {
            "horizon": "未来 5—20 个交易日",
            "scenarios": [
                {
                    "name": "下行风险",
                    "condition": "收盘跌破关键参考位37.3，同时20日收益继续恶化",
                }
            ],
            "invalidation": "价格跨越关键参考位后必须重算。",
        },
        "analysis_board": {"tracking_plan": []},
    }
    answer = (
        "**价格关系**\n"
        "7月22日发布公告；7月23日需要核验实际影响。条件展望仍为震荡观察，"
        "其下行失效条件是收盘跌破关键参考位37.3，"
        "同时20日收益继续恶化。\n\n"
        "**反方证据**\n"
        "2026一季报净利润同比下降46.58%，需要继续复核盈利兑现。"
    )

    assert (
        agent_module._has_unsupported_stock_failure_threshold(answer, evidence) is False
    )


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
    assert (
        "个股观察周期只能使用研究计划已有交易日窗口"
        in guard["unsupported_market_inferences"]
    )
    assert (
        "缺少披露日历证据时不能预测下一份报告日期"
        in guard["unsupported_market_inferences"]
    )


def test_model_language_cleanup_repairs_wireless_access_typo():
    cleaned = AgentService._clean_user_facing_model_language(
        "需要确认无钱接入产品毛利率是否下降。"
    )

    assert cleaned == "需要确认无线接入产品毛利率是否下降。"


def test_model_language_cleanup_keeps_cashflow_facts_without_unsupported_summary():
    cleaned = AgentService._clean_user_facing_model_language(
        "经营现金流净流出19.79亿元，而去年同期为净流入18.51亿元，"
        "现金覆盖能力转弱。毛利率下降（成本上升或产品结构变化）。"
    )

    assert "经营现金流净流出19.79亿元" in cleaned
    assert "去年同期为净流入18.51亿元" in cleaned
    assert "现金覆盖能力转弱" not in cleaned
    assert "成本上升或产品结构变化" not in cleaned


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
    assert "财报公告日期必须与结构化报告一致" in guard["unsupported_market_inferences"]
    assert (
        "最大回撤观察窗口必须与确定性指标一致" in guard["unsupported_market_inferences"]
    )


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
    assert (
        "财报公告日期必须与结构化报告一致" not in guard["unsupported_market_inferences"]
    )


def test_stock_guard_does_not_treat_valid_looking_ratio_as_notice_date():
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
                    "revenue_yoy_pct": 6.13,
                    "net_profit_yoy_pct": -46.58,
                }
            }
        },
    }

    guard = AgentService._validate_model_output(
        "根据2026年一季报（4月25日披露），营收同比增长6.13%，"
        "归母净利润同比下降46.58%。",
        evidence,
    )

    assert guard["passed"] is True
    assert (
        "财报公告日期必须与结构化报告一致"
        not in guard["unsupported_market_inferences"]
    )


def test_stock_guard_does_not_treat_report_period_as_notice_date():
    evidence = {
        "type": "stock_research",
        "symbol": "300750.SZ",
        "fundamentals": {
            "summary": {
                "latest_report": {
                    "report_date": "2026-06-30",
                    "report_date_name": "2026中报",
                    "report_type": "中报",
                    "notice_date": "2026-07-25",
                }
            }
        },
    }

    guard = AgentService._validate_model_output(
        "2026年中报（截至6月30日）披露，公司营收保持增长。",
        evidence,
    )

    assert guard["passed"] is True
    assert (
        "财报公告日期必须与结构化报告一致" not in guard["unsupported_market_inferences"]
    )


def test_stock_guard_accepts_rounded_ratio_endpoints_and_coarse_summary():
    evidence = {
        "type": "stock_research",
        "symbol": "300750.SZ",
        "financial_drivers": {
            "cashflow_analysis": {
                "cash_received_from_sales_to_revenue_pct": 94.769,
                "comparable_cash_received_from_sales_to_revenue_pct": 124.622,
                "operating_cashflow_to_net_profit": 1.387,
                "comparable_operating_cashflow_to_net_profit": 1.918,
            }
        },
        "business_structure": {
            "dimensions": [
                {
                    "segments": [
                        {
                            "gross_margin_pct": 20.6287,
                            "gross_margin_change_pp": -1.783,
                        },
                        {
                            "gross_margin_pct": 23.9577,
                            "gross_margin_change_pp": -1.56,
                        },
                        {
                            "gross_margin_pct": 21.1557,
                            "gross_margin_change_pp": -1.786,
                        },
                    ]
                }
            ]
        },
    }
    answer = (
        "动力电池系统毛利率下降1.78个百分点至20.63%，"
        "储能电池系统毛利率下降1.56个百分点至23.96%，"
        "境内毛利率下降1.79个百分点至21.16%。"
        "两大产品毛利率分别下降1.6～1.8个百分点。"
        "经营现金流与归母净利润的比率从1.9倍降到1.4倍。"
        "销售收现率从超过120%跌到不足95%。"
    )

    guard = AgentService._validate_model_output(answer, evidence)

    assert guard["passed"] is True
    assert guard["unsupported_numbers"] == []


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
    assert (
        "今日涨跌方向必须与更新的当前报价一致" in guard["unsupported_market_inferences"]
    )
    assert (
        "今日或当前价格必须优先使用更新的报价快照"
        in guard["unsupported_market_inferences"]
    )


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


def test_stock_guard_accepts_historical_weakness_in_sentence_mentioning_today():
    evidence = {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "user_question": "中兴通讯今天为什么涨？",
        "metrics": {"latest_close": 33.73, "return_1d_pct": -6.31},
        "provenance": {"market_timestamp": "2026-07-20T01:30:00+00:00"},
        "current_quote": {
            "price": 34.88,
            "pct_change": 3.41,
            "market_timestamp": "2026-07-21T16:14:42+08:00",
        },
    }

    guard = AgentService._validate_model_output(
        "当前报价34.88元，上涨3.41%。"
        "前一天和近期几个交易日的下跌，不能用来否定今天上涨的事实。",
        evidence,
    )

    assert guard["passed"] is True
    assert "今日涨跌方向必须与更新的当前报价一致" not in guard[
        "unsupported_market_inferences"
    ]


def test_stock_guard_accepts_previous_complete_session_before_current_quote():
    evidence = {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "user_question": "中兴通讯最近走弱吗？",
        "metrics": {"latest_close": 33.30, "return_1d_pct": -2.29},
        "provenance": {"market_timestamp": "2026-07-30T01:30:00+00:00"},
        "current_quote": {
            "price": 34.00,
            "pct_change": 2.10,
            "market_timestamp": "2026-07-31T12:05:00+08:00",
        },
    }

    guard = AgentService._validate_model_output(
        "上一完整交易日收于33.30元；今天盘中最新报价34.00元，上涨2.10%。",
        evidence,
    )

    assert guard["passed"] is True


def test_stock_guard_scopes_current_quote_check_to_each_sentence():
    evidence = {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "user_question": "中兴通讯最近走弱吗？",
        "metrics": {"latest_close": 33.30, "return_1d_pct": -2.29},
        "provenance": {"market_timestamp": "2026-07-30T01:30:00+00:00"},
        "current_quote": {
            "price": 34.00,
            "pct_change": 2.10,
            "market_timestamp": "2026-07-31T12:05:00+08:00",
        },
    }

    guard = AgentService._validate_model_output(
        "中兴通讯今天盘中最新报价34.00元，上涨2.10%。"
        "但最近一个完整交易日下跌2.29%，收于33.30元。"
        "最新报告期距今已有一段时间，没有同日公告直接印证近期下跌。",
        evidence,
    )

    assert guard["passed"] is True


def test_stock_guard_accepts_current_quote_inside_evidenced_reassessment_section():
    evidence = {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "user_question": "中兴通讯什么时候需要重新判断？",
        "current_quote": {
            "price": 34.0,
            "pct_change": 2.1,
            "market_date": "2026-07-31",
        },
        "price_levels": {
            "recent_20d_low": 32.39,
            "recent_20d_high": 43.0,
            "ma20": 36.7635,
        },
        "conditional_outlook": {
            "horizon": "未来5—20个交易日",
            "scenarios": [
                {
                    "condition": (
                        "收盘有效站上43.0，且随后不跌回MA20 36.7635"
                    )
                },
                {"condition": "收盘跌破32.39"},
            ],
        },
    }

    guard = AgentService._validate_model_output(
        "### 什么时候需要重新判断\n"
        "当前报价34.0元仍在近20日低点32.39元与高点43.0元之间。"
        "如果收盘有效站上43.0元且不跌回MA20 36.7635元，"
        "或者收盘跌破32.39元，就需要重新判断。",
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
    assert "更新的报价快照不能写成当日收盘" in guard["unsupported_market_inferences"]


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
        "stock_market_context": {"analysis_target": {"basis": "current_quote"}},
    }

    normalized = agent_module._normalize_current_quote_semantics(
        "中兴通讯今日以37.86元收盘，涨幅8.54%。\n上一完整日线收盘34.88元。",
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
        "stock_market_context": {"analysis_target": {"basis": "current_quote"}},
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


def test_current_quote_close_guard_accepts_comparison_with_previous_close():
    evidence = {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "user_question": "中兴通讯今天为什么跌？",
        "metrics": {"latest_close": 35.25, "return_1d_pct": 0.71},
        "provenance": {"market_timestamp": "2026-07-27T01:30:00+00:00"},
        "current_quote": {
            "price": 34.2,
            "previous_close": 35.25,
            "pct_change": -2.98,
            "market_timestamp": "2026-07-28T12:57:00+08:00",
        },
    }

    guard = AgentService._validate_model_output(
        "最新报价34.20元，比上一交易日收盘价35.25元下跌约2.98%，今天还没收盘。",
        evidence,
    )

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
        "stock_market_context": {"analysis_target": {"basis": "current_quote"}},
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
    assert (
        "收盘后报价不能继续描述为盘中或尚未收盘"
        in guard["unsupported_market_inferences"]
    )


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
        "stock_market_context": {"analysis_target": {"basis": "current_quote"}},
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
        "stock_market_context": {"analysis_target": {"basis": "current_quote"}},
    }
    answer = (
        "A股已收盘，当前为2026年7月22日收盘后最新报价。"
        "中兴通讯最新报价37.50元，较前一交易日最新报价34.88元上涨7.51%。"
        "最新完整日线截止7月21日，最新报价34.88元。"
        "盘中报价下跌2.98%，相对于此前最新报价34.88元，这是盘中价格，还没收盘。"
        "盘中报价下跌2.98%，比此前最新报价34.88元走低。"
    )

    normalized = agent_module._normalize_history_price_mislabeled_as_current_quote(
        answer, evidence
    )
    session_guard = AgentService._validate_model_output(
        "A股已收盘，当前为2026年7月22日收盘后最新报价。", evidence
    )

    assert "收盘价34.88元" in normalized
    assert "最新报价34.88元" not in normalized
    assert "相对于上一交易日收盘价34.88元" in normalized
    assert "比上一交易日收盘价34.88元" in normalized
    assert "还没收盘" in normalized
    assert "A股已收盘" in normalized
    assert session_guard["passed"] is True


def test_numeric_guard_accepts_rounded_whole_market_count_with_over_wording():
    evidence = {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "stock_market_context": {
            "market_breadth": {
                "same_date_as_target": True,
                "breadth": {"total": 5532, "advancers": 2835, "decliners": 2521},
            }
        },
    }

    guard = AgentService._validate_model_output(
        "今天上午超过5500只A股有涨跌数据，上涨家数略多于下跌家数。",
        evidence,
    )

    assert guard["passed"] is True


def test_numeric_guard_accepts_chinese_plus_rounded_whole_market_count():
    evidence = {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "stock_market_context": {
            "market_breadth": {
                "same_date_as_target": True,
                "breadth": {"total": 5532, "advancers": 2835, "decliners": 2521},
            }
        },
    }

    guard = AgentService._validate_model_output(
        "今天全市场5000多只股票里，上涨2835家、下跌2521家。",
        evidence,
    )

    assert guard["passed"] is True


def test_numeric_guard_accepts_rounded_whole_market_breadth_shares():
    evidence = {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "stock_market_context": {
            "market_breadth": {
                "same_date_as_target": True,
                "breadth": {
                    "total": 5532,
                    "advancers": 2835,
                    "decliners": 2521,
                    "unchanged": 176,
                },
            }
        },
    }

    guard = AgentService._validate_model_output(
        "今天上涨的股票比下跌的略多（约51%涨、46%跌）。",
        evidence,
    )

    assert guard["passed"] is True


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
        "stock_market_context": {"analysis_target": {"basis": "current_quote"}},
    }
    answer = "最新报价仍低于 MA20（37.28元）。"

    normalized = agent_module._normalize_stock_current_quote_ma20_relation(
        answer, evidence
    )
    guard = AgentService._validate_model_output(answer, evidence)

    assert "最新报价已高于 MA20" in normalized
    assert guard["passed"] is False
    assert (
        "当前报价与MA20关系必须与确定性数据一致"
        in guard["unsupported_market_inferences"]
    )


def test_current_quote_ma20_guard_accepts_explicit_not_above_when_quote_is_below():
    evidence = {
        "type": "stock_research",
        "symbol": "000065.SZ",
        "metrics": {"ma20": 9.10},
        "price_levels": {"ma20": 9.10},
        "current_quote": {
            "price": 9.04,
            "pct_change": -1.53,
            "market_timestamp": "2026-07-28T16:14:57+08:00",
        },
    }

    guard = AgentService._validate_model_output(
        "最新报价9.04元仍在20日均线9.10元附近，并未有效站上。",
        evidence,
    )

    assert guard["passed"] is True


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
        "a_share_information": {"news": [{"title": "中兴通讯盘中触及涨停后成交放大"}]},
    }
    answer = "最新报价38.2元，涨幅9.52%，盘中涨停。"

    rejected = AgentService._validate_model_output(answer, evidence)
    normalized = agent_module._normalize_current_limit_status(answer, evidence)
    accepted = AgentService._validate_model_output(normalized, evidence)

    assert rejected["passed"] is False
    assert (
        "当前涨跌停状态必须与最新报价涨跌幅一致"
        in rejected["unsupported_market_inferences"]
    )
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


def test_relative_event_date_normalizer_removes_future_label_when_date_exists():
    normalized = agent_module._normalize_relative_event_dates(
        "明日（7月24日）收盘后最新报价为35元。"
    )

    assert normalized == "7月24日收盘后最新报价为35元。"


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
            "market_state": {"summary": "目标交易日的代表性指数对照仍待补证。"},
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
    assert (
        "用户询问今日时必须给出更新报价并区分历史日线"
        in guard["unsupported_market_inferences"]
    )


def test_stock_guard_treats_epistemic_now_as_confidence_not_quote_request():
    evidence = {
        "type": "stock_research",
        "symbol": "000065.SZ",
        "user_question": (
            "那你现在最有把握能确认的两件事是什么？"
            "最不能确认的一件事是什么？"
        ),
        "current_quote": {
            "price": 9.31,
            "pct_change": 1.2,
            "market_timestamp": "2026-07-31T15:10:00+08:00",
        },
        "provenance": {"market_timestamp": "2026-07-30T15:00:00+08:00"},
    }

    assert agent_module._stock_current_quote_required_but_missing(
        "最有把握确认的是目标日实际涨跌；最不能确认的是直接驱动。",
        evidence,
    ) is False


def test_stock_guard_repairs_missing_quote_change_without_replacing_model_answer():
    evidence = {
        "type": "stock_research",
        "symbol": "000065.SZ",
        "display_name": "北方国际",
        "user_question": "请基于最新数据说明回撤与现金流、借款公告的关系。",
        "provenance": {"market_timestamp": "2026-07-28T01:30:00+00:00"},
        "current_quote": {
            "name": "北方国际",
            "currency": "CNY",
            "price": 9.04,
            "pct_change": -1.53,
            "market_timestamp": "2026-07-28T16:14:57+08:00",
            "market_date": "2026-07-28",
            "quote_label": "收盘后最新报价",
        },
        "financial_drivers": {
            "cashflow_analysis": {"operating_cashflow": 216477658.72}
        },
    }
    answer = (
        "北方国际最新报价9.04元。经营现金流净额约2.16亿元，"
        "但现金流净额本身较可比期收缩。"
        "没有正文依据能把借款公告直接解释为资金压力加剧或回撤的触发事件，"
        "也不能把它和这次股价下跌建立因果。"
    )

    guard = AgentService._validate_model_output(answer, evidence)
    repaired = AgentService._repair_guard_failure(answer, evidence, guard)

    assert guard["passed"] is False
    assert guard["unsupported_market_inferences"] == [
        "用户询问今日时必须给出更新报价并区分历史日线"
    ]
    assert repaired is not None
    assert repaired[1]["passed"] is True
    assert repaired[0].startswith(
        "最新行情：北方国际收盘后最新报价（2026-07-28）为9.04元，较前收盘下跌1.53%。"
    )
    assert "经营现金流净额约2.16亿元" in repaired[0]
    assert "没有正文依据能把借款公告直接解释为资金压力加剧" in repaired[0]


def test_stock_quote_guard_does_not_treat_return_percentage_as_share_price():
    evidence = {
        "type": "stock_research",
        "symbol": "000065.SZ",
        "user_question": "请基于最新数据判断近5日走平能不能叫企稳。",
        "provenance": {"market_timestamp": "2026-07-28T01:30:00+00:00"},
        "current_quote": {
            "price": 9.04,
            "pct_change": -1.53,
            "market_timestamp": "2026-07-28T16:14:57+08:00",
        },
        "metrics": {
            "return_5d_pct": 0.0,
            "return_60d_pct": -28.54,
            "ma20": 9.10,
        },
    }
    answer = (
        "近5日价格0.00%不能叫企稳。北方国际最新报价9.04元，"
        "较前收盘下跌1.53%，仍在20日均线9.10元附近；"
        "60日累计收益为-28.54%。"
    )

    guard = AgentService._validate_model_output(answer, evidence)

    assert guard["passed"] is True


def test_stock_quote_guard_does_not_treat_latest_financial_report_year_as_price():
    evidence = {
        "type": "stock_research",
        "symbol": "000065.SZ",
        "user_question": "请分析最新报告期利润质量和资产负债率。",
        "provenance": {"market_timestamp": "2026-07-28T01:30:00+00:00"},
        "current_quote": {
            "price": 9.04,
            "pct_change": -1.53,
            "market_timestamp": "2026-07-28T16:14:57+08:00",
        },
        "earnings_quality": {
            "latest_report": {
                "revenue_yoy_pct": -35.56,
                "parent_net_profit_yoy_pct": -37.54,
            }
        },
    }

    guard = AgentService._validate_model_output(
        "最新财报是2026年一季报，营收同比减少35.56%，归母净利润同比减少37.54%。",
        evidence,
    )

    assert guard["passed"] is True


def test_stock_quote_guard_does_not_treat_quote_timestamp_as_share_price():
    evidence = {
        "type": "stock_research",
        "symbol": "600841.SS",
        "user_question": "请分析最新报告期利润质量和估值数据日期。",
        "provenance": {"market_timestamp": "2026-07-29T01:30:00+00:00"},
        "current_quote": {
            "price": 5.87,
            "pct_change": 4.63,
            "market_timestamp": "2026-07-30T13:42:01+08:00",
        },
    }

    guard = AgentService._validate_model_output(
        "最新盘中报价在7月30日13:42为5.87元。",
        evidence,
    )

    assert (
        "今日或当前价格必须优先使用更新的报价快照"
        not in guard["unsupported_market_inferences"]
    )
    assert (
        "用户询问今日时必须给出更新报价并区分历史日线"
        not in guard["unsupported_market_inferences"]
    )


def test_stock_guard_accepts_explicit_borrowing_noncausality_boundary():
    evidence = {
        "type": "stock_research",
        "symbol": "000065.SZ",
        "user_question": "借款公告和这次回撤有什么关系？",
        "research_plan": {"focus": "mixed"},
    }

    guard = AgentService._validate_model_output(
        "没有正文依据能把借款公告直接解释为资金压力加剧或回撤的触发事件，"
        "也不能把它和这次股价下跌建立因果。",
        evidence,
    )

    assert guard["passed"] is True


def test_stock_guard_accepts_unsigned_quote_change_with_matching_direction():
    evidence = {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "user_question": "中兴通讯今天为什么跌？",
        "metrics": {"latest_close": 37.5, "return_1d_pct": 7.51},
        "provenance": {"market_timestamp": "2026-07-22T01:30:00+00:00"},
        "current_quote": {
            "price": 35.91,
            "pct_change": -4.24,
            "market_timestamp": "2026-07-23T14:47:27+08:00",
        },
    }

    guard = AgentService._validate_model_output(
        "盘中最新报价35.91元，下跌4.24%；最近完整日线属于上一交易日。",
        evidence,
    )

    assert guard["passed"] is True


def test_stock_guard_accepts_rounded_current_quote_change():
    evidence = {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "user_question": "中兴通讯今天为什么跌？",
        "metrics": {"latest_close": 35.25, "return_1d_pct": 0.71},
        "provenance": {"market_timestamp": "2026-07-27T01:30:00+00:00"},
        "current_quote": {
            "price": 34.2,
            "pct_change": -2.98,
            "market_timestamp": "2026-07-28T12:05:03+08:00",
        },
    }

    guard = AgentService._validate_model_output(
        "中兴通讯今天盘中跌了大约3%，最新报价34.20元；最近完整日线属于上一交易日。",
        evidence,
    )

    assert guard["passed"] is True


def test_stock_guard_accepts_micro_move_wording_for_unsigned_quote_change():
    evidence = {
        "type": "stock_research",
        "symbol": "600519.SS",
        "user_question": "贵州茅台现在最需要关注什么？",
        "metrics": {"latest_close": 1297.41, "return_1d_pct": 0.42},
        "provenance": {"market_timestamp": "2026-07-24T01:30:00+00:00"},
        "current_quote": {
            "price": 1289.5,
            "pct_change": -0.61,
            "market_timestamp": "2026-07-27T16:14:56+08:00",
        },
    }

    guard = AgentService._validate_model_output(
        "最新报价1289.5元，当天微跌0.61%；最近完整日线属于上一交易日。",
        evidence,
    )

    assert guard["passed"] is True


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
    assert (
        "跨日期市场广度不能用于排除目标日的系统性拖累"
        in guard["unsupported_market_inferences"]
    )


def test_stock_guard_requires_component_breadth_for_industry_participation_claims():
    evidence = {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "stock_market_context": {
            "exact_industry_index": {
                "status": "same_market_date",
                "name": "通信设备",
                "return_1d_pct": -1.42,
                "component_breadth": {"status": "unavailable_for_target_date"},
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
    separated_causal_claim = AgentService._validate_model_output(
        "中兴通讯当日相对行业抗跌，但核心是被行业整体拖累。",
        available_evidence,
    )

    assert unsafe["passed"] is False
    assert (
        "缺少行业成分涨跌家数时不能确认行业普涨普跌或参与面"
        in unsafe["unsupported_market_inferences"]
    )
    assert cautious["passed"] is True
    assert supported["passed"] is True
    assert causal["passed"] is False
    assert separated_causal_claim["passed"] is False
    assert (
        "行业成分广度只能描述同步性不能证明个股涨跌因果"
        in causal["unsupported_market_inferences"]
    )
    assert (
        "行业成分广度只能描述同步性不能证明个股涨跌因果"
        in separated_causal_claim["unsupported_market_inferences"]
    )


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
    assert (
        "跨日期市场广度不能用于排除目标日的系统性拖累"
        in guard["unsupported_market_inferences"]
    )

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
    assert (
        "跨日期市场广度不能用于排除目标日的系统性拖累"
        in (real_wording_guard["unsupported_market_inferences"])
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
    assert (
        "跨日期市场广度不能用于排除目标日的系统性拖累"
        in (independent_guard["unsupported_market_inferences"])
    )
    assert relative_index_guard["passed"] is False
    assert (
        "跨日期市场广度不能用于排除目标日的系统性拖累"
        in (relative_index_guard["unsupported_market_inferences"])
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
    assert (
        "跨日期市场广度不能用于排除目标日的系统性拖累"
        in (mislabeled_breadth["unsupported_market_inferences"])
    )
    assert safely_labeled_breadth["passed"] is True

    flexible_turnover_wording = AgentService._validate_model_output(
        "7月20日A股全市场成交约29734.49亿元，"
        "上涨家数占优（3107家涨、2300家跌、121家平盘）。",
        evidence,
    )
    assert flexible_turnover_wording["passed"] is False
    assert (
        "跨日期市场广度不能用于排除目标日的系统性拖累"
        in (flexible_turnover_wording["unsupported_market_inferences"])
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
    assert (
        "缺少事件或业务证据时不能用技术指标行业轮动或业务结构解释个股涨跌"
        in (causal_hypothesis_guard["unsupported_market_inferences"])
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
        "一季报公告后股价并未出现单日极端反应，因此只能算长期背景。\n"
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
    assert (
        "缺少事件研究证据时不能声称基本面已被市场消化或情绪驱动超跌"
        in (absorption_guard["unsupported_market_inferences"])
    )
    assert absorption_repaired is not None
    assert "已在市场消化" not in absorption_repaired[0]
    assert "不构成新信息" not in absorption_repaired[0]
    assert "此前已存在的信息" not in absorption_repaired[0]
    assert "公告后股价并未出现单日极端反应" not in absorption_repaired[0]
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
    assert (
        "公告或媒体线索不能在缺少事件研究时评为正面负面或催化"
        in (event_sentiment_guard["unsupported_market_inferences"])
    )

    indirect_sentiment_guard = AgentService._validate_model_output(
        "这些都属于中性信息线索，暂时看不出明显催化。",
        evidence,
    )
    assert indirect_sentiment_guard["passed"] is False
    assert (
        "公告或媒体线索不能在缺少事件研究时评为正面负面或催化"
        in indirect_sentiment_guard["unsupported_market_inferences"]
    )


def test_stock_guard_removes_unproven_financial_reaction_and_borrowing_story():
    evidence = {
        "type": "stock_research",
        "symbol": "000065.SZ",
        "display_name": "北方国际",
        "user_question": "这次回撤和财务、现金流、借款公告有什么关系？",
        "research_plan": {"focus": "mixed"},
        "financial_drivers": {
            "cashflow_analysis": {
                "operating_cashflow": 216477658.72,
                "comparable_operating_cashflow": 333946803.6,
                "operating_cashflow_change": -117469144.88,
                "operating_cashflow_to_net_profit": 1.96,
            }
        },
        "event_timeline": {
            "events": [
                {
                    "event_date": "2026-07-16",
                    "title": "北方国际投资者关系管理信息",
                    "evidence_level": "official_disclosure",
                },
                {
                    "event_date": "2026-06-15",
                    "title": "向控股股东申请借款暨关联交易公告",
                    "evidence_level": "official_disclosure",
                },
            ]
        },
    }
    answer = (
        "最新一季报经营现金流为2.16亿元，较可比期减少约1.17亿元，"
        "经营现金流对净利润覆盖约1.96倍。"
        "这两三周的回撤很大程度上可能是市场对一季报弱势的延续反应。"
        "向控股股东申请借款的关联交易公告可能加剧市场对资金面的担忧。"
        "已确认的是财务变化；它是否造成这段股价变化仍未确认。"
        "经营现金流仍为正，且覆盖净利润，因此不能把同比减少自动写成现金流为负。"
        "公告标题只能证明事项已经披露，仍需阅读用途和偿付安排才能判断财务含义。"
    )

    guard = AgentService._validate_model_output(answer, evidence)
    repaired = AgentService._repair_guard_failure(answer, evidence, guard)

    assert guard["passed"] is False
    assert (
        "缺少事件或业务证据时不能用技术指标行业轮动或业务结构解释个股涨跌"
        in guard["unsupported_market_inferences"]
    )
    assert repaired is not None
    assert "延续反应" not in repaired[0]
    assert "加剧市场对资金面的担忧" not in repaired[0]
    assert "经营现金流为2.16亿元" in repaired[0]
    assert "是否造成这段股价变化仍未确认" in repaired[0]
    assert "2026-07-16：北方国际投资者关系管理信息" in repaired[0]
    assert "2026-06-15：向控股股东申请借款暨关联交易公告" in repaired[0]
    assert "标题本身不能证明" in repaired[0]
    assert repaired[1]["passed"] is True


def test_stock_guard_rejects_debt_ratio_as_absolute_debt_scale_claim():
    evidence = {
        "type": "stock_research",
        "symbol": "000065.SZ",
        "earnings_quality": {
            "latest_report": {
                "debt_asset_ratio_pct": 53.47,
                "total_liabilities": None,
            },
            "comparable_report": {
                "debt_asset_ratio_pct": 57.23,
                "total_liabilities": None,
            },
        },
    }

    guard = AgentService._validate_model_output(
        "资产负债率从57.23%降至53.47%，负债整体规模有所下降。",
        evidence,
    )

    assert guard["passed"] is False
    assert (
        "资产负债率变化不能直接改写为负债绝对规模变化"
        in guard["unsupported_market_inferences"]
    )


def test_stock_guard_accepts_debt_ratio_percentage_point_change_without_scale_claim():
    evidence = {
        "type": "stock_research",
        "symbol": "000065.SZ",
        "earnings_quality": {
            "latest_report": {
                "debt_asset_ratio_pct": 53.47,
                "total_liabilities": None,
            },
            "comparable_report": {
                "debt_asset_ratio_pct": 57.23,
                "total_liabilities": None,
            },
        },
    }

    guard = AgentService._validate_model_output(
        "资产负债率从57.23%降至53.47%。",
        evidence,
    )

    assert guard["passed"] is True


def test_stock_guard_accepts_explicit_debt_to_asset_ratio_direction():
    evidence = {
        "type": "stock_research",
        "symbol": "600841.SS",
        "earnings_quality": {
            "latest_report": {
                "debt_asset_ratio_pct": 42.48,
                "total_liabilities": None,
            },
            "comparable_report": {
                "debt_asset_ratio_pct": 74.9,
                "total_liabilities": None,
            },
        },
    }

    guard = AgentService._validate_model_output(
        "资产负债率从74.9%降至42.48%，负债占资产的比例明显下降。",
        evidence,
    )

    assert guard["passed"] is True


def test_stock_guard_accepts_explicit_debt_scale_rejection():
    evidence = {
        "type": "stock_research",
        "symbol": "000065.SZ",
        "earnings_quality": {
            "latest_report": {
                "debt_asset_ratio_pct": 53.47,
                "total_liabilities": None,
            },
            "comparable_report": {
                "debt_asset_ratio_pct": 57.23,
                "total_liabilities": None,
            },
        },
    }

    guard = AgentService._validate_model_output(
        "资产负债率从57.23%降至53.47%，并非必然说明负债总量已经减少。",
        evidence,
    )

    assert guard["passed"] is True


def test_stock_guard_accepts_debt_scale_question_requiring_verification():
    evidence = {
        "type": "stock_research",
        "symbol": "600841.SS",
        "earnings_quality": {
            "latest_report": {
                "debt_asset_ratio_pct": 42.48,
                "total_liabilities": None,
            },
            "comparable_report": {
                "debt_asset_ratio_pct": 74.9,
                "total_liabilities": None,
            },
        },
    }

    guard = AgentService._validate_model_output(
        "资产负债率从74.9%降至42.48%，比例明显下降，但总负债金额是否一同下降仍需核对。",
        evidence,
    )

    assert guard["passed"] is True


def test_stock_guard_accepts_explicit_rejection_of_financial_price_causality():
    evidence = {
        "type": "stock_research",
        "symbol": "000065.SZ",
        "user_question": "这些财务压力和近20日回撤有什么关系？",
        "research_plan": {"focus": "mixed"},
    }

    guard = AgentService._validate_model_output(
        "这些财务压力是已经确认的事实，不等于它们就是近20日回撤的直接原因；"
        "目前没有事件研究或公司原文支持这一因果，只能作为基本面反方事实。",
        evidence,
    )

    assert guard["passed"] is True


def test_stock_guard_rejects_unproven_revenue_to_cashflow_cause():
    evidence = {
        "type": "stock_research",
        "symbol": "000065.SZ",
        "financial_drivers": {
            "filing_evidence": {
                "status": "insufficient",
                "explicit_company_explanations": [],
            }
        },
    }

    guard = AgentService._validate_model_output(
        "经营现金流同比下降约1.17亿元，主要原因是收入规模收缩。",
        evidence,
    )

    assert guard["passed"] is False
    assert (
        "缺少公司原文时不能把经营现金流变化归因于收入收缩"
        in guard["unsupported_market_inferences"]
    )


def test_stock_guard_removes_static_bridge_business_cause_but_keeps_financial_facts():
    evidence = {
        "type": "stock_research",
        "symbol": "000065.SZ",
        "financial_drivers": {
            "confirmed_mechanical_drivers": [
                {
                    "label": "毛利率变化对毛利的机械影响",
                    "calculation_nature": "static_counterfactual",
                    "statement": "按本期收入静态测算对应毛利增加0.98亿元。",
                }
            ]
        },
    }
    answer = (
        "营收与净利润同比下降，增长事实承压。"
        "毛利率提高按本期收入静态测算对应毛利增加0.98亿元，"
        "说明利润下滑并非来自成本端恶化。"
        "这一测算不是已确认的经营原因。"
        "经营现金流仍需与可比报告期分别核对，不能由毛利桥代替。"
        "公司原文尚未说明毛利率变化来自价格、结构、成本还是交付。"
    )

    guard = AgentService._validate_model_output(answer, evidence)
    repaired = AgentService._repair_guard_failure(answer, evidence, guard)

    assert guard["passed"] is False
    assert (
        "静态毛利桥不能改写为已确认经营原因" in guard["unsupported_market_inferences"]
    )
    assert repaired is not None
    assert "说明利润下滑并非来自成本端恶化" not in repaired[0]
    assert "营收与净利润同比下降" in repaired[0]
    assert "不是已确认的经营原因" in repaired[0]
    assert repaired[1]["passed"] is True


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
    ordinary_evidence = {**evidence, "user_question": "今天为什么上涨？"}
    ordinary_guard = AgentService._validate_model_output(answer, ordinary_evidence)
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
    assert (
        "行业成分使用未复权补充行情时必须说明证券来源和除权边界"
        in guard["semantic_conflicts"]
    )
    assert repaired is not None
    assert "成分行情口径补充" in repaired[0]
    assert "贝特瑞（920185.BJ）使用新浪公开未复权日线补充" in repaired[0]
    assert "另有 49 只使用前复权日线" in repaired[0]
    assert "除权除息" in repaired[0]
    assert repaired[1]["passed"] is True
    assert safe["passed"] is True
    assert raw_internal["passed"] is False
    assert raw_internal["private_operational_patterns"]
    assert unsafe_source_guard["passed"] is False
    assert unsafe_source_guard["private_operational_patterns"]
    assert unsafe_source_repaired is not None
    assert "当前数据源未返回" not in unsafe_source_repaired[0]
    assert (
        "贝特瑞（920185.BJ）使用新浪公开未复权日线补充" in (unsafe_source_repaired[0])
    )
    assert unsafe_source_repaired[1]["passed"] is True
    assert combined_unsafe_guard["passed"] is False
    assert combined_unsafe_repaired is not None
    assert "当前行情源未返回" not in combined_unsafe_repaired[0]
    assert (
        "贝特瑞（920185.BJ）使用新浪公开未复权日线补充" in (combined_unsafe_repaired[0])
    )
    assert combined_unsafe_repaired[1]["passed"] is True
    assert ordinary_guard["passed"] is True
    assert "行业成分使用未复权补充行情时必须说明证券来源和除权边界" not in (
        ordinary_guard["semantic_conflicts"]
    )


def test_component_source_appendix_summarizes_truncated_fallback_names():
    evidence = {
        "type": "stock_research",
        "stock_market_context": {
            "exact_industry_index": {
                "component_breadth": {
                    "status": "available",
                    "coverage": {
                        "constituents": 50,
                        "available_returns": 50,
                        "primary_adjusted_returns": 1,
                        "fallback_unadjusted_returns": 49,
                    },
                    "source_fallbacks": [
                        {"symbol": "000009.SZ", "name": "中国宝安"},
                        {"symbol": "000973.SZ", "name": "佛塑科技"},
                    ],
                }
            }
        },
    }

    appendix = AgentService._stock_component_source_boundary_appendix(evidence)

    assert appendix is not None
    assert "共 49 只成分" in appendix
    assert "例如 中国宝安（000009.SZ）、佛塑科技（000973.SZ）" in appendix
    assert "另有 1 只使用前复权日线" in appendix


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
    assert (
        "用户明确询问成分贡献时必须给出标的估算贡献和口径边界"
        in missing["semantic_conflicts"]
    )
    assert complete["passed"] is True
    assert wrong_metric["passed"] is False
    assert (
        "60日累计收益不能误用最大回撤数值"
        in wrong_metric["unsupported_market_inferences"]
    )


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
        "通信设备50只成分中，上涨16只（占32%）、下跌34只（占68%）、平盘0只。",
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
    assert (
        "用户明确询问行业成分涨跌家数时必须给出上涨下跌平盘家数"
        in (guard["semantic_conflicts"])
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
        workspace_root=tmp_path / "workspaces-contribution-repair",
        hermes_enabled=True,
    )
    database = Database(guarded_settings.workspace_root)
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
        model_answer + "\n无证据传闻称当日资金规模为9999亿元，这一行应被删除。"
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
    assert (
        "用户明确询问成分贡献时必须给出标的估算贡献和口径边界"
        in (mixed_guard["semantic_conflicts"])
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
        "provenance": {"market_timestamp": "2026-07-21T15:00:00+08:00"},
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


def test_model_language_cleanup_removes_accidentally_repeated_opening_passage():
    opening = (
        "今天A股与此前形成了非常明显的反差，主要指数从同步下跌转为全面上涨，"
        "但同日资讯没有提供可确认的直接触发事件。"
    )
    answer = (
        f"{opening}只能先确认价格和广度"
        f"{opening}只能先确认价格和广度事实本身。\n\n第二段。"
    )

    cleaned = AgentService._clean_user_facing_model_language(answer)

    assert cleaned == f"{opening}只能先确认价格和广度事实本身。\n\n第二段。"


def test_model_language_cleanup_neutralizes_misleading_systemic_heading():
    cleaned = AgentService._clean_user_facing_model_language(
        '**二、能确认的"非系统性拖累"**\n\n全市场系统性拖累不能确认。'
    )

    assert "**二、市场与行业对照**" in cleaned
    assert '能确认的"非系统性拖累"' not in cleaned


def test_model_language_cleanup_softens_absolute_causality_wording():
    cleaned = AgentService._clean_user_facing_model_language(
        '全市场上涨家数占优，不存在系统性拖累。这被称为"当前最可能的市场解释"。'
    )

    assert "不存在系统性拖累" not in cleaned
    assert "当日事实不支持全市场普跌解释" in cleaned
    assert "当前最可能的市场解释" not in cleaned
    assert "市场资讯反复提及的解释" in cleaned


def test_model_language_cleanup_keeps_relative_performance_out_of_causal_claims():
    cleaned = AgentService._clean_user_facing_model_language(
        "今日下跌属于独立于大市的个股回调，不能归结为系统性拖累。"
    )

    assert "独立于大市" not in cleaned
    assert "不能归结为系统性拖累" not in cleaned
    assert "相对大市表现明显分化" in cleaned
    assert "当日事实不支持全市场普跌解释" in cleaned
    assert "具体驱动仍未确认" in cleaned


def test_model_language_cleanup_does_not_turn_market_comparison_into_causality():
    cleaned = AgentService._clean_user_facing_model_language(
        "7月23日全市场普涨，当日盘面不支持系统性普跌拖累个股。"
    )

    assert "系统性普跌拖累个股" not in cleaned
    assert "当日事实不支持全市场普跌解释" in cleaned


def test_model_language_cleanup_neutralizes_unverified_event_causality():
    cleaned = AgentService._clean_user_facing_model_language(
        "综合来看，今日大跌主要表现为除权除息公告引发的提前调整与前期急涨后的回吐，"
        "但当日具体驱动尚未得到强确认。"
    )

    assert "公告引发" not in cleaned
    assert "主要表现为" not in cleaned
    assert "现有证据只能确认价格下跌与相对表现，具体驱动仍未确认" in cleaned


def test_stock_guard_rejects_unverified_event_causality():
    answer = "今日大跌主要表现为除权除息公告引发的提前调整与前期急涨后的回吐。"
    evidence = {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "guard_source_text": answer,
    }

    guard = AgentService._validate_model_output(answer, evidence)

    assert guard["passed"] is False
    assert (
        "缺少事件或业务证据时不能用技术指标行业轮动或业务结构解释个股涨跌"
        in guard["unsupported_market_inferences"]
    )


def test_model_language_cleanup_neutralizes_self_factor_and_resonance_claims():
    cleaned = AgentService._clean_user_facing_model_language(
        "中兴通讯下跌主要来自个股自身因素，同日大盘普涨不支持系统性拖累。"
        "今日下跌更多体现为高波动下的获利回吐和基本面隐忧共振。"
        "20日年化波动率较高，回落不意外。"
    )

    assert "个股自身因素" not in cleaned
    assert "获利回吐" not in cleaned
    assert "基本面隐忧共振" not in cleaned
    assert "回落不意外" not in cleaned
    assert "具体驱动仍未确认" in cleaned
    assert "同日市场事实不支持全市场普跌解释" in cleaned


def test_model_language_cleanup_neutralizes_independent_performance_wording():
    cleaned = AgentService._clean_user_facing_model_language(
        "当日事实不支持全市场普跌解释解释；当日不支持全市场系统性拖累。"
        "中兴通讯该日下跌属于与大盘方向不同的独立表现。"
    )

    assert "解释解释" not in cleaned
    assert "系统性拖累" not in cleaned
    assert "独立表现" not in cleaned
    assert "当日事实不支持全市场普跌解释" in cleaned
    assert "相对市场方向明显分化，但具体驱动仍未确认" in cleaned


def test_stock_guard_rejects_self_factor_and_resonance_claims():
    evidence = {
        "type": "stock_research",
        "symbol": "000063.SZ",
    }

    for answer in (
        "中兴通讯下跌主要来自个股自身因素。",
        "它今天的跌幅更多是自身因素主导的。",
        "中兴通讯下跌更像跟公司当天自己的情况有关，而不是被市场整体拖累。",
        "中兴通讯下跌更可能是公司自身或通信设备板块的因素。",
        "中兴通讯跌的原因主要得看公司自身或者通信设备板块的情况。",
        "中兴通讯今天属于个股层面的独立走弱。",
        "今日下跌更多体现为高波动下的获利回吐和基本面隐忧共振。",
    ):
        guard = AgentService._validate_model_output(answer, evidence)
        assert guard["passed"] is False
        assert (
            "缺少事件或业务证据时不能用技术指标行业轮动或业务结构解释个股涨跌"
            in guard["unsupported_market_inferences"]
        )


def test_stock_guard_removes_speculative_fund_flow_and_timing_explanations():
    evidence = {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "user_question": "中兴通讯今天为什么跌？",
    }
    answer = (
        "中兴通讯相对市场偏弱，但市场与行业对比本身只能确认同步或分化，不能证明具体因果。"
        "当前能确认的是价格方向与相对表现，不能从横截面对比直接推出公司发生了什么。"
        "如果没有日期对齐的公司材料，回答就应该停在具体驱动仍未确认这一层。"
        "当天也没有取得能够直接确认公司特定驱动的正式披露，现有媒体标题只能作为待核验线索。"
        "这种格局说明相对弱势更可能是短期资金行为或前期强势后的节奏变化，"
        "而非公司基本面出了问题。具体驱动仍未确认。"
    )

    guard = AgentService._validate_model_output(answer, evidence)
    repaired = AgentService._repair_guard_failure(answer, evidence, guard)

    assert guard["passed"] is False
    assert (
        "缺少事件或业务证据时不能用技术指标行业轮动或业务结构解释个股涨跌"
        in guard["unsupported_market_inferences"]
    )
    assert repaired is not None
    assert "短期资金行为" not in repaired[0]
    assert "节奏变化" not in repaired[0]
    assert "基本面出了问题" not in repaired[0]
    assert repaired[1]["passed"] is True


def test_stock_guard_repairs_price_cause_story_from_financing_and_dividend_clues():
    evidence = {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "user_question": "中兴通讯今天为什么跌？",
        "research_plan": {"focus": "price_cause"},
        "metrics": {"latest_close": 35.25, "return_1d_pct": 0.71},
        "provenance": {"market_timestamp": "2026-07-27T01:30:00+00:00"},
        "current_quote": {
            "price": 34.2,
            "pct_change": -2.98,
            "market_timestamp": "2026-07-28T12:05:03+08:00",
        },
    }
    answer = (
        "中兴通讯今天盘中跌了大约3%，最新报价34.20元。"
        "融资余额处于相对高位，意味着借钱买入的资金对价格波动往往更敏感；"
        "股权登记日前后，部分短线资金也可能因为拿完分红就走而选择卖出。"
        "股权登记日在技术上会使当日参考价自动扣除分红金额，这可能是额外的技术性因素。"
        "等今天收盘后的除权除息公告出来，再判断股权登记除息对价格的具体影响。"
        "可以等收盘后看公司有没有发权益分派实施公告。"
        "现阶段能确认的是盘中价格下跌，并没有同日公司公告能把这次价格变化锁定到"
        "某个公司级事件；这些媒体标题只能帮助定位后续核验方向，具体驱动仍未确认。"
    )

    guard = AgentService._validate_model_output(answer, evidence)
    repaired = AgentService._repair_guard_failure(answer, evidence, guard)

    assert guard["passed"] is False
    assert (
        "缺少事件或业务证据时不能用技术指标行业轮动或业务结构解释个股涨跌"
        in guard["unsupported_market_inferences"]
    )
    assert repaired is not None
    assert "最新报价34.20元" in repaired[0]
    assert "资金对价格波动往往更敏感" not in repaired[0]
    assert "拿完分红就走" not in repaired[0]
    assert "当日参考价自动扣除分红金额" not in repaired[0]
    assert "收盘后的除权除息公告" not in repaired[0]
    assert "具体驱动仍未确认" in repaired[0]
    assert repaired[1]["passed"] is True


def test_stock_guard_removes_financing_sensitivity_and_undisclosed_factor_story():
    evidence = {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "user_question": "中兴通讯今天为什么跌？",
        "research_plan": {"focus": "price_cause"},
    }
    answer = (
        "融资余额占流通市值比例不算低，这类资金对价格波动往往更敏感。"
        "换句话说，借钱买这只股票的资金比例不算低，这类资金对价格波动更敏感。"
        "这条媒体线索不能直接解释今天为什么跌。"
        "如果不是，就要进一步留意公司是否有其他尚未被正式披露的事项。"
        "接下来值得留意成交量，这可以帮助判断是否有什么还未披露的重要变化。"
        "目前只能等公司可能发布的正式公告。"
        "目前没有同日公司公告，具体驱动仍未确认。"
    )

    guard = AgentService._validate_model_output(answer, evidence)

    assert guard["passed"] is False
    assert (
        "缺少事件或业务证据时不能用技术指标行业轮动或业务结构解释个股涨跌"
        in guard["unsupported_market_inferences"]
    )


def test_model_language_cleanup_removes_duplicate_chinese_punctuation():
    cleaned = AgentService._clean_user_facing_model_language(
        "先核对下一次披露。；再等待完整日线；。"
    )

    assert "。；" not in cleaned
    assert "；。" not in cleaned
    assert cleaned == "先核对下一次披露；再等待完整日线。"


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
            "announcements": [{"published_at": "2026-07-20", "title": "回购结果公告"}],
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
    assert (
        "个股情景触发与失效方向必须与确定性条件一致"
        in guard["unsupported_market_inferences"]
    )


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
        workspace_root=tmp_path / "workspaces-market-metric-consistency",
        hermes_enabled=True,
    )
    database = Database(guarded_settings.workspace_root)
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
        message="这段判断的反方证据是什么？什么时候需要重新判断？",
        evidence=evidence,
        model_tier="economy",
        execute_agent=True,
    )

    assert run["status"] == "guarded"
    assert "代表性指数可用 4/4 个" in run["answer"]
    assert "什么时候需要重新判断：" in run["answer"]
    assert "两条均线均未被跌破" not in run["answer"]
    assert "罗素2000已经在60日线下方" not in run["answer"]
    assert "四个指数中最低" not in run["answer"]
    assert set(run["usage"]["output_guard"]["unsupported_market_inferences"]) == {
        "指数波动率最高最低表述必须与当前证据排序一致",
        "均线是否跌破的表述必须与最新收盘和均线位置一致",
        "用户明确询问何时需要重新判断时回答必须说明对应情况",
    }


def test_model_language_cleanup_translates_market_driver_field_phrase():
    cleaned = AgentService._clean_user_facing_model_language(
        "当前证据中 market_drivers 的资讯项为空。"
    )

    assert cleaned == "当前没有与本问题直接相关的市场资讯。"


def test_market_reassessment_cleanup_removes_invented_future_rules():
    evidence = {
        "type": "market_brief",
        "user_question": "今天普涨，什么时候需要重新判断？",
        "indices": [{"metrics": {"ma20": 3904.0}}],
    }
    answer = (
        "如果全市场上涨家数连续两到三个交易日维持在三分之二以上，"
        "说明修复更强。后续关注指数能否站上20日均线或5日均线。"
    )

    cleaned = agent_module._normalize_market_reassessment_language(answer, evidence)

    assert "连续两到三个交易日" not in cleaned
    assert "三分之二" not in cleaned
    assert "5日均线" not in cleaned
    assert "后续完整交易日" in cleaned
    assert "上涨家数仍占明显优势" in cleaned


def test_market_reassessment_cleanup_removes_method_thresholds_and_short_windows():
    evidence = {
        "type": "market_brief",
        "user_question": "今天普涨，哪些已有数据会让我重新判断？",
        "indices": [{"metrics": {"ma20": 3904.0}}],
    }
    answer = (
        "31日普涨分类门槛是上涨比例超过65%，且净涨家数大于500家。"
        "全市场涨跌家数的方向能否在后续交易日持续保持优势。"
        "如果一两天内又跌回均线下方，就说明修复无效。"
    )

    cleaned = agent_module._normalize_market_reassessment_language(answer, evidence)

    assert "分类门槛" not in cleaned
    assert "65%" not in cleaned
    assert "500家" not in cleaned
    assert "持续保持" not in cleaned
    assert "一两天" not in cleaned
    assert "后续完整交易日" in cleaned
    assert "又跌回均线下方，就说明修复无效" in cleaned


def test_market_reassessment_cleanup_preserves_sentence_after_vague_window():
    evidence = {
        "type": "market_brief",
        "user_question": "接下来最值得观察什么？",
        "indices": [{"metrics": {"ma20": 3904.0}}],
    }
    answer = (
        "第一个看广度优势是否还在。如果接下来一两天内上涨家数明显减少，"
        "就需要重新判断。\n\n另一个看主要指数与20日均线的关系。"
    )

    cleaned = agent_module._normalize_market_reassessment_language(answer, evidence)

    assert "如果后续完整交易日里上涨家数明显减少，就需要重新判断" in cleaned
    assert "另一个看主要指数与20日均线的关系" in cleaned
    assert "如果接下来\n" not in cleaned


def test_market_reassessment_cleanup_corrects_ma20_cost_metaphor_locally():
    evidence = {
        "type": "market_brief",
        "user_question": "接下来最值得观察什么？",
        "indices": [{"metrics": {"ma20": 3904.0}}],
    }
    answer = (
        "二十日移动均线代表了最近一个月的平均持仓成本，"
        "价格逐步靠近它，只说明近期价格重心在改善。"
    )

    cleaned = agent_module._normalize_market_reassessment_language(answer, evidence)

    assert "平均持仓成本" not in cleaned
    assert "二十日均线是过去二十个交易日收盘价的滚动平均" in cleaned
    assert "价格逐步靠近它，只说明近期价格重心在改善" in cleaned

    vague_window = agent_module._normalize_market_reassessment_language(
        "二十日均线是过去若干个交易日收盘价的滚动平均。",
        evidence,
    )
    assert vague_window == "二十日均线是过去二十个交易日收盘价的滚动平均。"


def test_market_reassessment_cleanup_neutralizes_vague_window_and_ma_pressure():
    evidence = {
        "type": "market_brief",
        "user_question": "接下来最值得观察什么？",
        "indices": [{"metrics": {"ma20": 3904.0}}],
    }
    answer = (
        "如果之后几个完整交易日里广度仍在，就继续观察。"
        "如果指数始终被压在这条均线下方，中期趋势尚未改善。"
    )

    cleaned = agent_module._normalize_market_reassessment_language(answer, evidence)

    assert "如果后续完整交易日里广度仍在" in cleaned
    assert "仍位于这条均线下方" in cleaned
    assert "被压在" not in cleaned


def test_market_reassessment_cleanup_removes_duplicate_observation_language():
    evidence = {
        "type": "market_brief",
        "user_question": "今天普涨，什么时候需要重新判断？",
        "indices": [{"metrics": {"ma20": 3904.0}}],
    }
    answer = (
        "一要看后续完整交易日中，后续完整交易日里，"
        "全市场上涨家数是否仍占明显优势是否延续。"
    )

    cleaned = agent_module._normalize_market_reassessment_language(answer, evidence)

    assert cleaned == "一要看后续完整交易日里，全市场上涨家数是否仍占明显优势。"


def test_market_reassessment_cleanup_normalizes_vague_future_window():
    evidence = {
        "type": "market_brief",
        "user_question": "接下来最值得观察什么？",
    }
    answer = (
        "第一个是后续几个交易日里全市场的后续完整交易日里，"
        "上涨家数是否仍占明显优势。"
    )

    cleaned = agent_module._normalize_market_reassessment_language(answer, evidence)

    assert cleaned == "第一个是后续完整交易日里，上涨家数是否仍占明显优势。"


def test_market_guard_allows_natural_turnover_boundary_without_repair():
    evidence = {"type": "market_brief", "market_state": {}}
    answer = (
        "成交额较前一交易日增加，只说明当天交易更活跃，"
        "不能据此解读为资金净流入、机构加仓或市场参与意愿回升。"
    )

    guard = AgentService._validate_model_output(answer, evidence)

    assert guard["passed"] is True
    assert guard["unsupported_market_inferences"] == []


def test_market_guard_accepts_turnover_total_wording_as_complete_answer():
    evidence = {
        "type": "market_brief",
        "user_question": "请结合全市场成交额解释今天的行情。",
        "market_state": {},
        "market_breadth": {
            "turnover": {
                "status": "available",
                "total_amount_100m_cny": 25590.66,
            }
        },
    }
    answer = (
        "全市场当日成交总额为25590.66亿元，说明交易金额较大；"
        "这并不等同于资金净流入或机构加仓。"
    )

    guard = AgentService._validate_model_output(answer, evidence)

    assert guard["passed"] is True
    assert guard["semantic_conflicts"] == []
    assert guard["unsupported_market_inferences"] == []


def test_market_guard_allows_negated_style_leadership_boundary():
    evidence = {
        "type": "market_brief",
        "market_state": {},
        "indices": [
            {
                "symbol": "000001.SS",
                "name": "上证综指",
                "same_date_as_analysis_target": True,
                "metrics": {"return_1d_pct": 0.72},
            },
            {
                "symbol": "399006.SZ",
                "name": "创业板指",
                "same_date_as_analysis_target": True,
                "metrics": {"return_1d_pct": 3.06},
            },
        ],
    }
    answer = (
        "上证综指与创业板指涨幅存在差异，但没有风格指数和权重贡献数据，"
        "不能把它定性为中小市值风格领涨。"
    )

    guard = AgentService._validate_model_output(answer, evidence)

    assert guard["passed"] is True
    assert guard["unsupported_market_inferences"] == []


def test_market_guard_repair_keeps_cautious_turnover_and_drops_flow_story():
    evidence = {"type": "market_brief", "market_state": {}}
    answer = (
        "今天多数个股上涨，市场体感明显强于部分宽基指数。\n\n"
        "成交额放大，说明增量资金集中流入科技板块。\n\n"
        "成交额只说明交易活跃度，不说明资金净流入或机构意图。\n\n"
        "目前可以确认的是当日参与面较广，具体事件驱动仍需核验。"
    )

    guard = AgentService._validate_model_output(answer, evidence)
    repaired = AgentService._repair_guard_failure(answer, evidence, guard)

    assert guard["passed"] is False
    assert repaired is not None
    assert "增量资金集中流入" not in repaired[0]
    assert "不说明资金净流入" in repaired[0]
    assert repaired[1]["passed"] is True


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
    answer = "5个代表性指数全部上涨。\n如果跌破5日均线，B浪反弹将失效。"

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
        "indices": [{"metrics": {"return_5d_pct": -4.43, "ma20": 15186.8}}],
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


def test_numeric_guard_accepts_transparent_ratio_from_supported_percentages():
    evidence = {
        "type": "market_brief",
        "indices": [
            {
                "name": "科创50",
                "metrics": {"volatility_20d_annualized_pct": 71.5},
            },
            {
                "name": "上证综指",
                "metrics": {"volatility_20d_annualized_pct": 20.9},
            },
        ],
    }

    derived = AgentService._validate_model_output(
        "科创50的20日年化波动率为71.5%，约是上证综指20.9%的3.4倍。",
        evidence,
    )
    invented = AgentService._validate_model_output(
        "科创50的20日年化波动率为71.5%，约是上证综指20.9%的5.8倍。",
        evidence,
    )

    assert derived["passed"] is True
    assert invented["passed"] is False
    assert "5.8" in invented["unsupported_numbers"]


def test_stock_numeric_guard_does_not_trust_cross_stock_knowledge_numbers():
    evidence = {
        "type": "stock_research",
        "symbol": "000065.SZ",
        "display_name": "北方国际",
        "metrics": {"volatility_20d_annualized_pct": 32.9162},
        "knowledge_context": {
            "items": [
                {
                    "title": "我的最新研究行动与观察条件",
                    "excerpt": ("另一只股票最新价135.92元，20日年化波动率115.10%。"),
                }
            ]
        },
    }

    current_stock = AgentService._validate_model_output(
        "北方国际20日年化波动率约32.92%。",
        evidence,
    )
    polluted = AgentService._validate_model_output(
        "北方国际20日年化波动率超过115.10%。",
        evidence,
    )

    assert current_stock["passed"] is True
    assert polluted["passed"] is False
    assert polluted["unsupported_numbers"] == ["115.10%"]


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
    invented = AgentService._validate_model_output("道指高于MA60约9.9%。", evidence)

    assert valid["passed"] is True
    assert invented["passed"] is False
    assert "9.9%" in invented["unsupported_numbers"]


def test_numeric_guard_accepts_natural_market_count_and_point_rounding():
    evidence = {
        "type": "market_brief",
        "indices": [
            {
                "name": "沪深300",
                "metrics": {"latest_close": 4549.72, "ma20": 4712.458},
            }
        ],
        "market_breadth": {
            "breadth": {
                "total": 5533,
                "advancers": 4708,
                "decliners": 714,
                "unchanged": 111,
            }
        },
    }

    guard = AgentService._validate_model_output(
        "今天上涨4700多只、下跌不到800只；沪深300距20日均线约160点左右。",
        evidence,
    )

    assert guard["passed"] is True
    assert guard["unsupported_numbers"] == []


def test_numeric_guard_accepts_previous_session_return_derived_from_recent_bars():
    evidence = {
        "type": "market_brief",
        "indices": [
            {
                "name": "深证成指",
                "metrics": {"return_1d_pct": 0.72},
                "recent_bars": [
                    {"timestamp": "2026-07-29", "close": 100.0},
                    {"timestamp": "2026-07-30", "close": 97.27},
                    {"timestamp": "2026-07-31", "close": 97.9703},
                ],
            }
        ],
    }

    guard = AgentService._validate_model_output(
        "深证成指昨天跌2.73%，今天涨0.72%。",
        evidence,
    )

    assert guard["passed"] is True
    assert guard["unsupported_numbers"] == []


def test_market_downtrend_guard_allows_explicit_negation():
    evidence = {
        "type": "market_brief",
        "indices": [{"metrics": {"trend_state": "中期偏弱"}}],
    }

    safe = AgentService._validate_model_output(
        "中期偏弱不等于已确认下行趋势。",
        evidence,
    )
    natural_safe = AgentService._validate_model_output(
        "整体格局是轻微收跌，而非大幅下行。",
        evidence,
    )
    direct_boundary = AgentService._validate_model_output(
        "此前仍为正收益，不能直接确认新下跌趋势已开启。",
        evidence,
    )
    no_trend = AgentService._validate_model_output(
        "相邻交易日方向相反，说明市场没有形成持续的上涨或下跌趋势。",
        evidence,
    )
    overclaim = AgentService._validate_model_output(
        "当前趋势依然向下。",
        evidence,
    )

    assert safe["passed"] is True
    assert natural_safe["passed"] is True
    assert direct_boundary["passed"] is True
    assert no_trend["passed"] is True
    assert overclaim["passed"] is False
    assert overclaim["unsupported_market_inferences"] == [
        "中期偏弱不能直接改写为已确认的下行趋势"
    ]


def test_market_guard_accepts_natural_unconfirmed_boundary_wording():
    evidence = {
        "type": "market_brief",
        "user_question": "说明反方证据和还不能确认的原因",
        "indices": [],
    }

    guard = AgentService._validate_model_output(
        "### 反方证据或未能确认之处\n当前缺少充分交叉验证，具体驱动仍有待核验。",
        evidence,
    )

    assert guard["passed"] is True


def test_market_cause_guard_accepts_natural_down_wording_and_major_index_scope():
    evidence = {
        "type": "market_brief",
        "user_question": "美股为什么收盘跌了，请说明还不能确认的原因",
        "question_focus": {"key": "market_cause"},
        "analysis_target": {"market_date": "2026-07-22"},
        "indices": [
            {
                "name": "标普500",
                "symbol": "^GSPC",
                "same_date_as_analysis_target": True,
                "metrics": {"return_1d_pct": -0.1364},
            },
            {
                "name": "纳斯达克综合",
                "symbol": "^IXIC",
                "same_date_as_analysis_target": True,
                "metrics": {"return_1d_pct": -0.5663},
            },
            {
                "name": "道琼斯工业指数",
                "symbol": "^DJI",
                "same_date_as_analysis_target": True,
                "metrics": {"return_1d_pct": -0.0116},
            },
            {
                "name": "罗素2000",
                "symbol": "^RUT",
                "same_date_as_analysis_target": True,
                "metrics": {"return_1d_pct": -0.9192},
            },
        ],
    }
    answer = (
        "2026年7月22日美股三大指数收跌：标普500跌0.14%，"
        "纳斯达克综合跌0.57%，道琼斯工业指数跌0.01%。"
        "纳斯达克综合在三大指数中跌幅最大；罗素2000下跌0.92%。"
        "当前尚不能把收跌归因到单一原因。"
    )

    guard = AgentService._validate_model_output(answer, evidence)

    assert guard["passed"] is True


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
    assert (
        "股东户数下降不能直接写成机构或主力吸筹"
        in absorption["unsupported_market_inferences"]
    )
    assert northbound["passed"] is False
    assert (
        "香港中央结算代理人有限公司不能自动等同北向资金"
        in northbound["unsupported_market_inferences"]
    )
    assert channel_label["passed"] is False
    assert (
        "香港中央结算有限公司不能在缺少身份口径时直接标注为北向通道"
        in channel_label["unsupported_market_inferences"]
    )
    assert land_connect_label["passed"] is False
    assert (
        "香港中央结算有限公司不能在缺少身份口径时直接标注为北向通道"
        in land_connect_label["unsupported_market_inferences"]
    )
    assert generic_channel_label["passed"] is False
    assert (
        "香港中央结算有限公司不能在缺少身份口径时直接标注为北向通道"
        in generic_channel_label["unsupported_market_inferences"]
    )
    assert etf_motive["passed"] is False
    assert (
        "十大股东名单变化不能直接归因为ETF主动或被动调仓"
        in etf_motive["unsupported_market_inferences"]
    )
    assert filing_deadline["passed"] is False
    assert (
        "缺少披露日历证据时不能补写下一份报告的预计截止时间"
        in filing_deadline["unsupported_market_inferences"]
    )
    assert holder_count_deadline["passed"] is False
    assert (
        "缺少固定披露频率证据时不能补写下一次股东户数的预计天数"
        in holder_count_deadline["unsupported_market_inferences"]
    )
    assert wrong_streak["passed"] is False
    assert (
        "股东户数连续变化次数或方向与确定性证据不一致"
        in wrong_streak["unsupported_market_inferences"]
    )
    assert unsupported_top10_history["passed"] is False
    assert (
        "缺少历史十大股东合计序列时不能声称前十持股跨期持平或变化"
        in unsupported_top10_history["unsupported_market_inferences"]
    )
    assert inferred_controller["passed"] is False
    assert (
        "股东名单本身不能补写控股国资国家队等身份标签"
        in inferred_controller["unsupported_market_inferences"]
    )
    assert etf_trading_label["passed"] is False
    assert (
        "十大股东名单变化不能直接归因为ETF主动或被动调仓"
        in etf_trading_label["unsupported_market_inferences"]
    )
    assert foreign_intent["passed"] is False
    assert (
        "香港中央结算持股不能直接证明外资配置意愿"
        in foreign_intent["unsupported_market_inferences"]
    )


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


def test_shareholder_guard_accepts_real_answer_with_explicit_boundaries():
    answer = (
        "中兴通讯最新股东户数披露截至2026年7月20日（公告日7月21日），户数为"
        "620,081户，较上次（2026年7月10日）的575,136户增加44,945户，上升"
        "7.815%。\n\n"
        "这说明持有人数量增加，持股呈现分散线索。同期（7月10日至7月20日）股价"
        "下跌16.78%，但股东户数上升与股价下跌之间的因果关系尚未确认。\n\n"
        "不能推断的内容：1）不能直接将股东户数上升预测为股价将继续下跌；2）不能"
        "解读为机构出货或主力离场；3）股东户数下降才对应持股集中度上升线索，本次"
        "为上升，属于分散，不能反向类推；4）最近一次变化方向为上升，仅一次，尚未"
        "形成至少两次连续同向变化的趋势，不宜外推；5）十大股东数据报告期为2026年"
        "3月31日，是报告期存量，不能当作当前实时持仓；前十名合计持股41.34%，前三"
        "名36.96%，但不能与往期比较，无法判断集中度较上个报告期变化；6）“香港中央"
        "结算代理人有限公司”对应H股登记代理口径，“香港中央结算有限公司”是A股流通"
        "股东，其持股减少不能直接等同于北向资金当日流出；7）“新进”仅表示进入前十"
        "名单，不能解释为主动建仓或机构增配。\n\n"
        "下一次应核对的披露：等待下一次股东户数披露，确认分散方向是否持续；等待"
        "下一份定期报告（如2026年半年报）更新十大股东，以对照持股变化。"
    )
    evidence = {
        "type": "shareholder_structure",
        "holder_count_streak_direction": "increase",
        "holder_count_streak_count": 1,
        "top10_historical_comparison_available": False,
        "guard_source_text": answer,
    }

    guard = AgentService._validate_model_output(answer, evidence)

    assert guard["passed"] is True
    assert guard["unsupported_market_inferences"] == []


def test_shareholder_guard_does_not_accept_a_reversed_boundary():
    evidence = {
        "type": "shareholder_structure",
        "top10_historical_comparison_available": True,
    }

    guard = AgentService._validate_model_output(
        "十大股东不是实时持仓，而是当日资金流。",
        evidence,
    )

    assert guard["passed"] is False
    assert (
        "十大股东报告期存量不能写成实时持仓或当日资金流"
        in guard["unsupported_market_inferences"]
    )


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
    actions = (
        [
            {
                "key": f"triggered-{index}",
                "status": "triggered",
                "title": f"触发{index}",
                "current_evidence": "证据",
                "next_step": "复核",
            }
            for index in range(4)
        ]
        + [
            {
                "key": f"pending-{index}",
                "status": "pending_data",
                "title": f"补证{index}",
                "current_evidence": "缺口",
                "next_step": "补证",
            }
            for index in range(3)
        ]
        + [
            {
                "key": f"watching-{index}",
                "status": "watching",
                "title": f"观察{index}",
                "current_evidence": "未触发",
                "next_step": "观察",
            }
            for index in range(2)
        ]
    )
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
        workspace_root=tmp_path / "stream-protocol-workspaces",
        hermes_bin=hermes_bin,
        hermes_enabled=True,
    )
    database = Database(guarded_settings.workspace_root)
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
    captured = {}

    def fake_popen(command, **kwargs):
        captured["command"] = command
        return _FakeStreamingProcess(lines)

    monkeypatch.setattr(
        "app.services.agent_hermes_execution.subprocess.Popen", fake_popen
    )
    updates = []

    answer, usage = service._execute_hermes_streaming(
        model_tier="economy",
        run_dir=run_dir,
        user_workspace=tmp_path,
        evidence={
            "type": "market_brief",
            "indices": [{"name": "上证综指", "metrics": {"return_1d_pct": -1.23}}],
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
    assert all(item["is_guarded_partial"] is True for item in updates)
    assert usage["streaming"]["raw_delta_events"] == 2
    assert usage["streaming"]["visible_events"] == 2
    assert usage["streaming"]["withheld_segments"] == 1
    assert usage["streaming"]["max_tokens"] == 900
    assert usage["streaming"]["max_iterations"] == 4
    assert usage["streaming"]["reasoning_effort"] == "none"
    max_tokens_index = captured["command"].index("--max-tokens")
    assert captured["command"][max_tokens_index + 1] == "900"
    max_iterations_index = captured["command"].index("--max-iterations")
    assert captured["command"][max_iterations_index + 1] == "4"
    reasoning_index = captured["command"].index("--reasoning-effort")
    assert captured["command"][reasoning_index + 1] == "none"


def test_streaming_bridge_keeps_standalone_markdown_heading_as_final_prefix(
    tmp_path: Path, settings, monkeypatch
):
    bin_dir = tmp_path / "hermes-heading" / "venv" / "bin"
    bin_dir.mkdir(parents=True)
    hermes_bin = bin_dir / "hermes"
    python_bin = bin_dir / "python"
    hermes_bin.touch()
    python_bin.touch()
    guarded_settings = replace(
        settings,
        workspace_root=tmp_path / "stream-heading-workspaces",
        hermes_bin=hermes_bin,
        hermes_enabled=True,
    )
    database = Database(guarded_settings.workspace_root)
    database.initialize()
    service = AgentService(database, guarded_settings)
    run_dir = tmp_path / "run-heading"
    run_dir.mkdir()
    (run_dir / "prompt.md").write_text("测试标题流式协议", encoding="utf-8")
    final_answer = "**直接回答：当前证据不足。** 后续仍需核验。"
    lines = [
        json.dumps(
            {"type": "delta", "text": "**直接回答：当前证据不足。** "},
            ensure_ascii=False,
        )
        + "\n",
        json.dumps(
            {"type": "delta", "text": "后续仍需核验。"},
            ensure_ascii=False,
        )
        + "\n",
        json.dumps(
            {
                "type": "final",
                "answer": final_answer,
                "usage": {"model": "fake-stream"},
            },
            ensure_ascii=False,
        )
        + "\n",
    ]
    monkeypatch.setattr(
        "app.services.agent_hermes_execution.subprocess.Popen",
        lambda *args, **kwargs: _FakeStreamingProcess(lines),
    )
    updates = []

    answer, usage = service._execute_hermes_streaming(
        model_tier="economy",
        run_dir=run_dir,
        user_workspace=tmp_path,
        evidence={"type": "market_brief"},
        trusted_context=None,
        stream_callback=updates.append,
    )

    assert [item["draft"] for item in updates] == [
        "**直接回答：当前证据不足。**",
        final_answer,
    ]
    assert answer == final_answer
    assert answer.startswith(updates[-1]["draft"])
    assert usage["streaming"]["withheld_segments"] == 0


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
        workspace_root=tmp_path / "stream-completeness-workspaces",
        hermes_bin=hermes_bin,
        hermes_enabled=True,
    )
    database = Database(guarded_settings.workspace_root)
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
        "app.services.agent_hermes_execution.subprocess.Popen",
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
        "当前反弹尚未扭转短期回落格局。需要重新判断的情况：后续事实若与当前证据冲突，就需要重新评估。",
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
        workspace_root=tmp_path / "stream-stock-completeness-workspaces",
        hermes_bin=hermes_bin,
        hermes_enabled=True,
    )
    database = Database(guarded_settings.workspace_root)
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
        "app.services.agent_hermes_execution.subprocess.Popen",
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
    assert "静态估算贡献-0.24个百分点" in drafts[-1]
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
        workspace_root=tmp_path / "stream-quote-workspaces",
        hermes_bin=hermes_bin,
        hermes_enabled=True,
    )
    database = Database(guarded_settings.workspace_root)
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
        "app.services.agent_hermes_execution.subprocess.Popen",
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
            "provenance": {"market_timestamp": "2026-07-20T15:00:00+08:00"},
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


def test_streaming_bridge_injects_short_quote_anchor_when_model_omits_it(
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
        workspace_root=tmp_path / "stream-quote-anchor-workspaces",
        hermes_bin=hermes_bin,
        hermes_enabled=True,
    )
    database = Database(guarded_settings.workspace_root)
    database.initialize()
    service = AgentService(database, guarded_settings)
    run_dir = tmp_path / "run-quote-anchor"
    run_dir.mkdir()
    (run_dir / "prompt.md").write_text("测试补充短报价锚点", encoding="utf-8")
    lines = [
        json.dumps(
            {"type": "delta", "text": "北方国际近20日仍处于回撤区间。"},
            ensure_ascii=False,
        )
        + "\n",
        json.dumps(
            {"type": "delta", "text": "财务变化已经确认，但股价因果仍未确认。"},
            ensure_ascii=False,
        )
        + "\n",
        json.dumps(
            {
                "type": "final",
                "answer": (
                    "北方国际近20日仍处于回撤区间。"
                    "财务变化已经确认，但股价因果仍未确认。"
                ),
                "usage": {"model": "fake-stream"},
            },
            ensure_ascii=False,
        )
        + "\n",
    ]
    monkeypatch.setattr(
        "app.services.agent_hermes_execution.subprocess.Popen",
        lambda *args, **kwargs: _FakeStreamingProcess(lines),
    )
    updates = []

    answer, usage = service._execute_hermes_streaming(
        model_tier="economy",
        run_dir=run_dir,
        user_workspace=tmp_path,
        evidence={
            "type": "stock_research",
            "symbol": "000065.SZ",
            "display_name": "北方国际",
            "user_question": "请基于最新数据说明北方国际的回撤。",
            "current_quote": {
                "name": "北方国际",
                "currency": "CNY",
                "price": 9.04,
                "pct_change": -1.53,
                "market_timestamp": "2026-07-28T16:14:57+08:00",
                "market_date": "2026-07-28",
                "quote_label": "收盘后最新报价",
            },
            "provenance": {"market_timestamp": "2026-07-28T01:30:00+00:00"},
        },
        trusted_context=None,
        stream_callback=updates.append,
    )

    assert answer.startswith("北方国际近20日仍处于回撤区间")
    assert len(updates) == 1
    assert updates[0]["draft"].startswith(
        "最新行情：北方国际收盘后最新报价（2026-07-28）为9.04元，较前收盘下跌1.53%。"
    )
    assert "财务变化已经确认，但股价因果仍未确认" in updates[0]["draft"]
    assert usage["streaming"]["required_context_prefix_injected"] is True


def test_streaming_bridge_does_not_wait_for_component_source_appendix(
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
        workspace_root=tmp_path / "stream-component-boundary-workspaces",
        hermes_bin=hermes_bin,
        hermes_enabled=True,
    )
    database = Database(guarded_settings.workspace_root)
    database.initialize()
    service = AgentService(database, guarded_settings)
    run_dir = tmp_path / "run-component-boundary"
    run_dir.mkdir()
    (run_dir / "prompt.md").write_text("测试成分口径不阻塞首屏", encoding="utf-8")
    lines = [
        json.dumps(
            {
                "type": "delta",
                "text": "中兴通讯收盘后最新报价34.03元，跌3.46%。",
            },
            ensure_ascii=False,
        )
        + "\n",
        json.dumps(
            {
                "type": "delta",
                "text": "行业50只成分中上涨12只、下跌38只、平盘0只。",
            },
            ensure_ascii=False,
        )
        + "\n",
        json.dumps(
            {
                "type": "final",
                "answer": (
                    "中兴通讯收盘后最新报价34.03元，跌3.46%。"
                    "行业50只成分中上涨12只、下跌38只、平盘0只。"
                ),
                "usage": {"model": "fake-stream"},
            },
            ensure_ascii=False,
        )
        + "\n",
    ]
    monkeypatch.setattr(
        "app.services.agent_hermes_execution.subprocess.Popen",
        lambda *args, **kwargs: _FakeStreamingProcess(lines),
    )
    updates = []
    evidence = {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "display_name": "中兴通讯",
        "user_question": "中兴通讯为什么跌？",
        "current_quote": {
            "market_timestamp": "2026-07-28T16:14:00+08:00",
            "price": 34.03,
            "pct_change": -3.46,
            "quote_basis": "post_close_snapshot",
        },
        "stock_market_context": {
            "exact_industry_index": {
                "status": "same_market_date",
                "component_breadth": {
                    "status": "available",
                    "total_constituents": 50,
                    "advancers": 12,
                    "decliners": 38,
                    "unchanged": 0,
                    "coverage": {
                        "fallback_unadjusted_returns": 1,
                        "primary_adjusted_returns": 49,
                    },
                    "source_fallbacks": [{"symbol": "000063.SZ", "name": "中兴通讯"}],
                },
            }
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

    assert updates[0]["draft"] == "中兴通讯收盘后最新报价34.03元，跌3.46%。"
    assert "上涨12只、下跌38只、平盘0只" in updates[-1]["draft"]
    assert usage["streaming"]["visible_events"] == 2


def test_stock_repair_keeps_safe_first_sentence_when_industry_cause_is_removed():
    evidence = {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "display_name": "中兴通讯",
        "user_question": "中兴通讯为什么跌？",
        "current_quote": {
            "market_timestamp": "2026-07-28T16:14:00+08:00",
            "price": 34.03,
            "pct_change": -3.46,
        },
        "metrics": {"return_1d_pct": -2.29},
        "stock_market_context": {
            "exact_industry_index": {
                "status": "same_market_date",
                "return_1d_pct": -7.69,
                "stock_minus_industry_pct": 5.4,
                "component_breadth": {
                    "status": "available",
                    "advancers": 12,
                    "decliners": 38,
                    "unchanged": 0,
                },
            }
        },
    }
    answer = (
        "中兴通讯收盘后最新报价34.03元，跌了3.46%。"
        "行业多数成分下跌，因此更像行业普跌中的跟随，而非公司事件驱动。\n\n"
        "中兴通讯当日跌2.29%，跑赢行业5.4个百分点，"
        "说明核心是被行业整体拖累。\n\n"
        "当前可确认的是价格事实；行业同步只说明背景一致，不能证明行业下跌就是个股原因。\n\n"
        "交易时段内没有取得能够直接说明这次价格变化的公司公告或监管披露原文。\n\n"
        "目前没有取得能解释当日价格波动的公司正式披露，具体驱动仍未确认。"
    )

    guard = AgentService._validate_model_output(answer, evidence)
    repaired = AgentService._repair_guard_failure(answer, evidence, guard)

    assert repaired is not None
    assert repaired[0].startswith("中兴通讯收盘后最新报价34.03元，跌了3.46%。")
    assert "更像行业普跌中的跟随" not in repaired[0]
    assert "跑赢行业5.4个百分点" in repaired[0]
    assert "不能单独确认个股涨跌的直接原因" in repaired[0]
    assert "具体驱动仍未确认" in repaired[0]
    assert repaired[1]["passed"] is True


def test_stock_repair_removes_industry_main_cause_and_sentiment_exclusion_cleanly():
    evidence = {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "display_name": "中兴通讯",
        "user_question": "中兴通讯最近下跌是行业还是情绪？",
        "a_share_information": {
            "sentiment": {
                "band": "中性或混合",
                "sample_size": 28,
                "neutral_count": 28,
            }
        },
    }
    answer = (
        "行业暴跌是主因，但个股相对抗跌；市场情绪无方向性信号。\n\n"
        "**一、行业与个股**\n"
        "中兴通讯下跌更多是跟随行业整体调整。"
        "当前能确认的是个股与行业同日下跌，"
        "但个股相对表现更强，近期直接驱动仍未确认。\n\n"
        "**二、社区样本**\n"
        "社区样本28条均为中性或混合，只说明样本内没有明确方向。"
        "因此情绪不是当天下跌的主力推手。\n\n"
        "综合来看，公司财务压力属于长期背景，而市场情绪并无明确指向。\n\n"
        "**三、仍未确认的直接驱动**\n"
        "。公司财务压力属于较慢变化的背景，不能自动解释近期价格变化。"
    )

    guard = AgentService._validate_model_output(answer, evidence)
    repaired = AgentService._repair_guard_failure(answer, evidence, guard)

    assert guard["passed"] is False
    assert repaired is not None
    repaired_answer, repaired_guard = repaired
    assert "行业暴跌是主因" not in repaired_answer
    assert "跟随行业整体调整" not in repaired_answer
    assert "市场情绪无方向性信号" not in repaired_answer
    assert "情绪不是当天下跌的主力推手" not in repaired_answer
    assert "市场情绪并无明确指向" not in repaired_answer
    assert "社区样本28条均为中性或混合" in repaired_answer
    assert "不能排除未被样本捕捉的情绪影响" in repaired_answer
    assert "\n。" not in repaired_answer
    assert not any(line.rstrip().endswith("；") for line in repaired_answer.splitlines())
    assert repaired_guard["passed"] is True


def test_stock_guard_preserves_explicit_industry_causality_boundary():
    evidence = {
        "type": "stock_research",
        "user_question": "中兴通讯下跌究竟更像行业还是公司因素？",
    }
    answer = (
        "行业大跌只能说明个股与行业同向运动，不能写成行业拖累了个股，"
        "也不能因此认为公司因素已经被排除；近期直接驱动尚未确认。"
    )

    guard = AgentService._validate_model_output(answer, evidence)

    assert (
        "行业成分广度只能描述同步性不能证明个股涨跌因果"
        not in guard["unsupported_market_inferences"]
    )

    natural_boundary = AgentService._validate_model_output(
        "行业同步表现只能证明共同运动，无法单独说明个股涨跌因果，"
        "因此尚不能在行业因素与公司因素之间做出确定区分。",
        evidence,
    )
    assert (
        "行业成分广度只能描述同步性不能证明个股涨跌因果"
        not in natural_boundary["unsupported_market_inferences"]
    )


def test_stock_guard_preserves_natural_cannot_force_industry_company_choice():
    evidence = {
        "type": "stock_research",
        "user_question": "贵州茅台7月30日上涨更像行业还是公司因素？",
        "research_plan": {"focus": "price_cause"},
    }
    answer = (
        "中证白酒指数当日上涨，行业成分也普遍同向。"
        "在缺少同日公司正式披露或可直接对齐价格的公司事件时，"
        "不能强行判断是行业因素还是公司因素在主导当天上涨。"
    )

    guard = AgentService._validate_model_output(answer, evidence)

    assert (
        "行业成分广度只能描述同步性不能证明个股涨跌因果"
        not in guard["unsupported_market_inferences"]
    )


def test_stock_guard_preserves_natural_missing_industry_and_event_boundary():
    evidence = {
        "type": "stock_research",
        "symbol": "000065.SZ",
        "user_question": "北方国际7月30日下跌更像行业还是公司因素？",
        "research_plan": {"focus": "price_cause"},
        "stock_market_context": {
            "stock_target": {
                "market_date": "2026-07-30",
                "return_1d_pct": -0.43,
            },
            "indices": [
                {"name": "深证成指", "return_1d_pct": -2.73},
                {"name": "上证综指", "return_1d_pct": -0.62},
            ],
            "market_breadth": {"same_date_as_target": False},
            "exact_industry_index": {"status": "unavailable_for_target_date"},
        },
    }
    answer = (
        "北方国际下跌0.43%，深证成指下跌2.73%，上证综指下跌0.62%。"
        "它确实跑赢了大盘，但这不是行业对比，只是市场对照。"
        "问题的核心是这种相对抗跌到底更像行业拖着走，还是公司自身在支撑。"
        "缺少行业样本，我说不清到底是行业整体抗跌带动了它，"
        "还是公司自身因素在支撑。当天没有盘中催化剂，"
        "收盘后公告也不构成同日驱动。"
    )

    guard = AgentService._validate_model_output(answer, evidence)

    assert guard["passed"] is True
    assert guard["unsupported_market_inferences"] == []


def test_market_repair_surgically_removes_recurring_causal_stories():
    evidence = {"type": "market_brief", "market_state": {}}
    answer = (
        "当前能确认的是代表性指数同步下跌，具体驱动尚未确认。"
        "今天的全市场广度可用于描述上涨覆盖面，但不能反向证明昨天的个股分布。\n\n"
        "风险提示公告说明市场情绪承压。"
        "今天反弹只能看作连续下跌后的一次技术性修复。"
        "可能存在中小盘此前跌幅并不深、今天迅速回暖的情况。\n\n"
        "后续完整交易日里，可以继续观察上涨家数是否仍占优势，"
        "以及核心指数与已有均线的关系。"
        "同时留意政策信号或宏观经济数据为反弹提供额外支撑。"
    )

    guard = AgentService._validate_model_output(answer, evidence)
    repaired = AgentService._repair_guard_failure(answer, evidence, guard)

    assert guard["passed"] is False
    assert repaired is not None
    repaired_answer, repaired_guard = repaired
    assert "情绪承压" not in repaired_answer
    assert "技术性修复" not in repaired_answer
    assert "中小盘此前跌幅并不深" not in repaired_answer
    assert "政策信号" not in repaired_answer
    assert "代表性指数同步下跌" in repaired_answer
    assert "核心指数与已有均线的关系" in repaired_answer
    assert repaired_guard["passed"] is True


def test_repair_artifact_cleanup_removes_dangling_company_explanation_lead():
    cleaned = AgentOutputGuard._clean_repair_artifacts(
        [
            "公司在一季报中给出了几条明确解释：",
            "",
            "这些事实说明财务背景承压。",
        ]
    )

    assert "公司在一季报中给出了几条明确解释：" not in cleaned
    assert "这些事实说明财务背景承压。" in cleaned


def test_streamed_unverified_draft_is_followed_by_final_guarded_answer(
    tmp_path: Path, settings, monkeypatch
):
    guarded_settings = replace(
        settings,
        workspace_root=tmp_path / "stream-final-guard-workspaces",
        hermes_enabled=True,
    )
    database = Database(guarded_settings.workspace_root)
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


def test_non_prefix_final_answer_is_reconciled_by_http_without_sse_replacement(
    tmp_path: Path, settings, monkeypatch
):
    guarded_settings = replace(
        settings,
        workspace_root=tmp_path / "stream-final-http-reconcile-workspaces",
        hermes_enabled=True,
    )
    database = Database(guarded_settings.workspace_root)
    database.initialize()
    user = database.create_user("Stream Final HTTP Reconcile User")
    service = AgentService(database, guarded_settings)

    def fake_stream(**kwargs):
        kwargs["stream_callback"](
            {
                "type": "delta",
                "draft": "当前证据不足，后续仍需核验。",
                "is_unverified": True,
                "is_guarded_partial": True,
            }
        )
        return (
            "**直接回答：不能确认。** 当前证据不足，后续仍需核验。",
            {
                "model": "fake-stream",
                "streaming": {
                    "enabled": True,
                    "first_token_seconds": 0.2,
                    "first_visible_seconds": 0.4,
                },
            },
        )

    monkeypatch.setattr(service, "_execute_hermes_streaming", fake_stream)
    streamed = []
    run = service.run(
        user=user,
        intent="market_brief",
        message="当前能否确认趋势？",
        evidence={"type": "market_brief", "indices": []},
        model_tier="economy",
        execute_agent=True,
        stream_callback=streamed.append,
    )

    assert run["status"] == "completed"
    assert run["answer"].startswith("**直接回答：不能确认。**")
    assert streamed == [
        {
            "type": "delta",
            "draft": "当前证据不足，后续仍需核验。",
            "is_unverified": True,
            "is_guarded_partial": True,
        }
    ]
    assert run["usage"]["streaming"]["final_delivery"] == (
        "http_reconcile_non_prefix"
    )


def test_stock_specialist_off_topic_answer_is_retried_with_focused_prompt(
    tmp_path: Path, settings, monkeypatch
):
    guarded_settings = replace(
        settings,
        workspace_root=tmp_path / "specialist-retry-workspaces",
        hermes_enabled=True,
    )
    database = Database(guarded_settings.workspace_root)
    database.initialize()
    user = database.create_user("Specialist Retry User")
    service = AgentService(database, guarded_settings)
    calls = []

    def fake_stream(**kwargs):
        calls.append(kwargs.get("prompt_path"))
        if len(calls) == 1:
            return (
                "您好，您的消息可能被截断了。如果是手机屏幕太暗，请重新发送一次完整的消息。",
                {"model": "fake-first", "streaming": {"enabled": True}},
            )
        return (
            "北方国际主要依靠工程建设与服务、资源设备供应链形成收入；"
            "反方证据是业务分类口径仍需结合最新正式报告复核。",
            {"model": "fake-retry", "streaming": {"enabled": True}},
        )

    monkeypatch.setattr(service, "_execute_hermes_streaming", fake_stream)
    streamed = []
    run = service.run(
        user=user,
        intent="business_structure",
        message="北方国际靠什么业务赚钱？",
        evidence={
            "type": "business_structure",
            "symbol": "000065.SZ",
            "name": "北方国际",
            "summary": "最大业务为工程建设与服务。",
            "dimensions": [
                {
                    "classification": "product",
                    "segments": [
                        {"item_name": "工程建设与服务"},
                        {"item_name": "资源设备供应链"},
                    ],
                }
            ],
            "research_plan": {
                "focus": "business",
                "focus_label": "主营业务与收入结构",
            },
        },
        model_tier="economy",
        execute_agent=True,
        stream_callback=streamed.append,
    )

    assert len(calls) == 2
    assert calls[0] is None
    assert calls[1].name == "prompt.retry.md"
    assert run["status"] == "completed"
    assert "工程建设与服务" in run["answer"]
    assert "手机屏幕" not in run["answer"]
    assert run["usage"]["relevance_retry"]["passed"] is True
    assert any(item.get("type") == "reset" for item in streamed)
    run_dir = Path(run["workspace_path"]) / "runs" / run["id"]
    assert (run_dir / "answer.irrelevant.md").is_file()
    assert (run_dir / "prompt.retry.md").is_file()


def test_relative_industry_rounding_near_miss_keeps_single_model_call(
    tmp_path: Path, settings, monkeypatch
):
    guarded_settings = replace(
        settings,
        workspace_root=tmp_path / "relative-industry-repair-workspaces",
        hermes_enabled=True,
    )
    database = Database(guarded_settings.workspace_root)
    database.initialize()
    user = database.create_user("Relative Industry Repair User")
    service = AgentService(database, guarded_settings)
    calls = []

    def fake_stream(**kwargs):
        calls.append(kwargs.get("prompt_path"))
        return (
            "宁德时代在2026年7月28日相对CS电池增强。公司同日下跌2.29%，"
            "指数下跌2.82%，个股跑赢行业0.53个百分点；成分有效收益覆盖"
            "50/50只，其中上涨6只、下跌44只。反方证据是60日累计下跌"
            "12.17%，单日增强不能代表中期趋势。若历史同日数据更正后差值"
            "转负，当前判断将被推翻；后续交易日只形成新的判断。",
            {"model": "fake-relative-industry", "api_calls": 1},
        )

    monkeypatch.setattr(service, "_execute_hermes_streaming", fake_stream)
    run = service.run(
        user=user,
        intent="stock_research",
        message="宁德时代相对CS电池行业是增强还是走弱？",
        evidence={
            "type": "stock_research",
            "symbol": "300750.SZ",
            "display_name": "宁德时代",
            "user_question": "宁德时代相对CS电池行业是增强还是走弱？",
            "research_plan": {"focus": "relative_industry"},
            "metrics": {"return_60d_pct": -12.17},
            "stock_market_context": {
                "exact_industry_index": {
                    "status": "same_market_date",
                    "name": "CS电池",
                    "market_date": "2026-07-28",
                    "return_1d_pct": -2.82,
                    "stock_return_1d_pct": -2.285,
                    "stock_minus_industry_pct": 0.535,
                    "constituent_count": 50,
                    "component_breadth": {
                        "status": "available",
                        "advancers": 6,
                        "decliners": 44,
                        "unchanged": 0,
                        "coverage": {
                            "available_returns": 50,
                            "constituents": 50,
                        },
                    },
                }
            },
        },
        model_tier="economy",
        execute_agent=True,
        stream_callback=lambda _event: None,
    )

    assert calls == [None]
    assert run["status"] == "completed"
    assert "跑赢行业0.54个百分点" in run["answer"]
    assert run["usage"]["api_calls"] == 1
    assert run["usage"]["relevance_repair"]["method"] == (
        "normalize_relative_industry_spread_v1"
    )
    assert "relevance_retry" not in run["usage"]


def test_quality_review_cashflow_overclaim_gets_concise_editor_pass(
    tmp_path: Path, settings, monkeypatch
):
    guarded_settings = replace(
        settings,
        workspace_root=tmp_path / "quality-review-retry-workspaces",
        hermes_enabled=True,
    )
    database = Database(guarded_settings.workspace_root)
    database.initialize()
    user = database.create_user("Quality Review Retry User")
    service = AgentService(database, guarded_settings)
    stream_calls = []
    editor_prompts = []

    def fake_stream(**kwargs):
        prompt_path = kwargs.get("prompt_path")
        stream_calls.append(prompt_path)
        if prompt_path and Path(prompt_path).name == "prompt.quality_editor.md":
            editor_prompts.append(Path(prompt_path).read_text(encoding="utf-8"))
            return (
                "工业富联的经营改善质量目前一般。营收和利润增长是已确认的报表事实。"
                "经营现金流12亿元，同比增长3%；经营现金流与归母净利润比率从1.93"
                "降至1.39；销售收现率从125%降至95%。三个指标口径不同，具体原因"
                "尚未由公司解释。反方证据是资产负债率上升，而负债结构尚未拆分。",
                {"model": "fake-editor", "api_calls": 1},
            )
        return (
            "工业富联经营改善很有质量，利润有经营现金流支撑，说明利润不是纸面数字。",
            {
                "model": "fake-first",
                "api_calls": 1,
                "streaming": {"enabled": True},
            },
        )

    monkeypatch.setattr(service, "_execute_hermes_streaming", fake_stream)
    monkeypatch.setattr(
        service,
        "_execute_hermes",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("quality editor should use the bounded streaming bridge")
        ),
    )
    streamed = []
    run = service.run(
        user=user,
        intent="stock_research",
        message="工业富联为什么进入经营改善候选，改善是否有质量？",
        evidence={
            "type": "stock_research",
            "symbol": "601138.SS",
            "display_name": "工业富联",
            "research_plan": {
                "focus": "quality_review",
                "focus_label": "经营改善质量核验",
            },
            "earnings_quality": {
                "latest_report": {"debt_asset_ratio_pct": 63.0},
            },
            "financial_drivers": {
                "cashflow_analysis": {
                    "operating_cashflow": 1_200_000_000,
                    "operating_cashflow_change_pct": 3.0,
                    "operating_cashflow_to_net_profit": 1.39,
                    "comparable_operating_cashflow_to_net_profit": 1.93,
                    "cash_received_from_sales_to_revenue_pct": 95.0,
                    "comparable_cash_received_from_sales_to_revenue_pct": 125.0,
                }
            },
        },
        model_tier="economy",
        execute_agent=True,
        stream_callback=streamed.append,
    )

    assert len(stream_calls) == 2
    assert len(editor_prompts) == 1
    assert "结构化事实" in editor_prompts[0]
    assert "经营现金流金额及同比" in editor_prompts[0]
    assert run["status"] == "completed"
    assert "改善质量目前一般" in run["answer"]
    assert "纸面数字" not in run["answer"]
    assert run["usage"]["quality_editor"]["passed"] is True
    assert run["usage"]["quality_editor"]["model_tier"] == "economy"
    assert run["usage"]["api_calls"] == 2
    assert "回款质量" in run["usage"]["quality_editor"]["reason"]
    assert not any(item.get("type") == "reset" for item in streamed)


def test_quality_review_rich_draft_is_repaired_before_second_model_call(
    tmp_path: Path, settings, monkeypatch
):
    guarded_settings = replace(
        settings,
        workspace_root=tmp_path / "quality-review-local-repair-workspaces",
        hermes_enabled=True,
    )
    database = Database(guarded_settings.workspace_root)
    database.initialize()
    user = database.create_user("Quality Review Local Repair User")
    service = AgentService(database, guarded_settings)
    stream_calls = []

    def fake_stream(**kwargs):
        stream_calls.append(kwargs.get("prompt_path"))
        if len(stream_calls) > 1:
            raise AssertionError(
                "a complete rich draft should not call an editor model"
            )
        return (
            "工业富联的经营改善质量目前一般。营收和利润增长是已确认的报表事实。\n\n"
            "经营现金流12亿元，同比增长3%；经营现金流与归母净利润比率从1.93"
            "降至1.39；销售收现率从125%降至95%。利润增长的现金兑现程度正在减弱。"
            "三项指标口径不同，具体原因尚未由公司解释。\n\n"
            "主营披露只说明现有业务构成，不能据此确认本期增长来自哪个产品。"
            "反方证据是资产负债率上升，而负债结构尚未拆分。\n\n"
            "当前没有同报告期同行经营数据，不能判断改善质量是否优于行业。"
            "下一步需要核验负债构成和现金流变化的公司原文。",
            {
                "model": "fake-rich-first",
                "api_calls": 1,
                "streaming": {"enabled": True},
            },
        )

    monkeypatch.setattr(service, "_execute_hermes_streaming", fake_stream)

    run = service.run(
        user=user,
        intent="stock_research",
        message="工业富联为什么进入经营改善候选，改善是否有质量？",
        evidence={
            "type": "stock_research",
            "symbol": "601138.SS",
            "display_name": "工业富联",
            "research_plan": {
                "focus": "quality_review",
                "focus_label": "经营改善质量核验",
            },
            "earnings_quality": {
                "latest_report": {"debt_asset_ratio_pct": 63.0},
            },
            "financial_drivers": {
                "cashflow_analysis": {
                    "operating_cashflow": 1_200_000_000,
                    "operating_cashflow_change_pct": 3.0,
                    "operating_cashflow_to_net_profit": 1.39,
                    "comparable_operating_cashflow_to_net_profit": 1.93,
                    "cash_received_from_sales_to_revenue_pct": 95.0,
                    "comparable_cash_received_from_sales_to_revenue_pct": 125.0,
                }
            },
        },
        model_tier="economy",
        execute_agent=True,
        stream_callback=lambda _event: None,
    )

    assert len(stream_calls) == 1
    assert run["status"] == "completed"
    assert "现金兑现程度" not in run["answer"]
    assert "经营现金流12亿元" in run["answer"]
    assert run["usage"]["api_calls"] == 1
    assert run["usage"]["relevance_repair"]["passed"] is True
    assert run["usage"]["relevance_repair"]["method"] == (
        "neutralize_quality_review_overclaims_v1"
    )
    assert "quality_editor" not in run["usage"]


def test_quality_review_natural_cash_ratio_draft_skips_editor_and_retry(
    tmp_path: Path, settings, monkeypatch
):
    guarded_settings = replace(
        settings,
        workspace_root=tmp_path / "quality-review-natural-ratio-workspaces",
        hermes_enabled=True,
    )
    database = Database(guarded_settings.workspace_root)
    database.initialize()
    user = database.create_user("Quality Review Natural Ratio User")
    service = AgentService(database, guarded_settings)
    stream_calls = []

    def fake_stream(**kwargs):
        stream_calls.append(kwargs.get("prompt_path"))
        if len(stream_calls) > 1:
            raise AssertionError("a natural rich draft should not call another model")
        return (
            "中兴通讯这份一季报盈利质量承压，说不上好。营收349.88亿元，"
            "同比增长6.13%，但归母净利润13.10亿元，同比下降46.58%。\n\n"
            "经营现金流从去年同期净流入18.51亿元变为本期净流出19.79亿元。"
            "经营现金流与归母净利润的比率从0.75变成负的1.51，说明当期的"
            "报表利润并没有伴随着实际的现金净流入。销售商品、提供劳务收到的"
            "现金占营收的比例从106.25%降至95.96%。销售收现率也从106.25%"
            "降到95.96%，意味着每百元收入实际收到的现金减少。公司解释是销售商品收到的"
            "现金减少，同时购买商品、接受劳务支付的现金增加。这能确认现金流"
            "压力来自收付两端的同时挤压，但具体结算原因仍不能确认。\n\n"
            "最新主营构成来自年报，不能直接解释一季报利润变化。最重要的反方"
            "事实是经营现金流由正转负且覆盖关系严重恶化、销售收现率同步走低。"
            "公司并未说明销售收现率下降的具体业务背景。下一步需要重点核验"
            "应收账款回款节奏和负债结构。当前也没有同报告期同行经营数据。",
            {
                "model": "fake-natural-first",
                "api_calls": 1,
                "streaming": {"enabled": True},
            },
        )

    monkeypatch.setattr(service, "_execute_hermes_streaming", fake_stream)

    run = service.run(
        user=user,
        intent="stock_research",
        message="中兴通讯最新财报到底好不好？像分析师一样自然聊。",
        evidence={
            "type": "stock_research",
            "symbol": "000063.SZ",
            "display_name": "中兴通讯",
            "research_plan": {
                "focus": "quality_review",
                "focus_label": "经营改善质量核验",
            },
            "earnings_quality": {
                "comparable_report": {
                    "operating_cashflow_to_net_profit": 0.7546,
                }
            },
            "financial_drivers": {
                "cashflow_analysis": {
                    "operating_cashflow": -1_978_648_000,
                    "comparable_operating_cashflow": 1_851_253_000,
                    "operating_cashflow_change_pct": -206.882,
                    "operating_cashflow_to_net_profit": -1.51,
                    "comparable_operating_cashflow_to_net_profit": 0.755,
                    "cash_received_from_sales_to_revenue_pct": 95.96,
                    "comparable_cash_received_from_sales_to_revenue_pct": 106.245,
                }
            },
        },
        model_tier="economy",
        execute_agent=True,
        stream_callback=lambda _event: None,
    )

    assert len(stream_calls) == 1
    assert run["status"] == "completed"
    assert "经营现金流与归母净利润的比率" in run["answer"]
    assert "销售商品、提供劳务收到的现金占营收的比例" in run["answer"]
    assert "销售商品收到的现金减少" in run["answer"]
    assert "实际的现金净流入" not in run["answer"]
    assert "每百元收入实际收到的现金减少" not in run["answer"]
    assert "覆盖关系严重恶化" not in run["answer"]
    assert "销售收现率较可比期下降" in run["answer"]
    assert "公司并未说明销售收现率下降的具体业务背景" in run["answer"]
    assert "需要重点核验应收账款回款节奏" in run["answer"]
    assert "收付两端的同时挤压" not in run["answer"]
    assert run["usage"]["api_calls"] == 1
    assert run["usage"]["relevance_repair"]["passed"] is True
    assert run["usage"]["relevance_repair"]["method"] == (
        "neutralize_quality_review_overclaims_v1"
    )
    assert "quality_editor" not in run["usage"]
    assert "relevance_retry" not in run["usage"]


def test_quality_review_cautious_short_term_cashflow_sentence_is_not_overclaim():
    answer = (
        "公司已经解释经营现金流转负来自收现减少、付现增加，但销售收现率和"
        "付款节奏的波动在季度之间常有季节因素，仅凭单季数据不够判断长期资金压力。"
    )

    assert quality_review_overclaim_issue(answer) is None


def test_quality_review_contextual_followup_does_not_force_full_fact_recap():
    evidence = {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "display_name": "中兴通讯",
        "research_plan": {
            "focus": "quality_review",
            "contextual_followup": True,
        },
        "financial_drivers": {
            "cashflow_analysis": {
                "operating_cashflow": -1_978_648_000,
                "comparable_operating_cashflow": 1_851_253_000,
                "operating_cashflow_change_pct": -206.882,
                "operating_cashflow_to_net_profit": -1.51,
                "comparable_operating_cashflow_to_net_profit": 0.755,
                "cash_received_from_sales_to_revenue_pct": 95.96,
                "comparable_cash_received_from_sales_to_revenue_pct": 106.245,
            }
        },
    }
    answer = (
        "中兴通讯真正值得改变判断的是毛利率大幅下降且原因未披露。"
        "经营现金流由正转负也值得跟踪，但公司已说明来自收现减少、付现增加，"
        "单季数据仍不足以判断长期资金压力。"
    )

    assert quality_review_required_fact_issue(answer, evidence) is None
    assert stock_specialist_relevance_issue(answer, evidence) is None


def test_quality_review_accepts_natural_positive_cashflow_amount_rounding():
    evidence = {
        "type": "stock_research",
        "symbol": "300750.SZ",
        "display_name": "宁德时代",
        "research_plan": {"focus": "quality_review"},
        "earnings_quality": {
            "comparable_report": {"operating_cashflow_to_net_profit": 1.925}
        },
        "financial_drivers": {
            "cashflow_analysis": {
                "operating_cashflow": 60_216_851_000,
                "comparable_operating_cashflow": 58_687_066_000,
                "operating_cashflow_change_pct": 2.607,
                "operating_cashflow_to_net_profit": 1.391,
                "comparable_operating_cashflow_to_net_profit": 1.925,
                "cash_received_from_sales_to_revenue_pct": 94.769,
                "comparable_cash_received_from_sales_to_revenue_pct": 124.622,
            }
        },
    }
    answer = (
        "宁德时代上半年经营现金流净额602亿元，同比增长2.6%；"
        "经营现金流与归母净利润比率从1.93降至1.39；"
        "销售收现率从124.62%降至94.77%。"
    )

    assert quality_review_required_fact_issue(answer, evidence) is None
    assert quality_review_required_fact_issue(
        answer.replace("602亿元", "602亿"), evidence
    ) is None
    assert "财务费用是本期利润的一项重要非主营扰动" in (
        normalize_quality_review_language(
            "但增长的利润有一部分被非经营性因素抬高了，最明显的是财务费用。"
        )
    )


def test_quality_review_accepts_w30_cashflow_change_without_repeating_amount():
    evidence = {
        "type": "stock_research",
        "symbol": "300750.SZ",
        "display_name": "宁德时代",
        "research_plan": {"focus": "quality_review"},
        "earnings_quality": {
            "comparable_report": {"operating_cashflow_to_net_profit": 1.925}
        },
        "financial_drivers": {
            "cashflow_analysis": {
                "operating_cashflow": 60_216_851_000,
                "comparable_operating_cashflow": 58_687_066_000,
                "operating_cashflow_change_pct": 2.607,
                "operating_cashflow_to_net_profit": 1.391,
                "comparable_operating_cashflow_to_net_profit": 1.925,
                "cash_received_from_sales_to_revenue_pct": 94.769,
                "comparable_cash_received_from_sales_to_revenue_pct": 124.622,
            }
        },
    }
    answer = (
        "宁德时代归母净利润增长约42%，但经营现金流净额同比仅小幅增长约2.6%，"
        "经营现金流与归母净利润的比值从去年同期的1.93降至现在的1.39。"
        "销售商品收到的现金占收入的比例也从约125%降至约95%。"
    )

    assert quality_review_required_fact_issue(answer, evidence) is None

    draft = (
        "宁德时代经营改善有真实业务进展。经营现金流602亿，同比只微增2.6%，"
        "意味着增加的近128亿利润里，绝大部分并没有多变成现金。经营现金流与"
        "归母净利润的比率从1.93降到1.39，销售收现率从124.6%降到94.8%。"
    )
    repaired = repair_quality_review_answer(draft, evidence)

    assert repaired is not None
    assert "经营现金流602亿，同比只微增2.6%" in repaired
    assert "并没有多变成现金" not in repaired
    assert quality_review_required_fact_issue(repaired, evidence) is None


def test_quality_review_repair_restores_inventory_verification_boundary():
    evidence = {
        "type": "stock_research",
        "symbol": "300750.SZ",
        "display_name": "宁德时代",
        "research_plan": {"focus": "quality_review"},
        "a_share_information": {
            "announcements": [
                {
                    "summary": (
                        "公司公告原文摘录：库存增加主要是为下半年市场需求而提前备货。"
                    )
                }
            ]
        },
    }
    draft = (
        "宁德时代经营改善有真实业务进展。公司解释存货增加是为下半年市场需求"
        "提前备货，但现金流被库存占用自然跟着出现。"
    )

    repaired = repair_quality_review_answer(draft, evidence)

    assert repaired is not None
    assert "存货分类、库龄和跌价准备" in repaired
    assert quality_review_required_fact_issue(repaired, evidence) is None


def test_quality_review_keeps_grounded_initial_draft_when_editor_and_retry_fail(
    tmp_path: Path, settings, monkeypatch
):
    guarded_settings = replace(
        settings,
        workspace_root=tmp_path / "quality-soft-fallback-workspaces",
        hermes_enabled=True,
    )
    database = Database(guarded_settings.workspace_root)
    database.initialize()
    user = database.create_user("Quality Soft Fallback User")
    service = AgentService(database, guarded_settings)
    calls = []
    initial_answer = (
        "宁德时代这份中报的改善并不只有利润表数字，主营需求和经营现金流仍值得"
        "结合起来看。当前最重要的矛盾是利润增长较快，而现金流和销售收现率变化"
        "的原因还没有被公司充分解释；这类差异需要继续核对，但不能直接写成回款"
        "恶化或利润失真。毛利率和存货结构也应在下一份正式披露里继续追踪。"
    )

    def fake_stream(**kwargs):
        calls.append(kwargs.get("prompt_path"))
        if len(calls) == 1:
            answer = initial_answer
        elif len(calls) == 2:
            answer = (
                "宁德时代改善质量一般，但当前证据还需要继续核对。公司经营和财务"
                "变化需要放在一起理解，不能只凭一个指标下结论；毛利率、存货和现金"
                "流各自反映不同问题，后续仍应阅读正式披露。"
            )
        else:
            answer = (
                "宁德时代当前财报既有改善也有待核验项。利润、主营、现金流和存货"
                "应分别理解，不能把其中一个指标直接扩大成完整经营结论；目前更适合"
                "保留问题，等待公司后续披露补充原因。"
            )
        return answer, {"model": "fake-deepseek", "api_calls": 1}

    monkeypatch.setattr(service, "_execute_hermes_streaming", fake_stream)
    run = service.run(
        user=user,
        intent="stock_research",
        message="宁德时代最新财报究竟好不好？像分析师聊天。",
        evidence={
            "type": "stock_research",
            "symbol": "300750.SZ",
            "display_name": "宁德时代",
            "research_plan": {"focus": "quality_review"},
            "financial_drivers": {
                "cashflow_analysis": {
                    "operating_cashflow": 60_216_851_000,
                    "operating_cashflow_change_pct": 2.607,
                    "cash_received_from_sales_to_revenue_pct": 94.769,
                    "comparable_cash_received_from_sales_to_revenue_pct": 124.622,
                }
            },
        },
        model_tier="economy",
        execute_agent=True,
        stream_callback=lambda _event: None,
    )

    assert len(calls) == 3
    assert run["status"] == "completed"
    assert run["answer"] == initial_answer
    assert run["usage"]["quality_editor"]["passed"] is False
    assert run["usage"]["relevance_retry"]["preserved_generated_answer"] is True
    assert run["usage"]["relevance_retry"]["source"] == "initial"
    assert run["usage"]["output_guard"]["passed"] is True


def test_quality_review_repairs_natural_cashflow_paragraph_without_editor():
    evidence = {
        "type": "stock_research",
        "symbol": "300750.SZ",
        "display_name": "宁德时代",
        "research_plan": {"focus": "quality_review"},
        "earnings_quality": {
            "comparable_report": {"operating_cashflow_to_net_profit": 1.925}
        },
        "financial_drivers": {
            "cashflow_analysis": {
                "operating_cashflow": 60_216_851_000,
                "operating_cashflow_change_pct": 2.607,
                "operating_cashflow_to_net_profit": 1.391,
                "comparable_operating_cashflow_to_net_profit": 1.925,
                "cash_received_from_sales_to_revenue_pct": 94.769,
                "comparable_cash_received_from_sales_to_revenue_pct": 124.622,
            }
        },
    }
    answer = (
        "宁德时代经营改善有一定质量，但利润表增速要打两个折扣——一是毛利率"
        "收缩，二是经营现金流覆盖关系在弱化。\n\n"
        "本期经营现金流602亿元，同比增长约2.6%，远慢于利润增速；经营现金流"
        "对归母净利润的覆盖从1.93倍降到1.39倍，销售商品现金占收入的比例从"
        "124.6%下降到94.8%，这意味着利润增长的现金转化效率比去年同期明显变弱，"
        "具体原因公司半年报正文尚未给出详细拆解。\n\n"
        "当前没有同报告期同行经营数据，不能判断是否优于行业。"
    )

    repaired = repair_quality_review_answer(answer, evidence)

    assert repaired is not None
    assert "经营现金流602亿元" in repaired
    assert "从1.93倍降到1.39倍" in repaired
    assert "从124.6%降到94.8%" in repaired
    assert "现金转化效率" not in repaired
    assert stock_specialist_relevance_issue(repaired, evidence) is None


def test_quality_review_repairs_real_deepseek_cashflow_sentences_locally():
    evidence = {
        "type": "stock_research",
        "symbol": "300750.SZ",
        "display_name": "宁德时代",
        "research_plan": {"focus": "quality_review"},
        "earnings_quality": {
            "comparable_report": {"operating_cashflow_to_net_profit": 1.925}
        },
        "financial_drivers": {
            "cashflow_analysis": {
                "operating_cashflow": 60_216_851_000,
                "operating_cashflow_change_pct": 2.607,
                "operating_cashflow_to_net_profit": 1.391,
                "comparable_operating_cashflow_to_net_profit": 1.925,
                "cash_received_from_sales_to_revenue_pct": 94.769,
                "comparable_cash_received_from_sales_to_revenue_pct": 124.622,
            }
        },
    }
    answer = (
        "宁德时代经营改善质量一般。经营现金流602亿，同比只增长约2.6%。"
        "但要注意，602亿的经营现金流仍然是正的，而且覆盖归母净利润的比率"
        "为1.39倍，说明上半年经营活动的现金净流入依然大于账面净利润。"
        "这个比率去年是1.93倍。销售收现率从124.6%降到94.8%。\n\n"
        "最重要的反方事实是毛利率收缩、经营现金流增速慢于利润，销售收现率"
        "回落，这些差异叠加在一起，说明利润的高增长有一部分尚未在现金流层面"
        "得到同等程度的兑现。当前没有同报告期同行经营数据。"
    )

    repaired = repair_quality_review_answer(answer, evidence)

    assert repaired is not None
    assert "经营现金流602亿" in repaired
    assert "本期比率为1.39倍" in repaired
    assert "不能合并推断利润兑现程度" in repaired
    assert stock_specialist_relevance_issue(repaired, evidence) is None


def test_quality_review_prompt_does_not_reinject_generated_report_body(
    tmp_path: Path, settings, monkeypatch
):
    guarded_settings = replace(
        settings,
        workspace_root=tmp_path / "quality-review-prompt-workspaces",
        hermes_enabled=True,
    )
    database = Database(guarded_settings.workspace_root)
    database.initialize()
    user = database.create_user("Quality Review Prompt User")
    service = AgentService(database, guarded_settings)

    monkeypatch.setattr(
        service,
        "_execute_hermes_streaming",
        lambda **kwargs: (
            "宁德时代的经营改善质量目前仍需核验。公司原文只确认财务费用变化"
            "主要受汇兑损失影响；反方证据是经营现金流与利润的同报告期关系"
            "仍需结合完整报表判断。",
            {"model": "fake-quality-review", "streaming": {"enabled": True}},
        ),
    )

    run = service.run(
        user=user,
        intent="stock_research",
        message="宁德时代为什么进入经营改善候选，改善是否有质量？",
        evidence={
            "type": "stock_research",
            "symbol": "300750.SZ",
            "display_name": "宁德时代",
            "research_plan": {
                "focus": "quality_review",
                "focus_label": "经营改善质量核验",
            },
            "financial_drivers": {
                "latest_period": {
                    "report_date": "2026-06-30",
                    "operating_cashflow": 586.9,
                },
                "filing_evidence": {
                    "status": "available",
                    "explicit_company_explanations": [
                        {
                            "theme": "财务费用",
                            "statement": "主要受汇兑损失影响。",
                        }
                    ],
                },
            },
        },
        model_tier="economy",
        execute_agent=True,
        stream_callback=lambda event: None,
        knowledge_context={
            "items": [
                {
                    "scope": "common",
                    "source_key": "research-report:300750.SZ",
                    "title": "宁德时代利润与现金流驱动分析",
                    "excerpt": "收入规模对应毛利增加245.301亿元。",
                },
                {
                    "scope": "user",
                    "source_key": "upload:catl-note",
                    "title": "我的宁德时代调研笔记",
                    "excerpt": "用户关注海外业务风险。",
                },
            ]
        },
    )

    prompt = (Path(run["workspace_path"]) / "runs" / run["id"] / "prompt.md").read_text(
        encoding="utf-8"
    )
    assert "245.301" not in prompt
    assert "收入规模对应毛利增加" not in prompt
    assert "宁德时代利润与现金流驱动分析" not in prompt
    assert "用户关注海外业务风险" in prompt
    assert "主要受汇兑损失影响" in prompt


def test_stock_price_move_prompt_does_not_reinject_generated_report_body(
    tmp_path: Path, settings, monkeypatch
):
    guarded_settings = replace(
        settings,
        workspace_root=tmp_path / "stock-price-move-prompt-workspaces",
        hermes_enabled=True,
    )
    database = Database(guarded_settings.workspace_root)
    database.initialize()
    user = database.create_user("Stock Price Move Prompt User")
    service = AgentService(database, guarded_settings)
    monkeypatch.setattr(
        service,
        "_execute_hermes_streaming",
        lambda **kwargs: (
            "北方国际当日上涨，但现有材料尚不能确认单一直接驱动。",
            {"model": "fake-price-move", "streaming": {"enabled": True}},
        ),
    )

    run = service.run(
        user=user,
        intent="stock_research",
        message="请深度分析北方国际今天为什么上涨",
        evidence={
            "type": "stock_research",
            "symbol": "000065.SZ",
            "display_name": "北方国际",
            "user_question": "请深度分析北方国际今天为什么上涨",
            "research_plan": {
                "focus": "price_cause",
                "focus_label": "个股涨跌原因",
            },
            "stock_target": {
                "symbol": "000065.SZ",
                "name": "北方国际",
                "market_date": "2026-07-30",
                "return_1d_pct": 2.29,
            },
        },
        model_tier="economy",
        execute_agent=True,
        stream_callback=lambda event: None,
        conversation_history=[
            {"role": "user", "content": "先看一下这家公司。"},
            {"role": "assistant", "content": "旧回答写成了固定报告结构。"},
            {"role": "user", "content": "今天上涨更像行业还是公司因素？"},
        ],
        knowledge_context={
            "items": [
                {
                    "scope": "common",
                    "source_key": "research-report:000065.SZ",
                    "title": "北方国际利润与现金流驱动分析",
                    "excerpt": "盈利质量承压，下一步复核收入和现金流。",
                }
            ]
        },
    )

    prompt = (Path(run["workspace_path"]) / "runs" / run["id"] / "prompt.md").read_text(
        encoding="utf-8"
    )
    assert "北方国际利润与现金流驱动分析" not in prompt
    assert "盈利质量承压" not in prompt
    assert "下一步复核收入和现金流" not in prompt
    assert "旧回答写成了固定报告结构" not in prompt
    assert "今天上涨更像行业还是公司因素" in prompt


def test_quality_review_retries_unconfirmed_growth_and_cashflow_interpretations():
    evidence = {
        "type": "stock_research",
        "symbol": "300750.SZ",
        "display_name": "宁德时代",
        "research_plan": {
            "focus": "quality_review",
            "focus_label": "经营改善质量核验",
        },
    }

    cases = {
        "宁德时代改善质量一般，利润增长主要来自收入规模扩张。": "增长原因",
        "宁德时代毛利率下降，意味着增长主要由规模驱动。": "增长原因",
        "宁德时代增长有规模支撑，但原因仍需核验。": "增长原因",
        "宁德时代改善质量一般，现金回收效率反而在走弱。": "回款质量",
        "宁德时代经营现金流几乎停滞，改善质量仍需复核。": "可比增速",
        "宁德时代经营现金流近乎停滞，改善质量仍需复核。": "可比增速",
        "宁德时代经营现金流净额几乎原地踏步，改善质量仍需复核。": "可比增速",
        "宁德时代销售收现率下降，暗示结算节奏可能存在压力。": "回款质量",
        "宁德时代收入转化为现金的效率出现明显落差。": "回款质量",
        "宁德时代收入的快速增长并没有同步转化为同等比例的现金流入。": "回款质量",
        "宁德时代利润转化为现金的效率在减弱。": "回款质量",
        "宁德时代经营现金回款效率也在下降。": "回款质量",
        "宁德时代销售回款效率出现明显下滑。": "回款质量",
        "宁德时代销售收现率降至94.8%，回款效率回落明显。": "回款质量",
        "宁德时代实际收回的现金比去年少，回款节奏有所放慢。": "回款质量",
        "宁德时代销售收现率下降则提示回款效率在降低。": "回款质量",
        "宁德时代这三项线索提示回款和营运资金占用可能在加大。": "回款质量",
        "宁德时代利润率、现金覆盖和销售回款匹配度都在减弱。": "回款质量",
        "宁德时代利润增长的现金兑现程度在减弱。": "回款质量",
        "宁德时代当前现金流压力可能会持续，因此改善质量一般。": "回款质量",
        "宁德时代利润增长对现金流的带动作用就会更弱。": "现金流驱动",
        "宁德时代收入增长对利润形成明显拉动。": "利润驱动",
        "宁德时代动力电池占比下降、储能占比上升，结构有所优化。": "结构优化",
        "宁德时代两大产品毛利率下降，增收不增利压力仍在。": "增收不增利",
        "宁德时代存货增速较快，可能意味着产品积压。": "积压",
        "宁德时代存货增速较快，需要警惕去库压力或备货节奏错位。": "积压",
        "宁德时代存货增速较快，若未来需计提跌价，可能进一步影响利润。": "积压",
        "宁德时代行业毛利率下降，改善质量一般。": "行业整体毛利率",
        "宁德时代报表呈现量增价减，改善质量一般。": "压缩式经营标签",
        "宁德时代仍停留在收入规模快速膨胀阶段。": "压缩式经营标签",
        "宁德时代三项指标方向一致地说明现金流增速跟不上利润增速。": "压缩式经营标签",
        "宁德时代毛利率、覆盖比率和销售收现率三项指标同步走弱。": "压缩式经营标签",
        "宁德时代经营现金流绝对金额仍在正增长，并非资金紧张。": "资金压力",
        "宁德时代这三项合在一起，说明本期利润增长尚未得到经营现金流和回款节奏的同等确认。": "回款节奏",
    }
    for answer, expected_reason in cases.items():
        reason = stock_specialist_relevance_issue(answer, evidence)
        assert reason is not None
        assert expected_reason in reason

    assert (
        stock_specialist_relevance_issue(
            "宁德时代改善质量目前一般。经营现金流同比增长2.6%，低于利润增速；"
            "销售收现率下降，但公司原文尚未解释具体原因。",
            evidence,
        )
        is None
    )
    assert (
        stock_specialist_relevance_issue(
            "宁德时代改善质量目前一般。覆盖倍数不能证明利润有现金支撑；"
            "产品占比变化不代表业务结构优化，也不能把存货增速直接解释成产品积压。",
            evidence,
        )
        is None
    )


def test_quality_review_event_appendix_uses_operating_boundary_not_price_move():
    appendix = AgentOutputGuard._stock_event_evidence_appendix(
        {
            "type": "stock_research",
            "user_question": "宁德时代经营改善是否有质量？请结合最新公告。",
            "research_plan": {"focus": "quality_review"},
            "event_timeline": {
                "events": [
                    {
                        "evidence_level": "official_disclosure",
                        "category": "announcement",
                        "event_date": "2026-07-26",
                        "title": "宁德时代:投资者关系活动记录表",
                    }
                ]
            },
        }
    )

    assert appendix is not None
    assert "本轮相关公司披露" in appendix
    assert "经营改善的原因或质量" in appendix
    assert "股价回撤" not in appendix


def test_quality_review_editor_uses_direct_inventory_explanation():
    evidence = {
        "type": "stock_research",
        "symbol": "300750.SZ",
        "display_name": "宁德时代",
        "research_plan": {"focus": "quality_review"},
        "a_share_information": {
            "announcements": [
                {
                    "title": "宁德时代投资者关系活动记录表",
                    "published_at": "2026-07-26",
                    "summary": (
                        "公司公告原文摘录：5、库存增加的原因？"
                        "库存增加主要是为下半年市场需求而提前备货。"
                    ),
                }
            ]
        },
    }
    bad_answer = (
        "宁德时代改善质量一般，但公司并未解释存货增长的原因。"
        "后续需要核验存货分类和库龄。"
    )

    reason = stock_specialist_relevance_issue(bad_answer, evidence)
    prompt = build_quality_review_editor_prompt(
        draft=bad_answer,
        evidence=evidence,
    )

    assert reason is not None
    assert "已有的库存增加公司原文解释" in reason
    assert "库存增加主要是为下半年市场需求而提前备货" in prompt
    assert "不得再声称公司没有解释" in prompt

    repaired = repair_quality_review_answer(
        (
            "宁德时代改善质量目前一般。营收和利润增长是已确认的报表事实，"
            "毛利率变化仍需核验。\n\n"
            "经营现金流金额、覆盖比率和销售收现率口径不同，具体原因尚未确认。\n\n"
            "公司并未解释存货增长的原因。当前也没有同期同行经营数据，无法判断"
            "改善质量是否优于行业。下一步需要核对存货和应收账款明细。"
        ),
        evidence,
    )
    assert repaired is not None
    assert "库存增加主要是为下半年市场需求提前备货" in repaired
    assert "仍需结合存货分类、库龄、跌价准备" in repaired
    assert "公司并未解释存货" not in repaired


def test_quality_review_repair_does_not_repeat_existing_inventory_explanation():
    evidence = {
        "type": "stock_research",
        "symbol": "300750.SZ",
        "display_name": "宁德时代",
        "research_plan": {"focus": "quality_review"},
        "a_share_information": {
            "announcements": [
                {
                    "title": "宁德时代投资者关系活动记录表",
                    "published_at": "2026-07-24",
                    "summary": (
                        "公司公告原文摘录：库存增加主要是为下半年市场需求而提前备货。"
                    ),
                }
            ]
        },
    }
    answer = (
        "宁德时代改善质量一般。公司解释库存增加主要是为下半年市场需求而"
        "提前备货，但仍需核验存货分类、库龄和跌价准备。存货增速快于收入的"
        "原因仍未解释。主营结构变化本身不能证明经营质量改善，分部占比变化"
        "也不能代替订单和产品价格证据。"
    )

    repaired = repair_quality_review_answer(answer, evidence)

    assert repaired is not None
    assert repaired.count("提前备货") == 1
    assert "原因仍未解释" not in repaired
    assert stock_specialist_relevance_issue(repaired, evidence) is None


def test_quality_review_rejects_mixed_inventory_unresolved_claim_after_direct_explanation():
    evidence = {
        "type": "stock_research",
        "symbol": "300750.SZ",
        "display_name": "宁德时代",
        "research_plan": {"focus": "quality_review"},
        "a_share_information": {
            "announcements": [
                {
                    "title": "宁德时代投资者关系活动记录表",
                    "published_at": "2026-07-26",
                    "summary": (
                        "公司公告原文摘录：5、库存增加的原因？"
                        "库存增加主要是为下半年市场需求而提前备货。"
                    ),
                }
            ]
        },
    }
    answer = (
        "公司解释库存增加主要是为下半年市场需求提前备货，但毛利率下滑、"
        "销售收现率下降和存货快于收入的原因仍属`unresolved_themes`。"
    )

    assert stock_specialist_relevance_issue(answer, evidence) == (
        "经营改善回答遗漏或否定了公告中已有的库存增加公司原文解释"
    )


def test_quality_review_accepts_natural_inventory_classification_wording():
    evidence = {
        "type": "stock_research",
        "symbol": "300750.SZ",
        "display_name": "宁德时代",
        "research_plan": {"focus": "quality_review"},
        "a_share_information": {
            "announcements": [
                {
                    "title": "宁德时代投资者关系活动记录表",
                    "published_at": "2026-07-24",
                    "summary": (
                        "公司公告原文摘录：库存增加主要是为下半年市场需求而提前备货。"
                    ),
                }
            ]
        },
    }
    answer = (
        "宁德时代经营改善质量一般。公司解释库存增加主要是为下半年市场需求而"
        "提前备货，但仍需核验存货的具体分类、库龄结构、订单覆盖比例和存货跌价"
        "准备金额。当前没有同报告期同行经营数据，不能判断是否优于行业。"
    )

    assert stock_specialist_relevance_issue(answer, evidence) is None


def test_quality_review_accepts_inventory_category_composition_wording():
    evidence = {
        "type": "stock_research",
        "symbol": "300750.SZ",
        "display_name": "宁德时代",
        "research_plan": {"focus": "quality_review"},
        "a_share_information": {
            "announcements": [
                {
                    "title": "宁德时代投资者关系活动记录表",
                    "published_at": "2026-07-24",
                    "summary": (
                        "公司公告原文摘录：库存增加主要是为下半年市场需求而提前备货。"
                    ),
                }
            ]
        },
    }
    answer = (
        "宁德时代经营改善质量较强。公司解释库存增加主要是为下半年市场需求而"
        "提前备货。下一步需核验存货中原材料、在产品和产成品的构成比例、各类"
        "库存的库龄、订单覆盖和存货跌价准备。"
    )

    assert stock_specialist_relevance_issue(answer, evidence) is None


def test_quality_review_repair_drops_unverified_not_backlog_claim():
    evidence = {
        "type": "stock_research",
        "symbol": "300750.SZ",
        "display_name": "宁德时代",
        "research_plan": {"focus": "quality_review"},
        "a_share_information": {
            "announcements": [
                {
                    "title": "宁德时代投资者关系活动记录表",
                    "published_at": "2026-07-24",
                    "summary": (
                        "公司公告原文摘录：库存增加主要是为下半年市场需求而提前备货。"
                    ),
                }
            ]
        },
    }
    answer = (
        "宁德时代经营改善质量较强。营收和利润增长是已确认的报表事实，毛利率"
        "变化的具体原因仍需公司原文确认。公司解释库存增加主要是为下半年市场需求而"
        "提前备货。这是公司管理层的正式口径，可以确认公司当时的备货意图，而非"
        "被动积压。下一步需核验存货中原材料、在产品和产成品的构成比例、各类"
        "库存的库龄、订单覆盖和存货跌价准备。当前没有同报告期同行经营数据，"
        "不能判断是否优于行业。最重要的反方事实仍是毛利率和销售收现率变化，"
        "但这些指标不能合并成同一个经营原因。"
    )

    repaired = repair_quality_review_answer(answer, evidence)

    assert repaired is not None
    assert "而非被动积压" not in repaired
    assert "原材料、在产品和产成品的构成比例" in repaired
    assert stock_specialist_relevance_issue(repaired, evidence) is None


def test_quality_review_local_language_normalization_keeps_counter_fact():
    answer = (
        "**现金流整体充裕，但回款节奏需核验。** 三项现金流指标变化方向和"
        "幅度不同，表明利润增长与现金回笼节奏出现差异。"
        "不能简单概括为“现金质量恶化”或“具体原因尚未确认”。"
        "**最重要反方事实与行业边界。** 利润增速明显快于经营现金流增速，"
        "这意味着净利润增长中有部分尚未在同期现金回款中完全体现。"
    )

    normalized = normalize_quality_review_language(answer)

    assert "现金流整体充裕" not in normalized
    assert "现金流数据需分项理解" in normalized
    assert "现金回笼节奏出现差异" not in normalized
    assert "不能简单概括" not in normalized
    assert "具体原因尚未确认" in normalized
    assert "最重要的反方事实是利润增速明显快于经营现金流" in normalized
    assert "具体原因仍需核验" in normalized


def test_stream_segmenter_keeps_bold_heading_markers_together():
    segments, pending = AgentService._take_complete_stream_segments(
        "**最重要反方事实与行业边界。** 利润增速快于经营现金流增速。"
    )

    assert segments == [
        "**最重要反方事实与行业边界。**",
        " 利润增速快于经营现金流增速。",
    ]
    assert pending == ""


def test_quality_review_allows_selected_cashflow_facts_but_rejects_all_product_claim():
    evidence = {
        "type": "stock_research",
        "symbol": "300750.SZ",
        "display_name": "宁德时代",
        "research_plan": {"focus": "quality_review"},
        "financial_drivers": {
            "cashflow_analysis": {
                "operating_cashflow": 60_216_851_000,
                "operating_cashflow_change_pct": 2.607,
                "operating_cashflow_to_net_profit": 1.391,
                "comparable_operating_cashflow_to_net_profit": 1.925,
                "cash_received_from_sales_to_revenue_pct": 94.769,
                "comparable_cash_received_from_sales_to_revenue_pct": 124.622,
            }
        },
        "business_structure": {
            "dimensions": [
                {
                    "classification": "product",
                    "segments": [
                        {
                            "item_name": "动力电池系统",
                            "gross_margin_pct": 20.63,
                            "comparable_gross_margin_pct": 22.41,
                        },
                        {
                            "item_name": "电池材料及回收、矿产资源",
                            "gross_margin_pct": 27.04,
                            "comparable_gross_margin_pct": None,
                        },
                    ],
                }
            ]
        },
    }
    missing_sales_cash = (
        "宁德时代改善质量一般。经营现金流602.17亿元，同比增长2.61%；"
        "经营现金流与归母净利润比率从1.93降至1.39。销售收现率下降。"
    )
    all_products = (
        "宁德时代改善质量一般。全部产品分部毛利率均有所下降。"
        "经营现金流602.17亿元，同比增长2.61%；经营现金流与归母净利润比率"
        "从1.93降至1.39；销售收现率从124.62%降至94.77%。"
    )

    assert stock_specialist_relevance_issue(missing_sales_cash, evidence) is None
    assert stock_specialist_relevance_issue(all_products, evidence) == (
        "经营改善回答把缺少可比数据的产品分部也写成了毛利率下降"
    )


def test_quality_review_accepts_two_period_cashflow_amounts_without_repeating_yoy():
    evidence = {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "display_name": "中兴通讯",
        "research_plan": {"focus": "quality_review"},
        "earnings_quality": {
            "comparable_report": {
                "operating_cashflow_to_net_profit": 0.7546,
            }
        },
        "financial_drivers": {
            "cashflow_analysis": {
                "operating_cashflow": -1_978_648_000,
                "comparable_operating_cashflow": 1_851_253_000,
                "operating_cashflow_change_pct": -206.882,
                "operating_cashflow_to_net_profit": -1.51,
                "comparable_operating_cashflow_to_net_profit": 0.755,
                "cash_received_from_sales_to_revenue_pct": 95.96,
                "comparable_cash_received_from_sales_to_revenue_pct": 106.245,
            }
        },
    }
    answer = (
        "中兴通讯经营现金流从上年同期18.51亿元净流入变为本期"
        "净流出19.79亿元；经营现金流与归母净利润比率从0.75变为"
        "-1.51，销售收现率从106.245%降至95.96%。这些口径需要分别理解。"
    )

    assert stock_specialist_relevance_issue(answer, evidence) is None


def test_quality_review_numeric_guard_accepts_evidenced_sales_cash_100pct_crossing():
    evidence = {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "display_name": "中兴通讯",
        "research_plan": {"focus": "quality_review"},
        "financial_drivers": {
            "cashflow_analysis": {
                "cash_received_from_sales_to_revenue_pct": 95.96,
                "comparable_cash_received_from_sales_to_revenue_pct": 106.245,
            }
        },
    }

    supported = AgentService._validate_model_output(
        "销售收现率从106.245%降至95.96%，已经跌破100%。",
        evidence,
    )
    no_crossing_evidence = {
        **evidence,
        "financial_drivers": {
            "cashflow_analysis": {
                "cash_received_from_sales_to_revenue_pct": 95.96,
                "comparable_cash_received_from_sales_to_revenue_pct": 96.0,
            }
        },
    }
    no_crossing = AgentService._validate_model_output(
        "销售收现率从96%降至95.96%，已经跌破100%。",
        no_crossing_evidence,
    )
    unrelated_metric = AgentService._validate_model_output(
        "毛利率已经跌破100%。",
        evidence,
    )

    assert supported["unsupported_numbers"] == []
    assert no_crossing["unsupported_numbers"] == ["100%"]
    assert unrelated_metric["unsupported_numbers"] == ["100%"]


def test_quality_review_repair_keeps_ratios_when_removing_cash_mismatch_label():
    evidence = {
        "type": "stock_research",
        "symbol": "000063.SZ",
        "display_name": "中兴通讯",
        "research_plan": {"focus": "quality_review"},
        "earnings_quality": {
            "comparable_report": {
                "operating_cashflow_to_net_profit": 0.7546,
            }
        },
        "financial_drivers": {
            "cashflow_analysis": {
                "operating_cashflow": -1_978_648_000,
                "comparable_operating_cashflow": 1_851_253_000,
                "operating_cashflow_change_pct": -206.882,
                "operating_cashflow_to_net_profit": -1.51,
                "comparable_operating_cashflow_to_net_profit": 0.755,
                "cash_received_from_sales_to_revenue_pct": 95.96,
                "comparable_cash_received_from_sales_to_revenue_pct": 106.245,
            }
        },
    }
    answer = (
        "中兴通讯经营现金流从上年同期净流入18.51亿元变为本期净流出"
        "19.79亿元。经营现金流与归母净利润的比率变成负的1.51倍，去年同期"
        "是0.75倍，说明当期的报表利润并没有伴随着实际的现金净流入。"
        "经营现金流恶化，"
        "公司在报告里也做了解释：主要因为销售商品收到的现金减少，以及购买"
        "商品支付的现金增加。这能确认现金流压力来自收付两端的同时挤压。"
        "同时，销售商品、提供劳务收到的现金占营收的比例从106.245%降至"
        "95.96%，回款速度变慢。三项指标指向了同一个方向——回款和付款节奏"
        "在本季度出现了变化，但具体原因还不能确认。"
    )

    repaired = repair_quality_review_answer(answer, evidence)

    assert repaired is not None
    assert "负的1.51" in repaired
    assert "0.75" in repaired
    assert "95.96%" in repaired
    assert "销售商品收到的现金减少" in repaired
    assert "购买商品支付的现金增加" in repaired
    assert "报表利润并没有伴随着实际的现金净流入" not in repaired
    assert "收付两端的同时挤压" not in repaired
    assert "回款速度变慢" not in repaired
    assert "指向了同一个方向" not in repaired
    assert "回款和付款节奏" not in repaired
    assert stock_specialist_relevance_issue(repaired, evidence) is None


def test_quality_review_numeric_repair_keeps_cashflow_fact_paragraph():
    evidence = {
        "type": "stock_research",
        "symbol": "300750.SZ",
        "display_name": "宁德时代",
        "research_plan": {"focus": "quality_review"},
        "earnings_quality": {
            "latest_report": {
                "revenue": 276_917_000_000,
                "revenue_yoy_pct": 54.80,
                "net_profit": 43_284_000_000,
                "net_profit_yoy_pct": 41.98,
            }
        },
        "financial_drivers": {
            "cashflow_analysis": {
                "operating_cashflow": 60_217_000_000,
                "operating_cashflow_change_pct": 2.61,
                "operating_cashflow_to_net_profit": 1.39,
                "comparable_operating_cashflow_to_net_profit": 1.93,
                "cash_received_from_sales_to_revenue_pct": 94.77,
                "comparable_cash_received_from_sales_to_revenue_pct": 124.62,
            }
        },
    }
    answer = (
        "宁德时代改善质量一般。\n\n"
        "营收同比54.80%，归母净利润同比41.98%，两者相差12.82个百分点；"
        "经营现金流602.17亿元，同比增长2.61%；经营现金流与归母净利润比率"
        "从1.93降至1.39；销售收现率从124.62%降至94.77%。"
    )
    guard = AgentService._validate_model_output(answer, evidence)

    repaired = AgentService._repair_guard_failure(answer, evidence, guard)

    assert guard["unsupported_numbers"] == ["12.82"]
    assert repaired is not None
    repaired_answer, repaired_guard = repaired
    assert "12.82" not in repaired_answer
    assert "经营现金流602.17亿元" in repaired_answer
    assert "销售收现率从124.62%降至94.77%" in repaired_answer
    assert repaired_guard["passed"] is True
    assert stock_specialist_relevance_issue(repaired_answer, evidence) is None


def test_clean_user_facing_language_translates_unresolved_themes_key():
    cleaned = AgentService._clean_user_facing_model_language(
        "这些原因仍属`unresolved_themes`，需要继续核验。"
    )

    assert cleaned == "这些原因仍属仍待核验事项，需要继续核验。"
    assert "unresolved_themes" not in cleaned


def test_quality_review_repair_drops_overclaim_sentences_without_static_fallback():
    evidence = {
        "type": "stock_research",
        "symbol": "300750.SZ",
        "display_name": "宁德时代",
        "research_plan": {"focus": "quality_review"},
    }
    answer = (
        "宁德时代改善质量目前一般。2026中报营收和净利润同比增长，但毛利率与"
        "销售收现率下降，具体经营原因仍需公司原文确认。\n\n"
        "经营现金流净额同比增长2.61%，低于归母净利润41.98%的增速；覆盖比率"
        "从1.93降至1.39，这些数字只说明同报告期差异。利润向现金的转化质量明显"
        "减弱。\n\n"
        "公司明确解释财务费用变化主要来自汇兑损失；毛利率变化、存货增速快于收入"
        "以及销售收现率下降的原因尚未确认。产品占比变化不代表业务结构优化。\n\n"
        "最重要的反方证据是利润与经营现金流增速差异、两项核心产品毛利率下降，"
        "以及存货增速快于收入。下一步应核对存货分类、应收账龄和管理层原文。"
    )

    repaired = repair_quality_review_answer(answer, evidence)

    assert repaired is not None
    assert "利润向现金的转化质量明显减弱" not in repaired
    assert "产品占比变化不代表业务结构优化" in repaired
    assert stock_specialist_relevance_issue(repaired, evidence) is None


def test_quality_review_repair_neutralizes_real_deepseek_cashflow_shortcuts():
    evidence = {
        "type": "stock_research",
        "symbol": "300750.SZ",
        "display_name": "宁德时代",
        "research_plan": {"focus": "quality_review"},
    }
    answer = (
        "宁德时代改善质量目前一般。增长有规模支撑，但毛利率、现金流覆盖比率和"
        "销售收现率三项指标同步走弱。\n\n"
        "经营现金流同比增长2.6%，覆盖比率从1.93降至1.39；销售收现率降至"
        "94.8%，回款效率回落明显。具体原因尚未由公司解释。\n\n"
        "最重要的反方证据是三项线索提示回款和营运资金占用可能在加大，但目前"
        "不能证明产品积压。后续需要核验存货分类和应收账龄，才能进一步判断"
        "现金流压力和盈利质量是否会持续。"
    )

    repaired = repair_quality_review_answer(answer, evidence)

    assert repaired is not None
    assert "增长有规模支撑" not in repaired
    assert "三项指标同步走弱" not in repaired
    assert "回款效率回落明显" not in repaired
    assert "提示回款和营运资金占用可能在加大" not in repaired
    assert "现金流压力" not in repaired
    assert "营收和利润增长是已确认的报表事实" in repaired
    assert "具体原因尚未确认" in repaired
    assert stock_specialist_relevance_issue(repaired, evidence) is None


def test_quality_review_repair_neutralizes_cross_metric_confirmation_shortcut():
    evidence = {
        "type": "stock_research",
        "symbol": "300750.SZ",
        "display_name": "宁德时代",
        "research_plan": {"focus": "quality_review"},
    }
    answer = (
        "宁德时代改善质量目前一般。经营现金流同比增长2.6%，覆盖比率从1.93降至"
        "1.39，销售收现率从125.0%降至94.8%。\n\n"
        "这三项合在一起，说明本期利润增长尚未得到经营现金流和回款节奏的同等确认。"
        "公司原文已说明库存增加主要是为下半年市场需求而提前备货。公司尚未解释"
        "毛利率下降，也不排除产品组合、原材料价格或交付批次的影响。\n\n"
        "反方事实是动力电池和储能系统毛利率均较可比期下降；当前没有同报告期同行"
        "经营数据，不能判断改善质量是否优于行业。下一步需核验存货分类、库龄、订单"
        "覆盖和跌价准备，并继续查找销售收现率变化的公司原文。"
    )

    repaired = repair_quality_review_answer(answer, evidence)

    assert repaired is not None
    assert "回款节奏的同等确认" not in repaired
    assert "不能合并推断回款节奏" in repaired
    assert "提前备货" in repaired
    assert "不排除产品组合" not in repaired
    assert "具体原因仍需公司原文或分部数据确认" in repaired
    assert stock_specialist_relevance_issue(repaired, evidence) is None


def test_quality_review_stream_guard_withholds_overclaim_sentence(
    tmp_path: Path, settings
):
    guarded_settings = replace(
        settings,
        workspace_root=tmp_path / "quality-review-stream-workspaces",
    )
    database = Database(guarded_settings.workspace_root)
    database.initialize()
    service = AgentService(database, guarded_settings)
    evidence = {
        "type": "stock_research",
        "symbol": "300750.SZ",
        "display_name": "宁德时代",
        "research_plan": {"focus": "quality_review"},
    }

    guard = service._validate_stream_output(
        "宁德时代销售收现率降至94.8%，回款效率回落明显。",
        evidence,
    )

    assert service._stream_partial_guard_has_blocker(guard) is True
    assert any("回款质量" in item for item in guard["unsupported_market_inferences"])


def test_stock_specialist_many_wrong_numbers_gets_grounded_model_retry(
    tmp_path: Path, settings, monkeypatch
):
    guarded_settings = replace(
        settings,
        workspace_root=tmp_path / "specialist-guard-retry-workspaces",
        hermes_enabled=True,
    )
    database = Database(guarded_settings.workspace_root)
    database.initialize()
    user = database.create_user("Specialist Guard Retry User")
    service = AgentService(database, guarded_settings)
    calls = []

    def fake_stream(**kwargs):
        calls.append(kwargs.get("prompt_path"))
        if len(calls) == 1:
            return (
                "北方国际的工程建设与服务占收入72%，资源设备供应链占17%，"
                "两项毛利率分别为6.9%和4.9%。",
                {"model": "fake-first", "streaming": {"enabled": True}},
            )
        return (
            "北方国际当前最大的收入来源是工程建设与服务，"
            "资源设备供应链也是主要组成部分。反方证据是两项业务合计占比较高，"
            "而分部标签本身不能证明未来盈利会继续改善。",
            {"model": "fake-retry", "streaming": {"enabled": True}},
        )

    monkeypatch.setattr(service, "_execute_hermes_streaming", fake_stream)
    streamed = []
    run = service.run(
        user=user,
        intent="business_structure",
        message="请继续分析北方国际的主营业务和反方证据。",
        evidence={
            "type": "business_structure",
            "symbol": "000065.SZ",
            "name": "北方国际",
            "summary": "最大业务为工程建设与服务。",
            "dimensions": [
                {
                    "classification": "product",
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
            "research_plan": {
                "focus": "business",
                "focus_label": "主营业务与收入结构",
            },
        },
        model_tier="economy",
        execute_agent=True,
        stream_callback=streamed.append,
    )

    assert len(calls) == 2
    assert calls[0] is None
    assert calls[1].name == "prompt.guard_retry.md"
    assert run["status"] == "completed"
    assert "工程建设与服务" in run["answer"]
    assert "72%" not in run["answer"]
    assert run["usage"]["guard_retry"]["passed"] is True
    assert run["usage"]["output_guard"]["passed"] is True
    assert any(item.get("type") == "reset" for item in streamed)
    run_dir = Path(run["workspace_path"]) / "runs" / run["id"]
    assert (run_dir / "answer.guard_rejected.md").is_file()
    assert (run_dir / "prompt.guard_retry.md").is_file()


def test_two_round_business_followup_reloads_current_company_segments(
    tmp_path: Path, settings, monkeypatch
):
    guarded_settings = replace(
        settings,
        workspace_root=tmp_path / "business-followup-workspaces",
        hermes_enabled=True,
    )
    database = Database(guarded_settings.workspace_root)
    database.initialize()
    user = database.create_user("Business Followup User")
    service = AgentService(database, guarded_settings)
    prompts = []

    def fake_stream(**kwargs):
        prompt_path = kwargs.get("prompt_path") or (kwargs["run_dir"] / "prompt.md")
        prompts.append(prompt_path.read_text(encoding="utf-8"))
        return (
            "北方国际的主要收入来源是工程建设与服务和资源设备供应链。"
            "当前更重要的反方证据是业务集中度较高，但这不能单独证明未来盈利变化。",
            {"model": "fake-deepseek", "streaming": {"enabled": True}},
        )

    monkeypatch.setattr(service, "_execute_hermes_streaming", fake_stream)

    def evidence(question: str) -> dict:
        return {
            "type": "business_structure",
            "symbol": "000065.SZ",
            "name": "北方国际",
            "user_question": question,
            "summary": "最大业务为工程建设与服务。",
            "dimensions": [
                {
                    "classification": "product",
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
            "research_plan": {
                "focus": "business",
                "focus_label": "主营业务与收入结构",
            },
        }

    first_question = "北方国际靠什么业务赚钱？"
    first = service.run(
        user=user,
        intent="business_structure",
        message=first_question,
        evidence=evidence(first_question),
        model_tier="economy",
        execute_agent=True,
        conversation_id="business-followup",
        stream_callback=lambda _event: None,
    )
    second_question = (
        "请继续分析北方国际主营业务，说明结构变化、反方证据和当前不能确认的内容。"
    )
    second = service.run(
        user=user,
        intent="business_structure",
        message=second_question,
        evidence=evidence(second_question),
        model_tier="economy",
        execute_agent=True,
        conversation_id="business-followup",
        conversation_history=[
            {"role": "user", "content": first_question},
            {"role": "assistant", "content": first["answer"]},
        ],
        stream_callback=lambda _event: None,
    )

    assert first["status"] == "completed"
    assert second["status"] == "completed"
    assert len(prompts) == 2
    assert "工程建设与服务" in prompts[1]
    assert "资源设备供应链" in prompts[1]
    assert '"dimensions"' in prompts[1]
    assert '"price_move_event_evidence"' not in prompts[1]
    assert "本轮仅展示已核验事实" not in second["answer"]


def test_business_structure_guard_accepts_colloquial_rounded_percentage_points():
    evidence = {
        "type": "business_structure",
        "symbol": "000065.SZ",
        "business_structure": {
            "dimensions": [
                {
                    "segments": [
                        {
                            "item_name": "电力运营",
                            "gross_margin_change_pp": 9.3869,
                        },
                        {
                            "item_name": "资源设备供应链",
                            "revenue_growth_pct": -39.278,
                            "revenue_share_change_pp": 2.8297,
                            "comparable_gross_margin_pct": 12.043,
                            "gross_margin_pct": 8.6796,
                            "gross_margin_change_pp": -3.3637,
                        },
                    ]
                }
            ]
        },
    }

    guard = AgentService._validate_model_output(
        "电力运营毛利率比上一年提升了9个多百分点。",
        evidence,
    )

    assert guard["passed"] is True
    assert guard["unsupported_numbers"] == []

    approximate_guard = AgentService._validate_model_output(
        "电力运营毛利率比上一年提升了约9个百分点。",
        evidence,
    )

    assert approximate_guard["passed"] is True
    assert approximate_guard["unsupported_numbers"] == []

    transition_guard = AgentService._validate_model_output(
        "该分部毛利率从12.043%跌到8.68%，下降了3.4个百分点；"
        "收入同比下降近4成，另一项占比提升2.8个百分点。",
        evidence,
    )

    assert transition_guard["passed"] is True
    assert transition_guard["unsupported_numbers"] == []


def test_business_structure_numeric_repair_keeps_supported_sentences():
    evidence = {
        "type": "business_structure",
        "business_structure": {
            "dimensions": [
                {
                    "segments": [
                        {
                            "item_name": "工程建设与服务",
                            "revenue_share_pct": 46.6,
                        },
                        {
                            "item_name": "资源设备供应链",
                            "revenue_share_pct": 40.2,
                        },
                    ]
                }
            ]
        },
    }
    answer = (
        "北方国际第一大业务是工程建设与服务，占46.6%。"
        "资源设备供应链占40.2%，也是主要收入来源。"
        "另外两块业务合计占12.8%。"
    )

    guard = AgentService._validate_model_output(answer, evidence)
    repaired = AgentService._repair_guard_failure(answer, evidence, guard)

    assert guard["unsupported_numbers"] == ["12.8%"]
    assert repaired is not None
    repaired_answer, repaired_guard = repaired
    assert repaired_guard["passed"] is True
    assert "第一大业务是工程建设与服务" in repaired_answer
    assert "资源设备供应链占40.2%" in repaired_answer
    assert "12.8%" not in repaired_answer


def test_streaming_bridge_failure_falls_back_to_oneshot_cli(
    tmp_path: Path, settings, monkeypatch
):
    guarded_settings = replace(
        settings,
        workspace_root=tmp_path / "stream-fallback-workspaces",
        hermes_enabled=True,
    )
    database = Database(guarded_settings.workspace_root)
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
