    const welcomeMessage = "你好，我是清数智算。我会记住这个对话的上下文，并结合实时证据、你的资料库、已确认记忆和金融 Skills 回答。";
    const evaluationMode = new URLSearchParams(window.location.search).get("qa") === "1";
    const state = {
      user: null,
      health: null,
      pendingImage: null,
      imageUploading: false,
      conversationId: null,
      conversations: [],
      conversationMessages: [],
      watchlist: [],
      researchActions: [],
      researchActionSummary: {},
      researchReports: [],
      selectedWatchlistSymbol: null,
      watchlistTimeframe: "intraday",
      watchlistFilter: "all",
      editingWatchlistSymbol: null,
      knowledge: [],
      knowledgeSummary: {},
      knowledgeQuery: "",
      knowledgeScope: "all",
      knowledgeType: "all",
      workspacePage: "insights",
      insightItems: [],
      insightFilter: "all",
      stockScreener: null,
      stockScreenerLoading: false,
      liZongStrategy: null,
      liZongLoading: false,
      liZongFilter: "qualified",
      deepStock: null,
      deepStockSessions: [],
      deepStockOverviewSymbol: null,
      stockSpaceTab: "overview",
      diagnosisSymbol: null,
      liveMarkets: [],
      marketBreadth: null,
      reviewTab: "outcomes",
      researchOutcomes: null,
      selectedOutcomeSymbol: null,
      reviewRuns: [],
      reviewRunSummary: {},
      selectedReviewRunId: null,
      reviewRunSearchTimer: null,
      reviewQuality: null,
      agentContextMetadata: {},
      agentContextQuestion: "",
      agentProcessExpanded: false,
      agentContextCollapsed: true,
      pendingAgentRequests: new Map(),
      agentResearchRunning: false,
      evaluationMode
    };
    const $ = (id) => document.getElementById(id);

    function currentWelcomeMessage() {
      return welcomeMessage;
    }

    function agentIntentLabel(intent) {
      return {
        market_brief: "大盘诊断",
        stock_screen: "选股研究",
        stock_research: "个股研究",
        business_structure: "主营结构",
        earnings_quality: "财报质量",
        financial_drivers: "利润与现金流",
        shareholder_structure: "股东结构",
        analyst_expectations: "分析师预期",
        event_timeline: "事件脉络",
        research_tracking: "研究变化",
        research_priority: "研究优先级",
        research_actions: "研究行动",
        research_outcome: "研究复盘",
        watchlist_brief: "自选股跟踪",
        general_research: "综合研究"
      }[intent] || "综合研究";
    }

    function appendAgentContextItem(container, {title, tag, copy}) {
      const item = document.createElement("div"); item.className = "agent-context-item";
      const head = document.createElement("div"); head.className = "agent-context-item-head";
      const titleNode = document.createElement("div"); titleNode.className = "agent-context-item-title"; titleNode.textContent = title;
      const tagNode = document.createElement("span"); tagNode.className = "agent-context-item-tag"; tagNode.textContent = tag;
      head.append(titleNode, tagNode); item.appendChild(head);
      if (copy) { const copyNode = document.createElement("div"); copyNode.className = "agent-context-item-copy"; copyNode.textContent = copy; item.appendChild(copyNode); }
      container.appendChild(item);
    }

    function collectAnswerSources(metadata = {}) {
      const structuredSources = metadata?.evidence_sources || metadata?.evidenceSources || [];
      const knowledgeSources = metadata?.knowledge_sources || metadata?.knowledgeSources || [];
      const marketSources = metadata?.market_sources || metadata?.marketSources || [];
      const rows = [];
      const seen = new Set();
      const push = item => {
        const title = String(item?.title || "").trim();
        if (!title) return;
        const key = `${String(item?.tag || item?.kind || "证据")}|${title}`;
        if (seen.has(key)) return;
        seen.add(key); rows.push({...item, title});
      };
      const evidenceTime = value => {
        const raw = String(value || "").trim();
        if (!raw) return "";
        return /^\d{4}-\d{2}-\d{2}$/.test(raw) ? raw : readableTime(raw);
      };
      structuredSources.forEach(source => push({
        title: source.title || "结构化证据",
        tag: source.kind || "证据",
        copy: source.summary || source.source || "本轮结构化证据",
        meta: [source.source, evidenceTime(source.as_of)].filter(Boolean).join(" · "),
        url: source.url || null
      }));
      knowledgeSources.forEach(source => push({
        title: source.title || source.original_name || "研究资料",
        tag: source.scope === "user" ? "个人资料" : "通用资料",
        copy: source.summary || source.snippet || "与当前问题相关的资料片段",
        documentId: source.document_id || null,
        scope: source.scope
      }));
      if (!structuredSources.length) marketSources.forEach(source => push({
        title: source.title || source.name || "市场资讯",
        tag: "市场资讯",
        copy: source.summary || source.source || source.published_at || "用于定位市场事件",
        meta: source.published_at ? readableTime(source.published_at) : ""
      }));
      return rows;
    }

    function setAgentProcessExpanded(expanded) {
      state.agentProcessExpanded = Boolean(expanded);
      $("agentResearchProcess")?.classList.toggle("collapsed", !state.agentProcessExpanded);
      if ($("agentProcessToggle")) {
        $("agentProcessToggle").textContent = state.agentProcessExpanded ? "收起研究过程" : "查看研究过程";
        $("agentProcessToggle").setAttribute("aria-expanded", state.agentProcessExpanded ? "true" : "false");
      }
    }

    function setAgentContextCollapsed(collapsed) {
      state.agentContextCollapsed = Boolean(collapsed);
      $("agentSection")?.classList.toggle("context-collapsed", state.agentContextCollapsed);
      if ($("agentContextToggle")) {
        $("agentContextToggle").textContent = state.agentContextCollapsed ? "展开金融侧栏" : "收起金融侧栏";
        $("agentContextToggle").setAttribute("aria-expanded", state.agentContextCollapsed ? "false" : "true");
      }
    }

    function renderAgentResearchProcess(metadata, question, evidenceSources) {
      const container = $("agentResearchProcess");
      if (!container) return;
      container.innerHTML = "";
      const targetTitle = $("diagnosisTitle")?.textContent || "等待识别市场或证券";
      const hasQuestion = Boolean(String(question || "").trim());
      const hasTarget = !targetTitle.includes("等待识别") || Boolean(metadata?.symbol || metadata?.marketKey || metadata?.market_key);
      const hasEvidence = evidenceSources.length > 0;
      const hasAnswer = Boolean(metadata && Object.keys(metadata).length) || state.conversationMessages.some(item => item.role === "assistant");
      const running = Boolean(state.agentResearchRunning);
      const steps = [
        {title: "理解问题", note: hasQuestion ? "已锁定当前研究问题" : "等待输入研究问题", status: hasQuestion ? "done" : "pending"},
        {title: "关联行情", note: hasTarget ? targetTitle : "按问题识别市场或证券", status: hasTarget ? "done" : hasQuestion ? "active" : "pending"},
        {title: "检索证据", note: hasEvidence ? `${evidenceSources.length} 项可追溯资料` : "等待检索资料与市场信息", status: hasEvidence ? "done" : running || hasQuestion ? "active" : "pending"},
        {title: "形成回答", note: running ? "生成中并进行事实校验" : hasAnswer ? "回答已保存，可继续追问" : "等待形成研究回答", status: running ? "active" : hasAnswer ? "done" : "pending"}
      ];
      steps.forEach((step, index) => {
        const item = document.createElement("div"); item.className = `agent-process-step ${step.status}`;
        const marker = document.createElement("span"); marker.className = "agent-process-index"; marker.textContent = step.status === "done" ? "✓" : String(index + 1);
        const copy = document.createElement("div"); copy.className = "agent-process-copy";
        const title = document.createElement("strong"); title.textContent = step.title;
        const note = document.createElement("span"); note.textContent = step.note;
        copy.append(title, note); item.append(marker, copy); container.appendChild(item);
      });
    }

    function renderAgentResearchContext(metadata = state.agentContextMetadata, question = state.agentContextQuestion) {
      state.agentContextMetadata = metadata || {};
      state.agentContextQuestion = question || "";
      const evidenceSources = collectAnswerSources(metadata);
      const targetTitle = $("diagnosisTitle")?.textContent || "等待识别市场或证券";
      const targetMeta = $("diagnosisMeta")?.textContent || "提出问题后自动关联行情、证据与研究上下文";
      $("agentTargetName").textContent = targetTitle;
      $("agentTargetMeta").textContent = question || targetMeta;
      $("agentSourceCount").textContent = evidenceSources.length;
      $("agentKnowledgeCount").textContent = state.knowledge.length;
      $("agentConversationCount").textContent = state.conversations.length;
      renderAgentResearchProcess(metadata, question, evidenceSources);

      const evidenceList = $("agentEvidenceList"); evidenceList.innerHTML = "";
      $("agentEvidenceSummary").textContent = evidenceSources.length
        ? `本轮展示 ${evidenceSources.length} 项可追溯证据，覆盖结构化行情、财务、公告资讯与资料库。`
        : "当前回答尚未附带可展示的证据索引。";
      evidenceSources.slice(0, 8).forEach(item => appendAgentContextItem(evidenceList, item));
      if (!evidenceSources.length) appendAgentContextItem(evidenceList, {title: "等待下一轮研究回答", tag: "证据", copy: "回答完成后，这里会列出个人资料、通用资料和市场资讯引用。"});

      const capabilityList = $("agentCapabilityList"); capabilityList.innerHTML = "";
      appendAgentContextItem(capabilityList, {
        title: state.health?.hermes_enabled ? "AI 实时综合研究" : "确定性研究回答",
        tag: state.health?.hermes_enabled ? "已启用" : "基础模式",
        copy: state.health?.hermes_enabled ? "按当前问题调用模型、资料库和金融研究工具。" : "先由确定性工具构建行情与分析证据。"
      });
      appendAgentContextItem(capabilityList, {title: `资料库检索 · ${state.knowledge.length} 份`, tag: "可用", copy: "只检索与当前问题相关的个人资料与通用资料。"});
      appendAgentContextItem(capabilityList, {title: `历史研究 · ${state.conversations.length} 个对话`, tag: "记忆", copy: "每个对话独立保存上下文，可继续追问或归档。"});
      appendAgentContextItem(capabilityList, {
        title: `${agentIntentLabel(metadata?.intent)}工作流`,
        tag: metadata?.status === "completed" ? "已完成" : "按需",
        copy: "确定性数据负责数字和指标，Agent 负责解释、反方审查与失效条件。"
      });
      [
        {title: "行情与技术结构", tag: "全市场", copy: "实时报价、日线、收益、均线、RSI、MACD、布林带、ATR、波动和回撤。"},
        {title: "财报质量与利润现金流", tag: "财务", copy: "对比同类报告期，拆解利润桥、费用率、营运资金与现金流矛盾。"},
        {title: "股东结构与分析师预期", tag: "A股", copy: "核验股东户数、前十大股东、评级分布、EPS预测和研报修订。"},
        {title: "公告、新闻与事件脉络", tag: "事件", copy: "公司公告优先，新闻用于定位线索，社区情绪只作为低权重证据。"},
        {title: "研究行动与结果回填", tag: "跟踪", copy: "把证据变化变成复核任务，并按固定周期核验原条件和失效信号。"}
      ].forEach(item => appendAgentContextItem(capabilityList, item));
    }

    function renderDiagnosisPlaceholder() {
      state.diagnosisSymbol = null;
      setAgentContextCollapsed(true);
      $("diagnosisContext").hidden = false;
      $("diagnosisTitle").textContent = "等待识别市场或证券";
      $("diagnosisMeta").textContent = "Agent 会根据问题自动呈现对应的大盘分钟线或个股日 K 线";
      $("diagnosisPrice").textContent = "—";
      $("diagnosisChange").className = "diagnosis-change flat";
      $("diagnosisChange").textContent = "—";
      $("diagnosisMetrics").innerHTML = '<div class="diagnosis-metric"><div class="diagnosis-metric-label">对话联动</div><div class="diagnosis-metric-value">等待提问</div></div>';
      const canvas = $("diagnosisKline");
      const context = canvas.getContext("2d");
      context?.clearRect(0, 0, canvas.width, canvas.height);
      renderAgentResearchContext();
    }

    function activateWorkspace(page = "insights") {
      const pages = {
        insights: ["今日观察", "全球行情、A股全景、行业轮动与个人研究脉冲"],
        agent: ["AI 研究", "连续对话、历史研究、自动 K 线与证据链"],
        screening: ["选股研究", "用确定性规则生成可解释研究候选，再进入个股空间继续核验"],
        deep_stock: ["个股研究", "围绕一只股票持续保存判断、变化、证据、任务、对话和报告"],
        watchlist: ["我的关注", "按研究状态管理自选股、下一动作与分时/日线/周线"],
        knowledge: ["资料库", "集中查看通用研究资料与个人资料，并管理可被 Agent 检索的内容"],
        review: ["复盘中心", "跟踪研究结论、后续验证与风险变化"]
      };
      if (!pages[page]) page = "insights";
      state.workspacePage = page;
      const insightsVisible = page === "insights";
      $("homeFocus").hidden = !insightsVisible;
      $("liveSection").hidden = !insightsVisible;
      $("marketDashboard").hidden = !insightsVisible;
      $("insightSection").hidden = !insightsVisible;
      $("insightAsk").hidden = !insightsVisible;
      $("watchlistPanel").hidden = page !== "watchlist";
      $("stockScreenerPanel").hidden = page !== "screening";
      $("deepStockPanel").hidden = page !== "deep_stock";
      $("knowledgePanel").hidden = page !== "knowledge";
      $("agentSection").hidden = page !== "agent";
      $("methodSection").hidden = page !== "review";
      $("productNotice").hidden = page === "agent" || page === "review";
      document.body.classList.toggle("agent-page", page === "agent");
      document.body.classList.toggle("review-page", page === "review");
      $("workspaceTitle").textContent = pages[page][0];
      $("workspaceSubtitle").textContent = pages[page][1];
      for (const button of document.querySelectorAll(".nav-item[data-page]")) {
        button.classList.toggle("active", button.dataset.page === page);
      }
      updateAgentMode();
      if (page === "insights") refreshInsightsIfStale();
      if (page === "agent" && state.conversationMessages.length) {
        requestAnimationFrame(() => { void syncDiagnosisFromConversation(state.conversationMessages); });
      }
      if (page === "review") void loadResearchMethod();
      if (page === "watchlist") void loadWatchlist();
      if (page === "screening") {
        if (!state.liZongStrategy) void loadLiZongStrategy();
        if (!state.stockScreener) void loadStockScreener();
      }
      if (page === "deep_stock") {
        void loadDeepStock();
        const symbol = $("deepStockSymbol").value;
        if (symbol) void loadDeepStockOverview(symbol);
      }
      if (page === "knowledge") void loadKnowledge();
      window.scrollTo({top: 0, behavior: "smooth"});
    }

    async function api(path, options = {}) {
      const isFormData = options.body instanceof FormData;
      const response = await fetch(path, {
        ...options,
        credentials: "same-origin",
        headers: {
          ...(isFormData ? {} : { "Content-Type": "application/json" }),
          ...(options.headers || {})
        }
      });
      let payload;
      try { payload = await response.json(); } catch { payload = {}; }
      if (!response.ok) throw new Error(payload.detail || `请求失败：${response.status}`);
      return payload;
    }

    // 并发的相同 GET 只发一次请求（启动时 loadWatchlist/loadArticles 会同时拉研究行动）。
    const inflightGetRequests = new Map();
    function apiGetShared(path) {
      if (!inflightGetRequests.has(path)) {
        inflightGetRequests.set(path, api(path).finally(() => inflightGetRequests.delete(path)));
      }
      return inflightGetRequests.get(path);
    }

    // 同一 loader 在途期间，重复触发复用同一个 Promise（SSE 与定时器经常同时点火）。
    function dedupLoader(loader) {
      let inflight = null;
      return function dedupedLoader(...args) {
        if (inflight) return inflight;
        inflight = Promise.resolve()
          .then(() => loader(...args))
          .finally(() => { inflight = null; });
        return inflight;
      };
    }

    // 通用 keyed 列表协调：按 key 复用既有行，仅对新增/内容变化/顺序变化的行做 DOM 操作，
    // 避免全量 innerHTML 重建带来的闪烁、焦点丢失和 canvas 重绘。
    // 每行的最新数据挂在 el._listItem 上，事件监听统一从 el._listItem 取数，避免闭包持有过期对象。
    // signature(item) 返回渲染所用字段的签名；签名未变的行跳过 update（保留 canvas、焦点与滚动状态）。
    function reconcileKeyedList(container, items, {key, signature = null, create, update}) {
      const previous = new Map();
      for (const child of Array.from(container.children)) {
        if (child.dataset && child.dataset.listKey !== undefined) previous.set(child.dataset.listKey, child);
        else if (child.classList && child.classList.contains("empty")) child.remove();
      }
      const ordered = items.map(item => {
        const k = String(key(item));
        let el = previous.get(k);
        const isNew = !el;
        if (isNew) {
          el = create(item);
          el.dataset.listKey = k;
        } else {
          previous.delete(k);
        }
        el._listItem = item;
        const sig = signature ? signature(item) : null;
        if (isNew || sig === null || el.dataset.listSig !== sig) {
          if (sig !== null) el.dataset.listSig = sig;
          update(el, item, isNew);
        }
        return el;
      });
      for (const stale of previous.values()) stale.remove();
      // 顺序对齐：只做必要的 insertBefore 移动，未变动行保持原节点。
      let ref = null;
      for (const child of container.children) {
        if (child.dataset && child.dataset.listKey !== undefined) { ref = child; break; }
      }
      for (const el of ordered) {
        if (el === ref) {
          ref = ref.nextElementSibling;
          while (ref && !(ref.dataset && ref.dataset.listKey !== undefined)) ref = ref.nextElementSibling;
        } else {
          container.insertBefore(el, ref);
        }
      }
      return ordered;
    }

    function pct(value) {
      if (value === null || value === undefined) return "—";
      const number = Number(value);
      return `${number > 0 ? "+" : ""}${number.toFixed(2)}%`;
    }

    function numeric(value) {
      if (value === null || value === undefined) return "—";
      return Number(value).toLocaleString("zh-CN", { maximumFractionDigits: 2 });
    }

    function compactNumber(value, currency = "") {
      const number = Number(value);
      if (!Number.isFinite(number)) return "—";
      const absolute = Math.abs(number);
      const suffix = currency ? ` ${currency}` : "";
      if (absolute >= 1e12) return `${(number / 1e12).toFixed(2)}万亿${suffix}`;
      if (absolute >= 1e8) return `${(number / 1e8).toFixed(2)}亿${suffix}`;
      if (absolute >= 1e4) return `${(number / 1e4).toFixed(2)}万${suffix}`;
      return `${numeric(number)}${suffix}`;
    }

    function liZongStatusLabel(value) {
      return {
        qualified: "候选待观察",
        triggered: "今日触发",
        data_incomplete: "数据待补",
        invalidated: "规则已失效",
        not_qualified: "未满足"
      }[value] || "待核验";
    }

    function liZongRuleLabel(value) {
      return {
        "LZ-F-01": "总市值严格大于150亿元",
        "LZ-F-02": "连续五个完整年度ROE达标",
        "LZ-F-04": "非自然人股东至少5名",
        "LZ-C-01": "近一年至少6次收盘涨停",
        "LZ-C-02": "近一年出现连续两日涨停",
        "LZ-C-03": "近十日存在收盘涨停",
        "LZ-C-04": "近十日无5%阴线",
        "LZ-VP-01": "近二十日出现360日复权新高",
        "LZ-VP-02": "连续三日成交量达到基准两倍",
        "LZ-T-01": "当日收盘涨停",
        "LZ-T-02": "高开至少3.5%且收阳",
        "LZ-T-03": "振幅严格大于9.8%且收阳"
      }[value] || value;
    }

    function liZongRuleStatus(value) {
      return {passed: "通过", failed: "未通过", data_incomplete: "数据不完整"}[value] || "待核验";
    }

    function strategyShortValue(value) {
      if (value === null || value === undefined) return "—";
      if (typeof value === "number") return numeric(value);
      if (typeof value === "string") return value;
      const text = JSON.stringify(value, null, 0);
      return text.length > 220 ? `${text.slice(0, 220)}…` : text;
    }

    function showLiZongDetail(item) {
      const lines = [
        `# ${item.name || item.internal_symbol}｜李总策略逐规则证据`,
        `策略版本：${item.strategy_version || "—"}；参数版本：${item.parameter_version || "—"}；数据交易日：${item.as_of_date || "待确认"}`,
        "",
        "## 规则核验"
      ];
      (item.rule_results || []).forEach(rule => {
        lines.push(`- ${rule.rule_id} ${liZongRuleLabel(rule.rule_id)}｜${liZongRuleStatus(rule.status)}`);
        lines.push(`  实际值：${strategyShortValue(rule.actual_value)}`);
        lines.push(`  阈值：${strategyShortValue(rule.threshold)}`);
        lines.push(`  证据时间：${rule.evidence_date || rule.report_period || "待确认"}；来源：${rule.source || "待确认"}；公式：${rule.formula_version || "—"}`);
        (rule.limitations || []).forEach(value => lines.push(`  限制：${value}`));
      });
      if (item.limitations?.length) {
        lines.push("", "## 当前边界", ...item.limitations.map(value => `- ${value}`));
      }
      lines.push("", `- ${item.boundary || "仅用于研究候选和人工复核。"}`);
      openReader(`${item.name || item.internal_symbol}｜李总策略证据`, lines.join("\n"), `${liZongStatusLabel(item.status)} · ${item.as_of_date || "数据时间待确认"}`);
    }

    function renderLiZongStrategy(payload) {
      state.liZongStrategy = payload;
      const items = payload?.items || [];
      const counts = payload?.counts || {};
      const meta = payload?.data_meta || {};
      const definition = payload?.strategy || {};
      $("liZongVersion").textContent = definition.current_version || definition.version?.version || "li_zong_v1";
      $("liZongDate").textContent = meta.latest_as_of_date || "待发布";
      $("liZongCoverage").textContent = `${meta.evaluated_symbols || 0} 只`;
      $("liZongQualified").textContent = counts.qualified ?? 0;
      $("liZongTriggered").textContent = counts.triggered ?? 0;
      $("liZongIncomplete").textContent = counts.data_incomplete ?? 0;
      $("liZongState").textContent = payload?.status === "ready" ? "研究数据已就绪" : "首批快照准备中";
      document.querySelectorAll("[data-li-zong-filter]").forEach(button => button.classList.toggle("active", button.dataset.liZongFilter === state.liZongFilter));

      const filtered = items.filter(item => item.status === state.liZongFilter);
      const container = $("liZongResults"); container.innerHTML = "";
      if (!filtered.length) {
        const empty = document.createElement("div"); empty.className = "screener-empty";
        empty.textContent = payload?.status === "ready"
          ? `${liZongStatusLabel(state.liZongFilter)}列表当前为空。系统会保留上一稳定结果，并在新数据发布后重新计算。`
          : "系统正在为当前研究池建立可追溯数据快照。页面不会用演示数字或供应商错误填充结果。";
        container.appendChild(empty); return;
      }
      filtered.forEach(item => {
        const summary = item.summary || {};
        const card = document.createElement("article"); card.className = "li-zong-card";
        const head = document.createElement("div"); head.className = "li-zong-card-head";
        const identity = document.createElement("div");
        const name = document.createElement("div"); name.className = "li-zong-card-name"; name.textContent = item.name || item.internal_symbol;
        const metaNode = document.createElement("div"); metaNode.className = "li-zong-card-meta"; metaNode.textContent = `${item.symbol || item.internal_symbol} · ${item.as_of_date || "数据时间待确认"} · ${item.parameter_version || "默认参数"}`;
        identity.append(name, metaNode);
        const badge = document.createElement("span"); badge.className = `li-zong-badge ${item.status || ""}`; badge.textContent = liZongStatusLabel(item.status);
        head.append(identity, badge); card.appendChild(head);

        const metricRows = [
          ["总市值", summary.market_cap_yi == null ? "—" : `${numeric(summary.market_cap_yi)}亿`],
          ["五年ROE最低", summary.roe_min_pct == null ? "—" : `${numeric(summary.roe_min_pct)}%`],
          ["机构股东", summary.non_natural_holder_count == null ? "—" : `${summary.non_natural_holder_count}名`],
          ["一年涨停", summary.annual_limit_up_count == null ? "—" : `${summary.annual_limit_up_count}次`],
          ["出现连板", summary.has_consecutive_limit_up ? "是" : "否"],
          ["十日涨停", summary.recent_limit_up_count == null ? "—" : `${summary.recent_limit_up_count}次`],
          ["十日5%阴线", summary.recent_bearish_drop_count == null ? "—" : `${summary.recent_bearish_drop_count}次`],
          ["近期新高", summary.new_high_dates?.length ? summary.new_high_dates.at(-1) : "未命中"],
          ["三日倍量", summary.volume_sequences?.length ? `${summary.volume_sequences.length}段` : "未命中"],
          ["当前触发", item.triggered_rule_ids?.length ? item.triggered_rule_ids.join("、") : "未触发"]
        ];
        const metrics = document.createElement("div"); metrics.className = "li-zong-metrics";
        metricRows.forEach(([label, value]) => {
          const node = document.createElement("div"); node.className = "li-zong-metric";
          const labelNode = document.createElement("span"); labelNode.textContent = label;
          const valueNode = document.createElement("strong"); valueNode.textContent = value;
          node.append(labelNode, valueNode); metrics.appendChild(node);
        });
        card.appendChild(metrics);
        if (item.limitations?.length) {
          const limitations = document.createElement("div"); limitations.className = "li-zong-limitations";
          limitations.textContent = item.limitations.slice(0, 2).join("；"); card.appendChild(limitations);
        }
        const actions = document.createElement("div"); actions.className = "li-zong-actions";
        const detail = document.createElement("button"); detail.type = "button"; detail.className = "btn"; detail.textContent = "查看逐规则证据"; detail.addEventListener("click", () => showLiZongDetail(item));
        const follow = document.createElement("button"); follow.type = "button"; follow.className = "btn"; follow.textContent = item.status === "triggered" ? "加入重点关注" : "加入关注"; follow.addEventListener("click", () => { void addScreenCandidateToWatchlist(item, follow, "李总策略"); });
        const research = document.createElement("button"); research.type = "button"; research.className = "btn primary"; research.textContent = "进入个股研究"; research.addEventListener("click", () => { void openDeepStockSymbol(item.internal_symbol); });
        const ask = document.createElement("button"); ask.type = "button"; ask.className = "btn"; ask.textContent = "让 Agent 核验"; ask.addEventListener("click", () => prepareAgentQuestion(`请核验${item.name}（${item.internal_symbol}）的李总策略结果。逐条说明基本面、股性、量价和触发规则的证据时间、反方证据、数据缺口、失效条件与下一步需要核验什么；不要输出买卖指令。`));
        actions.append(detail, follow, research, ask); card.appendChild(actions); container.appendChild(card);
      });
    }

    async function loadLiZongStrategy() {
      if (state.liZongLoading) return;
      state.liZongLoading = true;
      $("liZongState").textContent = "正在读取已发布快照";
      try {
        renderLiZongStrategy(await api("/v1/stock-strategies/li-zong/candidates?limit=200"));
      } catch {
        state.liZongStrategy = null;
        $("liZongState").textContent = "首批快照准备中";
        $("liZongResults").innerHTML = '<div class="screener-empty">系统正在准备可追溯策略快照；现有选股工具和个股研究仍可正常使用。</div>';
      } finally {
        state.liZongLoading = false;
      }
    }

    function stockScreenFieldLabel(key) {
      return {
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
        turnover_rate_pct: "换手率"
      }[key] || key;
    }

    function renderStockScreener(payload) {
      state.stockScreener = payload;
      const profile = payload?.profile || {};
      const meta = payload?.data_meta || {};
      const items = payload?.items || [];
      $("stockScreenTitle").textContent = profile.label || "研究候选";
      $("stockScreenCountBadge").textContent = `${items.length} 只`;
      const periods = meta.financial_report_periods || [];
      $("stockScreenMeta").textContent = [
        meta.latest_completed_trade_date ? `行情交易日 ${meta.latest_completed_trade_date}` : "行情日期待确认",
        meta.return_20d_base_date ? `20日比较基准 ${meta.return_20d_base_date}` : "",
        periods.length ? `财务报告期 ${periods.slice(0, 3).join("、")}` : "财务报告期逐只展示",
        profile.sort_rule || ""
      ].filter(Boolean).join(" · ");
      $("stockScreenBoundary").textContent = payload?.boundary || "这是可解释的研究候选筛选，不构成推荐、评级、目标价或交易建议。";

      const rules = $("stockScreenRules"); rules.innerHTML = "";
      (payload?.rules || []).slice(0, 10).forEach(rule => {
        const node = document.createElement("div"); node.className = "screener-rule";
        node.textContent = `${rule.field} ${rule.operator} ${rule.value}${rule.unit || ""}`;
        node.title = rule.reason || "确定性筛选条件";
        rules.appendChild(node);
      });
      if (!rules.childElementCount) {
        const node = document.createElement("div"); node.className = "screener-rule"; node.textContent = "当前规则正在整理。"; rules.appendChild(node);
      }

      const container = $("stockScreenResults"); container.innerHTML = "";
      if (!items.length) {
        const empty = document.createElement("div"); empty.className = "screener-empty";
        empty.textContent = payload?.status === "empty" ? "当前没有股票同时满足全部条件。建议一次只放宽一项规则后重新筛选。" : "完整市场截面正在准备，请稍后重试。";
        container.appendChild(empty); return;
      }
      items.forEach(item => {
        const card = document.createElement("article"); card.className = "screener-card";
        const head = document.createElement("div"); head.className = "screener-card-head";
        const identity = document.createElement("div");
        const name = document.createElement("div"); name.className = "screener-stock-name"; name.textContent = item.name || item.internal_symbol;
        const stockMeta = document.createElement("div"); stockMeta.className = "screener-stock-meta"; stockMeta.textContent = `${item.internal_symbol || item.ts_code} · ${item.industry || "行业待确认"}`;
        identity.append(name, stockMeta);
        const period = document.createElement("div"); period.className = "screener-period";
        period.textContent = item.financials?.report_period ? `财务报告期\n${item.financials.report_period}` : "财务报告期\n待补充";
        head.append(identity, period); card.appendChild(head);

        const metricRows = [
          ["近5日", pct(item.metrics?.return_5d_pct)],
          ["近20日", pct(item.metrics?.return_20d_pct)],
          ["行业超额", pct(item.metrics?.industry_excess_20d_pct)],
          ["PE TTM", numeric(item.metrics?.pe_ttm)],
          ["PB", numeric(item.metrics?.pb)],
          ["总市值", item.metrics?.total_mv_yi == null ? "—" : `${numeric(item.metrics.total_mv_yi)}亿`]
        ];
        const metrics = document.createElement("div"); metrics.className = "screener-metrics";
        metricRows.forEach(([label, value]) => {
          const metric = document.createElement("div"); metric.className = "screener-metric";
          const labelNode = document.createElement("span"); labelNode.textContent = label;
          const valueNode = document.createElement("strong"); valueNode.textContent = value;
          metric.append(labelNode, valueNode); metrics.appendChild(metric);
        });
        card.appendChild(metrics);

        const reasons = document.createElement("ul"); reasons.className = "screener-reasons";
        (item.matched_reasons || []).slice(0, 4).forEach(value => { const li = document.createElement("li"); li.textContent = value; reasons.appendChild(li); });
        card.appendChild(reasons);
        if (item.missing_fields?.length) {
          const missing = document.createElement("div"); missing.className = "screener-missing";
          missing.textContent = `仍需补充：${item.missing_fields.slice(0, 6).map(stockScreenFieldLabel).join("、")}`;
          card.appendChild(missing);
        }
        const actions = document.createElement("div"); actions.className = "screener-actions";
        const follow = document.createElement("button"); follow.type = "button"; follow.className = "btn"; follow.textContent = "加入关注";
        follow.addEventListener("click", () => { void addScreenCandidateToWatchlist(item, follow); });
        const research = document.createElement("button"); research.type = "button"; research.className = "btn primary"; research.textContent = "进入股票研究空间";
        research.addEventListener("click", () => { void openDeepStockSymbol(item.internal_symbol); });
        const ask = document.createElement("button"); ask.type = "button"; ask.className = "btn"; ask.textContent = "让 Agent 继续研究";
        ask.addEventListener("click", () => prepareAgentQuestion(`请继续研究${item.name}（${item.internal_symbol}）。它命中了“${profile.label || "研究候选"}”筛选，请核验最新财务、公告、反方证据、失效条件和当前仍缺失的信息。`));
        actions.append(follow, research, ask); card.appendChild(actions); container.appendChild(card);
      });
    }

    async function loadStockScreener() {
      if (state.stockScreenerLoading) return;
      state.stockScreenerLoading = true;
      const button = $("runStockScreener"); button.disabled = true; button.textContent = "正在筛选完整市场…";
      $("stockScreenResults").innerHTML = '<div class="screener-empty">正在对齐完整交易日行情、估值截面和候选财务指标…</div>';
      const filters = {};
      const industry = $("stockScreenIndustry").value.trim();
      const minCap = $("stockScreenMinCap").value;
      const maxPe = $("stockScreenMaxPe").value;
      if (industry) filters.industry = industry;
      if (minCap !== "") filters.min_market_cap_yi = Number(minCap);
      if (maxPe !== "") filters.max_pe_ttm = Number(maxPe);
      try {
        const payload = await api("/me/stock-screener", {
          method: "POST",
          body: JSON.stringify({
            profile: $("stockScreenProfile").value,
            market: $("stockScreenMarket").value,
            max_results: Number($("stockScreenCount").value),
            filters
          })
        });
        renderStockScreener(payload);
      } catch {
        state.stockScreener = null;
        $("stockScreenTitle").textContent = "市场数据正在准备";
        $("stockScreenMeta").textContent = "系统只会在完整行情截面可核验时返回候选。";
        $("stockScreenCountBadge").textContent = "— 只";
        $("stockScreenResults").innerHTML = '<div class="screener-empty">完整市场数据仍在准备，请稍后点击“执行确定性筛选”重试。</div>';
      } finally {
        state.stockScreenerLoading = false;
        button.disabled = false; button.textContent = "执行确定性筛选";
      }
    }

    async function addScreenCandidateToWatchlist(item, button, sourceLabel = null) {
      button.disabled = true;
      try {
        await api("/me/watchlist", {
          method: "POST",
          body: JSON.stringify({
            symbol: item.internal_symbol,
            name: item.name,
            market: "A股",
            thesis: `由${sourceLabel || state.stockScreener?.profile?.label || "研究候选筛选"}进入关注；需要继续核验财务、公告和反方证据。`
          })
        });
        button.textContent = "已加入关注";
        await loadWatchlist();
      } catch {
        button.disabled = false; button.textContent = "重试加入关注";
      }
    }

    function readableTime(value) {
      if (!value) return "时间待确认";
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return "时间待确认";
      return date.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
    }

    function readableResearchPreview(value) {
      return String(value || "")
        .replace(/\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})/g, match => readableTime(match))
        .replace(/。\s*(?=(?:最近完整日线|当前报价|下一步|复核))/g, "。\n")
        .replace(/[ \t]{2,}/g, " ")
        .trim();
    }

    function marketSessionDate(value, timezoneName = "UTC") {
      if (!value) return null;
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return null;
      try {
        return new Intl.DateTimeFormat("en-CA", {timeZone: timezoneName, year: "numeric", month: "2-digit", day: "2-digit"}).format(date);
      } catch { return date.toISOString().slice(0, 10); }
    }

    function cleanReaderInline(value) {
      return String(value || "").replace(/\*\*(.*?)\*\*/g, "$1").replace(/`([^`]+)`/g, "$1").trim();
    }

    function appendReaderText(container, body, documentTitle = "") {
      const lines = String(body || "内容正在生成。").split(/\r?\n/);
      let list = null;
      const flushList = () => {
        if (!list) return;
        container.appendChild(list);
        list = null;
      };
      for (const rawLine of lines) {
        const line = rawLine.trim();
        if (!line) { flushList(); continue; }
        const heading = line.match(/^(#{1,3})\s+(.+)$/);
        if (heading) {
          flushList();
          const headingText = cleanReaderInline(heading[2]);
          if (headingText === cleanReaderInline(documentTitle)) continue;
          const node = document.createElement("div");
          node.className = `reader-section-title${heading[1].length > 1 ? " sub" : ""}`;
          node.textContent = headingText;
          container.appendChild(node);
          continue;
        }
        const bullet = line.match(/^(?:[-*•]|\d+[.)])\s+(.+)$/);
        if (bullet) {
          if (!list) { list = document.createElement("ul"); list.className = "reader-list"; }
          const item = document.createElement("li"); item.textContent = cleanReaderInline(bullet[1]); list.appendChild(item);
          continue;
        }
        flushList();
        const node = document.createElement("p"); node.className = "reader-paragraph"; node.textContent = cleanReaderInline(line); container.appendChild(node);
      }
      flushList();
      if (!container.children.length) {
        const node = document.createElement("p"); node.className = "reader-paragraph"; node.textContent = "内容正在生成。"; container.appendChild(node);
      }
    }

    function openReader(title, body, meta = "", sourceUrl = "") {
      state.readerContext = {title: title || "研究内容", meta, body: body || ""};
      state.readerReturnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      $("readerTitle").textContent = title || "研究内容";
      $("readerMeta").textContent = meta;
      const readerBody = $("readerBody");
      readerBody.innerHTML = "";
      const copy = document.createElement("div"); copy.className = "reader-body-copy";
      appendReaderText(copy, body, title);
      readerBody.appendChild(copy);
      if (sourceUrl) {
        try {
          const parsed = new URL(sourceUrl, window.location.href);
          if (["http:", "https:"].includes(parsed.protocol)) {
            const link = document.createElement("a"); link.className = "reader-source-link"; link.href = parsed.href; link.target = "_blank"; link.rel = "noopener noreferrer"; link.textContent = "打开原始公告或信息源 ↗";
            readerBody.appendChild(link);
          }
        } catch { /* Invalid source links remain hidden. */ }
      }
      $("readerBackdrop").classList.add("open");
      $("readerBackdrop").setAttribute("aria-hidden", "false");
      document.body.style.overflow = "hidden";
      requestAnimationFrame(() => $("readerClose").focus());
    }

    function closeReader() {
      $("readerBackdrop").classList.remove("open");
      $("readerBackdrop").setAttribute("aria-hidden", "true");
      document.body.style.overflow = "";
      if (state.readerReturnFocus?.isConnected) state.readerReturnFocus.focus();
      state.readerReturnFocus = null;
    }

    function tone(value) {
      if (value > 0) return "up";
      if (value < 0) return "down";
      return "flat";
    }

    function watchlistQuote(item) {
      const current = item.current_quote || {};
      const change = current.pct_change ?? item.metrics?.return_1d_pct;
      return {
        price: current.price ?? item.latest_bar?.close ?? item.metrics?.latest_close,
        change,
        label: current.label || "最近收盘",
        marketTimestamp: current.market_timestamp || item.market_timestamp
      };
    }

    function appendInlineMarkdown(target, text) {
      const pattern = /(\*\*[^*\n]+\*\*|`[^`\n]+`)/g;
      let cursor = 0;
      for (const match of text.matchAll(pattern)) {
        if (match.index > cursor) target.appendChild(document.createTextNode(text.slice(cursor, match.index)));
        if (match[0].startsWith("**")) {
          const strong = document.createElement("strong");
          strong.textContent = match[0].slice(2, -2);
          target.appendChild(strong);
        } else {
          const code = document.createElement("code");
          code.textContent = match[0].slice(1, -1);
          target.appendChild(code);
        }
        cursor = match.index + match[0].length;
      }
      if (cursor < text.length) target.appendChild(document.createTextNode(text.slice(cursor)));
    }

    function renderMarkdown(text) {
      const fragment = document.createDocumentFragment();
      const lines = String(text || "").replace(/\r\n/g, "\n").split("\n");
      let list = null;
      let listType = null;
      let codeLines = null;
      let firstContent = true;
      const plainSectionHeading = /^(?:直接结论|核心判断|当日价格事实|最新行情事实|价格事实|财务与财报证据|财务与公告证据(?:（反方为主）)?|已确认的财务与公告证据|支持事件与反方事件|当日媒体叙事|可能解释|反方证据|不能确认的部分|证据边界|风险边界|结论)$/;
      const keyBoundaryLead = /^(最关键的不能确认部分|最关键的证据边界|最关键的反方证据|结论)[：:]\s*(.+)$/;
      const closeList = () => { list = null; listType = null; };
      const appendCode = () => {
        if (!codeLines) return;
        const pre = document.createElement("pre");
        const code = document.createElement("code");
        code.textContent = codeLines.join("\n");
        pre.appendChild(code); fragment.appendChild(pre); codeLines = null;
      };
      for (const line of lines) {
        if (/^```/.test(line.trim())) {
          if (codeLines) appendCode();
          else { closeList(); codeLines = []; }
          continue;
        }
        if (codeLines) { codeLines.push(line); continue; }
        if (!line.trim()) { closeList(); continue; }
        const heading = line.match(/^(#{1,4})\s+(.+)$/);
        if (heading) {
          closeList();
          const level = Math.min(4, heading[1].length + 1);
          const node = document.createElement(`h${level}`);
          appendInlineMarkdown(node, heading[2]); fragment.appendChild(node); firstContent = false; continue;
        }
        const chineseHeading = line.match(/^([一二三四五六七八九十]+[、.．])\s*(.+)$/);
        if (chineseHeading) {
          closeList();
          const node = document.createElement("h3");
          appendInlineMarkdown(node, `${chineseHeading[1]}${chineseHeading[2]}`); fragment.appendChild(node); firstContent = false; continue;
        }
        const trimmed = line.trim();
        if (plainSectionHeading.test(trimmed)) {
          closeList();
          const node = document.createElement("h3");
          node.textContent = trimmed; fragment.appendChild(node); firstContent = false; continue;
        }
        const unordered = line.match(/^\s*[-*]\s+(.+)$/);
        const ordered = line.match(/^\s*\d+[.)、]\s+(.+)$/);
        if (unordered || ordered) {
          const nextType = ordered ? "ol" : "ul";
          if (!list || listType !== nextType) {
            list = document.createElement(nextType); listType = nextType; fragment.appendChild(list);
          }
          const item = document.createElement("li");
          appendInlineMarkdown(item, (ordered || unordered)[1]); list.appendChild(item); firstContent = false; continue;
        }
        closeList();
        const quote = line.match(/^>\s?(.+)$/);
        const node = document.createElement(quote ? "blockquote" : "p");
        const copy = quote ? quote[1] : line;
        const boundary = !quote ? copy.match(keyBoundaryLead) : null;
        if (boundary) {
          node.className = "answer-key-boundary";
          const strong = document.createElement("strong"); strong.textContent = `${boundary[1]}：`;
          node.append(strong, document.createTextNode(boundary[2]));
        } else {
          if (firstContent && copy.length <= 80 && /(?:不能确认|可以确认|尚不能|结论|不支持|支持)/.test(copy)) node.className = "answer-conclusion";
          appendInlineMarkdown(node, copy);
        }
        fragment.appendChild(node);
        firstContent = false;
      }
      appendCode();
      return fragment;
    }

    function appendMessageSources(node, metadata) {
      const answerSources = collectAnswerSources(metadata);
      const sourceCount = answerSources.length;
      if (!sourceCount) return;
      const sources = document.createElement("details");
      sources.className = "message-sources";
      const summary = document.createElement("summary"); summary.textContent = `查看本轮证据与引用 · ${sourceCount} 项`;
      const list = document.createElement("div"); list.className = "message-source-list";
      answerSources.forEach(source => {
        const row = document.createElement(source.url ? "a" : source.documentId || source.copy ? "button" : "div");
        if (row.tagName === "BUTTON") row.type = "button";
        if (source.url) { row.href = source.url; row.target = "_blank"; row.rel = "noopener noreferrer"; }
        row.className = "message-source-item";
        const kind = document.createElement("span"); kind.className = "message-source-kind"; kind.textContent = source.tag || "证据";
        const title = document.createElement("span"); title.className = "message-source-title"; title.textContent = source.title || "研究资料";
        row.append(kind, title);
        if (source.copy) {
          const copy = document.createElement("span"); copy.className = "message-source-copy"; copy.textContent = source.copy; row.appendChild(copy);
        }
        if (source.meta) {
          const meta = document.createElement("span"); meta.className = "message-source-meta"; meta.textContent = source.meta; row.appendChild(meta);
        }
        if (source.documentId) row.addEventListener("click", async () => {
          row.disabled = true;
          try {
            const document = await api(`/me/knowledge/${encodeURIComponent(source.documentId)}`);
            openReader(document.title || source.title, document.content || "这份资料暂时没有可阅读正文。", `${source.scope === "user" ? "个人资料" : "通用资料"} · 更新 ${readableTime(document.updated_at)}`);
          } catch (error) {
            openReader(source.title || "研究资料", error?.message || "这份资料暂时无法读取。", "资料读取未完成");
          } finally { row.disabled = false; }
        });
        else if (!source.url && source.copy && row.tagName === "BUTTON") row.addEventListener("click", () => {
          openReader(source.title || "本轮证据", source.copy, source.meta || source.tag || "结构化证据");
        });
        list.appendChild(row);
      });
      sources.append(summary, list);
      node.appendChild(sources);
    }

    function appendMessageActions(node, text) {
      const actions = document.createElement("div"); actions.className = "message-actions";
      const copy = document.createElement("button");
      copy.type = "button"; copy.className = "message-action"; copy.textContent = "复制"; copy.title = "复制回答";
      copy.addEventListener("click", async () => {
        try {
          await navigator.clipboard.writeText(text);
          copy.textContent = "已复制";
          setTimeout(() => { copy.textContent = "复制"; }, 1200);
        } catch { copy.textContent = "复制失败"; }
      });
      actions.appendChild(copy); node.appendChild(actions);
    }

    function renderMessageContent(node, role, text, pending, metadata) {
      node.textContent = "";
      if (role === "agent" && !pending) {
        const body = document.createElement("div"); body.className = "message-body";
        body.appendChild(renderMarkdown(text)); node.appendChild(body);
        appendMessageSources(node, metadata);
        appendMessageActions(node, text);
      } else {
        node.textContent = text;
      }
    }

    function addMessage(role, text, pending = false, metadata = null) {
      const node = document.createElement("div");
      node.className = `message ${role}${pending ? " pending" : ""}`;
      renderMessageContent(node, role, text, pending, metadata);
      $("messages").appendChild(node);
      $("messages").scrollTop = $("messages").scrollHeight;
      return node;
    }

    function replaceMessageContent(node, text, metadata = null) {
      if (!node) return;
      node.classList.remove("pending");
      node.classList.remove("streaming-draft");
      renderMessageContent(node, "agent", text, false, metadata);
    }

    function comparableAnswerText(text) {
      return String(text || "")
        .replace(/(^|\n)\s*[-+]\s+/g, "$1")
        .replace(/[`*_>#]/g, "")
        .replace(/\s+/g, "")
        .trim();
    }

    function streamDraftWasRevised(draft, finalAnswer) {
      const draftText = comparableAnswerText(draft);
      const finalText = comparableAnswerText(finalAnswer);
      if (!draftText || !finalText) return false;
      return !finalText.startsWith(draftText);
    }

    function finalizeStreamingMessage(node, text, metadata = null, options = {}) {
      if (!node) return null;
      cancelScheduledDraft(node);
      const messages = $("messages");
      const distanceFromBottom = messages.scrollHeight - messages.scrollTop - messages.clientHeight;
      const keepAtBottom = distanceFromBottom < 96;
      const draft = String(options.draft || "");
      const revised = streamDraftWasRevised(draft, text);
      replaceMessageContent(node, text, metadata);
      node.classList.add("stream-finalized");
      if (draft) {
        const status = document.createElement("div");
        status.className = `stream-final-status${revised ? " revised" : ""}`;
        status.textContent = options.mode === "refine"
          ? "深度研究已完成 · 已在当前回答内更新最终结论"
          : revised
            ? "证据校验完成 · 草稿中的不确定内容已修正，以下为最终答案"
            : "证据校验完成 · 以下内容已保存为最终答案";
        node.prepend(status);
      }
      if (keepAtBottom) messages.scrollTop = messages.scrollHeight;
      return node;
    }

    function renderStreamingDraft(node, text, label = "AI 实时生成中（草稿） · 完成证据校验前内容可能调整") {
      if (!node?.isConnected) return;
      node.classList.remove("pending");
      node.classList.add("streaming-draft");
      node.textContent = "";
      const status = document.createElement("div"); status.className = "stream-draft-status"; status.textContent = label;
      const body = document.createElement("div"); body.className = "message-body"; body.appendChild(renderMarkdown(text));
      node.append(status, body);
      $("messages").scrollTop = $("messages").scrollHeight;
    }

    // SSE delta 可能每秒到达几十次；全量 Markdown 重渲染按 ~90ms 节流，只画最新草稿。
    const scheduledDraftRenders = new Map();
    function scheduleStreamingDraft(node, text, label) {
      if (!node) return;
      let entry = scheduledDraftRenders.get(node);
      if (!entry) {
        entry = {text: "", label: undefined, timer: null};
        scheduledDraftRenders.set(node, entry);
      }
      entry.text = text;
      if (label !== undefined) entry.label = label;
      if (entry.timer !== null) return;
      entry.timer = setTimeout(() => {
        entry.timer = null;
        scheduledDraftRenders.delete(node);
        if (!node.isConnected || node.classList.contains("stream-finalized")) return;
        renderStreamingDraft(node, entry.text, entry.label);
      }, 90);
    }
    function cancelScheduledDraft(node) {
      const entry = scheduledDraftRenders.get(node);
      if (entry?.timer !== null && entry?.timer !== undefined) clearTimeout(entry.timer);
      scheduledDraftRenders.delete(node);
    }

    function connectPrivateAgentStream(requestId, pending) {
      const source = new EventSource(`/me/chat/stream/${encodeURIComponent(requestId)}`);
      const context = {node: pending, source, draft: "", opened: false};
      state.pendingAgentRequests.set(requestId, context);
      let settleReady;
      const ready = new Promise(resolve => { settleReady = resolve; });
      const timer = setTimeout(() => settleReady(), 600);
      source.onopen = () => {
        context.opened = true;
        clearTimeout(timer);
        settleReady();
      };
      source.onmessage = event => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === "agent_progress" && data.label && !context.draft && pending.isConnected) {
            pending.textContent = data.label;
          }
          if (data.type === "agent_delta" && data.draft) {
            context.draft = data.draft;
            scheduleStreamingDraft(pending, context.draft);
          }
          if (data.type === "agent_stream_status" && data.label) {
            if (context.draft) scheduleStreamingDraft(pending, context.draft, data.label);
            else if (pending.isConnected) pending.textContent = data.label;
          }
          if (["agent_stream_complete", "agent_stream_error"].includes(data.type)) source.close();
        } catch { /* malformed private events do not affect the final HTTP answer */ }
      };
      source.onerror = () => {
        clearTimeout(timer);
        settleReady();
      };
      return {source, ready, context};
    }

    function visibleConversationItems(items = []) {
      return items.filter(item => state.evaluationMode
        ? item.quality_scope === "evaluation"
        : item.quality_scope !== "evaluation");
    }

    function renderConversationList(items) {
      state.conversations = visibleConversationItems(items || []);
      for (const container of [$("conversationList"), $("agentHistoryList")]) {
        container.innerHTML = "";
        for (const item of state.conversations) {
          const row = document.createElement("div");
          row.className = `conversation-row${item.id === state.conversationId ? " active" : ""}`;
          const open = document.createElement("button"); open.className = "conversation-open"; open.type = "button";
          const title = document.createElement("span"); title.className = "conversation-title"; title.textContent = item.title || "新的研究对话";
          const meta = document.createElement("span"); meta.className = "conversation-meta";
          meta.textContent = `${item.message_count || 0} 条消息 · 更新 ${readableTime(item.updated_at)}`;
          open.title = `${title.textContent} · ${meta.textContent}`;
          open.append(title, meta);
          open.addEventListener("click", () => openConversation(item.id));
          const remove = document.createElement("button"); remove.className = "conversation-delete"; remove.type = "button"; remove.title = "归档对话"; remove.textContent = "×";
          remove.addEventListener("click", async event => {
            event.stopPropagation();
            await archiveConversation(item.id);
          });
          row.append(open, remove); container.appendChild(row);
        }
        if (!container.children.length) container.innerHTML = '<div class="knowledge-summary">还没有历史对话</div>';
      }
      const switcher = $("conversationSwitcher");
      switcher.innerHTML = '<option value="">新的研究对话</option>';
      for (const item of state.conversations) {
        const option = document.createElement("option");
        option.value = item.id;
        option.textContent = item.title || "新的研究对话";
        switcher.appendChild(option);
      }
      switcher.value = state.conversationId || "";
      renderAgentResearchContext();
    }

    async function loadConversations(openLatest = false, activatePage = false) {
      if (!state.user) return;
      const data = await api("/me/conversations?limit=100");
      const visibleItems = visibleConversationItems(data.items || []);
      renderConversationList(visibleItems);
      if (openLatest && !state.conversationId && visibleItems.length) {
        await openConversation(visibleItems[0].id, activatePage);
      }
    }

    async function openConversation(conversationId, activatePage = true) {
      if (activatePage) activateWorkspace("agent");
      const data = await api(`/me/conversations/${encodeURIComponent(conversationId)}`);
      state.conversationId = data.id;
      state.conversationMessages = data.messages || [];
      const boundDeepStockSession = state.deepStockSessions.find(item => item.conversation_id === data.id) || null;
      const lastAssistant = [...state.conversationMessages].reverse().find(item => item.role === "assistant");
      const lastUser = [...state.conversationMessages].reverse().find(item => item.role === "user");
      state.agentContextMetadata = lastAssistant?.metadata || {};
      state.agentContextQuestion = lastUser?.content || data.title || "";
      setAgentProcessExpanded(false);
      $("conversationTitle").textContent = data.title || "金融研究 Agent";
      $("messages").innerHTML = "";
      if ((data.messages || []).length) {
        const freshness = document.createElement("div");
        freshness.className = "history-freshness";
        freshness.textContent = `历史回答保留生成时的证据快照（最近更新 ${readableTime(data.updated_at)}）；涉及当日行情，请直接追问“用最新数据重新分析”。`;
        $("messages").appendChild(freshness);
      }
      renderDiagnosisPlaceholder();
      if (!(data.messages || []).length) {
        addMessage(
          "agent",
          boundDeepStockSession
            ? `已关联${boundDeepStockSession.name || boundDeepStockSession.symbol}的长期研究空间。下方已经准备好当前阶段问题，你可以直接发送，也可以改成自己最关心的问法。`
            : currentWelcomeMessage()
        );
      }
      for (const message of (data.messages || [])) {
        addMessage(message.role === "assistant" ? "agent" : "user", message.content, false, message.metadata);
      }
      if ((data.messages || []).length) await syncDiagnosisFromConversation(data.messages || []);
      else if (boundDeepStockSession?.symbol) {
        state.agentContextMetadata = {symbol: boundDeepStockSession.symbol, intent: "stock_research"};
        state.agentContextQuestion = boundDeepStockSession.next_question || data.title || "";
        await loadStockDiagnosis(boundDeepStockSession.symbol);
        if (boundDeepStockSession.next_question) $("chatInput").value = boundDeepStockSession.next_question;
      }
      renderConversationList(state.conversations);
      clearImageAttachment();
      await loadMemoryCandidates();
      if (state.workspacePage === "agent") $("chatInput").focus();
    }

    function startNewConversation(activatePage = true) {
      if (activatePage) activateWorkspace("agent");
      state.conversationId = null;
      state.conversationMessages = [];
      state.agentContextMetadata = {};
      state.agentContextQuestion = "";
      setAgentProcessExpanded(false);
      $("conversationTitle").textContent = "新的研究对话";
      $("messages").innerHTML = "";
      addMessage("agent", currentWelcomeMessage());
      renderDiagnosisPlaceholder();
      renderConversationList(state.conversations);
      clearImageAttachment();
      if (state.workspacePage === "agent") $("chatInput").focus();
    }

    async function archiveConversation(conversationId) {
      try {
        await api(`/me/conversations/${encodeURIComponent(conversationId)}`, {method: "DELETE"});
        if (state.conversationId === conversationId) startNewConversation(false);
        await loadConversations(false);
      } catch { addMessage("agent", "这个对话暂时无法归档，请稍后重试。"); }
    }

    function knowledgeCategory(item) {
      const key = `${item.original_name || ""} ${item.title || ""}`.toLowerCase();
      if (/evidence-hierarchy|market-causality|market-trend-risk|research-workflows|证据规则|研究工作流/.test(key)) return {key: "method", label: "规则与方法"};
      if (/earnings-quality|financial-drivers|business-structure|filing-evidence|peer-operating|财报|利润|现金流|主营|同行/.test(key)) return {key: "financial", label: "财务与经营"};
      if (/event-timeline|事件脉络|公告/.test(key)) return {key: "event", label: "事件与公告"};
      if (/analyst-expectations|shareholder-structure|分析师|股东/.test(key)) return {key: "ownership", label: "预期与股东"};
      if (/research-archive|research-outcome|research-actions|研究档案|研究结果复盘|研究行动/.test(key)) return {key: "research", label: "研究档案"};
      return {key: "other", label: "其他资料"};
    }

    function knowledgeSymbol(item) {
      return `${item.original_name || ""} ${item.title || ""}`.match(/\b(?:\d{6}\.(?:SZ|SS)|NVDA)\b/i)?.[0]?.toUpperCase() || "";
    }

    async function openKnowledgeDocument(item, button) {
      const original = button.textContent;
      button.disabled = true; button.textContent = "读取中…";
      try {
        const document = await api(`/me/knowledge/${encodeURIComponent(item.id)}`);
        const category = knowledgeCategory(item);
        openReader(document.title || item.title, document.content || "这份资料暂时没有可阅读正文。", `${category.label} · ${item.scope === "user" ? "个人资料" : "通用资料"} · 更新 ${readableTime(item.updated_at)}`);
      } catch (error) {
        openReader(item.title, error?.message || "这份资料暂时无法读取。", "资料读取未完成");
      } finally {
        button.disabled = false; button.textContent = original;
      }
    }

    function renderKnowledge(data = null) {
      if (data) {
        state.knowledge = data.items || [];
        state.knowledgeSummary = data.summary || {};
      }
      renderAgentResearchContext();
      $("knowledgeSummary").textContent = `通用资料 ${state.knowledgeSummary.common || 0} 份 · 个人资料 ${state.knowledgeSummary.user || 0} 份 · Agent 只会检索与当前问题相关的片段`;
      const query = state.knowledgeQuery.trim().toLowerCase();
      const visibleItems = state.knowledge.filter(item => {
        const category = knowledgeCategory(item);
        const haystack = `${item.title || ""} ${item.original_name || ""} ${knowledgeSymbol(item)}`.toLowerCase();
        return (!query || haystack.includes(query))
          && (state.knowledgeScope === "all" || item.scope === state.knowledgeScope)
          && (state.knowledgeType === "all" || category.key === state.knowledgeType);
      });
      $("knowledgeVisibleCount").textContent = `显示 ${visibleItems.length} / ${state.knowledge.length} 份资料`;
      const container = $("knowledgeList"); container.innerHTML = "";
      for (const item of visibleItems) {
        const row = document.createElement("div"); row.className = "knowledge-item";
        const identity = document.createElement("div");
        const title = document.createElement("div"); title.className = "knowledge-item-title"; title.title = item.title; title.textContent = item.title;
        const meta = document.createElement("div"); meta.className = "knowledge-item-meta";
        const symbol = knowledgeSymbol(item);
        meta.textContent = `${item.original_name || "系统生成资料"} · ${numeric(item.content_chars || 0)} 字${symbol ? ` · ${symbol}` : ""}`;
        identity.append(title, meta);
        const category = knowledgeCategory(item);
        const categoryNode = document.createElement("div"); categoryNode.className = "knowledge-category"; categoryNode.textContent = category.label;
        const badge = document.createElement("span"); badge.className = `knowledge-badge${item.scope === "user" ? " user" : ""}`; badge.textContent = item.scope === "user" ? "个人" : "通用";
        const updated = document.createElement("div"); updated.className = "knowledge-updated"; updated.textContent = readableTime(item.updated_at);
        const controls = document.createElement("div"); controls.className = "knowledge-item-controls";
        const read = document.createElement("button"); read.className = "knowledge-read"; read.type = "button"; read.textContent = "查看";
        read.addEventListener("click", () => { void openKnowledgeDocument(item, read); });
        controls.appendChild(read);
        if (item.scope === "user") {
          const remove = document.createElement("button"); remove.className = "knowledge-remove"; remove.type = "button"; remove.title = "删除个人资料"; remove.textContent = "×";
          remove.addEventListener("click", async () => {
            if (!window.confirm(`确定删除“${item.title}”吗？删除后 Agent 将无法再检索这份个人资料。`)) return;
            try { await api(`/me/knowledge/${encodeURIComponent(item.id)}`, {method:"DELETE"}); await loadKnowledge(); }
            catch { addMessage("agent", "这份个人资料暂时无法删除。"); }
          });
          controls.appendChild(remove);
        }
        row.append(identity, categoryNode, badge, updated, controls);
        container.appendChild(row);
      }
      if (!container.children.length) container.innerHTML = '<div class="empty">没有符合当前筛选条件的资料。</div>';
    }

    async function loadKnowledge() {
      if (!state.user) return;
      renderKnowledge(await api("/me/knowledge"));
    }

    async function uploadKnowledgeFile(file) {
      if (!file) return;
      $("uploadKnowledge").disabled = true;
      $("uploadKnowledge").textContent = "正在入库…";
      const form = new FormData(); form.append("file", file, file.name);
      try {
        const document = await api("/me/knowledge", {method: "POST", body: form});
        await loadKnowledge();
        addMessage("agent", `已将“${document.title}”加入你的资料库，后续对话会按问题自动检索。`);
      } catch (error) {
        addMessage("agent", error.message || "这份资料暂时无法入库。");
      } finally {
        $("knowledgeInput").value = "";
        $("uploadKnowledge").disabled = false;
        $("uploadKnowledge").textContent = "＋ 添加个人资料";
      }
    }

    async function resolveMemoryCandidate(memoryId, action, card) {
      const buttons = card.querySelectorAll("button");
      buttons.forEach(button => button.disabled = true);
      const status = card.querySelector(".memory-card-status");
      status.textContent = action === "confirm" ? "正在保存个人偏好…" : "正在处理…";
      try {
        await api(`/me/memories/${encodeURIComponent(memoryId)}/${action}`, { method: "POST" });
        card.classList.add("resolved");
        card.querySelector(".memory-card-actions")?.remove();
        status.textContent = action === "confirm"
          ? "已保存为长期偏好，后续研究会结合这条信息。"
          : "本次不保存，不会用于后续研究。";
      } catch {
        status.textContent = "这次操作暂未完成，请重试。";
        buttons.forEach(button => button.disabled = false);
      }
    }

    function renderMemoryCandidate(memory, answer = "") {
      if (answer) addMessage("agent", answer);
      if (!memory?.id || document.querySelector(`[data-memory-id="${memory.id}"]`)) return;
      const card = document.createElement("div");
      card.className = "memory-card";
      card.dataset.memoryId = memory.id;
      const title = document.createElement("div"); title.className = "memory-card-title"; title.textContent = "待确认的个人偏好";
      const content = document.createElement("div"); content.className = "memory-card-content"; content.textContent = memory.content || "";
      const status = document.createElement("div"); status.className = "memory-card-status"; status.textContent = "只有你确认后，它才会用于后续分析。";
      const actions = document.createElement("div"); actions.className = "memory-card-actions";
      const confirm = document.createElement("button"); confirm.className = "btn primary"; confirm.textContent = "确认保存";
      const reject = document.createElement("button"); reject.className = "btn"; reject.textContent = "暂不保存";
      confirm.addEventListener("click", () => resolveMemoryCandidate(memory.id, "confirm", card));
      reject.addEventListener("click", () => resolveMemoryCandidate(memory.id, "reject", card));
      actions.append(confirm, reject); card.append(title, content, status, actions); $("messages").appendChild(card);
      $("messages").scrollTop = $("messages").scrollHeight;
    }

    async function loadMemoryCandidates() {
      if (!state.user) return;
      try {
        const data = await api("/me/memories?status=candidate");
        for (const memory of (data.items || []).slice(0, 3).reverse()) renderMemoryCandidate(memory);
      } catch { /* session recovery is handled by ensureUser */ }
    }

    async function ensureUser() {
      let user = null;
      try {
        user = await api("/session");
      } catch {
        const legacyUserId = localStorage.getItem("qingshu_demo_user");
        if (legacyUserId) {
          try {
            user = await api("/sessions/claim", {
              method: "POST",
              body: JSON.stringify({ user_id: legacyUserId })
            });
          } catch { /* already claimed or invalid legacy workspace */ }
          localStorage.removeItem("qingshu_demo_user");
        }
      }
      if (!user) {
        user = await api("/users", {
          method: "POST",
          body: JSON.stringify({ name: "网页体验用户" })
        });
      }
      state.user = user;
      $("userStatus").textContent = `个人空间 · ${user.name}`;
    }

    function renderImageAttachment() {
      const container = $("imageAttachment");
      if (state.imageUploading) {
        container.hidden = false;
        $("imageAttachmentName").textContent = "正在安全处理图片…";
        $("removeImage").hidden = true;
      } else if (state.pendingImage) {
        container.hidden = false;
        $("imageAttachmentName").textContent = `已附加：${state.pendingImage.original_name}`;
        $("removeImage").hidden = false;
      } else {
        container.hidden = true;
        $("imageAttachmentName").textContent = "";
      }
      $("attachImage").disabled = state.imageUploading || !state.health?.hermes_enabled;
      if (state.pendingImage) $("useHermes").checked = true;
      $("useHermes").disabled = !state.health?.hermes_enabled || state.imageUploading || Boolean(state.pendingImage);
      updateAgentMode();
    }

    function clearImageAttachment() {
      state.pendingImage = null;
      state.imageUploading = false;
      $("imageInput").value = "";
      renderImageAttachment();
    }

    async function uploadSelectedImage(file) {
      if (!file || !state.health?.hermes_enabled) return;
      state.imageUploading = true;
      renderImageAttachment();
      const form = new FormData();
      form.append("file", file, file.name);
      try {
        state.pendingImage = await api("/me/uploads/images", { method: "POST", body: form });
        $("useHermes").checked = true;
      } catch {
        state.pendingImage = null;
        addMessage("agent", "这张图片未能安全读取，请使用 PNG、JPEG 或 WebP，并确认文件大小合适。");
      } finally {
        state.imageUploading = false;
        renderImageAttachment();
      }
    }

    function renderSystemHealth(dataHealth) {
      const status = dataHealth?.status || "initializing";
      const initializing = status === "initializing";
      $("systemStatus").className = `status-pill ${initializing ? "attention" : "live"}`;
      $("systemStatus").textContent = initializing ? "正在准备研究服务" : "研究服务已连接";
      renderHomeFocus();
    }

    function renderHomeFocus() {
      if (!$("homeFocus")) return;
      const openMarkets = state.liveMarkets.filter(item => item.is_open);
      const latestMarketTimestamp = state.liveMarkets
        .map(item => item.market_timestamp)
        .filter(Boolean)
        .sort((a, b) => new Date(b) - new Date(a))[0];
      const priorityCount = state.researchActions.filter(item => ["risk_review", "priority_research"].includes(item.research_status)).length;
      const pendingCount = state.researchActions.reduce((sum, item) => sum + (item.actions || []).filter(action => action.status === "pending_data").length, 0);
      const priorityItems = [...state.researchActions]
        .filter(item => ["risk_review", "priority_research", "pending_review"].includes(item.research_status))
        .sort((a, b) => ({risk_review: 3, priority_research: 2, pending_review: 1}[b.research_status] || 0) - ({risk_review: 3, priority_research: 2, pending_review: 1}[a.research_status] || 0));
      const topPriority = priorityItems[0] || null;
      const breadth = state.marketBreadth?.breadth || {};
      const liveChina = state.liveMarkets.find(item => item.name === "中国A股" || item.instrument === "上证综指");
      const liveChinaDate = liveChina?.market_timestamp ? marketSessionDate(liveChina.market_timestamp, "Asia/Shanghai") : null;
      const breadthDate = state.marketBreadth?.market_date || null;
      const breadthIsPrevious = Boolean(liveChinaDate && breadthDate && breadthDate < liveChinaDate);
      const breadthTimeLabel = breadthIsPrevious ? "上一完整交易日" : "当前市场日期";
      const sessionTag = $("homeSessionTag");
      sessionTag.className = `home-focus-tag ${openMarkets.length ? "live" : "closed"}`;
      sessionTag.textContent = openMarkets.length
        ? `${openMarkets.length} 个市场交易中`
        : (state.liveMarkets.length ? "主要市场当前休市" : "正在读取市场状态");
      $("homeEvidenceTime").textContent = latestMarketTimestamp
        ? `行情更新 ${readableTime(latestMarketTimestamp)}`
        : (state.marketBreadth?.market_date ? `A股市场日期 ${marketDateLabel(state.marketBreadth.market_date)}` : "等待第一批行情");
      $("homeMarketStepMeta").textContent = state.liveMarkets.length
        ? `覆盖 ${state.liveMarkets.length} 个市场 · ${openMarkets.length} 个交易中`
        : "正在读取实时市场";
      $("homeAShareStepMeta").textContent = breadth.total
        ? `${breadthTimeLabel} · ${numeric(Number(breadth.advance_ratio || 0) * 100)}% 上涨`
        : "正在读取全市场涨跌";
      $("homeWatchStepMeta").textContent = state.watchlist.length
        ? (topPriority ? `${topPriority.name || topPriority.symbol} · ${topPriority.research_status_label || "优先复核"}` : `${state.watchlist.length} 只关注 · 暂无新增冲突`)
        : "添加关注后形成研究任务";

      const marketCopy = openMarkets.length
        ? `${openMarkets.map(item => item.name).join("、")}正在交易。`
        : (state.liveMarkets.length ? "当前展示主要市场最近一次可用行情。" : "全球市场行情正在载入。 ");
      const breadthCopy = breadth.total
        ? `A股${breadthIsPrevious ? `上一完整交易日（${marketDateLabel(breadthDate)}）` : "当前市场日期"}${breadth.state || "广度已更新"}，上涨 ${breadth.advancers || 0} 家、下跌 ${breadth.decliners || 0} 家。`
        : "A股全市场广度正在同步。";
      const researchCopy = priorityCount
        ? `${topPriority?.name || "自选股"}等 ${priorityCount} 只标的需要优先复核${pendingCount ? `，另有 ${pendingCount} 项待补证` : ""}。`
        : (state.watchlist.length ? "当前自选股没有新增的优先复核任务。" : "添加关注股票后会形成持续研究任务。 ");
      $("homeFocusCopy").textContent = `${marketCopy}${breadthCopy}${researchCopy}`;
    }

    function prepareAgentQuestion(question) {
      activateWorkspace("agent");
      startNewConversation(false);
      $("chatInput").value = question;
      state.agentContextQuestion = question;
      renderAgentResearchContext(state.agentContextMetadata, question);
      $("chatInput").focus();
    }

    function updateAgentMode() {
      const evaluationSuffix = state.evaluationMode ? " · 验收隔离" : "";
      if (!state.health?.hermes_enabled) {
        $("agentMode").textContent = `基础研究${evaluationSuffix}`;
        return;
      }
      if (!$("useHermes").checked) {
        $("agentMode").textContent = `确定性研究${evaluationSuffix}`;
        return;
      }
      if (state.pendingImage) {
        $("agentMode").textContent = `AI 图像研究${evaluationSuffix}`;
        return;
      }
      if (state.workspacePage === "agent") {
        const mode = $("modelTier").value === "deep"
          ? "AI 实时深度研究"
          : "AI 实时研究";
        $("agentMode").textContent = `${mode}${evaluationSuffix}`;
        return;
      }
      const mode = $("modelTier").value === "deep" ? "AI 深度研究" : "AI 标准解读";
      $("agentMode").textContent = `${mode}${evaluationSuffix}`;
    }

    async function loadHealth() {
      state.health = await api("/health");
      renderSystemHealth(state.health.data_health);
      $("useHermes").disabled = !state.health.hermes_enabled;
      $("useHermes").checked = Boolean(state.health.hermes_enabled);
      $("useHermesLabel").hidden = !state.health.hermes_enabled;
      renderImageAttachment();
    }

    function researchStatusMeta(status) {
      return {
        risk_review: {label: "风险复核", color: "#e34b52"},
        priority_research: {label: "优先研究", color: "#eaa331"},
        pending_review: {label: "待补证", color: "#4d83e8"},
        observe: {label: "持续观察", color: "#22a579"}
      }[status] || {label: "持续观察", color: "#9aa6b5"};
    }

    function researchActionFor(symbol) {
      return state.researchActions.find(item => item.symbol === symbol) || null;
    }

    function primaryResearchAction(item) {
      const actions = item?.actions || [];
      return actions.find(action => action.status === "triggered")
        || actions.find(action => action.status === "pending_data")
        || actions[0]
        || null;
    }

    function renderSectors(data) {
      const container = $("sectors");
      const sectors = data.sectors || [];
      reconcileKeyedList(container, sectors.map((item, index) => ({item, index})), {
        key: ({item}) => item.code || item.name,
        signature: ({item, index}) => JSON.stringify([
          index, item.name, item.code, item.pct_change,
          item.advancers, item.decliners, item.unchanged, item.main_net_inflow
        ]),
        create() {
          const row = document.createElement("button"); row.type = "button"; row.className = "sector-rotation-row";
          const rank = document.createElement("span");
          const name = document.createElement("span"); name.className = "sector-name";
          const change = document.createElement("strong");
          const breadth = document.createElement("div"); breadth.className = "sector-breadth";
          const track = document.createElement("div"); track.className = "sector-breadth-track";
          const fill = document.createElement("span"); track.appendChild(fill);
          const breadthValue = document.createElement("small");
          breadth.append(track, breadthValue);
          const flow = document.createElement("span");
          row.append(rank, name, change, breadth, flow);
          row._refs = {rank, name, change, fill, breadthValue, flow};
          row.addEventListener("click", () => {
            const current = row._listItem.item;
            prepareAgentQuestion(`分析A股“${current.name || current.code}”板块当前表现：先说明涨跌幅、内部上涨比例和数据时间，再结合公开信息解释可能驱动、反方证据以及不能确认的部分；不要把主力净流入字段直接解释成真实资金意图。`);
          });
          return row;
        },
        update(row, {item, index}) {
          const refs = row._refs;
          const total = Number(item.advancers || 0) + Number(item.decliners || 0) + Number(item.unchanged || 0);
          const advanceRatio = total ? Number(item.advancers || 0) / total : 0;
          row.setAttribute("aria-label", `研究${item.name || item.code}板块`);
          refs.rank.className = `sector-rank${index < 3 ? " top" : ""}`;
          refs.rank.textContent = index + 1;
          refs.name.textContent = item.name || item.code;
          refs.change.className = tone(item.pct_change);
          refs.change.textContent = pct(item.pct_change);
          refs.fill.style.width = `${Math.max(0, Math.min(100, advanceRatio * 100))}%`;
          refs.breadthValue.textContent = total ? `${Math.round(advanceRatio * 100)}%` : "—";
          refs.flow.className = `sector-flow ${tone(item.main_net_inflow)}`;
          refs.flow.textContent = compactNumber(item.main_net_inflow);
        }
      });
      let head = container.querySelector(".sector-table-head");
      if (sectors.length) {
        if (!head) {
          head = document.createElement("div"); head.className = "sector-table-head";
          for (const label of ["排名", "板块", "涨跌幅", "内部上涨", "主力净流入"]) {
            const cell = document.createElement("span"); cell.textContent = label; head.appendChild(cell);
          }
          container.prepend(head);
        }
      } else {
        head?.remove();
        container.innerHTML = '<div class="empty">板块快照正在整理</div>';
      }
      const updatedAt = data.market_timestamp || data.fetched_at;
      $("sectorSource").textContent = updatedAt
        ? `市场快照 ${readableTime(updatedAt)} · ${data.coverage?.returned || sectors.length} 个板块进入本次排序`
        : "正在建立板块市场快照";
    }

    function renderWatchlistPulse() {
      const container = $("watchlistPulse");
      if (!container) return;
      container.innerHTML = "";
      const rank = {risk_review: 4, priority_research: 3, pending_review: 2, observe: 1};
      const items = [...state.watchlist].sort((a, b) => {
        const actionA = researchActionFor(a.symbol);
        const actionB = researchActionFor(b.symbol);
        const statusGap = (rank[actionB?.research_status] || 0) - (rank[actionA?.research_status] || 0);
        return statusGap || Math.abs(Number(watchlistQuote(b).change || 0)) - Math.abs(Number(watchlistQuote(a).change || 0));
      }).slice(0, 4);
      for (const item of items) {
        const actionItem = researchActionFor(item.symbol);
        const meta = researchStatusMeta(actionItem?.research_status);
        const nextAction = primaryResearchAction(actionItem);
        const quote = watchlistQuote(item);
        const row = document.createElement("button"); row.type = "button"; row.className = "watchlist-pulse-row";
        const name = document.createElement("span"); name.className = "watchlist-pulse-name"; name.textContent = item.name || item.symbol;
        const symbol = document.createElement("span"); symbol.className = "watchlist-pulse-symbol"; symbol.textContent = item.symbol; name.appendChild(symbol);
        const change = document.createElement("span"); change.className = `watchlist-pulse-change ${tone(quote.change)}`; change.textContent = item.status === "available" ? `${pct(quote.change)} · ${quote.label}` : "更新中";
        const action = document.createElement("span"); action.className = "watchlist-pulse-action";
        const badge = document.createElement("span"); badge.className = `research-status-badge ${actionItem?.research_status || "observe"}`; badge.textContent = meta.label;
        const copy = document.createElement("span"); copy.textContent = nextAction?.next_step || actionItem?.headline || item.thesis || "继续观察行情与新证据";
        action.append(badge, copy); row.append(name, change, action);
        row.addEventListener("click", () => { void openDeepStockSymbol(item.symbol); });
        container.appendChild(row);
      }
      if (!items.length) container.innerHTML = '<div class="empty">添加关注后，这里会显示行情变化与研究动作。</div>';
      const priorityCount = state.researchActions.filter(item => ["risk_review", "priority_research"].includes(item.research_status)).length;
      $("watchlistPulseSource").textContent = items.length
        ? `${state.watchlist.length} 只关注股票 · ${priorityCount} 只需要优先复核`
        : "只显示当前用户空间中的关注与研究状态。";
    }

    function renderWatchlistOverview(reportMap) {
      const stats = $("watchlistOverviewStats"); stats.innerHTML = "";
      const priorityCount = state.researchActions.filter(item => ["risk_review", "priority_research"].includes(item.research_status)).length;
      const pendingCount = state.researchActions.reduce((sum, item) => sum + (item.actions || []).filter(action => action.status === "pending_data").length, 0);
      const reportCount = state.watchlist.filter(item => reportMap.has(item.symbol)).length;
      for (const [label, value] of [["关注股票", state.watchlist.length], ["优先复核", priorityCount], ["待补证项", pendingCount], ["已有报告", reportCount]]) {
        const card = document.createElement("div"); card.className = "watchlist-overview-stat";
        const labelNode = document.createElement("span"); labelNode.textContent = label;
        const valueNode = document.createElement("strong"); valueNode.textContent = value;
        card.append(labelNode, valueNode); stats.appendChild(card);
      }
      const distribution = $("watchlistStatusDistribution"); distribution.innerHTML = "";
      const statuses = ["risk_review", "priority_research", "pending_review", "observe"];
      const counts = statuses.map(status => state.researchActions.filter(item => item.research_status === status).length);
      const total = Math.max(1, counts.reduce((sum, value) => sum + value, 0));
      let cursor = 0;
      const stops = statuses.map((status, index) => {
        const start = cursor; cursor += counts[index] / total * 100;
        return `${researchStatusMeta(status).color} ${start}% ${cursor}%`;
      });
      if (!counts.some(Boolean)) stops.splice(0, stops.length, "#dfe5ed 0 100%");
      const ring = document.createElement("div"); ring.className = "watchlist-status-ring"; ring.style.background = `conic-gradient(${stops.join(",")})`;
      const ringValue = document.createElement("strong"); ringValue.textContent = state.watchlist.length; ring.appendChild(ringValue);
      const legend = document.createElement("div"); legend.className = "watchlist-status-legend";
      statuses.forEach((status, index) => {
        const meta = researchStatusMeta(status);
        const item = document.createElement("div"); item.className = "watchlist-status-item";
        const dot = document.createElement("i"); dot.style.background = meta.color;
        const label = document.createElement("span"); label.textContent = meta.label;
        const value = document.createElement("strong"); value.textContent = counts[index];
        item.append(dot, label, value); legend.appendChild(item);
      });
      distribution.append(ring, legend);
    }

    function renderWatchlistTasks() {
      const container = $("watchlistTasks"); container.innerHTML = "";
      const researchRank = {risk_review: 4, priority_research: 3, pending_review: 2, observe: 1};
      const tasks = state.researchActions.map(item => ({...item, primary_action: primaryResearchAction(item)}))
        .filter(item => item.primary_action)
        .sort((a, b) => (researchRank[b.research_status] || 0) - (researchRank[a.research_status] || 0) || Number(b.priority_score || 0) - Number(a.priority_score || 0))
        .slice(0, 6);
      for (const task of tasks) {
        const item = document.createElement("button"); item.type = "button"; item.className = "watchlist-task-item";
        const top = document.createElement("div"); top.className = "watchlist-task-top";
        const symbol = document.createElement("span"); symbol.className = "watchlist-task-symbol"; symbol.textContent = `${task.name || task.symbol} · ${task.symbol}`;
        const statusMeta = researchStatusMeta(task.research_status);
        const status = document.createElement("span"); status.className = `research-status-badge ${task.research_status || "observe"}`; status.textContent = statusMeta.label;
        const title = document.createElement("div"); title.className = "watchlist-task-title"; title.textContent = task.primary_action.next_step || task.primary_action.title;
        const remaining = Math.max(0, (task.actions || []).length - 1);
        const time = document.createElement("div"); time.className = "watchlist-task-time";
        const taskTimezone = /\.(?:SS|SZ)$/i.test(task.symbol || "") ? "Asia/Shanghai" : "America/New_York";
        time.textContent = `${task.data_as_of ? `数据截至 ${marketDateLabel(task.data_as_of, taskTimezone)}` : "等待建立研究基线"}${remaining ? ` · 另有 ${remaining} 项观察动作` : ""}`;
        top.append(symbol, status); item.append(top, title, time);
        item.setAttribute("aria-label", `${task.name || task.symbol}，${task.primary_action.title || task.primary_action.next_step || "查看研究任务"}`);
        item.addEventListener("click", () => openReader(
          task.primary_action.title || task.primary_action.next_step || "研究任务",
          researchActionDetail(task.primary_action),
          `${task.name || task.symbol} · ${statusMeta.label}`
        ));
        container.appendChild(item);
      }
      if (!tasks.length) container.innerHTML = '<div class="empty">建立关注后，研究行动会自动出现在这里。</div>';
    }

    function startEditWatchlist(item) {
      state.editingWatchlistSymbol = item.symbol;
      const form = $("watchlistAddForm"); form.hidden = false; form.classList.add("editing");
      $("watchlistSymbol").value = item.symbol; $("watchlistSymbol").readOnly = true;
      $("watchlistName").value = item.name || "";
      $("watchlistMarket").value = item.market || "A股";
      $("watchlistThesis").value = item.thesis || "";
      const submit = form.querySelector('button[type="submit"]'); if (submit) submit.textContent = "保存修改";
      $("watchlistThesis").focus();
    }

    function resetWatchlistForm() {
      state.editingWatchlistSymbol = null;
      const form = $("watchlistAddForm"); form.reset(); form.hidden = true; form.classList.remove("editing");
      $("watchlistSymbol").readOnly = false;
      const submit = form.querySelector('button[type="submit"]'); if (submit) submit.textContent = "保存";
    }

    function renderWatchlist(data, reports = [], actionsPacket = {}) {
      state.watchlist = data.items || [];
      state.researchReports = reports;
      state.researchActions = actionsPacket.items || [];
      state.researchActionSummary = actionsPacket.summary || {};
      refreshDeepStockSymbolOptions();
      const container = $("watchlist");
      const reportMap = new Map(reports.map(item => [item.symbol, item]));
      const actionMap = new Map(state.researchActions.map(item => [item.symbol, item]));
      const visibleItems = state.watchlist.filter(item => state.watchlistFilter === "all" || actionMap.get(item.symbol)?.research_status === state.watchlistFilter);
      reconcileKeyedList(container, visibleItems.map(item => ({
        item,
        actionItem: actionMap.get(item.symbol),
        report: reportMap.get(item.symbol),
        selected: state.selectedWatchlistSymbol === item.symbol
      })), {
        key: model => model.item.symbol,
        signature: model => JSON.stringify([
          model.item.name, model.item.symbol, model.item.thesis, model.item.status,
          model.item.current_quote, model.item.metrics, model.item.latest_bar,
          model.item.market_timestamp, model.item.latest_change,
          model.actionItem ? [
            model.actionItem.research_status, model.actionItem.headline, model.actionItem.data_as_of,
            (model.actionItem.actions || []).map(action => [action.title, action.next_step, action.status])
          ] : null,
          model.report ? 1 : 0, model.selected
        ]),
        create() {
          const row = document.createElement("div");
          row.tabIndex = 0;
          const identity = document.createElement("div");
          const name = document.createElement("div"); name.className = "watchlist-stock-name";
          const symbol = document.createElement("span"); symbol.className = "watchlist-stock-symbol";
          identity.append(name, symbol);
          const quote = document.createElement("div"); quote.className = "watchlist-quote-cell";
          const latest = document.createElement("strong");
          const change = document.createElement("span");
          quote.append(latest, change);
          const status = document.createElement("span");
          const reason = document.createElement("div"); reason.className = "watchlist-stock-reason";
          const next = document.createElement("div"); next.className = "watchlist-next-action";
          const updated = document.createElement("div"); updated.className = "watchlist-updated";
          const actions = document.createElement("div"); actions.className = "watchlist-stock-actions";
          const reportButton = document.createElement("button"); reportButton.type = "button"; reportButton.className = "icon-button";
          const editButton = document.createElement("button"); editButton.type = "button"; editButton.className = "icon-button"; editButton.textContent = "编辑";
          const deleteButton = document.createElement("button"); deleteButton.type = "button"; deleteButton.className = "icon-button danger"; deleteButton.textContent = "删除";
          actions.append(reportButton, editButton, deleteButton);
          row.append(identity, quote, status, reason, next, updated, actions);
          row._refs = {name, symbol, latest, change, status, reason, next, updated, reportButton, editButton, deleteButton};
          reportButton.addEventListener("click", event => {
            event.stopPropagation();
            const model = row._listItem;
            if (model.report) void openResearchReport(model.item.symbol, reportButton);
            else void openDeepStockSymbol(model.item.symbol);
          });
          editButton.addEventListener("click", event => { event.stopPropagation(); startEditWatchlist(row._listItem.item); });
          deleteButton.addEventListener("click", event => { event.stopPropagation(); void deleteWatchlistItem(row._listItem.item); });
          row.addEventListener("click", () => { void loadWatchlistDetail(row._listItem.item, state.watchlistTimeframe); });
          row.addEventListener("keydown", event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); void loadWatchlistDetail(row._listItem.item, state.watchlistTimeframe); } });
          return row;
        },
        update(row, model) {
          const {item, actionItem, report, selected} = model;
          const refs = row._refs;
          row.className = `watchlist-stock-row${selected ? " active" : ""}`;
          row.dataset.symbol = item.symbol;
          refs.name.textContent = item.name || item.symbol;
          refs.symbol.textContent = item.symbol;
          const quoteData = watchlistQuote(item);
          refs.latest.textContent = numeric(quoteData.price);
          refs.change.className = tone(quoteData.change);
          refs.change.textContent = item.status === "available" ? `${pct(quoteData.change)} · ${quoteData.label}` : "行情更新中";
          const meta = researchStatusMeta(actionItem?.research_status);
          refs.status.className = `research-status-badge ${actionItem?.research_status || "observe"}`;
          refs.status.textContent = meta.label;
          refs.reason.textContent = item.thesis || "尚未记录关注理由";
          const primaryAction = primaryResearchAction(actionItem);
          refs.next.textContent = primaryAction?.next_step || actionItem?.headline || "继续观察行情与新增证据";
          refs.updated.textContent = readableTime(quoteData.marketTimestamp || actionItem?.data_as_of || item.latest_change?.created_at || item.market_timestamp);
          refs.reportButton.textContent = report ? "分析" : "研究";
          refs.reportButton.title = report ? "阅读服务器预生成分析" : "进入股票研究空间";
          refs.editButton.title = `编辑 ${item.name || item.symbol}`;
          refs.deleteButton.title = `删除 ${item.name || item.symbol}`;
        }
      });
      let head = container.querySelector(".watchlist-table-head");
      if (visibleItems.length) {
        if (!head) {
          head = document.createElement("div"); head.className = "watchlist-table-head";
          for (const label of ["股票 / 代码", "最新行情", "研究状态", "关注理由", "下一动作", "最近更新", "操作"]) {
            const cell = document.createElement("span"); cell.textContent = label; head.appendChild(cell);
          }
          container.prepend(head);
        }
      } else {
        head?.remove();
      }
      if (!state.watchlist.length) {
        container.innerHTML = '<div class="empty">还没有关注股票。点击右上角“添加关注”即可开始。</div>';
        $("watchlistDetail").innerHTML = '<div class="empty">添加股票后可查看分时、日线和周线</div>';
        state.selectedWatchlistSymbol = null;
      } else if (!visibleItems.length) {
        container.innerHTML = '<div class="empty">这个研究状态下暂时没有股票。</div>';
      } else {
        const selected = visibleItems.find(item => item.symbol === state.selectedWatchlistSymbol) || visibleItems[0];
        if (state.selectedWatchlistSymbol !== selected.symbol) void loadWatchlistDetail(selected, state.watchlistTimeframe);
      }
      renderWatchlistOverview(reportMap);
      renderWatchlistTasks();
      renderWatchlistPulse();
      renderHomeFocus();
      const coverage = data.coverage || {};
      $("watchlistSource").textContent = `已更新 ${coverage.available || 0}/${coverage.requested || 0} 只关注股票；研究状态来自行情、报告、证据变化与资料缺口，不代表买卖建议。`;
    }

    function aggregateWeekly(points = []) {
      const weeks = new Map();
      for (const point of points) {
        const date = new Date(point.timestamp);
        if (Number.isNaN(date.getTime())) continue;
        const day = date.getUTCDay() || 7;
        date.setUTCDate(date.getUTCDate() - day + 1);
        const key = date.toISOString().slice(0, 10);
        const current = weeks.get(key);
        const close = Number(point.close);
        if (!Number.isFinite(close)) continue;
        if (!current) {
          weeks.set(key, {
            timestamp: key,
            open: Number(point.open ?? close),
            high: Number(point.high ?? close),
            low: Number(point.low ?? close),
            close,
            volume: Number(point.volume || 0)
          });
        } else {
          current.high = Math.max(current.high, Number(point.high ?? close));
          current.low = Math.min(current.low, Number(point.low ?? close));
          current.close = close;
          current.volume += Number(point.volume || 0);
        }
      }
      return [...weeks.values()];
    }

    function periodMetrics(points = [], payload = {}) {
      if (!points.length) return {};
      const first = Number(points[0].open ?? points[0].close);
      const last = Number(points.at(-1).close);
      const highs = points.map(item => Number(item.high ?? item.close)).filter(Number.isFinite);
      const lows = points.map(item => Number(item.low ?? item.close)).filter(Number.isFinite);
      return {
        latest: payload.latest_price ?? payload.metrics?.latest_close ?? last,
        change: payload.pct_change ?? payload.metrics?.return_1d_pct ?? (first ? (last / first - 1) * 100 : null),
        high: highs.length ? Math.max(...highs) : null,
        low: lows.length ? Math.min(...lows) : null,
        volume: points.reduce((sum, item) => sum + Number(item.volume || 0), 0)
      };
    }

    async function loadWatchlistDetail(item, timeframe = "intraday") {
      if (!item) return;
      state.selectedWatchlistSymbol = item.symbol;
      state.watchlistTimeframe = timeframe;
      document.querySelectorAll(".watchlist-stock-row").forEach(row => {
        row.classList.toggle("active", row.dataset.symbol === item.symbol);
      });
      const detail = $("watchlistDetail");
      detail.innerHTML = '<div class="empty">正在整理行情图表…</div>';
      let payload;
      let actualTimeframe = timeframe;
      try {
        if (timeframe === "intraday") payload = await api(`/stocks/${encodeURIComponent(item.symbol)}/intraday`);
        else if (timeframe === "weekly") {
          payload = await api(`/stocks/${encodeURIComponent(item.symbol)}/history?range=2y`);
          payload = {...payload, points: aggregateWeekly(payload.points || [])};
        } else payload = await api(`/stocks/${encodeURIComponent(item.symbol)}/history?range=6mo`);
      } catch {
        payload = await api(`/stocks/${encodeURIComponent(item.symbol)}/history?range=1mo`);
        actualTimeframe = "daily";
        state.watchlistTimeframe = "daily";
      }
      if (state.selectedWatchlistSymbol !== item.symbol) return;
      const points = payload.points || [];
      const metrics = periodMetrics(points, payload);
      detail.innerHTML = "";
      const head = document.createElement("div"); head.className = "stock-detail-head";
      const identity = document.createElement("div");
      const name = document.createElement("div"); name.className = "stock-detail-name"; name.textContent = item.name || payload.display_name || item.symbol;
      const symbol = document.createElement("div"); symbol.className = "stock-detail-symbol"; symbol.textContent = `${item.symbol} · 更新于 ${readableTime(payload.market_timestamp || points.at(-1)?.timestamp)}`;
      identity.append(name, symbol);
      const quote = document.createElement("div");
      const price = document.createElement("div"); price.className = "stock-detail-price"; price.textContent = numeric(metrics.latest);
      const change = document.createElement("div"); change.className = `stock-detail-change ${tone(metrics.change)}`; change.textContent = pct(metrics.change);
      quote.append(price, change); head.append(identity, quote);

      const tabs = document.createElement("div"); tabs.className = "chart-tabs";
      for (const [key, label] of [["intraday", "分时"], ["daily", "日线"], ["weekly", "周线"]]) {
        const button = document.createElement("button"); button.type = "button"; button.className = `chart-tab${actualTimeframe === key ? " active" : ""}`; button.textContent = label;
        button.addEventListener("click", () => { if (state.watchlistTimeframe !== key) void loadWatchlistDetail(item, key); });
        tabs.appendChild(button);
      }
      const canvas = document.createElement("canvas"); canvas.className = "stock-detail-chart"; canvas.setAttribute("aria-label", `${item.name || item.symbol}${actualTimeframe}行情`);
      const cards = document.createElement("div"); cards.className = "stock-detail-metrics";
      const metricItems = [
        ["区间最高", numeric(metrics.high)], ["区间最低", numeric(metrics.low)],
        ["区间成交量", compactNumber(metrics.volume)], ["趋势状态", payload.metrics?.trend_state || payload.metrics?.technical_state || "按图表观察"]
      ];
      for (const [label, value] of metricItems) {
        const card = document.createElement("div"); card.className = "stock-detail-metric";
        const labelNode = document.createElement("span"); labelNode.textContent = label;
        const valueNode = document.createElement("strong"); valueNode.textContent = value;
        card.append(labelNode, valueNode); cards.appendChild(card);
      }
      const actions = document.createElement("div"); actions.className = "stock-detail-actions";
      const deep = document.createElement("button"); deep.type = "button"; deep.className = "btn primary"; deep.textContent = "进入股票研究空间"; deep.addEventListener("click", () => { void openDeepStockSymbol(item.symbol); });
      const ask = document.createElement("button"); ask.type = "button"; ask.className = "btn"; ask.textContent = "向 Agent 提问"; ask.addEventListener("click", () => {
        activateWorkspace("agent"); $("chatInput").value = `分析${item.name || item.symbol}最近的行情、基本面变化和需要复核的风险。`; $("chatInput").focus();
      });
      actions.append(deep, ask);
      detail.append(head, tabs, canvas, cards, actions);
      requestAnimationFrame(() => drawCandles(canvas, points));
    }

    async function deleteWatchlistItem(item) {
      try {
        await api(`/me/watchlist/${encodeURIComponent(item.symbol)}`, {method: "DELETE"});
        if (state.selectedWatchlistSymbol === item.symbol) state.selectedWatchlistSymbol = null;
        await loadWatchlist();
      } catch {
        $("watchlistSource").textContent = "删除没有完成，请稍后重试。";
      }
    }

    function delayText(seconds, freshness) {
      if (seconds === null || seconds === undefined) return "延迟未知";
      if (freshness === "closed_snapshot") return "最近收盘快照";
      if (seconds < 60) return `${seconds} 秒延迟`;
      return `${Math.round(seconds / 60)} 分钟延迟`;
    }

    function drawCandles(canvas, points) {
      if (!points || !points.length) return;
      canvas._candlePoints = points;
      const rect = canvas.getBoundingClientRect();
      const ratio = window.devicePixelRatio || 1;
      const width = Math.max(180, rect.width);
      const height = Math.max(92, Math.round(rect.height || 92));
      canvas.width = width * ratio;
      canvas.height = height * ratio;
      const ctx = canvas.getContext("2d");
      ctx.scale(ratio, ratio);
      ctx.clearRect(0, 0, width, height);
      const sample = points.length > 180 ? points.filter((_, index) => index % Math.ceil(points.length / 180) === 0) : points;
      const values = sample.flatMap(point => [point.high, point.low, point.open, point.close]).filter(value => Number.isFinite(Number(value))).map(Number);
      if (!values.length) return;
      const min = Math.min(...values); const max = Math.max(...values); const span = max - min || 1;
      const top = 7; const bottom = height - 8; const plotHeight = bottom - top;
      ctx.strokeStyle = "rgba(82,105,139,.12)"; ctx.lineWidth = 1;
      for (let grid = 1; grid < 3; grid++) { const y = top + plotHeight * grid / 3; ctx.beginPath(); ctx.moveTo(0,y); ctx.lineTo(width,y); ctx.stroke(); }
      const slot = width / sample.length; const bodyWidth = Math.max(1, Math.min(4, slot * .62));
      const y = value => top + (max - Number(value)) / span * plotHeight;
      sample.forEach((point, index) => {
        const open = Number(point.open ?? point.close); const close = Number(point.close);
        const high = Number(point.high ?? Math.max(open, close)); const low = Number(point.low ?? Math.min(open, close));
        const x = slot * index + slot / 2; const rising = close >= open;
        ctx.strokeStyle = rising ? "#ff7185" : "#55dbb6"; ctx.fillStyle = ctx.strokeStyle;
        ctx.beginPath(); ctx.moveTo(x, y(high)); ctx.lineTo(x, y(low)); ctx.stroke();
        const bodyTop = Math.min(y(open), y(close)); const bodyHeight = Math.max(1, Math.abs(y(open) - y(close)));
        ctx.fillRect(x - bodyWidth / 2, bodyTop, bodyWidth, bodyHeight);
      });
    }

    function inferDiagnosisMarketKey(data, question = "") {
      const evidenceKey = data?.evidence?.market_drivers?.market_key || data?.market_key;
      const normalized = evidenceKey === "gold" ? "london_gold" : evidenceKey;
      if (["china", "japan", "korea", "us", "london_gold"].includes(normalized)) return normalized;
      const folded = String(question || "").toLowerCase();
      if (/(伦敦金|黄金|xau)/.test(folded)) return "london_gold";
      if (/(美股|纳指|纳斯达克|标普|道指|nasdaq|s&p)/.test(folded)) return "us";
      if (/(日股|日经|日本股市)/.test(folded)) return "japan";
      if (/(韩股|韩国股市|kospi)/.test(folded)) return "korea";
      if (/(a股|大盘|上证|深证|创业板|沪深)/i.test(folded)) return "china";
      return null;
    }

    function inferDiagnosisSymbol(data, question = "") {
      const direct = data?.evidence?.symbol || data?.evidence?.item?.symbol || data?.symbol;
      if (direct) return String(direct);
      const tracked = data?.evidence?.events || data?.evidence?.items;
      if (Array.isArray(tracked) && tracked.length === 1 && tracked[0]?.symbol) return String(tracked[0].symbol);
      const sixDigits = String(question).match(/(?<!\d)(\d{6})(?!\d)/);
      if (sixDigits) return sixDigits[1];
      const aliases = [
        [/中兴通讯|中兴/, "000063.SZ"],
        [/中际旭创|中际/, "300308.SZ"],
        [/贵州茅台|茅台/, "600519.SS"],
        [/英伟达|nvidia|nvda/i, "NVDA"]
      ];
      for (const [pattern, symbol] of aliases) if (pattern.test(String(question))) return symbol;
      const ticker = String(question).match(/(?<![A-Z0-9])([A-Z]{1,5})(?![A-Z0-9])/);
      if (!ticker) return null;
      const candidate = ticker[1];
      const marketTerms = new Set(["A", "AI", "ETF", "GDP", "CPI", "RSI", "MACD", "IPO", "PMI", "KOSPI", "XAU"]);
      return marketTerms.has(candidate) ? null : candidate;
    }

    function renderDiagnosisChart({title, meta, price, change, points, metrics = []}) {
      setAgentContextCollapsed(false);
      $("diagnosisContext").hidden = false;
      $("diagnosisTitle").textContent = title || "已识别研究对象";
      $("diagnosisMeta").textContent = meta || "数据时间待确认";
      $("diagnosisPrice").textContent = numeric(price);
      $("diagnosisChange").className = `diagnosis-change ${tone(Number(change || 0))}`;
      $("diagnosisChange").textContent = pct(change);
      const metricsNode = $("diagnosisMetrics");
      metricsNode.innerHTML = "";
      for (const item of metrics) {
        const card = document.createElement("div"); card.className = "diagnosis-metric";
        const label = document.createElement("div"); label.className = "diagnosis-metric-label"; label.textContent = item.label;
        const value = document.createElement("div"); value.className = "diagnosis-metric-value"; value.textContent = item.value ?? "—";
        card.append(label, value); metricsNode.appendChild(card);
      }
      renderAgentResearchContext();
      requestAnimationFrame(() => drawCandles($("diagnosisKline"), points || []));
    }

    async function loadMarketDiagnosis(marketKey) {
      if (!marketKey) return;
      if (!state.liveMarkets.length) {
        const data = await api("/markets/live");
        state.liveMarkets = data.markets || [];
      }
      const market = state.liveMarkets.find(item => item.key === marketKey);
      if (!market || !(market.points || []).length) return;
      renderDiagnosisChart({
        title: `${market.name} · ${market.instrument}`,
        meta: `${market.session_label || "市场状态待确认"} · ${market.interval || "分钟"} K · 数据至 ${readableTime(market.market_timestamp)}`,
        price: market.latest_price,
        change: market.pct_change,
        points: market.points,
        metrics: [
          {label: "交易状态", value: market.session_label},
          {label: "行情周期", value: market.interval || "—"},
          {label: "数据时点", value: readableTime(market.market_timestamp)},
          {label: "前收", value: numeric(market.previous_close)},
          {label: "更新时间", value: delayText(market.delay_seconds, market.freshness)}
        ]
      });
    }

    async function loadStockDiagnosis(symbol) {
      if (!symbol) return;
      state.diagnosisSymbol = symbol;
      try {
        const isAShare = /\.(?:SS|SZ)$/i.test(String(symbol));
        const [history, fundamentals] = await Promise.all([
          api(`/stocks/${encodeURIComponent(symbol)}/history?range=3mo`),
          isAShare
            ? api(`/a-share/${encodeURIComponent(symbol)}/fundamentals`).catch(() => null)
            : Promise.resolve(null)
        ]);
        const metrics = history.metrics || {};
        const latest = (history.points || []).at(-1) || {};
        const quote = fundamentals?.valuation || null;
        const historyTimestamp = history.market_timestamp || latest.timestamp;
        const quoteTimestamp = quote?.market_timestamp || null;
        const quoteIsNewer = quoteTimestamp && (
          !historyTimestamp || Date.parse(quoteTimestamp) > Date.parse(historyTimestamp)
        );
        const quoteLabel = quote?.quote_label || "报价快照";
        renderDiagnosisChart({
          title: `${history.display_name || history.symbol || symbol} · ${history.symbol || symbol}`,
          meta: quoteIsNewer
            ? `${quoteLabel}至 ${readableTime(quoteTimestamp)} · 日 K 至 ${marketDateLabel(historyTimestamp, history?.timezone || "Asia/Shanghai")}`
            : `日 K · 数据至 ${marketDateLabel(historyTimestamp, history?.timezone || "Asia/Shanghai")} · 只描述已发生的技术结构`,
          price: quoteIsNewer ? quote.price : (metrics.latest_close ?? latest.close),
          change: quoteIsNewer ? quote.pct_change : metrics.return_1d_pct,
          points: history.points || [],
          metrics: [
            {label: "技术状态", value: metrics.technical_state || metrics.trend_state},
            {label: "RSI14", value: numeric(metrics.rsi_14)},
            {label: "MACD 柱", value: numeric(metrics.macd_histogram)},
            {label: "ATR14", value: metrics.atr_14_pct == null ? "—" : `${numeric(metrics.atr_14_pct)}%`},
            {label: "5/20日量比", value: numeric(metrics.volume_ratio_5_20)}
          ]
        });
      } catch {
        $("diagnosisMeta").textContent = "这只股票的 K 线正在同步，研究回答仍会保留已取得的证据。";
      }
    }

    async function maybeUpdateDiagnosis(data, question = "") {
      const symbol = inferDiagnosisSymbol(data, question);
      if (symbol) {
        await loadStockDiagnosis(symbol);
        return;
      }
      const marketKey = inferDiagnosisMarketKey(data, question);
      if (marketKey) await loadMarketDiagnosis(marketKey);
    }

    async function syncDiagnosisFromConversation(messages) {
      if (!messages.length) return;
      const lastAssistant = [...messages].reverse().find(item => item.role === "assistant");
      const lastUser = [...messages].reverse().find(item => item.role === "user");
      const metadata = lastAssistant?.metadata || {};
      const context = {symbol: metadata.symbol, market_key: metadata.market_key};
      const symbol = inferDiagnosisSymbol(context, lastUser?.content || "");
      if (symbol) {
        await loadStockDiagnosis(symbol);
        return;
      }
      const marketKey = inferDiagnosisMarketKey(context, lastUser?.content || "");
      if (marketKey) await loadMarketDiagnosis(marketKey);
    }

    function marketDateLabel(value, timezoneName = "Asia/Shanghai") {
      if (!value) return "市场日期待确认";
      const matched = String(value).match(/^(\d{4})-(\d{2})-(\d{2})$/);
      if (matched) return `${matched[1]}-${matched[2]}-${matched[3]}`;
      const marketDate = marketSessionDate(value, timezoneName);
      return /^\d{4}-\d{2}-\d{2}$/.test(String(marketDate || ""))
        ? marketDate
        : readableTime(value);
    }

    function drawSparkline(canvas, points, changeValue = 0) {
      if (!canvas || !points?.length) return;
      canvas._sparkPoints = points;
      canvas._sparkChange = changeValue;
      const rect = canvas.getBoundingClientRect();
      const ratio = window.devicePixelRatio || 1;
      const width = Math.max(80, rect.width || 96);
      const height = Math.max(42, rect.height || 62);
      canvas.width = width * ratio; canvas.height = height * ratio;
      const ctx = canvas.getContext("2d"); ctx.scale(ratio, ratio); ctx.clearRect(0, 0, width, height);
      const values = points.map(item => Number(item.close)).filter(Number.isFinite);
      if (values.length < 2) return;
      const min = Math.min(...values); const max = Math.max(...values); const span = max - min || 1;
      const pad = 5; const color = Number(changeValue) >= 0 ? "#e34b52" : "#15966a";
      const coordinates = values.map((value, index) => ({x: pad + index / (values.length - 1) * (width - pad * 2), y: pad + (max - value) / span * (height - pad * 2)}));
      const gradient = ctx.createLinearGradient(0, 0, 0, height);
      gradient.addColorStop(0, Number(changeValue) >= 0 ? "rgba(227,75,82,.17)" : "rgba(21,150,106,.16)");
      gradient.addColorStop(1, "rgba(255,255,255,0)");
      ctx.beginPath(); ctx.moveTo(coordinates[0].x, height - pad);
      for (const point of coordinates) ctx.lineTo(point.x, point.y);
      ctx.lineTo(coordinates.at(-1).x, height - pad); ctx.closePath(); ctx.fillStyle = gradient; ctx.fill();
      ctx.beginPath(); coordinates.forEach((point, index) => index ? ctx.lineTo(point.x, point.y) : ctx.moveTo(point.x, point.y));
      ctx.strokeStyle = color; ctx.lineWidth = 1.7; ctx.lineJoin = "round"; ctx.lineCap = "round"; ctx.stroke();
    }

    function renderAShareIndices(data) {
      const container = $("aShareIndexCards");
      const order = ["000001.SS", "399001.SZ", "399006.SZ", "000300.SS"];
      const indexMap = new Map((data.indices || []).map(item => [item.symbol, item]));
      const items = order.map(symbol => indexMap.get(symbol)).filter(Boolean);
      reconcileKeyedList(container, items, {
        key: item => item.symbol,
        signature: item => {
          const metrics = item.metrics || {};
          return JSON.stringify([
            item.name, metrics.latest_close, metrics.return_1d_pct, metrics.return_5d_pct,
            metrics.rsi_14, metrics.technical_state, metrics.trend_state,
            item.latest_bar?.timestamp || item.market_timestamp, item.recent_bars
          ]);
        },
        create(item) {
          const card = document.createElement("article");
          card.tabIndex = 0;
          card.setAttribute("role", "button");
          const identity = document.createElement("div");
          const name = document.createElement("div"); name.className = "ashare-index-name";
          const symbol = document.createElement("div"); symbol.className = "ashare-index-symbol";
          const value = document.createElement("div"); value.className = "ashare-index-value";
          const change = document.createElement("div");
          identity.append(name, symbol, value, change);
          const canvas = document.createElement("canvas"); canvas.className = "ashare-sparkline";
          const meta = document.createElement("div"); meta.className = "ashare-index-meta";
          const period = document.createElement("span");
          const technical = document.createElement("span"); technical.className = "technical-tag";
          meta.append(period, technical); card.append(identity, canvas, meta);
          card._refs = {name, symbol, value, change, canvas, period, technical};
          const ask = () => prepareAgentQuestion(`分析${card._listItem.name}当前行情：先区分最新数据时点和上一完整交易日，再说明已发生的技术结构、可能驱动、反方证据和不能确认的部分。`);
          card.addEventListener("click", ask);
          card.addEventListener("keydown", event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); ask(); } });
          return card;
        },
        update(card, item) {
          const refs = card._refs;
          const metrics = item.metrics || {};
          card.className = "ashare-index-card interactive";
          card.setAttribute("aria-label", `研究${item.name}`);
          refs.name.textContent = item.name;
          refs.symbol.textContent = `${item.symbol} · ${marketDateLabel(item.latest_bar?.timestamp || item.market_timestamp)}`;
          refs.value.textContent = numeric(metrics.latest_close);
          refs.change.className = `ashare-index-change ${tone(metrics.return_1d_pct)}`;
          refs.change.textContent = pct(metrics.return_1d_pct);
          refs.canvas.setAttribute("aria-label", `${item.name}最近五个交易日走势`);
          refs.period.textContent = `5日 ${pct(metrics.return_5d_pct)} · RSI ${numeric(metrics.rsi_14)}`;
          refs.technical.textContent = metrics.technical_state || metrics.trend_state || "技术结构待确认";
          requestAnimationFrame(() => { if (card.isConnected) drawSparkline(refs.canvas, card._listItem.recent_bars || [], (card._listItem.metrics || {}).return_1d_pct); });
        }
      });
      if (!container.firstElementChild) container.innerHTML = '<div class="empty">A 股指数快照正在更新</div>';
    }

    function updateMarketDashboardDate() {
      const breadth = state.marketBreadth;
      if (!breadth?.market_date) return;
      const liveChina = state.liveMarkets.find(item => item.name === "中国A股" || item.instrument === "上证综指");
      const liveDate = liveChina?.market_timestamp ? marketSessionDate(liveChina.market_timestamp, "Asia/Shanghai") : null;
      const isPreviousCompleteSession = Boolean(liveDate && breadth.market_date < liveDate);
      const label = isPreviousCompleteSession ? "上一完整交易日" : "市场日期";
      $("marketDashboardDate").textContent = `${label} ${marketDateLabel(breadth.market_date)} · 沪深京 ${breadth.coverage?.returned || breadth.breadth?.total || 0} 只`;
    }

    function renderMarketBreadth(data) {
      state.marketBreadth = data;
      renderHomeFocus();
      const breadth = data.breadth || {};
      const container = $("marketBreadthOverview"); container.innerHTML = "";
      if (data.status !== "available" || !breadth.total) {
        container.innerHTML = '<div class="empty">全市场广度正在整理</div>'; return;
      }
      const advance = Math.max(0, Number(breadth.advance_ratio || 0) * 100);
      const unchanged = Math.max(0, Number(breadth.unchanged_ratio || 0) * 100);
      const declineStart = Math.min(100, advance + unchanged);
      const ring = document.createElement("div"); ring.className = "breadth-ring";
      ring.style.background = `conic-gradient(var(--red) 0 ${advance}%, #cfd6df ${advance}% ${declineStart}%, var(--green) ${declineStart}% 100%)`;
      const center = document.createElement("div"); center.className = "breadth-ring-center";
      const total = document.createElement("strong"); total.textContent = numeric(breadth.total);
      const totalLabel = document.createElement("span"); totalLabel.textContent = "覆盖股票"; center.append(total, totalLabel); ring.appendChild(center);
      const list = document.createElement("div"); list.className = "breadth-stat-list";
      for (const [label, value, dotClass, ratio] of [["上涨", breadth.advancers, "up-dot", breadth.advance_ratio], ["平盘", breadth.unchanged, "", breadth.unchanged_ratio], ["下跌", breadth.decliners, "down-dot", breadth.decline_ratio]]) {
        const item = document.createElement("div"); item.className = "breadth-stat";
        const dot = document.createElement("i"); dot.className = `breadth-stat-dot ${dotClass}`;
        const labelNode = document.createElement("span"); labelNode.textContent = `${label} ${(Number(ratio || 0) * 100).toFixed(2)}%`;
        const valueNode = document.createElement("strong"); valueNode.textContent = numeric(value);
        item.append(dot, labelNode, valueNode); list.appendChild(item);
      }
      container.append(ring, list);
      $("breadthState").textContent = breadth.state || "市场广度已更新";
      updateMarketDashboardDate();
    }

    function renderMarketDistribution(data) {
      const distribution = data.distribution || {};
      const container = $("marketDistribution"); container.innerHTML = "";
      const bins = distribution.bins || {};
      const items = [
        ["≥ 3%", bins.strong_advancers_ge_3, "advance"],
        ["0 ～ 3%", bins.mild_advancers_gt_0_lt_3, "advance"],
        ["平盘", bins.unchanged, "flat"],
        ["-3% ～ 0", bins.mild_decliners_lt_0_gt_neg3, "decline"],
        ["≤ -3%", bins.strong_decliners_le_neg3, "decline"]
      ];
      if (distribution.status !== "available" || !items.some(item => Number(item[1]) > 0)) {
        container.innerHTML = '<div class="empty">涨跌分布正在整理</div>'; return;
      }
      const summary = document.createElement("div"); summary.className = "distribution-summary";
      const p25 = document.createElement("span"); p25.textContent = `25%分位 `; const p25Value = document.createElement("strong"); p25Value.className = tone(distribution.p25_pct_change); p25Value.textContent = pct(distribution.p25_pct_change); p25.appendChild(p25Value);
      const p75 = document.createElement("span"); p75.textContent = `75%分位 `; const p75Value = document.createElement("strong"); p75Value.className = tone(distribution.p75_pct_change); p75Value.textContent = pct(distribution.p75_pct_change); p75.appendChild(p75Value);
      summary.append(p25, p75);
      const bars = document.createElement("div"); bars.className = "distribution-bars";
      const max = Math.max(...items.map(item => Number(item[1] || 0)), 1);
      for (const [label, value, kind] of items) {
        const column = document.createElement("div"); column.className = "distribution-column";
        const count = document.createElement("span"); count.className = "distribution-value"; count.textContent = numeric(value || 0);
        const bar = document.createElement("div"); bar.className = `distribution-bar ${kind}`; bar.style.height = `${Math.max(4, Number(value || 0) / max * 92)}px`;
        const labelNode = document.createElement("span"); labelNode.className = "distribution-label"; labelNode.textContent = label;
        column.append(count, bar, labelNode); bars.appendChild(column);
      }
      container.append(summary, bars);
      $("distributionMedian").textContent = `中位数 ${pct(distribution.median_pct_change)}`;
    }

    function renderTurnover(data) {
      const turnover = data.turnover || {};
      const container = $("marketTurnover"); container.innerHTML = "";
      if (turnover.status !== "available") {
        container.innerHTML = '<div class="empty">成交额正在汇总</div>'; return;
      }
      const total = Number(turnover.total_amount_100m_cny || 0);
      const exchanges = turnover.exchanges || {};
      const values = [["沪市", exchanges.shanghai?.amount_100m_cny || 0], ["深市", exchanges.shenzhen?.amount_100m_cny || 0], ["北交所", exchanges.beijing?.amount_100m_cny || 0]];
      const totalRow = document.createElement("div"); totalRow.className = "turnover-total";
      const totalValue = document.createElement("strong"); totalValue.textContent = numeric(total);
      const unit = document.createElement("span"); unit.textContent = "亿元 · 当日累计"; totalRow.append(totalValue, unit);
      const track = document.createElement("div"); track.className = "turnover-track";
      values.forEach(([, value]) => { const segment = document.createElement("span"); segment.style.width = `${total ? Number(value) / total * 100 : 0}%`; track.appendChild(segment); });
      const exchangeGrid = document.createElement("div"); exchangeGrid.className = "turnover-exchanges";
      values.forEach(([label, value]) => {
        const item = document.createElement("div"); item.className = "turnover-exchange";
        const labelNode = document.createElement("span"); labelNode.textContent = label;
        const valueNode = document.createElement("strong"); valueNode.textContent = `${numeric(value)} 亿`;
        item.append(labelNode, valueNode); exchangeGrid.appendChild(item);
      });
      const history = turnover.history_comparison || {};
      const foot = document.createElement("div"); foot.className = "turnover-foot";
      foot.textContent = history.status === "available" && history.change_vs_previous_pct !== null
        ? `较上一交易日 ${pct(history.change_vs_previous_pct)}；同口径历史由本系统逐日积累。`
        : "同口径历史正在逐日积累，当前不判断放量或缩量。";
      container.append(totalRow, track, exchangeGrid, foot);
      $("turnoverStatus").textContent = `覆盖 ${turnover.coverage?.valid_amount || data.coverage?.returned || 0} 只`;
    }

    async function loadMarketDashboard() {
      const [indicesResult, breadthResult] = await Promise.allSettled([
        api("/indices?scope=all&group=china"),
        api("/markets/breadth")
      ]);
      if (indicesResult.status === "fulfilled") renderAShareIndices(indicesResult.value);
      else $("aShareIndexCards").innerHTML = '<div class="empty">A 股指数快照正在更新</div>';
      if (breadthResult.status === "fulfilled") {
        renderMarketBreadth(breadthResult.value);
        renderMarketDistribution(breadthResult.value);
        renderTurnover(breadthResult.value);
      } else {
        $("marketBreadthOverview").innerHTML = '<div class="empty">全市场广度正在更新</div>';
        $("marketDistribution").innerHTML = '<div class="empty">涨跌分布正在更新</div>';
        $("marketTurnover").innerHTML = '<div class="empty">成交额正在更新</div>';
        $("marketDashboardDate").textContent = "正在对齐最新市场日期";
      }
      lastDashboardLoadedAt = Date.now();
    }

    function renderLiveMarkets(data) {
      state.liveMarkets = data.markets || [];
      const container = $("liveMarkets");
      reconcileKeyedList(container, state.liveMarkets, {
        key: market => market.instrument || market.name,
        signature: market => JSON.stringify([
          market.name, market.instrument, market.is_open, market.session_label,
          market.latest_price, market.pct_change, market.interval,
          market.market_timestamp, market.delay_seconds, market.freshness, market.points
        ]),
        create(market) {
          const card = document.createElement("div");
          card.tabIndex = 0;
          card.setAttribute("role", "button");
          const top = document.createElement("div"); top.className = "live-card-top";
          const identity = document.createElement("div");
          const name = document.createElement("div"); name.className = "live-market-name";
          const instrument = document.createElement("div"); instrument.className = "live-instrument";
          identity.append(name, instrument);
          const badge = document.createElement("span");
          top.append(identity, badge);
          const priceRow = document.createElement("div"); priceRow.className = "live-price-row";
          const price = document.createElement("span"); price.className = "live-price";
          const change = document.createElement("span");
          priceRow.append(price, change);
          const canvas = document.createElement("canvas"); canvas.className = "kline";
          const meta = document.createElement("div"); meta.className = "live-meta";
          card.append(top, priceRow, canvas, meta);
          card._refs = {name, instrument, badge, price, change, canvas, meta};
          const ask = () => {
            const current = card._listItem;
            prepareAgentQuestion(`分析${current.name}的${current.instrument}当前行情：先说明报价和数据时间，再分析已发生的结构、可能驱动、反方证据和不能确认的部分。`);
          };
          card.addEventListener("click", ask);
          card.addEventListener("keydown", event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); ask(); } });
          return card;
        },
        update(card, market) {
          const refs = card._refs;
          card.className = `live-card interactive${market.is_open ? " open" : ""}`;
          card.setAttribute("aria-label", `研究${market.name}${market.instrument}`);
          refs.name.textContent = market.name;
          refs.instrument.textContent = market.instrument;
          refs.badge.className = `session-badge${market.is_open ? " open" : ""}`;
          refs.badge.textContent = market.session_label;
          refs.price.textContent = numeric(market.latest_price);
          refs.change.className = `live-change ${tone(market.pct_change)}`;
          refs.change.textContent = pct(market.pct_change);
          refs.canvas.setAttribute("aria-label", `${market.instrument}当日K线`);
          const marketTime = market.market_timestamp ? new Date(market.market_timestamp).toLocaleTimeString("zh-CN", {hour:"2-digit", minute:"2-digit"}) : "未知";
          refs.meta.textContent = `${market.interval || "—"} · 最新 ${marketTime} · ${delayText(market.delay_seconds, market.freshness)}`;
          requestAnimationFrame(() => { if (card.isConnected) drawCandles(refs.canvas, card._listItem.points); });
        }
      });
      if (!container.firstElementChild) container.innerHTML = '<div class="empty">盘中数据正在同步</div>';
      const coverage = data.coverage || {};
      $("liveSource").textContent = `覆盖 ${coverage.available || 0}/${coverage.requested || 0}，当前交易中 ${coverage.open || 0} 个。${data.session_method || ""}`;
      liveRefreshRemaining = data.refresh_after_seconds || 30;
      updateMarketDashboardDate();
      renderHomeFocus();
    }

    let liveRefreshRemaining = 30;
    let lastLiveLoadedAt = 0;
    let lastDashboardLoadedAt = 0;
    let lastArticlesLoadedAt = 0;

    function insightsVisible() {
      return state.workspacePage === "insights" && document.visibilityState === "visible";
    }

    // 回到今日观察页时补齐离开期间跳过的刷新（间隔与各自轮询一致）。
    function refreshInsightsIfStale() {
      const now = Date.now();
      if (now - lastLiveLoadedAt > 30000) void loadLiveMarkets();
      if (now - lastDashboardLoadedAt > 60000) {
        void loadMarketDashboard();
        void loadSectors();
      }
      if (state.user && now - lastArticlesLoadedAt > 60000) void loadArticles();
    }

    async function loadLiveMarkets() {
      $("refreshLive").disabled = true;
      try {
        renderLiveMarkets(await api("/markets/live"));
        lastLiveLoadedAt = Date.now();
      }
      catch (error) { $("liveSource").textContent = "行情正在重新连接，页面将自动重试"; }
      finally { $("refreshLive").disabled = false; }
    }

    async function loadSectors() {
      try { renderSectors(await api("/sectors/hot?limit=10")); }
      catch (error) { $("sectorSource").textContent = "正在整理最新板块市场快照"; }
    }

    async function loadWatchlist() {
      if (!state.user) return;
      try {
        const watchlist = await api("/me/watchlist/brief");
        const [reportsResult, actionsResult] = await Promise.allSettled([
          api("/research-reports?limit=20"),
          apiGetShared("/me/research-actions")
        ]);
        const reports = reportsResult.status === "fulfilled" ? reportsResult.value.items || [] : [];
        const actions = actionsResult.status === "fulfilled" ? actionsResult.value : {items: [], summary: {}};
        renderWatchlist(watchlist, reports, actions);
      } catch (error) { $("watchlistSource").textContent = "自选股正在更新"; }
    }

    loadLiveMarkets = dedupLoader(loadLiveMarkets);
    loadSectors = dedupLoader(loadSectors);
    loadMarketDashboard = dedupLoader(loadMarketDashboard);
    loadArticles = dedupLoader(loadArticles);
    loadWatchlist = dedupLoader(loadWatchlist);

    function refreshDeepStockSymbolOptions() {
      const select = $("deepStockSymbol");
      if (!select) return;
      const selected = select.value;
      const known = new Map([
        ["000063.SZ", "中兴通讯"],
        ["300308.SZ", "中际旭创"],
        ["NVDA", "英伟达"]
      ]);
      for (const item of state.watchlist || []) known.set(item.symbol, item.name || item.symbol);
      for (const item of state.deepStockSessions || []) known.set(item.symbol, item.name || item.symbol);
      select.innerHTML = "";
      for (const [symbol, name] of known) {
        const option = document.createElement("option");
        option.value = symbol;
        option.textContent = `${name} · ${symbol}`;
        select.appendChild(option);
      }
      if ([...known.keys()].includes(selected)) select.value = selected;
    }

    async function optionalApi(path) {
      try { return await api(path); }
      catch { return null; }
    }

    function structuredItemText(item) {
      if (typeof item === "string") return item;
      if (!item || typeof item !== "object") return "";
      const title = item.title || item.label || item.name || item.account_label || item.event_type_label;
      const detail = item.summary || item.detail || item.statement || item.effect || item.explanation || item.current_value_text;
      if (title && detail && !String(detail).startsWith(String(title))) return `${title}：${detail}`;
      return String(detail || title || "");
    }

    function appendDeepInfoCard(container, {title, meta = "", copy = "", items = []}) {
      const meaningfulItems = items.map(structuredItemText).filter(Boolean);
      if (!copy && !meaningfulItems.length) return;
      const card = document.createElement("section"); card.className = "deep-info-card";
      const head = document.createElement("div"); head.className = "deep-info-head";
      const titleNode = document.createElement("div"); titleNode.className = "deep-info-title"; titleNode.textContent = title;
      const detail = document.createElement("button"); detail.type = "button"; detail.className = "deep-info-detail"; detail.textContent = "详细资料";
      detail.addEventListener("click", () => {
        const sections = [];
        if (copy) sections.push(copy);
        if (meaningfulItems.length) sections.push(meaningfulItems.map((text, index) => `${index + 1}. ${text}`).join("\n\n"));
        openReader(title, sections.join("\n\n"), meta || "结构化研究资料");
      });
      head.append(titleNode, detail); card.appendChild(head);
      if (meta) { const metaNode = document.createElement("div"); metaNode.className = "deep-info-meta"; metaNode.textContent = meta; card.appendChild(metaNode); }
      if (copy) { const copyNode = document.createElement("div"); copyNode.className = "deep-info-copy"; copyNode.textContent = copy; card.appendChild(copyNode); }
      if (meaningfulItems.length) {
        const list = document.createElement("ul"); list.className = "deep-info-list";
        for (const text of meaningfulItems.slice(0, 4)) { const item = document.createElement("li"); item.textContent = text; list.appendChild(item); }
        card.appendChild(list);
      }
      container.appendChild(card);
    }

    function appendDeepBoardCard(container, {kind, title, items = []}) {
      const normalized = items.map(structuredItemText).filter(Boolean);
      const previewItems = normalized.slice(0, 3);
      const card = document.createElement("section"); card.className = `deep-board-card ${kind}`;
      const head = document.createElement("div"); head.className = "deep-board-head";
      const titleNode = document.createElement("div"); titleNode.className = "deep-board-title"; titleNode.textContent = title;
      const count = document.createElement("span"); count.className = "deep-board-count"; count.textContent = `${normalized.length} 项`;
      const headActions = document.createElement("div"); headActions.className = "deep-board-head-actions";
      headActions.appendChild(count);
      if (normalized.length) {
        const detail = document.createElement("button"); detail.type = "button"; detail.className = "deep-board-detail"; detail.textContent = "查看全部";
        detail.addEventListener("click", () => openReader(
          title,
          normalized.map((text, index) => `${index + 1}. ${text}`).join("\n\n"),
          `结构化证据 ${normalized.length} 项 · 点击外部或关闭按钮返回`
        ));
        headActions.appendChild(detail);
      }
      head.append(titleNode, headActions); card.appendChild(head);
      const list = document.createElement("ul"); list.className = "deep-board-list";
      for (const text of previewItems.length ? previewItems : ["当前没有可确定展示的结构化证据。"] ) {
        const item = document.createElement("li"); item.textContent = text; list.appendChild(item);
      }
      card.appendChild(list); container.appendChild(card);
    }

    function researchClaimText(item) {
      if (!item) return "";
      const coverageLabels = {sufficient: "来源与时间较完整", partial: "部分覆盖", insufficient: "弱证据线索", unavailable: "暂不可用"};
      const evidence = item.evidence_summary ? `；依据：${item.evidence_summary}` : "";
      const source = item.source_name ? `；来源：${item.source_name}` : "";
      const dataTimeLabel = /^\d{4}-\d{2}-\d{2}$/.test(String(item.data_time || "")) ? item.data_time : readableTime(item.data_time);
      const dataTime = item.data_time ? `；数据时间：${dataTimeLabel}` : "";
      const coverage = item.coverage_status ? `；${coverageLabels[item.coverage_status] || "待核验"}` : "";
      const limitation = item.limitations?.[0] ? `；边界：${item.limitations[0]}` : "";
      return `${item.claim || "未命名研究主张"}${evidence}${source}${dataTime}${coverage}${limitation}`;
    }

    function invalidationConditionText(item) {
      if (!item) return "";
      return `${item.label ? `${item.label}：` : ""}${item.condition || "条件待明确"}${item.meaning ? `；含义：${item.meaning}` : ""}`;
    }

    function latestFinancialMetrics(fundamentals) {
      const report = fundamentals?.summary?.latest_report || fundamentals?.financial_periods?.[0] || {};
      return [
        ["营收同比", report.revenue_yoy_pct == null ? "—" : pct(report.revenue_yoy_pct)],
        ["净利润同比", report.net_profit_yoy_pct == null ? "—" : pct(report.net_profit_yoy_pct)],
        ["毛利率", report.gross_margin_pct == null ? "—" : `${numeric(report.gross_margin_pct)}%`],
        ["现金流/净利润", numeric(fundamentals?.summary?.operating_cashflow_to_net_profit)],
        ["资产负债率", report.debt_asset_ratio_pct == null ? "—" : `${numeric(report.debt_asset_ratio_pct)}%`],
        ["ROE", report.roe_weighted_pct == null ? "—" : `${numeric(report.roe_weighted_pct)}%`]
      ];
    }

    function activateStockSpaceTab(tabKey = "overview") {
      const allowed = new Set(["overview", "ai", "evidence", "tasks", "history"]);
      if (!allowed.has(tabKey)) tabKey = "overview";
      state.stockSpaceTab = tabKey;
      document.querySelectorAll("[data-stock-space-tab]").forEach(button => {
        const active = button.dataset.stockSpaceTab === tabKey;
        button.classList.toggle("active", active);
        button.setAttribute("aria-selected", active ? "true" : "false");
      });
      document.querySelectorAll("[data-stock-space-pane]").forEach(pane => {
        pane.hidden = pane.dataset.stockSpacePane !== tabKey;
      });
    }

    function appendStockWorkspaceItem(container, title, meta = "", detail = null) {
      const interactive = Boolean(detail?.body || detail?.url);
      const item = document.createElement(interactive ? "button" : "div"); item.className = `stock-workspace-item${interactive ? " interactive" : ""}`;
      if (interactive) item.type = "button";
      const titleNode = document.createElement("strong"); titleNode.textContent = title;
      item.appendChild(titleNode);
      if (meta) { const metaNode = document.createElement("span"); metaNode.textContent = meta; item.appendChild(metaNode); }
      if (interactive) {
        const affordance = document.createElement("span"); affordance.className = "stock-workspace-item-detail"; affordance.textContent = detail.label || "查看依据与原文";
        item.appendChild(affordance);
        item.setAttribute("aria-label", `${title}，${affordance.textContent}`);
        item.addEventListener("click", () => openReader(title, detail.body || meta, detail.meta || meta, detail.url || ""));
      }
      container.appendChild(item);
    }

    function stockSpaceChangeItems(events, information) {
      const official = (events?.recent_official_events || events?.events || []).map(item => ({
        title: item.title || item.label || "公司披露更新",
        meta: `${item.event_date || item.published_at || "日期待确认"} · ${item.evidence_label || "公司或监管披露"}`,
        url: item.url,
        detail: [
          `证据层级：${item.evidence_label || "公司或监管披露"}`,
          `事件分类：${item.event_label || item.event_type || "待分类"}`,
          `研究相关性：${item.research_relevance_label || "需要结合原判断复核"}`,
          `事件状态：${{confirmed_disclosure: "已确认披露"}[item.event_status] || "已收录，等待阅读原文"}`,
          "处理原则：先阅读官方原文，再判断它是否改变当前关注理由；标题本身不等于影响已经被证实。"
        ].join("\n\n")
      }));
      const announcements = (information?.announcements || []).map(item => ({
        title: item.title || "公司公告更新",
        meta: `${readableTime(item.published_at)} · 公告`,
        url: item.url,
        detail: [
          `来源：${item.source || "公司公告"}`,
          `发布时间：${readableTime(item.published_at)}`,
          item.summary || "公司公告属于优先核验的事实来源。",
          "下一步：阅读原文中的具体金额、时间、对象和适用范围，再与当前判断逐项对照。"
        ].filter(Boolean).join("\n\n")
      }));
      const news = (information?.news || []).map(item => ({
        title: item.title || "市场信息更新",
        meta: `${readableTime(item.published_at)} · 媒体线索，需与正式披露交叉核验`,
        url: item.url,
        detail: [
          `来源：${item.source || "媒体信息"}`,
          `发布时间：${readableTime(item.published_at)}`,
          item.summary || "当前只有媒体标题或摘要，不能直接写成公司已确认的因果。",
          "下一步：寻找公司公告、监管文件或第二个独立信息源交叉确认。"
        ].filter(Boolean).join("\n\n")
      }));
      const seen = new Set();
      return [...official, ...announcements, ...news].filter(item => {
        const key = item.title.trim();
        if (!key || seen.has(key)) return false;
        seen.add(key); return true;
      }).slice(0, 3);
    }

    function workspaceChangeItems(changes) {
      const severityLabels = {attention: "需要优先复核", notice: "发现新变化", stable: "研究基线"};
      return (changes || []).map(change => {
        const details = [
          change.summary,
          ...(change.changes || []).map(item => item.detail || item.title),
          ...(change.new_evidence || []).map(item => `${item.category_label || "新增证据"}：${item.title}`),
          change.boundary
        ].filter(Boolean);
        return {
          title: change.summary || "研究证据发生变化",
          meta: `${readableTime(change.data_as_of || change.created_at)} · ${severityLabels[change.severity] || "等待复核"}`,
          detail: details.join("\n\n")
        };
      }).slice(0, 3);
    }

    function researchActionDetail(action) {
      if (!action) return "当前还没有结构化任务依据。";
      const checks = (action.checks || []).filter(Boolean);
      return [
        `触发条件：${action.condition || "待明确"}`,
        `当前证据：${action.current_evidence || "待补充"}`,
        `下一动作：${action.next_step || "继续核验相关证据"}`,
        checks.length ? `逐项检查：\n${checks.map((item, index) => `${index + 1}. ${item}`).join("\n")}` : ""
      ].filter(Boolean).join("\n\n");
    }

    function renderStockSpaceTasks(symbol, session = null, workspace = null) {
      const container = $("deepStockTasks");
      if (!container) return;
      const actionItem = state.researchActions.find(item => item.symbol === symbol) || null;
      const coverageStatusLabels = {sufficient: "历史证据充分", partial: "部分覆盖", insufficient: "证据不足", unavailable: "尚未取得"};
      const coverageActions = (session?.coverage_tasks || []).map(task => ({
        ...task,
        current_evidence: task.coverage_status === "sufficient" && task.last_observed_status !== "sufficient"
          ? `历史证据仍保留；最近一次刷新为“${coverageStatusLabels[task.last_observed_status] || "待核验"}”。`
          : `当前覆盖：${coverageStatusLabels[task.coverage_status] || "待核验"}。`
      }));
      const actions = (workspace?.pending_actions?.length
        ? [...workspace.pending_actions]
        : [...coverageActions, ...(actionItem?.actions || [])]
      ).sort((a, b) => {
        const rank = {triggered: 3, pending_data: 2, watching: 1};
        return (rank[b.status] || 0) - (rank[a.status] || 0);
      });
      container.innerHTML = "";
      const head = document.createElement("div"); head.className = "stock-space-section-head";
      const copyWrap = document.createElement("div");
      const title = document.createElement("div"); title.className = "stock-space-section-title"; title.textContent = "待处理研究任务";
      const copy = document.createElement("div"); copy.className = "stock-space-section-copy"; copy.textContent = "这里只列下一步需要核验的证据，不把研究任务包装成买卖信号。";
      copyWrap.append(title, copy);
      const ask = document.createElement("button"); ask.type = "button"; ask.className = "btn primary"; ask.textContent = "让 Agent 帮我处理";
      ask.addEventListener("click", () => { void continueDeepStockConversation(actions[0]?.next_step || session?.next_question); });
      head.append(copyWrap, ask); container.appendChild(head);
      const grid = document.createElement("div"); grid.className = "stock-task-grid";
      if (actions.length) {
        for (const action of actions) {
          const card = document.createElement("article"); card.className = "stock-task-card";
          const status = document.createElement("span"); status.className = "stock-task-status";
          status.textContent = {triggered: "需要复核", pending_data: "等待证据", watching: "持续观察"}[action.status] || "研究任务";
          const cardTitle = document.createElement("div"); cardTitle.className = "stock-task-title"; cardTitle.textContent = action.title || "继续核验研究证据";
          const cardCopy = document.createElement("div"); cardCopy.className = "stock-task-copy"; cardCopy.textContent = action.next_step || action.current_evidence || "继续按当前研究条件观察。";
          const evidenceCopy = document.createElement("div"); evidenceCopy.className = "stock-task-evidence"; evidenceCopy.textContent = action.current_evidence || "当前证据待补充。";
          const detail = document.createElement("button"); detail.type = "button"; detail.className = "stock-workspace-item-detail"; detail.textContent = "查看任务依据";
          detail.addEventListener("click", () => openReader(action.title || "研究任务", researchActionDetail(action), `${status.textContent} · ${action.severity || "常规"}`));
          card.append(status, cardTitle, cardCopy, evidenceCopy, detail); grid.appendChild(card);
        }
      } else {
        const card = document.createElement("article"); card.className = "stock-task-card";
        const status = document.createElement("span"); status.className = "stock-task-status"; status.textContent = "下一步";
        const cardTitle = document.createElement("div"); cardTitle.className = "stock-task-title"; cardTitle.textContent = session?.current_stage?.label || "建立下一项观察条件";
        const cardCopy = document.createElement("div"); cardCopy.className = "stock-task-copy"; cardCopy.textContent = session?.next_question || "当前没有需要优先处理的新任务，可以继续核验反方证据和失效条件。";
        card.append(status, cardTitle, cardCopy); grid.appendChild(card);
      }
      container.appendChild(grid);
    }

    function renderStockSpaceHistory(session, workspace = null) {
      const container = $("deepStockHistory");
      if (!container) return;
      container.innerHTML = "";
      const head = document.createElement("div"); head.className = "stock-space-section-head";
      const copyWrap = document.createElement("div");
      const title = document.createElement("div"); title.className = "stock-space-section-title"; title.textContent = "历史与复盘";
      const copy = document.createElement("div"); copy.className = "stock-space-section-copy"; copy.textContent = "报告和对话保留生成时的证据快照，后续新证据不会静默改写旧结论。";
      copyWrap.append(title, copy); head.appendChild(copyWrap); container.appendChild(head);
      const grid = document.createElement("div"); grid.className = "stock-history-grid";
      const conversation = document.createElement("article"); conversation.className = "stock-history-card";
      const conversationTitle = document.createElement("div"); conversationTitle.className = "stock-history-title"; conversationTitle.textContent = session ? "绑定的研究对话" : "尚未建立绑定对话";
      const conversationCopy = document.createElement("div"); conversationCopy.className = "stock-history-copy";
      conversationCopy.textContent = session ? `${session.conversation?.message_count || 0} 条消息，七阶段问题会进入同一历史会话，方便连续追问和复核。` : "建立研究空间后，AI研究会绑定一个可长期保存的历史对话。";
      conversation.append(conversationTitle, conversationCopy);
      if (session) {
        const actions = document.createElement("div"); actions.className = "stock-workspace-actions";
        const open = document.createElement("button"); open.type = "button"; open.className = "btn"; open.textContent = "继续对话"; open.addEventListener("click", () => { void continueDeepStockConversation(); });
        actions.appendChild(open); conversation.appendChild(actions);
      }
      const latestReport = workspace?.latest_report || session?.latest_report || null;
      const report = document.createElement("article"); report.className = "stock-history-card";
      const reportTitle = document.createElement("div"); reportTitle.className = "stock-history-title"; reportTitle.textContent = latestReport?.title || "最新服务器研究报告";
      const reportCopy = document.createElement("div"); reportCopy.className = "stock-history-copy"; reportCopy.textContent = readableResearchPreview(latestReport?.summary) || "最新报告正在后台按确定性数据更新，历史对话仍可继续使用。";
      report.append(reportTitle, reportCopy);
      if (latestReport) {
        const meta = document.createElement("div"); meta.className = "stock-history-meta"; meta.textContent = `数据时间 ${readableTime(latestReport.market_timestamp)} · 生成于 ${readableTime(latestReport.generated_at)}`;
        const actions = document.createElement("div"); actions.className = "stock-workspace-actions";
        const read = document.createElement("button"); read.type = "button"; read.className = "btn primary"; read.textContent = "阅读完整报告";
        read.addEventListener("click", () => openReader(latestReport.title, latestReport.body || latestReport.summary, meta.textContent));
        actions.appendChild(read); report.append(meta, actions);
      }
      grid.append(conversation, report); container.appendChild(grid);
      const coverageHistory = [...(session?.coverage_history || [])].reverse();
      if (coverageHistory.length) {
        const statusLabels = {sufficient: "充分", partial: "部分覆盖", insufficient: "不足", unavailable: "尚未取得"};
        const historyCard = document.createElement("article"); historyCard.className = "stock-history-card stock-coverage-history";
        const historyTitle = document.createElement("div"); historyTitle.className = "stock-history-title"; historyTitle.textContent = "六维证据变化";
        const historyCopy = document.createElement("div"); historyCopy.className = "stock-history-copy"; historyCopy.textContent = `已保存最近 ${coverageHistory.length} 次证据覆盖快照。专项刷新不会静默抹掉此前已取得的充分证据。`;
        const historyList = document.createElement("div"); historyList.className = "stock-coverage-history-list";
        for (const entry of coverageHistory) {
          const item = document.createElement("div"); item.className = "stock-coverage-history-item";
          const time = document.createElement("div"); time.className = "stock-coverage-history-time"; time.textContent = `${readableTime(entry.observed_at)} · ${agentIntentLabel(entry.intent)}`;
          const changes = (entry.changes || []).map(change => {
            const from = change.from ? statusLabels[change.from] || "待核验" : "首次记录";
            const to = statusLabels[change.to] || "待核验";
            return change.from ? `${change.label}：${from} → ${to}` : `${change.label}：${to}`;
          });
          const change = document.createElement("div"); change.className = "stock-coverage-history-change"; change.textContent = changes.length ? changes.join("；") : "本轮刷新未改变已保存的证据覆盖状态。";
          item.append(time, change); historyList.appendChild(item);
        }
        historyCard.append(historyTitle, historyCopy, historyList); grid.appendChild(historyCard);
      }
    }

    async function loadDeepStockOverview(symbol) {
      if (!symbol) return;
      state.deepStockOverviewSymbol = symbol;
      const container = $("deepStockOverview");
      container.innerHTML = '<div class="empty">正在汇总行情、财务、股东、研报与事件…</div>';
      const encoded = encodeURIComponent(symbol);
      const isAShare = /\.(?:SS|SZ)$/i.test(symbol);
      const [workspace, history, fundamentals, earnings, drivers, shareholders, expectations, events, information] = await Promise.all([
        optionalApi(`/v1/stocks/${encoded}/workspace`),
        optionalApi(`/stocks/${encoded}/history?range=1y`),
        optionalApi(isAShare ? `/a-share/${encoded}/fundamentals` : `/us-equity/${encoded}/fundamentals`),
        optionalApi(`/stocks/${encoded}/earnings-quality`),
        optionalApi(`/stocks/${encoded}/financial-drivers`),
        isAShare ? optionalApi(`/a-share/${encoded}/shareholders`) : Promise.resolve(null),
        isAShare ? optionalApi(`/a-share/${encoded}/analyst-expectations`) : Promise.resolve(null),
        optionalApi(`/stocks/${encoded}/event-timeline`),
        isAShare ? optionalApi(`/a-share/${encoded}/information`) : Promise.resolve(null)
      ]);
      if (state.deepStockOverviewSymbol !== symbol) return;

      const valuation = fundamentals?.valuation || {};
      const workspaceQuote = workspace?.overview?.quote || {};
      const historyMetrics = history?.metrics || {};
      const points = history?.points || [];
      const latest = points.at(-1) || {};
      const name = workspace?.name || fundamentals?.name || fundamentals?.summary?.name || history?.display_name || state.watchlist.find(item => item.symbol === symbol)?.name || symbol;
      const price = workspaceQuote.price ?? valuation.price ?? historyMetrics.latest_close ?? latest.close;
      const change = workspaceQuote.pct_change ?? valuation.pct_change ?? historyMetrics.return_1d_pct;
      const currency = workspaceQuote.currency || valuation.currency || history?.currency || "";
      const quoteTimestamp = workspace?.data_meta?.quote_as_of || workspaceQuote.market_timestamp || valuation.market_timestamp;
      const dailyTimestamp = workspace?.data_meta?.daily_as_of || history?.market_timestamp || latest.timestamp;
      const quoteDate = marketSessionDate(quoteTimestamp, history?.timezone || "UTC");
      const dailyDate = marketSessionDate(dailyTimestamp, history?.timezone || "UTC");
      const quoteLabel = workspaceQuote.label || valuation.quote_label || (quoteDate && dailyDate && quoteDate > dailyDate ? "最新报价" : "最近收盘");
      const stateWatchItem = state.watchlist.find(item => item.symbol === symbol) || null;
      const watchItem = workspace?.relation?.in_watchlist
        ? {...(stateWatchItem || {}), symbol, name, thesis: workspace?.thesis?.summary || stateWatchItem?.thesis || null}
        : stateWatchItem;
      const actionItem = state.researchActions.find(item => item.symbol === symbol) || null;
      const localSession = state.deepStockSessions.find(item => item.symbol === symbol) || null;
      const session = workspace?.stage_progress ? {
        ...(localSession || {}),
        status: workspace.stage_progress.status,
        progress: workspace.stage_progress.progress,
        current_stage: workspace.stage_progress.current_stage,
        next_question: workspace.stage_progress.next_question,
        updated_at: workspace.stage_progress.updated_at,
        conversation: workspace.conversation || localSession?.conversation,
        latest_report: workspace.latest_report || localSession?.latest_report,
        evidence_coverage: workspace.evidence_summary || localSession?.evidence_coverage,
        coverage_tasks: (workspace.pending_actions || []).filter(item => item.source === "evidence_coverage")
      } : localSession;
      const evidenceCoverage = workspace?.evidence_summary || session?.evidence_coverage || {};
      const claimLedger = workspace?.claim_ledger || {};
      const researchClaims = claimLedger.claims || [];
      const coverageDimensions = evidenceCoverage.dimensions || [];
      const coverageSummary = evidenceCoverage.summary || {};
      const changeItems = workspace?.important_changes?.length
        ? workspaceChangeItems(workspace.important_changes)
        : stockSpaceChangeItems(events, information);
      const pendingActions = [...(workspace?.pending_actions || actionItem?.actions || [])].sort((a, b) => {
        const rank = {triggered: 3, pending_data: 2, watching: 1};
        return (rank[b.status] || 0) - (rank[a.status] || 0);
      }).slice(0, 3);
      const moduleAvailability = [
        Boolean(points.length), Boolean(fundamentals), earnings?.status === "available",
        drivers?.status === "available", Boolean(shareholders), Boolean(expectations),
        Boolean(events), Boolean(information)
      ];
      const availableModuleCount = moduleAvailability.filter(Boolean).length;

      container.innerHTML = "";
      const shell = document.createElement("div"); shell.className = "deep-overview-shell";
      const quote = document.createElement("section"); quote.className = "deep-quote-card";
      const identity = document.createElement("div"); identity.className = "deep-quote-identity";
      const titleRow = document.createElement("div"); titleRow.className = "deep-quote-title-row";
      const nameNode = document.createElement("div"); nameNode.className = "deep-quote-name"; nameNode.textContent = name;
      const symbolNode = document.createElement("span"); symbolNode.className = "deep-quote-symbol"; symbolNode.textContent = symbol;
      titleRow.append(nameNode, symbolNode);
      const quoteTags = document.createElement("div"); quoteTags.className = "deep-quote-tags";
      for (const text of [isAShare ? "A股" : "美股", expectations?.industry, workspace?.relation?.label || (watchItem ? "已加入关注" : "尚未关注")].filter(Boolean)) {
        const tag = document.createElement("span"); tag.className = "deep-quote-tag"; tag.textContent = text; quoteTags.appendChild(tag);
      }
      const priceNode = document.createElement("div"); priceNode.className = "deep-quote-price"; priceNode.textContent = numeric(price);
      const changeNode = document.createElement("strong"); changeNode.className = `deep-quote-change ${tone(change)}`; changeNode.textContent = `${pct(change)} · ${quoteLabel}${currency ? ` · ${currency}` : ""}`;
      const evidenceBadges = document.createElement("div"); evidenceBadges.className = "deep-evidence-badges";
      const coverageBadge = document.createElement("span"); coverageBadge.className = "deep-evidence-badge"; coverageBadge.textContent = coverageDimensions.length ? `六维证据 ${coverageSummary.sufficient || 0}/6 充分` : `确定性模块 ${availableModuleCount}/8`;
      const qualityBadge = document.createElement("span"); qualityBadge.className = `deep-evidence-badge${(earnings?.contradictions || []).length ? " attention" : ""}`; qualityBadge.textContent = earnings?.overall_label || "财报质量待核验";
      evidenceBadges.append(coverageBadge, qualityBadge);
      identity.append(titleRow, quoteTags, priceNode, changeNode, evidenceBadges); quote.appendChild(identity);
      for (const [label, value] of [
        ["TTM 市盈率", numeric(valuation.pe_ttm)],
        ["市净率", numeric(valuation.pb)],
        ["总市值", compactNumber(valuation.total_market_cap, currency)],
        ["数据时间", readableTime(quoteTimestamp || dailyTimestamp)]
      ]) {
        const stat = document.createElement("div"); stat.className = "deep-quote-stat";
        const labelNode = document.createElement("span"); labelNode.textContent = label;
        const valueNode = document.createElement("strong"); valueNode.textContent = value;
        stat.append(labelNode, valueNode); quote.appendChild(stat);
      }
      shell.appendChild(quote);

      const priorityLabel = pendingActions.some(item => item.status === "triggered") ? "优先复核" : pendingActions.length ? "正常处理" : "常规观察";
      const workflowLabel = session?.current_stage?.label
        || (session?.status === "completed" ? "七阶段已完成，继续复核新证据" : "可启动 AI 深度研究");
      const counterevidenceCount = (claimLedger?.summary?.weakens || 0) + (claimLedger?.summary?.unresolved || 0) || workspace?.counterevidence?.length || (earnings?.contradictions || []).length;
      const attentionLabel = counterevidenceCount ? `${counterevidenceCount} 项反方证据或压力待核验` : "暂无新增高优先级冲突";
      const trackingLabel = workspace?.relation?.in_watchlist
        ? (session?.status === "completed" ? "七阶段研究已完成" : session ? "研究持续沉淀中" : "关注中，尚未启动深研")
        : "尚未加入跟踪";

      const primaryGrid = document.createElement("div"); primaryGrid.className = "stock-primary-grid";
      const chartCard = document.createElement("section"); chartCard.className = "deep-chart-card stock-primary-chart";
      const chartHead = document.createElement("div"); chartHead.className = "stock-chart-head";
      const chartHeadCopy = document.createElement("div"); chartHeadCopy.className = "stock-chart-head-copy";
      const chartTitle = document.createElement("div"); chartTitle.className = "stock-chart-title"; chartTitle.textContent = "股价走势";
      const chartMeta = document.createElement("div"); chartMeta.className = "stock-chart-meta";
      chartMeta.textContent = points.length
        ? `数据至 ${marketDateLabel(history.market_timestamp || latest.timestamp, history?.timezone || "Asia/Shanghai")} · 仅呈现已完成日线`
        : "完整日线正在同步";
      chartHeadCopy.append(chartTitle, chartMeta);
      const chartPeriods = document.createElement("div"); chartPeriods.className = "stock-chart-periods"; chartPeriods.setAttribute("aria-label", "K线区间");
      const canvas = document.createElement("canvas"); canvas.className = "deep-chart-canvas"; canvas.setAttribute("aria-label", `${name}日K线`);
      const periodOptions = [["3月", 66], ["6月", 132], ["1年", null]];
      const periodButtons = [];
      periodOptions.forEach(([label, limit]) => {
        const button = document.createElement("button"); button.type = "button"; button.className = `stock-chart-period${limit === null ? " active" : ""}`; button.textContent = label;
        button.addEventListener("click", () => {
          periodButtons.forEach(item => item.classList.remove("active")); button.classList.add("active");
          chartMeta.textContent = points.length
            ? `数据至 ${marketDateLabel(history.market_timestamp || latest.timestamp, history?.timezone || "Asia/Shanghai")} · ${label}已完成日线`
            : "完整日线正在同步";
          requestAnimationFrame(() => drawCandles(canvas, limit ? points.slice(-limit) : points));
        });
        periodButtons.push(button); chartPeriods.appendChild(button);
      });
      chartHead.append(chartHeadCopy, chartPeriods); chartCard.append(chartHead, canvas);
      if (points.length) requestAnimationFrame(() => drawCandles(canvas, points));
      else {
        const emptyChart = document.createElement("div"); emptyChart.className = "empty"; emptyChart.textContent = "日线数据正在同步"; chartCard.replaceChild(emptyChart, canvas);
      }
      const chartMetrics = document.createElement("div"); chartMetrics.className = "stock-chart-metrics";
      for (const [label, value] of [
        ["趋势结构", historyMetrics.trend_state || "待确认"],
        ["近20日", historyMetrics.return_20d_pct == null ? "—" : pct(historyMetrics.return_20d_pct)],
        ["60日最大回撤", historyMetrics.max_drawdown_60d_pct == null ? "—" : pct(historyMetrics.max_drawdown_60d_pct)],
        ["20日年化波动", historyMetrics.volatility_20d_annualized_pct == null ? "—" : `${numeric(historyMetrics.volatility_20d_annualized_pct)}%`]
      ]) {
        const metric = document.createElement("div"); metric.className = "stock-chart-metric";
        const labelNode = document.createElement("span"); labelNode.textContent = label;
        const valueNode = document.createElement("strong"); valueNode.textContent = value;
        metric.append(labelNode, valueNode); chartMetrics.appendChild(metric);
      }
      chartCard.appendChild(chartMetrics);

      const digest = document.createElement("aside"); digest.className = "stock-research-digest"; digest.setAttribute("aria-label", "当前研究摘要");
      const digestHead = document.createElement("div"); digestHead.className = "stock-digest-head";
      const digestTitle = document.createElement("div"); digestTitle.className = "stock-digest-title"; digestTitle.textContent = "当前研究摘要";
      const digestPriority = document.createElement("span"); digestPriority.className = "stock-digest-priority"; digestPriority.textContent = priorityLabel;
      digestHead.append(digestTitle, digestPriority);
      const digestSummary = document.createElement("div"); digestSummary.className = "stock-digest-summary";
      const digestSummaryLabel = document.createElement("span"); digestSummaryLabel.textContent = "当前最需要复核";
      const digestSummaryCopy = document.createElement("strong");
      digestSummaryCopy.textContent = claimLedger?.strongest_counterevidence?.claim
        || (earnings?.contradictions || [])[0]
        || pendingActions[0]?.current_evidence
        || pendingActions[0]?.next_step
        || drivers?.plausible_clues?.[0]
        || "目前没有新增的高优先级冲突，继续按既有研究主线观察。";
      digestSummary.append(digestSummaryLabel, digestSummaryCopy);
      const dimensions = document.createElement("div"); dimensions.className = "stock-digest-dimensions";
      const latestReport = fundamentals?.summary?.latest_report || fundamentals?.financial_periods?.[0] || {};
      const detailList = items => (items || []).map(structuredItemText).filter(Boolean);
      const detailSection = (label, items) => {
        const values = detailList(items);
        return values.length ? `${label}：\n${values.map((item, index) => `${index + 1}. ${item}`).join("\n")}` : "";
      };
      const appendDimension = (label, status, detail, statusClass = "", reader = null) => {
        const row = document.createElement(reader?.body ? "button" : "div"); row.className = "stock-digest-dimension";
        if (reader?.body) {
          row.type = "button";
          row.setAttribute("aria-label", `${label}：${status || "待确认"}，查看详细资料`);
          row.addEventListener("click", () => openReader(
            reader.title || `${name} · ${label}研究`,
            reader.body,
            reader.meta || `${label}证据 · ${readableTime(quoteTimestamp || dailyTimestamp)}`
          ));
        }
        const labelNode = document.createElement("span"); labelNode.className = "stock-digest-label"; labelNode.textContent = label;
        const statusNode = document.createElement("strong"); statusNode.className = `stock-digest-status${statusClass ? ` ${statusClass}` : ""}`; statusNode.textContent = status || "待确认";
        const detailNode = document.createElement("span"); detailNode.className = "stock-digest-detail"; detailNode.textContent = detail || "等待更多结构化证据";
        row.append(labelNode, statusNode, detailNode); dimensions.appendChild(row);
      };
      appendDimension(
        "价格",
        historyMetrics.trend_state || "待确认",
        `近20日 ${historyMetrics.return_20d_pct == null ? "—" : pct(historyMetrics.return_20d_pct)}；60日最大回撤 ${historyMetrics.max_drawdown_60d_pct == null ? "—" : pct(historyMetrics.max_drawdown_60d_pct)}`,
        Number(historyMetrics.return_20d_pct) < 0 ? "risk" : "positive",
        {
          title: `${name} · 价格结构与波动`,
          meta: `最新报价 ${readableTime(quoteTimestamp)} · 完整日线 ${dailyDate || "待确认"}`,
          body: [
            `当前结构：${historyMetrics.trend_state || "待确认"}`,
            `最新报价：${numeric(price)}${currency ? ` ${currency}` : ""}，涨跌幅 ${pct(change)}，口径为“${quoteLabel}”。`,
            `最近完整日线：${dailyDate || "待确认"}。`,
            `近20日收益：${historyMetrics.return_20d_pct == null ? "—" : pct(historyMetrics.return_20d_pct)}。`,
            `60日最大回撤：${historyMetrics.max_drawdown_60d_pct == null ? "—" : pct(historyMetrics.max_drawdown_60d_pct)}。`,
            `20日年化波动率：${historyMetrics.volatility_20d_annualized_pct == null ? "—" : `${numeric(historyMetrics.volatility_20d_annualized_pct)}%`}。`,
            "研究边界：以上只描述已经发生的价格路径和波动结构，不能单独证明公司基本面变化或未来方向。"
          ].join("\n\n")
        }
      );
      appendDimension(
        "盈利",
        earnings?.overall_label || "待确认",
        earnings?.contradictions?.[0] || earnings?.supports?.[0] || "等待财报质量结论",
        (earnings?.contradictions || []).length ? "risk" : "positive",
        {
          title: `${name} · 盈利质量`,
          meta: `${latestReport.report_date_name || latestReport.report_date || "最新可用报告期"} · 结构化财务证据`,
          body: [
            `当前判断：${earnings?.overall_label || "待确认"}`,
            detailSection("支持证据", earnings?.supports),
            detailSection("矛盾与反证", earnings?.contradictions),
            detailSection("需要复核", earnings?.review_points),
            "研究边界：增长、利润率和现金流必须按同类报告期比较；单一同比数字不能替代对收入结构、费用和现金流的联合核验。"
          ].filter(Boolean).join("\n\n")
        }
      );
      appendDimension(
        "现金流",
        drivers?.overall_label || "待确认",
        drivers?.summary || drivers?.confirmed_mechanical_drivers?.[0] || "等待现金流驱动结论",
        /承压|下降|弱/.test(String(drivers?.overall_label || "")) ? "risk" : "",
        {
          title: `${name} · 利润与现金流拆解`,
          meta: `${latestReport.report_date_name || latestReport.report_date || "最新可用报告期"} · 财报科目与公司原文`,
          body: [
            `当前判断：${drivers?.overall_label || "待确认"}`,
            drivers?.summary ? `摘要：${drivers.summary}` : "",
            detailSection("已确认的报表机械影响", drivers?.confirmed_mechanical_drivers),
            detailSection("需要继续核验的线索", drivers?.plausible_clues),
            detailSection("仍未确认的原因", drivers?.unresolved_causes),
            detailSection("复核事项", drivers?.review_points),
            "研究边界：公司财报原文属于一手披露，但管理层解释仍不等于已经完成独立因果验证。"
          ].filter(Boolean).join("\n\n")
        }
      );
      appendDimension(
        "证据",
        `${availableModuleCount}/8 已就绪`,
        `${changeItems.length} 项重要变化 · ${pendingActions.length} 项待处理`,
        availableModuleCount >= 7 ? "positive" : "",
        {
          title: `${name} · 证据覆盖`,
          meta: `确定性模块 ${availableModuleCount}/8 · 只表示资料覆盖，不是投资评分`,
          body: [
            `已就绪模块：${[
              ["价格日线", Boolean(points.length)],
              ["财务与估值", Boolean(fundamentals)],
              ["盈利质量", earnings?.status === "available"],
              ["利润与现金流", drivers?.status === "available"],
              ["股东结构", Boolean(shareholders)],
              ["券商预期", Boolean(expectations)],
              ["事件时间线", Boolean(events)],
              ["公告与资讯", Boolean(information)]
            ].filter(([, ready]) => ready).map(([module]) => module).join("、") || "暂无"}。`,
            `最新重要变化：${changeItems.length} 项；当前待处理：${pendingActions.length} 项。`,
            "覆盖说明：模块就绪只表示已有可读取资料，不代表证据一致、结论正确或具备买卖意义。",
            "查看方式：进入“数据与证据”标签，可继续展开已确认事实、反方证据、资料缺口和各研究模块。"
          ].join("\n\n")
        }
      );
      const digestStatusRow = document.createElement("div"); digestStatusRow.className = "stock-digest-status-row";
      for (const text of [trackingLabel, workflowLabel, attentionLabel]) {
        const pill = document.createElement("span"); pill.className = "stock-digest-status-pill"; pill.textContent = text; digestStatusRow.appendChild(pill);
      }
      const digestActions = document.createElement("div"); digestActions.className = "stock-digest-actions";
      const viewEvidence = document.createElement("button"); viewEvidence.type = "button"; viewEvidence.className = "btn"; viewEvidence.textContent = "查看证据"; viewEvidence.addEventListener("click", () => activateStockSpaceTab("evidence"));
      const digestAgent = document.createElement("button"); digestAgent.type = "button"; digestAgent.className = "btn primary"; digestAgent.textContent = "与 Agent 研究"; digestAgent.addEventListener("click", () => { void continueDeepStockConversation(pendingActions[0]?.next_step || session?.next_question || `请基于当前证据复核${name}的研究判断。`); });
      digestActions.append(viewEvidence, digestAgent);
      digest.append(digestHead, digestSummary, dimensions, digestStatusRow, digestActions);
      primaryGrid.append(chartCard, digest); shell.appendChild(primaryGrid);

      const workspaceSummary = document.createElement("div"); workspaceSummary.className = "stock-workspace-summary";
      const thesisCard = document.createElement("section"); thesisCard.className = "stock-workspace-card primary";
      const thesisHead = document.createElement("div"); thesisHead.className = "stock-workspace-card-head";
      const thesisTitle = document.createElement("div"); thesisTitle.className = "stock-workspace-card-title"; thesisTitle.textContent = "当前研究判断";
      const thesisMeta = document.createElement("span"); thesisMeta.className = "stock-workspace-card-meta"; thesisMeta.textContent = watchItem?.thesis ? "由你确认" : "待你确认";
      thesisHead.append(thesisTitle, thesisMeta);
      const judgmentLayout = document.createElement("div"); judgmentLayout.className = "stock-judgment-layout";
      const judgmentMain = document.createElement("div"); judgmentMain.className = "stock-judgment-main";
      const judgmentLabel = document.createElement("div"); judgmentLabel.className = "stock-judgment-label"; judgmentLabel.textContent = "研究主线";
      const thesisCopy = document.createElement("div"); thesisCopy.className = "stock-workspace-copy";
      thesisCopy.textContent = watchItem?.thesis || "还没有记录为什么关注这只股票、主要观察什么以及何时重新判断。补充后，Agent 会把它作为最高优先级私人上下文。";
      judgmentMain.append(judgmentLabel, thesisCopy);
      const systemObservation = document.createElement("aside"); systemObservation.className = "stock-system-observation";
      const systemTitle = document.createElement("strong"); systemTitle.textContent = "系统观察（基于当前确定性数据）";
      const observationList = document.createElement("ul"); observationList.className = "stock-system-observation-list";
      const observations = [
        ["价格", [historyMetrics.trend_state ? `结构为“${historyMetrics.trend_state}”` : "结构待确认", historyMetrics.return_20d_pct != null ? `近20日 ${pct(historyMetrics.return_20d_pct)}` : ""].filter(Boolean).join("；")],
        ["盈利", earnings?.overall_label ? `${earnings.overall_label}${earnings?.contradictions?.[0] ? `；${earnings.contradictions[0]}` : ""}` : "财报质量仍待建立结构化结论"],
        ["现金流", drivers?.overall_label || drivers?.summary || "现金流驱动仍待进一步核验"]
      ];
      observations.forEach(([label, value]) => {
        const item = document.createElement("li"); item.className = "stock-system-observation-item";
        const labelNode = document.createElement("span"); labelNode.className = "stock-system-observation-label"; labelNode.textContent = label;
        const valueNode = document.createElement("span"); valueNode.className = "stock-system-observation-value"; valueNode.textContent = String(value || "待确认").replace(/。；/g, "；");
        item.append(labelNode, valueNode); observationList.appendChild(item);
      });
      systemObservation.append(systemTitle, observationList); judgmentLayout.append(judgmentMain, systemObservation);
      const thesisActions = document.createElement("div"); thesisActions.className = "stock-workspace-actions";
      const editThesis = document.createElement("button"); editThesis.type = "button"; editThesis.className = "btn"; editThesis.textContent = watchItem ? "编辑当前判断" : "加入关注并记录判断";
      editThesis.addEventListener("click", () => {
        editThesis.hidden = true;
        thesisCopy.hidden = true;
        const editor = document.createElement("div"); editor.className = "stock-thesis-editor";
        const textarea = document.createElement("textarea");
        textarea.className = "insight-question";
        textarea.setAttribute("aria-label", `${name}当前判断`);
        textarea.placeholder = "写下为什么关注、主要观察什么，以及什么变化会让你重新判断";
        textarea.value = watchItem?.thesis || "";
        const status = document.createElement("div"); status.className = "stock-thesis-status";
        status.textContent = "保存后，这段判断会进入你的个人资料库，并成为后续 Agent 对话的优先上下文。";
        const editorActions = document.createElement("div"); editorActions.className = "stock-thesis-editor-actions";
        const save = document.createElement("button"); save.type = "button"; save.className = "btn primary"; save.textContent = "保存当前判断";
        const cancel = document.createElement("button"); cancel.type = "button"; cancel.className = "btn"; cancel.textContent = "取消";
        const closeEditor = () => { editor.remove(); thesisCopy.hidden = false; editThesis.hidden = false; };
        cancel.addEventListener("click", closeEditor);
        save.addEventListener("click", async () => {
          const thesis = textarea.value.trim();
          if (!thesis) { status.textContent = "请先写下当前判断，或点击取消返回。"; textarea.focus(); return; }
          save.disabled = true; cancel.disabled = true; status.textContent = "正在保存并同步个人上下文…";
          try {
            const saved = await api("/me/watchlist", {
              method: "POST",
              body: JSON.stringify({ symbol, name: name === symbol ? null : name, market: currency === "USD" ? "美股" : "A股", thesis })
            });
            const existing = state.watchlist.find(item => item.symbol === saved.symbol);
            if (existing) Object.assign(existing, saved);
            else state.watchlist.push(saved);
            closeEditor();
            await loadDeepStockOverview(symbol);
            await loadWatchlist();
          } catch (error) {
            save.disabled = false; cancel.disabled = false;
            status.textContent = error?.message || "当前判断暂未保存，请稍后重试。";
          }
        });
        editorActions.append(save, cancel); editor.append(textarea, status, editorActions);
        thesisCard.appendChild(editor);
        textarea.focus();
      });
      thesisActions.className = "stock-workspace-head-actions";
      thesisActions.append(thesisMeta, editThesis);
      thesisHead.replaceChildren(thesisTitle, thesisActions);
      thesisCard.append(thesisHead, judgmentLayout);

      const changesCard = document.createElement("section"); changesCard.className = "stock-workspace-card changes";
      const changesHead = document.createElement("div"); changesHead.className = "stock-workspace-card-head";
      const changesTitle = document.createElement("div"); changesTitle.className = "stock-workspace-card-title"; changesTitle.textContent = "最新重要变化";
      const changesMeta = document.createElement("span"); changesMeta.className = "stock-workspace-card-meta"; changesMeta.textContent = `${changeItems.length} 项`;
      changesHead.append(changesTitle, changesMeta);
      const changesList = document.createElement("div"); changesList.className = "stock-workspace-list";
      if (changeItems.length) changeItems.forEach(item => appendStockWorkspaceItem(changesList, item.title, item.meta, {body: item.detail, meta: item.meta, url: item.url}));
      else appendStockWorkspaceItem(changesList, "当前没有需要优先处理的新变化", "继续按当前判断观察；新增公告和事件会进入这里。 ");
      changesCard.append(changesHead, changesList);

      const tasksCard = document.createElement("section"); tasksCard.className = "stock-workspace-card tasks";
      const tasksHead = document.createElement("div"); tasksHead.className = "stock-workspace-card-head";
      const tasksTitle = document.createElement("div"); tasksTitle.className = "stock-workspace-card-title"; tasksTitle.textContent = "今日待处理";
      const tasksMeta = document.createElement("span"); tasksMeta.className = "stock-workspace-card-meta"; tasksMeta.textContent = pendingActions.length ? `${pendingActions.length} 项` : session ? "1 项" : "未启动";
      tasksHead.append(tasksTitle, tasksMeta);
      const taskList = document.createElement("div"); taskList.className = "stock-workspace-list";
      if (pendingActions.length) pendingActions.forEach(action => appendStockWorkspaceItem(
        taskList,
        action.title || "继续研究",
        action.next_step || action.current_evidence || "继续核验相关证据。",
        {body: researchActionDetail(action), meta: `任务状态：${{triggered: "需要复核", pending_data: "等待证据", watching: "持续观察"}[action.status] || "研究任务"}`, label: "查看任务依据"}
      ));
      else appendStockWorkspaceItem(taskList, session?.current_stage?.label || "开始 AI 深度研究", session?.next_question || "启动后会持续保存研究阶段、未决问题和下一条需要核验的证据。 ");
      const taskActions = document.createElement("div"); taskActions.className = "stock-workspace-actions";
      const openTasks = document.createElement("button"); openTasks.type = "button"; openTasks.className = "btn"; openTasks.textContent = "查看全部任务"; openTasks.addEventListener("click", () => activateStockSpaceTab("tasks"));
      const askAgent = document.createElement("button"); askAgent.type = "button"; askAgent.className = "btn primary"; askAgent.textContent = "与 Agent 研究"; askAgent.addEventListener("click", () => { void continueDeepStockConversation(pendingActions[0]?.next_step || session?.next_question); });
      taskActions.append(openTasks, askAgent); tasksCard.append(tasksHead, taskList, taskActions);
      workspaceSummary.append(thesisCard, changesCard, tasksCard); shell.appendChild(workspaceSummary);

      const evidenceContainer = $("deepStockEvidence"); evidenceContainer.innerHTML = "";
      const evidenceHead = document.createElement("div"); evidenceHead.className = "stock-space-section-head";
      const evidenceCopyWrap = document.createElement("div");
      const evidenceTitle = document.createElement("div"); evidenceTitle.className = "stock-space-section-title"; evidenceTitle.textContent = "数据与证据";
      const evidenceCopy = document.createElement("div"); evidenceCopy.className = "stock-space-section-copy"; evidenceCopy.textContent = "先区分已确认事实、反方证据和仍需补证，再展开财务、股东、研报和事件详情。";
      evidenceCopyWrap.append(evidenceTitle, evidenceCopy); evidenceHead.appendChild(evidenceCopyWrap); evidenceContainer.appendChild(evidenceHead);
      const evidenceShell = document.createElement("div"); evidenceShell.className = "deep-overview-shell";
      if (coverageDimensions.length) {
        const coverageGrid = document.createElement("div"); coverageGrid.className = "evidence-coverage-grid";
        const statusLabels = {sufficient: "证据充分", partial: "部分覆盖", insufficient: "证据不足", unavailable: "尚未取得"};
        coverageDimensions.forEach(dimension => {
          const card = document.createElement("article"); card.className = "evidence-coverage-card";
          const head = document.createElement("div"); head.className = "evidence-coverage-head";
          const label = document.createElement("div"); label.className = "evidence-coverage-label"; label.textContent = dimension.label;
          const status = document.createElement("span"); status.className = `evidence-coverage-status ${dimension.coverage_status}`; status.textContent = statusLabels[dimension.coverage_status] || "待核验";
          head.append(label, status);
          const copy = document.createElement("div"); copy.className = "evidence-coverage-copy";
          copy.textContent = (dimension.sources || []).length
            ? `已取得：${dimension.sources.join("、")}`
            : (dimension.missing_items || ["需要继续补充可核验证据。"]).join("；");
          card.append(head, copy); coverageGrid.appendChild(card);
        });
        const boundary = document.createElement("div"); boundary.className = "evidence-coverage-boundary"; boundary.textContent = evidenceCoverage.boundary || "覆盖状态只表示证据完整程度，不是公司评分或买卖信号。";
        coverageGrid.appendChild(boundary); evidenceShell.appendChild(coverageGrid);
      }
      const researchBoard = document.createElement("div"); researchBoard.className = "deep-research-board";
      const confirmedClaims = researchClaims.filter(item => item.relation === "supports");
      const counterClaims = researchClaims.filter(item => ["weakens", "unresolved"].includes(item.relation));
      const confirmedItems = confirmedClaims.length ? confirmedClaims.map(researchClaimText) : [
        historyMetrics.trend_state ? `价格结构：${historyMetrics.trend_state}；20日收益 ${pct(historyMetrics.return_20d_pct)}。` : "",
        ...(earnings?.supports || []).slice(0, 2),
        ...(drivers?.confirmed_mechanical_drivers || []).slice(0, 2),
        events?.coverage?.official_events ? `已归档 ${events.coverage.official_events} 条公司公告或监管事件。` : ""
      ];
      const counterItems = counterClaims.length ? counterClaims.map(researchClaimText) : [
        ...(workspace?.counterevidence || []).map(item => [item.statement, item.evidence].filter(Boolean).join("：")),
        ...(earnings?.contradictions || []).slice(0, 3),
        ...(drivers?.plausible_clues || []).slice(0, 2)
      ];
      const gapItems = claimLedger?.information_gaps?.length ? claimLedger.information_gaps.map(item => item.description) : [
        ...(workspace?.next_evidence || []).map(item => item.description),
        ...(drivers?.unresolved_causes || []).slice(0, 3),
        ...(earnings?.review_points || []).slice(0, 3)
      ];
      const invalidationItems = (claimLedger?.invalidation_conditions || workspace?.invalidation_conditions || []).map(invalidationConditionText);
      appendDeepBoardCard(researchBoard, {kind: "confirmed", title: "已确认的证据", items: confirmedItems});
      appendDeepBoardCard(researchBoard, {kind: "counter", title: "关键反证与压力", items: counterItems});
      appendDeepBoardCard(researchBoard, {kind: "gaps", title: "仍需补证", items: gapItems});
      appendDeepBoardCard(researchBoard, {kind: "invalidation", title: "判断失效条件", items: invalidationItems});
      evidenceShell.appendChild(researchBoard);

      const moduleShell = document.createElement("section"); moduleShell.className = "deep-module-shell";
      const moduleTabs = document.createElement("div"); moduleTabs.className = "deep-module-tabs"; moduleTabs.setAttribute("role", "tablist"); moduleTabs.setAttribute("aria-label", "个股证据模块");
      const modulePanels = new Map();
      const createPanel = (key, label) => {
        const panel = document.createElement("div"); panel.className = "deep-module-panel"; panel.dataset.modulePanel = key; panel.dataset.moduleLabel = label; panel.hidden = true; modulePanels.set(key, panel); return panel;
      };
      const financialPanel = createPanel("financial", "财务质量");
      const driverPanel = createPanel("drivers", "利润与现金流");
      const ownershipPanel = createPanel("ownership", "股东与研报");
      const eventPanel = createPanel("events", "事件与舆情");

      if (fundamentals) {
        const report = fundamentals.summary?.latest_report || fundamentals.financial_periods?.[0] || {};
        appendDeepInfoCard(financialPanel, {
          title: "财务与估值",
          meta: report.report_date_name || report.report_date || "最新结构化报告期",
          copy: `TTM 市盈率 ${numeric(valuation.pe_ttm)}，市净率 ${numeric(valuation.pb)}，总市值 ${compactNumber(valuation.total_market_cap, currency)}。`,
          items: latestFinancialMetrics(fundamentals).map(([label, value]) => `${label}：${value}`)
        });
      }
      if (earnings && earnings.status === "available") {
        appendDeepInfoCard(financialPanel, {
          title: "财报质量",
          meta: `${earnings.overall_label || "已完成分析"} · 证据置信度 ${earnings.confidence || "待补充"}`,
          copy: earnings.summary,
          items: [...(earnings.supports || []).slice(0, 2), ...(earnings.contradictions || []).slice(0, 3)]
        });
      }
      if (drivers && drivers.status === "available") {
        appendDeepInfoCard(driverPanel, {
          title: "利润与现金流驱动",
          meta: `${drivers.overall_label || "报表科目拆解"} · 证据置信度 ${drivers.confidence || "待补充"}`,
          copy: drivers.summary,
          items: [...(drivers.confirmed_mechanical_drivers || []).slice(0, 4), ...(drivers.company_explanations || []).slice(0, 2)]
        });
        appendDeepInfoCard(driverPanel, {
          title: "仍需核验的经营原因",
          meta: "机械拆解不等于业务因果",
          copy: drivers.boundary,
          items: [...(drivers.unresolved_causes || []).slice(0, 3), ...(drivers.review_points || []).slice(0, 3)]
        });
      }
      if (shareholders) {
        const latestHolder = shareholders.holder_history?.[0] || {};
        appendDeepInfoCard(ownershipPanel, {
          title: "股东结构",
          meta: latestHolder.as_of ? `股东户数截至 ${latestHolder.as_of}` : shareholders.top10_report_date ? `前十大股东截至 ${shareholders.top10_report_date}` : "最新披露",
          copy: latestHolder.holder_count == null ? "已取得前十大股东结构。" : `股东户数 ${compactNumber(latestHolder.holder_count)}，较上期 ${pct(latestHolder.holder_count_change_pct)}。`,
          items: (shareholders.top_holders || []).slice(0, 5).map(item => `${item.rank}. ${item.name} · 持股 ${item.holding_ratio_pct == null ? "—" : `${numeric(item.holding_ratio_pct)}%`}`)
        });
      }
      if (expectations && expectations.status !== "unavailable") {
        appendDeepInfoCard(ownershipPanel, {
          title: "券商一致预期",
          meta: `${expectations.rating_window || "统计窗口"} · ${expectations.rating_organization_count ?? "—"} 家机构`,
          copy: [expectations.rating_statement, expectations.forecast_statement].filter(Boolean).join(" "),
          items: (expectations.latest_reports || []).slice(0, 5).map(item => `${item.published_at || "日期待确认"} · ${item.institution || "研究机构"} · ${item.title}`)
        });
      }
      if (events) {
        const confirmedEvents = (events.recent_official_events || []).length ? events.recent_official_events : (events.events || []);
        appendDeepInfoCard(eventPanel, {
          title: "重要事件",
          meta: `截至 ${events.as_of_date || "最近更新"} · 官方事件 ${events.coverage?.official_events ?? 0} 条`,
          copy: "优先呈现公司公告与监管披露；媒体线索放在新闻模块单独查看。",
          items: confirmedEvents.slice(0, 6).map(item => `${item.event_date || item.published_at || "日期待确认"} · ${item.title || item.label}`)
        });
      }
      if (information) {
        const sentiment = information.sentiment || {};
        appendDeepInfoCard(eventPanel, {
          title: "公告、新闻与市场情绪",
          meta: `社区样本 ${sentiment.sample_size ?? 0} 条 · ${sentiment.band || "中性或混合"}`,
          copy: "公告优先作为事实依据；新闻用于定位事件；社区内容只反映低可信情绪样本。",
          items: [...(information.announcements || []).slice(0, 3), ...(information.news || []).slice(0, 3)].map(item => `${readableTime(item.published_at)} · ${item.title}`)
        });
      }
      if (fundamentals?.regulatory_filings?.length) {
        appendDeepInfoCard(eventPanel, {
          title: "监管披露",
          meta: `${fundamentals.regulatory_filings.length} 条近期文件`,
          copy: "优先使用公司或监管机构正式披露核对经营事实。",
          items: fundamentals.regulatory_filings.slice(0, 6).map(item => `${readableTime(item.published_at)} · ${item.title}`)
        });
      }

      const availablePanels = [...modulePanels.entries()].filter(([, panel]) => panel.children.length);
      availablePanels.forEach(([key, panel], index) => {
        const button = document.createElement("button"); button.type = "button"; button.className = `deep-module-tab${index === 0 ? " active" : ""}`;
        button.textContent = panel.dataset.moduleLabel; button.dataset.moduleTab = key; button.setAttribute("role", "tab"); button.setAttribute("aria-selected", index === 0 ? "true" : "false");
        panel.hidden = index !== 0;
        button.addEventListener("click", () => {
          moduleTabs.querySelectorAll(".deep-module-tab").forEach(item => { const active = item === button; item.classList.toggle("active", active); item.setAttribute("aria-selected", active ? "true" : "false"); });
          availablePanels.forEach(([panelKey, panelNode]) => { panelNode.hidden = panelKey !== key; });
        });
        moduleTabs.appendChild(button);
      });
      if (availablePanels.length) {
        moduleShell.appendChild(moduleTabs);
        availablePanels.forEach(([, panel]) => moduleShell.appendChild(panel));
        evidenceShell.appendChild(moduleShell);
      }
      container.appendChild(shell);
      evidenceContainer.appendChild(evidenceShell);
      renderStockSpaceTasks(symbol, session, workspace);
      renderStockSpaceHistory(session, workspace);
    }

    async function openDeepStockSymbol(symbol) {
      activateWorkspace("deep_stock");
      activateStockSpaceTab("overview");
      refreshDeepStockSymbolOptions();
      const select = $("deepStockSymbol");
      if (![...select.options].some(option => option.value === symbol)) {
        const option = document.createElement("option"); option.value = symbol; option.textContent = symbol; select.appendChild(option);
      }
      select.value = symbol;
      const session = state.deepStockSessions.find(item => item.symbol === symbol) || null;
      renderDeepStock(session);
      await loadDeepStockOverview(symbol);
    }

    function deepStageStateLabel(status) {
      return {completed: "已完成", in_progress: "当前阶段", pending: "待研究"}[status] || "待研究";
    }

    function renderDeepStock(session) {
      state.deepStock = session || null;
      renderStockSpaceHistory(session);
      const container = $("deepStockContent");
      if (!session) {
        $("deepStockAgent").disabled = true;
        $("deepStockAgent").hidden = true;
        $("deepStockAgent").textContent = "先建立研究";
        $("startDeepStock").hidden = false;
        container.className = "";
        container.innerHTML = "";
        const cta = document.createElement("section"); cta.className = "deep-session-cta";
        const copyWrap = document.createElement("div");
        const title = document.createElement("div"); title.className = "deep-session-cta-title"; title.textContent = "开始这只股票的 AI 深度研究";
        const copy = document.createElement("div"); copy.className = "deep-session-cta-copy"; copy.textContent = "Agent 会围绕经营、行业、估值、反方证据和风险逐步研究，并把对话、证据缺口与报告持续保存在当前股票下。";
        const points = document.createElement("div"); points.className = "deep-session-cta-points";
        for (const text of ["七阶段研究进度", "证据缺口持续补齐", "报告与对话长期保存"]) {
          const point = document.createElement("span"); point.className = "deep-session-cta-point"; point.textContent = text; points.appendChild(point);
        }
        copyWrap.append(title, copy, points);
        const action = document.createElement("button"); action.type = "button"; action.className = "btn primary"; action.textContent = "开始 AI 深度研究"; action.addEventListener("click", startDeepStockSession);
        cta.append(copyWrap, action); container.appendChild(cta);
        $("startDeepStock").textContent = "开始 AI 深度研究";
        return;
      }
      $("deepStockSymbol").value = session.symbol;
      $("deepStockAgent").disabled = false;
      $("deepStockAgent").hidden = false;
      $("deepStockAgent").textContent = "继续 AI 研究";
      $("startDeepStock").hidden = true;
      container.className = "deep-stock-body";
      container.innerHTML = "";

      const main = document.createElement("div"); main.className = "deep-stock-main";
      const progress = document.createElement("section"); progress.className = "deep-stock-progress";
      const progressHead = document.createElement("div"); progressHead.className = "deep-stock-progress-head";
      const progressIdentity = document.createElement("div");
      const progressValue = document.createElement("div"); progressValue.className = "deep-stock-progress-value"; progressValue.textContent = `研究流程 ${session.progress?.completed || 0}/${session.progress?.total || 7}`;
      const progressMeta = document.createElement("div"); progressMeta.className = "deep-stock-progress-meta";
      progressMeta.textContent = session.current_stage
        ? `当前：${session.current_stage.label} · 绑定对话已有 ${session.conversation?.message_count || 0} 条消息`
        : "七个阶段已完成，后续继续复核新增证据";
      progressIdentity.append(progressValue, progressMeta);
      const continueButton = document.createElement("button"); continueButton.type = "button"; continueButton.className = "btn primary"; continueButton.textContent = "继续深聊";
      continueButton.addEventListener("click", () => { void continueDeepStockConversation(); });
      progressHead.append(progressIdentity, continueButton);
      const track = document.createElement("div"); track.className = "deep-stock-track";
      const trackFill = document.createElement("span"); trackFill.style.width = `${session.progress?.percent || 0}%`; track.appendChild(trackFill);
      progress.append(progressHead, track);

      const stages = document.createElement("div"); stages.className = "deep-stage-list";
      for (const item of session.stages || []) {
        const card = document.createElement("article"); card.className = `deep-stage ${item.status || "pending"}`;
        const head = document.createElement("div"); head.className = "deep-stage-head";
        const index = document.createElement("span"); index.className = "deep-stage-index"; index.textContent = `0${item.index}`.slice(-2);
        const status = document.createElement("span"); status.className = "deep-stage-state"; status.textContent = deepStageStateLabel(item.status);
        head.append(index, status);
        const title = document.createElement("div"); title.className = "deep-stage-title"; title.textContent = item.label;
        const copy = document.createElement("div"); copy.className = "deep-stage-copy"; copy.textContent = item.description;
        const action = document.createElement("span"); action.className = "deep-stage-action"; action.textContent = "点击进入该阶段对话 →";
        card.tabIndex = 0; card.setAttribute("role", "button"); card.setAttribute("aria-label", `${item.label}：进入该阶段对话`);
        card.addEventListener("click", () => { void continueDeepStockConversation(item.question); });
        card.addEventListener("keydown", event => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            void continueDeepStockConversation(item.question);
          }
        });
        card.append(head, title, copy, action); stages.appendChild(card);
      }
      main.append(progress, stages);

      const side = document.createElement("aside"); side.className = "deep-stock-side";
      const next = document.createElement("section"); next.className = "deep-stock-card";
      const nextTitle = document.createElement("div"); nextTitle.className = "deep-stock-card-title"; nextTitle.textContent = "下一步研究问题";
      const nextCopy = document.createElement("div"); nextCopy.className = "deep-stock-card-copy"; nextCopy.textContent = session.next_question;
      next.append(nextTitle, nextCopy);

      const unresolved = document.createElement("section"); unresolved.className = "deep-stock-card";
      const unresolvedTitle = document.createElement("div"); unresolvedTitle.className = "deep-stock-card-title"; unresolvedTitle.textContent = "未解决证据";
      if ((session.unresolved_items || []).length) {
        const list = document.createElement("ul"); list.className = "deep-stock-list";
        for (const item of session.unresolved_items) { const li = document.createElement("li"); li.textContent = item; list.appendChild(li); }
        unresolved.append(unresolvedTitle, list);
      } else {
        const copy = document.createElement("div"); copy.className = "deep-stock-card-copy"; copy.textContent = "当前没有已识别的结构化缺口；新对话仍会继续检查反方证据。";
        unresolved.append(unresolvedTitle, copy);
      }

      const report = document.createElement("section"); report.className = "deep-stock-card";
      const reportTitle = document.createElement("div"); reportTitle.className = "deep-stock-card-title"; reportTitle.textContent = "最新研究报告";
      const reportCopy = document.createElement("div"); reportCopy.className = "deep-stock-card-copy";
      reportCopy.textContent = readableResearchPreview(session.latest_report?.summary) || "服务器正在生成最新研究报告；阶段对话仍可先开始。";
      report.append(reportTitle, reportCopy);
      if (session.latest_report) {
        const actions = document.createElement("div"); actions.className = "deep-stock-actions";
        const read = document.createElement("button"); read.type = "button"; read.className = "report-link"; read.textContent = "阅读完整报告";
        read.addEventListener("click", () => openReader(
          session.latest_report.title || `${session.name}研究报告`,
          session.latest_report.body || session.latest_report.summary,
          `数据时间 ${readableTime(session.latest_report.market_timestamp)} · 生成于 ${readableTime(session.latest_report.generated_at)}`
        ));
        actions.appendChild(read); report.appendChild(actions);
      }
      side.append(next, unresolved, report);
      container.append(main, side);
    }

    async function loadDeepStock() {
      if (!state.user) return;
      try {
        const data = await api("/me/deep-stock?limit=50");
        state.deepStockSessions = data.items || [];
        refreshDeepStockSymbolOptions();
        if (!state.deepStock && state.deepStockSessions.length) {
          $("deepStockSymbol").value = state.deepStockSessions[0].symbol;
        }
        const selected = $("deepStockSymbol").value;
        renderDeepStock(state.deepStockSessions.find(item => item.symbol === selected) || null);
        if (selected) void loadDeepStockOverview(selected);
      } catch {
        $("deepStockContent").className = "deep-stock-empty";
        $("deepStockContent").textContent = "个股研究状态正在重新连接。";
      }
    }

    async function startDeepStockSession() {
      const symbol = $("deepStockSymbol").value;
      if (!symbol) return null;
      $("startDeepStock").disabled = true;
      try {
        const session = await api("/me/deep-stock", {
          method: "POST",
          body: JSON.stringify({symbol})
        });
        state.deepStock = session;
        await loadConversations(false);
        await loadDeepStock();
        await loadDeepStockOverview(symbol);
        return session;
      } catch (error) {
        $("deepStockContent").className = "deep-stock-empty";
        $("deepStockContent").textContent = error.message || "这只股票暂时无法建立研究空间。";
        return null;
      } finally { $("startDeepStock").disabled = false; }
    }

    async function continueDeepStockConversation(prefillQuestion = null) {
      const session = state.deepStock || await startDeepStockSession();
      if (!session?.conversation_id) return;
      await loadConversations(false);
      await openConversation(session.conversation_id, false);
      activateWorkspace("agent");
      $("modelTier").value = "deep";
      updateAgentMode();
      $("chatInput").value = prefillQuestion || session.next_question || "请继续当前个股研究阶段。";
      $("chatInput").focus();
    }

    async function openResearchReport(symbol, button) {
      const original = button.textContent;
      button.disabled = true;
      button.textContent = "读取中…";
      try {
        const report = await api(`/research-reports/${encodeURIComponent(symbol)}`);
        openReader(
          report.title || `${symbol}研究快照`,
          report.body || report.summary,
          `数据时间 ${readableTime(report.market_timestamp)} · 生成于 ${readableTime(report.generated_at)}`
        );
        button.textContent = "阅读分析";
      } catch (error) {
        openReader(`${symbol}研究快照`, "研究证据正在更新，请稍后重试。", "尚未生成可阅读版本");
        button.textContent = original;
      } finally { button.disabled = false; }
    }

    function dedupeInsightItems(items = []) {
      const seen = new Set();
      return items.filter(item => {
        const titleKey = String(item.title || "")
          .normalize("NFKC")
          .toLowerCase()
          .replace(/[\s\p{P}\p{S}]+/gu, "")
          .slice(0, 180);
        const key = titleKey || String(item.url || item.id || "");
        if (!key || seen.has(key)) return false;
        seen.add(key);
        return true;
      });
    }

    function humanizeInsightText(value) {
      return String(value || "")
        .replace(/\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})/g, match => readableTime(match))
        .replace(/(代表性指数)?上涨比例\s+(0(?:\.\d+)?|1(?:\.0+)?)(?!%)/g, (_, prefix, ratio) => `${prefix || ""}上涨比例 ${(Number(ratio) * 100).toFixed(1)}%`)
        .replace(/置信度\s+low_to_medium\b/g, "置信度 中等偏低")
        .replace(/置信度\s+medium_to_high\b/g, "置信度 中等偏高")
        .replace(/置信度\s+medium\b/g, "置信度 中等")
        .replace(/置信度\s+low\b/g, "置信度 较低")
        .replace(/置信度\s+high\b/g, "置信度 较高");
    }

    // 与 dedupeInsightItems 同源的行 key：优先 id，其次归一化标题（列表已去重，key 在列表内唯一）。
    function insightRowKey(article) {
      if (article.id !== undefined && article.id !== null && article.id !== "") return `id:${article.id}`;
      const titleKey = String(article.title || "")
        .normalize("NFKC")
        .toLowerCase()
        .replace(/[\s\p{P}\p{S}]+/gu, "")
        .slice(0, 180);
      return `${article.category || "insight"}:${titleKey || article.url || article.created_at || ""}`;
    }

    function renderArticles(items = state.insightItems) {
      const container = $("articleFeed");
      const visibleItems = state.insightFilter === "all"
        ? items
        : items.filter(item => item.category === state.insightFilter);
      reconcileKeyedList(container, visibleItems, {
        key: insightRowKey,
        signature: article => JSON.stringify([
          article.title, article.content_label, article.created_at,
          humanizeInsightText(article.summary || article.body || "")
        ]),
        create() {
          const row = document.createElement("button"); row.className = "article-item";
          const title = document.createElement("span"); title.className = "article-item-title";
          const time = document.createElement("span"); time.className = "article-item-time";
          const summary = document.createElement("span"); summary.className = "article-item-summary";
          row.append(title, time, summary);
          row._refs = {title, time, summary};
          row.addEventListener("click", () => {
            const article = row._listItem;
            openReader(article.title, humanizeInsightText(article.body || article.summary), `${article.content_label || "市场洞察"} · ${readableTime(article.created_at)}`);
          });
          return row;
        },
        update(row, article) {
          const refs = row._refs;
          refs.title.textContent = article.title || "市场洞察";
          refs.time.textContent = `${article.content_label || "市场短文"} · ${readableTime(article.created_at)}`;
          refs.summary.textContent = humanizeInsightText(article.summary || article.body || "");
        }
      });
      if (!container.firstElementChild) container.innerHTML = '<div class="empty">新的市场洞察正在形成</div>';
      renderHomeFocus();
    }

    async function loadArticles() {
      const [articlesResult, reportsResult, actionsResult] = await Promise.allSettled([
        api("/articles?limit=12"),
        api("/research-reports?limit=12"),
        apiGetShared("/me/research-actions")
      ]);
      const articles = articlesResult.status === "fulfilled" ? articlesResult.value : {items: []};
      const reports = reportsResult.status === "fulfilled" ? reportsResult.value : {items: []};
      const actions = actionsResult.status === "fulfilled" ? actionsResult.value : {items: []};
      const opportunities = (actions.items || [])
        .filter(item => item.research_status !== "observe")
        .map(item => {
          const actionLines = (item.actions || [])
            .filter(action => action.status !== "watching")
            .slice(0, 5)
            .map(action => `${action.title}\n当前证据：${action.current_evidence}\n下一步：${action.next_step}`);
          return {
            category: "opportunity",
            content_label: "待复核机会",
            title: `${item.name || item.symbol} · ${item.research_status_label || "研究复核"}`,
            summary: `${item.headline || "存在需要继续研究的线索"}。这里的“机会”是待复核研究任务，不是买入信号。`,
            body: [`研究对象：${item.name || item.symbol}（${item.symbol}）`, `当前状态：${item.research_status_label || "待复核"}`, `原关注理由：${item.thesis || "尚未记录"}`, ...actionLines, actions.boundary || "研究机会不等于交易建议。"].join("\n\n"),
            created_at: item.latest_report_at || item.data_as_of || actions.generated_at
          };
        });
      state.insightItems = dedupeInsightItems([
        ...(articles.items || []).map(item => ({ ...item, category: "market", content_label: "大盘洞察" })),
        ...(reports.items || []).map(item => ({ ...item, category: "stock", created_at: item.generated_at, content_label: "个股研究" })),
        ...opportunities
      ].sort((a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0)));
      lastArticlesLoadedAt = Date.now();
      renderArticles();
    }

    function reviewSeconds(value) {
      const number = Number(value);
      if (!Number.isFinite(number)) return "—";
      if (number < 1) return `${Math.round(number * 1000)} ms`;
      return `${number.toFixed(number < 10 ? 2 : 1)} s`;
    }

    function researchDate(value) {
      const text = String(value || "");
      const match = text.match(/^\d{4}-\d{2}-\d{2}/);
      return match ? match[0] : "日期待确认";
    }

    function outcomeStatus(row) {
      if (!row) return {key: "unavailable", label: "尚无快照"};
      if (row.result_status === "available") return {key: "available", label: "已到期"};
      if (row.result_status === "pending") return {key: "pending", label: `观察 ${row.observed_sessions || 0}/${row.horizon_sessions || 0}`};
      return {key: "unavailable", label: "暂不可评估"};
    }

    function outcomeReturn(row) {
      if (!row) return null;
      return row.result_status === "available" ? row.close_return_pct : row.partial_return_pct;
    }

    function activateReviewTab(tabName = "outcomes") {
      state.reviewTab = ["outcomes", "runs", "evidence", "quality"].includes(tabName) ? tabName : "outcomes";
      document.querySelectorAll("[data-review-tab]").forEach(button => {
        const active = button.dataset.reviewTab === state.reviewTab;
        button.classList.toggle("active", active);
        button.setAttribute("aria-selected", active ? "true" : "false");
      });
      document.querySelectorAll("[data-review-panel]").forEach(panel => {
        panel.hidden = panel.dataset.reviewPanel !== state.reviewTab;
      });
    }

    function renderReviewStats(outcomesData) {
      const coverage = outcomesData?.coverage || {};
      const values = [
        [coverage.requested_symbols ?? 0, "来自我的关注"],
        [coverage.with_archives ?? 0, "可持续复核"],
        [coverage.available_outcomes ?? 0, "累计历史节点"],
        [coverage.pending_outcomes ?? 0, "累计历史节点"]
      ];
      const cards = $("reviewStats").children;
      values.forEach(([value, caption], index) => {
        const card = cards[index];
        if (!card) return;
        card.querySelector("strong").textContent = value;
        card.querySelector("small").textContent = caption;
      });
    }

    function renderOutcomeProgress(container, rows) {
      [3, 5, 10].forEach(horizon => {
        const row = (rows || []).find(item => Number(item.horizon_sessions) === horizon);
        const status = outcomeStatus(row);
        const card = document.createElement("div"); card.className = `review-outcome-horizon ${status.key}`;
        const label = document.createElement("span"); label.textContent = `T+${horizon}`;
        const detail = document.createElement("small");
        const result = outcomeReturn(row);
        detail.textContent = row && result !== null && result !== undefined ? `${status.label} · ${pct(result)}` : status.label;
        card.append(label, detail); container.appendChild(card);
      });
    }

    function renderOutcomeResult(row) {
      const status = outcomeStatus(row);
      const card = document.createElement("article"); card.className = `review-outcome-result ${status.key}`;
      const head = document.createElement("div"); head.className = "review-outcome-result-head";
      const title = document.createElement("strong"); title.textContent = `T+${row?.horizon_sessions || "—"}`;
      const badge = document.createElement("span"); badge.className = `review-outcome-state ${status.key}`; badge.textContent = status.label;
      head.append(title, badge); card.appendChild(head);

      const result = outcomeReturn(row);
      const value = document.createElement("div"); value.className = "review-outcome-result-value";
      if (Number(result) > 0) value.classList.add("up");
      if (Number(result) < 0) value.classList.add("down");
      value.textContent = result === null || result === undefined ? "等待观察" : pct(result);
      card.appendChild(value);

      const path = document.createElement("div"); path.className = "review-outcome-result-path";
      const up = document.createElement("span"); up.textContent = `最大上行 ${row?.maximum_favorable_excursion_pct === null || row?.maximum_favorable_excursion_pct === undefined ? "—" : pct(row.maximum_favorable_excursion_pct)}`;
      const down = document.createElement("span"); down.textContent = `最大下行 ${row?.maximum_adverse_excursion_pct === null || row?.maximum_adverse_excursion_pct === undefined ? "—" : pct(row.maximum_adverse_excursion_pct)}`;
      path.append(up, down); card.appendChild(path);

      const copy = document.createElement("div"); copy.className = "review-outcome-result-copy";
      copy.textContent = row?.review_conclusion || "当前还没有足够的后续交易日，系统会继续自动观察。";
      card.appendChild(copy);
      return card;
    }

    function appendOutcomeContext(container, label, value) {
      const card = document.createElement("div"); card.className = "review-outcome-context-item";
      const title = document.createElement("span"); title.textContent = label;
      const detail = document.createElement("strong"); detail.textContent = value || "—";
      card.append(title, detail); container.appendChild(card);
    }

    function renderOutcomeDetail(item, packet) {
      const container = $("reviewOutcomeDetail"); container.innerHTML = "";
      const rows = item.latest_anchor || [];
      const available = rows.filter(row => row.result_status === "available").length;
      const head = document.createElement("div"); head.className = "review-outcome-detail-head";
      const identity = document.createElement("div");
      const name = document.createElement("div"); name.className = "review-outcome-detail-name"; name.textContent = item.name || item.symbol;
      const meta = document.createElement("div"); meta.className = "review-outcome-detail-meta"; meta.textContent = `${item.symbol} · 最近研究快照 ${researchDate(item.latest_anchor_at)}`;
      identity.append(name, meta);
      const badge = document.createElement("span"); badge.className = "review-outcome-detail-badge";
      badge.textContent = available ? `${available} 项已经到期` : "正在持续观察";
      head.append(identity, badge); container.appendChild(head);

      const thesis = document.createElement("div"); thesis.className = "review-outcome-thesis-box";
      const thesisLabel = document.createElement("span"); thesisLabel.textContent = "原关注理由";
      const thesisCopy = document.createElement("strong"); thesisCopy.textContent = item.thesis || "尚未记录关注理由；可以在“我的关注”中补充。";
      thesis.append(thesisLabel, thesisCopy); container.appendChild(thesis);

      const resultSection = document.createElement("section"); resultSection.className = "review-outcome-section";
      const resultTitle = document.createElement("div"); resultTitle.className = "review-outcome-section-title"; resultTitle.textContent = "后续验证进度";
      const resultCopy = document.createElement("div"); resultCopy.className = "review-outcome-section-copy"; resultCopy.textContent = "分别查看研究之后第 3、5、10 个交易日；区间最大上行和下行只描述实际路径。";
      const grid = document.createElement("div"); grid.className = "review-outcome-horizon-grid";
      [3, 5, 10].forEach(horizon => grid.appendChild(renderOutcomeResult(rows.find(row => Number(row.horizon_sessions) === horizon) || {horizon_sessions: horizon, result_status: "pending", observed_sessions: 0})));
      resultSection.append(resultTitle, resultCopy, grid); container.appendChild(resultSection);

      const context = item.current_research_context || {};
      const metrics = context.metrics || {};
      const financial = context.latest_financial || {};
      const contextSection = document.createElement("section"); contextSection.className = "review-outcome-section";
      const contextTitle = document.createElement("div"); contextTitle.className = "review-outcome-section-title"; contextTitle.textContent = "当前研究背景";
      const contextCopy = document.createElement("div"); contextCopy.className = "review-outcome-section-copy"; contextCopy.textContent = "这些数据用于判断原条件是否仍然成立，不代替上面的历史结果。";
      const contextGrid = document.createElement("div"); contextGrid.className = "review-outcome-context-grid";
      appendOutcomeContext(contextGrid, "最新收盘", metrics.latest_close === null || metrics.latest_close === undefined ? "—" : numeric(metrics.latest_close));
      appendOutcomeContext(contextGrid, "20日变化", metrics.return_20d_pct === null || metrics.return_20d_pct === undefined ? "—" : pct(metrics.return_20d_pct));
      appendOutcomeContext(contextGrid, "趋势状态", metrics.trend_state || metrics.technical_state || "—");
      appendOutcomeContext(contextGrid, "60日最大回撤", metrics.max_drawdown_60d_pct === null || metrics.max_drawdown_60d_pct === undefined ? "—" : pct(metrics.max_drawdown_60d_pct));
      appendOutcomeContext(contextGrid, "最新财报", financial.report_date_name || "—");
      appendOutcomeContext(contextGrid, "营收同比", financial.revenue_yoy_pct === null || financial.revenue_yoy_pct === undefined ? "—" : pct(financial.revenue_yoy_pct));
      appendOutcomeContext(contextGrid, "净利润同比", financial.net_profit_yoy_pct === null || financial.net_profit_yoy_pct === undefined ? "—" : pct(financial.net_profit_yoy_pct));
      appendOutcomeContext(contextGrid, "经营现金流/净利润", context.operating_cashflow_to_net_profit === null || context.operating_cashflow_to_net_profit === undefined ? "—" : numeric(context.operating_cashflow_to_net_profit));
      contextSection.append(contextTitle, contextCopy, contextGrid); container.appendChild(contextSection);

      const actions = document.createElement("div"); actions.style.marginTop = "18px";
      const ask = document.createElement("button"); ask.type = "button"; ask.className = "btn primary"; ask.textContent = "让 Agent 复核这次研究";
      ask.addEventListener("click", () => {
        prepareAgentQuestion(`${item.name || item.symbol}之前的研究后来怎么样？请结合T+3、T+5、T+10进度，说明原判断是否需要修正。`);
      });
      actions.appendChild(ask); container.appendChild(actions);

      const boundary = document.createElement("div"); boundary.className = "review-outcome-boundary";
      boundary.textContent = packet.boundary || "研究结果只用于复核条件与反证，不评价买卖收益或荐股能力。";
      container.appendChild(boundary);
    }

    function openOutcome(symbol) {
      state.selectedOutcomeSymbol = symbol;
      document.querySelectorAll(".review-outcome-item").forEach(item => item.classList.toggle("active", item.dataset.symbol === symbol));
      const packet = state.researchOutcomes || {};
      const selected = (packet.items || []).find(item => item.symbol === symbol);
      if (selected) renderOutcomeDetail(selected, packet);
    }

    function renderResearchOutcomes(data) {
      state.researchOutcomes = data || {};
      renderReviewStats(data);
      const container = $("reviewOutcomeList"); container.innerHTML = "";
      for (const item of (data.items || [])) {
        const button = document.createElement("button"); button.type = "button"; button.className = `review-outcome-item${state.selectedOutcomeSymbol === item.symbol ? " active" : ""}`; button.dataset.symbol = item.symbol;
        const head = document.createElement("div"); head.className = "review-outcome-item-head";
        const identity = document.createElement("div");
        const name = document.createElement("div"); name.className = "review-outcome-name"; name.textContent = item.name || item.symbol;
        const symbol = document.createElement("span"); symbol.className = "review-outcome-symbol"; symbol.textContent = item.symbol;
        identity.append(name, symbol);
        const anchor = document.createElement("span"); anchor.className = "review-outcome-anchor"; anchor.textContent = researchDate(item.latest_anchor_at);
        head.append(identity, anchor); button.appendChild(head);
        const thesis = document.createElement("div"); thesis.className = "review-outcome-thesis"; thesis.textContent = item.thesis || "尚未记录关注理由"; button.appendChild(thesis);
        const progress = document.createElement("div"); progress.className = "review-outcome-progress"; renderOutcomeProgress(progress, item.latest_anchor || []); button.appendChild(progress);
        button.addEventListener("click", () => openOutcome(item.symbol)); container.appendChild(button);
      }
      if (!container.children.length) {
        container.innerHTML = '<div class="empty">还没有可跟踪的研究。先在“我的关注”添加股票并生成研究报告。</div>';
        $("reviewOutcomeDetail").innerHTML = '<div class="review-detail-empty"><div class="review-detail-empty-icon">◇</div><strong>暂无研究结果</strong><span>研究快照形成后，系统会按交易日自动回填。</span></div>';
        return;
      }
      const visible = (data.items || []).some(item => item.symbol === state.selectedOutcomeSymbol);
      if (!visible) state.selectedOutcomeSymbol = data.items[0].symbol;
      openOutcome(state.selectedOutcomeSymbol);
    }

    function renderRunReviewList(data) {
      state.reviewRuns = data.items || [];
      state.reviewRunSummary = data.summary || {};
      const summary = state.reviewRunSummary;
      $("reviewRunSummary").textContent = `显示 ${summary.filtered || 0} / ${summary.total || 0} 条`;
      const container = $("reviewRunList"); container.innerHTML = "";
      for (const item of state.reviewRuns) {
        const row = document.createElement("button");
        row.type = "button";
        row.className = `review-run-item${state.selectedReviewRunId === item.id ? " active" : ""}`;
        row.dataset.runId = item.id;
        const head = document.createElement("div"); head.className = "review-run-item-head";
        const title = document.createElement("div"); title.className = "review-run-item-title";
        title.textContent = item.symbol ? `${item.display_name} · ${item.symbol}` : item.intent_label;
        const status = document.createElement("span"); status.className = `review-status ${item.status}`; status.textContent = item.status_label;
        head.append(title, status);
        const question = document.createElement("div"); question.className = "review-run-item-question"; question.textContent = item.question;
        const meta = document.createElement("div"); meta.className = "review-run-item-meta";
        const guard = document.createElement("span");
        const dot = document.createElement("span"); dot.className = `review-guard-dot${item.guard?.passed && !item.guard?.repaired ? " clean" : ""}`;
        guard.append(dot, document.createTextNode(` ${item.guard?.label || (item.guard?.repaired ? "守卫修复" : "守卫通过")}`));
        const duration = document.createElement("span"); duration.textContent = reviewSeconds(item.duration_seconds);
        const time = document.createElement("span"); time.textContent = readableTime(item.created_at);
        meta.append(guard, duration, time);
        row.append(head, question, meta);
        row.addEventListener("click", () => { void openRunReview(item.id); });
        container.appendChild(row);
      }
      if (!container.children.length) {
        container.innerHTML = '<div class="empty">当前筛选条件下没有可复盘的用户 Run。</div>';
        state.selectedReviewRunId = null;
        $("reviewRunDetail").innerHTML = '<div class="review-detail-empty"><div class="review-detail-empty-icon">⌁</div><strong>没有匹配的 Run</strong><span>调整状态、守卫或时间范围后再查看。</span></div>';
      }
    }

    function appendReviewMetric(container, label, value) {
      const card = document.createElement("div"); card.className = "review-detail-metric";
      const labelNode = document.createElement("span"); labelNode.textContent = label;
      const valueNode = document.createElement("strong"); valueNode.textContent = value || "—";
      card.append(labelNode, valueNode); container.appendChild(card);
    }

    function renderRunReviewDetail(data) {
      const container = $("reviewRunDetail"); container.innerHTML = "";
      const head = document.createElement("div"); head.className = "review-detail-head";
      const identity = document.createElement("div");
      const title = document.createElement("div"); title.className = "review-detail-title";
      title.textContent = data.symbol ? `${data.display_name} · ${data.symbol}` : data.intent_label;
      const subtitle = document.createElement("div"); subtitle.className = "review-detail-subtitle";
      subtitle.textContent = `${data.conversation_title} · ${data.intent_label} · ${readableTime(data.created_at)}`;
      identity.append(title, subtitle);
      const status = document.createElement("span"); status.className = `review-status ${data.status}`; status.textContent = data.status_label;
      head.append(identity, status); container.appendChild(head);

      const question = document.createElement("div"); question.className = "review-detail-question";
      question.textContent = data.question; container.appendChild(question);

      const metrics = document.createElement("div"); metrics.className = "review-detail-metrics";
      appendReviewMetric(metrics, "证据快照", readableTime(data.data_as_of));
      appendReviewMetric(metrics, "总耗时", reviewSeconds(data.duration_seconds));
      appendReviewMetric(metrics, "首个安全可见", reviewSeconds(data.timings?.first_visible_seconds));
      appendReviewMetric(metrics, "模型状态", data.model_state);
      container.appendChild(metrics);

      const timelineSection = document.createElement("section"); timelineSection.className = "review-detail-section";
      const timelineTitle = document.createElement("div"); timelineTitle.className = "review-detail-section-title";
      timelineTitle.append(document.createTextNode("阶段耗时"), Object.assign(document.createElement("small"), {textContent: "均来自本轮真实计时"}));
      const timeline = document.createElement("div"); timeline.className = "review-timeline";
      const timingRows = [
        ["路由与证据包", data.timings?.evidence_seconds],
        ["Hermes 综合", data.timings?.model_seconds],
        ["输出守卫", data.timings?.guard_seconds],
        ["请求总计", data.timings?.total_seconds]
      ];
      timingRows.forEach(([label, value]) => {
        const row = document.createElement("div"); row.className = "review-timeline-row";
        const name = document.createElement("strong"); name.textContent = label;
        const duration = document.createElement("span"); duration.textContent = reviewSeconds(value);
        row.append(name, duration); timeline.appendChild(row);
      });
      timelineSection.append(timelineTitle, timeline); container.appendChild(timelineSection);

      const evidenceSection = document.createElement("section"); evidenceSection.className = "review-detail-section";
      const evidenceTitle = document.createElement("div"); evidenceTitle.className = "review-detail-section-title";
      const moduleCaption = data.evidence?.total_modules
        ? `${data.evidence.ready_modules || 0} / ${data.evidence.total_modules} 个模块就绪`
        : "市场级结构化证据包";
      evidenceTitle.append(document.createTextNode("本轮证据"), Object.assign(document.createElement("small"), {textContent: moduleCaption}));
      const modules = document.createElement("div"); modules.className = "review-module-list";
      for (const item of (data.evidence?.modules || [])) {
        const badge = document.createElement("span"); badge.className = `review-module ${item.status || "ready"}`;
        badge.textContent = `${item.label} ${item.evidence_count || 0}`; modules.appendChild(badge);
      }
      const sources = document.createElement("div"); sources.className = "review-source-list";
      const sourceSummary = [
        [`资料库`, data.evidence?.knowledge_documents],
        [`公告`, data.evidence?.announcements],
        [`新闻`, data.evidence?.news],
        [`社区样本`, data.evidence?.social_posts]
      ];
      sourceSummary.forEach(([label, value]) => {
        const badge = document.createElement("span"); badge.className = "review-source"; badge.textContent = `${label} ${value || 0}`; sources.appendChild(badge);
      });
      for (const item of (data.evidence?.knowledge_items || [])) {
        const badge = document.createElement("span"); badge.className = "review-source"; badge.textContent = `${item.scope} · ${item.title}`; sources.appendChild(badge);
      }
      evidenceSection.append(evidenceTitle, modules, sources); container.appendChild(evidenceSection);

      if (data.quote?.price !== null && data.quote?.price !== undefined) {
        const quoteSection = document.createElement("section"); quoteSection.className = "review-detail-section";
        const quoteTitle = document.createElement("div"); quoteTitle.className = "review-detail-section-title"; quoteTitle.textContent = "行情口径";
        const quoteBox = document.createElement("div"); quoteBox.className = "review-timeline";
        const quoteRows = [
          ["当前报价", `${numeric(data.quote.price)} ${data.quote.currency || ""} · ${pct(data.quote.pct_change)} · ${readableTime(data.quote.market_timestamp)}`],
          ["上一完整日线", `${numeric(data.quote.daily_close)} ${data.quote.currency || ""} · ${readableTime(data.quote.daily_timestamp)}`]
        ];
        quoteRows.forEach(([label, value]) => {
          const row = document.createElement("div"); row.className = "review-timeline-row";
          const name = document.createElement("strong"); name.textContent = label;
          const detail = document.createElement("span"); detail.textContent = value;
          row.append(name, detail); quoteBox.appendChild(row);
        });
        quoteSection.append(quoteTitle, quoteBox); container.appendChild(quoteSection);
      }

      const guardSection = document.createElement("section"); guardSection.className = "review-detail-section";
      const guardTitle = document.createElement("div"); guardTitle.className = "review-detail-section-title"; guardTitle.textContent = "展示前守卫";
      const guardBox = document.createElement("div"); guardBox.className = `review-guard-box${data.guard?.passed && !data.guard?.repaired ? " clean" : ""}`;
      guardBox.textContent = (data.guard?.summary || []).join("；");
      guardSection.append(guardTitle, guardBox); container.appendChild(guardSection);

      const answerSection = document.createElement("section"); answerSection.className = "review-detail-section";
      const answerTitle = document.createElement("div"); answerTitle.className = "review-detail-section-title";
      answerTitle.append(document.createTextNode("最终用户可见回答"), Object.assign(document.createElement("small"), {textContent: "与对话中保存内容一致"}));
      const answer = document.createElement("div"); answer.className = "review-answer message-body";
      answer.appendChild(renderMarkdown(data.answer || "本轮未形成可展示回答。"));
      answerSection.append(answerTitle, answer); container.appendChild(answerSection);
    }

    async function openRunReview(runId) {
      state.selectedReviewRunId = runId;
      document.querySelectorAll(".review-run-item").forEach(item => item.classList.toggle("active", item.dataset.runId === runId));
      $("reviewRunDetail").innerHTML = '<div class="review-detail-empty"><div class="review-detail-empty-icon">⌁</div><strong>正在读取本轮证据</strong><span>只加载可面向用户复盘的字段。</span></div>';
      try {
        const data = await api(`/me/run-reviews/${encodeURIComponent(runId)}`);
        if (state.selectedReviewRunId === runId) renderRunReviewDetail(data);
      } catch {
        $("reviewRunDetail").innerHTML = '<div class="review-detail-empty"><div class="review-detail-empty-icon">!</div><strong>这条复盘暂时无法读取</strong><span>请选择其他 Run 或稍后重试。</span></div>';
      }
    }

    async function loadRunReviews() {
      const params = new URLSearchParams({days: $("reviewRunDays").value || "7", limit: "50"});
      const status = $("reviewRunStatus").value;
      const repaired = $("reviewRunRepair").value;
      const query = $("reviewRunSearch").value.trim();
      if (status) params.set("status", status);
      if (repaired) params.set("repaired", repaired);
      if (query) params.set("q", query);
      const data = await api(`/me/run-reviews?${params.toString()}`);
      renderRunReviewList(data);
      const selectedStillVisible = state.reviewRuns.some(item => item.id === state.selectedReviewRunId);
      if (!selectedStillVisible && state.reviewRuns.length) state.selectedReviewRunId = state.reviewRuns[0].id;
      if (state.selectedReviewRunId) await openRunReview(state.selectedReviewRunId);
      return data;
    }

    async function refreshRunReviews() {
      try {
        await loadRunReviews();
      } catch {
        $("reviewRunSummary").textContent = "筛选结果暂时无法读取";
      }
    }

    function renderResearchMethod(data) {
      const steps = $("methodSteps"); steps.innerHTML = "";
      for (const [index, item] of (data.pipeline || []).entries()) {
        const row = document.createElement("div"); row.className = "method-step";
        const title = document.createElement("div"); title.className = "method-item-title";
        const marker = document.createElement("span"); marker.className = "method-step-index"; marker.textContent = String(index + 1);
        title.append(marker, document.createTextNode(item.title));
        const detail = document.createElement("div"); detail.className = "method-item-meta"; detail.textContent = item.detail;
        row.append(title, detail); steps.appendChild(row);
      }
      if (!steps.children.length) steps.innerHTML = '<div class="empty">分析流程正在整理</div>';

      const tools = $("methodTools"); tools.innerHTML = "";
      for (const item of (data.tools || [])) {
        const row = document.createElement("div"); row.className = "method-tool";
        const title = document.createElement("div"); title.className = "method-item-title"; title.textContent = item.name;
        const detail = document.createElement("div"); detail.className = "method-item-meta"; detail.textContent = item.role;
        row.append(title, detail); tools.appendChild(row);
      }
      if (!tools.children.length) tools.innerHTML = '<div class="empty">工具清单正在整理</div>';

      const cases = $("methodCases"); cases.innerHTML = "";
      for (const item of (data.recent_analyses || [])) {
        const row = document.createElement("button"); row.className = "method-case"; row.type = "button";
        const head = document.createElement("div"); head.className = "method-case-head";
        const title = document.createElement("div"); title.className = "method-item-title"; title.textContent = item.title;
        const time = document.createElement("div"); time.className = "method-item-meta"; time.textContent = readableTime(item.generated_at);
        head.append(title, time);
        const detail = document.createElement("div"); detail.className = "method-item-meta"; detail.textContent = item.summary;
        const modules = document.createElement("div"); modules.className = "method-module-row";
        for (const module of (item.modules || [])) {
          const badge = document.createElement("span"); badge.className = "method-module";
          badge.textContent = `${module.label} ${module.evidence_count ?? 0}`; modules.appendChild(badge);
        }
        row.append(head, detail, modules);
        row.addEventListener("click", async () => {
          try {
            const report = await api(`/research-reports/${encodeURIComponent(item.symbol)}`);
            openReader(
              report.title || item.title,
              report.body || report.summary,
              `数据时间 ${readableTime(report.market_timestamp)} · 生成于 ${readableTime(report.generated_at)}`
            );
          } catch {
            openReader(item.title, item.summary, "已保存研究摘要");
          }
        });
        cases.appendChild(row);
      }
      if (!cases.children.length) cases.innerHTML = '<div class="empty">预计算研究正在建立</div>';
      $("methodBoundary").textContent = (data.boundaries || []).join("  ");
    }

    function renderResearchActions(data) {
      const summary = data.summary || {};
      $("methodActionSummary").textContent = `覆盖 ${summary.symbols || 0} 个自选标的 · ${summary.triggered || 0} 项需要复核 · ${summary.pending_data || 0} 项待补证 · ${summary.watching || 0} 项继续观察`;
      const container = $("methodActions"); container.innerHTML = "";
      const statusLabels = {risk_review: "风险复核", priority_research: "优先研究", pending_review: "待补证", observe: "持续观察"};
      const actionLabels = {triggered: "已达到复核条件", pending_data: "仍待补证", watching: "继续观察"};
      for (const item of (data.items || [])) {
        const card = document.createElement("div"); card.className = "method-action-item";
        const head = document.createElement("div"); head.className = "method-action-head";
        const identity = document.createElement("div");
        const title = document.createElement("div"); title.className = "method-item-title"; title.textContent = `${item.name || item.symbol} · ${item.symbol}`;
        const meta = document.createElement("div"); meta.className = "method-item-meta"; meta.textContent = item.headline || "已建立研究行动";
        identity.append(title, meta);
        const state = document.createElement("span"); state.className = `method-action-state ${item.research_status || "observe"}`; state.textContent = statusLabels[item.research_status] || item.research_status_label || "持续观察";
        head.append(identity, state); card.appendChild(head);
        for (const action of (item.actions || []).slice(0, 4)) {
          const row = document.createElement("div"); row.className = "method-action-row";
          const rowTitle = document.createElement("div"); rowTitle.className = "method-action-row-title"; rowTitle.textContent = `${actionLabels[action.status] || "研究行动"} · ${action.title}`;
          const evidence = document.createElement("div"); evidence.className = "method-action-row-meta"; evidence.textContent = action.current_evidence || action.condition;
          const next = document.createElement("div"); next.className = "method-action-row-meta"; next.textContent = `下一步：${action.next_step}`;
          row.append(rowTitle, evidence, next); card.appendChild(row);
        }
        container.appendChild(card);
      }
      if (!container.children.length) container.innerHTML = '<div class="empty">添加自选股和关注理由后，这里会形成研究行动。</div>';
    }

    function renderEvidenceTasks(data) {
      const summary = data.summary || {};
      $("methodEvidenceSummary").textContent = `共 ${summary.total || 0} 项 · ${summary.pending || 0} 项等待补齐 · ${summary.collecting || 0} 项正在采集 · ${summary.resolved || 0} 项已入库 · ${summary.pending_external || 0} 项等待外部资料`;
      const container = $("methodEvidenceTasks"); container.innerHTML = "";
      for (const item of (data.items || []).slice(0, 12)) {
        const card = document.createElement("div"); card.className = "method-action-item";
        const head = document.createElement("div"); head.className = "method-action-head";
        const identity = document.createElement("div");
        const title = document.createElement("div"); title.className = "method-item-title";
        title.textContent = `${item.symbol || item.market_key || "通用研究"} · ${item.title}`;
        const meta = document.createElement("div"); meta.className = "method-item-meta";
        meta.textContent = item.description || "待补充研究证据";
        identity.append(title, meta);
        const state = document.createElement("span");
        state.className = `method-action-state evidence-task-state ${item.status || "pending"}`;
        state.textContent = item.status_label || "等待处理";
        head.append(identity, state); card.appendChild(head);
        const lifecycle = document.createElement("div"); lifecycle.className = "method-action-row";
        const source = document.createElement("div"); source.className = "method-action-row-title";
        source.textContent = item.resolution_document_id ? "补齐结果已进入个人资料库" : "任务会保留并继续处理";
        const time = document.createElement("div"); time.className = "method-action-row-meta";
        time.textContent = `发现于 ${readableTime(item.created_at)} · 最近处理 ${readableTime(item.processed_at || item.updated_at)}`;
        const note = document.createElement("div"); note.className = "method-action-row-meta";
        note.textContent = item.resolution_note || (item.status === "pending_external" ? "等待可靠外部资料或新增数据工具，不会自动标记为解决。" : "后台会依据任务类型调用确定性数据工具。 ");
        lifecycle.append(source, time, note); card.appendChild(lifecycle);
        container.appendChild(card);
      }
      if (!container.children.length) container.innerHTML = '<div class="empty">新的对话证据缺口会在这里形成后台补证任务。</div>';
    }

    function renderConversationQuality(data) {
      const summary = data.summary || {};
      const statuses = summary.run_statuses || {};
      const latency = data.latency || {}, p50 = latency.p50_seconds || {};
      const latencyText = latency.sample_size
        ? ` · 分段P50：证据 ${p50.routing_and_evidence_seconds ?? "—"}s / 首片段 ${p50.first_token_seconds ?? "—"}s / 首个安全可见 ${p50.first_visible_seconds ?? "—"}s / 模型 ${p50.model_seconds ?? "—"}s / 守卫 ${p50.guard_seconds ?? "—"}s / 总计 ${p50.request_total_seconds ?? "—"}s`
        : "";
      const excludedText = summary.excluded_evaluation_conversations
        ? ` · 已隔离 ${summary.excluded_evaluation_conversations} 个开发验收对话 / ${summary.excluded_evaluation_runs || 0} 个 Run`
        : "";
      const scoreText = summary.quality_score_status === "insufficient_sample"
        ? "普通用户样本不足，暂不评分"
        : `质量分 ${summary.quality_score ?? "—"}`;
      const evaluation = data.evaluation || {}, evaluationSummary = evaluation.summary || {};
      const evaluationText = state.evaluationMode && evaluationSummary.runs
        ? ` · 验收审计：${evaluationSummary.runs} 个 Run / ${evaluationSummary.repaired_runs || 0} 个修复 / ${evaluationSummary.verbose_answers || 0} 个冗长 / ${evaluationSummary.internal_language_answers || 0} 个内部措辞`
        : "";
      $("conversationQualitySummary").textContent = `${scoreText} · ${summary.conversations || 0} 个普通对话 · ${summary.messages || 0} 条消息 · ${summary.runs || 0} 个 Run · ${summary.issues || 0} 类待改善问题 · ${summary.open_data_needs || 0} 项开放数据需求${excludedText}${evaluationText}${latencyText}`;
      const container = $("conversationQualityIssues"); container.innerHTML = "";
      for (const item of (data.issues || []).slice(0, 8)) {
        const card = document.createElement("div"); card.className = "method-action-item";
        const head = document.createElement("div"); head.className = "method-action-head";
        const identity = document.createElement("div");
        const title = document.createElement("div"); title.className = "method-item-title"; title.textContent = item.title;
        const detail = document.createElement("div"); detail.className = "method-item-meta"; detail.textContent = item.detail;
        identity.append(title, detail);
        const state = document.createElement("span"); state.className = `method-action-state ${item.severity === "critical" ? "risk_review" : "pending_review"}`; state.textContent = item.severity === "critical" ? "优先修复" : "继续改善";
        head.append(identity, state); card.appendChild(head);
        const next = document.createElement("div"); next.className = "method-action-row";
        const nextTitle = document.createElement("div"); nextTitle.className = "method-action-row-title"; nextTitle.textContent = "下一步";
        const nextCopy = document.createElement("div"); nextCopy.className = "method-action-row-meta"; nextCopy.textContent = item.next_step;
        next.append(nextTitle, nextCopy); card.appendChild(next);
        container.appendChild(card);
      }
      if (state.evaluationMode) for (const item of (evaluation.issues || []).slice(0, 8)) {
        const card = document.createElement("div"); card.className = "method-action-item";
        const head = document.createElement("div"); head.className = "method-action-head";
        const identity = document.createElement("div");
        const title = document.createElement("div"); title.className = "method-item-title"; title.textContent = `验收样本 · ${item.title}`;
        const detail = document.createElement("div"); detail.className = "method-item-meta"; detail.textContent = item.detail;
        identity.append(title, detail);
        const stateTag = document.createElement("span"); stateTag.className = `method-action-state ${item.severity === "critical" ? "risk_review" : "pending_review"}`; stateTag.textContent = item.severity === "critical" ? "优先修复" : "继续改善";
        head.append(identity, stateTag); card.appendChild(head);
        const next = document.createElement("div"); next.className = "method-action-row";
        const nextTitle = document.createElement("div"); nextTitle.className = "method-action-row-title"; nextTitle.textContent = "下一步";
        const nextCopy = document.createElement("div"); nextCopy.className = "method-action-row-meta"; nextCopy.textContent = item.next_step;
        next.append(nextTitle, nextCopy); card.appendChild(next); container.appendChild(card);
      }
      for (const item of (data.data_needs || []).filter(item => item.status === "open").slice(0, 6)) {
        const card = document.createElement("div"); card.className = "method-action-item";
        const title = document.createElement("div"); title.className = "method-item-title"; title.textContent = `数据需求 · ${item.label}`;
        const detail = document.createElement("div"); detail.className = "method-item-meta"; detail.textContent = `历史回答提及 ${item.mentions || 0} 次；需要可靠来源、字段口径和验收条件。`;
        card.append(title, detail); container.appendChild(card);
      }
      if (!container.children.length) container.innerHTML = `<div class="empty">当前没有检测到明确问题。Run 状态：completed ${statuses.completed || 0}，guarded ${statuses.guarded || 0}，degraded ${statuses.degraded || 0}。</div>`;
    }

    async function loadResearchMethod() {
      try {
        const [method, actions, tasks, quality, outcomes] = await Promise.all([
          api("/research-method?limit=4"),
          api("/me/research-actions"),
          api("/me/evidence-tasks?limit=50"),
          api("/me/conversation-quality"),
          api("/me/research-outcomes?limit=120")
        ]);
        renderResearchOutcomes(outcomes);
        renderResearchMethod(method);
        renderResearchActions(actions);
        renderEvidenceTasks(tasks);
        renderConversationQuality(quality);
        state.reviewQuality = quality;
        void loadRunReviews().catch(() => { $("reviewRunSummary").textContent = "暂时无法读取回答记录"; });
        activateReviewTab(state.reviewTab);
      }
      catch {
        $("methodBoundary").textContent = "复盘内容正在整理；这不会影响正常研究对话。";
        $("reviewRunSummary").textContent = "暂时无法读取真实 Run";
        $("reviewOutcomeList").innerHTML = '<div class="empty">研究结果暂时无法读取，请稍后重试。</div>';
      }
    }

    function connectServerEvents() {
      const stream = new EventSource("/events");
      stream.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === "article_published" && insightsVisible()) loadArticles();
          if (data.type === "market_updated" && insightsVisible()) {
            loadLiveMarkets();
            loadMarketDashboard();
            loadSectors();
          }
          if (data.type === "research_reports_updated") {
            loadWatchlist();
            if (insightsVisible()) loadArticles();
            if (state.workspacePage === "review") loadResearchMethod();
          }
          if (data.type === "evidence_tasks_updated" && state.workspacePage === "review") loadResearchMethod();
          if (data.type === "agent_progress" && data.request_id) {
            const request = state.pendingAgentRequests.get(data.request_id);
            const pending = request?.node || request;
            if (pending?.isConnected && data.label && !request?.draft) pending.textContent = data.label;
          }
          if (data.type === "data_health_updated") {
            state.health = {...(state.health || {}), data_health: data.data_health};
            renderSystemHealth(data.data_health);
          }
        } catch { /* heartbeat or malformed events are safely ignored */ }
      };
      stream.onerror = () => {
        $("systemStatus").className = "status-pill attention";
        $("systemStatus").textContent = "正在重新连接";
      };
      stream.onopen = () => {
        renderSystemHealth(state.health?.data_health || {status: "initializing", user_label: "数据正在同步"});
      };
    }

    async function refineChat(preview, node, metadata) {
      if (!preview?.run_id || !preview?.assistant_message_id || !preview?.conversation_id || !node) return;
      const status = document.createElement("div");
      status.className = "refine-status";
      status.textContent = "AI 正在补充深度解读…";
      node.appendChild(status);
      try {
        const refined = await api("/me/chat/refine", {
          method: "POST",
          body: JSON.stringify({
            preview_run_id: preview.run_id,
            conversation_id: preview.conversation_id,
            assistant_message_id: preview.assistant_message_id,
            model_tier: $("modelTier").value
          })
        });
        if (refined.status === "completed" || refined.status === "already_refined") {
          finalizeStreamingMessage(node, refined.answer, metadata, {
            draft: preview.answer || "",
            mode: "refine"
          });
          renderAgentResearchContext(metadata, state.agentContextQuestion);
          if (refined.deep_stock_session) state.deepStock = refined.deep_stock_session;
        } else {
          status.remove();
        }
        await loadConversations(false);
      } catch {
        status.remove();
      }
    }

    async function sendChat(message) {
      const attachedImage = state.pendingImage;
      const question = message.trim() || (attachedImage ? "请分析这张图片，并说明可验证的观察和不能确认的内容。" : "");
      if (!question) return;
      state.agentContextQuestion = question;
      state.agentResearchRunning = true;
      setAgentProcessExpanded(true);
      renderAgentResearchContext(state.agentContextMetadata, question);
      const wantsHermes = !attachedImage && Boolean($("useHermes").checked) && Boolean(state.health?.hermes_enabled);
      const directHermes = wantsHermes && state.workspacePage === "agent";
      const requestId = directHermes
        ? (globalThis.crypto?.randomUUID?.() || `chat-${Date.now()}-${Math.random().toString(16).slice(2)}`)
        : null;
      addMessage("user", attachedImage ? `已附加图片：${attachedImage.original_name}\n${question}` : question);
      const pending = addMessage(
        "agent",
        directHermes
          ? "AI 正在检索实时证据、资料库和金融研究工具，并针对这个问题生成回答…"
          : "正在读取数据并构建证据…",
        true
      );
      let privateStream = null;
      $("sendButton").disabled = true;
      $("attachImage").disabled = true;
      try {
        if (requestId) {
          privateStream = connectPrivateAgentStream(requestId, pending);
          await privateStream.ready;
        }
        const data = await api("/me/chat", {
          method: "POST",
          body: JSON.stringify({
            message: question,
            model_tier: attachedImage ? "vision" : $("modelTier").value,
            execute_agent: attachedImage ? true : directHermes,
            prefer_precomputed: wantsHermes && !directHermes,
            image_id: attachedImage?.id || null,
            conversation_id: state.conversationId,
            request_id: requestId,
            quality_scope: state.evaluationMode ? "evaluation" : "user"
          })
        });
        state.conversationId = data.conversation_id || state.conversationId;
        $("conversationTitle").textContent = data.conversation_title || $("conversationTitle").textContent;
        if (attachedImage) clearImageAttachment();
        const responseMetadata = {
          knowledgeSources: data.knowledge?.items || [],
          marketSources: data.evidence?.market_drivers?.items || [],
          evidenceSources: data.evidence_sources || [],
          intent: data.intent,
          status: data.status,
          symbol: inferDiagnosisSymbol(data, question),
          marketKey: inferDiagnosisMarketKey(data, question)
        };
        state.agentContextMetadata = responseMetadata;
        renderAgentResearchContext(responseMetadata, question);
        const streamDraft = privateStream?.context?.draft || "";
        let responseNode = pending;
        if (data.intent === "memory_candidate" && data.evidence?.memory) {
          pending.remove();
          responseNode = null;
          renderMemoryCandidate(data.evidence.memory, data.answer || "");
        } else if (data.answer) {
          responseNode = finalizeStreamingMessage(pending, data.answer, responseMetadata, {draft: streamDraft});
        }
        else if (data.article) {
          responseNode = finalizeStreamingMessage(
            pending,
            `${data.article.title}\n\n${data.article.summary || data.article.body}\n\n发布状态：${data.decision}`,
            responseMetadata,
            {draft: streamDraft}
          );
          await loadArticles();
        } else {
          responseNode = finalizeStreamingMessage(pending, data.reason || "任务已完成。", responseMetadata, {draft: streamDraft});
        }
        if (["watchlist_update", "watchlist_brief"].includes(data.intent)) await loadWatchlist();
        if (["research_priority", "research_outcome"].includes(data.intent)) await loadKnowledge();
        if (data.deep_stock_session) state.deepStock = data.deep_stock_session;
        await maybeUpdateDiagnosis(data, question);
        await loadConversations(false);
        if (
          wantsHermes &&
          data.status === "preview" &&
          ["market_brief", "stock_screen", "stock_research", "earnings_quality", "financial_drivers", "business_structure", "shareholder_structure", "analyst_expectations", "event_timeline", "research_tracking", "research_priority", "research_actions", "research_outcome", "watchlist_brief", "general_research"].includes(data.intent)
        ) {
          void refineChat(data, responseNode, responseMetadata);
        }
      } catch (error) {
        finalizeStreamingMessage(
          pending,
          "这次研究暂未完成，我会保留当前可用数据，请稍后重试。",
          null,
          {draft: privateStream?.context?.draft || ""}
        );
      } finally {
        if (requestId) {
          privateStream?.source?.close();
          state.pendingAgentRequests.delete(requestId);
        }
        state.agentResearchRunning = false;
        setAgentProcessExpanded(false);
        renderAgentResearchContext(state.agentContextMetadata, state.agentContextQuestion);
        $("sendButton").disabled = false;
        $("attachImage").disabled = state.imageUploading || !state.health?.hermes_enabled;
      }
    }

    $("chatForm").addEventListener("submit", async (event) => {
      event.preventDefault();
      const input = $("chatInput"); const message = input.value; input.value = "";
      await sendChat(message);
    });
    $("chatInput").addEventListener("keydown", event => {
      if (
        event.key === "Enter" &&
        !event.shiftKey &&
        !event.isComposing &&
        event.keyCode !== 229
      ) {
        event.preventDefault();
        if (!$("sendButton").disabled) $("chatForm").requestSubmit();
      }
    });
    document.querySelectorAll("[data-message]").forEach((button) => button.addEventListener("click", async () => {
      activateWorkspace("agent");
      await sendChat(button.dataset.message);
    }));
    $("toggleQuickActions").addEventListener("click", () => {
      const container = $("quickActions");
      const expanded = !container.classList.contains("expanded");
      container.classList.toggle("expanded", expanded);
      document.querySelectorAll("[data-quick-secondary]").forEach(item => { item.hidden = !expanded; });
      $("toggleQuickActions").setAttribute("aria-expanded", expanded ? "true" : "false");
      $("toggleQuickActions").textContent = expanded ? "收起能力" : "更多能力 · 9";
    });
    document.querySelectorAll("[data-insight-filter]").forEach(button => button.addEventListener("click", () => {
      state.insightFilter = button.dataset.insightFilter || "all";
      for (const item of document.querySelectorAll("[data-insight-filter]")) {
        item.classList.toggle("active", item === button);
      }
      renderArticles();
    }));
    $("insightAskForm").addEventListener("submit", async event => {
      event.preventDefault();
      const question = $("insightQuestion").value.trim();
      if (!question) return;
      $("insightQuestion").value = "";
      $("insightAskButton").disabled = true;
      activateWorkspace("agent");
      startNewConversation(false);
      try { await sendChat(question); }
      finally { $("insightAskButton").disabled = false; }
    });
    $("earningsQualityAction").addEventListener("click", async () => {
      const symbol = state.diagnosisSymbol || "000063.SZ";
      await sendChat(`${symbol}财报质量怎么样？`);
    });
    $("financialDriversAction").addEventListener("click", async () => {
      const symbol = state.diagnosisSymbol || "000063.SZ";
      await sendChat(`${symbol}利润为什么下降？请拆解利润、费用率、营运资金和现金流。`);
    });
    $("shareholderAction").addEventListener("click", async () => {
      const symbol = state.diagnosisSymbol || "000063.SZ";
      await sendChat(`${symbol}股东户数怎么变了？十大股东结构有什么值得继续核对的线索？`);
    });
    $("analystExpectationsAction").addEventListener("click", async () => {
      const symbol = state.diagnosisSymbol || "000063.SZ";
      await sendChat(`${symbol}一致预期怎么样？最近是否上修，最新研报有哪些？`);
    });
    $("eventTimelineAction").addEventListener("click", async () => {
      const symbol = state.diagnosisSymbol || "000063.SZ";
      await sendChat(`${symbol}最近有什么重要事件？请区分官方公告、媒体线索、可能的催化和风险事件。`);
    });
    $("refreshLive").addEventListener("click", () => { void Promise.all([loadLiveMarkets(), loadMarketDashboard(), loadSectors()]); });
    $("modelTier").addEventListener("change", updateAgentMode);
    $("useHermes").addEventListener("change", updateAgentMode);
    $("attachImage").addEventListener("click", () => $("imageInput").click());
    $("imageInput").addEventListener("change", async event => {
      const file = event.target.files?.[0];
      await uploadSelectedImage(file);
    });
    $("uploadKnowledge").addEventListener("click", () => $("knowledgeInput").click());
    $("knowledgeInput").addEventListener("change", async event => {
      await uploadKnowledgeFile(event.target.files?.[0]);
    });
    $("removeImage").addEventListener("click", clearImageAttachment);
    $("startDeepStock").addEventListener("click", startDeepStockSession);
    $("deepStockAgent").addEventListener("click", () => { void continueDeepStockConversation(); });
    $("deepStockSymbol").addEventListener("change", () => {
      const symbol = $("deepStockSymbol").value;
      const session = state.deepStockSessions.find(item => item.symbol === symbol) || null;
      activateStockSpaceTab("overview");
      renderDeepStock(session);
      void loadDeepStockOverview(symbol);
    });
    document.querySelectorAll("[data-stock-space-tab]").forEach(button => button.addEventListener("click", () => {
      activateStockSpaceTab(button.dataset.stockSpaceTab || "overview");
    }));
    $("addWatchlist").addEventListener("click", () => {
      resetWatchlistForm();
      $("watchlistAddForm").hidden = false;
      $("watchlistSymbol").focus();
    });
    $("cancelWatchlistAdd").addEventListener("click", resetWatchlistForm);
    $("watchlistAddForm").addEventListener("submit", async event => {
      event.preventDefault();
      const submit = event.submitter;
      if (submit) submit.disabled = true;
      try {
        const saved = await api("/me/watchlist", {
          method: "POST",
          body: JSON.stringify({
            symbol: $("watchlistSymbol").value.trim(),
            name: $("watchlistName").value.trim() || null,
            market: $("watchlistMarket").value,
            thesis: $("watchlistThesis").value.trim() || null
          })
        });
        state.selectedWatchlistSymbol = saved.symbol;
        resetWatchlistForm();
        await loadWatchlist();
        const item = state.watchlist.find(entry => entry.symbol === saved.symbol);
        if (item) await loadWatchlistDetail(item, "intraday");
      } catch {
        $("watchlistSource").textContent = "未能添加这只股票，请检查代码后重试。";
      } finally { if (submit) submit.disabled = false; }
    });
    document.querySelectorAll("[data-watchlist-filter]").forEach(button => button.addEventListener("click", () => {
      state.watchlistFilter = button.dataset.watchlistFilter || "all";
      document.querySelectorAll("[data-watchlist-filter]").forEach(item => item.classList.toggle("active", item === button));
      void loadWatchlist();
    }));
    $("globalSearch").addEventListener("keydown", event => {
      if (event.key !== "Enter" || event.isComposing) return;
      event.preventDefault();
      const query = event.currentTarget.value.trim();
      if (!query) return;
      const folded = query.toLowerCase().replace(/[.\s]/g, "");
      const matched = state.watchlist.find(item =>
        String(item.name || "").toLowerCase().includes(query.toLowerCase()) ||
        String(item.symbol || "").toLowerCase().replace(/[.\s]/g, "").includes(folded)
      );
      const symbol = matched?.symbol || inferDiagnosisSymbol({}, query);
      if (symbol) void openDeepStockSymbol(symbol);
    });
    $("knowledgeSearch").addEventListener("input", event => {
      state.knowledgeQuery = event.currentTarget.value;
      renderKnowledge();
    });
    $("knowledgeScopeFilter").addEventListener("change", event => {
      state.knowledgeScope = event.currentTarget.value;
      renderKnowledge();
    });
    $("knowledgeTypeFilter").addEventListener("change", event => {
      state.knowledgeType = event.currentTarget.value;
      renderKnowledge();
    });
    $("readerClose").addEventListener("click", closeReader);
    $("readerDismiss").addEventListener("click", closeReader);
    $("readerContinue").addEventListener("click", () => {
      const context = state.readerContext;
      closeReader();
      prepareAgentQuestion(`请结合当前资料继续研究“${context?.title || "这项内容"}”，说明它与当前判断的关系、反方证据和下一步需要核验什么。`);
    });
    $("readerBackdrop").addEventListener("click", event => {
      if (event.target === $("readerBackdrop")) closeReader();
    });
    document.addEventListener("keydown", event => {
      if (event.key === "Escape") closeReader();
    });
    $("newConversation").addEventListener("click", () => startNewConversation(true));
    $("agentHistoryNew").addEventListener("click", () => startNewConversation(true));
    $("stockScreenerForm").addEventListener("submit", event => {
      event.preventDefault();
      void loadStockScreener();
    });
    document.querySelectorAll("[data-li-zong-filter]").forEach(button => button.addEventListener("click", () => {
      state.liZongFilter = button.dataset.liZongFilter;
      if (state.liZongStrategy) renderLiZongStrategy(state.liZongStrategy);
      else void loadLiZongStrategy();
    }));
    $("conversationSwitcher").addEventListener("change", async event => {
      if (event.target.value) await openConversation(event.target.value);
      else startNewConversation(true);
    });
    document.querySelectorAll(".nav-item[data-page]").forEach(button => button.addEventListener("click", () => {
      activateWorkspace(button.dataset.page);
    }));
    document.querySelectorAll(".sidebar-resource-btn[data-page]").forEach(button => button.addEventListener("click", () => {
      activateWorkspace(button.dataset.page);
    }));
    document.querySelectorAll("[data-open-page]").forEach(button => button.addEventListener("click", () => {
      activateWorkspace(button.dataset.openPage);
    }));
    document.querySelectorAll("[data-home-focus]").forEach(button => button.addEventListener("click", () => {
      const target = button.dataset.homeFocus;
      if (target === "markets") {
        void loadLiveMarkets();
        $("liveSection").scrollIntoView({behavior: "smooth", block: "start"});
      } else if (target === "ashare") {
        $("marketDashboard").scrollIntoView({behavior: "smooth", block: "start"});
      } else if (target === "watchlist") {
        activateWorkspace("watchlist");
      }
    }));
    $("agentProcessToggle").addEventListener("click", () => setAgentProcessExpanded(!state.agentProcessExpanded));
    $("agentContextToggle").addEventListener("click", () => setAgentContextCollapsed(!state.agentContextCollapsed));
    document.querySelectorAll("[data-agent-context-tab]").forEach(button => button.addEventListener("click", () => {
      const key = button.dataset.agentContextTab;
      document.querySelectorAll("[data-agent-context-tab]").forEach(item => {
        const active = item === button;
        item.classList.toggle("active", active);
        item.setAttribute("aria-selected", active ? "true" : "false");
      });
      $("agentContextMarket").hidden = key !== "market";
      $("agentContextEvidence").hidden = key !== "evidence";
      $("agentContextCapabilities").hidden = key !== "capabilities";
    }));
    document.querySelectorAll("[data-review-tab]").forEach(button => button.addEventListener("click", () => {
      activateReviewTab(button.dataset.reviewTab);
    }));
    [$("reviewRunStatus"), $("reviewRunRepair"), $("reviewRunDays")].forEach(control => {
      control.addEventListener("change", () => { void refreshRunReviews(); });
    });
    $("reviewRunSearch").addEventListener("input", () => {
      window.clearTimeout(state.reviewRunSearchTimer);
      state.reviewRunSearchTimer = window.setTimeout(() => { void refreshRunReviews(); }, 260);
    });

    (async function boot() {
      try {
        activateWorkspace("insights");
        // 公共行情无需会话，与登录并行拉取（activateWorkspace 内的补充刷新会被在途去重合并）。
        const publicLoads = Promise.allSettled([loadMarketDashboard(), loadSectors(), loadLiveMarkets()]);
        await Promise.all([loadHealth(), ensureUser()]);
        await Promise.all([loadWatchlist(), loadArticles(), loadKnowledge(), loadDeepStock()]);
        await loadConversations(true, false);
        if (!state.conversationId) {
          startNewConversation(false);
          await loadMemoryCandidates();
        }
        connectServerEvents();
        await publicLoads;
      } catch (error) {
        $("systemStatus").textContent = "正在重新连接";
        addMessage("agent", "页面正在重新连接数据，请稍后刷新。");
      }
    })();
    setInterval(() => {
      if (!insightsVisible()) return;
      liveRefreshRemaining -= 1;
      if (liveRefreshRemaining <= 0) loadLiveMarkets();
      $("liveCountdown").textContent = `${Math.max(0, liveRefreshRemaining)} 秒后刷新`;
    }, 1000);
    setInterval(() => { if (insightsVisible()) loadArticles(); }, 60000);
    setInterval(() => { if (insightsVisible()) { loadMarketDashboard(); loadSectors(); } }, 60000);

    // 窗口尺寸变化后按缓存的数据重绘可见 canvas（防抖 140ms）。
    let canvasResizeTimer = null;
    window.addEventListener("resize", () => {
      window.clearTimeout(canvasResizeTimer);
      canvasResizeTimer = window.setTimeout(() => {
        document.querySelectorAll("canvas").forEach(canvas => {
          if (!canvas.getClientRects().length) return;
          if (canvas._sparkPoints) drawSparkline(canvas, canvas._sparkPoints, canvas._sparkChange || 0);
          else if (canvas._candlePoints) drawCandles(canvas, canvas._candlePoints);
        });
      }, 140);
    });
