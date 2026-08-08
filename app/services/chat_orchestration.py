from __future__ import annotations

from dataclasses import dataclass
import re
import time
from typing import Any

from fastapi import HTTPException

from app.api_models import ChatRequest
from app.providers.market import ProviderError
from app.services.chat_context import (
    ChatConversationNotFound,
    ChatUploadExpired,
    ChatUploadNotFound,
    build_financial_advisor_context,
)
from app.services.chat_knowledge_context import _filter_knowledge_context
from app.services.chat_routing import (
    _extract_thesis,
    _is_deep_stock_coverage_query,
    _is_research_action_query,
    _is_research_outcome_query,
    _is_research_priority_query,
    _is_research_tracking_query,
    _is_watchlist_daily_query,
    _needs_research_object_clarification,
)
from app.services.chat_streaming import ChatStreamPublisher
from app.utils import utc_now


def _public_upload(upload: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": upload["id"],
        "kind": upload["kind"],
        "original_name": upload["original_name"],
        "mime_type": upload["mime_type"],
        "size_bytes": upload["size_bytes"],
        "width": upload["width"],
        "height": upload["height"],
        "created_at": upload["created_at"],
    }


@dataclass(slots=True)
class ChatOrchestrationService:
    event_broker: Any
    agent_streams: Any
    chat_context: Any
    chat_persistence: Any
    articles: Any
    database: Any
    chat_screening_evidence: Any
    stock_comparison: Any
    stock_assets: Any
    analysis: Any
    research_actions: Any
    research_priority: Any
    research_outcomes: Any
    research_reports: Any
    research_tracking: Any
    chat_company_evidence: Any
    chat_market_evidence: Any
    chat_stock_research_evidence: Any
    chat_execution: Any
    fund_products: Any
    risk_profiles: Any

    def handle(
        self,
        user: dict[str, Any],
        payload: ChatRequest,
    ) -> dict[str, Any]:
        user_id = str(user["id"])
        request_started = time.perf_counter()
        if payload.request_id and payload.execute_agent:
            try:
                self.agent_streams.open(payload.request_id, user_id)
            except PermissionError as exc:
                raise HTTPException(status_code=404, detail="实时回答不存在") from exc

        chat_stream = ChatStreamPublisher(
            event_broker=self.event_broker,
            agent_streams=self.agent_streams,
            request_id=payload.request_id,
            user_id=user_id,
            execute_agent=payload.execute_agent,
            started_at=request_started,
        )
        publish_agent_progress = chat_stream.progress

        publish_agent_progress(
            "routing_started",
            "正在识别问题，并检索实时证据与资料库…",
        )
        try:
            prepared = self.chat_context.prepare(
                user_id=user_id,
                message=payload.message,
                conversation_id=payload.conversation_id,
                quality_scope=payload.quality_scope,
                requested_symbol=payload.symbol,
                image_id=payload.image_id,
                model_tier=payload.model_tier,
            )
        except ChatConversationNotFound as exc:
            raise HTTPException(status_code=404, detail="研究对话不存在") from exc
        except ChatUploadNotFound as exc:
            raise HTTPException(
                status_code=404, detail="图片不存在或不属于当前用户"
            ) from exc
        except ChatUploadExpired as exc:
            raise HTTPException(
                status_code=410, detail="图片文件已失效，请重新上传"
            ) from exc

        message = prepared.message
        conversation = prepared.conversation
        conversation_id = prepared.conversation_id
        history = prepared.history
        symbols = prepared.symbols
        symbol = prepared.symbol
        prior_intent = prepared.prior_intent
        contextual_followup = prepared.contextual_followup
        explicit_market_query = prepared.explicit_market_query
        explicit_industry_topic = prepared.explicit_industry_topic
        stock_screen_query = prepared.stock_screen_query
        li_zong_query = prepared.li_zong_query
        stock_comparison_query = prepared.stock_comparison_query
        financial_driver_query = prepared.financial_driver_query
        earnings_quality_query = prepared.earnings_quality_query
        business_structure_query = prepared.business_structure_query
        shareholder_query = prepared.shareholder_query
        analyst_expectations_context = prepared.analyst_expectations_context
        event_timeline_context = prepared.event_timeline_context
        company_evidence_intent = (
            "event_timeline"
            if event_timeline_context
            else "analyst_expectations"
            if analyst_expectations_context
            else "shareholder_structure"
            if shareholder_query
            else "business_structure"
            if business_structure_query
            else "financial_drivers"
            if financial_driver_query
            else "earnings_quality"
            if earnings_quality_query
            else None
        )
        if symbol and company_evidence_intent:
            planned_stock_question = (
                self.chat_stock_research_evidence.research_plan.build(
                    message,
                    conversation_history=history,
                )
            )
            if planned_stock_question.get("focus") in {
                "mixed",
                "comprehensive",
                "quality_review",
                "valuation_review",
                "business_growth",
            }:
                # A compound user question needs one coherent stock answer with
                # all selected modules.  Routing it to the first matching
                # specialist drops the remaining cash-flow, event, industry or
                # price evidence even though the research plan requested it.
                company_evidence_intent = None
        upload = prepared.upload
        image_path = prepared.image_path
        model_tier = prepared.model_tier
        knowledge_context = prepared.knowledge_context
        confirmed_risk_profile = self.risk_profiles.confirmed_context(user_id)
        financial_advisor_context = build_financial_advisor_context(
            message,
            confirmed_profile=confirmed_risk_profile,
        )
        fund_product_context = None
        if upload is None:
            try:
                fund_product_context = self.fund_products.build_question_context(
                    message
                )
            except (ProviderError, ValueError):
                if re.search(r"(?<!\d)\d{6}(?!\d)", message) and any(
                    term in message for term in ("基金", "ETF", "etf", "联接")
                ):
                    fund_product_context = {
                        "contract_version": "fund_product_research_v1",
                        "status": "unavailable",
                        "boundary": (
                            "当前没有取得这些产品的可核验时点事实；回答只能解释核验方法，"
                            "不能补写收益、规模、费率或产品状态。"
                        ),
                    }

        def persist_response(
            response_payload: dict[str, Any],
            *,
            assistant_content: str,
            response_intent: str,
            response_symbol: str | None = None,
            run_id: str | None = None,
            evidence_payload: dict[str, Any] | None = None,
            structured_answer: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            return self.chat_persistence.persist(
                response_payload,
                user_id=user_id,
                conversation=conversation,
                conversation_id=conversation_id,
                knowledge_context=knowledge_context,
                model_tier=model_tier,
                assistant_content=assistant_content,
                response_intent=response_intent,
                response_symbol=response_symbol,
                run_id=run_id,
                evidence_payload=evidence_payload,
                structured_answer=structured_answer,
            )

        if any(
            keyword in message
            for keyword in ("行情文章", "市场文章", "市场脉冲", "生成文章")
        ):
            if upload is not None:
                raise HTTPException(
                    status_code=422, detail="图片不用于全站市场文章生成"
                )
            result = self.articles.generate(
                model_tier=payload.model_tier
                if payload.model_tier != "vision"
                else "economy",
                execute_agent=payload.execute_agent,
                force=False,
            )
            article = result.get("article") or {}
            assistant_content = (
                article.get("summary")
                or article.get("body")
                or result.get("reason")
                or "市场文章任务已完成。"
            )
            return persist_response(
                {"intent": "market_pulse_article", **result},
                assistant_content=assistant_content,
                response_intent="market_pulse_article",
            )
        if any(keyword in message for keyword in ("加入自选", "添加自选", "加到自选")):
            if symbol is None:
                raise HTTPException(
                    status_code=422, detail="没有识别到要添加的证券代码"
                )
            item = self.database.upsert_watchlist(
                user_id,
                symbol,
                name=None,
                market=None,
                thesis=_extract_thesis(message),
            )
            intent = "watchlist_update"
            evidence = {
                "type": intent,
                "generated_at": utc_now(),
                "item": item,
                "warnings": [],
            }
        elif message.startswith("记住") or "请记住" in message:
            content = re.sub(r"^请?记住[：:\s]*", "", message).strip() or message
            memory = self.database.create_memory(user_id, "user_statement", content)
            intent = "memory_candidate"
            evidence = {
                "type": intent,
                "generated_at": utc_now(),
                "memory": memory,
                "warnings": ["该内容只是候选记忆，确认后才会用于长期个性化。"],
            }
        elif fund_product_context is not None and upload is None:
            intent = "general_research"
            symbol = None
            evidence = {
                "type": intent,
                "generated_at": utc_now(),
                "fund_product_context": fund_product_context,
                "financial_advisor_context": financial_advisor_context,
                "knowledge_context": knowledge_context,
                "research_capabilities": [
                    "基金与ETF当前产品事实",
                    "同口径历史收益窗口",
                    "用户已确认适合性事实",
                    "金融知识资料库",
                ],
            }
        elif li_zong_query and upload is None:
            intent = "stock_screen"
            screening_result = self.chat_screening_evidence.build_li_zong(
                message,
                symbol=symbol,
            )
            evidence = screening_result.evidence
            symbol = screening_result.symbol
        elif stock_screen_query and upload is None:
            intent = "stock_screen"
            evidence = self.chat_screening_evidence.build_standard(message)
        elif stock_comparison_query and upload is None:
            intent = "stock_comparison"
            try:
                evidence = self.stock_comparison.build(
                    user_id,
                    symbols,
                    question=message,
                )
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        elif _is_watchlist_daily_query(message):
            intent = "watchlist_brief"
            evidence = self.analysis.watchlist_brief(user_id)
            asset_packet = self.stock_assets.list_assets(user_id)
            research_assets = [
                item
                for item in (asset_packet.get("items") or [])
                if item.get("relation_type") != "ended"
            ]
            active_symbols = {str(item.get("symbol") or "") for item in research_assets}
            evidence["items"] = [
                item
                for item in (evidence.get("items") or [])
                if str(item.get("symbol") or "") in active_symbols
            ]
            evidence["research_assets"] = research_assets
            evidence["user_question"] = message
            evidence["answer_contract"] = {
                "per_stock_time_fields": (
                    "current_quote.market_timestamp",
                    "latest_bar.timestamp",
                    "research_assets.data_times.financial_report_period",
                    "research_assets.report_meta.generated_at",
                    "research_assets.report_meta.market_timestamp",
                ),
                "required_sections": (
                    "优先级与原因",
                    "最新报价",
                    "最近完整日线",
                    "最新财务报告期",
                    "反方证据",
                    "什么时候需要重新判断",
                    "下一步研究任务",
                ),
                "report_scope": "server_public_evidence_snapshot_only",
            }
            evidence["boundary"] = (
                "服务器预生成报告只作为公共证据快照；用户正式判断、任务和变化处理状态"
                "来自当前账号的股票研究空间。回答必须即时生成，不得直接回放报告正文，"
                "不得输出目标价或买卖建议。"
            )
        elif _is_research_action_query(message) and symbol is None:
            intent = "research_actions"
            evidence = self.research_actions.get_packet(user_id)
        elif _is_research_priority_query(message):
            intent = "research_priority"
            evidence = self.research_priority.get_packet(user_id)
        elif _is_research_outcome_query(message):
            intent = "research_outcome"
            targets = (
                [symbol]
                if symbol
                else [item["symbol"] for item in self.database.list_watchlist(user_id)]
            )
            refresh_warnings = []
            for target in targets[:10]:
                if self.database.latest_research_report(target) is not None:
                    continue
                try:
                    self.research_reports.generate(target, execute_agent=False)
                except Exception as exc:
                    refresh_warnings.append(f"{target}: {type(exc).__name__}")
            evidence = self.research_outcomes.get_packet(user_id, symbol=symbol)
            evidence["warnings"] = refresh_warnings
        elif _is_research_tracking_query(message) and not _is_deep_stock_coverage_query(
            message
        ):
            intent = "research_tracking"
            targets = (
                [symbol]
                if symbol
                else [item["symbol"] for item in self.database.list_watchlist(user_id)]
            )
            refresh_warnings = []
            for target in targets[:10]:
                if self.database.latest_research_report(target) is not None:
                    continue
                try:
                    self.research_reports.generate(target, execute_agent=False)
                except Exception as exc:
                    refresh_warnings.append(f"{target}: {type(exc).__name__}")
            evidence = self.research_tracking.get_packet(user_id, symbol=symbol)
            evidence["watchlist_snapshot"] = self.analysis.watchlist_brief(user_id)
            evidence["warnings"] = refresh_warnings
        elif company_evidence_intent:
            company_result = self.chat_company_evidence.build(
                company_evidence_intent,
                user_id=user_id,
                symbol=symbol,
                message=message,
            )
            if company_result.clarification:
                clarification = {
                    "run_id": None,
                    "status": "clarification",
                    "intent": "clarification",
                    "model_tier": model_tier,
                    "answer": company_result.clarification,
                    "evidence": {
                        "type": "clarification",
                        "generated_at": utc_now(),
                    },
                    "error": None,
                }
                return persist_response(
                    clarification,
                    assistant_content=clarification["answer"],
                    response_intent="clarification",
                )
            intent = company_result.intent
            evidence = company_result.evidence or {}
        elif "自选" in message:
            intent = "watchlist_brief"
            evidence = self.analysis.watchlist_brief(user_id)
        elif (
            explicit_market_query
            or (prior_intent == "market_brief" and contextual_followup)
        ) and symbol is None:
            intent = "market_brief"
            evidence = self.chat_market_evidence.build(
                message=message,
                history=history,
                explicit_market_query=explicit_market_query,
                explicit_industry_topic=explicit_industry_topic,
            )
        else:
            if symbol is None:
                if upload is None and _needs_research_object_clarification(
                    message, history
                ):
                    clarification = {
                        "run_id": None,
                        "status": "clarification",
                        "intent": "clarification",
                        "model_tier": model_tier,
                        "answer": (
                            "我还没识别到具体的研究对象。你可以直接说“中兴通讯为什么大跌”"
                            "“分析英伟达”或输入证券代码；询问整体行情时可以说“今天大盘怎么样”。"
                        ),
                        "evidence": {
                            "type": "clarification",
                            "generated_at": utc_now(),
                        },
                        "error": None,
                    }
                    return persist_response(
                        clarification,
                        assistant_content=clarification["answer"],
                        response_intent="clarification",
                    )
                if upload is not None:
                    intent = "visual_research"
                    evidence = {
                        "type": intent,
                        "generated_at": utc_now(),
                        "image": _public_upload(upload),
                        "user_question": message,
                        "analysis_boundary": [
                            "只做定性图像观察，不把模糊的坐标、价格或百分比当作可验证事实。",
                            "不仅凭图片识别公司、时间或证券代码。",
                            "需要数值分析时，请用户补充证券代码并调用确定性行情工具。",
                        ],
                    }
                else:
                    intent = "general_research"
                    evidence = {
                        "type": intent,
                        "generated_at": utc_now(),
                        "knowledge_context": knowledge_context,
                        "research_capabilities": [
                            "连续对话上下文",
                            "已确认用户记忆",
                            "用户与通用资料库检索",
                            "金融研究工具",
                        ],
                    }
                    if financial_advisor_context:
                        evidence["financial_advisor_context"] = (
                            financial_advisor_context
                        )
            else:
                intent = "stock_research"
                try:
                    evidence = self.chat_stock_research_evidence.build(
                        user_id=user_id,
                        symbol=symbol,
                        message=message,
                        history=history,
                        publish_progress=publish_agent_progress,
                    )
                except ProviderError as exc:
                    raise HTTPException(status_code=502, detail=str(exc)) from exc

        if symbol and intent in {
            "stock_research",
            "earnings_quality",
            "financial_drivers",
            "business_structure",
            "shareholder_structure",
            "analyst_expectations",
            "event_timeline",
        }:
            evidence = self.chat_stock_research_evidence.attach_workspace_context(
                evidence,
                user_id=user_id,
                symbol=symbol,
                message=message,
                history=history,
            )

        evidence.setdefault("user_question", message)
        knowledge_context = _filter_knowledge_context(
            knowledge_context,
            intent=intent,
            symbol=symbol,
            evidence=evidence,
        )
        if knowledge_context.get("items"):
            evidence["knowledge_context"] = knowledge_context
        else:
            evidence.pop("knowledge_context", None)

        return self.chat_execution.execute(
            user=user,
            user_id=user_id,
            intent=intent,
            message=message,
            evidence=evidence,
            model_tier=model_tier,
            execute_agent=payload.execute_agent,
            image_path=image_path,
            conversation_id=conversation_id,
            conversation_history=history,
            knowledge_context=knowledge_context,
            request_started=request_started,
            request_id=payload.request_id,
            symbol=symbol,
            chat_stream=chat_stream,
            persist_response=persist_response,
        )
