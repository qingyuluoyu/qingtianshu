from __future__ import annotations

from typing import Any


CONTRACT_VERSION = "stock_evidence_path_v1"
WATCHLIST_PATH = "watchlist_preanalysis"
ONLINE_PATH = "online_research"


def build_stock_research_contract(
    *,
    watchlist_item: dict[str, Any] | None,
    latest_report: dict[str, Any] | None,
) -> dict[str, Any]:
    is_watchlist = watchlist_item is not None
    path = WATCHLIST_PATH if is_watchlist else ONLINE_PATH
    return {
        "contract_version": CONTRACT_VERSION,
        "path": path,
        "is_watchlist": is_watchlist,
        "skill_name": (
            "watchlist-stock-research" if is_watchlist else "online-stock-research"
        ),
        "precomputed_report_available": bool(
            is_watchlist and latest_report and latest_report.get("evidence")
        ),
        "precomputed_report_reuse_allowed": is_watchlist,
        "precomputed_report_body_allowed": False,
        "force_online_refresh": not is_watchlist,
        "always_refresh_modules": [
            "market",
            "company_information",
            "fundamentals",
            "event_timeline",
        ],
        "answer_source": "new_model_run",
        "boundary": (
            "预生成报告只可提供版本化证据，不得作为本轮回答正文；"
            "本轮回答必须由当前 Hermes/DeepSeek Run 针对用户问题重新生成。"
        ),
    }


def finalize_stock_research_contract(
    contract: dict[str, Any],
    *,
    evidence: dict[str, Any],
    latest_report: dict[str, Any] | None,
) -> dict[str, Any]:
    statuses = evidence.get("module_statuses") or {}
    required = set((evidence.get("research_plan") or {}).get("required_modules") or [])
    fresh_modules = []
    reused_modules = []
    unavailable_modules = []
    for key, item in statuses.items():
        status = str((item or {}).get("status") or "")
        if status == "fresh":
            fresh_modules.append(key)
        elif status in {"reused", "reused_fallback"}:
            reused_modules.append(key)
        elif status == "unavailable":
            unavailable_modules.append(key)

    fundamentals = evidence.get("fundamentals") or {}
    financial_summary = fundamentals.get("summary") or {}
    financial_report = financial_summary.get("latest_report") or {}
    information = (
        evidence.get("a_share_information")
        or evidence.get("global_information")
        or {}
    )
    information_refresh = information.get("refresh") or {}
    report_reference = None
    if contract.get("precomputed_report_available") and latest_report:
        report_reference = {
            "report_id": latest_report.get("id"),
            "generated_at": latest_report.get("generated_at"),
            "market_timestamp": latest_report.get("market_timestamp"),
            "status": latest_report.get("status"),
        }

    return {
        **contract,
        "fresh_modules": sorted(fresh_modules),
        "reused_modules": sorted(reused_modules),
        "unavailable_modules": sorted(unavailable_modules),
        "missing_required_modules": sorted(required.intersection(unavailable_modules)),
        "fallback_used": any(
            str((item or {}).get("status") or "") == "reused_fallback"
            for item in statuses.values()
        ),
        "data_times": {
            "evidence_generated_at": evidence.get("generated_at"),
            "latest_quote_time": (evidence.get("current_quote") or {}).get(
                "market_timestamp"
            ),
            "complete_daily_bar_time": (evidence.get("provenance") or {}).get(
                "market_timestamp"
            ),
            "financial_report_period": financial_report.get("report_date"),
            "information_refreshed_at": information_refresh.get("refreshed_at"),
        },
        "precomputed_report_reference": report_reference,
    }
