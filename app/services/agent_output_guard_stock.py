from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import json
import re
from typing import Any

from app.services.agent_output_guard_common import (
    _LONG_DECIMAL_RE,
    _NUMBER_RE,
    _number_value,
)

_STOCK_FAILURE_THRESHOLD_LABEL = "个股失效条件只能使用证据包已有阈值和观察周期"
_STOCK_OBSERVATION_WINDOW_LABEL = "个股观察周期只能使用研究计划已有交易日窗口"
_LI_ZONG_RULE_BOTTLENECK_LABEL = (
    "缺少逐规则汇总统计时不能推断李总策略的主要瓶颈或规则稀缺度"
)
_LI_ZONG_COVERAGE_CONFLATION_LABEL = "李总策略名单预筛覆盖不能冒充深度规则完成率"
_STOCK_SCREEN_SCOPE_OVERCLAIM_LABEL = "通用选股覆盖不足时不能外推为全市场结论"
_STOCK_SCREEN_CANDIDATE_COUNT_LABEL = "通用选股候选数量必须与确定性结果一致"
_STOCK_DISCLOSURE_DATE_LABEL = "缺少披露日历证据时不能预测下一份报告日期"
_STOCK_REPORT_DATE_CONFLICT_LABEL = "财报公告日期必须与结构化报告一致"
_STOCK_DRAWDOWN_WINDOW_LABEL = "最大回撤观察窗口必须与确定性指标一致"
_STOCK_SCENARIO_DIRECTION_LABEL = "个股情景触发与失效方向必须与确定性条件一致"
_STOCK_CURRENT_QUOTE_DIRECTION_LABEL = "今日涨跌方向必须与更新的当前报价一致"
_STOCK_CURRENT_QUOTE_PRICE_LABEL = "今日或当前价格必须优先使用更新的报价快照"
_STOCK_CURRENT_QUOTE_CLOSE_LABEL = "更新的报价快照不能写成当日收盘"
_STOCK_CURRENT_QUOTE_SESSION_LABEL = "收盘后报价不能继续描述为盘中或尚未收盘"
_STOCK_CURRENT_QUOTE_MA20_LABEL = "当前报价与MA20关系必须与确定性数据一致"
_STOCK_CURRENT_LIMIT_STATUS_LABEL = "当前涨跌停状态必须与最新报价涨跌幅一致"
_STOCK_CURRENT_QUOTE_REQUIRED_LABEL = "用户询问今日时必须给出更新报价并区分历史日线"
_STOCK_CROSS_DATE_MARKET_LABEL = "跨日期市场广度不能用于排除目标日的系统性拖累"
_STOCK_INDUSTRY_BREADTH_LABEL = "缺少行业成分涨跌家数时不能确认行业普涨普跌或参与面"
_STOCK_60D_RETURN_BINDING_LABEL = "60日累计收益不能误用最大回撤数值"
_STOCK_DEBT_RATIO_SCALE_LABEL = "资产负债率变化不能直接改写为负债绝对规模变化"
_STOCK_CASHFLOW_CAUSE_LABEL = "缺少公司原文时不能把经营现金流变化归因于收入收缩"
_STOCK_STATIC_FINANCIAL_CAUSAL_LABEL = "静态毛利桥不能改写为已确认经营原因"
_STOCK_INDUSTRY_CAUSAL_LABEL = "行业成分广度只能描述同步性不能证明个股涨跌因果"
_STOCK_CONTRIBUTION_REQUIRED_LABEL = (
    "用户明确询问成分贡献时必须给出标的估算贡献和口径边界"
)
_STOCK_INDUSTRY_COUNTS_REQUIRED_LABEL = (
    "用户明确询问行业成分涨跌家数时必须给出上涨下跌平盘家数"
)
_STOCK_COMPONENT_SOURCE_BOUNDARY_LABEL = (
    "行业成分使用未复权补充行情时必须说明证券来源和除权边界"
)
_STOCK_MARKET_ABSORPTION_LABEL = (
    "缺少事件研究证据时不能声称基本面已被市场消化或情绪驱动超跌"
)
_STOCK_EVENT_SENTIMENT_LABEL = "公告或媒体线索不能在缺少事件研究时评为正面负面或催化"
_STOCK_UNSUPPORTED_CAUSAL_HYPOTHESIS_LABEL = (
    "缺少事件或业务证据时不能用技术指标行业轮动或业务结构解释个股涨跌"
)
_STOCK_REASSESSMENT_HEADING = (
    r"(?:失效条件|不成立条件|什么时候需要重新判断|需要重新判断的情况)"
)
_MARKET_CAUSE_FACT_REQUIRED_LABEL = "大盘涨跌原因回答必须保留至少一项同日指数价格事实"
_STOCK_FAILURE_THRESHOLD_LANGUAGE_RE = re.compile(
    r"(?:低于|高于|不低于|不高于|以下|以上|超过|跌破|突破|"
    r"降至|升至|放缓至|扩大至|收缩至|达到|维持|连续|持续)"
)
_STOCK_INVENTED_REPORT_WINDOW_RE = re.compile(
    r"连续\s*[一二两三四五六七八九十]+\s*个?(?:报告期|季度|财季)"
)
_STOCK_INVENTED_SINGLE_DIGIT_RE = re.compile(
    r"(?:增速|增长|毛利率|净利率|现金流)[^。；\n]{0,40}(?:放缓|下降|收缩)?"
    r"[^。；\n]{0,16}(?:至|到)?\s*个位数"
)
_STOCK_OBSERVATION_WINDOW_RE = re.compile(
    r"(?:(?:未来|后续|接下来)\s*)?"
    r"(\d+)\s*(?:[-—–~～至到]\s*(\d+)\s*)?个?交易日(?:内|后|观察|复核)"
)
_STOCK_T_PLUS_WINDOW_RE = re.compile(
    r"(?<![A-Za-z0-9_])T\s*\+\s*(\d+)(?!\d)", re.IGNORECASE
)
_LI_ZONG_RULE_BOTTLENECK_RE = re.compile(
    r"(?:尤其|主要卡在|主要来自|核心瓶颈|最大瓶颈|最严格|最难满足|"
    r"极少|很少|稀缺|约束最强)"
)
_LI_ZONG_RULE_TERM_RE = re.compile(
    r"(?:ROE|市值|股东|涨停|连板|阴线|复权新高|成交量|量价|股性|基本面)"
)
_STOCK_DISCLOSURE_DATE_RE = re.compile(
    r"(?:中报|半年报|年报|季报|定期报告|下一份报告|下一份财报)"
    r"[^。；\n]{0,60}(?:预计|大概率|可能于|约在)[^。；\n]{0,20}"
    r"(?:\d{1,2}\s*月|上半年|下半年|一季度|二季度|三季度|四季度)"
)
_STOCK_REPORT_NOTICE_CLAIM_RE = re.compile(
    r"(?P<report_year>20\d{2})\s*(?:年)?(?:一季报|中报|半年报|三季报|年报)"
    r"[^。；\n]{0,70}(?:公告日|披露日|公告于|披露于)\s*"
    r"(?P<notice_year>20\d{2})(?:[-/.年](?P<month>\d{1,2})"
    r"(?:[-/.月](?P<day>\d{1,2}))?)?"
)
_STOCK_DRAWDOWN_WINDOW_RE = re.compile(r"(?P<days>\d+)\s*日(?:内)?最大回撤")
_STOCK_SCENARIO_DIRECTION_CONFLICT_RE = re.compile(
    r"(?:(?:向下|下行风险)[^。；\n]{0,20}(?:失效|需要重新判断)[^。；\n]{0,140}"
    r"(?:跌破|继续恶化)|(?:区间|震荡)[^。；\n]{0,20}(?:失效|需要重新判断)"
    r"[^。；\n]{0,140}(?:运行在|仍在|处于)[^。；\n]{0,50}(?:之间|区间))"
)


def _number_unit(text: str, match: re.Match[str]) -> str:
    token = match.group(0)
    suffix = text[match.end() : match.end() + 12]
    if token.endswith("%"):
        return "percent"
    if re.match(r"\s*个?百分点", suffix):
        return "percentage_point"
    if re.match(r"\s*(?:个)?交易日", suffix):
        return "trading_day"
    if re.match(r"\s*(?:个)?(?:报告期|季度|财季)", suffix):
        return "report_period"
    return "plain"


def _sanctioned_stock_failure_text(evidence: dict[str, Any]) -> str:
    outlook = evidence.get("conditional_outlook") or {}
    board = evidence.get("analysis_board") or {}
    sanctioned = {
        "scenarios": outlook.get("scenarios") or [],
        "invalidation": outlook.get("invalidation"),
        "horizon": outlook.get("horizon"),
        "price_levels": evidence.get("price_levels") or {},
        "tracking_plan": board.get("tracking_plan") or [],
        "user_thesis": evidence.get("user_thesis"),
        "user_question": evidence.get("user_question"),
    }
    return json.dumps(sanctioned, ensure_ascii=False, default=str)


