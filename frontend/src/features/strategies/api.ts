import { api } from "../../api/client";
import { requestError } from "../../api/requestError";

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

// ---------- 策略监控 ----------

export type StrategyInfo = {
  id: string;
  name: string;
  description: string | null;
  status: string | null;
  lastRunAt: string | null;
  candidateCount: number | null;
};

export type StrategyRun = {
  id: string;
  strategyId: string;
  status: string | null;
  startedAt: string | null;
  finishedAt: string | null;
  candidatesFound: number | null;
  qualifiedCount: number | null;
  triggeredCount: number | null;
};

export type BacktestResult = {
  id: string;
  strategyId: string;
  period: string | null;
  startedAt: string | null;
  totalReturnPct: number | null;
  benchmarkReturnPct: number | null;
  status: string | null;
};

export type TriggerItem = {
  id: string;
  symbol: string | null;
  name: string | null;
  triggerType: string | null;
  triggeredAt: string | null;
  status: string | null;
};

// 策略列表
export async function listStrategies(): Promise<StrategyInfo[]> {
  const { data, error, response } = await api.GET("/v1/stock-strategies");
  if (!response.ok || error || data === undefined) throw requestError("策略列表", response.status);
  const root = asRecord(data);
  const items = Array.isArray(root?.strategies) ? root.strategies : [];
  return items.flatMap((raw) => {
    const s = asRecord(raw);
    if (!s) return [];
    return [{
      id: asString(s.id) ?? "",
      name: asString(s.name) ?? "",
      description: asString(s.description),
      status: asString(s.status),
      lastRunAt: asString(s.last_run_at ?? s.lastRunAt),
      candidateCount: asNumber(s.candidate_count ?? s.candidateCount),
    }];
  });
}

// 李总策略详情
export async function getLiZongStrategy(): Promise<StrategyInfo | null> {
  const { data, error, response } = await api.GET("/v1/stock-strategies/li-zong");
  if (!response.ok || error || data === undefined) throw requestError("策略详情", response.status);
  const root = asRecord(data);
  const s = asRecord(root?.strategy ?? root);
  if (!s) return null;
  return {
    id: asString(s.id) ?? "li-zong",
    name: asString(s.name) ?? "李总策略",
    description: asString(s.description),
    status: asString(s.status),
    lastRunAt: asString(s.last_run_at ?? s.lastRunAt),
    candidateCount: asNumber(s.candidate_count ?? s.candidateCount),
  };
}

// 启动策略运行
export async function runStrategy(): Promise<{ runId: string } | null> {
  const { data, error, response } = await api.POST("/v1/stock-strategies/li-zong/runs", {
    body: {} as unknown as never,
  });
  if (!response.ok || error || data === undefined) throw requestError("启动策略", response.status);
  const root = asRecord(data);
  return { runId: asString(root?.run_id ?? root?.runId) ?? "" };
}

// 策略候选
export async function getStrategyCandidates(limit = 30): Promise<Array<{ symbol: string; name: string; status: string; score: number | null }>> {
  const { data, error, response } = await api.GET("/v1/stock-strategies/li-zong/candidates", {
    params: { query: { limit } },
  });
  if (!response.ok || error || data === undefined) throw requestError("策略候选", response.status);
  const root = asRecord(data);
  const items = Array.isArray(root?.candidates) ? root.candidates : [];
  return items.flatMap((raw) => {
    const c = asRecord(raw);
    if (!c) return [];
    return [{
      symbol: asString(c.symbol) ?? "",
      name: asString(c.name) ?? "",
      status: asString(c.status) ?? "",
      score: asNumber(c.score),
    }];
  });
}

// 观察池
export async function getObservationPool(limit = 50): Promise<Array<{ symbol: string; name: string; addedAt: string | null }>> {
  const { data, error, response } = await api.GET("/v1/stock-strategies/li-zong/observation-pool", {
    params: { query: { limit } },
  });
  if (!response.ok || error || data === undefined) throw requestError("观察池", response.status);
  const root = asRecord(data);
  const items = Array.isArray(root?.items) ? root.items : [];
  return items.flatMap((raw) => {
    const item = asRecord(raw);
    if (!item) return [];
    return [{
      symbol: asString(item.symbol) ?? "",
      name: asString(item.name) ?? "",
      addedAt: asString(item.added_at ?? item.addedAt),
    }];
  });
}

// 策略历史
export async function getStrategyHistory(limit = 20): Promise<StrategyRun[]> {
  const { data, error, response } = await api.GET("/v1/stock-strategies/li-zong/history", {
    params: { query: { limit } },
  });
  if (!response.ok || error || data === undefined) throw requestError("策略历史", response.status);
  const root = asRecord(data);
  const runs = Array.isArray(root?.runs) ? root.runs : [];
  return runs.flatMap((raw) => {
    const r = asRecord(raw);
    if (!r) return [];
    return [{
      id: asString(r.id) ?? "",
      strategyId: asString(r.strategy_id ?? r.strategyId) ?? "",
      status: asString(r.status),
      startedAt: asString(r.started_at ?? r.startedAt),
      finishedAt: asString(r.finished_at ?? r.finishedAt),
      candidatesFound: asNumber(r.candidates_found ?? r.candidatesFound),
      qualifiedCount: asNumber(r.qualified_count ?? r.qualifiedCount),
      triggeredCount: asNumber(r.triggered_count ?? r.triggeredCount),
    }];
  });
}

// 回测结果
export async function getBacktestResult(period: "3m" | "1y" | "3y" = "1y"): Promise<BacktestResult | null> {
  const { data, error, response } = await api.GET("/v1/stock-strategies/li-zong/backtest", {
    params: { query: { period } },
  });
  if (!response.ok || error || data === undefined) throw requestError("策略回测", response.status);
  const root = asRecord(data);
  const bt = asRecord(root?.backtest ?? root);
  if (!bt) return null;
  return {
    id: asString(bt.id) ?? `backtest-${period}`,
    strategyId: asString(bt.strategy_id ?? bt.strategyId) ?? "li-zong",
    period: asString(bt.period) ?? period,
    startedAt: asString(bt.started_at ?? bt.startedAt),
    totalReturnPct: asNumber(bt.total_return_pct ?? bt.totalReturnPct),
    benchmarkReturnPct: asNumber(bt.benchmark_return_pct ?? bt.benchmarkReturnPct),
    status: asString(bt.status),
  };
}

// 策略触发
export async function getStrategyTriggers(limit = 20): Promise<TriggerItem[]> {
  const { data, error, response } = await api.GET("/v1/stock-strategies/li-zong/triggers", {
    params: { query: { limit } },
  });
  if (!response.ok || error || data === undefined) throw requestError("策略触发记录", response.status);
  const root = asRecord(data);
  const items = Array.isArray(root?.triggers) ? root.triggers : [];
  return items.flatMap((raw) => {
    const t = asRecord(raw);
    if (!t) return [];
    return [{
      id: asString(t.id) ?? "",
      symbol: asString(t.symbol),
      name: asString(t.name),
      triggerType: asString(t.trigger_type ?? t.triggerType),
      triggeredAt: asString(t.triggered_at ?? t.triggeredAt),
      status: asString(t.status),
    }];
  });
}
