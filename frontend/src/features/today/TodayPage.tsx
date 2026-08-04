import { type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { todayQueries } from "./queries";
import type { EventConnectionState } from "./events";
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

  const sessionClosed = overview.data?.session.exchangeStatus !== "open";
  const eventLabel = eventState === "connected" ? "更新通道已连接" : eventState === "reconnecting" ? "更新通道重连中" : "按需更新";
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["today"] });

  return (
    <div className={styles.page}>
      <header className={styles.hero}>
        <div>
          <div className={styles.eyebrow}>TODAY · VERIFIED READ</div>
          <h1>今日观察</h1>
          <p>{overview.data?.headline ?? "市场事实与个人研究事项分区读取，数据缺失时不以零值代替。"}</p>
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

      <ModuleCard
        className={styles.full}
        title="主要指数"
        meta={indices.data?.generatedAt ? `更新 ${formatDateTime(indices.data.generatedAt)}` : undefined}
        pending={indices.isPending}
        error={indices.isError}
        onRetry={() => void indices.refetch()}
      >
        <div className={styles.indexGrid}>
          {indices.data?.items.map((item) => (
            <article className={styles.indexCard} key={item.symbol}>
              <div className={styles.indexName}><strong>{item.name}</strong><span>{item.symbol}</span></div>
              {item.status === "available" && item.latestClose !== null ? (
                <>
                  <div className={styles.indexValue}>{formatNumber(item.latestClose)}</div>
                  <div className={tone(item.return1dPct)}>{percent(item.return1dPct)}</div>
                  <small>
                    市场 {formatDateTime(item.marketTimestamp)}
                    {item.isStale === true ? " · 缓存数据" : item.isStale === null ? " · 新鲜度待确认" : ""}
                  </small>
                </>
              ) : <div className={styles.emptyCompact}>暂不可用</div>}
            </article>
          ))}
        </div>
      </ModuleCard>

      <div className={styles.twoColumns}>
        <ModuleCard title="市场广度" pending={breadth.isPending} error={breadth.isError} onRetry={() => void breadth.refetch()}>
          {breadth.data?.status === "available" ? (
            <>
              <div className={styles.breadthLead}>
                <strong>{breadth.data.state ?? "市场状态待确认"}</strong>
                <span>
                  {breadth.data.marketDate ?? "日期待确认"}
                  {breadth.data.isStale === true ? " · 非实时" : breadth.data.isStale === null ? " · 新鲜度待确认" : ""}
                </span>
              </div>
              <div className={styles.statGrid}>
                <div><span>上涨</span><strong className={styles.up}>{formatCount(breadth.data.advancers)}</strong></div>
                <div><span>下跌</span><strong className={styles.down}>{formatCount(breadth.data.decliners)}</strong></div>
                <div><span>平盘</span><strong>{formatCount(breadth.data.unchanged)}</strong></div>
                <div><span>全市场</span><strong>{formatCount(breadth.data.total)}</strong></div>
              </div>
              <div className={styles.metricRow}>
                <div><span>成交额</span><strong>{breadth.data.turnover100mCny === null ? "暂无可比数据" : `${formatNumber(breadth.data.turnover100mCny)} 亿元`}</strong></div>
                <div><span>涨跌中位数</span><strong className={tone(breadth.data.medianPctChange)}>{percent(breadth.data.medianPctChange)}</strong></div>
                <div><span>市场覆盖率</span><strong>{breadth.data.coverageRatio === null ? "暂无" : percent(breadth.data.coverageRatio * 100)}</strong></div>
              </div>
              {breadth.data.historyStatus === "intraday_not_comparable" ? <p className={styles.helper}>盘中累计成交额不与完整收盘日直接比较。</p> : null}
            </>
          ) : <div className={styles.empty}>市场广度暂不可用</div>}
        </ModuleCard>

        <ModuleCard
          title="热门板块"
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
            <div className={styles.sectorList}>
              {sectors.data.items.slice(0, 8).map((item, index) => (
                <div key={item.code}>
                  <span className={styles.rank}>{String(index + 1).padStart(2, "0")}</span>
                  <strong>{item.name}</strong>
                  <span>{formatCount(item.advancers)} 涨 / {formatCount(item.decliners)} 跌</span>
                  <b className={tone(item.pctChange)}>{percent(item.pctChange)}</b>
                </div>
              ))}
              <p className={styles.helper}>来源：{sectors.data.source ?? "待确认"} · 数据时间 {formatDateTime(sectors.data.marketTimestamp ?? sectors.data.fetchedAt)}</p>
            </div>
          ) : <div className={styles.empty}>暂无可确认板块数据</div>}
        </ModuleCard>
      </div>

      <div className={styles.twoColumns}>
        <ModuleCard
          title="优先处理"
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

        <ModuleCard title="研究变化" pending={changes.isPending} error={changes.isError} onRetry={() => void changes.refetch()}>
          {changes.data && changes.data.items.length > 0 ? (
            <div className={styles.changeList}>
              {changes.data.items.slice(0, 6).map((item) => (
                <article key={item.id}>
                  <div><strong>{item.symbol ? <Link to={`/stocks/${encodeURIComponent(item.symbol)}`}>{item.symbol}</Link> : "组合研究"}</strong>{item.severity ? <span>{item.severity}</span> : null}</div>
                  <p>{item.summary}</p>
                  <small>{item.dataAsOf ?? "数据日期待确认"}</small>
                </article>
              ))}
            </div>
          ) : <div className={styles.empty}>暂无研究变化</div>}
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
