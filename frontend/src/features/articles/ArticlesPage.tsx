import { useCallback, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { generateMarketPulse, listArticles } from "./api";
import { articlesQueries } from "./queries";
import styles from "./ArticlesPage.module.css";

type Props = { authenticated: boolean };

export function ArticlesPage({ authenticated }: Props) {
  const queryClient = useQueryClient();
  const listQ = useQuery(articlesQueries.list(20));
  const [generating, setGenerating] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [modelTier, setModelTier] = useState("standard");

  const articles = listQ.data ?? [];

  const handleGenerate = useCallback(async () => {
    setGenerating(true);
    setMessage(null);
    const article = await generateMarketPulse(modelTier, false);
    if (article) {
      setMessage(`已生成：${article.title}`);
      await queryClient.invalidateQueries({ queryKey: ["articles"] });
    } else {
      setMessage("生成失败，请重试");
    }
    setGenerating(false);
  }, [modelTier, queryClient]);

  return (
    <div className={styles.page}>
      <header className={styles.hero}>
        <div>
          <h1>文章生成</h1>
          <p>生成市场脉搏等自动化研究报告。</p>
        </div>
        <div className={styles.generate}>
          <select
            aria-label="模型等级"
            className={styles.select}
            onChange={(e) => setModelTier(e.target.value)}
            value={modelTier}
          >
            <option value="standard">标准模型</option>
            <option value="advanced">高级模型</option>
          </select>
          <button
            className={styles.generateBtn}
            disabled={generating}
            onClick={handleGenerate}
            type="button"
          >
            {generating ? "生成中…" : "生成市场脉搏"}
          </button>
        </div>
      </header>

      {message ? (
        <div className={styles.message} role="status">{message}</div>
      ) : null}

      <section>
        <h2 className={styles.sectionTitle}>最新文章 ({articles.length})</h2>
        {listQ.isPending ? (
          <div className={styles.loading}>正在读取…</div>
        ) : listQ.isError ? (
          <div className={styles.error} role="status">
            <span>文章列表暂时不可用。</span>
            <button onClick={() => void listQ.refetch()} type="button">重新读取</button>
          </div>
        ) : articles.length === 0 ? (
          <div className={styles.empty}>暂无生成文章。</div>
        ) : (
          <ul className={styles.list}>
            {articles.map((article) => (
              <li key={article.id} className={styles.articleItem}>
                <div className={styles.articleHead}>
                  <strong>{article.title}</strong>
                  <span className={`${styles.status} ${article.status === "complete" ? styles.statusDone : ""}`}>
                    {article.status ?? "—"}
                  </span>
                </div>
                {article.summary ? <p className={styles.summary}>{article.summary}</p> : null}
                <div className={styles.articleMeta}>
                  {article.modelTier ? <span>模型：{article.modelTier}</span> : null}
                  {article.generatedAt ? <span>{new Date(article.generatedAt).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai" })}</span> : null}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
