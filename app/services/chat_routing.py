from __future__ import annotations

from datetime import datetime
import re
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from app.catalog import RESEARCH_TARGETS, SECURITY_NAME_ALIASES, normalize_symbol
from app.services.market_news import MarketNewsService


__all__ = (
    "_extract_symbol",
    "_extract_symbols",
    "_is_li_zong_strategy_followup",
    "_is_stock_screen_query",
    "_stock_screen_parameters",
    "_conversation_title",
    "_extract_industry_topic",
    "_extract_thesis",
    "_intent_from_history",
    "_is_analyst_expectations_query",
    "_is_business_structure_query",
    "_is_contextual_followup",
    "_is_deep_stock_coverage_query",
    "_is_earnings_quality_query",
    "_is_event_timeline_query",
    "_is_financial_driver_query",
    "_is_market_query",
    "_is_market_ticker_reference",
    "_is_peer_comparison_query",
    "_is_research_action_query",
    "_is_research_outcome_query",
    "_is_research_priority_query",
    "_is_research_tracking_query",
    "_is_shareholder_query",
    "_is_watchlist_daily_query",
    "_market_date",
    "_market_key_from_history",
    "_market_question_focus",
    "_needs_research_object_clarification",
    "_needs_stock_market_context",
    "_prefers_stock_context_followup",
    "_question_market_date",
    "_question_price_direction",
    "_stock_screen_profile_from_history",
    "_symbol_from_history",
    "_symbols_from_history",
)

def _extract_symbol(
    explicit: str | None,
    message: str,
    watchlist: list[dict[str, Any]] | None = None,
) -> str | None:
    symbols = _extract_symbols(explicit, message, watchlist=watchlist)
    return symbols[0] if symbols else None


def _extract_symbols(
    explicit: str | None,
    message: str,
    watchlist: list[dict[str, Any]] | None = None,
) -> list[str]:
    candidates: list[tuple[int, int, str]] = []
    if explicit:
        try:
            candidates.append((-1, 0, normalize_symbol(explicit)))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    for match in re.finditer(r"(?<!\d)(\d{6})(?!\d)", message):
        candidates.append((match.start(), 0, normalize_symbol(match.group(1))))
    aliases = dict(SECURITY_NAME_ALIASES)
    aliases.update(
        {
            str(target.get("name") or "").strip(): symbol
            for symbol, target in RESEARCH_TARGETS.items()
            if str(target.get("name") or "").strip()
        }
    )
    for item in watchlist or []:
        name = str(item.get("name") or "").strip()
        symbol = str(item.get("symbol") or "").strip()
        if name and symbol:
            aliases[name] = symbol
    folded_message = message.casefold()
    for alias, symbol in sorted(
        aliases.items(), key=lambda item: len(item[0]), reverse=True
    ):
        folded_alias = alias.casefold()
        if not folded_alias:
            continue
        start = 0
        while True:
            index = folded_message.find(folded_alias, start)
            if index < 0:
                break
            candidates.append((index, -len(alias), normalize_symbol(symbol)))
            start = index + max(1, len(folded_alias))
    ticker_pattern = re.compile(
        r"(?<![A-Z0-9])([A-Z]{1,5}(?:[.=-][A-Z0-9]{1,5})?)(?![A-Z0-9])"
    )
    for ticker in ticker_pattern.finditer(message):
        # T+3/T+5/T+10 are research horizons, not the NYSE ticker T.  Resolve
        # natural-language company aliases first, then skip every horizon-like
        # token while continuing to search for a real ticker later in the text.
        suffix = message[ticker.end(1) :]
        if re.match(r"\s*\+\s*\d+", suffix):
            continue
        raw_ticker = ticker.group(1)
        following_text = message[ticker.end(1) : ticker.end(1) + 24]
        if raw_ticker.upper() == "CS" and re.match(
            r"\s*[\u4e00-\u9fff]{1,12}(?:行业|板块|指数)",
            following_text,
        ):
            # “CS电池”是中证行业指数简称，不是第二只股票。把 CS 当成
            # 美股代码会把单股相对行业问题误路由到多股比较，随后整套
            # 精确行业指数证据都会丢失。
            continue
        if raw_ticker.upper() in {
            "PE",
            "PB",
            "PS",
            "ROE",
            "ROA",
            "EPS",
            "TTM",
            "ETF",
            "LOF",
            "REIT",
            "REITS",
            "QDII",
            "SZ",
            "SS",
            "SH",
        }:
            continue
        if len(raw_ticker) == 1:
            before = message[max(0, ticker.start(1) - 16) : ticker.start(1)]
            after = following_text
            explicit_single_ticker = bool(
                re.search(
                    r"(?:分析|研究|看看|查看|评估|跟踪|股票|美股|证券代码|"
                    r"ticker)\s*$",
                    before,
                    re.IGNORECASE,
                )
                or re.match(
                    r"\s*(?:的\s*)?(?:最新)?(?:股价|股票|公司|财报|业绩|"
                    r"估值|行情|市值|公告)",
                    after,
                    re.IGNORECASE,
                )
            )
            if not explicit_single_ticker:
                continue
        if not _is_market_ticker_reference(raw_ticker, message):
            candidates.append(
                (ticker.start(1), 0, normalize_symbol(raw_ticker))
            )
    output: list[str] = []
    for _, _, symbol in sorted(candidates, key=lambda item: (item[0], item[1])):
        if symbol not in output:
            output.append(symbol)
    return output


