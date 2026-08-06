import type { ReactNode } from "react";
import { ModuleState } from "./ModuleState";
import styles from "./workbench.module.css";

export function ChartContainer({
  title,
  description,
  hasData,
  children,
}: {
  title: string;
  description?: string;
  hasData: boolean;
  children: ReactNode;
}) {
  return (
    <section aria-label={title} className={styles.chartContainer}>
      <header>
        <h2>{title}</h2>
        {description ? <p>{description}</p> : null}
      </header>
      <div className={styles.chartRegion}>
        {hasData ? children : <ModuleState state="empty" title="暂无可展示的图表数据" />}
      </div>
    </section>
  );
}
