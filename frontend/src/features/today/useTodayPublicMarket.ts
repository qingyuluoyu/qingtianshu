import { useQuery } from "@tanstack/react-query";
import { todayQueries } from "./queries";

/** Queries whose results are market-wide and do not depend on a user's session. */
export function useTodayPublicMarket() {
  const indices = useQuery(todayQueries.indices());
  const breadth = useQuery(todayQueries.breadth());
  const sectors = useQuery(todayQueries.sectors());
  const capitalFlow = useQuery(todayQueries.capitalFlow());
  const anomalies = useQuery(todayQueries.anomalies());
  const reports = useQuery(todayQueries.researchReports());
  const globalIndices = useQuery(todayQueries.globalIndices());
  const liveMarkets = useQuery(todayQueries.liveMarkets());

  return { indices, breadth, sectors, capitalFlow, anomalies, reports, globalIndices, liveMarkets };
}
