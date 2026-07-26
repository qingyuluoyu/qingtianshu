from __future__ import annotations

from datetime import datetime
from typing import Any


def _public_run_review(
    run: dict[str, Any],
    *,
    conversation_title: str,
    include_answer: bool,
) -> dict[str, Any]:
    input_data = run.get("input") or {}
    evidence = run.get("evidence") or {}
    usage = run.get("usage") or {}
    timings = usage.get("timings") or {}
    streaming = usage.get("streaming") or {}
    output_guard = usage.get("output_guard") or {}
    repair = output_guard.get("repair") or {}

    repair_groups = {
        "numbers": repair.get("original_unsupported_numbers") or [],
        "market": repair.get("original_unsupported_market_inferences") or [],
        "internal": repair.get("original_private_operational_patterns") or [],
        "semantic": repair.get("original_semantic_conflicts") or [],
    }
    repaired = bool(repair) or any(repair_groups.values())
    repair_summary: list[str] = []
    if repair_groups["numbers"]:
        repair_summary.append(
            f"移除或改写 {len(repair_groups['numbers'])} 处无法由证据核验的数字"
        )
    if repair_groups["market"]:
        repair_summary.append(
            f"修正 {len(repair_groups['market'])} 处行情口径或数据时点表述"
        )
    if repair_groups["internal"]:
        repair_summary.append(
            f"移除 {len(repair_groups['internal'])} 处不应面向用户的运行措辞"
        )
    if repair_groups["semantic"]:
        repair_summary.append(f"修正 {len(repair_groups['semantic'])} 处证据与结论冲突")
    if repaired and not repair_summary:
        repair_summary.append("回答在展示前经过了守卫修复")
    if not repair_summary:
        repair_summary.append("未发现需要修复的数字、时点或内部措辞")

    current_quote = evidence.get("current_quote") or {}
    provenance = evidence.get("provenance") or {}
    knowledge_context = evidence.get("knowledge_context") or {}
    knowledge_coverage = knowledge_context.get("coverage") or {}
    information = evidence.get("a_share_information") or {}
    analysis_board = evidence.get("analysis_board") or {}
    modules = [
        {
            "label": str(item.get("label") or item.get("name") or "分析模块"),
            "evidence_count": int(item.get("evidence_count") or 0),
            "status": str(item.get("status") or "ready"),
        }
        for item in (analysis_board.get("modules") or [])
        if isinstance(item, dict)
    ]
    knowledge_items = [
        {
            "title": str(item.get("title") or "研究资料"),
            "scope": "个人资料" if item.get("scope") == "user" else "通用资料",
        }
        for item in (knowledge_context.get("items") or [])[:8]
        if isinstance(item, dict)
    ]

    duration_seconds: float | None = None
    if timings.get("request_total_seconds") is not None:
        try:
            duration_seconds = round(float(timings["request_total_seconds"]), 3)
        except (TypeError, ValueError):
            duration_seconds = None
    if duration_seconds is None:
        try:
            started = datetime.fromisoformat(str(run.get("created_at")))
            finished = datetime.fromisoformat(str(run.get("finished_at")))
            duration_seconds = round(max(0.0, (finished - started).total_seconds()), 3)
        except (TypeError, ValueError):
            duration_seconds = None

    status = str(run.get("status") or "unknown")
    if status == "guarded" and not repaired:
        repair_summary = ["模型原始回答未满足展示条件，系统改用已验证证据生成回退回答"]
    elif status == "degraded" and not repaired:
        repair_summary = ["模型综合未完整完成，系统保留并展示了可验证的证据回答"]
    elif status == "failed" and not repaired:
        repair_summary = ["本轮未形成可展示回答，证据和运行记录已保留供后续复盘"]
    guard_label = (
        "守卫修复"
        if repaired
        else {
            "guarded": "守卫回退",
            "degraded": "降级完成",
            "failed": "未完成",
        }.get(status, "守卫通过")
    )
    status_labels = {
        "completed": "已完成",
        "guarded": "守卫回退",
        "degraded": "降级完成",
        "failed": "未完成",
    }
    intent = str(run.get("intent") or "general_research")
    intent_labels = {
        "market_brief": "大盘诊断",
        "stock_screen": "选股研究",
        "stock_research": "个股研究",
        "earnings_quality": "财报质量",
        "financial_drivers": "利润与现金流",
        "shareholder_structure": "股东结构",
        "analyst_expectations": "分析师预期",
        "event_timeline": "事件脉络",
        "research_tracking": "研究变化",
        "research_priority": "研究优先级",
        "research_actions": "研究行动",
        "research_outcome": "研究复盘",
        "watchlist_brief": "自选股跟踪",
        "general_research": "综合研究",
    }
    item: dict[str, Any] = {
        "id": str(run.get("id") or ""),
        "conversation_id": str(input_data.get("conversation_id") or ""),
        "conversation_title": conversation_title,
        "question": str(
            input_data.get("message") or evidence.get("user_question") or "研究问题"
        ),
        "intent": intent,
        "intent_label": intent_labels.get(intent, "综合研究"),
        "status": status,
        "status_label": status_labels.get(status, status),
        "symbol": str(evidence.get("symbol") or input_data.get("symbol") or ""),
        "display_name": str(
            evidence.get("display_name") or current_quote.get("name") or "市场研究"
        ),
        "model_tier": str(run.get("model_tier") or "economy"),
        "model_state": (
            "AI 已完成综合"
            if usage.get("model") or usage.get("provider")
            else "确定性分析已完成"
        ),
        "created_at": run.get("created_at"),
        "finished_at": run.get("finished_at"),
        "duration_seconds": duration_seconds,
        "data_as_of": (
            current_quote.get("market_timestamp")
            or provenance.get("market_timestamp")
            or evidence.get("generated_at")
        ),
        "timings": {
            "evidence_seconds": timings.get("routing_and_evidence_seconds"),
            "first_token_seconds": timings.get("first_token_seconds")
            or streaming.get("first_token_seconds"),
            "first_visible_seconds": timings.get("first_visible_seconds")
            or streaming.get("first_visible_seconds"),
            "model_seconds": timings.get("model_seconds"),
            "guard_seconds": timings.get("guard_seconds"),
            "total_seconds": duration_seconds,
        },
        "guard": {
            "passed": status == "completed" and bool(output_guard.get("passed", True)),
            "repaired": repaired,
            "label": guard_label,
            "summary": repair_summary,
        },
        "quote": {
            "price": current_quote.get("price"),
            "currency": current_quote.get("currency"),
            "pct_change": current_quote.get("pct_change"),
            "market_timestamp": current_quote.get("market_timestamp"),
            "daily_close": (evidence.get("metrics") or {}).get("latest_close"),
            "daily_timestamp": provenance.get("market_timestamp"),
        },
        "evidence": {
            "modules": modules,
            "ready_modules": int(analysis_board.get("ready_modules") or 0),
            "total_modules": int(analysis_board.get("total_modules") or len(modules)),
            "knowledge_documents": int(
                knowledge_coverage.get("matched_documents") or len(knowledge_items)
            ),
            "knowledge_items": knowledge_items,
            "announcements": len(information.get("announcements") or []),
            "news": len(information.get("news") or []),
            "social_posts": len(information.get("social_posts") or []),
            "warnings": len(evidence.get("warnings") or []),
            "market_source": str(
                current_quote.get("source") or provenance.get("source") or ""
            ),
        },
        "answer_excerpt": str(run.get("answer") or "")[:220],
    }
    if include_answer:
        item["answer"] = str(run.get("answer") or "")
    return item
