import { api } from "../../api/client";
import type { components } from "../../api/openapi.generated";
import {
  parseLiZongBacktest,
  parseLiZongCandidates,
  parseLiZongRunLatest,
  parseScreenerProfiles,
  parseStockScreen,
  type LiZongBacktest,
  type LiZongCandidates,
  type LiZongRunLatest,
  type ScreenerProfiles,
  type StockScreen,
} from "./adapters";

export class ScreeningApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
    public readonly code: string | null = null,
  ) {
    super(message);
    this.name = "ScreeningApiError";
  }
}

function errorCode(error: unknown): string | null {
  if (typeof error !== "object" || error === null) return null;
  const detail = (error as { detail?: unknown }).detail;
  if (typeof detail !== "object" || detail === null) return null;
  const code = (detail as { code?: unknown }).code;
  return typeof code === "string" && code.length > 0 ? code : null;
}

function unwrap<T>(
  response: Response,
  data: unknown,
  error: unknown,
  parse: (value: unknown) => T,
): T {
  if (!response.ok || error || data === undefined) {
    const code = errorCode(error);
    throw new ScreeningApiError(
      response.status,
      response.status === 401 ? "会话已失效" : "数据暂时不可用",
      code,
    );
  }
  return parse(data);
}

// ---------- 通用筛选 ----------

export type ScreenParams = {
  profile: string;
  market: string;
  /** 服务端真实上限参数（1-30），不是分页。 */
  maxResults: number;
  filters: Record<string, number>;
};

type ScreenRequestBody = components["schemas"]["StockScreenRequest"];
type ScreenFiltersBody = components["schemas"]["StockScreenFilters"];

export async function getScreenerProfiles(): Promise<ScreenerProfiles> {
  const { data, error, response } = await api.GET("/stock-screener/profiles");
  return unwrap(response, data, error, parseScreenerProfiles);
}

/**
 * POST /me/stock-screener 是契约定义的筛选查询入口（读语义，force_refresh 固定 false，
 * 不触发数据重建）；本切片没有任何其他写操作。
 */
export async function runStockScreen(
  params: ScreenParams,
  signal?: AbortSignal,
): Promise<StockScreen> {
  const body: ScreenRequestBody = {
    profile: params.profile as ScreenRequestBody["profile"],
    market: params.market as ScreenRequestBody["market"],
    max_results: params.maxResults,
    force_refresh: false,
    filters: params.filters as ScreenFiltersBody,
  };
  const { data, error, response } = await api.POST("/me/stock-screener", { body, signal });
  return unwrap(response, data, error, parseStockScreen);
}

// ---------- 李总策略（全部只读 GET） ----------

export type LiZongStatusFilter = "qualified" | "triggered" | "not_qualified" | "data_incomplete" | null;

export async function getLiZongCandidates(status: LiZongStatusFilter): Promise<LiZongCandidates> {
  const { data, error, response } = await api.GET("/v1/stock-strategies/li-zong/candidates", {
    params: { query: { status: status ?? undefined, limit: 200 } },
  });
  return unwrap(response, data, error, parseLiZongCandidates);
}

export async function getLiZongRunLatest(): Promise<LiZongRunLatest> {
  const { data, error, response } = await api.GET("/v1/stock-strategies/li-zong/runs/latest");
  return unwrap(response, data, error, parseLiZongRunLatest);
}

export type BacktestPeriod = "3m" | "1y" | "3y";

export async function getLiZongBacktest(period: BacktestPeriod): Promise<LiZongBacktest> {
  const { data, error, response } = await api.GET("/v1/stock-strategies/li-zong/backtest", {
    params: { query: { period } },
  });
  return unwrap(response, data, error, parseLiZongBacktest);
}
