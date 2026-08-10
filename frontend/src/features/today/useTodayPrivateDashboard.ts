import { useQuery } from "@tanstack/react-query";
import { todayQueries } from "./queries";

/** Queries that are scoped to the authenticated user's workspace. */
export function useTodayPrivateDashboard(authenticated: boolean) {
  const overview = useQuery({ ...todayQueries.overview(), enabled: authenticated });
  const watchlist = useQuery({ ...todayQueries.watchlistBrief(), enabled: authenticated });
  const actions = useQuery({ ...todayQueries.researchActions(), enabled: authenticated });
  const changes = useQuery({ ...todayQueries.researchChanges(), enabled: authenticated });
  const positions = useQuery({ ...todayQueries.positions(), enabled: authenticated });
  const dataHealth = useQuery({ ...todayQueries.dataHealth(), enabled: authenticated });

  return { overview, watchlist, actions, changes, positions, dataHealth };
}
