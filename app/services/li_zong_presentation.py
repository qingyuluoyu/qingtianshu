from __future__ import annotations

from typing import Any

from app.catalog import RESEARCH_TARGETS


def external_ts_code(symbol: str) -> str:
    """Expose Shanghai symbols with the Tushare-compatible `.SH` suffix."""

    return symbol[:-3] + ".SH" if symbol.endswith(".SS") else symbol


def public_li_zong_candidate(item: dict[str, Any]) -> dict[str, Any]:
    """Convert an internal strategy record into the stable public API shape."""

    result = dict(item.get("result") or {})
    rules = list(result.get("rule_results") or item.get("rule_results") or [])
    rule_map = {str(rule.get("rule_id")): rule for rule in rules}

    def actual(rule_id: str) -> Any:
        return (rule_map.get(rule_id) or {}).get("actual_value")

    roe_values = [
        entry.get("roe_pct")
        for entry in (actual("LZ-F-02") or [])
        if isinstance(entry, dict) and entry.get("roe_pct") is not None
    ]
    shareholder = actual("LZ-F-04") or {}
    annual_limits = actual("LZ-C-01") or {}
    recent_limits = actual("LZ-C-03") or {}
    bearish = actual("LZ-C-04") or {}
    new_high = actual("LZ-VP-01") or {}
    volume = actual("LZ-VP-02") or {}
    symbol = str(item.get("symbol") or result.get("symbol") or "")
    target = RESEARCH_TARGETS.get(symbol) or {}
    stock_basic = result.get("stock_basic") or {}
    return {
        "id": item.get("id"),
        "symbol": external_ts_code(symbol),
        "internal_symbol": symbol,
        "name": stock_basic.get("name") or target.get("name") or symbol,
        "industry": stock_basic.get("industry"),
        "market": stock_basic.get("market") or target.get("market"),
        "status": item.get("status") or result.get("status"),
        "evaluation_status": item.get("evaluation_status") or result.get("status"),
        "strategy_version": item.get("strategy_version")
        or result.get("strategy_version"),
        "parameter_version": item.get("parameter_version")
        or result.get("parameter_version"),
        "data_version": item.get("data_version"),
        "as_of_date": item.get("as_of_date") or result.get("as_of_date"),
        "previous_status": item.get("previous_status"),
        "candidate_qualified": bool(result.get("candidate_qualified")),
        "triggered_rule_ids": list(result.get("triggered_rule_ids") or []),
        "summary": {
            "market_cap_yi": (actual("LZ-F-01") or {}).get("market_cap_yi"),
            "roe_min_pct": min(roe_values) if roe_values else None,
            "annual_roe_years": len(roe_values),
            "non_natural_holder_count": shareholder.get(
                "non_natural_holder_count"
            ),
            "unknown_holder_count": shareholder.get("unknown_holder_count"),
            "annual_limit_up_count": annual_limits.get("limit_up_count"),
            "has_consecutive_limit_up": (
                (rule_map.get("LZ-C-02") or {}).get("status") == "passed"
            ),
            "recent_limit_up_count": recent_limits.get("limit_up_count"),
            "recent_bearish_drop_count": bearish.get("bearish_drop_count"),
            "new_high_dates": list(new_high.get("new_high_dates") or []),
            "volume_sequences": list(volume.get("sequences") or []),
        },
        "rule_results": rules,
        "matched_reasons": [
            f"{rule.get('rule_id')} 已通过"
            for rule in rules
            if rule.get("status") == "passed"
        ][:6],
        "limitations": list(result.get("limitations") or []),
        "created_at": item.get("created_at"),
        "invalidated_at": item.get("invalidated_at"),
        "boundary": result.get("boundary")
        or "仅用于确定性研究候选筛选和人工复核，不构成买卖建议。",
    }


def public_li_zong_observation(item: dict[str, Any]) -> dict[str, Any]:
    """Render a near-match as an observation, never as a strict candidate."""

    public = public_li_zong_candidate(item)
    public.update(
        {
            "observation_band": item.get("observation_band"),
            "candidate_rule_pass_count": int(
                item.get("candidate_rule_pass_count") or 0
            ),
            "candidate_rule_total": int(item.get("candidate_rule_total") or 9),
            "passed_candidate_rule_ids": list(
                item.get("passed_candidate_rule_ids") or []
            ),
            "failed_candidate_rule_ids": list(
                item.get("failed_candidate_rule_ids") or []
            ),
            "is_strict_candidate": False,
        }
    )
    public["boundary"] = (
        "该股票只属于接近满足研究观察池，不是李总策略候选或触发标的；"
        "严格9条候选规则和3条触发规则没有放宽。"
    )
    return public
