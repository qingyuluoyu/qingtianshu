from __future__ import annotations

import re
from typing import Any


SNAPSHOT_VERSION = "advisor_lab_context_v1"
_SENSITIVE_KEY_PARTS = (
    "key",
    "token",
    "secret",
    "password",
    "workspace_path",
    "prompt",
)
_MAX_HISTORY_MESSAGES = 40
_MAX_TEXT_LENGTH = 500
_MAX_TIME_FIELDS = 30


class AdvisorLabPolicy:
    """Server-side guard for the standalone advisor test station."""

    _BLOCKED_OPERATIONS: tuple[tuple[tuple[str, ...], str], ...] = (
        (("加入自选", "添加自选", "加到自选"), "测试台不允许修改自选股。"),
        (("请记住", "记住我", "写入记忆"), "测试台不允许写入长期记忆。"),
        (
            (
                "生成研究报告",
                "生成一份研究报告",
                "生成报告",
                "创建研究任务",
                "新建研究任务",
            ),
            "测试台不允许创建报告或研究任务。",
        ),
        (("生成文章", "市场文章"), "测试台不允许生成文章任务。"),
        (("确认写回", "确认候选", "确认研究结论"), "测试台不允许确认 AI 写回。"),
        (
            ("买入", "卖出", "开仓", "平仓", "调仓", "创建交易", "创建买入操作"),
            "测试台不允许创建交易或仓位操作。",
        ),
        (("运行回测", "开始回测"), "测试台不允许创建回测任务。"),
    )

    @classmethod
    def blocked_operation(cls, message: str) -> str | None:
        folded = "".join(str(message or "").split()).casefold()
        for phrases, reason in cls._BLOCKED_OPERATIONS:
            if any(phrase.casefold() in folded for phrase in phrases):
                return reason
        return None


def investment_profile_questions(message: str) -> list[str]:
    folded = "".join(str(message or "").split())
    if not any(term in folded for term in ("加仓", "补仓", "加码")):
        return []
    return ["当前持仓成本与仓位", "资金使用期限", "可承受的最大回撤", "计划加仓比例"]


def _safe_text(value: Any, limit: int = _MAX_TEXT_LENGTH) -> str:
    text = str(value or "").strip()
    return text[:limit]


