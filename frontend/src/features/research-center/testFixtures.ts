import {
  parseResearchActions,
  parseResearchChanges,
  parseResearchOutcomes,
  parseResearchReport,
  parseTradeReviewCenter,
  parseWorkspaceTimeline,
} from "./adapters";

// ---------- 原始载荷（形状与 8010 真实响应一致，数值为测试样例） ----------

export function changesPayload() {
  return {
    type: "research_tracking",
    generated_at: "2026-08-06T10:28:55+00:00",
    symbol: null,
    coverage: { requested: 2, with_report: 2, with_change_archive: 1 },
    boundary: "研究变化档案是长期证据记录，不是收益评分、胜率或交易指令。",
    items: [
      {
        symbol: "000063.SZ",
        name: "中兴通讯",
        thesis: null,
        in_watchlist: true,
        latest_report_at: "2026-08-06T09:20:09+00:00",
        latest_change: {
          id: "change-1",
          symbol: "000063.SZ",
          event_type: "evidence_change",
          severity: "notice",
          summary: "中兴通讯最新变化：新增回购与股东回报（媒体报道）。",
          created_at: "2026-08-06T09:20:09+00:00",
          data_as_of: "2026-08-06T01:30:00+00:00",
          changes: [
            {
              dimension: "event",
              label: "回购与股东回报（媒体报道）",
              before: null,
              after: "中兴通讯：2025年度A、H股股息安排说明",
              detail: "新增回购与股东回报（媒体报道）。",
              severity: "notice",
            },
            {
              dimension: "price",
              label: "20日收益",
              before: "-10.20%",
              after: "-13.96%",
              detail: "20日收益由 -10.20% 变为 -13.96%。",
              severity: "medium",
            },
          ],
          new_evidence: [
            {
              category_label: "回购与股东回报（媒体报道）",
              title: "中兴通讯：2025年度A、H股股息安排说明",
              published_at: "2026-08-06T16:52:00+08:00",
            },
          ],
          next_review: {
            horizon_sessions: 3,
            focus: "确认短期价格结构与信息增量",
            checks: ["收盘与 MA20 的相对位置是否变化"],
          },
          boundary: "变化事件用于研究复核，不是买卖、止盈止损等交易指令。",
        },
        current_state: {
          latest_close: 34.7,
          return_1d_pct: -0.1151,
          return_20d_pct: -13.9598,
          trend_state: "中期偏弱",
          technical_state: "动量转弱",
        },
        next_review: {
          horizon_sessions: 3,
          focus: "确认短期价格结构与信息增量",
          checks: ["收盘与 MA20 的相对位置是否变化"],
        },
      },
      {
        symbol: "600519.SS",
        name: "贵州茅台",
        thesis: { summary: "渠道批价与动销是核心变量。" },
        in_watchlist: true,
        latest_report_at: "2026-08-05T09:00:00+00:00",
        latest_change: null,
        current_state: null,
        next_review: null,
      },
    ],
  };
}

export function emptyChangesPayload() {
  return {
    type: "research_tracking",
    generated_at: "2026-08-06T10:28:55+00:00",
    symbol: null,
    coverage: { requested: 0, with_report: 0, with_change_archive: 0 },
    boundary: "研究变化档案是长期证据记录。",
    items: [],
  };
}

function anchorBase() {
  return {
    protocol: {
      anchor: "研究快照对应的数据库日线收盘价",
      horizon: "之后第3个已存交易日",
      price_series: "优先使用复权收盘价；复权价缺失时使用原始收盘价",
      mfe_mae: "区间内最大上行与最大下行，仅描述路径，不代表可实现收益",
    },
    boundary: "结果回填只检验研究条件后来是否出现，不把研究快照视为买卖信号。",
    symbol: "000063.SZ",
    name: "中兴通讯",
    report_id: "report-1",
  };
}

