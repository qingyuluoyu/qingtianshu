import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  buildChatRequestBody,
  ContractError,
  type AdvisorContext,
  type ConversationDetail,
  type ConversationMessage,
  type ConversationSummary,
  type StructuredAnswer,
  type WritebackCandidate,
} from "./adapters";
import {
  AdvisorApiError,
  confirmAiWriteback,
  openChatStream,
  postChat,
  rejectAiWriteback,
} from "./api";
import { advisorQueries, advisorQueryKeys } from "./queries";
import styles from "./AdvisorPage.module.css";

type Props = { authenticated: boolean };

// ---------- 格式化助手 ----------

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

// ---------- 状态翻译（合同 §6.3，只翻译后端状态） ----------

function statusLabel(status: string): string {
  return ({
    ready: "数据完整",
    complete: "证据充分",
    completed: "已完成",
    sufficient: "证据充分",
    partial: "部分数据可用",
    insufficient: "数据不足",
    unavailable: "当前不可用",
    pending_confirmation: "待确认草稿",
    waiting_data: "等待数据",
    stale: "内容已过期",
    ended: "已结束",
    paused: "已暂停",
    confirmed: "已确认",
    rejected: "已拒绝",
    failed: "生成失败",
    clarification: "需要补充信息",
    blocked: "无法回答",
    active: "进行中",
  } as Record<string, string>)[status] ?? status;
}

function statusTone(status: string): string {
  if (["ready", "complete", "completed", "sufficient", "confirmed", "active"].includes(status)) return styles.badgeReady;
  if (["partial", "insufficient", "clarification"].includes(status)) return styles.badgePartial;
  if (["pending_confirmation", "waiting_data"].includes(status)) return styles.badgeWaiting;
  if (["stale", "failed", "blocked"].includes(status)) return styles.badgeStale;
  return styles.badgeUnavailable;
}

function candidateTypeLabel(type: string | null): string {
  return ({
    thesis: "研究判断候选",
    observation_task: "观察任务候选",
    action_plan: "操作计划候选",
    review_draft: "复盘草稿候选",
  } as Record<string, string>)[type ?? ""] ?? "AI 候选";
}

const SOURCE_PAGE_LABELS: Record<string, string> = {
  watchlist: "我的关注",
  "stock-research": "个股研究",
  screening: "透明选股",
  today: "今日观察",
  "research-center": "研究中心",
};

