import { useMemo, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { CandlestickChart } from "../stock-research/charts";
import {
  buildRelationPatch,
  type RelationPatch,
  type WatchlistAsset,
  type WatchlistAssets,
} from "./adapters";
import { patchStockRelation, WatchlistApiError } from "./api";
import { watchlistQueries, watchlistQueryKeys } from "./queries";
import styles from "./WatchlistPage.module.css";

type Props = { authenticated: boolean };

// ---------- 格式化助手（直通原则：百分数不缩放） ----------

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "时间待确认";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "时间待确认";
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

function formatNumber(value: number | null, digits = 2): string {
  if (value === null) return "--";
  return new Intl.NumberFormat("zh-CN", { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(value);
}

/** pct_change 后端已是百分数，直通加 % 不缩放。 */
function percent(value: number | null): string {
  if (value === null) return "--";
  return `${value > 0 ? "+" : ""}${formatNumber(value)}%`;
}

function tone(value: number | null): string {
  if (value === null || value === 0) return styles.flat;
  return value > 0 ? styles.up : styles.down;
}

// ---------- 状态翻译（合同 §6.3，只翻译后端状态，不自行推断） ----------

function statusLabel(status: string): string {
  return ({
    available: "数据完整",
    ready: "数据完整",
    sufficient: "证据充分",
    partial: "部分数据可用",
    insufficient: "数据不足",
    unavailable: "当前不可用",
    pending_confirmation: "待确认草稿",
    waiting_data: "等待数据",
    stale: "内容已过期",
    ended: "已结束",
    paused: "已暂停",
    empty: "暂无数据",
    not_configured: "未配置",
  } as Record<string, string>)[status] ?? status;
}

function statusTone(status: string): string {
  if (["available", "ready", "sufficient"].includes(status)) return styles.badgeReady;
  if (["partial", "insufficient"].includes(status)) return styles.badgePartial;
  if (["pending_confirmation", "waiting_data"].includes(status)) return styles.badgeWaiting;
  if (status === "stale") return styles.badgeStale;
  return styles.badgeUnavailable;
}

function relationLabel(asset: WatchlistAsset): string {
  if (asset.relationType === "ended") return "已结束";
  if (asset.trackingStatus === "paused") return "已暂停";
  return asset.relationLabel ?? "关注";
}

function researchStateLabel(asset: WatchlistAsset): string {
  if (asset.relationType === "ended") return "已结束";
  if (asset.trackingStatus === "paused") return "已暂停";
  if (asset.workflowStatus === "waiting_data") return "等待数据";
  if (asset.workflowStatus === "researching") return "研究中";
  return "跟踪中";
}

// ---------- 筛选与排序（浏览器侧作用于同一份聚合列表，不发额外请求） ----------

const FILTERS = [
  { key: "all", label: "全部" },
  { key: "priority", label: "重点" },
  { key: "changed", label: "有变化" },
  { key: "tasks", label: "有任务" },
  { key: "paused", label: "暂停" },
  { key: "ended", label: "结束" },
] as const;

type FilterKey = (typeof FILTERS)[number]["key"];

const SORTS = [
  { key: "default", label: "默认顺序" },
  { key: "pct_desc", label: "涨幅优先" },
  { key: "pct_asc", label: "跌幅优先" },
  { key: "change_desc", label: "最近变化优先" },
] as const;

type SortKey = (typeof SORTS)[number]["key"];

function matchesFilter(asset: WatchlistAsset, filter: FilterKey): boolean {
  switch (filter) {
    case "priority": return asset.relationType === "watching" && asset.priority === "high";
    case "changed": return asset.latestChange !== null;
    case "tasks": return asset.openTaskCount !== null && asset.openTaskCount > 0;
    case "paused": return asset.trackingStatus === "paused" && asset.relationType !== "ended";
    case "ended": return asset.relationType === "ended";
    default: return true;
  }
}

function sortAssets(items: WatchlistAsset[], sort: SortKey): WatchlistAsset[] {
  if (sort === "default") return items;
  const sorted = [...items];
  if (sort === "pct_desc" || sort === "pct_asc") {
    const direction = sort === "pct_desc" ? -1 : 1;
    sorted.sort((a, b) => {
      const av = a.quote.pctChange;
      const bv = b.quote.pctChange;
      if (av === null && bv === null) return 0;
      if (av === null) return 1;
      if (bv === null) return -1;
      return (av - bv) * direction;
    });
    return sorted;
  }
  sorted.sort((a, b) => {
    const av = a.latestChange?.createdAt ?? null;
    const bv = b.latestChange?.createdAt ?? null;
    if (av === null && bv === null) return 0;
    if (av === null) return 1;
    if (bv === null) return -1;
    return bv.localeCompare(av);
  });
  return sorted;
}

// ---------- 通用卡片 ----------

function ModuleCard({ title, meta, pending, error, onRetry, children }: {
  title: string;
  meta?: ReactNode;
  pending?: boolean;
  error?: boolean;
  onRetry?: () => void;
  children: ReactNode;
}) {
  return (
    <section className={styles.card} aria-label={title}>
      <div className={styles.cardHeader}>
        <h2>{title}</h2>
        {meta ? <div className={styles.meta}>{meta}</div> : null}
      </div>
      {pending ? <div className={styles.skeleton} aria-live="polite">正在读取…</div> : null}
      {!pending && error ? (
        <div className={styles.moduleError} role="status">
          <span>本模块暂时不可用，其他内容仍可继续查看。</span>
          {onRetry ? <button type="button" onClick={onRetry}>重新读取</button> : null}
        </div>
      ) : null}
      {!pending && !error ? children : null}
    </section>
  );
}

// ---------- 概览筛选卡 ----------

function WatchlistSummaryCards({ assets, active, onSelect }: {
  assets: WatchlistAssets;
  active: FilterKey;
  onSelect: (filter: FilterKey) => void;
}) {
  const items = assets.items;
  const counts: Record<FilterKey, number | null> = {
    all: assets.summary.total,
    priority: items.filter((item) => matchesFilter(item, "priority")).length,
    changed: items.filter((item) => matchesFilter(item, "changed")).length,
    tasks: items.filter((item) => matchesFilter(item, "tasks")).length,
    paused: assets.summary.paused,
    ended: assets.summary.ended,
  };
  const hints: Record<FilterKey, string> = {
    all: "含已结束研究空间",
    priority: "优先级 high 的关注",
    changed: "存在最近变化记录",
    tasks: "有进行中的观察任务",
    paused: "跟踪已暂停",
    ended: "历史保留可回看",
  };
  return (
    <div className={styles.summaryGrid} role="group" aria-label="关注概览筛选">
      {FILTERS.map(({ key, label }) => (
        <button
          aria-pressed={active === key}
          className={styles.summaryCard}
          key={key}
          onClick={() => onSelect(key)}
          type="button"
        >
          <span>{label}</span>
          <strong>{counts[key] === null ? "--" : counts[key]}</strong>
          <small>{hints[key]}</small>
        </button>
      ))}
    </div>
  );
}

// ---------- 关系操作 ----------

type RelationAction = { key: string; label: string; danger?: boolean };

function relationActions(asset: WatchlistAsset): RelationAction[] {
  if (asset.relationType === "ended") {
    return [{ key: "resume", label: "恢复关注" }];
  }
  const actions: RelationAction[] = [];
  if (asset.relationType === "watching") {
    actions.push(asset.priority === "high"
      ? { key: "unpin", label: "取消重点" }
      : { key: "pin", label: "设为重点" });
  }
  actions.push(asset.trackingStatus === "paused"
    ? { key: "resumeTracking", label: "恢复跟踪" }
    : { key: "pause", label: "暂停跟踪" });
  actions.push({ key: "end", label: "结束关注", danger: true });
  return actions;
}

// ---------- 资产表格 ----------

function AssetTable({ items, selectedSymbol, pendingSymbol, onSelect, onAction }: {
  items: WatchlistAsset[];
  selectedSymbol: string | null;
  pendingSymbol: string | null;
  onSelect: (symbol: string) => void;
  onAction: (asset: WatchlistAsset, action: RelationAction) => void;
}) {
  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>代码</th>
            <th>名称</th>
            <th>价格</th>
            <th>涨跌</th>
            <th>判断</th>
            <th>变化</th>
            <th>任务</th>
            <th>研究状态</th>
            <th>报告时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          {items.map((asset) => {
            const quoteUnavailable = asset.quote.price === null;
            const rowPending = pendingSymbol === asset.symbol;
            return (
              <tr
                aria-selected={selectedSymbol === asset.symbol}
                key={asset.symbol}
                onClick={() => onSelect(asset.symbol)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    onSelect(asset.symbol);
                  }
                }}
                tabIndex={0}
              >
                <td className={styles.symbolCell}>
                  <strong>{asset.symbol}</strong>
                  <small>{asset.market ?? "市场待确认"}</small>
                </td>
                <td className={styles.nameCell}>
                  <span>{asset.name ?? "名称待确认"}</span>
                  <small>{relationLabel(asset)}{asset.priority === "high" && asset.relationType === "watching" ? " · 重点" : ""}</small>
                </td>
                <td>
                  {quoteUnavailable ? "--" : formatNumber(asset.quote.price)}
                  {quoteUnavailable ? <small className={styles.flat} style={{ display: "block" }}>行情不可用</small> : null}
                </td>
                <td className={tone(asset.quote.pctChange)}>{percent(asset.quote.pctChange)}</td>
                <td className={styles.thesisCell}>
                  <span>{asset.activeThesis?.summary ?? "尚未保存当前判断"}</span>
                </td>
                <td className={styles.changeCell}>
                  {asset.latestChange ? (
                    <>
                      <span>{asset.latestChange.summary ?? asset.latestChange.title ?? "有变化记录"}</span>
                      <small>{formatDateTime(asset.latestChange.createdAt)}</small>
                    </>
                  ) : "暂无变化"}
                </td>
                <td>{asset.openTaskCount ?? "--"}</td>
                <td>
                  <span className={`${styles.badge} ${statusTone(asset.dataStatus ?? "unavailable")}`}>
                    {researchStateLabel(asset)}
                  </span>
                </td>
                <td>{asset.reportMeta?.generatedAt ? formatDateTime(asset.reportMeta.generatedAt) : "暂无报告"}</td>
                <td>
                  <div className={styles.rowActions} onClick={(event) => event.stopPropagation()} onKeyDown={(event) => event.stopPropagation()}>
                    {relationActions(asset).map((action) => (
                      <button
                        className={`${styles.rowAction} ${action.danger ? styles.rowActionDanger : ""}`}
                        disabled={rowPending}
                        key={action.key}
                        onClick={() => onAction(asset, action)}
                        type="button"
                      >
                        {rowPending ? "写入中…" : action.label}
                      </button>
                    ))}
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ---------- 右侧快速预览 ----------

function StockQuickPreview({ asset }: { asset: WatchlistAsset }) {
  const workspace = useQuery(watchlistQueries.workspace(asset.symbol));
  const history = useQuery(watchlistQueries.history(asset.symbol));
  const thesis = asset.activeThesis?.summary ?? workspace.data?.thesis.summary ?? null;
  const quoteAsOf = asset.dataTimes.quoteAsOf ?? asset.quote.marketTimestamp;
  const advisorQuery = `?symbol=${encodeURIComponent(asset.symbol)}&source=watchlist`;
  return (
    <>
      <ModuleCard
        meta={quoteAsOf ? `行情时间：${formatDateTime(quoteAsOf)}` : "行情时间待确认"}
        title={`${asset.name ?? asset.symbol} 快速预览`}
      >
        <div className={styles.previewGrid}>
          <div className={styles.metricGrid}>
            <div className={styles.metric}>
              <span>最新价格</span>
              <strong>{asset.quote.price === null ? "--" : formatNumber(asset.quote.price)}</strong>
              <small>{asset.quote.label ?? (asset.quote.price === null ? "行情不可用" : "行情标签待确认")}{asset.quote.currency ? ` · ${asset.quote.currency}` : ""}</small>
            </div>
            <div className={styles.metric}>
              <span>涨跌幅</span>
              <strong className={tone(asset.quote.pctChange)}>{percent(asset.quote.pctChange)}</strong>
              <small>百分数直通，不缩放</small>
            </div>
            <div className={styles.metric}>
              <span>关系</span>
              <strong>{relationLabel(asset)}</strong>
              <small>{asset.priority === "high" && asset.relationType === "watching" ? "重点关注" : "常规"}</small>
            </div>
            <div className={styles.metric}>
              <span>进行中任务</span>
              <strong>{asset.openTaskCount ?? "--"}</strong>
              <small>观察任务不是交易指令</small>
            </div>
          </div>
          {thesis ? (
            <>
              <p className={styles.statement}>{thesis}</p>
              <p className={styles.helper}>当前判断{asset.activeThesis?.version ? ` · 版本 ${asset.activeThesis.version}` : ""}</p>
            </>
          ) : (
            <p className={styles.statement}>尚未保存当前判断。系统不会替你生成结论，可以从个股研究页或问顾问开始。</p>
          )}
          {asset.nextAction ? (
            <p className={styles.helper}>下一步：{asset.nextAction.title ?? asset.nextAction.nextStep ?? "待确认"}</p>
          ) : null}
          <div className={styles.actionRow}>
            <Link className={styles.actionLink} to={`/stocks/${encodeURIComponent(asset.symbol)}`}>进入个股研究</Link>
            <Link className={styles.actionLink} to={`/advisor${advisorQuery}`}>问顾问</Link>
          </div>
        </div>
      </ModuleCard>
      <ModuleCard
        error={history.isError}
        meta={history.data?.coverage.lastTimestamp ? `日线截至：${history.data.coverage.lastTimestamp.slice(0, 10)}` : undefined}
        onRetry={() => void history.refetch()}
        pending={history.isPending}
        title="近期走势（3mo）"
      >
        {history.data && history.data.points.length > 1 ? (
          <>
            <div className={styles.chartFrame}>
              <CandlestickChart height={260} points={history.data.points} width={640} />
            </div>
            <div className={styles.klineMeta}>
              <span>频率：{history.data.dataGranularity === "1d" ? "日线" : history.data.dataGranularity ?? "待确认"}</span>
              <span>来源：{history.data.source ?? "待确认"}</span>
              {history.data.isStale === true ? <span>缓存数据</span> : null}
            </div>
          </>
        ) : <div className={styles.empty}>K 线数据暂不可用</div>}
      </ModuleCard>
      {workspace.isError ? (
        <ModuleCard error onRetry={() => void workspace.refetch()} title="研究空间详情">{null}</ModuleCard>
      ) : null}
    </>
  );
}

// ---------- 最近变化与任务/报告摘要 ----------

function RecentSection({ items }: { items: WatchlistAsset[] }) {
  const changed = items
    .filter((item) => item.latestChange !== null)
    .sort((a, b) => (b.latestChange?.createdAt ?? "").localeCompare(a.latestChange?.createdAt ?? ""))
    .slice(0, 5);
  const withTasks = items.filter((item) => item.openTaskCount !== null && item.openTaskCount > 0).slice(0, 5);
  const withReports = items
    .filter((item) => item.reportMeta !== null)
    .sort((a, b) => (b.reportMeta?.generatedAt ?? "").localeCompare(a.reportMeta?.generatedAt ?? ""))
    .slice(0, 5);
  return (
    <ModuleCard title="最近变化与任务/报告摘要">
      {changed.length === 0 && withTasks.length === 0 && withReports.length === 0 ? (
        <div className={styles.empty}>暂无变化、任务或报告记录</div>
      ) : (
        <>
          {changed.length > 0 ? (
            <>
              <h3 style={{ margin: "0 0 6px", fontSize: 13 }}>最近变化</h3>
              <div className={styles.itemList}>
                {changed.map((item) => (
                  <article key={`change-${item.symbol}`}>
                    <div className={styles.itemHead}>
                      <strong>{item.name ?? item.symbol}</strong>
                      <span className={styles.tag}>{item.latestChange?.eventType ?? "变化"}</span>
                    </div>
                    <p>{item.latestChange?.summary ?? item.latestChange?.title ?? "有变化记录"}</p>
                    <small>记录时间：{formatDateTime(item.latestChange?.createdAt)}{item.latestChange?.sourceName ? ` · 来源：${item.latestChange.sourceName}` : ""}</small>
                  </article>
                ))}
              </div>
            </>
          ) : null}
          {withTasks.length > 0 ? (
            <>
              <h3 style={{ margin: "14px 0 6px", fontSize: 13 }}>进行中的观察任务</h3>
              <div className={styles.itemList}>
                {withTasks.map((item) => (
                  <article key={`task-${item.symbol}`}>
                    <div className={styles.itemHead}>
                      <strong>{item.name ?? item.symbol}</strong>
                      <span className={`${styles.tag} ${styles.tagNeutral}`}>{item.openTaskCount ?? "--"} 项进行中</span>
                    </div>
                    {item.nextAction ? <p>{item.nextAction.title ?? item.nextAction.nextStep ?? "待确认"}</p> : null}
                  </article>
                ))}
              </div>
            </>
          ) : null}
          {withReports.length > 0 ? (
            <>
              <h3 style={{ margin: "14px 0 6px", fontSize: 13 }}>研究报告</h3>
              <div className={styles.itemList}>
                {withReports.map((item) => (
                  <article key={`report-${item.symbol}`}>
                    <div className={styles.itemHead}>
                      <strong>{item.reportMeta?.title ?? `${item.name ?? item.symbol} 研究报告`}</strong>
                      <span className={`${styles.tag} ${item.reportFreshness.status === "attention" ? styles.tagRisk : styles.tagNeutral}`}>
                        {item.reportFreshness.label ?? "已有快照"}
                      </span>
                    </div>
                    <small>报告生成时间：{formatDateTime(item.reportMeta?.generatedAt)}</small>
                  </article>
                ))}
              </div>
            </>
          ) : null}
        </>
      )}
    </ModuleCard>
  );
}

// ---------- 二次确认对话框（结束关注） ----------

function ConfirmEndDialog({ asset, pending, onCancel, onConfirm }: {
  asset: WatchlistAsset;
  pending: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <div className={styles.dialogOverlay} onClick={pending ? undefined : onCancel}>
      <div
        aria-labelledby="confirm-end-title"
        aria-modal="true"
        className={styles.dialog}
        onClick={(event) => event.stopPropagation()}
        role="dialog"
      >
        <h2 id="confirm-end-title">结束对 {asset.name ?? asset.symbol} 的关注？</h2>
        <p>
          结束后该股票将从关注列表移除并标记为「已结束」，判断、任务与历史记录仍会保留，之后可以恢复关注。
          此操作会提交服务端关系变更，版本号 {asset.version ?? "待确认"}。
        </p>
        <div className={styles.dialogActions}>
          <button className={styles.dialogCancel} disabled={pending} onClick={onCancel} type="button">取消</button>
          <button className={styles.dialogConfirm} disabled={pending} onClick={onConfirm} type="button">
            {pending ? "写入中…" : "确认结束关注"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------- 页面 ----------

type MutationNotice = { kind: "success" | "conflict" | "failed"; text: string } | null;

const ACTION_SUCCESS_LABELS: Record<string, string> = {
  pin: "已设为重点",
  unpin: "已取消重点",
  pause: "已暂停跟踪",
  resumeTracking: "已恢复跟踪",
  resume: "已恢复关注",
  end: "已结束关注",
};

export function WatchlistPage({ authenticated }: Props) {
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const filterParam = searchParams.get("filter");
  const filter: FilterKey = FILTERS.some((item) => item.key === filterParam) ? (filterParam as FilterKey) : "all";
  const sortParam = searchParams.get("sort");
  const sort: SortKey = SORTS.some((item) => item.key === sortParam) ? (sortParam as SortKey) : "default";
  const assetsQuery = useQuery({ ...watchlistQueries.assets(), enabled: authenticated });
  const assets = assetsQuery.data ?? null;

  const [confirmEnd, setConfirmEnd] = useState<WatchlistAsset | null>(null);
  const [notice, setNotice] = useState<MutationNotice>(null);

  const refreshAssets = () => {
    void queryClient.invalidateQueries({ queryKey: ["stock-workspaces"] });
  };

  const mutation = useMutation({
    mutationFn: ({ symbol, patch }: { symbol: string; patch: RelationPatch; actionKey: string }) =>
      patchStockRelation(symbol, patch),
    onSuccess: (_data, variables) => {
      setConfirmEnd(null);
      setNotice({ kind: "success", text: `${ACTION_SUCCESS_LABELS[variables.actionKey] ?? "关系已更新"}（${variables.symbol}）。` });
      refreshAssets();
      void queryClient.invalidateQueries({ queryKey: watchlistQueryKeys.workspace(variables.symbol) });
    },
    onError: (error, variables) => {
      setConfirmEnd(null);
      if (error instanceof WatchlistApiError && error.status === 409) {
        // 409：不覆盖他页/他端最新版本，刷新列表取回新 base_version 后由用户重新确认。
        setNotice({ kind: "conflict", text: error.message });
        refreshAssets();
        return;
      }
      setNotice({ kind: "failed", text: `写入失败（${variables.symbol}）：${error instanceof Error ? error.message : "数据暂时不可用"}。未做任何本地改动，请重试。` });
    },
  });

  const updateParams = (updates: Record<string, string | null>) => {
    const next = new URLSearchParams(searchParams);
    for (const [key, value] of Object.entries(updates)) {
      if (value === null) next.delete(key);
      else next.set(key, value);
    }
    setSearchParams(next);
  };

  const handleAction = (asset: WatchlistAsset, action: RelationAction) => {
    setNotice(null);
    if (action.key === "end") {
      setConfirmEnd(asset);
      return;
    }
    try {
      const patch = buildRelationPatch(asset, (
        action.key === "pin" ? { priority: "high" }
        : action.key === "unpin" ? { priority: "normal" }
        : action.key === "pause" ? { trackingStatus: "paused" }
        : action.key === "resumeTracking" ? { trackingStatus: "active" }
        : { relationType: "watching", priority: "normal", trackingStatus: "active" }
      ));
      mutation.mutate({ symbol: asset.symbol, patch, actionKey: action.key });
    } catch (error) {
      setNotice({ kind: "failed", text: error instanceof Error ? error.message : "无法构造关系更新" });
    }
  };

  const handleConfirmEnd = () => {
    if (!confirmEnd) return;
    try {
      const patch = buildRelationPatch(confirmEnd, { relationType: "ended" });
      mutation.mutate({ symbol: confirmEnd.symbol, patch, actionKey: "end" });
    } catch (error) {
      setConfirmEnd(null);
      setNotice({ kind: "failed", text: error instanceof Error ? error.message : "无法构造关系更新" });
    }
  };

  const filtered = useMemo(() => {
    if (!assets) return [];
    return sortAssets(assets.items.filter((item) => matchesFilter(item, filter)), sort);
  }, [assets, filter, sort]);

  const symbolParam = searchParams.get("symbol");
  const selectedSymbol = symbolParam && assets?.items.some((item) => item.symbol === symbolParam)
    ? symbolParam
    : filtered[0]?.symbol ?? null;
  const selectedAsset = assets?.items.find((item) => item.symbol === selectedSymbol) ?? null;

  if (!authenticated) {
    return (
      <div className={styles.page}>
        <header className={styles.header}>
          <div className={styles.headerTitle}>
            <h1>我的关注</h1>
            <p>将持续跟踪的股票组织为研究资产目录；关系变更需要服务端确认，冲突时以服务端版本为准。</p>
          </div>
        </header>
        <div className={styles.card}>
          <div className={styles.empty}>
            <span>业务内容已锁定，请先登录或注册。</span>
            <span>登录后可管理你的关注标的、判断版本与观察事项。</span>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div className={styles.headerTitle}>
          <h1>我的关注</h1>
          <p>将持续跟踪的股票组织为研究资产目录；关系变更需要服务端确认，冲突时以服务端版本为准。</p>
        </div>
        <div className={styles.headerMeta}>
          {assetsQuery.isPending ? <span>列表读取中…</span> : null}
          {assets ? (
            <>
              <span>列表状态：<span className={`${styles.badge} ${statusTone(assets.status)}`}>{statusLabel(assets.status)}</span></span>
              <span>共 {assets.summary.total ?? "--"} 项研究资产</span>
            </>
          ) : null}
        </div>
      </header>

      {notice ? (
        <p className={`${styles.notice} ${notice.kind === "success" ? styles.noticeSuccess : ""} ${notice.kind === "conflict" ? styles.noticeConflict : ""}`} role="status">
          {notice.text}
        </p>
      ) : null}

      {assetsQuery.isError ? (
        <div className={styles.moduleError} role="status">
          <span>关注列表暂时不可用。</span>
          <button type="button" onClick={() => void assetsQuery.refetch()}>重新读取</button>
        </div>
      ) : null}

      {assetsQuery.isPending ? <div className={styles.skeleton} aria-live="polite">正在读取关注列表…</div> : null}

      {assets && assets.items.length === 0 ? (
        <div className={styles.card}>
          <div className={styles.empty}>
            <span>还没有关注任何股票。使用页面顶部的全局搜索查找股票，或从透明选股开始形成研究候选。</span>
            <div className={styles.actionRow}>
              <Link className={styles.actionLink} to="/screening">前往透明选股</Link>
            </div>
          </div>
          {assets.boundary ? <p className={styles.boundaryNote}>{assets.boundary}</p> : null}
        </div>
      ) : null}

      {assets && assets.items.length > 0 ? (
        <>
          <WatchlistSummaryCards
            active={filter}
            assets={assets}
            onSelect={(next) => updateParams({ filter: next === "all" ? null : next })}
          />
          <div className={styles.layout}>
            <div className={styles.mainColumn}>
              <ModuleCard
                meta={`${filtered.length} / ${assets.items.length} 项`}
                title="研究资产"
              >
                <div className={styles.filterBar}>
                  <label className={styles.sortLabel}>
                    排序
                    <select
                      aria-label="列表排序"
                      onChange={(event) => updateParams({ sort: event.target.value === "default" ? null : event.target.value })}
                      value={sort}
                    >
                      {SORTS.map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}
                    </select>
                  </label>
                  <span className={styles.meta}>筛选与排序在已聚合的列表数据上进行，不触发额外单股请求。</span>
                </div>
                {filtered.length === 0 ? (
                  <div className={styles.empty}>当前筛选下没有资产，切换上方概览卡查看其他分组。</div>
                ) : (
                  <AssetTable
                    items={filtered}
                    onAction={handleAction}
                    onSelect={(symbol) => updateParams({ symbol })}
                    pendingSymbol={mutation.isPending ? mutation.variables?.symbol ?? null : null}
                    selectedSymbol={selectedSymbol}
                  />
                )}
                {assets.boundary ? <p className={styles.boundaryNote}>{assets.boundary}</p> : null}
              </ModuleCard>
              <RecentSection items={assets.items} />
            </div>
            <div className={styles.mainColumn}>
              {selectedAsset ? <StockQuickPreview asset={selectedAsset} /> : (
                <div className={styles.card}><div className={styles.empty}>选择左侧一行查看快速预览。</div></div>
              )}
            </div>
          </div>
        </>
      ) : null}

      {confirmEnd ? (
        <ConfirmEndDialog
          asset={confirmEnd}
          onCancel={() => setConfirmEnd(null)}
          onConfirm={handleConfirmEnd}
          pending={mutation.isPending}
        />
      ) : null}

      <footer className={styles.footer}>
        红绿仅表示事实涨跌方向，不构成买卖建议；价格与涨跌幅来自列表聚合快照，行情失败仅影响对应行。
      </footer>
    </div>
  );
}
