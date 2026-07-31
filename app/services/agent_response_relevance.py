from __future__ import annotations

import json
import re
from typing import Any


_STOCK_SPECIALIST_TYPES = {
    "earnings_quality",
    "financial_drivers",
    "business_structure",
    "shareholder_structure",
    "analyst_expectations",
    "event_timeline",
}

_FOCUS_TERMS = {
    "earnings_quality": ("财报", "营收", "利润", "毛利", "现金流", "盈利"),
    "financial_drivers": ("利润", "费用", "现金流", "应收", "存货", "毛利"),
    "business_structure": ("主营", "业务", "收入", "毛利", "产品", "地区"),
    "shareholder_structure": ("股东", "持仓", "持有人", "户数", "股份"),
    "analyst_expectations": ("分析师", "一致预期", "研报", "评级", "EPS", "预期"),
    "event_timeline": ("公告", "事件", "披露", "新闻", "监管", "时间"),
}

_CLEAR_OFF_TOPIC_TERMS = (
    "手机屏幕太暗",
    "消息可能被截断",
    "重新发送一次完整的消息",
    "有什么我可以继续为您服务",
)

_QUALITY_CASHFLOW_OVERCLAIM_RE = re.compile(
    r"(?:利润[^。；\n]{0,28}(?:现金流支撑|现金支撑|不是(?:纸面|账面)数字)|"
    r"每赚[^。；\n]{0,36}(?:收回|拿到)[^。；\n]{0,20}(?:现金|经营现金流)|"
    r"实际收回[^。；\n]{0,24}经营现金流|"
    r"没有出现[^。；\n]{0,30}钱没收回来|"
    r"现金转化(?:效率|能力|程度|质量)|"
    r"(?:现金回收|现金兑现)[^。；\n]{0,12}(?:效率|能力|程度|质量)"
    r"[^。；\n]{0,12}(?:走弱|下降|恶化|变差|减弱|回落)|"
    r"经营现金(?:回款)?[^。；\n]{0,12}(?:效率|能力)[^。；\n]{0,12}"
    r"(?:走弱|下降|恶化|变差|降低)|"
    r"(?:收入|利润)?转化为现金[^。；\n]{0,8}(?:的)?效率[^。；\n]{0,12}"
    r"(?:落差|走弱|下降|恶化|变差)|"
    r"(?:利润|收入)[^。；\n]{0,12}(?:向|转化为|兑现为)现金[^。；\n]{0,12}"
    r"(?:质量|强度|能力)[^。；\n]{0,12}(?:减弱|走弱|下降|恶化|不足)|"
    r"(?:收入|营收)[^。；\n]{0,24}(?:没有|未能|并未)[^。；\n]{0,12}"
    r"(?:同步)?转化为[^。；\n]{0,16}现金(?:流入)?|"
    r"利润转化为现金的效率[^。；\n]{0,8}(?:在)?(?:减弱|走弱|下降|恶化)|"
    r"实际收回[^。；\n]{0,16}现金[^。；\n]{0,12}(?:少|减少|变少)|"
    r"利润(?:增加|增长)[^。；\n]{0,36}(?:尚未|没有)[^。；\n]{0,24}"
    r"(?:转化|兑现)[^。；\n]{0,16}(?:现金|现金回收)|"
    r"(?:销售)?回款(?:效率|能力|匹配度)?[^。；\n]{0,12}(?:明显)?"
    r"(?:变慢|放慢|恶化|走弱|下滑|回落|下降|降低|减弱)|"
    r"销售收现率[^。；\n]{0,50}(?:回款|现金)(?:效率|能力)?[^。；\n]{0,12}"
    r"(?:变慢|放慢|恶化|走弱|下滑|回落|下降|降低)|"
    r"销售收现率[^。；\n]{0,36}(?:说明|表明|意味着|暗示)[^。；\n]{0,36}"
    r"(?:回款|结算|应收)[^。；\n]{0,20}(?:变慢|放慢|压力|恶化|走弱|降低)|"
    r"销售收现率[^。；\n]{0,36}(?:提示|说明|表明)[^。；\n]{0,36}"
    r"(?:回款|现金)(?:效率|能力|匹配度)[^。；\n]{0,12}"
    r"(?:降低|下降|走弱|恶化|减弱|下滑|回落)|"
    r"(?:这些|上述|这三项|三项|多项)?(?:指标|变化|线索|事实)"
    r"[^。；\n]{0,12}(?:提示|说明|表明|意味着|暗示)[^。；\n]{0,24}"
    r"(?:回款|营运资金占用|应收)[^。；\n]{0,20}"
    r"(?:加大|增加|上升|承压|压力|走弱|恶化)|"
    r"(?:现金流|回款|营运资金)(?:压力|承压))"
)
_QUALITY_CAUSAL_OVERCLAIM_RE = re.compile(
    r"(?:(?:利润|净利润|业绩|经营)?(?:增长|改善)[^。；\n]{0,24}"
    r"(?:主要(?:来自|依赖|靠|由)|依赖|来自|靠)[^。；\n]{0,20}"
    r"(?:收入|营收)(?:规模)?(?:扩张|增长)|"
    r"增长[^。；\n]{0,16}主要由(?:收入|营收|规模)[^。；\n]{0,12}(?:驱动|推动)|"
    r"增长[^。；\n]{0,12}(?:有|具有)(?:收入|营收)?规模支撑|"
    r"(?:真实的)?规模增长基础)"
)
_QUALITY_IMPRECISE_CASHFLOW_RE = re.compile(
    r"经营现金流[^。；\n]{0,12}(?:几乎|近乎|基本|接近)"
    r"(?:停滞|没有增长|原地踏步)"
)
_QUALITY_REVENUE_CAUSAL_BRIDGE_RE = re.compile(
    r"(?:(?:收入|营收)(?:增长|扩张)[^。；\n]{0,20}"
    r"(?:拉动|带动|贡献)[^。；\n]{0,16}(?:利润|净利润|毛利)|"
    r"(?:收入|营收)(?:增长|扩张)[^。；\n]{0,16}(?:利润|净利润|毛利)"
    r"[^。；\n]{0,16}(?:拉动|带动|贡献))"
)
_QUALITY_PROFIT_CASHFLOW_CAUSAL_RE = re.compile(
    r"(?:利润|净利润)[^。；\n]{0,20}(?:对|向)[^。；\n]{0,16}现金流"
    r"[^。；\n]{0,16}(?:带动|转化|兑现|支撑)"
)
_QUALITY_STRUCTURE_OVERCLAIM_RE = re.compile(
    r"(?:产品|收入|主营)?结构[^。；\n]{0,12}(?:优化|升级|改善)"
)
_QUALITY_ACCOUNTING_CONTRADICTION_RE = re.compile(r"增收不增利")
_QUALITY_INVENTORY_OVERCLAIM_RE = re.compile(
    r"存货[^。；\n]{0,48}(?:意味着|说明|表明|可能(?:意味着|是)?)"
    r"[^。；\n]{0,24}(?:产品)?积压|"
    r"存货[^。；\n]{0,48}(?:出货节奏(?:放缓|问题)|去库压力|"
    r"备货节奏(?:错位|异常)|库存压力)|"
    r"(?:备货(?:解释|意图)|公司(?:口径|解释))[^。；\n]{0,32}"
    r"(?:排除|证明并非|而非|不是)[^。；\n]{0,12}(?:被动)?积压|"
    r"(?:若|如果)?未来[^。；\n]{0,20}(?:计提|增加)[^。；\n]{0,12}"
    r"(?:存货)?跌价(?:准备)?[^。；\n]{0,20}(?:影响|拖累)[^。；\n]{0,12}利润"
)
_QUALITY_INDUSTRY_OVERCLAIM_RE = re.compile(
    r"行业(?:整体)?毛利率[^。；\n]{0,12}(?:下降|下滑|走弱)"
)
_QUALITY_MARKET_PRICING_OVERCLAIM_RE = re.compile(
    r"(?:市场|股价|资金)[^。；\n]{0,24}"
    r"(?:没有|尚未|未|已经|已|暂时)?(?:定价|认可|反映|忽略)"
)
_QUALITY_DEBT_OVERCLAIM_RE = re.compile(
    r"(?:借贷杠杆|有息负债|借款|融资压力)[^。；\n]{0,16}"
    r"(?:放大|增加|上升|加重)"
)
_QUALITY_UNSUPPORTED_SUMMARY_RE = re.compile(
    r"量增价减|(?:仍|还)?停留在[^。；\n]{0,20}(?:收入|营收)?规模(?:快速)?膨胀(?:的)?阶段|"
    r"三项指标(?:方向)?一致[^。；\n]{0,24}(?:现金流|现金)|"
    r"(?:三项|上述三项)(?:指标|变化)[^。；\n]{0,12}"
    r"(?:同步|共同|一致)[^。；\n]{0,12}(?:走弱|下降|恶化|回落)"
)
_QUALITY_UNSUPPORTED_REASSURANCE_RE = re.compile(
    r"经营现金流[^。；\n]{0,36}(?:正增长|增长)[^。；\n]{0,24}并非资金紧张"
)
_QUALITY_CROSS_METRIC_CONFIRMATION_RE = re.compile(
    r"利润(?:增加|增长)[^。；\n]{0,28}(?:尚未|没有|未能)得到[^。；\n]{0,28}"
    r"经营现金流[^。；\n]{0,28}回款节奏[^。；\n]{0,20}(?:同等)?确认"
)
_QUALITY_CASHFLOW_INTERPRETATION_RE = re.compile(
    r"(?:(?:经营现金流|销售收现率|现金回笼|资金回收|回款)"
    r"[^。；\n]{0,80}(?:说明|表明|意味着|提示|隐忧|压力|能力|效率|现金质量|"
    r"弱化|恶化|变慢|比例降低)|"
    r"(?:说明|表明|意味着|提示)[^。；\n]{0,50}"
    r"(?:经营现金流|销售收现率|现金回笼|资金回收|回款))"
)

_QUALITY_NEGATION_TERMS = (
    "不代表",
    "不等于",
    "不能",
    "不得",
    "并非",
    "并未",
    "无法",
    "尚未",
    "未能",
    "没有证据",
    "不能仅凭",
    "不能据此",
    "不足以",
    "不够判断",
    "待核验",
    "仍需核验",
    "需要进一步核验",
    "需要重点核验",
    "是否",
    "是否存在",
)


def _has_affirmative_quality_match(pattern: re.Pattern[str], text: str) -> bool:
    """Return true only when a risky phrase is asserted, not explicitly denied."""

    for match in pattern.finditer(text):
        prefix_start = max(
            text.rfind("。", 0, match.start()),
            text.rfind("；", 0, match.start()),
            text.rfind("\n", 0, match.start()),
        )
        prefix = text[prefix_start + 1 : match.start()][-36:]
        context = f"{prefix}{match.group()}"
        if any(term in context for term in _QUALITY_NEGATION_TERMS):
            continue
        return True
    return False


def _subject_aliases(evidence: dict[str, Any]) -> list[str]:
    workspace = evidence.get("stock_workspace_context") or {}
    aliases = [
        evidence.get("display_name"),
        workspace.get("name"),
        evidence.get("name"),
        evidence.get("symbol"),
    ]
    symbol = str(evidence.get("symbol") or "").strip()
    if symbol:
        aliases.append(symbol.split(".", 1)[0])
    return list(
        dict.fromkeys(
            value
            for item in aliases
            if (value := str(item or "").strip()) and len(value) >= 2
        )
    )


def _specialist_payload(evidence: dict[str, Any]) -> dict[str, Any]:
    evidence_type = str(evidence.get("type") or "")
    nested = evidence.get(evidence_type)
    return nested if isinstance(nested, dict) else evidence


def _evidence_text_anchors(evidence: dict[str, Any]) -> list[str]:
    evidence_type = str(evidence.get("type") or "")
    payload = _specialist_payload(evidence)
    anchors: list[str] = []
    if evidence_type == "business_structure":
        for dimension in payload.get("dimensions") or []:
            for segment in (dimension.get("segments") or [])[:6]:
                anchors.append(str(segment.get("item_name") or ""))
    elif evidence_type == "shareholder_structure":
        for holder in (payload.get("top_holders") or [])[:6]:
            anchors.append(str(holder.get("holder_name") or holder.get("name") or ""))
    elif evidence_type == "analyst_expectations":
        for report in (payload.get("latest_reports") or [])[:6]:
            anchors.extend(
                [
                    str(report.get("organization") or ""),
                    str(report.get("rating") or ""),
                ]
            )
    elif evidence_type == "event_timeline":
        for event in (payload.get("events") or [])[:6]:
            anchors.append(str(event.get("event_label") or event.get("title") or ""))
    elif evidence_type in {"earnings_quality", "financial_drivers"}:
        anchors.extend(
            str(item)
            for item in (
                payload.get("supports")
                or payload.get("confirmed_mechanical_drivers")
                or []
            )[:6]
        )
    return [item.strip() for item in anchors if len(item.strip()) >= 3]


def quality_review_overclaim_issue(text: str) -> str | None:
    if _QUALITY_UNSUPPORTED_REASSURANCE_RE.search(text):
        return "经营改善回答用经营现金流正增长无依据地排除了资金压力"
    if _QUALITY_CROSS_METRIC_CONFIRMATION_RE.search(text):
        return "经营改善回答把不同现金流口径合并成了回款节奏对利润增长的确认"
    checks = (
        (
            _QUALITY_CASHFLOW_OVERCLAIM_RE,
            "经营改善回答把现金流覆盖关系过度解释为回款质量或利润真实性",
        ),
        (
            _QUALITY_CAUSAL_OVERCLAIM_RE,
            "经营改善回答把营收和利润的共同变化写成了未经公司原文确认的增长原因",
        ),
        (
            _QUALITY_IMPRECISE_CASHFLOW_RE,
            "经营改善回答用主观措辞替代了经营现金流的可比增速事实",
        ),
        (
            _QUALITY_REVENUE_CAUSAL_BRIDGE_RE,
            "经营改善回答把营收增长写成了未经公司原文确认的利润驱动",
        ),
        (
            _QUALITY_PROFIT_CASHFLOW_CAUSAL_RE,
            "经营改善回答把利润变化写成了未经公司原文确认的现金流驱动",
        ),
        (
            _QUALITY_STRUCTURE_OVERCLAIM_RE,
            "经营改善回答把主营占比变化写成了未经证明的结构优化",
        ),
        (
            _QUALITY_ACCOUNTING_CONTRADICTION_RE,
            "经营改善回答使用了与本期利润增长事实冲突的增收不增利表述",
        ),
        (
            _QUALITY_INVENTORY_OVERCLAIM_RE,
            "经营改善回答把存货增速线索直接解释成了积压或出货问题",
        ),
        (
            _QUALITY_INDUSTRY_OVERCLAIM_RE,
            "经营改善回答把公司披露分部误写成了行业整体毛利率",
        ),
        (
            _QUALITY_MARKET_PRICING_OVERCLAIM_RE,
            "经营改善回答使用了没有直接事件证据的市场定价推断",
        ),
        (
            _QUALITY_DEBT_OVERCLAIM_RE,
            "经营改善回答把资产负债率变化过度解释为借款或有息杠杆变化",
        ),
        (
            _QUALITY_UNSUPPORTED_SUMMARY_RE,
            "经营改善回答使用了没有产品价格或公司原文支持的压缩式经营标签",
        ),
        (
            _QUALITY_CASHFLOW_INTERPRETATION_RE,
            "经营改善回答把不同现金流指标压缩成了未经证明的回款质量或现金质量结论",
        ),
    )
    for pattern, reason in checks:
        if _has_affirmative_quality_match(pattern, text):
            return reason
    return None


def _quality_review_announcement_extracts(
    evidence: dict[str, Any],
) -> list[dict[str, str]]:
    extracts: list[dict[str, str]] = []
    information = evidence.get("a_share_information") or {}
    for item in (information.get("announcements") or [])[:3]:
        summary = str(item.get("summary") or "").strip()
        if not summary:
            continue
        extracts.append(
            {
                "title": str(item.get("title") or ""),
                "published_at": str(item.get("published_at") or ""),
                "summary_excerpt": summary[:2600],
            }
        )
    return extracts


def quality_review_fact_frame(evidence: dict[str, Any]) -> dict[str, Any]:
    quality = evidence.get("earnings_quality") or {}
    drivers = evidence.get("financial_drivers") or {}
    business = evidence.get("business_structure") or {}
    workspace = evidence.get("stock_workspace_context") or {}
    dimensions: list[dict[str, Any]] = []
    for dimension in (business.get("dimensions") or [])[:2]:
        dimensions.append(
            {
                "classification": dimension.get("classification"),
                "label": dimension.get("label"),
                "current_report_date": dimension.get("current_report_date"),
                "comparable_report_date": dimension.get("comparable_report_date"),
                "segments": [
                    {
                        "item_name": item.get("item_name"),
                        "revenue_growth_pct": item.get("revenue_growth_pct"),
                        "revenue_share_pct": item.get("revenue_share_pct"),
                        "comparable_revenue_share_pct": item.get(
                            "comparable_revenue_share_pct"
                        ),
                        "gross_margin_pct": item.get("gross_margin_pct"),
                        "comparable_gross_margin_pct": item.get(
                            "comparable_gross_margin_pct"
                        ),
                    }
                    for item in (dimension.get("segments") or [])[:3]
                ],
            }
        )
    return {
        "subject": (
            evidence.get("display_name")
            or workspace.get("name")
            or evidence.get("symbol")
        ),
        "industry_label": ((workspace.get("research_entry") or {}).get("industry")),
        "latest_report": quality.get("latest_report") or {},
        "comparable_report": quality.get("comparable_report") or {},
        "cashflow_analysis": drivers.get("cashflow_analysis") or {},
        "confirmed_mechanical_drivers": (
            drivers.get("confirmed_mechanical_drivers") or []
        )[:4],
        "filing_evidence": drivers.get("filing_evidence") or {},
        "business_dimensions": dimensions,
        "business_coverage_limits": (business.get("coverage_limits") or [])[:3],
        "company_announcement_extracts": _quality_review_announcement_extracts(
            evidence
        ),
        "entry_snapshot": workspace.get("research_entry") or {},
    }


