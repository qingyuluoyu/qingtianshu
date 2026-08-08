from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from app.catalog import RESEARCH_TARGETS, normalize_symbol
from app.db import Database
from app.utils import utc_now


class EarningsQualityService:
    """Deterministic earnings trend and quality review without trade ratings."""

    METHOD = "deterministic_earnings_quality_v1"

    def __init__(self, database: Database):
        self.database = database

    def get_packet(self, symbol: str, *, persist: bool = True) -> dict[str, Any]:
        canonical = normalize_symbol(symbol)
        periods = self.database.list_financial_periods(canonical, limit=12)
        if not periods:
            return {
                "type": "earnings_quality",
                "symbol": canonical,
                "name": RESEARCH_TARGETS.get(canonical, {}).get("name") or canonical,
                "status": "unavailable",
                "generated_at": utc_now(),
                "method": self.METHOD,
                "summary": "尚未建立结构化财务期，不能进行财报质量分析。",
                "latest_report": None,
                "comparable_report": None,
                "factors": [],
                "supports": [],
                "contradictions": [],
                "review_points": ["先取得可核验的结构化财务报告期。"],
                "coverage": {"periods": 0, "available_fields": 0, "comparable": False},
                "boundary": "不使用媒体预测或估值倍数替代缺失财务事实。",
            }

        latest = periods[0]
        comparable = _find_comparable_period(latest, periods[1:])
        name = (
            RESEARCH_TARGETS.get(canonical, {}).get("name")
            or latest.get("name")
            or canonical
        )
        latest_cash_ratio = _ratio(
            latest.get("operating_cashflow"), latest.get("parent_net_profit")
        )
        comparable_cash_ratio = _ratio(
            (comparable or {}).get("operating_cashflow"),
            (comparable or {}).get("parent_net_profit"),
        )
        factors: list[dict[str, Any]] = []

        revenue_yoy = latest.get("revenue_yoy_pct")
        profit_yoy = latest.get("net_profit_yoy_pct")
        factors.append(
            _growth_factor(
                "revenue_growth",
                "营收增速",
                revenue_yoy,
                (comparable or {}).get("revenue_yoy_pct"),
            )
        )
        factors.append(
            _growth_factor(
                "profit_growth",
                "净利润增速",
                profit_yoy,
                (comparable or {}).get("net_profit_yoy_pct"),
            )
        )
        gross_margin_factor = _margin_factor(
            "gross_margin",
            "毛利率",
            latest.get("gross_margin_pct"),
            (comparable or {}).get("gross_margin_pct"),
        )
        _attach_margin_sensitivity(gross_margin_factor, latest)
        factors.append(gross_margin_factor)
        factors.append(
            _margin_factor(
                "net_margin",
                "净利率",
                latest.get("net_margin_pct"),
                (comparable or {}).get("net_margin_pct"),
            )
        )
        factors.append(
            _cashflow_factor(latest_cash_ratio, comparable_cash_ratio)
        )
        factors.append(
            _leverage_factor(
                latest.get("debt_asset_ratio_pct"),
                (comparable or {}).get("debt_asset_ratio_pct"),
            )
        )
        factors = [factor for factor in factors if factor.get("status") != "missing"]

        supports: list[str] = []
        contradictions: list[str] = []
        if _positive(revenue_yoy) and _positive(profit_yoy):
            supports.append("最新报告期营收与净利润同比均为正增长。")
        if _positive(revenue_yoy) and _negative(profit_yoy):
            contradictions.append("营收增长但净利润下降，收入扩张没有同步转化为利润。")
        if _negative(revenue_yoy) and _positive(profit_yoy):
            contradictions.append("营收下降但净利润增长，需要核对非经常性因素、成本和口径。")
        if _negative(revenue_yoy) and _negative(profit_yoy):
            contradictions.append("营收与净利润同比同时下降，增长证据整体承压。")

        gross_delta = _delta(
            latest.get("gross_margin_pct"), (comparable or {}).get("gross_margin_pct")
        )
        net_delta = _delta(
            latest.get("net_margin_pct"), (comparable or {}).get("net_margin_pct")
        )
        if gross_delta is not None and net_delta is not None:
            if gross_delta >= 1 and net_delta >= 1:
                supports.append("毛利率与净利率相对可比报告期同时改善。")
            elif gross_delta >= 1 and net_delta <= -1:
                contradictions.append("毛利率改善但净利率下降，期间费用或其他损益可能形成拖累。")
            elif gross_delta <= -1 and net_delta <= -1:
                contradictions.append("毛利率与净利率相对可比报告期同时收缩。")

        if latest_cash_ratio is not None:
            if latest_cash_ratio >= 1:
                supports.append(
                    "本期经营现金流金额高于归母净利润；这只说明本期覆盖关系，"
                    "仍需结合经营现金流同比变化、销售收现和营运资金判断现金质量。"
                )
            elif latest_cash_ratio < 0:
                contradictions.append("经营现金流与归母净利润方向相反，盈利兑现需要优先复核。")
            elif latest_cash_ratio < 0.5:
                contradictions.append("经营现金流对归母净利润覆盖低于 0.5。")
            elif latest_cash_ratio < 0.8:
                contradictions.append(
                    "经营现金流对归母净利润覆盖低于 0.8，增长与现金兑现尚未完全一致。"
                )

        debt_delta = _delta(
            latest.get("debt_asset_ratio_pct"),
            (comparable or {}).get("debt_asset_ratio_pct"),
        )
        if debt_delta is not None:
            if debt_delta <= -3:
                supports.append("资产负债率较可比报告期下降超过 3 个百分点。")
            elif debt_delta >= 3:
                contradictions.append("资产负债率较可比报告期上升超过 3 个百分点。")

        overall_label = _overall_label(
            revenue_yoy,
            profit_yoy,
            latest_cash_ratio,
            gross_delta,
            net_delta,
            contradictions,
            comparable is not None,
        )
        available_fields = sum(
            isinstance(latest.get(key), (int, float))
            for key in (
                "revenue_yoy_pct",
                "net_profit_yoy_pct",
                "gross_margin_pct",
                "net_margin_pct",
                "roe_weighted_pct",
                "debt_asset_ratio_pct",
                "operating_cashflow",
                "parent_net_profit",
            )
        )
        confidence = (
            "high"
            if comparable is not None and available_fields >= 7
            else "medium"
            if available_fields >= 5
            else "low"
        )
        review_points = _review_points(
            latest, comparable, latest_cash_ratio, contradictions
        )
        packet = {
            "type": "earnings_quality",
            "symbol": canonical,
            "name": name,
            "status": "available",
            "generated_at": utc_now(),
            "method": self.METHOD,
            "overall_label": overall_label,
            "confidence": confidence,
            "summary": _summary(name, latest, overall_label, contradictions),
            "latest_report": _public_period(latest, latest_cash_ratio),
            "comparable_report": _public_period(
                comparable, comparable_cash_ratio
            ) if comparable else None,
            "factors": factors,
            "supports": supports,
            "contradictions": contradictions,
            "review_points": review_points,
            "period_history": [
                _public_period(
                    period,
                    _ratio(
                        period.get("operating_cashflow"),
                        period.get("parent_net_profit"),
                    ),
                )
                for period in periods[:5]
            ],
            "coverage": {
                "periods": len(periods),
                "available_fields": available_fields,
                "comparable": comparable is not None,
                "comparable_basis": (
                    "上一年度同类报告期"
                    if comparable is not None
                    else "尚未找到上一年度同类报告期"
                ),
            },
            "interpretation_rules": [
                "增长比较使用各报告期已经披露的同比增速，不把累计口径误写成环比。",
                "利润率、现金流覆盖和负债率优先与上一年度同类报告期比较。",
                "财务状态只描述已披露经营证据，不生成估值结论、买卖评级或未来利润预测。",
            ],
            "boundary": (
                "财报质量分析不等于公司好坏或股票涨跌判断；"
                "仍需结合公告原文、业务结构、行业供需和会计口径复核。"
            ),
        }
        if persist:
            fingerprint = _fingerprint(packet)
            saved = self.database.save_earnings_quality_snapshot(packet, fingerprint)
            packet["snapshot_id"] = saved["id"]
            packet["snapshot_created_at"] = saved["created_at"]
            self._index_common_knowledge(packet)
        return packet

    def refresh_symbols(self, symbols: list[str]) -> dict[str, Any]:
        results = []
        for symbol in sorted({normalize_symbol(item) for item in symbols}):
            packet = self.get_packet(symbol)
            results.append(
                {
                    "symbol": symbol,
                    "status": packet["status"],
                    "report_date": (packet.get("latest_report") or {}).get(
                        "report_date"
                    ),
                    "overall_label": packet.get("overall_label"),
                }
            )
        return {
            "requested": len(results),
            "completed": sum(item["status"] == "available" for item in results),
            "results": results,
        }

    def _index_common_knowledge(self, packet: dict[str, Any]) -> None:
        symbol = packet["symbol"]
        name = packet["name"]
        source_key = f"earnings-quality:{symbol}"
        document_id = "earnings-" + hashlib.sha256(
            source_key.encode("utf-8")
        ).hexdigest()[:24]
        latest = packet.get("latest_report") or {}
        comparable = packet.get("comparable_report") or {}
        lines = [
            f"# {name}最新财报质量分析",
            "",
            f"最新报告期：{latest.get('report_date_name') or latest.get('report_date')}",
            f"财务状态：{packet.get('overall_label')}（证据置信度 {packet.get('confidence')}）",
            f"可比报告期：{comparable.get('report_date_name') or '尚未找到'}",
            "",
            packet.get("summary") or "",
            "",
            "## 支持证据",
            *[f"- {item}" for item in packet.get("supports") or ["暂无明确支持项。"]],
            "",
            "## 矛盾与风险",
            *[
                f"- {item}"
                for item in packet.get("contradictions") or ["暂无明确矛盾项。"]
            ],
            "",
            "## 下一步复核",
            *[f"- {item}" for item in packet.get("review_points") or []],
            "",
            packet["boundary"],
        ]
        self.database.upsert_knowledge_document(
            document_id=document_id,
            owner_user_id=None,
            scope="common",
            title=f"{name}最新财报质量分析",
            original_name=f"{symbol}-earnings-quality.md",
            mime_type="text/markdown",
            content="\n".join(lines),
            source_key=source_key,
        )


