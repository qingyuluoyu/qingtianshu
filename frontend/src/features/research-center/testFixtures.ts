import {
  parseEvidenceTasks,
  parseResearchActions,
  parseResearchChanges,
  parseResearchOutcomes,
  parseResearchPriority,
  parseRunReviews,
} from "./adapters";

export function priorityPayload() {
  return {
    type: "research_priority",
    generated_at: "2026-08-07T06:00:00+00:00",
    items: [
      {
        symbol: "000063.SZ",
        name: "中兴通讯",
        thesis: "验证利润、订单和经营现金流",
        status: "available",
        priority_score: 78,
        priority_label: "优先复核",
        reasons: ["最新证据出现利润与现金流节奏差异。"],
        next_review: { focus: "核对最新公告与经营现金流", checks: ["公告", "现金流"] },
        data_as_of: "2026-08-06T15:00:00+08:00",
      },
      {
        symbol: "300308.SZ",
        name: "中际旭创",
        status: "baseline_missing",
        priority_score: 45,
        priority_label: "优先建立基线",
        reasons: ["尚无服务器研究报告。"],
        next_review: { focus: "建立首份研究基线", checks: [] },
        data_as_of: null,
      },
    ],
    coverage: { requested: 2, available: 1, missing_baseline: 1 },
    sorting: "按研究复核紧迫度排序，不按预期收益或投资吸引力排序。",
    boundary: "优先级不是买卖评级。",
  };
}

export function changesPayload() {
  return {
    type: "research_tracking",
    generated_at: "2026-08-07T06:01:00+00:00",
    items: [],
    events: [
      {
        id: "change-1",
        symbol: "000063.SZ",
        event_type: "evidence_change",
        severity: "attention",
        summary: "利润、现金流与价格结构出现新的反方证据。",
        created_at: "2026-08-07T05:30:00+00:00",
        data_as_of: "2026-08-06",
        next_review: { focus: "核对半年报与公告原文" },
      },
    ],
    coverage: { requested: 2, with_report: 1, with_change_archive: 1 },
    method: "比较连续研究报告中的证据变化。",
    boundary: "研究变化档案不是收益评分或交易指令。",
  };
}

export function actionsPayload() {
  return {
    type: "research_actions",
    generated_at: "2026-08-07T06:02:00+00:00",
    items: [
      {
        symbol: "000063.SZ",
        name: "中兴通讯",
        thesis: "验证利润、订单和经营现金流",
        research_status: "risk_review",
        research_status_label: "风险复核",
        priority_score: 78,
        data_as_of: "2026-08-06T15:00:00+08:00",
        headline: "1项需要复核 · 1项待补证",
        actions: [
          {
            id: "action-1",
            title: "复核最新证据变化",
            status: "triggered",
            severity: "high",
            condition: "连续研究报告出现新证据",
            current_evidence: "现金流增速没有同步确认利润改善。",
            next_step: "打开最新研究报告并核对公司原文。",
            checks: ["现金流", "公告"],
          },
          {
            id: "action-2",
            title: "补齐行业供需证据",
            status: "pending_data",
            severity: "medium",
            condition: "行业证据不足",
            current_evidence: "当前只有公司侧披露。",
            next_step: "补齐行业供需与客户结构资料。",
            checks: [],
          },
        ],
      },
    ],
    summary: { symbols: 1, triggered: 1, pending_data: 1, watching: 0, priority_research: 1 },
    boundary: "研究行动不是价格提醒、买卖信号或仓位建议。",
  };
}

export function evidenceTasksPayload() {
  return {
    generated_at: "2026-08-07T06:03:00+00:00",
    method: "deterministic_evidence_task_lifecycle_v1",
    summary: { total: 2, pending: 1, pending_external: 1, resolved: 0, failed: 0 },
    items: [
      {
        id: "task-1",
        conversation_id: "conversation-1",
        run_id: "run-1",
        symbol: "000063.SZ",
        title: "补齐公司最新公告",
        description: "公司最新公告尚未接入",
        status: "pending",
        status_label: "等待后台补齐",
        priority: 80,
        updated_at: "2026-08-07T05:40:00+00:00",
      },
      {
        id: "task-2",
        conversation_id: "conversation-1",
        run_id: "run-1",
        symbol: "000063.SZ",
        title: "补齐行业供需资料",
        description: "当前工具链没有可靠自动采集器",
        status: "pending_external",
        status_label: "等待外部资料或新数据源",
        priority: 60,
        resolution_note: "需要人工提供行业材料。",
        updated_at: "2026-08-07T05:41:00+00:00",
      },
    ],
    boundary: "已解决只表示资料已采集，不表示投资结论成立。",
  };
}

export function outcomesPayload() {
  return {
    type: "research_outcome",
    generated_at: "2026-08-07T06:04:00+00:00",
    items: [
      {
        symbol: "000063.SZ",
        name: "中兴通讯",
        thesis: "验证利润、订单和经营现金流",
        latest_anchor_at: "2026-07-30T15:00:00+08:00",
        latest_available: [
          {
            id: "outcome-1",
            horizon_sessions: 3,
            result_status: "available",
            observed_sessions: 3,
            close_return_pct: -2.35,
            review_conclusion: "原价格区间未被确认，反方证据仍需保留。",
            target_timestamp: "2026-08-04T15:00:00+08:00",
          },
        ],
        latest_progress: null,
        coverage: { anchors: 2, available: 1, pending: 2 },
      },
    ],
    coverage: { requested_symbols: 1, with_archives: 1, available_outcomes: 1, pending_outcomes: 2 },
    method: "按第3、5、10个交易日回填研究条件。",
    boundary: "该复盘不评价买卖收益、策略胜率或荐股准确率。",
  };
}

export function runReviewsPayload() {
  return {
    items: [
      {
        id: "run-1",
        conversation_id: "conversation-1",
        conversation_title: "中兴通讯研究",
        question: "利润改善是否得到经营现金流确认？",
        intent: "stock_research",
        intent_label: "个股研究",
        status: "completed",
        status_label: "已完成",
        symbol: "000063.SZ",
        display_name: "中兴通讯",
        created_at: "2026-08-07T05:20:00+00:00",
        duration_seconds: 8.42,
        data_as_of: "2026-08-06T15:00:00+08:00",
        guard: { passed: true, repaired: false, label: "守卫通过", summary: [] },
        evidence: { ready_modules: 7, total_modules: 9, knowledge_documents: 2 },
        answer_excerpt: "现有证据只能确认利润同比改善，经营现金流仍需要同报告期核验。",
      },
    ],
    summary: { total: 1, filtered: 1, repaired: 0, statuses: { completed: 1 }, days: 30 },
  };
}

export const parsedResearchCenter = {
  priority: () => parseResearchPriority(priorityPayload()),
  changes: () => parseResearchChanges(changesPayload()),
  actions: () => parseResearchActions(actionsPayload()),
  evidenceTasks: () => parseEvidenceTasks(evidenceTasksPayload()),
  outcomes: () => parseResearchOutcomes(outcomesPayload()),
  runReviews: () => parseRunReviews(runReviewsPayload()),
};
