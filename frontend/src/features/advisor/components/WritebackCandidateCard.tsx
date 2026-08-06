import type { WritebackCandidate } from "../adapters";
import styles from "../AdvisorPage.module.css";

function text(payload: Record<string, unknown>, key: string): string | null {
  const value = payload[key];
  return typeof value === "string" && value.trim() ? value : null;
}

function presentation(candidate: WritebackCandidate): { title: string; lines: string[]; boundary: string } {
  const payload = candidate.payload;
  if (candidate.candidateType === "observation_task") {
    return {
      title: "AI 整理的观察任务",
      lines: [text(payload, "title"), text(payload, "description")].filter((item): item is string => Boolean(item)),
      boundary: "确认前不会创建个人任务。",
    };
  }
  if (candidate.candidateType === "action_plan") {
    return {
      title: "AI 整理的操作计划草稿",
      lines: [text(payload, "trigger_text"), text(payload, "boundary")].filter((item): item is string => Boolean(item)),
      boundary: "确认前不会创建计划；AI 不填写目标价、仓位或收益承诺。",
    };
  }
  if (candidate.candidateType === "review_draft") {
    return {
      title: "AI 生成的交易复盘草稿",
      lines: [text(payload, "price_result"), text(payload, "logic_result"), text(payload, "improvement_text")].filter((item): item is string => Boolean(item)),
      boundary: "确认后仍只是可编辑草稿，最终复盘继续由你确认。",
    };
  }
  return {
    title: "AI 提出的判断草稿",
    lines: [text(payload, "current_reason_text"), text(payload, "reason_text")].filter((item): item is string => Boolean(item)),
    boundary: "确认前不会修改正式判断。",
  };
}

const statusLabels: Record<string, string> = {
  pending_confirmation: "等待你确认",
  confirmed: "已由你确认",
  rejected: "已拒绝，正式记录未改变",
  stale: "候选已失效，请基于最新记录重新生成",
};

export function WritebackCandidateCard({
  candidate,
  conflict,
  onConfirm,
  onReject,
}: {
  candidate: WritebackCandidate;
  conflict?: string | null;
  onConfirm: () => void;
  onReject: () => void;
}) {
  const view = presentation(candidate);
  const pending = candidate.status === "pending_confirmation";
  return (
    <article className={styles.writebackCard}>
      <div className={styles.evidenceHeader}>
        <strong>{view.title}</strong>
        <span>{candidate.symbol ?? "跨市场研究"}</span>
      </div>
      {view.lines.map((line) => <p key={line}>{line}</p>)}
      <small>{view.boundary}</small>
      <div className={styles.writebackStatus}>{conflict ?? statusLabels[candidate.status] ?? candidate.status}</div>
      {pending ? (
        <div className={styles.writebackActions}>
          <button onClick={onConfirm} type="button">确认写回</button>
          <button onClick={onReject} type="button">暂不采用</button>
        </div>
      ) : null}
    </article>
  );
}
