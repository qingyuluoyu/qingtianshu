import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { EventConnectionState } from "./events";
import { todayQueries } from "./queries";
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
  ResearchReportsCard,
  SectorCard,
  TodayHeader,
  TurnoverCard,
} from "./TodayComponents";
import styles from "./TodayPage.module.css";

type Props = { authenticated: boolean; eventState?: EventConnectionState };

export function shouldLoadDataHealth(authenticated: boolean): boolean {
  return authenticated;
}

/** TodayPage only owns request orchestration and layout; display logic lives in TodayComponents. */
export function TodayPage({ authenticated, eventState = "idle" }: Props) {
  const queryClient = useQueryClient();
  const overview = useQuery({ ...todayQueries.overview(), enabled: authenticated });
  const indices = useQuery({ ...todayQueries.indices(), enabled: authenticated });
  const breadth = useQuery({ ...todayQueries.breadth(), enabled: authenticated });
  const sectors = useQuery({ ...todayQueries.sectors(), enabled: authenticated });
  const watchlist = useQuery({ ...todayQueries.watchlistBrief(), enabled: authenticated });
  const actions = useQuery({ ...todayQueries.researchActions(), enabled: authenticated });
  const changes = useQuery({ ...todayQueries.researchChanges(), enabled: authenticated });
  const capitalFlow = useQuery({ ...todayQueries.capitalFlow(), enabled: authenticated });
  const anomalies = useQuery({ ...todayQueries.anomalies(), enabled: authenticated });
  const reports = useQuery({ ...todayQueries.researchReports(), enabled: authenticated });
  const positions = useQuery({ ...todayQueries.positions(), enabled: authenticated });

  // Secondary market context never competes with the first-screen data contract.
  const coreSettled = [overview, indices, breadth, sectors, watchlist, actions, changes]
    .every((query) => query.isSuccess || query.isError);
  const dataHealth = useQuery({ ...todayQueries.dataHealth(), enabled: shouldLoadDataHealth(authenticated) });
  const globalIndices = useQuery({ ...todayQueries.globalIndices(), enabled: authenticated && coreSettled });
  const liveMarkets = useQuery({ ...todayQueries.liveMarkets(), enabled: authenticated && coreSettled });
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["today"] });

  return <div className={styles.page}>
    <TodayHeader eventState={eventState} onRefresh={refresh} overview={overview.data} pending={overview.isPending} />
    <IndexSection error={indices.isError} generatedAt={indices.data?.generatedAt} items={indices.data?.items} loadHistory={authenticated && coreSettled} onRetry={() => void indices.refetch()} pending={indices.isPending} />
    <div className={styles.fourColumns}>
      <MarketBreadthCard data={breadth.data} error={breadth.isError} onRetry={() => void breadth.refetch()} pending={breadth.isPending} />
      <TurnoverCard data={breadth.data} error={breadth.isError} onRetry={() => void breadth.refetch()} pending={breadth.isPending} />
      <DistributionCard data={breadth.data} error={breadth.isError} onRetry={() => void breadth.refetch()} pending={breadth.isPending} />
      <CapitalFlowCard data={capitalFlow.data} error={capitalFlow.isError} onRetry={() => void capitalFlow.refetch()} pending={capitalFlow.isPending} />
    </div>
    <div className={styles.threeColumns}>
      <PersonalResearchSection actions={actions.data} onRefresh={() => void overview.refetch()} overview={overview.data} overviewError={overview.isError} overviewPending={overview.isPending} watchlist={watchlist.data} />
      <SectorCard data={sectors.data} error={sectors.isError} onRetry={() => void sectors.refetch()} pending={sectors.isPending} />
      <AnomalyCard data={anomalies.data} error={anomalies.isError} onRetry={() => void anomalies.refetch()} pending={anomalies.isPending} />
    </div>
    <div className={styles.threeColumns}>
      <ChangesCard authenticated={authenticated} changes={changes.data} changesError={changes.isError} changesPending={changes.isPending} onRetryChanges={() => void changes.refetch()} onRetryPositions={() => void positions.refetch()} positions={positions.data} positionsError={positions.isError} positionsPending={positions.isPending} />
      <ResearchReportsCard data={reports.data} error={reports.isError} onRetry={() => void reports.refetch()} pending={reports.isPending} />
      <GlobalMarketCard error={globalIndices.isError && liveMarkets.isError} indices={globalIndices.data} markets={liveMarkets.data} onRetry={() => { void globalIndices.refetch(); void liveMarkets.refetch(); }} pending={globalIndices.isPending && liveMarkets.isPending} />
    </div>
    <DataHealthBar data={dataHealth.data} error={dataHealth.isError} onRetry={() => void dataHealth.refetch()} pending={dataHealth.isPending} />
    <footer className={styles.boundary}>{overview.data?.boundary ?? "页面只呈现已确认事实与研究事项，不生成买卖、仓位或收益建议。"}</footer>
  </div>;
}
