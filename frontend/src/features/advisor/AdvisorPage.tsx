import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { ModuleState } from "../../components/workbench/ModuleState";
import { OverlayDialog } from "../../components/workbench/OverlayDialog";
import {
  AdvisorApiError,
  archiveAdvisorConversation,
  confirmAdvisorWriteback,
  createAdvisorConversation,
  rejectAdvisorWriteback,
  renameAdvisorConversation,
  sendAdvisorMessage,
  type AdvisorChatRequest,
} from "./api";
import type { AdvisorConversationSummary, AdvisorEntryContext, WritebackCandidate } from "./adapters";
import { ConversationSidebar } from "./components/ConversationSidebar";
import { ContextBar } from "./components/ContextBar";
import { EvidenceDrawer } from "./components/EvidenceDrawer";
import { MessageStream } from "./components/MessageStream";
import { WritebackCandidateCard } from "./components/WritebackCandidateCard";
import { advisorQueries, advisorQueryKeys } from "./queries";
import { useAdvisorStream } from "./useAdvisorStream";
import styles from "./AdvisorPage.module.css";

function sourcePage(value: string | null): string {
  if (value === "stock-research" || value === "stock") return "stock";
  if (value === "screening") return "screening";
  if (value === "watchlist") return "watchlist";
  if (value === "today") return "today";
  if (value === "research-center" || value === "research_center") return "research_center";
  return "advisor";
}

function errorMessage(error: unknown): string {
  if (error instanceof AdvisorApiError) return error.message;
  if (error instanceof Error && error.message) return error.message;
  return "操作暂时无法完成";
}

function latestRunId(messages: { role: string; runId: string | null }[]): string | null {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (message?.role === "assistant" && message.runId) return message.runId;
  }
  return null;
}

function dedupeById<T extends { id: string }>(...collections: T[][]): T[] {
  const items = new Map<string, T>();
  collections.forEach((collection) => collection.forEach((item) => items.set(item.id, item)));
  return [...items.values()];
}