def _stock_failure_line_has_unsupported_threshold(
    line: str, evidence: dict[str, Any]
) -> bool:
    threshold_text = re.sub(
        r"(?:以上|上述)(?:失效条件|不成立条件|需要重新判断的情况|情况)",
        "",
        line,
    )
    if not _STOCK_FAILURE_THRESHOLD_LANGUAGE_RE.search(threshold_text):
        return False
    sanctioned_text = _sanctioned_stock_failure_text(evidence)
    if _STOCK_INVENTED_REPORT_WINDOW_RE.search(
        line
    ) and not _STOCK_INVENTED_REPORT_WINDOW_RE.search(sanctioned_text):
        return True
    if _STOCK_INVENTED_SINGLE_DIGIT_RE.search(line) and "个位数" not in sanctioned_text:
        return True
    sanctioned: list[tuple[float, str]] = []
    for match in _NUMBER_RE.finditer(sanctioned_text):
        value = _number_value(match.group(0))
        if value is not None:
            sanctioned.append((value, _number_unit(sanctioned_text, match)))
    for match in _NUMBER_RE.finditer(line):
        token = match.group(0)
        suffix = line[match.end() : match.end() + 2]
        if (
            not token.endswith("%")
            and not line[: match.start()].strip()
            and suffix[:1] in {".", "、", ")", "）"}
        ):
            continue
        value = _number_value(token)
        if value is None:
            continue
        unit = _number_unit(line, match)
        if not any(
            unit == allowed_unit
            and abs(value - allowed) <= max(0.02, abs(allowed) * 0.005)
            for allowed, allowed_unit in sanctioned
        ):
            return True
    return False


def _has_unsupported_stock_failure_threshold(
    answer: str, evidence: dict[str, Any]
) -> bool:
    in_failure_section = False
    for raw_line in answer.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        normalized_line = re.sub(r"^[-+*]\s+", "", line)
        section_match = re.match(
            r"^(?:#{1,6}\s*)?(?:\*\*|__)?"
            + _STOCK_REASSESSMENT_HEADING
            + r"(?:\*\*|__)?"
            r"\s*(?:[：:]\s*(?P<remainder>.*))?$",
            normalized_line,
        )
        if section_match:
            in_failure_section = True
            remainder = str(section_match.group("remainder") or "").strip()
            if remainder and _stock_failure_line_has_unsupported_threshold(
                remainder, evidence
            ):
                return True
            continue
        if in_failure_section and (
            re.match(r"^#{1,6}\s+", line)
            or re.match(r"^(?:\*\*|__)[^*_]+(?:\*\*|__)\s*$", line)
        ):
            break
        if in_failure_section and _stock_failure_line_has_unsupported_threshold(
            line, evidence
        ):
            return True
        inline_condition = re.search(
            _STOCK_REASSESSMENT_HEADING
            + r"\s*(?:是|为|[：:])\s*(?P<condition>.+)",
            line,
        )
        if inline_condition and _stock_failure_line_has_unsupported_threshold(
            inline_condition.group("condition"), evidence
        ):
            return True
        for clause in re.split(r"[。；;]", line):
            if re.search(
                r"(?:假设|判断|框架|逻辑)[^。；\n]{0,24}(?:失效|不成立)",
                clause,
            ) and _stock_failure_line_has_unsupported_threshold(clause, evidence):
                return True
    return False


def _has_unsupported_stock_observation_window(
    answer: str, evidence: dict[str, Any]
) -> bool:
    allowed_text = _sanctioned_stock_failure_text(evidence)
    allowed: set[int] = set()
    for match in _STOCK_OBSERVATION_WINDOW_RE.finditer(allowed_text):
        allowed.add(int(match.group(1)))
        if match.group(2):
            allowed.add(int(match.group(2)))
    allowed.update(
        int(match.group(1))
        for match in re.finditer(r'"horizon_sessions"\s*:\s*(\d+)', allowed_text)
    )
    allowed.update(
        int(match.group(1)) for match in _STOCK_T_PLUS_WINDOW_RE.finditer(allowed_text)
    )
    for match in _STOCK_OBSERVATION_WINDOW_RE.finditer(answer):
        claimed = {int(match.group(1))}
        if match.group(2):
            claimed.add(int(match.group(2)))
        if not claimed.issubset(allowed):
            return True
    for match in _STOCK_T_PLUS_WINDOW_RE.finditer(answer):
        if int(match.group(1)) not in allowed:
            return True
    return False


def _has_li_zong_rule_bottleneck_overclaim(
    answer: str, evidence: dict[str, Any]
) -> bool:
    if (
        ((evidence.get("profile") or {}).get("key") != "li_zong")
        or evidence.get("selection_mode") != "candidate_pool"
        or (evidence.get("data_meta") or {}).get("rule_aggregate_counts")
    ):
        return False
    return any(
        _LI_ZONG_RULE_BOTTLENECK_RE.search(clause)
        and _LI_ZONG_RULE_TERM_RE.search(clause)
        for clause in re.split(r"[。；\n]", answer)
    )


def _has_li_zong_coverage_conflation(answer: str, evidence: dict[str, Any]) -> bool:
    if ((evidence.get("profile") or {}).get("key") != "li_zong") or evidence.get(
        "selection_mode"
    ) != "candidate_pool":
        return False
    has_legacy_coverage = bool(
        re.search(
            r"已评估\s*[\d,]+\s*/\s*[\d,]+\s*只[^。；\n]{0,80}待处理",
            answer,
        )
    )
    return has_legacy_coverage and not any(
        term in answer for term in ("深度处理", "深度核验", "深度规则完成率")
    )


def _has_stock_screen_scope_overclaim(answer: str, evidence: dict[str, Any]) -> bool:
    if (
        evidence.get("type") != "stock_screen"
        or (evidence.get("profile") or {}).get("key") == "li_zong"
    ):
        return False
    snapshot = ((evidence.get("data_contract") or {}).get("coverage") or {}).get(
        "market_snapshot"
    ) or {}
    representation = (evidence.get("data_contract") or {}).get(
        "representation"
    ) or {}
    expected = int(snapshot.get("expected") or 0)
    available = int(snapshot.get("available") or 0)
    represents_full_market = representation.get("represents_full_market")
    if represents_full_market is True:
        return False
    if represents_full_market is None and (not expected or available >= expected):
        return False
    if any(
        term in answer
        for term in (
            "已覆盖范围",
            "本轮覆盖范围",
            "股票池覆盖",
            "仍有未覆盖",
            "不代表全市场",
            "不能外推全市场",
            "财务核验",
            "部分覆盖",
        )
    ):
        return False
    return bool(
        re.search(
            r"(?:A股全市场|全市场|全部A股|所有A股|全体A股)"
            r"[^。；\n]{0,100}(?:候选|筛选|股票|标的|没有|无|得到|共)",
            answer,
        )
    )


def _has_stock_screen_candidate_count_conflict(
    answer: str, evidence: dict[str, Any]
) -> bool:
    if (
        evidence.get("type") != "stock_screen"
        or (evidence.get("profile") or {}).get("key") == "li_zong"
    ):
        return False
    expected = len(evidence.get("items") or [])
    pattern = re.compile(
        r"(?:筛选出|筛出|得到|共有|共计|共命中|候选数量(?:为|是)?|"
        r"本轮(?:共(?:命中)?|共有|得到|筛选出))\s*"
        r"([\d,]{1,7})\s*只(?:研究)?候选"
    )
    for match in pattern.finditer(answer):
        claimed = int(match.group(1).replace(",", ""))
        if claimed != expected:
            return True
    return False


def _has_unsupported_stock_disclosure_date(
    answer: str, evidence: dict[str, Any]
) -> bool:
    sanctioned_text = _sanctioned_stock_failure_text(evidence)
    return any(
        match.group(0) not in sanctioned_text
        for match in _STOCK_DISCLOSURE_DATE_RE.finditer(answer)
    )


