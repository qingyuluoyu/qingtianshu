import { type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { HISTORY_RANGES, type HistoryRange } from "./api";
import { stockResearchQueries, stockResearchQueryKeys } from "./queries";
import { CandlestickChart } from "./charts";
import type {
  EventTimeline,
  FinancialDrivers,
  Fundamentals,
  HistoryMetrics,
  Information,
  ModuleEnvelope,
  Shareholders,
  StockHistory,
  StockPage,
  Workspace,
  AnalystExpectations,
  EarningsQuality,
} from "./adapters";
import styles from "./StockResearchPage.module.css";

type Props = { authenticated: boolean };

type TabKey = "overview" | "technical" | "financials" | "events" | "research";

const TABS: Array<{ key: TabKey; label: string }> = [
  { key: "overview", label: "研究总览" },
  { key: "technical", label: "行情技术" },
  { key: "financials", label: "公司财务" },
  { key: "events", label: "事件预期" },
  { key: "research", label: "我的研究" },
];

const RANGE_LABELS: Record<HistoryRange, string> = { "3mo": "近3月", "6mo": "近6月", "1y": "近1年" };

// ---------- 格式化助手（直通原则：百分数不缩放；元→亿元仅为展示层单位标注） ----------

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

function formatDate(value: string | null | undefined): string {
  if (!value) return "日期待确认";
  return value.length <= 10 ? value : value.slice(0, 10);
}

function formatNumber(value: number | null, digits = 2): string {
  if (value === null) return "--";
  return new Intl.NumberFormat("zh-CN", { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(value);
}

function formatCount(value: number | null): string {
  return value === null ? "--" : new Intl.NumberFormat("zh-CN").format(value);
}

/** pct 字段后端已是百分数，直通加 % 不缩放。 */
function percent(value: number | null, sign = true): string {
  if (value === null) return "--";
  return `${sign && value > 0 ? "+" : ""}${formatNumber(value)}%`;
}

/** ratio 0-1 小数字段，UI 乘 100 展示为百分比。 */
function ratioPercent(value: number | null): string {
  if (value === null) return "--";
  return `${formatNumber(value * 100)}%`;
}

function tone(value: number | null): string {
  if (value === null || value === 0) return styles.flat;
  return value > 0 ? styles.up : styles.down;
}

/** 接口金额单位为元（CNY），此处仅做展示层单位标注（÷1e8 显示为亿元），与后端结论文本口径一致。 */
function formatCny100m(value: number | null): string {
  if (value === null) return "--";
  return `${formatNumber(value / 1e8)} 亿元`;
}

/** 持股数量单位为股，展示层标注为亿股。 */
function formatShares100m(value: number | null): string {
  if (value === null) return "--";
  return `${formatNumber(value / 1e8)} 亿股`;
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
    not_started: "未开始",
  } as Record<string, string>)[status] ?? status;
}

function statusTone(status: string): string {
  if (["available", "ready", "sufficient"].includes(status)) return styles.badgeReady;
  if (["partial", "insufficient"].includes(status)) return styles.badgePartial;
  if (["pending_confirmation", "waiting_data"].includes(status)) return styles.badgeWaiting;
  if (status === "stale") return styles.badgeStale;
  return styles.badgeUnavailable;
}

// ---------- 通用卡片 ----------

function ModuleCard({ title, meta, pending, error, onRetry, children, className = "" }: {
  title: string;
  meta?: ReactNode;
  pending?: boolean;
  error?: boolean;
  onRetry?: () => void;
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
          {onRetry ? <button type="button" onClick={onRetry}>重新读取</button> : null}
        </div>
      ) : null}
      {!pending && !error ? children : null}
    </section>
  );
}

/** 聚合内单个模块：status 不可用时只影响本卡片，不清空整页；重试触发聚合重取。 */
function ModuleSection<T>({ title, envelope, meta, onRetry, children }: {
  title: string;
  envelope: ModuleEnvelope<T> | undefined;
  meta?: ReactNode;
  onRetry?: () => void;
  children: (data: T) => ReactNode;
}) {
  const usable = envelope && envelope.data !== null && envelope.status !== "unavailable";
  return (
    <ModuleCard
      error={!usable}
      meta={meta ?? (envelope ? <span className={`${styles.badge} ${statusTone(envelope.status)}`}>{statusLabel(envelope.status)}</span> : undefined)}
      onRetry={onRetry}
      pending={false}
      title={title}
    >
      {usable ? children(envelope.data as T) : null}
    </ModuleCard>
  );
}

// ---------- 各标签页 ----------

function QuoteHeader({ history, workspace }: { history: StockHistory | null; workspace: Workspace | null }) {
  const metrics = history?.metrics ?? null;
  const price = workspace?.quote?.price ?? history?.regularMarketPrice ?? metrics?.latestClose ?? null;
  const pctChange = metrics?.return1dPct ?? workspace?.quote?.pctChange ?? null;
  const change = metrics?.change1d ?? null;
  const barDate = history?.coverage.lastTimestamp ?? history?.marketTimestamp ?? null;
  return (
    <div className={styles.quoteBlock}>
      {history === null ? <span className={styles.flat}>行情暂不可用</span> : (
        <>
          <div className={styles.quotePrice}>
            <strong>{formatNumber(price)}</strong>
            <span className={tone(change)}>{change === null ? "--" : `${change > 0 ? "+" : ""}${formatNumber(change)}`}</span>
            <span className={tone(pctChange)}>{percent(pctChange)}</span>
          </div>
          <small>
            日线截至：{barDate ? formatDate(barDate) : "待确认"} · 行情时间：{formatDateTime(history.regularMarketTimestamp)}
            {history.isStale === true ? " · 缓存数据" : ""}
          </small>
          <small>来源：{history.source ?? "待确认"} · {history.currency ?? "币种待确认"} · 时区 {history.timezone ?? "待确认"}</small>
        </>
      )}
    </div>
  );
}

