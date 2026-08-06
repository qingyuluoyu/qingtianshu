import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { getGlobalSearch } from "../../api/search";
import styles from "../../components/AppShell.module.css";

export function GlobalSearch() {
  const [input, setInput] = useState("");
  const [debounced, setDebounced] = useState("");
  const [open, setOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();

  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(input.trim()), 250);
    return () => window.clearTimeout(timer);
  }, [input]);

  useEffect(() => {
    const onKeydown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        inputRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKeydown);
    return () => window.removeEventListener("keydown", onKeydown);
  }, []);

  const search = useQuery({
    queryKey: ["global-search", debounced],
    queryFn: () => getGlobalSearch(debounced),
    enabled: debounced.length > 0,
    staleTime: 15_000,
    retry: false,
  });
  const groups = search.data ?? [];
  const showPanel = open && debounced.length > 0;

  const pick = (url: string) => {
    setOpen(false);
    setInput("");
    navigate(url);
  };

  return (
    <div className={styles.searchWrap}>
      <input
        aria-label="全局搜索"
        className={styles.searchInput}
        onBlur={() => window.setTimeout(() => setOpen(false), 150)}
        onChange={(event) => { setInput(event.target.value); setOpen(true); }}
        onFocus={() => setOpen(true)}
        onKeyDown={(event) => {
          if (event.key === "Escape") setOpen(false);
          if (event.key === "Enter") {
            const first = groups[0]?.items[0];
            if (first) pick(first.url);
          }
        }}
        placeholder="搜索股票 / 板块 / 行业（⌘K）"
        ref={inputRef}
        value={input}
      />
      {showPanel ? (
        <div className={styles.searchPanel} role="listbox">
          {search.isPending ? <div className={styles.searchHint}>搜索中…</div> : null}
          {!search.isPending && groups.length === 0 ? <div className={styles.searchHint}>没有匹配结果</div> : null}
          {groups.map((group) => (
            <div key={group.key}>
              <div className={styles.searchGroupLabel}>{group.label}</div>
              {group.items.map((item) => (
                <button
                  className={styles.searchItem}
                  key={`${group.key}-${item.id}`}
                  onClick={() => pick(item.url)}
                  type="button"
                >
                  <strong>{item.title}</strong>
                  {item.subtitle ? <span>{item.subtitle}</span> : null}
                </button>
              ))}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}
