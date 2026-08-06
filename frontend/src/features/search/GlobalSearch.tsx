import { useEffect, useId, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { getGlobalSearch } from "../../api/search";
import styles from "../../components/AppShell.module.css";

export function GlobalSearch() {
  const [input, setInput] = useState("");
  const [debounced, setDebounced] = useState("");
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState<number | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const listboxId = useId();
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
  const items = useMemo(
    () => groups.flatMap((group) => group.items.map((item) => ({ ...item, groupKey: group.key }))),
    [groups],
  );
  const showPanel = open && debounced.length > 0;
  const activeItem = activeIndex === null ? null : items[activeIndex] ?? null;
  const activeOptionId = activeItem
    ? `global-search-option-${activeItem.groupKey.replace(/[^a-zA-Z0-9_-]/g, "-")}-${activeItem.id.replace(/[^a-zA-Z0-9_-]/g, "-")}`
    : undefined;

  useEffect(() => setActiveIndex(null), [debounced]);

  useEffect(() => {
    if (activeIndex !== null && activeIndex >= items.length) setActiveIndex(null);
  }, [activeIndex, items.length]);

  const pick = (url: string) => {
    setOpen(false);
    setActiveIndex(null);
    setInput("");
    navigate(url);
  };

  return (
    <div className={styles.searchWrap}>
      <input
        aria-activedescendant={activeOptionId}
        aria-autocomplete="list"
        aria-controls={listboxId}
        aria-expanded={showPanel}
        aria-label="全局搜索"
        className={styles.searchInput}
        onBlur={() => window.setTimeout(() => { setOpen(false); setActiveIndex(null); }, 150)}
        onChange={(event) => { setInput(event.target.value); setOpen(true); setActiveIndex(null); }}
        onFocus={() => setOpen(true)}
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            setOpen(false);
            setActiveIndex(null);
          }
          if (event.key === "ArrowDown" && items.length > 0) {
            event.preventDefault();
            setActiveIndex((index) => Math.min((index ?? -1) + 1, items.length - 1));
          }
          if (event.key === "ArrowUp" && items.length > 0) {
            event.preventDefault();
            setActiveIndex((index) => Math.max((index ?? 0) - 1, 0));
          }
          if (event.key === "Enter" && activeIndex !== null) {
            event.preventDefault();
            const selected = items[activeIndex];
            if (selected) pick(selected.url);
          }
        }}
        placeholder="搜索股票 / 板块 / 行业（⌘K）"
        ref={inputRef}
        role="combobox"
        value={input}
      />
      {showPanel ? (
        <div className={styles.searchPanel} id={listboxId} role="listbox">
          {search.isPending ? <div className={styles.searchHint}>搜索中…</div> : null}
          {!search.isPending && groups.length === 0 ? <div className={styles.searchHint}>没有匹配结果</div> : null}
          {groups.map((group) => (
            <div key={group.key}>
              <div className={styles.searchGroupLabel}>{group.label}</div>
              {group.items.map((item) => (
                <button
                  aria-selected={activeOptionId === `global-search-option-${group.key.replace(/[^a-zA-Z0-9_-]/g, "-")}-${item.id.replace(/[^a-zA-Z0-9_-]/g, "-")}`}
                  className={styles.searchItem}
                  id={`global-search-option-${group.key.replace(/[^a-zA-Z0-9_-]/g, "-")}-${item.id.replace(/[^a-zA-Z0-9_-]/g, "-")}`}
                  key={`${group.key}-${item.id}`}
                  onClick={() => pick(item.url)}
                  onMouseEnter={() => setActiveIndex(items.findIndex((candidate) => candidate.groupKey === group.key && candidate.id === item.id))}
                  role="option"
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
