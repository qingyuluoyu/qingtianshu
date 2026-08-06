import { type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { todayQueries } from "./queries";
import type { EventConnectionState } from "./events";
import type { IndexCard, LiveMarket } from "./adapters";
import { CHART_COLORS, BarChart, DonutChart, Histogram, Sparkline } from "./charts";
import styles from "./TodayPage.module.css";

type Props = {
  authenticated: boolean;
  eventState?: EventConnectionState;
};

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
  if (value === null) return "暂无";
  return new Intl.NumberFormat("zh-CN", { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(value);
}

function formatCount(value: number | null): string {
  return value === null ? "暂无" : new Intl.NumberFormat("zh-CN").format(value);
}

function percent(value: number | null): string {
  if (value === null) return "暂无";
  return `${value > 0 ? "+" : ""}${formatNumber(value)}%`;
}

function tone(value: number | null): string {
  if (value === null || value === 0) return styles.flat;
  return value > 0 ? styles.up : styles.down;
}

function priorityKind(kind: string): string {
  return ({
    research_action: "研究行动",
    observation_task: "观察任务",
    draft_confirmation: "判断草稿",
    change_event: "重要变化",
    trade_review: "交易复盘",
  } as Record<string, string>)[kind] ?? "研究事项";
}

function changeEventType(eventType: string | null): string {
  return ({ baseline: "基线建立", evidence_change: "证据变化" } as Record<string, string>)[eventType ?? ""] ?? "研究更新";
}

const GLOBAL_INDEX_ORDER = ["^GSPC", "^IXIC", "^DJI"] as const;
const LIVE_MARKET_ORDER = ["dollar_index", "london_gold", "brent_crude", "us10y_yield"] as const;

/** 海外市场现价：currency="PCT" 表示值本身是百分数，直接拼 % 不乘 100。 */
function livePrice(item: LiveMarket): string {
  if (item.latestPrice === null) return "暂无";
  if (item.currency === "PCT") return `${formatNumber(item.latestPrice)}%`;
  return `${formatNumber(item.latestPrice)}${item.currency ? ` ${item.currency}` : ""}`;
}

function themeToneClass(toneValue: string): string {
  return ({
    positive: styles.themePositive,
    negative: styles.themeNegative,
    neutral: styles.themeNeutral,
  } as Record<string, string>)[toneValue] ?? styles.themeUnknown;
}

/** 研报发布时间：纯日期直接展示，含时间走通用格式化。 */
function formatPublished(value: string | null): string {
  if (!value) return "时间待确认";
  return value.length <= 10 ? value : formatDateTime(value);
}

function ModuleCard({ title, meta, pending, error, onRetry, children, className = "" }: {
  title: string;
  meta?: ReactNode;
  pending: boolean;
  error: boolean;
  onRetry: () => void;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`${styles.card} ${className}`} aria-label={title}>
      <div className={styles.cardHeader}>
        <h2>{title}</h2>
        {meta ? <div className={styles.meta}>{meta}</div> : null}
      </div>
      {pending ? <div className={styles.skeleton} aria-live="polite">正在读取…</div> : null}
      {!pending && error ? (
        <div className={styles.moduleError} role="status">
          <span>本模块暂时不可用，其他内容仍可继续查看。</span>
          <button type="button" onClick={onRetry}>重新读取</button>
        </div>
      ) : null}
      {!pending && !error ? children : null}
    </section>
  );
}

function pointChange(value: number | null): string {
  if (value === null) return "暂无";
  return `${value > 0 ? "+" : ""}${formatNumber(value)}`;
}

function IndexCardView({ item, authenticated }: { item: IndexCard; authenticated: boolean }) {
  const available = item.status === "available" && item.latestClose !== null;
  const history = useQuery({ ...todayQueries.indexHistory(item.symbol), enabled: authenticated && available });
  return (
    <article className={styles.indexCard} key={item.symbol}>
      <div className={styles.indexName}><strong>{item.name}</strong><span>{item.symbol}</span></div>
      {available ? (
        <>
          <div className={styles.indexQuote}>
            <span className={styles.indexValue}>{formatNumber(item.latestClose)}</span>
            <span className={tone(item.change1d)}>{pointChange(item.change1d)}</span>
            <span className={tone(item.return1dPct)}>{percent(item.return1dPct)}</span>
          </div>
          {history.data ? <Sparkline values={history.data.closes} /> : null}
          <small>
            市场 {formatDateTime(item.marketTimestamp)}
            {item.isStale === true ? " · 缓存数据" : item.isStale === null ? " · 新鲜度待确认" : ""}
          </small>
        </>
      ) : <div className={styles.emptyCompact}>暂不可用</div>}
    </article>
  );
}

export function TodayPage({ authenticated, eventState = "idle" }: Props) {
  const queryClient = useQueryClient();
  const overview = useQuery({ ...todayQueries.overview(), enabled: authenticated });
  const indices = useQuery({ ...todayQueries.indices(), enabled: authenticated });
  const breadth = useQuery({ ...todayQueries.breadth(), enabled: authenticated });
  const sectors = useQuery({ ...todayQueries.sectors(), enabled: authenticated });
  const watchlist = useQuery({ ...todayQueries.watchlistBrief(), enabled: authenticated });
  const actions = useQuery({ ...todayQueries.researchActions(), enabled: authenticated });
  const changes = useQuery({ ...todayQueries.researchChanges(), enabled: authenticated });
  const dataHealth = useQuery({ ...todayQueries.dataHealth(), enabled: authenticated });
  const reports = useQuery({ ...todayQueries.researchReports(), enabled: authenticated });
  const globalIndices = useQuery({ ...todayQueries.globalIndices(), enabled: authenticated });
  const liveMarkets = useQuery({ ...todayQueries.liveMarkets(), enabled: authenticated });
  const anomalies = useQuery({ ...todayQueries.anomalies(), enabled: authenticated });
  const capitalFlow = useQuery({ ...todayQueries.capitalFlow(), enabled: authenticated });
  const positions = useQuery({ ...todayQueries.positions(), enabled: authenticated });

  const sessionClosed = overview.data?.session.exchangeStatus !== "open";
  const eventLabel = eventState === "connected" ? "更新通道已连接" : eventState === "reconnecting" ? "更新通道重连中" : "按需更新";
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["today"] });

  const breadthData = breadth.data;
  const distributionBins = breadthData?.distributionBins ?? null;
  const globalRows = GLOBAL_INDEX_ORDER.flatMap((symbol) => {
    const item = globalIndices.data?.items.find((candidate) => candidate.symbol === symbol);
    return item ? [item] : [];
  });
  const liveRows = LIVE_MARKET_ORDER.flatMap((key) => {
    const item = liveMarkets.data?.items.find((candidate) => candidate.key === key);
    return item ? [item] : [];
  });
  const globalPending = globalIndices.isPending && liveMarkets.isPending;
  const globalFailed = globalIndices.isError && liveMarkets.isError;
  const capitalFlowData = capitalFlow.data;
  const capitalFlowAvailable = capitalFlowData !== undefined
    && (capitalFlowData.mainNetInflow100mCny !== null || capitalFlowData.points.length > 0);
  // 北向资金说明优先取后端 method/warnings 文案，缺失时用静态口径说明。
  const northboundNote = capitalFlowData
    ? [...capitalFlowData.warnings, capitalFlowData.method ?? ""].find((text) => text.includes("北向"))
      ?? "北向资金自 2024-08 起已停止公开披露，本模块仅展示主力资金口径。"
    : null;

  return (
    <div className={styles.page}>
      <header className={styles.hero}>
        <div>
          <h1>今日观察</h1>
          <p>今天市场发生了什么？你应该关注哪些重点信号？</p>
        </div>
        <div className={styles.heroStatus}>
          <span className={`${styles.badge} ${sessionClosed ? styles.badgeMuted : styles.badgeLive}`}>
            {overview.data?.session.exchangeLabel ?? "交易状态读取中"}
          </span>
          <span data-testid="today-market-date">{overview.data?.marketDate ?? "市场日期读取中"}</span>
          <span data-generated-at={overview.data?.generatedAt ?? ""} data-testid="today-generated-at">生成 {formatDateTime(overview.data?.generatedAt)}</span>
          <span>{eventLabel}</span>
          <button className={styles.refresh} type="button" onClick={refresh}>刷新</button>
        </div>
      </header>

      {overview.data?.coverageStatus === "partial" ? (
        <div className={styles.notice} role="status">部分数据暂不可用；已返回模块仍保持可读。</div>
      ) : null}
      {overview.data && sessionClosed ? (
        <div className={styles.notice} role="status">当前为{overview.data.session.label}，行情展示最近已确认数据，并标注对应市场时间。</div>
      ) : null}
      {overview.data?.headline ? <div className={styles.notice} role="status">{overview.data.headline}</div> : null}

      <ModuleCard
        className={styles.full}
        title="主要指数"
        meta={indices.data?.generatedAt ? `更新 ${formatDateTime(indices.data.generatedAt)}` : undefined}
        pending={indices.isPending}
        error={indices.isError}
        onRetry={() => void indices.refetch()}
      >
        <div className={styles.indexGrid}>
          {indices.data?.items.map((item) => <IndexCardView authenticated={authenticated} item={item} key={item.symbol} />)}
        </div>
      </ModuleCard>

      <div className={styles.fourColumns}>
        <ModuleCard title="市场广度" pending={breadth.isPending} error={breadth.isError} onRetry={() => void breadth.refetch()}>
          {breadthData?.status === "available" ? (
            <>
              <div className={styles.breadthLead}>
                <strong>{breadthData.state ?? "市场状态待确认"}</strong>
                <span>
                  {breadthData.marketDate ?? "日期待确认"}
                  {breadthData.isStale === true ? " · 非实时" : breadthData.isStale === null ? " · 新鲜度待确认" : ""}
                </span>
              </div>
              <div className={styles.donutWrap}>
                <DonutChart segments={[
                  { label: "上涨", value: breadthData.advancers ?? 0, color: CHART_COLORS.up },
                  { label: "下跌", value: breadthData.decliners ?? 0, color: CHART_COLORS.down },
                  { label: "平盘", value: breadthData.unchanged ?? 0, color: CHART_COLORS.flat },
                ]} />
                <div className={styles.donutLegend}>
                  <div><i style={{ background: CHART_COLORS.up }} /><span>上涨家数</span><strong>{formatCount(breadthData.advancers)}</strong><em>{breadthData.advanceRatio === null ? "暂无" : percent(breadthData.advanceRatio * 100)}</em></div>
                  <div><i style={{ background: CHART_COLORS.down }} /><span>下跌家数</span><strong>{formatCount(breadthData.decliners)}</strong><em>{breadthData.declineRatio === null ? "暂无" : percent(breadthData.declineRatio * 100)}</em></div>
                  <div><i style={{ background: CHART_COLORS.flat }} /><span>平盘家数</span><strong>{formatCount(breadthData.unchanged)}</strong><em>{breadthData.unchangedRatio === null ? "暂无" : percent(breadthData.unchangedRatio * 100)}</em></div>
                  <div><i style={{ background: CHART_COLORS.up }} /><span>涨停家数</span><strong>{formatCount(breadthData.limitUpCount)}</strong><em /></div>
                  <div><i style={{ background: CHART_COLORS.down }} /><span>跌停家数</span><strong>{formatCount(breadthData.limitDownCount)}</strong><em /></div>
                </div>
              </div>
              <p className={styles.helper}>全市场 {formatCount(breadthData.total)} 只 · 覆盖率 {breadthData.coverageRatio === null ? "暂无" : `${formatNumber(breadthData.coverageRatio * 100)}%`}</p>
              {breadthData.limitMethod ? <p className={styles.helper}>{breadthData.limitMethod}</p> : null}
            </>
          ) : <div className={styles.empty}>市场广度暂不可用</div>}
        </ModuleCard>

        <ModuleCard title="两市成交额" pending={breadth.isPending} error={breadth.isError} onRetry={() => void breadth.refetch()}>
          {breadthData?.status === "available" ? (
            <>
              <div className={styles.turnoverLead}>
                <span>今日成交额</span>
                <strong>{breadthData.turnover100mCny === null ? "暂无可比数据" : `${formatNumber(breadthData.turnover100mCny)} 亿`}</strong>
              </div>
              <div className={styles.turnoverCompare}>
                <span>较昨日</span>
                <strong className={tone(breadthData.turnoverChangeVsPreviousPct)}>{percent(breadthData.turnoverChangeVsPreviousPct)}</strong>
              </div>
              {breadthData.turnoverHistory.length > 0 ? (
                <>
                  <p className={styles.helper}>近日成交额（亿元）</p>
                  <BarChart points={breadthData.turnoverHistory.map((point) => ({ label: point.date, value: point.amount100mCny }))} />
                </>
              ) : null}
              {breadthData.historyStatus === "intraday_not_comparable" ? <p className={styles.helper}>盘中累计成交额不与完整收盘日直接比较。</p> : null}
              {breadthData.turnoverChangeVsPreviousPct === null && breadthData.historyStatus !== "intraday_not_comparable" ? <p className={styles.helper}>历史对比数据积累中，暂无可比基准。</p> : null}
            </>
          ) : <div className={styles.empty}>成交额暂不可用</div>}
        </ModuleCard>

        <ModuleCard title="涨跌分布" meta="按涨跌幅分档" pending={breadth.isPending} error={breadth.isError} onRetry={() => void breadth.refetch()}>
          {breadthData?.status === "available" && distributionBins && distributionBins.length > 0 ? (
            <>
              <Histogram bins={distributionBins.map((bin) => ({
                label: bin.label,
                count: bin.count,
                tone: bin.key.includes("decliner") ? "down" : bin.key === "unchanged" ? "flat" : "up",
              }))} />
              <p className={styles.helper}>下跌 {formatCount(breadthData.decliners)} · 平盘 {formatCount(breadthData.unchanged)} · 上涨 {formatCount(breadthData.advancers)} · 涨跌中位数 <b className={tone(breadthData.medianPctChange)}>{percent(breadthData.medianPctChange)}</b></p>
            </>
          ) : <div className={styles.empty}>涨跌分布暂不可用</div>}
        </ModuleCard>

        <ModuleCard
          title="资金流向"
          meta={capitalFlowData?.marketTimestamp ? `更新 ${formatDateTime(capitalFlowData.marketTimestamp)}` : "亿元"}
          pending={capitalFlow.isPending}
          error={capitalFlow.isError}
          onRetry={() => void capitalFlow.refetch()}
        >
          {capitalFlowData && capitalFlowAvailable ? (
            <>
              <div className={styles.turnoverLead}>
                <span>主力净流入</span>
                <strong className={tone(capitalFlowData.mainNetInflow100mCny)}>
                  {capitalFlowData.mainNetInflow100mCny === null
                    ? "暂无"
                    : `${capitalFlowData.mainNetInflow100mCny > 0 ? "+" : ""}${formatNumber(capitalFlowData.mainNetInflow100mCny)} 亿`}
                </strong>
              </div>
              {capitalFlowData.isStale === true ? <p className={styles.helper}>缓存数据，非最新时点。</p> : null}
              {capitalFlowData.points.length > 1 ? (
                <>
                  <p className={styles.helper}>当日累计主力净流入（亿元）</p>
                  <Sparkline values={capitalFlowData.points.map((point) => point.value100mCny)} />
                </>
              ) : null}
              {northboundNote ? <p className={styles.helper}>{northboundNote}</p> : null}
            </>
          ) : <div className={styles.empty}>资金流向暂不可用</div>}
        </ModuleCard>
      </div>

      <div className={styles.threeColumns}>
        <ModuleCard
          title="今日优先事项"
          meta={actions.isPending
            ? "研究行动摘要读取中"
            : actions.isError
              ? <span className={styles.stale}>研究行动摘要暂不可用</span>
              : actions.data
                ? `${actions.data.items.length} 条确定性研究行动`
                : undefined}
          pending={overview.isPending}
          error={overview.isError}
          onRetry={() => void overview.refetch()}
        >
          {overview.data && overview.data.themes.length > 0 ? (
            <div className={styles.themeGrid}>
              {overview.data.themes.map((theme) => (
                <article className={styles.themeCard} key={theme.key}>
                  <div className={styles.themeHead}>
                    <i className={themeToneClass(theme.tone)} />
                    <strong>{theme.title}</strong>
                  </div>
                  <p>{theme.summary}</p>
                  {theme.basis ? <small>{theme.basis}</small> : null}
                </article>
              ))}
            </div>
          ) : null}
          {overview.data && overview.data.priorityItems.length > 0 ? (
            <div className={styles.priorityList}>
              {overview.data.priorityItems.map((item, index) => (
                <article key={item.id}>
                  <div className={styles.priorityIndex}>{index + 1}</div>
                  <div>
                    <div className={styles.itemTitle}>
                      <strong>{item.symbol ? <Link to={`/stocks/${encodeURIComponent(item.symbol)}`}>{item.title}</Link> : item.title}</strong>
                      <span>{priorityKind(item.kind)}{item.statusLabel ? ` · ${item.statusLabel}` : ""}</span>
                    </div>
                    {item.detail ? <p>{item.detail}</p> : null}
                    <small>{item.rankReason ?? "由后端确定性规则排序"}{item.symbol ? ` · ${item.symbol}` : ""}{item.updatedAt ? ` · ${formatDateTime(item.updatedAt)}` : ""}</small>
                  </div>
                </article>
              ))}
              {overview.data.priorityTotal > 5 ? <p className={styles.helper}>当前仅展示后端排序前 5 项。</p> : null}
            </div>
          ) : <div className={styles.empty}>{overview.data?.priorityEmptyMessage ?? "当前没有需要立即处理的个人研究事项。"}</div>}
          <div className={styles.personalMeta}>
            {watchlist.isPending ? "关注状态读取中" : watchlist.isError ? "关注状态暂不可用" : watchlist.data?.requested === 0 ? "关注列表为空" : `关注 ${watchlist.data?.requested ?? 0} 项 · 数据可用 ${watchlist.data?.available ?? 0} 项`}
          </div>
        </ModuleCard>

        <ModuleCard
          title="板块热度"
          meta={sectors.data?.isStale === null
            ? <span className={styles.stale}>新鲜度待确认</span>
            : sectors.data?.isStale || sectors.data?.hasWarnings
              ? <span className={styles.stale}>缓存 / 延迟数据</span>
              : undefined}
          pending={sectors.isPending}
          error={sectors.isError}
          onRetry={() => void sectors.refetch()}
        >
          {sectors.data && sectors.data.items.length > 0 ? (
            <div className={styles.sectorTable}>
              <div className={styles.sectorTableHead}><span>排名</span><span>板块</span><span>涨跌幅</span><span>净流入</span></div>
              {sectors.data.items.slice(0, 8).map((item, index) => (
                <div key={item.code}>
                  <span className={styles.rank}>{String(index + 1).padStart(2, "0")}</span>
                  <strong>{item.name}</strong>
                  <b className={tone(item.pctChange)}>{percent(item.pctChange)}</b>
                  <b className={tone(item.mainNetInflow100mCny)}>{item.mainNetInflow100mCny === null ? "暂无" : `${formatNumber(item.mainNetInflow100mCny)}亿`}</b>
                </div>
              ))}
              <p className={styles.helper}>来源：{sectors.data.source ?? "待确认"} · 数据时间 {formatDateTime(sectors.data.marketTimestamp ?? sectors.data.fetchedAt)} · 主力净流入不等于真实资金意图</p>
            </div>
          ) : <div className={styles.empty}>暂无可确认板块数据</div>}
        </ModuleCard>

        <ModuleCard
          title="异动机会 / 风险提示"
          meta="涨跌幅 |≥7%|"
          pending={anomalies.isPending}
          error={anomalies.isError}
          onRetry={() => void anomalies.refetch()}
        >
          {anomalies.data && anomalies.data.items.length > 0 ? (
            <div className={styles.sectorTable}>
              <div className={styles.sectorTableHead}><span>排名</span><span>个股</span><span>异动类型</span><span>涨跌幅</span></div>
              {anomalies.data.items.map((item, index) => (
                <div key={item.symbol}>
                  <span className={styles.rank}>{String(index + 1).padStart(2, "0")}</span>
                  <strong>{item.symbol ? <Link to={`/stocks/${encodeURIComponent(item.symbol)}`}>{item.name ?? item.symbol}</Link> : (item.name ?? item.symbol)}</strong>
                  <b>{item.kind}</b>
                  <b className={tone(item.pctChange)}>{percent(item.pctChange)}</b>
                </div>
              ))}
              <p className={styles.helper}>数据时间 {formatDateTime(anomalies.data.marketTimestamp)} · 口径：全市场快照中 |涨跌幅|≥7% 的个股</p>
            </div>
          ) : (
            <div className={styles.empty}>
              {anomalies.data?.status === "available" ? "当前没有 |涨跌幅|≥7% 的异动个股。" : "异动数据暂不可用。"}
            </div>
          )}
        </ModuleCard>
      </div>

      <div className={styles.threeColumns}>
        <ModuleCard title="我的股票新变化" pending={changes.isPending} error={changes.isError} onRetry={() => void changes.refetch()}>
          {changes.data && changes.data.items.length > 0 ? (
            <div className={styles.changeList}>
              {changes.data.items.slice(0, 6).map((item) => (
                <article key={item.id}>
                  <div><strong>{item.symbol ? <Link to={`/stocks/${encodeURIComponent(item.symbol)}`}>{item.symbol}</Link> : "组合研究"}</strong><span>{changeEventType(item.eventType)}{item.severity ? ` · ${item.severity}` : ""}</span></div>
                  <p>{item.summary}</p>
                  <small>{item.dataAsOf ?? "数据日期待确认"}</small>
                </article>
              ))}
            </div>
          ) : <div className={styles.empty}>暂无研究变化</div>}
          <h3 className={styles.subHeading}>我的持仓</h3>
          {!authenticated ? <p className={styles.helper}>暂无持仓</p>
            : positions.isPending ? <p className={styles.helper}>持仓读取中…</p>
              : positions.isError ? <p className={styles.helper}>持仓暂不可用，其他内容仍可查看。</p>
                : positions.data && positions.data.items.length > 0 ? (
                  <div className={styles.positionTable}>
                    <div className={styles.positionHead}><span>代码</span><span>名称</span><span>数量</span><span>成本</span><span>均价</span></div>
                    {positions.data.items.map((item) => (
                      <div className={styles.positionRow} key={`${item.workspaceId ?? "ws"}-${item.symbol}`}>
                        <strong>{item.symbol ? <Link to={`/stocks/${encodeURIComponent(item.symbol)}`}>{item.symbol}</Link> : item.symbol}</strong>
                        <span>{item.name ?? "—"}</span>
                        <b>{item.quantity === null ? "暂无" : formatCount(item.quantity)}</b>
                        <b>{formatNumber(item.costBasis)}</b>
                        <b>{formatNumber(item.averageCost)}</b>
                      </div>
                    ))}
                  </div>
                ) : <p className={styles.helper}>暂无持仓</p>}
        </ModuleCard>

        <ModuleCard title="今日研究报告" pending={reports.isPending} error={reports.isError} onRetry={() => void reports.refetch()}>
          {reports.data && reports.data.items.length > 0 ? (
            <div className={styles.reportList}>
              {reports.data.items.slice(0, 8).map((item, index) => (
                <article key={`${item.symbol ?? "report"}-${index}`}>
                  <strong>{item.symbol ? <Link to={`/stocks/${encodeURIComponent(item.symbol)}`}>{item.title}</Link> : item.title}</strong>
                  <small>{[item.name ?? item.symbol, item.institution, item.rating ? `评级 ${item.rating}` : null, formatPublished(item.publishedAt)].filter(Boolean).join(" · ")}</small>
                </article>
              ))}
            </div>
          ) : <div className={styles.empty}>{reports.data?.status === "empty" ? "暂无最新研究报告" : "暂无已生成的研究报告"}</div>}
        </ModuleCard>

        <ModuleCard
          title="全球市场观察"
          pending={globalPending}
          error={globalFailed}
          onRetry={() => { void globalIndices.refetch(); void liveMarkets.refetch(); }}
        >
          {globalRows.length > 0 || liveRows.length > 0 ? (
            <div className={styles.globalTable}>
              <div className={styles.sectorTableHead}><span>指数</span><span>最新价</span><span>涨跌幅</span></div>
              {globalRows.map((item) => (
                <div key={item.symbol}>
                  <strong>{item.name}</strong>
                  <b>{formatNumber(item.latestClose)}</b>
                  <b className={tone(item.return1dPct)}>{percent(item.return1dPct)}</b>
                </div>
              ))}
              {liveRows.map((item) => (
                <div key={item.key}>
                  <strong>{item.name}</strong>
                  <b>{livePrice(item)}</b>
                  <b className={tone(item.pctChange)}>{percent(item.pctChange)}</b>
                </div>
              ))}
              <p className={styles.helper}>海外市场存在延迟，展示最近已确认数据；美债收益率为百分数原值。</p>
            </div>
          ) : <div className={styles.empty}>海外市场数据暂不可用</div>}
        </ModuleCard>
      </div>

      <ModuleCard
        className={styles.full}
        title="数据状态"
        meta={dataHealth.data ? `检查 ${dataHealth.data.summary.total} 项` : undefined}
        pending={dataHealth.isPending}
        error={dataHealth.isError}
        onRetry={() => void dataHealth.refetch()}
      >
        {dataHealth.data ? (
          <div className={styles.healthLayout}>
            <div className={styles.healthSummary}>
              <span className={`${styles.healthDot} ${dataHealth.data.status === "healthy" ? styles.healthGood : styles.healthAttention}`} />
              <div><strong>{dataHealth.data.userLabel}</strong><small>{dataHealth.data.status} · 检查时间 {formatDateTime(dataHealth.data.createdAt)}</small></div>
              <dl>
                <div><dt>正常</dt><dd>{dataHealth.data.summary.healthy}</dd></div>
                <div><dt>关注</dt><dd>{dataHealth.data.summary.attention}</dd></div>
                <div><dt>关键</dt><dd>{dataHealth.data.summary.critical}</dd></div>
              </dl>
            </div>
            <div>
              <div className={styles.healthCategories}>
                {dataHealth.data.categories.map((category) => (
                  <div key={category.key}><span>{category.label}</span><strong>{category.status}</strong><small>{category.count} 项</small></div>
                ))}
              </div>
              <div className={styles.healthChecks}>
                {dataHealth.data.actionableChecks.length > 0 ? dataHealth.data.actionableChecks.map((check) => (
                  <div key={check.key}><span>{check.status === "critical" ? "关键" : "关注"}</span><strong>{check.label}</strong></div>
                )) : <span>当前没有需要用户关注的数据检查。</span>}
              </div>
            </div>
          </div>
        ) : null}
      </ModuleCard>

      <footer className={styles.boundary}>{overview.data?.boundary ?? "页面只呈现已确认事实与研究事项，不生成买卖、仓位或收益建议。"}</footer>
    </div>
  );
}