export function outcomesPayload() {
  return {
    type: "research_outcome",
    generated_at: "2026-08-06T10:28:56+00:00",
    symbol: null,
    boundary: "结果回填只检验研究条件后来是否出现。",
    items: [
      {
        symbol: "000063.SZ",
        name: "中兴通讯",
        thesis: null,
        latest_anchor_at: "2026-08-06T01:30:00+00:00",
        coverage: { anchors: 5, available: 2, pending: 3 },
        latest_anchor: [
          {
            ...anchorBase(),
            id: "anchor-pending-1",
            anchor_timestamp: "2026-08-06T01:30:00+00:00",
            horizon_sessions: 3,
            result_status: "pending",
            observed_sessions: 0,
            anchor_close: 34.7,
            target_timestamp: null,
            target_close: null,
            close_return_pct: null,
            maximum_favorable_excursion_pct: null,
            maximum_adverse_excursion_pct: null,
            scenario_result: "not_started",
            scenario_label: "尚无后续交易日",
            review_conclusion: "T+3尚未开始形成后续交易日样本。",
            calculated_at: "2026-08-06T09:26:31+00:00",
            original_outlook_label: "偏弱观察",
            progress_timestamp: null,
            partial_return_pct: null,
            data_as_of: "2026-08-06T01:30:00+00:00",
          },
        ],
        latest_progress: {
          ...anchorBase(),
          id: "anchor-progress-1",
          anchor_timestamp: "2026-08-05T01:30:00+00:00",
          horizon_sessions: 3,
          result_status: "pending",
          observed_sessions: 1,
          anchor_close: 34.74,
          target_timestamp: null,
          target_close: null,
          close_return_pct: null,
          maximum_favorable_excursion_pct: 0.0,
          maximum_adverse_excursion_pct: -0.5,
          scenario_result: "range_held",
          scenario_label: "区间情景延续",
          review_conclusion: "T+3尚未到期；目前已观察1个交易日，还差2个交易日。",
          calculated_at: "2026-08-06T13:23:08+00:00",
          original_outlook_label: "偏弱观察",
          progress_timestamp: "2026-08-06T01:30:00+00:00",
          partial_return_pct: -0.1151,
          data_as_of: "2026-08-06T01:30:00+00:00",
        },
        latest_available: [
          {
            ...anchorBase(),
            id: "anchor-done-1",
            anchor_timestamp: "2026-07-30T01:30:00+00:00",
            horizon_sessions: 3,
            result_status: "ready",
            observed_sessions: 3,
            anchor_close: 34.02,
            target_timestamp: "2026-08-04T01:30:00+00:00",
            target_close: 33.39,
            close_return_pct: -1.8524,
            maximum_favorable_excursion_pct: 2.1164,
            maximum_adverse_excursion_pct: -3.4027,
            scenario_result: "range_held",
            scenario_label: "区间情景延续",
            review_conclusion: "T+3已到期：尚无清晰条件触发，不能据此判断原研究失效。",
            calculated_at: "2026-08-05T09:00:00+00:00",
            original_outlook_label: "偏弱观察",
            progress_timestamp: null,
            partial_return_pct: null,
            data_as_of: "2026-08-04T01:30:00+00:00",
          },
        ],
      },
      {
        symbol: "600519.SS",
        name: "贵州茅台",
        thesis: null,
        latest_anchor_at: null,
        coverage: { anchors: 0, available: 0, pending: 0 },
        latest_anchor: [],
        latest_progress: null,
        latest_available: [],
      },
    ],
  };
}

export function emptyOutcomesPayload() {
  return {
    type: "research_outcome",
    generated_at: "2026-08-06T10:28:56+00:00",
    symbol: null,
    boundary: "结果回填只检验研究条件后来是否出现。",
    items: [],
  };
}

