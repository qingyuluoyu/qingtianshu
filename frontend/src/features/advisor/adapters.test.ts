import { describe, expect, it } from "vitest";
import {
  buildChatRequestBody,
  ContractError,
  parseChatResponse,
  parseConversationDetail,
  parseConversationList,
  parseWritebackList,
} from "./adapters";
import {
  chatResponsePayload,
  conversationDetailPayload,
  conversationsPayload,
  writebacksPayload,
} from "./testFixtures";

describe("advisor adapters", () => {
  it("parses conversation list and keeps null distinct from 0", () => {
    const list = parseConversationList(conversationsPayload());
    expect(list.items).toHaveLength(2);
    expect(list.items[0].id).toBe("conv-1");
    expect(list.items[0].messageCount).toBe(2);
    // 0 是有效数值（空对话），不能吞掉。
    expect(list.items[1].messageCount).toBe(0);
    expect(list.items[1].lastMessagePreview).toBeNull();
    expect(list.items[0].researchTargets[0]).toEqual({ symbol: "000063.SZ", name: "中兴通讯" });
  });

  it("rejects non-object conversation list payloads", () => {
    expect(() => parseConversationList([])).toThrow(ContractError);
    expect(() => parseConversationList(null)).toThrow(ContractError);
  });

  it("parses conversation detail with messages, evidence sources and structured answer", () => {
    const detail = parseConversationDetail(conversationDetailPayload());
    expect(detail.messages).toHaveLength(2);
    const assistant = detail.messages[1];
    expect(assistant.role).toBe("assistant");
    expect(assistant.metadata?.symbol).toBe("000063.SZ");
    expect(assistant.metadata?.evidenceSources).toHaveLength(2);
    expect(assistant.metadata?.evidenceSources[0].asOf).toBe("2026-08-06 10:00");
    const structured = assistant.metadata?.structuredAnswer;
    expect(structured?.status).toBe("partial");
    expect(structured?.confirmedFacts).toEqual(["三季度经营性现金流为正"]);
    expect(structured?.citations?.[0]?.dataTime).toBe("2026-09-30");
    // 用户消息 metadata 为 null 时不崩溃。
    expect(detail.messages[0].metadata).toBeNull();
  });

  it("throws ContractError on wrong structured_answer contract version", () => {
    const payload = conversationDetailPayload();
    const metadata = payload.messages[1].metadata;
    expect(metadata).not.toBeNull();
    if (!metadata) throw new Error("fixture requires assistant metadata");
    metadata.structured_answer.contract_version = "other_v9";
    expect(() => parseConversationDetail(payload)).toThrow(ContractError);
  });

  it("parses writeback list with contract lock and passthrough status", () => {
    const list = parseWritebackList(writebacksPayload());
    expect(list.items).toHaveLength(2);
    expect(list.summary.pendingConfirmation).toBe(1);
    const thesis = list.items[0];
    expect(thesis.candidateType).toBe("thesis");
    expect(thesis.status).toBe("pending_confirmation");
    expect(thesis.baseVersion).toBe(2);
    expect(thesis.payload.reason_text).toBe("现金流为正但覆盖能力待核验");
    expect(list.items[1].status).toBe("stale");
  });

  it("rejects wrong writeback contract version", () => {
    expect(() => parseWritebackList({ contract_version: "other_v9", items: [] })).toThrow(ContractError);
  });

  it("parses chat response including clarification required_fields", () => {
    const response = parseChatResponse(chatResponsePayload());
    expect(response.status).toBe("completed");
    expect(response.conversationId).toBe("conv-1");
    expect(response.requiredFields).toEqual([]);
    const clarification = parseChatResponse({
      status: "clarification",
      answer: "请补充",
      evidence: { type: "advisor_lab_clarification", required_fields: ["投资期限", "风险承受能力"] },
    });
    expect(clarification.requiredFields).toEqual(["投资期限", "风险承受能力"]);
  });

  it("buildChatRequestBody attaches context line and dedicated symbol field", () => {
    const body = buildChatRequestBody(
      "现金流怎么样？",
      { symbol: "000063.SZ", sourcePage: "stock-research", module: "financials", asOf: "2026-08-06" },
      { conversationId: "conv-1", requestId: "req-123456" },
    );
    expect(body.symbol).toBe("000063.SZ");
    expect(body.conversationId).toBe("conv-1");
    expect(body.requestId).toBe("req-123456");
    expect(body.message).toContain("现金流怎么样？");
    expect(body.message).toContain("[研究上下文：标的=000063.SZ；来源页=stock-research；模块=financials；数据时间=2026-08-06]");
  });

  it("buildChatRequestBody without context sends the plain question", () => {
    const body = buildChatRequestBody("今天市场怎么样", { symbol: null, sourcePage: null, module: null, asOf: null });
    expect(body.message).toBe("今天市场怎么样");
    expect(body.symbol).toBeUndefined();
    expect(body.conversationId).toBeUndefined();
  });

  it("buildChatRequestBody rejects empty questions", () => {
    expect(() => buildChatRequestBody("   ", { symbol: null, sourcePage: null, module: null, asOf: null })).toThrow(ContractError);
  });
});
