from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from difflib import SequenceMatcher
import hashlib
from pathlib import Path
import re
from statistics import median
from typing import Any

from app.db import Database
from app.utils import json_dumps, utc_now, write_json


EVIDENCE_INTENTS = {
    "market_brief",
    "stock_research",
    "earnings_quality",
    "financial_drivers",
    "business_structure",
    "shareholder_structure",
    "analyst_expectations",
    "event_timeline",
    "research_tracking",
    "research_actions",
    "research_outcome",
    "watchlist_brief",
}

DATA_GAP_KEYWORDS = {
    "market_turnover": (
        "成交额缺失",
        "未提供成交额",
        "缺少全市场成交额",
        "没有全市场成交额",
        "全市场成交额不可用",
    ),
    "market_distribution": (
        "个股涨幅分布缺失",
        "个股涨跌幅分布缺失",
        "缺少个股涨幅分布",
        "缺少个股涨跌幅分布",
        "未提供个股涨跌幅分布",
        "分档分布数据缺少",
    ),
    "index_contribution": ("成分贡献度", "权重贡献", "指数贡献度"),
    "industry_components": ("行业成分股", "板块成分股", "完整行业指数"),
    "industry_supply_demand": ("行业供需", "库存", "开工率", "产能"),
    "company_orders": ("在手订单", "订单可见度", "客户集中度"),
    "institutional_holdings": ("机构持仓", "基金持仓", "持仓穿透"),
    "analyst_history": ("一致预期历史", "预期修订历史", "研报全文"),
    "sentiment_coverage": ("情绪样本不足", "社区样本不足", "情绪数据缺失"),
}

DATA_GAP_LABELS = {
    "market_turnover": "A股全市场成交额与同口径历史",
    "market_distribution": "A股个股涨跌幅分布",
    "index_contribution": "指数成分贡献度",
    "industry_components": "行业指数与成分股口径",
    "industry_supply_demand": "行业供需、库存、产能与开工率",
    "company_orders": "公司订单、客户结构与集中度",
    "institutional_holdings": "机构与基金持仓穿透",
    "analyst_history": "研报全文与一致预期长历史",
    "sentiment_coverage": "更完整的新闻与社区情绪覆盖",
}

MIN_SCORABLE_ASSISTANT_MESSAGES = 10
MIN_SCORABLE_RUNS = 10
_USER_FACING_OPERATIONAL_RE = re.compile(
    r"(?:数据源|行情源|主源|备用源|上游|降级|缓存(?:命中|回退)?|"
    r"接口(?:失败|错误)|请求失败|内部任务|job_name|ProxyError|WAF|HTTP\s*429|"
    r"当前[^。；\n]{0,24}未返回[^。；\n]{0,24}(?:日线|历史|数据))",
    re.IGNORECASE,
)


