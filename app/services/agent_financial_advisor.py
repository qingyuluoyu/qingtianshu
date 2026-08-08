from __future__ import annotations

import re
from typing import Any


_CN_MAGNITUDE = "一二两三四五六七八九十百几半"
_CN_PERCENT_OR_FRACTION = rf"(?:百分之[{_CN_MAGNITUDE}]+|[{_CN_MAGNITUDE}]+成)"
_ARABIC_PERCENT = r"[+-]?\d+(?:\.\d+)?%"
_ARABIC_NUMBER = r"\d+(?:\.\d+)?"


def _fund_percentage_aliases(evidence: dict[str, Any]) -> set[str]:
    context = evidence.get("fund_product_context") or {}
    values: set[float] = set()

    def collect(value: Any, key: str = "") -> None:
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                collect(child_value, str(child_key))
            return
        if isinstance(value, list):
            for child in value:
                collect(child, key)
            return
        if "pct" not in key.casefold() or isinstance(value, bool):
            return
        try:
            values.add(float(value))
        except (TypeError, ValueError):
            return

    collect(context)
    aliases: set[str] = set()
    for value in values:
        for digits in range(5):
            rendered = f"{value:.{digits}f}".rstrip("0").rstrip(".")
            aliases.add(f"{rendered}%")
            if value > 0:
                aliases.add(f"+{rendered}%")
    return aliases