def _find_comparable_period(
    latest: dict[str, Any], candidates: list[dict[str, Any]]
) -> dict[str, Any] | None:
    signature = _period_signature(latest)
    if signature is None:
        return None
    latest_year = int(str(latest.get("report_date") or "0000")[:4] or 0)
    matches = [
        item
        for item in candidates
        if _period_signature(item) == signature
        and int(str(item.get("report_date") or "0000")[:4] or 0) < latest_year
    ]
    return matches[0] if matches else None


def _period_signature(period: dict[str, Any]) -> str | None:
    report_type = str(period.get("report_type") or "")
    if report_type in {"一季报", "中报", "半年报", "三季报", "年报", "10-K"}:
        return {
            "一季报": "Q1",
            "中报": "Q2",
            "半年报": "Q2",
            "三季报": "Q3",
            "年报": "FY",
            "10-K": "FY",
        }[report_type]
    name = str(period.get("report_date_name") or "").upper()
    match = re.search(r"\bQ([1-4])\b", name)
    return f"Q{match.group(1)}" if match else None


def _growth_factor(
    key: str, label: str, current: Any, comparable: Any
) -> dict[str, Any]:
    if not isinstance(current, (int, float)):
        return {"key": key, "label": label, "status": "missing"}
    change = _delta(current, comparable)
    if current > 0:
        status = "support"
    elif current < 0:
        status = "risk"
    else:
        status = "neutral"
    if change is None:
        interpretation = f"同比 {current:.2f}%，尚无同类报告期比较。"
    elif change >= 5:
        interpretation = f"同比 {current:.2f}%，较可比期加快 {change:.2f} 个百分点。"
    elif change <= -5:
        interpretation = f"同比 {current:.2f}%，较可比期放缓 {abs(change):.2f} 个百分点。"
    else:
        interpretation = f"同比 {current:.2f}%，较可比期变化 {change:.2f} 个百分点。"
    return {
        "key": key,
        "label": label,
        "status": status,
        "value_pct": round(float(current), 4),
        "comparable_pct": _round(comparable),
        "change_pp": _round(change),
        "interpretation": interpretation,
    }