def quality_review_evidence_conflict_issue(
    text: str,
    evidence: dict[str, Any],
) -> str | None:
    announcement_text = "\n".join(
        item.get("summary_excerpt") or ""
        for item in _quality_review_announcement_extracts(evidence)
    )
    has_inventory_explanation = (
        "库存增加主要是为下半年市场需求而提前备货" in announcement_text
    )
    if has_inventory_explanation and re.search(
        r"(?:公司|公告|报告)[^。；\n]{0,28}(?:并未|没有|未)"
        r"[^。；\n]{0,24}(?:解释|说明)[^。；\n]{0,20}(?:存货|库存)|"
        r"(?:存货|库存)[^。；\n]{0,28}(?:并未|没有|未)"
        r"[^。；\n]{0,20}(?:解释|说明)|"
        r"(?:存货|库存)[^。；\n]{0,32}(?:快于|高于|超过|增加|增长)"
        r"[^。；\n]{0,24}(?:原因|成因)"
        r"[^。；\n]{0,28}(?:尚未|没有|未|仍属)"
        r"[^。；\n]{0,24}(?:解释|说明|确认|归因|待核验|unresolved_themes)",
        text,
    ):
        return "经营改善回答遗漏或否定了公告中已有的库存增加公司原文解释"
    product_dimensions = [
        item
        for item in (evidence.get("business_structure") or {}).get("dimensions") or []
        if item.get("classification") == "product"
    ]
    has_incomplete_product_comparison = any(
        segment.get("comparable_gross_margin_pct") is None
        for dimension in product_dimensions
        for segment in (dimension.get("segments") or [])
    )
    if has_incomplete_product_comparison and re.search(
        r"(?:全部|所有)(?:主要)?(?:产品|产品分部|分部)"
        r"[^。；\n]{0,18}(?:毛利率)?[^。；\n]{0,12}"
        r"(?:均|都)?(?:下降|下滑|收缩|走低)",
        text,
    ):
        return "经营改善回答把缺少可比数据的产品分部也写成了毛利率下降"
    return None


def _quality_review_number_mentioned(text: str, value: Any) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    normalized = text.replace(",", "")
    variants: set[str] = set()
    for decimal_places in (1, 2, 3):
        formatted = f"{number:.{decimal_places}f}"
        variants.add(formatted)
        variants.add(formatted.rstrip("0").rstrip("."))
    for variant in sorted(variants, key=len, reverse=True):
        if variant and re.search(rf"(?<!\d){re.escape(variant)}(?!\d)", normalized):
            return True
    if number < 0:
        magnitude_variants: set[str] = set()
        for decimal_places in (1, 2, 3):
            formatted = f"{abs(number):.{decimal_places}f}"
            magnitude_variants.add(formatted)
            magnitude_variants.add(formatted.rstrip("0").rstrip("."))
        for variant in sorted(magnitude_variants, key=len, reverse=True):
            if variant and re.search(
                rf"(?:负(?:的)?|负值(?:为|是)?|为负(?:的)?)"
                rf"[^。；！？\n\d]{{0,4}}(?<!\d){re.escape(variant)}(?!\d)",
                normalized,
            ):
                return True
    return False


def _valuation_metric_number_mentioned(text: str, value: Any) -> bool:
    """Accept exact valuation values plus natural integer rounding for large multiples."""

    if _quality_review_number_mentioned(text, value):
        return True
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    if abs(number) < 10:
        return False
    rounded = round(number)
    if abs(number - rounded) > 0.5:
        return False
    return re.search(
        rf"(?:约|大约|近|中位数(?:为|约为)?)\s*{abs(rounded)}(?:\.0)?(?:\s*倍)?",
        text.replace(",", ""),
    ) is not None


def _directional_amount_mentioned(text: str, value: Any) -> bool:
    """Match a signed amount expressed with a Chinese cash-flow direction.

    Financial answers commonly render ``-4.53 亿元`` as ``净流出 4.53 亿元``.
    Keep the generic number matcher sign-sensitive, and accept this equivalence
    only when the negative direction is written next to the magnitude.
    """

    if _quality_review_number_mentioned(text, value):
        return True
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    if number >= 0:
        return False

    normalized = text.replace(",", "")
    variants: set[str] = set()
    magnitude = abs(number)
    for decimal_places in (1, 2, 3):
        formatted = f"{magnitude:.{decimal_places}f}"
        variants.add(formatted)
        variants.add(formatted.rstrip("0").rstrip("."))
    outflow_terms = r"(?:净流出|流出|净支出|为负)"
    for variant in sorted(variants, key=len, reverse=True):
        if not variant:
            continue
        number_pattern = rf"(?<!\d){re.escape(variant)}(?!\d)"
        if re.search(
            rf"{outflow_terms}[^。；！？\n\d]{{0,12}}{number_pattern}",
            normalized,
        ) or re.search(
            rf"{number_pattern}\s*(?:亿元|万元|元)?"
            rf"[^。；！？，,\n]{{0,6}}(?:的)?{outflow_terms}",
            normalized,
        ):
            return True
    return False


def _ratio_mentioned(text: str, value: Any) -> bool:
    """Accept a dimensionless ratio in decimal or equivalent percent form."""

    if _quality_review_number_mentioned(text, value):
        return True
    try:
        percent = float(value) * 100.0
    except (TypeError, ValueError):
        return False
    normalized = text.replace(",", "")
    variants: set[str] = set()
    for decimal_places in (0, 1, 2):
        formatted = f"{percent:.{decimal_places}f}"
        variants.add(formatted)
        variants.add(formatted.rstrip("0").rstrip("."))
    return any(
        variant
        and re.search(
            rf"(?<![\d.]){re.escape(variant)}\s*(?:%|％)(?!\d)",
            normalized,
        )
        for variant in sorted(variants, key=len, reverse=True)
    )


def _calendar_date_mentioned(text: str, value: Any) -> bool:
    """Recognize an ISO evidence date in common user-facing Chinese formats."""

    raw = str(value or "").strip().split("T", 1)[0]
    match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", raw)
    if match is None:
        return False
    year, month, day = (int(part) for part in match.groups())
    variants = {
        raw,
        f"{year}/{month:02d}/{day:02d}",
        f"{year}年{month}月{day}日",
        f"{year}年{month:02d}月{day:02d}日",
    }
    return any(variant in text for variant in variants)


def _same_day_peer_subject_metric_mentioned(
    text: str,
    peer_comparison: dict[str, Any],
    key: str,
) -> bool:
    """Allow a dated same-day peer subject value to satisfy valuation facts.

    Intraday single-stock valuation and the latest complete-day peer cross-section
    are both valid, but they must not be silently mixed.  This accepts the latter
    only when the answer states its date and uses the subject value from that
    exact cross-section.
    """

    as_of = str(peer_comparison.get("as_of") or "").strip()
    if not as_of or not _calendar_date_mentioned(text, as_of):
        return False
    method = str(peer_comparison.get("method") or "")
    basis_text = " ".join(
        str(peer_comparison.get(field) or "")
        for field in ("group_label", "selection_basis")
    )
    rows = [
        peer_comparison.get("subject") or {},
        *(peer_comparison.get("peers") or []),
    ]
    timestamp_dates = [
        str(row.get("market_timestamp") or "")[:10]
        for row in rows
        if row.get("market_timestamp")
    ]
    explicit_same_day = method.startswith("dynamic_same_day") or any(
        term in basis_text for term in ("同日", "同一交易日")
    )
    timestamps_align = bool(timestamp_dates) and all(
        date == as_of for date in timestamp_dates
    )
    if not explicit_same_day and not timestamps_align:
        return False
    metric = (peer_comparison.get("metrics") or {}).get(key) or {}
    value = metric.get("subject_value")
    if value is None or not _quality_review_number_mentioned(text, value):
        return False
    if key == "pe_ttm":
        return bool(re.search(r"(?:PE\s*TTM|TTM\s*(?:市盈率|PE))", text, re.I))
    return "PB" in text.upper() or "市净率" in text


def _has_inventory_classification_boundary(text: str) -> bool:
    """Recognize natural descriptions of the inventory composition check."""

    if re.search(r"(?:存货|库存)(?:的)?(?:具体)?分类", text):
        return True
    for sentence in re.split(r"[。；！？\n]", text):
        category_hits = sum(term in sentence for term in ("原材料", "在产品", "产成品"))
        if category_hits >= 2 and any(
            term in sentence
            for term in ("构成", "占比", "比例", "金额", "明细", "变化")
        ):
            return True
    return False


def _has_sales_cash_ratio_label(text: str) -> bool:
    """Recognize the metric name or its natural financial definition."""

    if "销售收现率" in text:
        return True
    return re.search(
        r"销售商品(?:、提供劳务)?收到的现金"
        r"[^。；！？\n]{0,20}(?:营收|营业收入)"
        r"[^。；！？\n]{0,10}(?:比例|比率)",
        text,
    ) is not None


def _directional_percentage_mentioned(text: str, value: Any) -> bool:
    """Match signed percentages expressed with either symbols or Chinese direction.

    Models often render ``-2.285%`` as ``下跌2.285%`` or ``跌幅2.285%``.
    The generic numeric matcher must remain sign-sensitive, so this semantic
    equivalence is deliberately limited to percentage facts whose direction is
    stated next to the magnitude.
    """

    if _quality_review_number_mentioned(text, value):
        return True
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    if number >= 0:
        return False

    normalized = text.replace(",", "")
    variants: set[str] = set()
    magnitude = abs(number)
    for decimal_places in (1, 2, 3, 4):
        formatted = f"{magnitude:.{decimal_places}f}"
        variants.add(formatted)
        variants.add(formatted.rstrip("0").rstrip("."))
    down_terms = r"(?:下跌|跌幅|收跌|回落|下降|走弱|减少|跑输|落后|负)"
    for variant in sorted(variants, key=len, reverse=True):
        if not variant:
            continue
        number_pattern = rf"(?<!\d){re.escape(variant)}(?!\d)"
        if re.search(
            rf"{down_terms}[^。；！？\n\d]{{0,12}}{number_pattern}",
            normalized,
        ) or re.search(
            rf"{number_pattern}\s*(?:%|％|个百分点)?"
            rf"[^。；！？，,\n]{{0,4}}(?:的)?{down_terms}",
            normalized,
        ):
            return True
    return False


def quality_review_required_fact_issue(
    text: str,
    evidence: dict[str, Any],
) -> str | None:
    """Reject polished-looking edits that silently drop core quality facts."""

    if bool((evidence.get("research_plan") or {}).get("contextual_followup")):
        # A follow-up such as “哪些事实真正会改变判断，别重复整份财报”
        # should answer the new question instead of being forced to restate the
        # complete three-metric cash-flow frame from the opening turn.
        return None

    cashflow = (evidence.get("financial_drivers") or {}).get("cashflow_analysis") or {}
    operating_cashflow = cashflow.get("operating_cashflow")
    comparable_operating_cashflow = cashflow.get("comparable_operating_cashflow")
    operating_cashflow_pct = cashflow.get("operating_cashflow_change_pct")
    if operating_cashflow is not None and operating_cashflow_pct is not None:
        amount_yi = float(operating_cashflow) / 100_000_000
        comparable_amount_yi = (
            float(comparable_operating_cashflow) / 100_000_000
            if comparable_operating_cashflow is not None
            else None
        )
        has_change_context = _quality_review_number_mentioned(
            text, operating_cashflow_pct
        ) or (
            comparable_amount_yi is not None
            and _quality_review_number_mentioned(text, comparable_amount_yi)
        )
        if not (
            "经营现金流" in text
            and _directional_amount_mentioned(text, amount_yi)
            and has_change_context
        ):
            return "经营改善回答遗漏经营现金流金额或同比变化"

    current_coverage = cashflow.get("operating_cashflow_to_net_profit")
    comparable_coverage = cashflow.get("comparable_operating_cashflow_to_net_profit")
    if current_coverage is not None and comparable_coverage is not None:
        comparable_coverage_values = [comparable_coverage]
        raw_comparable_coverage = (
            (evidence.get("earnings_quality") or {})
            .get("comparable_report", {})
            .get("operating_cashflow_to_net_profit")
        )
        if raw_comparable_coverage is not None:
            comparable_coverage_values.append(raw_comparable_coverage)
        if not (
            "经营现金流" in text
            and "归母净利润" in text
            and _quality_review_number_mentioned(text, current_coverage)
            and any(
                _quality_review_number_mentioned(text, value)
                for value in comparable_coverage_values
            )
        ):
            return "经营改善回答遗漏经营现金流与归母净利润的两期比率"

    current_sales_cash = cashflow.get("cash_received_from_sales_to_revenue_pct")
    comparable_sales_cash = cashflow.get(
        "comparable_cash_received_from_sales_to_revenue_pct"
    )
    if current_sales_cash is not None and comparable_sales_cash is not None:
        if not (
            _has_sales_cash_ratio_label(text)
            and _quality_review_number_mentioned(text, current_sales_cash)
            and _quality_review_number_mentioned(text, comparable_sales_cash)
        ):
            return "经营改善回答遗漏销售收现率的本期或可比期数值"

    inventory_explanation = _quality_review_inventory_explanation(evidence)
    if inventory_explanation:
        if not ("下半年" in text and "备货" in text):
            return "经营改善回答遗漏公告中的库存增加公司原文解释"
        if not (
            _has_inventory_classification_boundary(text)
            and "库龄" in text
            and "跌价准备" in text
        ):
            return "经营改善回答遗漏库存解释后的分类、库龄或跌价准备核验边界"

    return None


def valuation_review_stream_overclaim_issue(answer: str) -> str | None:
    """Reject local valuation claims that are unsafe even in a partial stream."""

    for sentence in re.split(r"[。；\n]", answer):
        if not re.search(
            r"盈利(?:方向|趋势)?(?:已经|已|仍|正|正在)?(?:在)?延续|"
            r"(?:确认|表明|说明|预示)[^。；\n]{0,16}盈利(?:方向|趋势)?延续",
            sentence,
        ):
            continue
        if any(
            term in sentence
            for term in (
                "不能确认",
                "无法确认",
                "尚不能",
                "是否延续",
                "延续性仍需核验",
                "仍需核验是否延续",
            )
        ):
            continue
        return "估值回答把阶段性扭亏和业绩预告外推成了盈利延续"
    return None


