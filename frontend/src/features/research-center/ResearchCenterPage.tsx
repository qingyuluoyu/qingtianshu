import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { ModuleState } from "../../components/workbench/ModuleState";
import type {
  EvidenceTask,
  ResearchAction,
  ResearchActionGroup,
  ResearchOutcome,
} from "./adapters";
import { researchCenterQueries } from "./queries";
import styles from "./ResearchCenterPage.module.css";

function formatTime(value: string | null): string {
  if (!value) return "时间待确认";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

function formatPercent(value: number | null): string {
  if (value === null) return "--";
  if (value === 0) return "0.00%";
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function count(value: number | null | undefined): string {
  return value === null || value === undefined ? "--" : String(value);
}

function advisorHref(symbol: string | null, asOf?: string | null): string {
  const query = new URLSearchParams({ source: "research-center" });
  if (symbol) query.set("symbol", symbol);
  if (asOf) query.set("as_of", asOf);
  return `/advisor?${query.toString()}`;
}

function tone(status: string | null): string {
  if (["triggered", "failed", "risk_review", "attention"].includes(status ?? "")) return styles.toneRisk;
  if (["pending_data", "pending", "pending_external", "collecting", "notice"].includes(status ?? "")) return styles.toneWarning;
  if (["resolved", "completed", "available"].includes(status ?? "")) return styles.toneReady;
  return styles.toneNeutral;
}

function statusText(status: string | null): string {
  const labels: Record<string, string> = {
    attention: "需要关注",
    available: "可复核",
    baseline_missing: "待建立基线",
    collecting: "采集中",
    completed: "已完成",
    degraded: "部分完成",
    failed: "处理失败",
    guarded: "完成并已检查",
    notice: "需要留意",
    observe: "持续观察",
    pending: "待处理",
    pending_data: "待补证",
    pending_external: "等待外部资料",
    pending_review: "待复核",
    priority_research: "优先研究",
    resolved: "已解决",
    risk_review: "风险复核",
    triggered: "已触发",
    watching: "持续观察",
  };
  return status ? labels[status] ?? "状态待确认" : "状态待确认";
}

function outputCheckText(label: string | null): string {
  if (!label) return "回答检查状态待确认";
  return label.replace("守卫", "回答检查");
}

function ModuleCard({
  title,
  meta,
  loading,
  error,
  empty,
  emptyTitle,
  emptyDetail,
  onRetry,
  children,
}: {
  title: string;
  meta?: string | null;
  loading?: boolean;
  error?: boolean;
  empty?: boolean;
  emptyTitle?: string;
  emptyDetail?: string;
  onRetry?: () => void;
  children: ReactNode;
}) {
  return (
    <section className={styles.card}>
      <div className={styles.cardHeader}>
        <h2>{title}</h2>
        {meta ? <span>{meta}</span> : null}
      </div>
      {loading ? <ModuleState detail="正在读取个人研究状态。" state="loading" title="读取中" /> : null}
      {error ? <ModuleState detail="其他研究模块仍可继续使用。" onRetry={onRetry} state="error" title="该模块暂时不可用" /> : null}
      {!loading && !error && empty ? (
        <ModuleState detail={emptyDetail} state="empty" title={emptyTitle ?? "暂无记录"} />
      ) : null}
      {!loading && !error && !empty ? children : null}
    </section>
  );
}

function ActionRow({ group, action }: { group: ResearchActionGroup; action: ResearchAction }) {
  return (
    <article className={styles.actionItem}>
      <div className={styles.itemHead}>
        <div>
          <span className={`${styles.statusTag} ${tone(action.status)}`}>{statusText(action.status)}</span>
          <strong>{action.title}</strong>
        </div>
        <Link to={`/stocks/${encodeURIComponent(group.symbol)}`}>{group.name ?? group.symbol}</Link>
      </div>
      {action.currentEvidence ? <p>{action.currentEvidence}</p> : null}
      {action.nextStep ? <p className={styles.nextStep}>下一步：{action.nextStep}</p> : null}
    </article>
  );
}

function EvidenceTaskRow({ task }: { task: EvidenceTask }) {
  return (
    <article className={styles.taskItem}>
      <div className={styles.itemHead}>
        <div>
          <span className={`${styles.statusTag} ${tone(task.status)}`}>{task.statusLabel ?? statusText(task.status)}</span>
          <strong>{task.title}</strong>
        </div>
        <time dateTime={task.updatedAt ?? undefined}>{formatTime(task.updatedAt)}</time>
      </div>
      {task.description ? <p>{task.description}</p> : null}
      {task.resolutionNote ? <p className={styles.nextStep}>处理记录：{task.resolutionNote}</p> : null}
      <div className={styles.inlineLinks}>
        {task.symbol ? <Link to={`/stocks/${encodeURIComponent(task.symbol)}`}>查看个股研究</Link> : null}
        <Link to={advisorHref(task.symbol)}>继续向顾问核验</Link>
      </div>
    </article>
  );
}

function OutcomeRow({ symbol, name, outcome }: { symbol: string; name: string | null; outcome: ResearchOutcome }) {
  const value = outcome.resultStatus === "available" ? outcome.closeReturnPct : outcome.partialReturnPct;
  return (
    <article className={styles.outcomeItem}>
      <div className={styles.itemHead}>
        <div>
          <span className={`${styles.statusTag} ${tone(outcome.resultStatus)}`}>
            {outcome.resultStatus === "available" ? "已到期" : "观察中"}
          </span>
          <strong>{name ?? symbol} · T+{count(outcome.horizonSessions)}</strong>
        </div>
        <span className={value !== null && value < 0 ? styles.down : value !== null && value > 0 ? styles.up : styles.flat}>
          {formatPercent(value)}
        </span>
      </div>
      <p>{outcome.reviewConclusion ?? `已观察 ${count(outcome.observedSessions)} 个交易日。`}</p>
      <Link to={`/stocks/${encodeURIComponent(symbol)}`}>回到当前研究</Link>
    </article>
  );
}

export function ResearchCenterPage({ authenticated }: { authenticated: boolean }) {
  const priority = useQuery({ ...researchCenterQueries.priority(), enabled: authenticated });
  const changes = useQuery({ ...researchCenterQueries.changes(), enabled: authenticated });
  const actions = useQuery({ ...researchCenterQueries.actions(), enabled: authenticated });
  const evidenceTasks = useQuery({ ...researchCenterQueries.evidenceTasks(), enabled: authenticated });
  const outcomes = useQuery({ ...researchCenterQueries.outcomes(), enabled: authenticated });
  const runReviews = useQuery({ ...researchCenterQueries.runReviews(), enabled: authenticated });

  if (!authenticated) {
    return (
      <section className={styles.locked}>
        <h1>研究中心</h1>
        <ModuleState detail="登录后才能读取你的研究优先级、变化、行动、补证和复盘记录。" state="forbidden" title="登录后可使用研究中心" />
      </section>
    );
  }

  const actionRows = (actions.data?.items ?? []).flatMap((group) => group.actions.map((action) => ({ group, action })));
  const outcomeRows = (outcomes.data?.items ?? []).flatMap((group) => {
    if (group.latestAvailable.length > 0) return group.latestAvailable.map((outcome) => ({ group, outcome }));
    return group.latestProgress ? [{ group, outcome: group.latestProgress }] : [];
  });
  const fetching = [priority, changes, actions, evidenceTasks, outcomes, runReviews].some((query) => query.isFetching);

  const refreshAll = () => {
    void Promise.all([
      priority.refetch(),
      changes.refetch(),
      actions.refetch(),
      evidenceTasks.refetch(),
      outcomes.refetch(),
      runReviews.refetch(),
    ]);
  };

  return (
    <div className={styles.page}>
      <header className={styles.pageHeader}>
        <div>
          <span className={styles.eyebrow}>有来源的个人研究工作流</span>
          <h1>研究中心</h1>
          <p>把“过去判断—发生变化—当前行动—补证进度—结果复盘”放在同一页；这里组织研究，不替你生成正式结论。</p>
        </div>
        <button disabled={fetching} onClick={refreshAll} type="button">{fetching ? "正在刷新…" : "刷新研究状态"}</button>
      </header>

      <section aria-label="研究中心概览" className={styles.summaryGrid}>
        <article><span>关注标的</span><strong>{count(priority.data?.coverage.requested)}</strong><small>来自真实关注关系</small></article>
        <article><span>优先处理</span><strong>{count(actions.data?.summary.priorityResearch)}</strong><small>按复核紧迫度</small></article>
        <article><span>已触发行动</span><strong>{count(actions.data?.summary.triggered)}</strong><small>不是交易信号</small></article>
        <article><span>补证任务</span><strong>{count(evidenceTasks.data?.summary.total)}</strong><small>含等待外部资料</small></article>
        <article><span>到期复盘</span><strong>{count(outcomes.data?.coverage.availableOutcomes)}</strong><small>T+3 / T+5 / T+10</small></article>
        <article><span>近 30 日 Run</span><strong>{count(runReviews.data?.summary.total)}</strong><small>只含正式对话</small></article>
      </section>

      <div className={styles.topGrid}>
        <ModuleCard
          empty={priority.data?.items.length === 0}
          emptyDetail="先从透明选股或全局搜索进入个股研究，再明确加入关注。"
          emptyTitle="还没有需要排序的关注标的"
          error={priority.isError}
          loading={priority.isLoading}
          meta={priority.data?.generatedAt ? `生成 ${formatTime(priority.data.generatedAt)}` : null}
          onRetry={() => { void priority.refetch(); }}
          title="优先处理"
        >
          <div className={styles.priorityList}>
            {priority.data?.items.slice(0, 8).map((item) => (
              <article key={item.symbol}>
                <div className={styles.itemHead}>
                  <div>
                    <span className={`${styles.statusTag} ${tone(item.status)}`}>{item.priorityLabel ?? statusText(item.status)}</span>
                    <strong>{item.name ?? item.symbol}</strong>
                  </div>
                  <span className={styles.score}>复核紧迫度 {count(item.priorityScore)}</span>
                </div>
                <p>{item.reasons[0] ?? item.nextReviewFocus ?? "当前没有显著变化，继续按既定证据复核。"}</p>
                <div className={styles.inlineLinks}>
                  <Link to={`/stocks/${encodeURIComponent(item.symbol)}`}>查看个股研究</Link>
                  <Link to={advisorHref(item.symbol, item.dataAsOf)}>问顾问</Link>
                </div>
              </article>
            ))}
          </div>
          {priority.data?.sorting ? <p className={styles.boundary}>{priority.data.sorting}</p> : null}
        </ModuleCard>

        <ModuleCard
          empty={actionRows.length === 0}
          emptyDetail="当关注标的存在研究基线或证据缺口时，系统会在这里给出可追溯的核验动作。"
          emptyTitle="暂无研究行动"
          error={actions.isError}
          loading={actions.isLoading}
          meta={actions.data?.generatedAt ? `生成 ${formatTime(actions.data.generatedAt)}` : null}
          onRetry={() => { void actions.refetch(); }}
          title="当前行动"
        >
          <div className={styles.actionList}>
            {actionRows.slice(0, 10).map(({ group, action }) => <ActionRow action={action} group={group} key={`${group.symbol}-${action.id}`} />)}
          </div>
          {actions.data?.boundary ? <p className={styles.boundary}>{actions.data.boundary}</p> : null}
        </ModuleCard>
      </div>

      <div className={styles.mainGrid}>
        <ModuleCard
          empty={changes.data?.events.length === 0}
          emptyDetail="没有变化档案不等于没有风险，只表示当前没有可回读的连续报告变化记录。"
          emptyTitle="暂无可追溯变化"
          error={changes.isError}
          loading={changes.isLoading}
          meta={changes.data ? `${count(changes.data.coverage.withChangeArchive)}/${count(changes.data.coverage.requested)} 有变化档案` : null}
          onRetry={() => { void changes.refetch(); }}
          title="研究变化"
        >
          <div className={styles.timeline}>
            {changes.data?.events.slice(0, 12).map((event) => (
              <article key={event.id}>
                <span className={`${styles.timelineDot} ${tone(event.severity)}`} />
                <div>
                  <div className={styles.itemHead}>
                    <Link to={`/stocks/${encodeURIComponent(event.symbol)}`}>{event.symbol}</Link>
                    <time dateTime={event.createdAt ?? undefined}>{formatTime(event.createdAt)}</time>
                  </div>
                  <strong>{event.summary}</strong>
                  {event.nextReviewFocus ? <p>下一次复核：{event.nextReviewFocus}</p> : null}
                </div>
              </article>
            ))}
          </div>
          {changes.data?.boundary ? <p className={styles.boundary}>{changes.data.boundary}</p> : null}
        </ModuleCard>

        <div className={styles.sideColumn}>
          <ModuleCard
            empty={evidenceTasks.data?.items.length === 0}
            emptyDetail="当前没有由正式研究对话产生的资料缺口任务。"
            emptyTitle="暂无补证任务"
            error={evidenceTasks.isError}
            loading={evidenceTasks.isLoading}
            meta={evidenceTasks.data?.generatedAt ? `更新 ${formatTime(evidenceTasks.data.generatedAt)}` : null}
            onRetry={() => { void evidenceTasks.refetch(); }}
            title="补证任务"
          >
            <div className={styles.taskList}>
              {evidenceTasks.data?.items.slice(0, 8).map((task) => <EvidenceTaskRow key={task.id} task={task} />)}
            </div>
            {evidenceTasks.data?.boundary ? <p className={styles.boundary}>{evidenceTasks.data.boundary}</p> : null}
          </ModuleCard>

          <ModuleCard
            empty={outcomeRows.length === 0}
            emptyDetail="尚无到期或进行中的研究条件复盘；页面不会用示例收益填充。"
            emptyTitle="暂无研究结果"
            error={outcomes.isError}
            loading={outcomes.isLoading}
            meta={outcomes.data ? `可用 ${count(outcomes.data.coverage.availableOutcomes)} · 进行中 ${count(outcomes.data.coverage.pendingOutcomes)}` : null}
            onRetry={() => { void outcomes.refetch(); }}
            title="研究结果复盘"
          >
            <div className={styles.outcomeList}>
              {outcomeRows.slice(0, 9).map(({ group, outcome }) => (
                <OutcomeRow key={`${group.symbol}-${outcome.id}`} name={group.name} outcome={outcome} symbol={group.symbol} />
              ))}
            </div>
            {outcomes.data?.boundary ? <p className={styles.boundary}>{outcomes.data.boundary}</p> : null}
          </ModuleCard>
        </div>
      </div>

      <ModuleCard
        empty={runReviews.data?.items.length === 0}
        emptyDetail="在金融顾问完成一次正式研究对话后，这里会出现可回读的 Run 复盘。"
        emptyTitle="近 30 日暂无正式 Run"
        error={runReviews.isError}
        loading={runReviews.isLoading}
        meta={runReviews.data ? `共 ${count(runReviews.data.summary.total)} 条 · 修复 ${count(runReviews.data.summary.repaired)} 条` : null}
        onRetry={() => { void runReviews.refetch(); }}
        title="回答与证据复盘"
      >
        <div className={styles.runGrid}>
          {runReviews.data?.items.slice(0, 12).map((run) => (
            <article key={run.id}>
              <div className={styles.itemHead}>
                <div>
                  <span className={`${styles.statusTag} ${tone(run.status)}`}>{run.statusLabel ?? statusText(run.status)}</span>
                  <strong>{run.intentLabel ?? "综合研究"}</strong>
                </div>
                <time dateTime={run.createdAt ?? undefined}>{formatTime(run.createdAt)}</time>
              </div>
              <p className={styles.question}>{run.question}</p>
              {run.answerExcerpt ? <p>{run.answerExcerpt}</p> : null}
              <div className={styles.runMeta}>
                <span>{outputCheckText(run.guardLabel)}</span>
                <span>证据模块 {count(run.readyModules)}/{count(run.totalModules)}</span>
                <span>{run.durationSeconds === null ? "耗时待确认" : `${run.durationSeconds.toFixed(2)}s`}</span>
              </div>
              <Link to={run.conversationId ? `/advisor/${encodeURIComponent(run.conversationId)}` : advisorHref(run.symbol)}>打开原对话</Link>
            </article>
          ))}
        </div>
      </ModuleCard>

      <footer className={styles.footer}>
        研究中心展示的是已持久化研究状态、证据缺口和历史复盘；优先级不是投资排名，历史变化不是荐股收益，任何正式判断仍需你明确确认。
      </footer>
    </div>
  );
}
