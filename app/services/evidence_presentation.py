from __future__ import annotations

from datetime import datetime
import re
from typing import Any
from zoneinfo import ZoneInfo

from app.services.stock_price_move import build_stock_price_move_visible_sources


def _market_date(value: Any, timezone_name: str = "Asia/Shanghai") -> str | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        timezone_value = ZoneInfo(timezone_name)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone_value)
        return parsed.astimezone(timezone_value).date().isoformat()
    except (TypeError, ValueError):
        return str(value)[:10]


def _public_evidence_number(
    value: Any, *, digits: int = 2, signed: bool = False
) -> str | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or abs(number) == float("inf"):
        return None
    if signed:
        return f"{number:+.{digits}f}"
    return f"{number:.{digits}f}".rstrip("0").rstrip(".")


def build_visible_evidence_sources(
    evidence: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Build a small, user-facing index of the structured evidence sent to Agent."""

    packet = evidence or {}
    focused_price_move_sources = build_stock_price_move_visible_sources(packet)
    if focused_price_move_sources is not None:
        return focused_price_move_sources
    display_name = str(packet.get("display_name") or "研究对象").strip()
    generated_at = packet.get("generated_at")
    sources: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def add(
        kind: str,
        title: str,
        summary: str | None = None,
        *,
        as_of: Any = None,
        source: str | None = None,
        url: str | None = None,
    ) -> None:
        clean_title = str(title or "").strip()
        if not clean_title:
            return
        key = (kind, clean_title)
        if key in seen:
            return
        seen.add(key)
        item: dict[str, Any] = {"kind": kind, "title": clean_title}
        if summary:
            item["summary"] = str(summary).strip()
        if as_of:
            item["as_of"] = str(as_of)
        if source:
            item["source"] = source
        if url and re.match(r"^https?://", str(url).strip(), re.IGNORECASE):
            item["url"] = str(url).strip()
        sources.append(item)

    if packet.get("type") == "stock_comparison":
        for comparison_item in (packet.get("items") or [])[:5]:
            name = str(
                comparison_item.get("name")
                or comparison_item.get("symbol")
                or "研究对象"
            )
            if comparison_item.get("status") != "available":
                add(
                    "比较边界",
                    f"{name}本轮证据状态",
                    "本轮未形成可比较的确定性证据。",
                    as_of=generated_at,
                    source="多股统一口径研究",
                )
                continue
            snapshot = comparison_item.get("snapshot") or {}
            financial = snapshot.get("financial") or {}
            if financial.get("report_date"):
                add(
                    "财务口径",
                    f"{name}财务报告期",
                    (
                        f"{financial.get('report_date_name') or financial.get('report_date')}；"
                        f"{financial.get('period_basis_label') or financial.get('period_basis') or '口径待确认'}"
                    ),
                    as_of=financial.get("notice_date") or financial.get("report_date"),
                    source="结构化财务披露",
                )
            for child in build_visible_evidence_sources(
                comparison_item.get("evidence") or {}
            )[:3]:
                add(
                    str(child.get("kind") or "研究证据"),
                    f"{name}｜{child.get('title')}",
                    child.get("summary"),
                    as_of=child.get("as_of"),
                    source=child.get("source"),
                    url=child.get("url"),
                )
        return sources[:16]

    quote = packet.get("current_quote") or {}
    quote_price = _public_evidence_number(quote.get("price"))
    quote_change = _public_evidence_number(quote.get("pct_change"), signed=True)
    if quote_price is not None:
        currency = str(quote.get("currency") or "").strip()
        quote_label = str(quote.get("quote_label") or "最新报价").strip()
        quote_summary = f"{quote_label} {quote_price}"
        if currency:
            quote_summary += f" {currency}"
        if quote_change is not None:
            quote_summary += f"；涨跌幅 {quote_change}%"
        add(
            "行情事实",
            f"{str(quote.get('name') or display_name).strip()}最新报价",
            quote_summary,
            as_of=quote.get("market_timestamp"),
            source="实时行情快照",
        )

    metrics = packet.get("metrics") or {}
    provenance = packet.get("provenance") or {}
    daily_close = _public_evidence_number(metrics.get("latest_close"))
    if daily_close is not None:
        daily_parts = [f"最近完整日线收盘 {daily_close}"]
        trend_state = str(metrics.get("trend_state") or "").strip()
        if trend_state:
            daily_parts.append(f"趋势结构 {trend_state}")
        return_20d = _public_evidence_number(metrics.get("return_20d_pct"), signed=True)
        if return_20d is not None:
            daily_parts.append(f"近20日 {return_20d}%")
        volatility = _public_evidence_number(
            metrics.get("volatility_20d_annualized_pct")
        )
        if volatility is not None:
            daily_parts.append(f"20日年化波动 {volatility}%")
        add(
            "历史行情",
            f"{display_name}最近完整日线与技术结构",
            "；".join(daily_parts),
            as_of=provenance.get("market_timestamp"),
            source="复权历史日线与确定性指标",
        )

    earnings_quality = packet.get("earnings_quality") or {}
    if earnings_quality.get("status") == "available":
        latest_report = earnings_quality.get("latest_report") or {}
        report_name = str(
            latest_report.get("report_date_name")
            or latest_report.get("report_date")
            or "最新财报"
        )
        add(
            "财务证据",
            f"{display_name}{report_name}财报质量",
            earnings_quality.get("summary"),
            as_of=latest_report.get("notice_date") or latest_report.get("report_date"),
            source="定期报告与确定性财务分析",
        )

    financial_drivers = packet.get("financial_drivers") or {}
    if financial_drivers.get("status") == "available":
        latest_period = financial_drivers.get("latest_period") or {}
        period_name = str(
            latest_period.get("report_date_name")
            or latest_period.get("report_date")
            or "最新报告期"
        )
        add(
            "财务拆解",
            f"{display_name}{period_name}利润与现金流拆解",
            financial_drivers.get("summary"),
            as_of=latest_period.get("notice_date") or latest_period.get("report_date"),
            source="三表科目与财报原文",
        )

    information = packet.get("a_share_information") or {}
    for item in (information.get("announcements") or [])[:1]:
        if not isinstance(item, dict):
            continue
        add(
            "公司公告",
            str(item.get("title") or "公司公告"),
            item.get("summary"),
            as_of=item.get("published_at"),
            source="公司披露",
            url=item.get("url"),
        )
    news_items = [
        item
        for item in (information.get("news") or [])
        if isinstance(item, dict)
        and not re.search(
            r"走势预测|后市是否|买入机会|目标价|人气排名|涨停又炸板|主力.*扫货",
            str(item.get("title") or ""),
        )
    ]
    news_items = [
        item
        for _, item in sorted(
            enumerate(news_items),
            key=lambda pair: (
                0
                if re.search(
                    r"超节点|WAIC|OEX|算力|订单|中标|合同|回购|减持|增持|监管|财报",
                    str(pair[1].get("title") or ""),
                    re.IGNORECASE,
                )
                else 1,
                pair[0],
            ),
        )
    ]
    for item in news_items[:2]:
        if not isinstance(item, dict):
            continue
        add(
            "新闻线索",
            str(item.get("title") or "公司新闻"),
            item.get("summary"),
            as_of=item.get("published_at"),
            source="公开资讯线索",
            url=item.get("url"),
        )

    fundamentals = packet.get("fundamentals") or {}
    for item in (fundamentals.get("regulatory_filings") or [])[:2]:
        if not isinstance(item, dict):
            continue
        add(
            "监管文件",
            str(item.get("title") or item.get("form") or "监管文件"),
            item.get("summary"),
            as_of=item.get("filed_at") or item.get("published_at"),
            source="监管披露",
            url=item.get("url") or item.get("source_url"),
        )

    indices = [
        item
        for item in (packet.get("indices") or [])
        if isinstance(item, dict) and item.get("status") == "available"
    ]
    index_parts: list[str] = []
    for item in indices[:4]:
        metrics_item = item.get("metrics") or {}
        change = _public_evidence_number(metrics_item.get("return_1d_pct"), signed=True)
        if change is not None:
            index_parts.append(f"{item.get('name') or item.get('symbol')} {change}%")
    if index_parts:
        add(
            "大盘行情",
            "代表性指数最近完整交易日",
            "；".join(index_parts),
            as_of=generated_at,
            source="指数历史行情",
        )

    breadth = packet.get("market_breadth") or {}
    breadth_values = breadth.get("breadth") or {}
    if breadth.get("status") == "available" and breadth_values:
        add(
            "市场广度",
            "A股全市场上涨与下跌家数",
            (
                f"上涨 {breadth_values.get('advancers')} 家；"
                f"下跌 {breadth_values.get('decliners')} 家；"
                f"平盘 {breadth_values.get('unchanged')} 家"
            ),
            as_of=breadth.get("market_date"),
            source="沪深京全市场快照",
        )

    hot_sectors = packet.get("hot_sectors") or {}
    sector_parts: list[str] = []
    for item in (hot_sectors.get("sectors") or [])[:4]:
        if not isinstance(item, dict):
            continue
        change = _public_evidence_number(item.get("pct_change"), signed=True)
        if change is not None:
            sector_parts.append(f"{item.get('name')} {change}%")
    if sector_parts:
        add(
            "板块行情",
            "A股热门板块",
            "；".join(sector_parts),
            as_of=hot_sectors.get("market_timestamp"),
            source="板块涨跌幅榜",
        )

    if packet.get("type") == "stock_screen":
        data_contract = packet.get("data_contract") or {}
        contract_as_of = data_contract.get("as_of") or {}
        contract_coverage = data_contract.get("coverage") or {}
        snapshot_coverage = contract_coverage.get("market_snapshot") or {}
        screen_date = contract_as_of.get("market_date") or (
            packet.get("data_meta") or {}
        ).get("latest_completed_trade_date")
        snapshot_available = int(snapshot_coverage.get("available") or 0)
        snapshot_expected = int(snapshot_coverage.get("expected") or 0)
        scope_parts = []
        if snapshot_expected:
            scope_parts.append(
                f"股票池覆盖 {snapshot_available}/{snapshot_expected} 只"
            )
        if data_contract.get("data_version"):
            scope_parts.append(f"数据版本 {data_contract['data_version']}")
        financial_periods = contract_as_of.get("financial_report_periods") or []
        if financial_periods:
            scope_parts.append("已取得财务报告期 " + "、".join(financial_periods[:3]))
        if scope_parts:
            add(
                "选股范围",
                f"{(packet.get('profile') or {}).get('label') or '研究候选'}数据范围",
                "；".join(scope_parts),
                as_of=screen_date,
                source="股票基础、完整日线、估值市值截面与财务指标",
            )

        history_packet = packet.get("history") or {}
        benchmark_name = str(
            (history_packet.get("benchmark") or {}).get("name") or "沪深300"
        )
        signal_labels = {
            "triggered": "已触发人工复核",
            "qualified": "已进入候选",
        }
        for item in (history_packet.get("items") or [])[:4]:
            if not isinstance(item, dict):
                continue
            symbol = str(
                item.get("internal_symbol") or item.get("symbol") or ""
            ).strip()
            name = str(item.get("name") or symbol or "历史样本").strip()
            signal_date = str(item.get("signal_date") or "").strip()
            summary_parts = [
                signal_labels.get(
                    str(item.get("signal_type") or ""),
                    "历史规则事件",
                )
            ]
            horizons = (item.get("performance") or {}).get("horizons") or {}
            for day in ("5", "10", "20"):
                outcome = horizons.get(day) or {}
                if outcome.get("status") != "available":
                    summary_parts.append(f"{day}日观察尚未完整")
                    continue
                stock_return = _public_evidence_number(
                    outcome.get("stock_return_pct"), signed=True
                )
                benchmark_return = _public_evidence_number(
                    outcome.get("benchmark_return_pct"), signed=True
                )
                excess_return = _public_evidence_number(
                    outcome.get("excess_return_pct"), signed=True
                )
                if (
                    stock_return is None
                    or benchmark_return is None
                    or excess_return is None
                ):
                    summary_parts.append(f"{day}日观察数据不完整")
                    continue
                summary_parts.append(
                    f"{day}日个股 {stock_return}% / {benchmark_name} "
                    f"{benchmark_return}% / 超额 {excess_return}%"
                )
            title = f"{name}（{symbol}）"
            if signal_date:
                title += f"｜{signal_date}信号"
            add(
                "历史回放",
                title,
                "；".join(summary_parts),
                as_of=signal_date or item.get("replay_as_of_date"),
                source="李总策略点时历史回放与沪深300复权日线",
            )

        for item in (packet.get("items") or [])[:6]:
            reasons = "；".join(
                str(value) for value in (item.get("matched_reasons") or [])[:2]
            )
            evidence_times = item.get("evidence_times") or {}
            summary_parts = [reasons or "命中当前透明筛选规则"]
            if evidence_times.get("financial_report_period"):
                summary_parts.append(
                    f"财务报告期 {evidence_times['financial_report_period']}"
                )
            missing_reasons = [
                str(value.get("reason") or "").strip()
                for value in (item.get("missing_reasons") or [])[:2]
                if isinstance(value, dict) and value.get("reason")
            ]
            if missing_reasons:
                summary_parts.append("数据缺口：" + "；".join(missing_reasons))
            add(
                "选股证据",
                f"{item.get('name')}（{item.get('internal_symbol')}）",
                "；".join(summary_parts),
                as_of=evidence_times.get("market_date") or screen_date,
                source="确定性研究候选筛选",
            )

    li_zong = packet.get("li_zong_strategy") or {}
    if li_zong:
        passed = [
            str(item.get("rule_id"))
            for item in (li_zong.get("rule_results") or [])
            if item.get("status") == "passed"
        ]
        add(
            "策略证据",
            f"{display_name}李总策略逐规则快照",
            (
                f"状态 {li_zong.get('status') or '待核验'}；"
                f"通过规则 {', '.join(passed[:6]) or '无'}"
            ),
            as_of=li_zong.get("as_of_date"),
            source="Tushare稳定快照与确定性规则引擎",
        )

    market_drivers = packet.get("market_drivers") or {}
    for item in (market_drivers.get("items") or [])[:3]:
        if not isinstance(item, dict):
            continue
        add(
            "市场资讯",
            str(item.get("title") or "市场资讯"),
            item.get("summary"),
            as_of=item.get("published_at"),
            source="市场资讯线索",
            url=item.get("url"),
        )

    return sources[:12]


def agent_evidence_progress(
    intent: str,
    evidence: dict[str, Any] | None,
) -> dict[str, Any]:
    """Summarize evidence already obtained without presenting an AI conclusion."""

    packet = evidence or {}
    items: list[dict[str, str]] = []

    def add(label: str, detail: Any) -> None:
        clean_label = str(label or "").strip()
        clean_detail = str(detail or "").strip()
        if not clean_label or not clean_detail:
            return
        items.append({"label": clean_label, "detail": clean_detail})

    title = "本轮已读取的研究证据"
    if intent == "market_brief":
        title = "本轮已读取的市场证据"
        analysis_target = packet.get("analysis_target") or {}
        market_date = str(analysis_target.get("market_date") or "").strip()
        date_alignment = packet.get("date_alignment") or {}
        aligned_indices = int(date_alignment.get("aligned_indices") or 0)
        available_indices = int(date_alignment.get("available_indices") or 0)
        if aligned_indices or available_indices:
            detail = f"{aligned_indices or available_indices} 项代表性指数"
            if market_date:
                detail += f" · 分析日 {market_date}"
            add("指数行情", detail)

        breadth_packet = packet.get("market_breadth") or {}
        breadth = breadth_packet.get("breadth") or {}
        if breadth_packet.get("status") == "available" and breadth.get("total"):
            detail = f"沪深京 {int(breadth['total'])} 只"
            if breadth.get("advancers") is not None and breadth.get("decliners") is not None:
                detail += (
                    f" · 上涨 {int(breadth['advancers'])} / "
                    f"下跌 {int(breadth['decliners'])}"
                )
            if breadth.get("state"):
                detail += f" · {breadth['state']}"
            add("全市场广度", detail)

        turnover = breadth_packet.get("turnover") or {}
        if turnover.get("status") == "available":
            amount = _public_evidence_number(turnover.get("total_amount_100m_cny"))
            add(
                "成交口径",
                f"全市场成交额 {amount} 亿元 · 已核对交易所覆盖"
                if amount is not None
                else "已取得全市场成交额与分交易所覆盖",
            )

        sector_packet = packet.get("hot_sectors") or {}
        sector_count = len(sector_packet.get("sectors") or [])
        news_count = len((packet.get("market_drivers") or {}).get("items") or [])
        if sector_count or news_count:
            parts = []
            if sector_count:
                parts.append(f"{sector_count} 个板块快照")
            if news_count:
                parts.append(f"{news_count} 条资讯线索")
            add("结构与事件", " · ".join(parts))
    elif intent in {
        "stock_research",
        "earnings_quality",
        "financial_drivers",
        "business_structure",
        "shareholder_structure",
        "analyst_expectations",
        "event_timeline",
    }:
        display_name = str(
            packet.get("display_name") or packet.get("symbol") or "当前股票"
        ).strip()
        title = f"本轮已读取的个股证据 · {display_name}"
        plan = packet.get("research_plan") or {}
        focus_label = str(plan.get("focus_label") or "").strip()
        if focus_label:
            add("研究重点", focus_label)

        provenance = packet.get("provenance") or {}
        market_time = str(provenance.get("market_timestamp") or "").strip()
        symbol = str(packet.get("symbol") or "").upper()
        timezone_name = (
            "Asia/Shanghai"
            if symbol.endswith((".SS", ".SZ"))
            else "Asia/Hong_Kong"
            if symbol.endswith(".HK")
            else "America/New_York"
        )
        market_date = _market_date(market_time, timezone_name)
        if packet.get("metrics"):
            add(
                "价格与技术",
                f"最近完整日线与技术指标 · 数据至 {market_date}"
                if market_date
                else "最近完整日线与技术指标已取得",
            )

        statuses = list((packet.get("module_statuses") or {}).values())
        applicable = [
            item for item in statuses if item.get("status") != "not_applicable"
        ]
        ready = [
            item
            for item in applicable
            if item.get("status") in {"fresh", "reused", "reused_fallback"}
        ]
        if applicable:
            labels = [str(item.get("label") or "").strip() for item in ready]
            labels = [label for label in labels if label]
            detail = f"已取得 {len(ready)}/{len(applicable)} 个计划模块"
            if labels:
                detail += " · " + "、".join(labels[:4])
            add("证据模块", detail)

        missing = [item for item in applicable if item.get("status") == "unavailable"]
        if missing:
            labels = [str(item.get("label") or "").strip() for item in missing]
            add("仍待补证", "、".join(label for label in labels if label))
    elif intent == "stock_comparison":
        comparison_items = list(packet.get("items") or [])
        available = sum(item.get("status") == "available" for item in comparison_items)
        title = "本轮已读取的多股比较证据"
        if comparison_items:
            add("研究对象", f"{len(comparison_items)} 只股票 · {available} 只可统一比较")
    elif intent == "stock_screen":
        title = "本轮已读取的选股证据"
        candidates = list(packet.get("items") or [])
        coverage = packet.get("coverage") or {}
        universe = (
            coverage.get("universe_count")
            or coverage.get("expected")
            or packet.get("universe_count")
        )
        if universe:
            add("股票池", f"{int(universe)} 只股票 · {len(candidates)} 只进入当前候选")
        elif candidates:
            add("筛选结果", f"{len(candidates)} 只股票进入当前候选")

    source_count = len(build_visible_evidence_sources(packet))
    if source_count and not any(item["label"] == "可追溯证据" for item in items):
        add("可追溯证据", f"{source_count} 项来源与时间记录")

    knowledge_count = len((packet.get("knowledge_context") or {}).get("items") or [])
    if knowledge_count:
        add("资料库", f"本轮匹配 {knowledge_count} 份相关资料")

    if not items:
        add("研究输入", "当前问题、连续对话上下文与可用研究工具已准备")

    return {
        "title": title,
        "items": items[:4],
        "boundary": "以上是本轮已经取得的确定性输入，不代表 AI 最终判断。",
    }
