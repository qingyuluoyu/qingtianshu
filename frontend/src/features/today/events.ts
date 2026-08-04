import { useEffect, useState } from "react";
import { useQueryClient, type QueryKey } from "@tanstack/react-query";
import { todayQueryKeys } from "./queries";

const researchKeys = [
  todayQueryKeys.overview,
  todayQueryKeys.researchActions,
  todayQueryKeys.researchChanges,
] satisfies QueryKey[];

export function queryKeysForEvent(type: string): QueryKey[] {
  if (type === "market_updated") {
    return [todayQueryKeys.overview, todayQueryKeys.indices, todayQueryKeys.breadth, todayQueryKeys.sectors];
  }
  if (type === "data_health_updated") return [todayQueryKeys.dataHealth];
  if (type === "evidence_tasks_updated" || type.startsWith("research-change")) return researchKeys;
  // This page does not issue a report query, so report refreshes have no consumer to invalidate.
  if (type === "research_reports_updated") return [];
  return [];
}

export type EventConnectionState = "idle" | "connected" | "reconnecting";

export function usePublicEvents(enabled: boolean): EventConnectionState {
  const queryClient = useQueryClient();
  const [state, setState] = useState<EventConnectionState>("idle");

  useEffect(() => {
    if (!enabled) {
      setState("idle");
      return;
    }
    const source = new EventSource("/events");
    source.onopen = () => setState("connected");
    source.onerror = () => setState("reconnecting");
    source.onmessage = (message) => {
      try {
        const payload: unknown = JSON.parse(message.data);
        if (typeof payload !== "object" || payload === null || !("type" in payload)) return;
        const type = (payload as { type?: unknown }).type;
        if (typeof type !== "string") return;
        const keys = queryKeysForEvent(type);
        if (keys.length === 0 && import.meta.env.DEV && type !== "connected" && type !== "research_reports_updated") {
          console.debug(`[events] ignored event type: ${type}`);
        }
        for (const queryKey of keys) void queryClient.invalidateQueries({ queryKey });
      } catch {
        if (import.meta.env.DEV) console.debug("[events] ignored malformed payload");
      }
    };
    return () => source.close();
  }, [enabled, queryClient]);

  return state;
}