def _has_stock_report_notice_date_conflict(
    answer: str, evidence: dict[str, Any]
) -> bool:
    latest = ((evidence.get("fundamentals") or {}).get("summary") or {}).get(
        "latest_report"
    ) or {}
    report_date = str(latest.get("report_date") or "")
    notice_date = str(latest.get("notice_date") or "")
    if not report_date or not notice_date:
        return False
    for match in _STOCK_REPORT_NOTICE_CLAIM_RE.finditer(answer):
        if match.group("report_year") != report_date[:4]:
            return True
        claimed = match.group("notice_year")
        if match.group("month"):
            claimed += f"-{int(match.group('month')):02d}"
        if match.group("day"):
            claimed += f"-{int(match.group('day')):02d}"
        if not notice_date.startswith(claimed):
            return True
    report_type = str(latest.get("report_type") or "")
    report_terms = {report_type, "Q1"} if report_type == "一季报" else {report_type}
    for clause in re.split(r"[。；\n]", answer):
        if not any(term and term in clause for term in report_terms):
            continue
        notice_positions = [
            match.start() for match in re.finditer(r"(?:公告|披露)", clause)
        ]
        if not notice_positions:
            continue
        for date_match in re.finditer(
            r"(?:(?P<year>20\d{2})[-/.年])?"
            r"(?P<month>\d{1,2})(?:[-/.月])(?P<day>\d{1,2})日?",
            clause,
        ):
            month = int(date_match.group("month"))
            day = int(date_match.group("day"))
            # A nearby percentage such as ``46.58%`` can look like ``MM.DD``
            # to the permissive date matcher. Only calendar-valid month/day
            # pairs may participate in the notice-date consistency check.
            if not (1 <= month <= 12 and 1 <= day <= 31):
                continue
            date_prefix = clause[max(0, date_match.start() - 12) : date_match.start()]
            if re.search(r"(?:截至|报告期截至|期末为|止于)\s*$", date_prefix):
                # “2026年中报（截至6月30日）披露”中的6月30日是报告期，
                # 不是公告日；不能因为它靠近“披露”二字就判为公告日期冲突。
                continue
            if not any(
                abs(date_match.start() - position) <= 16
                or abs(date_match.end() - position) <= 16
                for position in notice_positions
            ):
                continue
            claimed_year = date_match.group("year") or notice_date[:4]
            claimed = f"{claimed_year}-{month:02d}-{day:02d}"
            if claimed != notice_date:
                return True
    return False


def _has_stock_drawdown_window_conflict(answer: str, evidence: dict[str, Any]) -> bool:
    metrics = evidence.get("metrics") or {}
    expected = 60 if metrics.get("max_drawdown_60d_pct") is not None else None
    if expected is None:
        return False
    return any(
        int(match.group("days")) != expected
        for match in _STOCK_DRAWDOWN_WINDOW_RE.finditer(answer)
    )


def _has_stock_scenario_direction_conflict(answer: str) -> bool:
    return bool(_STOCK_SCENARIO_DIRECTION_CONFLICT_RE.search(answer))


def _stock_current_quote_is_newer(evidence: dict[str, Any]) -> bool:
    quote_time = (evidence.get("current_quote") or {}).get("market_timestamp")
    history_time = (evidence.get("provenance") or {}).get("market_timestamp")
    if not quote_time or not history_time:
        return False
    try:
        quote_at = datetime.fromisoformat(str(quote_time).replace("Z", "+00:00"))
        history_at = datetime.fromisoformat(str(history_time).replace("Z", "+00:00"))
        if quote_at.tzinfo is None:
            quote_at = quote_at.replace(tzinfo=timezone.utc)
        if history_at.tzinfo is None:
            history_at = history_at.replace(tzinfo=timezone.utc)
        return quote_at > history_at
    except (TypeError, ValueError):
        return str(quote_time) > str(history_time)


def _stock_current_quote_conflicts(
    answer: str, evidence: dict[str, Any]
) -> tuple[bool, bool]:
    analysis_target = (evidence.get("stock_market_context") or {}).get(
        "analysis_target"
    ) or {}
    if analysis_target.get("basis") == "explicit_question_date":
        return False, False
    quote = evidence.get("current_quote") or {}
    if not _stock_current_quote_is_newer(evidence):
        return False, False
    quote_change = quote.get("pct_change")
    quote_price = quote.get("price")
    if not isinstance(quote_change, (int, float)) and not isinstance(
        quote_price, (int, float)
    ):
        return False, False
    direction_conflict = False
    price_conflict = False
    current_terms = ("今天", "今日", "当前", "现在", "盘中", "最新")
    previous_terms = (
        "上一交易日",
        "前一交易日",
        "此前交易日",
        "上一根日线",
        "完整日线",
        "历史日线",
        "前日",
    )
    for raw_line in answer.splitlines():
        line = raw_line.strip()
        if not line or not any(term in line for term in current_terms):
            continue
        explicit_current_quote = re.search(
            r"(?:当前|现在|最新)(?:报价|价格|股价|报)"
            r"[^0-9]{0,8}[0-9]+(?:\.[0-9]+)?",
            line,
        )
        if any(term in line for term in previous_terms) and not explicit_current_quote:
            continue
        negative_down = re.search(
            r"(?:不是|并非|并未|没有|并没有|未出现)[^。；\n]{0,10}"
            r"(?:下跌|收跌|大跌|走弱|下挫)",
            line,
        ) or re.search(r"(?:下跌|收跌|大跌)[^。；\n]{0,8}(?:不成立|有误|错误)", line)
        negative_up = re.search(
            r"(?:不是|并非|并未|没有|并没有|未出现)[^。；\n]{0,10}"
            r"(?:上涨|收涨|大涨|走强|反弹)",
            line,
        ) or re.search(r"(?:上涨|收涨|大涨)[^。；\n]{0,8}(?:不成立|有误|错误)", line)
        claims_down = bool(re.search(r"(?:下跌|收跌|大跌|走弱|下挫)", line))
        claims_up = bool(re.search(r"(?:上涨|收涨|大涨|走强|反弹)", line))
        if isinstance(quote_change, (int, float)):
            if quote_change > 0 and claims_down and not negative_down and not claims_up:
                direction_conflict = True
            if quote_change < 0 and claims_up and not negative_up and not claims_down:
                direction_conflict = True
        if isinstance(quote_price, (int, float)):
            price_matches = re.finditer(
                r"(?:收盘价|股价|价格|报价|现报|收于)"
                r"\s*(?:为|是|约|在|至|达到|:|：)?\s*"
                r"([0-9]+(?:\.[0-9]+)?)",
                line,
            )
            for price_match in price_matches:
                trailing = line[price_match.end() : price_match.end() + 3]
                if re.match(r"\s*(?:%|％|年|月|日|时|分|:|：)", trailing):
                    # “近5日价格0.00%” is a return statement, not a claim that
                    # the current share price is 0.00.  A line-level scan used
                    # to treat it as a stale quote whenever the same paragraph
                    # also contained the words “最新报价”.
                    # Likewise, in “报价在7月30日13:42为5.87元”, the first
                    # number after “报价” is a timestamp component, not price.
                    continue
                nearby_prefix = line[
                    max(0, price_match.start() - 28) : price_match.start()
                ]
                if any(term in nearby_prefix for term in previous_terms):
                    continue
                claimed_price = float(price_match.group(1))
                tolerance = max(0.02, abs(float(quote_price)) * 0.002)
                if abs(claimed_price - float(quote_price)) > tolerance:
                    price_conflict = True
                    break
    return direction_conflict, price_conflict


def _stock_current_quote_close_conflict(answer: str, evidence: dict[str, Any]) -> bool:
    analysis_target = (evidence.get("stock_market_context") or {}).get(
        "analysis_target"
    ) or {}
    if analysis_target.get("basis") == "explicit_question_date":
        return False
    quote = evidence.get("current_quote") or {}
    quote_price = quote.get("price")
    if not isinstance(quote_price, (int, float)):
        return False
    if not _stock_current_quote_is_newer(evidence):
        return False

    previous_terms = (
        "上一交易日",
        "前一交易日",
        "此前交易日",
        "上一根日线",
        "完整日线",
        "历史日线",
        "前日",
        "前收盘",
        "上一收盘",
    )
    tolerance = max(0.02, abs(float(quote_price)) * 0.002)
    for clause in re.split(r"[。；\n]", answer):
        if not clause.strip() or not re.search(r"(?:收盘(?:价)?|收于)", clause):
            continue
        mentioned_quote = any(
            value is not None and abs(value - float(quote_price)) <= tolerance
            for match in _NUMBER_RE.finditer(clause)
            if (value := _number_value(match.group(0))) is not None
        )
        if (
            re.search(
                r"(?:A股|市场|交易时段|交易所|当日交易)"
                r"[^。；\n]{0,10}(?:已经|已|现已)?收盘",
                clause,
            )
            and not mentioned_quote
            and "收盘价" not in clause
        ):
            continue
        # These phrases explicitly preserve the intraday boundary.  Treating
        # every occurrence of “收盘” as a completed close used to turn natural
        # sentences such as “尚未收盘” into the broken phrase “尚未最新报价”.
        if re.search(
            r"(?:尚未|还未|还没|未|不是|并非|不能|不应|不可|没有|并没有)"
            r"[^。；\n]{0,8}(?:收盘(?:价)?|收于)",
            clause,
        ):
            continue
        if re.search(r"(?:收盘(?:价)?|收于)(?:前|后|时|之前|之后)", clause):
            continue
        if re.search(
            r"收盘[^。；\n]{0,10}(?:尚未|还未|未)"
            r"[^。；\n]{0,6}(?:形成|确认|完成|确定)",
            clause,
        ):
            continue
        current_close_claim = any(
            not any(term in match.group(0) for term in previous_terms)
            for match in re.finditer(
                r"(?:今天|今日|当前|现在|最新|盘中)[^。；\n]{0,18}"
                r"(?:收盘(?:价)?|收于)",
                clause,
            )
        )
        quote_close_claim = any(
            value is not None and abs(value - float(quote_price)) <= tolerance
            for match in re.finditer(
                r"(?:收盘(?:价)?(?:为|是|报|达到)?|收于)"
                r"[^0-9]{0,8}(?P<price>[0-9]+(?:\.[0-9]+)?)",
                clause,
            )
            if (value := _number_value(match.group("price"))) is not None
        )
        if (
            any(term in clause for term in previous_terms)
            and not current_close_claim
            and not quote_close_claim
        ):
            continue
        if current_close_claim or quote_close_claim:
            return True
    return False


