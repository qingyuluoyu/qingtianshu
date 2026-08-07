import { useMemo, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import type {
  ChangeEvent,
  OutcomeAnchor,
  ResearchActionItem,
  ResearchChanges,
  ResearchOutcomes,
  TradeReview,
  TradeReviewCenter,
  WorkspaceTimeline,
} from "./adapters";
import { archiveTradeReview, confirmTradeReview, ResearchCenterApiError } from "./api";
import { researchCenterQueries, researchCenterQueryKeys } from "./queries";
import styles from "./ResearchCenterPage.module.css";

type Props = { authenticated: boolean };

// ---------- 格式化助手（直通原则：百分数不缩放） ----------

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "时间待确认";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "时间待确认";
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

function formatNumber(value: number | null, digits = 2): string {
  if (value === null) return "--";
  return new Intl.NumberFormat("zh-CN", { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(value);
}

/** *_pct 后端已是百分数，直通加 % 不缩放。 */
function percent(value: number | null): string {
  if (value === null) return "--";
  return `${value > 0 ? "+" : ""}${formatNumber(value)}%`;
}

function tone(value: number | null): string {
  if (value === null || value === 0) return styles.flat;
  return value > 0 ? styles.up : styles.down;
}

// ---------- 状态翻译（合同 §6.3，只翻译后端状态，不自行推断） ----------

function statusLabel(status: string): string {
  return ({
    available: "数据完整",
    ready: "数据完整",
    fresh: "数据完整",
    sufficient: "证据充分",
    partial: "部分数据可用",
    insufficient: "数据不足",
    missing: "数据缺失",
    unavailable: "当前不可用",
    draft: "待确认草稿",
    pending_confirmation: "待确认草稿",
    waiting_data: "等待数据",
    pending: "待形成",
    confirmed: "已确认",
    archived: "已归档",
    stale: "内容已过期",
    ended: "已结束",
    paused: "已暂停",
    empty: "暂无数据",
    preview: "预览快照",
    active: "进行中",
    completed: "已完成",
  } as Record<string, string>)[status] ?? status;
}

function statusTone(status: string): string {
  if (["available", "ready", "fresh", "sufficient", "confirmed", "completed", "active"].includes(status)) return styles.badgeReady;
  if (["partial", "insufficient", "missing"].includes(status)) return styles.badgePartial;
  if (["draft", "pending_confirmation", "waiting_data", "pending"].includes(status)) return styles.badgeWaiting;
  if (status === "stale") return styles.badgeStale;
  return styles.badgeUnavailable;
}

function severityLabel(severity: string | null): string {
  return ({ notice: "提示", medium: "中等", high: "高", low: "低" } as Record<string, string>)[severity ?? ""] ?? severity ?? "提示";
}

// ---------- 通用卡片 ----------

function ModuleCard({ title, meta, pending, error, onRetry, children }: {
  title: string;
  meta?: ReactNode;
  pending?: boolean;
  error?: boolean;
  onRetry?: () => void;
  children: ReactNode;
}) {
  return (
    <section className={styles.card} aria-label={title}>
      <div className={styles.cardHeader}>
        <h2>{title}</h2>
        {meta ? <div className={styles.meta}>{meta}</div> : null}
      </div>
      {pending ? <div className={styles.skeleton} aria-live="polite">正在读取…</div> : null}
      {!pending && error ? (
        <div className={styles.moduleError} role="status">
          <span>本模块暂时不可用，其他内容仍可继续查看。</span>
          {onRetry ? <button type="button" onClick={onRetry}>重新读取</button> : null}
        </div>
      ) : null}
      {!pending && !error ? children : null}
    </section>
  );
}

// ---------- 概览卡（ResearchReviewSummary）：计数全部来自真实聚合 ----------

const FOCUS_FILTERS = [
  { key: "all", label: "全部" },
  { key: "reviews", label: "待复盘" },
  { key: "changed", label: "判断有变化" },
  { key: "outcomes", label: "已有结果" },
] as const;

type FocusKey = (typeof FOCUS_FILTERS)[number]["key"];

function ResearchReviewSummary({ changes, outcomes, tradeReviews, active, onSelect }: {
  changes: ResearchChanges | null;
  outcomes: ResearchOutcomes | null;
  tradeReviews: TradeReviewCenter | null;
  active: FocusKey;
  onSelect: (focus: FocusKey) => void;
}) {
  const availableResults = outcomes?.items.reduce((sum, item) => sum + (item.coverage.available ?? 0), 0) ?? null;
  const pendingResults = outcomes?.items.reduce((sum, item) => sum + (item.coverage.pending ?? 0), 0) ?? null;
  const cards: { key: FocusKey; label: string; value: string; hint: string }[] = [
    {
      key: "reviews",
      label: "待复盘",
      // 真实聚合：复盘中心 actionable = 可复盘（ready）+ 待确认草稿（draft）。
      value: tradeReviews ? String(tradeReviews.summary.actionable ?? "--") : "--",
      hint: "可复盘与待确认草稿（交易复盘中心）",
    },
    {
      key: "changed",
      label: "判断有变化",
      value: changes ? String(changes.coverage.withChangeArchive ?? "--") : "--",
      hint: changes ? `共跟踪 ${changes.coverage.requested ?? "--"} 只 · ${changes.coverage.withReport ?? "--"} 只有快照` : "变化档案待读取",
    },
    {
      key: "outcomes",
      label: "已有结果",
      value: availableResults === null ? "--" : String(availableResults),
      hint: pendingResults === null ? "结果锚点待读取" : `另有 ${pendingResults} 个锚点待形成`,
    },
  ];
  return (
    <div className={styles.summaryGrid} role="group" aria-label="研究复盘概览">
      {cards.map((card) => (
        <button
          aria-pressed={active === card.key}
          className={styles.summaryCard}
          key={card.key}
          onClick={() => onSelect(active === card.key ? "all" : card.key)}
          type="button"
        >
          <span>{card.label}</span>
          <strong>{card.value}</strong>
          <small>{card.hint}</small>
        </button>
      ))}
    </div>
  );
}

// ---------- 左侧股票列表（ReviewStockList） ----------

type StockEntry = {
  symbol: string;
  name: string | null;
  latestChangeAt: string | null;
  latestChangeSummary: string | null;
  hasChange: boolean;
  availableOutcomes: number;
  tradeReviewCount: number;
};

function ReviewStockList({ items, selectedSymbol, onSelect }: {
  items: StockEntry[];
  selectedSymbol: string | null;
  onSelect: (symbol: string) => void;
}) {
  return (
    <div className={styles.stockList} role="listbox" aria-label="研究股票列表">
      {items.map((item) => (
        <button
          aria-selected={selectedSymbol === item.symbol}
          className={styles.stockItem}
          key={item.symbol}
          onClick={() => onSelect(item.symbol)}
          role="option"
          type="button"
        >
          <strong>{item.name ?? "名称待确认"}</strong>
          <span className={styles.code}>{item.symbol}</span>
          <small>
            {item.latestChangeSummary
              ? `变化 ${formatDateTime(item.latestChangeAt)}`
              : item.availableOutcomes > 0
                ? `${item.availableOutcomes} 个已到期结果`
                : "暂无新变化"}
          </small>
        </button>
      ))}
    </div>
  );
}

// ---------- 中央：判断-变化-处理链（DecisionChangeTimeline） ----------

function ChangeEventRow({ change }: { change: ChangeEvent }) {
  return (
    <article>
      <div className={styles.itemHead}>
        <strong>{change.eventType ?? "变化记录"}</strong>
        <span className={`${styles.tag} ${change.severity === "high" ? styles.tagRisk : styles.tagNeutral}`}>
          {severityLabel(change.severity)}
        </span>
      </div>
      <p>{change.summary ?? "有变化记录"}</p>
      <small>
        记录时间：{formatDateTime(change.createdAt)}
        {change.dataAsOf ? ` · 数据时间：${formatDateTime(change.dataAsOf)}` : ""}
      </small>
      {change.nextReview?.focus ? <small>下一步观察：{change.nextReview.focus}</small> : null}
    </article>
  );
}

function DecisionChangeTimeline({ timeline }: { timeline: WorkspaceTimeline }) {
  const changes = [...timeline.importantChanges]
    .sort((a, b) => (b.createdAt ?? "").localeCompare(a.createdAt ?? ""));
  const theses = [...timeline.thesisHistory]
    .sort((a, b) => (b.versionNo ?? 0) - (a.versionNo ?? 0));
  return (
    <>
      <h3 className={styles.sectionTitle}>判断</h3>
      {theses.length === 0 ? (
        <p className={styles.statement}>尚未保存当前判断。系统不会替你生成结论，可以从个股研究页或问顾问开始。</p>
      ) : (
        <div className={styles.itemList}>
          {theses.map((thesis) => (
            <article key={thesis.id ?? `thesis-${thesis.versionNo ?? "x"}`}>
              <div className={styles.itemHead}>
                <strong>判断版本 {thesis.versionNo ?? "--"}</strong>
                <span className={`${styles.badge} ${statusTone(thesis.status ?? "unavailable")}`}>
                  {statusLabel(thesis.status ?? "unavailable")}
                </span>
              </div>
              <p>{thesis.reasonText ?? "内容待确认"}</p>
              <small>
                创建：{formatDateTime(thesis.createdAt)}
                {thesis.confirmedAt ? ` · 确认：${formatDateTime(thesis.confirmedAt)}` : ""}
              </small>
            </article>
          ))}
        </div>
      )}
      <h3 className={styles.sectionTitle}>变化（{timeline.historySummary.changeCount ?? changes.length}）</h3>
      {changes.length === 0 ? (
        <div className={styles.empty}>暂无变化档案记录</div>
      ) : (
        <div className={styles.itemList}>
          {changes.map((change, index) => <ChangeEventRow change={change} key={change.id ?? `change-${index}`} />)}
        </div>
      )}
      <h3 className={styles.sectionTitle}>处理</h3>
      {timeline.observationTasks.items.length === 0 && (timeline.tradeReviewSummary.total ?? 0) === 0 ? (
        <p className={styles.statement}>暂无观察任务或交易复盘记录。判断与变化保留在上方档案中。</p>
      ) : (
        <div className={styles.itemList}>
          {timeline.observationTasks.items.map((task) => (
            <article key={task.id ?? task.title ?? "task"}>
              <div className={styles.itemHead}>
                <strong>{task.title ?? "观察任务"}</strong>
                <span className={`${styles.badge} ${statusTone(task.status ?? "unavailable")}`}>
                  {statusLabel(task.status ?? "unavailable")}
                </span>
              </div>
              {task.description ? <p>{task.description}</p> : null}
              <small>更新：{formatDateTime(task.updatedAt)}{task.version !== null ? ` · 版本 ${task.version}` : ""}</small>
            </article>
          ))}
          {(timeline.tradeReviewSummary.total ?? 0) > 0 ? (
            <article>
              <div className={styles.itemHead}>
                <strong>交易复盘</strong>
                <span className={`${styles.tag} ${styles.tagNeutral}`}>{timeline.tradeReviewSummary.total ?? "--"} 项</span>
              </div>
              <small>
                等待数据 {timeline.tradeReviewSummary.waitingData ?? "--"} · 待确认草稿 {timeline.tradeReviewSummary.needsConfirmation ?? "--"}（明细见右下复盘中心）
              </small>
            </article>
          ) : null}
        </div>
      )}
    </>
  );
}

// ---------- 右侧：下一步（ReviewActions） ----------

function ReviewActions({ symbol, actionItem }: { symbol: string; actionItem: ResearchActionItem | null }) {
  const triggered = actionItem?.actions.filter((action) => action.status === "triggered") ?? [];
  const advisorQuery = `?symbol=${encodeURIComponent(symbol)}&source=research-center`;
  return (
    <>
      {actionItem ? (
        <>
          <div className={styles.itemHead}>
            <span className={`${styles.badge} ${statusTone(actionItem.researchStatus ?? "unavailable")}`}>
              {actionItem.researchStatusLabel ?? statusLabel(actionItem.researchStatus ?? "unavailable")}
            </span>
            {actionItem.dataAsOf ? <span className={styles.meta}>数据时间：{formatDateTime(actionItem.dataAsOf)}</span> : null}
          </div>
          {actionItem.headline ? <p className={styles.statement} style={{ marginTop: 10 }}>{actionItem.headline}</p> : null}
          {triggered.length > 0 ? (
            <div className={styles.itemList} style={{ marginTop: 8 }}>
              {triggered.map((action) => (
                <article key={action.id ?? action.key ?? action.title ?? "action"}>
                  <div className={styles.itemHead}>
                    <strong>{action.title ?? "复核事项"}</strong>
                    <span className={`${styles.tag} ${styles.tagNeutral}`}>{severityLabel(action.severity)}</span>
                  </div>
                  {action.currentEvidence ? <p>{action.currentEvidence}</p> : null}
                  {action.nextStep ? <small>下一步：{action.nextStep}</small> : null}
                </article>
              ))}
            </div>
          ) : (
            <p className={styles.statement} style={{ marginTop: 10 }}>当前没有已触发的复核事项。</p>
          )}
        </>
      ) : (
        <p className={styles.statement}>该股票暂无行动看板数据。</p>
      )}
      <h3 className={styles.sectionTitle}>维持判断 / 继续观察 / 已复盘</h3>
      <p className={styles.helper} style={{ marginTop: 0 }}>
        当前后端没有记录「维持判断、继续观察、已复盘」的接口，这里只提供说明与跳转，不会显示为已保存。
        研究层面的处理请通过个股研究或顾问完成；交易层面的复盘以右下「交易复盘中心」的真实状态机为准。
      </p>
      <div className={styles.actionRow}>
        <Link className={styles.actionLink} to={`/stocks/${encodeURIComponent(symbol)}`}>进入个股研究</Link>
        <Link className={styles.actionLink} to={`/advisor${advisorQuery}`}>问顾问</Link>
      </div>
    </>
  );
}

// ---------- 报告变化（ReportDiff） ----------

function ReportDiff({ change }: { change: ChangeEvent | null }) {
  if (!change) {
    return <div className={styles.empty}>最新研究快照没有记录维度变化</div>;
  }
  return (
    <>
      {change.changes.length > 0 ? (
        <div>
          {change.changes.map((diff, index) => (
            <div className={styles.diffRow} key={`${diff.label ?? "diff"}-${index}`}>
              <strong>{diff.label ?? diff.dimension ?? "变化维度"}</strong>
              <p>
                {diff.before ? <span className={styles.diffBefore}>{diff.before} → </span> : null}
                {diff.after ?? diff.detail ?? "变化详情待确认"}
              </p>
            </div>
          ))}
        </div>
      ) : (
        <p className={styles.statement}>{change.summary ?? "有变化记录"}</p>
      )}
      {change.newEvidence.length > 0 ? (
        <>
          <h3 className={styles.sectionTitle}>新增证据</h3>
          <div className={styles.itemList}>
            {change.newEvidence.map((evidence, index) => (
              <article key={`${evidence.title ?? "evidence"}-${index}`}>
                <div className={styles.itemHead}>
                  <strong>{evidence.title ?? "证据"}</strong>
                  <span className={`${styles.tag} ${styles.tagNeutral}`}>{evidence.categoryLabel ?? "证据"}</span>
                </div>
                <small>公告发布时间：{formatDateTime(evidence.publishedAt)}</small>
              </article>
            ))}
          </div>
        </>
      ) : null}
      {change.boundary ? <p className={styles.boundaryNote}>{change.boundary}</p> : null}
    </>
  );
}

// ---------- 进度（ResearchProgress）：进行中的结果观察 ----------

function ResearchProgress({ progress }: { progress: OutcomeAnchor | null }) {
  if (!progress) {
    return <div className={styles.empty}>当前没有进行中的结果观察</div>;
  }
  const total = progress.horizonSessions ?? 0;
  const observed = progress.observedSessions ?? 0;
  const ratio = total > 0 ? Math.min(1, observed / total) : 0;
  return (
    <>
      <div className={styles.itemHead}>
        <strong>{progress.originalOutlookLabel ?? "研究快照"}</strong>
        <span className={`${styles.badge} ${statusTone(progress.resultStatus ?? "pending")}`}>
          {statusLabel(progress.resultStatus ?? "pending")}
        </span>
      </div>
      <div className={styles.progressBar} role="img" aria-label={`已观察 ${observed} / ${total} 个交易日`}>
        <svg className={styles.progressTrack} viewBox="0 0 100 10" preserveAspectRatio="none" aria-hidden="true">
          <rect x="0" y="0" width="100" height="10" rx="5" fill="#edf1f6" />
          <rect x="0" y="0" width={ratio * 100} height="10" rx="5" fill="#2f6bff" />
        </svg>
      </div>
      <div className={styles.progressMeta}>
        <span>交易日窗口：{progress.protocol?.horizon ?? `T+${total}`} · 已观察 {observed} / {total}</span>
        <span>阶段收益：<span className={tone(progress.partialReturnPct)}>{percent(progress.partialReturnPct)}</span>（直通）</span>
        <span>进度时间：{formatDateTime(progress.progressTimestamp)}</span>
      </div>
      {progress.reviewConclusion ? <p className={styles.helper}>{progress.reviewConclusion}</p> : null}
    </>
  );
}

// ---------- 历史结果（OutcomeCards）：锚点 / 交易日窗口 / 基准 / 数据可得时间 ----------

function OutcomeCard({ anchor, name }: { anchor: OutcomeAnchor; name: string | null }) {
  return (
    <article>
      <div className={styles.itemHead}>
        <strong>{name ?? "结果"}</strong>
        <span className={`${styles.badge} ${statusTone(anchor.resultStatus ?? "unavailable")}`}>
          {anchor.scenarioLabel ?? statusLabel(anchor.resultStatus ?? "unavailable")}
        </span>
      </div>
      <div className={styles.metricGrid} style={{ marginTop: 10 }}>
        <div className={styles.metric}>
          <span>结果锚点（OutcomeAnchor）</span>
          <strong>{anchor.anchorClose === null ? "--" : formatNumber(anchor.anchorClose)}</strong>
          <small>{anchor.protocol?.anchor ?? "锚点口径待确认"} · {formatDateTime(anchor.anchorTimestamp)}</small>
        </div>
        <div className={styles.metric}>
          <span>交易日窗口</span>
          <strong>{anchor.horizonSessions === null ? "--" : `T+${anchor.horizonSessions}`}</strong>
          <small>
            {anchor.protocol?.horizon ?? "窗口口径待确认"}
            {anchor.targetTimestamp ? ` · 到期 ${formatDateTime(anchor.targetTimestamp)}` : " · 尚未到期"}
          </small>
        </div>
        <div className={styles.metric}>
          <span>窗口收益</span>
          <strong className={tone(anchor.closeReturnPct)}>{percent(anchor.closeReturnPct)}</strong>
          <small>
            最大上行 {percent(anchor.maximumFavorableExcursionPct)} · 最大下行 {percent(anchor.maximumAdverseExcursionPct)}（仅描述路径）
          </small>
        </div>
        <div className={styles.metric}>
          <span>基准与数据可得时间</span>
          <strong style={{ fontSize: 12 }}>{anchor.protocol?.priceSeries ?? "基准口径待确认"}</strong>
          <small>数据可得：{formatDateTime(anchor.dataAsOf)} · 计算：{formatDateTime(anchor.calculatedAt)}</small>
        </div>
      </div>
      {anchor.reviewConclusion ? <p className={styles.helper}>{anchor.reviewConclusion}</p> : null}
      {anchor.boundary ? <p className={styles.boundaryNote}>{anchor.boundary}</p> : null}
    </article>
  );
}

// ---------- 交易复盘中心（真实状态机：confirm / archive，base_version + 409） ----------

type MutationNotice = { kind: "success" | "conflict" | "failed"; text: string } | null;

function TradeReviewCenterSection({ center, pendingId, onTransition }: {
  center: TradeReviewCenter;
  pendingId: string | null;
  onTransition: (review: TradeReview, action: "confirm" | "archive") => void;
}) {
  if (center.items.length === 0) {
    return (
      <>
        <div className={styles.empty}>
          <span>暂无交易复盘记录。</span>
          <span>复盘由真实交易操作触发；没有记录时不展示任何示例复盘。</span>
        </div>
        {center.boundary ? <p className={styles.boundaryNote}>{center.boundary}</p> : null}
      </>
    );
  }
  return (
    <div className={styles.itemList}>
      {center.items.map((review) => {
        const versionNo = review.currentVersion?.versionNo ?? null;
        const rowPending = pendingId === review.id;
        const canConfirm = review.status === "draft" && review.canConfirm === true && versionNo !== null;
        const canArchive = review.status === "confirmed" && versionNo !== null;
        return (
          <article key={review.id}>
            <div className={styles.itemHead}>
              <strong>{review.name ?? review.symbol ?? "交易复盘"}</strong>
              <span className={`${styles.badge} ${statusTone(review.status ?? "unavailable")}`}>
                {statusLabel(review.status ?? "unavailable")}
              </span>
            </div>
            {review.operation ? (
              <p>
                {review.operation.operationType ?? "操作"} · 价格 {review.operation.price === null ? "--" : formatNumber(review.operation.price)}
                {review.operation.reasonText ? ` · ${review.operation.reasonText}` : ""}
              </p>
            ) : null}
            {review.priceObservation?.summary ? <p>{review.priceObservation.summary}</p> : null}
            {review.currentVersion?.logicResult ? <p>{review.currentVersion.logicResult}</p> : null}
            <small>
              操作时间：{formatDateTime(review.operation?.operatedAt)}
              {versionNo !== null ? ` · 草稿版本 ${versionNo}` : " · 草稿版本待确认"}
              {review.currentVersion?.createdSource ? ` · 来源：${review.currentVersion.createdSource === "ai" ? "AI 草稿" : "用户草稿"}` : ""}
              {review.confirmedAt ? ` · 确认：${formatDateTime(review.confirmedAt)}` : ""}
              {review.archivedAt ? ` · 归档：${formatDateTime(review.archivedAt)}` : ""}
            </small>
            {canConfirm || canArchive ? (
              <div className={styles.actionRow}>
                {canConfirm ? (
                  <button
                    className={styles.writeButton}
                    disabled={rowPending}
                    onClick={() => onTransition(review, "confirm")}
                    type="button"
                  >
                    {rowPending ? "写入中…" : "确认复盘"}
                  </button>
                ) : null}
                {canArchive ? (
                  <button
                    className={`${styles.writeButton} ${styles.writeButtonSecondary}`}
                    disabled={rowPending}
                    onClick={() => onTransition(review, "archive")}
                    type="button"
                  >
                    {rowPending ? "写入中…" : "归档复盘"}
                  </button>
                ) : null}
              </div>
            ) : null}
          </article>
        );
      })}
    </div>
  );
}

// ---------- 页面 ----------

export function ResearchCenterPage({ authenticated }: Props) {
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const focusParam = searchParams.get("focus");
  const focus: FocusKey = FOCUS_FILTERS.some((item) => item.key === focusParam) ? (focusParam as FocusKey) : "all";

  const changesQuery = useQuery({ ...researchCenterQueries.changes(), enabled: authenticated });
  const outcomesQuery = useQuery({ ...researchCenterQueries.outcomes(), enabled: authenticated });
  const actionsQuery = useQuery({ ...researchCenterQueries.actions(), enabled: authenticated });
  const tradeReviewsQuery = useQuery({ ...researchCenterQueries.tradeReviews(), enabled: authenticated });

  const changes = changesQuery.data ?? null;
  const outcomes = outcomesQuery.data ?? null;
  const actions = actionsQuery.data ?? null;
  const tradeReviews = tradeReviewsQuery.data ?? null;

  const [notice, setNotice] = useState<MutationNotice>(null);

  const mutation = useMutation({
    mutationFn: ({ reviewId, baseVersion, action }: { reviewId: string; baseVersion: number; action: "confirm" | "archive" }) =>
      action === "confirm" ? confirmTradeReview(reviewId, baseVersion) : archiveTradeReview(reviewId, baseVersion),
    onSuccess: (_data, variables) => {
      setNotice({
        kind: "success",
        text: variables.action === "confirm"
          ? "复盘已确认并落库为正式复盘（可恢复查看）。"
          : "复盘已归档，历史记录仍可查看。",
      });
      void queryClient.invalidateQueries({ queryKey: researchCenterQueryKeys.tradeReviews() });
      if (selectedSymbol) void queryClient.invalidateQueries({ queryKey: researchCenterQueryKeys.timeline(selectedSymbol) });
    },
    onError: (error) => {
      if (error instanceof ResearchCenterApiError && error.status === 409) {
        // 409：不覆盖最新版本，刷新复盘中心取回新 base_version 后由用户重新确认。
        setNotice({ kind: "conflict", text: error.message });
        void queryClient.invalidateQueries({ queryKey: researchCenterQueryKeys.tradeReviews() });
        return;
      }
      setNotice({ kind: "failed", text: `写入失败：${error instanceof Error ? error.message : "数据暂时不可用"}。未做任何本地改动，请重试。` });
    },
  });

  // 股票列表：以判断/变化链为主，补齐只在结果里出现的股票（不做逐股补请求，§8.4）。
  const stockEntries = useMemo<StockEntry[]>(() => {
    const entries = new Map<string, StockEntry>();
    for (const item of changes?.items ?? []) {
      entries.set(item.symbol, {
        symbol: item.symbol,
        name: item.name,
        latestChangeAt: item.latestChange?.createdAt ?? null,
        latestChangeSummary: item.latestChange?.summary ?? null,
        hasChange: item.latestChange !== null,
        availableOutcomes: 0,
        tradeReviewCount: 0,
      });
    }
    for (const item of outcomes?.items ?? []) {
      const entry = entries.get(item.symbol) ?? {
        symbol: item.symbol,
        name: item.name,
        latestChangeAt: null,
        latestChangeSummary: null,
        hasChange: false,
        availableOutcomes: 0,
        tradeReviewCount: 0,
      };
      entry.availableOutcomes = item.coverage.available ?? 0;
      entry.name = entry.name ?? item.name;
      entries.set(item.symbol, entry);
    }
    for (const review of tradeReviews?.items ?? []) {
      if (!review.symbol) continue;
      const entry = entries.get(review.symbol);
      if (entry) entry.tradeReviewCount += 1;
    }
    return [...entries.values()];
  }, [changes, outcomes, tradeReviews]);

  const filteredEntries = useMemo(() => {
    if (focus === "changed") return stockEntries.filter((entry) => entry.hasChange);
    if (focus === "outcomes") return stockEntries.filter((entry) => entry.availableOutcomes > 0);
    if (focus === "reviews") return stockEntries.filter((entry) => entry.tradeReviewCount > 0);
    return stockEntries;
  }, [stockEntries, focus]);

  const symbolParam = searchParams.get("symbol");
  const selectedSymbol = symbolParam && stockEntries.some((entry) => entry.symbol === symbolParam)
    ? symbolParam
    : filteredEntries[0]?.symbol ?? stockEntries[0]?.symbol ?? null;

  const timelineQuery = useQuery({ ...researchCenterQueries.timeline(selectedSymbol ?? ""), enabled: authenticated && selectedSymbol !== null });
  const reportQuery = useQuery({ ...researchCenterQueries.report(selectedSymbol ?? ""), enabled: authenticated && selectedSymbol !== null });

  const selectedChangeItem = changes?.items.find((item) => item.symbol === selectedSymbol) ?? null;
  const selectedOutcomeItem = outcomes?.items.find((item) => item.symbol === selectedSymbol) ?? null;
  const selectedActionItem = actions?.items.find((item) => item.symbol === selectedSymbol) ?? null;
  const report = reportQuery.data ?? null;

  const updateParams = (updates: Record<string, string | null>) => {
    const next = new URLSearchParams(searchParams);
    for (const [key, value] of Object.entries(updates)) {
      if (value === null) next.delete(key);
      else next.set(key, value);
    }
    setSearchParams(next);
  };

  const handleTransition = (review: TradeReview, action: "confirm" | "archive") => {
    setNotice(null);
    const baseVersion = review.currentVersion?.versionNo ?? null;
    if (baseVersion === null) {
      setNotice({ kind: "failed", text: "复盘草稿版本缺失，无法安全写入。" });
      return;
    }
    mutation.mutate({ reviewId: review.id, baseVersion, action });
  };

  if (!authenticated) {
    return (
      <div className={styles.page}>
        <header className={styles.header}>
          <div className={styles.headerTitle}>
            <h1>研究中心</h1>
            <p>回看判断、变化、任务、报告与结果；所有计数与结论均可追溯到真实接口。</p>
          </div>
        </header>
        <div className={styles.card}>
          <div className={styles.empty}>
            <span>业务内容已锁定，请先登录或注册。</span>
            <span>登录后可回看研究判断链、变化档案、报告差异与结果锚点。</span>
          </div>
        </div>
      </div>
    );
  }

  const aggregatePending = changesQuery.isPending || outcomesQuery.isPending;
  const aggregateError = changesQuery.isError && outcomesQuery.isError;

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div className={styles.headerTitle}>
          <h1>研究中心</h1>
          <p>回看判断、变化、任务、报告与结果；结果只检验研究条件后来是否出现，不构成买卖建议。</p>
        </div>
        <div className={styles.headerMeta}>
          {aggregatePending ? <span>聚合读取中…</span> : null}
          {changes?.generatedAt ? <span>变化档案生成：{formatDateTime(changes.generatedAt)}</span> : null}
          {outcomes?.generatedAt ? <span>结果生成：{formatDateTime(outcomes.generatedAt)}</span> : null}
        </div>
      </header>

      {notice ? (
        <p className={`${styles.notice} ${notice.kind === "success" ? styles.noticeSuccess : ""} ${notice.kind === "conflict" ? styles.noticeConflict : ""}`} role="status">
          {notice.text}
        </p>
      ) : null}

      {aggregateError ? (
        <div className={styles.moduleError} role="status">
          <span>研究聚合暂时不可用。</span>
          <button type="button" onClick={() => { void changesQuery.refetch(); void outcomesQuery.refetch(); }}>重新读取</button>
        </div>
      ) : null}

      {!aggregateError ? (
        <ResearchReviewSummary
          active={focus}
          changes={changes}
          outcomes={outcomes}
          tradeReviews={tradeReviews}
          onSelect={(next) => updateParams({ focus: next === "all" ? null : next })}
        />
      ) : null}

      <div className={styles.workspace}>
          <div className={styles.column} role="region" aria-label="研究股票">
            <ModuleCard meta={`${filteredEntries.length} / ${stockEntries.length} 只`} title="跟踪标的">
              {stockEntries.length === 0 && !aggregatePending && !aggregateError ? (
                <div className={styles.empty}>
                  <strong>尚未选择研究股票</strong>
                  <span>还没有研究跟踪记录。先在关注页添加股票并形成研究快照，研究中心才会出现判断、变化与结果。</span>
                  <div className={styles.actionRow}>
                    <Link className={styles.actionLink} to="/watchlist">前往我的关注</Link>
                    <Link className={styles.actionLink} to="/screening">前往透明选股</Link>
                  </div>
                </div>
              ) : filteredEntries.length === 0 ? (
                <div className={styles.empty}>当前分组下没有股票，切换上方概览卡查看其他分组。</div>
              ) : (
                <ReviewStockList
                  items={filteredEntries}
                  onSelect={(symbol) => updateParams({ symbol })}
                  selectedSymbol={selectedSymbol}
                />
              )}
            </ModuleCard>
          </div>

          <div className={styles.column} role="region" aria-label="判断、变化与处理">
            {selectedSymbol ? (
              <>
                <ModuleCard
                  error={timelineQuery.isError}
                  meta={timelineQuery.data?.dataMeta.dailyAsOf ? `日线截至：${formatDateTime(timelineQuery.data.dataMeta.dailyAsOf)}` : undefined}
                  onRetry={() => void timelineQuery.refetch()}
                  pending={timelineQuery.isPending}
                  title="判断-变化-处理链"
                >
                  {timelineQuery.data ? <DecisionChangeTimeline timeline={timelineQuery.data} /> : null}
                </ModuleCard>
                <ModuleCard
                  error={reportQuery.isError}
                  meta={report?.generatedAt ? `报告生成时间：${formatDateTime(report.generatedAt)}` : undefined}
                  onRetry={() => void reportQuery.refetch()}
                  pending={reportQuery.isPending}
                  title={`报告变化${report?.title ? `｜${report.title}` : ""}`}
                >
                  <ReportDiff change={selectedChangeItem?.latestChange ?? null} />
                </ModuleCard>
                <ModuleCard title="结果进度">
                  <ResearchProgress progress={selectedOutcomeItem?.latestProgress ?? null} />
                </ModuleCard>
                <ModuleCard
                  meta={selectedOutcomeItem ? `已到期 ${selectedOutcomeItem.coverage.available ?? "--"} · 待形成 ${selectedOutcomeItem.coverage.pending ?? "--"}` : undefined}
                  title="历史结果"
                >
                  {selectedOutcomeItem && selectedOutcomeItem.latestAvailable.length > 0 ? (
                    <div className={styles.itemList}>
                      {selectedOutcomeItem.latestAvailable.map((anchor) => (
                        <OutcomeCard anchor={anchor} key={anchor.id ?? anchor.anchorTimestamp ?? "anchor"} name={selectedOutcomeItem.name} />
                      ))}
                    </div>
                  ) : selectedOutcomeItem && selectedOutcomeItem.latestAnchor.length > 0 ? (
                    <div className={styles.itemList}>
                      {selectedOutcomeItem.latestAnchor.map((anchor) => (
                        <OutcomeCard anchor={anchor} key={anchor.id ?? anchor.anchorTimestamp ?? "anchor"} name={selectedOutcomeItem.name} />
                      ))}
                    </div>
                  ) : (
                    <div className={styles.empty}>该股票还没有形成结果锚点；结果在快照之后的第 N 个已存交易日到期回填。</div>
                  )}
                </ModuleCard>
              </>
            ) : (
              <div className={styles.card}><div className={styles.empty}>选择左侧一只股票查看判断、变化与处理记录。</div></div>
            )}
          </div>

          <div className={`${styles.column} ${styles.actionsColumn}`} role="region" aria-label="下一步">
            {selectedSymbol ? (
              <ModuleCard
                error={actionsQuery.isError}
                onRetry={() => void actionsQuery.refetch()}
                title="下一步"
              >
                {actionsQuery.isPending ? <div className={styles.skeleton} aria-live="polite">正在读取…</div> : (
                  <ReviewActions actionItem={selectedActionItem} symbol={selectedSymbol} />
                )}
              </ModuleCard>
            ) : (
              <ModuleCard title="待处理动作">
                <div className={styles.empty}>选择研究股票后查看待处理任务与复盘动作。</div>
              </ModuleCard>
            )}
            <ModuleCard
              error={tradeReviewsQuery.isError}
              meta={tradeReviews ? `共 ${tradeReviews.summary.total ?? "--"} 项 · 已确认 ${tradeReviews.summary.confirmed ?? "--"} · 已归档 ${tradeReviews.summary.archived ?? "--"}` : undefined}
              onRetry={() => void tradeReviewsQuery.refetch()}
              pending={tradeReviewsQuery.isPending}
              title="交易复盘中心"
            >
              {tradeReviews ? (
                <TradeReviewCenterSection
                  center={tradeReviews}
                  onTransition={handleTransition}
                  pendingId={mutation.isPending ? mutation.variables?.reviewId ?? null : null}
                />
              ) : null}
            </ModuleCard>
          </div>
        </div>

      {changes?.boundary ? <p className={styles.boundaryNote}>{changes.boundary}</p> : null}
      {outcomes?.boundary ? <p className={styles.boundaryNote}>{outcomes.boundary}</p> : null}

      <footer className={styles.footer}>
        结果锚点只检验研究条件后来是否出现，不代表可实现收益；红绿仅表示事实涨跌方向，不构成买卖建议。
      </footer>
    </div>
  );
}