export function actionsPayload() {
  return {
    type: "research_actions",
    generated_at: "2026-08-06T13:20:35+00:00",
    method: "deterministic_research_action_board_v1",
    items: [
      {
        symbol: "000063.SZ",
        name: "中兴通讯",
        thesis: null,
        research_status: "priority_research",
        research_status_label: "优先研究",
        priority_score: 87,
        priority_label: "优先复核",
        data_as_of: "2026-08-06T01:30:00+00:00",
        latest_report_id: "report-1",
        latest_report_at: "2026-08-06T09:20:09+00:00",
        headline: "4项需要复核 · 2项待补证 · 2项继续观察",
        actions: [
          {
            id: "action-1",
            key: "volatility_review",
            category: "risk",
            title: "检查波动是否显著放大",
            status: "triggered",
            severity: "medium",
            condition: "20日年化波动率达到 35% 或更高",
            current_evidence: "当前20日年化波动率 57.64%。",
            next_step: "结合ATR、成交量和最新事件判断波动来源。",
            checks: [],
          },
          {
            id: "action-2",
            key: "missing_thesis",
            category: "user_context",
            title: "补充关注理由",
            status: "pending_data",
            severity: "medium",
            condition: "自选股缺少用户关注理由",
            current_evidence: null,
            next_step: "在个股页或顾问中补充关注理由。",
            checks: [],
          },
        ],
      },
    ],
  };
}

export function timelinePayload() {
  return {
    contract_version: "stock_workspace_timeline_v1",
    symbol: "000063.SZ",
    name: "中兴通讯",
    thesis_history: [
      {
        id: "thesis-1",
        version_no: 2,
        reason_text: "算力订单兑现节奏是核心变量。",
        status: "confirmed",
        created_at: "2026-08-01T10:00:00+00:00",
        confirmed_at: "2026-08-01T10:05:00+00:00",
      },
    ],
    important_changes: changesPayload().items[0]!.latest_change
      ? [changesPayload().items[0]!.latest_change]
      : [],
    observation_tasks: {
      contract_version: "observation_tasks_v1",
      items: [
        {
          id: "task-1",
          title: "跟踪 MA20 收复情况",
          status: "active",
          description: "确认收盘与 MA20 的相对位置。",
          version: 1,
          updated_at: "2026-08-05T12:00:00+00:00",
        },
      ],
      summary: { total: 1, active: 1, pending: 0, completed: 0 },
      boundary: "观察任务不是交易指令。",
    },
    trade_reviews: {
      contract_version: "trade_review_v1",
      symbol: "000063.SZ",
      items: [],
      summary: { total: 1, waiting_data: 0, needs_confirmation: 1 },
      boundary: "价格结果与逻辑结果分开。",
    },
    position: { available: false, status: "unavailable" },
    history_summary: {
      change_count: 3,
      position_snapshot_count: 0,
      recent_report_count: 3,
      observation_task_count: 1,
      coverage_snapshot_count: 0,
      thesis_version_count: 1,
      latest_report_at: "2026-08-06T13:20:40+00:00",
      trade_review_count: 1,
      latest_change_at: "2026-08-06T13:20:40+00:00",
      action_plan_count: 0,
      position_operation_count: 0,
    },
    data_meta: {
      status: "ready",
      daily_as_of: "2026-08-06T01:30:00+00:00",
      report_market_timestamp: "2026-08-06T01:30:00+00:00",
      private_context_user_isolated: true,
      financial_report_period: "2026-03-31",
      report_generated_at: "2026-08-06T13:20:40+00:00",
      quote_as_of: "2026-08-06T16:14:15+08:00",
      public_evidence_cacheable: true,
      strategy_as_of: "2026-08-05",
    },
  };
}

export function emptyTimelinePayload() {
  const payload = timelinePayload();
  return {
    ...payload,
    thesis_history: [],
    important_changes: [],
    observation_tasks: { ...payload.observation_tasks, items: [], summary: { total: 0, active: 0, pending: 0, completed: 0 } },
    trade_reviews: { ...payload.trade_reviews, summary: { total: 0, waiting_data: 0, needs_confirmation: 0 } },
  };
}

export function reportPayload() {
  return {
    id: "report-1",
    symbol: "000063.SZ",
    name: "中兴通讯",
    title: "中兴通讯研究快照｜2026-08-06",
    summary: "中兴通讯 当前价格证据：34.7 CNY。",
    body: "中兴通讯 当前价格证据。",
    status: "preview",
    market_timestamp: "2026-08-06T01:30:00+00:00",
    generated_at: "2026-08-06T13:20:40+00:00",
  };
}