def _normalize_current_quote_semantics(answer: str, evidence: dict[str, Any]) -> str:
    if not _stock_current_quote_close_conflict(answer, evidence):
        return answer

    normalized_clauses: list[str] = []
    parts = re.split(r"([。；\n])", answer)
    for index in range(0, len(parts), 2):
        clause = parts[index]
        separator = parts[index + 1] if index + 1 < len(parts) else ""
        if _stock_current_quote_close_conflict(clause, evidence):
            clause = re.sub(
                r"(?:今天|今日)\s*以\s*"
                r"(?P<price>[0-9]+(?:\.[0-9]+)?\s*(?:元|美元|港元)?)\s*收盘",
                r"最新报价为 \g<price>",
                clause,
            )
            clause = re.sub(
                r"截至(?:今天|今日)(?:A股)?收盘",
                "截至当前报价快照",
                clause,
            )
            clause = re.sub(
                r"(?:今天|今日|当前|现在|最新|盘中)\s*收盘(?:价)?",
                "最新报价",
                clause,
            )
            clause = re.sub(
                r"(?:今天|今日|当前|现在|最新|盘中)\s*收于",
                "当前报",
                clause,
            )
            if _stock_current_quote_close_conflict(clause, evidence):
                clause = re.sub(r"收盘(?:价)?", "最新报价", clause, count=1)
                clause = re.sub(r"收于", "当前报", clause, count=1)
        normalized_clauses.extend((clause, separator))
    return "".join(normalized_clauses)


def _normalize_stock_research_number_precision(answer: str) -> str:
    """Keep user-facing stock research numbers readable and reproducible."""

    def replace(match: re.Match[str]) -> str:
        raw = match.group("value")
        try:
            rounded = Decimal(raw).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        except InvalidOperation:
            return raw
        if rounded == 0:
            return "0"
        formatted = format(abs(rounded), "f").rstrip("0").rstrip(".")
        if rounded < 0:
            return f"-{formatted}"
        if raw.startswith("+"):
            return f"+{formatted}"
        return formatted

    return _LONG_DECIMAL_RE.sub(replace, answer)


def _stock_current_quote_session_conflict(
    answer: str, evidence: dict[str, Any]
) -> bool:
    quote = evidence.get("current_quote") or {}
    if quote.get("quote_basis") != "post_close_snapshot":
        return False
    return bool(
        re.search(
            r"(?:当前|现在|目前|最新报价|该报价|此报价)"
            r"[^。；\n]{0,12}(?:仍在盘中|还在盘中|处于盘中|属于盘中报价|是盘中报价|尚未收盘|还未收盘)",
            answer,
        )
        or re.search(r"(?:收盘前仍可能|仍在交易中|当日尚未收盘)", answer)
    )


def _normalize_current_quote_session_semantics(
    answer: str, evidence: dict[str, Any]
) -> str:
    if (evidence.get("current_quote") or {}).get(
        "quote_basis"
    ) != "post_close_snapshot":
        return answer
    normalized = re.sub(
        r"(?:当前|现在|目前)(?:仍|还)?(?:处于|在)?盘中(?:交易)?",
        "当前市场已收盘",
        answer,
    )
    normalized = re.sub(
        r"(?:最新报价|该报价|此报价)(?:属于|是|仍是)?盘中报价",
        "该报价是收盘后最新报价",
        normalized,
    )
    normalized = re.sub(
        r"(?:当前|现在|目前|当日)?(?:仍|还)?尚未收盘",
        "市场已经收盘",
        normalized,
    )
    normalized = re.sub(
        r"收盘前仍可能(?:打开|变化)",
        "当日交易已经结束",
        normalized,
    )
    return normalized


def _normalize_history_price_mislabeled_as_current_quote(
    answer: str, evidence: dict[str, Any]
) -> str:
    if not _stock_current_quote_is_newer(evidence):
        return answer
    quote = evidence.get("current_quote") or {}
    history_close = (evidence.get("metrics") or {}).get("latest_close")
    previous_close = quote.get("previous_close")
    quote_price = quote.get("price")
    if not isinstance(history_close, (int, float)) or not isinstance(
        quote_price, (int, float)
    ):
        return answer
    tolerance = max(0.02, abs(float(history_close)) * 0.002)
    pattern = re.compile(
        r"(?P<prefix>(?:最新|最近)(?:一根)?完整日线[^。；\n]{0,40}?[，,]\s*)"
        r"(?:当前|最新)报价(?P<price>[0-9]+(?:\.[0-9]+)?)(?P<unit>\s*(?:元|美元|港元)?)"
    )

    def replace(match: re.Match[str]) -> str:
        value = _number_value(match.group("price"))
        if value is None or abs(value - float(history_close)) > tolerance:
            return match.group(0)
        if abs(value - float(quote_price)) <= tolerance:
            return match.group(0)
        return (
            f"{match.group('prefix')}收盘价{match.group('price')}{match.group('unit')}"
        )

    normalized = pattern.sub(replace, answer)
    baseline_close = (
        previous_close if isinstance(previous_close, (int, float)) else history_close
    )
    if not isinstance(baseline_close, (int, float)):
        return normalized
    baseline_tolerance = max(0.02, abs(float(baseline_close)) * 0.002)
    previous_pattern = re.compile(
        r"(?P<prefix>较?(?:前一|上一)交易日)(?:最新)?报价"
        r"(?P<price>[0-9]+(?:\.[0-9]+)?)(?P<unit>\s*(?:元|美元|港元)?)"
    )

    def replace_previous(match: re.Match[str]) -> str:
        value = _number_value(match.group("price"))
        if value is None or abs(value - float(baseline_close)) > baseline_tolerance:
            return match.group(0)
        return (
            f"{match.group('prefix')}收盘价{match.group('price')}{match.group('unit')}"
        )

    normalized = previous_pattern.sub(replace_previous, normalized)
    earlier_quote_pattern = re.compile(
        r"(?P<prefix>(?:相对于|相较于|较|比)?此前)(?:最新)?报价\s*"
        r"(?P<price>[0-9]+(?:\.[0-9]+)?)(?P<unit>\s*(?:元|美元|港元)?)"
    )

    def replace_earlier_quote(match: re.Match[str]) -> str:
        value = _number_value(match.group("price"))
        if value is None or abs(value - float(baseline_close)) > baseline_tolerance:
            return match.group(0)
        relation = match.group("prefix")
        if relation.startswith("相对于"):
            prefix = "相对于上一交易日收盘价"
        elif relation.startswith("相较于"):
            prefix = "相较于上一交易日收盘价"
        elif relation.startswith("较"):
            prefix = "较上一交易日收盘价"
        elif relation.startswith("比"):
            prefix = "比上一交易日收盘价"
        else:
            prefix = "此前上一交易日收盘价"
        return f"{prefix}{match.group('price')}{match.group('unit')}"

    return earlier_quote_pattern.sub(replace_earlier_quote, normalized)


def _stock_current_quote_ma20_conflict(answer: str, evidence: dict[str, Any]) -> bool:
    quote_price = (evidence.get("current_quote") or {}).get("price")
    ma20 = (evidence.get("price_levels") or {}).get("ma20")
    if not isinstance(ma20, (int, float)):
        ma20 = (evidence.get("metrics") or {}).get("ma20")
    if not isinstance(quote_price, (int, float)) or not isinstance(ma20, (int, float)):
        return False
    for clause in re.split(r"[。；\n]", answer):
        if not re.search(r"(?:当前|最新)(?:报价|价格|股价)", clause):
            continue
        if not re.search(r"(?:MA\s*20|20\s*日均线)", clause, re.IGNORECASE):
            continue
        negates_above = bool(
            re.search(
                r"(?:未|没有|并未|尚未|不能|无法)(?:有效)?"
                r"(?:高于|位于[^。；\n]{0,8}上方|站上|突破)",
                clause,
            )
        )
        negates_below = bool(
            re.search(
                r"(?:未|没有|并未|尚未|不能|无法)(?:有效)?"
                r"(?:低于|位于[^。；\n]{0,8}下方|跌破)",
                clause,
            )
        )
        claims_above = bool(
            re.search(r"(?:高于|上方|站上|突破)", clause)
        ) and not negates_above
        claims_below = bool(
            re.search(r"(?:低于|下方|跌破)", clause)
        ) and not negates_below
        if (
            float(quote_price) > float(ma20)
            and (claims_below or negates_above)
            and not claims_above
        ):
            return True
        if (
            float(quote_price) < float(ma20)
            and (claims_above or negates_below)
            and not claims_below
        ):
            return True
    return False


