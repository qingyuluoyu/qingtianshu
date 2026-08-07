import { describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), patch: vi.fn() }));

vi.mock("../../api/client", () => ({ api: { GET: mocks.get, POST: mocks.post, PATCH: mocks.patch } }));

import {
  createTradeReviewFollowup,
  generateTradeReviewDraft,
  getPendingWritebacks,
  ResearchCenterApiError,
  updateTradeReviewDraft,
} from "./api";

function response(status = 200): Response {
  return new Response(null, { status });
}

describe("research center write API", () => {
  it("sends the explicit model tier and base version when generating", async () => {
    mocks.post.mockResolvedValue({ data: { id: "candidate-1" }, error: undefined, response: response(201) });

    await generateTradeReviewDraft("review-1", 3, "deep");

    expect(mocks.post).toHaveBeenCalledWith("/v1/trade-reviews/{review_id}/generate-draft", {
      params: { path: { review_id: "review-1" } },
      body: { base_version: 3, model_tier: "deep" },
    });
  });

  it("sends complete draft and followup payloads", async () => {
    mocks.patch.mockResolvedValue({ data: {}, error: undefined, response: response() });
    mocks.post.mockResolvedValue({ data: {}, error: undefined, response: response(201) });

    await updateTradeReviewDraft("review-1", {
      baseVersion: 2,
      priceResult: "窗口收益 -1.85%。",
      logicResult: "仍需观察订单兑现。",
      planDeviation: null,
      biasTags: ["锚定"],
      improvementText: "增加复核节点。",
    });
    await createTradeReviewFollowup("review-1", {
      target: "observation_task",
      title: null,
      priority: "normal",
    });

    expect(mocks.patch).toHaveBeenCalledWith("/v1/trade-reviews/{review_id}/draft", expect.objectContaining({
      body: expect.objectContaining({ base_version: 2, bias_tags: ["锚定"] }),
    }));
    expect(mocks.post).toHaveBeenCalledWith("/v1/trade-reviews/{review_id}/followups", expect.objectContaining({
      body: { target: "observation_task", title: null, priority: "normal" },
    }));
  });

  it("maps a 409 write response to ResearchCenterApiError", async () => {
    mocks.patch.mockResolvedValue({ data: undefined, error: {}, response: response(409) });

    await expect(updateTradeReviewDraft("review-1", {
      baseVersion: 2,
      priceResult: "窗口收益 -1.85%。",
      logicResult: "仍需观察订单兑现。",
      planDeviation: null,
      biasTags: [],
      improvementText: null,
    })).rejects.toMatchObject<Partial<ResearchCenterApiError>>({ status: 409 });
  });

  it("requests only pending writebacks", async () => {
    mocks.get.mockResolvedValue({ data: { items: [] }, error: undefined, response: response() });

    await getPendingWritebacks();

    expect(mocks.get).toHaveBeenCalledWith("/v1/ai-writebacks", { params: { query: { status: "pending_confirmation", limit: 100 } } });
  });
});