def _margin_factor(
    key: str, label: str, current: Any, comparable: Any
) -> dict[str, Any]:
    if not isinstance(current, (int, float)):
        return {"key": key, "label": label, "status": "missing"}
    change = _delta(current, comparable)
    status = "support" if change is not None and change >= 1 else "risk" if change is not None and change <= -1 else "neutral"
    comparison = (
        f"较可比期{'提高' if change >= 0 else '下降'} {abs(change):.2f} 个百分点"
        if change is not None
        else "尚无同类报告期比较"
    )
    return {
        "key": key,
        "label": label,
        "status": status,
        "value_pct": round(float(current), 4),
        "comparable_pct": _round(comparable),
        "change_pp": _round(change),
        "interpretation": f"{label} {current:.2f}%，{comparison}。",
    }


def _cashflow_factor(current: float | None, comparable: float | None) -> dict[str, Any]:
    if current is None:
        return {"key": "cashflow_coverage", "label": "现金流覆盖", "status": "missing"}
    status = "support" if current >= 1 else "risk" if current < 0.5 else "mixed"
    return {
        "key": "cashflow_coverage",
        "label": "现金流覆盖",
        "status": status,
        "value_ratio": current,
        "comparable_ratio": comparable,
        "change": _round(_delta(current, comparable)),
        "interpretation": (
            f"经营现金流/归母净利润为 {current:.3f}"
            + (
                f"，可比期为 {comparable:.3f}。"
                if comparable is not None
                else "，尚无同类报告期比较。"
            )
        ),
        "interpretation_boundary": (
            "该比率只表示同一报告期经营现金流金额与归母净利润的关系；"
            "不能单独证明整体盈利质量、回款情况或现金流趋势。"
        ),
    }