def _is_stock_screen_query(message: str) -> bool:
    folded = re.sub(r"\s+", "", message).casefold()
    product_terms = (
        "股票型基金",
        "股票基金",
        "债券型基金",
        "债券基金",
        "指数基金",
        "货币基金",
        "混合基金",
        "基金",
        "etf",
        "lof",
        "reits",
        "reit",
        "qdii",
    )
    screening_text = folded
    for term in product_terms:
        screening_text = screening_text.replace(term, "")
    # “该选股票基金还是债券基金”里的“选股/选股票”只是产品名称
    # 交界，不能启动全A股筛选。若句子还明确要求筛选股票，下面的
    # 正常规则仍会识别。
    if screening_text != folded and not any(
        term in screening_text
        for term in (
            "筛选股票",
            "筛股票",
            "筛选a股",
            "筛a股",
            "候选股票",
            "股票候选",
            "研究候选",
            "选股策略",
        )
    ):
        if not re.search(
            r"(?:找|挑|筛|选)(?:一些|几只|一批)?[^。；，,]{0,12}(?:股票|公司)",
            screening_text,
        ):
            return False
    folded = screening_text
    # Candidate cards are evidence for a bound stock conversation, not a request
    # to run the whole-market screener again.  In particular, wording such as
    # "不要复述选股卡片" previously matched the bare "选股" expression below and
    # silently sent an otherwise stock-specific question back to stock_screen.
    # Remove references to an existing screening artefact before detecting an
    # actual screening action.  Explicit requests such as "重新选股" and
    # "筛选几只股票" remain untouched.
    folded = re.sub(
        r"(?:不要|别|无需|不必|不需要|并非要|不是要|没让你|没有让你)"
        r"(?:再|重新)?[^。！？；]{0,16}"
        r"(?:选股|候选)(?:卡片|文案|结果|入口|说明)?",
        "",
        folded,
    )
    folded = re.sub(
        r"(?:复述|重复|照搬|引用|查看|解释|评价)"
        r"[^。！？；]{0,8}(?:选股|候选)(?:卡片|文案|结果|入口)",
        "",
        folded,
    )
    direct_terms = (
        "筛选股票",
        "筛股票",
        "筛选a股",
        "筛a股",
        "研究候选",
        "候选股票",
        "股票候选",
        "经营改善模板",
        "经营改善候选",
        "相对行业增强模板",
        "相对行业增强候选",
        "估值约束模板",
        "估值约束候选",
        "回撤后待复核",
        "低估值股票",
        "业绩增长股票",
        "趋势增强股票",
        "回撤企稳股票",
    )
    if re.search(r"(?<!自)选股", folded) or any(
        term in folded for term in direct_terms
    ):
        return True
    if re.search(
        r"(?:按|用|使用|运行|执行)(?:一下|一次)?"
        r"(?:相对行业增强|估值约束)(?:模板)?(?:筛选|选股|候选)?",
        folded,
    ):
        return True
    return bool(
        re.search(
            r"(?:找|挑|筛|选)(?:一些|几只|一批)?[^。；，,]{0,12}(?:股票|公司)", folded
        )
    )


def _is_li_zong_strategy_followup(message: str) -> bool:
    """Recognize strategy-specific follow-ups even without the words '李总策略'."""
    folded = re.sub(r"\s+", "", message).casefold()
    candidate_terms = ("候选", "观察池", "8/9", "6/9", "7/9", "九条", "9条")
    rule_terms = (
        "触发",
        "规则",
        "通过",
        "未通过",
        "盘后",
        "复核",
        "涨停",
        "阴线",
        "新高",
        "倍量",
        "roe",
        "市值",
        "股东",
    )
    return any(term in folded for term in candidate_terms) and any(
        term in folded for term in rule_terms
    )


