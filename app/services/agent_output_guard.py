from __future__ import annotations

from datetime import datetime
import json
import re
from typing import Any

from app.services.agent_evidence_compaction import aligned_market_indices
from app.services.agent_output_guard_common import (
    _EVIDENCE_MAGNITUDE_RE,
    _NEGATIVE_NUMBER_CONTEXT_RE,
    _NUMBER_RE,
    _POSITIVE_NUMBER_CONTEXT_RE,
    _PRIVATE_OPERATIONAL_OUTPUT_PATTERNS,
    _PROHIBITED_OUTPUT_PATTERNS,
)
from app.services.agent_output_guard_market import (
    _MARKET_NEWS_CAUSAL_LABEL,
    _MARKET_TECHNICAL_REPAIR_CAUSAL_LABEL,
    _MARKET_STYLE_GAP_STORY_LABEL,
    _MARKET_NEW_CATALYST_GATE_LABEL,
    _UNSUPPORTED_PEER_OPERATING_INFERENCE_PATTERNS,
    _is_index_contribution_clause,
    _NEGATIVE_SENTIMENT_LANGUAGE_RE,
    _POSITIVE_SENTIMENT_LANGUAGE_RE,
    _UNSUPPORTED_MARKET_INFERENCE_PATTERNS,
    _UNSUPPORTED_SHAREHOLDER_INFERENCE_PATTERNS,
    _has_unsupported_shareholder_inference,
    _SHAREHOLDER_STREAK_CLAIM_RE,
    _AVAILABLE_DISTRIBUTION_MISSING_RE,
    _AVAILABLE_TURNOVER_MISSING_RE,
    _AVAILABLE_MARKET_DRIVERS_MISSING_RE,
    _has_available_index_return_missing_claim,
    _market_cause_fact_required_but_missing,
    _has_whole_market_breadth_overclaim,
    _has_unsupported_majority_stock_claim,
    _has_uncautious_breadth_label,
    _has_uncautious_structural_market_claim,
    _has_unproven_downtrend_claim,
    _has_wrong_index_return_extreme_claim,
    _has_unavailable_index_return_claim,
    _has_index_return_direction_conflict,
    _has_index_trend_state_conflict,
    _has_wrong_index_volatility_extreme_claim,
    _has_mismatched_major_index_count,
    _has_moving_average_status_conflict,
    _has_unproven_analyst_revision_claim,
    _has_unsafe_rating_recommendation,
    _TOP10_HISTORICAL_COMPARISON_RE,
    _REPRESENTATIVE_INDEX_COUNT_RE,
    _APPROX_REPRESENTATIVE_INDEX_COUNT_RE,
    _SINGLE_INDEX_ADVANCE_RATIO_RE,
    _UNAVAILABLE_MA5_RE,
    _UNSUPPORTED_WAVE_RE,
)
from app.services.agent_output_guard_stock import (
    _STOCK_FAILURE_THRESHOLD_LABEL,
    _STOCK_OBSERVATION_WINDOW_LABEL,
    _LI_ZONG_RULE_BOTTLENECK_LABEL,
    _LI_ZONG_COVERAGE_CONFLATION_LABEL,
    _STOCK_SCREEN_SCOPE_OVERCLAIM_LABEL,
    _STOCK_SCREEN_CANDIDATE_COUNT_LABEL,
    _STOCK_DISCLOSURE_DATE_LABEL,
    _STOCK_REPORT_DATE_CONFLICT_LABEL,
    _STOCK_DRAWDOWN_WINDOW_LABEL,
    _STOCK_SCENARIO_DIRECTION_LABEL,
    _STOCK_CURRENT_QUOTE_DIRECTION_LABEL,
    _STOCK_CURRENT_QUOTE_PRICE_LABEL,
    _STOCK_CURRENT_QUOTE_CLOSE_LABEL,
    _STOCK_CURRENT_QUOTE_SESSION_LABEL,
    _STOCK_CURRENT_QUOTE_MA20_LABEL,
    _STOCK_CURRENT_LIMIT_STATUS_LABEL,
    _STOCK_CURRENT_QUOTE_REQUIRED_LABEL,
    _STOCK_CROSS_DATE_MARKET_LABEL,
    _STOCK_INDUSTRY_BREADTH_LABEL,
    _STOCK_60D_RETURN_BINDING_LABEL,
    _STOCK_DEBT_RATIO_SCALE_LABEL,
    _STOCK_CASHFLOW_CAUSE_LABEL,
    _STOCK_STATIC_FINANCIAL_CAUSAL_LABEL,
    _STOCK_INDUSTRY_CAUSAL_LABEL,
    _STOCK_CONTRIBUTION_REQUIRED_LABEL,
    _STOCK_INDUSTRY_COUNTS_REQUIRED_LABEL,
    _STOCK_COMPONENT_SOURCE_BOUNDARY_LABEL,
    _STOCK_MARKET_ABSORPTION_LABEL,
    _STOCK_EVENT_SENTIMENT_LABEL,
    _STOCK_SENTIMENT_EXCLUSION_LABEL,
    _STOCK_UNSUPPORTED_CAUSAL_HYPOTHESIS_LABEL,
    _MARKET_CAUSE_FACT_REQUIRED_LABEL,
    _stock_failure_line_has_unsupported_threshold,
    _has_unsupported_stock_failure_threshold,
    _has_unsupported_stock_observation_window,
    _has_li_zong_rule_bottleneck_overclaim,
    _has_li_zong_coverage_conflation,
    _has_stock_screen_scope_overclaim,
    _has_stock_screen_candidate_count_conflict,
    _has_unsupported_stock_disclosure_date,
    _has_stock_report_notice_date_conflict,
    _has_stock_drawdown_window_conflict,
    _has_stock_scenario_direction_conflict,
    _stock_current_quote_conflicts,
    _stock_current_quote_close_conflict,
    _stock_current_quote_session_conflict,
    _stock_current_quote_ma20_conflict,
    _stock_current_limit_status_conflict,
    _stock_current_quote_required_but_missing,
    _has_stock_cross_date_market_claim,
    _has_stock_industry_breadth_overclaim,
    _has_stock_industry_causal_overclaim,
    _stock_contribution_required_but_missing,
    _stock_industry_counts_required_but_missing,
    _stock_component_source_boundary_required_but_missing,
    _has_stock_market_absorption_overclaim,
    _is_public_component_source_boundary_clause,
    _is_evidence_security_entity_clause,
    _has_stock_event_sentiment_overclaim,
    _has_stock_sentiment_exclusion_overclaim,
    _has_stock_unsupported_causal_hypothesis,
    _has_stock_60d_return_binding_conflict,
    _has_stock_debt_ratio_scale_conflict,
    _has_stock_cashflow_causal_conflict,
    _has_stock_static_financial_causal_overclaim,
)


_REASSESSMENT_REQUEST_TERMS = (
    "失效条件",
    "不成立条件",
    "什么时候需要重新判断",
    "何时需要重新判断",
    "需要重新判断的情况",
    "什么情况会推翻",
    "哪些情况会推翻",
    "什么会推翻",
)
_REASSESSMENT_ANSWER_TERMS = (
    *_REASSESSMENT_REQUEST_TERMS,
    "需要重新评估",
    "当前判断需要重算",
    "必须重算当前判断",
)
_REASSESSMENT_REQUIRED_LABEL = (
    "用户明确询问何时需要重新判断时回答必须说明对应情况"
)


def _asks_for_reassessment_conditions(text: Any) -> bool:
    normalized = str(text or "")
    return any(term in normalized for term in _REASSESSMENT_REQUEST_TERMS)


def _answer_explains_reassessment_conditions(text: Any) -> bool:
    normalized = str(text or "")
    return any(term in normalized for term in _REASSESSMENT_ANSWER_TERMS)


