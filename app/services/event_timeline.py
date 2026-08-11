from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any

from app.catalog import RESEARCH_TARGETS, normalize_symbol
from app.db import Database
from app.services.china_info import ChinaInformationService
from app.utils import utc_now


_EVENT_RULES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "financial_reporting",
        "财报与业绩",
        (
            "年度报告",
            "半年度报告",
            "季度报告",
            "一季度报告",
            "三季度报告",
            "业绩预告",
            "业绩快报",
            "业绩说明会",
            "earnings",
            "financial results",
            "10-q",
            "10-k",
        ),
    ),
    (
        "contract_order",
        "订单与合同",
        ("中标", "中选", "签订合同", "重大合同", "订单", "框架协议"),
    ),
    (
        "capital_return",
        "回购与股东回报",
        ("回购", "增持", "分红", "现金红利", "权益分派", "股息"),
    ),
    (
        "shareholder_change",
        "股东与股权变化",
        (
            "减持",
            "解禁",
            "股东权益变动",
            "股权变动",
            "股份变动",
            "股东总数",
            "质押",
            "股权激励",
        ),
    ),
    (
        "regulatory_legal",
        "监管与诉讼",
        (
            "立案",
            "处罚",
            "调查",
            "问询函",
            "监管函",
            "诉讼",
            "仲裁",
            "风险提示",
            "investigation",
            "lawsuit",
            "antitrust",
            "regulatory",
        ),
    ),
    (
        "financing_mna",
        "融资与并购重组",
        (
            "定向增发",
            "定增",
            "可转债",
            "可转换债券",
            "转股价格调整",
            "收购",
            "并购",
            "重组",
            "出售资产",
            "acquisition",
            "merger",
        ),
    ),
    (
        "operations_product",
        "经营、产品与产能",
        (
            "产品发布",
            "新产品",
            "发布",
            "亮相",
            "获批",
            "投产",
            "产能",
            "项目建设",
            "战略合作",
            "合作协议",
            "调价",
            "launch",
        ),
    ),
    (
        "governance",
        "治理与管理层",
        (
            "董事",
            "监事",
            "高级管理人员",
            "总经理",
            "辞职",
            "聘任",
            "任命",
            "chief executive",
        ),
    ),
)

_SUPPORTIVE_TERMS = (
    "中标",
    "中选",
    "回购",
    "增持",
    "预增",
    "扭亏",
    "分红",
    "获批",
    "签订合同",
    "利润增长",
)
_ADVERSE_TERMS = (
    "减持",
    "预亏",
    "亏损",
    "处罚",
    "立案",
    "调查",
    "诉讼",
    "仲裁",
    "风险提示",
    "终止",
    "下修",
    "违约",
)
_OFFICIAL_CATEGORIES = {"announcement", "regulatory_filing"}
_MEDIA_CATEGORIES = {"news", "global_news"}