def _stock_screen_parameters(message: str) -> dict[str, Any]:
    folded = re.sub(r"\s+", "", message).casefold()
    if any(term in folded for term in ("回撤", "超跌", "企稳", "跌下来")):
        profile = "pullback"
    elif any(
        term in folded for term in ("趋势", "强势", "跑赢行业", "相对行业", "动量")
    ):
        profile = "trend"
    elif any(
        term in folded
        for term in (
            "低估值",
            "估值低",
            "估值约束",
            "价值",
            "市盈率",
            "市净率",
            "pe",
            "pb",
        )
    ):
        profile = "value"
    else:
        profile = "quality"

    market = "all"
    if "科创板" in folded:
        market = "star"
    elif "创业板" in folded:
        market = "gem"
    elif "北交所" in folded or "北证" in folded:
        market = "bj"
    elif "沪市" in folded or "上交所" in folded:
        market = "sh"
    elif "深市" in folded or "深交所" in folded:
        market = "sz"
    elif "主板" in folded:
        market = "main"

    count_match = re.search(r"(?:前|最多|给我|找|选|筛)?(\d{1,2})只", folded)
    max_results = min(30, max(1, int(count_match.group(1)))) if count_match else 12
    filters: dict[str, Any] = {}

    def number(pattern: str) -> float | None:
        match = re.search(pattern, folded, re.IGNORECASE)
        return float(match.group(1)) if match else None

    patterns = {
        "max_pe_ttm": r"(?:pe|市盈率)(?:ttm)?(?:低于|小于|不高于|不超过|≤|<=|<)?(\d+(?:\.\d+)?)倍?(?:以下)?",
        "max_pb": r"(?:pb|市净率)(?:低于|小于|不高于|不超过|≤|<=|<)?(\d+(?:\.\d+)?)倍?(?:以下)?",
        "min_roe": r"roe(?:高于|大于|不低于|至少|超过|≥|>=|>)?(\d+(?:\.\d+)?)%?",
        "min_revenue_yoy": r"(?:营收|营业收入)(?:同比)?(?:增长|增速)?(?:高于|大于|不低于|至少|超过|≥|>=|>)?(\d+(?:\.\d+)?)%",
        "min_net_profit_yoy": r"(?:净利润|归母净利润)(?:同比)?(?:增长|增速)?(?:高于|大于|不低于|至少|超过|≥|>=|>)?(\d+(?:\.\d+)?)%",
    }
    for key, pattern in patterns.items():
        value = number(pattern)
        if value is not None:
            filters[key] = value

    market_cap_match = re.search(
        r"(?:总)?市值(?:在)?(\d+(?:\.\d+)?)(?:亿|亿元)(?:以上|起|到(\d+(?:\.\d+)?)(?:亿|亿元))?",
        folded,
    )
    if market_cap_match:
        filters["min_market_cap_yi"] = float(market_cap_match.group(1))
        if market_cap_match.group(2):
            filters["max_market_cap_yi"] = float(market_cap_match.group(2))
    else:
        minimum_cap = number(
            r"(?:总)?市值(?:高于|大于|不低于|至少|超过|≥|>=|>)(\d+(?:\.\d+)?)(?:亿|亿元)"
        )
        maximum_cap = number(
            r"(?:总)?市值(?:低于|小于|不高于|不超过|≤|<=|<)(\d+(?:\.\d+)?)(?:亿|亿元)"
        )
        if minimum_cap is not None:
            filters["min_market_cap_yi"] = minimum_cap
        if maximum_cap is not None:
            filters["max_market_cap_yi"] = maximum_cap

    industry_match = re.search(
        r"([\u4e00-\u9fff]{2,10})(?:行业|板块)(?:里|内|中的|的)?(?:股票|公司)",
        folded,
    )
    if industry_match:
        industry = industry_match.group(1)
        industry = re.sub(r"^(?:帮我|请|找|筛选|筛|选|一些)", "", industry)
        if industry:
            filters["industry"] = industry

    return {
        "profile": profile,
        "market": market,
        "max_results": max_results,
        "filters": filters or None,
    }

