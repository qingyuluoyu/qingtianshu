import styles from "./ScreeningPage.module.css";

type ModeKey = "screen" | "lizong" | "backtest";

const modes: Array<{ key: ModeKey; label: string; hint: string }> = [
  { key: "screen", label: "通用筛选", hint: "透明规则条件、命中候选和每条规则的事实依据。" },
  { key: "lizong", label: "李总指标筛选", hint: "展示策略快照候选、命中理由和数据缺口。" },
  { key: "backtest", label: "历史复盘 / 回测", hint: "仅展示服务端已完成的回测结果和真实进度。" },
];

type Props = { active: ModeKey; onSelect: (mode: ModeKey) => void };

/** Presentation-only mode selector; URL state remains in ScreeningPage. */
export function ScreeningFilters({ active, onSelect }: Props) {
  return <div className={styles.modeGrid} role="group" aria-label="选股模式">
    {modes.map(({ key, label, hint }) => <button aria-pressed={active === key} className={styles.modeCard} key={key} onClick={() => onSelect(key)} type="button">
      <span>{label}</span><small>{hint}</small>
    </button>)}
  </div>;
}
