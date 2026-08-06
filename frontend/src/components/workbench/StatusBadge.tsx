import styles from "./workbench.module.css";

export type WorkbenchStatus =
  | "available"
  | "partial"
  | "stale"
  | "unavailable"
  | "loading"
  | "forbidden"
  | "conflict"
  | "error";

const defaultLabels: Record<WorkbenchStatus, string> = {
  available: "可用",
  partial: "部分可用",
  stale: "数据较旧",
  unavailable: "暂不可用",
  loading: "加载中",
  forbidden: "无权访问",
  conflict: "版本冲突",
  error: "加载失败",
};

const toneClasses: Record<WorkbenchStatus, string> = {
  available: styles.badgeAvailable,
  partial: styles.badgePartial,
  stale: styles.badgeStale,
  unavailable: styles.badgeUnavailable,
  loading: styles.badgeLoading,
  forbidden: styles.badgeForbidden,
  conflict: styles.badgeConflict,
  error: styles.badgeError,
};

export function StatusBadge({ status, label }: { status: WorkbenchStatus; label?: string }) {
  const text = label ?? defaultLabels[status];
  return <span aria-label={`状态：${text}`} className={`${styles.badge} ${toneClasses[status]}`}>{text}</span>;
}