def _is_market_query(message: str) -> bool:
    folded = re.sub(r"\s+", "", message).casefold()
    # “市场”也常出现在公司经营语境里，例如“市场需求”“市场份额”或
    # “市场竞争”。这些短语描述的是公司的终端需求或竞争位置，并不是
    # 用户要求离开当前个股去诊断大盘。先移除这些高频经营搭配，再识别
    # 真正的市场、指数和资产类别对象。
    market_scope_text = re.sub(
        r"市场(?:需求|份额|占有率|空间|规模|容量|竞争|格局|地位|"
        r"渗透率|拓展|开拓|销售|订单|定价|价格)",
        "",
        folded,
    )
    market_scope_text = re.sub(
        r"行业(?:边界|口径|约束|可比性|比较边界|对比边界|数据|证据)",
        "",
        market_scope_text,
    )
    market_terms = (
        "大盘",
        "市场",
        "板块",
        "行业",
        "指数",
        "行情",
        "美股",
        "a股",
        "港股",
        "日股",
        "日本股市",
        "韩股",
        "韩国股市",
        "欧股",
        "欧洲股市",
        "伦敦金",
        "现货黄金",
        "黄金",
        "标普",
        "s&p",
        "纳指",
        "纳斯达克",
        "道指",
        "道琼斯",
        "上证",
        "深证",
        "创业板",
        "沪深300",
        "中证500",
        "恒生",
        "日经",
        "kospi",
        "vix",
        "dax",
    )
    # Trading-session words describe a time state, not a research object.
    # Treating “盘中/收盘” alone as an explicit market request used to switch
    # stock follow-ups such as “现在仍在盘中吗” from the current company to the
    # default A-share market.  Explicit market routing therefore requires an
    # actual market, index, sector, or asset-class reference.
    return any(term in market_scope_text for term in market_terms)


