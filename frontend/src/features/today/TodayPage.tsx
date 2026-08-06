import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { EventConnectionState } from "./events";
import { todayQueries } from "./queries";
import {
  DataHealthBar,
  DistributionCard,
  GlobalMarketCard,
  IndexSection,
  MarketBreadthCard,
  PersonalResearchSection,
  SectorCard,
  TodayHeader,
  TurnoverCard,
} from "./TodayComponents";
import styles from "./TodayPage.module.css";

type Props = { authenticated: boolean; eventState?: EventConnectionState };

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

  // Secondary market context never competes with the first-screen data contract.
  const coreSettled = [overview, indices, breadth, sectors, watchlist, actions, changes]
    .every((query) => query.isSuccess || query.isError);
  const dataHealth = useQuery({ ...todayQueries.dataHealth(), enabled: authenticated && coreSettled });
  const globalIndices = useQuery({ ...todayQueries.globalIndices(), enabled: authenticated && coreSettled });
  const liveMarkets = useQuery({ ...todayQueries.liveMarkets(), enabled: authenticated && coreSettled });
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["today"] });

  return <div className={styles.page}>
    <TodayHeader eventState={eventState} onRefresh={refresh} overview={overview.data} pending={overview.isPending} />
    <IndexSection error={indices.isError} generatedAt={indices.data?.generatedAt} items={indices.data?.items} loadHistory={authenticated && coreSettled} onRetry={() => void indices.refetch()} pending={indices.isPending} />
    <div className={styles.threeColumns}>
      <MarketBreadthCard data={breadth.data} error={breadth.isError} onRetry={() => void breadth.refetch()} pending={breadth.isPending} />
      <TurnoverCard data={breadth.data} error={breadth.isError} onRetry={() => void breadth.refetch()} pending={breadth.isPending} />
      <DistributionCard data={breadth.data} error={breadth.isError} onRetry={() => void breadth.refetch()} pending={breadth.isPending} />
    </div>
    <div className={styles.threeColumns}>
      <PersonalResearchSection actions={actions.data} changes={changes.data} onRefresh={() => void overview.refetch()} overview={overview.data} overviewError={overview.isError} overviewPending={overview.isPending} watchlist={watchlist.data} />
      <SectorCard data={sectors.data} error={sectors.isError} onRetry={() => void sectors.refetch()} pending={sectors.isPending} />
      <GlobalMarketCard error={globalIndices.isError && liveMarkets.isError} indices={globalIndices.data} markets={liveMarkets.data} onRetry={() => { void globalIndices.refetch(); void liveMarkets.refetch(); }} pending={globalIndices.isPending && liveMarkets.isPending} />
    </div>
    <DataHealthBar data={dataHealth.data} error={dataHealth.isError} onRetry={() => void dataHealth.refetch()} pending={dataHealth.isPending} />
    <footer className={styles.boundary}>{overview.data?.boundary ?? "页面只呈现已确认事实与研究事项，不生成买卖、仓位或收益建议。"}</footer>
  </div>;
}
