import { api } from "../../api/client";
import { TodayApiError } from "../today/api";
import {
  parseGlobalIndices,
  parseSectors,
  type GlobalIndices,
  type Sectors,
} from "../today/adapters";

function unwrap<T>(
  response: Response,
  data: unknown,
  error: unknown,
  parse: (value: unknown) => T,
): T {
  if (!response.ok || error || data === undefined) {
    throw new TodayApiError(response.status, response.status === 401 ? "会话已失效" : "数据暂时不可用");
  }
  return parse(data);
}

/** 指数总览按分组取数（scope=all），复用 today 的通用指数解析器。 */
export async function getIndicesByGroup(group: string): Promise<GlobalIndices> {
  const { data, error, response } = await api.GET("/indices", { params: { query: { scope: "all", group } } });
  return unwrap(response, data, error, parseGlobalIndices);
}

/** 板块热度，行情数据页展示更多行数（limit 直通后端，解析上限同步放宽）。 */
export async function getSectors(limit: number): Promise<Sectors> {
  const { data, error, response } = await api.GET("/sectors/hot", { params: { query: { limit } } });
  return unwrap(response, data, error, (value) => parseSectors(value, limit));
}
