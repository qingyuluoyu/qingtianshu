import { describe, expect, it } from "vitest";
import {
  buildRelationPatch,
  ContractError,
  parseStockRelation,
  parseWatchlistAssets,
} from "./adapters";
import { assetsPayload, emptyAssetsPayload } from "./testFixtures";

describe("parseWatchlistAssets", () => {
  it("locks the contract version and rejects non-object payloads", () => {
    expect(() => parseWatchlistAssets(null)).toThrow(ContractError);
    expect(() => parseWatchlistAssets([])).toThrow(ContractError);
    expect(() => parseWatchlistAssets({ contract_version: "other_v9", items: [] })).toThrow(/stock_asset_list_v1/);
  });

  it("parses items with passthrough values (no percent scaling, no unit rewrite)", () => {
    const parsed = parseWatchlistAssets(assetsPayload());
    expect(parsed.status).toBe("partial");
    expect(parsed.items).toHaveLength(3);
    const first = parsed.items[0]!;
    expect(first.symbol).toBe("000063.SZ");
    expect(first.version).toBe(3);
    // pct_change 为百分数直通：-0.14 保持 -0.14，不缩放、不取绝对值。
    expect(first.quote.pctChange).toBe(-0.14);
    expect(first.quote.price).toBe(34.69);
    expect(first.priority).toBe("high");
    expect(first.openTaskCount).toBe(2);
    expect(first.activeThesis?.summary).toBe("算力订单兑现节奏是核心变量。");
    expect(first.latestChange?.eventType).toBe("official_financial_disclosure");
    expect(first.reportMeta?.generatedAt).toBe("2026-08-06T06:50:12+00:00");
    expect(parsed.summary.total).toBe(3);
    expect(parsed.summary.paused).toBe(1);
  });

  it("distinguishes 0, missing fields, empty strings and empty lists", () => {
    const payload = assetsPayload();
    // 0 是有效数值：pct_change = 0 直通为 0，不是 null。
    (payload.items[2]!.quote as Record<string, unknown>).pct_change = 0;
    (payload.items[2]!.quote as Record<string, unknown>).price = 0;
    // 空字符串与缺字段 → null。
    (payload.items[1] as Record<string, unknown>).name = "";
    delete (payload.items[1] as Record<string, unknown>).market;
    const parsed = parseWatchlistAssets(payload);
    expect(parsed.items[2]!.quote.pctChange).toBe(0);
    expect(parsed.items[2]!.quote.price).toBe(0);
    expect(parsed.items[1]!.name).toBeNull();
    expect(parsed.items[1]!.market).toBeNull();
    // 空字符串 summary 视为缺失。
    expect(parsed.items[1]!.activeThesis).toBeNull();
  });

  it("keeps a missing task count unknown instead of inventing zero tasks", () => {
    const payload = assetsPayload();
    delete (payload.items[1] as Record<string, unknown>).open_task_count;

    const parsed = parseWatchlistAssets(payload);

    expect(parsed.items[1]!.openTaskCount).toBeNull();
  });

  it("keeps unavailable quote state separate from a zero price", () => {
    const parsed = parseWatchlistAssets(assetsPayload());
    const paused = parsed.items[1]!;
    expect(paused.quote.price).toBeNull();
    expect(paused.quote.status).toBe("unavailable");
    expect(paused.dataStatus).toBe("partial");
    expect(paused.warnings).toContain("该股票的行情或研究摘要暂未完整返回");
  });

  it("parses the empty list as a real empty state", () => {
    const parsed = parseWatchlistAssets(emptyAssetsPayload());
    expect(parsed.status).toBe("empty");
    expect(parsed.items).toHaveLength(0);
    expect(parsed.summary.total).toBe(0);
  });

  it("drops items without a symbol instead of inventing one", () => {
    const payload = assetsPayload();
    payload.items.push({ workspace_id: "ws-bad" } as never);
    const parsed = parseWatchlistAssets(payload);
    expect(parsed.items).toHaveLength(3);
  });
});

describe("parseStockRelation", () => {
  it("parses the relation packet version and state", () => {
    const relation = parseStockRelation({
      contract_version: "stock_domain_v1",
      symbol: "000063.SZ",
      version: 4,
      relation_type: "watching",
      priority: "high",
      tracking_status: "paused",
      workflow_status: "idle",
      attention_tags: ["算力"],
    });
    expect(relation.version).toBe(4);
    expect(relation.trackingStatus).toBe("paused");
    expect(relation.attentionTags).toEqual(["算力"]);
  });
});

describe("buildRelationPatch", () => {
  const base = parseWatchlistAssets(assetsPayload()).items;

  it("builds a full-state patch that only changes the target field", () => {
    // PATCH 为全量替换语义：设为重点必须保留 tracking_status / workflow_status / tags。
    const patch = buildRelationPatch(base[0]!, { priority: "high" });
    expect(patch).toEqual({
      baseVersion: 3,
      relationType: "watching",
      priority: "high",
      trackingStatus: "active",
      workflowStatus: "researching",
      attentionTags: ["算力"],
    });
  });

  it("clears priority when ending the relation (backend rule)", () => {
    const patch = buildRelationPatch(base[0]!, { relationType: "ended" });
    expect(patch.relationType).toBe("ended");
    expect(patch.priority).toBeNull();
    expect(patch.baseVersion).toBe(3);
  });

  it("restores an ended relation with watching + normal priority", () => {
    const patch = buildRelationPatch(base[2]!, {
      relationType: "watching",
      priority: "normal",
      trackingStatus: "active",
    });
    expect(patch).toMatchObject({ baseVersion: 5, relationType: "watching", priority: "normal" });
  });

  it("refuses to write without a version (would lose conflict protection)", () => {
    expect(() => buildRelationPatch({ ...base[0]!, version: null }, { priority: "high" }))
      .toThrow(/关系版本缺失/);
  });
});
