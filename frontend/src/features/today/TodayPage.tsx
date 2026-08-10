import { useQueryClient } from "@tanstack/react-query";
import { AccessGate } from "../../components/AccessGate";
import type { EventConnectionState } from "./events";
import {
  AnomalyCard,
  CapitalFlowCard,
  ChangesCard,
  DataHealthBar,
  DistributionCard,
  GlobalMarketCard,
  IndexSection,
  MarketBreadthCard,
  PersonalResearchSection,
  PrivateModuleNotice,
  ResearchReportsCard,
  SectorCard,
  TodayHeader,
  TurnoverCard,
} from "./TodayComponents";
import styles from "./TodayPage.module.css";
import { useTodayPublicMarket } from "./useTodayPublicMarket";
import { useTodayPrivateDashboard } from "./useTodayPrivateDashboard";

type Props = { authenticated: boolean; eventState?: EventConnectionState };

export function TodayPage({ authenticated, eventState = "idle" }: Props) {
  const queryClient = useQueryClient();
  const { overview, watchlist, actions, changes, positions, dataHealth } = useTodayPrivateDashboard(authenticated);
  const { indices, breadth, sectors, capitalFlow, anomalies, reports, globalIndices, liveMarkets } = useTodayPublicMarket();
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["today"] });

  return <div className={styles.page}>
    <TodayHeader eventState={eventState} onRefresh={refresh} overview={authenticated ? overview.data : undefined} pending={authenticated && overview.isPending} />

    {authenticated ? (
      <section aria-label="今日任务" className={styles.prioritySection}>
        <div className={styles.sectionLead}>
          <div>
            <p className={styles.sectionEyebrow}>先处理个人事项</p>
            <h2>今日任务</h2>
          </div>
          <p>按风险、到期时间和研究状态确定性排序，不暴露虚假精确分数。</p>
        </div>
        <PersonalResearchSection actions={actions.data} onRefresh={() => void overview.refetch()} overview={overview.data} overviewError={overview.isError} overviewPending={overview.isPending} watchlist={watchlist.data} />
      </section>
    ) : null}

    <section aria-label="市场脉搏" className={styles.dashboardSection}>
      <div className={styles.sectionLead}>
        <div>
          <p className={styles.sectionEyebrow}>市场快照</p>
          <h2>市场脉搏</h2>
        </div>
        <p>先看交易状态、主要指数与市场温度。</p>
      </div>
      <IndexSection error={indices.isError} generatedAt={indices.data?.generatedAt} items={indices.data?.items} loadHistory onRetry={() => void indices.refetch()} pending={indices.isPending} />
      <div className={styles.signalGrid}>
        <MarketBreadthCard data={breadth.data} error={breadth.isError} onRetry={() => void breadth.refetch()} pending={breadth.isPending} />
        <TurnoverCard data={breadth.data} error={breadth.isError} onRetry={() => void breadth.refetch()} pending={breadth.isPending} />
        <DistributionCard data={breadth.data} error={breadth.isError} onRetry={() => void breadth.refetch()} pending={breadth.isPending} />
        <CapitalFlowCard data={capitalFlow.data} error={capitalFlow.isError} onRetry={() => void capitalFlow.refetch()} pending={capitalFlow.isPending} />
      </div>
    </section>

    <section aria-label="市场背景" className={styles.dashboardSection}>
      <div className={styles.sectionLead}>
        <div>
          <p className={styles.sectionEyebrow}>结构确认</p>
          <h2>市场背景</h2>
        </div>
        <p>用行业热度与异动线索确认市场结构。</p>
      </div>
      <div className={styles.contextGrid}>
        <SectorCard data={sectors.data} error={sectors.isError} onRetry={() => void sectors.refetch()} pending={sectors.isPending} />
        <AnomalyCard data={anomalies.data} error={anomalies.isError} onRetry={() => void anomalies.refetch()} pending={anomalies.isPending} />
      </div>
    </section>

    <section aria-label="研究跟进" className={styles.dashboardSection}>
      <div className={styles.sectionLead}>
        <div>
          <p className={styles.sectionEyebrow}>研究工作台</p>
          <h2>研究跟进</h2>
        </div>
        <p>公开线索与个人研究分层显示，登录后查看关注与持仓变化。</p>
      </div>
      <div className={styles.followUpGrid}>
        <AccessGate allowed={authenticated} fallback={<PrivateModuleNotice title="我的股票新变化" />}><ChangesCard changes={changes.data} changesError={changes.isError} changesPending={changes.isPending} onRetryChanges={() => void changes.refetch()} onRetryPositions={() => void positions.refetch()} positions={positions.data} positionsError={positions.isError} positionsPending={positions.isPending} /></AccessGate>
        <ResearchReportsCard data={reports.data} error={reports.isError} onRetry={() => void reports.refetch()} pending={reports.isPending} />
        <GlobalMarketCard error={globalIndices.isError && liveMarkets.isError} indices={globalIndices.data} markets={liveMarkets.data} onRetry={() => { void globalIndices.refetch(); void liveMarkets.refetch(); }} pending={globalIndices.isPending && liveMarkets.isPending} />
      </div>
    </section>

    <AccessGate allowed={authenticated}><DataHealthBar data={dataHealth.data} error={dataHealth.isError} onRetry={() => void dataHealth.refetch()} pending={dataHealth.isPending} /></AccessGate>
    <footer className={styles.boundary}>{overview.data?.boundary ?? "页面只呈现已确认事实与研究事项，不生成买卖、仓位或收益建议。"}</footer>
  </div>;
}