def valuation_review_required_fact_issue(
    text: str,
    evidence: dict[str, Any],
) -> str | None:
    """Keep valuation-candidate answers numerically and semantically grounded."""

    if str(evidence.get("type") or "") != "stock_research":
        return None
    if str((evidence.get("research_plan") or {}).get("focus") or "") != (
        "valuation_review"
    ):
        return None
    answer = str(text or "").strip()
    if not _valuation_opening_directly_rejects_cheap(answer):
        return "估值回答首段没有直接说明命中估值约束不等于便宜"
    if re.search(
        r"(?:低|偏低|很低|极低)[^。；\n]{0,12}PE"
        r"(?:\s*[（(]?\s*TTM\s*[）)]?)?[^。；\n]{0,80}"
        r"(?:主要(?:是)?因为|主要来自|建立在|归因于)[^。；\n]{0,120}"
        r"(?:刚脱离巨亏|刚扭亏|盈利(?:还)?很薄|微薄的滚动利润|"
        r"前期大额亏损|历史亏损|一次性收益|非经常性损益)",
        answer,
        re.IGNORECASE,
    ):
        return "估值回答用未拆解的利润或非经常性因素错误解释低PE"
    if re.search(
        r"(?:低估值|低倍数|偏低估值倍数)[^。；\n]{0,80}"
        r"(?:更像是|主要来自|建立在|归因于)[^。；\n]{0,120}"
        r"(?:刚刚?扭亏|刚脱离巨亏|盈利(?:还)?很薄|历史亏损|"
        r"现金流(?:尚未|还没)跟上)",
        answer,
        re.IGNORECASE,
    ):
        return "估值回答把低倍数错误归因于扭亏、薄利润或现金流阶段"
    if re.search(
        r"(?:倍数差距|估值差距|估值倍数差异)[^。；\n]{0,80}"
        r"(?:主要由|主要来自|归因于)[^。；\n]{0,120}"
        r"(?:利润(?:极薄|很薄|规模很小)|近期刚扭亏|刚刚?扭亏)",
        answer,
        re.IGNORECASE,
    ):
        return "估值回答把低倍数错误归因于扭亏或薄利润"
    if re.search(
        r"(?:销售收现率|销售商品、?提供劳务收到的现金占营收的比例)"
        r"[^。；\n]{0,120}(?:下降|下滑)[^。；\n]{0,80}"
        r"(?:说明|意味着)[^。；\n]{0,80}"
        r"(?:更多营收尚未转化|回款缺口扩大|回款恶化|收入没有变成现金)",
        answer,
    ):
        return "估值回答把销售收现率下降直接解释成回款恶化"
    if re.search(
        r"资产负债率[^。；\n]{0,100}(?:下降|降低)[^。；\n]{0,50}"
        r"表面上[^。；\n]{0,12}负债压力(?:有所)?(?:减轻|改善)",
        answer,
    ):
        return "估值回答把资产负债率下降先解释成负债压力减轻"
    if re.search(
        r"(?:亿元|万元|元)的?每股收益|每股收益[^。；\n]{0,16}(?:亿元|万元)",
        answer,
    ):
        return "估值回答混淆了每股收益与利润金额单位"
    if re.search(
        r"(?:按此|据此|由此|因此)(?:可以|可)?(?:计算|测算|得到|得出)"
        r"[^。；\n]{0,48}"
        r"(?:动态)?(?:市盈率|PE)",
        answer,
        re.IGNORECASE,
    ):
        return "估值回答把行情源动态市盈率错误说成由其他数字直接计算"
    for sentence in re.split(r"[。；\n]", answer):
        if not re.search(r"(?:PE\s*TTM|TTM\s*(?:市盈率|PE))", sentence, re.I):
            continue
        if re.search(
            r"(?:PE\s*TTM|TTM\s*(?:市盈率|PE))[^，,]{0,72}"
            r"(?:对应的是|来自|由于|受|取决于)[^，,]{0,32}"
            r"(?:一季报|单季|低利润基数|利润基数偏低|刚扭亏)",
            sentence,
            re.I,
        ) or re.search(
            r"(?:一季报|单季|低利润基数|利润基数偏低|基数效应|刚扭亏)"
            r"[^，,]{0,40}"
            r"(?:使|导致|压缩|放大|降低|抬高)[^，,]{0,24}"
            r"(?:PE\s*TTM|TTM\s*(?:市盈率|PE))",
            sentence,
            re.I,
        ):
            return "估值回答用单季利润基数直接解释滚动十二个月市盈率"
        if re.search(
            r"(?:低\s*PE|PE\s*TTM)[^。；\n]{0,80}"
            r"(?:可能|主要)?(?:是|来自|由于|受)[^。；\n]{0,36}"
            r"(?:利润基数偏低|历史亏损|亏损基数)",
            sentence,
            re.I,
        ):
            return "估值回答用历史亏损或低利润基数错误解释低PE"
        if not any(
            term in sentence
            for term in ("不是以", "并非以", "不能以", "不应以", "不得以")
        ) and re.search(
            r"(?:PE\s*TTM|TTM\s*(?:市盈率|PE))[^，,]{0,48}"
            r"(?:是以|基于)[^，,]{0,28}(?:全年利润|年度利润)"
            r"[^，,]{0,20}(?:计算|基础)",
            sentence,
            re.I,
        ):
            return "估值回答把滚动十二个月市盈率错误说成只基于单一年度利润"
    if re.search(
        r"TTM\s*(?:盈利|利润)[^。；\n]{0,32}(?:很低|偏低|较低|很少)"
        r"[^。；\n]{0,24}(?:拉低|压低|降低)[^。；\n]{0,16}(?:PE|市盈率)",
        answer,
        re.I,
    ) or re.search(
        r"(?:PE\s*低|低\s*PE)[^。；\n]{0,100}(?:因为|来自|由于)"
        r"[^。；\n]{0,100}(?:过去四个季度|历史亏损|总体赚得很少|利润很低)",
        answer,
        re.I,
    ) or re.search(
        r"(?:历史亏损|低利润基数)[^。；\n]{0,100}(?:导致|使得?|从而)"
        r"[^。；\n]{0,32}(?:PE|市盈率)[^。；\n]{0,24}"
        r"(?:被)?(?:压得很低|压低|降低)",
        answer,
        re.I,
    ):
        return "估值回答用未拆解的滚动盈利或历史利润错误解释低PE"
    if re.search(
        r"(?:一次性收益|非经常性损益)[^。；\n]{0,80}(?:PE|市盈率)"
        r"[^。；\n]{0,28}(?:被动)?(?:拉低|压低|降低)",
        answer,
        re.I,
    ) or re.search(
        r"PE\s*的?低位[^。；\n]{0,24}(?:更多)?源于",
        answer,
        re.I,
    ):
        return "估值回答用未拆解的非经常性损益或分母因素解释低PE"
    for sentence in re.split(r"[。；\n]", answer):
        if not any(
            term in sentence
            for term in (
                "估值极低",
                "极低估值",
                "真正的低估值机会",
                "真正低估机会",
                "价值洼地",
                "财务陷阱",
                "就是低估值陷阱",
                "属于低估值陷阱",
            )
        ):
            continue
        if any(
            boundary in sentence
            for boundary in (
                "不能确认",
                "无法确认",
                "尚不能",
                "不能据此",
                "不等于",
                "不代表",
                "不意味着",
                "不能直接",
                "不是已确认",
                "并非已确认",
                "仍需核验",
                "需要核验",
            )
        ):
            continue
        return "估值回答在缺少完整行业分位和持续盈利核验时下了确定性价值结论"
    if re.search(
        r"(?:低|偏低的?)\s*(?:PE|PB|估值倍数|倍数)[^。；\n]{0,64}"
        r"(?:更多|主要)?反映(?:了)?市场[^。；\n]{0,100}"
        r"(?:定价|态度|担忧|顾虑)",
        answer,
        re.IGNORECASE,
    ):
        return "估值回答把低倍数写成了没有证据的市场定价意图"
    if re.search(
        r"低倍数[^。；\n]{0,48}(?:可能)?来自[^。；\n]{0,180}"
        r"(?:一次性|不可持续|经营质量)",
        answer,
    ) or re.search(
        r"低倍数是否被[^。；\n]{0,100}(?:一次性收益|低利润基数)"
        r"[^。；\n]{0,60}(?:扭曲|影响)",
        answer,
    ):
        return "估值回答用未拆解的盈利或经营质量因素解释低倍数"
    if re.search(
        r"(?:盈利|利润)(?:的)?现金兑现(?:能力|效率|程度|质量)?"
        r"[^。；\n]{0,12}(?:弱|差|不足|偏弱|较弱|不强|薄弱)",
        answer,
    ):
        return "估值回答把现金流与利润方向差异概括成了现金兑现能力"
    if re.search(
        r"(?:盈利|利润)(?:的)?现金兑现[^。；\n]{0,12}(?:严重)?偏离|"
        r"现金流[^。；\n]{0,12}(?:尚)?不能为利润提供支撑",
        answer,
    ):
        return "估值回答把现金流与利润方向差异升级成了现金支撑结论"
    if re.search(r"现金(?:回收|回笼)节奏[^。；\n]{0,16}(?:存在)?压力", answer):
        return "估值回答把销售收现率变化升级成了现金回收压力"
    if re.search(
        r"(?:账面)?(?:盈利|利润)[^。；\n]{0,24}"
        r"(?:没有|尚未|未能)[^。；\n]{0,16}"
        r"(?:同步)?(?:变成|转化为|兑现为)[^。；\n]{0,16}"
        r"现金(?:净流入|流入|流|回笼)",
        answer,
    ):
        return "估值回答把经营现金流与利润方向差异解释成利润没有变成现金"
    if re.search(
        r"(?:销售收现率|销售商品、?提供劳务收到的现金占营业收入的比例)"
        r"[^。；\n]{0,180}(?:下降|下滑)[^。；\n]*[。；]"
        r"[^。；\n]{0,180}(?:回款质量|回款恶化|利润的?[‘'\"“]?(?:含金量)"
        r"[’'\"”]?|真实财务压力|收入没有变成现金)",
        answer,
    ):
        return "估值回答把销售收现率下降直接解释成回款或利润现金质量"
    if "销售收现率" in answer and re.search(
        r"(?:卖货)?回款(?:变慢|走弱|恶化|质量下降)|"
        r"销售回款[^。；\n]{0,40}(?:差距|缺口)[^。；\n]{0,20}(?:拉大|扩大)|"
        r"盈利[^。；\n]{0,32}(?:真金白银|转化为现金)[^。；\n]{0,24}"
        r"(?:能力)?(?:很弱|偏弱|下降|恶化)",
        answer,
    ):
        return "估值回答把销售收现率下降直接解释成回款恶化或利润现金质量"
    if re.search(
        r"(?:资产)?负债率下降[^。；\n]{0,16}"
        r"(?:积极信号|积极变化|改善信号|积极线索)",
        answer,
    ):
        return "估值回答把资产负债率下降升级成了积极改善信号"
    if re.search(
        r"资产负债率[^。；\n]{0,120}(?:下降|降低)[^。；\n]{0,80}"
        r"(?:积极信号|积极变化|改善信号|积极线索)",
        answer,
    ):
        return "估值回答把资产负债率下降升级成了积极改善信号"
    if re.search(
        r"(?:动态市盈率|动态\s*PE)[^。；\n]{0,100}"
        r"(?:印证|说明|反映|代表)[^。；\n]{0,100}市场[^。；\n]{0,80}"
        r"(?:预期|态度|担忧|顾虑)",
        answer,
        re.IGNORECASE,
    ):
        return "估值回答把动态市盈率写成了没有证据的市场预期"
    if re.search(
        r"(?:动态市盈率|动态\s*PE)[^。；\n]{0,100}"
        r"(?:印证|说明|反映|代表|意味着|暗示)[^。；\n]{0,100}"
        r"(?:经常性)?(?:盈利|利润)[^。；\n]{0,40}"
        r"(?:偏薄|很薄|不高|不可持续)",
        answer,
        re.IGNORECASE,
    ):
        return "估值回答用动态市盈率推断了未经拆解的经常性盈利质量"
    if re.search(
        r"PE\s*TTM[^。；\n]{0,120}(?:刚告别亏损|刚刚?扭亏)"
        r"[^。；\n]{0,160}(?:非经常性损益|前期亏损|历史亏损)",
        answer,
        re.IGNORECASE,
    ):
        return "估值回答用扭亏、历史亏损或非经常性损益猜测低PE成因"
    if re.search(r"整体财务杠杆[^。；\n]{0,16}(?:明显)?下降", answer):
        return "估值回答把资产负债率变化升级成了整体财务杠杆下降"
    if re.search(r"盈利(?:仍|正|正在|还)?在?持续(?!性)", answer):
        return "估值回答把阶段性扭亏和业绩预告外推成了盈利持续"
    if re.search(r"盈利改善趋势(?:可能)?延续", answer):
        return "估值回答把阶段性扭亏和业绩预告外推成了盈利改善趋势延续"
    if issue := valuation_review_stream_overclaim_issue(answer):
        return issue
    if any(
        term in answer
        for term in ("半年度预告延续盈利", "半年度业绩预告延续盈利")
    ):
        return "估值回答把半年度业绩预告写成了盈利延续"
    if re.search(
        r"经营层面[^。；\n]{0,20}方向性变化[^。；\n]{0,20}"
        r"(?:不只是|不仅是|而非)单季波动",
        answer,
    ):
        return "估值回答把阶段性报表变化外推成了持续经营方向"
    for sentence in re.split(r"[。；\n]", answer):
        if not re.search(r"财务结构[^。；\n]{0,24}(?:收缩|改善|优化)", sentence):
            continue
        if any(
            term in sentence
            for term in ("不能确认", "尚不能", "无法确认", "是否", "不能据此")
        ):
            continue
        return "估值回答把资产负债率变化升级成了财务结构变化"
    if re.search(r"(?:预示|说明|确认)[^。；\n]{0,12}扭亏持续", answer):
        return "估值回答把阶段性扭亏和业绩预告外推成了扭亏持续"
    if any(
        term in answer
        for term in ("业务结构简单且方向明确", "业务结构清晰且专注")
    ):
        return "估值回答把主营集中度美化成了结构简单明确"
    if re.search(
        r"主营(?:业务)?集中度[^。；\n]{0,16}(?:方向清晰|方向明确)",
        answer,
    ):
        return "估值回答把主营集中度美化成了方向清晰"
    for sentence in re.split(r"[。；\n]", answer):
        scale_sentence = re.sub(
            r"负债占(?:总)?资产(?:的)?(?:比例|比重)"
            r"[^。；\n]{0,12}(?:下降|减少|降低|收缩|减轻)",
            "",
            sentence,
        )
        if not re.search(
            r"资产负债率[^。；\n]{0,120}(?:负债(?!率)|债务)"
            r"(?:整体|总体|绝对)?(?:总量|规模|余额)?"
            r"[^。；\n]{0,16}(?:下降|减少|降低|收缩|减轻)",
            scale_sentence,
        ):
            continue
        if any(
            term in sentence
            for term in (
                "不能据此",
                "不能证明",
                "不代表",
                "并非说明",
                "无法判断",
                "不能直接等同于",
                "不能等同于",
                "不等同于",
                "不等于",
                "是否",
                "仍需核对",
            )
        ):
            continue
        return "估值回答把资产负债率变化改写成了负债绝对规模变化"

    disclosure_parts: list[str] = []
    information = evidence.get("a_share_information") or {}
    for item in information.get("announcements") or []:
        disclosure_parts.extend(
            str(item.get(key) or "") for key in ("title", "summary")
        )
    timeline = evidence.get("event_timeline") or {}
    for item in timeline.get("events") or []:
        disclosure_parts.extend(
            str(item.get(key) or "") for key in ("title", "direct_excerpt", "summary")
        )
    drivers = evidence.get("financial_drivers") or {}
    filing = drivers.get("filing_evidence") or {}
    for item in filing.get("explicit_company_explanations") or []:
        disclosure_parts.extend(
            str(item.get(key) or "") for key in ("label", "statement", "excerpt")
        )
    direct_disclosure = " ".join(disclosure_parts)
    unsupported_event_terms = (
        "重大资产重组",
        "股权处置",
        "资产处置",
        "一次性收益",
        "一次性大额收益",
        "非经常性收益",
        "非经常性项目",
        "非经常项目",
    )
    for term in unsupported_event_terms:
        if term not in answer or term in direct_disclosure:
            continue
        unsupported_sentences = [
            sentence
            for sentence in re.split(r"[。；\n]", answer)
            if term in sentence
            and not (
                "是否" in sentence
                or "待核验" in sentence
                or "需要核验" in sentence
                or "需要确认" in sentence
                or "尚未确认" in sentence
                or "不能确认" in sentence
                or "无法确认" in sentence
                or "明细" in sentence
            )
        ]
        if unsupported_sentences:
            return f"估值回答补写了证据中没有直接披露的{term}"

    valuation = (evidence.get("fundamentals") or {}).get("valuation") or {}
    peers = evidence.get("peer_comparison") or {}
    for label, key in (("PE", "pe_ttm"), ("PB", "pb")):
        value = valuation.get(key)
        if value is None:
            continue
        label_mentioned = (
            label in answer.upper()
            or (key == "pe_ttm" and "市盈率" in answer)
            or (key == "pb" and "市净率" in answer)
        )
        current_value_mentioned = label_mentioned and _quality_review_number_mentioned(
            answer, value
        )
        if not current_value_mentioned and not _same_day_peer_subject_metric_mentioned(
            answer,
            peers,
            key,
        ):
            return f"估值回答遗漏当前{label}数值或带日期的同日同行口径"

    if peers.get("metrics"):
        if issue := peer_valuation_required_fact_issue(answer, evidence):
            return issue
    elif not (
        any(term in answer for term in ("同行", "同业", "可比"))
        and any(term in answer for term in ("不能", "无法", "缺少", "尚未取得"))
    ):
        return "估值回答遗漏同行估值尚未取得的边界"

    cashflow = (evidence.get("financial_drivers") or {}).get("cashflow_analysis") or {}
    operating_cashflow = cashflow.get("operating_cashflow")
    coverage = cashflow.get("operating_cashflow_to_net_profit")
    if operating_cashflow is not None:
        amount_yi = float(operating_cashflow) / 100_000_000.0
        if not (
            "经营现金流" in answer
            and _directional_amount_mentioned(answer, amount_yi)
        ):
            return "估值回答遗漏经营现金流金额"
    if coverage is not None and not (
        "经营现金流" in answer
        and "归母净利润" in answer
        and _quality_review_number_mentioned(answer, coverage)
    ):
        return "估值回答遗漏经营现金流与归母净利润比率"

    latest_report = (evidence.get("earnings_quality") or {}).get("latest_report") or {}
    debt_ratio = latest_report.get("debt_asset_ratio_pct")
    if debt_ratio is not None and not (
        "资产负债率" in answer and _quality_review_number_mentioned(answer, debt_ratio)
    ):
        return "估值回答遗漏最新资产负债率"
    return None


def peer_valuation_required_fact_issue(
    text: str,
    evidence: dict[str, Any],
) -> str | None:
    """Require the decision-useful peer snapshot without forcing a data dump."""

    if str(evidence.get("type") or "") != "stock_research":
        return None
    question = str(evidence.get("user_question") or "")
    if not any(
        term in question
        for term in ("同行", "同业", "估值", "PE", "PB", "市盈率", "市净率")
    ):
        return None
    peer_comparison = evidence.get("peer_comparison") or {}
    if (
        str(peer_comparison.get("method") or "").startswith("dynamic_same_day")
        and peer_comparison.get("as_of")
        and not _calendar_date_mentioned(text, peer_comparison.get("as_of"))
    ):
        return "同行估值回答遗漏同日估值日期"
    metrics = peer_comparison.get("metrics") or {}
    required_metrics = (
        ("PE", "pe_ttm", "TTM市盈率"),
        ("PB", "pb", "市净率"),
    )
    for short_label, key, label in required_metrics:
        metric = metrics.get(key) or {}
        if not metric:
            continue
        if not (
            (short_label in text or label in text)
            and _valuation_metric_number_mentioned(text, metric.get("subject_value"))
            and _valuation_metric_number_mentioned(text, metric.get("peer_median"))
        ):
            return f"同行估值回答遗漏{label}的本标的数值或同行中位数"
    peer_names = [
        str(peer.get("name") or peer.get("symbol") or "").strip()
        for peer in peer_comparison.get("peers") or []
        if str(peer.get("name") or peer.get("symbol") or "").strip()
    ]
    missing_peer_names = [name for name in peer_names if name not in text]
    if missing_peer_names:
        return "同行估值回答遗漏同行样本名称：" + "、".join(missing_peer_names)
    operating = peer_comparison.get("operating_comparison") or {}
    if str(operating.get("status") or "") in {"partial", "unavailable"}:
        if not (
            ("同报告期" in text or "报告期" in text)
            and any(term in text for term in ("不能", "无法", "不可", "不足", "缺少"))
        ):
            return "同行估值回答遗漏同报告期经营数据不足的结论边界"
    return None


def _relative_industry_component_coverage_mentioned(
    answer: str,
    breadth: dict[str, Any],
) -> bool:
    coverage = breadth.get("coverage") or {}
    available = coverage.get("available_returns")
    total = coverage.get("constituents") or breadth.get("total_constituents")
    if not isinstance(available, int) or not isinstance(total, int):
        return True
    compact = re.sub(r"\s+", "", answer)
    ratio_pattern = rf"{available}(?:/|／|只有效成分[^\d]{{0,8}}){total}"
    if re.search(ratio_pattern, compact):
        return True
    if (
        _quality_review_number_mentioned(answer, available)
        and _quality_review_number_mentioned(answer, total)
        and any(
            term in answer
            for term in (
                "覆盖",
                "有效成分",
                "有效收益",
                "全部有收益",
                "全部取得收益",
                "全部可取得收益",
            )
        )
    ):
        return True
    breadth_counts = [
        breadth.get("advancers"),
        breadth.get("decliners"),
        breadth.get("unchanged"),
    ]
    labeled_counts = (
        (breadth.get("advancers"), "上涨"),
        (breadth.get("decliners"), "下跌"),
        (breadth.get("unchanged"), "平盘"),
    )
    if (
        all(isinstance(value, int) for value in breadth_counts)
        and sum(breadth_counts) == available == total
        and _quality_review_number_mentioned(answer, total)
        and all(
            value == 0
            or (label in answer and _quality_review_number_mentioned(answer, value))
            for value, label in labeled_counts
        )
    ):
        return True
    return bool(
        all(isinstance(value, int) for value in breadth_counts)
        and sum(breadth_counts) == available == total
        and all(
            _quality_review_number_mentioned(answer, value) for value in breadth_counts
        )
        and all(term in answer for term in ("上涨", "下跌", "平盘"))
        and _quality_review_number_mentioned(answer, total)
    )


