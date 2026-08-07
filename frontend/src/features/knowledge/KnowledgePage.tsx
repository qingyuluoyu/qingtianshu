import { useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { deleteKnowledgeDocument, listKnowledgeDocuments, uploadKnowledgeDocument, type KnowledgeDocument } from "./api";
import { knowledgeQueries } from "./queries";
import styles from "./KnowledgePage.module.css";

type Props = { authenticated: boolean };

export function KnowledgePage({ authenticated }: Props) {
  const queryClient = useQueryClient();
  const list = useQuery(knowledgeQueries.list());
  const [uploading, setUploading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const [title, setTitle] = useState("");

  const handleUpload = async () => {
    const file = fileRef.current?.files?.[0];
    if (!file) return;
    setUploading(true);
    setMessage(null);
    const doc = await uploadKnowledgeDocument(title || file.name, file);
    if (doc) {
      setMessage(`已上传：${doc.title}`);
      setTitle("");
      if (fileRef.current) fileRef.current.value = "";
      await queryClient.invalidateQueries({ queryKey: ["knowledge"] });
    } else {
      setMessage("上传失败，请重试");
    }
    setUploading(false);
  };

  const handleDelete = async (id: string) => {
    const ok = await deleteKnowledgeDocument(id);
    if (ok) {
      setMessage("已删除");
      await queryClient.invalidateQueries({ queryKey: ["knowledge"] });
    } else {
      setMessage("删除失败，请重试");
    }
  };

  const docs: KnowledgeDocument[] = list.data ?? [];

  return (
    <div className={styles.page}>
      <header className={styles.hero}>
        <div>
          <h1>知识库</h1>
          <p>管理您的私有知识文档，用于 AI 顾问上下文增强。</p>
        </div>
      </header>

      <section className={styles.upload}>
        <h2>上传文档</h2>
        <div className={styles.uploadForm}>
          <input
            aria-label="文档标题"
            className={styles.input}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="文档标题（可选）"
            value={title}
          />
          <input
            accept=".txt,.md,.pdf,.doc,.docx"
            aria-label="选择文件"
            className={styles.fileInput}
            onChange={() => {}}
            ref={fileRef}
            type="file"
          />
          <button
            className={styles.uploadBtn}
            disabled={uploading}
            onClick={handleUpload}
            type="button"
          >
            {uploading ? "上传中…" : "上传"}
          </button>
        </div>
        {message ? <p className={styles.message}>{message}</p> : null}
      </section>

      <section>
        <h2 className={styles.sectionTitle}>已上传文档 ({docs.length})</h2>
        {list.isPending ? (
          <div className={styles.loading}>正在读取…</div>
        ) : list.isError ? (
          <div className={styles.error} role="status">
            <span>知识库暂时不可用。</span>
            <button onClick={() => void list.refetch()} type="button">重新读取</button>
          </div>
        ) : docs.length === 0 ? (
          <div className={styles.empty}>暂无知识库文档，请上传。</div>
        ) : (
          <ul className={styles.list}>
            {docs.map((doc) => (
              <li key={doc.id} className={styles.docItem}>
                <div className={styles.docInfo}>
                  <strong>{doc.title}</strong>
                  <span>{doc.category ?? "未分类"} · {doc.status ?? "已就绪"} · {doc.chunkCount ?? 0} 块</span>
                  <small>{doc.createdAt ? new Date(doc.createdAt).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai" }) : ""}</small>
                </div>
                <button
                  className={styles.deleteBtn}
                  onClick={() => handleDelete(doc.id)}
                  type="button"
                >
                  删除
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