export function tradeReviewCenterPayload() {
  return {
    contract_version: "trade_review_center_v1",
    items: [
      {
        id: "review-1",
        symbol: "000063.SZ",
        name: "中兴通讯",
        status: "draft",
        data_status: "fresh",
        horizon_sessions: 5,
        ready_at: "2026-08-05T09:00:00+00:00",
        confirmed_at: null,
        archived_at: null,
        updated_at: "2026-08-05T10:00:00+00:00",
        can_confirm: true,
        can_generate_draft: false,
        operation: {
          operation_type: "buy",
          operated_at: "2026-07-28T10:00:00+00:00",
          price: 35.2,
          reason_text: "验证算力订单逻辑",
        },
        price_observation: { ready: true, summary: "5个交易日窗口收益 -1.85%。" },
        current_version: {
          version_no: 2,
          status: "draft",
          price_result: "窗口收益 -1.85%。",
          logic_result: "原假设未被证伪，但兑现节奏慢于预期。",
          plan_deviation: null,
          improvement_text: null,
          created_source: "ai",
          created_at: "2026-08-05T10:00:00+00:00",
        },
        versions: [],
        followups: { observation_task: null, thesis: null },
      },
      {
        id: "review-2",
        symbol: "600519.SS",
        name: "贵州茅台",
        status: "confirmed",
        data_status: "fresh",
        horizon_sessions: 5,
        ready_at: "2026-08-01T09:00:00+00:00",
        confirmed_at: "2026-08-02T09:00:00+00:00",
        archived_at: null,
        updated_at: "2026-08-02T09:00:00+00:00",
        can_confirm: false,
        can_generate_draft: false,
        operation: {
          operation_type: "sell",
          operated_at: "2026-07-20T10:00:00+00:00",
          price: 1480.0,
          reason_text: null,
        },
        price_observation: { ready: true, summary: "5个交易日窗口收益 +0.42%。" },
        current_version: {
          version_no: 1,
          status: "confirmed",
          price_result: "窗口收益 +0.42%。",
          logic_result: "逻辑兑现符合预期。",
          plan_deviation: null,
          improvement_text: null,
          created_source: "user",
          created_at: "2026-08-02T09:00:00+00:00",
        },
        versions: [],
        followups: { observation_task: null, thesis: null },
      },
    ],
    summary: {
      total: 2,
      filtered: 2,
      actionable: 1,
      waiting_data: 0,
      ready: 0,
      needs_confirmation: 1,
      confirmed: 1,
      archived: 0,
    },
    filters: { status: null, symbol: null, query: null, limit: 100 },
    boundary: "价格结果由数据库确定性计算；逻辑结果由 Agent 生成草稿，只有用户确认后才成为正式复盘。",
  };
}

export function emptyTradeReviewCenterPayload() {
  return {
    contract_version: "trade_review_center_v1",
    items: [],
    summary: { total: 0, filtered: 0, actionable: 0, waiting_data: 0, ready: 0, needs_confirmation: 0, confirmed: 0, archived: 0 },
    filters: { status: null, symbol: null, query: null, limit: 100 },
    boundary: "价格结果由数据库确定性计算。",
  };
}

// ---------- 解析后的数据（Page 测试用） ----------

export const parsedChanges = () => parseResearchChanges(changesPayload());
export const parsedEmptyChanges = () => parseResearchChanges(emptyChangesPayload());
export const parsedOutcomes = () => parseResearchOutcomes(outcomesPayload());
export const parsedEmptyOutcomes = () => parseResearchOutcomes(emptyOutcomesPayload());
export const parsedActions = () => parseResearchActions(actionsPayload());
export const parsedTimeline = () => parseWorkspaceTimeline(timelinePayload());
export const parsedEmptyTimeline = () => parseWorkspaceTimeline(emptyTimelinePayload());
export const parsedReport = () => parseResearchReport(reportPayload());
export const parsedTradeReviewCenter = () => parseTradeReviewCenter(tradeReviewCenterPayload());
export const parsedEmptyTradeReviewCenter = () => parseTradeReviewCenter(emptyTradeReviewCenterPayload());