class ConversationQualityService:
    METHOD = "deterministic_conversation_quality_review_v3"

    def __init__(self, database: Database):
        self.database = database

    def analyze(
        self,
        user_id: str,
        *,
        conversation_limit: int = 100,
        run_limit: int = 500,
    ) -> dict[str, Any]:
        all_conversations = self.database.list_conversations(
            user_id, include_archived=True, limit=conversation_limit
        )
        evaluation_conversations = [
            item
            for item in all_conversations
            if item.get("quality_scope") == "evaluation"
        ]
        conversations = [
            item for item in all_conversations if item.get("quality_scope") != "evaluation"
        ]
        evaluation_conversation_ids = {
            str(item["id"]) for item in evaluation_conversations
        }
        evaluation_run_ids: set[str] = set()
        excluded_evaluation_messages = 0
        for conversation in evaluation_conversations:
            messages = self.database.list_conversation_messages(
                user_id, str(conversation["id"]), limit=500
            )
            excluded_evaluation_messages += len(messages)
            evaluation_run_ids.update(
                str(item["run_id"])
                for item in messages
                if item.get("run_id")
            )
        messages_by_conversation: dict[str, list[dict[str, Any]]] = {}
        all_messages: list[dict[str, Any]] = []
        for conversation in conversations:
            messages = self.database.list_conversation_messages(
                user_id, str(conversation["id"]), limit=500
            )
            messages_by_conversation[str(conversation["id"])] = messages
            all_messages.extend(messages)

        all_runs = self.database.list_user_runs(user_id, limit=run_limit)
        evaluation_runs = [
            run
            for run in all_runs
            if str(run.get("id") or "") in evaluation_run_ids
            or str((run.get("input") or {}).get("conversation_id") or "")
            in evaluation_conversation_ids
        ]
        runs = [
            run
            for run in all_runs
            if str(run.get("id") or "") not in evaluation_run_ids
            and str((run.get("input") or {}).get("conversation_id") or "")
            not in evaluation_conversation_ids
        ]
        excluded_evaluation_runs = len(all_runs) - len(runs)
        status_counts = Counter(str(run.get("status") or "unknown") for run in runs)
        intent_counts = Counter(str(run.get("intent") or "unknown") for run in runs)
        issues: list[dict[str, Any]] = []
        latency_summary = self._latency_breakdown(runs)

        failure_runs = [
            run for run in runs if run.get("status") in {"guarded", "degraded", "failed"}
        ]
        if failure_runs:
            issues.append(
                self._issue(
                    "run_fallbacks",
                    "critical" if any(run.get("status") == "failed" for run in failure_runs) else "attention",
                    "部分回答发生守卫回退或模型降级",
                    (
                        f"最近 {len(runs)} 个 Run 中有 {len(failure_runs)} 个状态为 "
                        "guarded、degraded 或 failed。"
                    ),
                    "逐条复盘 output_guard、错误类型和证据包，区分真实越界与守卫误杀。",
                    [self._run_example(run) for run in failure_runs[:5]],
                )
            )

        repaired_runs = [
            run
            for run in runs
            if (((run.get("usage") or {}).get("output_guard") or {}).get("repair"))
        ]
        if repaired_runs:
            issues.append(
                self._issue(
                    "guard_repairs",
                    "attention",
                    "模型回答需要行级修复后才能展示",
                    f"最近样本中有 {len(repaired_runs)} 个回答触发了数字或证据行修复。",
                    "保留修复安全网，同时把高频误杀转换为聚焦测试和 Prompt 约束。",
                    [self._run_example(run) for run in repaired_runs[:5]],
                )
            )

        slow_runs = [
            (run, latency)
            for run in runs
            if (latency := self._latency_seconds(run)) is not None and latency > 30
        ]
        if slow_runs:
            issues.append(
                self._issue(
                    "slow_answers",
                    "attention",
                    "部分 AI 回答等待时间超过 30 秒",
                    (
                        f"检测到 {len(slow_runs)} 个慢 Run；网页已反馈取证、生成、"
                        "守卫和保存阶段，并支持经过句级守卫的正文增量展示。"
                    ),
                    (
                        "结合首个模型片段、首个安全可见片段和总耗时，区分模型延迟、"
                        "长句等待与证据守卫耗时，再针对高频慢路径优化。"
                    ),
                    [
                        {
                            **self._run_example(run),
                            "latency_seconds": round(latency, 3),
                            "timings": (run.get("usage") or {}).get("timings")
                            or {},
                        }
                        for run, latency in slow_runs[:5]
                    ],
                )
            )

        repeated = self._repeated_answer_examples(messages_by_conversation)
        if repeated:
            issues.append(
                self._issue(
                    "repeated_answers",
                    "attention",
                    "相邻问题出现高度相似回答",
                    f"发现 {len(repeated)} 组相邻助手回答相似度达到 0.90 以上。",
                    "检查问题焦点路由、证据裁剪和历史上下文，避免固定全景模板覆盖当前问题。",
                    repeated[:5],
                )
            )

        referenced_run_ids = {
            str(message["run_id"])
            for message in all_messages
            if message.get("role") == "assistant"
            and message.get("run_id")
            and self._message_has_visible_references(message)
        }
        missing_reference_runs = [
            run
            for run in runs
            if run.get("intent") in EVIDENCE_INTENTS
            and run.get("status") in {"completed", "guarded", "degraded"}
            and str(run.get("answer") or "").strip()
            and "本次参考" not in str(run.get("answer") or "")
            and str(run.get("id") or "") not in referenced_run_ids
            and self._has_reference_evidence(run.get("evidence") or {})
        ]
        if missing_reference_runs:
            issues.append(
                self._issue(
                    "missing_visible_references",
                    "attention",
                    "部分证据型回答没有用户可见的参考来源",
                    f"检测到 {len(missing_reference_runs)} 个有证据包但最终消息未展示参考来源的 Run。",
                    "把资料库、公告、监管文件和市场资讯的来源摘要稳定附在最终回答后。",
                    [self._run_example(run) for run in missing_reference_runs[:5]],
                )
            )

        data_needs = self._data_needs(all_messages)
        capabilities = self._current_capabilities()
        for item in data_needs:
            item["status"] = (
                "resolved_in_current_backend"
                if capabilities.get(item["key"])
                else "open"
            )

        penalties = (
            min(25, len(failure_runs) * 5)
            + min(15, len(repaired_runs) * 2)
            + min(15, len(slow_runs))
            + min(20, len(repeated) * 5)
            + min(15, len(missing_reference_runs) * 2)
        )
        diagnostic_score = max(0, 100 - penalties)
        assistant_message_count = sum(
            item.get("role") == "assistant" for item in all_messages
        )
        score_is_ready = (
            assistant_message_count >= MIN_SCORABLE_ASSISTANT_MESSAGES
            and len(runs) >= MIN_SCORABLE_RUNS
        )
        evaluation_audit = self._evaluation_audit(evaluation_runs)
        summary = {
            "quality_score": diagnostic_score if score_is_ready else None,
            "diagnostic_score": diagnostic_score,
            "quality_score_status": (
                "available" if score_is_ready else "insufficient_sample"
            ),
            "minimum_score_sample": {
                "assistant_messages": MIN_SCORABLE_ASSISTANT_MESSAGES,
                "runs": MIN_SCORABLE_RUNS,
            },
            "conversations": len(conversations),
            "messages": len(all_messages),
            "user_messages": sum(item.get("role") == "user" for item in all_messages),
            "assistant_messages": assistant_message_count,
            "runs": len(runs),
            "run_statuses": dict(status_counts),
            "intents": dict(intent_counts),
            "issues": len(issues),
            "open_data_needs": sum(item["status"] == "open" for item in data_needs),
            "timing_samples": latency_summary.get("sample_size", 0),
            "excluded_evaluation_conversations": len(evaluation_conversations),
            "excluded_evaluation_messages": excluded_evaluation_messages,
            "excluded_evaluation_runs": excluded_evaluation_runs,
        }
        payload = {
            "method": self.METHOD,
            "generated_at": utc_now(),
            "summary": summary,
            "latency": latency_summary,
            "issues": issues,
            "data_needs": data_needs,
            "evaluation": evaluation_audit,
            "boundaries": [
                "该复盘只检查可确定的运行状态、延迟、重复度、引用和缺口关键词，不让模型给自己打分。",
                "高相似度提示需要人工复核，不等于回答一定错误。",
                "只分析当前用户自己的对话，不向其他用户暴露聊天内容。",
                "普通用户样本不足最低门槛时不显示质量分，避免用很小样本制造虚高结论。",
                "开发验收对话不计入普通用户质量分，但单独审计回退、修复、冗长和内部措辞。",
            ],
        }
        fingerprint_payload = {
            "summary": summary,
            "issue_keys": [item["key"] for item in issues],
            "data_needs": [(item["key"], item["status"]) for item in data_needs],
            "evaluation_summary": evaluation_audit.get("summary") or {},
        }
        fingerprint = hashlib.sha256(
            json_dumps(fingerprint_payload).encode("utf-8")
        ).hexdigest()
        self.database.save_conversation_quality_snapshot(
            user_id, fingerprint, payload
        )
        user = self.database.get_user(user_id)
        if user is not None:
            write_json(
                Path(user["workspace_path"])
                / "quality"
                / "conversation-review-latest.json",
                payload,
            )
        return payload

    @classmethod
    def _evaluation_audit(cls, runs: list[dict[str, Any]]) -> dict[str, Any]:
        statuses = Counter(str(run.get("status") or "unknown") for run in runs)
        repaired = [
            run
            for run in runs
            if (((run.get("usage") or {}).get("output_guard") or {}).get("repair"))
        ]
        verbose = []
        internal_language = []
        answer_lengths = []
        for run in runs:
            answer = str(run.get("answer") or "").strip()
            if not answer:
                continue
            answer_lengths.append(len(answer))
            intent = str(run.get("intent") or "")
            limit = 900 if intent == "stock_research" else 750 if intent == "market_brief" else 1100
            if len(answer) > limit:
                verbose.append({**cls._run_example(run), "answer_chars": len(answer), "limit": limit})
            if _USER_FACING_OPERATIONAL_RE.search(answer):
                internal_language.append(cls._run_example(run))

        issues = []
        fallback_runs = [
            run for run in runs if run.get("status") in {"guarded", "degraded", "failed"}
        ]
        if fallback_runs:
            issues.append(
                cls._issue(
                    "evaluation_fallbacks",
                    "critical" if any(run.get("status") == "failed" for run in fallback_runs) else "attention",
                    "开发验收仍出现回退或失败",
                    f"验收样本中有 {len(fallback_runs)} 个 Run 未以完整模型回答完成。",
                    "按问题类型复盘证据包、原始回答和守卫结果，不以确定性摘要替代完成度验收。",
                    [cls._run_example(run) for run in fallback_runs[:5]],
                )
            )
        if repaired:
            issues.append(
                cls._issue(
                    "evaluation_repairs",
                    "attention",
                    "开发验收回答频繁依赖事后修复",
                    f"验收样本中有 {len(repaired)} 个回答经删除或追加后才可展示。",
                    "把高频修复原因前移到 Skill、证据裁剪和回答契约，减少逐词补丁。",
                    [cls._run_example(run) for run in repaired[:5]],
                )
            )
        if verbose:
            issues.append(
                cls._issue(
                    "evaluation_verbose_answers",
                    "attention",
                    "标准问答仍像整份研究报告",
                    f"验收样本中有 {len(verbose)} 个回答超过对应标准长度。",
                    "按用户问题裁剪模块；只有明确要求深度研究时才展开全景报告。",
                    verbose[:5],
                )
            )
        if internal_language:
            issues.append(
                cls._issue(
                    "evaluation_internal_language",
                    "critical",
                    "用户回答仍暴露内部运维措辞",
                    f"验收样本中有 {len(internal_language)} 个回答出现数据源、行情源、降级或失败过程。",
                    "公开回答只保留来源、时间和口径边界，不解释内部采集失败过程。",
                    internal_language[:5],
                )
            )
        return {
            "summary": {
                "runs": len(runs),
                "run_statuses": dict(statuses),
                "repaired_runs": len(repaired),
                "verbose_answers": len(verbose),
                "internal_language_answers": len(internal_language),
                "median_answer_chars": round(float(median(answer_lengths)), 1)
                if answer_lengths
                else None,
            },
            "issues": issues,
        }

    @staticmethod
    def _latency_breakdown(runs: list[dict[str, Any]]) -> dict[str, Any]:
        keys = (
            "routing_and_evidence_seconds",
            "agent_setup_seconds",
            "model_seconds",
            "guard_seconds",
            "request_total_seconds",
            "first_token_seconds",
            "first_visible_seconds",
        )
        samples = [
            (run.get("usage") or {}).get("timings") or {}
            for run in runs
            if (run.get("usage") or {}).get("timings")
        ]
        percentiles = {}
        for key in keys:
            values = [
                float(item[key])
                for item in samples
                if isinstance(item.get(key), (int, float))
            ]
            if values:
                percentiles[key] = round(float(median(values)), 3)
        return {
            "sample_size": len(samples),
            "p50_seconds": percentiles,
            "boundary": (
                "当前记录的是请求路由与证据准备、Agent Prompt 准备、模型进程、"
                "输出守卫和请求总耗时；实时生成 Run 另记录首个模型片段与"
                "首个通过句级数字和证据守卫的可见片段，非流式或降级 Run 不填这两项。"
            ),
        }

    @staticmethod
    def _issue(
        key: str,
        severity: str,
        title: str,
        detail: str,
        next_step: str,
        examples: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "key": key,
            "severity": severity,
            "title": title,
            "detail": detail,
            "next_step": next_step,
            "examples": examples,
        }

    @staticmethod
    def _run_example(run: dict[str, Any]) -> dict[str, Any]:
        input_data = run.get("input") or {}
        return {
            "run_id": run.get("id"),
            "intent": run.get("intent"),
            "status": run.get("status"),
            "question": str(input_data.get("message") or "")[:160],
            "error": str(run.get("error") or "")[:200] or None,
            "created_at": run.get("created_at"),
        }

    @staticmethod
    def _latency_seconds(run: dict[str, Any]) -> float | None:
        try:
            started = datetime.fromisoformat(str(run.get("created_at")))
            finished = datetime.fromisoformat(str(run.get("finished_at")))
        except (TypeError, ValueError):
            return None
        return max(0.0, (finished - started).total_seconds())

    @staticmethod
    def _normalize_answer(text: str) -> str:
        text = re.sub(r"本次参考[\s\S]*$", "", text)
        text = re.sub(r"\s+", "", text)
        text = re.sub(r"\d+(?:\.\d+)?", "#", text)
        return text[:4000]

    def _repeated_answer_examples(
        self, messages_by_conversation: dict[str, list[dict[str, Any]]]
    ) -> list[dict[str, Any]]:
        repeated = []
        for conversation_id, messages in messages_by_conversation.items():
            assistant_messages = [
                item
                for item in messages
                if item.get("role") == "assistant"
                and len(str(item.get("content") or "")) >= 120
            ]
            for previous, current in zip(
                assistant_messages, assistant_messages[1:], strict=False
            ):
                previous_text = self._normalize_answer(
                    str(previous.get("content") or "")
                )
                current_text = self._normalize_answer(str(current.get("content") or ""))
                ratio = SequenceMatcher(None, previous_text, current_text).ratio()
                if ratio >= 0.9:
                    repeated.append(
                        {
                            "conversation_id": conversation_id,
                            "previous_message_id": previous.get("id"),
                            "current_message_id": current.get("id"),
                            "similarity": round(ratio, 4),
                            "preview": str(current.get("content") or "")[:180],
                        }
                    )
        return repeated

    @staticmethod
    def _has_reference_evidence(evidence: dict[str, Any]) -> bool:
        knowledge = evidence.get("knowledge_context") or {}
        market_drivers = evidence.get("market_drivers") or {}
        return bool(
            (knowledge.get("items") or [])
            or (market_drivers.get("items") or [])
            or evidence.get("filing_evidence")
            or evidence.get("regulatory_filings")
            or evidence.get("latest_report")
        )

    @staticmethod
    def _message_has_visible_references(message: dict[str, Any]) -> bool:
        metadata = message.get("metadata") or {}
        return bool(
            metadata.get("knowledge_sources")
            or metadata.get("market_sources")
            or "本次参考" in str(message.get("content") or "")
        )

    def _data_needs(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        examples: dict[str, list[str]] = defaultdict(list)
        counts: Counter[str] = Counter()
        for message in messages:
            if message.get("role") != "assistant":
                continue
            content = str(message.get("content") or "")
            for key, keywords in DATA_GAP_KEYWORDS.items():
                if any(keyword in content for keyword in keywords):
                    counts[key] += 1
                    if len(examples[key]) < 3:
                        examples[key].append(content[:180])
        return [
            {
                "key": key,
                "label": DATA_GAP_LABELS[key],
                "mentions": counts[key],
                "examples": examples[key],
            }
            for key, _ in counts.most_common()
        ]

    def _current_capabilities(self) -> dict[str, bool]:
        breadth = self.database.get_cache(
            "sina:a-share-market-breadth:hs_a", allow_stale=True
        ) or {}
        return {
            "market_turnover": (breadth.get("turnover") or {}).get("status")
            == "available",
            "market_distribution": (breadth.get("distribution") or {}).get(
                "status"
            )
            == "available",
        }