def normalize_financial_advisor_answer(
    answer: str,
    evidence: dict[str, Any],
) -> str:
    """Remove invented teaching thresholds from incomplete suitability answers."""

    context = evidence.get("financial_advisor_context") or {}
    if context.get("status") not in {
        "needs_profile",
        "ready_for_conditional_guidance",
    }:
        return answer

    normalized = str(answer or "")
    supported_product_percentages = _fund_percentage_aliases(evidence)

    def replace_duration(match: re.Match[str], replacement: str) -> str:
        if not evidence.get("fund_product_context"):
            return replacement
        before = normalized[max(0, match.start() - 3) : match.start()]
        after = normalized[match.end() : match.end() + 4]
        if before.endswith(("近", "过去", "最近")) or after.startswith(
            ("收益", "回报", "表现", "涨跌", "累计")
        ):
            return match.group(0)
        return replacement

    replacements = (
        (
            rf"短期可能下跌{_CN_PERCENT_OR_FRACTION}(?:甚至更多)?",
            "短期可能出现明显下跌",
        ),
        (
            rf"(?:可能)?(?:一段时间)?(?:下跌|跌掉){_CN_PERCENT_OR_FRACTION}(?:甚至更多)?",
            "可能出现明显下跌",
        ),
        (
            rf"(?:中间|暂时|账户暂时)?(?:亏了|亏损){_CN_PERCENT_OR_FRACTION}",
            "出现明显账面亏损",
        ),
        (
            rf"(?:出现)?回撤{_CN_PERCENT_OR_FRACTION}",
            "出现明显回撤",
        ),
        (
            rf"[{_CN_MAGNITUDE}]+年以上(?:用不到|用不上|不用|不动)的钱",
            "长期不用的钱",
        ),
        (
            rf"[{_CN_MAGNITUDE}]+年(?:以上)?(?:的)?(?:长期)?"
            r"(?:都)?(?:用不到|用不上|不用|不动)",
            "长期不用",
        ),
        (
            rf"[{_CN_MAGNITUDE}]+年内",
            "短期内",
        ),
        (
            rf"[{_CN_MAGNITUDE}]+年以上",
            "长期",
        ),
        (
            rf"[{_CN_MAGNITUDE}]+个月生活费",
            "必要的应急生活费",
        ),
    )
    for pattern, replacement in replacements:
        normalized = re.sub(pattern, replacement, normalized)

    normalized = re.sub(
        rf"(?:[{_CN_MAGNITUDE}]+个月|{_ARABIC_NUMBER}\s*个月)"
        rf"[、，,]\s*[{_CN_MAGNITUDE}]+年[，,]\s*还是(?:可以)?放长期",
        "短期内，还是可以长期不用",
        normalized,
    )
    normalized = re.sub(
        rf"{_ARABIC_NUMBER}\s*年(?:以上)?(?:的)?(?:长期)?"
        r"(?:都)?(?:用不到|用不上|不用|不动)",
        "长期不用",
        normalized,
    )
    normalized = re.sub(rf"{_ARABIC_NUMBER}\s*年内", "短期内", normalized)
    normalized = re.sub(rf"{_ARABIC_NUMBER}\s*年以上", "长期", normalized)
    normalized = re.sub(
        rf"(?:[{_CN_MAGNITUDE}]+|{_ARABIC_NUMBER}\s*)个月",
        lambda match: replace_duration(match, "短期内"),
        normalized,
    )
    normalized = re.sub(
        rf"(?:[{_CN_MAGNITUDE}]+|{_ARABIC_NUMBER}\s*)年",
        lambda match: replace_duration(match, "较长时间"),
        normalized,
    )

    normalized = re.sub(
        rf"(?:亏了|亏损){_CN_PERCENT_OR_FRACTION}",
        "出现明显账面亏损",
        normalized,
    )
    normalized = re.sub(
        rf"{_CN_PERCENT_OR_FRACTION}",
        "明显幅度",
        normalized,
    )
    normalized = re.sub(
        rf"（比如[^\n）]*{_ARABIC_PERCENT}[^\n）]*）",
        "（例如完全不能接受亏损、能否承受明显波动，以及亏损时会不会被迫卖出）",
        normalized,
    )
    normalized = re.sub(
        rf"(?:亏了|亏损|亏掉|回撤){_ARABIC_PERCENT}",
        "出现明显亏损",
        normalized,
    )
    normalized = re.sub(
        _ARABIC_PERCENT,
        lambda match: (
            match.group(0)
            if match.group(0) in supported_product_percentages
            else "明显幅度"
        ),
        normalized,
    )
    normalized = re.sub(
        r"跌\s*明显幅度\s*(?:就)?受不了",
        "出现明显下跌就受不了",
        normalized,
    )
    normalized = re.sub(
        r"跌\s*明显幅度\s*(?:还)?能继续持有",
        "出现明显下跌仍能继续持有",
        normalized,
    )
    normalized = re.sub(
        r"短期内账面亏损了[，,]?比如出现明显账面亏损",
        "出现明显账面亏损",
        normalized,
    )
    normalized = re.sub(
        r"(?:为了帮你[^，。；：:]{0,24}[，,])?"
        r"(?:我想|我们可以|要)?先(?:了解|确认|核对|看看|搞清|想清楚)"
        rf"[{_CN_MAGNITUDE}]+(?:个)?(?:问题|件事)[：:]",
        "如果继续细化，可以先补充：",
        normalized,
    )
    normalized = re.sub(
        rf"请(?:你)?先告诉我(?:这|以上)?[{_CN_MAGNITUDE}]+(?:点|项|件事)",
        "请先告诉我这些情况",
        normalized,
    )
    normalized = re.sub(
        r"(?:那就)?只能选波动(?:很小|较小)的货币基金、?存款这类",
        "通常应优先核对安全性和流动性更高的工具",
        normalized,
    )
    normalized = re.sub(
        r"(?:可能)?是最适合(?:您|你)?(?:现在)?优先比较的方向",
        "是当前值得优先了解和比较的方向之一",
        normalized,
    )
    normalized = re.sub(
        r"优先从([^，。；\n]{1,30})开始比较[，,]\s*收益更高",
        r"可以先从\1开始比较，重点核对风险、流动性和完整成本",
        normalized,
    )
    normalized = re.sub(
        r"(?:所以)?(?:我|我们)?需要再确认(?:几|一|二|两|三)"
        r"(?:个)?(?:问题|件事)[：:]?\s*$",
        "",
        normalized,
    ).rstrip()
    normalized = re.sub(
        r"如果继续细化，可以先补充[：:]\s*$",
        "",
        normalized,
    ).rstrip()
    normalized = re.sub(
        r"(?:但)?(?:你|您)?可以如果继续细化，可以先补充[：:]",
        "如果继续细化，可以先补充：",
        normalized,
    )
    normalized = re.sub(
        r"(?m)^(?P<marker>\s*\d+[.、]\s*)"
        r"(?P<question>[^（(\n]+[？?])"
        r"（\s*(?P=marker)(?P=question)\s*$",
        lambda match: f"{match.group('marker')}{match.group('question')}",
        normalized,
    )
    return normalized


__all__ = ["normalize_financial_advisor_answer"]
