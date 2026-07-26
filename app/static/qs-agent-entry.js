function currentWelcomeMessage() {
      return welcomeMessage;
    }

    const marketDiagnosisPrompt = "请诊断当前A股大盘。必须基于最新可用且尽量属于同一交易日的主要指数、全市场涨跌分布、成交额、市场广度和行业结构，说明当前市场状态、核心驱动、反方证据、失效条件与数据时间；如数据日期不一致要明确指出。不要预测下一交易日方向，不要给出买卖建议。";

    function syncAgentEntryHubVisibility() {
      const hub = $("agentEntryHub");
      if (!hub) return;
      const hasUserMessage = Boolean($("messages")?.querySelector(".message.user"));
      hub.hidden = state.workspacePage !== "agent"
        || stockAgentIsEmbedded()
        || state.agentResearchRunning
        || hasUserMessage;
      syncAgentResumeResearch();
    }

    function latestConversationItem() {
      return state.conversations.reduce((latest, item) => {
        if (Number(item?.message_count || 0) <= 0 || item?.quality_scope === "evaluation") return latest;
        if (!latest) return item;
        const itemTime = new Date(item.updated_at || 0).getTime() || 0;
        const latestTime = new Date(latest.updated_at || 0).getTime() || 0;
        return itemTime > latestTime ? item : latest;
      }, null);
    }

    function syncAgentResumeResearch() {
      const host = $("agentResumeResearch");
      const button = $("agentResumeOpen");
      if (!host || !button) return;
      const item = latestConversationItem();
      host.hidden = !item;
      button.dataset.conversationId = item?.id || "";
      if (!item) return;
      const title = item.title || "未命名研究对话";
      $("agentResumeTitle").textContent = title;
      $("agentResumeMeta").textContent = `${conversationScopeLabel(item)} · ${Number(item.message_count || 0)} 条消息 · 更新 ${readableTime(item.updated_at)}`;
      button.setAttribute("aria-label", `继续上次研究：${title}`);
    }

    function normalizedStockLookup(value) {
      return String(value || "")
        .normalize("NFKC")
        .trim()
        .toUpperCase()
        .replace(/\s+/g, "")
        .replace(/\.SH$/, ".SS");
    }

    function stockDiagnosisCandidates(data) {
      const bySymbol = new Map();
      for (const group of (data?.groups || [])) {
        if (!["stocks", "workspaces"].includes(group.key)) continue;
        for (const item of (group.items || [])) {
          const symbol = normalizedStockLookup(item.symbol);
          if (!symbol) continue;
          const existing = bySymbol.get(symbol);
          if (!existing || item.type === "stock") {
            bySymbol.set(symbol, {
              symbol,
              name: String(item.title || existing?.name || symbol).trim() || symbol
            });
          }
        }
      }
      return [...bySymbol.values()];
    }

    async function resolveStockDiagnosisTarget(query) {
      const raw = String(query || "").normalize("NFKC").trim();
      if (!raw) throw new Error("请输入股票名称或代码。");
      const data = await api(`/v1/search?q=${encodeURIComponent(raw)}&limit=8`);
      const candidates = stockDiagnosisCandidates(data);
      if (!candidates.length) {
        throw new Error(`没有找到“${raw}”对应的股票，请输入完整名称或 6 位代码。`);
      }
      const key = normalizedStockLookup(raw);
      const exact = candidates.filter(item => {
        const symbol = normalizedStockLookup(item.symbol);
        return key === symbol
          || key === symbol.split(".", 1)[0]
          || key === normalizedStockLookup(item.name);
      });
      if (exact.length === 1) return exact[0];
      if (!exact.length && candidates.length === 1) return candidates[0];
      const examples = (exact.length ? exact : candidates)
        .slice(0, 3)
        .map(item => `${item.name}（${item.symbol}）`)
        .join("、");
      throw new Error(`找到多个可能结果：${examples}。请输入完整名称或代码。`);
    }

    async function runMarketDiagnosisEntry() {
      const button = $("agentMarketDiagnosis");
      const original = button.textContent;
      button.disabled = true;
      button.textContent = "正在建立实时诊断…";
      try {
        startNewConversation(true, "push");
        await sendChat(marketDiagnosisPrompt);
      } finally {
        button.disabled = false;
        button.textContent = original;
      }
    }

    async function runStockDiagnosisEntry(query) {
      const button = $("agentStockDiagnosis");
      const status = $("agentStockDiagnosisStatus");
      const original = button.textContent;
      button.disabled = true;
      button.textContent = "识别中…";
      status.className = "agent-entry-status";
      status.textContent = "正在从稳定股票范围和你的研究空间中识别标的…";
      try {
        const target = await resolveStockDiagnosisTarget(query);
        status.textContent = `已识别 ${target.name}（${target.symbol}），正在进入唯一绑定研究对话…`;
        const session = await api("/me/deep-stock", {
          method: "POST",
          body: JSON.stringify({symbol: target.symbol})
        });
        state.deepStock = session;
        await loadConversations(false);
        await loadDeepStock({force: true});
        const question = `请诊断${target.name}（${target.symbol}）当前研究状态。基于最新可验证的行情与技术结构、经营和财务质量、行业相对位置、估值口径、公告与事件，给出证据链、反方证据、原判断失效条件和下一条最值得核验的证据；明确行情数据时间和财务报告期。不要给目标价或买卖建议。`;
        await continueDeepStockConversation(question, session);
        $("chatInput").value = "";
        const completed = await sendChat(question);
        status.textContent = completed
          ? `已在 ${target.name} 的长期研究空间完成本轮即时诊断。`
          : `已进入 ${target.name} 的长期研究空间；本轮即时诊断未完整完成，可在对话中重试。`;
      } catch (error) {
        status.className = "agent-entry-status error";
        status.textContent = error.message || "这只股票暂时无法诊断，请稍后重试。";
      } finally {
        button.disabled = false;
        button.textContent = original;
      }
    }

    function agentIntentLabel(intent) {
      return {
        market_brief: "大盘诊断",
        stock_screen: "选股研究",
        stock_research: "个股研究",
        stock_comparison: "多股比较",
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
        $("agentContextToggle").textContent = state.agentContextCollapsed ? "展开研究依据" : "收起研究依据";
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
