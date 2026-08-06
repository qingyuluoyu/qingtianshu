import { ModuleState } from "../../../components/workbench/ModuleState";
import type { AdvisorMessage } from "../adapters";
import styles from "../AdvisorPage.module.css";

function readableTime(value: string | null): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit" }).format(date);
}

export function MessageStream({
  messages,
  pendingUserMessage,
  streamDraft,
  streamLabel,
  streamError,
  loading,
  error,
  hasConversation,
  onRetry,
}: {
  messages: AdvisorMessage[];
  pendingUserMessage: string | null;
  streamDraft: string;
  streamLabel: string | null;
  streamError: string | null;
  loading: boolean;
  error: boolean;
  hasConversation: boolean;
  onRetry: () => void;
}) {
  if (loading) return <ModuleState state="loading" title="正在读取对话消息" />;
  if (error) return <ModuleState detail="已保存的消息没有被本地内容覆盖。" onRetry={onRetry} state="error" title="对话暂时无法读取" />;
  if (!hasConversation && !pendingUserMessage) {
    return <ModuleState detail="可以询问市场、个股、基金、风险或研究方法。系统只把 AI 输出作为候选，不会自动替你形成正式判断。" state="empty" title="开始一条有证据的研究对话" />;
  }
  if (messages.length === 0 && !pendingUserMessage) {
    return <ModuleState detail="输入第一个问题后，回答和证据会保存到这条对话。" state="empty" title="这条对话还没有消息" />;
  }
  return (
    <div aria-live="polite" className={styles.messages}>
      {messages.map((message) => (
        <article className={`${styles.message} ${message.role === "user" ? styles.userMessage : styles.assistantMessage}`} key={message.id}>
          <div className={styles.messageMeta}>
            <strong>{message.role === "user" ? "你" : "金融顾问"}</strong>
            {readableTime(message.createdAt) ? <time dateTime={message.createdAt ?? undefined}>{readableTime(message.createdAt)}</time> : null}
          </div>
          <div className={styles.messageBody}>{message.content}</div>
        </article>
      ))}
      {pendingUserMessage ? (
        <article className={`${styles.message} ${styles.userMessage}`}>
          <div className={styles.messageMeta}><strong>你</strong><span>发送中</span></div>
          <div className={styles.messageBody}>{pendingUserMessage}</div>
        </article>
      ) : null}
      {pendingUserMessage || streamDraft || streamError ? (
        <article className={`${styles.message} ${styles.assistantMessage} ${styles.streamingMessage}`}>
          <div className={styles.messageMeta}><strong>金融顾问</strong><span>{streamLabel ?? "正在处理"}</span></div>
          {streamDraft ? <div className={styles.messageBody}>{streamDraft}</div> : null}
          {streamError ? <div className={styles.streamError} role="alert">{streamError}</div> : null}
        </article>
      ) : null}
    </div>
  );
}
