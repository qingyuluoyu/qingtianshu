from __future__ import annotations

from typing import Any

from app.catalog import normalize_symbol


def _filter_knowledge_context(
    context: dict[str, Any],
    *,
    intent: str,
    symbol: str | None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    original_items = list(context.get("items") or [])
    items = list(original_items)
    attached_document_id = context.get("attached_document_id")
    research_focus = str(
        (((evidence or {}).get("research_plan") or {}).get("focus") or "")
    )
    if intent == "market_brief":
        stock_research_prefixes = (
            "research-report:",
            "earnings-quality:",
            "financial-drivers:",
            "business-structure:",
            "shareholder-structure:",
            "analyst-expectations:",
            "event-timeline:",
            "filing-evidence:",
            "research-outcome:",
        )
        items = [
            item
            for item in items
            if (
                item.get("scope") == "user"
                and not str(item.get("source_key") or "").startswith(
                    stock_research_prefixes
                )
            )
            or str(item.get("source_key") or "")
            in {
                "builtin:evidence-hierarchy.md",
                "builtin:market-causality.md",
                "builtin:market-trend-risk.md",
            }
            or str(item.get("source_key") or "").startswith(("market-", "market:"))
        ]
    elif intent == "general_research" and (evidence or {}).get(
        "financial_advisor_context"
    ):
        required_sources = set(
            ((evidence or {}).get("financial_advisor_context") or {}).get(
                "required_sources"
            )
            or []
        )
        generated_research_prefixes = (
            "research-report:",
            "earnings-quality:",
            "financial-drivers:",
            "business-structure:",
            "shareholder-structure:",
            "analyst-expectations:",
            "event-timeline:",
            "filing-evidence:",
            "research-outcome:",
            "research-actions:",
            "research-priority:",
            "research-change:",
            "deep-stock:",
        )
        items = [
            item
            for item in items
            if str(item.get("source_key") or "") in required_sources
            or (
                item.get("scope") == "user"
                and not str(item.get("source_key") or "").startswith(
                    generated_research_prefixes
                )
            )
        ]
    elif intent == "stock_screen":
        stock_specific_prefixes = (
            "research-report:",
            "earnings-quality:",
            "financial-drivers:",
            "business-structure:",
            "shareholder-structure:",
            "analyst-expectations:",
            "event-timeline:",
            "filing-evidence:",
            "research-outcome:",
            "deep-stock:",
        )
        items = [
            item
            for item in items
            if not str(item.get("source_key") or "").startswith(stock_specific_prefixes)
        ]
    elif intent in {"research_priority", "research_actions"}:
        items = [
            item
            for item in items
            if item.get("scope") == "user"
            and not str(item.get("source_key") or "").startswith(
                ("research-priority:", "research-actions:")
            )
        ]
    elif (
        intent
        in {
            "stock_research",
            "research_tracking",
            "earnings_quality",
            "financial_drivers",
            "business_structure",
            "shareholder_structure",
            "analyst_expectations",
            "event_timeline",
        }
        and symbol
    ):
        canonical = normalize_symbol(symbol)
        if research_focus == "price_cause":
            # A same-day price question already receives refreshed quote,
            # market/industry context and a scoped event timeline.  Generated
            # slow-moving stock archives are neither fresh price evidence nor
            # independent user material, and re-injecting them here can make
            # the model explain today's move with an old financial or holder
            # snapshot.  Keep generic reference material and genuine uploads;
            # the latter remains contextual only under the prompt contract.
            generated_stock_prefixes = (
                "research-report:",
                "earnings-quality:",
                "financial-drivers:",
                "business-structure:",
                "peer-operating:",
                "shareholder-structure:",
                "analyst-expectations:",
                "event-timeline:",
                "filing-evidence:",
                "research-outcome:",
                "research-actions:",
                "research-priority:",
                "research-change:",
                "deep-stock:",
            )
            items = [
                item
                for item in items
                if not str(item.get("source_key") or "").startswith(
                    generated_stock_prefixes
                )
            ]
        question = str((evidence or {}).get("user_question") or "")
        time_sensitive_question = any(
            term in question
            for term in (
                "今天",
                "今日",
                "当前",
                "现在",
                "盘中",
                "最新",
                "报价",
                "为什么涨",
                "为什么跌",
                "为什么上涨",
                "为什么下跌",
                "上涨原因",
                "下跌原因",
                "涨停",
                "跌停",
            )
        )
        if time_sensitive_question:
            snapshot_prefixes = (
                "research-report:",
                "research-outcome:",
                "research-actions:",
                "research-priority:",
                "research-change:",
            )
            items = [
                item
                for item in items
                if not str(item.get("source_key") or "").startswith(snapshot_prefixes)
            ]
        report_period = ((evidence or {}).get("latest_period") or {}).get(
            "report_date"
        ) or ((evidence or {}).get("latest_report") or {}).get("report_date")
        wanted = {
            f"research-report:{canonical}",
            f"earnings-quality:{canonical}",
            f"financial-drivers:{canonical}",
            f"business-structure:{canonical}",
            f"peer-operating:{canonical}",
            f"shareholder-structure:{canonical}",
            f"analyst-expectations:{canonical}",
            f"event-timeline:{canonical}",
        }
        items = [
            item
            for item in items
            if (
                (
                    str(item.get("source_key") or "").startswith(
                        f"filing-evidence:{canonical}:"
                    )
                    and (
                        not report_period
                        or report_period in str(item.get("title") or "")
                    )
                )
                or not str(item.get("source_key") or "").startswith(
                    (
                        "research-report:",
                        "earnings-quality:",
                        "financial-drivers:",
                        "business-structure:",
                        "peer-operating:",
                        "shareholder-structure:",
                        "analyst-expectations:",
                        "event-timeline:",
                        "filing-evidence:",
                    )
                )
                or item.get("source_key") in wanted
            )
        ]
    elif intent == "research_outcome":
        canonical = normalize_symbol(symbol) if symbol else None
        wanted = (
            {
                f"research-report:{canonical}",
                f"research-outcome:{canonical}",
            }
            if canonical
            else set()
        )
        items = [
            item
            for item in items
            if (
                item.get("source_key") in wanted
                if canonical
                else str(item.get("source_key") or "").startswith("research-outcome:")
            )
        ]
    if attached_document_id:
        attached_items = [
            item
            for item in original_items
            if item.get("document_id") == attached_document_id
        ]
        items = [
            *attached_items,
            *[
                item
                for item in items
                if item.get("document_id") != attached_document_id
            ],
        ]
    coverage = dict(context.get("coverage") or {})
    coverage["matched_documents"] = len(items)
    return {**context, "items": items, "coverage": coverage}
