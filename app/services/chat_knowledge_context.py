from __future__ import annotations

from typing import Any

from app.catalog import normalize_symbol


_GENERATED_STOCK_KNOWLEDGE_PREFIXES = (
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


def filter_quality_review_knowledge_context(
    context: dict[str, Any],
) -> dict[str, Any]:
    """Keep genuine user material out of generated-report feedback loops.

    A quality-review turn already carries the current company's structured
    filing extracts, comparable financial statements, operating cash flow and
    business segments in its deterministic evidence packet. Re-retrieving a
    generated research report feeds earlier prose and mechanical bridges back
    into DeepSeek, which can make a fresh answer copy the archived narrative.
    User uploads remain useful context, but every generated stock archive and
    generic common document is excluded from this specialist prompt.
    """

    items = [
        item
        for item in (context.get("items") or [])
        if item.get("scope") == "user"
        and not str(item.get("source_key") or "").startswith(
            _GENERATED_STOCK_KNOWLEDGE_PREFIXES
        )
    ]
    coverage = dict(context.get("coverage") or {})
    coverage["matched_documents"] = len(items)
    return {**context, "items": items, "coverage": coverage}


def _filter_knowledge_context(
    context: dict[str, Any],
    *,
    intent: str,
    symbol: str | None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    items = list(context.get("items") or [])
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
        if research_focus == "quality_review":
            context = filter_quality_review_knowledge_context(
                {**context, "items": items}
            )
            items = list(context.get("items") or [])
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
        # These user-wide generated documents intentionally contain several
        # securities.  They belong on portfolio/action pages, but putting them
        # into a single-stock prompt can reassign another stock's numbers to the
        # current company.  Current-symbol deterministic modules remain
        # available below; genuine uploads and generic education material are
        # still retained.
        aggregate_generated_prefixes = (
            "research-actions:",
            "research-priority:",
            "research-change:",
            "deep-stock:",
        )
        items = [
            item
            for item in items
            if (
                not str(item.get("source_key") or "").startswith(
                    aggregate_generated_prefixes
                )
                and (
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
    coverage = dict(context.get("coverage") or {})
    coverage["matched_documents"] = len(items)
    return {**context, "items": items, "coverage": coverage}