def _normalize_stock_current_quote_ma20_relation(
    answer: str, evidence: dict[str, Any]
) -> str:
    quote_price = (evidence.get("current_quote") or {}).get("price")
    ma20 = (evidence.get("price_levels") or {}).get("ma20")
    if not isinstance(ma20, (int, float)):
        ma20 = (evidence.get("metrics") or {}).get("ma20")
    if not isinstance(quote_price, (int, float)) or not isinstance(ma20, (int, float)):
        return answer
    quote_term = r"(?P<quote>(?:当前|最新)(?:报价|价格|股价))"
    ma_term = r"(?P<ma>(?:MA\s*20|20\s*日均线))"
    if float(quote_price) > float(ma20):
        return re.sub(
            quote_term
            + r"\s*(?:仍|已经|已)?\s*(?:低于|位于)\s*"
            + ma_term
            + r"(?:\s*下方)?",
            r"\g<quote>已高于 \g<ma>",
            answer,
            flags=re.IGNORECASE,
        )
    if float(quote_price) < float(ma20):
        return re.sub(
            quote_term
            + r"\s*(?:仍|已经|已)?\s*(?:高于|位于|站上)\s*"
            + ma_term
            + r"(?:\s*上方)?",
            r"\g<quote>仍低于 \g<ma>",
            answer,
            flags=re.IGNORECASE,
        )
    return answer


def _current_quote_is_at_common_a_share_limit(evidence: dict[str, Any]) -> bool:
    symbol = str(evidence.get("symbol") or "")
    quote_change = (evidence.get("current_quote") or {}).get("pct_change")
    if not symbol.endswith((".SS", ".SZ")) or not isinstance(
        quote_change, (int, float)
    ):
        return True
    # A-share boards commonly use 5%, 10%, 20%, or 30% daily limits.  The
    # exact price is rounded to the tick, so a small percentage tolerance is
    # necessary; a 9.5% quote is not treated as a 10% limit-up price.
    return (
        min(abs(abs(float(quote_change)) - limit) for limit in (5, 10, 20, 30)) <= 0.2
    )


def _stock_current_limit_status_conflict(answer: str, evidence: dict[str, Any]) -> bool:
    quote_change = (evidence.get("current_quote") or {}).get("pct_change")
    if not isinstance(quote_change, (int, float)):
        return False
    if _current_quote_is_at_common_a_share_limit(evidence):
        return False
    current_terms = ("当前", "目前", "现在", "最新", "盘中")
    historical_terms = ("曾", "一度", "此前", "先前", "触及", "打开过", "最高")
    target_terms = ("涨停", "封板") if quote_change >= 0 else ("跌停",)
    for clause in re.split(r"[。；\n]", answer):
        if not any(term in clause for term in target_terms):
            continue
        if any(term in clause for term in historical_terms):
            continue
        if any(term in clause for term in current_terms):
            return True
    return False


def _has_intraday_limit_touch_evidence(evidence: dict[str, Any], term: str) -> bool:
    information = evidence.get("a_share_information") or {}
    event_timeline = evidence.get("event_timeline") or {}
    titles = [
        str(item.get("title") or "")
        for item in [
            *(information.get("news") or []),
            *(information.get("announcements") or []),
            *(event_timeline.get("events") or []),
        ]
        if isinstance(item, dict)
    ]
    return any(
        term in title or (term == "涨停" and "封板" in title) for title in titles
    )


def _normalize_current_limit_status(answer: str, evidence: dict[str, Any]) -> str:
    if not _stock_current_limit_status_conflict(answer, evidence):
        return answer
    quote_change = float((evidence.get("current_quote") or {}).get("pct_change"))
    rising = quote_change >= 0
    limit_term = "涨停" if rising else "跌停"
    touched = _has_intraday_limit_touch_evidence(evidence, limit_term)
    replacement = (
        f"盘中曾触及{limit_term}后回落" if touched else f"当前未处于{limit_term}价"
    )
    pattern = (
        r"(?:当前|目前|现在|最新(?:报价)?|盘中)"
        r"(?:仍|已|正|处于|为)?\s*" + (r"(?:涨停|封板)" if rising else r"跌停")
    )
    normalized = re.sub(pattern, replacement, answer)
    if _stock_current_limit_status_conflict(normalized, evidence):
        normalized = re.sub(
            r"(?<!曾)(?<!触及)(?<!一度)" + (r"(?:涨停|封板)" if rising else r"跌停"),
            replacement,
            normalized,
        )
    return normalized


def _normalize_relative_event_dates(answer: str) -> str:
    answer = re.sub(
        r"(?:明日|明天)[（(](\d{1,2}月\d{1,2}日)[）)]",
        r"\1",
        answer,
    )
    answer = re.sub(
        r"(?:昨日|昨天|前天)[（(](\d{1,2}月\d{1,2}日)[）)]",
        r"\1",
        answer,
    )
    answer = re.sub(
        r"(?<=\d{4}-\d{2}-\d{2})[（(](?:昨日|昨天|前天)[）)]",
        "",
        answer,
    )
    return re.sub(r"(?:昨日|昨天|前天)", "此前", answer)


def _stock_current_quote_required_but_missing(
    answer: str, evidence: dict[str, Any]
) -> bool:
    question = str(evidence.get("user_question") or "")
    # “最新报告期/最新财报” asks for fresh accounting evidence, not a live
    # quote.  Leaving the bare word “最新” here used to force an unrelated
    # price-and-change preamble into valuation and earnings-quality answers.
    quote_question = re.sub(
        r"(?:最新|当前)(?:报告期|财报|一季报|半年报|季报|中报|年报|"
        r"财务报告|业绩报告|正式报告)",
        "",
        question,
    )
    if not any(
        term in quote_question
        for term in ("今天", "今日", "当前", "现在", "盘中", "最新")
    ):
        return False
    quote = evidence.get("current_quote") or {}
    if not _stock_current_quote_is_newer(evidence):
        return False
    quote_price = quote.get("price")
    quote_change = quote.get("pct_change")
    if not isinstance(quote_price, (int, float)) or not isinstance(
        quote_change, (int, float)
    ):
        return True

    claimed_values = [
        value
        for match in _NUMBER_RE.finditer(answer)
        if (value := _number_value(match.group(0))) is not None
    ]
    price_tolerance = max(0.02, abs(float(quote_price)) * 0.002)
    if not any(
        abs(value - float(quote_price)) <= price_tolerance + 1e-9
        for value in claimed_values
    ):
        return True

    change_tolerance = max(0.02, abs(float(quote_change)) * 0.002)
    if any(
        abs(value - float(quote_change)) <= change_tolerance + 1e-9
        for value in claimed_values
    ):
        return False

    direction_terms = (
        (
            "下跌",
            "跌了",
            "微跌",
            "跌幅",
            "收跌",
            "回落",
            "走低",
            "下挫",
            "下滑",
        )
        if float(quote_change) < 0
        else ("上涨", "涨了", "微涨", "涨幅", "收涨", "反弹", "走高", "上扬")
    )
    for clause in re.split(r"[。；\n]", answer):
        if not any(term in clause for term in direction_terms):
            continue
        for match in _NUMBER_RE.finditer(clause):
            value = _number_value(match.group(0))
            if (
                value is not None
                and abs(abs(value) - abs(float(quote_change)))
                <= change_tolerance + 1e-9
            ):
                return False
    return True


def _has_stock_cross_date_market_claim(answer: str, evidence: dict[str, Any]) -> bool:
    market_context = evidence.get("stock_market_context") or {}
    breadth = market_context.get("market_breadth") or {}
    if breadth.get("same_date_as_target") is True:
        return False
    cautious_terms = (
        "不能确认",
        "无法确认",
        "不能用于解释",
        "不用于解释",
        "与目标日不一致",
        "不是目标日",
        "其他交易日",
        "尚无",
        "尚未取得",
        "尚未获得",
        "尚未形成",
        "待补证",
        "缺乏同日",
        "缺少同日",
        "同日数据缺失",
    )
    for clause in re.split(r"[。；\n]", answer):
        if any(term in clause for term in cautious_terms):
            continue
        if re.search(
            r"(?:不存在|没有|未见|未形成|无|可以排除|可排除|排除|并非|不是|"
            r"不属于|不构成|非)"
            r"[^。；\n]{0,24}(?:全市场|系统性|大盘)"
            r"[^。；\n]{0,16}(?:拖累|普跌|下跌)|"
            r"(?:全市场|系统性|大盘)[^。；\n]{0,20}"
            r"(?:已排除|可以排除|可排除|不存在|并非|不是)|"
            r"(?:市场|市场整体)[^。；\n]{0,20}"
            r"(?:并非|不是|不属于|不构成|未形成)[^。；\n]{0,16}"
            r"(?:全面下跌|系统性拖累)",
            clause,
        ):
            return True
        if re.search(
            r"(?:全市场(?:广度|涨跌家数|上涨|下跌|成交额)|"
            r"(?:A股)?全市场[^。；\n]{0,60}"
            r"(?:上涨家数|下跌家数|平盘|成交(?:额)?)|"
            r"全A股[^。；\n]{0,48}(?:上涨|下跌|平盘|成交额)|"
            r"(?:全市场|全A股|沪深京)[^。；\n]{0,28}成交额)",
            clause,
        ):
            return True
    return False


