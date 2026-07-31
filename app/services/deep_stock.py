from __future__ import annotations

from typing import Any

from app.catalog import RESEARCH_TARGETS, normalize_symbol
from app.db import Database
from app.services.research_claims import build_research_claim_ledger
from app.services.security_master import SecurityMasterService
from app.utils import utc_now


class DeepStockConversationConflict(ValueError):
    """A stock workspace cannot silently replace or share its primary chat."""


class DeepStockResearchService:
    """Persist one guided stock-research space per user and security."""

    WORKFLOW_VERSION = "guided_deep_stock_v1"
    STAGE_COMPLETION_GATE_VERSION = "stage_completion_gate_v2"
    RUN_NOT_ADVANCED_NOTICE = (
        "本轮没有形成可复核的新结论，研究进度保持不变；"
        "可重新发起研究或继续核验下一条证据。"
    )
    RUN_EVIDENCE_REVIEW_NOTICE = "本轮结论的证据引用仍需补充核验，研究进度保持不变。"
    CORE_EVIDENCE_REVIEW_NOTICE = (
        "本轮核心证据尚不完整，研究进度保持不变；请先补齐下一条关键证据。"
    )
    STAGES = (
        {
            "key": "original_thesis",
            "label": "原始研究逻辑",
            "description": "先记录用户为什么关注这家公司，以及最初依赖哪些事实。",
            "question": "你最初为什么关注这家公司？请写出最重要的两三个事实和你最担心的反例。",
        },
        {
            "key": "company_industry",
            "label": "公司与行业",
            "description": "核验业务结构、收入与毛利来源、行业位置和竞争约束。",
            "question": "请基于已取得的业务与行业证据，解释这家公司靠什么赚钱、行业位置如何，哪些环节仍缺证。",
        },
        {
            "key": "financial_cashflow",
            "label": "财务与现金流",
            "description": "比较同类报告期的增长、利润率、营运资金与现金流质量。",
            "question": "请拆解这家公司最新财报的利润与现金流，区分机械影响、公司原文解释和未确认因果。",
        },
        {
            "key": "valuation_peers",
            "label": "估值与同行",
            "description": "使用固定同行与一致口径比较，不输出目标价。",
            "question": "请比较这家公司与固定同行的估值和经营差异，说明口径、样本边界和不能下结论的部分。",
        },
        {
            "key": "events_sentiment",
            "label": "事件与情绪",
            "description": "整理公告、监管文件、新闻与社区样本，区分强弱证据。",
            "question": "请梳理近期重要事件和情绪分歧，区分官方披露、媒体线索与社区弱证据。",
        },
        {
            "key": "counterevidence",
            "label": "反方证据",
            "description": "主动寻找与原逻辑冲突的事实，而不是只补强看多或看空叙事。",
            "question": "只看反方证据：哪些事实最可能推翻当前研究逻辑？哪些只是价格波动而不是基本面反证？",
        },
        {
            "key": "invalidation_next",
            "label": "什么时候需要重新判断",
            "description": "明确哪些可观察事实会推翻当前判断，并把未决问题变成持续跟踪任务。",
            "question": "请说明什么情况会推翻当前研究判断、仍有哪些证据缺口，以及下一次最值得核验的事实。",
        },
    )

    _THESIS_TERMS = ("原逻辑", "关注理由", "最初", "看好", "担心", "因为")
    _INVALIDATION_TERMS = (
        "失效",
        "证伪",
        "推翻",
        "下一步",
        "下一证据",
        "还要验证",
        "需要核验",
        "观察条件",
    )
    COVERAGE_DIMENSIONS = (
        ("company_operating", "公司经营"),
        ("financial_quality", "财务质量"),
        ("industry_relative", "行业与相对表现"),
        ("valuation", "估值"),
        ("technical_state", "技术状态"),
        ("risk_events", "风险事件"),
    )
    STAGE_COVERAGE_GATES = {
        "company_industry": ("company_operating",),
        "financial_cashflow": ("financial_quality",),
        "valuation_peers": ("valuation", "industry_relative"),
        "events_sentiment": ("risk_events",),
        "counterevidence": ("risk_events",),
        "invalidation_next": ("risk_events",),
    }
    COVERAGE_STATUS_RANK = {
        "unavailable": 0,
        "insufficient": 1,
        "partial": 2,
        "sufficient": 3,
    }
    ANALYSIS_BOARD_MODULES = {
        "market": {"market"},
        "news": {"company_information", "event_timeline"},
        "sentiment": {"company_information"},
        "fundamentals": {
            "fundamentals",
            "earnings_quality",
            "financial_drivers",
            "business_structure",
            "shareholder_structure",
        },
        "peers": {"peer_comparison"},
        "analyst_expectations": {"analyst_expectations"},
        "debate": set(),
    }
    ANALYSIS_BOARD_LABELS = {
        "行情结构",
        "公告、新闻与事件脉络",
        "情绪与分歧",
        "基本面与现金流",
        "同行估值与经营",
        "分析师预期与研报",
        "多空与风险委员会",
    }
    BASE_MISSING_INFORMATION_MODULES = {
        "公司最新公告尚未接入": {"company_information", "event_timeline"},
        "结构化财务与估值数据尚未接入": {
            "fundamentals",
            "earnings_quality",
            "financial_drivers",
            "peer_comparison",
        },
        "行业供需与一致预期尚未接入": {
            "analyst_expectations",
            "peer_comparison",
        },
        "新闻与事件影响尚未接入": {"company_information", "event_timeline"},
    }
    EVIDENCE_PERSISTED_RUN_STATUSES = {"completed", "preview"}
    STAGE_ADVANCING_RUN_STATUSES = {"completed"}
    STAGE_CLAIM_SOURCE_KEYS = {
        "company_industry": {"deterministic_business_structure"},
        "financial_cashflow": {
            "structured_fundamentals",
            "deterministic_earnings_quality",
            "deterministic_financial_driver",
        },
        "events_sentiment": {
            "deterministic_event_timeline",
            "eastmoney_guba_heuristic_weak",
        },
        "counterevidence": None,
        "invalidation_next": None,
    }

    def __init__(self, database: Database):
        self.database = database
        self.security_master = SecurityMasterService(database)

    def list_sessions(self, user_id: str, limit: int = 50) -> dict[str, Any]:
        items = [
            self._public_session(self._reconcile_legacy_stages(user_id, item))
            for item in self.database.list_deep_stock_sessions(user_id, limit=limit)
        ]
        return {
            "method": self.WORKFLOW_VERSION,
            "items": items,
            "summary": {
                "total": len(items),
                "completed": sum(item["status"] == "completed" for item in items),
                "active": sum(item["status"] == "active" for item in items),
            },
        }

    def get_or_create(
        self,
        user_id: str,
        symbol: str,
        conversation_id: str | None = None,
        entry_context: dict[str, Any] | None = None,
        quality_scope: str = "user",
    ) -> dict[str, Any]:
        canonical = normalize_symbol(symbol)
        research_entry = self._normalize_research_entry(entry_context)
        existing = self.database.get_deep_stock_session(user_id, canonical)
        if existing is not None:
            existing = self._reconcile_legacy_stages(user_id, existing)
            if conversation_id and str(existing["conversation_id"]) != conversation_id:
                raise DeepStockConversationConflict(
                    "这只股票已经绑定长期研究对话，不能静默替换主会话"
                )
        bound_conversation = None
        if conversation_id:
            conversation_session = self.database.get_deep_stock_session_by_conversation(
                user_id, conversation_id
            )
            if (
                conversation_session is not None
                and str(conversation_session["symbol"]) != canonical
            ):
                raise DeepStockConversationConflict(
                    "这个研究对话已经属于另一只股票，不能重复绑定"
                )
            bound_conversation = self.database.get_conversation(
                user_id, conversation_id
            )
            if (
                bound_conversation is None
                or bound_conversation.get("status") != "active"
            ):
                raise ValueError("要绑定的研究对话不存在或已归档")
        elif existing:
            bound_conversation = self.database.get_conversation(
                user_id, str(existing["conversation_id"])
            )
            if bound_conversation and bound_conversation.get("status") != "active":
                bound_conversation = None
        if bound_conversation is None:
            display_name = self.security_master.display_name(
                canonical,
                (research_entry or {}).get("display_name"),
                self._display_name(user_id, canonical),
            )
            bound_conversation = self.database.create_conversation(
                user_id,
                f"个股研究｜{display_name}",
                quality_scope=quality_scope,
            )

        report = self.database.latest_research_report(canonical)
        name = self.security_master.display_name(
            canonical,
            (research_entry or {}).get("display_name"),
            self._display_name(user_id, canonical),
        )
        current_title = str(bound_conversation.get("title") or "")
        automatic_titles = {
            f"个股研究｜{canonical}",
            f"个股研究｜{canonical.split('.', 1)[0]}",
            f"个股研究｜{str((existing or {}).get('name') or '').strip()}",
            f"个股研究｜{str((report or {}).get('name') or '').strip()}",
        }
        automatic_titles.discard("个股研究｜")
        desired_title = f"个股研究｜{name}"
        if current_title != desired_title and (
            conversation_id is not None or current_title in automatic_titles
        ):
            bound_conversation = (
                self.database.rename_conversation(
                    user_id,
                    str(bound_conversation["id"]),
                    desired_title,
                )
                or bound_conversation
            )
        if existing is None:
            watchlist = self.database.get_watchlist_item(user_id, canonical)
            thesis = str((watchlist or {}).get("thesis") or "").strip()
            stages = self._new_stages(thesis)
            evidence_modules: dict[str, Any] = {}
            if thesis:
                evidence_modules["original_thesis"] = {
                    "source": "watchlist_thesis",
                    "summary": thesis,
                    "updated_at": utc_now(),
                }
            unresolved = self._report_unresolved(report)
        else:
            stages = list(existing.get("stages") or [])
            evidence_modules = dict(existing.get("evidence_modules") or {})
            unresolved = self._dedupe(
                [
                    *(existing.get("unresolved_items") or []),
                    *self._report_unresolved(report),
                ]
            )
        if research_entry is not None:
            evidence_modules["screening_entry"] = research_entry
            unresolved = self._dedupe(
                [
                    *unresolved,
                    *[
                        f"筛选入口待核验：{item}"
                        for item in research_entry.get("missing_fields") or []
                    ],
                ]
            )
        stages = self._normalize_stage_statuses(stages)
        status = (
            "completed"
            if stages and all(item.get("status") == "completed" for item in stages)
            else "active"
        )
        next_question = self._next_question(stages, name)
        if (
            research_entry is not None
            and (
                next(
                    (
                        item
                        for item in stages
                        if item.get("status") in {"in_progress", "needs_review"}
                    ),
                    {},
                )
            ).get("key")
            == "original_thesis"
        ):
            focus = str(research_entry.get("research_focus") or "").strip()
            next_question = (
                f"请先核验{name}命中“{research_entry['source_label']}”的理由。"
                + (f"当前优先问题是：{focus}" if focus else "")
                + "同时检查反方证据和缺失项，再形成自己的关注理由。"
            )
        session = self.database.save_deep_stock_session(
            user_id=user_id,
            symbol=canonical,
            name=name,
            conversation_id=str(bound_conversation["id"]),
            workflow_version=self.WORKFLOW_VERSION,
            status=status,
            stages=stages,
            evidence_modules=evidence_modules,
            unresolved_items=unresolved[:12],
            next_question=next_question,
            latest_run_id=(existing or {}).get("latest_run_id"),
            latest_report_id=(report or {}).get("id"),
            completed_at=(existing or {}).get("completed_at")
            or (utc_now() if status == "completed" else None),
        )
        latest_run_id = session.get("latest_run_id")
        if existing and latest_run_id:
            latest_run = self.database.get_run(str(latest_run_id), user_id)
            if (
                latest_run
                and latest_run.get("status") in self.EVIDENCE_PERSISTED_RUN_STATUSES
            ):
                input_data = latest_run.get("input") or {}
                reconciled = self.observe_chat(
                    user_id=user_id,
                    conversation_id=str(session["conversation_id"]),
                    symbol=canonical,
                    intent=str(latest_run.get("intent") or "stock_research"),
                    message=str(input_data.get("message") or ""),
                    run=latest_run,
                    evidence=latest_run.get("evidence") or {},
                )
                if reconciled is not None:
                    return reconciled
        return self._public_session(session)

    @staticmethod
    def _normalize_research_entry(
        entry_context: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if not isinstance(entry_context, dict):
            return None
        source_kind = str(entry_context.get("source_kind") or "").strip()
        if source_kind not in {"stock_screen", "li_zong_strategy"}:
            return None

        def clean_text(value: Any, limit: int) -> str | None:
            text = " ".join(str(value or "").split()).strip()
            return text[:limit] if text else None

        def clean_items(value: Any, limit: int) -> list[str]:
            if not isinstance(value, list):
                return []
            items = [clean_text(item, 160) for item in value]
            return list(dict.fromkeys(item for item in items if item))[:limit]

        source_label = clean_text(entry_context.get("source_label"), 80)
        if source_label is None:
            source_label = "研究候选筛选"
        matched_reasons = clean_items(entry_context.get("matched_reasons"), 12)
        research_focus = clean_text(entry_context.get("research_focus"), 300)
        attention_flags = clean_items(entry_context.get("attention_flags"), 4)
        missing_fields = clean_items(entry_context.get("missing_fields"), 8)
        normalized = {
            "source_kind": source_kind,
            "source_label": source_label,
            "display_name": clean_text(entry_context.get("display_name"), 80),
            "industry": clean_text(entry_context.get("industry"), 80),
            "profile_key": clean_text(entry_context.get("profile_key"), 60),
            "as_of_date": clean_text(entry_context.get("as_of_date"), 32),
            "candidate_status": clean_text(entry_context.get("candidate_status"), 40),
            "matched_reasons": matched_reasons,
            "missing_fields": missing_fields,
            "status": "user_selected_context",
            "limitations": [
                "这是用户从筛选结果进入研究空间时保存的研究线索，"
                "不会直接完成研究阶段，仍需用正式行情、财务和公告证据核验。"
            ],
            "updated_at": utc_now(),
        }
        if research_focus:
            normalized["research_focus"] = research_focus
        if attention_flags:
            normalized["attention_flags"] = attention_flags
        return normalized

    def get(self, user_id: str, symbol: str) -> dict[str, Any] | None:
        canonical = normalize_symbol(symbol)
        session = self.database.get_deep_stock_session(user_id, canonical)
        if session is not None:
            session = self._reconcile_legacy_stages(user_id, session)
        return self._public_session(session) if session else None

    def evidence_coverage_packet(
        self,
        evidence: dict[str, Any],
        *,
        intent: str | None = None,
    ) -> dict[str, Any]:
        """Expose the PRD's six evidence dimensions to the research Agent."""

        coverage = self._coverage_dimensions(evidence, intent=intent)
        counts = {
            status: sum(item["coverage_status"] == status for item in coverage.values())
            for status in ("sufficient", "partial", "insufficient", "unavailable")
        }
        return {
            "dimensions": list(coverage.values()),
            "summary": {
                **counts,
                "total": len(coverage),
                "refresh_attention": 0,
            },
            "tasks": self._coverage_tasks(coverage),
            "boundary": (
                "六维覆盖只表示当前已取得证据的完整程度；"
                "不构成公司评分、投资评级或买卖信号。"
            ),
        }

    def observe_chat(
        self,
        *,
        user_id: str,
        conversation_id: str,
        symbol: str | None,
        intent: str,
        message: str,
        run: dict[str, Any],
        evidence: dict[str, Any],
    ) -> dict[str, Any] | None:
        session = self.database.get_deep_stock_session_by_conversation(
            user_id, conversation_id
        )
        if session is None:
            return None
        session = self._reconcile_legacy_stages(user_id, session)
        if symbol and normalize_symbol(symbol) != session["symbol"]:
            return self._public_session(session)
        if intent == "market_brief":
            # A user may ask about the broad market while a stock-bound
            # conversation is open. Keep the answer in conversation history,
            # but never let market-only evidence advance or overwrite the
            # single-stock research workflow.
            return self._public_session(session)

        stages = list(session.get("stages") or [])
        evidence_modules = dict(session.get("evidence_modules") or {})
        unresolved = list(session.get("unresolved_items") or [])
        run_status = str(run.get("status") or "")
        run_id = run.get("id")
        now = utc_now()
        coverage_override = self._repair_stale_coverage_observations(
            self._coverage_from_modules(evidence_modules),
            user_id=user_id,
        )
        stage_gate_allowed, stage_gate_reason = self._stage_advance_gate(
            run,
            evidence,
        )
        unresolved = [item for item in unresolved if not self._is_run_gate_notice(item)]
        if run_status not in self.EVIDENCE_PERSISTED_RUN_STATUSES:
            unresolved.append(self.RUN_NOT_ADVANCED_NOTICE)
        else:
            coverage = self._coverage_dimensions(evidence, intent=intent)
            if run_status in self.STAGE_ADVANCING_RUN_STATUSES and stage_gate_allowed:
                assessments = self._stage_assessments(
                    intent=intent,
                    message=message,
                    evidence=evidence,
                )
                for stage in stages:
                    key = str(stage.get("key"))
                    assessment = assessments.get(key)
                    if assessment is None or stage.get("status") == "completed":
                        continue
                    stage_status = str(assessment["status"])
                    stage.update(
                        {
                            "status": stage_status,
                            "review_status": stage_status,
                            "review_reasons": assessment["review_reasons"],
                            "source_refs": assessment["source_refs"],
                            "coverage_gate": assessment["coverage_gate"],
                            "last_evaluated_at": now,
                            "last_evaluated_run_id": run_id,
                        }
                    )
                    if stage_status == "completed":
                        stage.update(
                            {
                                "completed_at": now,
                                "run_id": run_id,
                                "evidence_modules": assessment["modules"],
                                "completion_gate_version": (
                                    self.STAGE_COMPLETION_GATE_VERSION
                                ),
                            }
                        )
                    evidence_modules[key] = {
                        "run_id": run_id,
                        "intent": intent,
                        "status": stage_status,
                        "modules": assessment["modules"],
                        "coverage_gate": assessment["coverage_gate"],
                        "source_refs": assessment["source_refs"],
                        "review_reasons": assessment["review_reasons"],
                        "updated_at": now,
                    }
            elif run_status in self.STAGE_ADVANCING_RUN_STATUSES:
                unresolved.append(stage_gate_reason)
            coverage_override = self._merge_coverage_snapshot(
                previous=coverage_override,
                current=coverage,
                run_id=str(run_id or ""),
                intent=intent,
                observed_at=now,
            )
            evidence_modules["_coverage_snapshot"] = {
                "dimensions": list(coverage_override.values()),
                "updated_at": now,
                "run_id": run_id,
                "intent": intent,
            }
            evidence_modules["_coverage_history"] = self._append_coverage_history(
                evidence_modules.get("_coverage_history"),
                coverage_override,
                run_id=str(run_id or ""),
                intent=intent,
                observed_at=now,
            )
            unresolved.extend(
                self._evidence_unresolved(evidence, include_coverage=False)
            )
            coverage_labels = {label for _, label in self.COVERAGE_DIMENSIONS}
            unresolved = [
                item
                for item in unresolved
                if not any(
                    str(item).startswith(f"{label}：")
                    or str(item).startswith(f"证据覆盖｜{label}：")
                    for label in coverage_labels
                )
            ]
            unresolved.extend(
                f"证据覆盖｜{task['label']}：{task['next_step']}"
                for task in self._coverage_tasks(coverage_override)
            )

        stages = self._normalize_stage_statuses(stages)
        status = (
            "completed"
            if stages and all(item.get("status") == "completed" for item in stages)
            else "active"
        )
        report = self.database.latest_research_report(str(session["symbol"]))
        saved = self.database.save_deep_stock_session(
            user_id=user_id,
            symbol=str(session["symbol"]),
            name=str(session["name"]),
            conversation_id=conversation_id,
            workflow_version=self.WORKFLOW_VERSION,
            status=status,
            stages=stages,
            evidence_modules=evidence_modules,
            unresolved_items=self._dedupe(unresolved)[-12:],
            next_question=self._next_question(stages, str(session["name"])),
            latest_run_id=run_id or session.get("latest_run_id"),
            latest_report_id=(report or {}).get("id")
            or session.get("latest_report_id"),
            completed_at=utc_now() if status == "completed" else None,
        )
        return self._public_session(
            saved,
            evidence_override=evidence,
            coverage_override=coverage_override or None,
        )

    def _new_stages(self, thesis: str) -> list[dict[str, Any]]:
        now = utc_now()
        stages = []
        for index, definition in enumerate(self.STAGES, start=1):
            completed = definition["key"] == "original_thesis" and bool(thesis)
            stages.append(
                {
                    **definition,
                    "index": index,
                    "status": "completed" if completed else "pending",
                    "completed_at": now if completed else None,
                    "run_id": None,
                    "evidence_modules": ["watchlist_thesis"] if completed else [],
                }
            )
        return self._normalize_stage_statuses(stages)

    def _stage_assessments(
        self, *, intent: str, message: str, evidence: dict[str, Any]
    ) -> dict[str, dict[str, Any]]:
        assessments: dict[str, dict[str, Any]] = {}
        coverage = self._coverage_dimensions(evidence, intent=intent)

        def assess(
            stage_key: str,
            *,
            addressed: bool,
            modules: list[str],
            extra_reasons: list[str] | None = None,
        ) -> None:
            if not addressed:
                return
            required = self.STAGE_COVERAGE_GATES.get(stage_key, ())
            coverage_gate = {key: coverage[key]["coverage_status"] for key in required}
            reasons = list(extra_reasons or [])
            if not modules:
                reasons.append("本阶段核心证据包缺失或不可用。")
            missing_dimensions = [
                dict(self.COVERAGE_DIMENSIONS)[key]
                for key, status in coverage_gate.items()
                if status != "sufficient"
            ]
            if missing_dimensions:
                reasons.append(
                    f"证据覆盖尚未达到完成门槛：{'、'.join(missing_dimensions)}。"
                )
            source_refs = self._stage_source_refs(
                evidence,
                stage_key=stage_key,
                modules=modules,
                intent=intent,
            )
            if modules and not source_refs:
                reasons.append("本阶段尚缺可追溯来源或明确用户输入。")
            assessments[stage_key] = {
                "status": "completed" if not reasons else "needs_review",
                "modules": modules,
                "coverage_gate": coverage_gate,
                "source_refs": source_refs,
                "review_reasons": self._dedupe(reasons),
            }

        if any(term in message for term in self._THESIS_TERMS):
            assessments["original_thesis"] = {
                "status": "completed",
                "modules": ["user_statement"],
                "coverage_gate": {},
                "source_refs": ["用户输入"],
                "review_reasons": [],
            }

        company_modules = self._present_modules(
            evidence, ("business_structure", "research_frame")
        )
        if intent == "business_structure" and self._packet_available(evidence):
            company_modules = ["business_structure"]
        assess(
            "company_industry",
            addressed=intent in {"stock_research", "business_structure"},
            modules=company_modules,
        )

        financial_modules = self._present_modules(
            evidence, ("fundamentals", "earnings_quality", "financial_drivers")
        )
        if intent in {
            "earnings_quality",
            "financial_drivers",
        } and self._packet_available(evidence):
            financial_modules = [intent]
        assess(
            "financial_cashflow",
            addressed=intent
            in {"stock_research", "earnings_quality", "financial_drivers"},
            modules=financial_modules,
        )

        valuation_modules = self._present_modules(
            evidence, ("peer_comparison", "analyst_expectations")
        )
        if intent == "analyst_expectations" and self._packet_available(evidence):
            valuation_modules = ["analyst_expectations"]
        assess(
            "valuation_peers",
            addressed=intent in {"stock_research", "analyst_expectations"},
            modules=valuation_modules,
        )

        event_modules = self._present_modules(
            evidence,
            ("event_timeline", "a_share_information", "global_information"),
        )
        if intent == "event_timeline" and self._packet_available(evidence):
            event_modules = ["event_timeline"]
        assess(
            "events_sentiment",
            addressed=intent in {"stock_research", "event_timeline"},
            modules=event_modules,
        )

        counter_modules = self._present_modules(
            evidence, ("evidence_debate", "analysis_board")
        )
        assess(
            "counterevidence",
            addressed=intent == "stock_research",
            modules=counter_modules,
            extra_reasons=(
                []
                if self._counterevidence_sufficient(evidence)
                else ["尚未取得具体反方证据或待验证风险主张。"]
            ),
        )

        if any(term in message for term in self._INVALIDATION_TERMS):
            invalidation_modules = self._present_modules(
                evidence,
                (
                    "research_frame",
                    "analysis_board",
                    "conditional_outlook",
                    "evidence_debate",
                ),
            )
            assess(
                "invalidation_next",
                addressed=True,
                modules=invalidation_modules,
                extra_reasons=(
                    []
                    if self._invalidation_sufficient(evidence)
                    else ["什么时候需要重新判断以及下一证据尚未形成可核验闭环。"]
                ),
            )
        return assessments

    @staticmethod
    def _stage_advance_gate(
        run: dict[str, Any], evidence: dict[str, Any]
    ) -> tuple[bool, str]:
        if str(run.get("status") or "") != "completed":
            return False, DeepStockResearchService.RUN_NOT_ADVANCED_NOTICE
        usage = run.get("usage") or {}
        output_guard = usage.get("output_guard") if isinstance(usage, dict) else None
        if not isinstance(output_guard, dict) or output_guard.get("passed") is not True:
            return (
                False,
                DeepStockResearchService.RUN_EVIDENCE_REVIEW_NOTICE,
            )
        if not DeepStockResearchService._packet_available(evidence):
            return (
                False,
                DeepStockResearchService.CORE_EVIDENCE_REVIEW_NOTICE,
            )
        return True, ""

    @classmethod
    def _is_run_gate_notice(cls, value: Any) -> bool:
        text = str(value or "")
        return text in {
            cls.RUN_NOT_ADVANCED_NOTICE,
            cls.RUN_EVIDENCE_REVIEW_NOTICE,
            cls.CORE_EVIDENCE_REVIEW_NOTICE,
        } or any(
            term in text
            for term in (
                "完整模型与输出校验",
                "最终输出守卫",
                "核心证据包缺失或失败",
                "最近一轮研究未完成",
            )
        )

    @classmethod
    def _public_issue_text(cls, value: Any) -> str:
        text = " ".join(str(value or "").split())
        if not text:
            return ""
        if text == cls.CORE_EVIDENCE_REVIEW_NOTICE:
            return text
        if "核心证据包缺失或失败" in text:
            return cls.CORE_EVIDENCE_REVIEW_NOTICE
        if cls._is_run_gate_notice(text):
            return cls.RUN_NOT_ADVANCED_NOTICE
        if any(
            term in text
            for term in (
                "完成 Run",
                "历史 Run",
                "当前证据门禁",
                "更严格的证据门禁",
                "旧版规则完成",
            )
        ):
            return "部分历史研究阶段需要用当前证据重新核验。"
        return text

    @classmethod
    def _public_issue_list(cls, values: list[Any]) -> list[str]:
        output: list[str] = []
        for value in values:
            text = cls._public_issue_text(value)
            if text and text not in output:
                output.append(text)
        return output

    def _stage_source_refs(
        self,
        evidence: dict[str, Any],
        *,
        stage_key: str,
        modules: list[str],
        intent: str,
    ) -> list[str]:
        refs: list[str] = []
        for module_key in modules:
            packet = evidence.get(module_key)
            if packet in (None, {}, [], "") and module_key == intent:
                packet = evidence
            refs.extend(self._collect_source_refs(packet))

        ledger = evidence.get("research_claims")
        if not isinstance(ledger, dict):
            ledger = build_research_claim_ledger(evidence)
        allowed_source_keys = self.STAGE_CLAIM_SOURCE_KEYS.get(stage_key, set())
        for claim in ledger.get("claims") or []:
            source_key = str(claim.get("source_key") or "")
            if (
                allowed_source_keys is not None
                and source_key not in allowed_source_keys
            ):
                continue
            source_name = str(claim.get("source_name") or "").strip()
            if source_name:
                refs.append(source_name)
            source_url = str(claim.get("source_url") or "").strip()
            if source_url:
                refs.append(source_url)
        return self._dedupe(refs)[:8]

    @classmethod
    def _collect_source_refs(cls, value: Any, depth: int = 0) -> list[str]:
        if depth > 5 or value in (None, "", [], {}):
            return []
        refs: list[str] = []
        if isinstance(value, dict):
            for key, child in value.items():
                normalized = str(key).lower()
                if normalized in {
                    "source",
                    "source_name",
                    "source_url",
                    "url",
                    "provider",
                } and isinstance(child, (str, int, float)):
                    text = str(child).strip()
                    if text:
                        refs.append(text)
                if normalized == "sources" and isinstance(child, list):
                    for item in child:
                        if isinstance(item, dict):
                            for source_key in ("name", "source", "url", "source_url"):
                                text = str(item.get(source_key) or "").strip()
                                if text:
                                    refs.append(text)
                refs.extend(cls._collect_source_refs(child, depth + 1))
        elif isinstance(value, list):
            for item in value[:30]:
                refs.extend(cls._collect_source_refs(item, depth + 1))
        return cls._dedupe(refs)

    def _coverage_dimensions(
        self, evidence: dict[str, Any], *, intent: str | None = None
    ) -> dict[str, dict[str, Any]]:
        """Build the PRD's six evidence dimensions without model scoring."""

        def packet(key: str) -> dict[str, Any]:
            value = evidence.get(key)
            return value if isinstance(value, dict) else {}

        def has_any(value: dict[str, Any], keys: tuple[str, ...]) -> bool:
            return any(value.get(key) not in (None, {}, [], "") for key in keys)

        def dimension(
            key: str,
            *,
            sources: list[str],
            sufficient: bool,
            partial: bool,
            attempted: bool,
            missing_items: list[str],
            as_of: list[str] | None = None,
        ) -> tuple[str, dict[str, Any]]:
            status = (
                "sufficient"
                if sufficient
                else "partial"
                if partial
                else "insufficient"
                if attempted
                else "unavailable"
            )
            label = dict(self.COVERAGE_DIMENSIONS)[key]
            return key, {
                "key": key,
                "label": label,
                "coverage_status": status,
                "observed_in_run": bool(attempted or sufficient or partial),
                "sources": self._dedupe(sources),
                "missing_items": [] if status == "sufficient" else missing_items,
                "as_of": self._dedupe(as_of or []),
            }

        business = packet("business_structure")
        direct_business = intent == "business_structure" and self._packet_available(
            evidence
        )
        business_content = direct_business or has_any(
            business,
            (
                "rows",
                "dimensions",
                "key_changes",
                "business_profile",
                "anchor_report_date",
            ),
        )
        company_sources = []
        if business_content:
            company_sources.append("主营与业务结构")
        company = dimension(
            "company_operating",
            sources=company_sources,
            sufficient=business_content,
            partial=False,
            attempted=bool(business),
            missing_items=["需要可核验的主营构成、收入或毛利来源证据。"],
            as_of=[
                str(value)
                for value in (
                    business.get("anchor_report_date"),
                    business.get("latest_fetched_at"),
                )
                if value
            ],
        )

        fundamentals = packet("fundamentals")
        earnings = packet("earnings_quality")
        drivers = packet("financial_drivers")
        direct_financial = intent in {
            "earnings_quality",
            "financial_drivers",
        } and self._packet_available(evidence)
        fundamental_content = has_any(
            fundamentals,
            ("summary", "financial_periods", "statements", "valuation"),
        )
        earnings_content = has_any(
            earnings,
            ("factors", "supports", "contradictions", "report_period"),
        )
        driver_content = has_any(
            drivers,
            (
                "confirmed_mechanical_drivers",
                "plausible_clues",
                "company_explanations",
                "unresolved_causes",
                "report_period",
            ),
        )
        financial_source_count = sum(
            (fundamental_content, earnings_content, driver_content)
        )
        financial = dimension(
            "financial_quality",
            sources=[
                label
                for present, label in (
                    (fundamental_content, "结构化财务"),
                    (earnings_content, "盈利质量"),
                    (driver_content, "利润与现金流驱动"),
                    (direct_financial, "专项财务分析"),
                )
                if present
            ],
            sufficient=direct_financial or financial_source_count >= 2,
            partial=financial_source_count == 1,
            attempted=bool(fundamentals or earnings or drivers),
            missing_items=["需要同类报告期财务、利润质量和现金流证据交叉核验。"],
            as_of=self._collect_dates(
                fundamentals,
                earnings,
                drivers,
                keys=("report_period", "report_date", "notice_date", "fetched_at"),
            ),
        )

        peers = packet("peer_comparison")
        peer_operating = (
            peers.get("operating_comparison")
            if isinstance(peers.get("operating_comparison"), dict)
            else {}
        )
        expectations = packet("analyst_expectations")
        market_context = packet("stock_market_context")
        exact_industry_index = (
            market_context.get("exact_industry_index")
            if isinstance(market_context.get("exact_industry_index"), dict)
            else {}
        )
        peer_content = has_any(peers, ("metrics", "peers")) or has_any(
            peer_operating, ("metrics", "peers", "coverage")
        )
        exact_industry_content = (
            exact_industry_index.get("status") == "same_market_date"
            and exact_industry_index.get("return_1d_pct") is not None
            and exact_industry_index.get("stock_return_1d_pct") is not None
            and exact_industry_index.get("stock_minus_industry_pct") is not None
        )
        expectation_industry = bool(
            expectations.get("industry")
            or expectations.get("industry_index")
            or expectations.get("latest_reports")
        )
        direct_expectations = (
            intent == "analyst_expectations" and self._packet_available(evidence)
        )
        industry = dimension(
            "industry_relative",
            sources=[
                label
                for present, label in (
                    (peer_content, "固定同行比较"),
                    (exact_industry_content, "同日官方行业指数对照"),
                    (expectation_industry, "行业与分析师覆盖"),
                    (direct_expectations, "分析师预期专项"),
                )
                if present
            ],
            sufficient=peer_content or exact_industry_content,
            partial=expectation_industry or direct_expectations,
            attempted=bool(peers or expectations or market_context),
            missing_items=["需要固定同行或同日行业相对表现证据。"],
            as_of=self._collect_dates(
                peers,
                expectations,
                exact_industry_index,
                keys=("report_period", "market_timestamp", "fetched_at"),
            )
            + (
                [str(exact_industry_index.get("market_date"))]
                if exact_industry_index.get("market_date")
                else []
            ),
        )

        valuation_packet = (
            fundamentals.get("valuation")
            if isinstance(fundamentals.get("valuation"), dict)
            else {}
        )
        valuation_content = has_any(
            valuation_packet,
            ("price", "pe_ttm", "pb", "market_cap", "market_timestamp"),
        )
        peer_valuation_content = has_any(peers, ("metrics", "peers"))
        valuation = dimension(
            "valuation",
            sources=[
                label
                for present, label in (
                    (valuation_content, "当前估值截面"),
                    (peer_valuation_content, "固定同行估值"),
                )
                if present
            ],
            sufficient=valuation_content and peer_valuation_content,
            partial=valuation_content or peer_valuation_content,
            attempted=bool(valuation_packet or peers),
            missing_items=["需要当前估值与固定同行一致口径比较。"],
            as_of=self._collect_dates(
                valuation_packet,
                peers,
                keys=("market_timestamp", "report_period", "fetched_at"),
            ),
        )

        metrics = packet("metrics")
        technical_fields = (
            "return_20d_pct",
            "ma20",
            "rsi_14",
            "macd_histogram",
            "atr_14_pct",
            "volume_ratio_5_20",
            "volatility_20d_annualized_pct",
            "max_drawdown_60d_pct",
        )
        technical_count = sum(metrics.get(key) is not None for key in technical_fields)
        has_price = metrics.get("latest_close") is not None
        technical = dimension(
            "technical_state",
            sources=["完整日线与技术指标"] if has_price else [],
            sufficient=has_price and technical_count >= 2,
            partial=has_price,
            attempted=bool(metrics),
            missing_items=["需要最近完整日线及至少两项技术结构指标。"],
            as_of=[
                str(value)
                for value in (
                    packet("provenance").get("market_timestamp"),
                    metrics.get("market_timestamp"),
                )
                if value
            ],
        )

        timeline = packet("event_timeline")
        information = packet("a_share_information")
        global_information = packet("global_information")
        direct_event = intent == "event_timeline" and self._packet_available(evidence)
        selected_modules = {
            str(item)
            for item in (packet("research_plan").get("selected_modules") or [])
            if item
        }
        event_selected = bool(
            selected_modules.intersection({"company_information", "event_timeline"})
        )
        event_content = (
            direct_event
            or has_any(timeline, ("events", "sources"))
            or any(
                information.get(key)
                for key in ("announcements", "news", "social_posts")
            )
            or bool(global_information.get("news"))
        )
        debate_content = self._counterevidence_sufficient(evidence)
        risk_attempted = bool(
            direct_event
            or event_selected
            or timeline
            or information
            or global_information
        )
        risk = dimension(
            "risk_events",
            sources=[
                label
                for present, label in (
                    (event_content, "公告、新闻与事件"),
                    (debate_content, "反方证据与风险委员会"),
                )
                if present
            ],
            sufficient=event_content,
            partial=debate_content and risk_attempted,
            attempted=risk_attempted,
            missing_items=["需要事件证据与反方风险证据同时覆盖。"],
            as_of=self._collect_dates(
                timeline,
                information,
                global_information,
                keys=("market_timestamp", "published_at", "fetched_at", "generated_at"),
            ),
        )

        return dict((company, financial, industry, valuation, technical, risk))

    @staticmethod
    def _collect_dates(*packets: dict[str, Any], keys: tuple[str, ...]) -> list[str]:
        dates: list[str] = []
        for packet in packets:
            for key in keys:
                value = packet.get(key)
                if value not in (None, "", [], {}):
                    dates.append(str(value))
        return dates

    @staticmethod
    def _counterevidence_sufficient(evidence: dict[str, Any]) -> bool:
        debate = evidence.get("evidence_debate") or {}
        if not isinstance(debate, dict):
            return False
        return bool(
            debate.get("bear_case")
            or debate.get("risk_committee")
            or debate.get("manager_view")
        )

    @staticmethod
    def _invalidation_sufficient(evidence: dict[str, Any]) -> bool:
        outlook = evidence.get("conditional_outlook") or {}
        frame = evidence.get("research_frame") or {}
        return bool(
            (
                isinstance(outlook, dict)
                and (
                    outlook.get("scenarios")
                    or outlook.get("invalidation")
                    or outlook.get("conditions")
                    or outlook.get("label")
                )
            )
            and (
                (
                    isinstance(frame, dict)
                    and frame.get("missing_information") is not None
                )
                or DeepStockResearchService._counterevidence_sufficient(evidence)
            )
        )

    @staticmethod
    def _packet_available(evidence: dict[str, Any]) -> bool:
        return bool(evidence) and evidence.get("status") not in {
            "unavailable",
            "missing",
            "failed",
        }

    @staticmethod
    def _present_modules(evidence: dict[str, Any], keys: tuple[str, ...]) -> list[str]:
        present = []
        for key in keys:
            value = evidence.get(key)
            if value in (None, {}, [], ""):
                continue
            if isinstance(value, dict) and value.get("status") in {
                "unavailable",
                "missing",
                "failed",
            }:
                continue
            present.append(key)
        return present

    def _normalize_stage_statuses(
        self, stages: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        normalized = []
        active_assigned = False
        definitions = {item["key"]: item for item in self.STAGES}
        for index, stage in enumerate(stages, start=1):
            key = str(stage.get("key"))
            definition = definitions.get(key, {})
            item = {
                **definition,
                **stage,
                "index": index,
            }
            if item.get("status") != "completed":
                if not active_assigned:
                    item["status"] = (
                        "needs_review"
                        if item.get("review_status") == "needs_review"
                        else "in_progress"
                    )
                else:
                    item["status"] = "pending"
                active_assigned = True
            normalized.append(item)
        return normalized

    def _reconcile_legacy_stages(
        self,
        user_id: str,
        session: dict[str, Any],
    ) -> dict[str, Any]:
        stages = list(session.get("stages") or [])
        if not stages:
            return session
        evidence_modules = dict(session.get("evidence_modules") or {})
        unresolved = list(session.get("unresolved_items") or [])
        changed = False
        run_cache: dict[str, dict[str, Any] | None] = {}

        for stage in stages:
            if stage.get("status") != "completed":
                continue
            if (
                stage.get("completion_gate_version")
                == self.STAGE_COMPLETION_GATE_VERSION
            ):
                continue
            key = str(stage.get("key") or "")
            if key == "original_thesis":
                stage.update(
                    {
                        "completion_gate_version": self.STAGE_COMPLETION_GATE_VERSION,
                        "review_status": "completed",
                        "review_reasons": [],
                        "source_refs": stage.get("source_refs") or ["用户输入"],
                    }
                )
                changed = True
                continue

            run_id = str(stage.get("run_id") or "").strip()
            run = None
            if run_id:
                if run_id not in run_cache:
                    run_cache[run_id] = self.database.get_run(run_id, user_id)
                run = run_cache[run_id]
            reasons: list[str] = []
            assessment: dict[str, Any] | None = None
            if run is None:
                reasons.append("历史阶段缺少可回溯的完成 Run。")
            else:
                run_evidence = run.get("evidence") or {}
                gate_allowed, gate_reason = self._stage_advance_gate(
                    run,
                    run_evidence,
                )
                if not gate_allowed:
                    reasons.append(gate_reason)
                else:
                    run_input = run.get("input") or {}
                    assessments = self._stage_assessments(
                        intent=str(run.get("intent") or ""),
                        message=str(run_input.get("message") or ""),
                        evidence=run_evidence,
                    )
                    assessment = assessments.get(key)
                    if assessment is None:
                        reasons.append("历史 Run 没有独立覆盖本阶段研究问题。")
                    elif assessment.get("status") != "completed":
                        reasons.extend(assessment.get("review_reasons") or [])

            if assessment is not None and not reasons:
                stage.update(
                    {
                        "completion_gate_version": self.STAGE_COMPLETION_GATE_VERSION,
                        "review_status": "completed",
                        "review_reasons": [],
                        "coverage_gate": assessment["coverage_gate"],
                        "source_refs": assessment["source_refs"],
                        "evidence_modules": assessment["modules"],
                    }
                )
                module = evidence_modules.get(key)
                if isinstance(module, dict):
                    module.update(
                        {
                            "status": "completed",
                            "coverage_gate": assessment["coverage_gate"],
                            "source_refs": assessment["source_refs"],
                            "review_reasons": [],
                        }
                    )
                changed = True
                continue

            stage.update(
                {
                    "status": "needs_review",
                    "review_status": "needs_review",
                    "review_reasons": self._dedupe(
                        [
                            "该阶段由旧版规则完成，需按当前证据门禁重新核验。",
                            *reasons,
                        ]
                    ),
                    "completed_at": None,
                    "completion_gate_version": self.STAGE_COMPLETION_GATE_VERSION,
                }
            )
            module = evidence_modules.get(key)
            if isinstance(module, dict):
                module.update(
                    {
                        "status": "needs_review",
                        "review_reasons": stage["review_reasons"],
                    }
                )
            changed = True

        if not changed:
            return session

        stages = self._normalize_stage_statuses(stages)
        status = (
            "completed"
            if stages and all(item.get("status") == "completed" for item in stages)
            else "active"
        )
        if status != "completed":
            unresolved.append("历史研究阶段已按更严格的证据门禁重新审计。")
        saved = self.database.save_deep_stock_session(
            user_id=user_id,
            symbol=str(session["symbol"]),
            name=str(session["name"]),
            conversation_id=str(session["conversation_id"]),
            workflow_version=str(
                session.get("workflow_version") or self.WORKFLOW_VERSION
            ),
            status=status,
            stages=stages,
            evidence_modules=evidence_modules,
            unresolved_items=self._dedupe(unresolved)[-12:],
            next_question=self._next_question(stages, str(session["name"])),
            latest_run_id=session.get("latest_run_id"),
            latest_report_id=session.get("latest_report_id"),
            completed_at=(
                session.get("completed_at") if status == "completed" else None
            ),
        )
        return saved

    def _public_session(
        self,
        session: dict[str, Any] | None,
        *,
        evidence_override: dict[str, Any] | None = None,
        coverage_override: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if session is None:
            raise ValueError("个股研究会话不存在")
        stages = []
        for raw_stage in session.get("stages") or []:
            stage = dict(raw_stage)
            stage["review_reasons"] = self._public_issue_list(
                list(stage.get("review_reasons") or [])
            )
            stages.append(stage)
        completed = sum(item.get("status") == "completed" for item in stages)
        current = next(
            (
                item
                for item in stages
                if item.get("status") in {"in_progress", "needs_review"}
            ),
            None,
        )
        report = self.database.latest_research_report(str(session["symbol"]))
        display_name = self.security_master.display_name(
            str(session["symbol"]),
            session.get("name"),
            (report or {}).get("name"),
            ((report or {}).get("evidence") or {}).get("display_name"),
        )
        restored_coverage = self._coverage_from_modules(
            dict(session.get("evidence_modules") or {})
        )
        restored_coverage = self._repair_stale_coverage_observations(
            restored_coverage,
            user_id=str(session["user_id"]),
        )
        if coverage_override is not None:
            coverage = coverage_override
        elif restored_coverage:
            coverage = restored_coverage
        else:
            coverage_evidence = (
                dict(evidence_override)
                if evidence_override is not None
                else self._session_coverage_evidence(session, report)
            )
            coverage = self._coverage_dimensions(coverage_evidence)
        coverage_counts = {
            status: sum(item["coverage_status"] == status for item in coverage.values())
            for status in ("sufficient", "partial", "insufficient", "unavailable")
        }
        refresh_attention = sum(
            bool(item.get("last_observed_status"))
            and item.get("last_observed_status") != item.get("coverage_status")
            for item in coverage.values()
        )
        coverage_tasks = self._coverage_tasks(coverage)
        public_unresolved = self._public_session_unresolved(
            session,
            coverage_tasks=coverage_tasks,
        )
        coverage_history = list(
            (session.get("evidence_modules") or {}).get("_coverage_history") or []
        )
        research_entry = dict(
            (session.get("evidence_modules") or {}).get("screening_entry") or {}
        )
        conversation = self.database.get_conversation(
            str(session["user_id"]), str(session["conversation_id"])
        )
        conversation_title = str((conversation or {}).get("title") or "")
        automatic_suffixes = {
            str(session.get("name") or ""),
            str((report or {}).get("name") or ""),
            str(session["symbol"]),
            str(session["symbol"]).split(".", 1)[0],
        }
        if (
            conversation_title.startswith("个股研究｜")
            and conversation_title.split("｜", 1)[1] in automatic_suffixes
        ):
            conversation_title = f"个股研究｜{display_name}"
        return {
            **session,
            "name": display_name,
            "stages": stages,
            "unresolved_items": public_unresolved,
            "progress": {
                "completed": completed,
                "total": len(stages),
                "percent": round(completed / len(stages) * 100) if stages else 0,
            },
            "current_stage": current,
            "conversation": {
                "id": session["conversation_id"],
                "title": conversation_title,
                "message_count": (conversation or {}).get("message_count", 0),
            },
            "latest_report": self._public_report(report),
            "evidence_coverage": {
                "dimensions": list(coverage.values()),
                "summary": {
                    **coverage_counts,
                    "total": len(coverage),
                    "refresh_attention": refresh_attention,
                },
                "boundary": (
                    "六维覆盖只表示当前已取得证据的完整程度；"
                    "不构成公司评分、投资评级或买卖信号。"
                ),
            },
            "coverage_tasks": coverage_tasks,
            "coverage_history": coverage_history[-20:],
            "research_entry": research_entry or None,
        }

    def _public_session_unresolved(
        self,
        session: dict[str, Any],
        *,
        coverage_tasks: list[dict[str, Any]],
    ) -> list[str]:
        run_gate_notices = [
            str(item)
            for item in (session.get("unresolved_items") or [])
            if item and self._is_run_gate_notice(str(item))
        ]
        unresolved = [
            str(item)
            for item in (session.get("unresolved_items") or [])
            if item
            and not self._is_run_gate_notice(str(item))
            and not self._is_generated_evidence_notice(str(item))
        ]
        latest_run_id = str(session.get("latest_run_id") or "")
        if latest_run_id:
            run = self.database.get_run(latest_run_id, str(session["user_id"]))
            run_evidence = (run or {}).get("evidence") or {}
            if (
                run
                and run.get("status") in self.EVIDENCE_PERSISTED_RUN_STATUSES
                and isinstance(run_evidence, dict)
            ):
                unresolved.extend(
                    self._evidence_unresolved(
                        run_evidence,
                        include_coverage=False,
                    )
                )
        unresolved.extend(
            f"证据覆盖｜{task['label']}：{task['next_step']}"
            for task in coverage_tasks
        )
        unresolved.extend(run_gate_notices)
        return self._public_issue_list(self._dedupe(unresolved)[-12:])

    @classmethod
    def _is_generated_evidence_notice(cls, item: str) -> bool:
        if item in cls.BASE_MISSING_INFORMATION_MODULES:
            return True
        if item.startswith("证据覆盖｜"):
            return True
        if any(
            item.startswith(f"{label}：")
            for _, label in cls.COVERAGE_DIMENSIONS
        ):
            return True
        return any(
            item == f"{label}仍需补充可核验证据。"
            for label in cls.ANALYSIS_BOARD_LABELS
        )

    def _coverage_from_modules(
        self, evidence_modules: dict[str, Any]
    ) -> dict[str, dict[str, Any]]:
        snapshot = evidence_modules.get("_coverage_snapshot") or {}
        dimensions = snapshot.get("dimensions") if isinstance(snapshot, dict) else []
        if not isinstance(dimensions, list):
            return {}
        restored = {
            str(item.get("key")): dict(item)
            for item in dimensions
            if isinstance(item, dict) and item.get("key")
        }
        return {
            key: restored[key] for key, _ in self.COVERAGE_DIMENSIONS if key in restored
        }

    def _repair_stale_coverage_observations(
        self,
        previous: dict[str, dict[str, Any]],
        *,
        user_id: str,
    ) -> dict[str, dict[str, Any]]:
        """Remove refresh warnings created by runs that never observed a dimension."""

        repaired = {key: dict(item) for key, item in previous.items()}
        run_cache: dict[str, dict[str, Any] | None] = {}
        for key, item in repaired.items():
            status = str(item.get("coverage_status") or "unavailable")
            observed_status = str(item.get("last_observed_status") or status)
            run_id = str(item.get("last_observed_run_id") or "")
            if observed_status == status or not run_id:
                continue
            if run_id not in run_cache:
                run_cache[run_id] = self.database.get_run(run_id, user_id)
            run = run_cache[run_id]
            if not run or run.get("status") not in self.EVIDENCE_PERSISTED_RUN_STATUSES:
                continue
            run_evidence = run.get("evidence") or {}
            if not isinstance(run_evidence, dict):
                continue
            current = (
                self._coverage_dimensions(
                    run_evidence,
                    intent=str(run.get("intent") or ""),
                ).get(key)
                or {}
            )
            if current.get("observed_in_run"):
                continue
            for field in (
                "last_observed_status",
                "last_observed_at",
                "last_observed_run_id",
                "last_observed_intent",
            ):
                item.pop(field, None)
        return repaired

    def _merge_coverage_snapshot(
        self,
        *,
        previous: dict[str, dict[str, Any]],
        current: dict[str, dict[str, Any]],
        run_id: str,
        intent: str,
        observed_at: str,
    ) -> dict[str, dict[str, Any]]:
        merged: dict[str, dict[str, Any]] = {}
        for key, label in self.COVERAGE_DIMENSIONS:
            candidate = dict(
                current.get(key)
                or {
                    "key": key,
                    "label": label,
                    "coverage_status": "unavailable",
                    "sources": [],
                    "missing_items": ["尚未取得可核验证据。"],
                    "as_of": [],
                }
            )
            observed_in_run = bool(candidate.pop("observed_in_run", False))
            prior = dict(previous.get(key) or {})
            current_status = str(candidate.get("coverage_status") or "unavailable")
            prior_status = str(prior.get("coverage_status") or "unavailable")
            if prior and not observed_in_run:
                item = prior
            elif prior and self.COVERAGE_STATUS_RANK.get(
                prior_status, 0
            ) > self.COVERAGE_STATUS_RANK.get(current_status, 0):
                item = prior
                item["last_observed_status"] = current_status
                item["last_observed_at"] = observed_at
                item["last_observed_run_id"] = run_id or None
                item["last_observed_intent"] = intent
            else:
                item = candidate
                item.update(
                    {
                        "updated_at": observed_at,
                        "run_id": run_id or None,
                        "intent": intent,
                        "last_observed_status": current_status,
                        "last_observed_at": observed_at,
                        "last_observed_run_id": run_id or None,
                        "last_observed_intent": intent,
                    }
                )
            merged[key] = item
        return merged

    def _append_coverage_history(
        self,
        existing: Any,
        coverage: dict[str, dict[str, Any]],
        *,
        run_id: str,
        intent: str,
        observed_at: str,
    ) -> list[dict[str, Any]]:
        history = [dict(item) for item in (existing or []) if isinstance(item, dict)]
        previous_statuses = (
            dict((history[-1] or {}).get("statuses") or {}) if history else {}
        )
        statuses = {key: item.get("coverage_status") for key, item in coverage.items()}
        changes = [
            {
                "key": key,
                "label": dict(self.COVERAGE_DIMENSIONS)[key],
                "from": previous_statuses.get(key),
                "to": status,
            }
            for key, status in statuses.items()
            if previous_statuses.get(key) != status
        ]
        history.append(
            {
                "observed_at": observed_at,
                "run_id": run_id or None,
                "intent": intent,
                "statuses": statuses,
                "changes": changes,
            }
        )
        return history[-20:]

    def _coverage_tasks(
        self, coverage: dict[str, dict[str, Any]]
    ) -> list[dict[str, Any]]:
        tasks: list[dict[str, Any]] = []
        for key, label in self.COVERAGE_DIMENSIONS:
            item = coverage.get(key) or {}
            status = str(item.get("coverage_status") or "unavailable")
            observed_status = str(item.get("last_observed_status") or status)
            if status == "sufficient" and observed_status == status:
                continue
            retained = status == "sufficient" and observed_status != status
            missing = item.get("missing_items") or []
            next_step = (
                f"已有历史证据被保留，但最近一次刷新仅达到“{observed_status}”；需要重新核验数据时间和来源。"
                if retained
                else str(missing[0])
                if missing
                else "继续补充该维度的可核验证据。"
            )
            tasks.append(
                {
                    "id": f"coverage:{key}",
                    "key": key,
                    "label": label,
                    "title": f"补齐{label}证据"
                    if not retained
                    else f"重新确认{label}证据",
                    "status": "pending_data"
                    if status in {"unavailable", "insufficient"} or retained
                    else "watching",
                    "coverage_status": status,
                    "last_observed_status": observed_status,
                    "next_step": next_step,
                    "updated_at": item.get("updated_at")
                    or item.get("last_observed_at"),
                }
            )
        return tasks

    def _session_coverage_evidence(
        self,
        session: dict[str, Any],
        report: dict[str, Any] | None,
    ) -> dict[str, Any]:
        evidence = dict((report or {}).get("evidence") or {})
        latest_run_id = session.get("latest_run_id")
        if not latest_run_id:
            return evidence
        run = self.database.get_run(str(latest_run_id), str(session["user_id"]))
        if not run or run.get("status") != "completed":
            return evidence
        run_evidence = run.get("evidence") or {}
        if not isinstance(run_evidence, dict):
            return evidence
        intent = str(run.get("intent") or "")
        if intent == "stock_research":
            return dict(run_evidence)
        specialized_keys = {
            "business_structure": "business_structure",
            "earnings_quality": "earnings_quality",
            "financial_drivers": "financial_drivers",
            "analyst_expectations": "analyst_expectations",
            "event_timeline": "event_timeline",
        }
        target_key = specialized_keys.get(intent)
        if target_key:
            evidence[target_key] = dict(run_evidence)
        return evidence

    def _public_report(self, report: dict[str, Any] | None) -> dict[str, Any] | None:
        if report is None:
            return None
        symbol = str(report.get("symbol") or "")
        original_name = str(report.get("name") or "")
        display_name = self.security_master.display_name(
            symbol,
            original_name,
            (report.get("evidence") or {}).get("display_name"),
        )

        def localized(value: Any) -> Any:
            if not value or not original_name or original_name == display_name:
                return value
            return str(value).replace(original_name, display_name)

        return {
            "id": report.get("id"),
            "symbol": report.get("symbol"),
            "name": display_name,
            "title": localized(report.get("title")),
            "summary": localized(report.get("summary")),
            "body": localized(report.get("body")),
            "status": report.get("status"),
            "generated_at": report.get("generated_at"),
            "market_timestamp": report.get("market_timestamp"),
        }

    def _display_name(self, user_id: str, symbol: str) -> str:
        watchlist = self.database.get_watchlist_item(user_id, symbol) or {}
        report = self.database.latest_research_report(symbol) or {}
        return self.security_master.display_name(
            symbol,
            watchlist.get("name"),
            RESEARCH_TARGETS.get(symbol, {}).get("name"),
            report.get("name"),
            (report.get("evidence") or {}).get("display_name"),
        )

    def _next_question(
        self, stages: list[dict[str, Any]], name: str | None = None
    ) -> str:
        current = next(
            (item for item in stages if item.get("status") != "completed"), None
        )
        if current:
            question = str(current.get("question") or "请继续补充当前阶段的研究证据。")
            return f"关于{name}：{question}" if name else question
        return "七个研究阶段已经完成。后续对话将继续复核新证据与原逻辑是否变化。"

    def _report_unresolved(self, report: dict[str, Any] | None) -> list[str]:
        return self._evidence_unresolved((report or {}).get("evidence") or {})

    def _evidence_unresolved(
        self,
        evidence: dict[str, Any],
        *,
        include_coverage: bool = True,
    ) -> list[str]:
        selected_modules = {
            str(item)
            for item in (
                (evidence.get("research_plan") or {}).get("selected_modules") or []
            )
            if item
        }
        items = [
            str(item)
            for item in (
                (evidence.get("research_frame") or {}).get("missing_information") or []
            )
            if item
            and self._missing_information_is_selected(str(item), selected_modules)
        ]
        for module in (evidence.get("analysis_board") or {}).get("modules") or []:
            if module.get("status") not in {"ready", "available", "complete"}:
                required_modules = self.ANALYSIS_BOARD_MODULES.get(
                    str(module.get("key") or ""),
                    set(),
                )
                if (
                    selected_modules
                    and required_modules
                    and not selected_modules.intersection(required_modules)
                ):
                    continue
                label = module.get("label")
                if label:
                    items.append(f"{label}仍需补充可核验证据。")
        if include_coverage:
            for dimension in self._coverage_dimensions(evidence).values():
                if dimension["coverage_status"] == "sufficient":
                    continue
                missing = dimension.get("missing_items") or []
                if missing:
                    items.append(f"{dimension['label']}：{missing[0]}")
        return self._dedupe(items)

    @classmethod
    def _missing_information_is_selected(
        cls,
        item: str,
        selected_modules: set[str],
    ) -> bool:
        if not selected_modules:
            return True
        required_modules = cls.BASE_MISSING_INFORMATION_MODULES.get(item)
        return required_modules is None or bool(
            selected_modules.intersection(required_modules)
        )

    @staticmethod
    def _dedupe(items: list[Any]) -> list[str]:
        result = []
        seen = set()
        for item in items:
            text = str(item).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            result.append(text)
        return result