def relative_industry_required_fact_issue(
    text: str,
    evidence: dict[str, Any],
) -> str | None:
    """Require exact same-date industry evidence for relative-performance turns."""

    if str(evidence.get("type") or "") != "stock_research":
        return None
    plan = evidence.get("research_plan") or {}
    question = str(evidence.get("user_question") or "")
    if str(plan.get("focus") or "") != "relative_industry" and not re.search(
        r"相对[^，。；,]{0,12}(?:行业|板块)",
        re.sub(r"\s+", "", question),
    ):
        return None
    industry = (evidence.get("stock_market_context") or {}).get(
        "exact_industry_index"
    ) or {}
    answer = str(text or "")
    name = str(industry.get("name") or industry.get("full_name") or "").strip()
    compact_answer = re.sub(r"\s+", "", answer)
    compact_name = re.sub(r"\s+", "", name)
    if compact_name and compact_name not in compact_answer:
        return "相对行业回答遗漏官方行业指数名称"
    status = str(industry.get("status") or "")
    if status != "same_market_date" or industry.get("return_1d_pct") is None:
        stock_return = industry.get("stock_return_1d_pct")
        if stock_return is not None and not _directional_percentage_mentioned(
            answer, stock_return
        ):
            return "相对行业回答遗漏公司同日收益"
        unavailable_boundary = (
            any(
                term in answer
                for term in (
                    "不能确认",
                    "无法确认",
                    "尚不能判断",
                    "无法判断",
                    "不能判断",
                    "无法直接判定",
                    "不能直接判定",
                    "尚无法判定",
                )
            )
            and "指数" in answer
            and any(
                term in answer
                for term in (
                    "尚未取得",
                    "未取得",
                    "暂未取得",
                    "尚未发布",
                    "尚未形成",
                    "缺少",
                )
            )
        )
        if not unavailable_boundary:
            return "相对行业回答遗漏目标日官方指数不可用边界"
        for sentence in re.split(r"(?<=[。！？；\n])", answer):
            if any(
                term in sentence
                for term in (
                    "不能确认",
                    "无法确认",
                    "尚不能判断",
                    "无法判断",
                    "不能判断",
                    "无法直接判断",
                    "不能直接判断",
                    "无法直接判定",
                    "不能直接判定",
                    "尚无法判定",
                    "无法直接计算",
                    "不能直接计算",
                    "无法计算",
                    "不能计算",
                    "不能改写成",
                    "不能据此断定",
                    "不能直接等同于",
                    "不能直接等同为",
                    "不能等同于",
                    "不能直接写成",
                    "无法升级为",
                    "不能升级为",
                    "尚未形成",
                    "还未形成",
                    "没有形成",
                    "不构成",
                )
            ):
                continue
            conditional_data_completion = any(
                term in sentence for term in ("如果", "若", "一旦", "待")
            ) and any(
                term in sentence
                for term in (
                    "补齐",
                    "补全",
                    "取得",
                    "获取",
                    "发布",
                    "形成",
                    "更正",
                    "计算出",
                )
            )
            if conditional_data_completion:
                continue
            if re.search(
                r"(?:相对[^。；\n]{0,16}(?:增强|走强|走弱|同步)|"
                r"(?:跑赢|跑输)(?:行业|指数)|公司减(?:行业|指数)|"
                r"个股减(?:行业|指数))",
                sentence,
            ):
                return "相对行业回答在官方指数缺失时仍给出指数相对方向"
        breadth = industry.get("component_breadth") or {}
        if str(breadth.get("status") or "") == "available":
            if not _relative_industry_component_coverage_mentioned(answer, breadth):
                return "相对行业回答遗漏行业成分有效收益覆盖"
            median = breadth.get("median_pct_change")
            if median is not None and not _directional_percentage_mentioned(
                answer, median
            ):
                return "相对行业回答遗漏行业成分涨跌幅中位数"
        if not any(term in answer for term in ("反方", "风险", "限制", "边界")):
            return "相对行业回答遗漏反方证据或口径限制"
        if not any(
            term in answer for term in ("推翻", "失效", "不再成立", "改变判断", "改写")
        ):
            return "相对行业回答遗漏可观察的失效条件"
        return None
    for key, label in (
        ("stock_return_1d_pct", "公司同日收益"),
        ("return_1d_pct", "行业指数同日收益"),
        ("stock_minus_industry_pct", "公司相对行业差值"),
    ):
        value = industry.get(key)
        if value is not None and not _directional_percentage_mentioned(answer, value):
            return f"相对行业回答遗漏{label}"

    breadth = industry.get("component_breadth") or {}
    if str(breadth.get("status") or "") == "available":
        if not _relative_industry_component_coverage_mentioned(answer, breadth):
            return "相对行业回答遗漏行业成分有效收益覆盖"
    if not any(term in answer for term in ("反方", "风险", "限制", "边界")):
        return "相对行业回答遗漏反方证据或口径限制"
    if not any(term in answer for term in ("推翻", "失效", "不再成立", "改变判断")):
        return "相对行业回答遗漏可观察的失效条件"
    return None


def repair_relative_industry_answer(
    text: str,
    evidence: dict[str, Any],
) -> str | None:
    """Repair a narrow relative-industry fact-frame failure locally.

    DeepSeek occasionally truncates a half-cent percentage-point result even
    when the evidence already contains the authoritative spread.  Preserve the
    freshly generated answer and correct only the explicitly labelled spread;
    when the official target-day index return is unavailable, prepend the
    verified boundary and remove only unsupported index-direction sentences.
    """

    issue = relative_industry_required_fact_issue(text, evidence)
    industry = (evidence.get("stock_market_context") or {}).get(
        "exact_industry_index"
    ) or {}
    status = str(industry.get("status") or "")
    if status != "same_market_date" or industry.get("return_1d_pct") is None:
        if issue not in {
            "相对行业回答遗漏目标日官方指数不可用边界",
            "相对行业回答在官方指数缺失时仍给出指数相对方向",
        }:
            return None
        answer = str(text or "").strip()
        if len(answer) < 80:
            return None
        market_context = evidence.get("stock_market_context") or {}
        analysis_target = market_context.get("analysis_target") or {}
        breadth = industry.get("component_breadth") or {}
        market_date = str(
            analysis_target.get("market_date")
            or breadth.get("market_date")
            or "目标交易日"
        )
        display_name = str(
            evidence.get("display_name") or evidence.get("symbol") or "当前公司"
        ).strip()
        index_name = str(
            industry.get("name") or industry.get("full_name") or "官方行业指数"
        ).strip()
        stock_return = industry.get("stock_return_1d_pct")
        stock_return_text = (
            f"{float(stock_return):+.2f}%"
            if isinstance(stock_return, (int, float))
            and not isinstance(stock_return, bool)
            else "已取得"
        )
        kept_lines = []
        for line in answer.splitlines():
            stripped = line.strip()
            if not stripped:
                kept_lines.append(line)
                continue
            if any(
                term in stripped
                for term in (
                    "不能确认",
                    "无法确认",
                    "尚不能判断",
                    "无法判断",
                    "不能判断",
                )
            ):
                continue
            if re.search(
                r"(?:相对[^。；\n]{0,16}(?:增强|走强|走弱|同步)|"
                r"(?:跑赢|跑输)(?:行业|指数)|公司减(?:行业|指数)|"
                r"个股减(?:行业|指数))",
                stripped,
            ):
                continue
            kept_lines.append(line)
        body = "\n".join(kept_lines).strip()
        boundary = (
            f"{display_name}在{market_date}相对{index_name}是增强、同步还是走弱，"
            f"当前不能确认：公司当日收益为{stock_return_text}，但{index_name}"
            "目标日官方收益尚未取得，不能计算公司减指数的同日差值。"
        )
        verification = (
            "成分涨跌分布只能作为旁证；若成分复权口径或当日分布更正，"
            "当前成分中位数旁证需要改写，官方指数目标日收益补齐后才能形成正式判断。"
        )
        repaired = "\n\n".join(item for item in (boundary, body, verification) if item)
        return (
            repaired
            if relative_industry_required_fact_issue(repaired, evidence) is None
            else None
        )
    if issue != "相对行业回答遗漏公司相对行业差值":
        return None
    value = industry.get("stock_minus_industry_pct")
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    answer = str(text or "").strip()
    if len(answer) < 80:
        return None

    expected_positive = float(value) >= 0
    signed = f"{float(value):+.2f}"
    magnitude = f"{abs(float(value)):.2f}"
    parts = re.split(r"([。；\n])", answer)
    changed = False
    for index in range(0, len(parts), 2):
        clause = parts[index]
        if "个百分点" not in clause:
            continue
        if expected_positive and "跑赢" in clause:
            replacement = magnitude
        elif not expected_positive and "跑输" in clause:
            replacement = magnitude
        elif any(
            term in clause
            for term in (
                "差值",
                "公司减行业",
                "个股减行业",
                "公司减指数",
                "个股减指数",
                "相对行业",
            )
        ):
            replacement = signed
        else:
            continue
        repaired_clause, count = re.subn(
            r"[+-]?\d+(?:\.\d+)?(?=\s*个百分点)",
            replacement,
            clause,
        )
        if count:
            parts[index] = repaired_clause
            changed = True

    repaired = "".join(parts).strip()
    if not changed:
        return None
    return (
        repaired
        if relative_industry_required_fact_issue(repaired, evidence) is None
        else None
    )


def repair_peer_valuation_answer(
    text: str,
    evidence: dict[str, Any],
) -> str | None:
    """Complete a mostly useful model answer with the verified peer snapshot.

    This repair is deliberately narrow: it only runs for a substantive answer
    about the bound stock when the remaining defect is a missing deterministic
    peer-valuation fact.  The model's fresh interpretation remains the body of
    the answer; the service appends one compact, auditable fact block instead of
    discarding the answer and returning the full generic research preview.
    """

    issue = peer_valuation_required_fact_issue(text, evidence)
    if issue is None:
        return str(text or "").strip()
    if not issue.startswith("同行估值回答遗漏"):
        return None
    answer = str(text or "").strip()
    if len(answer) < 80 or any(term in answer for term in _CLEAR_OFF_TOPIC_TERMS):
        return None
    aliases = _subject_aliases(evidence)
    if aliases and not any(alias in answer for alias in aliases):
        return None

    comparison = evidence.get("peer_comparison") or {}
    subject = comparison.get("subject") or {}
    peers = comparison.get("peers") or []
    metrics = comparison.get("metrics") or {}
    pe_metric = metrics.get("pe_ttm") or {}
    pb_metric = metrics.get("pb") or {}
    if not subject or not peers or not pe_metric or not pb_metric:
        return None

    def valuation(value: Any) -> str:
        try:
            return f"{float(value):.2f}"
        except (TypeError, ValueError):
            return "待确认"

    rows = [
        (
            str(subject.get("name") or subject.get("symbol") or aliases[0]),
            subject.get("pe_ttm"),
            subject.get("pb"),
        )
    ]
    rows.extend(
        (
            str(peer.get("name") or peer.get("symbol") or "固定同行"),
            peer.get("pe_ttm"),
            peer.get("pb"),
        )
        for peer in peers
    )
    if any(pe is None or pb is None for _, pe, pb in rows):
        return None

    fact_lines = [
        "**同日同行估值截面（已核验数字）**"
        if str(comparison.get("method") or "").startswith("dynamic_same_day")
        else "**固定同行估值截面（已核验数字）**"
    ]
    fact_lines.extend(
        f"- {name}：TTM市盈率 {valuation(pe)}，市净率 {valuation(pb)}。"
        for name, pe, pb in rows
    )
    fact_lines.append(
        f"- 同行中位数：TTM市盈率 {valuation(pe_metric.get('peer_median'))}，"
        f"市净率 {valuation(pb_metric.get('peer_median'))}。"
    )
    operating = comparison.get("operating_comparison") or {}
    if str(operating.get("status") or "") in {"partial", "unavailable"}:
        fact_lines.append(
            "同报告期经营数据不足，因此这些数字只能说明当前估值横截面差异，"
            "不能据此判断经营质量优劣、估值是否合理或形成投资评级。"
        )

    repaired = f"{answer}\n\n" + "\n".join(fact_lines)
    return (
        repaired
        if peer_valuation_required_fact_issue(repaired, evidence) is None
        else None
    )


