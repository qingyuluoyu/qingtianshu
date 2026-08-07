import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import type { GlobalIndex } from "../today/adapters";
import { Sparkline } from "../today/charts";
import { marketDataQueries } from "./queries";
import { todayQueries } from "../today/queries";
import {
  CapitalFlowCard,
  DistributionCard,
  GlobalMarketCard,
  MarketBreadthCard,
  ModuleCard,
  SectorCard,
  TurnoverCard,
  formatDateTime,
  formatNumber,
} from "../today/TodayComponents";
import styles from "./MarketDataPage.module.css";

type Props = { authenticated: boolean };

const INDEX_GROUPS = [
  ["china", "中国"],
  ["hong_kong", "香港"],
  ["us", "美国"],
  ["europe", "欧洲"],
  ["asia_pacific", "亚太"],
] as const;

type IndexGroup = (typeof INDEX_GROUPS)[number][0];

const SECTOR_LIMIT = 20;

// /markets/live 八品种，目录固定顺序；PCT 口径（美债收益率）由 GlobalMarketCard 直通。
const LIVE_MARKET_ORDER = ["china", "japan", "korea", "us", "london_gold", "dollar_index", "brent_crude", "us10y_yield"] as const;

function percent(value: number | null): string { return value === null ? "暂无" : `${value > 0 ? "+" : ""}${formatNumber(value)}%`; }
function tone(value: number | null): string { return value === null || value === 0 ? styles.flat : value > 0 ? styles.up : styles.down; }

function IndexHistoryView({ symbol, enabled }: { symbol: string; enabled: boolean }) {
  const history = useQuery({ ...todayQueries.indexHistory(symbol), enabled });
  if (history.isPending) return <div className={styles.historyState} aria-live="polite">正在读取走势…</div>;
  if (history.isError) {
    return <div className={styles.historyState} role="status"><span>走势数据暂时不可用。</span><button type="button" onClick={() => void history.refetch()}>重新读取</button></div>;
  }
  if (!history.data || history.data.closes.length < 2) return <div className={styles.historyState}>暂无足够走势数据</div>;
  return <div className={styles.historyChart}>
    <Sparkline height={72} values={history.data.closes} width={640} />
    <p className={styles.helper}>近 1 月日线收盘 · 数据时间 {formatDateTime(history.data.marketTimestamp)}</p>
  </div>;
}

function IndexRow({ item, expanded, onToggle, loadHistory }: { item: GlobalIndex; expanded: boolean; onToggle: () => void; loadHistory: boolean }) {
  const available = item.status === "available" && item.latestClose !== null;
  return <>
    <button aria-expanded={expanded} className={`${styles.indexRow} ${expanded ? styles.indexRowActive : ""}`} onClick={onToggle} type="button">
      <span className={styles.indexName}><strong>{item.name}</strong><small>{item.symbol}</small></span>
      {available ? <>
        <b>{formatNumber(item.latestClose)}</b>
        <b className={tone(item.change1d)}>{item.change1d === null ? "暂无" : `${item.change1d > 0 ? "+" : ""}${formatNumber(item.change1d)}`}</b>
        <b className={tone(item.return1dPct)}>{percent(item.return1dPct)}</b>
        <small>{formatDateTime(item.marketTimestamp)}{item.isStale === true ? " · 缓存" : item.isStale === null ? " · 新鲜度待确认" : ""}</small>
      </> : <small className={styles.unavailable}>暂不可用</small>}
    </button>
    {expanded ? <div className={styles.historyWrap}><IndexHistoryView enabled={loadHistory} symbol={item.symbol} /></div> : null}
  </>;
}

function IndexExplorer({ group, items, pending, error, onRetry, onGroupChange, loadHistory }: { group: IndexGroup; items: GlobalIndex[] | undefined; pending: boolean; error: boolean; onRetry: () => void; onGroupChange: (group: IndexGroup) => void; loadHistory: boolean }) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const tabs = <div className={styles.tabs} role="tablist">{INDEX_GROUPS.map(([key, label]) => <button aria-selected={group === key} className={group === key ? styles.tabActive : styles.tab} key={key} onClick={() => { setExpanded(null); onGroupChange(key); }} role="tab" type="button">{label}</button>)}</div>;
  return <ModuleCard className={styles.full} title="指数总览" meta={tabs} pending={pending} error={error} onRetry={onRetry}>
    {items?.length ? <div className={styles.indexTable}>
      <div className={styles.indexTableHead}><span>指数</span><span>最新价</span><span>涨跌</span><span>涨跌幅</span><span>市场时间</span></div>
      {items.map((item) => <IndexRow expanded={expanded === item.symbol} item={item} key={item.symbol} loadHistory={loadHistory} onToggle={() => setExpanded((current) => current === item.symbol ? null : item.symbol)} />)}
      <p className={styles.helper}>点击指数行查看近 1 月走势；涨跌幅为百分数直通，不缩放。</p>
    </div> : <div className={styles.empty}>该分组暂无可确认指数数据</div>}
  </ModuleCard>;
}

