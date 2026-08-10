import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { getGlobalSearch } from "../../api/search";
import styles from "./SearchPage.module.css";

const DEBOUNCE_MS = 250;

type Props = { authenticated: boolean };

export function SearchPage({ authenticated }: Props) {
  const [searchParams, setSearchParams] = useSearchParams();
  const initial = searchParams.get("q") ?? "";
  const [input, setInput] = useState(initial);
  const [debounced, setDebounced] = useState(initial);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(input.trim()), DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [input]);

  useEffect(() => {
    if (debounced) {
      setSearchParams({ q: debounced }, { replace: true });
    } else {
      setSearchParams({}, { replace: true });
    }
  }, [debounced, setSearchParams]);

  const search = useQuery({
    queryKey: ["global-search", debounced],
    queryFn: () => getGlobalSearch(debounced),
    enabled: debounced.length > 0,
    staleTime: 15_000,
    retry: false,
  });

  const groups = search.data ?? [];

  return (
    <div className={styles.page}>
      <header className={styles.hero}>
        <div>
          <h1>全局搜索</h1>
          <p>搜索股票代码、公司名称、行业板块。</p>
        </div>
        <input
          aria-label="搜索关键词"
          className={styles.searchInput}
          onChange={(e) => { setInput(e.target.value); }}
          placeholder="输入股票代码或公司名称…"
          value={input}
        />
      </header>

      {!debounced ? (
        <div className={styles.empty}>
          <p>请输入关键词开始搜索。</p>
          {!authenticated && <p className={styles.hint}>登录后可搜索更多结果。</p>}
        </div>
      ) : search.isPending ? (
        <div className={styles.loading}>搜索中…</div>
      ) : search.isError ? (
        <div className={styles.error} role="status">
          <span>搜索暂时不可用，无法判断是否存在匹配结果。</span>
          <button onClick={() => void search.refetch()} type="button">重新搜索</button>
        </div>
      ) : groups.length === 0 ? (
        <div className={styles.empty}>
          <p>没有匹配「{debounced}」的结果。</p>
        </div>
      ) : (
        <div className={styles.results}>
          {groups.map((group) => (
            <section key={group.key} className={styles.group}>
              <h2 className={styles.groupLabel}>{group.label}</h2>
              <ul className={styles.list}>
                {group.items.map((item) => (
                  <li key={`${group.key}-${item.id}`}>
                    <a className={styles.item} href={item.url} rel="noreferrer">
                      <strong>{item.title}</strong>
                      {item.subtitle ? <span>{item.subtitle}</span> : null}
                    </a>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}
