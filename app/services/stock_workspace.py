from __future__ import annotations

from typing import Any

from app.catalog import INDEX_BY_SYMBOL, RESEARCH_TARGETS, normalize_symbol
from app.db import Database
from app.services.deep_stock import DeepStockResearchService
from app.services.observation_tasks import ObservationTaskService
from app.services.research_actions import ResearchActionService
from app.services.research_claims import build_research_claim_ledger
from app.services.research_tracking import ResearchTrackingService


class StockWorkspaceService:
    """Aggregate public stock evidence and one user's private research context."""

    CONTRACT_VERSION = "stock_workspace_v1"
    _ACTION_STATUS_RANK = {"triggered": 3, "pending_data": 2, "watching": 1}
    _ACTION_SEVERITY_RANK = {"high": 3, "medium": 2, "low": 1}

    def __init__(
        self,
        database: Database,
        deep_stock: DeepStockResearchService,
        research_tracking: ResearchTrackingService,
        research_actions: ResearchActionService,
        observation_tasks: ObservationTaskService,
        li_zong_strategy: Any | None = None,
    ):
        self.database = database
        self.deep_stock = deep_stock
        self.research_tracking = research_tracking
        self.research_actions = research_actions
        self.observation_tasks = observation_tasks
        self.li_zong_strategy = li_zong_strategy

    def get_workspace(self, user_id: str, symbol: str) -> dict[str, Any]:
        canonical = normalize_symbol(symbol)
        if canonical in INDEX_BY_SYMBOL or canonical.startswith("^"):
            raise ValueError("股票研究空间不接受指数代码")

        watchlist = self.database.get_watchlist_item(user_id, canonical)
        formal_workspace = self.database.get_stock_workspace(user_id, canonical)
        active_thesis = (
            self.database.get_active_thesis(user_id, str(formal_workspace["id"]))
            if formal_workspace is not None
            else None
        )
        session = self.deep_stock.get(user_id, canonical)
        report = self.database.latest_research_report(canonical)
        evidence = dict((report or {}).get("evidence") or {})
        claim_ledger = build_research_claim_ledger(evidence)
        tracking = self.research_tracking.get_packet(
            user_id, symbol=canonical, limit=20
        )
        observation_tasks = self.observation_tasks.list_tasks(
            user_id=user_id, symbol=canonical, limit=100
        )
        action_item = self._action_item(user_id, canonical, watchlist)
        name = str(
            (session or {}).get("name")
            or self._display_name(
                canonical, formal_workspace, watchlist, report, evidence
            )
        )

        if session is not None:
            coverage = dict(session.get("evidence_coverage") or {})
            coverage_tasks = list(session.get("coverage_tasks") or [])
        else:
            coverage_packet = self.deep_stock.evidence_coverage_packet(evidence)
            coverage = {
                "dimensions": coverage_packet["dimensions"],
                "summary": coverage_packet["summary"],
                "boundary": coverage_packet["boundary"],
            }
            coverage_tasks = list(coverage_packet["tasks"])

        strategy_evidence = self._strategy_evidence(canonical)
        research_entry = dict((session or {}).get("research_entry") or {}) or None
        important_changes = self._important_changes(
            [
                *self._strategy_changes(strategy_evidence),
                *(tracking.get("events") or []),
            ]
        )
        pending_actions = self._pending_actions(action_item, coverage_tasks)
        user_task_actions = [
            self._observation_task_action(item)
            for item in observation_tasks.get("items", [])
            if item.get("status") in self.observation_tasks.ACTIVE_STATUSES
        ]
        pending_actions = [*user_task_actions, *pending_actions][:8]
        if research_entry is not None:
            pending_actions = [
                {
                    "id": f"screening-entry:{canonical}",
                    "title": f"核验{research_entry.get('source_label') or '研究候选'}线索",
                    "status": "watching",
                    "severity": "medium",
                    "source": "screening_entry",
                    "next_step": (
                        "逐条核验候选命中理由、反方证据和缺失字段，"
                        "再决定是否形成正式关注判断。"
                    ),
                },
                *pending_actions,
            ][:8]
        if strategy_evidence and strategy_evidence.get("status") == "triggered":
            pending_actions = [
                {
                    "id": f"li-zong:{strategy_evidence.get('id')}",
                    "title": "核验李总策略盘后触发",
                    "status": "triggered",
                    "severity": "high",
                    "source": "li_zong_strategy",
                    "next_step": (
                        "逐条复核触发日行情、基本面、股性和量价证据，"
                        "确认数据时间与失效条件。"
                    ),
                },
                *pending_actions,
            ][:8]
        quote, quote_meta = self._quote(evidence, report)
        latest_report = self._public_report(report)
        recent_reports = [
            self._public_report(item)
            for item in self.database.list_research_reports(canonical, limit=3)
        ]
        recent_research = [item for item in recent_reports if item is not None]
        counterevidence = self._counterevidence(claim_ledger)
        invalidation_conditions = list(
            claim_ledger.get("invalidation_conditions") or []
        )
        next_evidence = self._next_evidence(
            evidence, coverage_tasks, action_item, claim_ledger
        )
        relation = self._relation(
            formal_workspace, session, important_changes, pending_actions
        )
        thesis = self._thesis(active_thesis, watchlist)
        stage_progress = self._stage_progress(session)
        dimensions = list(coverage.get("dimensions") or [])
        sufficient_dimensions = sum(
            item.get("coverage_status") == "sufficient" for item in dimensions
        )
        data_status = (
            "empty"
            if report is None and not dimensions
            else "ready"
            if sufficient_dimensions == len(dimensions) and dimensions
            else "partial"
        )

        return {
            "contract_version": self.CONTRACT_VERSION,
            "symbol": canonical,
            "name": name,
            "overview": {
                "quote": quote,
                "quote_meta": quote_meta,
                "latest_change": important_changes[0] if important_changes else None,
                "data_status": data_status,
            },
            "relation": relation,
            "position_snapshot": {
                "available": False,
                "status": "not_configured",
            },
            "thesis": thesis,
            "important_changes": important_changes,
            "pending_actions": pending_actions,
            "observation_tasks": observation_tasks,
            "stage_progress": stage_progress,
            "evidence_summary": coverage,
            "claim_ledger": claim_ledger,
            "counterevidence": counterevidence,
            "invalidation_conditions": invalidation_conditions,
            "next_evidence": next_evidence,
            "strategy_evidence": strategy_evidence,
            "research_entry": research_entry,
            "latest_report": latest_report,
            "recent_research": recent_research,
            "conversation": (session or {}).get("conversation"),
            "data_meta": {
                "status": data_status,
                "quote_as_of": quote_meta.get("quote_as_of"),
                "daily_as_of": quote_meta.get("daily_as_of"),
                "report_generated_at": (report or {}).get("generated_at"),
                "report_market_timestamp": (report or {}).get("market_timestamp"),
                "strategy_as_of": (strategy_evidence or {}).get("as_of_date"),
                "public_evidence_cacheable": True,
                "private_context_user_isolated": True,
            },
            "history_summary": {
                "recent_report_count": len(recent_research),
                "change_count": len(tracking.get("events") or []),
                "coverage_snapshot_count": len(
                    (session or {}).get("coverage_history") or []
                ),
                "latest_report_at": (report or {}).get("generated_at"),
                "latest_change_at": (
                    important_changes[0].get("created_at")
                    if important_changes
                    else None
                ),
            },
            "completeness": {
                "has_stock_space": formal_workspace is not None,
                "has_thesis": bool(thesis.get("summary")),
                "has_research_session": session is not None,
                "has_latest_report": report is not None,
                "evidence_dimensions": len(dimensions),
                "sufficient_dimensions": sufficient_dimensions,
                "missing_items": self._completeness_missing(
                    formal_workspace, thesis, session, report, coverage_tasks
                ),
            },
            "boundary": (
                "股票研究空间用于保存用户判断、证据、反证和核验任务；"
                "不提供无来源综合评分、自产目标价或确定性买卖建议。"
            ),
        }

    def get_evidence_workspace(self, user_id: str, symbol: str) -> dict[str, Any]:
        workspace = self.get_workspace(user_id, symbol)
        return {
            "contract_version": "stock_workspace_evidence_v1",
            "symbol": workspace["symbol"],
            "name": workspace["name"],
            "evidence_summary": workspace["evidence_summary"],
            "claim_ledger": workspace["claim_ledger"],
            "counterevidence": workspace["counterevidence"],
            "invalidation_conditions": workspace["invalidation_conditions"],
            "next_evidence": workspace["next_evidence"],
            "data_meta": workspace["data_meta"],
            "boundary": workspace["boundary"],
        }

    def get_timeline_workspace(self, user_id: str, symbol: str) -> dict[str, Any]:
        workspace = self.get_workspace(user_id, symbol)
        return {
            "contract_version": "stock_workspace_timeline_v1",
            "symbol": workspace["symbol"],
            "name": workspace["name"],
            "important_changes": workspace["important_changes"],
            "recent_research": workspace["recent_research"],
            "history_summary": workspace["history_summary"],
            "data_meta": workspace["data_meta"],
        }

    def get_actions_workspace(self, user_id: str, symbol: str) -> dict[str, Any]:
        workspace = self.get_workspace(user_id, symbol)
        return {
            "contract_version": "stock_workspace_actions_v1",
            "symbol": workspace["symbol"],
            "name": workspace["name"],
            "relation": workspace["relation"],
            "stage_progress": workspace["stage_progress"],
            "pending_actions": workspace["pending_actions"],
            "observation_tasks": workspace["observation_tasks"],
            "next_evidence": workspace["next_evidence"],
            "boundary": (
                "研究行动只用于核验事实、补充证据和复核判断；"
                "不生成买卖、仓位、目标价或收益承诺。"
            ),
        }

    @staticmethod
    def _observation_task_action(task: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": f"observation-task:{task['id']}",
            "task_id": task["id"],
            "title": task.get("title") or "用户观察任务",
            "status": (
                "pending_data"
                if task.get("status") == "waiting_data"
                else "triggered"
            ),
            "task_status": task.get("status"),
            "task_status_label": task.get("status_label"),
            "severity": task.get("priority") or "normal",
            "source": "observation_task",
            "condition": "用户已保存为长期观察任务",
            "current_evidence": task.get("description"),
            "next_step": task.get("description"),
            "due_at": task.get("due_at"),
            "version": task.get("version"),
        }

    def _action_item(
        self,
        user_id: str,
        symbol: str,
        watchlist: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if watchlist is None:
            return None
        packet = self.research_actions.get_packet(user_id, persist=False)
        return next(
            (item for item in packet.get("items", []) if item.get("symbol") == symbol),
            None,
        )

    @staticmethod
    def _important_changes(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        seen: set[str] = set()
        for event in events:
            summary = " ".join(str(event.get("summary") or "").split())
            identity = summary or str(event.get("id") or "")
            if not identity or identity in seen:
                continue
            seen.add(identity)
            output.append(event)
            if len(output) == 3:
                break
        return output

    @staticmethod
    def _display_name(
        symbol: str,
        formal_workspace: dict[str, Any] | None,
        watchlist: dict[str, Any] | None,
        report: dict[str, Any] | None,
        evidence: dict[str, Any],
    ) -> str:
        quote = evidence.get("current_quote") or {}
        return str(
            (formal_workspace or {}).get("name")
            or (watchlist or {}).get("name")
            or (report or {}).get("name")
            or quote.get("name")
            or evidence.get("display_name")
            or (RESEARCH_TARGETS.get(symbol) or {}).get("name")
            or symbol
        )

    @staticmethod
    def _thesis(
        active_thesis: dict[str, Any] | None,
        watchlist: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if active_thesis is not None:
            return {
                "id": active_thesis.get("id"),
                "status": "active",
                "summary": active_thesis.get("reason_text"),
                "watch_items": active_thesis.get("watch_items") or [],
                "recheck_conditions": active_thesis.get("recheck_conditions") or [],
                "source": active_thesis.get("source"),
                "version": active_thesis.get("version_no"),
                "updated_at": active_thesis.get("confirmed_at")
                or active_thesis.get("created_at"),
            }
        summary = str((watchlist or {}).get("thesis") or "").strip()
        return {
            "status": "active" if summary else "empty",
            "summary": summary or None,
            "source": "watchlist_thesis" if summary else None,
            "version": 1 if summary else None,
            "updated_at": (watchlist or {}).get("updated_at"),
        }

    @staticmethod
    def _relation(
        workspace: dict[str, Any] | None,
        session: dict[str, Any] | None,
        changes: list[dict[str, Any]],
        actions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if workspace is None:
            return {
                "type": None,
                "preview_state": "candidate",
                "label": "尚未加入关注",
                "in_watchlist": False,
                "tracking_status": None,
                "workflow_status": "idle",
                "attention_flags": [],
            }
        flags: list[str] = []
        if changes:
            flags.append("new_change")
        if any(item.get("status") == "triggered" for item in actions):
            flags.append("review_needed")
        if any(item.get("status") == "pending_data" for item in actions):
            flags.append("task_due")
        relation_type = str(workspace.get("relation_type") or "watching")
        return {
            "workspace_id": workspace.get("id"),
            "version": workspace.get("version"),
            "type": relation_type,
            "preview_state": None,
            "label": {
                "watching": "已加入关注",
                "holding": "持仓研究中",
                "ended": "已结束跟踪",
            }.get(relation_type, "股票研究空间"),
            "in_watchlist": relation_type != "ended",
            "priority": workspace.get("priority"),
            "tracking_status": workspace.get("tracking_status"),
            "workflow_status": (
                "researching"
                if session is not None and session.get("status") != "completed"
                else workspace.get("workflow_status") or "idle"
            ),
            "attention_tags": workspace.get("attention_tags") or [],
            "attention_flags": flags,
            "created_at": workspace.get("created_at"),
            "updated_at": workspace.get("updated_at"),
            "ended_at": workspace.get("ended_at"),
        }

    @staticmethod
    def _stage_progress(session: dict[str, Any] | None) -> dict[str, Any]:
        if session is None:
            return {
                "status": "not_started",
                "progress": {"completed": 0, "total": 7, "percent": 0},
                "current_stage": None,
                "next_question": None,
                "updated_at": None,
            }
        return {
            "status": session.get("status"),
            "progress": session.get("progress"),
            "current_stage": session.get("current_stage"),
            "next_question": session.get("next_question"),
            "updated_at": session.get("updated_at"),
        }

    @classmethod
    def _pending_actions(
        cls,
        action_item: dict[str, Any] | None,
        coverage_tasks: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for action in (action_item or {}).get("actions", []):
            items.append({**action, "source": "research_action"})
        for task in coverage_tasks:
            items.append(
                {
                    **task,
                    "severity": task.get("severity") or "medium",
                    "source": "evidence_coverage",
                }
            )
        deduped: dict[str, dict[str, Any]] = {}
        for item in items:
            identity = str(item.get("id") or item.get("key") or item.get("title"))
            deduped.setdefault(identity, item)
        output = list(deduped.values())
        output.sort(
            key=lambda item: (
                cls._ACTION_STATUS_RANK.get(str(item.get("status")), 0),
                cls._ACTION_SEVERITY_RANK.get(str(item.get("severity")), 0),
                str(item.get("title") or ""),
            ),
            reverse=True,
        )
        return output[:8]

    @staticmethod
    def _quote(
        evidence: dict[str, Any], report: dict[str, Any] | None
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        quote = dict(evidence.get("current_quote") or {})
        valuation = dict((evidence.get("fundamentals") or {}).get("valuation") or {})
        metrics = dict(evidence.get("metrics") or {})
        provenance = dict(evidence.get("provenance") or {})
        price = quote.get("price")
        if price is None:
            price = valuation.get("price")
        if price is None:
            price = metrics.get("latest_close")
        pct_change = quote.get("pct_change")
        if pct_change is None:
            pct_change = valuation.get("pct_change")
        if pct_change is None:
            pct_change = metrics.get("return_1d_pct")
        quote_as_of = quote.get("market_timestamp") or valuation.get(
            "market_timestamp"
        )
        daily_as_of = (
            metrics.get("market_timestamp")
            or provenance.get("market_timestamp")
            or (report or {}).get("market_timestamp")
        )
        semantic_label = (
            quote.get("quote_label")
            or valuation.get("quote_label")
            or ("最新报价" if quote_as_of and quote_as_of != daily_as_of else "最近收盘")
        )
        return (
            {
                "price": price,
                "pct_change": pct_change,
                "currency": quote.get("currency") or valuation.get("currency"),
                "label": semantic_label,
                "market_timestamp": quote_as_of or daily_as_of,
                "daily_close": metrics.get("latest_close"),
                "daily_return_1d_pct": metrics.get("return_1d_pct"),
            },
            {
                "quote_as_of": quote_as_of,
                "daily_as_of": daily_as_of,
                "semantic_label": semantic_label,
                "dual_time_anchor": bool(
                    quote_as_of and daily_as_of and quote_as_of != daily_as_of
                ),
            },
        )

    @staticmethod
    def _counterevidence(claim_ledger: dict[str, Any]) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for claim in claim_ledger.get("claims") or []:
            relation = claim.get("relation")
            if relation not in {"weakens", "unresolved"}:
                continue
            output.append(
                {
                    "id": claim.get("id"),
                    "kind": (
                        "bear_case" if relation == "weakens" else "risk_committee"
                    ),
                    "label": "反方证据" if relation == "weakens" else "风险复核",
                    "statement": claim.get("claim"),
                    "evidence": claim.get("evidence_summary"),
                    "source_name": claim.get("source_name"),
                    "source_url": claim.get("source_url"),
                    "data_time": claim.get("data_time"),
                    "coverage_status": claim.get("coverage_status"),
                    "limitations": claim.get("limitations") or [],
                    "next_step": claim.get("next_step"),
                }
            )
        return output[:8]

    @staticmethod
    def _next_evidence(
        evidence: dict[str, Any],
        coverage_tasks: list[dict[str, Any]],
        action_item: dict[str, Any] | None,
        claim_ledger: dict[str, Any],
    ) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []

        def add(source: str, description: Any, status: str = "pending_data") -> None:
            text = str(description or "").strip()
            if text and all(item["description"] != text for item in output):
                output.append(
                    {"source": source, "description": text, "status": status}
                )

        for gap in claim_ledger.get("information_gaps") or []:
            add("claim_ledger", gap.get("description"))
            if output:
                output[-1]["related_claim_ids"] = gap.get("related_claim_ids") or []
        for task in coverage_tasks:
            add("evidence_coverage", task.get("next_step"), str(task.get("status") or "pending_data"))
        for item in (evidence.get("research_frame") or {}).get(
            "missing_information"
        ) or []:
            add("research_frame", item)
        for plan in (evidence.get("analysis_board") or {}).get("tracking_plan") or []:
            for check in plan.get("checks") or []:
                add("tracking_plan", check, "watching")
        for action in (action_item or {}).get("actions", []):
            add("research_action", action.get("next_step"), str(action.get("status") or "pending_data"))
        return output[:10]

    def _strategy_evidence(self, symbol: str) -> dict[str, Any] | None:
        if self.li_zong_strategy is None or not symbol.endswith((".SS", ".SZ")):
            return None
        try:
            item = self.li_zong_strategy.get_candidate(symbol)
        except (KeyError, ValueError):
            return None
        if item is None:
            return None
        result = dict(item.get("result") or {})
        return {
            "id": item.get("id"),
            "strategy_id": "li_zong",
            "strategy_version": item.get("strategy_version"),
            "parameter_version": item.get("parameter_version"),
            "status": item.get("status"),
            "evaluation_status": item.get("evaluation_status"),
            "as_of_date": item.get("as_of_date"),
            "data_version": item.get("data_version"),
            "triggered_rule_ids": result.get("triggered_rule_ids") or [],
            "rule_results": item.get("rule_results")
            or result.get("rule_results")
            or [],
            "trigger_events": item.get("trigger_events") or [],
            "limitations": result.get("limitations") or [],
            "boundary": (
                "策略证据只用于研究候选和人工复核，不构成买卖建议。"
            ),
        }

    @staticmethod
    def _strategy_changes(strategy: dict[str, Any] | None) -> list[dict[str, Any]]:
        if not strategy or strategy.get("status") != "triggered":
            return []
        triggered = list(strategy.get("triggered_rule_ids") or [])
        return [
            {
                "id": f"li-zong-trigger:{strategy.get('id')}",
                "event_type": "strategy_trigger",
                "summary": (
                    "李总策略出现盘后人工复核触发："
                    + "、".join(triggered or ["触发规则待核验"])
                ),
                "source": "Tushare稳定快照与确定性规则引擎",
                "event_time": strategy.get("as_of_date"),
                "created_at": strategy.get("as_of_date"),
                "status": "pending_confirmation",
                "evidence": {
                    "triggered_rule_ids": triggered,
                    "strategy_version": strategy.get("strategy_version"),
                    "parameter_version": strategy.get("parameter_version"),
                },
            }
        ]

    @staticmethod
    def _public_report(report: dict[str, Any] | None) -> dict[str, Any] | None:
        if report is None:
            return None
        return {
            "id": report.get("id"),
            "symbol": report.get("symbol"),
            "name": report.get("name"),
            "title": report.get("title"),
            "summary": report.get("summary"),
            "body": report.get("body"),
            "status": report.get("status"),
            "generated_at": report.get("generated_at"),
            "market_timestamp": report.get("market_timestamp"),
        }

    @staticmethod
    def _completeness_missing(
        workspace: dict[str, Any] | None,
        thesis: dict[str, Any],
        session: dict[str, Any] | None,
        report: dict[str, Any] | None,
        coverage_tasks: list[dict[str, Any]],
    ) -> list[str]:
        missing: list[str] = []
        if workspace is None:
            missing.append("尚未加入股票研究空间")
        if not thesis.get("summary"):
            missing.append("尚未建立当前判断")
        if session is None:
            missing.append("尚未启动股票内研究对话")
        if report is None:
            missing.append("尚未建立服务器端研究报告")
        if coverage_tasks:
            missing.append(f"仍有{len(coverage_tasks)}个证据维度需要补充或复核")
        return missing