def _attach_margin_sensitivity(
    factor: dict[str, Any], latest: dict[str, Any]
) -> None:
    revenue = latest.get("revenue")
    change = factor.get("change_pp")
    if not isinstance(revenue, (int, float)) or not isinstance(change, (int, float)):
        return
    factor["currency"] = latest.get("currency")
    factor["current_revenue_per_margin_point"] = round(abs(float(revenue)) / 100, 2)
    factor["current_revenue_margin_change_sensitivity"] = round(
        float(revenue) * float(change) / 100,
        2,
    )
    factor["sensitivity_boundary"] = (
        "按本期营收静态测算，仅用于量化利润率变化的规模；"
        "不是实际毛利变动归因，也不替代成本、业务结构和会计科目核对。"
    )


def _leverage_factor(current: Any, comparable: Any) -> dict[str, Any]:
    if not isinstance(current, (int, float)):
        return {"key": "leverage", "label": "资产负债率", "status": "missing"}
    change = _delta(current, comparable)
    status = "risk" if change is not None and change >= 3 else "support" if change is not None and change <= -3 else "neutral"
    return {
        "key": "leverage",
        "label": "资产负债率",
        "status": status,
        "value_pct": round(float(current), 4),
        "comparable_pct": _round(comparable),
        "change_pp": _round(change),
        "interpretation": (
            f"资产负债率 {current:.2f}%"
            + (
                f"，较可比期变化 {change:.2f} 个百分点。"
                if change is not None
                else "，尚无同类报告期比较。"
            )
        ),
    }