function MarketSnapshot({ history, fundamentals }: { history: StockHistory | null; fundamentals: Fundamentals | null }) {
  const metrics = history?.metrics ?? null;
  const valuation = fundamentals?.valuation ?? null;
  return (
    <ModuleCard
      meta={valuation?.marketTimestamp ? `行情时间：${formatDateTime(valuation.marketTimestamp)}` : undefined}
      title="行情快照"
    >
      {metrics === null && valuation === null ? <div className={styles.empty}>行情快照暂不可用</div> : (
        <>
          <div className={styles.metricGrid}>
            <div className={styles.metric}><span>最新收盘</span><strong>{formatNumber(metrics?.latestClose ?? valuation?.previousClose ?? null)}</strong><small>日线截至 {history?.coverage.lastTimestamp ? formatDate(history.coverage.lastTimestamp) : "待确认"}</small></div>
            <div className={styles.metric}><span>近5日收益</span><strong className={tone(metrics?.return5dPct ?? null)}>{percent(metrics?.return5dPct ?? null)}</strong><small>{metrics?.return5dBaseDate ? `${formatDate(metrics.return5dBaseDate)} 起` : "基准待确认"}</small></div>
            <div className={styles.metric}><span>近20日收益</span><strong className={tone(metrics?.return20dPct ?? null)}>{percent(metrics?.return20dPct ?? null)}</strong><small>{metrics?.return20dBaseDate ? `${formatDate(metrics.return20dBaseDate)} 起` : "基准待确认"}</small></div>
            <div className={styles.metric}><span>近60日收益</span><strong className={tone(metrics?.return60dPct ?? null)}>{percent(metrics?.return60dPct ?? null)}</strong><small>{metrics?.return60dBaseDate ? `${formatDate(metrics.return60dBaseDate)} 起` : "基准待确认"}</small></div>
          </div>
          {valuation !== null ? (
            <>
              <div className={styles.metricGrid} style={{ marginTop: 10 }}>
                <div className={styles.metric}><span>市盈率 TTM</span><strong>{formatNumber(valuation.peTtm)}</strong><small>静态 {formatNumber(valuation.peStatic)} · 动态 {formatNumber(valuation.peDynamic)}</small></div>
                <div className={styles.metric}><span>市净率</span><strong>{formatNumber(valuation.pb)}</strong><small>报告期口径待确认</small></div>
                <div className={styles.metric}><span>总市值</span><strong>{formatCny100m(valuation.totalMarketCap)}</strong><small>流通 {formatCny100m(valuation.floatMarketCap)}</small></div>
                <div className={styles.metric}><span>换手率</span><strong>{percent(valuation.turnoverRatePct, false)}</strong><small>{valuation.sessionLabel ?? "交易状态待确认"}</small></div>
              </div>
              {valuation.warnings.length > 0 ? <p className={styles.helper}>{valuation.warnings.join(" ")}</p> : null}
            </>
          ) : <p className={styles.helper}>估值快照暂不可用，仅展示日线收益。</p>}
        </>
      )}
    </ModuleCard>
  );
}

function ResearchStatus({ workspace, symbol }: { workspace: Workspace | null; symbol: string }) {
  if (workspace === null) {
    return <ModuleCard error onRetry={undefined} pending={false} title="研究状态">{null}</ModuleCard>;
  }
  const hasThesis = workspace.thesis.status !== "empty" && workspace.thesis.summary !== null;
  const advisorQuery = `?symbol=${encodeURIComponent(symbol)}&source=stock-research`;
  return (
    <ModuleCard
      meta={workspace.dataMeta.financialReportPeriod ? `报告期：${workspace.dataMeta.financialReportPeriod}` : undefined}
      title="研究状态"
    >
      {hasThesis ? (
        <>
          <p className={styles.statement}>{workspace.thesis.summary}</p>
          <p className={styles.helper}>版本 {workspace.thesis.version ?? "待确认"} · 更新 {formatDateTime(workspace.thesis.updatedAt)}</p>
        </>
      ) : (
        <>
          <p className={styles.statement}>尚未保存当前判断。系统不会替你生成结论，可以从创建判断或问顾问开始。</p>
          <div className={styles.actionRow}>
            <Link className={styles.actionLink} to={`/advisor${advisorQuery}&intent=new-thesis`}>创建当前判断</Link>
            <Link className={styles.actionLink} to={`/advisor${advisorQuery}`}>问顾问</Link>
          </div>
        </>
      )}
      <div className={styles.metricGrid} style={{ marginTop: 14 }}>
        <div className={styles.metric}><span>关注关系</span><strong>{workspace.relation.label ?? "--"}</strong><small>{workspace.relation.inWatchlist === true ? "已在关注列表" : "未加入关注"}</small></div>
        <div className={styles.metric}>
          <span>深度研究</span>
          <strong>{workspace.stageProgress.status === "not_started" || workspace.stageProgress.status === null
            ? "尚未开启"
            : statusLabel(workspace.stageProgress.status)}</strong>
          <small>{workspace.stageProgress.status !== null && workspace.stageProgress.status !== "not_started" && workspace.stageProgress.progress
            ? `进度 ${workspace.stageProgress.progress.completed ?? 0}/${workspace.stageProgress.progress.total ?? 7}`
            : "开启后按阶段记录"}</small>
        </div>
        <div className={styles.metric}><span>观察任务</span><strong>{workspace.observationTasksSummary.total ?? 0}</strong><small>进行中 {workspace.observationTasksSummary.inProgress ?? 0} · 等待数据 {workspace.observationTasksSummary.waitingData ?? 0}</small></div>
        <div className={styles.metric}><span>研究报告</span><strong>{workspace.historySummary.recentReportCount ?? 0}</strong><small>{workspace.latestReport?.generatedAt ? `生成时间：${formatDateTime(workspace.latestReport.generatedAt)}` : "暂无报告"}</small></div>
      </div>
      {workspace.completeness.missingItems.length > 0 ? (
        <p className={styles.helper}>待补齐：{workspace.completeness.missingItems.join("；")}</p>
      ) : null}
    </ModuleCard>
  );
}

function KeyChanges({ workspace }: { workspace: Workspace | null }) {
  if (workspace === null) return <ModuleCard error title="关键变化">{null}</ModuleCard>;
  const changes = workspace.importantChanges.slice(0, 4);
  return (
    <ModuleCard
      meta={workspace.latestChange?.createdAt ? `生成时间：${formatDateTime(workspace.latestChange.createdAt)}` : undefined}
      title="关键变化"
    >
      {changes.length === 0 ? <div className={styles.empty}>暂无已记录的关键变化</div> : (
        <div className={styles.itemList}>
          {changes.map((change) => (
            <article key={change.id}>
              <div className={styles.itemHead}>
                <strong>{change.summary ?? "研究更新"}</strong>
                <span className={`${styles.tag} ${change.severity === "stable" ? styles.tagNeutral : ""}`}>{change.severity ?? "变化"}</span>
              </div>
              {change.nextReviewFocus ? <p>下一步复核：{change.nextReviewFocus}</p> : null}
              <small>数据截至 {change.dataAsOf ? formatDateTime(change.dataAsOf) : "待确认"} · 记录 {formatDateTime(change.createdAt)}</small>
            </article>
          ))}
        </div>
      )}
    </ModuleCard>
  );
}

