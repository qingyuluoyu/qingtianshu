import styles from "./StockResearchPage.module.css";

/** Keeps the research boundary adjacent to the page while the container owns its source data. */
export function StockResearchEvidence({ boundary }: { boundary: string }) {
  return <footer className={styles.footer}>{boundary}</footer>;
}