export function MarketDataPage({ authenticated }: Props) {
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const groupParam = searchParams.get("group");
  const group: IndexGroup = (INDEX_GROUPS.some(([key]) => key === groupParam) ? groupParam : "china") as IndexGroup;

  const indices = useQuery(marketDataQueries.indices(group));
  const breadth = useQuery(todayQueries.breadth());
  const sectors = useQuery({ ...marketDataQueries.sectors(SECTOR_LIMIT), enabled: authenticated });
  const capitalFlow = useQuery(todayQueries.capitalFlow());
  const liveMarkets = useQuery(todayQueries.liveMarkets());

  const changeGroup = (next: IndexGroup) => {
    const params = new URLSearchParams(searchParams);
    if (next === "china") params.delete("group");
    else params.set("group", next);
    setSearchParams(params, { replace: true });
  };
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["market-data"] });
    void queryClient.invalidateQueries({ queryKey: ["today", "breadth"] });
    void queryClient.invalidateQueries({ queryKey: ["today", "capital-flow"] });
    void queryClient.invalidateQueries({ queryKey: ["today", "markets-live"] });
    void queryClient.invalidateQueries({ queryKey: ["today", "index-history"] });
  };

  if (!authenticated) {
    return <div className={styles.page}>
      <header className={styles.hero}><div><h1>行情数据</h1><p>集中呈现指数、市场广度、板块热度、全球市场与资金流向。</p></div></header>
      <div className={styles.threeColumns}>
        <MarketBreadthCard data={breadth.data} error={breadth.isError} onRetry={() => void breadth.refetch()} pending={breadth.isPending} />
        <TurnoverCard data={breadth.data} error={breadth.isError} onRetry={() => void breadth.refetch()} pending={breadth.isPending} />
        <DistributionCard data={breadth.data} error={breadth.isError} onRetry={() => void breadth.refetch()} pending={breadth.isPending} />
      </div>
      <div className={styles.threeColumns}>
        <CapitalFlowCard data={capitalFlow.data} error={capitalFlow.isError} onRetry={() => void capitalFlow.refetch()} pending={capitalFlow.isPending} />
        <GlobalMarketCard error={liveMarkets.isError} liveOrder={LIVE_MARKET_ORDER} markets={liveMarkets.data} onRetry={() => void liveMarkets.refetch()} pending={liveMarkets.isPending} />
        <div className={styles.locked}>
          <span>指数分组与板块热度已锁定，请先登录或注册。</span>
        </div>
      </div>
    </div>;
  }

  return <div className={styles.page}>
    <header className={styles.hero}>
      <div><h1>行情数据</h1><p>集中呈现指数、市场广度、板块热度、全球市场与资金流向；所有数值为后端已确认口径直通。</p></div>
      <div className={styles.heroStatus}><button className={styles.refresh} onClick={refresh} type="button">刷新</button></div>
    </header>
    <IndexExplorer error={indices.isError} group={group} items={indices.data?.items} onGroupChange={changeGroup} onRetry={() => void indices.refetch()} pending={indices.isPending} loadHistory={true} />
    <div className={styles.threeColumns}>
      <MarketBreadthCard data={breadth.data} error={breadth.isError} onRetry={() => void breadth.refetch()} pending={breadth.isPending} />
      <TurnoverCard data={breadth.data} error={breadth.isError} onRetry={() => void breadth.refetch()} pending={breadth.isPending} />
      <DistributionCard data={breadth.data} error={breadth.isError} onRetry={() => void breadth.refetch()} pending={breadth.isPending} />
    </div>
    <div className={styles.threeColumns}>
      <SectorCard data={sectors.data} error={sectors.isError} maxItems={SECTOR_LIMIT} onRetry={() => void sectors.refetch()} pending={sectors.isPending} />
      <CapitalFlowCard data={capitalFlow.data} error={capitalFlow.isError} onRetry={() => void capitalFlow.refetch()} pending={capitalFlow.isPending} />
      <GlobalMarketCard error={liveMarkets.isError} liveOrder={LIVE_MARKET_ORDER} markets={liveMarkets.data} onRetry={() => void liveMarkets.refetch()} pending={liveMarkets.isPending} />
    </div>
    <footer className={styles.boundary}>页面只呈现已确认行情事实，不生成买卖、仓位或收益建议。</footer>
  </div>;
}
