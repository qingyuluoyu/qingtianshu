import { DataTimestamp } from "../../../components/workbench/DataTimestamp";
import { StatusBadge } from "../../../components/workbench/StatusBadge";
import type { AdvisorEntryContext } from "../adapters";
import styles from "../AdvisorPage.module.css";

const sourceLabels: Record<string, string> = {
  today: "今日观察",
  screening: "透明选股",
  watchlist: "我的关注",
  stock: "个股研究",
  advisor: "金融顾问",
  research_center: "研究中心",
};

export function ContextBar({
  symbol,
  requestedSource,
  requestedModule,
  persisted,
  checking,
  hasRun,
}: {
  symbol: string | null;
  requestedSource: string;
  requestedModule: string;
  persisted: AdvisorEntryContext | null;
  checking: boolean;
  hasRun: boolean;
}) {
  const recorded = Boolean(
    persisted
    && persisted.sourcePage === requestedSource
    && persisted.module === requestedModule
    && (persisted.symbol ?? null) === symbol,
  );
  return (
    <section aria-label="本轮研究上下文" className={styles.contextBar}>
      <div>
        <span className={styles.eyebrow}>本轮上下文</span>
        <strong>{symbol ?? "全局金融研究"}</strong>
        <span>来自 {sourceLabels[requestedSource] ?? requestedSource} · {requestedModule}</span>
      </div>
      <div className={styles.contextStatus}>
        {recorded ? <StatusBadge label="来源已记录" status="available" /> : null}
        {!recorded && checking ? <StatusBadge label="正在核对来源记录" status="loading" /> : null}
        {!recorded && !checking ? <StatusBadge label={hasRun ? "来源记录未确认" : "发送后记录来源"} status="unavailable" /> : null}
        {persisted?.asOf ? <DataTimestamp asOf={persisted.asOf} /> : null}
      </div>
    </section>
  );
}