def _has_stock_industry_breadth_overclaim(
    answer: str, evidence: dict[str, Any]
) -> bool:
    industry_index = (evidence.get("stock_market_context") or {}).get(
        "exact_industry_index"
    ) or {}
    component_breadth = industry_index.get("component_breadth") or {}
    if component_breadth.get("status") == "available":
        return False
    cautious_terms = (
        "不能确认",
        "无法确认",
        "不能判断",
        "无法判断",
        "没有证据",
        "证据不足",
        "尚未取得",
        "尚未获得",
        "仍缺",
        "不能据此",
    )
    for clause in re.split(r"[。；\n]", answer):
        if any(term in clause for term in cautious_terms):
            continue
        if re.search(
            r"(?:行业|板块)[^。；\n]{0,24}(?:普涨|普跌|参与面(?:较)?(?:广|窄))|"
            r"(?:多数|大多数|绝大多数)[^。；\n]{0,16}(?:成分股|行业个股)"
            r"[^。；\n]{0,16}(?:上涨|下跌)",
            clause,
        ):
            return True
    return False


def _has_stock_industry_causal_overclaim(answer: str) -> bool:
    cautious_terms = (
        "不能确认",
        "无法确认",
        "不能证明",
        "无法证明",
        "不能单独证明",
        "无法单独证明",
        "不等于原因",
        "不是原因证明",
    )
    for clause in re.split(r"[。；\n]", answer):
        if any(term in clause for term in cautious_terms):
            continue
        if not re.search(r"(?:行业|板块)[^。；\n]{0,30}(?:普涨|普跌)", clause):
            continue
        if re.search(r"(?:导致|造成|驱动|拖累|共同作用|解释了|原因)", clause):
            return True
    return False


def _stock_contribution_required_but_missing(
    answer: str, evidence: dict[str, Any]
) -> bool:
    question = str(evidence.get("user_question") or "")
    if "贡献" not in question:
        return False
    industry_index = (evidence.get("stock_market_context") or {}).get(
        "exact_industry_index"
    ) or {}
    contribution = industry_index.get("component_contribution") or {}
    subject = contribution.get("subject") or {}
    expected = subject.get("estimated_contribution_pp")
    if contribution.get("status") != "available" or not isinstance(
        expected, (int, float)
    ):
        return False
    subject_name = str(
        subject.get("name") or evidence.get("display_name") or ""
    ).strip()
    if subject_name and subject_name not in answer and "中兴" not in answer:
        return True
    has_subject_value = False
    for clause in re.split(r"[。；\n]", answer):
        if "贡献" not in clause:
            continue
        values = [
            value
            for match in _NUMBER_RE.finditer(clause)
            if (value := _number_value(match.group(0))) is not None
        ]
        if any(
            abs(value - float(expected)) <= max(0.01, abs(float(expected)) * 0.02)
            for value in values
        ):
            has_subject_value = True
            break
    if not has_subject_value:
        return True
    if any(term in question for term in ("限制", "口径", "边界")):
        has_boundary = (
            "静态估算" in answer
            and any(term in answer for term in ("不是中证官方", "非官方", "不是官方"))
        ) or (
            "权重快照" in answer
            and any(term in answer for term in ("对账差", "权重漂移", "样本调整"))
        )
        return not has_boundary
    return False


def _stock_industry_counts_required_but_missing(
    answer: str, evidence: dict[str, Any]
) -> bool:
    question = str(evidence.get("user_question") or "")
    explicitly_requested = "涨跌家数" in question or (
        "成分" in question
        and all(term in question for term in ("上涨", "下跌", "平盘"))
    )
    if not explicitly_requested:
        return False
    industry_index = (evidence.get("stock_market_context") or {}).get(
        "exact_industry_index"
    ) or {}
    breadth = industry_index.get("component_breadth") or {}
    if breadth.get("status") != "available":
        return False
    for label, key in (
        ("上涨", "advancers"),
        ("下跌", "decliners"),
        ("平盘", "unchanged"),
    ):
        expected = breadth.get(key)
        if not isinstance(expected, int):
            return False
        if not re.search(
            rf"(?:{label}[^。；\n]{{0,18}}{expected}\s*(?:只|家)|"
            rf"{expected}\s*(?:只|家)[^。；\n]{{0,18}}{label})",
            answer,
        ):
            return True
    return False


def _stock_component_source_boundary_required_but_missing(
    answer: str, evidence: dict[str, Any]
) -> bool:
    industry_index = (evidence.get("stock_market_context") or {}).get(
        "exact_industry_index"
    ) or {}
    breadth = industry_index.get("component_breadth") or {}
    coverage = breadth.get("coverage") or {}
    fallback_count = coverage.get("fallback_unadjusted_returns")
    fallbacks = list(breadth.get("source_fallbacks") or [])
    if not (isinstance(fallback_count, int) and fallback_count > 0) and not fallbacks:
        return False
    names = [
        str(item.get("name") or item.get("symbol") or "").strip()
        for item in fallbacks[:3]
    ]
    names = [item for item in names if item]
    names_present = all(name in answer for name in names)
    source_present = any(term in answer for term in ("新浪公开日线", "公开未复权日线"))
    adjustment_present = "未复权" in answer
    boundary_present = any(
        term in answer for term in ("除权除息", "公司行动", "复权口径")
    )
    return not (
        names_present and source_present and adjustment_present and boundary_present
    )


def _has_stock_market_absorption_overclaim(answer: str) -> bool:
    return bool(
        re.search(
            r"(?:基本面|财报|业绩)[^。；\n]{0,50}"
            r"(?:已在市场消化|已被市场消化|已经计价|已计价)|"
            r"(?:基本面|财报|季报|中报|年报|业绩|盈利质量|经营压力)[^。；\n]{0,60}"
            r"(?:(?:不构成|不是|并非)[^。；\n]{0,24}新信息|"
            r"已被市场知晓|市场已经知晓)|"
            r"(?:基本面|财报|季报|中报|年报|业绩|盈利质量|经营压力)[^。；\n]{0,80}"
            r"(?:此前已存在(?:的)?信息|早已存在(?:的)?信息|"
            r"(?:不是|并非)[^。；\n]{0,20}新出现的驱动)|"
            r"(?:情绪驱动|情绪面驱动)[^。；\n]{0,24}(?:超跌|下跌|反弹)",
            answer,
        )
    )


def _is_public_component_source_boundary_clause(clause: str) -> bool:
    if "未复权日线" not in clause:
        return False
    if not any(term in clause for term in ("除权除息", "公司行动", "复权口径")):
        return False
    if not any(term in clause for term in ("成分", "贝特瑞", ".BJ")):
        return False
    if re.search(
        r"(?:fallback_|source_attempts|reason_code|数据源|行情源|主源|备用源|降级|"
        r"接口失败|请求失败|不可用|内部任务|job_name|ProxyError|WAF|"
        r"HTTP\s*429|缓存|上游)",
        clause,
        re.IGNORECASE,
    ):
        return False
    return True


def _is_evidence_security_entity_clause(clause: str, evidence: dict[str, Any]) -> bool:
    """Keep listed companies whose names overlap with provider brand names."""
    rows: list[dict[str, Any]] = []
    if isinstance(evidence, dict):
        rows.append(evidence)
        for key in ("item", "target", "security"):
            value = evidence.get(key)
            if isinstance(value, dict):
                rows.append(value)
        for key in ("items", "targets"):
            values = evidence.get(key)
            if isinstance(values, list):
                rows.extend(value for value in values if isinstance(value, dict))

    for row in rows:
        name = str(row.get("name") or "").strip()
        symbol = str(row.get("internal_symbol") or row.get("symbol") or "").strip()
        if not name or not symbol or name not in clause:
            continue
        code = symbol.split(".", 1)[0]
        if re.search(
            rf"(?<!\d){re.escape(code)}(?:\.(?:SZ|SS|SH|BJ))?(?!\d)",
            clause,
            re.IGNORECASE,
        ):
            return True
    return False


