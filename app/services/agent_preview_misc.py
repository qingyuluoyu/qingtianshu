from __future__ import annotations

from typing import Any

from app.services.agent_preview_common import fmt


def render_misc_preview(evidence: dict[str, Any]) -> str | None:
    kind = evidence.get("type")

    if kind == "general_research":
        items = evidence.get("knowledge_context", {}).get("items", [])
        if items:
            titles = "、".join(item.get("title") or "未命名资料" for item in items[:4])
            return (
                f"已从个人与通用资料库匹配到：{titles}。"
                "开启 AI 深度解读后，Hermes 会结合当前对话、已确认记忆、"
                "资料库摘录和相关 Skills 给出完整回答。"
            )
        return (
            "这是一个通用研究问题。开启 AI 深度解读后，Hermes 会结合"
            "当前对话、已确认记忆和研究 Skills 回答；涉及实时市场事实时"
            "仍会先调用确定性数据与资讯证据。"
        )

    if kind == "watchlist_brief":
        items = evidence.get("items", [])
        if not items:
            return "自选股目前为空。添加时请同时写下关注理由，后续才能检查原假设是否仍成立。"
        lines = [f"自选股共 {len(items)} 只，按单日波动绝对值展示："]
        for item in items:
            if item.get("status") == "available":
                metrics = item["metrics"]
                lines.append(
                    f"- {item.get('name') or item['symbol']}：1日 {fmt(metrics['return_1d_pct'])}%，"
                    f"20日 {fmt(metrics['return_20d_pct'])}%，{metrics['trend_state']}。关注理由："
                    f"{item.get('thesis') or '尚未填写'}"
                )
            else:
                lines.append(f"- {item.get('name') or item['symbol']}：行情暂不可用。")
        return "\n".join(lines)

    if kind == "research_tracking":
        items = evidence.get("items") or []
        events = evidence.get("events") or []
        if not items:
            return (
                "当前还没有可跟踪的研究对象。先把股票加入自选并写下关注理由，"
                "系统会保存研究基线和后续证据变化。"
            )
        if evidence.get("symbol") and items:
            item = items[0]
            latest_change = item.get("latest_change") or {}
            state = item.get("current_state") or {}
            lines = [
                latest_change.get("summary")
                or f"{item.get('name') or item['symbol']}已进入长期研究跟踪。",
                (
                    f"当前结构：{state.get('trend_state') or '待确认'}；"
                    f"技术状态：{state.get('technical_state') or '待确认'}；"
                    f"20日收益 {fmt(state.get('return_20d_pct'))}%；"
                    f"60日最大回撤 {fmt(state.get('max_drawdown_60d_pct'))}%。"
                ),
            ]
            next_review = item.get("next_review") or {}
            checks = next_review.get("checks") or []
            if checks:
                lines.append("下一次研究复核：" + "；".join(checks[:3]))
            lines.append("以上是长期证据变化记录，不是涨跌预测或交易指令。")
            return "\n".join(lines)
        lines = [f"自选股研究跟踪共覆盖 {len(items)} 个标的："]
        latest_by_symbol = {
            event.get("symbol"): event for event in events if event.get("symbol")
        }
        for item in items:
            event = (
                latest_by_symbol.get(item["symbol"]) or item.get("latest_change") or {}
            )
            lines.append(
                f"- {item.get('name') or item['symbol']}："
                f"{event.get('summary') or '已建立研究基线，等待新证据。'}"
            )
        lines.append("变化按研究证据归档，不代表收益排名或投资优先级。")
        return "\n".join(lines)

    if kind == "research_priority":
        items = evidence.get("items") or []
        if not items:
            return "当前自选股为空。先添加关注标的和关注理由，再建立研究复核顺序。"
        lines = ["今天的研究复核顺序（不是投资排名）："]
        for index, item in enumerate(items, start=1):
            reasons = "；".join(
                str(reason).rstrip("。；") for reason in (item.get("reasons") or [])
            )
            if reasons:
                reasons += "。"
            lines.append(
                f"{index}. {item.get('name') or item['symbol']}："
                f"{item.get('priority_label')}（紧迫度 {item.get('priority_score')}）。"
                f"{reasons}"
            )
            next_review = item.get("next_review") or {}
            checks = next_review.get("checks") or []
            if checks:
                lines.append(f"   下一步：{'；'.join(checks[:2])}")
        lines.append(evidence.get("boundary") or "该顺序只用于研究复核，不是买卖建议。")
        return "\n".join(lines)

    if kind == "research_actions":
        items = evidence.get("items") or []
        if not items:
            return (
                "当前还没有研究行动。先把标的加入自选并写下关注理由，"
                "系统会建立研究基线、观察条件和待补证清单。"
            )
        summary = evidence.get("summary") or {}
        lines = [
            (
                f"研究行动覆盖 {summary.get('symbols', len(items))} 个标的："
                f"{summary.get('triggered', 0)} 项需要复核，"
                f"{summary.get('pending_data', 0)} 项待补证，"
                f"{summary.get('watching', 0)} 项继续观察。"
            )
        ]
        for item in items[:5]:
            lines.append(
                f"- {item.get('name') or item['symbol']}："
                f"{item.get('research_status_label') or '持续观察'}；"
                f"{item.get('headline') or '已建立研究行动。'}"
            )
            important = [
                action
                for action in (item.get("actions") or [])
                if action.get("status") in {"triggered", "pending_data"}
            ][:2]
            for action in important:
                lines.append(
                    f"  - {action.get('title')}：{action.get('current_evidence')}"
                    f" 下一步：{action.get('next_step')}"
                )
        lines.append(
            evidence.get("boundary")
            or "研究行动只用于证据复核，不是投资排名或交易建议。"
        )
        return "\n".join(lines)

    if kind == "research_outcome":
        items = evidence.get("items") or []
        if not items:
            return (
                "当前还没有可复盘的研究对象。先把股票加入自选并建立研究快照，"
                "后台会按 T+3、T+5、T+10 交易日持续回填。"
            )

        def outcome_line(item: dict[str, Any]) -> str:
            available = item.get("latest_available") or []
            outcome = available[0] if available else item.get("latest_progress")
            if not outcome:
                latest_anchor = item.get("latest_anchor") or []
                outcome = latest_anchor[0] if latest_anchor else None
            if not outcome:
                return f"- {item.get('name') or item['symbol']}：已建立研究档案，等待后续交易日。"
            horizon = outcome.get("horizon_sessions")
            observed = outcome.get("observed_sessions") or 0
            if outcome.get("result_status") == "available":
                progress = f"T+{horizon}已到期，收盘变化 {fmt(outcome.get('close_return_pct'))}%"
            elif observed:
                progress = (
                    f"T+{horizon}已观察 {observed} 个交易日，"
                    f"阶段变化 {fmt(outcome.get('partial_return_pct'))}%"
                )
            else:
                progress = f"T+{horizon}尚待后续交易日"
            return (
                f"- {item.get('name') or item['symbol']}：{progress}；"
                f"{outcome.get('scenario_label') or '情景尚不可评估'}。"
            )

        if evidence.get("symbol") and items:
            item = items[0]
            lines = [f"{item.get('name') or item['symbol']}的历史研究复盘："]
            available = item.get("latest_available") or []
            progress = item.get("latest_progress")
            if available:
                shown = available[:3]
            elif progress:
                shown = [progress]
            else:
                shown = item.get("latest_anchor") or []
            for outcome in shown[:3]:
                horizon = outcome.get("horizon_sessions")
                observed = outcome.get("observed_sessions") or 0
                status = (
                    f"已到期，收盘变化 {fmt(outcome.get('close_return_pct'))}%"
                    if outcome.get("result_status") == "available"
                    else (
                        f"已观察 {observed} 个交易日，阶段变化 "
                        f"{fmt(outcome.get('partial_return_pct'))}%"
                        if observed
                        else "尚无后续交易日"
                    )
                )
                lines.append(
                    f"- 研究时间 {str(outcome.get('anchor_timestamp') or '').split('T')[0]} · T+{horizon}："
                    f"{status}；最大上行 {fmt(outcome.get('maximum_favorable_excursion_pct'))}%，"
                    f"最大下行 {fmt(outcome.get('maximum_adverse_excursion_pct'))}%；"
                    f"{outcome.get('scenario_label') or '情景尚不可评估'}。"
                )
                lines.append(f"  复核：{outcome.get('review_conclusion')}")
            lines.append(evidence.get("boundary") or "该结果只用于研究复核。")
            return "\n".join(lines)

        lines = ["自选股历史研究复盘："]
        lines.extend(outcome_line(item) for item in items)
        lines.append(evidence.get("boundary") or "该结果只用于研究复核。")
        return "\n".join(lines)

    if kind == "watchlist_update":
        item = evidence["item"]
        return (
            f"已将 {item.get('name') or item['symbol']} 加入自选。"
            f"关注理由：{item.get('thesis') or '尚未填写'}。"
            "后续简报会把价格变化与这条理由放在一起，但不会把相关性写成因果。"
        )

    if kind == "memory_candidate":
        memory = evidence["memory"]
        return (
            f"已创建记忆候选：{memory['content']}。"
            "它尚未进入长期记忆，请确认后再用于后续分析。"
        )

    if kind == "visual_research":
        return (
            "图片已保存在你的个人工作区。"
            "当前只能在 AI 图像研究模式下做定性观察；"
            "不会把图中模糊的坐标、价格或百分比当作已验证的市场数字。"
            "如需结合实时行情，请同时告诉我证券代码。"
        )

    if kind == "earnings_quality":
        if evidence.get("status") != "available":
            lines = [
                evidence.get("summary")
                or "尚未建立足够的结构化财务期，不能进行财报质量分析。"
            ]
            lines.extend(
                f"- {item}" for item in (evidence.get("review_points") or [])[:3]
            )
            lines.append(evidence.get("boundary") or "不能用预测或估值替代财务事实。")
            return "\n".join(lines)
        latest = evidence.get("latest_report") or {}
        comparable = evidence.get("comparable_report") or {}
        lines = [
            f"{evidence.get('name') or evidence.get('symbol')}财报质量："
            f"{evidence.get('overall_label')}（证据置信度 {evidence.get('confidence')}）。",
            f"- 最新报告期：{latest.get('report_date_name') or latest.get('report_date')}；"
            f"可比报告期：{comparable.get('report_date_name') or '尚未找到上一年度同类报告期'}。",
        ]
        for factor in (evidence.get("factors") or [])[:6]:
            if factor.get("interpretation"):
                lines.append(f"- {factor.get('label')}：{factor['interpretation']}")
        if evidence.get("supports"):
            lines.append("- 支持证据：" + "；".join(evidence["supports"][:3]))
        if evidence.get("contradictions"):
            lines.append(
                "- 需要解释的矛盾：" + "；".join(evidence["contradictions"][:3])
            )
        for explanation in (evidence.get("company_explanations") or [])[:4]:
            lines.append(
                "- 公司报告解释："
                f"{explanation.get('label')}；{explanation.get('excerpt')}"
                "（管理层披露，仍需交叉验证）"
            )
        related = evidence.get("related_information") or []
        if related:
            lines.append(
                "- 相关公告与信息线索："
                + "；".join(item.get("title") or "未命名信息" for item in related[:4])
                + "。标题只能用于定位原文，不能单独证明财务变化原因。"
            )
        if evidence.get("review_points"):
            lines.append("- 下一步复核：" + "；".join(evidence["review_points"][:3]))
        lines.append(evidence.get("boundary") or "财报质量分析不构成交易结论。")
        return "\n".join(lines)

    if kind == "financial_drivers":
        if evidence.get("status") != "available":
            lines = [
                evidence.get("summary")
                or "尚未建立同类报告期的详细三表，不能进行利润与现金流拆解。"
            ]
            lines.extend(
                f"- {item}" for item in (evidence.get("review_points") or [])[:3]
            )
            lines.append(evidence.get("boundary") or "缺失科目不会由模型补写。")
            return "\n".join(lines)
        latest = evidence.get("latest_period") or {}
        comparable = evidence.get("comparable_period") or {}
        question = str(evidence.get("user_question") or "")
        focus_theme = None
        focus_terms: tuple[str, ...] = ()
        if any(term in question for term in ("财务费用", "汇兑", "利息")):
            focus_theme = "financial_expense_fx_interest"
            focus_terms = ("财务费用", "汇兑", "利息")
        elif any(term in question for term in ("经营现金流", "现金流", "销售收现")):
            focus_theme = "operating_cashflow"
            focus_terms = ("经营现金流", "现金流", "销售收现", "销售商品")
        elif any(term in question for term in ("存货", "备货", "跌价")):
            focus_theme = "inventory"
            focus_terms = ("存货", "备货", "跌价")
        elif any(term in question for term in ("应收", "回款")):
            focus_theme = "receivables_collection"
            focus_terms = ("应收", "回款")
        elif any(term in question for term in ("应付", "付款")):
            focus_theme = "payables_payment"
            focus_terms = ("应付", "付款")
        elif any(term in question for term in ("毛利", "营业成本", "产品结构")):
            focus_theme = "gross_margin_cost"
            focus_terms = ("毛利", "营业成本", "产品结构")
        elif any(term in question for term in ("其他收益", "投资收益", "公允价值")):
            focus_theme = "other_income_investment_fair_value"
            focus_terms = ("其他收益", "投资收益", "公允价值")
        elif any(term in question for term in ("减值", "非经常性")):
            focus_theme = "impairment_nonrecurring"
            focus_terms = ("减值", "非经常性")
        lines = [
            f"{evidence.get('name') or evidence.get('symbol')}利润与现金流拆解："
            f"{evidence.get('overall_label')}（证据置信度 {evidence.get('confidence')}）。",
            f"- 最新报告期：{latest.get('report_date_name') or latest.get('report_date')}；"
            f"可比报告期：{comparable.get('report_date_name') or comparable.get('report_date')}。",
        ]
        drivers = list(evidence.get("confirmed_mechanical_drivers") or [])
        explanations = list(evidence.get("company_explanations") or [])
        clues = list(evidence.get("plausible_clues") or [])
        if focus_theme:
            focused_drivers = [
                item
                for item in drivers
                if any(
                    term in str(item.get("label") or item.get("statement") or "")
                    for term in focus_terms
                )
            ]
            drivers = focused_drivers or drivers[:1]
            explanations = [
                item for item in explanations if item.get("theme") == focus_theme
            ]
            clues = [
                item
                for item in clues
                if any(
                    term in str(item.get("label") or item.get("evidence") or "")
                    for term in focus_terms
                )
            ]
        for driver in drivers[: 6 if not focus_theme else 3]:
            lines.append(f"- 已确认机械影响：{driver.get('statement')}")
        for explanation in explanations[: 5 if not focus_theme else 2]:
            lines.append(
                "- 公司报告解释："
                f"{explanation.get('label')}；{explanation.get('excerpt')}"
                "（管理层披露，仍需交叉验证）"
            )
        for clue in clues[: 4 if not focus_theme else 2]:
            lines.append(f"- 待验证线索：{clue.get('label')}；{clue.get('evidence')}")
        if evidence.get("unresolved_causes") and not focus_theme:
            lines.append(
                "- 仍不能确认：" + "；".join(evidence["unresolved_causes"][:3])
            )
        if evidence.get("review_points"):
            lines.append(
                "- 下一步复核："
                + "；".join(evidence["review_points"][: 1 if focus_theme else 3])
            )
        lines.append(evidence.get("boundary") or "该拆解不构成交易结论。")
        return "\n".join(lines)

    if kind == "analyst_expectations":
        if evidence.get("status") != "available":
            return "\n".join(
                [
                    evidence.get("forecast_statement")
                    or "当前还没有可核验的分析师一致预期。",
                    *(
                        (
                            f"- {item}"
                            for item in (evidence.get("review_points") or [])[:3]
                        )
                    ),
                    evidence.get("boundary")
                    or "缺失预测值不会用于生成评级、目标价或未来收益概率。",
                ]
            )
        lines = [
            f"{evidence.get('name') or evidence.get('symbol')}分析师一致预期：",
            f"- {evidence.get('rating_statement')}",
            f"- {evidence.get('forecast_statement')}",
        ]
        revision = evidence.get("revision") or {}
        if revision.get("available"):
            lines.append(f"- 历史修订：{revision.get('summary')}")
            organization_delta = revision.get("organization_count_delta")
            if isinstance(organization_delta, int):
                lines.append(
                    "- 覆盖机构变化："
                    + (
                        f"增加 {organization_delta} 家。"
                        if organization_delta > 0
                        else f"减少 {abs(organization_delta)} 家。"
                        if organization_delta < 0
                        else "未变化。"
                    )
                )
        else:
            lines.append("- 历史修订：当前为首个可比较快照，尚不能判断上修或下修。")
        reports = evidence.get("latest_reports") or []
        if reports:
            lines.append("- 最新研报：")
            lines.extend(
                f"  - {item.get('published_at') or '日期待确认'}｜"
                f"{item.get('institution') or '机构待确认'}｜"
                f"{item.get('title')}｜样本评级 {item.get('rating') or '未披露'}"
                for item in reports[:5]
            )
        if evidence.get("review_points"):
            lines.append("- 下一步复核：" + "；".join(evidence["review_points"][:2]))
        lines.append(
            evidence.get("boundary")
            or "第三方预测不是公司指引，评级分布不构成交易建议。"
        )
        return "\n".join(line for line in lines if line)

    if kind == "event_timeline":
        if evidence.get("status") != "available":
            return "\n".join(
                [
                    f"{evidence.get('name') or evidence.get('symbol')}尚未形成可用的事件脉络。",
                    *(
                        (
                            f"- {item}"
                            for item in (evidence.get("review_points") or [])[:3]
                        )
                    ),
                    evidence.get("boundary") or "不使用缺失事件生成催化或风险结论。",
                ]
            )
        question = str(evidence.get("user_question") or "")
        risk_focus = any(term in question for term in ("风险", "利空", "不利"))
        items = (
            evidence.get("risk_events")
            if risk_focus and evidence.get("risk_events")
            else evidence.get("events")
        ) or []
        lines = [
            f"{evidence.get('name') or evidence.get('symbol')}重要事件脉络（截至 {evidence.get('as_of_date')}）："
        ]
        for item in items[:6]:
            lines.append(
                f"- {item.get('event_date') or '日期待确认'}｜"
                f"{item.get('evidence_label')}｜{item.get('event_label')}｜"
                f"{item.get('title')}"
            )
        media_count = (evidence.get("coverage") or {}).get("media_events", 0)
        if media_count:
            lines.append(
                f"- 其中有 {media_count} 条媒体线索，需用公告或监管原文再确认。"
            )
        if evidence.get("review_points"):
            lines.append("- 下一步：" + "；".join(evidence["review_points"][:2]))
        lines.append(evidence.get("boundary") or "事件脉络不构成交易建议。")
        return "\n".join(lines)

    if kind == "shareholder_structure":
        if evidence.get("status") != "available":
            return "\n".join(
                [
                    evidence.get("summary") or "尚未取得股东结构数据。",
                    *(
                        (
                            f"- {item}"
                            for item in (evidence.get("review_points") or [])[:3]
                        )
                    ),
                    evidence.get("boundary") or "缺少披露时不会补写股东结构。",
                ]
            )
        question = str(evidence.get("user_question") or "")
        lines = [
            f"{evidence.get('name') or evidence.get('symbol')}股东结构：",
            evidence.get("summary") or "",
            f"- {evidence.get('holder_count_statement')}",
            f"- {evidence.get('recent_pattern')}",
        ]
        if any(term in question for term in ("十大", "主要股东", "股东是谁", "机构")):
            holders = evidence.get("top_holders") or []
            if holders:
                lines.append(
                    f"- 十大股东报告期：{evidence.get('top10_report_date')}；"
                    + "；".join(
                        f"第{item.get('rank')}名 {item.get('name')} "
                        f"{fmt(item.get('holding_ratio_pct'), 3)}%"
                        for item in holders[:5]
                    )
                )
        else:
            history = evidence.get("holder_history") or []
            if history:
                lines.append(
                    "- 最近披露："
                    + "；".join(
                        f"{item.get('as_of')} 户数 {item.get('holder_count')}、"
                        f"较上次 {fmt(item.get('holder_count_change_pct'), 3)}%"
                        for item in history[:5]
                    )
                )
        for note in (evidence.get("special_name_notes") or [])[:2]:
            lines.append(f"- 口径提示：{note}")
        if evidence.get("review_points"):
            lines.append("- 下一步复核：" + "；".join(evidence["review_points"][:2]))
        lines.append(evidence.get("boundary") or "股东结构不构成交易结论。")
        return "\n".join(line for line in lines if line)

    if kind == "business_structure":
        if evidence.get("status") != "available":
            return "\n".join(
                [
                    evidence.get("summary") or "尚未取得主营构成数据。",
                    *(
                        (
                            f"- {item}"
                            for item in (evidence.get("review_points") or [])[:3]
                        )
                    ),
                    evidence.get("boundary") or "缺失业务占比不会由模型补写。",
                ]
            )
        question = str(evidence.get("user_question") or "")
        dimensions = list(evidence.get("dimensions") or [])
        if "地区" in question or "海外" in question or "国内" in question:
            dimensions = [
                item for item in dimensions if item.get("classification") == "region"
            ]
        elif any(term in question for term in ("产品", "业务", "靠什么", "收入来自")):
            dimensions = [
                item for item in dimensions if item.get("classification") == "product"
            ] or dimensions
        lines = [
            f"{evidence.get('name') or evidence.get('symbol')}主营业务结构：",
            evidence.get("summary") or "",
        ]
        for dimension in dimensions[:2]:
            lines.append(
                f"- {dimension.get('label')}（{dimension.get('current_report_date')}）："
                + "；".join(
                    f"{item.get('item_name')}收入占比 {fmt(item.get('revenue_share_pct'), 3)}%"
                    + (
                        f"、毛利率 {fmt(item.get('gross_margin_pct'), 3)}%"
                        if item.get("gross_margin_pct") is not None
                        else ""
                    )
                    for item in (dimension.get("segments") or [])[:5]
                )
            )
            margin_reference = dimension.get("margin_reference") or {}
            if margin_reference:
                lines.append(
                    f"- 最近可用分部毛利率参考期为 {margin_reference.get('current_report_date')}，"
                    "与最新收入构成期不同，不能混写为同一报告期。"
                )
                reference_items = [
                    item
                    for item in margin_reference.get("segments") or []
                    if item.get("gross_margin_pct") is not None
                ]
                if reference_items:
                    lines.append(
                        "- 该独立参考期的毛利率："
                        + "；".join(
                            f"{item.get('item_name')} "
                            f"{fmt(item.get('gross_margin_pct'), 3)}%"
                            for item in reference_items[:5]
                        )
                    )
        relevant_changes = [
            item
            for item in (evidence.get("key_changes") or [])
            if not dimensions
            or item.get("dimension")
            in {dimension.get("classification") for dimension in dimensions}
        ]
        if relevant_changes:
            lines.append(
                "- 关键变化："
                + "；".join(
                    str(item.get("statement") or "") for item in relevant_changes[:4]
                )
            )
        if evidence.get("review_points"):
            lines.append("- 下一步复核：" + "；".join(evidence["review_points"][:2]))
        if evidence.get("latest_fetched_at"):
            lines.append(f"- 数据抓取时间：{evidence.get('latest_fetched_at')}")
        lines.append(evidence.get("boundary") or "主营构成不构成交易结论。")
        return "\n".join(lines)
    return None