def _overall_label(
    revenue_yoy: Any,
    profit_yoy: Any,
    cash_ratio: float | None,
    gross_delta: float | None,
    net_delta: float | None,
    contradictions: list[str],
    has_comparable: bool,
) -> str:
    if not has_comparable:
        return "财务基线已建立"
    if len(contradictions) >= 2:
        return "盈利质量承压"
    if _positive(revenue_yoy) and _positive(profit_yoy):
        if cash_ratio is not None and cash_ratio >= 0.8 and not (
            (gross_delta is not None and gross_delta <= -1)
            or (net_delta is not None and net_delta <= -1)
        ):
            return "增长与盈利兑现较一致"
        return "增长为正但质量仍需复核"
    if _negative(revenue_yoy) or _negative(profit_yoy):
        return "增长与盈利分化"
    return "财务证据分化"


def _review_points(
    latest: dict[str, Any],
    comparable: dict[str, Any] | None,
    cash_ratio: float | None,
    contradictions: list[str],
) -> list[str]:
    points = []
    if contradictions:
        points.append("逐项核对利润变化来自主营、费用、资产减值还是非经常性损益。")
    if cash_ratio is None or cash_ratio < 0.8:
        points.append("核对经营现金流、应收账款、存货和合同负债变化，解释利润兑现差异。")
    if comparable is None:
        points.append("补齐上一年度同类报告期，避免把累计口径误解为环比变化。")
    if isinstance(latest.get("debt_asset_ratio_pct"), (int, float)):
        points.append("结合有息负债、货币资金和偿债期限复核资产负债率变化。")
    points.append("阅读公司公告或监管文件原文，确认结构化字段和会计口径。")
    return list(dict.fromkeys(points))[:4]


def _public_period(
    period: dict[str, Any] | None, cash_ratio: float | None
) -> dict[str, Any] | None:
    if period is None:
        return None
    return {
        key: period.get(key)
        for key in (
            "report_date",
            "report_type",
            "report_date_name",
            "notice_date",
            "currency",
            "revenue",
            "revenue_yoy_pct",
            "parent_net_profit",
            "net_profit_yoy_pct",
            "roe_weighted_pct",
            "gross_margin_pct",
            "net_margin_pct",
            "debt_asset_ratio_pct",
            "operating_cashflow",
            "total_assets",
            "total_liabilities",
            "total_equity",
            "period_basis",
        )
    } | {"operating_cashflow_to_net_profit": cash_ratio}


def _summary(
    name: str,
    latest: dict[str, Any],
    label: str,
    contradictions: list[str],
) -> str:
    base = (
        f"{name}最新财报为{latest.get('report_date_name') or latest.get('report_date')}，"
        f"确定性财务状态为“{label}”。"
    )
    if contradictions:
        return base + "主要需要复核：" + "；".join(contradictions[:2])
    return base + "当前未发现两项以上相互冲突的关键财务证据。"


def _fingerprint(packet: dict[str, Any]) -> str:
    stable = {
        key: packet.get(key)
        for key in (
            "symbol",
            "method",
            "overall_label",
            "confidence",
            "latest_report",
            "comparable_report",
            "factors",
            "supports",
            "contradictions",
            "review_points",
        )
    }
    return hashlib.sha256(
        json.dumps(stable, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _ratio(numerator: Any, denominator: Any) -> float | None:
    if not isinstance(numerator, (int, float)) or not isinstance(
        denominator, (int, float)
    ) or denominator == 0:
        return None
    return round(float(numerator) / float(denominator), 4)


def _delta(current: Any, previous: Any) -> float | None:
    if not isinstance(current, (int, float)) or not isinstance(
        previous, (int, float)
    ):
        return None
    return float(current) - float(previous)


def _round(value: Any, digits: int = 4) -> float | None:
    return round(float(value), digits) if isinstance(value, (int, float)) else None


def _positive(value: Any) -> bool:
    return isinstance(value, (int, float)) and value > 0


def _negative(value: Any) -> bool:
    return isinstance(value, (int, float)) and value < 0