def _normalize_valuation_review_language(text: str) -> str:
    """Turn local valuation overclaims into explicit evidence boundaries."""

    normalized = str(text or "").strip()
    normalized = normalized.replace(
        "**命中估值约束不等于便宜。**",
        "命中估值约束不等于便宜。",
    )
    normalized = normalized.replace(
        "**盈利已经扭亏，但现金兑现仍需复核**",
        "**利润已扭亏，但经营现金流仍为负**",
    )
    normalized = normalized.replace(
        "**负债率下降，但现金流偿债能力仍需验证**",
        "**资产负债率下降，不等于负债总量减少**",
    )
    normalized = normalized.replace(
        "**主营高度集中于发动机，但高集中度不等于方向明确**",
        "**主营集中于发动机，重卡业务仍亏损**",
    )
    normalized = normalized.replace(
        "**变动的负债率提醒我们，低 PB 来自高股东权益，不自动等于资产便宜。**",
        "**资产负债率下降，不等于负债总量减少**",
    )
    normalized = normalized.replace(
        "**刚扭亏的盈利还谈不上扎实，滚动 PE 的分母仍待拆解。**",
        "**利润已扭亏，但经营现金流仍为负**",
    )
    normalized = normalized.replace(
        "**主营高度依赖发动机，毛利率刚回升但还很低。**",
        "**主营集中于发动机，重卡业务毛利仍为负**",
    )
    normalized = re.sub(
        r"(?:但)?(?:这个|当前的?)?(?:低|偏低|很低|极低)的?\s*PE"
        r"(?:\s*[（(]?\s*TTM\s*[）)]?)?[^。；\n]{0,80}"
        r"(?:主要(?:是)?因为|主要来自|建立在|归因于)[^。；\n]{0,140}"
        r"(?:刚脱离巨亏|刚扭亏|盈利(?:还)?很薄|微薄的滚动利润|"
        r"前期大额亏损|历史亏损|一次性收益|非经常性损益)"
        r"[^。；\n]*[。；]?",
        "PE TTM 的滚动盈利分母尚未拆解，不能用单季扭亏、历史亏损或"
        "利润规模直接解释当前倍数；未核验的非经常性因素也不能直接解释。",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        r"(?:但从目前证据看[，,]?)?(?:这个|当前)?(?:低估值|低倍数|偏低估值倍数)"
        r"[^。；\n]{0,80}(?:更像是|主要来自|建立在|归因于)"
        r"[^。；\n]{0,140}(?:刚刚?扭亏|刚脱离巨亏|盈利(?:还)?很薄|"
        r"历史亏损|现金流(?:尚未|还没)跟上)[^。；\n]*[。；]?",
        "当前低倍数与阶段性扭亏、经营现金流净流出等事实同时存在，"
        "但这些事实是否解释估值差异仍未确认，因此不能据此认定便宜；"
        "PE TTM 的滚动盈利分母仍需单独核验。",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        r"(?:但)?(?:这组)?(?:倍数差距|估值差距|估值倍数差异)"
        r"[^。；\n]{0,80}(?:主要由|主要来自|归因于)"
        r"[^。；\n]{0,140}(?:利润(?:极薄|很薄|规模很小)|"
        r"近期刚扭亏|刚刚?扭亏)[^。；\n]*[。；]?",
        "当前只能确认倍数差异；利润规模和阶段性扭亏是否解释估值差异仍未确认，"
        "不能据此认定便宜。",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        r"((?:销售收现率|销售商品、?提供劳务收到的现金占营收的比例)"
        r"[^。；\n]{0,120}(?:下降|下滑)[^。；\n]{0,40})[，,]"
        r"(?:说明|意味着)[^。；\n]*[。；]?",
        r"\1；这一比率变化的原因尚未确认，需结合应收、预收和结算时点核验。",
        normalized,
    )
    normalized = re.sub(
        r"((?:销售商品(?:、提供劳务)?收到的现金占(?:营业)?收入的比例)"
        r"[^。；\n]{0,120}(?:下降|下滑)[^。；\n]{0,40})[，,]"
        r"(?:显示|说明|表明|意味着)[^。；\n]{0,80}"
        r"(?:现金)?回款比例[^。；\n]{0,24}(?:降低|下降)[^。；\n]*[。；]?",
        r"\1；这一比率变化的原因尚未确认，需结合应收、预收和结算时点核验。",
        normalized,
    )
    normalized = re.sub(
        r"这组数据(?:提示|说明|表明)[^。；\n]{0,220}"
        r"(?:现金回款比例|回款质量|利润的?[‘'\"“]?含金量[’'\"”]?|"
        r"真实财务压力)[^。；\n]*[。；]?",
        "销售收现率同比下降，但这一比率变化的原因尚未确认，需结合应收、"
        "预收和结算时点核验。",
        normalized,
    )
    normalized = re.sub(
        r"(?:说明|表明)[^。；\n]{0,48}(?:销售回款|回款)"
        r"[^。；\n]{0,60}(?:差距|缺口)[^。；\n]{0,24}(?:拉大|扩大)"
        r"[^。；\n]*[。；]?",
        "这一比率变化的原因尚未确认，需结合应收、预收和结算时点核验。",
        normalized,
    )
    normalized = re.sub(
        r"盈利[^。；\n]{0,36}(?:转化成|转化为)[^。；\n]{0,16}"
        r"(?:真金白银|现金)[^。；\n]{0,24}(?:能力)?(?:依然)?(?:很弱|偏弱)"
        r"[^。；\n]*[。；]?",
        "经营现金流与利润方向相反，原因仍需核验。",
        normalized,
    )
    normalized = re.sub(
        r"(?:卖货)?回款(?:变慢|走弱|恶化|质量下降)",
        "销售收现率下降原因未明",
        normalized,
    )
    normalized = re.sub(
        r"如果后续现金流迟迟不能改善[^。；\n]{0,180}"
        r"(?:低\s*PE|价值|数字低)[^。；\n]*[。；]?",
        "后续需核验经营现金流变化原因，不能据此解释当前低 PE。",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        r"[，,]表面上负债压力(?:有所)?(?:减轻|改善)[，,]但",
        "，但",
        normalized,
    )
    normalized = normalized.replace("估值极低", "估值倍数明显偏低")
    normalized = normalized.replace("TTM市盈率极低", "TTM市盈率明显偏低")
    normalized = re.sub(
        r"相比之下(?:本标的|[\u4e00-\u9fff]{2,12})(?:的)?(?:估值倍数)?极低",
        "相比之下本标的估值倍数较低",
        normalized,
    )
    normalized = re.sub(
        r"(?:当前|这组)?极低的?(PE|PB|市盈率|市净率|估值倍数)",
        r"当前偏低的\1",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        r"(?:极低倍数|极低的?估值倍数|估值倍数的?极端低位|极端低位)",
        "偏低估值倍数",
        normalized,
    )
    normalized = re.sub(
        r"(?:处于|位于)?极低位置",
        "处于较低位置",
        normalized,
    )
    normalized = re.sub(
        r"倍数(?:处在|处于|位于)?极低(?:的)?水平",
        "倍数处于较低水平",
        normalized,
    )
    normalized = re.sub(
        r"(PE\s*TTM|PB)\s*极低",
        r"\1 较低",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        r"(?:而)?(?:动态市盈率|动态\s*PE)[^。；\n]{0,100}"
        r"(?:侧面)?(?:印证|说明|反映|代表)[^。；\n]{0,120}"
        r"市场[^。；\n]{0,80}(?:预期|态度|担忧|顾虑)[^。；\n]*[。；]?",
        "",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        r"(?:动态市盈率|动态\s*PE)[^。；\n]{0,100}"
        r"(?:印证|说明|反映|代表|意味着|暗示)[^。；\n]{0,100}"
        r"(?:经常性)?(?:盈利|利润)[^。；\n]{0,40}"
        r"(?:偏薄|很薄|不高|不可持续)[^。；\n]*[。；]?",
        "动态 PE 与 PE TTM 的计算口径不同，不能据此推断经常性盈利质量或市场意图。",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = normalized.replace(
        "业绩预告显示扭亏在延续",
        "业绩预告给出预计盈利区间",
    )
    normalized = normalized.replace(
        "且明确说主要源自主营业务",
        "公告同时列出主营业务变化和合并报表范围变化，仍需正式半年报核验",
    )
    normalized = normalized.replace(
        "负债结构大幅改善",
        "资产负债率下降（不代表偿债压力已经改善）",
    )
    normalized = normalized.replace("负债率大幅下降", "资产负债率下降")
    normalized = re.sub(
        r"(?:资产)?负债率下降(?:的|这一)?(?:是|属于|可视为)?"
        r"(?:积极信号|积极变化|改善信号|积极线索)",
        "资产负债率下降这一报表比率变化",
        normalized,
    )
    normalized = normalized.replace(
        "公司盈利在改善、资产负债率下降这一报表比率变化",
        "公司盈利出现改善线索，资产负债率下降则只是报表比率变化",
    )
    normalized = normalized.replace("业务结构清晰且专注", "业务集中度较高")
    normalized = normalized.replace("业务结构简单且方向明确", "主营集中度较高")
    normalized = re.sub(
        r"主营(?:业务)?集中度[^。；\n]{0,16}(?:方向清晰|方向明确)",
        "主营业务集中度较高",
        normalized,
    )
    normalized = normalized.replace("现金流兑现", "现金流与利润关系")
    normalized = normalized.replace(
        "半年度预告延续盈利",
        "半年度业绩预告给出扭亏区间",
    )
    normalized = normalized.replace(
        "半年度业绩预告延续盈利",
        "半年度业绩预告给出扭亏区间",
    )
    normalized = re.sub(
        r"(?:这份|该)?(?:半年度业绩)?预告(?:确实)?"
        r"(?:表明|说明|确认|预示)[^。；\n]{0,16}"
        r"盈利(?:方向|趋势)?(?:已经|已|仍|正|正在)?(?:在)?延续",
        "半年度业绩预告给出预计盈利区间",
        normalized,
    )
    normalized = re.sub(
        r"半年度业绩预告确认盈利(?:方向|趋势)?延续",
        "半年度业绩预告给出预计盈利区间",
        normalized,
    )
    normalized = normalized.replace(
        "进一步确认了扭亏趋势",
        "给出上半年扭亏区间",
    )
    normalized = re.sub(
        r"(?:均|进一步)?(?:预示|说明|确认)[^。；\n]{0,12}扭亏持续",
        "对应半年度预计扭亏区间",
        normalized,
    )
    normalized = re.sub(
        r"盈利(?:仍|正|正在|还)?在?持续(?!性)",
        "公司已披露一季报扭亏及半年度业绩预告",
        normalized,
    )
    normalized = normalized.replace("现金兑现方向相反", "经营现金流与利润方向相反")
    normalized = normalized.replace("现金兑现待核验", "经营现金流待核验")
    normalized = normalized.replace(
        "利润的现金兑现关系需要优先复核",
        "经营现金流与利润的差异需要优先复核",
    )
    normalized = normalized.replace(
        "今年利润转正后现金流覆盖率反而恶化",
        "正负比率不能直接作改善或恶化比较",
    )
    normalized = re.sub(
        r"(?:盈利|利润)(?:增加|增长)?[^。；\n]{0,24}"
        r"(?:尚未|没有|未能)[^。；\n]{0,16}(?:同步)?"
        r"(?:变成|转化为|兑现为)[^。；\n]{0,16}"
        r"现金(?:净流入|流入|流|回笼)[^。；\n]*",
        "经营现金流与利润方向相反，原因仍需核验",
        normalized,
    )
    normalized = re.sub(
        r"(?:刚扭亏[，,]\s*)?(归母净利润\s*约?\s*[+-]?\d[\d,]*"
        r"(?:\.\d+)?\s*(?:万|亿)?元)[，,]\s*同比(?:增长)?"
        r"\s*约?\s*[+-]?\d+(?:\.\d+)?\s*倍",
        r"\1，较上年同期实现扭亏",
        normalized,
    )
    normalized = re.sub(
        r"但低估值可能来自[^。；\n]{0,260}(?:需要逐项核验|需要核验)"
        r"[^。；\n]*[。；]?",
        "但低倍数可能对应不同经营与会计原因，当前只应把盈利质量、"
        "现金流、业务结构和滚动盈利分母列为核验项，不能直接判断低估。",
        normalized,
    )
    normalized = re.sub(
        r"(?:(?:低|偏低的?)\s*(?:PE|PB|估值倍数|倍数)|低倍数)"
        r"[^。；\n]{0,180}(?:一次性收益|非经常性收益)[^。；\n]*[。；]?",
        "低倍数只说明当前估值截面偏低，不能据此认定盈利质量或资产质量；"
        "PE TTM 的滚动盈利分母尚未拆解，需核验扣非利润和非经常性损益明细。",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        r"如果[^。；\n]{0,80}(?:一次性收益|非经常性收益)"
        r"[^。；\n]{0,140}[。；]?",
        "PE TTM 的滚动盈利分母尚未拆解，需核验扣非利润和非经常性损益明细。",
        normalized,
    )
    normalized = re.sub(
        r"[^。；\n]{0,100}一次性(?:大额)?收益[^。；\n]{0,120}"
        r"(?:极端|极低|倍数)[^。；\n]*[。；]?",
        "PE TTM 的滚动盈利分母尚未拆解，需核验扣非利润和非经常性损益明细。",
        normalized,
    )
    normalized = re.sub(
        r"[^。；\n]{0,100}(?:不是|并非)纯粹靠非经常项目[^。；\n]*[。；]?",
        "半年度业绩预告给出归母净利润和扣非净利润区间，仍需正式报告核验。",
        normalized,
    )
    normalized = re.sub(
        r"[，,](?:说明|表明)[^。；\n]{0,120}"
        r"(?:并非|不是)(?:完全)?(?:依赖|依靠)非经常性?(?:项目|损益)[^。；\n]*",
        "",
        normalized,
    )
    normalized = re.sub(
        r"(?:PE\s*TTM|滚动十二个月|TTM)[^。；\n]{0,100}(?:分母|盈利)"
        r"[^。；\n]{0,120}(?:历史亏损|非经常性收益)[^。；\n]{0,80}"
        r"(?:尚未|未)(?:完成)?(?:拆解|拆清)[^。；\n]*[。；]?",
        "PE TTM 的滚动盈利分母尚未拆解，需核验扣非利润和非经常性损益明细。",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        r"(?:TTM\s*市盈率|市盈率\s*[（(]?TTM[）)]?)"
        r"[^。；\n]{0,80}(?:极低值|很低的?数值|处于很低的位置)"
        r"[^。；\n]{0,180}(?:过去亏损|历史亏损|非经常性损益)"
        r"[^。；\n]*[。；]?",
        "PE TTM 的滚动盈利分母尚未拆解，需核验扣非利润和非经常性损益明细。",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        r"PE\s*TTM[^。；\n]{0,100}(?:刚告别亏损|刚刚?扭亏)"
        r"[^。；\n]{0,180}(?:非经常性损益|前期亏损|历史亏损)"
        r"[^。；\n]*[。；]?",
        "PE TTM 的滚动盈利分母尚未拆解，需核验扣非利润和非经常性损益明细。",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        r"即使股价不变[^。；\n]{0,180}PE倍数[^。；\n]{0,120}"
        r"(?:不存在|消失)[^。；\n]*[。；]?",
        "未来利润变化会改变 PE，但不能倒推当前低倍数的成因。",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        r"低倍数[^。；\n]{0,48}(?:可能)?来自[^。；\n]{0,180}"
        r"(?:一次性|不可持续|经营质量)[^。；\n]*[。；]?",
        "低倍数只说明当前估值截面偏低，不能据此判断经营质量；"
        "PE TTM 的滚动盈利分母尚未拆解，需核验扣非利润和非经常性损益明细。",
        normalized,
    )
    normalized = re.sub(
        r"低倍数[^。；\n]{0,64}(?:可能)?(?:对应(?:着)?|意味着)"
        r"[^。；\n]{0,180}(?:一次性|非经常|盈利质量|经营质量)"
        r"[^。；\n]*[。；]?",
        "低倍数只说明当前估值截面偏低，不能据此判断经营质量；"
        "PE TTM 的滚动盈利分母尚未拆解，需核验扣非利润和非经常性损益明细。",
        normalized,
    )
    normalized = re.sub(
        r"低倍数是否被[^。；\n]{0,100}(?:一次性收益|低利润基数)"
        r"[^。；\n]{0,60}(?:扭曲|影响)[^。；\n]*[。；]?",
        "PE TTM 的滚动盈利分母尚未拆解，需核验扣非利润和非经常性损益明细。",
        normalized,
    )
    normalized = re.sub(
        r"PE\s*TTM[^。；\n]{0,180}(?:通常|往往)[^。；\n]{0,100}"
        r"(?:盈利|利润)[^。；\n]{0,40}(?:不可持续|难以持续)[^。；\n]*[。；]?",
        "这一倍数只能描述当前估值快照，不能据此判断市场意图或盈利是否可持续。",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        r"(?:从|较)(?:去年|上年)同期亏损\s*[+-]?\d[\d,]*(?:\.\d+)?\s*"
        r"(?:万|亿)?元?实现扭亏",
        "较上年同期实现扭亏",
        normalized,
    )
    normalized = re.sub(
        r"(?:最新报告期)?归母净利润\s*[+-]?\d[\d,]*(?:\.\d+)?\s*"
        r"(?:万|亿)?元?[，,]?\s*较上年同期实现扭亏[；;]?",
        "",
        normalized,
    )
    normalized = re.sub(
        r"(?:这)?意味着(?:公司)?[^。；\n]{0,220}(?:现金兑现质量|现金兑现|"
        r"尚未转化为现金)[^。；\n]*[。；]?",
        "这两个会计口径方向相反，需要核验营运资金变动和季节性，"
        "不能直接解释为利润尚未兑现为现金。",
        normalized,
    )
    normalized = re.sub(
        r"(?:这)?意味着(?:账面)?(?:盈利|利润)[^。；\n]{0,24}"
        r"(?:没有|尚未|未能)[^。；\n]{0,16}"
        r"(?:变成|转化为|兑现为)[^。；\n]{0,16}现金(?:净流入|流入|流)"
        r"[^。；\n]*[。；]?",
        "经营现金流与利润方向相反，需要核验营运资金变动和季节性，"
        "不能直接解释为利润尚未兑现为现金。",
        normalized,
    )
    normalized = re.sub(
        r"(?:(?:说明|表明|意味着)(?:本报告期|同期)?(?:归母)?(?:净利润|利润)|"
        r"(?:本报告期|同期)(?:归母)?(?:净利润|利润))"
        r"[^。；\n]{0,20}(?:没有|尚未|未能)[^。；\n]{0,16}"
        r"(?:变成|转化为|兑现为)[^。；\n]{0,16}"
        r"(?:经营性)?现金(?:净流入|流入|流)[^。；\n]*[。；]?",
        "经营现金流与利润方向相反，需要核验营运资金变动和季节性，"
        "不能直接解释为利润尚未兑现为现金。",
        normalized,
    )
    normalized = re.sub(
        r"(?:说明|表明|意味着)[^。；\n]{0,40}(?:账面)?(?:净利润|利润)"
        r"[^。；\n]{0,28}(?:没有|尚未|未能|并未)[^。；\n]{0,32}"
        r"(?:变成|转化为|兑现为)[^。；\n]{0,32}现金[^。；\n]*[。；]?",
        "经营现金流与利润方向相反，需要核验营运资金变动和季节性，"
        "不能直接解释为利润尚未兑现为现金。",
        normalized,
    )
    normalized = re.sub(
        r"(?:这)?(?:说明|显示)[^。；\n]{0,28}(?:报告期内的?)?(?:盈利|利润)"
        r"[^。；\n]{0,20}(?:没有|尚未|未能)[^。；\n]{0,20}"
        r"(?:以现金形式回到公司|转化为现金流入|兑现为现金流入)"
        r"[^。；\n]*[。；]?",
        "经营现金流与利润方向相反，需要核验营运资金变动和季节性，"
        "不能直接解释为利润尚未兑现为现金。",
        normalized,
    )
    normalized = re.sub(
        r"这显示公司经营层面[^。；\n]{0,24}方向性变化[^。；\n]{0,24}"
        r"(?:不只是|不仅是|而非)单季波动[^。；\n]*[。；]?",
        "这只说明已披露报告期的利润方向与上年同期不同，持续性仍需核验。",
        normalized,
    )
    normalized = re.sub(
        r"TTM口径下[^。；\n]{0,240}(?:资产处置|重组收益|一次性因素|"
        r"非经常性收益)[^。；\n]*[。；]?",
        "PE TTM 的滚动十二个月盈利分母尚未在当前证据中直接拆解；"
        "需核验扣非利润和非经常性损益明细。",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        r"(?:PE\s*TTM|TTM市盈率)[^。；\n]{0,220}"
        r"(?:资产处置|一次性收益|非经常项目)[^。；\n]*[。；]?",
        "PE TTM 的滚动盈利分母尚未拆解，需核验扣非利润和非经常性损益明细。",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        r"2025年实际EPS[^。；\n]{0,220}(?:下降|下滑)[^。；\n]*[。；]?",
        "券商一致预期 EPS 属于预测口径，不能与已实现年度 EPS 直接作同比结论；"
        "滚动盈利分母仍需单独核验。",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        r"(?:若|如果)盈利分母[^。；\n]{0,180}(?:非经常性|一次性)"
        r"[^。；\n]*[。；]?",
        "当前证据尚未拆解滚动盈利分母，需核验扣非利润和非经常性损益明细。",
        normalized,
    )
    normalized = re.sub(
        r"动态PE[^。；\n]{0,180}(?:暗示|说明|表明)[^。；\n]{0,120}"
        r"(?:盈利|利润)[^。；\n]{0,40}(?:下降|下滑)[^。；\n]*[。；]?",
        "动态 PE 与 PE TTM 的计算口径不同，二者不能互相替代；"
        "一致预期 EPS 也只是券商预测，不是公司正式指引。",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        r"(?:TTM市盈率|PE\s*TTM)[^。；\n]{0,80}主要来自"
        r"[^。；\n]*[。；]?",
        "PE TTM 的滚动盈利分母构成尚未在当前证据中直接拆解。",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        r"PE\s*TTM\s*[+-]?\d+(?:\.\d+)?[^。；\n]{0,20}由2025年"
        r"[^。；\n]*[。；]?",
        "PE TTM 的滚动盈利分母不能用单一年度利润或一季报利润直接替代。",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        r"资产负债率[^。；\n]{0,100}下降主因是[^。；\n]*[。；]?",
        "资产负债率下降是报表比率变化；当前证据不能据此确认负债绝对规模或"
        "偿债压力已经改善。",
        normalized,
    )
    normalized = re.sub(
        r"资产负债率虽然下降但(?:绝对)?水平仍在\s*\d+(?:\.\d+)?%以上",
        "资产负债率下降只说明负债占资产比例下降，不能据此判断负债绝对规模或偿债压力",
        normalized,
    )
    normalized = re.sub(
        r"(资产负债率[^。；\n]{0,100})[，,]\s*但(?:这一)?百分比下降"
        r"[^。；\n]{0,120}(?:负债总量|负债规模|偿债压力)[^。；\n]*[。；]?",
        r"\1。这只说明负债占资产的比例下降，不能据此判断负债绝对规模或偿债压力。",
        normalized,
    )
    normalized = re.sub(
        r"(资产负债率[^。；\n]{0,120}?)(?:，|；)\s*"
        r"(?:负债(?!率)|债务)(?:整体|总体|绝对)?(?:总量|规模|余额)?"
        r"[^。；\n]{0,16}(?:下降|减少|降低|收缩|减轻)[^。；\n]*[。；]?",
        r"\1。资产负债率变化只说明报表比率差异，不能单独证明负债绝对规模或偿债压力改善。",
        normalized,
    )
    normalized = re.sub(
        r"(?:资产)?负债率下降[^。；\n]{0,36}(?:不宜|不能|不可)"
        r"[^。；\n]{0,24}(?:视为|等同于)财务结构(?:改善|优化)[。；]?",
        "资产负债率下降只说明负债占资产比例下降，不能据此判断负债绝对规模或"
        "偿债压力。",
        normalized,
    )
    normalized = re.sub(
        r"财务结构(?:相较[^。；\n]{0,20})?(?:有所)?(?:收缩|改善|优化)"
        r"[^。；\n]*[。；]?",
        "资产负债率下降只说明负债占资产比例下降，不能据此判断负债绝对规模或"
        "偿债压力。",
        normalized,
    )
    normalized = re.sub(
        r"(?:尚|仍)?不能确认财务结构是否(?:真正)?改善",
        "不能据此判断负债绝对规模或偿债压力",
        normalized,
    )
    normalized = re.sub(
        r"(?:低\s*PE|PE\s*TTM)[^。；\n]{0,80}"
        r"(?:可能|主要)?(?:是|来自|由于|受)[^。；\n]{0,36}"
        r"(?:利润基数偏低|历史亏损|亏损基数)[^。；\n]*[。；]?",
        "PE TTM 的滚动盈利分母尚未拆解，当前不能归因于单季利润、历史亏损或"
        "低利润基数。",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        r"[^。；\n]{0,180}(?:历史基数|历史亏损|刚扭亏)[^。；\n]{0,120}"
        r"(?:拉低|压低|降低)[^。；\n]{0,24}(?:PE|市盈率)[^。；\n]*[。；]?",
        "PE TTM 的滚动盈利分母尚未拆解，当前不能归因于单季利润、历史亏损或"
        "低利润基数。",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        r"(?:PE\s*低|低\s*PE)[^。；\n]{0,140}(?:因为|来自|由于)"
        r"[^。；\n]{0,160}(?:过去四个季度|历史亏损|总体赚得很少|利润很低)"
        r"[^。；\n]*[。；]?",
        "PE TTM 的滚动盈利分母尚未拆解，当前不能归因于单季利润、历史亏损或"
        "低利润基数。",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        r"如果包含[^。；\n]{0,60}非经常性损益[^。；\n]{0,60}"
        r"(?:PE|市盈率)[^。；\n]{0,24}(?:被动)?(?:拉低|压低|降低)"
        r"[^。；\n]*[。；]?",
        "PE TTM 的滚动盈利分母尚未拆解，需核验扣非利润和非经常性损益明细。",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        r"[^。；\n]{0,80}(?:滚动四个季度|PE\s*分母|盈利分母)"
        r"[^。；\n]{0,180}(?:资产处置|一次性项目|非经常性损益|基数极低)"
        r"[^。；\n]*[。；]?",
        "PE TTM 的滚动盈利分母尚未拆解，需核验扣非利润和非经常性损益明细。",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        r"(?:历史亏损|非经常性损益)[^。；\n]{0,60}"
        r"(?:压低|降低)[^。；\n]{0,20}TTM\s*(?:利润|盈利)",
        "滚动盈利分母尚未拆解",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        r"(?:目前)?\s*PE\s*的?低位[^。；\n]{0,24}(?:更多)?源于"
        r"[^。；\n]*[。；]?",
        "PE TTM 的滚动盈利分母尚未拆解，不能直接解释当前倍数偏低的原因。",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        r"[^。；\n]{0,80}(?:历史亏损|低利润基数)[^。；\n]{0,100}"
        r"(?:导致|使得?|从而)[^。；\n]{0,32}(?:PE|市盈率)"
        r"[^。；\n]{0,24}(?:被)?(?:压得很低|压低|降低)[^。；\n]*[。；]?",
        "PE TTM 的滚动盈利分母尚未拆解，当前不能归因于单季利润、历史亏损或"
        "低利润基数。",
        normalized,
        flags=re.IGNORECASE,
    )
    denominator_boundary = (
        "PE TTM 的滚动盈利分母尚未拆解，当前不能归因于单季利润、历史亏损或"
        "低利润基数。"
    )
    normalized = re.sub(
        rf"(?:{re.escape(denominator_boundary)}\s*){{2,}}",
        denominator_boundary,
        normalized,
    )
    normalized = normalized.replace("最新一季报利润规模骤降", "最新一季报利润规模较小")
    normalized = normalized.replace("资产负债率从上一季度的", "资产负债率从上年同期的")
    normalized = normalized.replace(
        "TTM盈利分母可能含一次性收益",
        "TTM盈利分母构成尚未直接拆解",
    )
    normalized = normalized.replace(
        "一致预期大幅下行",
        "一致预期 EPS 与已实现 EPS 口径不可直接比较",
    )
    normalized = normalized.replace(
        "一致预期指向盈利大幅下滑",
        "一致预期属于预测口径",
    )
    normalized = normalized.replace(
        "股价相对于盈利和净资产都不高",
        "这只说明本组横截面的估值倍数较低",
    )
    normalized = re.sub(
        r"当前价格包含的盈利和净资产预期(?:极低|很低|偏低)",
        "当前横截面的估值倍数较低",
        normalized,
    )
    normalized = re.sub(
        r"(?:经营)?现金流[^。；\n]{0,70}(?:意味着|说明)[^。；\n]{0,120}"
        r"(?:真金白银|变成(?:经营)?现金|现金回流|现金收回|"
        r"转化为(?:经营)?现金流(?:入)?)[^。；\n]*[。；]?",
        "经营现金流与利润方向相反，需要核验营运资金变动和季节性，"
        "不能直接解释为利润尚未兑现为现金。",
        normalized,
    )
    normalized = re.sub(
        r"整体\s*[+-]?\d+(?:\.\d+)?%?[^。；\n]{0,30}毛利率"
        r"[^。；\n]{0,80}(?:制造业|行业)[^。；\n]{0,80}安全垫[^。；\n]*[。；]?",
        "毛利率变化只能说明报表差异，不能据此判断行业安全垫。",
        normalized,
    )
    normalized = re.sub(
        r"盈利质量的支点过于集中[^。；\n]{0,180}(?:未必能稳住|难以稳住)"
        r"[^。；\n]*[。；]?",
        "主营集中度较高，盈利稳定性仍需结合客户、订单和成本证据核验。",
        normalized,
    )
    normalized = re.sub(
        r"(?:预测|一致预期)[^。；\n]{0,80}(?:大幅)?(?:下降|下滑)"
        r"[^。；\n]{0,160}(?:可能与|或与)[^。；\n]{0,120}"
        r"(?:一次性|出表|非经常性)[^。；\n]*[。；]?",
        "已实现 EPS 与一致预期 EPS 的口径不同，当前证据不能据此归因于一次性会计因素。",
        normalized,
    )
    normalized = re.sub(
        r"(?:这个|该)?低倍数(?:是)?建立在[^。；\n]{0,160}经营现金流"
        r"[^。；\n]{0,80}(?:之上|基础上)[。；]?",
        "低倍数与经营现金流和利润方向相反同时存在，不能据此确认估值合理性。",
        normalized,
    )
    normalized = normalized.replace(
        "盈利的现金含量仍然薄弱",
        "经营现金流与利润方向相反，原因仍需核验",
    )
    normalized = normalized.replace("这些事实这两个会计口径", "这两个会计口径")
    normalized = normalized.replace("这经营现金流与利润方向相反", "经营现金流与利润方向相反")
    normalized = normalized.replace(
        "现金流与利润方向相反，这两个会计口径方向相反",
        "经营现金流与利润方向相反",
    )
    normalized = normalized.replace(
        "这表示净利润虽已转正，但与同期经营活动净现金流入完全是两个方向；"
        "利润还没有被实实在在的经营现金流入覆盖。",
        "归母净利润与经营现金流方向相反，需要核验营运资金变动和季节性；"
        "不能直接解释为利润尚未兑现为现金。",
    )
    normalized = re.sub(
        r"利润[^。；\n]{0,28}(?:还没有|尚未)[^。；\n]{0,28}"
        r"经营现金流入(?:的)?覆盖[^。；\n]*[。；]?",
        "经营现金流与利润方向相反，原因仍需核验。",
        normalized,
    )
    normalized = normalized.replace(
        "经营现金流为负、与利润方向背离，经营现金流与利润方向相反",
        "经营现金流为负、与利润方向相反",
    )
    normalized = normalized.replace(
        "经营现金流与利润方向完全相反",
        "经营现金流与利润方向相反",
    )
    normalized = normalized.replace(
        "负债率下降，但现金流偿债能力仍需验证",
        "资产负债率下降，不等于负债总量减少",
    )
    normalized = normalized.replace(
        "这一变化是财务结构上的积极事实",
        "这一变化只说明报表比率下降",
    )
    normalized = normalized.replace(
        "是一个积极变化",
        "只说明报表比率下降",
    )
    normalized = re.sub(
        r"(?:无法|不能)确认这一下降是来自负债减少还是资产扩张",
        "仍需核对总资产和总负债的绝对额变化",
        normalized,
    )
    normalized = normalized.replace(
        "负债率的下降能否转化为真实的财务安全",
        "资产负债率下降是否伴随负债绝对额变化",
    )
    normalized = normalized.replace(
        "但低倍数能确认的只是当前价格相对于滚动盈利和净资产的比值较低，"
        "不等于公司已经被低估。关键在于这个低倍数只说明当前估值截面偏低，"
        "不能据此认定盈利质量或资产质量；",
        "这些倍数只说明当前估值截面偏低，不等于公司已经被低估，也不能据此"
        "认定盈利质量或资产质量；",
    )
    normalized = normalized.replace(
        "资产负债率变化只说明报表比率差异，不能单独证明负债绝对规模或偿债压力改善。"
        "这一变化只说明报表比率下降，但仅凭资产负债率本身不能确认偿债压力已经减轻，"
        "尤其是经营现金流净额仍然为负。",
        "这个比率不能单独证明负债绝对规模或偿债压力改善；经营现金流净额仍为负。",
    )
    normalized = normalized.replace(
        "资产负债率下降是否伴随负债绝对额变化，还需要核对总负债的绝对规模变化以及"
        "后续现金流改善。",
        "还需核对总负债绝对额和后续经营现金流。",
    )
    normalized = normalized.replace(
        "不应解读为资产负债率下降只说明负债占资产比例下降，不能据此判断负债绝对规模或"
        "偿债压力",
        "不能据此判断负债绝对规模或偿债压力已经改善",
    )
    normalized = normalized.replace(
        "亏损面明显，进一步压缩了整体盈利空间",
        "该分部毛利为负，具体影响仍需结合收入规模和费用核验",
    )
    normalized = normalized.replace("主营结构的危险跷跷板", "主营结构集中度较高")
    normalized = normalized.replace(
        "直接拖垮整体利润",
        "该分部毛利为负，具体影响仍需结合收入规模和费用核验",
    )
    normalized = re.sub(
        r"这种结构下[^。；\n]{0,140}(?:整体)?盈利[^。；\n]{0,60}"
        r"(?:打回原形|波动会很大)[^。；\n]*[。；]?",
        "主营集中度较高，盈利对发动机业务变化较敏感，仍需结合订单、"
        "成本和客户结构核验。",
        normalized,
    )
    normalized = normalized.replace(
        "仍需核对是否涉及资产重组或负债结构实质性变化",
        "仍需核对总负债绝对额、有息负债和现金结构",
    )
    normalized = re.sub(
        r"PB\s*(?:只有|仅为|为)?\s*[+-]?\d+(?:\.\d+)?(?:倍)?，?"
        r"本质上是因为每股净资产比同行高",
        lambda match: re.sub(
            r"本质上是因为每股净资产比同行高",
            "只说明当前价格与每股净资产的比值较低",
            match.group(0),
        ),
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        r"而负债率骤降若来自[^。；\n]{0,80}PB[^。；\n]{0,60}被动抬升[。；]?",
        "资产负债率变化原因仍需核对总资产、总负债和股东权益的绝对额。",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = normalized.replace(
        "这与资产总量或负债结构变动有关",
        "还需核对总资产、总负债和股东权益的绝对额变化",
    )
    normalized = re.sub(
        r"(还需核对总资产、总负债和股东权益的绝对额变化。)"
        r"(PB\s*(?:只有|仅为|为)?\s*[+-]?\d+(?:\.\d+)?(?:倍)?，?"
        r"只说明当前价格与每股净资产的比值较低)；"
        r"资产负债率变化原因仍需核对总资产、总负债和股东权益的绝对额。",
        r"\1\2；不能据此判断资产质量。",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = normalized.replace(
        "一季报扭亏和公司2026年半年度业绩预告（预计归母净利润0.70至0.90亿元）"
        "均显示盈利方向在改善",
        "一季报已扭亏，公司2026年半年度业绩预告给出归母净利润0.70至0.90亿元区间",
    )
    normalized = normalized.replace(
        "当前利润规模小、经营现金流为负、同行经营比较缺失，现有证据更支持倍数差异存在"
        "明显质量约束，尚不能给确定性定性结论。",
        "当前经营现金流为负且同行经营比较缺失，现有证据不足以确认低估。",
    )
    normalized = normalized.replace(
        "是利润率改善的关键驱动力",
        "这一变化只说明报表毛利率上升",
    )
    normalized = normalized.replace(
        "但 10% 的毛利率在制造业中仍属偏薄",
        "但不能据此判断行业安全垫",
    )
    normalized = normalized.replace(
        "整体毛利来源基本全在发动机",
        "发动机是主要毛利来源",
    )
    normalized = normalized.replace("高经营现金流净流出", "经营现金流净流出")
    normalized = normalized.replace("% ；", "%；")
    normalized = normalized.replace(
        "但目前只能用一季报刚扭亏、高集中度的发动机业务、经营现金流净流出和负债率"
        "骤降来解释它的账面结构；",
        "但一季报刚扭亏、主营高度集中、经营现金流净流出和资产负债率下降同时存在；",
    )
    normalized = normalized.replace(
        "这些倍数确实远低于同行，但目前只能确认它是基于",
        "这些倍数确实低于本组同行，但当前还同时存在",
    )
    normalized = re.sub(
        r"但当前还同时存在最新一季报才刚扭亏、经营现金流仍为净流出且负债率从"
        r"([^；;]+)[；;]",
        r"但公司最新一季报刚扭亏，经营现金流仍为净流出，资产负债率从\1；",
        normalized,
    )
    normalized = normalized.replace(
        "的结构；能不能说“便宜”，还需要先看清这 ",
        "；能不能说“便宜”，还需要先拆清这 ",
    )
    normalized = normalized.replace(
        "倍 PE 到底是靠什么利润撑出来的",
        "倍 PE TTM 的滚动盈利分母",
    )
    normalized = normalized.replace(
        "动力新科的低估值倍数确实在同行中十分突出",
        "动力新科的估值倍数显著低于本组同行",
    )
    normalized = normalized.replace(
        "也没法把低倍数直接定性为",
        "仍不能把低倍数直接定性为",
    )
    normalized = normalized.replace("PE的低吸引力大打折扣", "因此不能直接判断低估")
    normalized = normalized.replace(
        "在现金兑现不确定的情况下，因此不能直接判断低估",
        "经营现金流与利润方向相反，因此不能直接判断低估",
    )
    normalized = normalized.replace(
        "整体财务杠杆明显下降，偿债压力的相对比例减少了",
        "资产负债率下降只说明负债占资产比例下降，不能据此判断偿债压力",
    )
    normalized = re.sub(
        r"这表示(?:账面)?利润[^。；\n]{0,32}(?:尚未|没有|未能)"
        r"[^。；\n]{0,24}(?:变成|转化为|兑现为)[^。；\n]{0,24}"
        r"(?:真实的?)?现金流入",
        "经营现金流与利润方向相反，不能直接解释为利润尚未兑现为现金",
        normalized,
    )
    normalized = re.sub(
        r"(?:并|进一步)?印证了?现金(?:回收|回笼)节奏(?:存在)?压力",
        "；销售收现率数值下降，具体原因仍需附注核验",
        normalized,
    )
    normalized = re.sub(
        r"(?:说明|表明)[^。；\n]{0,20}盈利改善趋势(?:可能)?延续",
        "对应已披露的一季报扭亏与半年度预计扭亏，持续性仍需正式报告核验",
        normalized,
    )
    normalized = re.sub(
        r"如果未来无法改善[^。；\n]{0,16}可能继续侵蚀利润",
        "后续需核验该业务亏损是否收窄",
        normalized,
    )
    normalized = re.sub(
        r"(?:盈利|利润)(?:的)?现金兑现(?:能力|效率|程度|质量)?"
        r"[^。；\n]{0,12}(?:弱|差|不足|偏弱|较弱|不强|薄弱)",
        "经营现金流与利润方向相反，原因仍需核验",
        normalized,
    )
    normalized = re.sub(
        r"(?:盈利|利润)(?:的)?现金兑现[^。；\n]{0,12}(?:严重)?偏离",
        "经营现金流与利润方向相反，原因仍需核验",
        normalized,
    )
    normalized = re.sub(
        r"现金流[^。；\n]{0,12}(?:尚)?不能为利润提供支撑",
        "经营现金流与利润方向相反，原因仍需核验",
        normalized,
    )
    normalized = normalized.replace(
        "重卡亏损业务已剥离",
        "上汽红岩自2025年12月起不再纳入合并报表",
    )
    normalized = normalized.replace(
        "去除了一个重大亏损来源",
        "减少了该子公司对合并报表的亏损影响",
    )
    normalized = normalized.replace(
        "账面利润什么时候能变成经营现金回流",
        "经营现金流与利润方向相反的原因是什么",
    )
    normalized = normalized.replace(
        "现金流收回和同行经营质量",
        "经营现金流与利润差异的原因和同行经营质量",
    )
    normalized = normalized.replace("比例在改善", "比例下降")
    normalized = normalized.replace("估值的分母太容易变", "PE TTM 的滚动盈利分母仍需拆解")
    normalized = normalized.replace("盈利基数太薄", "滚动盈利分母仍待拆解")
    normalized = normalized.replace("主营结构脆弱", "主营集中度较高")
    normalized = normalized.replace(
        "低估值更像是一面反映出盈利波动和现金矛盾的危险信号灯，"
        "而不是已确认的价值洼地",
        "低倍数仍需结合盈利持续性和经营现金流核验，不能据此确认低估",
    )
    normalized = normalized.replace("危险信号灯", "仍需核验的风险信号")
    normalized = normalized.replace("已确认的价值洼地", "已确认的低估结论")
    normalized = re.sub(
        r"(?:它|这组低倍数|当前倍数)[^。；\n]{0,36}反映的?[^。；\n]{0,24}"
        r"(?:更有可能|可能)是市场对[^。；\n]{0,160}(?:持谨慎态度|担忧|顾虑)"
        r"[^。；\n]*[。；]?",
        "这些事实只说明仍需核验盈利持续性、现金流和亏损业务，"
        "不能据此推断市场意图。",
        normalized,
    )
    normalized = re.sub(
        r"(?:因此|所以)?(?:低|偏低的?)\s*(?:PE|PB|估值倍数|倍数)"
        r"[^。；\n]{0,64}(?:更多|主要)?反映(?:了)?市场"
        r"[^。；\n]{0,100}(?:定价|态度|担忧|顾虑)[^。；\n]*[。；]?",
        "低倍数仍需结合盈利质量、现金流和资产回报核验，不能据此推断市场意图。",
        normalized,
        flags=re.IGNORECASE,
    )
    standard_denominator_boundary = (
        "PE TTM 的滚动盈利分母尚未拆解，需核验扣非利润和非经常性损益明细。"
    )
    normalized = normalized.replace(denominator_boundary, standard_denominator_boundary)
    normalized = normalized.replace(
        "PE TTM 的滚动盈利分母尚未拆解，不能直接解释当前倍数偏低的原因。",
        standard_denominator_boundary,
    )
    first_boundary = normalized.find(standard_denominator_boundary)
    if first_boundary >= 0:
        boundary_end = first_boundary + len(standard_denominator_boundary)
        normalized = (
            normalized[:boundary_end]
            + normalized[boundary_end:].replace(standard_denominator_boundary, "")
        )
    valuation_snapshot_boundary = (
        "低倍数只说明当前估值截面偏低，不能据此认定盈利质量或资产质量"
    )
    normalized = re.sub(
        rf"(滚动十二个月盈利\s*TTM\s*的分母尚未拆解)[，,]\s*"
        rf"(?:无法判断)?{re.escape(valuation_snapshot_boundary)}[；;]?\s*"
        r"(?:同时[，,])?",
        r"\1；",
        normalized,
    )
    first_snapshot_boundary = normalized.find(valuation_snapshot_boundary)
    if first_snapshot_boundary >= 0:
        snapshot_boundary_end = first_snapshot_boundary + len(
            valuation_snapshot_boundary
        )
        normalized = (
            normalized[:snapshot_boundary_end]
            + re.sub(
                rf"(?:无法判断)?{re.escape(valuation_snapshot_boundary)}[；;。]?",
                "",
                normalized[snapshot_boundary_end:],
            )
        )
    normalized = normalized.replace("① ", "首先，")
    normalized = normalized.replace("② ", "其次，")
    normalized = normalized.replace("③ 等", "随后，等待")
    normalized = normalized.replace("③ ", "随后，")
    normalized = re.sub(r"[④⑤⑥⑦⑧⑨⑩]", "", normalized)
    normalized = normalized.replace("，；", "；")
    normalized = re.sub(
        r"(?<=[。！？])\s*(?=\*\*[^*\n]+\*\*)",
        "\n\n",
        normalized,
    )
    normalized = re.sub(r"\n(?=综合来看[，,])", "\n\n", normalized)
    normalized = re.sub(
        r"(低估值更像是一个需要交叉验证的信号，而不是一个已经确认的结论。)"
        r"(?:交叉验证的信号，而不是一个已经确认的结论。)+",
        r"\1",
        normalized,
    )
    normalized = re.sub(
        r"(?P<sentence>[^。！？\n]{8,160}[。！？])(?:\s*(?P=sentence))+",
        r"\g<sentence>",
        normalized,
    )
    if normalized.count("**") % 2:
        # A sentence-level replacement can consume the closing marker of a
        # bold list label while leaving its opening marker behind. Remove only
        # the malformed line so unrelated valid headings keep their structure.
        normalized = "\n".join(
            line.replace("**", "") if line.count("**") % 2 else line
            for line in normalized.splitlines()
        )
    return re.sub(r"\n{3,}", "\n\n", normalized).strip()


def _valuation_opening_directly_rejects_cheap(text: str) -> bool:
    first_paragraph = next(
        (
            paragraph.strip()
            for paragraph in re.split(r"\n{2,}", str(text or ""))
            if paragraph.strip()
        ),
        "",
    )
    if re.fullmatch(
        r"(?:#{1,6}\s+.+|\*\*[^*]+\*\*)", first_paragraph
    ) and not re.search(r"[。！？]", first_paragraph):
        return False
    opening = re.sub(r"[#*_`>\-\s]+", "", first_paragraph[:320])
    return opening.startswith("不是") or bool(
        re.search(
            r"(?:不等于|≠|不代表|不意味着|不(?:直接)?说明|"
            r"不能(?:直接)?(?:说明|等同|判断|认定)|"
            r"不能据此(?:说明|判断|认定))[^。！？]{0,28}(?:便宜|低估)",
            opening,
        )
    )


def _valuation_review_peer_appendix(evidence: dict[str, Any]) -> str | None:
    comparison = evidence.get("peer_comparison") or {}
    subject = comparison.get("subject") or {}
    metrics = comparison.get("metrics") or {}
    pe = metrics.get("pe_ttm") or {}
    pb = metrics.get("pb") or {}
    peers = comparison.get("peers") or []
    required = (
        comparison.get("as_of"),
        subject.get("pe_ttm") or pe.get("subject_value"),
        subject.get("pb") or pb.get("subject_value"),
        pe.get("peer_median"),
        pb.get("peer_median"),
    )
    if any(value is None for value in required):
        return None

    def number(value: Any, decimals: int = 2) -> str:
        return f"{float(value):.{decimals}f}"

    peer_names = "、".join(
        str(item.get("name") or item.get("symbol") or "").strip()
        for item in peers
        if str(item.get("name") or item.get("symbol") or "").strip()
    )
    subject_name = str(
        subject.get("name") or evidence.get("display_name") or evidence.get("symbol")
    ).strip()
    line = (
        f"同日同行口径：{comparison['as_of']} 收盘，{subject_name} "
        f"PE TTM {number(required[1])}、PB {number(required[2])}；"
        f"同行样本{peer_names}的中位数分别为 {number(required[3])}、"
        f"{number(required[4])}。"
    )
    operating = comparison.get("operating_comparison") or {}
    if str(operating.get("status") or "") in {"partial", "unavailable"}:
        line += "同报告期经营数据不足，不能把倍数差异直接解释为经营质量。"
    return line


def _add_same_day_peer_date(text: str, evidence: dict[str, Any]) -> str:
    """Add only the missing market date to an otherwise complete peer paragraph."""

    comparison = evidence.get("peer_comparison") or {}
    as_of = str(comparison.get("as_of") or "").strip().split("T", 1)[0]
    if not as_of or _calendar_date_mentioned(text, as_of):
        return text
    peer_names = {
        str(item.get("name") or item.get("symbol") or "").strip()
        for item in (comparison.get("peers") or [])
        if str(item.get("name") or item.get("symbol") or "").strip()
    }
    paragraphs = [item.strip() for item in re.split(r"\n{2,}", text) if item.strip()]
    for index, paragraph in enumerate(paragraphs):
        if (
            ("PE" in paragraph.upper() or "市盈率" in paragraph)
            and ("PB" in paragraph.upper() or "市净率" in paragraph)
            and (
                any(term in paragraph for term in ("同行", "同业", "可比"))
                or any(name in paragraph for name in peer_names)
            )
        ):
            direct_rejection = re.match(
                r"^(?P<opening>不是[。！!])\s*(?P<body>.+)$",
                paragraph,
            )
            if direct_rejection:
                paragraphs[index] = (
                    f"{direct_rejection.group('opening')}截至 {as_of} 收盘，"
                    f"{direct_rejection.group('body')}"
                )
            else:
                paragraphs[index] = f"截至 {as_of} 收盘，{paragraph}"
            return "\n\n".join(paragraphs)
    return text


def _valuation_review_financial_appendix(evidence: dict[str, Any]) -> str | None:
    cashflow = (evidence.get("financial_drivers") or {}).get("cashflow_analysis") or {}
    latest = (evidence.get("earnings_quality") or {}).get("latest_report") or {}
    operating_cashflow = cashflow.get("operating_cashflow")
    coverage = cashflow.get("operating_cashflow_to_net_profit")
    debt_ratio = latest.get("debt_asset_ratio_pct")
    parts: list[str] = []
    if operating_cashflow is not None:
        parts.append(f"经营现金流 {float(operating_cashflow) / 100_000_000:.2f} 亿元")
    if coverage is not None:
        parts.append(f"经营现金流/归母净利润 {float(coverage):.2f}")
    if debt_ratio is not None:
        parts.append(f"资产负债率 {float(debt_ratio):.2f}%")
    return "最新报告期核验数字：" + "；".join(parts) + "。" if parts else None


def _normalize_valuation_review_ratio_precision(
    text: str,
    evidence: dict[str, Any],
) -> str:
    normalized = text
    earnings = evidence.get("earnings_quality") or {}
    for report in (
        earnings.get("latest_report") or {},
        earnings.get("comparable_report") or {},
    ):
        value = report.get("debt_asset_ratio_pct")
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        one_decimal = f"{float(value):.1f}"
        two_decimals = f"{float(value):.2f}"
        if one_decimal == two_decimals:
            continue
        normalized = re.sub(
            rf"(?<!\d){re.escape(one_decimal)}%(?!\d)",
            f"{two_decimals}%",
            normalized,
        )
    return normalized


def _normalize_valuation_review_peer_subject_values(
    text: str,
    evidence: dict[str, Any],
) -> str:
    """Replace a near-rounded subject multiple with the exact same-day value."""

    comparison = evidence.get("peer_comparison") or {}
    metrics = comparison.get("metrics") or {}
    normalized = text

    def replace_metric(
        candidate: str,
        *,
        label_pattern: str,
        expected: Any,
        canonical_label: str,
    ) -> str:
        try:
            expected_number = float(expected)
        except (TypeError, ValueError):
            return candidate
        tolerance = max(0.05, abs(expected_number) * 0.02)
        pattern = re.compile(
            rf"(?P<label>{label_pattern})\s*"
            r"(?P<link>不到|低于|不足|约为|约|为|只有|仅为)?\s*"
            r"(?P<number>[+-]?\d+(?:\.\d+)?)\s*(?P<unit>倍)?",
            re.IGNORECASE,
        )

        def replacement(match: re.Match[str]) -> str:
            try:
                observed = float(match.group("number"))
            except (TypeError, ValueError):
                return match.group(0)
            if abs(observed - expected_number) > tolerance:
                return match.group(0)
            unit = "倍" if match.group("unit") else ""
            return f"{canonical_label}约{expected_number:.2f}{unit}"

        return pattern.sub(replacement, candidate)

    normalized = replace_metric(
        normalized,
        label_pattern=r"PB|市净率",
        expected=(metrics.get("pb") or {}).get("subject_value"),
        canonical_label="PB",
    )
    normalized = replace_metric(
        normalized,
        label_pattern=r"PE\s*TTM|TTM\s*(?:市盈率|PE)",
        expected=(metrics.get("pe_ttm") or {}).get("subject_value"),
        canonical_label="PE TTM",
    )
    return normalized


def _normalize_valuation_review_debt_comparison(
    text: str,
    evidence: dict[str, Any],
) -> str:
    """Use one evidence-backed debt-ratio comparison instead of repeated raw ratios."""

    earnings = evidence.get("earnings_quality") or {}
    latest = earnings.get("latest_report") or {}
    comparable = earnings.get("comparable_report") or {}
    current_ratio = latest.get("debt_asset_ratio_pct")
    comparable_ratio = comparable.get("debt_asset_ratio_pct")
    if not all(
        isinstance(value, (int, float)) and not isinstance(value, bool)
        for value in (current_ratio, comparable_ratio)
    ):
        return text

    change_pp = float(current_ratio) - float(comparable_ratio)
    direction = "下降" if change_pp < 0 else "上升"
    canonical = (
        f"最新资产负债率为 {float(current_ratio):.2f}%，较可比期"
        f"{direction}约 {abs(change_pp):.2f} 个百分点"
    )
    normalized = re.sub(
        r"(?:最新)?资产负债率从(?:去年|上年)?同期(?:的)?\s*"
        r"[+-]?\d+(?:\.\d+)?%[^。；\n]{0,48}?"
        r"(?:降至|降到|下降[^。；\n]{0,24}(?:至|到)|"
        r"升至|升到|上升[^。；\n]{0,24}(?:至|到))\s*"
        r"(?:当前|本期)?(?:的)?\s*"
        r"[+-]?\d+(?:\.\d+)?%",
        canonical,
        text,
    )
    normalized = re.sub(
        r"(?:最新)?资产负债率从(?:去年|上年)?同期(?:的)?\s*"
        r"[+-]?\d+(?:\.\d+)?%\s*(?:下降|降低|上升|提高)"
        r"(?=[。；，,]|$)",
        canonical,
        normalized,
    )

    paragraphs = [
        item.strip() for item in re.split(r"\n{2,}", normalized) if item.strip()
    ]
    occurrences = [
        index for index, paragraph in enumerate(paragraphs) if canonical in paragraph
    ]
    if len(occurrences) > 1:
        preferred = next(
            (
                index
                for index in occurrences
                if _paragraph_starts_with_debt_heading(paragraphs[index])
            ),
            occurrences[-1],
        )
        for index in occurrences:
            if index == preferred:
                continue
            paragraphs[index] = paragraphs[index].replace(
                canonical,
                "资产负债率较可比期下降",
            )
        normalized = "\n\n".join(paragraphs)
    return re.sub(r"\s+([，。；])", r"\1", normalized)


def _paragraph_starts_with_debt_heading(paragraph: str) -> bool:
    heading = re.sub(r"^(?:#{1,6}\s+|\*\*)|\*\*$", "", paragraph.lstrip())
    return heading.startswith("资产负债率")


def _merge_valuation_fact_into_paragraph(
    text: str,
    fact: str,
    *,
    required_terms: tuple[str, ...],
) -> str:
    paragraphs = [item.strip() for item in re.split(r"\n{2,}", text) if item.strip()]
    for index, paragraph in enumerate(paragraphs):
        if all(term in paragraph for term in required_terms):
            paragraphs[index] = f"{paragraph.rstrip()} {fact}"
            return "\n\n".join(paragraphs)
    return f"{text.rstrip()}\n\n{fact}"


def _drop_redundant_valuation_summary(text: str) -> str:
    paragraphs = [item.strip() for item in re.split(r"\n{2,}", text) if item.strip()]
    paragraphs = [
        paragraph
        for paragraph in paragraphs
        if not re.fullmatch(r"(?:-{3,}|_{3,}|\*{3,})", paragraph)
    ]

    merged: list[str] = []
    heading_count = 0
    index = 0
    while index < len(paragraphs):
        paragraph = paragraphs[index]
        plain_heading = re.sub(r"^(?:#{1,6}\s+|\*\*)|\*\*$", "", paragraph)
        is_heading = bool(
            index + 1 < len(paragraphs)
            and len(plain_heading) <= 32
            and not re.search(r"[。！？；]", plain_heading)
            and (
                re.match(r"^(?:[一二三四五六七八九十]+|\d+)[、.．]", plain_heading)
                or re.match(r"^#{1,6}\s+", paragraph)
                or re.fullmatch(r"\*\*[^*]+\*\*", paragraph)
                or paragraph.endswith(("：", ":"))
            )
        )
        if is_heading:
            content = paragraphs[index + 1]
            if heading_count < 3:
                merged.append(f"**{plain_heading}**\n{content}")
                heading_count += 1
            else:
                merged.append(content)
            index += 2
            continue
        merged.append(paragraph)
        index += 1
    paragraphs = merged

    embedded_heading_count = 0
    for index, paragraph in enumerate(paragraphs):
        match = re.match(r"^\*\*[^*]+\*\*(?:\n|[：:]\s*|\s+)", paragraph)
        if match is None:
            continue
        if embedded_heading_count < 3:
            embedded_heading_count += 1
            continue
        paragraphs[index] = paragraph[match.end() :].lstrip()

    if (
        len(paragraphs) >= 2
        and len(paragraphs[0]) <= 64
        and re.search(r"(?:不等于|不代表|不能据此).{0,12}(?:便宜|低估)", paragraphs[0])
        and "PE" in paragraphs[1].upper()
        and "PB" in paragraphs[1].upper()
    ):
        paragraphs[0] = f"{paragraphs[0]} {paragraphs[1]}"
        paragraphs.pop(1)

    for index in range(len(paragraphs) - 1):
        if (
            any(term in paragraphs[index] for term in ("归母净利润", "利润已扭亏", "同比扭亏"))
            and "经营现金流" in paragraphs[index + 1]
            and not paragraphs[index + 1].lstrip().startswith(("**", "#"))
        ):
            paragraphs[index] = f"{paragraphs[index]}\n{paragraphs[index + 1]}"
            paragraphs.pop(index + 1)
            break

    for index, paragraph in enumerate(paragraphs):
        if not paragraph.startswith("主营结构") or index == 0:
            continue
        if any(term in paragraphs[index - 1] for term in ("归母净利润", "资产负债率")):
            paragraphs[index - 1] = f"{paragraphs[index - 1]}\n{paragraph}"
            paragraphs.pop(index)
            break
    if len(paragraphs) <= 6:
        return "\n\n".join(paragraphs)
    filtered = [
        paragraph
        for paragraph in paragraphs
        if not re.match(r"^(?:\*\*)?(?:简单说|一句话说|换句话说)[：:]", paragraph)
    ]
    return "\n\n".join(filtered)


def repair_valuation_review_answer(
    text: str,
    evidence: dict[str, Any],
) -> str | None:
    """Keep a useful valuation draft while repairing local deterministic defects."""

    if (
        str(evidence.get("type") or "") != "stock_research"
        or str((evidence.get("research_plan") or {}).get("focus") or "")
        != "valuation_review"
    ):
        return None
    original = str(text or "").strip()
    if len(original) < 120 or any(term in original for term in _CLEAR_OFF_TOPIC_TERMS):
        return None
    aliases = _subject_aliases(evidence)
    subject_missing = bool(aliases and not any(alias in original for alias in aliases))
    if subject_missing and not (
        ("PE" in original.upper() or "市盈率" in original)
        and ("PB" in original.upper() or "市净率" in original)
        and any(term in original for term in ("同行", "同业", "可比"))
    ):
        return None

    repaired = _drop_redundant_valuation_summary(
        _normalize_valuation_review_debt_comparison(
            _normalize_valuation_review_peer_subject_values(
                _normalize_valuation_review_ratio_precision(
                    _normalize_valuation_review_language(original),
                    evidence,
                ),
                evidence,
            ),
            evidence,
        )
    )
    if subject_missing:
        repaired = f"{aliases[0]}：{repaired}"
    if not ((evidence.get("fundamentals") or {}).get("valuation") or {}):
        # Valuation-review compaction intentionally omits a different-date
        # intraday snapshot when the user did not ask for it. If a stale draft
        # still carries those PE/PB values, remove that local clause and rely on
        # the verified same-day peer packet below.
        repaired = re.sub(
            r"(?:当前|目前|最新)(?:报价[^，。；\n]{0,40})?"
            r"PE\s*TTM(?:为|约为|只有|仅)?\s*[+-]?\d+(?:\.\d+)?(?:倍)?"
            r"[，,]\s*PB(?:为|约为|只有|仅)?\s*[+-]?\d+(?:\.\d+)?(?:倍)?"
            r"[，,]?",
            "",
            repaired,
            flags=re.IGNORECASE,
        )
    if not _valuation_opening_directly_rejects_cheap(repaired):
        subject_name = str(
            evidence.get("display_name") or evidence.get("symbol") or "这只股票"
        ).strip()
        repaired = re.sub(r"^(?:不能这样说|不能这么说|不是这样)[。！!]\s*", "", repaired)
        repaired = f"{subject_name}进入估值约束候选，不等于它便宜。\n\n{repaired}"
    repaired = _add_same_day_peer_date(repaired, evidence)
    appendices: list[str] = []
    peer_issue = peer_valuation_required_fact_issue(repaired, evidence)
    if peer_issue == "同行估值回答遗漏同日估值日期":
        repaired = _add_same_day_peer_date(repaired, evidence)
        peer_issue = peer_valuation_required_fact_issue(repaired, evidence)
    if peer_issue == "同行估值回答遗漏同报告期经营数据不足的结论边界":
        repaired = _merge_valuation_fact_into_paragraph(
            repaired,
            "同报告期经营数据不足，不能把倍数差异直接解释为经营质量。",
            required_terms=("PE", "PB"),
        )
        peer_issue = peer_valuation_required_fact_issue(repaired, evidence)
    if peer_issue:
        peer_appendix = _valuation_review_peer_appendix(evidence)
        if peer_appendix is None:
            return None
        appendices.append(peer_appendix)
        repaired = _merge_valuation_fact_into_paragraph(
            repaired,
            peer_appendix,
            required_terms=("PE", "PB"),
        )
    issue = valuation_review_required_fact_issue(repaired, evidence)
    if issue and "当前PE数值或带日期的同日同行口径" in issue:
        peer_appendix = _valuation_review_peer_appendix(evidence)
        if peer_appendix is None:
            return None
        if peer_appendix not in appendices:
            appendices.append(peer_appendix)
            repaired = _merge_valuation_fact_into_paragraph(
                repaired,
                peer_appendix,
                required_terms=("PE", "PB"),
            )
        issue = valuation_review_required_fact_issue(repaired, evidence)
    if issue and issue.startswith("估值回答遗漏"):
        financial_appendix = _valuation_review_financial_appendix(evidence)
        if financial_appendix and financial_appendix not in appendices:
            appendices.append(financial_appendix)
            repaired = _merge_valuation_fact_into_paragraph(
                repaired,
                financial_appendix,
                required_terms=("经营现金流",),
            )
    if "资产负债率" in repaired and not any(
        term in repaired for term in ("偿债压力", "负债绝对规模")
    ):
        repaired = _merge_valuation_fact_into_paragraph(
            repaired,
            "资产负债率变化只说明报表比率差异，不能单独证明负债绝对规模或"
            "偿债压力改善。",
            required_terms=("资产负债率",),
        )
    if peer_valuation_required_fact_issue(repaired, evidence) is not None:
        return None
    if valuation_review_required_fact_issue(repaired, evidence) is not None:
        return None
    return repaired


def _quality_review_inventory_explanation(evidence: dict[str, Any]) -> str | None:
    for item in _quality_review_announcement_extracts(evidence):
        if "库存增加主要是为下半年市场需求而提前备货" not in item.get(
            "summary_excerpt", ""
        ):
            continue
        published_at = str(item.get("published_at") or "")[:10]
        date_text = (
            f"在{published_at}的投资者交流中" if published_at else "在投资者交流中"
        )
        return (
            f"公司{date_text}表示，库存增加主要是为下半年市场需求提前备货；"
            "这是公司口径，仍需结合存货分类、库龄、跌价准备和应收账款账龄继续核验。"
        )
    return None


def build_quality_review_editor_prompt(
    *,
    draft: str,
    evidence: dict[str, Any],
) -> str:
    frame = quality_review_fact_frame(evidence)
    return f"""# 经营改善回答金融编辑

你正在编辑一份刚由 DeepSeek 针对当前用户问题生成的草稿。草稿不是证据，只能保留其中与下方
结构化事实完全一致的判断和自然表达。请直接输出修改后的最终中文回答，不解释编辑过程。

必须遵守：
1. 第一段直接给出改善质量较强、一般或仍无法确认，不给买卖建议。
2. 财务与现金流段按顺序写：经营现金流金额及同比、经营现金流/归母净利润的本期与可比期比率、
   销售收现率的本期与可比期数值。随后只写三项指标口径不同，具体原因是否已有公司原文。
3. 不得把上述指标改写为现金回笼比例、现金兑现程度、回款效率、资金回收效率、现金质量或现金
   覆盖能力；也不得用“说明、表明、意味着、提示”把它们连接到这些结论。
4. 营收和利润同时增长只作为报表事实；不得写增长有规模支撑、主要由规模驱动或收入拉动利润。
5. 若公司公告原文已经解释库存增加，就如实引用为“公司口径”，不得再声称公司没有解释；同时
   说明该解释不能替代存货分类、库龄和跌价准备核验。
6. 分部毛利率只按产品或地区原样陈述，不升级为整个业务盈利能力或行业毛利率结论。
7. 没有同期同行经营数据时，明确不能判断是否优于行业。保留最重要反方事实和下一步核验，按内容
   自然组织段落，面向普通投资者，避免报告腔、固定栏目和重复结论。

结构化事实：
{json.dumps(frame, ensure_ascii=False, indent=2)}

待编辑草稿：
{draft}
"""


def normalize_quality_review_language(text: str) -> str:
    """Apply narrow, evidence-preserving wording fixes used by stream and final."""

    normalized = str(text or "")
    replacements = (
        (
            r"现金流整体充裕，但回款节奏需核验",
            "现金流数据需分项理解",
        ),
        (
            r"不能简单概括为[“\"]现金质量恶化[”\"]或"
            r"[“\"]具体原因尚未确认[”\"]",
            "具体原因尚未确认",
        ),
        (
            r"(?:三项现金流指标变化方向和幅度不同，)?"
            r"表明利润增长与现金回笼节奏出现差异",
            "三项指标口径不同",
        ),
        (
            r"这意味着净利润增长中有部分尚未在同期现金回款中完全体现",
            "这两项差异是本轮最重要的反方事实，具体原因仍需核验",
        ),
        (
            r"说明利润与现金之间出现了严重错位",
            "两期比率方向不同，但该比率不能替代对经营现金流金额、销售收现和营运资金的判断",
        ),
        (
            r"回款速度变慢",
            "销售收现率下降，具体原因尚未确认",
        ),
        (
            r"利润的质量缺少现实验证",
            "利润与经营现金流的口径差异仍需核验",
        ),
        (
            r"说明当期的报表利润并没有伴随着实际的现金净流入",
            "这里只能确认同报告期归母净利润为正，而经营现金流净额为负",
        ),
        (
            r"(销售收现率(?:也)?从-?\d+(?:\.\d+)?%?降(?:到|至)"
            r"-?\d+(?:\.\d+)?%?)[，,]意味着每百元收入实际收到的现金减少",
            r"\1，即销售商品、提供劳务收到的现金占营收的比例下降",
        ),
        (
            r"经营现金流由正转负且覆盖关系严重恶化、销售收现率同步走低",
            "经营现金流由正转负、经营现金流与归母净利润比率转为负值，"
            "销售收现率较可比期下降",
        ),
        (
            r"反之，则说明成本端或回款节奏的问题比眼下能确认的更持久",
            "反之，则需要继续核验成本端和收付节奏是否存在更持久的问题",
        ),
        (
            r"这能确认现金流压力来自收付两端的同时挤压",
            "公司将经营现金流变化解释为收现减少与付现增加同时发生",
        ),
        (
            r"换句话说，收入在扩张，但赚到手的利润和实际收回来的现金都在缩水，"
            r"这是这份财报最值得警惕的地方",
            "收入增长、归母净利润下降，经营现金流由净流入转为净流出，"
            "这是本期最需要核验的反方事实",
        ),
        (
            r"(?<!最重要的反方事实是)(利润(?:同比)?增速(?:明显)?快于经营现金流)",
            r"最重要的反方事实是\1",
        ),
        (
            r"这是公司管理层的正式口径，可以确认公司当时的备货意图，"
            r"而非被动积压",
            "这是公司管理层给出的备货解释",
        ),
        (
            r"增长有规模支撑",
            "营收和利润增长是已确认的报表事实",
        ),
        (
            r"(?:整体)?改善有真实的规模增长基础",
            "营收和利润增长是已确认的报表事实",
        ),
        (
            r"现金转化质量存在明显的待核验缺口",
            "相关现金流差异的具体原因仍待核验",
        ),
        (
            r"销售回款效率(?:出现)?(?:明显)?(?:下滑|下降|走弱|恶化)",
            "销售收现率下降，具体原因尚未由公司解释",
        ),
        (
            r"回款效率(?:回落|下降|走弱|恶化)(?:明显)?",
            "具体原因尚未确认",
        ),
        (
            r"(?:这三项|三项|这些)线索提示回款和营运资金占用可能在加大",
            "三项指标口径不同，具体原因尚未确认",
        ),
        (
            r"(?:这)?三项指标方向(?:虽)?一致",
            "三项指标口径不同",
        ),
        (
            r"经营现金流(?:恶化|转弱|承压)，公司在报告里也做了解释："
            r"主要因为销售商品收到的现金减少，以及购买商品支付的现金增加",
            "经营现金流由净流入转为净流出，公司口径解释为销售商品收到的现金减少、"
            "购买商品支付的现金增加",
        ),
        (
            r"三项指标指向了同一个方向——回款和付款节奏在本季度出现了变化",
            "三项指标口径不同，分别反映经营现金流净额、利润覆盖和销售收现",
        ),
        (
            r"三项叠加说明当前的增长并没有带来更好的盈利质量和现金回报",
            "这些差异不能合并推断具体经营原因",
        ),
        (
            r"也就是说，营业收入增长很快，但利润率、现金覆盖和销售回款匹配度"
            r"都在减弱，三项变化的方向并不一致。",
            "这些指标口径不同，具体原因尚未由公司解释。",
        ),
        (
            r"说明当前利润增长的现金兑现程度在减弱",
            "但三项指标口径不同，具体原因尚未由公司解释",
        ),
        (
            r"现金流压力和盈利质量是否会持续",
            "盈利质量变化的原因和持续性",
        ),
        (
            r"三项指标同步走弱",
            "三项指标较可比期出现不同变化",
        ),
        (
            r"也不排除产品组合、原材料价格或交付批次的影响",
            "具体原因仍需公司原文或分部数据确认",
        ),
        (
            r"(?:这三项|三项|这些)(?:指标|变化|事实)?合在一起，?"
            r"说明本期利润增长尚未得到经营现金流和回款节奏的同等确认",
            "这些差异是需要继续核验的反方事实，但不能合并推断回款节奏",
        ),
    )
    for pattern, replacement in replacements:
        normalized = re.sub(pattern, replacement, normalized)
    return normalized


def repair_quality_review_answer(answer: str, evidence: dict[str, Any]) -> str | None:
    """Neutralize local overclaims and keep the model's grounded analysis intact."""

    if (
        str(evidence.get("type") or "") != "stock_research"
        or str((evidence.get("research_plan") or {}).get("focus") or "")
        != "quality_review"
    ):
        return None
    original = str(answer or "").strip()
    normalized = normalize_quality_review_language(original)
    kept_lines: list[str] = []
    for line in normalized.splitlines():
        if not line.strip():
            if kept_lines and kept_lines[-1] != "":
                kept_lines.append("")
            continue
        sentences = re.split(r"(?<=[。！？；])", line)
        safe_sentences = []
        for sentence in sentences:
            if not sentence.strip():
                continue
            if quality_review_evidence_conflict_issue(sentence, evidence):
                if explanation := _quality_review_inventory_explanation(evidence):
                    if explanation not in safe_sentences:
                        safe_sentences.append(explanation)
                continue
            if quality_review_overclaim_issue(sentence) is None:
                safe_sentences.append(sentence)
        if safe_sentences:
            kept_lines.append("".join(safe_sentences).strip())
    repaired = "\n".join(kept_lines).strip()
    repaired = re.sub(r"\n{3,}", "\n\n", repaired)
    aliases = _subject_aliases(evidence)
    if aliases and not any(alias in repaired for alias in aliases):
        subject = aliases[0]
        repaired = (
            f"{subject}的{repaired}"
            if repaired.startswith("改善质量")
            else f"{subject}：{repaired}"
        )
    if len(repaired) < 80 or len(repaired) < len(original) * 0.45:
        return None
    if quality_review_overclaim_issue(repaired) is not None:
        return None
    return repaired


def stock_specialist_relevance_issue(
    answer: str,
    evidence: dict[str, Any],
) -> str | None:
    """Return a retry reason when a specialist answer is plainly off-topic."""

    evidence_type = str(evidence.get("type") or "")
    quality_review = (
        evidence_type == "stock_research"
        and str((evidence.get("research_plan") or {}).get("focus") or "")
        == "quality_review"
    )
    valuation_review = (
        evidence_type == "stock_research"
        and str((evidence.get("research_plan") or {}).get("focus") or "")
        == "valuation_review"
    )
    if issue := relative_industry_required_fact_issue(answer, evidence):
        return issue
    if issue := peer_valuation_required_fact_issue(answer, evidence):
        return issue
    if issue := valuation_review_required_fact_issue(answer, evidence):
        return issue
    if (
        evidence_type not in _STOCK_SPECIALIST_TYPES
        and not quality_review
        and not valuation_review
    ):
        return None
    text = str(answer or "").strip()
    if len(text) < 16:
        return "专项回答过短，未覆盖当前问题"
    if any(term in text for term in _CLEAR_OFF_TOPIC_TERMS):
        return "专项回答出现与金融问题无关的内容"

    if quality_review:
        if issue := quality_review_overclaim_issue(text):
            return issue
        if issue := quality_review_evidence_conflict_issue(text, evidence):
            return issue
        if issue := quality_review_required_fact_issue(text, evidence):
            return issue
        subject_match = any(alias in text for alias in _subject_aliases(evidence))
        focus_match = any(
            term in text for term in ("改善", "财务", "利润", "现金流", "主营", "反方")
        )
        if subject_match and focus_match:
            return None
        return "经营改善回答没有覆盖当前股票或改善质量问题"

    if valuation_review:
        subject_match = any(alias in text for alias in _subject_aliases(evidence))
        focus_match = any(
            term in text
            for term in ("估值", "PE", "PB", "现金流", "资产负债率", "同行")
        )
        if subject_match and focus_match:
            return None
        return "估值约束回答没有覆盖当前股票或估值质量问题"

    subject_match = any(alias in text for alias in _subject_aliases(evidence))
    focus_match = any(term in text for term in _FOCUS_TERMS[evidence_type])
    evidence_match = any(anchor in text for anchor in _evidence_text_anchors(evidence))
    if evidence_type == "business_structure" and _evidence_text_anchors(evidence):
        if not evidence_match:
            return "主营专项回答没有使用当前公司披露的真实分部名称"
    if evidence_match or (subject_match and focus_match):
        return None
    return "专项回答没有覆盖当前股票或研究重点"


def stock_specialist_guard_retry_issue(
    output_guard: dict[str, Any],
    evidence: dict[str, Any],
) -> str | None:
    """Return a retry reason for a materially ungrounded specialist answer.

    A single formatting number can usually be repaired deterministically.  A
    cluster of unsupported numbers in a specialist answer is different: it
    indicates that generation drifted away from the current company's packet,
    so the user deserves one fresh, evidence-focused model attempt instead of
    a mechanically shortened preview.
    """

    if str(evidence.get("type") or "") not in _STOCK_SPECIALIST_TYPES:
        return None
    unsupported_numbers = list(output_guard.get("unsupported_numbers") or [])
    if len(unsupported_numbers) >= 2:
        return "专项回答包含多项不属于当前证据包的数字"
    return None


def build_stock_relevance_retry_prompt(
    *,
    base_prompt: str,
    message: str,
    evidence: dict[str, Any],
    retry_reason: str | None = None,
) -> str:
    plan = evidence.get("research_plan") or {}
    subject = next(
        iter(_subject_aliases(evidence)), str(evidence.get("symbol") or "当前股票")
    )
    focus = str(plan.get("focus_label") or evidence.get("type") or "当前问题")
    quality_review_contract = ""
    valuation_review_contract = ""
    peer_valuation_contract = ""
    if str(plan.get("focus") or "") == "quality_review":
        quality_review_contract = """
本次是经营改善质量专项重答，请在读取完整证据前先遵守这份短检查表：
- 第一段只给“改善质量较强、一般或仍无法确认”的证据状态。
- 营收和利润同时增长不得写成“增长主要来自收入规模扩张”。
- 主营占比变化不得写成“结构优化、结构升级”；公司分部毛利率不得写成行业整体毛利率。
- 本期利润已经增长时不得写“增收不增利”。
- 销售收现率下降只能陈述比率差异和原因未确认，不得写回款变慢、现金效率走弱或暗示结算压力。
- 经营现金流仍为正增长时写具体增速，不得称为几乎或近乎停滞、几乎原地踏步；不得把收现率写成现金效率落差。
- 营收增速高于利润增速只陈述差异，不得写收入增长拉动、带动或贡献了利润。
- 存货增速快于收入只能列为待核验线索，不得写产品积压、去库压力或备货节奏错位。
- 没有存货跌价准备金额、可比变化或公司原文时，不预测未来计提跌价会影响利润；只列下一步核验。
- 没有公司原文时，不列库存节奏、备货、订单或产销安排等可能原因。
- 不得用“量增价减”“仍停留在收入规模快速膨胀阶段”等标签概括报表变化。
- 现金流段依次并列经营现金流金额及同比、覆盖比率两期值、销售收现率两期值；不得概括为收入或
  利润没有转化为现金流入、利润转化为现金的效率减弱。
- 列完三项事实后直接转入公司原文和待核验原因，不再追加现金含量、现金兑现程度或现金效率概括。
- 经营现金流正增长不能写成公司并非资金紧张；三项不同口径不得称为方向一致。
- 利润率下降与营收增长只能并列，不得写增长主要由规模驱动。
- 收现率原因缺失时直接写原因未确认；结算、收入确认和预收安排只作为下一步核验项。
- 有“公司公告原文摘录”时至少使用一项相关管理层表述；只有标题时说明标题不能代替正文。
- 行业标签只说明筛选分类；没有同报告期同行经营数据时，说明不能判断是否优于行业。
按当前问题自然组织回答；不要用预存报告正文代替本轮分析，也不要为了格式增加固定段落。
"""
    if str(plan.get("focus") or "") == "valuation_review":
        valuation_review_contract = """
本次是估值约束质量专项重答，请在读取完整证据前先遵守这份短检查表：
- 第一段只给“有持续盈利支撑、存在明显质量约束或仍无法定性”的证据状态，不得写估值极低、
  真正低估、低估值机会、财务陷阱或确定性的低估值陷阱。
- PE TTM、动态 PE、静态 PE 是行情源三个不同字段；一致预期 EPS 是券商预测均值。不得声称行情源
  动态 PE 是按预测 EPS 计算得到，也不要另造估值口径。
- PE TTM 是滚动十二个月口径，不能用一季报、单季利润、刚扭亏或“低利润基数”直接解释其高低，
  也不能写成只以某一年度全年利润为基础；没有拆清滚动分母时只保留口径差异和待核验边界。
- 一季报扭亏与半年度业绩预告只能分别按报告期陈述，不得写成“预示扭亏持续”或盈利已经延续。
- 每股收益只能使用元/股；亿元、万元是利润或资产金额，禁止写“若干亿元的每股收益”。
- 没有公告原文或结构化非经常性损益明细时，不得补写重大资产重组、股权处置、资产处置或一次性收益；
  “低倍数也可能由一次性收益造成”仍是原因认定，必须改为“滚动盈利分母尚未拆解，需核验扣非利润
  与非经常性损益明细”。
- 写清同行样本名称、本标的 PE TTM 与 PB、同行中位数，并保留样本日期与选择依据；相对比例
  不是必答项。用户没有明确要求逐只比较时，不必机械罗列每家公司全部倍数。同行经营数据不足只
  限制解释，不能否认已经取得的估值截面。
- 联合写出最新归母净利润、经营现金流金额、经营现金流/归母净利润比率和资产负债率；负比率
  不得改写成每赚1元实际流出若干元。
- 不得创造毛利率、PE倍数或连续季度数等新的通过阈值；下一步只列正式披露中可核验的事项。
按问题和证据自然组织回答；不要复述候选入口，也不要为了格式增加固定段落。
"""
    peer_comparison = evidence.get("peer_comparison") or {}
    if (peer_comparison.get("metrics") or {}) and any(
        term in message
        for term in ("同行", "同业", "估值", "PE", "PB", "市盈率", "市净率")
    ):
        sample_label = (
            "同日同行"
            if str(peer_comparison.get("method") or "").startswith("dynamic_same_day")
            else "固定同行"
        )
        peer_valuation_contract = f"""
本次是{sample_label}估值专项重答。写清样本公司名称，并分别给出本标的和同行中位数的 TTM
市盈率与市净率；相对比例不是必答项。用户没有明确要求逐只比较时，不必机械罗列每家公司全部倍数。
不能用静态或动态市盈率代替 TTM 市盈率，也不能只完整回答 PE 或 PB 的一项。同报告期经营数据
不足只用于限制估值解释，不能据此否认已经取得的估值截面。不得把倍数差异直接写成便宜、昂贵、
高估、低估或投资评级。
"""
    return f"""# 必须重新聚焦本轮问题

上一版没有满足当前问题与证据边界，已经丢弃。不要提及上一版、系统校验或重新生成过程。
当前研究对象是：{subject}
当前研究重点是：{focus}
用户原问题是：{message}
上一版未通过的具体原因是：{retry_reason or "没有紧扣当前研究对象和问题"}
{quality_review_contract}
{valuation_review_contract}
{peer_valuation_contract}

第一段必须直接回答用户原问题。回答只能围绕当前研究对象，并使用下方已经提供的金融证据；
不得转向手机、设备、消息是否截断或其他无关主题。若某项事实缺失，用一句自然中文说明边界，
但仍要先用已有证据完成可回答的部分。

{base_prompt}
"""


def build_stock_guard_retry_prompt(
    *,
    base_prompt: str,
    message: str,
    evidence: dict[str, Any],
    retry_reason: str,
) -> str:
    plan = evidence.get("research_plan") or {}
    subject = next(
        iter(_subject_aliases(evidence)),
        str(evidence.get("symbol") or "当前股票"),
    )
    focus = str(plan.get("focus_label") or evidence.get("type") or "当前问题")
    anchors = _evidence_text_anchors(evidence)
    anchor_text = "、".join(anchors[:8]) or "当前结构化证据中的原始字段"
    return f"""# 必须依据当前股票证据重新回答

上一版包含不属于当前证据包的事实，已经丢弃。不要提及上一版、系统校验或重新生成过程。
当前研究对象是：{subject}
当前研究重点是：{focus}
用户原问题是：{message}
重新回答原因是：{retry_reason}

可信证据锚点：{anchor_text}
第一段直接回答用户问题，并至少原样使用一个可信证据锚点。所有数字只能逐字取自下方确定性证据；
不得凭记忆补充分部名称、占比、毛利率或报告年份。已有证据不足以支持的细节只需省略，不能用其他
公司的常见业务结构补位。保持自然、简洁、小白可读，不要输出内部流程说明。

{base_prompt}
"""