export function AdvisorPage({ authenticated }: { authenticated: boolean }) {
  const { conversationId = null } = useParams<{ conversationId?: string }>();
  const [searchParams] = useSearchParams();
  const location = useLocation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [message, setMessage] = useState("");
  const [pendingUserMessage, setPendingUserMessage] = useState<string | null>(null);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [renameTarget, setRenameTarget] = useState<AdvisorConversationSummary | null>(null);
  const [renameTitle, setRenameTitle] = useState("");
  const [archiveTarget, setArchiveTarget] = useState<AdvisorConversationSummary | null>(null);
  const [writebackAction, setWritebackAction] = useState<{ candidate: WritebackCandidate; kind: "confirm" | "reject" } | null>(null);
  const [writebackConflicts, setWritebackConflicts] = useState<Record<string, string>>({});
  const stream = useAdvisorStream();

  const symbol = useMemo(() => {
    const value = searchParams.get("symbol")?.trim();
    return value ? value.toUpperCase() : null;
  }, [searchParams]);
  const source = searchParams.get("source");
  const requestedSource = sourcePage(source);
  const requestedModule = (source?.trim() || "advisor").slice(0, 80);
  const asOf = searchParams.get("as_of")?.trim() || searchParams.get("asOf")?.trim() || null;
  const requestedEntryContext = useMemo(() => ({
    source_page: requestedSource as "today" | "screening" | "watchlist" | "stock" | "advisor" | "research_center",
    module: requestedModule,
    ...(asOf ? { as_of: asOf } : {}),
    ...(symbol ? { symbol } : {}),
  }), [asOf, requestedModule, requestedSource, symbol]);

  const conversations = useQuery({ ...advisorQueries.conversations(), enabled: authenticated });
  const conversation = useQuery({
    ...advisorQueries.conversation(conversationId ?? ""),
    enabled: authenticated && Boolean(conversationId),
  });
  const writebacks = useQuery({ ...advisorQueries.writebacks(), enabled: authenticated });
  const restoredRunId = latestRunId(conversation.data?.messages ?? []);
  const runId = activeRunId ?? restoredRunId;
  const run = useQuery({
    ...advisorQueries.run(runId ?? ""),
    enabled: authenticated && Boolean(runId),
  });

  const createConversation = useMutation({ mutationFn: createAdvisorConversation });
  const renameConversation = useMutation({
    mutationFn: ({ id, title }: { id: string; title: string }) => renameAdvisorConversation(id, title),
  });
  const archiveConversation = useMutation({ mutationFn: archiveAdvisorConversation });
  const sendMessage = useMutation({ mutationFn: sendAdvisorMessage });
  const resolveWriteback = useMutation({
    mutationFn: ({ id, kind }: { id: string; kind: "confirm" | "reject" }) => (
      kind === "confirm" ? confirmAdvisorWriteback(id) : rejectAdvisorWriteback(id)
    ),
  });

  useEffect(() => {
    stream.reset();
    setPendingUserMessage(null);
    setActiveRunId(null);
  // stream.reset is stable; conversation changes should discard only local in-flight presentation.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversationId]);

  if (!authenticated) {
    return (
      <section className={styles.locked}>
        <h1>金融顾问</h1>
        <ModuleState detail="登录后才能读取你的对话、证据和待确认草稿。" state="forbidden" title="登录后可使用金融顾问" />
      </section>
    );
  }

  const latestAssistant = [...(conversation.data?.messages ?? [])].reverse().find((item) => item.role === "assistant") ?? null;
  const citations = dedupeById(latestAssistant?.structuredAnswer?.citations ?? [], stream.state.citations);
  const evidenceSources = latestAssistant?.evidenceSources ?? [];
  const candidates = dedupeById(
    latestAssistant?.structuredAnswer?.candidateWritebacks ?? [],
    stream.state.candidates,
    writebacks.data?.items ?? [],
  );

  const handleCreate = async () => {
    const created = await createConversation.mutateAsync();
    await queryClient.invalidateQueries({ queryKey: advisorQueryKeys.conversations() });
    navigate(`/advisor/${encodeURIComponent(created.id)}${location.search}`);
  };

  const handleSend = async () => {
    const trimmed = message.trim();
    if (!trimmed || sendMessage.isPending) return;
    const requestId = crypto.randomUUID();
    setMessage("");
    setPendingUserMessage(trimmed);
    stream.start(requestId);
    const payload: AdvisorChatRequest = {
      message: trimmed,
      symbol,
      model_tier: "economy",
      execute_agent: true,
      prefer_precomputed: false,
      conversation_id: conversationId,
      request_id: requestId,
      quality_scope: "user",
      entry_context: requestedEntryContext,
    };
    try {
      const response = await sendMessage.mutateAsync(payload);
      stream.finish(response);
      setActiveRunId(response.runId);
      if (response.conversationId !== conversationId) {
        navigate(`/advisor/${encodeURIComponent(response.conversationId)}${location.search}`, { replace: !conversationId });
      }
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: advisorQueryKeys.conversations() }),
        queryClient.invalidateQueries({ queryKey: advisorQueryKeys.conversation(response.conversationId) }),
        queryClient.invalidateQueries({ queryKey: advisorQueryKeys.writebacks() }),
      ]);
      setPendingUserMessage(null);
    } catch (error) {
      stream.fail(errorMessage(error));
    }
  };

  const handleRename = async () => {
    if (!renameTarget || !renameTitle.trim()) return;
    await renameConversation.mutateAsync({ id: renameTarget.id, title: renameTitle.trim() });
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: advisorQueryKeys.conversations() }),
      queryClient.invalidateQueries({ queryKey: advisorQueryKeys.conversation(renameTarget.id) }),
    ]);
    setRenameTarget(null);
  };

  const handleArchive = async () => {
    if (!archiveTarget) return;
    await archiveConversation.mutateAsync(archiveTarget.id);
    await queryClient.invalidateQueries({ queryKey: advisorQueryKeys.conversations() });
    if (archiveTarget.id === conversationId) navigate(`/advisor${location.search}`, { replace: true });
    setArchiveTarget(null);
  };

  const handleWriteback = async () => {
    if (!writebackAction) return;
    const { candidate, kind } = writebackAction;
    try {
      await resolveWriteback.mutateAsync({ id: candidate.id, kind });
      setWritebackConflicts((current) => {
        const next = { ...current };
        delete next[candidate.id];
        return next;
      });
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: advisorQueryKeys.writebacks() }),
        conversationId ? queryClient.invalidateQueries({ queryKey: advisorQueryKeys.conversation(conversationId) }) : Promise.resolve(),
      ]);
      setWritebackAction(null);
    } catch (error) {
      const messageText = errorMessage(error);
      if (error instanceof AdvisorApiError && error.status === 409) {
        setWritebackConflicts((current) => ({ ...current, [candidate.id]: messageText }));
        await queryClient.invalidateQueries({ queryKey: advisorQueryKeys.writebacks() });
      }
      setWritebackAction(null);
    }
  };

  const persistedContext: AdvisorEntryContext | null = run.data?.entryContext ?? null;
  const streamAlreadyPersisted = stream.state.status === "completed"
    && Boolean(stream.state.runId)
    && (conversation.data?.messages ?? []).some((item) => item.runId === stream.state.runId);
  return (
    <section className={styles.page}>
      <header className={styles.pageHeader}>
        <div>
          <span className={styles.eyebrow}>有证据的个人金融研究</span>
          <h1>金融顾问</h1>
          <p>即时回答、已保存对话、证据和候选写回分开呈现；AI 不会自动替你形成正式判断。</p>
        </div>
        {writebacks.data?.pendingCount ? <span className={styles.pendingCount}>{writebacks.data.pendingCount} 项待确认</span> : null}
      </header>

      <div className={styles.layout}>
        <ConversationSidebar
          conversations={conversations.data ?? []}
          creating={createConversation.isPending}
          error={conversations.isError}
          loading={conversations.isLoading}
          onArchive={setArchiveTarget}
          onCreate={() => void handleCreate()}
          onRename={(item) => { setRenameTarget(item); setRenameTitle(item.title); }}
          onRetry={() => void conversations.refetch()}
          search={location.search}
          selectedId={conversationId}
        />

        <section className={styles.conversationPanel}>
          <ContextBar
            checking={run.isLoading}
            hasRun={Boolean(runId)}
            persisted={persistedContext}
            requestedModule={requestedModule}
            requestedSource={requestedSource}
            symbol={symbol}
          />
          <MessageStream
            error={conversation.isError}
            hasConversation={Boolean(conversationId)}
            loading={conversation.isLoading}
            messages={conversation.data?.messages ?? []}
            onRetry={() => void conversation.refetch()}
            pendingUserMessage={pendingUserMessage}
            streamDraft={streamAlreadyPersisted ? "" : stream.state.draft}
            streamError={stream.state.error}
            streamLabel={stream.state.label}
          />
          <form className={styles.composer} onSubmit={(event) => { event.preventDefault(); void handleSend(); }}>
            <label htmlFor="advisor-message">向金融顾问提问</label>
            <textarea
              disabled={sendMessage.isPending}
              id="advisor-message"
              maxLength={4000}
              onChange={(event) => setMessage(event.target.value)}
              placeholder={symbol ? `围绕 ${symbol} 继续提问，或明确要求生成供你确认的草稿` : "询问市场、个股、基金、风险或研究方法"}
              rows={4}
              value={message}
            />
            <div className={styles.composerFooter}>
              <span>回答会保存到个人对话；未确认的 AI 草稿不会写入正式记录。</span>
              <button disabled={sendMessage.isPending || !message.trim()} type="submit">{sendMessage.isPending ? "生成中…" : "发送"}</button>
            </div>
          </form>
        </section>

        <aside className={styles.contextPanel}>
          <section className={styles.contextSection}>
            <div className={styles.panelHeading}><div><span className={styles.eyebrow}>可追溯输入</span><h2>本轮证据</h2></div></div>
            <EvidenceDrawer citations={citations} sources={evidenceSources} />
          </section>
          <section className={styles.contextSection}>
            <div className={styles.panelHeading}><div><span className={styles.eyebrow}>需要你决定</span><h2>候选写回</h2></div></div>
            {writebacks.isLoading ? <ModuleState state="loading" title="正在读取候选草稿" /> : null}
            {writebacks.isError ? <ModuleState onRetry={() => void writebacks.refetch()} state="error" title="候选草稿暂时不可用" /> : null}
            {!writebacks.isLoading && !writebacks.isError && candidates.length === 0 ? (
              <ModuleState detail="普通研究问题不会自动生成写回；只有你明确要求形成草稿时，才会出现候选。" state="empty" title="没有待处理草稿" />
            ) : null}
            <div className={styles.writebackList}>
              {candidates.map((candidate) => (
                <WritebackCandidateCard
                  candidate={candidate}
                  conflict={writebackConflicts[candidate.id]}
                  key={candidate.id}
                  onConfirm={() => setWritebackAction({ candidate, kind: "confirm" })}
                  onReject={() => setWritebackAction({ candidate, kind: "reject" })}
                />
              ))}
            </div>
          </section>
        </aside>
      </div>

      <OverlayDialog onClose={() => setRenameTarget(null)} open={Boolean(renameTarget)} title="重命名研究对话">
        <form className={styles.dialogForm} onSubmit={(event) => { event.preventDefault(); void handleRename(); }}>
          <label htmlFor="advisor-conversation-title">对话标题</label>
          <input id="advisor-conversation-title" maxLength={120} onChange={(event) => setRenameTitle(event.target.value)} value={renameTitle} />
          <div className={styles.dialogActions}>
            <button onClick={() => setRenameTarget(null)} type="button">取消</button>
            <button disabled={renameConversation.isPending || !renameTitle.trim()} type="submit">保存标题</button>
          </div>
        </form>
      </OverlayDialog>

      <OverlayDialog onClose={() => setArchiveTarget(null)} open={Boolean(archiveTarget)} title="删除研究对话">
        <div className={styles.dialogForm}>
          <p>删除“{archiveTarget?.title}”后，这条对话不会再出现在个人列表中。是否继续？</p>
          <div className={styles.dialogActions}>
            <button onClick={() => setArchiveTarget(null)} type="button">取消</button>
            <button disabled={archiveConversation.isPending} onClick={() => void handleArchive()} type="button">确认删除</button>
          </div>
        </div>
      </OverlayDialog>

      <OverlayDialog onClose={() => setWritebackAction(null)} open={Boolean(writebackAction)} title={writebackAction?.kind === "reject" ? "拒绝这份 AI 草稿" : "确认写回 AI 草稿"}>
        <div className={styles.dialogForm}>
          <p>{writebackAction?.kind === "reject" ? "拒绝后不会改变现有正式记录。" : "只有这次确认后，候选内容才会进入对应的版本化正式工作流。"}</p>
          <div className={styles.dialogActions}>
            <button onClick={() => setWritebackAction(null)} type="button">取消</button>
            <button disabled={resolveWriteback.isPending} onClick={() => void handleWriteback()} type="button">
              {writebackAction?.kind === "reject" ? "确认拒绝这份草稿" : "确认写回这份草稿"}
            </button>
          </div>
        </div>
      </OverlayDialog>
    </section>
  );
}
