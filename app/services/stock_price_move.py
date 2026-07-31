from __future__ import annotations

from datetime import datetime
import re
from typing import Any, Iterable
from zoneinfo import ZoneInfo


STOCK_PRICE_MOVE_TERMS = (
    "为什么涨",
    "为什么跌",
    "为什么上涨",
    "为什么下跌",
    "为何上涨",
    "为何下跌",
    "上涨原因",
    "下跌原因",
    "涨停",
    "跌停",
    "封板",
    "大涨",
    "大跌",
    "上涨的事实",
    "下跌的事实",
    "怎么回事",
    "市场或板块拖累",
)

STOCK_PRICE_MOVE_QUALIFIER_TERMS = (
    "可能解释",
    "不能确认",
    "究竟更像",
    "更像",
    "更像什么",
    "更接近",
    "归因于",
    "直接驱动",
)

STOCK_PRICE_MOVE_CONTEXT_TERMS = (
    "股价",
    "涨跌",
    "上涨",
    "下跌",
    "收涨",
    "收跌",
    "大涨",
    "大跌",
    "回撤",
    "回落",
    "走强",
    "走弱",
    "异动",
    "涨幅",
    "跌幅",
)

STOCK_STRICT_SAME_DATE_TERMS = (
    "只使用同日",
    "仅使用同日",
    "只看同日",
    "仅看同日",
    "只基于同日",
    "仅基于同日",
    "只用同日",
    "仅用同日",
)


def is_stock_price_move_question(question: str) -> bool:
    text = str(question or "")
    if any(term in text for term in STOCK_PRICE_MOVE_TERMS):
        return True
    return any(term in text for term in STOCK_PRICE_MOVE_QUALIFIER_TERMS) and any(
        term in text for term in STOCK_PRICE_MOVE_CONTEXT_TERMS
    )


def is_deep_stock_price_move_question(question: str) -> bool:
    text = str(question or "")
    return is_stock_price_move_question(text) and any(
        term in text
        for term in (
            "深度分析",
            "深入分析",
            "详细分析",
            "全面分析",
            "信息量要大",
            "信息量充分",
            "充分展开",
        )
    )


def _market_date(value: Any, timezone_name: str) -> str | None:
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


def _event_market_date(item: dict[str, Any], timezone_name: str) -> str | None:
    for key in (
        "event_date",
        "trade_date",
        "notice_date",
        "filing_date",
        "published_at",
        "filed_at",
    ):
        if item.get(key):
            return _market_date(item.get(key), timezone_name)
    return None


def _event_session_relation(
    item: dict[str, Any], *, target_market_date: str, timezone_name: str
) -> str:
    published_at = item.get("published_at") or item.get("filed_at")
    if not published_at:
        return "date_only"
    try:
        parsed = datetime.fromisoformat(str(published_at).replace("Z", "+00:00"))
        market_timezone = ZoneInfo(timezone_name)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=market_timezone)
        local = parsed.astimezone(market_timezone)
    except (TypeError, ValueError):
        return "date_only"
    if local.date().isoformat() != target_market_date:
        return "other_market_date"
    minutes = local.hour * 60 + local.minute
    if minutes < 9 * 60 + 30:
        return "before_open"
    if minutes <= 15 * 60:
        return "during_market"
    return "after_close"


def _normalized_event_title(value: Any) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(value or "").casefold())


def _is_low_signal_price_move_media(item: dict[str, Any]) -> bool:
    """Keep recurring market-statistics headlines out of causal model context."""

    title = str(item.get("title") or "")
    return bool(
        re.search(r"(?:融资买入|融资余额|融资融券)", title)
        or re.search(r"(?:股权登记|分红登记|分红力度居前)", title)
    )


