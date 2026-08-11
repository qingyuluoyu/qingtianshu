from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


SOURCE_PROFILES: dict[str, dict[str, Any]] = {
    "deterministic_price_metrics": {
        "evidence_type": "system_calculation",
        "source_name": "系统价格与波动计算",
        "coverage_confidence": "high",
        "limitations": ["只描述已完成的价格路径，不能单独证明经营原因或未来方向。"],
    },
    "structured_fundamentals": {
        "evidence_type": "structured_data",
        "source_name": "结构化财务数据",
        "coverage_confidence": "high",
        "limitations": ["财务指标必须按报告期和公告时间解释，不能替代公告原文。"],
    },
    "deterministic_earnings_quality": {
        "evidence_type": "system_calculation",
        "source_name": "财报质量确定性分析",
        "coverage_confidence": "medium",
        "limitations": ["报表勾稽与同比关系不等于已经确认经营因果。"],
    },
    "deterministic_financial_driver": {
        "evidence_type": "system_calculation",
        "source_name": "利润与现金流机械拆解",
        "coverage_confidence": "medium",
        "limitations": ["机械拆解只能确认科目影响，业务原因仍需公告和附注核验。"],
    },
    "deterministic_business_structure": {
        "evidence_type": "system_calculation",
        "source_name": "主营结构确定性分析",
        "coverage_confidence": "medium",
        "limitations": ["分部集中度是复核线索，不能直接证明经营风险已经发生。"],
    },
    "deterministic_event_timeline": {
        "evidence_type": "official_disclosure",
        "source_name": "公司公告与监管事件时间线",
        "coverage_confidence": "high",
        "limitations": ["事件标题只用于定位原文，影响方向仍需结合披露内容核验。"],
    },
    "structured_shareholder_data": {
        "evidence_type": "structured_data",
        "source_name": "股东结构与持有人数据",
        "coverage_confidence": "medium",
        "limitations": [
            "股东户数与十大股东均是披露时点数据，不能自动解释当前资金流向。"
        ],
    },
    "structured_analyst_expectations": {
        "evidence_type": "structured_data",
        "source_name": "分析师一致预期与研报统计",
        "coverage_confidence": "medium",
        "limitations": [
            "一致预期受覆盖机构样本变化影响，不是公司指引或已实现业绩。"
        ],
    },
    "eastmoney_guba_heuristic_weak": {
        "evidence_type": "community",
        "source_name": "东方财富股吧弱情绪样本",
        "coverage_confidence": "low",
        "limitations": ["社区样本存在选择偏差，只能作为情绪线索。"],
    },
    "deterministic_outlook_calibration": {
        "evidence_type": "system_calculation",
        "source_name": "历史样本外走查",
        "coverage_confidence": "medium",
        "limitations": ["历史同类样本只用于校准当前规则，不构成未来收益概率。"],
    },
    "research_frame": {
        "evidence_type": "system_record",
        "source_name": "研究证据覆盖检查",
        "coverage_confidence": "low",
        "limitations": ["该项表示资料缺口，不是对公司方向的事实判断。"],
    },
}


