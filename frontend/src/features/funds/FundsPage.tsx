import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { searchFunds, listFunds, type FundItem } from "./api";
import { fundsQueries } from "./queries";
import styles from "./FundsPage.module.css";

type Props = { authenticated: boolean };

function percent(value: number | null): string {
  if (value === null) return "暂无";
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function tone(value: number | null): string {
  if (value === null || value === 0) return styles.flat;
  return value > 0 ? styles.up : styles.down;
}

function FundRow({ item }: { item: FundItem }) {
  return (
    <tr className={styles.row}>
      <td className={styles.code}>{item.code}</td>
      <td className={styles.name}>{item.name}</td>
      <td className={styles.category}>{item.category ?? "—"}</td>
      <td className={styles.nav}>{item.nav === null ? "暂无" : item.nav.toFixed(4)}</td>
      <td className={tone(item.pctChange)}>{percent(item.pctChange)}</td>
    </tr>
  );
}

export function FundsPage({ authenticated }: Props) {
  const [searchParams, setSearchParams] = useSearchParams();
  const query = searchParams.get("q") ?? "";
  const [input, setInput] = useState(query);

  useEffect(() => { setInput(query); }, [query]);

  const list = useQuery(fundsQueries.list(50));
  const searchResult = useQuery({
    queryKey: ["funds", "search", query, 30],
    queryFn: () => searchFunds(query, 30),
    enabled: query.length > 0,
    staleTime: 60_000,
    retry: false,
  });

  const items: FundItem[] = query.length > 0 ? (searchResult.data ?? []) : (list.data ?? []);
  const pending = query.length > 0 ? searchResult.isPending : list.isPending;
  const error = query.length > 0 ? searchResult.isError : list.isError;

  const refresh = () => {
    void list.refetch();
    if (query.length > 0) void searchResult.refetch();
  };

  const onSearch = (e: React.FormEvent) => {
    e.preventDefault();
    const q = input.trim();
    if (q) setSearchParams({ q });
    else setSearchParams({});
  };

  return (
    <div className={styles.page}>
      <header className={styles.hero}>
        <div>
          <h1>基金产品</h1>
          <p>搜索和浏览基金产品净值与涨跌幅。</p>
        </div>
        <form className={styles.searchForm} onSubmit={onSearch}>
          <input
            aria-label="搜索基金"
            className={styles.searchInput}
            onChange={(e) => setInput(e.target.value)}
            placeholder="输入基金代码或名称…"
            value={input}
          />
          <button className={styles.searchBtn} type="submit">搜索</button>
        </form>
      </header>

      <div className={styles.toolbar}>
        <span className={styles.count}>{items.length} 只基金</span>
        <button className={styles.refreshBtn} onClick={() => void refresh()} type="button">刷新</button>
      </div>

      {pending ? (
        <div className={styles.loading} aria-live="polite">正在读取…</div>
      ) : error ? (
        <div className={styles.error} role="status">
          <span>基金数据暂时不可用。</span>
          <button onClick={() => void refresh()} type="button">重新读取</button>
        </div>
      ) : items.length === 0 ? (
        <div className={styles.empty}>暂无基金数据</div>
      ) : (
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead><tr><th>代码</th><th>名称</th><th>分类</th><th>净值</th><th>涨跌幅</th></tr></thead>
            <tbody>{items.map((item) => <FundRow key={item.code} item={item} />)}</tbody>
          </table>
        </div>
      )}
    </div>
  );
}
