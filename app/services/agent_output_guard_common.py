from __future__ import annotations

import re


_NUMBER_RE = re.compile(r"(?<![A-Za-z0-9_])[-+]?\d[\d,]*(?:\.\d+)?%?")
_LONG_DECIMAL_RE = re.compile(
    r"(?<![A-Za-z0-9_.])(?P<value>[-+]?\d+\.\d{3,})(?![A-Za-z0-9_.])"
)
_EVIDENCE_MAGNITUDE_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
_NEGATIVE_NUMBER_CONTEXT_RE = re.compile(
    r"(?:下跌|跌|下降|减少|回撤|亏损|负增长|转负|"
    r"down|fell|falls|falling|dropped|drops|slipped|slips|declined|declines|lower)",
    re.IGNORECASE,
)
_POSITIVE_NUMBER_CONTEXT_RE = re.compile(
    r"(?:上涨|涨|上升|增长|增加|正增长|转正|"
    r"up|rose|rises|rising|gained|gains|advanced|advances|higher)",
    re.IGNORECASE,
)
_PROHIBITED_OUTPUT_PATTERNS = (
    re.compile(r"(?:目标价|目标点位)\s*[：:]?\s*[-+]?\d", re.IGNORECASE),
    re.compile(r"(?:胜率|概率)[^。；\n]{0,12}\d+(?:\.\d+)?%", re.IGNORECASE),
    re.compile(
        r"(?:未来|明日|下一交易日|预计|预测|大概率)"
        r"[^。；\n]{0,16}(?:上涨|下跌)[^。；\n]{0,10}\d+(?:\.\d+)?%",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?<!不)(?<!不能)(?<!无法)(?<!不会)(?<!并不)(?<!绝不)"
        r"(?<!没有)(?<!并非)(?<!不可)"
        r"(?:保证收益|稳赚|必涨|必跌|强烈买入|强烈卖出|建议买入|建议卖出)"
    ),
    re.compile(r"\b(?:BUY|HOLD|SELL)\b", re.IGNORECASE),
)
_PRIVATE_OPERATIONAL_OUTPUT_PATTERNS = (
    re.compile(
        r"\b(?:fallback_unadjusted_returns|source_attempts|reason_code)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:数据源|行情源|主源|备用源|上游|降级|缓存(?:命中|回退)?|"
        r"接口(?:失败|错误)|请求失败|不可用|内部任务|job_name|ProxyError|WAF|"
        r"HTTP\s*[45]\d\d|usage limit|billing cycle|quota|purchase extra usage|"
        r"upgrade your plan|kimi\.com/code)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:No reply:|maximum tool-iteration|max_iterations_reached|"
        r"maximum iterations)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:东方财富|新浪财经|新浪口径|Yahoo(?: Finance)?|"
        r"Tencent Finance|腾讯财经|Nasdaq News|NewsAPI|雪球|Xueqiu)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:数据库|系统|后台)[^。；\n]{0,40}"
        r"(?:尝试|抓取|同步|刷新)[^。；\n]{0,30}"
        r"(?:未成功|失败|尚未取得|不可用)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:标记为)?(?:已过时|陈旧)|\bstale\b|\bUTC\b|"
        r"\b(?:technical_state|trend_state|market_state|market_drivers|"
        r"question_focus(?:\.key)?|date_alignment|analysis_eligibility|"
        r"same_date_as_analysis_target|cross_date_excluded|market_cause|"
        r"return_(?:1|5|20|60)d_pct|"
        r"volume_ratio_5_20|max_drawdown(?:_60d_pct)?|evidence_readiness|"
        r"conditional_outlook|optional_gaps|not_directionally_consistent)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bfixed_peer_operating_comparison_v\d+\b", re.IGNORECASE),
)


def _number_value(token: str) -> float | None:
    try:
        return float(token.replace(",", "").rstrip("%"))
    except (TypeError, ValueError):
        return None
