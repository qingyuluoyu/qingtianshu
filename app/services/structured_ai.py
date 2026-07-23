from __future__ import annotations

import json
import re
from typing import Any
from uuid import uuid4

from app.catalog import normalize_symbol
from app.db import Database
from app.services.observation_tasks import ObservationTaskService
from app.services.research_claims import build_research_claim_ledger
from app.services.stock_domain import StockDomainService
from app.utils import json_dumps, utc_now


class StructuredAINotFound(ValueError):
    pass


class StructuredAIConflict(ValueError):
    pass


class StructuredAIInvalidState(ValueError):
    pass


class StructuredAIService:
    """Persist auditable citations and user-confirmable Agent writebacks."""

    CONTRACT_VERSION = "structured_ai_response_v1"
    THESIS_WRITEBACK_TERMS = (
        "形成判断草稿",
        "生成判断草稿",
        "提出判断草稿",
        "更新我的判断",
        "更新当前判断",
        "保存判断草稿",
        "写入当前判断",
    )
    OBSERVATION_TASK_WRITEBACK_TERMS = (
        "创建观察任务",
        "生成观察任务",
        "保存观察任务",
        "保存为观察任务",
        "创建核验任务",
        "生成核验任务",
        "保存核验任务",
        "保存为核验任务",
    )
    WRITEBACK_NEGATIONS = ("不要", "不用", "无需", "暂不", "先不")
    PUBLIC_CITATION_FIELDS = (
        "id",
        "claim_id",
        "source_name",
        "source_url",
        "evidence_type",
        "data_time",
        "report_period",
        "excerpt",
        "limitations",
        "created_at",
    )
    PUBLIC_WRITEBACK_FIELDS = (
        "id",
        "symbol",
        "candidate_type",
        "status",
        "payload",
        "citation_ids",
        "base_version",
        "created_at",
        "resolved_at",
    )

    def __init__(
        self,
        database: Database,
        stock_domain: StockDomainService,
        observation_tasks: ObservationTaskService,
    ):
        self.database = database
        self.stock_domain = stock_domain
        self.observation_tasks = observation_tasks

    def build_and_persist(
        self,
        *,
        user_id: str,
        run: dict[str, Any],
        evidence: dict[str, Any],
        answer: str,
        message: str,
        conversation_id: str | None,
        symbol: str | None,
    ) -> dict[str, Any] | None:
        if str(run.get("intent") or evidence.get("type") or "") != "stock_research":
            return None
        ledger = evidence.get("research_claims") or build_research_claim_ledger(
            evidence
        )
        claims = list(ledger.get("claims") or [])
        stored_citations = self._persist_citations(
            user_id=user_id,
            run_id=str(run["id"]),
            claims=claims,
        )
        citation_by_claim = {
            str(item.get("claim_id")): str(item.get("id"))
            for item in stored_citations
        }

        def structured_claims(relation: str) -> list[dict[str, Any]]:
            output = []
            for claim in claims:
                if claim.get("relation") != relation:
                    continue
                citation_id = citation_by_claim.get(str(claim.get("id")))
                output.append(
                    {
                        "id": claim.get("id"),
                        "text": claim.get("claim"),
                        "evidence_summary": claim.get("evidence_summary"),
                        "citation_ids": [citation_id] if citation_id else [],
                        "supporting_citation_ids": (
                            [citation_id]
                            if citation_id and relation == "supports"
                            else []
                        ),
                        "data_time": claim.get("data_time"),
                        "report_period": claim.get("report_period"),
                        "limitations": list(claim.get("limitations") or []),
                        "next_step": claim.get("next_step"),
                    }
                )
            return output

        confirmed_facts = []
        for claim in claims:
            fact = str(claim.get("evidence_summary") or "").strip()
            citation_id = citation_by_claim.get(str(claim.get("id")))
            if (
                not fact
                or not citation_id
                or claim.get("evidence_type")
                not in {"official_disclosure", "structured_data", "system_calculation"}
            ):
                continue
            confirmed_facts.append(
                {
                    "id": f"fact-{claim.get('id')}",
                    "text": fact,
                    "citation_ids": [citation_id],
                    "data_time": claim.get("data_time"),
                    "report_period": claim.get("report_period"),
                    "coverage_status": claim.get("coverage_status"),
                }
            )

        invalidation_conditions = []
        for item in ledger.get("invalidation_conditions") or []:
            citation_ids = self._unique_text(
                [
                    citation_by_claim.get(str(claim_id))
                    for claim_id in item.get("related_claim_ids") or []
                ],
                limit=8,
            )
            invalidation_conditions.append(
                {
                    "id": item.get("id"),
                    "label": item.get("label"),
                    "condition": item.get("condition"),
                    "meaning": item.get("meaning"),
                    "citation_ids": citation_ids,
                }
            )

        next_evidence_tasks = []
        for claim in claims:
            description = " ".join(str(claim.get("next_step") or "").split())
            if not description:
                continue
            next_evidence_tasks.append(
                {
                    "id": f"next-{claim.get('id')}",
                    "description": description,
                    "related_claim_ids": [claim.get("id")],
                    "citation_ids": [
                        citation_by_claim[str(claim.get("id"))]
                    ]
                    if str(claim.get("id")) in citation_by_claim
                    else [],
                }
            )
        for gap in ledger.get("information_gaps") or []:
            description = " ".join(str(gap.get("description") or "").split())
            if not description:
                continue
            next_evidence_tasks.append(
                {
                    "id": f"next-{gap.get('id')}",
                    "description": description,
                    "related_claim_ids": list(gap.get("related_claim_ids") or []),
                    "citation_ids": self._unique_text(
                        [
                            citation_by_claim.get(str(claim_id))
                            for claim_id in gap.get("related_claim_ids") or []
                        ],
                        limit=8,
                    ),
                }
            )

        writebacks: list[dict[str, Any]] = []
        if (
            run.get("status") == "completed"
            and symbol
            and self._wants_thesis_writeback(message)
        ):
            candidate = self._create_thesis_writeback(
                user_id=user_id,
                run_id=str(run["id"]),
                conversation_id=conversation_id,
                symbol=symbol,
                evidence=evidence,
                ledger=ledger,
                citation_by_claim=citation_by_claim,
            )
            if candidate is not None:
                writebacks.append(self.public_writeback(candidate))
        if (
            run.get("status") == "completed"
            and symbol
            and self._wants_observation_task_writeback(message)
        ):
            candidate = self._create_observation_task_writeback(
                user_id=user_id,
                run_id=str(run["id"]),
                conversation_id=conversation_id,
                symbol=symbol,
                evidence=evidence,
                next_evidence_tasks=next_evidence_tasks,
            )
            if candidate is not None:
                writebacks.append(self.public_writeback(candidate))

        status = (
            "complete"
            if run.get("status") == "completed" and claims
            else "partial"
            if claims
            else "unavailable"
        )
        return {
            "contract_version": self.CONTRACT_VERSION,
            "status": status,
            "answer_summary": self._answer_summary(answer),
            "confirmed_facts": confirmed_facts[:8],
            "evidence_based_inferences": structured_claims("supports")[:8],
            "hypotheses_to_verify": structured_claims("unresolved")[:8],
            "counter_evidence_and_risks": structured_claims("weakens")[:8],
            "information_gaps": list(ledger.get("information_gaps") or [])[:8],
            "invalidation_conditions": invalidation_conditions[:8],
            "next_evidence_tasks": next_evidence_tasks[:8],
            "stage_updates": [],
            "conclusion_boundary": ledger.get("boundary")
            or "结构化证据只用于研究复核，不构成交易建议。",
            "citations": [
                self.public_citation(item) for item in stored_citations
            ],
            "candidate_writebacks": writebacks,
        }

    def list_writebacks(
        self, *, user_id: str, status: str | None = None, limit: int = 100
    ) -> dict[str, Any]:
        allowed = {"pending_confirmation", "confirmed", "rejected", "stale"}
        if status is not None and status not in allowed:
            raise StructuredAIInvalidState("未知的候选写回状态")
        params: list[Any] = [user_id]
        status_clause = ""
        if status is not None:
            status_clause = "AND status = ?"
            params.append(status)
        params.append(max(1, min(int(limit), 300)))
        with self.database.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM ai_writeback_candidates
                WHERE user_id = ? {status_clause}
                ORDER BY created_at DESC, rowid DESC LIMIT ?
                """,
                params,
            ).fetchall()
        items = [self.public_writeback(self._writeback_row(row)) for row in rows]
        return {
            "contract_version": self.CONTRACT_VERSION,
            "items": items,
            "summary": {
                "total": len(items),
                "pending_confirmation": sum(
                    item["status"] == "pending_confirmation" for item in items
                ),
            },
        }

    def get_writeback(self, *, user_id: str, candidate_id: str) -> dict[str, Any]:
        candidate = self._get_writeback(user_id, candidate_id)
        if candidate is None:
            raise StructuredAINotFound("候选写回不存在")
        return self.public_writeback(candidate)

    def confirm_writeback(self, *, user_id: str, candidate_id: str) -> dict[str, Any]:
        candidate = self._get_writeback(user_id, candidate_id)
        if candidate is None:
            raise StructuredAINotFound("候选写回不存在")
        if candidate["status"] == "confirmed":
            return self._confirmed_writeback(candidate)
        if candidate["status"] != "pending_confirmation":
            raise StructuredAIInvalidState("该候选写回已经处理")
        if candidate["candidate_type"] == "observation_task":
            return self._confirm_observation_task(candidate)
        if candidate["candidate_type"] != "thesis":
            raise StructuredAIInvalidState("未知的候选写回类型")
        payload = candidate["payload"]
        workspace = self.database.get_stock_workspace(user_id, candidate["symbol"])
        if workspace is None:
            raise StructuredAINotFound("股票研究空间不存在")
        active = self.database.get_active_thesis(user_id, str(workspace["id"]))
        current_version = int(active["version_no"]) if active else 0
        if current_version != int(candidate["base_version"]):
            with self.database.connect() as connection:
                connection.execute(
                    """
                    UPDATE ai_writeback_candidates
                    SET status = 'stale', resolved_at = ?
                    WHERE id = ? AND user_id = ? AND status = 'pending_confirmation'
                    """,
                    (utc_now(), candidate_id, user_id),
                )
            raise StructuredAIConflict(
                f"正式判断已更新，当前版本为 {current_version}"
            )
        thesis = self.stock_domain.create_thesis_candidate(
            user_id=user_id,
            symbol=candidate["symbol"],
            reason_text=str(payload.get("reason_text") or ""),
            watch_items=list(payload.get("watch_items") or []),
            recheck_conditions=list(payload.get("recheck_conditions") or []),
            source="ai",
            source_run_id=candidate["run_id"],
            base_version=int(candidate["base_version"]),
        )
        confirmed = self.stock_domain.confirm_thesis(
            user_id=user_id,
            symbol=candidate["symbol"],
            thesis_id=str(thesis["id"]),
        )
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE ai_writeback_candidates
                SET status = 'confirmed', target_object_id = ?, resolved_at = ?
                WHERE id = ? AND user_id = ? AND status = 'pending_confirmation'
                """,
                (confirmed["id"], utc_now(), candidate_id, user_id),
            )
        refreshed = self._get_writeback(user_id, candidate_id)
        return {
            **self.public_writeback(refreshed),  # type: ignore[arg-type]
            "thesis": confirmed,
        }

    def _confirm_observation_task(self, candidate: dict[str, Any]) -> dict[str, Any]:
        workspace = self.database.get_stock_workspace(
            candidate["user_id"], candidate["symbol"]
        )
        if workspace is None or workspace.get("relation_type") == "ended":
            raise StructuredAIConflict("股票研究空间已结束，不能创建观察任务")
        payload = candidate["payload"]
        task = self.observation_tasks.create_task(
            user_id=candidate["user_id"],
            symbol=candidate["symbol"],
            title=str(payload.get("title") or "本轮研究证据核验"),
            description=str(payload.get("description") or "继续核验本轮研究证据。"),
            priority=str(payload.get("priority") or "normal"),
            due_at=payload.get("due_at"),
            source_type="research_action",
            source_ref_id=f"ai-writeback:{candidate['id']}",
        )
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE ai_writeback_candidates
                SET status = 'confirmed', target_object_id = ?, resolved_at = ?
                WHERE id = ? AND user_id = ? AND status = 'pending_confirmation'
                """,
                (task["id"], utc_now(), candidate["id"], candidate["user_id"]),
            )
        refreshed = self._get_writeback(candidate["user_id"], candidate["id"])
        return {
            **self.public_writeback(refreshed),  # type: ignore[arg-type]
            "observation_task": task,
        }

    def _confirmed_writeback(self, candidate: dict[str, Any]) -> dict[str, Any]:
        result = self.public_writeback(candidate)
        target_id = str(candidate.get("target_object_id") or "")
        if candidate["candidate_type"] == "thesis" and target_id:
            thesis = self.database.get_thesis_version(candidate["user_id"], target_id)
            if thesis is not None:
                result["thesis"] = thesis
        elif candidate["candidate_type"] == "observation_task" and target_id:
            result["observation_task"] = self.observation_tasks.get_task(
                user_id=candidate["user_id"], task_id=target_id
            )
        return result

    def reject_writeback(self, *, user_id: str, candidate_id: str) -> dict[str, Any]:
        candidate = self._get_writeback(user_id, candidate_id)
        if candidate is None:
            raise StructuredAINotFound("候选写回不存在")
        if candidate["status"] != "pending_confirmation":
            raise StructuredAIInvalidState("该候选写回已经处理")
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE ai_writeback_candidates
                SET status = 'rejected', resolved_at = ?
                WHERE id = ? AND user_id = ? AND status = 'pending_confirmation'
                """,
                (utc_now(), candidate_id, user_id),
            )
        refreshed = self._get_writeback(user_id, candidate_id)
        return self.public_writeback(refreshed)  # type: ignore[arg-type]

    def _persist_citations(
        self, *, user_id: str, run_id: str, claims: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        now = utc_now()
        with self.database.connect() as connection:
            for claim in claims:
                claim_id = str(claim.get("id") or "").strip()
                excerpt = str(
                    claim.get("evidence_summary") or claim.get("claim") or ""
                ).strip()
                if not claim_id or not excerpt:
                    continue
                connection.execute(
                    """
                    INSERT OR IGNORE INTO ai_citations(
                        id, user_id, run_id, claim_id, source_name, source_key,
                        source_url, evidence_type, data_time, report_period,
                        excerpt, limitations_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid4()),
                        user_id,
                        run_id,
                        claim_id,
                        str(claim.get("source_name") or "结构化证据"),
                        claim.get("source_key"),
                        claim.get("source_url"),
                        str(claim.get("evidence_type") or "system_record"),
                        claim.get("data_time"),
                        claim.get("report_period"),
                        excerpt,
                        json_dumps(list(claim.get("limitations") or [])),
                        now,
                    ),
                )
            rows = connection.execute(
                """
                SELECT * FROM ai_citations
                WHERE user_id = ? AND run_id = ?
                ORDER BY created_at ASC, rowid ASC
                """,
                (user_id, run_id),
            ).fetchall()
        return [self._citation_row(row) for row in rows]

    def _create_thesis_writeback(
        self,
        *,
        user_id: str,
        run_id: str,
        conversation_id: str | None,
        symbol: str,
        evidence: dict[str, Any],
        ledger: dict[str, Any],
        citation_by_claim: dict[str, str],
    ) -> dict[str, Any] | None:
        canonical = normalize_symbol(symbol)
        workspace = self.database.get_stock_workspace(user_id, canonical)
        if workspace is None or workspace.get("relation_type") == "ended":
            return None
        active = self.database.get_active_thesis(user_id, str(workspace["id"]))
        base_version = int(active["version_no"]) if active else 0
        claims = list(ledger.get("claims") or [])
        supports = [item for item in claims if item.get("relation") == "supports"]
        weakens = [item for item in claims if item.get("relation") == "weakens"]
        unresolved = [item for item in claims if item.get("relation") == "unresolved"]
        if not claims:
            return None
        name = str(evidence.get("display_name") or workspace.get("name") or canonical)
        parts = []
        if active and active.get("reason_text"):
            parts.append(str(active["reason_text"]).rstrip("。"))
        elif supports:
            parts.append(f"{name}当前支持证据：{supports[0].get('claim')}")
        else:
            parts.append(f"继续研究{name}，当前结论仍需更多证据确认")
        if supports and str(supports[0].get("claim") or "") not in parts[0]:
            parts.append(f"本轮新增支持证据：{supports[0].get('claim')}")
        counter = weakens[0] if weakens else unresolved[0] if unresolved else None
        if counter:
            parts.append(f"反方与待核验：{counter.get('claim')}")
        reason_text = "。".join(part for part in parts if part).strip()[:1000].rstrip("。") + "。"

        watch_items = self._unique_text(
            [
                *(item.get("next_step") for item in [*weakens, *unresolved]),
                *(
                    item.get("description")
                    for item in ledger.get("information_gaps") or []
                ),
            ],
            limit=8,
        )
        recheck_conditions = self._unique_text(
            [
                item.get("condition")
                for item in ledger.get("invalidation_conditions") or []
            ],
            limit=8,
        )
        selected_claims = [*supports[:2], *weakens[:2], *unresolved[:2]]
        citation_ids = self._unique_text(
            [citation_by_claim.get(str(item.get("id"))) for item in selected_claims],
            limit=8,
        )
        payload = {
            "current_reason_text": active.get("reason_text") if active else None,
            "reason_text": reason_text,
            "watch_items": watch_items,
            "recheck_conditions": recheck_conditions,
        }
        now = utc_now()
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO ai_writeback_candidates(
                    id, user_id, run_id, conversation_id, workspace_id, symbol,
                    candidate_type, status, payload_json, citation_ids_json,
                    base_version, target_object_id, created_at, resolved_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'thesis', 'pending_confirmation',
                    ?, ?, ?, NULL, ?, NULL)
                """,
                (
                    str(uuid4()),
                    user_id,
                    run_id,
                    conversation_id,
                    workspace["id"],
                    canonical,
                    json_dumps(payload),
                    json_dumps(citation_ids),
                    base_version,
                    now,
                ),
            )
            row = connection.execute(
                """
                SELECT * FROM ai_writeback_candidates
                WHERE user_id = ? AND run_id = ? AND candidate_type = 'thesis'
                """,
                (user_id, run_id),
            ).fetchone()
        return self._writeback_row(row) if row is not None else None

    def _create_observation_task_writeback(
        self,
        *,
        user_id: str,
        run_id: str,
        conversation_id: str | None,
        symbol: str,
        evidence: dict[str, Any],
        next_evidence_tasks: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        canonical = normalize_symbol(symbol)
        workspace = self.database.get_stock_workspace(user_id, canonical)
        if (
            workspace is None
            or workspace.get("relation_type") == "ended"
            or not next_evidence_tasks
        ):
            return None
        descriptions = self._unique_text(
            [item.get("description") for item in next_evidence_tasks], limit=6
        )
        if not descriptions:
            return None
        name = str(evidence.get("display_name") or workspace.get("name") or canonical)
        citation_ids = self._unique_text(
            [
                citation_id
                for item in next_evidence_tasks
                for citation_id in item.get("citation_ids") or []
            ],
            limit=8,
        )
        payload = {
            "title": f"{name}｜本轮证据核验"[:160],
            "description": "；".join(
                f"{index}. {description}"
                for index, description in enumerate(descriptions, start=1)
            )[:2000],
            "priority": "normal",
            "due_at": None,
            "source_task_ids": [
                str(item.get("id"))
                for item in next_evidence_tasks[:6]
                if item.get("id")
            ],
        }
        now = utc_now()
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO ai_writeback_candidates(
                    id, user_id, run_id, conversation_id, workspace_id, symbol,
                    candidate_type, status, payload_json, citation_ids_json,
                    base_version, target_object_id, created_at, resolved_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'observation_task',
                    'pending_confirmation', ?, ?, 0, NULL, ?, NULL)
                """,
                (
                    str(uuid4()),
                    user_id,
                    run_id,
                    conversation_id,
                    workspace["id"],
                    canonical,
                    json_dumps(payload),
                    json_dumps(citation_ids),
                    now,
                ),
            )
            row = connection.execute(
                """
                SELECT * FROM ai_writeback_candidates
                WHERE user_id = ? AND run_id = ?
                    AND candidate_type = 'observation_task'
                """,
                (user_id, run_id),
            ).fetchone()
        return self._writeback_row(row) if row is not None else None

    def _get_writeback(
        self, user_id: str, candidate_id: str
    ) -> dict[str, Any] | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM ai_writeback_candidates
                WHERE id = ? AND user_id = ?
                """,
                (candidate_id, user_id),
            ).fetchone()
        return self._writeback_row(row) if row is not None else None

    @staticmethod
    def _citation_row(row: Any) -> dict[str, Any]:
        item = dict(row)
        item["limitations"] = json.loads(item.pop("limitations_json"))
        return item

    @staticmethod
    def _writeback_row(row: Any) -> dict[str, Any]:
        item = dict(row)
        item["payload"] = json.loads(item.pop("payload_json"))
        item["citation_ids"] = json.loads(item.pop("citation_ids_json"))
        return item

    @classmethod
    def public_citation(cls, citation: dict[str, Any]) -> dict[str, Any]:
        return {
            key: citation.get(key)
            for key in cls.PUBLIC_CITATION_FIELDS
        }

    @classmethod
    def public_writeback(cls, candidate: dict[str, Any]) -> dict[str, Any]:
        return {
            key: candidate.get(key)
            for key in cls.PUBLIC_WRITEBACK_FIELDS
        }

    @classmethod
    def _wants_thesis_writeback(cls, message: str) -> bool:
        text = " ".join(str(message or "").split())
        if "判断" not in text:
            return False
        return cls._contains_non_negated_term(text, cls.THESIS_WRITEBACK_TERMS)

    @classmethod
    def _wants_observation_task_writeback(cls, message: str) -> bool:
        text = " ".join(str(message or "").split())
        if "任务" not in text:
            return False
        return cls._contains_non_negated_term(
            text, cls.OBSERVATION_TASK_WRITEBACK_TERMS
        )

    @classmethod
    def _contains_non_negated_term(
        cls, text: str, terms: tuple[str, ...]
    ) -> bool:
        for term in terms:
            start = text.find(term)
            if start < 0:
                continue
            prefix = text[max(0, start - 8) : start]
            if any(negation in prefix for negation in cls.WRITEBACK_NEGATIONS):
                continue
            return True
        return False

    @staticmethod
    def _answer_summary(answer: str) -> str:
        for block in re.split(r"\n\s*\n", str(answer or "")):
            clean = re.sub(r"^[#>*\-\d.、\s]+", "", block.strip())
            clean = re.sub(r"[*_`]", "", clean).strip()
            if len(clean) >= 16 and clean not in {"结论", "一句话结论"}:
                return clean[:500]
        return str(answer or "").strip()[:500]

    @staticmethod
    def _unique_text(values: list[Any], limit: int) -> list[str]:
        output: list[str] = []
        for value in values:
            text = " ".join(str(value or "").split())
            if text and text not in output:
                output.append(text[:300])
            if len(output) >= limit:
                break
        return output