def filter_knowledge_for_symbol(
    context: dict[str, Any], symbol: str | None
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Keep only the target security or an explicitly attached user document."""

    if not symbol:
        return context, []
    canonical = str(symbol).upper().replace(".SH", ".SS")
    target_code = canonical.split(".", 1)[0]
    kept: list[dict[str, Any]] = []
    excluded: list[dict[str, str]] = []
    for item in context.get("items") or []:
        if not isinstance(item, dict):
            continue
        scope = str(item.get("scope") or "")
        attached = bool(item.get("attached"))
        searchable = " ".join(
            str(item.get(key) or "")
            for key in ("title", "source_key", "content", "excerpt", "symbol")
        ).upper().replace(".SH", ".SS")
        mentioned_codes = set(re.findall(r"(?<!\d)(\d{6})(?:\.(?:SZ|SS))?", searchable))
        matches_target = canonical in searchable or target_code in mentioned_codes
        if matches_target or (scope == "user" and attached):
            kept.append(item)
            continue
        reason = (
            "证券标识不匹配当前研究对象"
            if mentioned_codes
            else "未标注当前研究对象，未作为个股研究资料使用"
        )
        excluded.append({"title": _safe_text(item.get("title"), 120), "reason": reason})
    return {**context, "items": kept}, excluded


def _is_sensitive_key(key: Any) -> bool:
    folded = str(key or "").casefold()
    return any(part in folded for part in _SENSITIVE_KEY_PARTS)


def _safe_scalar(value: Any) -> str | int | float | bool | None:
    if value is None or isinstance(value, (str, int, float, bool)):
        return _safe_text(value) if isinstance(value, str) else value
    return None


def _safe_history(history: list[dict[str, Any]]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for item in history[-_MAX_HISTORY_MESSAGES:]:
        role = _safe_text(item.get("role"), 20)
        content = _safe_text(item.get("content"))
        if role and content:
            items.append({"role": role, "content": content})
    return items


def _safe_knowledge(context: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for item in (context.get("items") or [])[:12]:
        if not isinstance(item, dict):
            continue
        public = {
            key: _safe_scalar(item.get(key))
            for key in (
                "document_id",
                "title",
                "source_key",
                "source_type",
                "scope",
                "score",
                "relevance",
                "attached",
            )
            if item.get(key) is not None
        }
        content = _safe_text(item.get("content") or item.get("excerpt"))
        if content:
            public["excerpt"] = content
        if public:
            items.append(public)
    coverage = context.get("coverage")
    if not isinstance(coverage, dict):
        return items, {}
    return (
        items,
        {
            str(key): _safe_scalar(value)
            for key, value in coverage.items()
            if not _is_sensitive_key(key) and _safe_scalar(value) is not None
        },
    )


def _time_fields(value: Any, *, prefix: str = "") -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if _is_sensitive_key(key):
                continue
            path = f"{prefix}.{key}" if prefix else str(key)
            folded = str(key).casefold()
            scalar = _safe_scalar(child)
            if scalar is not None and (
                folded.endswith(("_at", "_date", "_timestamp"))
                or folded in {"as_of", "period", "market_time"}
            ):
                found.append({"field": path, "value": scalar})
            if len(found) < _MAX_TIME_FIELDS:
                found.extend(_time_fields(child, prefix=path))
            if len(found) >= _MAX_TIME_FIELDS:
                return found[:_MAX_TIME_FIELDS]
    elif isinstance(value, list):
        for index, child in enumerate(value[:12]):
            found.extend(_time_fields(child, prefix=f"{prefix}[{index}]"))
            if len(found) >= _MAX_TIME_FIELDS:
                return found[:_MAX_TIME_FIELDS]
    return found[:_MAX_TIME_FIELDS]


def _source_summaries(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = evidence.get("sources") or evidence.get("evidence_sources") or []
    if not isinstance(candidates, list):
        return []
    results: list[dict[str, Any]] = []
    for item in candidates[:12]:
        if not isinstance(item, dict):
            continue
        public = {
            key: _safe_scalar(item.get(key))
            for key in ("id", "title", "name", "source", "published_at", "url", "scope")
            if item.get(key) is not None and not _is_sensitive_key(key)
        }
        if public:
            results.append(public)
    return results


def build_advisor_lab_snapshot(
    *,
    prepared: Any,
    intent: str,
    evidence: dict[str, Any],
    policy_events: list[dict[str, Any]],
    run: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create the only context representation exposed by the advisor lab."""

    knowledge_items, knowledge_coverage = _safe_knowledge(
        dict(getattr(prepared, "knowledge_context", {}) or {})
    )
    safe_evidence_keys = [
        str(key)
        for key in evidence
        if not _is_sensitive_key(key)
    ][:40]
    execution = {
        "run_id": (run or {}).get("id"),
        "status": (run or {}).get("status"),
        "usage": (run or {}).get("usage"),
    }
    return {
        "snapshot_version": SNAPSHOT_VERSION,
        "routing": {
            "intent": intent,
            "symbols": list(getattr(prepared, "symbols", []) or []),
            "symbol": getattr(prepared, "symbol", None),
            "prior_intent": getattr(prepared, "prior_intent", None),
            "contextual_followup": bool(
                getattr(prepared, "contextual_followup", False)
            ),
            "stock_context_followup": bool(
                getattr(prepared, "stock_context_followup", False)
            ),
            "model_tier": getattr(prepared, "model_tier", None),
        },
        "actual_context": {
            "conversation_history": _safe_history(
                list(getattr(prepared, "history", []) or [])
            ),
            "knowledge_items": knowledge_items,
            "knowledge_coverage": knowledge_coverage,
            "evidence_keys": safe_evidence_keys,
        },
        "evidence": {
            "type": _safe_text(evidence.get("type"), 80),
            "sources": _source_summaries(evidence),
            "time_fields": _time_fields(evidence),
        },
        "excluded_or_blocked": list(policy_events),
        "execution": execution,
    }


__all__ = [
    "AdvisorLabPolicy",
    "SNAPSHOT_VERSION",
    "build_advisor_lab_snapshot",
    "filter_knowledge_for_symbol",
    "investment_profile_questions",
]
