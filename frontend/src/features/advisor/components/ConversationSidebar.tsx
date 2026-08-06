import { Link } from "react-router-dom";
import { ModuleState } from "../../../components/workbench/ModuleState";
import type { AdvisorConversationSummary } from "../adapters";
import styles from "../AdvisorPage.module.css";

function readableTime(value: string | null): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function ConversationSidebar({
  conversations,
  selectedId,
  search,
  loading,
  error,
  creating,
  onRetry,
  onCreate,
  onRename,
  onArchive,
}: {
  conversations: AdvisorConversationSummary[];
  selectedId: string | null;
  search: string;
  loading: boolean;
  error: boolean;
  creating: boolean;
  onRetry: () => void;
  onCreate: () => void;
  onRename: (conversation: AdvisorConversationSummary) => void;
  onArchive: (conversation: AdvisorConversationSummary) => void;
}) {
  return (
    <aside aria-label="研究对话" className={styles.sidebar}>
      <div className={styles.panelHeading}>
        <div>
          <span className={styles.eyebrow}>个人研究记录</span>
          <h2>研究对话</h2>
        </div>
        <button disabled={creating} onClick={onCreate} type="button">
          {creating ? "创建中…" : "新建"}
        </button>
      </div>
      {loading ? <ModuleState state="loading" title="正在读取对话" /> : null}
      {error ? <ModuleState detail="没有覆盖本地历史记录，请重试读取。" onRetry={onRetry} state="error" title="对话列表暂时不可用" /> : null}
      {!loading && !error && conversations.length === 0 ? (
        <ModuleState detail="直接在右侧输入问题，系统会创建并保存第一条研究对话。" state="empty" title="还没有研究对话" />
      ) : null}
      <div className={styles.conversationList}>
        {conversations.map((conversation) => {
          const selected = conversation.id === selectedId;
          return (
            <article className={`${styles.conversationItem} ${selected ? styles.conversationSelected : ""}`} key={conversation.id}>
              <Link aria-current={selected ? "page" : undefined} to={`/advisor/${encodeURIComponent(conversation.id)}${search}`}>
                <strong>{conversation.title}</strong>
                {conversation.lastMessagePreview ? <span>{conversation.lastMessagePreview}</span> : <span>尚无消息</span>}
                {readableTime(conversation.updatedAt) ? <time dateTime={conversation.updatedAt ?? undefined}>{readableTime(conversation.updatedAt)}</time> : null}
              </Link>
              {selected ? (
                <div className={styles.conversationActions}>
                  <button onClick={() => onRename(conversation)} type="button">重命名</button>
                  <button onClick={() => onArchive(conversation)} type="button">删除</button>
                </div>
              ) : null}
            </article>
          );
        })}
      </div>
    </aside>
  );
}