def _has_stock_event_sentiment_overclaim(answer: str) -> bool:
    for clause in re.split(r"[。；\n]", answer):
        if not re.search(r"(?:公告|媒体|报道|事件|披露|线索|消息|信息)", clause):
            continue
        explicit_boundary = re.search(
            r"(?:不能|不得|不应|不可|无法|不宜|不作|不做|不代表|不等于)"
            r"[^。；\n]{0,24}(?:评为|评价为|归类为|判断为|认定为|解释为|"
            r"视为|证明|代表|等于)[^。；\n]{0,12}"
            r"(?:正面|负面|中性|利好|利空|催化)",
            clause,
        )
        if (
            any(
                term in clause
                for term in (
                    "属于中性",
                    "中性事件",
                    "中性话题",
                    "正面事件",
                    "负面事件",
                    "正面或中性",
                    "正面/中性",
                    "正面信号",
                    "负面信号",
                    "正面话题",
                    "负面话题",
                    "利好事件",
                    "利空事件",
                    "偏正面",
                    "偏负面",
                    "视为正面",
                    "视为负面",
                    "解读为正面",
                    "解读为负面",
                    "理解为正面",
                    "理解为负面",
                    "方向不一",
                    "方向一致",
                    "解释方向",
                    "明显催化剂",
                    "构成催化剂",
                )
            )
            and not explicit_boundary
        ):
            return True
        if not explicit_boundary and (
            re.search(
                r"(?:公告|媒体|报道|事件|披露)[^。；\n]{0,18}"
                r"(?:正面|负面|中性|利好|利空|催化)",
                clause,
            )
            or re.search(
                r"(?:正面|负面|中性|利好|利空|催化)[^。；\n]{0,18}"
                r"(?:公告|媒体|报道|事件|披露)",
                clause,
            )
        ):
            return True
    return False


def _has_stock_unsupported_causal_hypothesis(
    answer: str, evidence: dict[str, Any] | None = None
) -> bool:
    evidence = evidence or {}
    question = str(evidence.get("user_question") or "")
    research_focus = str((evidence.get("research_plan") or {}).get("focus") or "")
    price_cause_question = research_focus == "price_cause" or (
        any(
            term in question
            for term in (
                "为什么",
                "为何",
                "原因",
                "怎么跌",
                "怎么涨",
                "最可能",
                "有什么关系",
                "有何关系",
                "是否有关",
            )
        )
        and any(
            term in question
            for term in (
                "涨",
                "跌",
                "回撤",
                "回落",
                "走弱",
                "走强",
                "大涨",
                "大跌",
            )
        )
    )
    cautious_terms = (
        "不能确认",
        "无法确认",
        "不能说明",
        "无法说明",
        "不能单独证明",
        "无法单独证明",
        "没有证据",
        "未取得证据",
        "不等于",
        "不能归因",
    )
    for clause in re.split(r"[。；\n]", answer):
        explicit_causal_rejection = bool(
            re.search(
                r"(?:没有|缺少|无|尚无|未有)[^。；\n]{0,32}"
                r"(?:正文|原文|直接|充分)?(?:依据|证据)[^。；\n]{0,48}"
                r"(?:能|可以)?把[^。；\n]{0,120}"
                r"(?:解释为|归因于|认定为|视为|证明为)|"
                r"(?:不能|无法|不应|不宜|不足以)(?:直接)?把"
                r"[^。；\n]{0,140}(?:解释为|归因于|认定为|视为|"
                r"与[^。；\n]{0,50}建立因果)|"
                r"(?:不能|无法|不足以)[^。；\n]{0,120}建立因果|"
                r"(?:不能|无法|尚不能|尚无法|未能)(?:直接)?确认"
                r"[^。；\n]{0,120}(?:是|属于|构成)"
                r"[^。；\n]{0,40}(?:直接|主要|核心)?(?:原因|驱动)|"
                r"(?:不能|无法|不应|不宜|不足以)(?:直接)?"
                r"(?:解读|解释|认定|视为|归因)为[^。；\n]{0,120}"
                r"(?:原因|驱动|压力|紧张)|"
                r"(?:不等于|并不等于|不代表)[^。；\n]{0,120}"
                r"(?:直接|主要|核心)?(?:原因|驱动)",
                clause,
            )
        )
        if price_cause_question:
            market_story = re.search(
                r"(?:融资余额|融资买入|融资盘)[^。；\n]{0,100}"
                r"(?:意味着|说明|表明)[^。；\n]{0,100}"
                r"(?:对价格波动(?:往往)?更敏感|容易卖出|抛售|卖出压力|形成压力)|"
                r"(?:融资余额|融资买入|融资盘)[^。；\n]{0,160}"
                r"(?:这类|相关|融资)资金[^。；\n]{0,50}"
                r"(?:对价格波动(?:往往)?更敏感|容易卖出|抛售|卖出压力|形成压力)|"
                r"(?:借钱买|加杠杆买|融资买入)[^。；\n]{0,120}"
                r"(?:这类|相关|融资)资金[^。；\n]{0,50}"
                r"(?:对价格波动(?:往往)?更敏感|容易卖出|抛售|卖出压力|形成压力)|"
                r"(?:股权登记|分红登记|除权除息)[^。；\n]{0,140}"
                r"(?:可能|往往|通常)[^。；\n]{0,100}"
                r"(?:卖出|离场|获利了结|拿完分红就走)|"
                r"(?:股权登记日|分红登记日)[^。；\n]{0,100}"
                r"(?:当日|当天)?[^。；\n]{0,30}(?:参考价|股价)"
                r"[^。；\n]{0,30}(?:自动|会|将)[^。；\n]{0,20}"
                r"(?:扣除|调整|除权|除息)|"
                r"(?:股权登记|分红登记)[^。；\n]{0,100}"
                r"(?:除息|除权)[^。；\n]{0,60}(?:影响|因素|导致|额外)|"
                r"(?:等|等待|关注)[^。；\n]{0,30}(?:今天|今日)?收盘后"
                r"[^。；\n]{0,24}(?:除权除息|权益分派)(?:实施)?(?:公告|原文)",
                clause,
            )
            explicit_registration_boundary = re.search(
                r"(?:股权登记日|分红登记日)[^。；\n]{0,80}"
                r"(?:不等于|并不等于|不代表|不能说明|不会)"
                r"[^。；\n]{0,80}(?:自动扣除|一定要跌|必然下跌)|"
                r"(?:没有证据|尚无证据|未有证据)[^。；\n]{0,90}"
                r"(?:就是除权除息日|自动扣减|自动扣除)|"
                r"不能(?:直接)?(?:说|把)[^。；\n]{0,80}"
                r"(?:拿完分红就跑|登记日导致下跌|归结为[^。；\n]{0,20}分红除权)",
                clause,
            )
            if market_story and not explicit_registration_boundary:
                return True
        if not any(term in clause for term in ("无法核验", "不能核验", "不可能核验")):
            if re.search(
                r"(?:核验|确认|排除|排查|留意|关注|判断)[^。；\n]{0,180}"
                r"(?:未公开|未披露|尚未被正式披露|内幕)[^。；\n]{0,24}"
                r"(?:信息|消息|订单|仓位|变动|变化|事项|因素)",
                clause,
            ):
                return True
        if not explicit_causal_rejection and re.search(
            r"(?:主要(?:原因|表现为)|核心原因|直接原因|归因于|源于)"
            r"[^。；\n]{0,180}(?:公告|分红|除权除息|回购|新闻|消息|事件|"
            r"前期急涨|获利回吐|技术性回吐|提前调整)|"
            r"(?:公告|分红|除权除息|回购|新闻|消息|事件)"
            r"[^。；\n]{0,100}(?:引发|导致|造成|驱动|带来|触发)"
            r"[^。；\n]{0,80}(?:下跌|大跌|回落|调整|回吐)",
            clause,
        ):
            return True
        if price_cause_question and not explicit_causal_rejection and re.search(
            r"(?:这轮|这段|此次|本次|近\s*\d+\s*(?:日|天)|两三周)?"
            r"(?:的)?(?:股价)?(?:回撤|下跌|走弱)[^。；\n]{0,100}"
            r"(?:很大程度上)?(?:可能是|可能来自|更可能是|属于)"
            r"[^。；\n]{0,80}(?:市场对|投资者对)[^。；\n]{0,80}"
            r"(?:财报|[一三]?季报|中报|半年报|年报|业绩|基本面|盈利|利润|现金流)"
            r"[^。；\n]{0,40}"
            r"(?:延续反应|反应|定价|担忧|顾虑)",
            clause,
        ):
            return True
        if price_cause_question and not explicit_causal_rejection and re.search(
            r"(?:借款|关联交易|担保|授信|融资)[^。；\n]{0,120}"
            r"(?:公告|披露|事项)?[^。；\n]{0,80}"
            r"(?:侧面反映|表明|说明|可能加剧|加剧|引发)"
            r"[^。；\n]{0,60}(?:资金面|流动性|现金流|融资)"
            r"[^。；\n]{0,30}(?:压力|紧张|担忧|困难|吃紧)",
            clause,
        ):
            return True
        if re.search(
            r"(?:上涨|下跌|大跌|回落|走弱|走强)[^。；\n]{0,80}"
            r"(?:更像|主要)[^。；\n]{0,30}(?:跟随|跟着)"
            r"[^。；\n]{0,30}(?:整体市场|大盘|市场节奏)|"
            r"(?:上涨|下跌|涨了|跌了|涨的原因|跌的原因|大跌|回落|走弱|走强)"
            r"[^。；\n]{0,80}"
            r"(?:更像|更可能|大概率)[^。；\n]{0,60}"
            r"(?:公司|个股|板块|行业)[^。；\n]{0,40}(?:因素|原因|驱动)|"
            r"(?:涨的原因|跌的原因)[^。；\n]{0,40}(?:主要|只能|得)"
            r"[^。；\n]{0,30}(?:公司|个股|板块|行业)[^。；\n]{0,24}(?:情况|因素|原因)|"
            r"(?:属于|表现为|体现为)[^。；\n]{0,30}(?:个股|公司)"
            r"[^。；\n]{0,20}(?:独立走弱|独立走强|独立表现)|"
            r"(?:上涨|下跌|大跌|回落)[^。；\n]{0,24}(?:主要)?"
            r"(?:来自|源于|归因于|由)[^。；\n]{0,24}"
            r"(?:个股|公司)(?:自身|特定)?(?:因素|压力|原因)|"
            r"(?:上涨|下跌|大跌|回落|跌幅|涨幅)[^。；\n]{0,80}"
            r"(?:更多|主要)[^。；\n]{0,24}(?:是|由)?"
            r"(?:自身|个股|公司)(?:特定)?因素[^。；\n]{0,16}(?:主导|驱动)|"
            r"(?:上涨|下跌|大跌|回落)[^。；\n]{0,100}"
            r"(?:更像|更可能)[^。；\n]{0,60}(?:公司|个股)"
            r"[^。；\n]{0,28}(?:自己的情况|自身因素|特定因素)|"
            r"(?:更多|主要)?体现为[^。；\n]{0,120}"
            r"(?:获利回吐|基本面隐忧|因素共振|情绪共振)|"
            r"(?:获利回吐|基本面隐忧)[^。；\n]{0,60}(?:共振|导致|驱动)",
            clause,
        ):
            return True
        if re.search(
            r"(?:上涨|下跌|大跌|回落|相对弱势|相对偏弱|跑输|跑赢)"
            r"[^。；\n]{0,100}(?:更可能是|可能是|可能来自|可能源于|说明|表明)"
            r"[^。；\n]{0,100}(?:短期资金行为|资金选择|资金偏好|筹码变化|"
            r"节奏变化|获利了结|获利回吐|市场情绪|交易情绪|技术性因素)|"
            r"(?:上涨|下跌|大跌|回落|相对弱势|相对偏弱|跑输|跑赢)"
            r"[^。；\n]{0,100}(?:而非|并非|不是)[^。；\n]{0,36}基本面",
            clause,
        ):
            return True
        if any(term in clause for term in cautious_terms):
            continue
        if re.search(
            r"(?:并)?(?:没有|不存在|未见|可以排除|可排除|排除)"
            r"[^。；\n]{0,28}(?:独立于(?:市场|大盘|行业)的?)?"
            r"(?:个股|公司)(?:独立|特定|自身)?"
            r"(?:驱动|因素|利空|原因|信号)",
            clause,
        ):
            return True
        if re.search(
            r"(?:可能|原因|驱动|因素)[^。；\n]{0,140}"
            r"(?:MA\s*20|MA\s*60|均线|技术指标|[五5]\s*日收益|"
            r"行业内部轮动|板块轮动|业务结构未受益)|"
            r"(?:MA\s*20|MA\s*60|均线|技术指标|[五5]\s*日收益|"
            r"行业内部轮动|板块轮动|业务结构未受益)"
            r"[^。；\n]{0,100}(?:原因|驱动|公司特定因素|自身因素)",
            clause,
            re.IGNORECASE,
        ):
            return True
        if re.search(
            r"(?:属于|说明|表明|归因于)[^。；\n]{0,36}"
            r"(?:中兴通讯|中兴|个股|公司|其跌幅)"
            r"[^。；\n]{0,20}(?:自身)?(?:压力|原因|因素)",
            clause,
        ):
            return True
        if re.search(
            r"(?:最常见的情况|通常情况|大概率)[^。；\n]{0,180}"
            r"(?:基本面疑虑|筹码分布|持有人分散|提前定价)",
            clause,
        ):
            return True
        if price_cause_question and re.search(
            r"(?:等|等待|关注)[^。；\n]{0,70}(?:公司)?(?:可能)?"
            r"(?:发布|披露)(?:的)?(?:正式)?(?:公告|说明|澄清)",
            clause,
        ):
            return True
    return False


