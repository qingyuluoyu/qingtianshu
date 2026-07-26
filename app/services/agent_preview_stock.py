from __future__ import annotations

from typing import Any, Callable

from app.services.agent_evidence_compaction import (
    prompt_local_time as _prompt_local_time,
    prompt_market_date as _prompt_market_date,
)
from app.services.agent_output_guard_stock import (
    _current_quote_is_at_common_a_share_limit,
    _has_intraday_limit_touch_evidence,
    _stock_current_quote_is_newer,
)
from app.services.agent_preview_common import fmt, money
from app.services.stock_price_move import (
    build_stock_price_move_event_evidence as _build_stock_price_move_event_evidence,
    is_stock_price_move_question as _is_stock_price_move_question,
)


def render_stock_preview(
    evidence: dict[str, Any],
    *,
    render_li_zong_preview: Callable[[dict[str, Any]], str],
) -> str | None:
    kind = evidence.get("type")

    if kind == "stock_comparison":
        items = evidence.get("items") or []
        available = [item for item in items if item.get("status") == "available"]
        financial_basis = (evidence.get("comparison_basis") or {}).get(
            "financial"
        ) or {}
        status_label = {
            "exact_common_period": "财务报告期完全一致，可按列出的指标横向比较",
            "partial_exact_groups": "只有部分公司报告期一致，财务指标需分组比较",
            "not_aligned": "最新财务报告期未对齐，只能逐只陈述",
        }.get(str(financial_basis.get("status")), "财务口径需要逐只核对")
        lines = [
            "结论",
            f"本轮纳入 {len(items)} 只股票，其中 {len(available)} 只形成可用证据；{status_label}。",
            "",
            "关键差异",
        ]
        for item in items:
            name = item.get("name") or item.get("symbol")
            if item.get("status") != "available":
                lines.append(f"- {name}：本轮未形成可比较的确定性证据。")
                continue
            snapshot = item.get("snapshot") or {}
            valuation = snapshot.get("valuation") or {}
            financial = snapshot.get("financial") or {}
            period = financial.get("report_date_name") or financial.get("report_date")
            valuation_parts = []
            if valuation.get("pe_ttm") is not None:
                valuation_parts.append(f"PE(TTM) {fmt(valuation.get('pe_ttm'))}")
            if valuation.get("pb") is not None:
                valuation_parts.append(f"PB {fmt(valuation.get('pb'))}")
            financial_parts = []
            if financial.get("revenue_yoy_pct") is not None:
                financial_parts.append(
                    f"营收同比 {fmt(financial.get('revenue_yoy_pct'))}%"
                )
            if financial.get("net_profit_yoy_pct") is not None:
                financial_parts.append(
                    f"净利润同比 {fmt(financial.get('net_profit_yoy_pct'))}%"
                )
            if financial.get("gross_margin_pct") is not None:
                financial_parts.append(
                    f"毛利率 {fmt(financial.get('gross_margin_pct'))}%"
                )
            parts = [
                f"报告期 {period or '待确认'}",
                *valuation_parts,
                *financial_parts,
            ]
            lines.append(f"- {name}：" + "；".join(parts) + "。")
        lines.extend(["", "反方证据"])
        for item in available:
            risks = (item.get("snapshot") or {}).get("counter_evidence") or []
            risk_texts = []
            for risk in risks[:2]:
                if isinstance(risk, dict):
                    text = (
                        risk.get("claim") or risk.get("risk") or risk.get("statement")
                    )
                else:
                    text = risk
                if text:
                    risk_texts.append(str(text))
            lines.append(
                f"- {item.get('name') or item.get('symbol')}："
                + (
                    "；".join(risk_texts)
                    if risk_texts
                    else "当前没有足够的结构化反方证据可直接比较。"
                )
            )
        lines.extend(["", "下一步核验"])
        warnings = evidence.get("warnings") or []
        if warnings:
            lines.extend(f"- {warning}" for warning in warnings[:3])
        else:
            lines.append("- 等待下一次同口径财务披露后按相同维度重新比较。")
        lines.append(
            evidence.get("boundary") or "该比较用于研究，不构成公司排名或买卖建议。"
        )
        return "\n".join(lines)
    if kind == "stock_screen":
        profile = evidence.get("profile") or {}
        if profile.get("key") == "li_zong":
            return render_li_zong_preview(evidence)
        items = evidence.get("items") or []
        data_meta = evidence.get("data_meta") or {}
        data_contract = evidence.get("data_contract") or {}
        contract_as_of = data_contract.get("as_of") or {}
        coverage = data_contract.get("coverage") or {}
        snapshot = coverage.get("market_snapshot") or {}
        market_date = (
            contract_as_of.get("market_date")
            or data_meta.get("latest_completed_trade_date")
            or "待确认"
        )
        data_version = str(
            data_contract.get("data_version")
            or data_meta.get("data_version")
            or "待确认"
        )
        expected = int(snapshot.get("expected") or 0)
        available_count = int(snapshot.get("available") or 0)
        coverage_ratio = float(snapshot.get("ratio") or 0)
        coverage_text = (
            f"股票池覆盖 {available_count}/{expected} 只（{coverage_ratio * 100:.1f}%）"
            if expected
            else "股票池覆盖待确认"
        )
        scope_boundary = (
            "结果只代表本轮已覆盖范围，不能外推为全市场结论。"
            if expected and available_count < expected
            else "本轮股票池行情快照已完整覆盖。"
        )
        if evidence.get("status") == "unavailable":
            return (
                "选股数据正在准备中，当前没有足够的完整市场截面执行筛选。"
                "你可以稍后重试；系统不会在缺少确定性数据时临时编造候选。"
            )
        if not items:
            return (
                f"本次使用“{profile.get('label') or '研究候选'}”规则，"
                f"行情交易日为 {market_date}，{coverage_text}，数据版本 {data_version}。"
                f"{scope_boundary}"
                "当前覆盖范围内没有股票同时满足全部条件。建议一次只放宽一项规则再筛选，"
                "避免把多项条件同时移除后失去研究边界。\n\n"
                f"{evidence.get('boundary') or '研究候选筛选，不构成推荐或交易建议。'}"
            )
        lines = [
            f"本次使用“{profile.get('label') or '研究候选'}”规则，"
            f"行情交易日为 {market_date}，{coverage_text}，数据版本 {data_version}；"
            f"当前得到 {len(items)} 只研究候选。{scope_boundary}"
            f"{profile.get('sort_rule') or ''}",
            "",
        ]
        preview_items = items[:12]
        for index, item in enumerate(preview_items, start=1):
            reasons = "；".join(
                str(value) for value in (item.get("matched_reasons") or [])[:3]
            )
            evidence_times = item.get("evidence_times") or {}
            time_parts = []
            if evidence_times.get("market_date"):
                time_parts.append(f"行情日 {evidence_times['market_date']}")
            if evidence_times.get("financial_report_period"):
                time_parts.append(
                    f"财务报告期 {evidence_times['financial_report_period']}"
                )
            if evidence_times.get("financial_announcement_date"):
                time_parts.append(
                    f"财报公告日 {evidence_times['financial_announcement_date']}"
                )
            missing_reasons = [
                str(value.get("reason") or "").strip()
                for value in (item.get("missing_reasons") or [])[:4]
                if isinstance(value, dict) and value.get("reason")
            ]
            time_suffix = f"；{'；'.join(time_parts)}" if time_parts else ""
            missing_suffix = (
                f"；数据缺口：{'；'.join(missing_reasons)}" if missing_reasons else ""
            )
            lines.append(
                f"{index}. {item.get('name')}（{item.get('internal_symbol')}）："
                f"{reasons or '命中当前透明筛选规则'}{time_suffix}{missing_suffix}"
            )
        if len(items) > len(preview_items):
            lines.append(
                f"以上按原排序展示前 {len(preview_items)} 只；"
                f"另有 {len(items) - len(preview_items)} 只候选可在筛选结果中继续查看。"
            )
        lines.extend(
            [
                "",
                "下一步应选择其中一只进入股票研究空间，继续核验财报报告期、公司公告、行业口径和反方证据。",
                evidence.get("boundary")
                or "这是研究候选筛选，不构成推荐、评级或交易建议。",
            ]
        )
        return "\n".join(lines)
    if kind == "stock_research":
        metrics = evidence["metrics"]
        thesis = evidence.get("user_thesis") or "尚未记录关注理由"
        missing = evidence.get("research_frame", {}).get("missing_information", [])
        question = str(evidence.get("user_question") or "")
        current_quote = evidence.get("current_quote") or {}
        market_context = evidence.get("stock_market_context") or {}
        information = evidence.get("a_share_information") or {}
        coverage_packet = evidence.get("deep_stock_coverage") or {}
        coverage_query = any(
            term in question
            for term in (
                "六维证据",
                "证据六维",
                "证据覆盖",
                "覆盖状态",
                "覆盖情况",
                "覆盖缺口",
            )
        )
        if coverage_query and coverage_packet.get("dimensions"):
            status_labels = {
                "sufficient": "充分",
                "partial": "部分覆盖",
                "insufficient": "证据不足",
                "unavailable": "尚未取得",
            }
            summary = coverage_packet.get("summary") or {}
            lines = [
                "六维证据覆盖",
                (
                    f"{evidence.get('display_name') or evidence.get('symbol')}当前六维中，"
                    f"{summary.get('sufficient', 0)} 项充分、"
                    f"{summary.get('partial', 0)} 项部分覆盖、"
                    f"{summary.get('insufficient', 0)} 项证据不足、"
                    f"{summary.get('unavailable', 0)} 项尚未取得。"
                ),
            ]
            for dimension in coverage_packet.get("dimensions") or []:
                details = [
                    status_labels.get(str(dimension.get("coverage_status")), "待核验")
                ]
                sources = [str(item) for item in dimension.get("sources") or []]
                if sources:
                    details.append("已有证据：" + "、".join(sources))
                as_of_timezone = (
                    "Asia/Shanghai"
                    if str(evidence.get("symbol") or "").endswith((".SS", ".SZ"))
                    else "America/New_York"
                )
                as_of = [
                    (
                        _prompt_local_time(item, as_of_timezone)
                        if "T" in str(item)
                        else str(item)
                    )
                    for item in dimension.get("as_of") or []
                ]
                if as_of:
                    details.append("时间口径：" + "、".join(as_of[:3]))
                missing_items = [
                    str(item) for item in dimension.get("missing_items") or []
                ]
                if missing_items:
                    details.append("缺口：" + missing_items[0])
                lines.append(
                    f"- {dimension.get('label') or dimension.get('key')}："
                    + "；".join(details)
                    + "。"
                )

            research_change = evidence.get("research_change") or {}
            latest_change = research_change.get("latest_change") or {}
            new_evidence = latest_change.get("new_evidence") or []
            lines.append("新增证据")
            if new_evidence:
                for item in new_evidence[:4]:
                    lines.append(
                        f"- {item.get('published_at') or item.get('event_date') or item.get('created_at') or '日期待确认'}｜"
                        f"{item.get('title') or item.get('label') or '新增证据'}"
                    )
            elif latest_change.get("summary"):
                lines.append(
                    "- 最新变化记录未单列新的正式证据；"
                    + str(latest_change.get("summary"))
                )
            else:
                lines.append("- 当前变化档案未标识新的正式证据，不能把旧材料写成新增。")

            def evidence_text(item: Any) -> str:
                if isinstance(item, dict):
                    return str(
                        item.get("claim")
                        or item.get("risk")
                        or item.get("statement")
                        or item.get("summary")
                        or ""
                    ).strip()
                return str(item).strip()

            debate = evidence.get("evidence_debate") or {}
            counter_items = [
                text
                for text in (
                    evidence_text(item)
                    for item in [
                        *(debate.get("bear_case") or []),
                        *(debate.get("risk_committee") or []),
                    ]
                )
                if text
            ]
            lines.append("反方证据")
            if counter_items:
                lines.extend(f"- {item}" for item in counter_items[:5])
            else:
                lines.append("- 当前证据包未形成结构化反方证据，不能临时补写。")

            outlook = evidence.get("conditional_outlook") or {}
            invalidation = outlook.get("invalidation")
            lines.append("失效条件")
            if invalidation:
                lines.append("- " + evidence_text(invalidation))
            else:
                scenario_conditions = [
                    str(item.get("condition"))
                    for item in outlook.get("scenarios") or []
                    if isinstance(item, dict) and item.get("condition")
                ]
                if scenario_conditions:
                    lines.extend(
                        f"- {condition}" for condition in scenario_conditions[:3]
                    )
                else:
                    lines.append(
                        "- 当前证据尚未形成可量化失效门槛；不能自行发明毛利率、增速或价格阈值。"
                    )

            next_steps = [
                str(item.get("next_step"))
                for item in coverage_packet.get("tasks") or []
                if item.get("next_step")
            ]
            next_review = research_change.get("next_review") or {}
            next_steps.extend(
                str(item) for item in next_review.get("checks") or [] if item
            )
            next_steps.extend(str(item) for item in missing if item)
            deduped_steps = []
            seen_steps = set()
            for item in next_steps:
                normalized = item.strip()
                if not normalized or normalized in seen_steps:
                    continue
                seen_steps.add(normalized)
                deduped_steps.append(normalized)
            lines.append("下一步核验")
            if deduped_steps:
                lines.extend(f"- {item}" for item in deduped_steps[:6])
            else:
                lines.append("- 等待新的公司披露后，按相同六维口径重新核验。")
            lines.append(
                coverage_packet.get("boundary")
                or "六维覆盖只表示证据完整程度，不构成投资评级或买卖信号。"
            )
            return "\n".join(lines)
        if _is_stock_price_move_question(question):
            limit_query = any(term in question for term in ("涨停", "跌停", "封板"))
            cause_lines: list[str] = []
            analysis_target = market_context.get("analysis_target") or {}
            stock_target = market_context.get("stock_target") or {}
            quote_is_newer = current_quote and _stock_current_quote_is_newer(evidence)
            if any(term in question for term in ("收盘", "盘中")):
                if current_quote.get("quote_basis") == "post_close_snapshot":
                    cause_lines.append("A股已经收盘。")
                elif current_quote.get("quote_basis") == "intraday_snapshot":
                    cause_lines.append("A股仍在交易时段，当前是盘中报价。")
            if limit_query and quote_is_newer:
                quote_change = current_quote.get("pct_change")
                requested_limit = "跌停" if "跌停" in question else "涨停"
                sign_matches = isinstance(quote_change, (int, float)) and (
                    (requested_limit == "涨停" and quote_change > 0)
                    or (requested_limit == "跌停" and quote_change < 0)
                )
                cause_lines.append(
                    "是。"
                    if sign_matches
                    and _current_quote_is_at_common_a_share_limit(evidence)
                    else "不是。"
                )
            cause_lines.append(
                f"{evidence.get('display_name') or evidence['symbol']}涨跌证据核对："
            )
            if (
                analysis_target.get("basis") == "explicit_question_date"
                and stock_target.get("status") == "same_market_date"
            ):
                cause_lines.append(
                    f"- 用户指定交易日（{stock_target.get('market_date')}）："
                    f"收盘 {fmt(stock_target.get('close'))}，当日涨跌 "
                    f"{fmt(stock_target.get('return_1d_pct'))}%。"
                )
                if current_quote:
                    cause_lines.append(
                        f"- 最新报价（{_prompt_local_time(current_quote.get('market_timestamp'), 'Asia/Shanghai')}）："
                        f"{fmt(current_quote.get('price'))} {current_quote.get('currency') or ''}，"
                        f"涨跌幅 {fmt(current_quote.get('pct_change'))}%；"
                        "该报价只用于说明后续状态，不替换用户指定交易日。"
                    )
            elif quote_is_newer:
                quote_change = current_quote.get("pct_change")
                quote_basis = str(current_quote.get("quote_basis") or "")
                quote_label = str(current_quote.get("quote_label") or "当前报价")
                quote_direction = (
                    "上涨"
                    if isinstance(quote_change, (int, float)) and quote_change > 0
                    else "下跌"
                    if isinstance(quote_change, (int, float)) and quote_change < 0
                    else "涨跌待确认"
                )
                cause_lines.append(
                    f"- {quote_label}（{_prompt_local_time(current_quote.get('market_timestamp'), 'Asia/Shanghai')}）："
                    f"{fmt(current_quote.get('price'))} {current_quote.get('currency') or ''}，"
                    f"{quote_direction} {fmt(abs(float(quote_change)) if isinstance(quote_change, (int, float)) else quote_change)}%。"
                )
                if quote_basis == "post_close_snapshot":
                    cause_lines.append(
                        "- 交易状态：A股已经收盘；当天完整日线尚未入库，"
                        "因此保留为收盘后报价快照，不把它冒充完整日 K 字段。"
                    )
                if limit_query:
                    limit_term = "跌停" if "跌停" in question else "涨停"
                    sign_matches = isinstance(quote_change, (int, float)) and (
                        (limit_term == "涨停" and quote_change > 0)
                        or (limit_term == "跌停" and quote_change < 0)
                    )
                    if sign_matches and _current_quote_is_at_common_a_share_limit(
                        evidence
                    ):
                        if quote_basis == "post_close_snapshot":
                            cause_lines.append(
                                f"- 涨跌停状态：收盘后报价仍处于{limit_term}价附近；"
                                "当日交易已经结束。"
                            )
                        else:
                            cause_lines.append(
                                f"- 涨跌停状态：当前报价仍处于{limit_term}价附近；"
                                "收盘前仍可能打开。"
                            )
                    elif _has_intraday_limit_touch_evidence(evidence, limit_term):
                        cause_lines.append(
                            f"- 涨跌停状态：当前已不在{limit_term}价；"
                            f"媒体线索显示盘中曾触及{limit_term}，随后回落到"
                            f" {fmt(abs(float(quote_change)) if isinstance(quote_change, (int, float)) else quote_change)}%。"
                        )
                    else:
                        cause_lines.append(
                            f"- 涨跌停状态：按当前报价，未处于{limit_term}价。"
                        )
                cause_lines.append(
                    f"- 最近完整日线（{_prompt_market_date((evidence.get('provenance') or {}).get('market_timestamp'), 'Asia/Shanghai')}）："
                    f"收盘 {fmt(metrics.get('latest_close'))}，当日涨跌 "
                    f"{fmt(metrics.get('return_1d_pct'))}%。当前报价与完整日线不是同一时间锚点。"
                )
            else:
                cause_lines.append(
                    f"- 最近完整日线：收盘 {fmt(metrics.get('latest_close'))}，"
                    f"当日涨跌 {fmt(metrics.get('return_1d_pct'))}%。"
                )

            market_state = market_context.get("market_state") or {}
            aligned_indices = [
                item
                for item in market_context.get("indices") or []
                if item.get("comparison_status") == "same_market_date"
                and isinstance(item.get("return_1d_pct"), (int, float))
            ]
            if aligned_indices:
                cause_lines.append(
                    "- 同日代表性指数："
                    + "；".join(
                        f"{item.get('name')} {fmt(item.get('return_1d_pct'))}%"
                        for item in aligned_indices
                    )
                    + f"。{market_state.get('summary') or ''}"
                )
            breadth = market_context.get("market_breadth") or {}
            if breadth.get("same_date_as_target") is True:
                breadth_values = breadth.get("breadth") or {}
                cause_lines.append(
                    f"- 同日全市场广度：上涨 {breadth_values.get('advancers')} 家、"
                    f"下跌 {breadth_values.get('decliners')} 家、平盘 "
                    f"{breadth_values.get('unchanged')} 家，固定分类为“"
                    f"{breadth_values.get('state')}”。"
                )
            else:
                cause_lines.append(
                    "- 同日全市场涨跌家数尚未取得；其他交易日的广度不能用于解释目标日涨跌。"
                )
            industry_index = market_context.get("exact_industry_index") or {}
            if industry_index.get("status") == "same_market_date":
                mapping = industry_index.get("industry_mapping") or {}
                mapping_suffix = (
                    "（公司行业标签与中证指数为跨分类体系映射）"
                    if mapping.get("match_type") == "verified_alias"
                    else ""
                )
                cause_lines.append(
                    f"- 同日精确行业指数：{industry_index.get('name')} "
                    f"{fmt(industry_index.get('return_1d_pct'))}%{mapping_suffix}；"
                    f"公司同期 {fmt(industry_index.get('stock_return_1d_pct'))}%，"
                    f"相对行业 {fmt(industry_index.get('stock_minus_industry_pct'))} 个百分点。"
                    f"官方样本 {industry_index.get('constituent_count')} 只。"
                )
                component_breadth = industry_index.get("component_breadth") or {}
                if component_breadth.get("status") == "available":
                    cause_lines.append(
                        f"- 同日行业成分广度：上涨 {component_breadth.get('advancers')} 只、"
                        f"下跌 {component_breadth.get('decliners')} 只、平盘 "
                        f"{component_breadth.get('unchanged')} 只，固定分类为“"
                        f"{component_breadth.get('state')}”，成分涨跌幅中位数 "
                        f"{fmt(component_breadth.get('median_pct_change'))}%。"
                    )
                    component_coverage = component_breadth.get("coverage") or {}
                    fallback_count = component_coverage.get(
                        "fallback_unadjusted_returns"
                    )
                    if isinstance(fallback_count, int) and fallback_count:
                        fallback_names = "、".join(
                            str(item.get("name") or item.get("symbol") or "").strip()
                            for item in (
                                component_breadth.get("source_fallbacks") or []
                            )[:3]
                            if str(item.get("name") or item.get("symbol") or "").strip()
                        )
                        fallback_subject = (
                            fallback_names or f"其中 {fallback_count} 只成分"
                        )
                        cause_lines.append(
                            f"- 行业成分行情口径：{fallback_subject}使用新浪公开未复权日线补充；"
                            "若目标日前后存在除权除息，其单日收益和贡献需要重新核对。"
                        )
                    contribution = industry_index.get("component_contribution") or {}
                    subject_contribution = contribution.get("subject") or {}
                    if (
                        any(term in question for term in ("贡献", "权重", "归因"))
                        and contribution.get("status") == "available"
                        and subject_contribution
                    ):
                        cause_lines.append(
                            f"- 静态估算贡献：{subject_contribution.get('name') or evidence.get('display_name')} "
                            f"约 {fmt(subject_contribution.get('estimated_contribution_pp'))} 个百分点；"
                            "该数值按权重快照与复权涨跌幅相乘，不是官方逐日归因。"
                        )
                elif component_breadth.get("status") == "partial":
                    component_coverage = component_breadth.get("coverage") or {}
                    failures = component_breadth.get("failures") or []
                    missing_text = "；".join(
                        f"{item.get('name') or item.get('symbol')}（{item.get('reason') or '目标日行情待补'}）"
                        for item in failures[:3]
                    )
                    cause_lines.append(
                        f"- 同日行业成分广度仅为部分覆盖：有效 "
                        f"{component_coverage.get('available_returns') or component_breadth.get('available_returns')} / "
                        f"{component_coverage.get('constituents') or component_breadth.get('total_constituents')} 只；"
                        f"上涨 {component_breadth.get('advancers')} 只、下跌 "
                        f"{component_breadth.get('decliners')} 只、平盘 "
                        f"{component_breadth.get('unchanged')} 只。这里只描述有效样本，"
                        "不能称为完整行业普涨或普跌。"
                        + (f"缺失：{missing_text}。" if missing_text else "")
                    )
                    fallback_count = component_coverage.get(
                        "fallback_unadjusted_returns"
                    )
                    if isinstance(fallback_count, int) and fallback_count:
                        cause_lines.append(
                            f"- 行业成分行情口径：有效样本中有 {fallback_count} 只使用新浪未复权日线降级；"
                            "若目标日前后存在除权除息，其单日收益和贡献需要重新核对。"
                        )
                else:
                    cause_lines.append(
                        "- 目标日成分涨跌家数尚未完整取得，不能判断行业普涨、普跌或参与面。"
                    )
            elif not market_context.get("exact_industry_match_available"):
                cause_lines.append(
                    f"- {market_context.get('company_industry') or '公司所属'}行业的同日精确指数与成分口径仍待补证，"
                    "不能用宽泛热门板块替代。"
                )

            event_packet = _build_stock_price_move_event_evidence(evidence)
            target_market_date = event_packet.get("target_market_date") or "目标交易日"
            cause_lines.append("候选事件")
            official_events = event_packet.get("same_date_official_disclosures") or []
            media_events = event_packet.get("same_date_media_clues") or []
            after_close_events = event_packet.get("same_date_after_close_events") or []
            if official_events:
                cause_lines.extend(
                    f"- 已披露事实：{item.get('published_at') or item.get('event_date')}｜{item.get('title')}。"
                    "公告存在不等于已证明价格因果。"
                    for item in official_events[:2]
                )
            else:
                cause_lines.append(f"- {target_market_date} 未取得同日公司公告。")
            if media_events:
                source_count = event_packet.get("same_date_media_source_count") or 0
                source_boundary = (
                    "仅来自单一媒体来源"
                    if source_count <= 1
                    else f"来自 {source_count} 个来源"
                )
                cause_lines.extend(
                    f"- 待核验线索：{item.get('published_at') or item.get('event_date')}｜{item.get('title')}"
                    f"（{source_boundary}，不能作为直接原因）。"
                    for item in media_events[:2]
                )
            else:
                cause_lines.append("- 未取得开盘前或交易时段发布的同日媒体事件线索。")
            if after_close_events:
                cause_lines.append(
                    "- 收盘后信息："
                    + "；".join(
                        f"{item.get('published_at')}｜{item.get('title')}"
                        for item in after_close_events[:2]
                    )
                    + "。发布时间晚于当日收盘，不能解释当日交易时段。"
                )
            if not event_packet.get("strict_same_date_only"):
                adjacent_events = event_packet.get("adjacent_date_events") or []
                if adjacent_events:
                    cause_lines.append(
                        "- 邻近日线索："
                        + "；".join(
                            f"{item.get('event_date')}｜{item.get('title')}"
                            for item in adjacent_events[:2]
                        )
                        + "。这些不是同日事件，只能作为后续核验背景。"
                    )
            if any(term in question for term in ("情绪", "股吧", "舆情")):
                sentiment = information.get("sentiment") or {}
            else:
                sentiment = {}
            if sentiment:
                confidence = {
                    "low": "较低",
                    "medium": "中等",
                    "high": "较高",
                    "low_to_medium": "较低至中等",
                }.get(str(sentiment.get("confidence") or ""), "待确认")
                cause_lines.append(
                    f"- 社区情绪：{sentiment.get('band')}，样本 {sentiment.get('sample_size')} 条，"
                    f"置信度{confidence}。这只是弱证据，不是价格驱动证明。"
                )
            cause_lines.append("反方证据")
            if industry_index.get("status") == "same_market_date" and isinstance(
                industry_index.get("stock_minus_industry_pct"), (int, float)
            ):
                spread = float(industry_index["stock_minus_industry_pct"])
                if spread > 0:
                    cause_lines.append(
                        f"- 个股相对行业高 {fmt(spread)} 个百分点，"
                        "削弱了公司特定负面事件主导下跌的解释。"
                    )
                elif spread < 0:
                    cause_lines.append(
                        f"- 个股相对行业低 {fmt(abs(spread))} 个百分点，"
                        "说明行业同步下跌仍不足以解释全部相对弱势。"
                    )
            if not official_events:
                cause_lines.append(
                    "- 没有同日公司公告能够把价格变化锁定为公司级直接事件。"
                )
            cause_lines.extend(
                [
                    "下一步核验",
                    "- 对齐目标日分时异动与通信设备指数、主要成分股的同步时点。",
                    "- 复核深交所同日临时公告、监管问询或公司澄清原文；没有新增原文时保持“具体驱动未确认”。",
                ]
            )
            return "\n".join(cause_lines)

        lines = [f"{evidence.get('display_name') or evidence['symbol']} 当前价格证据："]
        if current_quote and _stock_current_quote_is_newer(evidence):
            lines.append(
                f"- {current_quote.get('quote_label') or '当前报价快照'}（{current_quote.get('market_timestamp')}）："
                f"{fmt(current_quote.get('price'))} {current_quote.get('currency') or ''}，"
                f"涨跌幅 {fmt(current_quote.get('pct_change'))}%。"
            )
            if current_quote.get("quote_basis") == "post_close_snapshot":
                lines.append(
                    "- 交易状态：市场已经收盘；当天完整日线尚未入库，"
                    "该数值仍按收盘后报价快照呈现。"
                )
            lines.append(
                f"- 最近完整日线（{_prompt_market_date((evidence.get('provenance') or {}).get('market_timestamp'), 'Asia/Shanghai')}）："
                f"趋势 {metrics['trend_state']}；1/20/60日收益为 "
                f"{fmt(metrics['return_1d_pct'])}% / {fmt(metrics['return_20d_pct'])}% / "
                f"{fmt(metrics['return_60d_pct'])}%。"
            )
        else:
            lines.append(
                f"- 趋势：{metrics['trend_state']}；1/20/60日收益为 "
                f"{fmt(metrics['return_1d_pct'])}% / {fmt(metrics['return_20d_pct'])}% / "
                f"{fmt(metrics['return_60d_pct'])}%。"
            )
        lines.extend(
            [
                f"- 风险：20日年化波动率 {fmt(metrics['volatility_20d_annualized_pct'])}%，"
                f"60日最大回撤 {fmt(metrics['max_drawdown_60d_pct'])}%。",
                f"- 你的原假设：{thesis}。价格本身不能证明这条基本面假设。",
            ]
        )
        market_state = market_context.get("market_state") or {}
        if market_state:
            lines.append(
                "- A股市场对照："
                f"{market_state.get('summary') or market_state.get('state') or '代表性指数状态已取得'}；"
                f"全市场广度为 {market_state.get('whole_market_breadth_state') or '待确认'}。"
            )
            if not market_context.get("exact_industry_match_available"):
                lines.append(
                    f"- {market_context.get('company_industry') or '公司所属'}行业的精确指数与成分口径仍待补证，"
                    "热门宽泛板块不能替代该行业。"
                )
            else:
                industry_index = market_context.get("exact_industry_index") or {}
                if industry_index.get("status") == "same_market_date":
                    lines.append(
                        f"- 同日{industry_index.get('name')}指数涨跌 "
                        f"{fmt(industry_index.get('return_1d_pct'))}%；"
                        f"公司相对行业 {fmt(industry_index.get('stock_minus_industry_pct'))} 个百分点。"
                        + (
                            f"成分广度为“{(industry_index.get('component_breadth') or {}).get('state')}”。"
                            if (industry_index.get("component_breadth") or {}).get(
                                "status"
                            )
                            == "available"
                            else "指数表现不等于成分股涨跌家数。"
                        )
                    )
        sentiment = information.get("sentiment") or {}
        if sentiment:
            lines.append(
                f"- 社区情绪样本：{sentiment.get('band')}，分数 {fmt(sentiment.get('score'), 3)}，"
                f"置信度 {sentiment.get('confidence')}，样本 {sentiment.get('sample_size')} 条。"
                "该指标来自股吧关键词与互动权重，不是走势预测。"
            )
        announcements = information.get("announcements") or []
        if announcements:
            lines.append(
                "- 最新公司公告："
                + "；".join(item["title"] for item in announcements[:3])
            )
        news = information.get("news") or []
        if news:
            lines.append(
                "- 最新媒体事件：" + "；".join(item["title"] for item in news[:3])
            )
        fundamentals = evidence.get("fundamentals") or {}
        regulatory_filings = fundamentals.get("regulatory_filings") or []
        if regulatory_filings:
            lines.append(
                "- 最新官方监管文件："
                + "；".join(item["title"] for item in regulatory_filings[:3])
            )
        global_news = (evidence.get("global_information") or {}).get("news") or []
        if global_news:
            lines.append(
                "- 最新海外媒体事件："
                + "；".join(item["title"] for item in global_news[:3])
            )
        valuation = fundamentals.get("valuation") or {}
        fundamental_summary = fundamentals.get("summary") or {}
        latest_report = fundamental_summary.get("latest_report") or {}
        peer_comparison = evidence.get("peer_comparison") or {}
        if valuation:
            total_market_cap = valuation.get("total_market_cap")
            market_cap_text = (
                f"，总市值 {money(total_market_cap, valuation.get('currency'))}"
                if isinstance(total_market_cap, (int, float))
                else ""
            )
            valuation_parts = []
            for label, key in (
                ("TTM市盈率", "pe_ttm"),
                ("动态市盈率", "pe_dynamic"),
                ("静态市盈率", "pe_static"),
                ("市净率", "pb"),
            ):
                if isinstance(valuation.get(key), (int, float)):
                    valuation_parts.append(f"{label} {fmt(valuation.get(key))}")
            lines.append(
                f"- 估值快照：{'，'.join(valuation_parts)}{market_cap_text}；"
                f"市场时间 {valuation.get('market_timestamp')}。"
                "这些倍数不能在缺少历史分位和业务结构校准时直接解释为便宜或昂贵。"
            )
        peer_metrics = peer_comparison.get("metrics") or {}
        if peer_metrics:
            peer_parts = []
            for label, key in (("TTM市盈率", "pe_ttm"), ("市净率", "pb")):
                metric = peer_metrics.get(key) or {}
                if metric:
                    peer_parts.append(
                        f"{label}：本标的 {fmt(metric.get('subject_value'))}，"
                        f"同行中位数 {fmt(metric.get('peer_median'))}，"
                        f"比值 {fmt(metric.get('subject_to_peer_median'), 3)}"
                    )
            peer_names = "、".join(
                item.get("name") or item.get("symbol")
                for item in peer_comparison.get("peers", [])
            )
            lines.append(
                f"- 固定同行估值样本（{peer_comparison.get('group_label')}，"
                f"{peer_names}）：{'；'.join(peer_parts)}。"
                "这是小样本横截面，不是完整行业分位或投资评级。"
            )
        peer_operating = peer_comparison.get("operating_comparison") or {}
        operating_metrics = peer_operating.get("metrics") or {}
        if operating_metrics:
            operating_parts = []
            for label, key, suffix in (
                ("营收同比", "revenue_yoy_pct", "%"),
                ("净利润同比", "net_profit_yoy_pct", "%"),
                ("毛利率", "gross_margin_pct", "%"),
                ("净利率", "net_margin_pct", "%"),
                (
                    "经营现金流/净利润",
                    "operating_cashflow_to_net_profit",
                    "",
                ),
            ):
                metric = operating_metrics.get(key) or {}
                if metric:
                    operating_parts.append(
                        f"{label}：本标的 {fmt(metric.get('subject_value'))}{suffix}，"
                        f"同行中位数 {fmt(metric.get('peer_median'))}{suffix}，"
                        f"同报告期样本 {metric.get('peer_sample_size')} 家"
                    )
            comparable_names = "、".join(
                item.get("name") or item.get("symbol")
                for item in peer_operating.get("peers", [])
                if item.get("status") == "comparable"
            )
            lines.append(
                f"- 固定同行同报告期经营比较（"
                f"{peer_operating.get('anchor_report_date_name') or peer_operating.get('anchor_report_date')}，"
                f"{comparable_names}）：{'；'.join(operating_parts)}。"
                "只比较相同报告日和累计口径，业务结构差异必须单列，"
                "不能据此生成公司优劣评级。"
            )
            operating_subject = peer_operating.get("subject") or {}
            subject_profile = operating_subject.get("business_profile") or {}
            subject_operating_financial = operating_subject.get("financial") or {}
            business_periods = []
            if subject_profile.get("anchor_report_date"):
                business_periods.append(
                    (
                        operating_subject.get("name")
                        or evidence.get("display_name")
                        or evidence.get("symbol"),
                        subject_profile.get("anchor_report_date"),
                    )
                )
            peer_detail_lines = []
            if subject_operating_financial:
                subject_segments = "、".join(
                    f"{segment.get('item_name')} {fmt(segment.get('revenue_share_pct'))}%"
                    for segment in (subject_profile.get("top_segments") or [])
                    if segment.get("item_name")
                )
                subject_adjustments = "、".join(
                    f"{segment.get('item_name')} {fmt(segment.get('revenue_share_pct'))}%"
                    for segment in (
                        subject_profile.get("composition_adjustments") or []
                    )
                    if segment.get("item_name")
                )
                peer_detail_lines.append(
                    f"{operating_subject.get('name') or evidence.get('display_name') or evidence.get('symbol')}："
                    f"营收同比 {fmt(subject_operating_financial.get('revenue_yoy_pct'))}%，"
                    f"净利润同比 {fmt(subject_operating_financial.get('net_profit_yoy_pct'))}%，"
                    f"毛利率 {fmt(subject_operating_financial.get('gross_margin_pct'))}%，"
                    f"经营现金流 {money(subject_operating_financial.get('operating_cashflow'), subject_operating_financial.get('currency'))}，"
                    f"经营现金流/净利润 {fmt(subject_operating_financial.get('operating_cashflow_to_net_profit'), 3)}；"
                    f"主营构成报告期 {subject_profile.get('anchor_report_date') or '未取得'}"
                    + (f"，主要分类 {subject_segments}" if subject_segments else "")
                    + (
                        f"，构成调整项 {subject_adjustments}"
                        if subject_adjustments
                        else ""
                    )
                )
            for item in peer_operating.get("peers") or []:
                profile = item.get("business_profile") or {}
                if profile.get("anchor_report_date"):
                    business_periods.append(
                        (
                            item.get("name") or item.get("symbol"),
                            profile.get("anchor_report_date"),
                        )
                    )
                financial = item.get("financial") or {}
                if item.get("status") != "comparable" or not financial:
                    continue
                segments = "、".join(
                    f"{segment.get('item_name')} {fmt(segment.get('revenue_share_pct'))}%"
                    for segment in (profile.get("top_segments") or [])
                    if segment.get("item_name")
                )
                adjustments = "、".join(
                    f"{segment.get('item_name')} {fmt(segment.get('revenue_share_pct'))}%"
                    for segment in (profile.get("composition_adjustments") or [])
                    if segment.get("item_name")
                )
                peer_detail_lines.append(
                    f"{item.get('name') or item.get('symbol')}：营收同比 "
                    f"{fmt(financial.get('revenue_yoy_pct'))}%，净利润同比 "
                    f"{fmt(financial.get('net_profit_yoy_pct'))}%，毛利率 "
                    f"{fmt(financial.get('gross_margin_pct'))}%，经营现金流 "
                    f"{money(financial.get('operating_cashflow'), financial.get('currency'))}，"
                    f"经营现金流/净利润 "
                    f"{fmt(financial.get('operating_cashflow_to_net_profit'), 3)}；"
                    f"主营构成报告期 {profile.get('anchor_report_date') or '未取得'}"
                    + (f"，主要分类 {segments}" if segments else "")
                    + (f"，构成调整项 {adjustments}" if adjustments else "")
                )
            if peer_detail_lines:
                lines.append("- 同行逐项事实：" + "；".join(peer_detail_lines) + "。")
            if business_periods:
                unique_business_periods = {
                    str(period) for _, period in business_periods if period
                }
                if len(unique_business_periods) == 1:
                    lines.append(
                        "- 主营构成报告期：四家公司均为 "
                        f"{next(iter(unique_business_periods))}；"
                        "报告期一致，但产品分类名称不是统一分类口径。"
                    )
                else:
                    lines.append(
                        "- 主营构成报告期："
                        + "；".join(
                            f"{name} {period}" for name, period in business_periods
                        )
                        + "。各期必须分开呈现。"
                    )
        if latest_report:
            currency = latest_report.get("currency")
            financial_parts = []
            if isinstance(latest_report.get("revenue"), (int, float)):
                financial_parts.append(
                    f"营收 {money(latest_report.get('revenue'), currency)}"
                )
            if isinstance(latest_report.get("revenue_yoy_pct"), (int, float)):
                financial_parts.append(
                    f"营收同比 {fmt(latest_report.get('revenue_yoy_pct'))}%"
                )
            if isinstance(latest_report.get("parent_net_profit"), (int, float)):
                financial_parts.append(
                    f"净利润 {money(latest_report.get('parent_net_profit'), currency)}"
                )
            if isinstance(latest_report.get("net_profit_yoy_pct"), (int, float)):
                financial_parts.append(
                    f"净利润同比 {fmt(latest_report.get('net_profit_yoy_pct'))}%"
                )
            for label, key in (
                ("加权ROE", "roe_weighted_pct"),
                ("毛利率", "gross_margin_pct"),
                ("净利率", "net_margin_pct"),
                ("资产负债率", "debt_asset_ratio_pct"),
            ):
                if isinstance(latest_report.get(key), (int, float)):
                    financial_parts.append(f"{label} {fmt(latest_report.get(key))}%")
            lines.append(
                f"- 最新财务（{latest_report.get('report_date_name')}，"
                f"{latest_report.get('period_basis_label') or '报告期口径'}）："
                f"{'，'.join(financial_parts)}。"
            )
            cashflow_ratio = fundamental_summary.get("operating_cashflow_to_net_profit")
            if cashflow_ratio is not None:
                lines.append(
                    f"- 盈利质量观察：经营现金流/净利润={fmt(cashflow_ratio, 3)}；"
                    "需结合报告期季节性核对。"
                )
        earnings_quality = evidence.get("earnings_quality") or {}
        if earnings_quality.get("status") == "available":
            quality_line = (
                f"- 财报质量：{earnings_quality.get('overall_label')}"
                f"（证据置信度 {earnings_quality.get('confidence')}）"
            )
            contradictions = earnings_quality.get("contradictions") or []
            if contradictions:
                quality_line += "；主要矛盾：" + "；".join(contradictions[:2])
            lines.append(quality_line + "。")
        financial_drivers = evidence.get("financial_drivers") or {}
        if financial_drivers.get("status") == "available":
            driver_line = (
                f"- 利润与现金流驱动：{financial_drivers.get('overall_label')}"
                f"（证据置信度 {financial_drivers.get('confidence')}）"
            )
            negative = [
                item
                for item in (
                    financial_drivers.get("confirmed_mechanical_drivers") or []
                )
                if item.get("direction") == "negative"
            ]
            clues = financial_drivers.get("plausible_clues") or []
            if negative:
                driver_line += "；主要负向机械影响：" + "；".join(
                    str(item.get("label")) for item in negative[:2]
                )
            if clues:
                driver_line += "；待复核线索：" + "；".join(
                    str(item.get("label")) for item in clues[:2]
                )
            lines.append(driver_line + "。")
        shareholder_structure = evidence.get("shareholder_structure") or {}
        if shareholder_structure.get("status") == "available":
            shareholder_line = (
                f"- 股东结构：截至 {shareholder_structure.get('holder_count_as_of')}，"
                f"股东户数 {shareholder_structure.get('holder_count')}，"
                f"较上次 {fmt(shareholder_structure.get('holder_count_change_pct'), 3)}%；"
                f"{shareholder_structure.get('holder_count_signal_label')}。"
            )
            if shareholder_structure.get("top10_report_date"):
                shareholder_line += (
                    f"最近十大股东报告期 {shareholder_structure.get('top10_report_date')}，"
                    f"前十名合计持股 {fmt(shareholder_structure.get('top10_ratio_pct'), 3)}%。"
                )
            lines.append(shareholder_line)
        analyst_expectations = evidence.get("analyst_expectations") or {}
        if analyst_expectations.get("status") == "available":
            analyst_line = (
                f"- 分析师预期：{analyst_expectations.get('rating_statement')} "
                f"{analyst_expectations.get('forecast_statement')}"
            )
            revision = analyst_expectations.get("revision") or {}
            if revision.get("available"):
                analyst_line += f" 历史修订：{revision.get('summary')}"
            else:
                analyst_line += " 当前没有历史快照可判断上修或下修。"
            lines.append(analyst_line)
        event_timeline = evidence.get("event_timeline") or {}
        if event_timeline.get("status") == "available":
            themes = "、".join(
                f"{item.get('label')} {item.get('count')}条"
                for item in (event_timeline.get("themes") or [])[:4]
            )
            lines.append(
                f"- 事件脉络：截至 {event_timeline.get('as_of_date')}"
                + (f"，主要主题为 {themes}。" if themes else "。")
            )
            for event in (event_timeline.get("events") or [])[:3]:
                lines.append(
                    f"  - {event.get('event_date') or '日期待确认'}｜"
                    f"{event.get('evidence_label')}｜{event.get('title')}"
                )
        outlook = evidence.get("conditional_outlook") or {}
        if outlook:
            lines.append(
                f"- 条件展望（{outlook.get('horizon')}）：{outlook.get('label')}，"
                f"置信度 {outlook.get('confidence')}。"
            )
            for scenario in outlook.get("scenarios", []):
                lines.append(
                    f"  - {scenario['name']}：当{scenario['condition']}；{scenario['meaning']}"
                )
            if "失效条件" in str(evidence.get("user_question") or ""):
                lines.append(
                    "- 失效条件："
                    + str(
                        outlook.get("invalidation")
                        or "价格跨越关键参考位或公告、财务、行业证据发生冲突时，当前判断必须重算。"
                    )
                )
            calibration = outlook.get("calibration") or {}
            analog = calibration.get("historical_analog") or {}
            if analog.get("sample_size", 0) > 0:
                lines.append(
                    f"- 历史走查（价格规则，{calibration.get('horizon')}）："
                    f"保留样本中同类信号 {analog.get('sample_size')} 次，"
                    f"未来收益中位数 {fmt(analog.get('median_forward_return_pct'))}%，"
                    f"四分位区间 {fmt(analog.get('p25_forward_return_pct'))}% 至 "
                    f"{fmt(analog.get('p75_forward_return_pct'))}%。"
                )
                if analog.get("direction_consistency") is not None:
                    lines.append(
                        f"  - 历史方向一致率 {fmt(analog.get('direction_consistency') * 100)}%；"
                        "这是样本描述，不是未来上涨或下跌概率。"
                    )
            elif calibration:
                lines.append(
                    "- 历史走查：当前价格信号在保留样本中的同类案例不足，"
                    "因此不提高结论置信度。"
                )
            lines.append(f"- 预测边界：{outlook.get('warning')}")
        debate = evidence.get("evidence_debate") or {}
        if debate:
            lines.append(f"- 多方证据结论：{debate.get('manager_view')}。")
            if debate.get("bull_case"):
                lines.append(
                    "  - 支持证据："
                    + "；".join(item["claim"] for item in debate["bull_case"])
                )
            if debate.get("bear_case"):
                lines.append(
                    "  - 反方证据："
                    + "；".join(item["claim"] for item in debate["bear_case"])
                )
            if debate.get("risk_committee"):
                lines.append(
                    "  - 风险委员会："
                    + "；".join(item["risk"] for item in debate["risk_committee"])
                )
        if missing:
            lines.append("下一步仍需补充：" + "；".join(missing))
        lines.append(
            "请优先核对公司公告或监管文件原文；结构化财务用于检验假设，"
            "媒体标题和社区讨论只能作为研究线索。"
        )
        return "\n".join(lines)
    return None
