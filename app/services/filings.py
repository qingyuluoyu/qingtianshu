from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from app.catalog import RESEARCH_TARGETS, normalize_symbol
from app.db import Database
from app.providers.filings import AShareFilingProvider
from app.utils import utc_now


_EXPLICIT_CAUSE_RE = re.compile(
    r"(?:主要因|主要系|主要由于|原因(?:分析)?|由于|受[^。；]{0,36}影响|"
    r"导致|系本期|因本期|较上年同期[^。；]{0,24}(?:增加|减少|下降|上升))"
)
_THEMES: tuple[dict[str, Any], ...] = (
    {
        "key": "gross_margin_cost",
        "label": "毛利率与营业成本",
        "keywords": ("毛利率", "营业成本", "毛利", "产品结构", "价格变化"),
    },
    {
        "key": "financial_expense_fx_interest",
        "label": "财务费用、汇兑与利息",
        "keywords": ("财务费用", "汇兑", "利息收入", "利息支出"),
    },
    {
        "key": "inventory",
        "label": "存货、备货与跌价",
        "keywords": ("存货", "备货", "跌价准备"),
    },
    {
        "key": "receivables_collection",
        "label": "应收账款与回款",
        "keywords": ("应收账款", "回款", "销售商品、提供劳务收到的现金"),
    },
    {
        "key": "payables_payment",
        "label": "应付账款与付款",
        "keywords": ("应付账款", "采购付款", "支付给供应商"),
    },
    {
        "key": "operating_cashflow",
        "label": "经营现金流与销售收现",
        "keywords": (
            "经营活动产生的现金流量净额",
            "经营活动现金流",
            "销售收现",
            "收到的现金",
        ),
    },
    {
        "key": "other_income_investment_fair_value",
        "label": "其他收益、投资收益与公允价值",
        "keywords": ("其他收益", "投资收益", "公允价值变动收益", "政府补助"),
    },
    {
        "key": "impairment_nonrecurring",
        "label": "减值与非经常性损益",
        "keywords": (
            "信用减值损失",
            "资产减值损失",
            "非经常性损益",
            "营业外收入",
            "营业外支出",
        ),
    },
)


