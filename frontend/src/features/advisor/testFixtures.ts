import {
  parseConversationDetail,
  parseConversationList,
  parseWritebackList,
  type ConversationDetail,
  type ConversationList,
  type WritebackList,
} from "./adapters";

export function conversationsPayload() {
  return {
    items: [
      {
        id: "conv-1",
        title: "中兴通讯研究",
        quality_scope: "user",
        conversation_mode: "formal",
        status: "active",
        message_count: 2,
        last_message_preview: "现金流覆盖需要核验",
        last_intent: "stock_research",
        conversation_scope: "stock",
        research_targets: [{ symbol: "000063.SZ", name: "中兴通讯" }],
        created_at: "2026-08-05T09:00:00+00:00",
        updated_at: "2026-08-06T02:00:00+00:00",
        archived_at: null,
      },
      {
        id: "conv-2",
        title: "市场回顾",
        quality_scope: "user",
        conversation_mode: "formal",
        status: "active",
        message_count: 0,
        last_message_preview: null,
        last_intent: null,
        conversation_scope: "market",
        research_targets: [],
        created_at: "2026-08-04T09:00:00+00:00",
        updated_at: null,
        archived_at: null,
      },
    ],
  };
}

export function conversationDetailPayload() {
  return {
    ...conversationsPayload().items[0],
    messages: [
      {
        id: "msg-u1",
        role: "user",
        content: "中兴通讯三季度现金流怎么样？",
        intent: null,
        run_id: null,
        metadata: null,
        created_at: "2026-08-05T09:01:00+00:00",
      },
      {
        id: "msg-a1",
        role: "assistant",
        content: "现金流覆盖需要核验，当前证据不足以给出结论。",
        intent: "stock_research",
        run_id: "run-1",
        metadata: {
          symbol: "000063.SZ",
          model_tier: "economy",
          evidence_sources: [
            { kind: "quote", title: "最新行情快照", as_of: "2026-08-06 10:00", source: "tushare" },
            { kind: "filing", title: "2026 年三季度报告", summary: "经营活动现金流披露", as_of: "2026-09-30" },
          ],
          structured_answer: {
            contract_version: "structured_ai_response_v1",
            status: "partial",
            answer_summary: "现金流覆盖需要核验。",
            confirmed_facts: ["三季度经营性现金流为正"],
            evidence_based_inferences: [],
            hypotheses_to_verify: ["现金流能否覆盖资本开支"],
            counter_evidence_and_risks: ["应收账款增速高于营收"],
            information_gaps: ["缺少最新季报现金流明细"],
            invalidation_conditions: [],
            next_evidence_tasks: [],
            stage_updates: [],
            conclusion_boundary: "结构化证据只用于研究复核，不构成交易建议。",
            citations: [
              {
                id: "cit-1",
                claim_id: "claim-1",
                source_name: "三季度报告",
                source_url: null,
                evidence_type: "filing",
                data_time: "2026-09-30",
                report_period: "2026-09-30",
                excerpt: "经营活动现金流净额为正",
                limitations: "未经审计",
                created_at: "2026-08-06T02:00:00+00:00",
              },
            ],
            candidate_writebacks: [],
          },
          knowledge_sources: [],
          market_sources: [],
          research_targets: [{ symbol: "000063.SZ", name: "中兴通讯" }],
          conversation_scope: "stock",
          advisor_lab_snapshot: null,
        },
        created_at: "2026-08-05T09:01:30+00:00",
      },
    ],
  };
}

export function writebacksPayload() {
  return {
    contract_version: "structured_ai_response_v1",
    items: [
      {
        id: "cand-1",
        symbol: "000063.SZ",
        candidate_type: "thesis",
        status: "pending_confirmation",
        payload: {
          reason_text: "现金流为正但覆盖能力待核验",
          watch_items: ["应收账款增速", "资本开支"],
          recheck_conditions: ["三季报披露后复核"],
        },
        citation_ids: ["cit-1"],
        base_version: 2,
        created_at: "2026-08-06T02:00:00+00:00",
        resolved_at: null,
      },
      {
        id: "cand-2",
        symbol: "000063.SZ",
        candidate_type: "observation_task",
        status: "stale",
        payload: { title: "核验现金流覆盖", description: "等待三季报", priority: "normal", due_at: null },
        citation_ids: [],
        base_version: 1,
        created_at: "2026-08-05T02:00:00+00:00",
        resolved_at: "2026-08-06T01:00:00+00:00",
      },
    ],
    summary: { total: 2, pending_confirmation: 1 },
  };
}

export function chatResponsePayload() {
  return {
    run_id: "run-2",
    status: "completed",
    intent: "stock_research",
    model_tier: "economy",
    answer: "已按证据梳理，现金流覆盖仍需核验。",
    evidence: { type: "stock_research" },
    evidence_tasks: {},
    deep_stock_session: null,
    structured_answer: null,
    error: null,
    conversation_id: "conv-1",
    conversation_title: "中兴通讯研究",
    assistant_message_id: "msg-a2",
    knowledge: { items: [], coverage: {} },
    evidence_sources: [],
    research_targets: [{ symbol: "000063.SZ", name: "中兴通讯" }],
  };
}

export function parsedConversations(): ConversationList {
  return parseConversationList(conversationsPayload());
}

export function parsedConversationDetail(): ConversationDetail {
  return parseConversationDetail(conversationDetailPayload());
}

export function parsedWritebacks(): WritebackList {
  return parseWritebackList(writebacksPayload());
}