def build_stock_price_move_event_evidence(
    evidence: dict[str, Any],
) -> dict[str, Any]:
    """Align public company events to the exact trading session being explained."""

    question = str(evidence.get("user_question") or "")
    market_context = evidence.get("stock_market_context") or {}
    analysis_target = market_context.get("analysis_target") or {}
    symbol = str(evidence.get("symbol") or "")
    timezone_name = (
        "Asia/Shanghai" if symbol.endswith((".SS", ".SZ")) else "America/New_York"
    )
    target_market_date = str(
        analysis_target.get("market_date")
        or (evidence.get("current_quote") or {}).get("market_date")
        or _market_date(
            (evidence.get("provenance") or {}).get("market_timestamp"),
            timezone_name,
        )
        or ""
    )
    strict_same_date_only = any(
        term in question for term in STOCK_STRICT_SAME_DATE_TERMS
    )

    raw_items: list[tuple[int, str, str, dict[str, Any]]] = []

    def extend(
        items: Iterable[dict[str, Any]] | None,
        *,
        authority_rank: int,
        evidence_kind: str,
        evidence_label: str,
    ) -> None:
        for item in items or []:
            if isinstance(item, dict) and item.get("title"):
                raw_items.append(
                    (authority_rank, evidence_kind, evidence_label, item)
                )

    information = evidence.get("a_share_information") or {}
    fundamentals = evidence.get("fundamentals") or {}
    timeline = evidence.get("event_timeline") or {}
    extend(
        information.get("announcements"),
        authority_rank=0,
        evidence_kind="official_disclosure",
        evidence_label="公司公告",
    )
    extend(
        fundamentals.get("regulatory_filings"),
        authority_rank=0,
        evidence_kind="official_disclosure",
        evidence_label="监管披露",
    )
    for item in timeline.get("events") or []:
        official = (
            item.get("evidence_level") == "official_disclosure"
            or item.get("category") == "announcement"
        )
        extend(
            [item],
            authority_rank=0 if official else 1,
            evidence_kind="official_disclosure" if official else "media_clue",
            evidence_label=(
                str(item.get("evidence_label") or "公司公告")
                if official
                else str(item.get("evidence_label") or "媒体线索")
            ),
        )
    extend(
        information.get("news"),
        authority_rank=1,
        evidence_kind="media_clue",
        evidence_label="媒体线索",
    )

    deduplicated: dict[tuple[str, str], dict[str, Any]] = {}
    for authority_rank, evidence_kind, evidence_label, item in raw_items:
        event_date = _event_market_date(item, timezone_name)
        title = str(item.get("title") or "").strip()
        key = (_normalized_event_title(title), str(event_date or ""))
        if not key[0]:
            continue
        candidate = {
            "title": title[:500],
            "source": str(
                item.get("source") or item.get("publisher") or "来源待核验"
            )[:160],
            "url": item.get("url") or item.get("source_url"),
            "published_at": item.get("published_at") or item.get("filed_at"),
            "event_date": event_date,
            "evidence_kind": evidence_kind,
            "evidence_label": evidence_label,
            "research_relevance": item.get("research_relevance"),
            "research_relevance_label": item.get("research_relevance_label"),
            "authority_rank": authority_rank,
        }
        direct_excerpt = _announcement_direct_excerpt(item)
        if direct_excerpt:
            candidate["direct_excerpt"] = direct_excerpt
        previous = deduplicated.get(key)
        if previous is None or authority_rank < int(previous["authority_rank"]):
            deduplicated[key] = candidate

    same_date_official: list[dict[str, Any]] = []
    same_date_media: list[dict[str, Any]] = []
    same_date_after_close: list[dict[str, Any]] = []
    adjacent_events: list[dict[str, Any]] = []
    for candidate in deduplicated.values():
        event_date = str(candidate.get("event_date") or "")
        date_relation = "date_unanchored"
        date_gap: int | None = None
        if target_market_date and event_date:
            try:
                date_gap = (
                    datetime.fromisoformat(event_date).date()
                    - datetime.fromisoformat(target_market_date).date()
                ).days
            except ValueError:
                date_gap = None
            if date_gap == 0:
                date_relation = "same_market_date"
            elif date_gap is not None and abs(date_gap) <= 3:
                date_relation = "adjacent_before" if date_gap < 0 else "adjacent_after"
            else:
                date_relation = "outside_target_window"
        candidate["date_relation"] = date_relation
        candidate["session_relation"] = (
            _event_session_relation(
                candidate,
                target_market_date=target_market_date,
                timezone_name=timezone_name,
            )
            if date_relation == "same_market_date"
            else "other_market_date"
        )
        candidate.pop("authority_rank", None)
        if date_relation == "same_market_date":
            if candidate["session_relation"] == "after_close":
                same_date_after_close.append(candidate)
            elif candidate["evidence_kind"] == "official_disclosure":
                same_date_official.append(candidate)
            else:
                same_date_media.append(candidate)
        elif date_relation in {"adjacent_before", "adjacent_after"}:
            adjacent_events.append(candidate)

    def newest_first(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(
            items,
            key=lambda item: str(
                item.get("published_at") or item.get("event_date") or ""
            ),
            reverse=True,
        )[:6]

    same_date_official = newest_first(same_date_official)
    same_date_media = newest_first(same_date_media)
    same_date_after_close = newest_first(same_date_after_close)
    adjacent_events = newest_first(adjacent_events)
    same_date_sources = {
        str(item.get("source") or "")
        for item in [*same_date_official, *same_date_media]
        if item.get("source")
    }
    media_sources = {
        str(item.get("source") or "")
        for item in same_date_media
        if item.get("source")
    }
    coverage_status = (
        "same_date_official_disclosure"
        if same_date_official
        else "same_date_media_multi_source"
        if len(media_sources) >= 2
        else "same_date_media_single_source"
        if same_date_media
        else "same_date_after_close_only"
        if same_date_after_close
        else "adjacent_date_only"
        if adjacent_events
        else "unavailable"
    )
    return {
        "target_market_date": target_market_date or None,
        "strict_same_date_only": strict_same_date_only,
        "coverage_status": coverage_status,
        "same_date_source_count": len(same_date_sources),
        "same_date_media_source_count": len(media_sources),
        "same_date_official_disclosures": same_date_official,
        "same_date_media_clues": same_date_media,
        "same_date_after_close_events": same_date_after_close,
        "adjacent_date_events": adjacent_events,
        "boundary": (
            "同日公告或媒体标题只能作为候选事件，仍需与价格异动时点、行业和市场对照交叉核验；"
            "收盘后发布的内容不能解释当日交易时段，邻近日事件也不能冒充同日直接原因。"
        ),
    }


def compact_stock_price_move_event_evidence(
    evidence: dict[str, Any],
) -> dict[str, Any]:
    """Keep the model prompt focused while the full evidence remains persisted.

    The user-facing citation list is built from the original evidence packet,
    so omitted prompt items remain inspectable without forcing the model to
    enumerate every same-day headline in its answer.
    """

    packet = build_stock_price_move_event_evidence(evidence)
    original_media = list(packet.get("same_date_media_clues") or [])
    model_media = [
        item for item in original_media if not _is_low_signal_price_move_media(item)
    ]
    low_signal_count = len(original_media) - len(model_media)
    compact_coverage_status = packet.get("coverage_status")
    if low_signal_count and not model_media and not packet.get(
        "same_date_official_disclosures"
    ):
        compact_coverage_status = "same_date_low_signal_background_only"
    return {
        **packet,
        "coverage_status": compact_coverage_status,
        "same_date_low_signal_background_count": low_signal_count,
        "same_date_official_disclosures": list(
            packet.get("same_date_official_disclosures") or []
        )[:2],
        "same_date_media_clues": model_media[:3],
        "same_date_media_source_count": len(
            {
                str(item.get("source") or "")
                for item in model_media
                if item.get("source")
            }
        ),
        "same_date_after_close_events": list(
            packet.get("same_date_after_close_events") or []
        )[:2],
        "adjacent_date_events": list(packet.get("adjacent_date_events") or [])[:2],
    }


def _number(value: Any, *, signed: bool = False) -> str | None:
    if not isinstance(value, (int, float)):
        return None
    text = f"{float(value):.2f}".rstrip("0").rstrip(".")
    if signed and float(value) > 0:
        return f"+{text}"
    return text


def build_stock_price_move_visible_sources(
    evidence: dict[str, Any] | None,
) -> list[dict[str, Any]] | None:
    """Return only date-aligned evidence suitable for a price-move answer UI.

    ``None`` means the packet is not a focused stock price-move question.  An
    empty list means it is focused, but no public evidence source was available.
    """

    packet = evidence or {}
    question = str(packet.get("user_question") or "")
    if packet.get("type") != "stock_research" or not is_stock_price_move_question(
        question
    ):
        return None

    display_name = str(
        packet.get("display_name") or packet.get("name") or packet.get("symbol") or "个股"
    ).strip()
    context = packet.get("stock_market_context") or {}
    target = context.get("analysis_target") or {}
    stock_target = context.get("stock_target") or {}
    event_packet = build_stock_price_move_event_evidence(packet)
    target_date = str(
        target.get("market_date") or event_packet.get("target_market_date") or ""
    )
    sources: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def add(
        kind: str,
        title: str,
        summary: str,
        *,
        as_of: Any = None,
        source: str | None = None,
        url: str | None = None,
    ) -> None:
        clean_title = str(title or "").strip()
        clean_summary = str(summary or "").strip()
        if not clean_title or not clean_summary:
            return
        key = (kind, clean_title)
        if key in seen:
            return
        seen.add(key)
        item: dict[str, Any] = {
            "kind": kind,
            "title": clean_title,
            "summary": clean_summary,
        }
        if as_of:
            item["as_of"] = str(as_of)
        if source:
            item["source"] = str(source)
        if url and re.match(r"^https?://", str(url).strip(), re.IGNORECASE):
            item["url"] = str(url).strip()
        sources.append(item)

    if stock_target.get("status") == "same_market_date":
        close = _number(stock_target.get("close"))
        change = _number(stock_target.get("return_1d_pct"), signed=True)
        parts = []
        if close is not None:
            parts.append(f"收盘 {close}")
        if change is not None:
            parts.append(f"涨跌幅 {change}%")
        add(
            "个股行情",
            f"{display_name}{target_date or '目标日'}完整日线",
            "；".join(parts) or "目标交易日完整日线已取得",
            as_of=stock_target.get("market_date") or target_date,
            source="个股完整日线",
        )
    else:
        quote = packet.get("current_quote") or {}
        quote_date = str(quote.get("market_date") or "")
        if not target_date or not quote_date or quote_date == target_date:
            price = _number(quote.get("price"))
            change = _number(quote.get("pct_change"), signed=True)
            parts = []
            if price is not None:
                parts.append(f"价格 {price}")
            if change is not None:
                parts.append(f"涨跌幅 {change}%")
            if parts:
                add(
                    "个股行情",
                    f"{display_name}{target_date or '目标日'}行情快照",
                    "；".join(parts),
                    as_of=quote.get("market_timestamp") or quote_date,
                    source="个股行情快照",
                )

    index_parts: list[str] = []
    for item in context.get("indices") or []:
        if not isinstance(item, dict):
            continue
        item_date = str(item.get("market_date") or "")
        if item.get("comparison_status") not in {None, "same_market_date"}:
            continue
        if target_date and item_date and item_date != target_date:
            continue
        change = _number(
            item.get("return_1d_pct")
            if item.get("return_1d_pct") is not None
            else (item.get("metrics") or {}).get("return_1d_pct"),
            signed=True,
        )
        if change is not None:
            index_parts.append(f"{item.get('name') or item.get('symbol')} {change}%")
    if index_parts:
        add(
            "市场对照",
            f"{target_date or '目标日'}代表性指数",
            "；".join(index_parts[:4]),
            as_of=target_date,
            source="指数完整日线",
        )

    breadth_packet = context.get("market_breadth") or packet.get("market_breadth") or {}
    breadth = breadth_packet.get("breadth") or {}
    if breadth and breadth_packet.get("same_date_as_target") is not False:
        parts = []
        for key, label in (
            ("advancers", "上涨"),
            ("decliners", "下跌"),
            ("unchanged", "平盘"),
        ):
            if breadth.get(key) is not None:
                parts.append(f"{label} {breadth[key]} 家")
        if parts:
            add(
                "市场广度",
                f"{target_date or '目标日'}A股全市场广度",
                "；".join(parts),
                as_of=breadth_packet.get("market_date") or target_date,
                source="沪深京全市场快照",
            )

    industry = context.get("exact_industry_index") or {}
    if industry.get("status") == "same_market_date":
        parts = []
        change = _number(industry.get("return_1d_pct"), signed=True)
        spread = _number(industry.get("stock_minus_industry_pct"), signed=True)
        if change is not None:
            parts.append(f"行业涨跌幅 {change}%")
        if spread is not None:
            parts.append(f"个股相对行业 {spread} 个百分点")
        component_breadth = industry.get("component_breadth") or {}
        if component_breadth.get("status") == "available":
            counts = []
            for key, label in (
                ("advancers", "上涨"),
                ("decliners", "下跌"),
                ("unchanged", "平盘"),
            ):
                if component_breadth.get(key) is not None:
                    counts.append(f"{label} {component_breadth[key]} 家")
            if counts:
                parts.append("成分股" + "、".join(counts))
        if parts:
            add(
                "行业对照",
                f"{target_date or '目标日'}{industry.get('name') or '精确行业'}",
                "；".join(parts),
                as_of=industry.get("market_date") or target_date,
                source="精确行业指数与成分广度",
                url=industry.get("source_url"),
            )

    for item in event_packet.get("same_date_official_disclosures") or []:
        direct_excerpt = str(item.get("direct_excerpt") or "").strip()
        add(
            "同日公告",
            str(item.get("title") or "同日公司公告"),
            (
                f"公司公告原文摘录：{direct_excerpt}；"
                "该披露存在不等于已证明价格因果。"
                if direct_excerpt
                else "目标交易时段内可见的公司或监管披露；"
                "公告标题存在不等于已证明价格因果。"
            ),
            as_of=item.get("published_at") or item.get("event_date"),
            source=str(item.get("source") or item.get("evidence_label") or "公司披露"),
            url=item.get("url"),
        )
    for item in event_packet.get("same_date_media_clues") or []:
        session_label = {
            "before_open": "开盘前发布",
            "during_market": "交易时段发布",
            "date_only": "仅确认同日发布",
        }.get(str(item.get("session_relation") or ""), "同日发布")
        add(
            "同日线索",
            str(item.get("title") or "同日媒体线索"),
            f"{session_label}；仅作为待核验线索，不能直接证明涨跌原因。",
            as_of=item.get("published_at") or item.get("event_date"),
            source=str(item.get("source") or "公开资讯线索"),
            url=item.get("url"),
        )
    for item in event_packet.get("same_date_after_close_events") or []:
        add(
            "收盘后边界",
            str(item.get("title") or "收盘后事件"),
            "发布时间晚于当日收盘，不能解释该交易日盘中价格变化。",
            as_of=item.get("published_at") or item.get("event_date"),
            source=str(item.get("source") or "公开资讯线索"),
            url=item.get("url"),
        )

    if not any(
        event_packet.get(key)
        for key in (
            "same_date_official_disclosures",
            "same_date_media_clues",
            "same_date_after_close_events",
        )
    ):
        add(
            "事件边界",
            f"{target_date or '目标日'}公司事件覆盖",
            "未取得同日公司公告或开盘前、交易时段媒体线索；具体公司驱动仍未确认。",
            as_of=target_date,
            source="同日公开信息检索",
        )

    return sources[:10]


def _announcement_direct_excerpt(item: dict[str, Any]) -> str:
    direct_excerpt = re.sub(
        r"\s+", " ", str(item.get("direct_excerpt") or "")
    ).strip()
    if direct_excerpt:
        return direct_excerpt[:1200]
    summary = re.sub(r"\s+", " ", str(item.get("summary") or "")).strip()
    prefix = "公司公告原文摘录："
    if summary.startswith(prefix):
        return summary[len(prefix) :].strip()[:1200]
    return ""
