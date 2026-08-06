from __future__ import annotations

from collections import defaultdict
from datetime import date
import hashlib
import json
from typing import Any

from app.catalog import RESEARCH_TARGETS, normalize_symbol
from app.db import Database
from app.providers.business_structure import AShareBusinessStructureProvider
from app.utils import utc_now


_DIMENSION_LABELS = {
    "product": "按产品",
    "region": "按地区",
    "industry": "按行业",
}


class BusinessStructureAnalysisService:
    METHOD = "deterministic_business_structure_v1"

    def __init__(
        self, database: Database, provider: AShareBusinessStructureProvider
    ):
        self.database = database
        self.provider = provider

    def refresh_symbol(self, symbol: str) -> dict[str, Any]:
        canonical = normalize_symbol(symbol)
        result = self.provider.fetch(canonical)
        saved = self.database.upsert_business_segment_rows(result["rows"])
        packet = self.get_packet(canonical, refresh_if_missing=False, persist=True)
        return {
            "symbol": canonical,
            "rows_saved": saved,
            "status": packet["status"],
            "anchor_report_date": packet.get("anchor_report_date"),
            "dimensions": len(packet.get("dimensions") or []),
            "refreshed_at": utc_now(),
        }

    def refresh_symbols(self, symbols: list[str]) -> dict[str, Any]:
        canonical_symbols = sorted(
            {
                normalize_symbol(symbol)
                for symbol in symbols
                if normalize_symbol(symbol).endswith((".SS", ".SZ"))
            }
        )
        results = []
        for symbol in canonical_symbols:
            try:
                refreshed = self.refresh_symbol(symbol)
                results.append(
                    {
                        **refreshed,
                        "analysis_status": refreshed.get("status"),
                        "status": "ok",
                    }
                )
            except Exception as exc:
                results.append(
                    {
                        "symbol": symbol,
                        "status": "failed",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
        return {
            "requested": len(canonical_symbols),
            "completed": sum(item["status"] == "ok" for item in results),
            "results": results,
        }

    def get_packet(
        self,
        symbol: str,
        *,
        refresh_if_missing: bool = True,
        persist: bool = True,
    ) -> dict[str, Any]:
        canonical = normalize_symbol(symbol)
        if not canonical.endswith((".SS", ".SZ")):
            raise ValueError("主营业务结构分析只支持 A 股证券")
        rows = self.database.list_business_segment_rows(canonical)
        if not rows and refresh_if_missing:
            fetched = self.provider.fetch(canonical)
            self.database.upsert_business_segment_rows(fetched["rows"])
            rows = self.database.list_business_segment_rows(canonical)
        if not rows:
            return self._unavailable(canonical)

        dimensions = []
        for classification in ("product", "region", "industry"):
            dimension_rows = [
                item for item in rows if item["classification"] == classification
            ]
            if dimension_rows:
                dimensions.append(_build_dimension(classification, dimension_rows))
        anchor_report_date = max(item["report_date"] for item in rows)
        key_changes = _key_changes(dimensions)
        source_urls = sorted(
            {
                str(item.get("source_url") or "").strip()
                for item in rows
                if str(item.get("source_url") or "").strip()
            }
        )
        source_names = sorted(
            {
                str(item.get("source") or "").strip()
                for item in rows
                if str(item.get("source") or "").strip()
            }
        )
        latest_fetched_at = max(
            (
                str(item.get("fetched_at") or "")
                for item in rows
                if item.get("fetched_at")
            ),
            default=None,
        )
        product = next(
            (item for item in dimensions if item["classification"] == "product"),
            None,
        )
        top_product = ((product or {}).get("segments") or [{}])[0]
        summary = (
            f"最新主营构成截至 {anchor_report_date}。"
            + (
                f"最大产品/业务为{top_product.get('item_name')}，"
                f"收入占比 {_pct(top_product.get('revenue_share_pct'))}。"
                if top_product.get("item_name")
                else ""
            )
            + "分析同时保留产品、地区、行业的同口径历史变化和披露缺口。"
        )
        packet = {
            "type": "business_structure",
            "symbol": canonical,
            "name": RESEARCH_TARGETS.get(canonical, {}).get("name") or canonical,
            "status": "available",
            "generated_at": utc_now(),
            "method": self.METHOD,
            "anchor_report_date": anchor_report_date,
            "latest_fetched_at": latest_fetched_at,
            "sources": [
                {
                    "source": ", ".join(source_names)
                    or "company_business_composition",
                    "source_url": source_url,
                }
                for source_url in source_urls
            ],
            "summary": summary,
            "dimensions": dimensions,
            "key_changes": key_changes,
            "coverage_limits": _coverage_limits(dimensions),
            "review_points": [
                "核对最新年报或中报中产品分类口径是否发生重命名或合并。",
                "把收入占比变化与同口径毛利率变化交叉验证，避免只看规模不看盈利质量。",
                "季度利润变化只能参考最近年报或中报的业务底盘，不能直接当作当季归因。",
            ],
            "coverage": {
                "rows": len(rows),
                "report_periods": len({item["report_date"] for item in rows}),
                "dimensions": len(dimensions),
                "latest_report_date": anchor_report_date,
            },
            "boundary": (
                "主营构成通常按年报或中报累计口径披露；收入占比、毛利率和分部变化"
                "只能说明业务结构事实，不能直接证明季度利润变化的唯一原因，"
                "也不构成收入预测、估值结论或交易指令。"
            ),
        }
        if persist:
            fingerprint = _fingerprint(packet)
            saved = self.database.save_business_structure_snapshot(packet, fingerprint)
            packet["snapshot_id"] = saved["id"]
            packet["snapshot_created_at"] = saved["created_at"]
            self._index_common_knowledge(packet)
        return packet

    def _index_common_knowledge(self, packet: dict[str, Any]) -> None:
        source_key = f"business-structure:{packet['symbol']}"
        document_id = "business-" + hashlib.sha256(
            source_key.encode("utf-8")
        ).hexdigest()[:24]
        sections = []
        for dimension in packet.get("dimensions") or []:
            lines = []
            for item in dimension.get("segments") or []:
                line = (
                    f"- {item.get('item_name')}：收入占比 "
                    f"{_pct(item.get('revenue_share_pct'))}，"
                    f"收入 {_money(item.get('revenue'))}"
                )
                if item.get("gross_margin_pct") is not None:
                    line += f"，毛利率 {_pct(item.get('gross_margin_pct'))}"
                if item.get("revenue_share_change_pp") is not None:
                    line += (
                        f"，较同类可比期占比变化 "
                        f"{_signed(item.get('revenue_share_change_pp'))} 个百分点"
                    )
                lines.append(line)
            sections.append(
                f"## {dimension.get('label')}\n\n"
                f"报告期：{dimension.get('current_report_date')}；"
                f"可比期：{dimension.get('comparable_report_date') or '无'}\n\n"
                + "\n".join(lines[:12])
            )
            margin_reference = dimension.get("margin_reference") or {}
            if margin_reference:
                reference_lines = []
                for item in margin_reference.get("segments") or []:
                    if item.get("gross_margin_pct") is None:
                        continue
                    line = (
                        f"- {item.get('item_name')}：毛利率 "
                        f"{_pct(item.get('gross_margin_pct'))}"
                    )
                    if item.get("gross_margin_change_pp") is not None:
                        line += (
                            "，较同类可比期变化 "
                            f"{_signed(item.get('gross_margin_change_pp'))} 个百分点"
                        )
                    reference_lines.append(line)
                if reference_lines:
                    sections.append(
                        f"### {dimension.get('label')}毛利率独立参考期\n\n"
                        f"参考期：{margin_reference.get('current_report_date')}；"
                        f"可比期：{margin_reference.get('comparable_report_date') or '无'}\n\n"
                        + "\n".join(reference_lines[:12])
                        + f"\n\n{margin_reference.get('boundary')}"
                    )
        changes = "\n".join(
            f"- {item.get('statement')}" for item in packet.get("key_changes") or []
        ) or "- 尚未形成同口径变化结论。"
        limits = "\n".join(
            f"- {item.get('label')}：{item.get('boundary')} 下一证据：{item.get('next_evidence')}"
            for item in packet.get("coverage_limits") or []
        ) or "- 当前未记录额外披露边界。"
        content = (
            f"# {packet['name']}主营业务结构分析\n\n"
            f"{packet.get('summary')}\n\n"
            + "\n\n".join(sections)
            + f"\n\n## 关键变化\n\n{changes}\n\n"
            f"## 仍待补证的研究维度\n\n{limits}\n\n"
            f"## 证据边界\n\n{packet.get('boundary')}\n\n"
            "## 数据来源\n\n"
            + "\n".join(
                f"- {item.get('source')}：{item.get('source_url')}"
                for item in packet.get("sources") or []
            )
        )
        self.database.upsert_knowledge_document(
            document_id=document_id,
            owner_user_id=None,
            scope="common",
            title=f"{packet['name']}主营业务结构分析",
            original_name=f"{packet['symbol']}-business-structure.md",
            mime_type="text/markdown",
            content=content,
            source_key=source_key,
        )

    def _unavailable(self, symbol: str) -> dict[str, Any]:
        return {
            "type": "business_structure",
            "symbol": symbol,
            "name": RESEARCH_TARGETS.get(symbol, {}).get("name") or symbol,
            "status": "insufficient",
            "generated_at": utc_now(),
            "method": self.METHOD,
            "anchor_report_date": None,
            "summary": "尚未取得可核验的主营业务构成数据。",
            "dimensions": [],
            "key_changes": [],
            "review_points": ["先取得公司年报或中报披露的主营构成明细。"],
            "coverage": {"rows": 0, "report_periods": 0, "dimensions": 0},
            "boundary": "缺少分部数据时，不根据公司名称或行业常识补写业务占比。",
        }


def _build_dimension(
    classification: str, rows: list[dict[str, Any]]
) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in rows:
        grouped[item["report_date"]].append(item)
    periods = sorted(grouped, reverse=True)
    current_date = periods[0]
    comparable_date = _comparable_date(current_date, periods[1:])
    segments = _compare_rows(
        grouped[current_date], grouped.get(comparable_date, [])
    )
    margin_reference = None
    if _margin_coverage(grouped[current_date]) < 0.5:
        margin_date = next(
            (
                period
                for period in periods
                if _margin_coverage(grouped[period]) >= 0.5
            ),
            None,
        )
        if margin_date and margin_date != current_date:
            margin_comparable = _comparable_date(
                margin_date, [item for item in periods if item < margin_date]
            )
            margin_reference = {
                "current_report_date": margin_date,
                "comparable_report_date": margin_comparable,
                "report_basis": _report_basis(margin_date),
                "segments": _compare_rows(
                    grouped[margin_date], grouped.get(margin_comparable, [])
                ),
                "boundary": "该毛利率参考期与最新收入构成期不同，不能混写为同一报告期。",
            }
    return {
        "classification": classification,
        "label": _DIMENSION_LABELS[classification],
        "current_report_date": current_date,
        "comparable_report_date": comparable_date,
        "report_basis": _report_basis(current_date),
        "segments": segments,
        "concentration": _concentration(segments),
        "margin_coverage": {
            "available": sum(
                item.get("gross_margin_pct") is not None for item in segments
            ),
            "total": len(segments),
        },
        "margin_reference": margin_reference,
    }


def _compare_rows(
    current_rows: list[dict[str, Any]], previous_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    previous = {_comparison_key(item["item_name"]): item for item in previous_rows}
    result = []
    for item in current_rows:
        prior = previous.get(_comparison_key(item["item_name"]))
        result.append(
            {
                "item_name": item["item_name"],
                "revenue": item.get("revenue"),
                "revenue_share_pct": item.get("revenue_share_pct"),
                "cost": item.get("cost"),
                "gross_profit": item.get("gross_profit"),
                "gross_profit_share_pct": item.get("gross_profit_share_pct"),
                "gross_margin_pct": item.get("gross_margin_pct"),
                "comparison_status": "matched" if prior else "new_or_renamed",
                "comparable_revenue": (prior or {}).get("revenue"),
                "comparable_revenue_share_pct": (prior or {}).get(
                    "revenue_share_pct"
                ),
                "comparable_gross_margin_pct": (prior or {}).get(
                    "gross_margin_pct"
                ),
                "revenue_change": _difference(
                    item.get("revenue"), (prior or {}).get("revenue")
                ),
                "revenue_growth_pct": _pct_change(
                    item.get("revenue"), (prior or {}).get("revenue")
                ),
                "revenue_share_change_pp": _difference(
                    item.get("revenue_share_pct"),
                    (prior or {}).get("revenue_share_pct"),
                ),
                "gross_profit_change": _difference(
                    item.get("gross_profit"), (prior or {}).get("gross_profit")
                ),
                "gross_margin_change_pp": _difference(
                    item.get("gross_margin_pct"),
                    (prior or {}).get("gross_margin_pct"),
                ),
            }
        )
    result.sort(
        key=lambda item: (
            item.get("revenue_share_pct") is not None,
            item.get("revenue_share_pct") or -1,
            item.get("revenue") or -1,
        ),
        reverse=True,
    )
    return result


def _key_changes(dimensions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    changes = []
    for dimension in dimensions:
        label = dimension["label"]
        concentration = dimension.get("concentration") or {}
        if concentration.get("top1_revenue_share_pct") is not None:
            changes.append(
                {
                    "key": f"{dimension['classification']}_concentration",
                    "dimension": dimension["classification"],
                    "kind": "concentration",
                    "statement": (
                        f"{label}第一大项目{concentration.get('top1_item')}收入占比 "
                        f"{_pct(concentration.get('top1_revenue_share_pct'))}，"
                        f"前三项合计 {_pct(concentration.get('top3_revenue_share_pct'))}。"
                    ),
                }
            )
        matched = [
            item
            for item in dimension.get("segments") or []
            if item.get("comparison_status") == "matched"
        ]
        share_moves = sorted(
            (
                item
                for item in matched
                if item.get("revenue_share_change_pp") is not None
            ),
            key=lambda item: abs(item["revenue_share_change_pp"]),
            reverse=True,
        )
        for item in share_moves[:2]:
            changes.append(
                {
                    "key": f"{dimension['classification']}_share_{item['item_name']}",
                    "dimension": dimension["classification"],
                    "kind": "revenue_share_change",
                    "statement": (
                        f"{label}{item['item_name']}收入占比由 "
                        f"{_pct(item.get('comparable_revenue_share_pct'))}变为 "
                        f"{_pct(item.get('revenue_share_pct'))}，变化 "
                        f"{_signed(item.get('revenue_share_change_pp'))} 个百分点。"
                    ),
                }
            )
        margin_rows = matched
        margin_source = dimension
        if not any(item.get("gross_margin_change_pp") is not None for item in margin_rows):
            margin_source = dimension.get("margin_reference") or {}
            margin_rows = margin_source.get("segments") or []
        margin_moves = sorted(
            (
                item
                for item in margin_rows
                if item.get("gross_margin_change_pp") is not None
            ),
            key=lambda item: abs(item["gross_margin_change_pp"]),
            reverse=True,
        )
        for item in margin_moves[:2]:
            margin_report_date = margin_source.get("current_report_date")
            period_prefix = (
                f"{margin_report_date} 毛利率参考期内，"
                if margin_source is not dimension and margin_report_date
                else ""
            )
            changes.append(
                {
                    "key": f"{dimension['classification']}_margin_{item['item_name']}",
                    "dimension": dimension["classification"],
                    "kind": "gross_margin_change",
                    "report_date": margin_source.get("current_report_date"),
                    "statement": (
                        f"{period_prefix}{label}{item['item_name']}毛利率由 "
                        f"{_pct(item.get('comparable_gross_margin_pct'))}变为 "
                        f"{_pct(item.get('gross_margin_pct'))}，变化 "
                        f"{_signed(item.get('gross_margin_change_pp'))} 个百分点。"
                    ),
                }
            )
    return changes[:12]


def _coverage_limits(dimensions: list[dict[str, Any]]) -> list[dict[str, str]]:
    available = {item.get("classification") for item in dimensions}
    limits = []
    if "region" in available:
        limits.append(
            {
                "key": "regional_product_breakdown",
                "label": "地区内产品与客户结构",
                "status": "not_disclosed_in_current_packet",
                "boundary": (
                    "当前地区分部只确认各地区收入和毛利，不能继续拆出地区内产品、"
                    "客户或订单构成。"
                ),
                "next_evidence": "年报分部附注、重大合同公告或公司正式经营说明。",
            }
        )
    limits.extend(
        [
            {
                "key": "order_backlog",
                "label": "订单与在手订单",
                "status": "not_disclosed_in_current_packet",
                "boundary": "主营收入构成不等于新增订单、在手订单或未来收入。",
                "next_evidence": "公司公告、业绩说明会记录或正式订单披露。",
            },
            {
                "key": "external_policy_exposure",
                "label": "地缘、出口管制与区域政策影响",
                "status": "requires_event_evidence",
                "boundary": "地区收入变化不能单独证明地缘或出口管制影响。",
                "next_evidence": "公司公告、监管文件和多源事件证据。",
            },
        ]
    )
    return limits


def _concentration(segments: list[dict[str, Any]]) -> dict[str, Any]:
    values = [
        item
        for item in segments
        if isinstance(item.get("revenue_share_pct"), (int, float))
    ]
    return {
        "top1_item": values[0]["item_name"] if values else None,
        "top1_revenue_share_pct": values[0]["revenue_share_pct"] if values else None,
        "top3_revenue_share_pct": round(
            sum(item["revenue_share_pct"] for item in values[:3]), 6
        ) if values else None,
    }


def _margin_coverage(rows: list[dict[str, Any]]) -> float:
    if not rows:
        return 0.0
    return sum(item.get("gross_margin_pct") is not None for item in rows) / len(rows)


def _comparable_date(current: str, candidates: list[str]) -> str | None:
    try:
        current_date = date.fromisoformat(current)
    except ValueError:
        return None
    expected = current_date.replace(year=current_date.year - 1).isoformat()
    return expected if expected in candidates else None


def _report_basis(report_date: str) -> str:
    if report_date.endswith("-03-31"):
        return "first_quarter_cumulative"
    if report_date.endswith("-06-30"):
        return "half_year_cumulative"
    if report_date.endswith("-09-30"):
        return "third_quarter_cumulative"
    return "annual"


def _comparison_key(item_name: str) -> str:
    return (
        str(item_name)
        .strip()
        .casefold()
        .replace("（", "(")
        .replace("）", ")")
        .replace("不包括", "不含")
        .replace(" ", "")
    )


def _difference(current: Any, previous: Any) -> float | None:
    if not isinstance(current, (int, float)) or not isinstance(previous, (int, float)):
        return None
    return round(float(current) - float(previous), 6)


def _pct_change(current: Any, previous: Any) -> float | None:
    if (
        not isinstance(current, (int, float))
        or not isinstance(previous, (int, float))
        or previous == 0
    ):
        return None
    return round((float(current) / float(previous) - 1.0) * 100.0, 6)


def _fingerprint(packet: dict[str, Any]) -> str:
    stable = {
        key: packet.get(key)
        for key in (
            "symbol",
            "method",
            "anchor_report_date",
            "dimensions",
            "key_changes",
            "coverage_limits",
            "coverage",
        )
    }
    return hashlib.sha256(
        json.dumps(stable, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _pct(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "—"
    number = f"{float(value):.3f}".rstrip("0").rstrip(".")
    return number + "%"


def _signed(value: Any) -> str:
    return "—" if not isinstance(value, (int, float)) else f"{float(value):+.3f}".rstrip("0").rstrip(".")


def _money(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "—"
    number = f"{float(value) / 100_000_000:.3f}".rstrip("0").rstrip(".")
    return number + " 亿元"