function sourcePageLabel(source: string | null): string | null {
  if (!source) return null;
  return SOURCE_PAGE_LABELS[source] ?? source;
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

// ---------- 上下文条（§5.5：symbol/sourcePage/module/asOf 来自 URL） ----------

function ContextBar({ context }: { context: AdvisorContext }) {
  const chips: string[] = [];
  if (context.symbol) chips.push(`标的：${context.symbol}`);
  if (context.sourcePage) chips.push(`来源页：${sourcePageLabel(context.sourcePage)}`);
  if (context.module) chips.push(`模块：${context.module}`);
  if (context.asOf) chips.push(`数据时间：${context.asOf}`);
  return (
    <div className={styles.contextBar} aria-label="已收集上下文">
      <span className={styles.contextTitle}>已收集上下文</span>
      {chips.length === 0 ? (
        <span className={styles.meta}>未携带页面上下文；可从个股研究页或我的关注点「问顾问」进入。</span>
      ) : chips.map((chip) => <span className={styles.contextChip} key={chip}>{chip}</span>)}
      {chips.length > 0 ? <span className={styles.meta}>上下文随每次提问一并发送并落库。</span> : null}
    </div>
  );
}

// ---------- 会话侧栏 ----------

function ConversationSidebar({ items, selectedId, search }: {
  items: ConversationSummary[];
  selectedId: string | null;
  search: string;
}) {
  return (
    <div className={styles.sidebarInner}>
      <Link className={styles.newChatLink} to={`/advisor${search}`}>开始新对话</Link>
      {items.length === 0 ? (
        <div className={styles.sidebarEmpty}>还没有研究对话。提出第一个问题后会自动创建会话。</div>
      ) : (
        <ul className={styles.conversationList}>
          {items.map((item) => (
            <li key={item.id}>
              <Link
                aria-current={selectedId === item.id ? "page" : undefined}
                className={styles.conversationItem}
                to={`/advisor/${encodeURIComponent(item.id)}${search}`}
              >
                <strong>{item.title ?? "未命名对话"}</strong>
                <span>{item.lastMessagePreview ?? "暂无消息"}</span>
                <small>
                  {item.messageCount ?? "--"} 条消息
                  {item.updatedAt ? ` · ${formatDateTime(item.updatedAt)}` : ""}
                </small>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ---------- 消息流 ----------

function hasEvidence(message: ConversationMessage): boolean {
  const metadata = message.metadata;
  if (!metadata) return false;
  return metadata.evidenceSources.length > 0 || metadata.structuredAnswer !== null;
}

function MessageStream({ detail, pendingExchange, progressLabel, selectedMessageId, onSelectMessage }: {
  detail: ConversationDetail | null;
  pendingExchange: { question: string } | null;
  progressLabel: string | null;
  selectedMessageId: string | null;
  onSelectMessage: (id: string) => void;
}) {
  const messages = detail?.messages ?? [];
  if (messages.length === 0 && !pendingExchange) {
    return <div className={styles.empty}>输入第一个问题，发送后才会创建本次研究运行。</div>;
  }
  return (
    <ol className={styles.messageList}>
      {messages.map((message) => {
        const isUser = message.role === "user";
        return (
          <li className={`${styles.message} ${isUser ? styles.messageUser : styles.messageAssistant}`} key={message.id}>
            <div className={styles.messageBubble}>
              <p className={styles.messageContent}>{message.content ?? "内容为空"}</p>
              <div className={styles.messageMeta}>
                <span>{isUser ? "我" : "顾问"}</span>
                <span>生成时间：{formatDateTime(message.createdAt)}</span>
                {!isUser && message.intent ? <span>意图：{message.intent}</span> : null}
                {message.metadata?.symbol ? <span>标的:{message.metadata.symbol}</span> : null}
              </div>
              {!isUser && hasEvidence(message) ? (
                <button
                  aria-pressed={selectedMessageId === message.id}
                  className={styles.evidenceToggle}
                  onClick={() => onSelectMessage(message.id)}
                  type="button"
                >
                  查看证据与五面分析
                </button>
              ) : null}
            </div>
          </li>
        );
      })}
      {pendingExchange ? (
        <>
          <li className={`${styles.message} ${styles.messageUser}`}>
            <div className={styles.messageBubble}>
              <p className={styles.messageContent}>{pendingExchange.question}</p>
              <div className={styles.messageMeta}><span>我</span><span>发送中…</span></div>
            </div>
          </li>
          <li className={`${styles.message} ${styles.messageAssistant}`} aria-live="polite">
            <div className={styles.messageBubble}>
              <p className={styles.messageContent}>{progressLabel ?? "正在识别问题，并检索实时证据与资料库…"}</p>
              <div className={styles.messageMeta}><span>顾问</span><span>生成中</span></div>
            </div>
          </li>
        </>
      ) : null}
    </ol>
  );
}

// ---------- 澄清问题（status=clarification 时渲染待补充项） ----------

function ClarifyingQuestionFlow({ requiredFields }: { requiredFields: string[] }) {
  if (requiredFields.length === 0) return null;
  return (
    <div className={styles.clarify} role="status">
      <strong>回答前需要补充以下信息：</strong>
      <ul>
        {requiredFields.map((field) => <li key={field}>{field}</li>)}
      </ul>
      <span className={styles.meta}>直接在下方输入框补充后再次发送。</span>
    </div>
  );
}

// ---------- 候选写回卡片（§5.5/§7.2：仅查看、确认、拒绝、回到对话修改；无假编辑按钮） ----------

function candidatePayloadRows(candidate: WritebackCandidate): { label: string; value: string }[] {
  const payload = candidate.payload;
  const rows: { label: string; value: string }[] = [];
  const push = (label: string, value: unknown) => {
    if (typeof value === "string" && value.length > 0) rows.push({ label, value });
    else if (typeof value === "number" && Number.isFinite(value)) rows.push({ label, value: String(value) });
    else if (Array.isArray(value)) {
      const items = value.filter((item): item is string => typeof item === "string" && item.length > 0);
      if (items.length > 0) rows.push({ label, value: items.join("；") });
    }
  };
  if (candidate.candidateType === "thesis") {
    push("判断理由", payload.reason_text);
    push("观察要点", payload.watch_items);
    push("复核条件", payload.recheck_conditions);
  } else if (candidate.candidateType === "observation_task") {
    push("任务", payload.title);
    push("说明", payload.description);
    push("优先级", payload.priority);
    push("截止时间", payload.due_at);
  } else if (candidate.candidateType === "action_plan") {
    push("动作", payload.action_type);
    push("触发条件", payload.trigger_text);
    push("备注", payload.note);
  } else {
    // 未识别类型（含 review_draft）：只直通原始字段，不编造结构。
    for (const [key, value] of Object.entries(payload)) push(key, value);
  }
  return rows;
}

function WritebackCandidateCard({ candidate, pending, onConfirm, onReject, onRevise }: {
  candidate: WritebackCandidate;
  pending: boolean;
  onConfirm: (candidate: WritebackCandidate) => void;
  onReject: (candidate: WritebackCandidate) => void;
  onRevise: (candidate: WritebackCandidate) => void;
}) {
  const status = candidate.status ?? "pending_confirmation";
  const rows = candidatePayloadRows(candidate);
  return (
    <article className={styles.candidateCard}>
      <div className={styles.candidateHead}>
        <strong>{candidateTypeLabel(candidate.candidateType)}</strong>
        <span className={`${styles.badge} ${statusTone(status)}`}>{statusLabel(status)}</span>
      </div>
      {candidate.symbol ? <div className={styles.meta}>标的：{candidate.symbol}</div> : null}
      {rows.length === 0 ? (
        <p className={styles.meta}>候选内容为空。</p>
      ) : (
        <dl className={styles.candidateRows}>
          {rows.map((row) => (
            <div key={row.label}>
              <dt>{row.label}</dt>
              <dd>{row.value}</dd>
            </div>
          ))}
        </dl>
      )}
      <div className={styles.meta}>
        生成时间：{formatDateTime(candidate.createdAt)}
        {candidate.baseVersion !== null ? ` · 基于版本 ${candidate.baseVersion}` : ""}
        {candidate.resolvedAt ? ` · 处理时间：${formatDateTime(candidate.resolvedAt)}` : ""}
      </div>
      {status === "pending_confirmation" ? (
        <div className={styles.candidateActions}>
          <button
            className={styles.confirmButton}
            disabled={pending}
            onClick={() => onConfirm(candidate)}
            type="button"
          >
            {pending ? "写入中…" : "确认写回"}
          </button>
          <button
            className={styles.rejectButton}
            disabled={pending}
            onClick={() => onReject(candidate)}
            type="button"
          >
            拒绝
          </button>
          <button
            className={styles.reviseButton}
            disabled={pending}
            onClick={() => onRevise(candidate)}
            type="button"
          >
            回到对话修改
          </button>
        </div>
      ) : null}
      {status === "stale" ? (
        <div className={styles.candidateActions}>
          <span className={styles.meta}>正式对象已更新，该候选不可再确认。</span>
          <button className={styles.reviseButton} onClick={() => onRevise(candidate)} type="button">回到对话重新生成</button>
        </div>
      ) : null}
    </article>
  );
}

// ---------- 证据与五面分析（EvidenceDrawer 内容；无数据时不渲染抽屉空壳） ----------

function FiveFactorAnalysis({ answer }: { answer: StructuredAnswer }) {
  const sections: { title: string; items: string[] }[] = [
    { title: "已确认事实", items: answer.confirmedFacts },
    { title: "证据支持的推断", items: answer.evidenceBasedInferences },
    { title: "待核验假设", items: answer.hypothesesToVerify },
    { title: "反方证据与风险", items: answer.counterEvidenceAndRisks },
    { title: "信息缺口", items: answer.informationGaps },
  ];
  return (
    <div className={styles.fiveFactor}>
      <div className={styles.meta}>
        结构化状态：
        <span className={`${styles.badge} ${statusTone(answer.status ?? "unavailable")}`}>
          {statusLabel(answer.status ?? "unavailable")}
        </span>
      </div>
      {answer.answerSummary ? <p className={styles.statement}>{answer.answerSummary}</p> : null}
      {sections.map((section) => (
        <div key={section.title}>
          <h3 className={styles.factorTitle}>{section.title}</h3>
          {section.items.length === 0 ? (
            <p className={styles.meta}>暂无记录</p>
          ) : (
            <ul className={styles.factorList}>
              {section.items.map((item) => <li key={item}>{item}</li>)}
            </ul>
          )}
        </div>
      ))}
      {answer.conclusionBoundary ? <p className={styles.boundaryNote}>{answer.conclusionBoundary}</p> : null}
    </div>
  );
}

// ---------- 确认写回对话框（§7.2：确认文案 + 版本字段） ----------

function ConfirmCandidateDialog({ candidate, pending, onCancel, onConfirm }: {
  candidate: WritebackCandidate;
  pending: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <div className={styles.dialogOverlay} onClick={pending ? undefined : onCancel}>
      <div
        aria-labelledby="confirm-candidate-title"
        aria-modal="true"
        className={styles.dialog}
        onClick={(event) => event.stopPropagation()}
        role="dialog"
      >
        <h2 id="confirm-candidate-title">确认写回{candidateTypeLabel(candidate.candidateType)}？</h2>
        <p>
          确认后该候选将写入正式研究记录{candidate.symbol ? `（${candidate.symbol}）` : ""}
          {candidate.baseVersion !== null ? `，候选基于版本 ${candidate.baseVersion}` : ""}
          。若正式对象已被其他操作更新，服务端会拒绝并把候选标记为已过期，不会覆盖最新版本。
        </p>
        <div className={styles.dialogActions}>
          <button className={styles.dialogCancel} disabled={pending} onClick={onCancel} type="button">取消</button>
          <button className={styles.dialogConfirm} disabled={pending} onClick={onConfirm} type="button">
            {pending ? "写入中…" : "确认写回"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------- 页面 ----------

type MutationNotice = { kind: "success" | "conflict" | "failed"; text: string } | null;

function newRequestId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") return crypto.randomUUID();
  return `req-${Math.random().toString(36).slice(2, 12)}-${Date.now().toString(36)}`;
}

export function AdvisorPage({ authenticated }: Props) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const { conversationId = null } = useParams<{ conversationId?: string }>();
  const [searchParams] = useSearchParams();

  // URL 上下文（§5.5）：source 与 sourcePage 两种参数名都接受（现有入口用 source）。
  const context: AdvisorContext = useMemo(() => ({
    symbol: searchParams.get("symbol"),
    sourcePage: searchParams.get("sourcePage") ?? searchParams.get("source"),
    module: searchParams.get("module"),
    asOf: searchParams.get("asOf"),
  }), [searchParams]);

  const conversationsQuery = useQuery({ ...advisorQueries.conversations(), enabled: authenticated });
  const conversationQuery = useQuery({ ...advisorQueries.conversation(conversationId ?? ""), enabled: authenticated && conversationId !== null });
  const writebacksQuery = useQuery({ ...advisorQueries.writebacks(), enabled: authenticated });

  const detail = conversationQuery.data ?? null;
  const writebacks = writebacksQuery.data ?? null;

  const [draft, setDraft] = useState("");
  const [notice, setNotice] = useState<MutationNotice>(null);
  const [progressLabel, setProgressLabel] = useState<string | null>(null);
  const [selectedMessageId, setSelectedMessageId] = useState<string | null>(null);
  const [confirmCandidate, setConfirmCandidate] = useState<WritebackCandidate | null>(null);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const streamCloseRef = useRef<(() => void) | null>(null);
  const prefillRef = useRef<string | null>(null);

  // 预填问题（§5.5）：?question= 优先，其次 intent 映射；只进草稿，绝不自动发送。
  useEffect(() => {
    const question = searchParams.get("question");
    const intent = searchParams.get("intent");
    const symbol = searchParams.get("symbol");
    let prefill: string | null = null;
    if (question) prefill = question;
    else if (intent === "new-thesis") {
      prefill = `我想为${symbol ?? "该标的"}形成一份当前判断，请基于可核验证据帮我梳理支持证据、反方证据与待核验项。`;
    } else if (intent === "deep-research") {
      prefill = `我想对${symbol ?? "该标的"}开启一轮深度研究，请先告诉我还需要补充哪些关键证据。`;
    }
    if (prefill === null) return;
    setDraft((current) => (current === "" || current === prefillRef.current ? prefill : current));
    prefillRef.current = prefill;
  }, [searchParams]);

  useEffect(() => () => {
    streamCloseRef.current?.();
  }, []);

  const invalidateAdvisorData = (id: string | null) => {
    void queryClient.invalidateQueries({ queryKey: advisorQueryKeys.conversations() });
    void queryClient.invalidateQueries({ queryKey: advisorQueryKeys.writebacks() });
    if (id) void queryClient.invalidateQueries({ queryKey: advisorQueryKeys.conversation(id) });
  };

  const sendMutation = useMutation({
    mutationFn: (body: ReturnType<typeof buildChatRequestBody>) => postChat(body),
    onSuccess: (data) => {
      streamCloseRef.current?.();
      streamCloseRef.current = null;
      setProgressLabel(null);
      if (data.status === "failed" || data.error) {
        setNotice({ kind: "failed", text: `本次回答生成失败${data.error ? `：${data.error}` : ""}。消息已留存在会话中，可修改后重试。` });
      } else {
        setNotice(null);
      }
      invalidateAdvisorData(data.conversationId ?? conversationId);
      if (data.conversationId && data.conversationId !== conversationId) {
        navigate(`/advisor/${encodeURIComponent(data.conversationId)}${searchParams.size > 0 ? `?${searchParams.toString()}` : ""}`);
      }
    },
    onError: (error) => {
      streamCloseRef.current?.();
      streamCloseRef.current = null;
      setProgressLabel(null);
      setNotice({
        kind: "failed",
        text: error instanceof AdvisorApiError && error.status === 401
          ? "会话已失效，请重新登录后再提问。"
          : `发送失败：${error instanceof Error ? error.message : "数据暂时不可用"}。未创建任何研究运行，请重试。`,
      });
    },
  });

  const writebackMutation = useMutation({
    mutationFn: ({ candidate, action }: { candidate: WritebackCandidate; action: "confirm" | "reject" }) =>
      action === "confirm" ? confirmAiWriteback(candidate.id) : rejectAiWriteback(candidate.id),
    onSuccess: (_data, variables) => {
      setConfirmCandidate(null);
      setNotice({
        kind: "success",
        text: variables.action === "confirm" ? "候选已确认并写入正式研究记录。" : "候选已拒绝，不会写入正式记录。",
      });
      invalidateAdvisorData(conversationId);
    },
    onError: (error) => {
      setConfirmCandidate(null);
      if (error instanceof AdvisorApiError && error.status === 409) {
        // 409：后端已把候选置 stale；只刷新取回最新状态，由用户回到对话重新生成，不做本地覆盖。
        setNotice({ kind: "conflict", text: error.message });
        invalidateAdvisorData(conversationId);
        return;
      }
      setNotice({ kind: "failed", text: `候选处理失败：${error instanceof Error ? error.message : "数据暂时不可用"}。请重试。` });
    },
  });

  const send = () => {
    setNotice(null);
    try {
      const requestId = newRequestId();
      const body = buildChatRequestBody(draft, context, { conversationId, requestId });
      streamCloseRef.current?.();
      streamCloseRef.current = openChatStream(requestId, (event) => {
        if (event.label) setProgressLabel(event.label);
      });
      setProgressLabel(null);
      sendMutation.mutate(body, {
        onSuccess: () => setDraft(""),
      });
      prefillRef.current = null;
    } catch (error) {
      if (error instanceof ContractError) {
        setNotice({ kind: "failed", text: error.message });
      }
    }
  };

  const reviseCandidate = (candidate: WritebackCandidate) => {
    setDraft(`关于刚才的${candidateTypeLabel(candidate.candidateType)}${candidate.symbol ? `（${candidate.symbol}）` : ""}，我希望调整为：`);
    composerRef.current?.focus();
  };

  // 证据抽屉消息：选中项优先，否则取最近一条带证据的助手消息。
  const evidenceMessage = useMemo(() => {
    if (!detail) return null;
    const messages = detail.messages.filter((message) => message.role === "assistant" && hasEvidence(message));
    if (messages.length === 0) return null;
    return messages.find((message) => message.id === selectedMessageId) ?? messages[messages.length - 1];
  }, [detail, selectedMessageId]);

  const liveStructured = sendMutation.data?.structuredAnswer ?? null;
  const structured = evidenceMessage?.metadata?.structuredAnswer ?? liveStructured;
  const evidenceSources = evidenceMessage?.metadata?.evidenceSources ?? sendMutation.data?.evidenceSources ?? [];
  const pendingCandidates = useMemo(() => {
    if (!writebacks) return [];
    const rank = (candidate: WritebackCandidate) => (candidate.status === "pending_confirmation" ? 0 : candidate.status === "stale" ? 1 : 2);
    return [...writebacks.items].sort((a, b) => rank(a) - rank(b)).slice(0, 20);
  }, [writebacks]);

  const showDrawer = pendingCandidates.length > 0 || evidenceMessage !== null || structured !== null || evidenceSources.length > 0;

  if (!authenticated) {
    return (
      <div className={styles.page}>
        <header className={styles.header}>
          <div className={styles.headerTitle}>
            <h1>金融顾问</h1>
            <p>基于证据回答问题，AI 输出只作为候选；正式判断、任务与记忆必须经你确认后写入。</p>
          </div>
        </header>
        <div className={styles.card}>
          <div className={styles.empty}>
            <span>业务内容已锁定，请先登录或注册。</span>
            <span>登录后可发起研究对话、追溯证据并确认 AI 候选写回。</span>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div className={styles.headerTitle}>
          <h1>金融顾问</h1>
          <p>基于证据回答问题，AI 输出只作为候选；正式判断、任务与记忆必须经你确认后写入。</p>
        </div>
        <div className={styles.headerMeta}>
          {writebacks && writebacks.summary.pendingConfirmation !== null && writebacks.summary.pendingConfirmation > 0 ? (
            <span>待确认候选：<span className={`${styles.badge} ${styles.badgeWaiting}`}>{writebacks.summary.pendingConfirmation}</span></span>
          ) : null}
          {detail ? <span>当前会话：{detail.title ?? "未命名对话"}</span> : null}
        </div>
      </header>

      {notice ? (
        <p className={`${styles.notice} ${notice.kind === "success" ? styles.noticeSuccess : ""} ${notice.kind === "conflict" ? styles.noticeConflict : ""}`} role="status">
          {notice.text}
        </p>
      ) : null}

      <div className={`${styles.layout} ${showDrawer ? "" : styles.layoutNoDrawer}`}>
        <aside className={`${styles.card} ${styles.sidebar}`} aria-label="会话列表与上下文">
          <ConversationSidebar
            items={conversationsQuery.data?.items ?? []}
            search={searchParams.size > 0 ? `?${searchParams.toString()}` : ""}
            selectedId={conversationId}
          />
          {conversationsQuery.isError ? (
            <div className={styles.moduleError} role="status">
              <span>会话列表暂时不可用。</span>
              <button type="button" onClick={() => void conversationsQuery.refetch()}>重新读取</button>
            </div>
          ) : null}
          <ContextBar context={context} />
        </aside>

        <main className={styles.mainColumn}>
          <ModuleCard
            error={conversationId !== null && conversationQuery.isError}
            meta={detail ? `${detail.messages.length} 条消息` : undefined}
            onRetry={() => void conversationQuery.refetch()}
            pending={conversationId !== null && conversationQuery.isPending}
            title="研究对话"
          >
            <MessageStream
              detail={detail}
              onSelectMessage={(id) => setSelectedMessageId(id)}
              pendingExchange={sendMutation.isPending ? { question: sendMutation.variables.message.split("\n[研究上下文：")[0] } : null}
              progressLabel={progressLabel}
              selectedMessageId={selectedMessageId}
            />
            {sendMutation.data?.status === "clarification" ? (
              <ClarifyingQuestionFlow requiredFields={sendMutation.data.requiredFields} />
            ) : null}
            <div className={styles.composer}>
              <textarea
                aria-label="向顾问提问"
                disabled={sendMutation.isPending}
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
                    event.preventDefault();
                    send();
                  }
                }}
                placeholder="输入你的研究问题（Ctrl/⌘ + Enter 发送）；发送后才会创建研究运行。"
                ref={composerRef}
                rows={3}
                value={draft}
              />
              <div className={styles.composerBar}>
                <span className={styles.meta}>
                  {context.symbol ? `将携带标的 ${context.symbol} 与页面上下文一并发送。` : "未携带页面上下文。"}
                </span>
                <button
                  className={styles.sendButton}
                  disabled={sendMutation.isPending || draft.trim().length === 0}
                  onClick={send}
                  type="button"
                >
                  {sendMutation.isPending ? "生成中…" : "发送"}
                </button>
              </div>
            </div>
          </ModuleCard>
        </main>

        {showDrawer ? (
          <aside className={styles.drawerColumn} aria-label="证据与候选写回">
            {pendingCandidates.length > 0 ? (
              <ModuleCard
                meta={writebacks?.summary.total !== null && writebacks?.summary.total !== undefined ? `共 ${writebacks.summary.total} 条` : undefined}
                title="AI 候选写回"
              >
                <p className={styles.helper}>
                  候选只是草稿，确认后才会写入正式研究记录；无编辑入口，需修改请回到对话。
                </p>
                <div className={styles.candidateList}>
                  {pendingCandidates.map((candidate) => (
                    <WritebackCandidateCard
                      candidate={candidate}
                      key={candidate.id}
                      onConfirm={(item) => setConfirmCandidate(item)}
                      onReject={(item) => writebackMutation.mutate({ candidate: item, action: "reject" })}
                      onRevise={reviseCandidate}
                      pending={writebackMutation.isPending && writebackMutation.variables?.candidate.id === candidate.id}
                    />
                  ))}
                </div>
              </ModuleCard>
            ) : null}
            {evidenceMessage || structured || evidenceSources.length > 0 ? (
              <ModuleCard
                meta={evidenceMessage ? `生成时间：${formatDateTime(evidenceMessage.createdAt)}` : undefined}
                title="证据与五面分析"
              >
                {structured ? <FiveFactorAnalysis answer={structured} /> : null}
                {evidenceSources.length > 0 ? (
                  <>
                    <h3 className={styles.factorTitle}>证据来源</h3>
                    <ul className={styles.evidenceList}>
                      {evidenceSources.map((source, index) => (
                        <li key={`${source.title}-${index}`}>
                          <strong>{source.title}</strong>
                          <span className={styles.meta}>
                            {source.kind ? `${source.kind} · ` : ""}
                            {source.asOf ? `数据时间：${source.asOf}` : "数据时间待确认"}
                            {source.source ? ` · 来源：${source.source}` : ""}
                          </span>
                          {source.summary ? <p>{source.summary}</p> : null}
                        </li>
                      ))}
                    </ul>
                  </>
                ) : null}
                {!structured && evidenceSources.length === 0 ? (
                  <div className={styles.empty}>该消息没有可追溯的证据记录。</div>
                ) : null}
              </ModuleCard>
            ) : null}
          </aside>
        ) : null}
      </div>

      {confirmCandidate ? (
        <ConfirmCandidateDialog
          candidate={confirmCandidate}
          onCancel={() => setConfirmCandidate(null)}
          onConfirm={() => writebackMutation.mutate({ candidate: confirmCandidate, action: "confirm" })}
          pending={writebackMutation.isPending}
        />
      ) : null}

      <footer className={styles.footer}>
        顾问回答仅为研究候选，不构成投资建议；红绿仅表示事实方向或数据状态。
      </footer>
    </div>
  );
}
