import type { WorkbenchStatus } from "./StatusBadge";
import { StatusBadge } from "./StatusBadge";
import styles from "./workbench.module.css";

export type ModuleStateKind =
  | "loading"
  | "empty"
  | "partial"
  | "unavailable"
  | "forbidden"
  | "conflict"
  | "error";

const statusByState: Record<ModuleStateKind, WorkbenchStatus> = {
  loading: "loading",
  empty: "unavailable",
  partial: "partial",
  unavailable: "unavailable",
  forbidden: "forbidden",
  conflict: "conflict",
  error: "error",
};

export function ModuleState({
  state,
  title,
  detail,
  onRetry,
}: {
  state: ModuleStateKind;
  title: string;
  detail?: string;
  onRetry?: () => void;
}) {
  const urgent = state === "error" || state === "forbidden" || state === "conflict";
  return (
    <div aria-live={urgent ? "assertive" : "polite"} className={styles.moduleState} role={urgent ? "alert" : "status"}>
      <StatusBadge status={statusByState[state]} />
      <strong>{title}</strong>
      {detail ? <p>{detail}</p> : null}
      {onRetry ? <button onClick={onRetry} type="button">重试</button> : null}
    </div>
  );
}
