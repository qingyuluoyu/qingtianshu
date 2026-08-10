import { api } from "../../api/client";

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function asString(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function asNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

// ---------- 文章生成 ----------

export type ArticleItem = {
  id: string;
  title: string;
  summary: string | null;
  status: string | null;
  modelTier: string | null;
  generatedAt: string | null;
  symbol: string | null;
  source: string | null;
};

export async function listArticles(limit = 20): Promise<ArticleItem[]> {
  const { data, error, response } = await api.GET("/articles", {
    params: { query: { limit } },
  });
  if (!response.ok || error || data === undefined) {
    throw new Error(`文章列表请求失败 (${response.status})`);
  }
  const root = asRecord(data);
  const items = Array.isArray(root?.items) ? root.items : [];
  return items.flatMap((raw) => {
    const item = asRecord(raw);
    if (!item) return [];
    return [{
      id: asString(item.id) ?? "",
      title: asString(item.title) ?? "",
      summary: asString(item.summary),
      status: asString(item.status),
      modelTier: asString(item.model_tier ?? item.modelTier),
      generatedAt: asString(item.generated_at ?? item.generatedAt),
      symbol: asString(item.symbol),
      source: asString(item.source),
    }];
  });
}

export async function generateMarketPulse(modelTier = "standard", executeAgent = false): Promise<ArticleItem | null> {
  const { data, error, response } = await api.POST("/articles/market-pulse", {
    body: { model_tier: modelTier, execute_agent: executeAgent } as unknown as never,
  });
  if (!response.ok || error || data === undefined) return null;
  const root = asRecord(data);
  const article = asRecord(root?.article ?? root);
  if (!article) return null;
  return {
    id: asString(article.id) ?? "",
    title: asString(article.title) ?? "市场脉搏",
    summary: asString(article.summary),
    status: asString(article.status) ?? "generating",
    modelTier: asString(article.model_tier ?? article.modelTier),
    generatedAt: asString(article.generated_at ?? article.generatedAt),
    symbol: asString(article.symbol),
    source: asString(article.source),
  };
}
