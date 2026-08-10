import type { ReactNode } from "react";

type AccessGateProps = {
  allowed: boolean;
  children: ReactNode;
  fallback?: ReactNode;
};

/** Keeps protected UI out of the tree until the caller has established access. */
export function AccessGate({ allowed, children, fallback = null }: AccessGateProps) {
  return allowed ? children : fallback;
}