class AgentOutputGuard:
    """Coordinate deterministic validation and repair of model-visible answers."""

    _aligned_market_indices = staticmethod(aligned_market_indices)

    @staticmethod
    def _convert_markdown_tables(answer: str) -> str:
        lines = answer.splitlines()
        converted: list[str] = []
        index = 0

        def cells(line: str) -> list[str]:
            return [item.strip() for item in line.strip().strip("|").split("|")]

        while index < len(lines):
            line = lines[index]
            if (
                line.strip().startswith("|")
                and index + 1 < len(lines)
                and re.match(
                    r"^\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*:?-{3,}:?\s*\|?\s*$",
                    lines[index + 1],
                )
            ):
                headers = cells(line)
                index += 2
                while index < len(lines) and lines[index].strip().startswith("|"):
                    values = cells(lines[index])
                    pairs = [
                        f"{header}：{value}"
                        for header, value in zip(headers, values)
                        if header and value
                    ]
                    if pairs:
                        converted.append("- " + "；".join(pairs))
                    index += 1
                continue
            converted.append(line)
            index += 1
        return "\n".join(converted)

    @staticmethod
    def _clean_user_facing_model_language(answer: str) -> str:
        answer = re.sub(
            r"(?im)^(\s*(?:#{1,6}\s*)?(?:\*\*|__)?)失效条件"
            r"((?:\*\*|__)?\s*[：:]?)",
            r"\1什么时候需要重新判断\2",
            answer,
        )
        answer = re.sub(
            r"(?im)^\s*(?:用户|提问者)询问(?:了)?[^\n]*$\n?",
            "",
            answer,
        )
        answer = re.sub(
            r"(?im)^.*(?:question_focus(?:\.key)?|date_alignment|"
            r"analysis_eligibility|same_date_as_analysis_target|"
            r"cross_date_excluded)[^\n]*$\n?",
            "",
            answer,
        )
        answer = re.sub(
            r"`?evidence_readiness`?\s*=\s*ready",
            "核心证据完整",
            answer,
            flags=re.IGNORECASE,
        )
        answer = re.sub(
            r"(?:均标注|均处于)\s*`?ready`?\s*(?:状态)?",
            "均可用",
            answer,
            flags=re.IGNORECASE,
        )
        answer = re.sub(
            r"\bscore\s+([-+]?\d)", r"情绪分数 \1", answer, flags=re.IGNORECASE
        )
        answer = re.sub(r"置信度\s+low\b", "置信度较低", answer, flags=re.IGNORECASE)
        answer = re.sub(r"置信度\s+medium\b", "置信度中等", answer, flags=re.IGNORECASE)
        answer = re.sub(r"置信度\s+high\b", "置信度较高", answer, flags=re.IGNORECASE)
        answer = re.sub(
            r"(?:同口径)?(?:历史比较|历史对比)?\s*(?:仍)?(?:处于|为)?\s*"
            r"`?building_history`?\s*(?:状态)?",
            "同口径历史仍在积累",
            answer,
            flags=re.IGNORECASE,
        )
        answer = re.sub(
            r"(?:证据中\s*)?`?exact_industry_match_available`?\s*=\s*false`?",
            "未取得与公司行业精确匹配的同日板块序列",
            answer,
            flags=re.IGNORECASE,
        )
        answer = re.sub(
            r"`?exact_industry_match_available`?\s*=\s*true`?",
            "已取得与公司行业精确匹配的同日板块序列",
            answer,
            flags=re.IGNORECASE,
        )
        answer = re.sub(
            r"`?same_date_as_target`?\s*=\s*false`?",
            "与目标交易日不一致",
            answer,
            flags=re.IGNORECASE,
        )
        answer = re.sub(
            r"`?same_date_as_target`?\s*=\s*true`?",
            "与目标交易日一致",
            answer,
            flags=re.IGNORECASE,
        )
        answer = re.sub(
            r"(?:今日|当日)?(?:上涨|下跌|回调)?(?:属于|是)?"
            r"(?:独立于|脱离)(?:大市|大盘|行业)的?"
            r"(?:个股)?(?:上涨|下跌|回调|表现)?",
            "相对大市表现明显分化",
            answer,
        )
        answer = re.sub(
            r"(?:不能|无法|不应)归结为(?:全市场)?(?:系统性|大盘或行业|市场或行业)"
            r"[^。；\n]{0,12}(?:拖累|因素|原因)",
            "当日事实不支持全市场普跌解释，但具体驱动仍未确认",
            answer,
        )
        answer = re.sub(
            r"(?:当日|今日)?(?:盘面|事实)?不支持(?:全市场)?(?:系统性)?普跌"
            r"(?:拖累(?:个股|该股)?)?",
            "当日事实不支持全市场普跌解释",
            answer,
        )
        answer = re.sub(
            r"(?:同日)?(?:大盘|市场)[^。；\n]{0,32}不支持(?:全市场)?系统性拖累",
            "同日市场事实不支持全市场普跌解释",
            answer,
        )
        answer = re.sub(
            r"(?:当日|今日)[^。；\n]{0,24}不支持(?:全市场)?系统性拖累",
            "当日事实不支持全市场普跌解释",
            answer,
        )
        answer = re.sub(
            r"(?:上涨|下跌|回落)?(?:属于|是)?与(?:大盘|大市|市场|行业)"
            r"方向不同的独立表现",
            "相对市场方向明显分化，但具体驱动仍未确认",
            answer,
        )
        answer = re.sub(
            r"[，,]\s*(?:现金覆盖能力|现金覆盖|现金质量|现金支撑)"
            r"(?:转弱|下降|恶化|改善|增强)",
            "",
            answer,
        )
        answer = re.sub(
            r"[（(](?:成本上升|成本变化)(?:或|、)"
            r"(?:产品结构|产品组合)(?:变化|调整)[）)]",
            "",
            answer,
        )
        answer = re.sub(
            r"(?:上涨|下跌|大跌|回落)[^。；\n]{0,24}(?:主要)?"
            r"(?:来自|源于|归因于|由)[^。；\n]{0,24}"
            r"(?:个股|公司)(?:自身|特定)?(?:因素|压力|原因)",
            "该股相对市场表现明显偏弱，但具体驱动仍未确认",
            answer,
        )
        answer = re.sub(
            r"(?:综合来看[，,]?)?(?:今日|当日|本次)?(?:大跌|下跌|回落)"
            r"[^。；\n]{0,24}(?:主要(?:表现为|原因是)|归因于|源于)"
            r"[^。；\n]{0,180}(?:引发|导致|造成|回吐|提前调整)[^。；\n]*",
            "现有证据只能确认价格下跌与相对表现，具体驱动仍未确认",
            answer,
        )
        answer = re.sub(
            r"(?:更多|主要)?体现为[^。；\n]{0,120}"
            r"(?:获利回吐|基本面隐忧|因素共振|情绪共振)[^。；\n]*",
            "具体驱动仍未确认",
            answer,
        )
        answer = re.sub(r"[，,]?(?:因此)?回落不意外", "", answer)
        replacements = {
            "原判断的失效条件": "什么情况会推翻原判断",
            "原判断失效条件": "什么情况会推翻原判断",
            "当前判断的失效条件": "需要重新判断当前结论的情况",
            "判断失效条件": "需要重新判断的情况",
            "失效条件": "需要重新判断的情况",
            "根据你提供的完整当前证据和技能要求": "根据当前可验证证据",
            '能确认的"非系统性拖累"': "市场与行业对照",
            "能确认的“非系统性拖累”": "市场与行业对照",
            "完全不存在系统性拖累": "当日事实不支持全市场普跌解释",
            "不存在系统性拖累": "当日事实不支持全市场普跌解释",
            '"当前最可能的市场解释"': "“市场资讯反复提及的解释”",
            "“当前最可能的市场解释”": "“市场资讯反复提及的解释”",
            "当前最可能的市场解释": "市场资讯反复提及的解释",
            "当前已接入资料未披露": "现有证据没有提供",
            "当前已接入资料": "现有资料",
            "尚未接入": "当前证据未提供",
            "未接入": "当前证据未提供",
            "无钱接入": "无线接入",
            "`conditional_outlook`": "条件展望",
            "conditional_outlook": "条件展望",
            "`optional_gaps`": "扩展证据缺口",
            "optional_gaps": "扩展证据缺口",
            "`unresolved_themes`": "仍待核验事项",
            "unresolved_themes": "仍待核验事项",
            "`not_directionally_consistent`": "历史方向一致性不足",
            "not_directionally_consistent": "历史方向一致性不足",
            "`low_to_medium`": "较低至中等",
            "low_to_medium": "较低至中等",
            "当前证据中 market_drivers 的资讯项为空": (
                "当前没有与本问题直接相关的市场资讯"
            ),
            "证据包中的 data": "当前可验证数据",
            "证据包中的数据": "当前可验证数据",
            "确定性证据包": "当前可验证证据",
            "证据包": "当前证据",
            "累计亏损": "累计跌幅",
            "两者technical_state": "两者的技术状态",
            "technical_state": "技术状态",
            "trend_state": "趋势状态",
            "market_state": "市场状态",
            "pct_change": "涨跌幅",
            "volume_ratio_5_20": "5/20日均量比",
            "max_drawdown_60d_pct": "近60日最大回撤",
            "max_drawdown": "最大回撤",
            "atr_14_pct": "ATR14波动幅度",
            "market_drivers": "市场资讯",
            "return_1d_pct": "1日累计收益",
            "return_5d_pct": "5日累计收益",
            "return_20d_pct": "20日累计收益",
            "return_60d_pct": "60日累计收益",
            "analysis_target.market_date": "目标交易日",
            "analysis_target": "目标交易日口径",
        }
        for old, new in replacements.items():
            answer = answer.replace(old, new)
        answer = answer.replace("当前当前", "当前")
        answer = re.sub(r"(?:解释){2,}", "解释", answer)
        answer = answer.replace("。；", "；").replace("；。", "。")
        answer = re.sub(
            r"[（(]\s*label\s*=\s*([^）)]+)[）)]",
            r"（\1）",
            answer,
            flags=re.IGNORECASE,
        )
        answer = re.sub(
            r"跌幅\s*0\s*(?:~|～|—|–|至|到)\s*-\s*(\d+(?:\.\d+)?%)",
            r"跌幅0—\1",
            answer,
        )
        answer = re.sub(
            r"跌幅\s*(?:≥|>=|大于等于)\s*-\s*(\d+(?:\.\d+)?%)",
            r"跌幅≥\1",
            answer,
        )
        answer = AgentOutputGuard._convert_markdown_tables(answer)
        cleaned = "\n".join(
            AgentOutputGuard._drop_empty_answer_sections(answer.splitlines())
        ).strip()
        return AgentOutputGuard._renumber_markdown_lists(cleaned)

    @staticmethod
    def _validate_model_output(
        answer: str,
        evidence: dict[str, Any],
        trusted_context: list[str] | None = None,
    ) -> dict[str, Any]:
        analyst_evidence = (
            evidence
            if evidence.get("type") == "analyst_expectations"
            else evidence.get("analyst_expectations") or {}
        )
        prohibited = [
            pattern.pattern
            for pattern in _PROHIBITED_OUTPUT_PATTERNS
            if pattern.search(answer)
        ]
        if _has_unsafe_rating_recommendation(
            answer,
            analyst_evidence_available=bool(analyst_evidence),
        ):
            prohibited.append("无研报样本语境的买入或卖出评级")
        answer_clauses_for_privacy = re.split(r"[。；\n]", answer)
        private_operational = [
            pattern.pattern
            for pattern in _PRIVATE_OPERATIONAL_OUTPUT_PATTERNS
            if any(
                pattern.search(clause)
                and not _is_public_component_source_boundary_clause(clause)
                and not _is_evidence_security_entity_clause(clause, evidence)
                for clause in answer_clauses_for_privacy
            )
        ]
        guard_evidence = evidence
        if evidence.get("type") == "market_brief":
            guard_evidence = dict(evidence)
            guard_evidence["indices"] = AgentOutputGuard._aligned_market_indices(evidence)
            hot_sectors = dict(evidence.get("hot_sectors") or {})
            if hot_sectors.get("same_date_as_analysis_target") is False:
                hot_sectors["sectors"] = []
            guard_evidence["hot_sectors"] = hot_sectors
            market_breadth = dict(evidence.get("market_breadth") or {})
            user_question = str(evidence.get("user_question") or "")
            cross_date_comparison = bool(
                evidence.get("cross_date_comparison")
            ) or any(
                term in user_question
                for term in ("今天", "今日", "当前", "盘中", "午间")
            ) and any(
                term in user_question
                for term in ("昨天", "昨日", "上一交易日", "前一交易日", "前日")
            )
            if (
                market_breadth.get("same_date_as_analysis_target") is False
                and not cross_date_comparison
            ):
                market_breadth = {
                    "status": "cross_date_excluded",
                    "market_date": market_breadth.get("market_date"),
                }
            guard_evidence["market_breadth"] = market_breadth
        elif evidence.get("type") == "stock_research":
            # Retrieved prose is contextual reading, not a subject-bound
            # numeric source. A user-wide research summary may contain metrics
            # for several stocks; accepting every number in that text allowed a
            # different security's volatility to pass as the current symbol's.
            # Current-stock numbers must be supported by structured evidence.
            guard_evidence = dict(evidence)
            guard_evidence.pop("knowledge_context", None)
        evidence_text = json.dumps(guard_evidence, ensure_ascii=False, default=str)
        if trusted_context:
            evidence_text += "\n" + "\n".join(trusted_context)
        evidence_values = AgentOutputGuard._numeric_values(evidence_text)
        allowed_values: list[float] = []
        allowed_magnitudes: list[float] = []
        for value in evidence_values:
            allowed_values.append(value)
            allowed_magnitudes.append(abs(value))
            absolute = abs(value)
            if absolute >= 1000:
                scaled = [
                    value / scale
                    for scale in (
                        10_000,
                        100_000_000,
                        1_000_000_000,
                        1_000_000_000_000,
                    )
                ]
                allowed_values.extend(scaled)
                allowed_magnitudes.extend(abs(item) for item in scaled)
            if absolute <= 10:
                allowed_values.append(value * 100)
                allowed_magnitudes.append(absolute * 100)

        earnings = guard_evidence.get("earnings_quality") or {}
        latest_report = earnings.get("latest_report") or {}
        comparable_report = earnings.get("comparable_report") or {}
        for key, current_value in latest_report.items():
            comparable_value = comparable_report.get(key)
            if not str(key).endswith("_pct") or not all(
                isinstance(value, (int, float)) and not isinstance(value, bool)
                for value in (current_value, comparable_value)
            ):
                continue
            change_pp = float(current_value) - float(comparable_value)
            allowed_values.append(change_pp)
            allowed_magnitudes.append(abs(change_pp))

        # Metric names such as return_60d_pct contain structural period numbers
        # that the answer may name as “60日”. Only take these magnitudes from
        # dictionary keys. Scanning the whole JSON text would accidentally let
        # unrelated values support newly invented ratios and thresholds.
        allowed_magnitudes.extend(AgentOutputGuard._evidence_key_magnitudes(guard_evidence))
        if evidence.get("type") == "market_brief":
            for item in guard_evidence.get("indices") or []:
                metrics = item.get("metrics") or {}
                latest = metrics.get("latest_close")
                if not isinstance(latest, (int, float)):
                    continue
                for key in ("ma20", "ma60"):
                    average = metrics.get(key)
                    if not isinstance(average, (int, float)) or float(average) == 0:
                        continue
                    difference = float(latest) - float(average)
                    distance_pct = difference / float(average) * 100
                    derived_values = {
                        difference,
                        round(difference),
                        round(distance_pct, 1),
                        round(distance_pct, 2),
                    }
                    allowed_values.extend(derived_values)
                    allowed_magnitudes.extend(abs(value) for value in derived_values)
        breadth_candidates = [
            ((guard_evidence.get("market_breadth") or {}).get("breadth") or {}),
            (
                (
                    (guard_evidence.get("stock_market_context") or {}).get(
                        "market_breadth"
                    )
                    or {}
                ).get("breadth")
                or {}
            ),
        ]
        for breadth in breadth_candidates:
            total = breadth.get("total")
            if not isinstance(total, (int, float)) or float(total) <= 0:
                continue
            for key in ("advancers", "decliners", "unchanged"):
                count = breadth.get(key)
                if not isinstance(count, (int, float)):
                    continue
                share = float(count) / float(total) * 100
                derived_shares = {round(share), round(share, 1), round(share, 2)}
                allowed_values.extend(derived_shares)
                allowed_magnitudes.extend(abs(value) for value in derived_shares)
        classification_method = str(
            (
                ((guard_evidence.get("market_breadth") or {}).get("breadth") or {}).get(
                    "classification_method"
                )
            )
            or ""
        )
        for threshold_match in _NUMBER_RE.finditer(classification_method):
            threshold = AgentOutputGuard._parse_number(threshold_match.group(0))
            if threshold is not None:
                allowed_values.append(abs(threshold))
                allowed_magnitudes.append(abs(threshold))

        def matches(
            candidate: float, allowed: list[float], tolerance_floor: float = 0.02
        ) -> bool:
            return any(
                abs(candidate - item) <= max(tolerance_floor, abs(item) * 0.005)
                for item in allowed
            )

        def is_supported_same_clause_ratio(
            number_match: re.Match[str], candidate: float
        ) -> bool:
            if number_match.group(0).endswith("%") or re.match(
                r"\s*倍", answer[number_match.end() : number_match.end() + 3]
            ) is None:
                return False
            clause_start = max(
                answer.rfind(mark, 0, number_match.start())
                for mark in ("。", "；", "！", "？", "\n")
            ) + 1
            prior_percentages = [
                item
                for item in _NUMBER_RE.finditer(
                    answer[clause_start : number_match.start()]
                )
                if item.group(0).endswith("%")
            ]
            if len(prior_percentages) < 2:
                return False
            numerator = AgentOutputGuard._parse_number(
                prior_percentages[-2].group(0)
            )
            denominator = AgentOutputGuard._parse_number(
                prior_percentages[-1].group(0)
            )
            if numerator is None or denominator in (None, 0):
                return False
            if not matches(abs(numerator), allowed_magnitudes, 0.051) or not matches(
                abs(denominator), allowed_magnitudes, 0.051
            ):
                return False
            expected = abs(numerator / denominator)
            token = number_match.group(0).lstrip("+-").replace(",", "")
            tolerance = 0.51 if "." not in token else 0.061
            return abs(abs(candidate) - expected) <= max(tolerance, expected * 0.02)

        unsupported = []
        unsupported_contexts = []
        for match in _NUMBER_RE.finditer(answer):
            token = match.group(0)
            value = AgentOutputGuard._parse_number(token)
            if value is None:
                continue
            line_start = answer.rfind("\n", 0, match.start()) + 1
            prefix = answer[line_start : match.start()]
            suffix = answer[match.end() : match.end() + 2]
            list_prefix = re.fullmatch(
                r"\s*(?:(?:[-+*]|#{1,6})\s+)?(?:\*\*|__)?",
                prefix,
            )
            is_list_marker = (
                not token.endswith("%")
                and list_prefix is not None
                and suffix[:1]
                in {
                    ".",
                    "、",
                    ")",
                    "）",
                }
            )
            if is_list_marker:
                continue
            named_index_prefix = answer[max(0, match.start() - 12) : match.start()]
            named_index_suffix = answer[match.end() : match.end() + 8]
            is_named_index_label = (
                not token.endswith("%")
                and re.search(
                    r"(?:沪深|中证|上证|科创|创业板|标普|日经|富时|纳斯达克)\s*$",
                    named_index_prefix,
                )
                is not None
                and re.match(
                    r"\s*(?:指数|ETF|etf|等|成分|[）)])?",
                    named_index_suffix,
                )
                is not None
            )
            if is_named_index_label:
                continue
            explicit_sign = token.startswith(("+", "-"))
            implied_value: float | None = None
            nearby = answer[
                max(line_start, match.start() - 24) : min(len(answer), match.end() + 12)
            ]
            absolute_ratio_transition = (
                "→" in nearby
                or "->" in nearby
                or (
                    token.endswith("%")
                    and re.search(
                        r"(?:从|由)[^。；\n]{0,32}$",
                        prefix[-40:],
                    )
                    is not None
                    and re.match(
                        r"\s*(?:下降|降低|回落|上升|提高|提升|增加|减少)",
                        answer[match.end() : match.end() + 24],
                    )
                    is not None
                )
                or (
                    token.endswith("%")
                    and re.search(
                        r"(?:率|占比|比重)(?:为|约为|是|达到|处于)\s*$",
                        prefix[-28:],
                    )
                    is not None
                )
                or (
                    "由" in nearby
                    and any(term in nearby for term in ("变为", "降至", "升至"))
                )
                or re.search(
                    r"(?:从|由)[^。；\n]{0,32}"
                    r"(?:变为|变成|降至|升至|降到|升到|下降到|上升到|"
                    r"跌到|涨到|回落到|提升到)\s*$",
                    prefix[-48:],
                )
                is not None
                or re.search(
                    r"(?:下降|上升|回落|提升|增加|减少)[^。；\n]{0,20}"
                    r"(?:至|到)(?:约|大约|近|超过|不足|高于|低于)?\s*$",
                    prefix[-48:],
                )
                is not None
                or re.search(
                    r"(?:变为|变成|降至|升至|降到|升到|下降到|上升到|"
                    r"跌到|涨到|回落到|提升到)"
                    r"(?:约|大约|近|超过|不足|高于|低于)?\s*$",
                    prefix[-24:],
                )
                is not None
            )
            if (
                token.endswith("%")
                and not explicit_sign
                and not absolute_ratio_transition
                and not AgentOutputGuard._is_breadth_share_percentage(answer, match)
            ):
                direction = AgentOutputGuard._percentage_direction(
                    answer[max(line_start, match.start() - 36) : match.start()]
                )
                if direction is not None:
                    implied_value = direction * abs(value)
            tolerance_floor = 0.02
            approximate_upper_bound: float | None = None
            approximate_plain_number: re.Match[str] | None = None
            if token.endswith("%"):
                numeric_token = token.lstrip("+-").rstrip("%")
                decimal_places = (
                    len(numeric_token.rsplit(".", 1)[1]) if "." in numeric_token else 0
                )
                if decimal_places == 0:
                    approximate_integer_percentage = re.search(
                        r"(?:约|大约|约为|近|超过|不足|多于|低于|高于|"
                        r"至少|不少于)\s*$",
                        prefix[-10:],
                    )
                    tolerance_floor = (
                        1.01
                        if (
                            AgentOutputGuard._is_percentage_range_endpoint(
                                answer, match
                            )
                            or approximate_integer_percentage
                        )
                        else 0.51
                    )
                    if approximate_integer_percentage:
                        trailing_zeros = len(numeric_token) - len(
                            numeric_token.rstrip("0")
                        )
                        if trailing_zeros > 0:
                            tolerance_floor = max(
                                tolerance_floor,
                                0.51 * (10**trailing_zeros),
                            )
                elif decimal_places == 1:
                    tolerance_floor = 0.051
            else:
                numeric_token = token.lstrip("+-").replace(",", "")
                trailing_zeros = len(numeric_token) - len(numeric_token.rstrip("0"))
                approximate_plain_number = re.search(
                    r"(?:约|大约|约为|近|超过|多于|高于|至少|不少于)\s*$",
                    prefix[-10:],
                )
                percentage_point_suffix = re.match(
                    r"\s*(?:个)?百分点",
                    answer[match.end() : match.end() + 8],
                )
                if re.match(
                    r"\s*(?:个)?多(?:个)?百分点",
                    answer[match.end() : match.end() + 8],
                ):
                    tolerance_floor = max(tolerance_floor, 1.01)
                elif percentage_point_suffix:
                    decimal_places = (
                        len(numeric_token.rsplit(".", 1)[1])
                        if "." in numeric_token
                        else 0
                    )
                    if decimal_places == 0:
                        tolerance_floor = max(
                            tolerance_floor,
                            1.01 if approximate_plain_number else 0.51,
                        )
                    elif decimal_places == 1:
                        tolerance_floor = max(tolerance_floor, 0.051)
                    elif decimal_places == 2:
                        tolerance_floor = max(tolerance_floor, 0.006)
                if (
                    "." not in numeric_token
                    and trailing_zeros > 0
                    and re.match(r"\s*多", answer[match.end() : match.end() + 3])
                ):
                    approximate_upper_bound = abs(value) + 10**trailing_zeros
                if "." not in numeric_token and approximate_plain_number:
                    if trailing_zeros > 0:
                        tolerance_floor = max(
                            tolerance_floor, 0.51 * (10**trailing_zeros)
                        )

            if explicit_sign:
                supported = matches(value, allowed_values, tolerance_floor)
            elif implied_value is not None:
                supported = matches(implied_value, allowed_values, tolerance_floor)
            else:
                supported = matches(value, allowed_values, tolerance_floor) or matches(
                    abs(value), allowed_magnitudes, tolerance_floor
                )
                if (
                    not supported
                    and approximate_plain_number
                    and re.match(
                        r"\s*成",
                        answer[match.end() : match.end() + 4],
                    )
                ):
                    supported = matches(
                        value * 10,
                        allowed_values,
                        1.01,
                    ) or matches(value * 10, allowed_magnitudes, 1.01)
            if not supported and approximate_upper_bound is not None:
                supported = any(
                    abs(value) <= item < approximate_upper_bound
                    for item in allowed_magnitudes
                )
            if not supported:
                supported = is_supported_same_clause_ratio(match, value)

            if not supported:
                unsupported.append(token)
                unsupported_contexts.append(
                    answer[
                        max(0, match.start() - 24) : min(len(answer), match.end() + 24)
                    ]
                )
        unsupported = list(dict.fromkeys(unsupported))[:12]
        semantic_conflicts: list[str] = []
        information = evidence.get("a_share_information") or {}
        sentiment = information.get("sentiment") or {}
        sentiment_band = str(sentiment.get("band") or "")
        if "偏多" in sentiment_band and _NEGATIVE_SENTIMENT_LANGUAGE_RE.search(answer):
            semantic_conflicts.append(
                f"社区情绪方向与证据不一致：证据为{sentiment_band}"
            )
        if "偏空" in sentiment_band and _POSITIVE_SENTIMENT_LANGUAGE_RE.search(answer):
            semantic_conflicts.append(
                f"社区情绪方向与证据不一致：证据为{sentiment_band}"
            )
        unsupported_market_inferences = []
        if evidence.get("type") == "market_brief":
            unsupported_market_inferences = []
            market_indices = AgentOutputGuard._aligned_market_indices(evidence)
            for label, pattern in _UNSUPPORTED_MARKET_INFERENCE_PATTERNS:
                match = pattern.search(answer)
                if match is None:
                    continue
                if label == "代表性指数涨幅不能直接证明市场或风格贡献" and (
                    evidence.get("index_contribution")
                    or (evidence.get("market_breadth") or {}).get("index_contribution")
                ):
                    continue
                if label == _MARKET_NEWS_CAUSAL_LABEL and any(
                    term in match.group(0)
                    for term in ("不能说明", "无法说明", "不能证明", "无法证明")
                ):
                    continue
                if (
                    label == "证据包没有给出阈值时不能发明量能或回撤验证门槛"
                    and AgentOutputGuard._is_evidenced_breadth_threshold(
                        answer, match, evidence
                    )
                ):
                    continue
                if label in {
                    "成交量或量比不能直接证明增量资金入场或资金流向",
                    "成交量或量比不能直接证明上涨参与面或市场覆盖范围",
                } and any(
                    term in match.group(0)
                    for term in (
                        "不能证明",
                        "不能说明",
                        "不能直接证明",
                        "不能直接说明",
                        "不能解读为",
                        "无法解读为",
                        "不宜解读为",
                        "不得解读为",
                        "不能视为",
                        "无法视为",
                        "无法证明",
                        "无法说明",
                        "无法直接证明",
                        "无法直接说明",
                        "不证明",
                        "不说明",
                        "不等于",
                        "不是",
                        "并非",
                    )
                ):
                    continue
                unsupported_market_inferences.append(label)
            market_state = evidence.get("market_state") or {}
            if market_state.get(
                "whole_market_breadth_available"
            ) is False and _has_whole_market_breadth_overclaim(answer, evidence):
                unsupported_market_inferences.append(
                    "缺少全市场涨跌家数时不能确认是否普涨"
                )
            if market_state.get(
                "whole_market_breadth_available"
            ) is False and _has_unsupported_majority_stock_claim(answer):
                unsupported_market_inferences.append(
                    "缺少同日全市场广度时不能声称多数个股涨跌"
                )
            if market_state.get("whole_market_breadth_available") is True:
                breadth_state = str(
                    market_state.get("whole_market_breadth_state") or ""
                )
                if (
                    breadth_state != "普涨"
                    and _has_uncautious_breadth_label(answer, "普涨")
                ) or (
                    breadth_state != "普跌"
                    and _has_uncautious_breadth_label(answer, "普跌")
                ):
                    unsupported_market_inferences.append(
                        "全市场广度结论必须沿用固定分类"
                    )
                if _has_uncautious_structural_market_claim(answer):
                    unsupported_market_inferences.append(
                        "固定广度分类和热门板块不能直接确认结构性行情"
                    )
                market_breadth = evidence.get("market_breadth") or {}
                user_question = str(evidence.get("user_question") or "")
                answer_clauses = re.split(r"[。；\n]", answer)
                turnover_available = (market_breadth.get("turnover") or {}).get(
                    "status"
                ) == "available"
                distribution_available = (market_breadth.get("distribution") or {}).get(
                    "status"
                ) == "available"
                if (
                    turnover_available
                    and "成交额" in user_question
                    and not any(
                        any(term in clause for term in ("成交额", "成交金额"))
                        and re.search(r"\d", clause)
                        for clause in answer_clauses
                    )
                ):
                    semantic_conflicts.append(
                        "用户明确询问成交额时必须引用可用的全市场成交额"
                    )
                turnover_market_date = str(market_breadth.get("market_date") or "")
                if (
                    turnover_available
                    and "成交额" in user_question
                    and any(
                        term in user_question
                        for term in ("证据时间", "数据时间", "日期", "哪天", "时点")
                    )
                    and turnover_market_date
                    and not AgentOutputGuard._answer_mentions_market_date(
                        answer, turnover_market_date
                    )
                ):
                    semantic_conflicts.append("全市场成交额时间必须引用市场快照日期")
                if turnover_available and re.search(
                    r"(?:全市场)?成交额[^。；\n]{0,50}"
                    r"(?:未|没有|缺少)[^。；\n]{0,24}(?:市场)?(?:日期|时间|时点)",
                    answer,
                ):
                    unsupported_market_inferences.append(
                        "已有全市场快照日期时不能声称成交额日期缺失"
                    )
                if (
                    distribution_available
                    and any(
                        term in user_question
                        for term in ("涨跌幅分布", "涨幅分布", "个股分布")
                    )
                    and not any(
                        any(
                            term in clause
                            for term in ("中位数", "四分位", "分档", "上涨至少")
                        )
                        and re.search(r"\d", clause)
                        for clause in answer_clauses
                    )
                ):
                    semantic_conflicts.append(
                        "用户明确询问涨跌幅分布时必须引用可用的分布统计"
                    )
                if distribution_available and _AVAILABLE_DISTRIBUTION_MISSING_RE.search(
                    answer
                ):
                    unsupported_market_inferences.append(
                        "已有全市场个股涨跌幅分布时不能声称该数据缺失"
                    )
                if turnover_available and _AVAILABLE_TURNOVER_MISSING_RE.search(answer):
                    unsupported_market_inferences.append(
                        "已有全市场成交额时不能声称该数据缺失"
                    )
            if (evidence.get("market_drivers") or {}).get(
                "items"
            ) and _AVAILABLE_MARKET_DRIVERS_MISSING_RE.search(answer):
                unsupported_market_inferences.append(
                    "已有市场资讯时不能声称消息面驱动资讯缺失"
                )
            if _has_available_index_return_missing_claim(answer, market_indices):
                unsupported_market_inferences.append(
                    "已有指数区间收益时不能声称该字段缺失"
                )
            trend_states = [
                str(item.get("metrics", {}).get("trend_state") or "")
                for item in market_indices
            ]
            if not any(
                term in state
                for state in trend_states
                for term in ("下行", "向下", "下降")
            ) and _has_unproven_downtrend_claim(answer):
                unsupported_market_inferences.append(
                    "中期偏弱不能直接改写为已确认的下行趋势"
                )
            available_indices = [
                item for item in market_indices if item.get("status") != "unavailable"
            ]
            for match in _REPRESENTATIVE_INDEX_COUNT_RE.finditer(answer):
                if int(match.group(1)) != len(available_indices):
                    unsupported_market_inferences.append(
                        "代表性指数数量与当前问题证据不一致"
                    )
                    break
            if _APPROX_REPRESENTATIVE_INDEX_COUNT_RE.search(answer):
                unsupported_market_inferences.append(
                    "代表性指数数量与当前问题证据不一致"
                )
            if _SINGLE_INDEX_ADVANCE_RATIO_RE.search(answer):
                unsupported_market_inferences.append(
                    "代表性指数上涨比例不能归到单一指数名下"
                )
            available_metric_keys = {
                key for item in available_indices for key in (item.get("metrics") or {})
            }
            if "ma5" not in available_metric_keys and _UNAVAILABLE_MA5_RE.search(
                answer
            ):
                unsupported_market_inferences.append("当前证据没有MA5或5日均线")
            if _UNSUPPORTED_WAVE_RE.search(answer):
                unsupported_market_inferences.append(
                    "当前证据不支持A浪B浪C浪等浪型判断"
                )
            if _has_wrong_index_return_extreme_claim(answer, available_indices):
                unsupported_market_inferences.append(
                    "指数领涨领跌或最大涨跌幅必须与当前证据排序一致"
                )
            if _has_unavailable_index_return_claim(answer, market_indices):
                unsupported_market_inferences.append(
                    "缺失收益的指数不能引用其他指数的涨跌幅"
                )
            if _has_index_return_direction_conflict(answer, market_indices):
                unsupported_market_inferences.append(
                    "指数区间收益正负方向必须与当前证据一致"
                )
            if _has_index_trend_state_conflict(answer, market_indices):
                unsupported_market_inferences.append("指数趋势状态必须与当前证据一致")
            if _has_wrong_index_volatility_extreme_claim(answer, available_indices):
                unsupported_market_inferences.append(
                    "指数波动率最高最低表述必须与当前证据排序一致"
                )
            if _has_mismatched_major_index_count(answer, available_indices):
                unsupported_market_inferences.append(
                    "三大指数表述不能与四个代表性指数混用"
                )
            if _has_moving_average_status_conflict(answer, available_indices):
                unsupported_market_inferences.append(
                    "均线是否跌破的表述必须与最新收盘和均线位置一致"
                )
            user_question = str(evidence.get("user_question") or "")
            if market_state.get("whole_market_breadth_available") is True and any(
                term in user_question
                for term in (
                    "固定分类",
                    "涨跌家数",
                    "上涨家数",
                    "下跌家数",
                )
            ):
                normalized_answer = answer.replace(",", "")
                breadth_state = str(
                    market_state.get("whole_market_breadth_state") or ""
                )
                required_counts = [
                    market_state.get("whole_market_advancers"),
                    market_state.get("whole_market_decliners"),
                ]
                if any(term in user_question for term in ("平盘", "不涨不跌")):
                    required_counts.append(market_state.get("whole_market_unchanged"))
                if (
                    not breadth_state
                    or breadth_state not in answer
                    or any(
                        isinstance(value, int) and str(value) not in normalized_answer
                        for value in required_counts
                    )
                ):
                    unsupported_market_inferences.append(
                        "用户询问全市场广度时回答必须给出涨跌家数和固定分类"
                    )
            if _asks_for_reassessment_conditions(
                user_question
            ) and not _answer_explains_reassessment_conditions(answer):
                unsupported_market_inferences.append(_REASSESSMENT_REQUIRED_LABEL)
            if "不能确认" in user_question and not any(
                term in answer
                for term in (
                    "不能确认",
                    "无法确认",
                    "尚不能确认",
                    "尚不能",
                    "未能确认",
                    "尚未能确认",
                    "不能判断",
                    "无法判断",
                    "有待确认",
                    "有待核验",
                    "尚待确认",
                    "不能解读为",
                    "无法解读为",
                    "证据边界",
                )
            ):
                unsupported_market_inferences.append(
                    "用户明确询问不能确认的部分时回答必须保留证据边界"
                )
            if _market_cause_fact_required_but_missing(answer, evidence):
                semantic_conflicts.append(_MARKET_CAUSE_FACT_REQUIRED_LABEL)
        if (
            evidence.get("type") != "market_brief"
            and evidence.get("symbol")
            and _has_unsupported_stock_failure_threshold(answer, evidence)
        ):
            unsupported_market_inferences.append(_STOCK_FAILURE_THRESHOLD_LABEL)
        if (
            evidence.get("type") != "market_brief"
            and (evidence.get("symbol") or evidence.get("type") == "stock_screen")
            and _has_unsupported_stock_observation_window(answer, evidence)
        ):
            unsupported_market_inferences.append(_STOCK_OBSERVATION_WINDOW_LABEL)
        if _has_li_zong_rule_bottleneck_overclaim(answer, evidence):
            unsupported_market_inferences.append(_LI_ZONG_RULE_BOTTLENECK_LABEL)
        if _has_li_zong_coverage_conflation(answer, evidence):
            unsupported_market_inferences.append(_LI_ZONG_COVERAGE_CONFLATION_LABEL)
        if _has_stock_screen_scope_overclaim(answer, evidence):
            unsupported_market_inferences.append(_STOCK_SCREEN_SCOPE_OVERCLAIM_LABEL)
        if _has_stock_screen_candidate_count_conflict(answer, evidence):
            unsupported_market_inferences.append(_STOCK_SCREEN_CANDIDATE_COUNT_LABEL)
        if (
            evidence.get("type") != "market_brief"
            and evidence.get("symbol")
            and _has_unsupported_stock_disclosure_date(answer, evidence)
        ):
            unsupported_market_inferences.append(_STOCK_DISCLOSURE_DATE_LABEL)
        if (
            evidence.get("type") != "market_brief"
            and evidence.get("symbol")
            and _has_stock_report_notice_date_conflict(answer, evidence)
        ):
            unsupported_market_inferences.append(_STOCK_REPORT_DATE_CONFLICT_LABEL)
        if (
            evidence.get("type") != "market_brief"
            and evidence.get("symbol")
            and _has_stock_drawdown_window_conflict(answer, evidence)
        ):
            unsupported_market_inferences.append(_STOCK_DRAWDOWN_WINDOW_LABEL)
        if (
            evidence.get("type") != "market_brief"
            and evidence.get("symbol")
            and _has_stock_scenario_direction_conflict(answer)
        ):
            unsupported_market_inferences.append(_STOCK_SCENARIO_DIRECTION_LABEL)
        if evidence.get("type") != "market_brief" and evidence.get("symbol"):
            (
                current_quote_direction_conflict,
                current_quote_price_conflict,
            ) = _stock_current_quote_conflicts(answer, evidence)
            if current_quote_direction_conflict:
                unsupported_market_inferences.append(
                    _STOCK_CURRENT_QUOTE_DIRECTION_LABEL
                )
            if current_quote_price_conflict:
                unsupported_market_inferences.append(_STOCK_CURRENT_QUOTE_PRICE_LABEL)
            if _stock_current_quote_close_conflict(answer, evidence):
                unsupported_market_inferences.append(_STOCK_CURRENT_QUOTE_CLOSE_LABEL)
            if _stock_current_quote_session_conflict(answer, evidence):
                unsupported_market_inferences.append(_STOCK_CURRENT_QUOTE_SESSION_LABEL)
            if _stock_current_quote_ma20_conflict(answer, evidence):
                unsupported_market_inferences.append(_STOCK_CURRENT_QUOTE_MA20_LABEL)
            if _stock_current_limit_status_conflict(answer, evidence):
                unsupported_market_inferences.append(_STOCK_CURRENT_LIMIT_STATUS_LABEL)
            if _stock_current_quote_required_but_missing(answer, evidence):
                unsupported_market_inferences.append(
                    _STOCK_CURRENT_QUOTE_REQUIRED_LABEL
                )
            if _has_stock_cross_date_market_claim(answer, evidence):
                unsupported_market_inferences.append(_STOCK_CROSS_DATE_MARKET_LABEL)
            if _has_stock_industry_breadth_overclaim(answer, evidence):
                unsupported_market_inferences.append(_STOCK_INDUSTRY_BREADTH_LABEL)
            if _has_stock_60d_return_binding_conflict(answer, evidence):
                unsupported_market_inferences.append(_STOCK_60D_RETURN_BINDING_LABEL)
            if _has_stock_debt_ratio_scale_conflict(answer, evidence):
                unsupported_market_inferences.append(_STOCK_DEBT_RATIO_SCALE_LABEL)
            if _has_stock_cashflow_causal_conflict(answer, evidence):
                unsupported_market_inferences.append(_STOCK_CASHFLOW_CAUSE_LABEL)
            if _has_stock_static_financial_causal_overclaim(answer, evidence):
                unsupported_market_inferences.append(
                    _STOCK_STATIC_FINANCIAL_CAUSAL_LABEL
                )
            if _has_stock_industry_causal_overclaim(answer):
                unsupported_market_inferences.append(_STOCK_INDUSTRY_CAUSAL_LABEL)
            if _has_stock_market_absorption_overclaim(answer):
                unsupported_market_inferences.append(_STOCK_MARKET_ABSORPTION_LABEL)
            if _has_stock_event_sentiment_overclaim(answer):
                unsupported_market_inferences.append(_STOCK_EVENT_SENTIMENT_LABEL)
            if _has_stock_sentiment_exclusion_overclaim(answer, evidence):
                unsupported_market_inferences.append(
                    _STOCK_SENTIMENT_EXCLUSION_LABEL
                )
            if _has_stock_unsupported_causal_hypothesis(answer, evidence):
                unsupported_market_inferences.append(
                    _STOCK_UNSUPPORTED_CAUSAL_HYPOTHESIS_LABEL
                )
            if _stock_contribution_required_but_missing(answer, evidence):
                semantic_conflicts.append(_STOCK_CONTRIBUTION_REQUIRED_LABEL)
            if _stock_industry_counts_required_but_missing(answer, evidence):
                semantic_conflicts.append(_STOCK_INDUSTRY_COUNTS_REQUIRED_LABEL)
            if _stock_component_source_boundary_required_but_missing(answer, evidence):
                semantic_conflicts.append(_STOCK_COMPONENT_SOURCE_BOUNDARY_LABEL)
        if (
            evidence.get("type") != "market_brief"
            and evidence.get("symbol")
            and _asks_for_reassessment_conditions(evidence.get("user_question"))
            and not _answer_explains_reassessment_conditions(answer)
        ):
            unsupported_market_inferences.append(_REASSESSMENT_REQUIRED_LABEL)
        peer_operating = (evidence.get("peer_comparison") or {}).get(
            "operating_comparison"
        ) or {}
        if peer_operating:
            if AgentOutputGuard._peer_net_profit_unit_replacements(answer, evidence):
                unsupported_market_inferences.append(
                    "同行净利润亿元换算必须与结构化财务一致"
                )
            business_dates = []
            notice_dates = []
            subject_profile = (peer_operating.get("subject") or {}).get(
                "business_profile"
            ) or {}
            subject_financial = (peer_operating.get("subject") or {}).get(
                "financial"
            ) or {}
            if subject_financial.get("notice_date"):
                notice_dates.append(subject_financial["notice_date"])
            if subject_profile.get("anchor_report_date"):
                business_dates.append(subject_profile["anchor_report_date"])
            for peer in peer_operating.get("peers") or []:
                profile = peer.get("business_profile") or {}
                financial = peer.get("financial") or {}
                if financial.get("notice_date"):
                    notice_dates.append(financial["notice_date"])
                if profile.get("anchor_report_date"):
                    business_dates.append(profile["anchor_report_date"])
            same_business_period = (
                bool(business_dates) and len(set(business_dates)) == 1
            )
            distinct_notice_dates = len(set(notice_dates)) > 1
            for label, pattern in _UNSUPPORTED_PEER_OPERATING_INFERENCE_PATTERNS:
                if (
                    label == "主营构成报告期必须与证据逐家公司一致"
                    and not same_business_period
                ):
                    continue
                if (
                    label == "同行公告日期不能用单一日期概括"
                    and not distinct_notice_dates
                ):
                    continue
                if any(
                    pattern.search(clause) and not _is_index_contribution_clause(clause)
                    for clause in re.split(r"[。；\n]", answer)
                ):
                    unsupported_market_inferences.append(label)
        if evidence.get("type") == "shareholder_structure" or evidence.get(
            "shareholder_structure"
        ):
            shareholder_evidence = (
                evidence
                if evidence.get("type") == "shareholder_structure"
                else evidence.get("shareholder_structure") or {}
            )
            unsupported_market_inferences.extend(
                label
                for label, pattern in _UNSUPPORTED_SHAREHOLDER_INFERENCE_PATTERNS
                if _has_unsupported_shareholder_inference(answer, pattern)
            )
            expected_streak = shareholder_evidence.get("holder_count_streak_count")
            expected_direction = shareholder_evidence.get(
                "holder_count_streak_direction"
            )
            if isinstance(expected_streak, int) and expected_direction in {
                "decrease",
                "increase",
            }:
                for match in _SHAREHOLDER_STREAK_CLAIM_RE.finditer(answer):
                    claimed_count = int(match.group(1))
                    claimed_direction = (
                        "decrease" if match.group(2) in {"下降", "减少"} else "increase"
                    )
                    if (
                        claimed_count != expected_streak
                        or claimed_direction != expected_direction
                    ):
                        unsupported_market_inferences.append(
                            "股东户数连续变化次数或方向与确定性证据不一致"
                        )
                        break
            if shareholder_evidence.get(
                "top10_historical_comparison_available"
            ) is False and _TOP10_HISTORICAL_COMPARISON_RE.search(answer):
                unsupported_market_inferences.append(
                    "缺少历史十大股东合计序列时不能声称前十持股跨期持平或变化"
                )
        if evidence.get("type") == "analyst_expectations" or evidence.get(
            "analyst_expectations"
        ):
            revision = analyst_evidence.get("revision") or {}
            if revision.get(
                "available"
            ) is not True and _has_unproven_analyst_revision_claim(answer):
                unsupported_market_inferences.append(
                    "缺少历史一致预期快照时不能声称EPS已经上修或下修"
                )
        return {
            "passed": not prohibited
            and not private_operational
            and not unsupported
            and not semantic_conflicts
            and not unsupported_market_inferences,
            "prohibited_patterns": prohibited,
            "private_operational_patterns": private_operational,
            "unsupported_numbers": unsupported,
            "unsupported_number_contexts": unsupported_contexts[:12],
            "semantic_conflicts": semantic_conflicts,
            "unsupported_market_inferences": unsupported_market_inferences,
            "method": "deterministic_numeric_and_policy_guard_v2",
        }

    @staticmethod
    def _peer_net_profit_unit_replacements(
        answer: str, evidence: dict[str, Any]
    ) -> list[tuple[int, int, str]]:
        peer_operating = (evidence.get("peer_comparison") or {}).get(
            "operating_comparison"
        ) or {}
        rows = [
            peer_operating.get("subject") or {},
            *(peer_operating.get("peers") or []),
        ]
        replacements: list[tuple[int, int, str]] = []
        occupied: set[tuple[int, int]] = set()
        for item in rows:
            financial = item.get("financial") or {}
            raw_profit = financial.get("parent_net_profit")
            name = str(item.get("name") or financial.get("name") or "").strip()
            if not name or not isinstance(raw_profit, (int, float)):
                continue
            expected = float(raw_profit) / 100_000_000
            aliases = [name]
            if len(name) >= 2:
                aliases.append(name[:2])
            alias_pattern = "|".join(
                re.escape(alias)
                for alias in sorted(set(aliases), key=len, reverse=True)
            )
            patterns = (
                re.compile(
                    rf"(?:{alias_pattern})[^。；\n]{{0,50}}?净利润"
                    rf"(?:也)?(?:仍为正数)?(?:基数)?(?:仅|约)?(?:为|是)?\s*[（(]?\s*"
                    rf"(?P<value>[-+]?\d+(?:\.\d+)?)\s*亿(?:元|美元)"
                ),
            )
            for pattern in patterns:
                for match in pattern.finditer(answer):
                    value_match = match.span("value")
                    if value_match in occupied:
                        continue
                    claimed = float(match.group("value"))
                    if abs(claimed - expected) <= max(0.02, abs(expected) * 0.01):
                        continue
                    replacement = f"{expected:.2f}".rstrip("0").rstrip(".")
                    replacements.append((*value_match, replacement))
                    occupied.add(value_match)
        return sorted(replacements, key=lambda item: item[0])

    @staticmethod
    def _is_percentage_range_endpoint(answer: str, match: re.Match[str]) -> bool:
        if not match.group(0).endswith("%"):
            return False
        left = answer[max(0, match.start() - 16) : match.start()]
        right = answer[match.end() : min(len(answer), match.end() + 16)]
        range_separator = r"\s*(?:—|–|~|～|至|到)\s*"
        return bool(
            re.search(rf"%{range_separator}$", left)
            or re.match(rf"^{range_separator}[-+]?\d+(?:\.\d+)?%", right)
        )

    @staticmethod
    def _is_breadth_share_percentage(answer: str, match: re.Match[str]) -> bool:
        if not match.group(0).endswith("%"):
            return False
        left = answer[max(0, match.start() - 40) : match.start()]
        right = answer[match.end() : min(len(answer), match.end() + 8)]
        if bool(
            re.search(
                r"\d[\d,]*\s*(?:家|只)\s*[（(]\s*"
                r"(?:(?:占比|占|比例)\s*)?$",
                left,
            )
            and re.match(r"^\s*[）)]", right)
        ):
            return True
        if re.search(
            r"(?:上涨|下跌|平盘)(?:方向|家数)?(?:占比|比例)"
            r"\s*(?:约|为|是|达到)?\s*$",
            left,
        ):
            return True
        if re.search(
            r"(?:上涨|下跌|平盘)[^。；\n]{0,20}"
            r"(?:占比|比例|占)[^。；\n]{0,14}$",
            left,
        ):
            return True
        if re.match(
            r"^\s*(?:的)?(?:有效样本|成分股?|家数)?[^。；\n]{0,10}"
            r"(?:上涨|下跌|平盘)",
            right,
        ):
            return True
        if re.search(
            r"(?:全市场|全A股|A股|股票|上涨的|下跌的)[^。；\n]{0,36}$",
            left,
        ) and re.match(r"^\s*(?:涨|跌)(?:[、，,）)])?", right):
            return True
        return bool(
            re.search(
                r"(?:上涨|下跌|平盘)(?:家数)?(?:占比|比例)[^。；\n]{0,36}"
                r"[、，,]\s*(?:上涨|下跌|平盘)(?:家数)?\s*(?:约|为|是)?\s*$",
                left,
            )
        )

    @staticmethod
    def _answer_mentions_market_date(answer: str, market_date: str) -> bool:
        if market_date in answer:
            return True
        try:
            parsed = datetime.strptime(market_date, "%Y-%m-%d")
        except ValueError:
            return False
        normalized = re.sub(r"\s+", "", answer)
        variants = (
            f"{parsed.year}年{parsed.month}月{parsed.day}日",
            f"{parsed.year}/{parsed.month}/{parsed.day}",
            f"{parsed.month}月{parsed.day}日",
        )
        return any(item in normalized for item in variants)

    @staticmethod
    def _is_evidenced_breadth_threshold(
        answer: str,
        match: re.Match[str],
        evidence: dict[str, Any],
    ) -> bool:
        classification_method = str(
            (
                ((evidence.get("market_breadth") or {}).get("breadth") or {}).get(
                    "classification_method"
                )
            )
            or ""
        )
        if not classification_method:
            return False
        nearby = answer[max(0, match.start() - 80) : min(len(answer), match.end() + 80)]
        if not any(term in nearby for term in ("固定分类", "普涨", "普跌")):
            return False
        claim_values = {
            abs(value)
            for token in _NUMBER_RE.findall(match.group(0))
            if (value := AgentOutputGuard._parse_number(token)) is not None
        }
        method_values = {
            abs(value) for value in AgentOutputGuard._numeric_values(classification_method)
        }
        return bool(claim_values) and claim_values.issubset(method_values)

    @staticmethod
    def _repair_trade_review_json_guard_failure(
        answer: str,
        evidence: dict[str, Any],
        guard: dict[str, Any],
        trusted_context: list[str] | None = None,
    ) -> tuple[str, dict[str, Any]] | None:
        """Keep a useful structured review when only a few numeric clauses fail.

        Trade-review answers are intentionally one JSON line, so the generic
        line-based repair would otherwise discard the entire model response.
        Remove only clauses containing unsupported numbers, then re-run the
        same deterministic guard before accepting the repaired JSON.
        """

        if evidence.get("type") != "trade_review":
            return None
        unsupported = [
            str(item).strip()
            for item in (guard.get("unsupported_numbers") or [])
            if str(item).strip()
        ]
        if not unsupported:
            return None
        if any(
            guard.get(key)
            for key in (
                "prohibited_patterns",
                "private_operational_patterns",
                "semantic_conflicts",
                "unsupported_market_inferences",
            )
        ):
            return None
        try:
            payload = json.loads(answer)
        except (json.JSONDecodeError, TypeError):
            return None
        if not isinstance(payload, dict):
            return None
        expected = {
            "logic_result",
            "plan_deviation",
            "bias_tags",
            "improvement_text",
        }
        if not expected.issubset(payload):
            return None

        removed = 0

        def clean_text(value: Any) -> str:
            nonlocal removed
            text = str(value or "").strip()
            if not text:
                return ""
            clauses = re.split(r"(?<=[。！？；])|\n+", text)
            kept: list[str] = []
            for clause in clauses:
                stripped = clause.strip()
                if not stripped:
                    continue
                if any(token in stripped for token in unsupported):
                    removed += 1
                    continue
                kept.append(stripped)
            return "".join(kept).strip()

        repaired_payload = dict(payload)
        for key in ("logic_result", "plan_deviation", "improvement_text"):
            repaired_payload[key] = clean_text(payload.get(key))
        bias_tags = payload.get("bias_tags")
        if not isinstance(bias_tags, list):
            return None
        repaired_payload["bias_tags"] = [
            str(item).strip() for item in bias_tags if str(item).strip()
        ][:3]
        if not removed or not repaired_payload["logic_result"]:
            return None

        repaired = json.dumps(
            repaired_payload, ensure_ascii=False, separators=(",", ":")
        )
        repaired_guard = AgentOutputGuard._validate_model_output(
            repaired,
            evidence,
            trusted_context=trusted_context,
        )
        if not repaired_guard["passed"]:
            return None
        return repaired, repaired_guard

    @staticmethod
    def _repair_guard_failure(
        answer: str,
        evidence: dict[str, Any],
        guard: dict[str, Any],
        trusted_context: list[str] | None = None,
    ) -> tuple[str, dict[str, Any]] | None:
        unsupported = set(guard.get("unsupported_numbers") or [])
        unsupported_market_inferences = set(
            guard.get("unsupported_market_inferences") or []
        )
        private_operational = list(guard.get("private_operational_patterns") or [])
        semantic_conflicts = list(guard.get("semantic_conflicts") or [])
        prohibited = list(guard.get("prohibited_patterns") or [])
        repairable_semantic_conflicts = {
            _STOCK_CONTRIBUTION_REQUIRED_LABEL,
            _STOCK_INDUSTRY_COUNTS_REQUIRED_LABEL,
            _STOCK_COMPONENT_SOURCE_BOUNDARY_LABEL,
            _MARKET_CAUSE_FACT_REQUIRED_LABEL,
        }
        has_repairable_semantic_conflicts = bool(semantic_conflicts) and set(
            semantic_conflicts
        ).issubset(repairable_semantic_conflicts)
        appendices: list[str | None] = []
        quote_fact_added = False
        if _STOCK_CURRENT_QUOTE_REQUIRED_LABEL in unsupported_market_inferences:
            quote_fact = AgentOutputGuard._stock_current_quote_fact(evidence)
            if quote_fact is None:
                return None
            answer = f"{quote_fact}\n\n{answer.lstrip()}"
            unsupported_market_inferences.discard(
                _STOCK_CURRENT_QUOTE_REQUIRED_LABEL
            )
            quote_fact_added = True
        if has_repairable_semantic_conflicts:
            if _STOCK_INDUSTRY_COUNTS_REQUIRED_LABEL in semantic_conflicts:
                appendices.append(
                    AgentOutputGuard._stock_industry_counts_appendix(evidence)
                )
            if _STOCK_CONTRIBUTION_REQUIRED_LABEL in semantic_conflicts:
                appendices.append(
                    AgentOutputGuard._stock_component_contribution_appendix(evidence)
                )
            if _STOCK_COMPONENT_SOURCE_BOUNDARY_LABEL in semantic_conflicts:
                appendices.append(
                    AgentOutputGuard._stock_component_source_boundary_appendix(evidence)
                )
            if _MARKET_CAUSE_FACT_REQUIRED_LABEL in semantic_conflicts:
                appendices.append(AgentOutputGuard._market_cause_facts_appendix(evidence))
            if any(not appendix for appendix in appendices):
                return None
        if (
            has_repairable_semantic_conflicts
            and not unsupported
            and not unsupported_market_inferences
            and not private_operational
            and not prohibited
        ):
            repaired = (
                f"{answer.rstrip()}\n\n"
                + "\n\n".join(str(appendix) for appendix in appendices)
            ).strip()
            repaired_guard = AgentOutputGuard._validate_model_output(
                repaired,
                evidence,
                trusted_context=trusted_context,
            )
            if not repaired_guard["passed"]:
                return None
            return repaired, repaired_guard
        if (
            (
                not unsupported
                and not unsupported_market_inferences
                and not private_operational
                and not semantic_conflicts
                and not quote_fact_added
            )
            or prohibited
            or (semantic_conflicts and not has_repairable_semantic_conflicts)
        ):
            return None

        removed_count = 0
        unit_corrected = False
        if "同行净利润亿元换算必须与结构化财务一致" in unsupported_market_inferences:
            replacements = AgentOutputGuard._peer_net_profit_unit_replacements(
                answer, evidence
            )
            for start, end, replacement in reversed(replacements):
                answer = answer[:start] + replacement + answer[end:]
            removed_count += len(replacements)
            unit_corrected = bool(replacements)
        peer_clause_patterns = [
            pattern
            for label, pattern in _UNSUPPORTED_PEER_OPERATING_INFERENCE_PATTERNS
            if label in unsupported_market_inferences
        ]
        if peer_clause_patterns:
            sanitized_lines = []
            for line in answer.splitlines():
                clauses = re.split(r"(?<=[。！？；])", line)
                kept_clauses = []
                for clause in clauses:
                    if any(
                        pattern.search(clause)
                        and not _is_index_contribution_clause(clause)
                        for pattern in peer_clause_patterns
                    ):
                        removed_count += 1
                        continue
                    kept_clauses.append(clause)
                sanitized_lines.append("".join(kept_clauses))
            answer = "\n".join(sanitized_lines)

        surgical_market_labels = {
            _MARKET_NEWS_CAUSAL_LABEL,
            _MARKET_TECHNICAL_REPAIR_CAUSAL_LABEL,
            _MARKET_STYLE_GAP_STORY_LABEL,
            _MARKET_NEW_CATALYST_GATE_LABEL,
        }
        market_clause_patterns = [
            (label, pattern)
            for label, pattern in _UNSUPPORTED_MARKET_INFERENCE_PATTERNS
            if label in unsupported_market_inferences
            and label in surgical_market_labels
        ]
        if market_clause_patterns:
            sanitized_lines = []
            removed_labels: set[str] = set()
            for line in answer.splitlines():
                clauses = re.split(r"(?<=[。！？；])", line)
                kept_clauses = []
                for clause in clauses:
                    matched_label = next(
                        (
                            label
                            for label, pattern in market_clause_patterns
                            if pattern.search(clause)
                        ),
                        None,
                    )
                    if matched_label is not None:
                        removed_count += 1
                        removed_labels.add(matched_label)
                        continue
                    kept_clauses.append(clause)
                sanitized_lines.append("".join(kept_clauses))
            answer = "\n".join(sanitized_lines)
            unsupported_market_inferences.difference_update(removed_labels)

        if _STOCK_CROSS_DATE_MARKET_LABEL in unsupported_market_inferences:
            section_heading = re.compile(r"^\s*(?:#{1,6}\s+.+|\*\*.+\*\*)\s*$")
            sanitized_lines = []
            dropping_cross_date_section = False
            for line in answer.splitlines():
                stripped = line.strip()
                is_heading = bool(section_heading.match(stripped))
                if is_heading and re.search(
                    r"(?:全市场广度|全市场成交额|全A股)",
                    stripped,
                ):
                    dropping_cross_date_section = True
                    removed_count += 1
                    continue
                if dropping_cross_date_section and is_heading:
                    dropping_cross_date_section = False
                if dropping_cross_date_section:
                    removed_count += 1
                    continue
                sanitized_lines.append(line)
            answer = "\n".join(sanitized_lines)

            sanitized_lines = []
            for line in answer.splitlines():
                clauses = re.split(r"(?<=[。！？；])", line)
                kept_clauses = []
                for clause in clauses:
                    if _has_stock_cross_date_market_claim(clause, evidence):
                        removed_count += 1
                        continue
                    kept_clauses.append(clause)
                sanitized_lines.append("".join(kept_clauses))
            answer = "\n".join(sanitized_lines)

        industry_boundary_added = False
        sentiment_boundary_added = False
        for label, predicate in (
            (
                _STOCK_INDUSTRY_CAUSAL_LABEL,
                _has_stock_industry_causal_overclaim,
            ),
            (
                _STOCK_MARKET_ABSORPTION_LABEL,
                _has_stock_market_absorption_overclaim,
            ),
            (
                _STOCK_EVENT_SENTIMENT_LABEL,
                _has_stock_event_sentiment_overclaim,
            ),
            (
                _STOCK_SENTIMENT_EXCLUSION_LABEL,
                lambda text: _has_stock_sentiment_exclusion_overclaim(
                    text, evidence
                ),
            ),
            (
                _STOCK_UNSUPPORTED_CAUSAL_HYPOTHESIS_LABEL,
                lambda text: _has_stock_unsupported_causal_hypothesis(text, evidence),
            ),
            (
                _STOCK_DEBT_RATIO_SCALE_LABEL,
                lambda text: _has_stock_debt_ratio_scale_conflict(text, evidence),
            ),
            (
                _STOCK_CASHFLOW_CAUSE_LABEL,
                lambda text: _has_stock_cashflow_causal_conflict(text, evidence),
            ),
            (
                _STOCK_STATIC_FINANCIAL_CAUSAL_LABEL,
                lambda text: _has_stock_static_financial_causal_overclaim(
                    text, evidence
                ),
            ),
        ):
            if label not in unsupported_market_inferences:
                continue
            sanitized_lines = []
            for line in answer.splitlines():
                clauses = re.split(r"(?<=[。！？；])", line)
                kept_clauses = []
                for clause in clauses:
                    if predicate(clause):
                        removed_count += 1
                        if label == _STOCK_INDUSTRY_CAUSAL_LABEL:
                            factual_prefix = re.split(
                                r"(?:，|,)?(?:说明|表明|意味着|因此|核心(?:是|在于)?)",
                                clause,
                                maxsplit=1,
                            )[0].strip()
                            if (
                                factual_prefix
                                and re.search(r"\d", factual_prefix)
                                and any(
                                    term in factual_prefix
                                    for term in ("行业", "板块")
                                )
                            ):
                                kept_clauses.append(
                                    factual_prefix.rstrip("，,") + "。"
                                )
                                if not industry_boundary_added:
                                    kept_clauses.append(
                                        "这只能说明个股与行业的同步或相对表现，"
                                        "不能单独确认个股涨跌的直接原因。"
                                    )
                                    industry_boundary_added = True
                        elif label == _STOCK_SENTIMENT_EXCLUSION_LABEL:
                            factual_prefix = re.split(
                                r"(?:，|,)?(?:而)?(?:市场)?情绪(?:面)?"
                                r"[^，。；]{0,12}(?:并无|没有|未有)明确"
                                r"(?:方向|指向)|"
                                r"(?:，|,)?(?:并没有|并未|所以|因此|这说明|意味着)",
                                clause,
                                maxsplit=1,
                            )[0].strip()
                            if factual_prefix and any(
                                term in factual_prefix
                                for term in ("社区", "样本", "中性", "混合")
                            ):
                                kept_clauses.append(
                                    factual_prefix.rstrip("，,") + "。"
                                )
                            if not sentiment_boundary_added:
                                kept_clauses.append(
                                    "这只说明本轮社区样本的方向分布，"
                                    "不能排除未被样本捕捉的情绪影响。"
                                )
                                sentiment_boundary_added = True
                        continue
                    kept_clauses.append(clause)
                sanitized_lines.append("".join(kept_clauses))
            answer = "\n".join(sanitized_lines)

        kept_lines = []
        for line in answer.splitlines():
            line_tokens = {match.group(0) for match in _NUMBER_RE.finditer(line)}
            line_has_unsupported_inference = any(
                label in unsupported_market_inferences
                and pattern.search(line)
                and (
                    label
                    != "证据包没有给出阈值时不能发明量能或回撤验证门槛"
                    or any(
                        term in line
                        for term in (
                            "后续",
                            "未来",
                            "接下来",
                            "至少",
                            "维持",
                            "扩大至",
                            "跌至",
                            "升至",
                            "如果",
                            "一旦",
                            "才",
                            "方",
                            "确认",
                            "有效",
                            "视为",
                        )
                    )
                )
                for label, pattern in (
                    *_UNSUPPORTED_MARKET_INFERENCE_PATTERNS,
                    *_UNSUPPORTED_PEER_OPERATING_INFERENCE_PATTERNS,
                )
            )
            line_has_unsupported_inference = line_has_unsupported_inference or any(
                label in unsupported_market_inferences
                and _has_unsupported_shareholder_inference(line, pattern)
                for label, pattern in _UNSUPPORTED_SHAREHOLDER_INFERENCE_PATTERNS
            )
            line_has_unsupported_inference = line_has_unsupported_inference or (
                "缺少全市场涨跌家数时不能确认是否普涨" in unsupported_market_inferences
                and _has_whole_market_breadth_overclaim(line, evidence)
            )
            line_has_unsupported_inference = line_has_unsupported_inference or (
                "缺少同日全市场广度时不能声称多数个股涨跌"
                in unsupported_market_inferences
                and _has_unsupported_majority_stock_claim(line)
            )
            line_has_unsupported_inference = line_has_unsupported_inference or (
                "全市场广度结论必须沿用固定分类" in unsupported_market_inferences
                and (
                    _has_uncautious_breadth_label(line, "普涨")
                    or _has_uncautious_breadth_label(line, "普跌")
                )
            )
            line_has_unsupported_inference = line_has_unsupported_inference or (
                "固定广度分类和热门板块不能直接确认结构性行情"
                in unsupported_market_inferences
                and _has_uncautious_structural_market_claim(line)
            )
            line_has_unsupported_inference = line_has_unsupported_inference or (
                "已有全市场个股涨跌幅分布时不能声称该数据缺失"
                in unsupported_market_inferences
                and _AVAILABLE_DISTRIBUTION_MISSING_RE.search(line)
            )
            line_has_unsupported_inference = line_has_unsupported_inference or (
                "已有全市场成交额时不能声称该数据缺失" in unsupported_market_inferences
                and _AVAILABLE_TURNOVER_MISSING_RE.search(line)
            )
            line_has_unsupported_inference = line_has_unsupported_inference or (
                "已有市场资讯时不能声称消息面驱动资讯缺失"
                in unsupported_market_inferences
                and _AVAILABLE_MARKET_DRIVERS_MISSING_RE.search(line)
            )
            line_has_unsupported_inference = line_has_unsupported_inference or (
                "已有指数区间收益时不能声称该字段缺失" in unsupported_market_inferences
                and _has_available_index_return_missing_claim(
                    line, list(evidence.get("indices") or [])
                )
            )
            line_has_unsupported_inference = line_has_unsupported_inference or (
                "中期偏弱不能直接改写为已确认的下行趋势"
                in unsupported_market_inferences
                and _has_unproven_downtrend_claim(line)
            )
            line_has_unsupported_inference = line_has_unsupported_inference or (
                "代表性指数数量与当前问题证据不一致" in unsupported_market_inferences
                and (
                    _REPRESENTATIVE_INDEX_COUNT_RE.search(line)
                    or _APPROX_REPRESENTATIVE_INDEX_COUNT_RE.search(line)
                )
            )
            line_has_unsupported_inference = line_has_unsupported_inference or (
                "代表性指数上涨比例不能归到单一指数名下"
                in unsupported_market_inferences
                and _SINGLE_INDEX_ADVANCE_RATIO_RE.search(line)
            )
            line_has_unsupported_inference = line_has_unsupported_inference or (
                "当前证据没有MA5或5日均线" in unsupported_market_inferences
                and _UNAVAILABLE_MA5_RE.search(line)
            )
            line_has_unsupported_inference = line_has_unsupported_inference or (
                "当前证据不支持A浪B浪C浪等浪型判断" in unsupported_market_inferences
                and _UNSUPPORTED_WAVE_RE.search(line)
            )
            line_has_unsupported_inference = line_has_unsupported_inference or (
                "指数领涨领跌或最大涨跌幅必须与当前证据排序一致"
                in unsupported_market_inferences
                and _has_wrong_index_return_extreme_claim(
                    line, list(evidence.get("indices") or [])
                )
            )
            line_has_unsupported_inference = line_has_unsupported_inference or (
                "缺失收益的指数不能引用其他指数的涨跌幅"
                in unsupported_market_inferences
                and _has_unavailable_index_return_claim(
                    line, list(evidence.get("indices") or [])
                )
            )
            line_has_unsupported_inference = line_has_unsupported_inference or (
                "指数区间收益正负方向必须与当前证据一致"
                in unsupported_market_inferences
                and _has_index_return_direction_conflict(
                    line, list(evidence.get("indices") or [])
                )
            )
            line_has_unsupported_inference = line_has_unsupported_inference or (
                "指数趋势状态必须与当前证据一致" in unsupported_market_inferences
                and _has_index_trend_state_conflict(
                    line, list(evidence.get("indices") or [])
                )
            )
            line_has_unsupported_inference = line_has_unsupported_inference or (
                "指数波动率最高最低表述必须与当前证据排序一致"
                in unsupported_market_inferences
                and _has_wrong_index_volatility_extreme_claim(
                    line, list(evidence.get("indices") or [])
                )
            )
            line_has_unsupported_inference = line_has_unsupported_inference or (
                "三大指数表述不能与四个代表性指数混用" in unsupported_market_inferences
                and "三大指数" in line
            )
            line_has_unsupported_inference = line_has_unsupported_inference or (
                "均线是否跌破的表述必须与最新收盘和均线位置一致"
                in unsupported_market_inferences
                and _has_moving_average_status_conflict(
                    line, list(evidence.get("indices") or [])
                )
            )
            line_has_unsupported_inference = line_has_unsupported_inference or (
                "股东户数连续变化次数或方向与确定性证据不一致"
                in unsupported_market_inferences
                and _SHAREHOLDER_STREAK_CLAIM_RE.search(line)
            )
            line_has_unsupported_inference = line_has_unsupported_inference or (
                "缺少历史十大股东合计序列时不能声称前十持股跨期持平或变化"
                in unsupported_market_inferences
                and _TOP10_HISTORICAL_COMPARISON_RE.search(line)
            )
            line_has_unsupported_inference = line_has_unsupported_inference or (
                "缺少历史一致预期快照时不能声称EPS已经上修或下修"
                in unsupported_market_inferences
                and _has_unproven_analyst_revision_claim(line)
            )
            line_has_unsupported_inference = line_has_unsupported_inference or (
                _STOCK_FAILURE_THRESHOLD_LABEL in unsupported_market_inferences
                and _stock_failure_line_has_unsupported_threshold(line, evidence)
            )
            line_has_unsupported_inference = line_has_unsupported_inference or (
                _STOCK_OBSERVATION_WINDOW_LABEL in unsupported_market_inferences
                and _has_unsupported_stock_observation_window(line, evidence)
            )
            line_has_unsupported_inference = line_has_unsupported_inference or (
                _LI_ZONG_RULE_BOTTLENECK_LABEL in unsupported_market_inferences
                and _has_li_zong_rule_bottleneck_overclaim(line, evidence)
            )
            line_has_unsupported_inference = line_has_unsupported_inference or (
                _LI_ZONG_COVERAGE_CONFLATION_LABEL in unsupported_market_inferences
                and _has_li_zong_coverage_conflation(line, evidence)
            )
            line_has_unsupported_inference = line_has_unsupported_inference or (
                _STOCK_SCREEN_SCOPE_OVERCLAIM_LABEL in unsupported_market_inferences
                and _has_stock_screen_scope_overclaim(line, evidence)
            )
            line_has_unsupported_inference = line_has_unsupported_inference or (
                _STOCK_DISCLOSURE_DATE_LABEL in unsupported_market_inferences
                and _has_unsupported_stock_disclosure_date(line, evidence)
            )
            line_has_unsupported_inference = line_has_unsupported_inference or (
                _STOCK_REPORT_DATE_CONFLICT_LABEL in unsupported_market_inferences
                and _has_stock_report_notice_date_conflict(line, evidence)
            )
            line_has_unsupported_inference = line_has_unsupported_inference or (
                _STOCK_DRAWDOWN_WINDOW_LABEL in unsupported_market_inferences
                and _has_stock_drawdown_window_conflict(line, evidence)
            )
            line_has_unsupported_inference = line_has_unsupported_inference or (
                _STOCK_SCENARIO_DIRECTION_LABEL in unsupported_market_inferences
                and _has_stock_scenario_direction_conflict(line)
            )
            line_quote_direction_conflict, line_quote_price_conflict = (
                _stock_current_quote_conflicts(line, evidence)
            )
            line_has_unsupported_inference = line_has_unsupported_inference or (
                _STOCK_CURRENT_QUOTE_DIRECTION_LABEL in unsupported_market_inferences
                and line_quote_direction_conflict
            )
            line_has_unsupported_inference = line_has_unsupported_inference or (
                _STOCK_CURRENT_QUOTE_PRICE_LABEL in unsupported_market_inferences
                and line_quote_price_conflict
            )
            line_has_unsupported_inference = line_has_unsupported_inference or (
                _STOCK_CURRENT_QUOTE_CLOSE_LABEL in unsupported_market_inferences
                and _stock_current_quote_close_conflict(line, evidence)
            )
            line_has_unsupported_inference = line_has_unsupported_inference or (
                _STOCK_CURRENT_QUOTE_SESSION_LABEL in unsupported_market_inferences
                and _stock_current_quote_session_conflict(line, evidence)
            )
            line_has_unsupported_inference = line_has_unsupported_inference or (
                _STOCK_CURRENT_QUOTE_MA20_LABEL in unsupported_market_inferences
                and _stock_current_quote_ma20_conflict(line, evidence)
            )
            line_has_unsupported_inference = line_has_unsupported_inference or (
                _STOCK_CURRENT_LIMIT_STATUS_LABEL in unsupported_market_inferences
                and _stock_current_limit_status_conflict(line, evidence)
            )
            line_has_unsupported_inference = line_has_unsupported_inference or (
                _STOCK_CROSS_DATE_MARKET_LABEL in unsupported_market_inferences
                and _has_stock_cross_date_market_claim(line, evidence)
            )
            line_has_unsupported_inference = line_has_unsupported_inference or (
                _STOCK_60D_RETURN_BINDING_LABEL in unsupported_market_inferences
                and _has_stock_60d_return_binding_conflict(line, evidence)
            )
            line_has_unsupported_inference = line_has_unsupported_inference or (
                _STOCK_DEBT_RATIO_SCALE_LABEL in unsupported_market_inferences
                and _has_stock_debt_ratio_scale_conflict(line, evidence)
            )
            line_has_unsupported_inference = line_has_unsupported_inference or (
                _STOCK_CASHFLOW_CAUSE_LABEL in unsupported_market_inferences
                and _has_stock_cashflow_causal_conflict(line, evidence)
            )
            line_has_unsupported_inference = line_has_unsupported_inference or (
                _STOCK_STATIC_FINANCIAL_CAUSAL_LABEL
                in unsupported_market_inferences
                and _has_stock_static_financial_causal_overclaim(line, evidence)
            )
            line_has_unsupported_inference = line_has_unsupported_inference or (
                _STOCK_INDUSTRY_CAUSAL_LABEL in unsupported_market_inferences
                and _has_stock_industry_causal_overclaim(line)
            )
            line_has_unsupported_inference = line_has_unsupported_inference or (
                _STOCK_MARKET_ABSORPTION_LABEL in unsupported_market_inferences
                and _has_stock_market_absorption_overclaim(line)
            )
            line_has_unsupported_inference = line_has_unsupported_inference or (
                _STOCK_EVENT_SENTIMENT_LABEL in unsupported_market_inferences
                and _has_stock_event_sentiment_overclaim(line)
            )
            line_has_unsupported_inference = line_has_unsupported_inference or (
                _STOCK_SENTIMENT_EXCLUSION_LABEL
                in unsupported_market_inferences
                and _has_stock_sentiment_exclusion_overclaim(line, evidence)
            )
            line_has_unsupported_inference = line_has_unsupported_inference or (
                _STOCK_UNSUPPORTED_CAUSAL_HYPOTHESIS_LABEL
                in unsupported_market_inferences
                and _has_stock_unsupported_causal_hypothesis(line, evidence)
            )
            line_has_private_operation = any(
                pattern.search(line) for pattern in _PRIVATE_OPERATIONAL_OUTPUT_PATTERNS
            ) and not (
                _is_public_component_source_boundary_clause(line)
                or _is_evidence_security_entity_clause(line, evidence)
            )
            if (
                line_tokens & unsupported
                and not line_has_unsupported_inference
                and not line_has_private_operation
                and (
                    evidence.get("type")
                    in {
                        "earnings_quality",
                        "financial_drivers",
                        "business_structure",
                        "shareholder_structure",
                        "analyst_expectations",
                        "event_timeline",
                    }
                    or (
                        evidence.get("type") == "stock_research"
                        and str(
                            (evidence.get("research_plan") or {}).get("focus") or ""
                        )
                        in {"quality_review", "valuation_review"}
                    )
                )
            ):
                kept_clauses = []
                for clause in re.split(r"(?<=[。！？；])", line):
                    clause_tokens = {
                        match.group(0) for match in _NUMBER_RE.finditer(clause)
                    }
                    if clause_tokens & unsupported:
                        removed_count += 1
                        continue
                    kept_clauses.append(clause)
                repaired_line = "".join(kept_clauses).strip()
                if repaired_line:
                    kept_lines.append(repaired_line)
                continue
            if (
                line_tokens & unsupported
                or line_has_unsupported_inference
                or line_has_private_operation
            ):
                removed_count += 1
                continue
            kept_lines.append(line)
        kept_lines = AgentOutputGuard._clean_repair_artifacts(kept_lines)
        repaired = "\n".join(
            AgentOutputGuard._drop_empty_answer_sections(kept_lines)
        ).strip()
        repaired = AgentOutputGuard._renumber_repaired_sections(repaired)
        repaired = AgentOutputGuard._renumber_markdown_lists(repaired)
        repaired = re.sub(r"\n{3,}", "\n\n", repaired)
        repaired = AgentOutputGuard._strip_unbalanced_markdown_emphasis(repaired)
        repaired = re.sub(r"[；;、]\s*$", "。", repaired)

        post_repair_appendices: list[str] = []
        if _stock_industry_counts_required_but_missing(repaired, evidence):
            appendix = AgentOutputGuard._stock_industry_counts_appendix(evidence)
            if appendix:
                post_repair_appendices.append(appendix)
        if _stock_contribution_required_but_missing(repaired, evidence):
            appendix = AgentOutputGuard._stock_component_contribution_appendix(evidence)
            if appendix:
                post_repair_appendices.append(appendix)
        if _stock_component_source_boundary_required_but_missing(repaired, evidence):
            appendix = AgentOutputGuard._stock_component_source_boundary_appendix(evidence)
            if appendix:
                post_repair_appendices.append(appendix)
        if _market_cause_fact_required_but_missing(repaired, evidence):
            appendix = AgentOutputGuard._market_cause_facts_appendix(evidence)
            if appendix:
                post_repair_appendices.append(appendix)
        if _STOCK_EVENT_SENTIMENT_LABEL in unsupported_market_inferences:
            appendix = AgentOutputGuard._stock_event_evidence_appendix(evidence)
            if appendix:
                post_repair_appendices.append(appendix)
        if (
            _STOCK_UNSUPPORTED_CAUSAL_HYPOTHESIS_LABEL
            in unsupported_market_inferences
            and any(
                term in str(evidence.get("user_question") or "")
                for term in ("公告", "事件", "披露", "消息", "信息")
            )
        ):
            appendix = AgentOutputGuard._stock_event_evidence_appendix(evidence)
            if appendix:
                post_repair_appendices.append(appendix)
        for appendix in post_repair_appendices:
            if appendix not in appendices:
                appendices.append(appendix)

        if appendices:
            repaired = (
                f"{repaired.rstrip()}\n\n"
                + "\n\n".join(str(appendix) for appendix in appendices)
            ).strip()

        specialist_repair = evidence.get("type") in {
            "earnings_quality",
            "financial_drivers",
            "business_structure",
            "shareholder_structure",
            "analyst_expectations",
            "event_timeline",
        }
        minimum_repaired_length = 40 if specialist_repair else 80
        if (
            (not removed_count and not quote_fact_added)
            or (len(repaired) < minimum_repaired_length and not unit_corrected)
            or len(repaired) < len(answer.strip()) * 0.45
        ):
            return None

        repaired_guard = AgentOutputGuard._validate_model_output(
            repaired,
            evidence,
            trusted_context=trusted_context,
        )
        if not repaired_guard["passed"]:
            return None
        return repaired, repaired_guard

    @staticmethod
    def _stock_current_quote_fact(evidence: dict[str, Any]) -> str | None:
        if evidence.get("type") != "stock_research":
            return None
        quote = evidence.get("current_quote") or {}
        price = quote.get("price")
        change = quote.get("pct_change")
        if not isinstance(price, (int, float)) or not isinstance(
            change, (int, float)
        ):
            return None

        def fmt(value: float) -> str:
            return f"{value:.2f}".rstrip("0").rstrip(".")

        currency = str(quote.get("currency") or "").upper()
        unit = {"CNY": "元", "USD": "美元", "HKD": "港元"}.get(
            currency, currency
        )
        unit = unit.strip()
        name = str(
            evidence.get("display_name") or quote.get("name") or evidence.get("symbol")
        ).strip()
        label = str(quote.get("quote_label") or "最新报价").strip()
        market_date = str(
            quote.get("market_date") or quote.get("market_timestamp") or ""
        )[:10]
        direction = "上涨" if float(change) >= 0 else "下跌"
        date_text = f"（{market_date}）" if market_date else ""
        unit_text = f"{unit}" if unit else ""
        return (
            f"最新行情：{name}{label}{date_text}为{fmt(float(price))}{unit_text}，"
            f"较前收盘{direction}{fmt(abs(float(change)))}%。"
        )

    @staticmethod
    def _stock_event_evidence_appendix(
        evidence: dict[str, Any],
    ) -> str | None:
        if evidence.get("type") != "stock_research":
            return None
        events = (evidence.get("event_timeline") or {}).get("events") or []
        selected: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for item in events:
            if item.get("evidence_level") != "official_disclosure" and item.get(
                "category"
            ) != "announcement":
                continue
            title = str(item.get("title") or "").strip()
            date = str(
                item.get("event_date")
                or item.get("published_at")
                or item.get("notice_date")
                or ""
            )[:10]
            if not title:
                continue
            key = (date, title)
            if key in seen:
                continue
            seen.add(key)
            selected.append(key)
            if len(selected) >= 2:
                break
        if not selected:
            return None
        question = str(evidence.get("user_question") or "")
        focus = str((evidence.get("research_plan") or {}).get("focus") or "")
        if focus == "quality_review":
            boundary = (
                "这些正式披露确实存在；标题本身不能证明经营改善的原因或质量，"
                "下一步需要核对原文中与本期经营、现金流和主营结构直接相关的内容。"
            )
        elif any(
            term in question
            for term in ("涨", "跌", "回撤", "异动", "企稳", "反转", "见底")
        ):
            boundary = (
                "这些正式披露确实存在；标题本身不能证明它们与本次股价变化存在因果关系，"
                "下一步需要核对公告原文中的事项内容和时间关系。"
            )
        else:
            boundary = (
                "这些正式披露确实存在；标题只能确认材料已经发布，不能代替原文对本轮问题"
                "作出解释，下一步需要核对具体事项和披露口径。"
            )
        lines = [
            "### 本轮相关公司披露",
            *[
                f"- {date}：{title}" if date else f"- {title}"
                for date, title in selected
            ],
            boundary,
        ]
        return "\n".join(lines)

    @staticmethod
    def _market_cause_facts_appendix(evidence: dict[str, Any]) -> str | None:
        target_date = str(
            (evidence.get("analysis_target") or {}).get("market_date") or ""
        ).strip()
        aligned = AgentOutputGuard._aligned_market_indices(evidence)
        returns = [
            (
                str(item.get("name") or item.get("symbol") or "代表性指数"),
                float((item.get("metrics") or {}).get("return_1d_pct")),
            )
            for item in aligned
            if isinstance(
                (item.get("metrics") or {}).get("return_1d_pct"),
                (int, float),
            )
        ]
        if not returns:
            return None

        def fmt(value: float) -> str:
            return f"{value:.2f}".rstrip("0").rstrip(".")

        lines = [
            "### 已确认的同日价格事实",
            *[
                f"- {name}在{target_date or '目标交易日'}上涨 {fmt(value)}%。"
                if value >= 0
                else f"- {name}在{target_date or '目标交易日'}下跌 {fmt(abs(value))}%。"
                for name, value in returns[:3]
            ],
        ]
        market_state = evidence.get("market_state") or {}
        if market_state.get("whole_market_breadth_available") is True:
            lines.append(
                "- 沪深京A股上涨 "
                f"{market_state.get('whole_market_advancers')} 家、下跌 "
                f"{market_state.get('whole_market_decliners')} 家、平盘 "
                f"{market_state.get('whole_market_unchanged')} 家，"
                f"固定广度分类为“{market_state.get('whole_market_breadth_state')}”。"
            )
        lines.append(
            "这些数据确认了当日价格与参与面，资讯标题只能作为可能驱动线索，不能单独证明因果。"
        )
        return "\n".join(lines)

    @staticmethod
    def _stock_industry_counts_appendix(
        evidence: dict[str, Any],
    ) -> str | None:
        industry_index = (evidence.get("stock_market_context") or {}).get(
            "exact_industry_index"
        ) or {}
        breadth = industry_index.get("component_breadth") or {}
        required = (
            breadth.get("advancers"),
            breadth.get("decliners"),
            breadth.get("unchanged"),
        )
        if breadth.get("status") != "available" or not all(
            isinstance(value, int) for value in required
        ):
            return None
        name = str(industry_index.get("name") or "对应行业指数").strip()
        market_date = str(
            breadth.get("market_date") or industry_index.get("market_date") or ""
        ).strip()
        total = breadth.get("total_constituents")
        if not isinstance(total, int):
            total = industry_index.get("constituent_count")
        median_change = breadth.get("median_pct_change")
        state = str(breadth.get("state") or "").strip()
        prefix = f"{market_date} " if market_date else ""
        total_text = f"，有效成分共 {total} 只" if isinstance(total, int) else ""
        state_text = f"，固定分类为“{state}”" if state else ""
        median_text = (
            f"，成分涨跌幅中位数 {float(median_change):.4f}%"
            if isinstance(median_change, (int, float))
            else ""
        )
        return "\n".join(
            [
                "### 行业成分广度补充",
                (
                    f"- {prefix}{name}{total_text}：上涨 {required[0]} 只、"
                    f"下跌 {required[1]} 只、平盘 {required[2]} 只"
                    f"{state_text}{median_text}。"
                ),
            ]
        )

    @staticmethod
    def _stock_component_contribution_appendix(
        evidence: dict[str, Any],
    ) -> str | None:
        industry_index = (evidence.get("stock_market_context") or {}).get(
            "exact_industry_index"
        ) or {}
        contribution = industry_index.get("component_contribution") or {}
        subject = contribution.get("subject") or {}
        estimated = subject.get("estimated_contribution_pp")
        if contribution.get("status") != "available" or not isinstance(
            estimated, (int, float)
        ):
            return None

        def fmt(value: Any, digits: int = 4) -> str | None:
            if not isinstance(value, (int, float)):
                return None
            rendered = f"{float(value):.{digits}f}".rstrip("0").rstrip(".")
            return "0" if rendered in {"-0", "+0"} else rendered

        subject_name = str(
            subject.get("name") or evidence.get("display_name") or "该成分股"
        ).strip()
        market_date = str(
            subject.get("market_date")
            or contribution.get("market_date")
            or industry_index.get("market_date")
            or ""
        ).strip()
        weight = subject.get("weight_pct")
        if not isinstance(weight, (int, float)):
            weight = industry_index.get("subject_weight_pct")
        pct_change = subject.get("pct_change")
        weights_as_of = str(
            contribution.get("weights_as_of")
            or industry_index.get("weights_as_of")
            or ""
        ).strip()
        index_name = str(industry_index.get("name") or "对应行业指数").strip()
        official_return = contribution.get("official_index_return_pct")
        if not isinstance(official_return, (int, float)):
            official_return = industry_index.get("return_1d_pct")
        estimated_total = contribution.get("estimated_total_contribution_pp")
        reconciliation_gap = contribution.get("reconciliation_gap_pp")
        boundary = str(contribution.get("boundary") or "").strip() or (
            "贡献度按官方权重快照与目标日复权涨跌幅静态相乘估算，"
            "不是中证官方逐日归因；权重漂移、公司行动和样本调整会形成对账差。"
        )

        subject_parts = []
        if market_date:
            subject_parts.append(f"目标日 {market_date}")
        if isinstance(pct_change, (int, float)):
            subject_parts.append(f"涨跌 {fmt(pct_change)}%")
        if isinstance(weight, (int, float)):
            subject_parts.append(f"权重 {fmt(weight)}%")
        if weights_as_of:
            subject_parts.append(f"权重日期 {weights_as_of}")
        subject_parts.append(f"静态估算贡献 {fmt(estimated)} 个百分点")

        lines = [
            "### 成分贡献口径补充",
            f"- {subject_name}：" + "；".join(subject_parts) + "。",
        ]
        reconciliation_parts = []
        if isinstance(official_return, (int, float)):
            reconciliation_parts.append(f"官方指数当日涨跌 {fmt(official_return)}%")
        if isinstance(estimated_total, (int, float)):
            reconciliation_parts.append(
                f"可用成分静态估算合计 {fmt(estimated_total)} 个百分点"
            )
        if isinstance(reconciliation_gap, (int, float)):
            reconciliation_parts.append(f"对账差 {fmt(reconciliation_gap)} 个百分点")
        if reconciliation_parts:
            lines.append(
                f"- {index_name}对账：" + "；".join(reconciliation_parts) + "。"
            )
        lines.append(f"- 口径边界：{boundary}")
        return "\n".join(lines)

    @staticmethod
    def _stock_component_source_boundary_appendix(
        evidence: dict[str, Any],
    ) -> str | None:
        industry_index = (evidence.get("stock_market_context") or {}).get(
            "exact_industry_index"
        ) or {}
        breadth = industry_index.get("component_breadth") or {}
        coverage = breadth.get("coverage") or {}
        fallbacks = list(breadth.get("source_fallbacks") or [])
        fallback_count = coverage.get("fallback_unadjusted_returns")
        if not fallbacks and not (
            isinstance(fallback_count, int) and fallback_count > 0
        ):
            return None
        names = []
        for item in fallbacks[:5]:
            name = str(item.get("name") or item.get("symbol") or "").strip()
            symbol = str(item.get("symbol") or "").strip()
            if name and symbol and symbol not in name:
                names.append(f"{name}（{symbol}）")
            elif name:
                names.append(name)
        named_subjects = "、".join(names)
        if (
            isinstance(fallback_count, int)
            and fallback_count > len(names)
            and named_subjects
        ):
            subject = f"共 {fallback_count} 只成分（例如 {named_subjects}）"
        else:
            subject = named_subjects or f"{fallback_count} 只成分"
        primary_count = coverage.get("primary_adjusted_returns")
        primary_text = (
            f"；另有 {primary_count} 只使用前复权日线"
            if isinstance(primary_count, int)
            else ""
        )
        return "\n".join(
            [
                "### 成分行情口径补充",
                (
                    f"- {subject}使用新浪公开未复权日线补充{primary_text}。"
                    "若目标日前后存在除权除息，该成分的单日收益和静态贡献需要重新核对。"
                ),
            ]
        )

    @staticmethod
    def _renumber_repaired_sections(answer: str) -> str:
        ordinals = "一二三四五六七八九十"
        section_heading = re.compile(
            r"^(?P<prefix>\s*(?:#{1,6}\s+|\*\*)?)"
            r"(?P<ordinal>[一二三四五六七八九十])、"
            r"(?P<rest>.+)$"
        )
        lines = answer.splitlines()
        positions = [
            index for index, line in enumerate(lines) if section_heading.match(line)
        ]
        if len(positions) > len(ordinals):
            return answer
        if positions:
            for number, index in enumerate(positions):
                match = section_heading.match(lines[index])
                if match is None:
                    continue
                lines[index] = (
                    f"{match.group('prefix')}{ordinals[number]}、"
                    f"{match.group('rest')}"
                )
        prose_ordinal = re.compile(
            r"^(?P<prefix>\s*)第(?P<ordinal>[一二三四五六七八九十])"
            r"(?P<marker>[，,:：])(?P<rest>.+)$"
        )
        prose_positions = [
            index for index, line in enumerate(lines) if prose_ordinal.match(line)
        ]
        if 0 < len(prose_positions) <= len(ordinals):
            for number, index in enumerate(prose_positions):
                match = prose_ordinal.match(lines[index])
                if match is None:
                    continue
                lines[index] = (
                    f"{match.group('prefix')}第{ordinals[number]}"
                    f"{match.group('marker')}{match.group('rest')}"
                )
        return "\n".join(lines)

    @staticmethod
    def _renumber_markdown_lists(answer: str) -> str:
        item = re.compile(r"^(?P<indent>\s*)(?P<number>\d+)(?P<marker>[.、])\s+")
        heading = re.compile(r"^\s*#{1,6}\s+")
        lines = answer.splitlines()
        expected = 1
        active = False
        for index, line in enumerate(lines):
            if heading.match(line):
                expected = 1
                active = False
                continue
            match = item.match(line)
            if match is None:
                continue
            if active and int(match.group("number")) == 1:
                expected = 1
            if not active:
                expected = 1
                active = True
            lines[index] = item.sub(
                f"{match.group('indent')}{expected}{match.group('marker')} ",
                line,
                count=1,
            )
            expected += 1
        return "\n".join(lines)

    @staticmethod
    def _strip_unbalanced_markdown_emphasis(answer: str) -> str:
        lines = answer.splitlines()
        for index, line in enumerate(lines):
            for marker in ("**", "__"):
                if line.count(marker) % 2:
                    line = line.replace(marker, "")
            lines[index] = line
        return "\n".join(lines)

    @staticmethod
    def _clean_repair_artifacts(lines: list[str]) -> list[str]:
        cleaned: list[str] = []
        for index, line in enumerate(lines):
            line = re.sub(r"^(?P<indent>\s*)[。；，、]+\s*", r"\g<indent>", line)
            line = re.sub(r"[；;、]\s*$", "。", line)
            stripped = line.strip()
            if not stripped:
                cleaned.append("")
                continue
            if re.fullmatch(r"[*_#`\s。；，、.!?,:：]+", stripped):
                continue
            if re.fullmatch(
                r"(?:公司|管理层|财报)[^。！？\n]{0,36}(?:解释|说明)[：:]",
                stripped,
            ):
                next_index = index + 1
                while next_index < len(lines) and not lines[next_index].strip():
                    next_index += 1
                next_line = lines[next_index].strip() if next_index < len(lines) else ""
                if not re.match(r"^(?:[-*+]\s+|\d+[.、)]\s+)", next_line):
                    continue
            cleaned.append(line)
        return cleaned

    @staticmethod
    def _drop_empty_answer_sections(lines: list[str]) -> list[str]:
        section_heading = re.compile(
            r"^(?:#{1,6}\s+[^\n]{1,80}|\*\*[^*\n]{1,80}\*\*[:：]?)\s*$"
        )
        keep = [True] * len(lines)
        for index, line in enumerate(lines):
            if not section_heading.match(line.strip()):
                continue
            next_index = index + 1
            while next_index < len(lines) and not lines[next_index].strip():
                next_index += 1
            if next_index >= len(lines) or section_heading.match(
                lines[next_index].strip()
            ):
                keep[index] = False
                for blank_index in range(index + 1, next_index):
                    keep[blank_index] = False
        return [
            line
            for index, line in enumerate(lines)
            if keep[index] and line.strip() != "---"
        ]

    @staticmethod
    def _numeric_values(text: str) -> list[float]:
        values = []
        for match in _NUMBER_RE.finditer(text):
            token = match.group(0)
            value = AgentOutputGuard._parse_number(token)
            if value is not None:
                if token.endswith("%") and not token.startswith(("+", "-")):
                    direction = AgentOutputGuard._percentage_direction(
                        text[max(0, match.start() - 64) : match.start()]
                    )
                    if direction is not None:
                        value = direction * abs(value)
                values.append(value)
        return values

    @staticmethod
    def _evidence_key_magnitudes(value: Any) -> list[float]:
        magnitudes: list[float] = []
        if isinstance(value, dict):
            for key, item in value.items():
                for token in _EVIDENCE_MAGNITUDE_RE.findall(str(key)):
                    parsed = AgentOutputGuard._parse_number(token)
                    if parsed is not None:
                        magnitudes.append(abs(parsed))
                if "_per_" in str(key) or str(key).startswith("per_"):
                    magnitudes.append(1.0)
                magnitudes.extend(AgentOutputGuard._evidence_key_magnitudes(item))
        elif isinstance(value, list):
            for item in value:
                magnitudes.extend(AgentOutputGuard._evidence_key_magnitudes(item))
        elif isinstance(value, str) and re.match(
            r"^\d{4}-\d{2}-\d{2}(?:T|\s)\d{2}:\d{2}", value
        ):
            for token in _EVIDENCE_MAGNITUDE_RE.findall(value):
                parsed = AgentOutputGuard._parse_number(token)
                if parsed is not None:
                    magnitudes.append(abs(parsed))
        return magnitudes

    @staticmethod
    def _percentage_direction(prefix: str) -> int | None:
        # Only inspect the current punctuation-delimited phrase and select the
        # direction word closest to the number. This prevents an earlier
        # "回撤" from making a later volatility figure negative, or an earlier
        # "跌" from overriding a later "涨".
        phrase = re.split(r"[\n，。、；：,;:]", prefix)[-1]
        if re.search(r"涨跌幅[^\n]{0,24}(?:中位数|四分位|分布)", phrase):
            return None
        directions = [
            *(
                (match.start(), -1)
                for match in _NEGATIVE_NUMBER_CONTEXT_RE.finditer(phrase)
            ),
            *(
                (match.start(), 1)
                for match in _POSITIVE_NUMBER_CONTEXT_RE.finditer(phrase)
            ),
        ]
        return max(directions, default=(0, None), key=lambda item: item[0])[1]

    @staticmethod
    def _parse_number(token: str) -> float | None:
        try:
            return float(token.replace(",", "").rstrip("%"))
        except (TypeError, ValueError):
            return None
