import type { ReactNode } from "react";
import styles from "./StockResearchPage.module.css";

type Props = {
  title: string;
  symbol: string;
  marketLabel: string | null;
  pending: boolean;
  status: { label: string; tone: string } | null;
  quoteAsOf: string | null;
  financialReportPeriod: string | null;
  quote: ReactNode;
};

/** Presentation-only stock header; data retrieval and financial labels stay in the page container. */
export function StockResearchHeader({ title, symbol, marketLabel, pending, status, quoteAsOf, financialReportPeriod, quote }: Props) {
  return <header className={styles.header}>
    <div className={styles.headerTitle}>
      <h1>{title}<small>{symbol}{marketLabel ? ` · ${marketLabel}` : ""}</small></h1>
      <div className={styles.headerMeta}>
        {pending ? <span>页面数据读取中…</span> : null}
        {status ? <span>页面状态：<span className={`${styles.badge} ${status.tone}`}>{status.label}</span></span> : null}
        {quoteAsOf ? <span>行情时间：{quoteAsOf}</span> : null}
        {financialReportPeriod ? <span>报告期：{financialReportPeriod}</span> : null}
      </div>
    </div>
    {quote}
  </header>;
}