def _has_stock_60d_return_binding_conflict(
    answer: str, evidence: dict[str, Any]
) -> bool:
    expected = (evidence.get("metrics") or {}).get("return_60d_pct")
    if not isinstance(expected, (int, float)):
        return False
    for clause in re.split(r"[。；\n]", answer):
        if not re.search(r"60\s*日(?:累计)?收益", clause):
            continue
        values = [
            value
            for match in _NUMBER_RE.finditer(clause)
            if (value := _number_value(match.group(0))) is not None
        ]
        if values and not any(
            abs(value - float(expected)) <= max(0.02, abs(float(expected)) * 0.005)
            for value in values
        ):
            return True
    return False


def _has_stock_debt_ratio_scale_conflict(
    answer: str, evidence: dict[str, Any]
) -> bool:
    earnings = evidence.get("earnings_quality") or {}
    latest = earnings.get("latest_report") or {}
    comparable = earnings.get("comparable_report") or {}
    if isinstance(latest.get("total_liabilities"), (int, float)) and isinstance(
        comparable.get("total_liabilities"), (int, float)
    ):
        return False
    for clause in re.split(r"[。；\n]", answer):
        if "资产负债率" not in clause:
            continue
        debt_scale_is_open_question = bool(
            re.search(
                r"(?:负债(?!率)|债务)(?:整体|总体|绝对)?(?:总量|规模|余额|金额)?"
                r"[^。；\n]{0,16}(?:是否|能否|有无)"
                r"[^。；\n]{0,16}(?:下降|减少|降低|收缩|减轻|变化)"
                r"(?:[^。；\n]{0,16}(?:仍|尚)?(?:需|需要|应|应该)?"
                r"(?:进一步)?(?:核对|确认|验证|查证|复核))?",
                clause,
            )
        )
        if debt_scale_is_open_question:
            continue
        if any(
            term in clause
            for term in (
                "不能说明",
                "不能证明",
                "不能据此",
                "不能判断",
                "不能直接判断",
                "无法判断",
                "尚无法判断",
                "不代表",
                "不等于",
                "并非说明",
                "并非必然说明",
                "不能直接改写",
            )
        ):
            continue
        scale_clause = re.sub(
            r"负债占(?:总)?资产(?:的)?(?:比例|比重)"
            r"[^。；\n]{0,12}(?:下降|减少|降低|收缩|减轻)",
            "",
            clause,
        )
        if re.search(
            r"(?:负债(?!率)|债务)(?:整体|总体|绝对)?(?:总量|规模|余额)?"
            r"[^。；\n]{0,16}(?:下降|减少|降低|收缩|减轻)|"
            r"(?:下降|减少|降低|收缩|减轻)[^。；\n]{0,16}"
            r"(?:负债(?!率)|债务)(?:整体|总体|绝对)?(?:总量|规模|余额)",
            scale_clause,
        ):
            return True
    return False


def _has_stock_cashflow_causal_conflict(
    answer: str, evidence: dict[str, Any]
) -> bool:
    filing = (evidence.get("financial_drivers") or {}).get("filing_evidence") or {}
    if filing.get("explicit_company_explanations"):
        return False
    for clause in re.split(r"[。；\n]", answer):
        if "经营现金流" not in clause or not any(
            term in clause for term in ("营收", "营业收入", "收入规模")
        ):
            continue
        if re.search(
            r"经营现金流[^。；\n]{0,100}"
            r"(?:主要原因(?:是|在于)|主要由于|源于|由)[^。；\n]{0,60}"
            r"(?:营收|营业收入|收入规模)|"
            r"(?:营收|营业收入|收入规模)[^。；\n]{0,80}"
            r"(?:导致|造成|拖累|使得)[^。；\n]{0,40}经营现金流",
            clause,
        ):
            return True
    return False


def _has_stock_static_financial_causal_overclaim(
    answer: str, evidence: dict[str, Any]
) -> bool:
    drivers = (evidence.get("financial_drivers") or {}).get(
        "confirmed_mechanical_drivers"
    ) or []
    if not any(
        item.get("calculation_nature") == "static_counterfactual"
        for item in drivers
        if isinstance(item, dict)
    ):
        return False
    cautious_terms = (
        "不等于实际",
        "不是实际",
        "不是已确认",
        "不能说明",
        "无法说明",
        "不能确认",
        "无法确认",
        "不能归因",
        "只是假设",
        "仅为静态",
    )
    for clause in re.split(r"[。；\n]", answer):
        if "静态" not in clause or any(term in clause for term in cautious_terms):
            continue
        if re.search(
            r"(?:说明|表明|意味着|证明)[^。；\n]{0,80}"
            r"(?:利润下滑|利润下降|成本端|经营原因|业务原因)|"
            r"(?:利润下滑|利润下降|经营原因|业务原因)[^。；\n]{0,60}"
            r"(?:来自|源于|归因于|由于|并非来自|不是来自)|"
            r"(?:静态测算|静态反事实)[^。；\n]{0,80}"
            r"(?:实际贡献|实际拖累|直接导致|直接拉低)",
            clause,
        ):
            return True
    return False