class AShareFilingService:
    METHOD = "deterministic_filing_theme_extraction_v1"

    def __init__(self, database: Database, provider: AShareFilingProvider):
        self.database = database
        self.provider = provider

    def refresh_symbol(
        self, symbol: str, *, limit: int = 3, force: bool = False
    ) -> dict[str, Any]:
        canonical = normalize_symbol(symbol)
        if not canonical.endswith((".SS", ".SZ")):
            raise ValueError("只支持 A 股证券的财报全文刷新")
        candidates = self.provider.list_financial_reports(canonical, limit=limit)
        results = []
        warnings = []
        for candidate in candidates:
            article_code = candidate["article_code"]
            existing = self.database.get_filing_document(canonical, article_code)
            try:
                if existing is not None and existing.get("content_hash") and not force:
                    document = existing
                    action = "unchanged"
                else:
                    document = self.database.upsert_filing_document(
                        self.provider.fetch_document(candidate)
                    )
                    action = "stored"
                packet = self._packet_from_document(document, persist=True)
                results.append(
                    {
                        "article_code": article_code,
                        "report_period": document.get("report_period"),
                        "action": action,
                        "content_chars": len(document.get("content_text") or ""),
                        "explicit_explanations": len(
                            packet.get("explicit_company_explanations") or []
                        ),
                    }
                )
            except Exception as exc:
                warnings.append(
                    f"{article_code} 财报正文刷新未完成：{type(exc).__name__}"
                )
        return {
            "symbol": canonical,
            "requested": len(candidates),
            "completed": len(results),
            "results": results,
            "warnings": warnings,
            "refreshed_at": utc_now(),
        }

    def refresh_symbols(self, symbols: list[str], *, limit: int = 3) -> dict[str, Any]:
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
                result = self.refresh_symbol(symbol, limit=limit)
                results.append({"status": "ok", **result})
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
            "completed": sum(item.get("status") == "ok" for item in results),
            "results": results,
        }

    def ensure_report(self, symbol: str, report_period: str) -> dict[str, Any]:
        canonical = normalize_symbol(symbol)
        existing = self._document_for_period(canonical, report_period)
        if existing is not None:
            return self._packet_from_document(existing, persist=True)
        candidates = self.provider.list_financial_reports(canonical, limit=8)
        candidate = next(
            (
                item
                for item in candidates
                if item.get("report_period") == report_period
            ),
            None,
        )
        if candidate is None:
            return self._unavailable(
                canonical,
                report_period,
                "公告列表中尚未发现与结构化财务期一致的财报全文。",
            )
        document = self.database.upsert_filing_document(
            self.provider.fetch_document(candidate)
        )
        return self._packet_from_document(document, persist=True)

    def get_packet(
        self,
        symbol: str,
        *,
        report_period: str | None = None,
        persist: bool = True,
    ) -> dict[str, Any]:
        canonical = normalize_symbol(symbol)
        documents = self.database.list_filing_documents(
            canonical, limit=12, include_content=True
        )
        document = next(
            (
                item
                for item in documents
                if report_period is None or item.get("report_period") == report_period
            ),
            None,
        )
        if document is None:
            return self._unavailable(
                canonical,
                report_period,
                "尚未保存与当前报告期一致的公司财报全文。",
            )
        return self._packet_from_document(document, persist=persist)

    def get_overview(
        self, symbol: str, *, refresh_if_missing: bool = True
    ) -> dict[str, Any]:
        canonical = normalize_symbol(symbol)
        documents = self.database.list_filing_documents(canonical, limit=6)
        refresh = None
        if not documents and refresh_if_missing:
            refresh = self.refresh_symbol(canonical)
            documents = self.database.list_filing_documents(canonical, limit=6)
        packet = self.get_packet(canonical, persist=True) if documents else self._unavailable(
            canonical, None, "尚未保存公司财报全文。"
        )
        return {
            "symbol": canonical,
            "generated_at": utc_now(),
            "documents": [self._public_document(item) for item in documents],
            "cause_evidence": packet,
            "refresh": refresh,
        }

    def _document_for_period(
        self, symbol: str, report_period: str
    ) -> dict[str, Any] | None:
        return next(
            (
                item
                for item in self.database.list_filing_documents(
                    symbol, limit=12, include_content=True
                )
                if item.get("report_period") == report_period
            ),
            None,
        )

    def _packet_from_document(
        self, document: dict[str, Any], *, persist: bool
    ) -> dict[str, Any]:
        paragraphs = _paragraphs(document.get("content_text") or "")
        items: list[dict[str, Any]] = []
        for theme in _THEMES:
            matches = []
            for paragraph in paragraphs:
                keyword = next(
                    (
                        item
                        for item in theme["keywords"]
                        if item in paragraph
                    ),
                    None,
                )
                if keyword is None:
                    continue
                excerpt = _bounded_excerpt(paragraph, keyword)
                classification = (
                    "explicit_company_explanation"
                    if _EXPLICIT_CAUSE_RE.search(excerpt)
                    else "reported_fact"
                )
                matches.append(
                    {
                        "theme": theme["key"],
                        "label": theme["label"],
                        "classification": classification,
                        "excerpt": excerpt,
                        "report_title": document.get("title"),
                        "report_period": document.get("report_period"),
                        "notice_date": document.get("notice_date"),
                        "article_code": document.get("article_code"),
                    }
                )
            matches.sort(
                key=lambda item: (
                    item["classification"] == "explicit_company_explanation",
                    len(item["excerpt"]),
                ),
                reverse=True,
            )
            seen = set()
            for match in matches:
                fingerprint = re.sub(r"\s+", "", match["excerpt"])
                if fingerprint in seen:
                    continue
                seen.add(fingerprint)
                items.append(match)
                if sum(item["theme"] == theme["key"] for item in items) >= 2:
                    break
        explicit = [
            item
            for item in items
            if item["classification"] == "explicit_company_explanation"
        ]
        reported = [
            item for item in items if item["classification"] == "reported_fact"
        ]
        explicit_themes = {item["theme"] for item in explicit}
        unresolved = [
            theme["label"] for theme in _THEMES if theme["key"] not in explicit_themes
        ]
        packet = {
            "type": "filing_cause_evidence",
            "symbol": document["symbol"],
            "name": RESEARCH_TARGETS.get(document["symbol"], {}).get("name")
            or document["symbol"],
            "status": "available" if items else "insufficient",
            "generated_at": utc_now(),
            "method": self.METHOD,
            "summary": (
                f"已从{document.get('title')}提取 {len(items)} 条主题证据，"
                f"其中 {len(explicit)} 条包含公司明确原因说明。"
            ),
            "document": self._public_document(document),
            "explicit_company_explanations": explicit[:10],
            "reported_facts": reported[:8],
            "unresolved_themes": unresolved,
            "coverage": {
                "content_chars": len(document.get("content_text") or ""),
                "paragraphs": len(paragraphs),
                "themes_checked": len(_THEMES),
                "themes_with_explicit_explanation": len(explicit_themes),
                "excerpts": len(items),
            },
            "confidence": "high" if len(explicit_themes) >= 3 else "medium" if explicit else "low",
            "boundary": (
                "公司财报原文属于一手披露，可用于确认公司给出的解释；"
                "该解释不等于已经被独立数据证明的唯一业务因果。"
            ),
        }
        if persist:
            fingerprint = hashlib.sha256(
                json.dumps(
                    {
                        "content_hash": document.get("content_hash"),
                        "items": items,
                        "method": self.METHOD,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest()
            saved = self.database.save_filing_evidence_snapshot(packet, fingerprint)
            packet["snapshot_id"] = saved["id"]
            packet["snapshot_created_at"] = saved["created_at"]
            self._index_common_knowledge(packet)
        return packet

    def _index_common_knowledge(self, packet: dict[str, Any]) -> None:
        document = packet.get("document") or {}
        source_key = (
            f"filing-evidence:{packet['symbol']}:{document.get('article_code')}"
        )
        document_id = "filing-" + hashlib.sha256(
            source_key.encode("utf-8")
        ).hexdigest()[:24]
        explicit = "\n".join(
            f"- {item['label']}：{item['excerpt']}"
            for item in packet.get("explicit_company_explanations") or []
        ) or "- 本报告期未抽取到明确原因说明。"
        facts = "\n".join(
            f"- {item['label']}：{item['excerpt']}"
            for item in packet.get("reported_facts") or []
        ) or "- 暂无额外事实摘录。"
        content = (
            f"# {packet['name']}财报原文原因证据\n\n"
            f"报告：{document.get('title')}\n\n"
            f"报告期：{document.get('report_period')}\n\n"
            f"公告日期：{document.get('notice_date')}\n\n"
            f"## 公司明确解释\n\n{explicit}\n\n"
            f"## 已披露事实\n\n{facts}\n\n"
            f"## 证据边界\n\n{packet.get('boundary')}"
        )
        self.database.upsert_knowledge_document(
            document_id=document_id,
            owner_user_id=None,
            scope="common",
            title=f"{packet['name']}财报原文原因证据｜{document.get('report_period')}",
            original_name=(
                f"{packet['symbol']}-{document.get('report_period')}-filing-evidence.md"
            ),
            mime_type="text/markdown",
            content=content,
            source_key=source_key,
        )

    @staticmethod
    def _public_document(document: dict[str, Any]) -> dict[str, Any]:
        return {
            "symbol": document.get("symbol"),
            "article_code": document.get("article_code"),
            "title": document.get("title"),
            "document_type": document.get("document_type"),
            "report_period": document.get("report_period"),
            "notice_date": document.get("notice_date"),
            "published_at": document.get("published_at"),
            "attach_url": document.get("attach_url"),
            "source_url": document.get("source_url"),
            "content_hash": document.get("content_hash"),
            "content_chars": document.get("content_chars")
            or len(document.get("content_text") or ""),
            "fetched_at": document.get("fetched_at"),
        }

    def _unavailable(
        self, symbol: str, report_period: str | None, summary: str
    ) -> dict[str, Any]:
        return {
            "type": "filing_cause_evidence",
            "symbol": symbol,
            "name": RESEARCH_TARGETS.get(symbol, {}).get("name") or symbol,
            "status": "insufficient",
            "generated_at": utc_now(),
            "method": self.METHOD,
            "summary": summary,
            "requested_report_period": report_period,
            "document": None,
            "explicit_company_explanations": [],
            "reported_facts": [],
            "unresolved_themes": [theme["label"] for theme in _THEMES],
            "coverage": {
                "content_chars": 0,
                "paragraphs": 0,
                "themes_checked": len(_THEMES),
                "themes_with_explicit_explanation": 0,
                "excerpts": 0,
            },
            "confidence": "none",
            "boundary": (
                "没有对应报告期正文时，不使用新闻标题或模型常识替代公司原文。"
            ),
        }


def _paragraphs(content: str) -> list[str]:
    paragraphs = []
    for block in re.split(r"\n\s*\n", content):
        normalized = re.sub(r"\s+", " ", block).strip()
        if len(normalized) >= 12:
            paragraphs.append(normalized)
    return paragraphs


def _bounded_excerpt(paragraph: str, keyword: str, limit: int = 900) -> str:
    if len(paragraph) <= limit:
        return paragraph
    start = paragraph.find(keyword)
    cause = _EXPLICIT_CAUSE_RE.search(paragraph, max(0, start - 80))
    center = cause.start() if cause and cause.start() < start + 600 else start
    left = max(0, min(start, center) - 140)
    right = min(len(paragraph), left + limit)
    excerpt = paragraph[left:right].strip()
    if left:
        excerpt = "…" + excerpt
    if right < len(paragraph):
        excerpt += "…"
    return excerpt
