import { describe, expect, it } from "vitest";
import {
  AdvisorContractError,
  parseAdvisorRun,
  parseConversationDetail,
  parseWritebackList,
} from "./adapters";

describe("advisor adapters", () => {
  it("keeps zero message counts and persisted entry context without inventing missing values", () => {
    const conversation = parseConversationDetail({
      id: "conversation-1",
      title: "新的研究对话",
      message_count: 0,
      research_targets: [],
      messages: [],
    });
    const run = parseAdvisorRun({
      id: "run-1",
      status: "completed",
      input: {
        entry_context: {
          source_page: "watchlist",
          module: "watchlist",
          symbol: "000063.SZ",
        },
      },
    });

    expect(conversation.messageCount).toBe(0);
    expect(run.entryContext).toEqual({
      sourcePage: "watchlist",
      module: "watchlist",
      asOf: null,
      symbol: "000063.SZ",
    });
  });

  it("does not turn an absent pending summary into zero", () => {
    expect(parseWritebackList({ items: [], summary: {} }).pendingCount).toBeNull();
  });

  it("rejects malformed successful conversation bodies", () => {
    expect(() => parseConversationDetail({ title: "缺少 ID", messages: [] })).toThrow(AdvisorContractError);
  });
});
