from __future__ import annotations

from typing import Any

from app.services.agent_evidence_compaction import aligned_market_indices
from app.services.agent_preview_common import fmt


def render_market_preview(evidence: dict[str, Any]) -> str | None:
    kind = evidence.get("type")

    if kind == "market_brief":
        state = evidence.get("market_state", {})
        industry_focus = evidence.get("industry_focus") or {}
        industry_snapshot = evidence.get("industry_snapshot") or {}
        if (
            industry_focus.get("name")
            and industry_snapshot.get("status") == "available"
        ):
            metrics = industry_snapshot.get("metrics") or {}
            component_analysis = industry_snapshot.get("component_analysis") or {}
            breadth = component_analysis.get("breadth") or {}
            market_date = (
                component_analysis.get("market_date")
                or (evidence.get("analysis_target") or {}).get("market_date")
                or "最近完整交易日"
            )
            lines = [
                f"按A股口径看，{industry_focus.get('name')}行业在 {market_date} 当日承压。",
                f"{industry_snapshot.get('index_full_name') or industry_snapshot.get('index_name') or industry_focus.get('name')}"
                f"当日涨跌 {fmt(metrics.get('return_1d_pct'))}%，"
                f"近5日 {fmt(metrics.get('return_5d_pct'))}%，"
                f"近20日 {fmt(metrics.get('return_20d_pct'))}%，"
                f"当前为{metrics.get('trend_state') or '趋势待确认'}。",
            ]
            if breadth.get("status") == "available":
                lines.append(
                    f"行业 {breadth.get('total_constituents')} 只成分股中，"
                    f"上涨 {breadth.get('advancers')} 只、下跌 {breadth.get('decliners')} 只、"
                    f"平盘 {breadth.get('unchanged')} 只；"
                    f"成分涨跌幅中位数 {fmt(breadth.get('median_pct_change'))}%，"
                    f"固定广度分类为“{breadth.get('state')}”。"
                )
            if state.get("whole_market_breadth_available"):
                lines.append(
                    f"同日沪深京A股上涨 {state.get('whole_market_advancers')} 家、"
                    f"下跌 {state.get('whole_market_decliners')} 家，"
                    f"全市场同样为“{state.get('whole_market_breadth_state')}”；"
                    "因此当日行业走弱与市场整体承压同步。"
                )
            lines.append(
                f"风险上，行业近60日累计涨跌 {fmt(metrics.get('return_60d_pct'))}%，"
                f"同期最大回撤 {fmt(metrics.get('max_drawdown_60d_pct'))}%；"
                "短期回落与中期累计表现需要分开看。"
            )
            lines.append(
                "当前没有足够的行业专属事件证据把这次下跌归结为单一原因，"
                "但已经可以确认行业价格、成分广度和大盘环境。"
            )
            return "\n\n".join(lines)
        indices = evidence.get("indices", [])
        aligned_indices = aligned_market_indices(evidence, indices)
        available = [
            item for item in aligned_indices if item.get("status") == "available"
        ]
        drivers_packet = evidence.get("market_drivers", {})
        question_focus = evidence.get("question_focus") or {}
        focus_key = question_focus.get("key") or "market_overview"
        market_key = drivers_packet.get("market_key")
        focus_rules = {
            "us": lambda item: item.get("group") == "us",
            "china": lambda item: item.get("group") == "china",
            "hong_kong": lambda item: item.get("group") == "hong_kong",
            "japan": lambda item: item.get("symbol") == "^N225",
            "korea": lambda item: item.get("symbol") == "^KS11",
            "europe": lambda item: item.get("group") == "europe",
        }
        focused = [
            item
            for item in available
            if market_key in focus_rules and focus_rules[market_key](item)
        ]
        live_focus = evidence.get("focused_live_market") or {}
        shown = [] if market_key == "gold" and live_focus else focused or available
        if market_key == "gold" and live_focus:
            lines = [
                f"伦敦金{live_focus.get('session_label') or '当前行情'}："
                f"最新 {fmt(live_focus.get('latest_price'))}，"
                f"相对前收 {fmt(live_focus.get('pct_change'))}%。"
            ]
        elif focused:
            returns = [
                item.get("metrics", {}).get("return_1d_pct")
                for item in focused
                if item.get("metrics", {}).get("return_1d_pct") is not None
            ]
            focus_state = state.get("label") or "数据不足"
            lines = [
                f"{drivers_packet.get('market_label') or '该市场'}收盘状态为“{focus_state}”；"
                f"目标交易日同日代表性指数 {len(focused)} 个，"
                f"其中 {len(returns)} 个可计算一日涨跌。"
            ]
        else:
            lines = [
                f"市场状态：{state.get('label', '数据不足')}。代表性指数可用 {len(available)}/{len(indices)} 个。"
            ]
        lines.insert(
            0,
            f"本次问题焦点：{question_focus.get('label') or '市场全景'}。",
        )
        if focus_key == "sector_rotation":
            state_label = state.get("label") or "结构待确认"
            if state.get("whole_market_breadth_available"):
                lines.insert(
                    1,
                    f"一句话判断：代表性指数当前为“{state_label}”；"
                    f"沪深京A股上涨 {state.get('whole_market_advancers')} 家、"
                    f"下跌 {state.get('whole_market_decliners')} 家、"
                    f"平盘 {state.get('whole_market_unchanged')} 家，"
                    f"固定广度分类为“{state.get('whole_market_breadth_state')}”。",
                )
                breadth_packet = evidence.get("market_breadth") or {}
                turnover = breadth_packet.get("turnover") or {}
                distribution = breadth_packet.get("distribution") or {}
                detail_lines = []
                if turnover.get("status") == "available":
                    exchange_amounts = turnover.get("exchanges") or {}
                    detail_lines.append(
                        "全市场当日累计成交额 "
                        f"{fmt(turnover.get('total_amount_100m_cny'))} 亿元；"
                        f"沪市 {fmt((exchange_amounts.get('shanghai') or {}).get('amount_100m_cny'))} 亿元、"
                        f"深市 {fmt((exchange_amounts.get('shenzhen') or {}).get('amount_100m_cny'))} 亿元、"
                        f"北交所 {fmt((exchange_amounts.get('beijing') or {}).get('amount_100m_cny'))} 亿元。"
                        "这是成交金额，不是资金净流入。"
                    )
                if distribution.get("status") == "available":
                    bins = distribution.get("bins") or {}
                    detail_lines.append(
                        "个股涨跌幅分布：中位数 "
                        f"{fmt(distribution.get('median_pct_change'))}%，"
                        f"四分位区间 {fmt(distribution.get('p25_pct_change'))}% 至 "
                        f"{fmt(distribution.get('p75_pct_change'))}%；"
                        f"上涨至少3% {bins.get('strong_advancers_ge_3')} 家，"
                        f"上涨0—3% {bins.get('mild_advancers_gt_0_lt_3')} 家，"
                        f"下跌超过3% {bins.get('strong_decliners_le_neg3')} 家。"
                    )
                missing = ["指数成分贡献度"]
                if distribution.get("status") != "available":
                    missing.insert(0, "个股涨幅分布")
                if turnover.get("status") != "available":
                    missing.insert(0, "全市场成交额")
                detail_lines.append(
                    "不能确认的部分：当前仍缺少"
                    + "、".join(missing)
                    + "，不能确认是否由少数权重股拉动，也不能把固定广度分类重新命名为结构性行情。"
                )
                lines[2:2] = detail_lines
            else:
                lines.insert(
                    1,
                    f"一句话判断：代表性指数当前为“{state_label}”，"
                    "当前只能看到代表性指数和热门板块排名；"
                    "证据不含全市场涨跌家数，不能确认整体普涨或结构性行情。",
                )
        for item in shown:
            metrics = item.get("metrics", {})
            lines.append(
                f"- {item['name']}：1日 {fmt(metrics.get('return_1d_pct'))}%，"
                f"5日 {fmt(metrics.get('return_5d_pct'))}%，{metrics.get('trend_state') or '趋势待确认'}"
            )
        if focus_key == "trend_reversal" and shown:
            lines.append("反弹与趋势确认：")
            include_60d_return = "60日" in str(evidence.get("user_question") or "")
            for item in shown[:3]:
                metrics = item.get("metrics") or {}
                return_details = f"20日 {fmt(metrics.get('return_20d_pct'))}%"
                if include_60d_return:
                    return_details += f"，60日 {fmt(metrics.get('return_60d_pct'))}%"
                lines.append(
                    f"- {item['name']}：{return_details}，"
                    f"趋势状态 {metrics.get('trend_state') or '待确认'}，"
                    f"最新收盘 {fmt(metrics.get('latest_close'))}，"
                    f"MA20 {fmt(metrics.get('ma20'))}。"
                )
        if focus_key == "volume_flows":
            breadth_packet = evidence.get("market_breadth") or {}
            turnover = breadth_packet.get("turnover") or {}
            if turnover.get("status") == "available":
                market_date = breadth_packet.get("market_date") or "市场日期待确认"
                latest_tick = (breadth_packet.get("coverage") or {}).get(
                    "latest_tick_time"
                )
                time_label = (
                    f"，快照内最新成交时点 {latest_tick}" if latest_tick else ""
                )
                lines.append(
                    f"沪深京A股全市场成交额（市场日期 {market_date}{time_label}）："
                    f"{fmt(turnover.get('total_amount_100m_cny'))} 亿元。"
                    "这是当日累计成交金额，不是资金净流入、机构买入或未来方向信号。"
                )
                comparison = turnover.get("history_comparison") or {}
                if comparison.get("status") == "building_history":
                    lines.append("同口径成交额历史仍在积累，当前不能确认放量或缩量。")
            if shown:
                lines.append("量能证据：")
                for item in shown[:3]:
                    metrics = item.get("metrics") or {}
                    lines.append(
                        f"- {item['name']} 5/20日量比 "
                        f"{fmt(metrics.get('volume_ratio_5_20'))}。"
                    )
        if focus_key == "market_risk" and shown:
            lines.append("风险证据：")
            for item in shown[:3]:
                metrics = item.get("metrics") or {}
                lines.append(
                    f"- {item['name']}：20日年化波动率 "
                    f"{fmt(metrics.get('volatility_20d_annualized_pct'))}%，"
                    f"60日最大回撤 {fmt(metrics.get('max_drawdown_60d_pct'))}%。"
                )
            if any(
                term in str(evidence.get("user_question") or "")
                for term in ("失效条件", "重新判断", "什么情况会推翻")
            ):
                lines.append("什么时候需要重新判断：")
                for item in shown[:3]:
                    metrics = item.get("metrics") or {}
                    latest_close = metrics.get("latest_close")
                    ma60 = metrics.get("ma60")
                    if not isinstance(latest_close, (int, float)) or not isinstance(
                        ma60, (int, float)
                    ):
                        continue
                    relation = "上方" if latest_close >= ma60 else "下方"
                    lines.append(
                        f"- {item['name']}当前收盘位于MA60{relation}；"
                        f"后续只复核收盘与MA60 {fmt(ma60)} 的关系是否改变。"
                    )
        sector_packet = evidence.get("hot_sectors", {})
        sectors = (
            sector_packet.get("sectors", [])[:3]
            if sector_packet.get("same_date_as_analysis_target") is not False
            else []
        )
        if sectors and market_key in {None, "china"}:
            lines.append(
                "热门板块（按当前涨跌幅）："
                + "、".join(
                    f"{item['name']} {fmt(item['pct_change'])}%" for item in sectors
                )
            )
        if sectors and market_key in {None, "china"}:
            lines.append("板块涨跌幅是当前市场截面，不代表后续持续性。")
        if (
            market_key in {None, "china"}
            and sector_packet.get("same_date_as_analysis_target") is False
        ):
            target_date = (evidence.get("analysis_target") or {}).get("market_date")
            sector_date = sector_packet.get("market_date")
            lines.append(
                f"板块榜已切换到 {sector_date or '新的交易日'}，"
                f"不用于解释 {target_date or '目标交易日'} 的涨跌。"
            )
        drivers = drivers_packet.get("items", [])[:3]
        if drivers:
            lines.append("当前市场驱动线索（需与价格事实交叉验证）：")
            lines.extend(f"- {item.get('title')}" for item in drivers)
        lines.append("以上仅总结已发生的行情，不构成下一交易日方向预测。")
        return "\n".join(lines)
    if kind == "market_pulse_article":
        market = evidence["market_brief"]
        state = market["market_state"]
        available = [
            item for item in market["indices"] if item.get("status") == "available"
        ]
        sectors = market.get("hot_sectors", {}).get("sectors", [])[:3]
        strongest = sorted(
            available,
            key=lambda item: item.get("metrics", {}).get("return_1d_pct") or -999,
            reverse=True,
        )
        weakest = list(reversed(strongest))
        index_times = sorted(
            {
                item.get("market_timestamp")
                for item in available
                if item.get("market_timestamp")
            }
        )
        average_return = state.get("average_return_1d_pct")
        advance_ratio = state.get("advance_ratio")
        if isinstance(average_return, (int, float)) and isinstance(
            advance_ratio, (int, float)
        ):
            market_state_sentence = (
                f"截至证据包所列市场时间，代表性指数状态为“{state['label']}”。"
                f"可用覆盖 {len(available)}/{len(market['indices'])}，"
                f"指数平均单日变化 {fmt(average_return)}%，"
                f"代表性指数上涨比例 {fmt(float(advance_ratio) * 100, 1)}%。"
            )
        else:
            market_state_sentence = (
                f"截至证据包所列市场时间，代表性指数状态为“{state['label']}”。"
                f"可用覆盖 {len(available)}/{len(market['indices'])}。"
                "由于跨市场交易时点不同，暂不计算整体平均涨跌和上涨比例。"
            )
        body = [
            f"# {evidence['article_title']}",
            "",
            market_state_sentence,
            "",
            "## 今天最重要的结构",
        ]
        if strongest:
            body.append(
                f"- 相对较强：{strongest[0]['name']}，单日 {fmt(strongest[0]['metrics']['return_1d_pct'])}%。"
            )
            body.append(
                f"- 相对较弱：{weakest[0]['name']}，单日 {fmt(weakest[0]['metrics']['return_1d_pct'])}%。"
            )
        if sectors:
            body.append(
                "- A股板块涨幅靠前："
                + "、".join(
                    f"{item['name']} {fmt(item['pct_change'])}%" for item in sectors
                )
                + "。这是涨跌幅排序，不等于持续性判断。"
            )
        body.extend(
            [
                "",
                "## 给个人投资者的含义",
                "当前更值得做的是核对自选股与市场结构是否一致，并检查原关注理由是否出现可验证变化；不要把指数或板块单日表现直接外推成下一交易日方向。",
                "",
                "## 数据边界",
                f"文章生成时间：{evidence['generated_at']}。"
                f"指数市场时间范围：{index_times[0] if index_times else '待确认'} 至 "
                f"{index_times[-1] if index_times else '待确认'}。"
                "本文聚焦指数和板块截面，不延伸为单股基本面结论。"
                "行情可能存在正常传输延迟，不据此预测下一交易日方向。",
            ]
        )
        return "\n".join(body)
    return None
