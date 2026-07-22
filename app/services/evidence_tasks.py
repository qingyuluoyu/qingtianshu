from __future__ import annotations

import hashlib
from typing import Any

from app.catalog import RESEARCH_TARGETS, normalize_symbol
from app.db import Database
from app.utils import utc_now


_EXTERNAL_GAP_TERMS = (
    "行业供需",
    "订单",
    "客户集中",
    "客户结构",
    "供应链",
    "政策影响",
    "产能利用",
    "渠道库存",
)


class EvidenceUnavailable(RuntimeError):
    pass


class EvidenceTaskService:
    """Turn evidence gaps into durable work and reusable user knowledge."""

    METHOD = "deterministic_evidence_task_lifecycle_v1"
    PUBLIC_STATUS = {
        "pending": "等待后台补齐",
        "collecting": "正在补齐",
        "resolved": "已补齐并入库",
        "pending_external": "等待外部资料或新数据源",
        "failed": "等待下一轮重试",
    }

    def __init__(
        self,
        database: Database,
        *,
        research_evidence: Any,
        analysis: Any,
        china_info: Any,
        filings: Any,
        market_news: Any,
    ):
        self.database = database
        self.research_evidence = research_evidence
        self.analysis = analysis
        self.china_info = china_info
        self.filings = filings
        self.market_news = market_news

    def capture_from_chat(
        self,
        *,
        user_id: str,
        conversation_id: str,
        run_id: str | None,
        intent: str,
        message: str,
        evidence: dict[str, Any],
        symbol: str | None = None,
    ) -> dict[str, Any]:
        canonical = self._canonical_symbol(symbol or evidence.get("symbol"))
        market_key = str(
            evidence.get("market_key")
            or (evidence.get("market_drivers") or {}).get("market_key")
            or ""
        ).strip() or None
        specs: list[dict[str, Any]] = []

        if canonical:
            specs.extend(self._stock_gap_specs(canonical, evidence))
        if intent == "market_brief":
            specs.extend(self._market_gap_specs(market_key, evidence))

        tasks = []
        seen: set[tuple[str, str]] = set()
        for spec in specs:
            identity = (spec["task_type"], spec["gap_key"])
            if identity in seen:
                continue
            seen.add(identity)
            fingerprint = self._fingerprint(
                user_id=user_id,
                task_type=spec["task_type"],
                gap_key=spec["gap_key"],
                symbol=canonical,
                market_key=market_key,
            )
            task = self.database.upsert_evidence_task(
                {
                    "user_id": user_id,
                    "conversation_id": conversation_id,
                    "run_id": run_id,
                    "subject_kind": "stock" if canonical else "market",
                    "symbol": canonical,
                    "market_key": market_key,
                    "intent": intent,
                    "task_type": spec["task_type"],
                    "gap_key": spec["gap_key"],
                    "title": spec["title"],
                    "description": spec["description"],
                    "query": f"{message}\n待补证：{spec['description']}",
                    "status": spec["status"],
                    "priority": spec["priority"],
                    "fingerprint": fingerprint,
                    "metadata": {
                        "method": self.METHOD,
                        "gap_text": spec["description"],
                        "resolution_check": spec.get("resolution_check"),
                        "evidence_generated_at": evidence.get("generated_at"),
                    },
                }
            )
            tasks.append(task)
        return {
            "captured": len(tasks),
            "tasks": [self.public_task(item) for item in tasks],
        }

    def get_packet(
        self,
        user_id: str,
        *,
        status: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        items = self.database.list_evidence_tasks(user_id, status=status, limit=limit)
        return {
            "generated_at": utc_now(),
            "method": self.METHOD,
            "summary": self.database.evidence_task_summary(user_id),
            "items": [self.public_task(item) for item in items],
            "boundary": (
                "已解决只表示指定资料已成功采集并写入用户资料库，不表示相关投资结论成立；"
                "等待外部资料的任务不会被系统伪装成已解决。"
            ),
        }

    def process_pending(
        self, *, user_id: str | None = None, limit: int = 10
    ) -> dict[str, Any]:
        candidates = self.database.list_pending_evidence_tasks(
            user_id=user_id, limit=limit
        )
        results = []
        for candidate in candidates:
            task = self.database.claim_evidence_task(
                candidate["id"], user_id=user_id
            )
            if task is None:
                continue
            try:
                outcome = self._execute(task)
                status = str(outcome.get("status") or "resolved")
                document_id = outcome.get("resolution_document_id")
                finished = self.database.finish_evidence_task(
                    task["id"],
                    status,
                    resolution_document_id=document_id,
                    metadata={
                        **(task.get("metadata") or {}),
                        **(outcome.get("metadata") or {}),
                        "processed_at": utc_now(),
                    },
                )
            except Exception as exc:
                finished = self.database.finish_evidence_task(
                    task["id"],
                    "failed",
                    error=f"{type(exc).__name__}: {exc}",
                    metadata={
                        **(task.get("metadata") or {}),
                        "processed_at": utc_now(),
                    },
                )
            if finished is not None:
                results.append(self.public_task(finished))
        summary = {
            "requested": len(candidates),
            "processed": len(results),
            "resolved": sum(item["status"] == "resolved" for item in results),
            "pending_external": sum(
                item["status"] == "pending_external" for item in results
            ),
            "failed": sum(item["status"] == "failed" for item in results),
        }
        return {"generated_at": utc_now(), "summary": summary, "items": results}

    def _execute(self, task: dict[str, Any]) -> dict[str, Any]:
        task_type = task["task_type"]
        if task_type == "market_news_refresh":
            return self._refresh_market_news(task)
        if task_type == "market_snapshot_refresh":
            return self._refresh_market_snapshot(task)
        if task_type == "a_share_information_refresh":
            return self._refresh_a_share_information(task)
        if task_type == "a_share_filing_refresh":
            return self._refresh_a_share_filing(task)
        if task_type == "stock_research_refresh":
            return self._refresh_stock_research(task)
        return {
            "status": "pending_external",
            "metadata": {"resolution_note": "当前工具链没有可靠的自动采集器。"},
        }

    def _refresh_market_news(self, task: dict[str, Any]) -> dict[str, Any]:
        packet = self.market_news.get_packet(
            task["query"], market_key=task.get("market_key"), limit=12
        )
        items = list(packet.get("items") or [])
        if not items:
            raise EvidenceUnavailable("本轮没有形成可用的市场新闻条目")
        lines = [
            f"# {packet.get('market_label') or task.get('market_key') or '市场'}最新事件证据",
            "",
            f"补证时间：{packet.get('generated_at') or utc_now()}",
            f"原研究问题：{task['query'].splitlines()[0]}",
            "",
            "## 已采集条目",
        ]
        for item in items:
            lines.extend(self._news_lines(item))
        lines.extend(
            [
                "",
                "## 使用边界",
                str(packet.get("interpretation") or "新闻标题不能单独证明市场涨跌因果。"),
            ]
        )
        document = self._write_document(task, "市场事件补证", "\n".join(lines))
        return {
            "status": "resolved",
            "resolution_document_id": document["id"],
            "metadata": {"evidence_items": len(items)},
        }

    def _refresh_market_snapshot(self, task: dict[str, Any]) -> dict[str, Any]:
        packet = self.analysis.market_brief(market_key=task.get("market_key"))
        indices = [
            item for item in packet.get("indices") or [] if item.get("status") == "available"
        ]
        if not indices:
            raise EvidenceUnavailable("本轮没有形成可用的代表性指数证据")
        lines = [
            "# 市场代表性指数补证",
            "",
            f"补证时间：{packet.get('generated_at') or utc_now()}",
            f"原研究问题：{task['query'].splitlines()[0]}",
            "",
        ]
        for item in indices:
            metrics = item.get("metrics") or {}
            lines.append(
                "- "
                f"{item.get('name') or item.get('symbol')}（{item.get('symbol')}）："
                f"1日收益 {metrics.get('return_1d_pct')}%，"
                f"MA20 {metrics.get('ma20')}，MA60 {metrics.get('ma60')}；"
                f"数据时间 {item.get('market_timestamp')}；来源 {item.get('source')}"
            )
        lines.extend(["", "这些数据描述已发生行情，不构成下一交易日预测。"])
        document = self._write_document(task, "市场指数补证", "\n".join(lines))
        return {
            "status": "resolved",
            "resolution_document_id": document["id"],
            "metadata": {"available_indices": len(indices)},
        }

    def _refresh_a_share_information(self, task: dict[str, Any]) -> dict[str, Any]:
        symbol = self._required_symbol(task)
        self.china_info.refresh_symbol(symbol)
        packet = self.china_info.get_packet(symbol, refresh_max_age_seconds=3600)
        items = list(packet.get("announcements") or []) + list(packet.get("news") or [])
        if not items:
            raise EvidenceUnavailable("本轮没有形成可用的公告或公司新闻")
        lines = [
            f"# {self._subject_name(symbol)}公告与新闻补证",
            "",
            f"补证时间：{packet.get('generated_at') or utc_now()}",
            f"原研究问题：{task['query'].splitlines()[0]}",
            "",
            "## 公司公告与新闻",
        ]
        for item in items[:20]:
            lines.extend(self._news_lines(item))
        lines.extend(
            [
                "",
                "公司公告优先于媒体标题；媒体线索需要回看原文后再确认因果。",
            ]
        )
        document = self._write_document(task, "公司信息补证", "\n".join(lines))
        return {
            "status": "resolved",
            "resolution_document_id": document["id"],
            "metadata": {"evidence_items": len(items)},
        }

    def _refresh_a_share_filing(self, task: dict[str, Any]) -> dict[str, Any]:
        symbol = self._required_symbol(task)
        refresh = self.filings.refresh_symbol(symbol, limit=3, force=True)
        overview = self.filings.get_overview(symbol, refresh_if_missing=False)
        documents = list(overview.get("documents") or [])
        if not documents:
            raise EvidenceUnavailable("本轮没有形成可用的财报全文")
        packet = overview.get("cause_evidence") or {}
        lines = [
            f"# {self._subject_name(symbol)}财报原文补证",
            "",
            f"补证时间：{refresh.get('refreshed_at') or utc_now()}",
            f"原研究问题：{task['query'].splitlines()[0]}",
            "",
            "## 已保存财报",
        ]
        for item in documents:
            lines.append(
                f"- {item.get('title')}｜报告期 {item.get('report_period') or '待确认'}｜"
                f"发布日期 {item.get('published_at') or item.get('notice_date') or '待确认'}｜"
                f"来源 {item.get('source') or '公司披露'}｜{item.get('source_url') or item.get('attach_url') or ''}"
            )
        explanations = list(packet.get("explicit_company_explanations") or [])
        if explanations:
            lines.extend(["", "## 公司原文中的显式解释"])
            for item in explanations[:12]:
                lines.append(f"- {item.get('text') or item.get('excerpt') or item}")
        lines.extend(["", "提取结果必须回到财报原文核对，不把模型推断写成公司解释。"])
        document = self._write_document(task, "财报原文补证", "\n".join(lines))
        return {
            "status": "resolved",
            "resolution_document_id": document["id"],
            "metadata": {"documents": len(documents)},
        }

    def _refresh_stock_research(self, task: dict[str, Any]) -> dict[str, Any]:
        symbol = self._required_symbol(task)
        evidence = self.research_evidence.build(task["user_id"], symbol)
        if not self._stock_gap_is_resolved(task, evidence):
            return {
                "status": "pending_external",
                "metadata": {
                    "resolution_note": "现有自动数据源刷新后，该证据维度仍未满足。",
                    "last_evidence_at": evidence.get("generated_at"),
                },
            }
        readiness = evidence.get("evidence_readiness") or {}
        lines = [
            f"# {self._subject_name(symbol)}研究证据补齐记录",
            "",
            f"补证时间：{evidence.get('generated_at') or utc_now()}",
            f"原研究问题：{task['query'].splitlines()[0]}",
            f"本次补齐维度：{task['description']}",
            f"证据完整度：{readiness.get('label') or '已重新计算'}（{readiness.get('coverage_ratio')}）",
            "",
            "## 当前可验证事实",
        ]
        for fact in evidence.get("facts") or []:
            lines.append(f"- {fact}")
        modules = (evidence.get("analysis_board") or {}).get("modules") or []
        if modules:
            lines.extend(["", "## 模块状态"])
            for item in modules:
                lines.append(
                    f"- {item.get('label')}：{item.get('status')}，"
                    f"证据数 {item.get('evidence_count', 0)}"
                )
        information = (
            evidence.get("a_share_information")
            or evidence.get("global_information")
            or {}
        )
        source_items = list(information.get("announcements") or []) + list(
            information.get("news") or []
        )
        if source_items:
            lines.extend(["", "## 最新公司信息"])
            for item in source_items[:12]:
                lines.extend(self._news_lines(item))
        provenance = evidence.get("provenance") or {}
        lines.extend(
            [
                "",
                "## 主要数据来源",
                f"- 行情来源：{provenance.get('source') or '见各模块来源'}",
                f"- 行情时间：{provenance.get('market_timestamp') or '见各模块数据时间'}",
                "",
                "该文档只证明资料已采集并结构化，不自动证明看多、看空或任何交易动作。",
            ]
        )
        document = self._write_document(task, "个股研究补证", "\n".join(lines))
        return {
            "status": "resolved",
            "resolution_document_id": document["id"],
            "metadata": {
                "coverage_ratio": readiness.get("coverage_ratio"),
                "last_evidence_at": evidence.get("generated_at"),
            },
        }

    def _stock_gap_specs(
        self, symbol: str, evidence: dict[str, Any]
    ) -> list[dict[str, Any]]:
        readiness = evidence.get("evidence_readiness") or (
            evidence.get("analysis_board") or {}
        ).get("readiness") or {}
        specs = []
        for label in readiness.get("missing_core_modules") or []:
            specs.append(
                self._gap_spec(
                    symbol,
                    str(label),
                    core=True,
                    resolution_check=f"core:{label}",
                )
            )
        optional = list(readiness.get("optional_gaps") or [])
        if not optional:
            optional = list(
                (evidence.get("research_frame") or {}).get("missing_information")
                or []
            )
        for gap in optional:
            specs.append(
                self._gap_spec(
                    symbol,
                    str(gap),
                    core=False,
                    resolution_check=f"optional:{gap}",
                )
            )
        for limit in (evidence.get("business_structure") or {}).get(
            "coverage_limits", []
        ):
            gap = str(
                limit.get("label")
                or limit.get("boundary")
                or limit.get("next_evidence")
                or "主营结构扩展证据"
            )
            specs.append(
                self._gap_spec(
                    symbol,
                    gap,
                    core=False,
                    resolution_check=f"business:{limit.get('key') or gap}",
                    force_external=True,
                )
            )
        return specs

    def _market_gap_specs(
        self, market_key: str | None, evidence: dict[str, Any]
    ) -> list[dict[str, Any]]:
        specs = []
        indices = list(evidence.get("indices") or [])
        if indices and not any(item.get("status") == "available" for item in indices):
            specs.append(
                {
                    "task_type": "market_snapshot_refresh",
                    "gap_key": "market_indices_unavailable",
                    "title": "重新采集代表性指数",
                    "description": "代表性指数本轮未形成可验证行情快照",
                    "status": "pending",
                    "priority": 95,
                    "resolution_check": "market:indices",
                }
            )
        market_drivers = evidence.get("market_drivers") or {}
        if not market_drivers.get("items"):
            specs.append(
                {
                    "task_type": "market_news_refresh",
                    "gap_key": f"market_news:{market_key or 'china'}",
                    "title": "补齐市场事件证据",
                    "description": "当前市场问题缺少可交叉核验的最新事件与新闻条目",
                    "status": "pending",
                    "priority": 85,
                    "resolution_check": "market:news",
                }
            )
        return specs

    def _gap_spec(
        self,
        symbol: str,
        gap: str,
        *,
        core: bool,
        resolution_check: str,
        force_external: bool = False,
    ) -> dict[str, Any]:
        external = force_external or any(term in gap for term in _EXTERNAL_GAP_TERMS)
        if external:
            task_type = "external_research"
            status = "pending_external"
            title = "等待外部专业证据"
        elif symbol.endswith((".SS", ".SZ")) and any(
            term in gap for term in ("财报全文", "财报原文", "附注")
        ):
            task_type = "a_share_filing_refresh"
            status = "pending"
            title = "补齐公司披露原文"
        elif symbol.endswith((".SS", ".SZ")) and any(
            term in gap for term in ("公告", "新闻", "事件")
        ):
            task_type = "a_share_information_refresh"
            status = "pending"
            title = "补齐公告与公司信息"
        else:
            task_type = "stock_research_refresh"
            status = "pending"
            title = "刷新个股研究证据"
        return {
            "task_type": task_type,
            "gap_key": "gap:" + hashlib.sha256(gap.encode("utf-8")).hexdigest()[:16],
            "title": title,
            "description": gap,
            "status": status,
            "priority": 95 if core else (45 if external else 70),
            "resolution_check": resolution_check,
        }

    @staticmethod
    def _stock_gap_is_resolved(
        task: dict[str, Any], evidence: dict[str, Any]
    ) -> bool:
        check = str((task.get("metadata") or {}).get("resolution_check") or "")
        readiness = evidence.get("evidence_readiness") or (
            evidence.get("analysis_board") or {}
        ).get("readiness") or {}
        if check.startswith("core:"):
            label = check.removeprefix("core:")
            return label not in set(readiness.get("missing_core_modules") or [])
        if check.startswith("optional:"):
            gap = check.removeprefix("optional:")
            return gap not in set(readiness.get("optional_gaps") or [])
        if check.startswith("business:"):
            return False
        return str(readiness.get("status")) in {"ready", "usable"}

    def _write_document(
        self, task: dict[str, Any], kind: str, content: str
    ) -> dict[str, Any]:
        document_id = "evidence-" + hashlib.sha256(
            str(task["id"]).encode("utf-8")
        ).hexdigest()[:24]
        subject = task.get("symbol") or task.get("market_key") or "研究问题"
        return self.database.upsert_knowledge_document(
            document_id=document_id,
            owner_user_id=task["user_id"],
            scope="user",
            title=f"{self._subject_name(str(subject))}｜{kind}",
            original_name=f"{task['task_type']}-{task['id']}.md",
            mime_type="text/markdown",
            content=content,
            source_key=f"evidence-task:{task['id']}",
        )

    @classmethod
    def public_task(cls, task: dict[str, Any]) -> dict[str, Any]:
        metadata = task.get("metadata") or {}
        return {
            key: task.get(key)
            for key in (
                "id",
                "conversation_id",
                "run_id",
                "subject_kind",
                "symbol",
                "market_key",
                "intent",
                "task_type",
                "gap_key",
                "title",
                "description",
                "query",
                "status",
                "priority",
                "resolution_document_id",
                "retry_count",
                "max_retries",
                "created_at",
                "updated_at",
                "last_seen_at",
                "started_at",
                "resolved_at",
            )
        } | {
            "status_label": cls.PUBLIC_STATUS.get(task.get("status"), "待处理"),
            "resolution_note": metadata.get("resolution_note"),
            "processed_at": metadata.get("processed_at"),
        }

    @staticmethod
    def _news_lines(item: dict[str, Any]) -> list[str]:
        title = str(item.get("title") or "未命名条目").strip()
        source = str(item.get("source") or "来源待确认").strip()
        published = item.get("published_at") or "时间待确认"
        url = str(item.get("url") or "").strip()
        summary = str(item.get("summary") or "").strip()
        line = f"- {title}｜{source}｜{published}"
        if url:
            line += f"｜{url}"
        return [line] + ([f"  - 摘要：{summary}"] if summary else [])

    @staticmethod
    def _canonical_symbol(value: Any) -> str | None:
        if not value:
            return None
        try:
            return normalize_symbol(str(value))
        except ValueError:
            return None

    @staticmethod
    def _required_symbol(task: dict[str, Any]) -> str:
        symbol = str(task.get("symbol") or "").strip()
        if not symbol:
            raise EvidenceUnavailable("任务缺少证券代码")
        return symbol

    @staticmethod
    def _subject_name(symbol_or_market: str) -> str:
        target = RESEARCH_TARGETS.get(symbol_or_market, {})
        return str(target.get("name") or symbol_or_market)

    @staticmethod
    def _fingerprint(
        *,
        user_id: str,
        task_type: str,
        gap_key: str,
        symbol: str | None,
        market_key: str | None,
    ) -> str:
        stable = "|".join(
            (user_id, task_type, gap_key, symbol or "", market_key or "")
        )
        return hashlib.sha256(stable.encode("utf-8")).hexdigest()
