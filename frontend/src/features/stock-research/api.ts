import { api } from "../../api/client";
import {
  parseDeepStockSession,
  parseObservationTasks,
  parsePeerComparisons,
  parseStockHistory,
  parseStockPage,
  parseStockPosition,
  parseTheses,
  parseWorkspace,
  type DeepStockSession,
  type ObservationTasks,
  type PeerComparisons,
  type StockHistory,
  type StockPage,
  type StockPosition,
  type Theses,
  type Workspace,
} from "./adapters";

export type HistoryRange = "3mo" | "6mo" | "1y";
export const HISTORY_RANGES: HistoryRange[] = ["3mo", "6mo", "1y"];

export class StockResearchApiError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message);
    this.name = "StockResearchApiError";
  }
}

function unwrap<T>(
  response: Response,
  data: unknown,
  error: unknown,
  parse: (value: unknown) => T,
): T {
  if (!response.ok || error || data === undefined) {
    throw new StockResearchApiError(response.status, response.status === 401 ? "会话已失效" : "数据暂时不可用");
  }
  return parse(data);
}

/** 404 表示业务对象不存在（如研究空间未创建），是合法空态，不是接口失败。 */
function unwrapOrNullOn404<T>(
  response: Response,
  data: unknown,
  error: unknown,
  parse: (value: unknown) => T,
): T | null {
  if (response.status === 404) return null;
  return unwrap(response, data, error, parse);
}

export async function getStockPage(symbol: string): Promise<StockPage> {
  const { data, error, response } = await api.GET("/v1/stocks/{symbol}/page", {
    params: { path: { symbol }, query: { range: "1y" } },
  });
  return unwrap(response, data, error, parseStockPage);
}

export async function getStockHistory(symbol: string, range: HistoryRange): Promise<StockHistory> {
  const { data, error, response } = await api.GET("/stocks/{symbol}/history", {
    params: { path: { symbol }, query: { range } },
  });
  return unwrap(response, data, error, parseStockHistory);
}

export async function getPeerComparisons(symbol: string): Promise<PeerComparisons> {
  const { data, error, response } = await api.GET("/peer-comparisons/{symbol}", {
    params: { path: { symbol } },
  });
  return unwrap(response, data, error, parsePeerComparisons);
}

export async function getStockWorkspace(symbol: string): Promise<Workspace> {
  const { data, error, response } = await api.GET("/v1/stocks/{symbol}/workspace", {
    params: { path: { symbol } },
  });
  return unwrap(response, data, error, parseWorkspace);
}

export async function getTheses(symbol: string): Promise<Theses | null> {
  const { data, error, response } = await api.GET("/v1/stocks/{symbol}/theses", {
    params: { path: { symbol } },
  });
  return unwrapOrNullOn404(response, data, error, parseTheses);
}

export async function getObservationTasks(symbol: string): Promise<ObservationTasks> {
  const { data, error, response } = await api.GET("/v1/stocks/{symbol}/observation-tasks", {
    params: { path: { symbol } },
  });
  return unwrap(response, data, error, parseObservationTasks);
}

export async function getStockPosition(symbol: string): Promise<StockPosition | null> {
  const { data, error, response } = await api.GET("/v1/stocks/{symbol}/position", {
    params: { path: { symbol } },
  });
  return unwrapOrNullOn404(response, data, error, parseStockPosition);
}

export async function getDeepStockSession(symbol: string): Promise<DeepStockSession | null> {
  const { data, error, response } = await api.GET("/me/deep-stock/{symbol}", {
    params: { path: { symbol } },
  });
  return unwrapOrNullOn404(response, data, error, parseDeepStockSession);
}