function NextActions({ workspace }: { workspace: Workspace | null }) {
  if (workspace === null) return <ModuleCard error title="下一步研究动作">{null}</ModuleCard>;
  const items = workspace.nextEvidence.slice(0, 6);
  return (
    <ModuleCard title="下一步研究动作">
      {items.length === 0 && workspace.pendingActionCount === 0 ? <div className={styles.empty}>暂无待核验事项</div> : (
        <div className={styles.itemList}>
          {items.map((item, index) => (
            <article key={`${item.source ?? "evidence"}-${index}`}>
              <div className={styles.itemHead}>
                <strong>{item.description}</strong>
                <span className={styles.tag}>{item.status === "watching" ? "观察中" : item.status ?? "待办"}</span>
              </div>
              {item.source ? <small>来源：{item.source}</small> : null}
            </article>
          ))}
        </div>
      )}
      {workspace.pendingActionCount > 0 ? <p className={styles.helper}>另有 {workspace.pendingActionCount} 条待处理行动项。</p> : null}
    </ModuleCard>
  );
}

const MODULE_LABELS: Array<{ key: keyof StockPage["modules"]; label: string }> = [
  { key: "history", label: "行情历史" },
  { key: "fundamentals", label: "财务基本面" },
  { key: "earningsQuality", label: "盈利质量" },
  { key: "financialDrivers", label: "利润与现金流驱动" },
  { key: "information", label: "公告与信息" },
  { key: "shareholders", label: "股东结构" },
  { key: "eventTimeline", label: "事件脉络" },
  { key: "analystExpectations", label: "分析师预期" },
  { key: "workspace", label: "研究空间" },
];

function ModuleStatusPanel({ page }: { page: StockPage }) {
  return (
    <ModuleCard
      meta={`可用 ${page.summary.available}/${page.summary.total}${page.summary.failed > 0 ? ` · 失败 ${page.summary.failed}` : ""}`}
      title="模块数据状态"
    >
      <div className={styles.statusGrid}>
        {MODULE_LABELS.map(({ key, label }) => {
          const envelope = page.modules[key];
          return (
            <div className={styles.statusCell} key={key}>
              <span>{label}</span>
              <span className={`${styles.badge} ${statusTone(envelope.status)}`}>{statusLabel(envelope.status)}</span>
            </div>
          );
        })}
      </div>
      {page.summary.requiredFailed.length > 0 ? (
        <p className={styles.helper}>必需模块失败：{page.summary.requiredFailed.join("、")}</p>
      ) : null}
      <p className={styles.helper}>状态由后端逐模块返回；单模块失败不影响其他模块展示。</p>
    </ModuleCard>
  );
}

function OverviewTab({ page }: { page: StockPage }) {
  const history = page.modules.history.data;
  const workspace = page.modules.workspace.data;
  const fundamentals = page.modules.fundamentals.data;
  const symbol = page.symbol;
  return (
    <>
      <div className={styles.twoColumns}>
        <MarketSnapshot fundamentals={fundamentals} history={history} />
        <ResearchStatus symbol={symbol} workspace={workspace} />
      </div>
      <div className={styles.twoColumns}>
        <KeyChanges workspace={workspace} />
        <NextActions workspace={workspace} />
      </div>
      <ModuleStatusPanel page={page} />
    </>
  );
}

function MetricsGrid({ metrics }: { metrics: HistoryMetrics }) {
  return (
    <div className={styles.metricGrid}>
      <div className={styles.metric}><span>RSI(14)</span><strong>{formatNumber(metrics.rsi14)}</strong><small>{metrics.technicalState ?? "状态待确认"}</small></div>
      <div className={styles.metric}><span>MACD(12,26)</span><strong>{formatNumber(metrics.macd1226, 4)}</strong><small>信号 {formatNumber(metrics.macdSignal9, 4)} · 柱 {formatNumber(metrics.macdHistogram, 4)}</small></div>
      <div className={styles.metric}><span>MA20 / MA60</span><strong>{formatNumber(metrics.ma20)} / {formatNumber(metrics.ma60)}</strong><small>{metrics.trendState ?? "趋势待确认"}</small></div>
      <div className={styles.metric}><span>布林带(20)位置</span><strong>{metrics.bollingerPosition20 === null ? "--" : formatNumber(metrics.bollingerPosition20)}</strong><small>上 {formatNumber(metrics.bollingerUpper20)} · 下 {formatNumber(metrics.bollingerLower20)}</small></div>
      <div className={styles.metric}><span>ATR(14) 占收盘</span><strong>{percent(metrics.atr14Pct, false)}</strong><small>波动幅度参考</small></div>
      <div className={styles.metric}><span>5/20日量比</span><strong>{formatNumber(metrics.volumeRatio5to20)}</strong><small>量能相对变化</small></div>
      <div className={styles.metric}><span>60日最大回撤</span><strong className={tone(metrics.maxDrawdown60dPct)}>{percent(metrics.maxDrawdown60dPct)}</strong><small>风险结构</small></div>
      <div className={styles.metric}><span>20日年化波动率</span><strong>{percent(metrics.volatility20dAnnualizedPct, false)}</strong><small>风险结构</small></div>
    </div>
  );
}

