import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useNavigate, useSearchParams } from "react-router-dom";
import type {
  LiZongCandidate,
  LiZongCandidates,
  LiZongRunLatest,
  ScreenItem,
  ScreenerProfile,
  StockScreen,
} from "./adapters";
import {
  startDeepStockResearch,
  type BacktestPeriod,
  type DeepStockEntryContext,
  type LiZongStatusFilter,
  type ScreenParams,
} from "./api";
import { screeningQueries } from "./queries";
import styles from "./ScreeningPage.module.css";

type Props = { authenticated: boolean };

// ---------- 格式化助手（直通原则：百分数不缩放） ----------

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "时间待确认";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "时间待确认";
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

function formatDate(value: string | null | undefined): string {
  if (!value) return "日期待确认";
  return value.slice(0, 10);
}

function formatNumber(value: number | null, digits = 2): string {
  if (value === null) return "--";
  return new Intl.NumberFormat("zh-CN", { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(value);
}

/** 后端已是百分数的字段直通加 %，不缩放。 */
function percent(value: number | null): string {
  if (value === null) return "--";
  return `${value > 0 ? "+" : ""}${formatNumber(value)}%`;
}

function signedTone(value: number | null): string {
  if (value === null || value === 0) return styles.flat;
  return value > 0 ? styles.up : styles.down;
}

/** coverage_ratio 等后端比例为原值直通（0~1），不换算成百分数。 */
function ratio(value: number | null): string {
  if (value === null) return "--";
  return formatNumber(value, 4);
}

// ---------- 状态翻译（合同 §6.3，只翻译后端状态，不自行推断） ----------

function statusLabel(status: string): string {
  return ({
    available: "数据完整",
    ready: "数据完整",
    complete: "覆盖完整",
    stable: "覆盖稳定",
    sufficient: "证据充分",
    constrained: "覆盖受限",
    partial: "部分数据可用",
    insufficient: "数据不足",
    unavailable: "当前不可用",
    pending_confirmation: "待确认草稿",
    waiting_data: "等待数据",
    stale: "内容已过期",
    ended: "已结束",
    paused: "已暂停",
    empty: "暂无数据",
    running: "执行中",
  } as Record<string, string>)[status] ?? status;
}

function statusTone(status: string): string {
  if (["available", "ready", "sufficient", "complete", "stable"].includes(status)) return styles.badgeReady;
  if (["partial", "insufficient", "constrained"].includes(status)) return styles.badgePartial;
  if (["pending_confirmation", "waiting_data", "running"].includes(status)) return styles.badgeWaiting;
  if (status === "stale") return styles.badgeStale;
  return styles.badgeUnavailable;
}

function candidateStatusLabel(status: string | null): string {
  if (status === null) return "状态待确认";
  return ({
    qualified: "通过",
    triggered: "已触发",
    not_qualified: "未通过",
    data_incomplete: "数据不足",
    invalidated: "已失效",
  } as Record<string, string>)[status] ?? status;
}

function candidateStatusTone(status: string | null): string {
  if (status === "qualified" || status === "triggered") return styles.badgeReady;
  if (status === "data_incomplete") return styles.badgePartial;
  if (status === "invalidated") return styles.badgeStale;
  return styles.badgeUnavailable;
}

function ruleStatusLabel(status: string | null): string {
  if (status === null) return "状态待确认";
  return ({ passed: "通过", failed: "未通过", data_incomplete: "数据不足" } as Record<string, string>)[status] ?? status;
}

function ruleStatusTone(status: string | null): string {
  if (status === "passed") return styles.badgeReady;
  if (status === "data_incomplete") return styles.badgePartial;
  return styles.badgeUnavailable;
}

function screenFieldLabel(field: string): string {
  return ({
    revenue_yoy: "营收同比",
    net_profit_yoy: "净利润同比",
    roe: "ROE",
    gross_margin: "毛利率",
    net_margin: "净利率",
    debt_to_assets: "资产负债率",
    pe_ttm: "PE TTM",
    pb: "PB",
    ps_ttm: "PS TTM",
    volume_ratio: "量比",
    turnover_rate_pct: "换手率",
  } as Record<string, string>)[field] ?? field;
}

function screenResearchFocus(screen: StockScreen, item: ScreenItem): string {
  if (item.researchFocus) return item.researchFocus;
  if (item.matchedReasons.length > 0) {
    return `先核验“${item.matchedReasons[0]}”，再检查财务、公告、行业对照和反方证据。`;
  }
  return `逐条核验${item.name ?? item.symbol}命中当前筛选条件的证据、反方事实和数据缺口。`;
}

function screenEntryContext(screen: StockScreen, item: ScreenItem): DeepStockEntryContext {
  return {
    source_kind: "stock_screen",
    source_label: screen.profile.label ?? "透明选股",
    display_name: item.name,
    industry: item.industry,
    profile_key: screen.profile.key || null,
    as_of_date: item.evidenceTimes.marketDate ?? screen.dataContract.marketDate,
    candidate_status: screen.status,
    matched_reasons: item.matchedReasons,
    research_focus: screenResearchFocus(screen, item),
    attention_flags: item.attentionFlags.slice(0, 4),
    missing_fields: item.missingFields.map(screenFieldLabel).slice(0, 8),
  };
}

function liZongEntryContext(data: LiZongCandidates, candidate: LiZongCandidate): DeepStockEntryContext {
  const ruleLabels = new Map(data.rules.map((rule) => [rule.ruleId, rule.label]));
  const missingRules = candidate.ruleResults
    .filter((rule) => rule.status !== "passed" && rule.ruleId)
    .map((rule) => ruleLabels.get(rule.ruleId ?? "") ?? rule.ruleId ?? "规则待核验");
  const missingFields = [...new Set([...missingRules, ...candidate.limitations])].slice(0, 8);
  const name = candidate.name ?? candidate.symbol;
  return {
    source_kind: "li_zong_strategy",
    source_label: data.strategyName ?? "李总策略规则快照",
    display_name: candidate.name,
    industry: candidate.industry,
    profile_key: "li_zong",
    as_of_date: candidate.asOfDate ?? data.dataMeta.latestAsOfDate,
    candidate_status: candidate.status,
    matched_reasons: candidate.matchedReasons,
    research_focus: `逐条核验${name}当前“${candidateStatusLabel(candidate.status)}”结果的基本面、股性、量价和触发规则，并检查反方证据。`,
    attention_flags: candidate.triggeredRuleIds.slice(0, 4).map((rule) => `触发规则 ${rule} 需要人工复核`),
    missing_fields: missingFields,
  };
}

// ---------- 通用卡片 ----------

function ModuleCard({ title, meta, pending, error, onRetry, children }: {
  title: string;
  meta?: ReactNode;
  pending?: boolean;
  error?: boolean;
  onRetry?: () => void;
  children: ReactNode;
}) {
  return (
    <section className={styles.card} aria-label={title}>
      <div className={styles.cardHeader}>
        <h2>{title}</h2>
        {meta ? <div className={styles.meta}>{meta}</div> : null}
      </div>
      {pending ? <div className={styles.skeleton} aria-live="polite">正在读取…</div> : null}
      {!pending && error ? (
        <div className={styles.moduleError} role="status">
          <span>本模块暂时不可用，其他内容仍可继续查看。</span>
          {onRetry ? <button type="button" onClick={onRetry}>重新读取</button> : null}
        </div>
      ) : null}
      {!pending && !error ? children : null}
    </section>
  );
}

// ---------- 模式卡片（§5.2：三种模式互斥，不混在一个表格） ----------

const MODES = [
  { key: "screen", label: "通用筛选", hint: "透明规则条件 + 命中候选，解释每条规则与漏斗口径。" },
  { key: "lizong", label: "李总指标筛选", hint: "李总策略快照候选：通过 / 未通过 / 数据不足 + 命中理由与缺失字段。" },
  { key: "backtest", label: "历史复盘 / 回测", hint: "仅展示服务端已完成的回测结果，未完成时显示真实进度与空态。" },
] as const;

type ModeKey = (typeof MODES)[number]["key"];

function ScreeningModeCards({ active, onSelect }: { active: ModeKey; onSelect: (mode: ModeKey) => void }) {
  return (
    <div className={styles.modeGrid} role="group" aria-label="选股模式">
      {MODES.map(({ key, label, hint }) => (
        <button
          aria-pressed={active === key}
          className={styles.modeCard}
          key={key}
          onClick={() => onSelect(key)}
          type="button"
        >
          <span>{label}</span>
          <small>{hint}</small>
        </button>
      ))}
    </div>
  );
}

// ---------- 通用筛选：条件面板 ----------

const FILTER_LABELS: Record<string, string> = {
  min_market_cap_yi: "总市值下限（亿元）",
  max_market_cap_yi: "总市值上限（亿元）",
  min_pe_ttm: "PE TTM 下限",
  max_pe_ttm: "PE TTM 上限",
  min_pb: "PB 下限",
  max_pb: "PB 上限",
  min_revenue_yoy: "营收同比下限（%）",
  min_net_profit_yoy: "净利润同比下限（%）",
  min_roe: "ROE 下限（%）",
  min_return_5d: "近 5 日收益下限（%）",
  min_return_20d: "近 20 日收益下限（%）",
  max_return_20d: "近 20 日收益上限（%）",
  min_industry_excess_20d: "近 20 日行业超额下限（%）",
  min_volume_ratio: "量比下限",
  min_turnover_rate: "换手率下限（%）",
  max_turnover_rate: "换手率上限（%）",
  min_listed_days: "上市天数下限（自然日）",
};

const MARKETS = [
  { key: "all", label: "全部市场" },
  { key: "sh", label: "上海" },
  { key: "sz", label: "深圳" },
  { key: "bj", label: "北京" },
  { key: "main", label: "主板" },
  { key: "gem", label: "创业板" },
  { key: "star", label: "科创板" },
] as const;

const MAX_RESULT_OPTIONS = [12, 20, 30] as const;

function FilterBuilder({ profiles, applied, onApply, disabled }: {
  profiles: ScreenerProfile[];
  applied: ScreenParams;
  onApply: (next: ScreenParams) => void;
  disabled: boolean;
}) {
  const appliedKey = JSON.stringify(applied);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [draftMarket, setDraftMarket] = useState(applied.market);
  const [draftMaxResults, setDraftMaxResults] = useState(String(applied.maxResults));
  const [draftError, setDraftError] = useState<string | null>(null);

  useEffect(() => {
    const parsed = JSON.parse(appliedKey) as ScreenParams;
    const next: Record<string, string> = {};
    for (const [key, value] of Object.entries(parsed.filters)) next[key] = String(value);
    setDraft(next);
    setDraftMarket(parsed.market);
    setDraftMaxResults(String(parsed.maxResults));
    setDraftError(null);
  }, [appliedKey]);

  const profile = profiles.find((item) => item.key === applied.profile) ?? null;
  const filterKeys = Object.keys(profile?.defaultFilters ?? applied.filters);

  const handleApply = () => {
    const filters: Record<string, number> = {};
    for (const key of filterKeys) {
      const raw = (draft[key] ?? "").trim();
      const value = Number(raw);
      if (raw === "" || !Number.isFinite(value)) {
        setDraftError(`「${FILTER_LABELS[key] ?? key}」需要填写数字；空值不是有效阈值。`);
        return;
      }
      filters[key] = value;
    }
    setDraftError(null);
    onApply({
      profile: applied.profile,
      market: draftMarket,
      maxResults: Number(draftMaxResults),
      filters,
    });
  };

  return (
    <ModuleCard meta={profile ? `排序口径：${profile.sortRule ?? "待确认"}` : undefined} title="筛选条件">
      {profile?.description ? <p className={styles.helper} style={{ marginTop: 0 }}>{profile.description}</p> : null}
      <div className={styles.filterGrid}>
        <label className={styles.filterField}>
          <span>筛选档案</span>
          <select
            aria-label="筛选档案"
            onChange={(event) => onApply({ ...applied, profile: event.target.value, filters: {} })}
            value={applied.profile}
          >
            {profiles.map((item) => <option key={item.key} value={item.key}>{item.label ?? item.key}</option>)}
          </select>
        </label>
        <label className={styles.filterField}>
          <span>市场范围</span>
          <select aria-label="市场范围" onChange={(event) => setDraftMarket(event.target.value)} value={draftMarket}>
            {MARKETS.map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}
          </select>
        </label>
        <label className={styles.filterField}>
          <span>展示条数（服务端上限，非分页）</span>
          <select aria-label="展示条数" onChange={(event) => setDraftMaxResults(event.target.value)} value={draftMaxResults}>
            {MAX_RESULT_OPTIONS.map((value) => <option key={value} value={value}>前 {value} 条</option>)}
          </select>
        </label>
        {filterKeys.map((key) => (
          <label className={styles.filterField} key={key}>
            <span>{FILTER_LABELS[key] ?? key}</span>
            <input
              aria-label={FILTER_LABELS[key] ?? key}
              inputMode="decimal"
              onChange={(event) => setDraft((current) => ({ ...current, [key]: event.target.value }))}
              value={draft[key] ?? ""}
            />
          </label>
        ))}
      </div>
      <div className={styles.filterActions}>
        <button className={styles.applyButton} disabled={disabled} onClick={handleApply} type="button">
          应用筛选
        </button>
        <span className={styles.meta}>阈值原样提交服务端；生效口径以结果中的 effective_filters 为准。</span>
      </div>
      {draftError ? <p className={styles.helper} role="alert">{draftError}</p> : null}
    </ModuleCard>
  );
}

// ---------- 通用筛选：结果摘要 ----------

function ScreenRunSummary({ screen }: { screen: StockScreen }) {
  const matched = screen.universe.matched;
  const coverageStatus = screen.dataContract.coverageStatus;
  return (
    <ModuleCard
      meta={`数据日期：${formatDate(screen.dataContract.marketDate)} · 生成时间：${formatDateTime(screen.dataContract.generatedAt)}`}
      title="本轮筛选摘要"
    >
      <div className={styles.chipRow}>
        <span className={`${styles.badge} ${statusTone(screen.status)}`}>{statusLabel(screen.status)}</span>
        {coverageStatus ? (
          <span className={`${styles.badge} ${statusTone(coverageStatus)}`}>{statusLabel(coverageStatus)}</span>
        ) : null}
        {screen.universe.representsFullMarket === false ? (
          <span className={`${styles.badge} ${styles.badgePartial}`}>不代表全市场</span>
        ) : null}
      </div>
      <div className={styles.metricGrid} style={{ marginTop: 12 }}>
        <div className={styles.metric}>
          <span>命中候选（真实总数）</span>
          <strong>{matched ?? "--"}</strong>
          <small>展示前 {screen.items.length} 条 · {screen.profile.sortRule ?? "排序口径待确认"}</small>
        </div>
        <div className={styles.metric}>
          <span>行情覆盖（原始比例直通）</span>
          <strong>{screen.universe.marketCoverage !== null && screen.universe.expectedListed !== null
            ? `${screen.universe.marketCoverage} / ${screen.universe.expectedListed}` : "--"}</strong>
          <small>{screen.dataContract.actualScopeLabel ?? "口径说明待确认"}</small>
        </div>
        <div className={styles.metric}>
          <span>财务报告期</span>
          <strong>{screen.dataContract.financialReportPeriods.length > 0 ? screen.dataContract.financialReportPeriods.join("、") : "--"}</strong>
          <small>财务指标不与行情交易日混用</small>
        </div>
      </div>
      {screen.dataContract.representationNote ? <p className={styles.helper}>{screen.dataContract.representationNote}</p> : null}
      {screen.warnings.map((warning) => <p className={styles.helper} key={warning}>注意：{warning}</p>)}
    </ModuleCard>
  );
}

// ---------- 通用筛选：候选表与详情 ----------

function screenItemStatus(item: ScreenItem): { label: string; tone: string } {
  // 通用筛选只返回命中项；命中但带缺失字段 = 数据不足（后端 missing_fields 直通），与完整命中区分。
  if (item.missingFields.length > 0) return { label: "数据不足", tone: styles.badgePartial };
  return { label: "通过", tone: styles.badgeReady };
}

function ScreenCandidateTable({ items, selectedSymbol, onSelect }: {
  items: ScreenItem[];
  selectedSymbol: string | null;
  onSelect: (symbol: string) => void;
}) {
  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>代码</th>
            <th>名称</th>
            <th>收盘</th>
            <th>涨跌</th>
            <th>总市值（亿）</th>
            <th>PE TTM</th>
            <th>近 5 日</th>
            <th>近 20 日</th>
            <th>状态</th>
            <th>命中理由</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => {
            const status = screenItemStatus(item);
            return (
              <tr
                aria-selected={selectedSymbol === item.symbol}
                key={item.symbol}
                onClick={() => onSelect(item.symbol)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    onSelect(item.symbol);
                  }
                }}
                tabIndex={0}
              >
                <td className={styles.symbolCell}>
                  <strong>{item.symbol}</strong>
                  <small>{item.market ?? "市场待确认"}</small>
                </td>
                <td className={styles.symbolCell}>
                  <strong>{item.name ?? "名称待确认"}</strong>
                  <small>{item.industry ?? "行业待确认"}</small>
                </td>
                <td>{formatNumber(item.metrics.latestClose)}</td>
                <td className={signedTone(item.metrics.pctChange)}>{percent(item.metrics.pctChange)}</td>
                <td>{formatNumber(item.metrics.totalMvYi)}</td>
                <td>{formatNumber(item.metrics.peTtm)}</td>
                <td className={signedTone(item.metrics.return5dPct)}>{percent(item.metrics.return5dPct)}</td>
                <td className={signedTone(item.metrics.return20dPct)}>{percent(item.metrics.return20dPct)}</td>
                <td><span className={`${styles.badge} ${status.tone}`}>{status.label}</span></td>
                <td className={styles.reasonCell}>
                  <span>{item.matchedReasons.length > 0
                    ? `${item.matchedReasons[0]}${item.matchedReasons.length > 1 ? ` 等 ${item.matchedReasons.length} 条` : ""}`
                    : "命中理由待确认"}</span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function coverageLabel(status: string | null): string {
  if (status === null) return "待确认";
  return statusLabel(status);
}

function ScreenCandidateDetail({ item, onResearch, researchError, researchPending }: {
  item: ScreenItem;
  onResearch: (item: ScreenItem) => void;
  researchError: string | null;
  researchPending: boolean;
}) {
  const status = screenItemStatus(item);
  return (
    <ModuleCard
      meta={`数据日期：${formatDate(item.evidenceTimes.marketDate)}`}
      title={`${item.name ?? item.symbol} 候选详情`}
    >
      <div className={styles.chipRow}>
        <span className={`${styles.badge} ${status.tone}`}>{status.label}</span>
        <span className={styles.meta}>{item.symbol}{item.industry ? ` · ${item.industry}` : ""}</span>
      </div>
      <div className={styles.metricGrid} style={{ marginTop: 12 }}>
        <div className={styles.metric}><span>最新收盘</span><strong>{formatNumber(item.metrics.latestClose)}</strong><small>最近完整交易日日线</small></div>
        <div className={styles.metric}><span>涨跌幅</span><strong className={signedTone(item.metrics.pctChange)}>{percent(item.metrics.pctChange)}</strong><small>百分数直通</small></div>
        <div className={styles.metric}><span>总市值（亿）</span><strong>{formatNumber(item.metrics.totalMvYi)}</strong><small>流通市值 {formatNumber(item.metrics.circMvYi)} 亿</small></div>
        <div className={styles.metric}><span>PE TTM / PB</span><strong>{formatNumber(item.metrics.peTtm)} / {formatNumber(item.metrics.pb)}</strong><small>估值与最近完整交易日对齐</small></div>
        <div className={styles.metric}><span>换手率 / 量比</span><strong>{percent(item.metrics.turnoverRatePct)} / {formatNumber(item.metrics.volumeRatio)}</strong><small>活跃度口径</small></div>
        <div className={styles.metric}><span>近 20 日行业超额</span><strong className={signedTone(item.metrics.industryExcess20dPct)}>{percent(item.metrics.industryExcess20dPct)}</strong><small>行业均值 {percent(item.metrics.industryAvgReturn20dPct)}</small></div>
      </div>
      {item.financials ? (
        <>
          <h3 style={{ margin: "16px 0 6px", fontSize: 13 }}>财务摘要（报告期：{item.financials.reportPeriod ?? "待确认"}）</h3>
          <div className={styles.metricGrid}>
            <div className={styles.metric}><span>营收同比</span><strong className={signedTone(item.financials.revenueYoy)}>{percent(item.financials.revenueYoy)}</strong><small>公告 {formatDate(item.financials.announcementDate)}</small></div>
            <div className={styles.metric}><span>净利润同比</span><strong className={signedTone(item.financials.netProfitYoy)}>{percent(item.financials.netProfitYoy)}</strong><small>覆盖：{coverageLabel(item.financials.coverageStatus)}</small></div>
            <div className={styles.metric}><span>ROE</span><strong>{percent(item.financials.roe)}</strong><small>毛利率 {percent(item.financials.grossMargin)}</small></div>
          </div>
        </>
      ) : (
        <p className={styles.helper}>财务数据不可用；这与数值为 0 不是同一状态。</p>
      )}
      <h3 style={{ margin: "16px 0 6px", fontSize: 13 }}>命中理由</h3>
      {item.matchedReasons.length > 0 ? (
        <div className={styles.itemList}>
          {item.matchedReasons.map((reason) => <article key={reason}><p>{reason}</p></article>)}
        </div>
      ) : <p className={styles.helper}>命中理由待确认。</p>}
      {item.missingFields.length > 0 ? (
        <>
          <h3 style={{ margin: "16px 0 6px", fontSize: 13 }}>缺失字段</h3>
          <p className={styles.helper}>{item.missingFields.join("、")}</p>
          {item.missingReasons.map((reason) => <p className={styles.helper} key={reason}>{reason}</p>)}
        </>
      ) : null}
      {item.limitations.map((limitation) => <p className={styles.helper} key={limitation}>限制：{limitation}</p>)}
      <p className={styles.helper}>
        覆盖状态：财务 {coverageLabel(item.coverageStatus.financialQuality)} · 估值 {coverageLabel(item.coverageStatus.valuation)} · 行情 {coverageLabel(item.coverageStatus.marketAndTrend)}
      </p>
      <div className={styles.actionRow}>
        <button className={styles.actionLink} disabled={researchPending} onClick={() => onResearch(item)} type="button">
          {researchPending ? "正在保存研究线索…" : "保存线索并进入个股研究"}
        </button>
      </div>
      {researchError ? <p className={styles.actionError} role="alert">{researchError}</p> : null}
    </ModuleCard>
  );
}

// ---------- 通用筛选：解释面板（规则 + 真实漏斗计数） ----------

function ScreenExplainPanel({ screen }: { screen: StockScreen }) {
  const funnelRows: { label: string; count: number | null }[] = [
    { label: "上市股票输入", count: screen.universe.listedInput },
    { label: "通用规则后（排除 ST / 上市时长）", count: screen.universe.afterCommonRules },
    { label: "市场范围后", count: screen.universe.afterMarketRules },
    { label: "估值覆盖", count: screen.universe.valuationCoverage },
    { label: "财务候选池", count: screen.universe.financialCandidatePool },
    { label: "最终命中", count: screen.universe.matched },
  ].filter((row) => row.count !== null);
  const base = screen.universe.listedInput ?? null;
  return (
    <ModuleCard title="规则与漏斗解释">
      {screen.rules.length > 0 ? (
        <ul className={styles.ruleList}>
          {screen.rules.map((rule, index) => (
            <li key={`${rule.field ?? "rule"}-${index}`}>
              <span className={styles.ruleText}>
                {rule.field ?? "规则"}{rule.operator ? ` ${rule.operator}` : ""}{rule.value !== null ? ` ${rule.value}` : ""}{rule.unit ?? ""}
                {rule.reason ? <small>{rule.reason}</small> : null}
              </span>
            </li>
          ))}
        </ul>
      ) : <div className={styles.empty}>规则说明暂不可用</div>}
      {funnelRows.length > 0 ? (
        <>
          <h3 style={{ margin: "16px 0 6px", fontSize: 13 }}>筛选漏斗（服务端真实计数）</h3>
          <ul className={styles.funnelList}>
            {funnelRows.map((row) => (
              <li key={row.label}>
                <span>{row.label}</span>
                <span className={styles.funnelCount}>{row.count}</span>
                <span className={styles.funnelBar}>
                  <i style={{ width: base !== null && base > 0 && row.count !== null ? `${Math.max(0.5, (row.count / base) * 100)}%` : "0.5%" }} />
                </span>
              </li>
            ))}
          </ul>
        </>
      ) : null}
      {screen.dataContract.contractVersion ? (
        <p className={styles.helper}>数据合同：{screen.dataContract.contractVersion}</p>
      ) : null}
    </ModuleCard>
  );
}

// ---------- 李总模式：run 摘要 ----------

function LiZongRunSummaryCard({ data, pending, error, onRetry }: {
  data: LiZongRunLatest | null;
  pending: boolean;
  error: boolean;
  onRetry: () => void;
}) {
  const run = data?.run ?? null;
  return (
    <ModuleCard
      error={error}
      meta={run ? `数据日期：${formatDate(run.asOfDate)} · 完成：${formatDateTime(run.finishedAt)}` : undefined}
      onRetry={onRetry}
      pending={pending}
      title="最近筛选 Run"
    >
      {run ? (
        <>
          <div className={styles.chipRow}>
            <span className={`${styles.badge} ${statusTone(run.status ?? "unavailable")}`}>{statusLabel(run.status ?? "unavailable")}</span>
            {data?.coverage?.fullMarketCoverage === false ? (
              <span className={`${styles.badge} ${styles.badgePartial}`}>未覆盖全市场</span>
            ) : null}
          </div>
          <div className={styles.metricGrid} style={{ marginTop: 12 }}>
            <div className={styles.metric}><span>评估范围</span><strong>{run.universeCount ?? "--"}</strong><small>预筛后 {run.prefilteredCount ?? "--"} 只</small></div>
            <div className={styles.metric}><span>覆盖率（原始比例直通）</span><strong>{ratio(run.coverageRatio)}</strong><small>待补齐 {data?.coverage?.remainingSymbols ?? "--"} 只</small></div>
            <div className={styles.metric}><span>通过 / 触发</span><strong>{run.qualifiedCount ?? "--"} / {run.triggeredCount ?? "--"}</strong><small>数据不足 {run.incompleteCount ?? "--"} 只</small></div>
          </div>
          {run.warnings.map((warning) => <p className={styles.helper} key={warning}>注意：{warning}</p>)}
          {run.error ? <p className={styles.helper}>错误：{run.error}</p> : null}
        </>
      ) : <div className={styles.empty}>暂无可用的筛选 Run；本页只读取后台已发布快照，不触发新任务。</div>}
    </ModuleCard>
  );
}

// ---------- 李总模式：候选表与规则清单 ----------

const LIZONG_STATUS_CHIPS: { key: LiZongStatusFilter; label: string }[] = [
  { key: null, label: "全部" },
  { key: "qualified", label: "通过" },
  { key: "triggered", label: "已触发" },
  { key: "not_qualified", label: "未通过" },
  { key: "data_incomplete", label: "数据不足" },
];

function liZongRuleStats(candidate: LiZongCandidate, candidateRuleTotal: number): { passed: number; total: number } {
  // 候选规则总数来自策略字典（非 trigger 组）；缺字典时回退到 rule_results 条数。
  const results = candidate.ruleResults.filter((rule) => !rule.ruleId?.startsWith("LZ-T-"));
  const passed = results.filter((rule) => rule.status === "passed").length;
  return { passed, total: candidateRuleTotal > 0 ? candidateRuleTotal : results.length };
}

function liZongGapText(candidate: LiZongCandidate): string {
  const gaps = candidate.ruleResults
    .filter((rule) => rule.status !== null && rule.status !== "passed" && rule.status !== "failed")
    .map((rule) => rule.ruleId)
    .filter((ruleId): ruleId is string => ruleId !== null);
  if (gaps.length > 0) return gaps.join("、");
  if (candidate.limitations.length > 0) return candidate.limitations[0]!;
  return "--";
}

function LiZongCandidateTable({ data, selectedSymbol, onSelect }: {
  data: LiZongCandidates;
  selectedSymbol: string | null;
  onSelect: (symbol: string) => void;
}) {
  const candidateRuleTotal = data.rules.filter((rule) => rule.group !== "trigger").length;
  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>代码</th>
            <th>名称</th>
            <th>状态</th>
            <th>候选规则</th>
            <th>触发规则</th>
            <th>总市值（亿）</th>
            <th>命中理由</th>
            <th>数据缺口</th>
          </tr>
        </thead>
        <tbody>
          {data.items.map((item) => {
            const stats = liZongRuleStats(item, candidateRuleTotal);
            return (
              <tr
                aria-selected={selectedSymbol === item.symbol}
                key={item.symbol}
                onClick={() => onSelect(item.symbol)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    onSelect(item.symbol);
                  }
                }}
                tabIndex={0}
              >
                <td className={styles.symbolCell}>
                  <strong>{item.symbol}</strong>
                  <small>{item.market ?? "市场待确认"}</small>
                </td>
                <td className={styles.symbolCell}>
                  <strong>{item.name ?? "名称待确认"}</strong>
                  <small>{item.industry ?? "行业待确认"}</small>
                </td>
                <td><span className={`${styles.badge} ${candidateStatusTone(item.status)}`}>{candidateStatusLabel(item.status)}</span></td>
                <td>{stats.passed}/{stats.total} 通过</td>
                <td>{item.triggeredRuleIds.length > 0 ? item.triggeredRuleIds.join("、") : "--"}</td>
                <td>{formatNumber(item.summary.marketCapYi)}</td>
                <td className={styles.reasonCell}>
                  <span>{item.matchedReasons.length > 0
                    ? `${item.matchedReasons[0]}${item.matchedReasons.length > 1 ? ` 等 ${item.matchedReasons.length} 条` : ""}`
                    : "--"}</span>
                </td>
                <td className={styles.missingCell}>{liZongGapText(item)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function LiZongCandidateDetail({ data, candidate, onResearch, researchError, researchPending }: {
  data: LiZongCandidates;
  candidate: LiZongCandidate;
  onResearch: (candidate: LiZongCandidate) => void;
  researchError: string | null;
  researchPending: boolean;
}) {
  const ruleLabels = new Map(data.rules.map((rule) => [rule.ruleId, rule.label]));
  const orderedResults = [...candidate.ruleResults].sort((a, b) => (a.ruleId ?? "").localeCompare(b.ruleId ?? ""));
  return (
    <ModuleCard
      meta={`数据日期：${formatDate(candidate.asOfDate)}`}
      title={`${candidate.name ?? candidate.symbol} 规则核验`}
    >
      <div className={styles.chipRow}>
        <span className={`${styles.badge} ${candidateStatusTone(candidate.status)}`}>{candidateStatusLabel(candidate.status)}</span>
        <span className={styles.meta}>{candidate.symbol}{candidate.industry ? ` · ${candidate.industry}` : ""}</span>
      </div>
      {orderedResults.length > 0 ? (
        <ul className={styles.ruleList} style={{ marginTop: 12 }}>
          {orderedResults.map((rule) => (
            <li key={rule.ruleId ?? "unknown"}>
              <span className={styles.ruleText}>
                {rule.ruleId ?? "规则"} · {ruleLabels.get(rule.ruleId ?? "") ?? "规则说明待确认"}
                <small>
                  证据 {formatDate(rule.evidenceDate)}{rule.reportPeriod ? ` · 报告期 ${rule.reportPeriod}` : ""}{rule.source ? ` · ${rule.source}` : ""}
                </small>
              </span>
              <span className={`${styles.badge} ${ruleStatusTone(rule.status)}`}>{ruleStatusLabel(rule.status)}</span>
            </li>
          ))}
        </ul>
      ) : <div className={styles.empty}>规则核验明细暂不可用</div>}
      {candidate.triggeredRuleIds.length > 0 ? (
        <p className={styles.helper}>触发规则：{candidate.triggeredRuleIds.join("、")}</p>
      ) : null}
      {candidate.matchedReasons.length > 0 ? (
        <div className={styles.itemList} style={{ marginTop: 10 }}>
          {candidate.matchedReasons.map((reason) => <article key={reason}><p>{reason}</p></article>)}
        </div>
      ) : null}
      {candidate.limitations.map((limitation) => <p className={styles.helper} key={limitation}>限制：{limitation}</p>)}
      <div className={styles.actionRow}>
        <button className={styles.actionLink} disabled={researchPending} onClick={() => onResearch(candidate)} type="button">
          {researchPending ? "正在保存研究线索…" : "保存线索并进入个股研究"}
        </button>
      </div>
      {researchError ? <p className={styles.actionError} role="alert">{researchError}</p> : null}
    </ModuleCard>
  );
}

function LiZongFunnelCard({ data }: { data: LiZongCandidates }) {
  const funnel = data.funnel;
  if (!funnel || funnel.steps.length === 0) return null;
  const base = funnel.startingCount;
  return (
    <ModuleCard meta={`数据日期：${formatDate(funnel.asOfDate)}`} title="规则漏斗分布">
      <ul className={styles.funnelList}>
        <li>
          <span>评估起点</span>
          <span className={styles.funnelCount}>{funnel.startingCount ?? "--"}</span>
          <span className={styles.funnelBar}><i style={{ width: "100%" }} /></span>
        </li>
        {funnel.steps.map((step) => (
          <li key={step.ruleId ?? step.label ?? "step"}>
            <span>{step.ruleId ?? ""} · {step.label ?? "规则"}</span>
            <span className={styles.funnelCount}>
              {step.remainingCount ?? "--"}
              {step.removedAtStep !== null ? <span className={styles.funnelRemoved}>（-{step.removedAtStep}）</span> : null}
            </span>
            <span className={styles.funnelBar}>
              <i style={{ width: base !== null && base > 0 && step.remainingCount !== null ? `${Math.max(0.5, (step.remainingCount / base) * 100)}%` : "0.5%" }} />
            </span>
          </li>
        ))}
        <li>
          <span>最终候选</span>
          <span className={styles.funnelCount}>{funnel.finalCandidateCount ?? "--"}</span>
          <span className={styles.funnelBar}>
            <i style={{ width: base !== null && base > 0 && funnel.finalCandidateCount !== null ? `${Math.max(0.5, (funnel.finalCandidateCount / base) * 100)}%` : "0.5%" }} />
          </span>
        </li>
      </ul>
      {funnel.boundary ? <p className={styles.helper}>{funnel.boundary}</p> : null}
    </ModuleCard>
  );
}

// ---------- 回测模式：指标卡与纯 SVG 净值图 ----------

const BACKTEST_PERIODS: { key: BacktestPeriod; label: string }[] = [
  { key: "3m", label: "近 3 月" },
  { key: "1y", label: "近 1 年" },
  { key: "3y", label: "近 3 年" },
];

const NAV_COLOR = "#2f6bff";
const BENCH_COLOR = "#98a2b3";

function BacktestChart({ points, benchmarkLabel, width = 640, height = 280 }: {
  points: { tradeDate: string | null; nav: number | null; benchmarkNav: number | null }[];
  benchmarkLabel: string;
  width?: number;
  height?: number;
}) {
  const navPoints = points.filter((point) => point.nav !== null) as Array<{ tradeDate: string | null; nav: number }>;
  const benchPoints = points.filter((point) => point.benchmarkNav !== null) as Array<{ tradeDate: string | null; benchmarkNav: number }>;
  if (navPoints.length < 2) return null;
  const allValues = [
    ...navPoints.map((point) => point.nav),
    ...benchPoints.map((point) => point.benchmarkNav),
  ];
  const min = Math.min(...allValues);
  const max = Math.max(...allValues);
  const span = max - min || 1;
  const pad = { top: 12, right: 8, bottom: 20, left: 8 };
  const plotWidth = width - pad.left - pad.right;
  const plotHeight = height - pad.top - pad.bottom;
  const x = (index: number, total: number) => pad.left + (total <= 1 ? 0 : (index / (total - 1)) * plotWidth);
  const y = (value: number) => pad.top + (1 - (value - min) / span) * plotHeight;
  const navPath = navPoints.map((point, index) => `${index === 0 ? "M" : "L"}${x(index, navPoints.length).toFixed(1)},${y(point.nav).toFixed(1)}`).join(" ");
  const benchPath = benchPoints.length >= 2
    ? benchPoints.map((point, index) => `${index === 0 ? "M" : "L"}${x(index, benchPoints.length).toFixed(1)},${y(point.benchmarkNav).toFixed(1)}`).join(" ")
    : null;
  const gridLevels = [0, 0.25, 0.5, 0.75, 1].map((ratioLevel) => min + span * ratioLevel);
  const firstDate = navPoints[0]?.tradeDate?.slice(0, 10) ?? "";
  const lastDate = navPoints[navPoints.length - 1]?.tradeDate?.slice(0, 10) ?? "";
  return (
    <div>
      <svg aria-label="回测净值与基准净值曲线" height={height} role="img" viewBox={`0 0 ${width} ${height}`} width="100%">
        {gridLevels.map((level) => {
          const gy = y(level);
          return (
            <g key={level}>
              <line stroke="#edf1f6" strokeWidth={1} x1={pad.left} x2={width - pad.right} y1={gy} y2={gy} />
              <text fill="#98a2b3" fontSize={10} textAnchor="end" x={width - 2} y={gy - 2}>{level.toFixed(2)}</text>
            </g>
          );
        })}
        <text fill="#98a2b3" fontSize={10} x={pad.left} y={height - 6}>{firstDate}</text>
        <text fill="#98a2b3" fontSize={10} textAnchor="end" x={width - pad.right} y={height - 6}>{lastDate}</text>
        {benchPath ? <path d={benchPath} fill="none" stroke={BENCH_COLOR} strokeWidth={1.5} /> : null}
        <path d={navPath} fill="none" stroke={NAV_COLOR} strokeWidth={2} />
      </svg>
      <div className={styles.chartLegend}>
        <span><i style={{ background: NAV_COLOR }} />组合净值（末值 {formatNumber(navPoints[navPoints.length - 1]?.nav ?? null)}）</span>
        <span><i style={{ background: BENCH_COLOR }} />基准净值（{benchmarkLabel}，末值 {formatNumber(benchPoints[benchPoints.length - 1]?.benchmarkNav ?? null)}）</span>
      </div>
    </div>
  );
}

function BacktestSection({ period, onSelectPeriod }: { period: BacktestPeriod; onSelectPeriod: (period: BacktestPeriod) => void }) {
  const backtestQuery = useQuery(screeningQueries.liZongBacktest(period));
  const data = backtestQuery.data ?? null;
  const result = data?.result ?? null;
  // §5.2：仅在实际任务完成且数据可用时展示完整指标；其余状态显示真实进度/空态。
  const ready = data !== null && data.status === "ready" && result !== null && result.status === "ready";
  return (
    <>
      <div className={styles.chipRow} role="group" aria-label="回测区间">
        {BACKTEST_PERIODS.map((item) => (
          <button
            aria-pressed={period === item.key}
            className={styles.chip}
            key={item.key}
            onClick={() => onSelectPeriod(item.key)}
            type="button"
          >
            {item.label}
          </button>
        ))}
      </div>
      <ModuleCard
        error={backtestQuery.isError}
        meta={ready && result ? `生成时间：${formatDateTime(result.generatedAt)}` : undefined}
        onRetry={() => void backtestQuery.refetch()}
        pending={backtestQuery.isPending}
        title={`回测指标（${data?.periodLabel ?? BACKTEST_PERIODS.find((item) => item.key === period)?.label ?? period}）`}
      >
        {ready && result ? (
          <>
            <div className={styles.metricGrid}>
              <div className={styles.metric}><span>区间收益</span><strong className={signedTone(result.periodReturnPct)}>{percent(result.periodReturnPct)}</strong><small>{formatDate(result.startDate)} ~ {formatDate(result.endDate)}</small></div>
              <div className={styles.metric}><span>年化收益</span><strong className={signedTone(result.annualizedReturnPct)}>{percent(result.annualizedReturnPct)}</strong><small>基准年化 {percent(result.benchmarkAnnualizedReturnPct)}</small></div>
              <div className={styles.metric}><span>最大回撤</span><strong className={signedTone(result.maxDrawdownPct)}>{percent(result.maxDrawdownPct)}</strong><small>服务端口径直通</small></div>
              <div className={styles.metric}><span>基准区间收益</span><strong className={signedTone(result.benchmarkReturnPct)}>{percent(result.benchmarkReturnPct)}</strong><small>{data.assumptions.benchmark ?? "基准说明待确认"}</small></div>
              <div className={styles.metric}><span>超额收益</span><strong className={signedTone(result.excessReturnPct)}>{percent(result.excessReturnPct)}</strong><small>相对基准</small></div>
              <div className={styles.metric}><span>年化波动率</span><strong>{percent(result.annualizedVolatilityPct)}</strong><small>百分数直通</small></div>
              <div className={styles.metric}><span>数据覆盖率（原始比例直通）</span><strong>{ratio(result.dataCoverageRatio)}</strong><small>完整 {result.completeSymbolCount ?? "--"} / 候选 {result.eligibleSymbolCount ?? "--"} 只</small></div>
              <div className={styles.metric}><span>换仓 / 曾入选</span><strong>{result.selectionUpdateCount ?? "--"} 次 / {result.everSelectedSymbolCount ?? "--"} 只</strong><small>总换手率 {percent(result.totalTurnoverPct)}</small></div>
            </div>
            {result.dataCoverageBoundary ? <p className={styles.helper}>{result.dataCoverageBoundary}</p> : null}
          </>
        ) : (
          <div className={styles.empty}>
            <span>该区间的回测尚未完成或结果不可用，不展示推算指标。</span>
            <span>
              当前状态：{data ? statusLabel(data.status) : "待确认"}
              {data?.progress?.phase ? `（${data.progress.phase}）` : ""}
              {data?.progress?.marketDataRatio !== null && data?.progress?.marketDataRatio !== undefined
                ? ` · 行情数据就绪比例 ${ratio(data.progress.marketDataRatio)}` : ""}
            </span>
          </div>
        )}
      </ModuleCard>
      {ready && result && result.points.length >= 2 ? (
        <ModuleCard title="净值曲线">
          <div className={styles.chartFrame}>
            <BacktestChart benchmarkLabel={data.assumptions.benchmark ?? "基准"} points={result.points} />
          </div>
          <div className={styles.chartMeta}>
            <span>交易日 {result.tradingDays ?? "--"} 天</span>
            <span>价格口径：{data.assumptions.priceBasis ?? "待确认"}</span>
            <span>加权：{data.assumptions.weighting ?? "待确认"}</span>
            <span>换仓规则：{data.assumptions.rebalance ?? "待确认"}</span>
          </div>
          {result.boundary ? <p className={styles.boundaryNote}>{result.boundary}</p> : null}
          {data.boundary ? <p className={styles.boundaryNote}>{data.boundary}</p> : null}
        </ModuleCard>
      ) : null}
    </>
  );
}

// ---------- 页面 ----------

function parseMode(value: string | null): ModeKey {
  return MODES.some((mode) => mode.key === value) ? (value as ModeKey) : "screen";
}

function parsePeriod(value: string | null): BacktestPeriod {
  return value === "3m" || value === "3y" ? value : "1y";
}

function parseLiZongStatus(value: string | null): LiZongStatusFilter {
  return value === "qualified" || value === "triggered" || value === "not_qualified" || value === "data_incomplete"
    ? value
    : null;
}

export function ScreeningPage({ authenticated }: Props) {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const mode = parseMode(searchParams.get("mode"));
  const period = parsePeriod(searchParams.get("period"));
  const liZongStatus = parseLiZongStatus(searchParams.get("status"));

  const updateParams = (updates: Record<string, string | null>, reset?: string[]) => {
    const next = new URLSearchParams(searchParams);
    for (const key of reset ?? []) next.delete(key);
    for (const [key, value] of Object.entries(updates)) {
      if (value === null) next.delete(key);
      else next.set(key, value);
    }
    setSearchParams(next);
  };

  // ----- 通用筛选参数（URL 为唯一事实来源，可分享） -----
  const profilesQuery = useQuery({ ...screeningQueries.profiles(), enabled: authenticated && mode === "screen" });
  const profiles = profilesQuery.data?.items ?? [];
  const screenParams = useMemo<ScreenParams | null>(() => {
    if (mode !== "screen" || profiles.length === 0) return null;
    const profileParam = searchParams.get("profile");
    const profile = profiles.find((item) => item.key === profileParam) ?? profiles[0]!;
    const marketParam = searchParams.get("m");
    const market = MARKETS.some((item) => item.key === marketParam) ? marketParam! : "all";
    const nParam = Number(searchParams.get("n"));
    const maxResults = MAX_RESULT_OPTIONS.includes(nParam as (typeof MAX_RESULT_OPTIONS)[number]) ? nParam : 12;
    const filters: Record<string, number> = {};
    for (const [key, defaultValue] of Object.entries(profile.defaultFilters)) {
      const raw = searchParams.get(`f_${key}`);
      const parsed = raw === null ? NaN : Number(raw);
      filters[key] = Number.isFinite(parsed) ? parsed : defaultValue;
    }
    return { profile: profile.key, market, maxResults, filters };
  }, [mode, profiles, searchParams]);

  const screenQuery = useQuery({
    ...screeningQueries.screen(screenParams ?? { profile: "", market: "all", maxResults: 12, filters: {} }),
    enabled: authenticated && screenParams !== null,
  });
  const screen = screenQuery.data ?? null;

  // ----- 李总模式 -----
  const liZongCandidatesQuery = useQuery({ ...screeningQueries.liZongCandidates(liZongStatus), enabled: authenticated && mode === "lizong" });
  const liZongRunQuery = useQuery({ ...screeningQueries.liZongRunLatest(), enabled: authenticated && mode === "lizong" });
  const liZongData = liZongCandidatesQuery.data ?? null;

  // ----- 选中候选（URL symbol） -----
  const symbolParam = searchParams.get("symbol");
  const selectedScreenItem = screen?.items.find((item) => item.symbol === symbolParam)
    ?? screen?.items[0]
    ?? null;
  const selectedLiZongItem = liZongData?.items.find((item) => item.symbol === symbolParam)
    ?? liZongData?.items[0]
    ?? null;
  const researchMutation = useMutation({
    mutationFn: ({ entryContext, symbol }: { entryContext: DeepStockEntryContext; symbol: string }) => (
      startDeepStockResearch(symbol, entryContext)
    ),
    onSuccess: (session) => navigate(`/stocks/${encodeURIComponent(session.symbol)}`),
  });
  const researchError = researchMutation.isError
    ? (researchMutation.error instanceof Error ? researchMutation.error.message : "保存研究线索失败，请稍后重试。")
    : null;
  const researchPendingFor = (symbol: string) => researchMutation.isPending && researchMutation.variables?.symbol === symbol;
  const researchErrorFor = (symbol: string) => researchMutation.variables?.symbol === symbol ? researchError : null;

  if (!authenticated) {
    return (
      <div className={styles.page}>
        <header className={styles.header}>
          <div className={styles.headerTitle}>
            <h1>透明选股</h1>
            <p>用透明规则形成研究候选，不输出投资建议。</p>
          </div>
        </header>
        <div className={styles.card}>
          <div className={styles.empty}>
            <span>业务内容已锁定，请先登录或注册。</span>
            <span>登录后可查看筛选条件、候选结果与回测证据。</span>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div className={styles.headerTitle}>
          <h1>透明选股</h1>
          <p>用透明规则形成研究候选，不输出投资建议；三种模式互斥，各自使用独立的筛选口径与表格。</p>
        </div>
        <div className={styles.headerMeta}>
          {mode === "screen" && screen ? (
            <span>结果状态：<span className={`${styles.badge} ${statusTone(screen.status)}`}>{statusLabel(screen.status)}</span></span>
          ) : null}
          {mode === "lizong" && liZongData ? (
            <span>快照状态：<span className={`${styles.badge} ${statusTone(liZongData.status)}`}>{statusLabel(liZongData.status)}</span></span>
          ) : null}
        </div>
      </header>

      <ScreeningModeCards
        active={mode}
        onSelect={(next) => {
          // 模式互斥：切换时只保留 mode 参数，其余筛选状态不跨模式共享。
          const params = new URLSearchParams();
          if (next !== "screen") params.set("mode", next);
          setSearchParams(params);
        }}
      />

      {mode === "screen" ? (
        <>
          {profilesQuery.isError ? (
            <div className={styles.moduleError} role="status">
              <span>筛选档案暂时不可用。</span>
              <button type="button" onClick={() => void profilesQuery.refetch()}>重新读取</button>
            </div>
          ) : null}
          {profilesQuery.isPending ? <div className={styles.skeleton} aria-live="polite">正在读取筛选档案…</div> : null}
          {screenParams ? (
            <FilterBuilder
              applied={screenParams}
              disabled={screenQuery.isFetching}
              onApply={(next) => {
                const updates: Record<string, string | null> = {
                  profile: next.profile,
                  m: next.market === "all" ? null : next.market,
                  n: next.maxResults === 12 ? null : String(next.maxResults),
                  symbol: null,
                };
                const reset: string[] = [];
                for (const key of searchParams.keys()) {
                  if (key.startsWith("f_")) reset.push(key);
                }
                for (const [key, value] of Object.entries(next.filters)) updates[`f_${key}`] = String(value);
                updateParams(updates, reset);
              }}
              profiles={profiles}
            />
          ) : null}
          {screenQuery.isError ? (
            <div className={styles.moduleError} role="status">
              <span>筛选结果暂时不可用。</span>
              <button type="button" onClick={() => void screenQuery.refetch()}>重新读取</button>
            </div>
          ) : null}
          {screenQuery.isPending && screenParams ? <div className={styles.skeleton} aria-live="polite">正在执行筛选…</div> : null}
          {screen ? (
            <>
              <ScreenRunSummary screen={screen} />
              {screen.items.length === 0 ? (
                <div className={styles.card}>
                  <div className={styles.empty}>
                    <span>当前条件下没有命中候选。</span>
                    <span>放宽上方阈值后重新应用筛选；命中数为 0 是真实结果，不用示例数据填充。</span>
                  </div>
                  {screen.boundary ? <p className={styles.boundaryNote}>{screen.boundary}</p> : null}
                </div>
              ) : (
                <div className={styles.layout}>
                  <div className={styles.mainColumn}>
                    <ModuleCard meta={`${screen.items.length} / ${screen.universe.matched ?? "--"} 条`} title="筛选候选">
                      <ScreenCandidateTable
                        items={screen.items}
                        onSelect={(symbol) => updateParams({ symbol })}
                        selectedSymbol={selectedScreenItem?.symbol ?? null}
                      />
                      <p className={styles.helper}>
                        服务端暂无分页参数：仅展示排序后的前 {screen.items.length} 条（上限由「展示条数」控制），命中总数见上方摘要，不提供伪分页。
                      </p>
                      {screen.boundary ? <p className={styles.boundaryNote}>{screen.boundary}</p> : null}
                    </ModuleCard>
                  </div>
                  <div className={styles.mainColumn}>
                    {selectedScreenItem ? (
                      <ScreenCandidateDetail
                        item={selectedScreenItem}
                        onResearch={(item) => researchMutation.mutate({
                          entryContext: screenEntryContext(screen, item),
                          symbol: item.internalSymbol ?? item.symbol,
                        })}
                        researchError={researchErrorFor(selectedScreenItem.internalSymbol ?? selectedScreenItem.symbol)}
                        researchPending={researchPendingFor(selectedScreenItem.internalSymbol ?? selectedScreenItem.symbol)}
                      />
                    ) : null}
                    <ScreenExplainPanel screen={screen} />
                  </div>
                </div>
              )}
            </>
          ) : null}
          {profilesQuery.data?.boundary ? <p className={styles.boundaryNote}>{profilesQuery.data.boundary}</p> : null}
        </>
      ) : null}

      {mode === "lizong" ? (
        <>
          <LiZongRunSummaryCard
            data={liZongRunQuery.data ?? null}
            error={liZongRunQuery.isError}
            onRetry={() => void liZongRunQuery.refetch()}
            pending={liZongRunQuery.isPending}
          />
          {liZongCandidatesQuery.isError ? (
            <div className={styles.moduleError} role="status">
              <span>候选快照暂时不可用。</span>
              <button type="button" onClick={() => void liZongCandidatesQuery.refetch()}>重新读取</button>
            </div>
          ) : null}
          {liZongCandidatesQuery.isPending ? <div className={styles.skeleton} aria-live="polite">正在读取候选快照…</div> : null}
          {liZongData ? (
            <>
              <div className={styles.chipRow} role="group" aria-label="候选状态筛选">
                {LIZONG_STATUS_CHIPS.map((chip) => {
                  const count = chip.key === null ? liZongData.counts.total
                    : chip.key === "qualified" ? liZongData.counts.qualified
                    : chip.key === "triggered" ? liZongData.counts.triggered
                    : chip.key === "not_qualified" ? liZongData.counts.notQualified
                    : liZongData.counts.dataIncomplete;
                  return (
                    <button
                      aria-pressed={liZongStatus === chip.key}
                      className={styles.chip}
                      key={chip.label}
                      onClick={() => updateParams({ status: chip.key, symbol: null })}
                      type="button"
                    >
                      {chip.label}{count !== null ? ` ${count}` : ""}
                    </button>
                  );
                })}
              </div>
              {liZongData.items.length === 0 ? (
                <div className={styles.card}>
                  <div className={styles.empty}>
                    <span>该状态下当前没有候选记录。</span>
                    <span>计数来自服务端快照统计，为空是真实状态，不用示例数据填充。</span>
                  </div>
                  {liZongData.boundary ? <p className={styles.boundaryNote}>{liZongData.boundary}</p> : null}
                </div>
              ) : (
                <div className={styles.layout}>
                  <div className={styles.mainColumn}>
                    <ModuleCard meta={`${liZongData.items.length} 条 · 数据日期 ${formatDate(liZongData.dataMeta.latestAsOfDate)}`} title="李总策略候选">
                      <LiZongCandidateTable
                        data={liZongData}
                        onSelect={(symbol) => updateParams({ symbol })}
                        selectedSymbol={selectedLiZongItem?.symbol ?? null}
                      />
                      <p className={styles.helper}>
                        快照覆盖 {liZongData.dataMeta.universeCount ?? "--"} 只（覆盖率 {ratio(liZongData.dataMeta.coverageRatio)}）；
                        列表为服务端 status 过滤结果（上限 200 条），不做前端逐股补全。
                      </p>
                      {liZongData.boundary ? <p className={styles.boundaryNote}>{liZongData.boundary}</p> : null}
                    </ModuleCard>
                    <LiZongFunnelCard data={liZongData} />
                  </div>
                  <div className={styles.mainColumn}>
                    {selectedLiZongItem ? (
                      <LiZongCandidateDetail
                        candidate={selectedLiZongItem}
                        data={liZongData}
                        onResearch={(candidate) => researchMutation.mutate({
                          entryContext: liZongEntryContext(liZongData, candidate),
                          symbol: candidate.internalSymbol ?? candidate.symbol,
                        })}
                        researchError={researchErrorFor(selectedLiZongItem.internalSymbol ?? selectedLiZongItem.symbol)}
                        researchPending={researchPendingFor(selectedLiZongItem.internalSymbol ?? selectedLiZongItem.symbol)}
                      />
                    ) : null}
                  </div>
                </div>
              )}
            </>
          ) : null}
        </>
      ) : null}

      {mode === "backtest" ? (
        <BacktestSection onSelectPeriod={(next) => updateParams({ period: next === "1y" ? null : next })} period={period} />
      ) : null}

      <footer className={styles.footer}>
        红绿仅表示事实涨跌方向，不构成买卖建议；候选、规则核验与回测指标均为服务端口径直通。只有你明确点击进入研究时才保存候选线索，系统不会自动形成正式判断。
      </footer>
    </div>
  );
}
