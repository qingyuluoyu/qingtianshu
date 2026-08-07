import { queryOptions } from "@tanstack/react-query";
import { getRiskProfile } from "./api";

export const riskProfileQueries = {
  profile: () =>
    queryOptions({
      queryKey: ["risk-profile"],
      queryFn: getRiskProfile,
      staleTime: 60_000,
      retry: false,
    }),
};