function TechnicalTab({ symbol, range }: { symbol: string; range: HistoryRange }) {
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const history = useQuery(stockResearchQueries.history(symbol, range));
  const data = history.data ?? null;
  return (
    <>
      <ModuleCard
        meta={
          <span className={styles.rangeSwitch} role="group" aria-label="区间切换">
            {HISTORY_RANGES.map((item) => (
              <button
                aria-pressed={item === range}
                key={item}
                onClick={() => {
                  const next = new URLSearchParams(searchParams);
                  next.set("range", item);
                  setSearchParams(next);
                }}
                type="button"
              >
                {RANGE_LABELS[item]}
              </button>
            ))}
          </span>
        }
        error={history.isError}
        onRetry={() => void history.refetch()}
        pending={history.isPending}
        title="K 线主区"
      >
        {data && data.points.length > 1 ? (
          <>
            <div className={styles.chartFrame}>
              <CandlestickChart points={data.points} />
            </div>
            <div className={styles.klineMeta}>
              <span>日线截至：{data.coverage.lastTimestamp ? formatDate(data.coverage.lastTimestamp) : "待确认"}</span>
              <span>频率：{data.dataGranularity === "1d" ? "日线" : data.dataGranularity ?? "待确认"}</span>
              <span>复权：OHLC 为原始价格，接口另附 adjusted_close 复权收盘参考列</span>
              <span>区间 {data.coverage.requestedRange ?? RANGE_LABELS[range]} · 有效 bar {data.coverage.points ?? data.points.length}</span>
              <span>来源：{data.source ?? "待确认"}</span>
              {data.isStale === true ? <span>缓存数据</span> : null}
            </div>
            {data.warnings.length > 0 ? <p className={styles.helper}>{data.warnings.join(" ")}</p> : null}
          </>
        ) : <div className={styles.empty}>K 线数据暂不可用</div>}
      </ModuleCard>
      <ModuleCard
        error={history.isError}
        onRetry={() => void queryClient.invalidateQueries({ queryKey: stockResearchQueryKeys.history(symbol, range) })}
        pending={history.isPending}
        title="关键指标"
      >
        {data ? (
          <>
            <MetricsGrid metrics={data.metrics} />
            {data.metrics.technicalMethod ? <p className={styles.helper}>{data.metrics.technicalMethod}</p> : null}
          </>
        ) : null}
      </ModuleCard>
      <ModuleCard error={history.isError} pending={history.isPending} title="区间表现">
        {data ? (
          <div className={styles.metricGrid}>
            <div className={styles.metric}><span>1日收益</span><strong className={tone(data.metrics.return1dPct)}>{percent(data.metrics.return1dPct)}</strong><small>{data.metrics.return1dBaseDate ? `${formatDate(data.metrics.return1dBaseDate)} → ${formatDate(data.metrics.return1dEndDate)}` : "基准待确认"}</small></div>
            <div className={styles.metric}><span>5日收益</span><strong className={tone(data.metrics.return5dPct)}>{percent(data.metrics.return5dPct)}</strong><small>{data.metrics.return5dBaseDate ? `${formatDate(data.metrics.return5dBaseDate)} → ${formatDate(data.metrics.return5dEndDate)}` : "基准待确认"}</small></div>
            <div className={styles.metric}><span>20日收益</span><strong className={tone(data.metrics.return20dPct)}>{percent(data.metrics.return20dPct)}</strong><small>{data.metrics.return20dBaseDate ? `${formatDate(data.metrics.return20dBaseDate)} → ${formatDate(data.metrics.return20dEndDate)}` : "基准待确认"}</small></div>
            <div className={styles.metric}><span>60日收益</span><strong className={tone(data.metrics.return60dPct)}>{percent(data.metrics.return60dPct)}</strong><small>{data.metrics.return60dBaseDate ? `${formatDate(data.metrics.return60dBaseDate)} → ${formatDate(data.metrics.return60dEndDate)}` : "基准待确认"}</small></div>
          </div>
        ) : null}
      </ModuleCard>
    </>
  );
}

