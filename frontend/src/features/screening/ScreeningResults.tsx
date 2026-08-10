import type { ScreenItem } from "./adapters";
import styles from "./ScreeningPage.module.css";

function formatNumber(value: number | null, digits = 2): string {
  if (value === null) return "--";
  return new Intl.NumberFormat("zh-CN", { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(value);
}

function percent(value: number | null): string {
  if (value === null) return "--";
  return `${value > 0 ? "+" : ""}${formatNumber(value)}%`;
}

function signedTone(value: number | null): string {
  if (value === null || value === 0) return styles.flat;
  return value > 0 ? styles.up : styles.down;
}

function candidateStatus(item: ScreenItem): { label: string; tone: string } {
  return item.missingFields.length > 0
    ? { label: "数据不足", tone: styles.badgePartial }
    : { label: "通过", tone: styles.badgeReady };
}

type Props = {
  items: ScreenItem[];
  selectedSymbol: string | null;
  onSelect: (symbol: string) => void;
};

/** Presentation-only candidate table; query and URL state remain in ScreeningPage. */
export function ScreeningResults({ items, selectedSymbol, onSelect }: Props) {
  return <div className={styles.tableWrap}>
    <table className={styles.table}>
      <thead><tr><th>代码</th><th>名称</th><th>收盘</th><th>涨跌</th><th>总市值（亿）</th><th>PE TTM</th><th>近 5 日价格涨跌</th><th>近 20 日价格涨跌</th><th>状态</th><th>命中理由</th></tr></thead>
      <tbody>{items.map((item) => {
        const status = candidateStatus(item);
        return <tr aria-selected={selectedSymbol === item.symbol} key={item.symbol} onClick={() => onSelect(item.symbol)} onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            onSelect(item.symbol);
          }
        }} tabIndex={0}>
          <td className={styles.symbolCell}><strong>{item.symbol}</strong><small>{item.market ?? "市场待确认"}</small></td>
          <td className={styles.symbolCell}><strong>{item.name ?? "名称待确认"}</strong><small>{item.industry ?? "行业待确认"}</small></td>
          <td>{formatNumber(item.metrics.latestClose)}</td>
          <td className={signedTone(item.metrics.pctChange)}>{percent(item.metrics.pctChange)}</td>
          <td>{formatNumber(item.metrics.totalMvYi)}</td>
          <td>{formatNumber(item.metrics.peTtm)}</td>
          <td className={signedTone(item.metrics.return5dPct)}>{percent(item.metrics.return5dPct)}</td>
          <td className={signedTone(item.metrics.return20dPct)}>{percent(item.metrics.return20dPct)}</td>
          <td><span className={`${styles.badge} ${status.tone}`}>{status.label}</span></td>
          <td className={styles.reasonCell}><span>{item.matchedReasons.length > 0 ? `${item.matchedReasons[0]}${item.matchedReasons.length > 1 ? ` 等 ${item.matchedReasons.length} 条` : ""}` : "命中理由待确认"}</span></td>
        </tr>;
      })}</tbody>
    </table>
  </div>;
}
