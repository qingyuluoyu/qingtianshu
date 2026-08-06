import type { WorkbenchStatus } from "./StatusBadge";
import { StatusBadge } from "./StatusBadge";
import styles from "./workbench.module.css";

export function DataTimestamp({
  asOf,
  source,
  status,
}: {
  asOf?: string | null;
  source?: string | null;
  status?: WorkbenchStatus | null;
}) {
  if (!asOf && !source && !status) return null;
  return (
    <div className={styles.timestamp}>
      {status ? <StatusBadge status={status} /> : null}
      {asOf ? <time dateTime={asOf}>数据时间：{asOf}</time> : null}
      {source ? <span>来源：{source}</span> : null}
    </div>
  );
}