function FinancialPeriodsTable({ fundamentals }: { fundamentals: Fundamentals }) {
  const periods = fundamentals.periods.slice(0, 4);
  if (periods.length === 0) return <div className={styles.empty}>暂无财务报告期数据</div>;
  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <thead>
          <tr><th>报告期</th><th>营收</th><th>营收同比</th><th>归母净利</th><th>净利同比</th><th>毛利率</th><th>净利率</th><th>ROE(加权)</th><th>资产负债率</th><th>EPS</th></tr>
        </thead>
        <tbody>
          {periods.map((period) => (
            <tr key={period.reportDate ?? period.reportDateName ?? "unknown"}>
              <td>{period.reportDateName ?? period.reportDate ?? "待确认"}</td>
              <td>{formatCny100m(period.revenue)}</td>
              <td className={tone(period.revenueYoyPct)}>{percent(period.revenueYoyPct)}</td>
              <td>{formatCny100m(period.parentNetProfit)}</td>
              <td className={tone(period.netProfitYoyPct)}>{percent(period.netProfitYoyPct)}</td>
              <td>{percent(period.grossMarginPct, false)}</td>
              <td>{percent(period.netMarginPct, false)}</td>
              <td>{percent(period.roeWeightedPct, false)}</td>
              <td>{percent(period.debtAssetRatioPct, false)}</td>
              <td>{formatNumber(period.epsBasic)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className={styles.helper}>
        金额单位：亿元（接口返回元，展示层换算） · 报告期：{periods[0]?.reportDate ?? "待确认"} · 公告日期 {periods[0]?.noticeDate ?? "待确认"}
        {periods[0]?.periodBasis === "year_to_date_cumulative" ? " · 一季报/中报/三季报为年初累计口径，不能当作单季度值" : ""}
        {periods[0]?.source ? ` · 来源：${periods[0].source}` : ""}
      </p>
    </div>
  );
}

function EarningsQualityCard({ data }: { data: EarningsQuality }) {
  return (
    <>
      <p className={styles.statement}><strong>{data.overallLabel ?? "状态待确认"}</strong>{data.summary ? `：${data.summary}` : ""}</p>
      {data.factors.length > 0 ? (
        <div className={styles.itemList} style={{ marginTop: 12 }}>
          {data.factors.map((factor) => (
            <article key={factor.key}>
              <div className={styles.itemHead}>
                <strong>{factor.label ?? factor.key}</strong>
                <span className={`${styles.tag} ${factor.status === "risk" ? styles.tagRisk : factor.status === "support" ? styles.tagSupport : styles.tagNeutral}`}>
                  {factor.status === "risk" ? "风险" : factor.status === "support" ? "支撑" : factor.status ?? "观察"}
                </span>
              </div>
              <p>{factor.interpretation ?? "解释待确认"}</p>
              <small>本期 {percent(factor.valuePct)} · 可比期 {percent(factor.comparablePct)} · 变化 {factor.changePp === null ? "--" : `${factor.changePp > 0 ? "+" : ""}${formatNumber(factor.changePp)} 个百分点`}</small>
            </article>
          ))}
        </div>
      ) : null}
      {data.contradictions.length > 0 ? <p className={styles.helper}>需要复核：{data.contradictions.join("；")}</p> : null}
      {data.boundary ? <p className={styles.boundaryNote}>{data.boundary}</p> : null}
    </>
  );
}

function FinancialDriversCard({ data }: { data: FinancialDrivers }) {
  return (
    <>
      <p className={styles.statement}><strong>{data.overallLabel ?? "状态待确认"}</strong>{data.summary ? `：${data.summary}` : ""}</p>
      {data.confirmedDrivers.length > 0 ? (
        <>
          <h3 style={{ margin: "14px 0 6px", fontSize: 13 }}>已确认的报表机械影响</h3>
          <div className={styles.itemList}>
            {data.confirmedDrivers.slice(0, 5).map((driver) => (
              <article key={driver.key}>
                <div className={styles.itemHead}>
                  <strong>{driver.label ?? driver.key}</strong>
                  <span className={tone(driver.amount)}>{driver.amount === null ? "--" : formatCny100m(driver.amount)}</span>
                </div>
                {driver.statement ? <p>{driver.statement}</p> : null}
              </article>
            ))}
          </div>
        </>
      ) : null}
      {data.plausibleClues.length > 0 ? (
        <>
          <h3 style={{ margin: "14px 0 6px", fontSize: 13 }}>可疑线索（未经证实）</h3>
          <div className={styles.itemList}>
            {data.plausibleClues.slice(0, 4).map((clue) => (
              <article key={clue.key}><strong>{clue.label ?? clue.key}</strong>{clue.evidence ? <p>{clue.evidence}</p> : null}</article>
            ))}
          </div>
        </>
      ) : null}
      {data.companyExplanations.length > 0 ? (
        <>
          <h3 style={{ margin: "14px 0 6px", fontSize: 13 }}>公司原文解释（管理层披露）</h3>
          <div className={styles.itemList}>
            {data.companyExplanations.slice(0, 4).map((item, index) => (
              <article key={`${item.reportTitle ?? "explanation"}-${index}`}>
                <strong>{item.label ?? "公司解释"}</strong>
                {item.excerpt ? <p>{item.excerpt}</p> : null}
                <small>{item.reportTitle ?? "出处待确认"}{item.noticeDate ? ` · 公告发布时间：${item.noticeDate}` : ""}</small>
              </article>
            ))}
          </div>
        </>
      ) : null}
      {data.unresolvedCauses.length > 0 ? <p className={styles.helper}>尚未确认原因：{data.unresolvedCauses.join("；")}</p> : null}
      {data.boundary ? <p className={styles.boundaryNote}>{data.boundary}</p> : null}
    </>
  );
}

function FinancialsTab({ symbol, page, onRetryPage }: { symbol: string; page: StockPage; onRetryPage: () => void }) {
  const peers = useQuery(stockResearchQueries.peers(symbol));
  return (
    <>
      <ModuleSection envelope={page.modules.fundamentals} onRetry={onRetryPage} title="估值与财务摘要">
        {(data) => <FinancialPeriodsTable fundamentals={data} />}
      </ModuleSection>
      <ModuleSection envelope={page.modules.earningsQuality} meta={page.modules.earningsQuality.data?.latestReportDateName ? `报告期：${page.modules.earningsQuality.data.latestReportDateName}` : undefined} onRetry={onRetryPage} title="盈利质量">
        {(data) => <EarningsQualityCard data={data} />}
      </ModuleSection>
      <ModuleSection envelope={page.modules.financialDrivers} onRetry={onRetryPage} title="利润与现金流驱动">
        {(data) => <FinancialDriversCard data={data} />}
      </ModuleSection>
      <ModuleCard
        error={peers.isError}
        meta={peers.data?.asOf ? `行情时间：${formatDateTime(peers.data.asOf)}` : undefined}
        onRetry={() => void peers.refetch()}
        pending={peers.isPending}
        title="同行估值对比"
      >
        {peers.data ? (
          peers.data.peers.length === 0 && peers.data.subject === null ? <div className={styles.empty}>暂无同行对比数据</div> : (
            <>
              <div className={styles.tableWrap}>
                <table className={styles.table}>
                  <thead><tr><th>公司</th><th>PE(TTM)</th><th>PB</th><th>总市值</th><th>行情时间</th></tr></thead>
                  <tbody>
                    {peers.data.subject ? (
                      <tr>
                        <td><strong>{peers.data.subject.name}（本股）</strong></td>
                        <td>{formatNumber(peers.data.subject.peTtm)}</td>
                        <td>{formatNumber(peers.data.subject.pb)}</td>
                        <td>{formatCny100m(peers.data.subject.totalMarketCap)}</td>
                        <td>{formatDateTime(peers.data.subject.marketTimestamp)}</td>
                      </tr>
                    ) : null}
                    {peers.data.peers.map((peer) => (
                      <tr key={peer.symbol ?? peer.name}>
                        <td>{peer.symbol ? <Link className={styles.extLink} to={`/stocks/${encodeURIComponent(peer.symbol)}`}>{peer.name}</Link> : peer.name}</td>
                        <td>{formatNumber(peer.peTtm)}</td>
                        <td>{formatNumber(peer.pb)}</td>
                        <td>{formatCny100m(peer.totalMarketCap)}</td>
                        <td>{formatDateTime(peer.marketTimestamp)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {peers.data.operatingComparison && peers.data.operatingComparison.metrics.length > 0 ? (
                <>
                  <h3 style={{ margin: "14px 0 6px", fontSize: 13 }}>同报告期经营指标对比（{peers.data.operatingComparison.anchorReportDateName ?? "报告期待确认"}）</h3>
                  <div className={styles.tableWrap}>
                    <table className={styles.table}>
                      <thead><tr><th>指标</th><th>本股</th><th>同行中位数</th><th>样本区间</th></tr></thead>
                      <tbody>
                        {peers.data.operatingComparison.metrics.map((metric) => {
                          const isRatio = metric.key === "经营现金流/净利润";
                          const fmt = (value: number | null) => isRatio ? ratioPercent(value) : percent(value);
                          return (
                            <tr key={metric.key}>
                              <td>{metric.key}</td>
                              <td>{fmt(metric.subjectValue)}</td>
                              <td>{fmt(metric.peerMedian)}</td>
                              <td>{metric.peerMin === null || metric.peerMax === null ? "--" : `${fmt(metric.peerMin)} ~ ${fmt(metric.peerMax)}`}</td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                  <p className={styles.helper}>同行样本 {peers.data.operatingComparison.metrics[0]?.peerSampleSize ?? peers.data.coverage.availablePeers ?? "待确认"} 家 · {peers.data.selectionBasis ?? "样本口径待确认"}</p>
                </>
              ) : null}
              {peers.data.warnings.length > 0 ? <p className={styles.helper}>{peers.data.warnings.join(" ")}</p> : null}
            </>
          )
        ) : null}
      </ModuleCard>
    </>
  );
}

function TimelineEventList({ title, events, tagClass }: { title: string; events: EventTimeline["recentOfficialEvents"]; tagClass?: string }) {
  if (events.length === 0) return null;
  return (
    <>
      <h3 style={{ margin: "14px 0 6px", fontSize: 13 }}>{title}</h3>
      <div className={styles.itemList}>
        {events.slice(0, 6).map((event, index) => (
          <article key={`${event.url ?? event.title}-${index}`}>
            <div className={styles.itemHead}>
              <strong>{event.url ? <a className={styles.extLink} href={event.url} rel="noreferrer" target="_blank">{event.title}</a> : event.title}</strong>
              <span className={`${styles.tag} ${tagClass ?? ""}`}>{event.researchRelevanceLabel ?? event.eventLabel ?? "事件"}</span>
            </div>
            <small>{event.evidenceLabel ?? "证据层级待确认"} · 公告发布时间：{event.publishedAt ? formatDateTime(event.publishedAt) : "待确认"} · 来源：{event.source ?? "待确认"}</small>
          </article>
        ))}
      </div>
    </>
  );
}

function EventsTab({ page, onRetryPage }: { page: StockPage; onRetryPage: () => void }) {
  return (
    <>
      <ModuleSection envelope={page.modules.eventTimeline} meta={page.modules.eventTimeline.data?.asOfDate ? `数据截至 ${page.modules.eventTimeline.data.asOfDate}` : undefined} onRetry={onRetryPage} title="事件脉络">
        {(data: EventTimeline) => (
          <>
            {data.themes.length > 0 ? (
              <div className={styles.metricGrid}>
                {data.themes.slice(0, 4).map((theme) => (
                  <div className={styles.metric} key={theme.eventType}><span>{theme.label ?? theme.eventType}</span><strong>{theme.count ?? 0}</strong><small>条事件</small></div>
                ))}
              </div>
            ) : null}
            <TimelineEventList events={data.recentOfficialEvents} title="官方披露" />
            <TimelineEventList events={data.supportiveEvents} tagClass={styles.tagSupport} title="可能的支持线索（媒体报道）" />
            <TimelineEventList events={data.riskEvents} tagClass={styles.tagRisk} title="风险事件" />
            {data.recentOfficialEvents.length === 0 && data.supportiveEvents.length === 0 && data.riskEvents.length === 0
              ? <div className={styles.empty}>暂无事件记录</div> : null}
            <p className={styles.helper}>官方披露 {data.coverage.officialEvents ?? 0} 条 · 媒体报道 {data.coverage.mediaEvents ?? 0} 条 · 媒体报道只是定位线索，结论需读原文。</p>
            {data.boundary ? <p className={styles.boundaryNote}>{data.boundary}</p> : null}
          </>
        )}
      </ModuleSection>
      <ModuleSection envelope={page.modules.information} onRetry={onRetryPage} title="公告与信息">
        {(data: Information) => (
          <>
            {data.announcements.length === 0 && data.news.length === 0 && data.socialPosts.length === 0
              ? <div className={styles.empty}>暂无公告与信息</div> : (
                <>
                  {data.announcements.length > 0 ? (
                    <>
                      <h3 style={{ margin: "0 0 6px", fontSize: 13 }}>公司公告</h3>
                      <div className={styles.itemList}>
                        {data.announcements.slice(0, 5).map((item, index) => (
                          <article key={`ann-${index}`}>
                            <strong>{item.url ? <a className={styles.extLink} href={item.url} rel="noreferrer" target="_blank">{item.title}</a> : item.title}</strong>
                            <small>公告发布时间：{item.publishedAt ? formatDateTime(item.publishedAt) : "待确认"} · {item.source ?? "来源待确认"}</small>
                          </article>
                        ))}
                      </div>
                    </>
                  ) : null}
                  {data.news.length > 0 ? (
                    <>
                      <h3 style={{ margin: "14px 0 6px", fontSize: 13 }}>媒体报道</h3>
                      <div className={styles.itemList}>
                        {data.news.slice(0, 5).map((item, index) => (
                          <article key={`news-${index}`}>
                            <strong>{item.url ? <a className={styles.extLink} href={item.url} rel="noreferrer" target="_blank">{item.title}</a> : item.title}</strong>
                            <small>发布时间：{item.publishedAt ? formatDateTime(item.publishedAt) : "待确认"} · {item.source ?? "来源待确认"}</small>
                          </article>
                        ))}
                      </div>
                    </>
                  ) : null}
                  {data.socialPosts.length > 0 ? (
                    <>
                      <h3 style={{ margin: "14px 0 6px", fontSize: 13 }}>社区讨论（低可信样本）</h3>
                      <div className={styles.itemList}>
                        {data.socialPosts.slice(0, 3).map((item, index) => (
                          <article key={`social-${index}`}>
                            <strong>{item.url ? <a className={styles.extLink} href={item.url} rel="noreferrer" target="_blank">{item.title}</a> : item.title}</strong>
                            <small>{item.publishedAt ? formatDateTime(item.publishedAt) : "时间待确认"} · {item.summary ?? item.source ?? "来源待确认"}</small>
                          </article>
                        ))}
                      </div>
                    </>
                  ) : null}
                </>
              )}
            {data.sentiment?.caveat ? <p className={styles.helper}>情绪样本说明：{data.sentiment.caveat}（置信度 {data.sentiment.confidence ?? "待确认"}）</p> : null}
          </>
        )}
      </ModuleSection>
      <ModuleSection envelope={page.modules.shareholders} meta={page.modules.shareholders.data?.holderCountAsOf ? `股东户数截至 ${page.modules.shareholders.data.holderCountAsOf}` : undefined} onRetry={onRetryPage} title="股东结构">
        {(data: Shareholders) => (
          <>
            {data.summary ? <p className={styles.statement}>{data.summary}</p> : null}
            <div className={styles.metricGrid} style={{ marginTop: 12 }}>
              <div className={styles.metric}><span>股东户数</span><strong>{formatCount(data.holderCount)}</strong><small>较上次 {percent(data.holderCountChangePct)}（{data.signalLabel ?? "信号待确认"}）</small></div>
              <div className={styles.metric}><span>前十大合计持股</span><strong>{percent(data.top10RatioPct, false)}</strong><small>报告期：{data.top10ReportDate ?? "待确认"}</small></div>
              <div className={styles.metric}><span>前三名合计持股</span><strong>{percent(data.top3RatioPct, false)}</strong><small>存量口径</small></div>
              <div className={styles.metric}><span>户均持股</span><strong>{data.averageHolding === null ? "--" : `${formatCount(Math.round(data.averageHolding))} 股`}</strong><small>披露日期 {data.announcedAt ?? "待确认"}</small></div>
            </div>
            {data.topHolders.length > 0 ? (
              <div className={styles.tableWrap} style={{ marginTop: 12 }}>
                <table className={styles.table}>
                  <thead><tr><th>排名</th><th>股东</th><th>持股数量</th><th>持股比例</th><th>变动</th></tr></thead>
                  <tbody>
                    {data.topHolders.slice(0, 6).map((holder) => (
                      <tr key={holder.rank ?? holder.name}>
                        <td>{holder.rank ?? "--"}</td>
                        <td>{holder.name}</td>
                        <td>{formatShares100m(holder.holding)}</td>
                        <td>{percent(holder.holdingRatioPct, false)}</td>
                        <td>{holder.holdingChange ?? "--"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
            {data.boundary ? <p className={styles.boundaryNote}>{data.boundary}</p> : null}
          </>
        )}
      </ModuleSection>
      <ModuleSection envelope={page.modules.analystExpectations} meta={page.modules.analystExpectations.data?.asOfDate ? `数据截至 ${page.modules.analystExpectations.data.asOfDate}` : undefined} onRetry={onRetryPage} title="分析师预期">
        {(data: AnalystExpectations) => (
          <>
            {data.ratingStatement ? <p className={styles.statement}>{data.ratingStatement}</p> : null}
            {data.forecastEps.length > 0 ? (
              <>
                <h3 style={{ margin: "14px 0 8px", fontSize: 13 }}>每股收益汇总（A=历史实际，E=券商预测均值）</h3>
                <div className={styles.epsTable}>
                  {data.forecastEps.map((eps) => (
                    <div className={styles.epsCell} key={eps.year ?? "unknown"}>
                      <span>{eps.year ?? "待确认"}{eps.kind === "actual" ? "A" : eps.kind === "estimate" ? "E" : ""}</span>
                      <strong>{formatNumber(eps.value, 3)}</strong>
                      <small>元/股</small>
                    </div>
                  ))}
                </div>
              </>
            ) : null}
            {data.revision ? (
              <p className={styles.helper} style={{ marginTop: 12 }}>
                预期修订：{data.revision.summary ?? "暂无修订对比"}{data.revision.previousSnapshotAt ? `（对比快照 ${formatDateTime(data.revision.previousSnapshotAt)}）` : ""}
              </p>
            ) : null}
            {data.latestReports.length > 0 ? (
              <>
                <h3 style={{ margin: "14px 0 6px", fontSize: 13 }}>最近研报（{data.ratingWindow ?? "统计窗口待确认"}）</h3>
                <div className={styles.itemList}>
                  {data.latestReports.slice(0, 5).map((report, index) => (
                    <article key={`${report.title}-${index}`}>
                      <div className={styles.itemHead}>
                        <strong>{report.reportUrl ? <a className={styles.extLink} href={report.reportUrl} rel="noreferrer" target="_blank">{report.title}</a> : report.title}</strong>
                        {report.rating ? <span className={styles.tag}>评级 {report.rating}</span> : null}
                      </div>
                      <small>{[report.institution, report.researchers, report.publishedAt].filter(Boolean).join(" · ")}</small>
                    </article>
                  ))}
                </div>
              </>
            ) : null}
            <p className={styles.helper}>覆盖机构 {data.coverage.ratingOrganizations ?? data.ratingOrganizationCount ?? "--"} 家 · 返回研报 {data.coverage.reportsReturned ?? "--"} 份 · 评级分布只描述研报样本，不构成交易建议。</p>
            {data.boundary ? <p className={styles.boundaryNote}>{data.boundary}</p> : null}
          </>
        )}
      </ModuleSection>
    </>
  );
}

function ResearchTab({ symbol, page, authenticated }: { symbol: string; page: StockPage | null; authenticated: boolean }) {
  const theses = useQuery({ ...stockResearchQueries.theses(symbol), enabled: authenticated });
  const tasks = useQuery({ ...stockResearchQueries.observationTasks(symbol), enabled: authenticated });
  const position = useQuery({ ...stockResearchQueries.position(symbol), enabled: authenticated });
  const deepStock = useQuery({ ...stockResearchQueries.deepStock(symbol), enabled: authenticated });
  if (!authenticated) {
    return (
      <ModuleCard title="我的研究">
        <div className={styles.empty}>登录后可查看你的判断、观察任务、持仓与深度研究。</div>
      </ModuleCard>
    );
  }
  const workspace = page?.modules.workspace.data ?? null;
  const advisorQuery = `?symbol=${encodeURIComponent(symbol)}&source=stock-research`;
  return (
    <>
      <ModuleCard error={theses.isError} onRetry={() => void theses.refetch()} pending={theses.isPending} title="当前判断">
        {workspace && workspace.thesis.status !== "empty" && workspace.thesis.summary ? (
          <>
            <p className={styles.statement}>{workspace.thesis.summary}</p>
            <p className={styles.helper}>版本 {workspace.thesis.version ?? "待确认"} · 更新 {formatDateTime(workspace.thesis.updatedAt)}</p>
          </>
        ) : theses.data && theses.data.items.length > 0 ? (
          <div className={styles.itemList}>
            {theses.data.items.map((thesis, index) => (
              <article key={thesis.id ?? index}>
                <strong>{thesis.summary ?? "已保存判断"}</strong>
                <small>状态 {thesis.status ? statusLabel(thesis.status) : "待确认"} · 版本 {thesis.version ?? "--"} · 更新 {formatDateTime(thesis.updatedAt)}</small>
              </article>
            ))}
          </div>
        ) : (
          <>
            <p className={styles.statement}>尚未保存当前判断。</p>
            <div className={styles.actionRow}>
              <Link className={styles.actionLink} to={`/advisor${advisorQuery}&intent=new-thesis`}>创建当前判断</Link>
              <Link className={styles.actionLink} to={`/advisor${advisorQuery}`}>问顾问</Link>
            </div>
          </>
        )}
        {workspace?.boundary ? <p className={styles.boundaryNote}>{workspace.boundary}</p> : null}
      </ModuleCard>
      <ModuleCard
        error={tasks.isError}
        meta={tasks.data ? `共 ${tasks.data.summary.total ?? 0} 项` : undefined}
        onRetry={() => void tasks.refetch()}
        pending={tasks.isPending}
        title="观察任务"
      >
        {tasks.data ? (
          tasks.data.items.length === 0 ? <div className={styles.empty}>暂无观察任务。观察任务只保存需要核验的事实与证据，不是交易指令。</div> : (
            <div className={styles.itemList}>
              {tasks.data.items.map((task, index) => (
                <article key={task.id ?? index}>
                  <div className={styles.itemHead}>
                    <strong>{task.title ?? "观察任务"}</strong>
                    <span className={styles.tag}>{task.status ? statusLabel(task.status) : "待确认"}</span>
                  </div>
                  {task.summary ? <p>{task.summary}</p> : null}
                </article>
              ))}
            </div>
          )
        ) : null}
        {tasks.data?.boundary ? <p className={styles.boundaryNote}>{tasks.data.boundary}</p> : null}
      </ModuleCard>
      <div className={styles.twoColumns}>
        <ModuleCard error={position.isError} onRetry={() => void position.refetch()} pending={position.isPending} title="我的持仓">
          {position.data === null ? <div className={styles.empty}>暂无该股票的持仓记录</div> : position.data ? (
            <div className={styles.metricGrid}>
              <div className={styles.metric}><span>持仓数量</span><strong>{formatCount(position.data.quantity)}</strong><small>股</small></div>
              <div className={styles.metric}><span>成本</span><strong>{formatNumber(position.data.costBasis)}</strong><small>账本原值</small></div>
              <div className={styles.metric}><span>均价</span><strong>{formatNumber(position.data.averageCost)}</strong><small>账本原值</small></div>
              <div className={styles.metric}><span>状态</span><strong>{position.data.status ? statusLabel(position.data.status) : "--"}</strong><small>持仓账本</small></div>
            </div>
          ) : null}
        </ModuleCard>
        <ModuleCard error={deepStock.isError} onRetry={() => void deepStock.refetch()} pending={deepStock.isPending} title="深度研究">
          {deepStock.data === null ? (
            <>
              <p className={styles.statement}>深度研究会话尚未建立。</p>
              <div className={styles.actionRow}>
                <Link className={styles.actionLink} to={`/advisor${advisorQuery}&intent=deep-research`}>开启深度研究</Link>
              </div>
            </>
          ) : deepStock.data ? (
            <>
              <p className={styles.statement}>深度研究会话已建立{deepStock.data.currentStage ? `，当前阶段：${deepStock.data.currentStage}` : ""}。</p>
              {workspace?.stageProgress.progress && workspace.stageProgress.status !== "not_started" ? (
                <p className={styles.helper}>进度 {workspace.stageProgress.progress.completed ?? 0}/{workspace.stageProgress.progress.total ?? 7}</p>
              ) : null}
            </>
          ) : null}
        </ModuleCard>
      </div>
      {workspace ? (
        <ModuleCard meta={workspace.historySummary.latestReportAt ? `最近报告生成时间：${formatDateTime(workspace.historySummary.latestReportAt)}` : undefined} title="研究档案">
          <div className={styles.metricGrid}>
            <div className={styles.metric}><span>变化记录</span><strong>{workspace.historySummary.changeCount ?? 0}</strong><small>{workspace.historySummary.latestChangeAt ? `最近 ${formatDateTime(workspace.historySummary.latestChangeAt)}` : "暂无"}</small></div>
            <div className={styles.metric}><span>研究报告</span><strong>{workspace.historySummary.recentReportCount ?? 0}</strong><small>{workspace.latestReport?.title ?? "暂无报告"}</small></div>
            <div className={styles.metric}><span>判断版本</span><strong>{workspace.historySummary.thesisVersionCount ?? 0}</strong><small>历史版本数</small></div>
            <div className={styles.metric}><span>观察任务累计</span><strong>{workspace.historySummary.observationTaskCount ?? 0}</strong><small>含已完成</small></div>
          </div>
        </ModuleCard>
      ) : null}
    </>
  );
}

// ---------- 页面 ----------

export function StockResearchPage({ authenticated }: Props) {
  const params = useParams<{ symbol: string }>();
  const symbol = params.symbol ?? "";
  const [searchParams] = useSearchParams();
  const tabParam = searchParams.get("tab");
  const tab: TabKey = TABS.some((item) => item.key === tabParam) ? (tabParam as TabKey) : "overview";
  const rangeParam = searchParams.get("range");
  const range: HistoryRange = HISTORY_RANGES.includes(rangeParam as HistoryRange) ? (rangeParam as HistoryRange) : "1y";

  const page = useQuery({ ...stockResearchQueries.page(symbol, "1y"), enabled: authenticated });
  const pageData = page.data ?? null;
  const historyModule = pageData?.modules.history.data ?? null;
  const workspaceModule = pageData?.modules.workspace.data ?? null;
  const retryPage = () => void page.refetch();

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div className={styles.headerTitle}>
          <h1>
            {pageData ? (workspaceModule?.name ?? historyModule?.displayName ?? pageData.symbol) : "个股研究"}
            <small>{pageData?.symbol ?? symbol}{pageData?.market ? ` · ${pageData.market === "a_share" ? "A股" : pageData.market}` : ""}</small>
          </h1>
          <div className={styles.headerMeta}>
            {page.isPending ? <span>页面数据读取中…</span> : null}
            {pageData ? (
              <>
                <span>页面状态：<span className={`${styles.badge} ${statusTone(pageData.status)}`}>{statusLabel(pageData.status)}</span></span>
                {pageData.modules.workspace.data?.dataMeta.quoteAsOf ? <span>行情时间：{formatDateTime(pageData.modules.workspace.data.dataMeta.quoteAsOf)}</span> : null}
                {pageData.modules.workspace.data?.dataMeta.financialReportPeriod ? <span>报告期：{pageData.modules.workspace.data.dataMeta.financialReportPeriod}</span> : null}
              </>
            ) : null}
          </div>
        </div>
        <QuoteHeader history={historyModule} workspace={workspaceModule} />
      </header>

      {page.isError ? (
        <div className={styles.moduleError} role="status">
          <span>个股页面数据暂时不可用。</span>
          <button type="button" onClick={() => void page.refetch()}>重新读取</button>
        </div>
      ) : null}
      {page.isPending ? <div className={styles.skeleton} aria-live="polite">正在读取个股研究数据…</div> : null}
      {!authenticated ? (
        <div className={styles.notice} role="status">登录后可查看完整个股研究内容与个人研究空间。</div>
      ) : null}
      {pageData && pageData.summary.failed > 0 ? (
        <div className={styles.notice} role="status">部分模块暂不可用（失败 {pageData.summary.failed}/{pageData.summary.total}）；已返回模块仍保持可读。</div>
      ) : null}

      <nav aria-label="个股研究标签" className={styles.tabs}>
        {TABS.map((item) => (
          <Link
            aria-current={item.key === tab ? "page" : undefined}
            className={`${styles.tab} ${item.key === tab ? styles.tabActive : ""}`}
            key={item.key}
            to={`/stocks/${encodeURIComponent(symbol)}?tab=${item.key}${item.key === "technical" ? `&range=${range}` : ""}`}
          >
            {item.label}
          </Link>
        ))}
      </nav>

      {pageData && tab === "overview" ? <OverviewTab page={pageData} /> : null}
      {tab === "technical" ? <TechnicalTab range={range} symbol={symbol} /> : null}
      {pageData && tab === "financials" ? <FinancialsTab onRetryPage={retryPage} page={pageData} symbol={symbol} /> : null}
      {pageData && tab === "events" ? <EventsTab onRetryPage={retryPage} page={pageData} /> : null}
      {tab === "research" ? <ResearchTab authenticated={authenticated} page={pageData} symbol={symbol} /> : null}

      <footer className={styles.footer}>
        {pageData?.modules.workspace.data?.boundary ?? "页面只呈现已确认事实、证据与个人研究状态，不生成买卖、目标价或收益建议。"}
      </footer>
    </div>
  );
}