def _extract_industry_topic(message: str) -> str | None:
    folded = re.sub(r"\s+", "", str(message or ""))
    match = re.search(
        r"(?P<topic>[A-Za-z0-9\u4e00-\u9fff]{2,18}?)(?:行业|板块)",
        folded,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    topic = match.group("topic")
    topic = re.sub(
        r"^(?:请|帮我|麻烦|我想|我想看|我想了解|看看|看下|分析|研究|聊聊|说说|"
        r"当前|今天|最近|目前|A股|a股)+",
        "",
        topic,
        flags=re.IGNORECASE,
    )
    topic = topic.strip("，。！？,.!?：:")
    # “现金流和行业边界”“估值与行业口径”中的“行业”是研究维度，
    # 前面的并列成分不是行业名称。若把它抽成行业主题，会让绑定个股的
    # 财务追问错误离开当前研究空间。
    if topic.endswith(("和", "与", "及")):
        return None
    if topic in {"这个", "该", "什么", "哪个", "整体", "当前", "最近"}:
        return None
    return topic or None


def _market_question_focus(message: str) -> dict[str, Any]:
    folded = re.sub(r"\s+", "", message).casefold()
    counter_evidence_terms = ("反方", "反证", "相反证据")
    index_breadth_gap_question = any(
        term in folded for term in ("为什么", "为何", "怎么回事", "发生了什么")
    ) and any(
        term in folded
        for term in (
            "指数表现",
            "指数和大多数个股",
            "指数与大多数个股",
            "多数个股的体感",
            "大多数个股的体感",
            "个股的体感",
            "账户体感",
        )
    )
    if index_breadth_gap_question:
        return {
            "key": "market_cause",
            "label": "指数与个股体感差异",
            "answer_requirements": [
                "先用同日指数、涨跌家数和涨跌幅中位数说明体感差异",
                "没有成分权重贡献或风格指数时不猜差异来源",
                "成交额与资讯标题只作为当日背景，不替代指数归因",
            ],
        }
    focus_rules = (
        (
            "market_risk",
            "市场风险与重新判断条件",
            (
                "风险",
                "回撤",
                "危险",
                "担心",
                "失效",
                "承压",
                "不成立",
                "推翻",
                "重新判断",
                "证据缺口",
            ),
            [
                "优先比较回撤、波动、趋势和关键均线位置",
                "说明风险已经发生的证据与仍未发生的情形",
                "不生成仓位或买卖指令",
            ],
        ),
        (
            "trend_reversal",
            "反弹与趋势确认",
            ("反弹", "反转", "企稳", "见底", "趋势", "牛市", "修复"),
            [
                "区分单日反弹、短期修复和中期趋势反转",
                "优先比较1日、5日、20日收益及均线位置",
                "给出尚未满足的确认条件和反方证据",
            ],
        ),
        (
            "sector_rotation",
            "板块轮动与市场广度",
            (
                "板块",
                "行业",
                "热点",
                "题材",
                "领涨",
                "领跌",
                "轮动",
                "普涨",
                "结构性",
                "市场广度",
                "上涨下跌家数",
                "涨跌幅分布",
            ),
            [
                "优先回答热门板块、上涨广度和结构分化",
                "区分指数上涨与少数板块拉动",
                "板块涨幅不外推为持续性或交易信号",
            ],
        ),
        (
            "volume_flows",
            "量能与资金线索",
            ("成交量", "成交额", "放量", "缩量", "量能", "资金", "北向", "etf"),
            [
                "优先解释指数5/20日量比和已取得的资金类资讯",
                "资金字段只能作为观察线索，不能写成已证明动机",
                "缺少北向或全市场成交额时明确指出缺口",
            ],
        ),
        (
            "market_cause",
            "涨跌原因与驱动证据",
            ("为什么", "原因", "驱动", "利好", "利空", "怎么回事"),
            [
                "优先组合价格事实与多条市场资讯",
                "区分反复出现的解释、单一线索和反方证据",
                "不能把相关性包装成唯一因果",
            ],
        ),
    )
    for key, label, terms, requirements in focus_rules:
        if any(term in folded for term in terms):
            return {
                "key": key,
                "label": label,
                "answer_requirements": requirements,
            }
    if any(term in folded for term in counter_evidence_terms):
        return {
            "key": "market_risk",
            "label": "市场风险与重新判断条件",
            "answer_requirements": [
                "优先比较回撤、波动、趋势和关键均线位置",
                "说明风险已经发生的证据与仍未发生的情形",
                "不生成仓位或买卖指令",
            ],
        }
    return {
        "key": "market_overview",
        "label": "市场全景",
        "answer_requirements": [
            "先回答当前市场状态，再给指数、板块与风险证据",
            "优先回应用户明确提到的市场",
            "不预测下一交易日方向",
        ],
    }


def _needs_stock_market_context(message: str) -> bool:
    folded = re.sub(r"\s+", "", message).casefold()
    relative_industry_pattern = re.search(
        r"相对[^，。；,]{0,12}(?:行业|板块)",
        folded,
    )
    named_industry_index_pattern = re.search(
        r"相对[^，。；,]{0,12}(?:cs|中证)[^，。；,]{0,8}指数",
        folded,
    )
    return bool(relative_industry_pattern or named_industry_index_pattern) or any(
        term in folded
        for term in (
            "为什么",
            "原因",
            "驱动",
            "怎么回事",
            "上涨",
            "下跌",
            "大涨",
            "大跌",
            "收涨",
            "收跌",
            "市场拖累",
            "大盘拖累",
            "板块拖累",
            "行业拖累",
            "跟涨",
            "跟跌",
            "逆势",
            "相对行业",
            "相对板块",
            "行业增强",
            "行业走弱",
            "跑赢行业",
            "跑输行业",
            "超额收益",
            "行业指数",
            "所属行业",
            "更强",
            "更弱",
        )
    )


def _market_date(value: Any, timezone_name: str = "Asia/Shanghai") -> str | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=ZoneInfo(timezone_name))
        return parsed.astimezone(ZoneInfo(timezone_name)).date().isoformat()
    except (TypeError, ValueError):
        match = re.search(r"20\d{2}-\d{2}-\d{2}", str(value))
        return match.group(0) if match else None


def _question_price_direction(message: str) -> int:
    folded = re.sub(r"\s+", "", message).casefold()
    explicit_down = any(
        term in folded
        for term in (
            "为什么跌",
            "为何跌",
            "下跌原因",
            "大跌原因",
            "跌了怎么回事",
            "下跌怎么回事",
        )
    )
    explicit_up = any(
        term in folded
        for term in (
            "为什么涨",
            "为何涨",
            "上涨原因",
            "大涨原因",
            "涨了怎么回事",
            "上涨怎么回事",
        )
    )
    if explicit_down and not explicit_up:
        return -1
    if explicit_up and not explicit_down:
        return 1
    down = any(
        term in folded
        for term in ("下跌", "大跌", "收跌", "跌了", "走弱", "为什么跌", "为何跌")
    )
    up = any(
        term in folded
        for term in ("上涨", "大涨", "收涨", "涨了", "走强", "为什么涨", "为何涨")
    )
    if down and not up:
        return -1
    if up and not down:
        return 1
    return 0


