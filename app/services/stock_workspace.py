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
    _AI_DIMENSION_KEYWORDS = {
        "company_operating": (
            "主营",
            "业务结构",
            "产品结构",
            "收入结构",
            "客户结构",
            "公司靠什么",
        ),
        "financial_quality": (
            "营收",
            "净利润",
            "毛利",
            "现金流",
            "存货",
            "应收",
            "费用",
            "财报",
        ),
        "industry_relative": (
            "行业",
            "同行",
            "相对表现",
            "一致预期",
            "券商",
            "机构",
        ),
        "valuation": ("估值", "市盈率", "市净率", "PE", "PB", "市值"),
        "technical_state": (
            "价格",
            "收盘",
            "收益",
            "均线",
            "回撤",
            "波动",
            "RSI",
            "MACD",
            "量比",
        ),
        "risk_events": (
            "公告",
            "事件",
            "新闻",
            "情绪",
            "风险",
            "反证",
            "失效",
            "监管",
        ),
    }

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
        structured_answer = self._latest_structured_answer(
            user_id,
            session,
            symbol=symbol,
        )
        evidence_layers = self._evidence_layers(
            evidence=evidence,
            dimensions=dimensions,
            claim_ledger=claim_ledger,
            structured_answer=structured_answer,
        )
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
            "evidence_layers": evidence_layers,
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
            "evidence_layers": workspace["evidence_layers"],
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

    def _latest_structured_answer(
        self,
        user_id: str,
        session: dict[str, Any] | None,
        *,
        symbol: str,
    ) -> dict[str, Any] | None:
        conversation_id = str(
            (session or {}).get("conversation_id")
            or ((session or {}).get("conversation") or {}).get("id")
            or ""
        )
        if conversation_id:
            messages = self.database.list_recent_conversation_messages(
                user_id,
                conversation_id,
                limit=200,
            )
            bound_answer = self._structured_answer_from_messages(
                reversed(messages),
                conversation_scope="bound_research_conversation",
            )
            if bound_answer:
                return bound_answer

        normalized_symbol = normalize_symbol(symbol)
        messages = self.database.list_recent_user_assistant_messages(
            user_id,
            limit=500,
        )
        same_stock_messages = []
        for message in messages:
            if message.get("conversation_id") == conversation_id:
                continue
            metadata = message.get("metadata") or {}
            message_symbol = metadata.get("symbol")
            if not message_symbol:
                structured = metadata.get("structured_answer")
                if isinstance(structured, dict):
                    message_symbol = structured.get("symbol")
            if not message_symbol:
                continue
            try:
                if normalize_symbol(str(message_symbol)) != normalized_symbol:
                    continue
            except (KeyError, ValueError):
                continue
            same_stock_messages.append(message)
        return self._structured_answer_from_messages(
            same_stock_messages,
            conversation_scope="same_stock_history",
        )

    @staticmethod
    def _structured_answer_from_messages(
        messages: Any,
        *,
        conversation_scope: str,
    ) -> dict[str, Any] | None:
        for message in messages:
            if message.get("role") != "assistant":
                continue
            metadata = message.get("metadata") or {}
            structured = metadata.get("structured_answer")
            if not isinstance(structured, dict):
                continue
            if structured.get("status") == "unavailable":
                continue
            return {
                **structured,
                "message_created_at": message.get("created_at"),
                "run_id": message.get("run_id"),
                "conversation_id": message.get("conversation_id"),
                "conversation_scope": conversation_scope,
            }
        return None

    @classmethod
    def _evidence_layers(
        cls,
        *,
        evidence: dict[str, Any],
        dimensions: list[dict[str, Any]],
        claim_ledger: dict[str, Any],
        structured_answer: dict[str, Any] | None,
    ) -> dict[str, Any]:
        dimension_by_key = {
            str(item.get("key")): dict(item)
            for item in dimensions
            if item.get("key")
        }
        keys = [key for key, _ in DeepStockResearchService.COVERAGE_DIMENSIONS]
        raw: dict[str, list[str]] = {key: [] for key in keys}
        calculated: dict[str, list[str]] = {key: [] for key in keys}
        ai_explanations: dict[str, list[str]] = {key: [] for key in keys}
        missing: dict[str, list[str]] = {
            key: list((dimension_by_key.get(key) or {}).get("missing_items") or [])
            for key in keys
        }

        def packet(key: str) -> dict[str, Any]:
            value = evidence.get(key)
            return value if isinstance(value, dict) else {}

        def add(bucket: dict[str, list[str]], key: str, value: Any) -> None:
            text = cls._layer_item_text(value)
            if text and text not in bucket[key]:
                bucket[key].append(text)

        def number(value: Any, suffix: str = "") -> str | None:
            if value is None or isinstance(value, bool):
                return None
            if isinstance(value, (int, float)):
                text = f"{float(value):.2f}".rstrip("0").rstrip(".")
                return f"{text}{suffix}"
            text = str(value).strip()
            return f"{text}{suffix}" if text else None

        def raw_line(
            label: str,
            value: Any,
            *,
            source: str,
            as_of: Any = None,
        ) -> str | None:
            value_text = str(value or "").strip()
            if not value_text:
                return None
            details = [f"{label}：{value_text}", f"来源：{source}"]
            if as_of:
                details.append(f"数据时间：{as_of}")
            return "；".join(details)

        business = packet("business_structure")
        business_as_of = business.get("anchor_report_date") or business.get(
            "latest_fetched_at"
        )
        business_dimensions = list(business.get("dimensions") or [])
        business_rows = list(business.get("rows") or [])
        add(
            raw,
            "company_operating",
            raw_line(
                "主营构成报告期",
                business.get("anchor_report_date"),
                source="主营与业务结构",
                as_of=business_as_of,
            ),
        )
        if business_dimensions or business_rows:
            add(
                raw,
                "company_operating",
                raw_line(
                    "已取得主营分类",
                    f"{len(business_dimensions) or len(business_rows)} 个维度或条目",
                    source="主营与业务结构",
                    as_of=business_as_of,
                ),
            )
        for item in list(business.get("key_changes") or [])[:2]:
            add(calculated, "company_operating", item)

        fundamentals = packet("fundamentals")
        financial_periods = list(fundamentals.get("financial_periods") or [])
        latest_period = financial_periods[0] if financial_periods else {}
        if not latest_period:
            latest_period = dict((fundamentals.get("summary") or {}).get("latest_report") or {})
        report_period = latest_period.get("report_period") or latest_period.get(
            "report_date"
        )
        add(
            raw,
            "financial_quality",
            raw_line(
                "最新结构化财务报告期",
                report_period,
                source="结构化财务",
                as_of=report_period,
            ),
        )
        for label, field in (
            ("营收同比", "revenue_yoy_pct"),
            ("净利润同比", "net_profit_yoy_pct"),
            ("毛利率", "gross_margin_pct"),
            ("经营现金流/净利润", "operating_cashflow_to_net_profit"),
        ):
            value = number(latest_period.get(field), "%" if field.endswith("pct") else "")
            add(
                raw,
                "financial_quality",
                raw_line(
                    label,
                    value,
                    source="结构化财务",
                    as_of=report_period,
                ),
            )
        earnings = packet("earnings_quality")
        drivers = packet("financial_drivers")
        add(
            calculated,
            "financial_quality",
            earnings.get("summary") or earnings.get("overall_label"),
        )
        add(
            calculated,
            "financial_quality",
            drivers.get("summary") or drivers.get("overall_label"),
        )
        for item in list(drivers.get("confirmed_mechanical_drivers") or [])[:2]:
            add(calculated, "financial_quality", item)

        peers = packet("peer_comparison")
        peer_items = list(peers.get("peers") or [])
        expectations = packet("analyst_expectations")
        industry_as_of = peers.get("report_period") or peers.get(
            "market_timestamp"
        )
        if peer_items:
            add(
                raw,
                "industry_relative",
                raw_line(
                    "固定同行样本",
                    f"{len(peer_items)} 家",
                    source="固定同行比较",
                    as_of=industry_as_of,
                ),
            )
        if expectations.get("industry"):
            add(
                raw,
                "industry_relative",
                raw_line(
                    "行业分类",
                    expectations.get("industry"),
                    source="分析师与行业覆盖",
                    as_of=expectations.get("fetched_at"),
                ),
            )
        if peer_items:
            add(
                calculated,
                "industry_relative",
                f"固定同行比较已覆盖 {len(peer_items)} 家样本；不同报告期或口径不进入比较。",
            )
        if expectations.get("industry"):
            add(
                calculated,
                "industry_relative",
                f"当前行业口径为“{expectations['industry']}”；分析师预期不等于公司指引。",
            )

        valuation = dict(fundamentals.get("valuation") or {})
        valuation_as_of = valuation.get("market_timestamp") or industry_as_of
        for label, field in (
            ("最新价格", "price"),
            ("TTM 市盈率", "pe_ttm"),
            ("市净率", "pb"),
            ("总市值", "total_market_cap"),
        ):
            add(
                raw,
                "valuation",
                raw_line(
                    label,
                    number(valuation.get(field)),
                    source="当前估值截面",
                    as_of=valuation_as_of,
                ),
            )
        if valuation and peer_items:
            add(
                calculated,
                "valuation",
                f"当前估值截面已与 {len(peer_items)} 家固定同行按一致口径比较；不生成目标价或高低估评级。",
            )
        elif valuation:
            add(
                calculated,
                "valuation",
                "已取得当前估值截面；固定同行一致口径仍需补充。",
            )

        metrics = packet("metrics")
        technical_as_of = packet("provenance").get(
            "market_timestamp"
        ) or metrics.get("market_timestamp")
        for label, field, suffix in (
            ("最近完整收盘", "latest_close", ""),
            ("20日收益", "return_20d_pct", "%"),
            ("MA20", "ma20", ""),
            ("RSI14", "rsi_14", ""),
        ):
            add(
                raw,
                "technical_state",
                raw_line(
                    label,
                    number(metrics.get(field), suffix),
                    source="完整日线与技术指标",
                    as_of=technical_as_of,
                ),
            )
        add(
            calculated,
            "technical_state",
            metrics.get("trend_state") or metrics.get("technical_state"),
        )
        if metrics.get("return_20d_pct") is not None:
            add(
                calculated,
                "technical_state",
                f"20日收益 {number(metrics.get('return_20d_pct'), '%')}；只描述已发生的价格路径。",
            )

        timeline = packet("event_timeline")
        information = packet("a_share_information")
        global_information = packet("global_information")
        debate = packet("evidence_debate")
        event_count = len(timeline.get("events") or [])
        announcement_count = len(information.get("announcements") or [])
        news_count = len(information.get("news") or []) + len(
            global_information.get("news") or []
        )
        social_count = len(information.get("social_posts") or [])
        risk_as_of = timeline.get("market_timestamp") or information.get(
            "fetched_at"
        )
        for label, count, source in (
            ("公司公告与监管事件", event_count + announcement_count, "公告与事件时间线"),
            ("新闻线索", news_count, "公司新闻"),
            ("社区弱情绪样本", social_count, "社区样本"),
        ):
            if count:
                add(
                    raw,
                    "risk_events",
                    raw_line(
                        label,
                        f"{count} 条",
                        source=source,
                        as_of=risk_as_of,
                    ),
                )
        bear_count = len(debate.get("bear_case") or [])
        risk_count = len(debate.get("risk_committee") or [])
        if bear_count or risk_count:
            add(
                calculated,
                "risk_events",
                f"反方证据 {bear_count} 项，风险复核 {risk_count} 项；必须与具体来源和时间绑定。",
            )

        claim_dimension = {
            "deterministic_business_structure": "company_operating",
            "structured_fundamentals": "financial_quality",
            "deterministic_earnings_quality": "financial_quality",
            "deterministic_financial_driver": "financial_quality",
            "deterministic_price_metrics": "technical_state",
            "deterministic_event_timeline": "risk_events",
            "eastmoney_guba_heuristic_weak": "risk_events",
        }
        for claim in claim_ledger.get("claims") or []:
            dimension_key = claim_dimension.get(str(claim.get("source_key") or ""))
            if not dimension_key:
                continue
            statement = str(claim.get("claim") or "").strip()
            evidence_summary = str(claim.get("evidence_summary") or "").strip()
            source_name = str(claim.get("source_name") or "").strip()
            text = statement
            if evidence_summary:
                text += f"；依据：{evidence_summary}"
            if source_name:
                text += f"；来源：{source_name}"
            add(calculated, dimension_key, text)

        ai_status = "not_generated"
        ai_source = "not_generated"
        if structured_answer:
            ai_status = str(structured_answer.get("status") or "partial")
            ai_source = str(
                structured_answer.get("conversation_scope")
                or "bound_research_conversation"
            )
            section_fallbacks = {
                "counter_evidence_and_risks": "risk_events",
                "invalidation_conditions": "risk_events",
            }
            for section in (
                "confirmed_facts",
                "evidence_based_inferences",
                "counter_evidence_and_risks",
                "hypotheses_to_verify",
                "information_gaps",
                "invalidation_conditions",
            ):
                for item in structured_answer.get(section) or []:
                    text = cls._layer_item_text(item)
                    if not text:
                        continue
                    dimension_key = cls._classify_ai_dimension(text)
                    dimension_key = dimension_key or section_fallbacks.get(section)
                    if not dimension_key:
                        continue
                    citation_count = len(item.get("citation_ids") or []) if isinstance(item, dict) else 0
                    suffix = f"（引用 {citation_count} 项）" if citation_count else ""
                    add(ai_explanations, dimension_key, f"{text}{suffix}")
                    if section == "information_gaps":
                        add(missing, dimension_key, text)
            summary = str(structured_answer.get("answer_summary") or "").strip()
            summary_dimension = cls._classify_ai_dimension(summary)
            if summary and summary_dimension:
                add(ai_explanations, summary_dimension, summary)

        derived_as_of = {
            "company_operating": [business_as_of],
            "financial_quality": [
                report_period,
                earnings.get("report_period"),
                drivers.get("report_period"),
            ],
            "industry_relative": [
                industry_as_of,
                expectations.get("fetched_at"),
            ],
            "valuation": [valuation_as_of],
            "technical_state": [technical_as_of],
            "risk_events": [
                risk_as_of,
                global_information.get("fetched_at"),
            ],
        }

        layer_dimensions = []
        for key, label in DeepStockResearchService.COVERAGE_DIMENSIONS:
            dimension = dimension_by_key.get(key) or {
                "key": key,
                "label": label,
                "coverage_status": "unavailable",
                "sources": [],
                "as_of": [],
                "missing_items": [],
            }
            dimension_as_of = [
                str(value)
                for value in dimension.get("as_of") or []
                if value
            ]
            for value in derived_as_of.get(key) or []:
                value_text = str(value or "").strip()
                if value_text and value_text not in dimension_as_of:
                    dimension_as_of.append(value_text)
            layer_dimensions.append(
                {
                    "key": key,
                    "label": label,
                    "coverage_status": dimension.get("coverage_status"),
                    "sources": list(dimension.get("sources") or []),
                    "as_of": dimension_as_of,
                    "raw_data": raw[key][:4],
                    "system_calculations": calculated[key][:4],
                    "ai_explanations": ai_explanations[key][:3],
                    "missing_items": missing[key][:4],
                    "ai_status": ai_status,
                }
            )
        return {
            "contract_version": "stock_workspace_evidence_layers_v1",
            "dimensions": layer_dimensions,
            "ai_status": ai_status,
            "ai_source": ai_source,
            "ai_message_created_at": (
                structured_answer.get("message_created_at")
                if structured_answer
                else None
            ),
            "boundary": (
                "原始数据、系统计算、Agent解释和缺失项分层展示；"
                "系统计算与AI解释都不能覆盖原始来源，也不构成买卖建议。"
            ),
        }

    @staticmethod
    def _layer_item_text(value: Any) -> str:
        if isinstance(value, str):
            return " ".join(value.split())
        if not isinstance(value, dict):
            return ""
        label = str(
            value.get("label")
            or value.get("title")
            or value.get("name")
            or ""
        ).strip()
        detail = str(
            value.get("text")
            or value.get("description")
            or value.get("claim")
            or value.get("risk")
            or value.get("summary")
            or value.get("detail")
            or value.get("condition")
            or value.get("effect")
            or ""
        ).strip()
        if label and detail and not detail.startswith(label):
            return f"{label}：{detail}"
        return detail or label

    @classmethod
    def _classify_ai_dimension(cls, text: str) -> str | None:
        normalized = str(text or "")
        if not normalized:
            return None
        normalized_folded = normalized.casefold()
        matches = []
        for order, (key, keywords) in enumerate(cls._AI_DIMENSION_KEYWORDS.items()):
            positions = [
                normalized_folded.find(keyword.casefold())
                for keyword in keywords
                if keyword.casefold() in normalized_folded
            ]
            if positions:
                matches.append((min(positions), -len(positions), order, key))
        return min(matches)[-1] if matches else None

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
