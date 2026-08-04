import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";

function isUnauthorizedError(error: unknown): boolean {
  return typeof error === "object"
    && error !== null
    && "status" in error
    && error.status === 401;
}

export function useUnauthorizedBoundary(authenticated: boolean, onUnauthorized: () => void): void {
  const queryClient = useQueryClient();
  const handledRef = useRef(false);
  const onUnauthorizedRef = useRef(onUnauthorized);
  onUnauthorizedRef.current = onUnauthorized;

  useEffect(() => {
    if (authenticated) handledRef.current = false;
  }, [authenticated]);

  useEffect(() => queryClient.getQueryCache().subscribe((event) => {
    if (event.type !== "updated" || event.action.type !== "error") return;
    if (handledRef.current || !isUnauthorizedError(event.query.state.error)) return;
    handledRef.current = true;
    onUnauthorizedRef.current();
  }), [queryClient]);
}
