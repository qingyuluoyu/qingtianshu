import { useCallback, useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getBacktestResult,
  getLiZongStrategy,
  getObservationPool,
  getStrategyCandidates,
  getStrategyHistory,
  getStrategyTriggers,
  runStrategy,
} from "./api";
import { strategiesQueries } from "./queries";
import styles from "./StrategiesPage.module.css";

type TabKey = "overview" | "candidates" | "observation" | "history" | "backtest" | "triggers";

type Props = { authenticated: boolean };

function percent(value: number | null): string {
  if (value === null) return "暂无";
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function tone(value: number | null): string {
  if (value === null || value === 0) return styles.flat;
  return value > 0 ? styles.up : styles.down;
}

export function StrategiesPage({ authenticated }: Props) {
  const [tab, setTab] = useState<TabKey>("overview");
  const [message, setMessage] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const strategy = useQuery(strategiesQueries.strategy());
  const candidates = useQuery(strategiesQueries.candidates(30));
  const pool = useQuery(strategiesQueries.observationPool(50));
  const history = useQuery(strategiesQueries.history(20));
  const backtest = useQuery(strategiesQueries.backtest("1y"));
  const triggers = useQuery(strategiesQueries.triggers(20));

  useEffect(() => { setTab("overview"); }, [strategy.data?.id]);

  const handleRun = useCallback(async () => {
    setMessage(null);
    try {
      const result = await runStrategy();
      if (!result?.runId) {
        setMessage("启动失败，请重试");
        return;
      }
      setMessage(`策略运行已启动：${result.runId}`);
      await queryClient.invalidateQueries({ queryKey: ["strategies"] });
    } catch {
      setMessage("启动失败，请重试");
    }
  }, [queryClient]);

  const tabs: { key: TabKey; label: string }[] = [
    { key: "overview", label: "概览" },
    { key: "candidates", label: "候选" },
    { key: "observation", label: "观察池" },
    { key: "history", label: "历史" },
    { key: "backtest", label: "回测" },
    { key: "triggers", label: "触发" },
  ];

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["strategies"] });
  };

  if (!authenticated) {
    return (
      <div className={styles.page}>
        <header className={styles.hero}><h1>策略监控</h1><p>请登录后查看策略运行状态与候选股票。</p></header>
      </div>
    );
  }

  return (
    <div className={styles.page}>
      <header className={styles.hero}>
        <div>
          <h1>策略监控</h1>
          <p>李总策略运行状态、候选股票、历史回测与触发记录。</p>
        </div>
        <div className={styles.heroActions}>
          <button className={styles.refreshBtn} onClick={refresh} type="button">刷新</button>
          <button className={styles.runBtn} disabled={strategy.isPending} onClick={handleRun} type="button">
            {strategy.isPending ? "运行中…" : "启动策略"}
          </button>
        </div>
      </header>

      {message ? <div className={styles.message} role="status">{message}</div> : null}

      <nav className={styles.tabs} aria-label="策略标签">
        {tabs.map((t) => (
          <button
            aria-selected={tab === t.key}
            className={tab === t.key ? styles.tabActive : styles.tab}
            key={t.key}
            onClick={() => setTab(t.key)}
            type="button"
          >
            {t.label}
          </button>
        ))}
      </nav>

      {tab === "overview" && (
        <section className={styles.card}>
          {strategy.isPending ? <div className={styles.loading}>正在读取…</div> : strategy.isError ? (
            <div className={styles.error}>策略信息暂时不可用。</div>
          ) : strategy.data ? (
            <div className={styles.overview}>
              <h2>{strategy.data.name}</h2>
              <p>{strategy.data.description ?? "李总精选策略"}</p>
              <div className={styles.metaGrid}>
                <div><span>状态</span><strong>{strategy.data.status ?? "—"}</strong></div>
                <div><span>候选数</span><strong>{strategy.data.candidateCount ?? "—"}</strong></div>
                <div><span>上次运行</span><strong>{strategy.data.lastRunAt ? new Date(strategy.data.lastRunAt).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai" }) : "—"}</strong></div>
              </div>
            </div>
          ) : (
            <div className={styles.empty}>暂无策略信息</div>
          )}
        </section>
      )}

      {tab === "candidates" && (
        <section className={styles.card}>
          <h2>候选股票 ({candidates.data?.length ?? 0})</h2>
          {candidates.isPending ? <div className={styles.loading}>正在读取…</div> : candidates.isError ? (
            <div className={styles.error}>候选列表暂时不可用。</div>
          ) : candidates.data?.length === 0 ? (
            <div className={styles.empty}>暂无候选股票</div>
          ) : (
            <div className={styles.tableWrap}>
              <table className={styles.table}>
                <thead><tr><th>代码</th><th>名称</th><th>状态</th><th>评分</th></tr></thead>
                <tbody>
                  {candidates.data?.map((c) => (
                    <tr key={c.symbol}>
                      <td><a className={styles.link} href={`/stocks/${encodeURIComponent(c.symbol)}`}>{c.symbol}</a></td>
                      <td>{c.name}</td>
                      <td><span className={`${styles.tag} ${c.status === "qualified" ? styles.tagOk : ""}`}>{c.status}</span></td>
                      <td>{c.score ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}

      {tab === "observation" && (
        <section className={styles.card}>
          <h2>观察池 ({pool.data?.length ?? 0})</h2>
          {pool.isPending ? <div className={styles.loading}>正在读取…</div> : pool.isError ? (
            <div className={styles.error}>观察池暂时不可用。</div>
          ) : pool.data?.length === 0 ? (
            <div className={styles.empty}>观察池为空</div>
          ) : (
            <div className={styles.tableWrap}>
              <table className={styles.table}>
                <thead><tr><th>代码</th><th>名称</th><th>加入时间</th></tr></thead>
                <tbody>
                  {pool.data?.map((item) => (
                    <tr key={item.symbol}>
                      <td><a className={styles.link} href={`/stocks/${encodeURIComponent(item.symbol)}`}>{item.symbol}</a></td>
                      <td>{item.name}</td>
                      <td>{item.addedAt ? new Date(item.addedAt).toLocaleDateString("zh-CN") : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}

      {tab === "history" && (
        <section className={styles.card}>
          <h2>运行历史 ({history.data?.length ?? 0})</h2>
          {history.isPending ? <div className={styles.loading}>正在读取…</div> : history.isError ? (
            <div className={styles.error}>历史记录暂时不可用。</div>
          ) : history.data?.length === 0 ? (
            <div className={styles.empty}>暂无运行历史</div>
          ) : (
            <div className={styles.tableWrap}>
              <table className={styles.table}>
                <thead><tr><th>运行ID</th><th>状态</th><th>开始时间</th><th>结束时间</th><th>候选数</th><th>达标数</th></tr></thead>
                <tbody>
                  {history.data?.map((r) => (
                    <tr key={r.id}>
                      <td className={styles.mono}>{r.id}</td>
                      <td>{r.status ?? "—"}</td>
                      <td>{r.startedAt ? new Date(r.startedAt).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai" }) : "—"}</td>
                      <td>{r.finishedAt ? new Date(r.finishedAt).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai" }) : "—"}</td>
                      <td>{r.candidatesFound ?? "—"}</td>
                      <td>{r.qualifiedCount ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}

      {tab === "backtest" && (
        <section className={styles.card}>
          <h2>回测结果（近1年）</h2>
          {backtest.isPending ? <div className={styles.loading}>正在读取…</div> : backtest.isError ? (
            <div className={styles.error}>回测结果暂时不可用。</div>
          ) : backtest.data ? (
            <div className={styles.backtestGrid}>
              <div className={styles.metric}><span>总收益</span><b className={tone(backtest.data.totalReturnPct)}>{percent(backtest.data.totalReturnPct)}</b></div>
              <div className={styles.metric}><span>基准收益</span><b className={tone(backtest.data.benchmarkReturnPct)}>{percent(backtest.data.benchmarkReturnPct)}</b></div>
              <div className={styles.metric}><span>状态</span><strong>{backtest.data.status ?? "—"}</strong></div>
            </div>
          ) : (
            <div className={styles.empty}>暂无回测数据</div>
          )}
        </section>
      )}

      {tab === "triggers" && (
        <section className={styles.card}>
          <h2>触发记录 ({triggers.data?.length ?? 0})</h2>
          {triggers.isPending ? <div className={styles.loading}>正在读取…</div> : triggers.isError ? (
            <div className={styles.error}>触发记录暂时不可用。</div>
          ) : triggers.data?.length === 0 ? (
            <div className={styles.empty}>暂无触发记录</div>
          ) : (
            <div className={styles.tableWrap}>
              <table className={styles.table}>
                <thead><tr><th>代码</th><th>名称</th><th>触发类型</th><th>触发时间</th><th>状态</th></tr></thead>
                <tbody>
                  {triggers.data?.map((t) => (
                    <tr key={t.id}>
                      <td>{t.symbol ?? "—"}</td>
                      <td>{t.name ?? "—"}</td>
                      <td>{t.triggerType ?? "—"}</td>
                      <td>{t.triggeredAt ? new Date(t.triggeredAt).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai" }) : "—"}</td>
                      <td>{t.status ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
