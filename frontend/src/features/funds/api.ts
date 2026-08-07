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

// ---------- 基金搜索 ----------

export type FundItem = {
  code: string;
  name: string;
  nav: number | null;
  navDate: string | null;
  pctChange: number | null;
  category: string | null;
};

export async function searchFunds(query: string, limit = 20): Promise<FundItem[]> {
  const { data, error, response } = await api.GET("/fund-products/search", {
    params: { query: { q: query, limit } },
  });
  if (!response.ok || error || data === undefined) return [];
  const root = asRecord(data);
  const items = Array.isArray(root?.items) ? root.items : [];
  return items.flatMap((raw) => {
    const item = asRecord(raw);
    if (!item) return [];
    return [{
      code: asString(item.code) ?? "",
      name: asString(item.name) ?? "",
      nav: asNumber(item.nav),
      navDate: asString(item.nav_date ?? item.navDate),
      pctChange: asNumber(item.pct_change ?? item.pctChange),
      category: asString(item.category),
    }];
  });
}

export async function getFundDetail(code: string): Promise<FundItem | null> {
  const { data, error, response } = await api.GET("/fund-products/{code}", {
    params: { path: { code } },
  });
  if (!response.ok || error || data === undefined) return null;
  const root = asRecord(data);
  if (!root) return null;
  return {
    code: asString(root.code) ?? code,
    name: asString(root.name) ?? "",
    nav: asNumber(root.nav),
    navDate: asString(root.nav_date ?? root.navDate),
    pctChange: asNumber(root.pct_change ?? root.pctChange),
    category: asString(root.category),
  };
}

export async function listFunds(limit = 50): Promise<FundItem[]> {
  const { data, error, response } = await api.GET("/fund-products", {
    params: { query: { limit } },
  });
  if (!response.ok || error || data === undefined) return [];
  const root = asRecord(data);
  const items = Array.isArray(root?.items) ? root.items : [];
  return items.flatMap((raw) => {
    const item = asRecord(raw);
    if (!item) return [];
    return [{
      code: asString(item.code) ?? "",
      name: asString(item.name) ?? "",
      nav: asNumber(item.nav),
      navDate: asString(item.nav_date ?? item.navDate),
      pctChange: asNumber(item.pct_change ?? item.pctChange),
      category: asString(item.category),
    }];
  });
}