class EventTimelineService:
    """Turn stored disclosures and news into a deterministic event timeline."""

    METHOD = "deterministic_event_timeline_v1"

    def __init__(
        self,
        database: Database,
        china_info: ChinaInformationService | None = None,
    ) -> None:
        self.database = database
        self.china_info = china_info

    def refresh_symbol(
        self, symbol: str, *, refresh_sources: bool = True
    ) -> dict[str, Any]:
        canonical = normalize_symbol(symbol)
        if (
            refresh_sources
            and canonical.endswith((".SS", ".SZ"))
            and self.china_info is not None
        ):
            try:
                self.china_info.get_packet(canonical, refresh_max_age_seconds=300)
            except Exception:
                # Existing persisted disclosures remain useful even when a live
                # refresh is temporarily unavailable.
                pass
        packet = self._build_packet(canonical)
        fingerprint = _fingerprint(packet)
        saved = self.database.save_event_timeline_snapshot(packet, fingerprint)
        packet["snapshot_id"] = saved["id"]
        packet["snapshot_created_at"] = saved["created_at"]
        self._index_common_knowledge(packet)
        return packet

    def refresh_symbols(
        self, symbols: list[str], *, refresh_sources: bool = False
    ) -> dict[str, Any]:
        canonical_symbols = sorted({normalize_symbol(symbol) for symbol in symbols})
        results = []
        for symbol in canonical_symbols:
            try:
                packet = self.refresh_symbol(symbol, refresh_sources=refresh_sources)
                results.append(
                    {
                        "symbol": symbol,
                        "status": "ok",
                        "events": len(packet.get("events") or []),
                        "as_of_date": packet.get("as_of_date"),
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
        refresh_sources: bool = True,
    ) -> dict[str, Any]:
        return self.refresh_symbol(symbol, refresh_sources=refresh_sources)

    def _build_packet(self, symbol: str) -> dict[str, Any]:
        items = self.database.list_news(
            symbol,
            limit=160,
            categories=("announcement", "news", "regulatory_filing", "global_news"),
        )
        events: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in items:
            title = re.sub(r"\s+", " ", str(item.get("title") or "")).strip()
            if not title:
                continue
            event_type, event_label = _classify_event(title)
            category = str(item.get("category") or "")
            if event_type == "other" and category not in _OFFICIAL_CATEGORIES:
                continue
            identity = _normalized_title(title)
            if identity in seen:
                continue
            seen.add(identity)
            relevance = _research_relevance(title)
            evidence_level, evidence_label, event_status = _evidence_level(category)
            events.append(
                {
                    "event_type": event_type,
                    "event_label": event_label,
                    "title": title,
                    "published_at": item.get("published_at"),
                    "event_date": str(item.get("published_at") or "")[:10] or None,
                    "category": category,
                    "evidence_level": evidence_level,
                    "evidence_label": evidence_label,
                    "event_status": event_status,
                    "research_relevance": relevance,
                    "research_relevance_label": {
                        "supportive": "可能的支持事件",
                        "adverse": "需优先复核的风险事件",
                        "mixed": "双向事件",
                        "neutral": "中性事件",
                    }[relevance],
                    "source": item.get("source"),
                    "url": item.get("url"),
                    "fetched_at": item.get("fetched_at"),
                }
            )
        events.sort(
            key=lambda item: (
                str(item.get("event_date") or ""),
                item.get("evidence_level")
                in {"official_disclosure", "regulatory_filing"},
                str(item.get("published_at") or ""),
            ),
            reverse=True,
        )
        deduplicated: list[dict[str, Any]] = []
        for event in events:
            if any(_same_event(event, existing) for existing in deduplicated):
                continue
            deduplicated.append(event)
        events = deduplicated[:40]
        type_counts = Counter(item["event_type"] for item in events)
        themes = [
            {
                "event_type": event_type,
                "label": _event_label(event_type),
                "count": count,
            }
            for event_type, count in type_counts.most_common()
        ]
        official = [
            item
            for item in events
            if item["evidence_level"] in {"official_disclosure", "regulatory_filing"}
        ]
        media = [item for item in events if item["evidence_level"] == "media_report"]
        adverse = [item for item in events if item["research_relevance"] == "adverse"]
        supportive = [
            item for item in events if item["research_relevance"] == "supportive"
        ]
        as_of_date = next(
            (item.get("event_date") for item in events if item.get("event_date")),
            datetime.now(timezone.utc).date().isoformat(),
        )
        name = RESEARCH_TARGETS.get(symbol, {}).get("name") or symbol
        return {
            "type": "event_timeline",
            "symbol": symbol,
            "name": name,
            "status": "available" if events else "insufficient",
            "generated_at": utc_now(),
            "as_of_date": as_of_date,
            "method": self.METHOD,
            "events": events,
            "themes": themes,
            "recent_official_events": official[:12],
            "risk_events": adverse[:8],
            "supportive_events": supportive[:8],
            "coverage": {
                "stored_items_scanned": len(items),
                "events_returned": len(events),
                "official_events": len(official),
                "media_events": len(media),
                "risk_events": len(adverse),
                "supportive_events": len(supportive),
                "event_types": len(type_counts),
            },
            "review_points": [
                "优先阅读最新官方公告或监管文件原文，不只依赖标题。",
                "媒体报道只作定位线索；没有官方披露时不得写成已确认事件。",
                "把新事件与用户关注理由、财务期和价格变化交叉核验，不用关键词直接推断股价影响。",
            ],
            "boundary": (
                "事件分类和研究相关性由确定性关键词规则生成，用于排列复核顺序；"
                "不估算事件发生概率、股价影响、目标价或交易方向。"
                "公告标题是官方披露索引，具体结论仍需阅读原文。"
            ),
        }

    def _index_common_knowledge(self, packet: dict[str, Any]) -> None:
        source_key = f"event-timeline:{packet['symbol']}"
        document_id = (
            "event-timeline-"
            + hashlib.sha256(source_key.encode("utf-8")).hexdigest()[:24]
        )
        event_lines = (
            "\n".join(
                f"- {item.get('event_date') or '日期待确认'}｜"
                f"{item.get('evidence_label')}｜{item.get('event_label')}｜"
                f"{item.get('research_relevance_label')}｜{item.get('title')}"
                for item in (packet.get("events") or [])[:24]
            )
            or "- 当前未形成可用的事件脉络。"
        )
        theme_lines = (
            "\n".join(
                f"- {item.get('label')}：{item.get('count')} 条"
                for item in packet.get("themes") or []
            )
            or "- 尚未形成可分类事件。"
        )
        content = (
            f"# {packet['name']}重要事件脉络\n\n"
            f"证券代码：{packet['symbol']}\n\n"
            f"数据截至：{packet.get('as_of_date')}\n\n"
            f"## 事件主题\n\n{theme_lines}\n\n"
            f"## 最新事件\n\n{event_lines}\n\n"
            f"## 下一步复核\n\n"
            + "\n".join(f"- {item}" for item in packet.get("review_points") or [])
            + f"\n\n## 证据边界\n\n{packet.get('boundary')}\n"
        )
        self.database.upsert_knowledge_document(
            document_id=document_id,
            owner_user_id=None,
            scope="common",
            title=f"{packet['name']}重要事件脉络",
            original_name=f"{packet['symbol']}-event-timeline.md",
            mime_type="text/markdown",
            content=content,
            source_key=source_key,
        )


def _classify_event(title: str) -> tuple[str, str]:
    folded = title.casefold()
    for event_type, label, terms in _EVENT_RULES:
        if any(term.casefold() in folded for term in terms):
            return event_type, label
    return "other", "其他官方披露"


def _event_label(event_type: str) -> str:
    return next(
        (label for key, label, _ in _EVENT_RULES if key == event_type),
        "其他官方披露",
    )


def _research_relevance(title: str) -> str:
    supportive = any(term in title for term in _SUPPORTIVE_TERMS)
    adverse = any(term in title for term in _ADVERSE_TERMS)
    if supportive and adverse:
        return "mixed"
    if adverse:
        return "adverse"
    if supportive:
        return "supportive"
    return "neutral"


def _evidence_level(category: str) -> tuple[str, str, str]:
    if category == "announcement":
        return "official_disclosure", "公司公告", "confirmed_disclosure"
    if category == "regulatory_filing":
        return "regulatory_filing", "监管文件", "confirmed_disclosure"
    if category in _MEDIA_CATEGORIES:
        return "media_report", "媒体报道", "reported_clue"
    return "unknown", "证据类型待确认", "reported_clue"


def _normalized_title(title: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", title.casefold())


def _same_event(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if left.get("event_date") != right.get("event_date") or left.get(
        "event_type"
    ) != right.get("event_type"):
        return False
    left_title = str(left.get("title") or "")
    right_title = str(right.get("title") or "")
    if _normalized_title(left_title) == _normalized_title(right_title):
        return True
    markers = (
        "回购",
        "分红",
        "股息",
        "增持",
        "减持",
        "股东总数",
        "股份变动",
        "合作协议",
        "转股价格",
        "可转换债券",
        "业绩预告",
        "业绩快报",
        "处罚",
        "立案",
        "调查",
        "诉讼",
        "仲裁",
    )
    common_markers = {
        marker for marker in markers if marker in left_title and marker in right_title
    }
    if not common_markers:
        return False
    left_official = left.get("evidence_level") in {
        "official_disclosure",
        "regulatory_filing",
    }
    right_official = right.get("evidence_level") in {
        "official_disclosure",
        "regulatory_filing",
    }
    if left_official != right_official:
        return True
    left_numbers = set(re.findall(r"\d+(?:\.\d+)?", left_title))
    right_numbers = set(re.findall(r"\d+(?:\.\d+)?", right_title))
    return bool(left_numbers & right_numbers)


def _fingerprint(packet: dict[str, Any]) -> str:
    stable = [
        {
            "event_type": item.get("event_type"),
            "title": item.get("title"),
            "published_at": item.get("published_at"),
            "evidence_level": item.get("evidence_level"),
            "research_relevance": item.get("research_relevance"),
        }
        for item in packet.get("events") or []
    ]
    return hashlib.sha256(
        json.dumps(stable, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