def build_research_claim_ledger(evidence: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize deterministic debate output into one auditable claim ledger."""

    debate = evidence.get("evidence_debate") or _specialized_debate(evidence)
    claims: list[dict[str, Any]] = []
    for relation, key in (
        ("supports", "bull_case"),
        ("weakens", "bear_case"),
        ("unresolved", "risk_committee"),
    ):
        for raw in debate.get(key) or []:
            packet = raw if isinstance(raw, Mapping) else {"statement": raw}
            statement = _statement(packet)
            if not statement:
                continue
            evidence_summary = str(packet.get("evidence") or "").strip() or None
            source_key = str(packet.get("source") or "").strip()
            if not source_key:
                source_key = _infer_source_key(statement, evidence_summary)
            metadata = _source_metadata(evidence, source_key, evidence_summary)
            claim_id = _stable_id(
                "claim",
                {
                    "relation": relation,
                    "statement": statement,
                    "evidence": evidence_summary,
                    "source": source_key,
                    "data_time": metadata.get("data_time"),
                },
            )
            claims.append(
                {
                    "id": claim_id,
                    "relation": relation,
                    "claim": statement,
                    "evidence_summary": evidence_summary,
                    "evidence_type": metadata["evidence_type"],
                    "source_key": source_key,
                    "source_name": metadata["source_name"],
                    "source_url": metadata.get("source_url"),
                    "published_at": metadata.get("published_at"),
                    "retrieved_at": metadata.get("retrieved_at"),
                    "data_time": metadata.get("data_time"),
                    "report_period": metadata.get("report_period"),
                    "trade_date": metadata.get("trade_date"),
                    "coverage_status": metadata["coverage_status"],
                    "coverage_confidence": metadata["coverage_confidence"],
                    "limitations": metadata["limitations"],
                    "next_step": packet.get("action") or packet.get("next_step"),
                }
            )

    unresolved_ids = [
        item["id"] for item in claims if item["relation"] == "unresolved"
    ]
    information_gaps = []
    for raw in (evidence.get("research_frame") or {}).get(
        "missing_information"
    ) or []:
        description = str(raw or "").strip()
        if not description:
            continue
        information_gaps.append(
            {
                "id": _stable_id("gap", description),
                "description": description,
                "status": "unresolved",
                "source_name": "研究证据覆盖检查",
                "related_claim_ids": unresolved_ids[:4],
            }
        )

    invalidation_conditions = _invalidation_conditions(evidence, claims)
    supports = sum(item["relation"] == "supports" for item in claims)
    weakens = sum(item["relation"] == "weakens" for item in claims)
    unresolved = sum(item["relation"] == "unresolved" for item in claims)
    strongest_counterevidence = next(
        (item for item in claims if item["relation"] == "weakens"),
        next((item for item in claims if item["relation"] == "unresolved"), None),
    )
    return {
        "status": "available" if claims else "unavailable",
        "method": "structured_claim_ledger_v1",
        "claims": claims,
        "summary": {
            "supports": supports,
            "weakens": weakens,
            "unresolved": unresolved,
            "information_gaps": len(information_gaps),
            "invalidation_conditions": len(invalidation_conditions),
        },
        "strongest_counterevidence": strongest_counterevidence,
        "information_gaps": information_gaps,
        "invalidation_conditions": invalidation_conditions,
        "boundary": (
            "Claim 关系只表示当前证据支持、削弱或尚未解决的研究主张；"
            "覆盖置信度描述来源与数据完整性，不表示未来涨跌概率。"
        ),
    }


def _statement(packet: Mapping[str, Any]) -> str:
    value = (
        packet.get("claim")
        or packet.get("risk")
        or packet.get("title")
        or packet.get("statement")
    )
    return " ".join(str(value or "").split())


def _specialized_debate(evidence: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Expose focused stock modules through the same auditable claim contract.

    Focused chat routes intentionally return a compact module packet instead of
    the full stock-research evidence envelope.  Turning the module's existing
    deterministic statements into debate-shaped records lets citations,
    writeback candidates and the live Agent share one evidence ledger without
    asking the model to invent an interpretation.
    """

    evidence_type = str(evidence.get("type") or "")
    bull_case: list[dict[str, Any]] = []
    bear_case: list[dict[str, Any]] = []
    risk_committee: list[dict[str, Any]] = []

    def add(
        target: list[dict[str, Any]],
        value: Any,
        *,
        source: str,
        action: str | None = None,
    ) -> None:
        if isinstance(value, Mapping):
            statement = _statement(value)
            evidence_summary = str(
                value.get("evidence") or value.get("summary") or statement
            ).strip()
        else:
            statement = " ".join(str(value or "").split())
            evidence_summary = statement
        if not statement:
            return
        target.append(
            {
                "statement": statement,
                "evidence": evidence_summary,
                "source": source,
                "action": action,
            }
        )

    if evidence_type == "earnings_quality":
        source = "deterministic_earnings_quality"
        for item in evidence.get("supports") or []:
            add(bull_case, item, source=source)
        for item in evidence.get("contradictions") or []:
            add(bear_case, item, source=source)
        for item in evidence.get("review_points") or []:
            add(risk_committee, f"仍需核验：{item}", source=source, action=str(item))
    elif evidence_type == "financial_drivers":
        source = "deterministic_financial_driver"
        for item in evidence.get("confirmed_mechanical_drivers") or []:
            add(bull_case, item, source=source)
        for item in evidence.get("plausible_clues") or []:
            add(risk_committee, item, source=source)
        for item in evidence.get("unresolved_causes") or []:
            add(risk_committee, f"仍未确认：{item}", source=source, action=str(item))
    elif evidence_type == "business_structure":
        source = "deterministic_business_structure"
        for item in evidence.get("key_changes") or []:
            add(bull_case, item, source=source)
        for item in evidence.get("coverage_limits") or []:
            action = (
                str(item.get("next_evidence") or "")
                if isinstance(item, Mapping)
                else None
            )
            add(risk_committee, item, source=source, action=action)
        for item in evidence.get("review_points") or []:
            add(risk_committee, f"仍需核验：{item}", source=source, action=str(item))
    elif evidence_type == "shareholder_structure":
        source = "structured_shareholder_data"
        for key in ("holder_count_statement", "recent_pattern", "top_holders_statement"):
            add(bull_case, evidence.get(key), source=source)
        for item in evidence.get("special_name_notes") or []:
            add(bear_case, item, source=source)
        for item in evidence.get("review_points") or []:
            add(risk_committee, f"仍需核验：{item}", source=source, action=str(item))
    elif evidence_type == "analyst_expectations":
        source = "structured_analyst_expectations"
        for value in (
            evidence.get("rating_statement"),
            evidence.get("forecast_statement"),
            (evidence.get("revision") or {}).get("summary"),
        ):
            add(bull_case, value, source=source)
        for item in evidence.get("review_points") or []:
            add(risk_committee, f"仍需核验：{item}", source=source, action=str(item))
    elif evidence_type == "event_timeline":
        source = "deterministic_event_timeline"
        for item in evidence.get("supportive_events") or []:
            add(bull_case, item, source=source)
        for item in evidence.get("risk_events") or []:
            add(bear_case, item, source=source)
        for item in evidence.get("review_points") or []:
            add(risk_committee, f"仍需核验：{item}", source=source, action=str(item))

    return {
        "bull_case": bull_case,
        "bear_case": bear_case,
        "risk_committee": risk_committee,
    }


def _infer_source_key(statement: str, evidence_summary: str | None) -> str:
    text = f"{statement} {evidence_summary or ''}"
    if any(term in text for term in ("回撤", "波动率", "收盘", "收益", "均线")):
        return "deterministic_price_metrics"
    if any(term in text for term in ("营收", "净利润", "资产负债率", "现金流/")):
        return "structured_fundamentals"
    if any(term in text for term in ("财报质量", "会计口径", "报表矛盾")):
        return "deterministic_earnings_quality"
    if any(term in text for term in ("科目", "存货", "应收", "经营现金流")):
        return "deterministic_financial_driver"
    if any(term in text for term in ("主营结构", "收入占比", "集中度")):
        return "deterministic_business_structure"
    if any(term in text for term in ("公告", "监管", "官方事件")):
        return "deterministic_event_timeline"
    if any(term in text for term in ("股东户数", "十大股东", "持有人")):
        return "structured_shareholder_data"
    if any(term in text for term in ("一致预期", "研报", "EPS", "评级分布")):
        return "structured_analyst_expectations"
    if any(term in text for term in ("历史走查", "历史同类样本")):
        return "deterministic_outlook_calibration"
    if any(term in text for term in ("证据覆盖", "资料缺口", "证据不完整")):
        return "research_frame"
    return "research_frame"


def _source_metadata(
    evidence: Mapping[str, Any], source_key: str, evidence_summary: str | None
) -> dict[str, Any]:
    profile = dict(SOURCE_PROFILES.get(source_key) or SOURCE_PROFILES["research_frame"])
    generated_at = evidence.get("generated_at")
    metadata: dict[str, Any] = {
        **profile,
        "source_url": None,
        "published_at": None,
        "retrieved_at": generated_at,
        "data_time": None,
        "report_period": None,
        "trade_date": None,
    }

    if source_key == "deterministic_price_metrics":
        quote = evidence.get("current_quote") or {}
        provenance = evidence.get("provenance") or {}
        data_time = provenance.get("market_timestamp") or quote.get(
            "market_timestamp"
        )
        metadata.update(
            {
                "source_name": provenance.get("source")
                or quote.get("source")
                or profile["source_name"],
                "source_url": provenance.get("source_url")
                or quote.get("source_url"),
                "retrieved_at": provenance.get("fetched_at")
                or quote.get("fetched_at")
                or generated_at,
                "data_time": data_time,
                "trade_date": str(data_time)[:10] if data_time else None,
            }
        )
    elif source_key == "structured_fundamentals":
        fundamentals = evidence.get("fundamentals") or {}
        latest = (fundamentals.get("summary") or {}).get("latest_report") or {}
        report_period = latest.get("report_date") or latest.get("report_period")
        metadata.update(
            {
                "source_name": latest.get("source") or profile["source_name"],
                "source_url": latest.get("source_url"),
                "published_at": latest.get("announcement_date")
                or latest.get("published_at"),
                "retrieved_at": fundamentals.get("generated_at") or generated_at,
                "data_time": report_period,
                "report_period": report_period,
            }
        )
    elif source_key in {
        "deterministic_earnings_quality",
        "deterministic_financial_driver",
    }:
        module_key = (
            "earnings_quality"
            if source_key == "deterministic_earnings_quality"
            else "financial_drivers"
        )
        module = evidence.get(module_key) or (
            evidence if evidence.get("type") == module_key else {}
        )
        period = module.get("latest_report") or module.get("latest_period") or {}
        document = (module.get("filing_evidence") or {}).get("document") or {}
        report_period = period.get("report_date") or period.get("report_period")
        metadata.update(
            {
                "source_name": document.get("source") or profile["source_name"],
                "source_url": document.get("source_url")
                or document.get("attach_url"),
                "published_at": document.get("published_at")
                or document.get("announcement_date"),
                "retrieved_at": module.get("generated_at") or generated_at,
                "data_time": report_period,
                "report_period": report_period,
            }
        )
    elif source_key == "deterministic_business_structure":
        module = evidence.get("business_structure") or (
            evidence if evidence.get("type") == "business_structure" else {}
        )
        report_period = module.get("anchor_report_date")
        sources = module.get("sources") or []
        first_source = sources[0] if sources and isinstance(sources[0], Mapping) else {}
        metadata.update(
            {
                "source_name": first_source.get("source") or profile["source_name"],
                "source_url": first_source.get("source_url"),
                "retrieved_at": module.get("latest_fetched_at")
                or module.get("generated_at")
                or generated_at,
                "data_time": report_period,
                "report_period": report_period,
            }
        )
    elif source_key == "deterministic_event_timeline":
        module = evidence.get("event_timeline") or (
            evidence if evidence.get("type") == "event_timeline" else {}
        )
        events = [
            *(module.get("supportive_events") or []),
            *(module.get("risk_events") or []),
            *(module.get("events") or []),
        ]
        match = _matching_event(events, evidence_summary)
        published_at = (
            match.get("published_at")
            or match.get("event_date")
            or module.get("as_of_date")
        )
        metadata.update(
            {
                "source_name": match.get("source") or profile["source_name"],
                "source_url": match.get("source_url") or match.get("url"),
                "published_at": published_at,
                "retrieved_at": module.get("generated_at") or generated_at,
                "data_time": published_at,
            }
        )
    elif source_key in {
        "structured_shareholder_data",
        "structured_analyst_expectations",
    }:
        module_key = (
            "shareholder_structure"
            if source_key == "structured_shareholder_data"
            else "analyst_expectations"
        )
        module = evidence.get(module_key) or (
            evidence if evidence.get("type") == module_key else {}
        )
        sources = module.get("sources") or []
        first_source = sources[0] if sources and isinstance(sources[0], Mapping) else {}
        data_time = (
            module.get("holder_count_as_of")
            or module.get("top10_report_date")
            or module.get("as_of_date")
            or module.get("latest_report_date")
        )
        metadata.update(
            {
                "source_name": first_source.get("source")
                or first_source.get("name")
                or profile["source_name"],
                "source_url": first_source.get("source_url")
                or first_source.get("url"),
                "retrieved_at": module.get("latest_fetched_at")
                or module.get("source_fetched_at")
                or module.get("generated_at")
                or generated_at,
                "data_time": data_time,
                "report_period": data_time,
            }
        )
    elif source_key == "eastmoney_guba_heuristic_weak":
        sentiment = (evidence.get("a_share_information") or {}).get("sentiment") or {}
        metadata.update(
            {
                "retrieved_at": sentiment.get("fetched_at") or generated_at,
                "data_time": sentiment.get("fetched_at") or generated_at,
            }
        )
    elif source_key == "deterministic_outlook_calibration":
        module = evidence.get("outlook_calibration") or {}
        metadata.update(
            {
                "retrieved_at": module.get("generated_at") or generated_at,
                "data_time": module.get("history_last"),
                "trade_date": module.get("history_last"),
            }
        )

    confidence = metadata["coverage_confidence"]
    metadata["coverage_status"] = {
        "high": "sufficient",
        "medium": "partial",
        "low": "insufficient",
    }[confidence]
    metadata["limitations"] = list(dict.fromkeys(metadata.get("limitations") or []))
    return metadata


def _matching_event(
    events: list[Mapping[str, Any]], evidence_summary: str | None
) -> Mapping[str, Any]:
    text = str(evidence_summary or "")
    for item in events:
        title = str(item.get("title") or "").strip()
        if title and title in text:
            return item
    return events[0] if events else {}


def _invalidation_conditions(
    evidence: Mapping[str, Any], claims: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    outlook = evidence.get("conditional_outlook") or {}
    price_claim_ids = [
        item["id"]
        for item in claims
        if item.get("source_key") == "deterministic_price_metrics"
    ]
    related_ids = price_claim_ids or [item["id"] for item in claims[:4]]
    output: list[dict[str, Any]] = []
    invalidation = str(outlook.get("invalidation") or "").strip()
    if invalidation:
        output.append(
            {
                "id": _stable_id("invalidation", invalidation),
                "kind": "overall_invalidation",
                "condition": invalidation,
                "meaning": "条件出现后必须重新计算并复核当前研究判断。",
                "related_claim_ids": related_ids,
            }
        )
    for scenario in outlook.get("scenarios") or []:
        name = str(scenario.get("name") or scenario.get("label") or "")
        if not any(term in name for term in ("下行", "失效", "风险")):
            continue
        condition = str(scenario.get("condition") or "").strip()
        if not condition:
            continue
        output.append(
            {
                "id": _stable_id("invalidation", {"name": name, "condition": condition}),
                "kind": "scenario_invalidation",
                "label": name or None,
                "condition": condition,
                "meaning": str(scenario.get("meaning") or "").replace(
                    "风险与仓位纪律", "风险证据与当前研究判断"
                )
                or None,
                "related_claim_ids": related_ids,
            }
        )
    return output[:6]


def _stable_id(prefix: str, value: Any) -> str:
    digest = hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode(
            "utf-8"
        )
    ).hexdigest()[:20]
    return f"{prefix}-{digest}"
