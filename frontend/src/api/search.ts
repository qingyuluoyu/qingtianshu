import { api } from "./client";

export type GlobalSearchItem = {
  id: string;
  title: string;
  subtitle: string | null;
  url: string;
};

export type GlobalSearchGroup = {
  key: string;
  label: string;
  items: GlobalSearchItem[];
};

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function asString(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

// 旧静态页路由改写为 React 路由；仅个股与行业组有可靠的落地页。
function rewriteUrl(groupKey: string, url: string | null): string | null {
  if (!url) return null;
  if (groupKey === "stocks" && url.startsWith("/stocks/")) return url;
  if (groupKey === "industries") {
    const match = /[?&]industry=([^&]+)/.exec(url);
    return match ? `/screening?industry=${match[1]}` : "/screening";
  }
  return null;
}

export async function getGlobalSearch(query: string): Promise<GlobalSearchGroup[]> {
  const { data, error, response } = await api.GET("/v1/search", {
    params: { query: { q: query, limit: 8 } },
  });
  if (!response.ok || error || data === undefined) return [];
  const root = asRecord(data);
  const groups = Array.isArray(root?.groups) ? root.groups : [];
  return groups.flatMap((rawGroup) => {
    const group = asRecord(rawGroup);
    const key = asString(group?.key);
    const label = asString(group?.label);
    if (!group || !key || !label) return [];
    const items = (Array.isArray(group.items) ? group.items : []).flatMap((rawItem) => {
      const item = asRecord(rawItem);
      const id = asString(item?.id);
      const title = asString(item?.title);
      const url = rewriteUrl(key, asString(item?.url));
      if (!item || !id || !title || !url) return [];
      return [{ id, title, subtitle: asString(item.subtitle), url }];
    });
    return items.length > 0 ? [{ key, label, items }] : [];
  });
}