def _question_market_date(
    message: str, reference_market_date: str | None
) -> str | None:
    iso_match = re.search(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})日?", message)
    month_day_match = re.search(r"(?<!\d)(\d{1,2})月(\d{1,2})日", message)
    year = None
    month = None
    day = None
    if iso_match:
        year, month, day = (int(value) for value in iso_match.groups())
    elif month_day_match:
        month, day = (int(value) for value in month_day_match.groups())
        reference_year = re.match(r"(20\d{2})", str(reference_market_date or ""))
        year = (
            int(reference_year.group(1))
            if reference_year
            else datetime.now(ZoneInfo("Asia/Shanghai")).year
        )
    if year is None or month is None or day is None:
        return None
    try:
        return datetime(year, month, day).date().isoformat()
    except ValueError:
        return None


def _is_market_ticker_reference(candidate: str, message: str) -> bool:
    folded = re.sub(r"\s+", "", message).casefold()
    ticker = candidate.upper()
    return (
        (ticker == "A" and "a股" in folded)
        or (ticker == "S" and "s&p" in folded)
        or (ticker in {"KOSPI", "VIX", "DAX"} and ticker.casefold() in folded)
    )


def _conversation_title(message: str) -> str:
    normalized = re.sub(r"\s+", " ", message).strip()
    if not normalized:
        return "新的研究对话"
    return normalized[:28] + ("…" if len(normalized) > 28 else "")


def _symbol_from_history(history: list[dict[str, Any]]) -> str | None:
    for item in reversed(history):
        metadata = item.get("metadata") or {}
        symbol = metadata.get("symbol")
        if symbol:
            try:
                return normalize_symbol(str(symbol))
            except ValueError:
                continue
    return None


def _symbols_from_history(history: list[dict[str, Any]]) -> list[str]:
    for item in reversed(history):
        metadata = item.get("metadata") or {}
        targets = metadata.get("research_targets") or []
        output: list[str] = []
        for target in targets:
            raw = target.get("symbol") if isinstance(target, dict) else target
            if not raw:
                continue
            try:
                canonical = normalize_symbol(str(raw))
            except ValueError:
                continue
            if canonical not in output:
                output.append(canonical)
        if len(output) >= 2:
            return output
    symbol = _symbol_from_history(history)
    return [symbol] if symbol else []


def _intent_from_history(history: list[dict[str, Any]]) -> str | None:
    for item in reversed(history):
        if item.get("role") == "assistant" and item.get("intent"):
            intent = str(item["intent"])
            if intent in {"general_research", "clarification"}:
                continue
            return intent
    return None


def _stock_screen_profile_from_history(
    history: list[dict[str, Any]],
) -> str | None:
    for item in reversed(history):
        if item.get("role") != "assistant" or item.get("intent") != "stock_screen":
            continue
        profile = (item.get("metadata") or {}).get("stock_screen_profile")
        if profile:
            return str(profile)
    return None


def _market_key_from_history(history: list[dict[str, Any]]) -> str | None:
    for item in reversed(history):
        metadata = item.get("metadata") or {}
        market_key = metadata.get("market_key")
        if market_key:
            return str(market_key)
        content = str(item.get("content") or "")
        if _is_market_query(content):
            return MarketNewsService.infer_market(content)
    return None


def _is_contextual_followup(message: str) -> bool:
    folded = re.sub(r"\s+", "", message).casefold()
    if not folded:
        return False
    strong_context_terms = (
        "同一个",
        "同一件",
        "这一次",
        "这次",
        "再次",
        "上述",
        "刚才",
        "前面",
        "上一题",
        "上一问",
        "前一题",
        "前一问",
        "重新回答",
        "重新答",
        "重答",
        "刚刚的回答",
        "你上段",
        "上一段",
        "上个回答",
        "刚才那段",
        "前一个回答",
        "接着",
        "继续",
    )
    if any(term in folded for term in strong_context_terms):
        return True
    if len(folded) > 80:
        return False
    context_terms = (
        "那",
        "那么",
        "它",
        "这个",
        "这些",
        "接下来",
        "主要风险",
        "最大风险",
        "风险是什么",
        "怎么看",
        "为什么",
        "更像",
        "反弹",
        "反转",
        "企稳",
        "趋势",
        "量能",
        "成交",
        "持续性",
        "能持续",
        "普涨",
        "结构性",
        "领涨",
        "领跌",
        "驱动",
        "催化",
        "反方",
        "反证",
        "相反证据",
        "失效条件",
        "重新判断",
        "什么情况会推翻",
        "不成立",
        "推翻",
        "证据缺口",
        "还缺什么证据",
        "需要补什么证据",
        "还有呢",
        "再比较",
        "继续比较",
        "重点比较",
        "变化",
        "进展",
        "更新",
        "现在",
        "当前",
        "最新",
        "报价",
        "日线",
        "纠正前提",
        "后来",
        "结果",
        "准不准",
    )
    return any(term in folded for term in context_terms)


