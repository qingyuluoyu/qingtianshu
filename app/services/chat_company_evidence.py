from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from app.providers.market import ProviderError


@dataclass(frozen=True, slots=True)
class ChatCompanyEvidenceResult:
    intent: str
    evidence: dict[str, Any] | None = None
    clarification: str | None = None


class ChatCompanyEvidenceService:
    """Build company-specific chat evidence outside the HTTP route layer."""

    def __init__(
        self,
        *,
        database: Any,
        event_timeline: Any,
        analyst_expectations: Any,
        shareholders: Any,
        business_structure: Any,
        fundamentals: Any,
        china_info: Any,
        us_fundamentals: Any,
        global_info: Any,
        financial_drivers: Any,
        earnings_quality: Any,
        filings: Any,
    ) -> None:
        self.database = database
        self.event_timeline = event_timeline
        self.analyst_expectations = analyst_expectations
        self.shareholders = shareholders
        self.business_structure = business_structure
        self.fundamentals = fundamentals
        self.china_info = china_info
        self.us_fundamentals = us_fundamentals
        self.global_info = global_info
        self.financial_drivers = financial_drivers
        self.earnings_quality = earnings_quality
        self.filings = filings
        self._builders: dict[
            str, Callable[[str, str, str], dict[str, Any]]
        ] = {
            "event_timeline": self._build_event_timeline,
            "analyst_expectations": self._build_analyst_expectations,
            "shareholder_structure": self._build_shareholder_structure,
            "business_structure": self._build_business_structure,
            "financial_drivers": self._build_financial_drivers,
            "earnings_quality": self._build_earnings_quality,
        }

    def build(
        self,
        intent: str,
        *,
        user_id: str,
        symbol: str | None,
        message: str,
    ) -> ChatCompanyEvidenceResult:
        if intent not in self._builders:
            raise ValueError(f"unsupported company evidence intent: {intent}")
        clarification = self._clarification(intent, symbol)
        if clarification:
            return ChatCompanyEvidenceResult(
                intent="clarification",
                clarification=clarification,
            )
        assert symbol is not None
        evidence = self._builders[intent](user_id, symbol, message)
        evidence["user_question"] = message
        self._attach_user_thesis(evidence, user_id=user_id, symbol=symbol)
        return ChatCompanyEvidenceResult(intent=intent, evidence=evidence)

    @staticmethod
    def _clarification(intent: str, symbol: str | None) -> str | None:
        missing_symbol = {
            "event_timeline": (
                "请告诉我具体公司或证券代码，例如“中兴通讯最近有什么重要事件”"
                "“中际旭创有哪些催化和风险事件”或“NVDA 最新事件脉络”。"
            ),
            "analyst_expectations": (
                "请告诉我具体 A 股公司或证券代码，例如“中兴通讯一致预期怎么样”"
                "“分析师最近上修中际旭创了吗”或“000063 最新研报有哪些”。"
            ),
            "shareholder_structure": (
                "请告诉我具体 A 股公司或证券代码，例如“中兴通讯股东户数怎么变了”"
                "“中兴通讯股东结构怎么样”或“000063 的十大股东是谁”。"
            ),
            "business_structure": (
                "请告诉我具体 A 股公司或证券代码，例如“中兴通讯靠什么业务赚钱”"
                "“中际旭创收入来自哪里”或“贵州茅台产品收入结构怎么变了”。"
            ),
            "financial_drivers": (
                "请告诉我具体公司或证券代码，例如“中兴通讯利润为什么下降”"
                "“分析中际旭创的应收和现金流”或“拆解 NVDA 最新利润驱动”。"
            ),
            "earnings_quality": (
                "请告诉我具体公司或证券代码，例如“中兴通讯财报质量怎么样”"
                "“为什么中际旭创利润增长但现金流偏弱”或“分析 NVDA 最新财报”。"
            ),
        }
        if symbol is None:
            return missing_symbol[intent]
        if symbol.endswith((".SS", ".SZ")):
            return None
        unsupported_market = {
            "analyst_expectations": (
                "当前一致预期与个股研报跟踪先覆盖 A 股；"
                "美股需要接入独立的分析师一致预期口径后再比较。"
            ),
            "shareholder_structure": (
                "当前股东户数和十大股东明细先覆盖 A 股；"
                "美股机构持仓需要接入 13F 等监管披露后再分析。"
            ),
            "business_structure": (
                "当前主营构成明细先覆盖 A 股；"
                "美股分部收入需要接入 SEC 分部披露后再分析。"
            ),
        }
        return unsupported_market.get(intent)

    def _build_event_timeline(
        self, user_id: str, symbol: str, message: str
    ) -> dict[str, Any]:
        del user_id, message
        return self.event_timeline.get_packet(symbol)

    def _build_analyst_expectations(
        self, user_id: str, symbol: str, message: str
    ) -> dict[str, Any]:
        del user_id, message
        try:
            return self.analyst_expectations.get_packet(symbol)
        except ProviderError:
            return self.analyst_expectations.get_packet(
                symbol, refresh_if_missing=False
            )

    def _build_shareholder_structure(
        self, user_id: str, symbol: str, message: str
    ) -> dict[str, Any]:
        del user_id, message
        return self.shareholders.get_packet(symbol)

    def _build_business_structure(
        self, user_id: str, symbol: str, message: str
    ) -> dict[str, Any]:
        del user_id, message
        return self.business_structure.get_packet(symbol)

    def _build_financial_drivers(
        self, user_id: str, symbol: str, message: str
    ) -> dict[str, Any]:
        del user_id, message
        related_information: list[dict[str, Any]] = []
        try:
            if symbol.endswith((".SS", ".SZ")):
                self.fundamentals.get_packet(symbol)
                information_packet = self.china_info.get_packet(symbol)
                related_information = self._information_items(
                    (information_packet.get("announcements") or [])[:4]
                    + (information_packet.get("news") or [])[:2]
                )
            else:
                fundamentals_packet = self.us_fundamentals.get_packet(symbol)
                related_information = self._information_items(
                    (fundamentals_packet.get("regulatory_filings") or [])[:5]
                )
        except Exception:
            pass
        evidence = self.financial_drivers.get_packet(symbol)
        evidence["related_information"] = related_information
        return evidence

    def _build_earnings_quality(
        self, user_id: str, symbol: str, message: str
    ) -> dict[str, Any]:
        del user_id, message
        related_information: list[dict[str, Any]] = []
        fundamental_packet: dict[str, Any] = {}
        try:
            if symbol.endswith((".SS", ".SZ")):
                fundamental_packet = self.fundamentals.get_packet(symbol)
                information_packet = self.china_info.get_packet(symbol)
                related_information = self._information_items(
                    (information_packet.get("announcements") or [])[:3]
                    + (information_packet.get("news") or [])[:3]
                )
            else:
                fundamental_packet = self.us_fundamentals.get_packet(symbol)
                information_packet = self.global_info.get_packet(symbol)
                related_information = self._information_items(
                    (fundamental_packet.get("regulatory_filings") or [])[:3]
                    + (information_packet.get("news") or [])[:3]
                )
        except Exception:
            pass
        evidence = self.earnings_quality.get_packet(symbol)
        evidence["fundamental_summary"] = fundamental_packet.get("summary") or {}
        evidence["related_information"] = related_information
        if symbol.endswith((".SS", ".SZ")):
            report_period = (evidence.get("latest_report") or {}).get("report_date")
            try:
                filing_evidence = self.filings.get_packet(
                    symbol, report_period=report_period
                )
                if filing_evidence.get("status") != "available" and report_period:
                    filing_evidence = self.filings.ensure_report(symbol, report_period)
                evidence["filing_evidence"] = filing_evidence
                evidence["company_explanations"] = (
                    filing_evidence.get("explicit_company_explanations") or []
                )
            except Exception:
                evidence["company_explanations"] = []
        return evidence

    def _attach_user_thesis(
        self,
        evidence: dict[str, Any],
        *,
        user_id: str,
        symbol: str,
    ) -> None:
        watchlist_item = self.database.get_watchlist_item(user_id, symbol)
        evidence["user_thesis"] = (
            watchlist_item.get("thesis") if watchlist_item else None
        )

    @staticmethod
    def _information_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "category": item.get("category"),
                "title": item.get("title"),
                "published_at": item.get("published_at"),
            }
            for item in items
        ]