def _prefers_stock_context_followup(message: str) -> bool:
    """Keep the company when a follow-up explicitly compares it with a market."""

    folded = re.sub(r"\s+", "", message).casefold()
    return any(
        term in folded
        for term in (
            "它相对",
            "它比",
            "它所在",
            "该股",
            "这只股票",
            "这家公司",
            "该公司",
            "公司相对",
            "相对所属行业",
            "相对行业",
            "相对板块",
        )
    )


def _is_research_tracking_query(message: str) -> bool:
    folded = re.sub(r"\s+", "", message).casefold()
    tracking_terms = (
        "最近有什么变化",
        "最近有何变化",
        "发生了什么变化",
        "研究进展",
        "跟踪变化",
        "跟踪更新",
        "跟踪动态",
        "新增证据",
        "证据变化",
        "原假设变了吗",
    )
    return any(term in folded for term in tracking_terms)


def _is_deep_stock_coverage_query(message: str) -> bool:
    folded = re.sub(r"\s+", "", message).casefold()
    coverage_terms = (
        "六维证据",
        "证据六维",
        "证据覆盖",
        "覆盖状态",
        "覆盖情况",
        "覆盖缺口",
    )
    return any(term in folded for term in coverage_terms)


def _is_earnings_quality_query(message: str) -> bool:
    folded = re.sub(r"\s+", "", message).casefold()
    terms = (
        "财报质量",
        "盈利质量",
        "业绩质量",
        "利润含金量",
        "财报怎么看",
        "财务报表怎么看",
        "利润为什么下降",
        "为什么利润下降",
        "净利润为什么下降",
        "营收增长为什么利润下降",
        "现金流质量",
        "现金流怎么样",
        "经营现金流",
        "利润兑现",
    )
    return any(term in folded for term in terms)


def _is_financial_driver_query(message: str) -> bool:
    folded = re.sub(r"\s+", "", message).casefold()
    terms = (
        "利润为什么下降",
        "为什么利润下降",
        "净利润为什么下降",
        "营收增长为什么利润下降",
        "利润下降原因",
        "利润增长原因",
        "利润驱动",
        "利润拆解",
        "三表拆解",
        "毛利率为什么下降",
        "毛利率下降原因",
        "费用率变化",
        "财务费用为什么",
        "财务费用上升原因",
        "汇兑损失",
        "其他收益为什么",
        "投资收益为什么",
        "减值为什么",
        "公司怎么解释利润",
        "公司如何解释利润",
        "财报原文怎么解释",
        "报告里怎么解释",
        "销售费用变化",
        "管理费用变化",
        "研发费用变化",
        "应收账款变化",
        "应收为什么增长",
        "存货为什么增长",
        "存货占用",
        "现金流为什么变差",
        "现金流为什么下降",
        "现金流为什么转负",
        "为什么现金流转负",
        "现金流转负原因",
        "销售收现",
        "营运资金",
    )
    return any(term in folded for term in terms)


def _is_business_structure_query(message: str) -> bool:
    folded = re.sub(r"\s+", "", message).casefold()
    terms = (
        "主营构成",
        "业务结构",
        "收入结构",
        "产品结构",
        "靠什么赚钱",
        "靠什么业务赚钱",
        "收入来自哪里",
        "收入来源",
        "哪个业务占比",
        "哪个产品占比",
        "哪个业务增长",
        "分部收入",
        "分部毛利",
        "业务毛利率",
        "产品毛利率",
        "地区收入",
        "国内收入",
        "海外收入",
        "毛利来源",
        "增长到底靠什么",
        "增长靠什么",
        "靠什么增长",
        "第二增长曲线",
        "第二曲线",
        "增长引擎",
    )
    return any(term in folded for term in terms)


def _is_peer_comparison_query(message: str) -> bool:
    folded = re.sub(r"\s+", "", message).casefold()
    direct_terms = (
        "固定同行",
        "同行比较",
        "同行对比",
        "同业比较",
        "同业对比",
        "公司对比",
        "横向比较",
        "同报告期经营差异",
        "分别比较",
        "同行估值",
        "同业估值",
        "估值同行",
        "相对同行",
        "相对同业",
    )
    if any(term in folded for term in direct_terms):
        return True
    comparison_terms = ("比较", "对比", "差异", "相对", "位置")
    peer_terms = (
        "同行",
        "同业",
        "竞品",
        "竞争对手",
        "烽火通信",
        "紫光股份",
        "锐捷网络",
        "新易盛",
        "天孚通信",
        "光迅科技",
        "亿纬锂能",
        "国轩高科",
        "欣旺达",
    )
    return any(term in folded for term in comparison_terms) and any(
        term in folded for term in peer_terms
    )


def _is_shareholder_query(message: str) -> bool:
    folded = re.sub(r"\s+", "", message).casefold()
    terms = (
        "股东户数",
        "股东人数",
        "股东结构",
        "十大股东",
        "前十大股东",
        "主要股东",
        "筹码集中",
        "持股集中",
        "持股分散",
        "机构持仓",
        "机构股东",
        "股东变化",
        "股东怎么变",
        "股东是谁",
    )
    return any(term in folded for term in terms)


def _is_analyst_expectations_query(message: str) -> bool:
    folded = re.sub(r"\s+", "", message).casefold()
    terms = (
        "一致预期",
        "分析师预期",
        "券商预期",
        "盈利预测",
        "eps预测",
        "分析师上修",
        "分析师下修",
        "预期上修",
        "预期下修",
        "最近上修",
        "最近下修",
        "券商怎么看",
        "机构怎么看",
        "最新研报",
        "个股研报",
        "研报有哪些",
        "评级分布",
        "覆盖机构",
    )
    return any(term in folded for term in terms)


def _is_research_outcome_query(message: str) -> bool:
    folded = re.sub(r"\s+", "", message).casefold()
    outcome_terms = (
        "之前的研究后来怎么样",
        "之前研究后来怎么样",
        "上次分析后来怎么样",
        "上次研究后来怎么样",
        "研究结果复盘",
        "研究结果怎么样",
        "回看之前的分析",
        "复盘之前的研究",
        "之前判断准不准",
        "之前分析准不准",
        "过去的研究结果",
    )
    return any(term in folded for term in outcome_terms)


def _is_research_priority_query(message: str) -> bool:
    folded = re.sub(r"\s+", "", message).casefold()
    priority_terms = (
        "今天先看什么",
        "今日先看什么",
        "先研究哪只",
        "先看哪只",
        "研究优先级",
        "今日研究重点",
        "今天研究重点",
        "自选股风险排序",
        "自选股复核顺序",
        "自选股先看什么",
    )
    return any(term in folded for term in priority_terms)


def _is_watchlist_daily_query(message: str) -> bool:
    folded = re.sub(r"\s+", "", message).casefold()
    daily_terms = (
        "自选股每日研究摘要",
        "自选股今日研究摘要",
        "关注组合每日研究摘要",
    )
    return any(term in folded for term in daily_terms)


def _is_research_action_query(message: str) -> bool:
    folded = re.sub(r"\s+", "", message).casefold()
    action_terms = (
        "研究行动",
        "行动清单",
        "观察条件",
        "研究条件",
        "待补证",
        "需要补什么证据",
        "哪些条件触发了",
        "什么需要复核",
        "现在要复核什么",
        "研究任务",
    )
    return any(term in folded for term in action_terms)


def _is_event_timeline_query(message: str) -> bool:
    folded = re.sub(r"\s+", "", message).casefold()
    event_terms = (
        "事件脉络",
        "重要事件",
        "最新事件",
        "最近发生了什么",
        "最近有什么大事",
        "有什么催化",
        "催化事件",
        "催化和风险",
        "风险事件",
        "公告风险",
        "重要公告",
        "最新公告讲了什么",
        "有什么需要阅读原文",
    )
    return any(term in folded for term in event_terms)


def _needs_research_object_clarification(
    message: str, history: list[dict[str, Any]]
) -> bool:
    if history:
        return False
    folded = re.sub(r"\s+", "", message).casefold()
    ambiguous_targets = (
        "这只股票",
        "这个股票",
        "这只股",
        "这家公司",
        "这个公司",
        "这个标的",
    )
    return any(term in folded for term in ambiguous_targets)


def _extract_thesis(message: str) -> str | None:
    for marker in ("关注理由是", "关注理由：", "关注理由:", "因为"):
        if marker in message:
            thesis = message.split(marker, 1)[1].strip(" 。")
            return thesis or None
    return None
