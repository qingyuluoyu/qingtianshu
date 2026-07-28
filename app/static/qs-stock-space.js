function renderStockSpaceTasks(symbol, session = null, workspace = null, actionPlans = null) {
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
      const allUserTasks = workspace?.observation_tasks?.items || [];
      const savedActionRefs = new Set(allUserTasks.filter(task => task.source_type === "research_action" && task.source_ref_id).map(task => String(task.source_ref_id)));
      const actions = (workspace?.pending_actions?.length
        ? [...workspace.pending_actions]
        : [...coverageActions, ...(actionItem?.actions || [])]
      ).filter(action => action.source !== "observation_task" && !savedActionRefs.has(String(action.id || `${action.title}:${action.next_step}`).slice(0, 160))).sort((a, b) => {
        const rank = {triggered: 3, pending_data: 2, watching: 1};
        return (rank[b.status] || 0) - (rank[a.status] || 0);
      });
      const userTasks = [
        ...allUserTasks.filter(task => !task.terminal),
        ...allUserTasks.filter(task => task.terminal).slice(0, 3)
      ];
      container.innerHTML = "";
      const head = document.createElement("div"); head.className = "stock-space-section-head";
      const copyWrap = document.createElement("div");
      const title = document.createElement("div"); title.className = "stock-space-section-title"; title.textContent = "任务与操作";
      const copy = document.createElement("div"); copy.className = "stock-space-section-copy"; copy.textContent = "我的观察任务会保存状态、结果和历史；系统建议只有在你确认后才成为个人任务。";
      copyWrap.append(title, copy);
      const taskFocus = userTasks.find(task => !task.terminal)?.description || actions[0]?.next_step || session?.next_question || "核验当前最重要的反方证据与失效条件";
      const agentTaskPrompt = `请立即核验 ${symbol} 当前最优先的研究问题：${taskFocus}\n\n必须使用当前可用的实时数据、资料库和证据链，区分已确认事实、推断与信息缺口，明确反方证据、数据时间和失效条件。完成即时核验后，生成观察任务草稿供我确认。正式任务必须等我点击确认后才写入；不要给出买卖建议。`;
      const ask = document.createElement("button"); ask.type = "button"; ask.className = "btn primary"; ask.textContent = "让 Agent 帮我处理";
      ask.addEventListener("click", () => { void continueDeepStockConversation(agentTaskPrompt); });
      head.append(copyWrap, ask); container.appendChild(head);
      const plans = actionPlans || state.stockActionPlans[symbol] || [];
      const positionWorkspace = renderPositionWorkspace(symbol, workspace);
      container.append(renderActionPlanWorkspace(symbol, plans, positionWorkspace), positionWorkspace);
      const grid = document.createElement("div"); grid.className = "stock-task-grid";
      if (userTasks.length) {
        const label = document.createElement("div"); label.className = "stock-task-section-label"; label.textContent = `我的观察任务 · ${workspace?.observation_tasks?.summary?.active || 0} 项进行中`; grid.appendChild(label);
        for (const task of userTasks) {
          const card = document.createElement("article"); card.className = "stock-task-card user-task";
          const status = document.createElement("span"); status.className = "stock-task-status"; status.textContent = task.status_label || "观察任务";
          const cardTitle = document.createElement("div"); cardTitle.className = "stock-task-title"; cardTitle.textContent = task.title || "用户观察任务";
          const cardCopy = document.createElement("div"); cardCopy.className = "stock-task-copy"; cardCopy.textContent = task.description || "继续核验相关事实。";
          const evidenceCopy = document.createElement("div"); evidenceCopy.className = "stock-task-evidence"; evidenceCopy.textContent = [task.due_at ? `截止 ${readableTime(task.due_at)}` : "未设置截止时间", `版本 ${task.version}`, task.source_type === "research_action" ? "由系统建议保存" : "由用户创建"].join(" · ");
          const taskActions = document.createElement("div"); taskActions.className = "stock-task-actions";
          const addTransition = (label, nextStatus, primary = false) => { const button = document.createElement("button"); button.type = "button"; button.className = `btn${primary ? " primary" : ""}`; button.textContent = label; button.addEventListener("click", () => { if (nextStatus === "completed") showObservationTaskCompletion(card, symbol, task); else void transitionObservationTask(symbol, task, nextStatus).catch(error => openReader("任务状态未更新", error.message || "请稍后重试。", task.status_label)); }); taskActions.appendChild(button); };
          if (task.status === "pending") { addTransition("开始处理", "in_progress", true); addTransition("等待数据", "waiting_data"); }
          if (task.status === "in_progress") addTransition("等待数据", "waiting_data");
          if (task.status === "waiting_data") addTransition("继续处理", "in_progress", true);
          if (!task.terminal) { addTransition("完成", "completed", task.status !== "pending"); addTransition("忽略", "ignored"); addTransition("取消任务", "cancelled"); }
          else addTransition("重开", "pending", true);
          if (task.can_edit) { const edit = document.createElement("button"); edit.type = "button"; edit.className = "btn"; edit.textContent = "编辑"; edit.addEventListener("click", () => showObservationTaskEditor(card, symbol, task)); taskActions.appendChild(edit); }
          const detail = document.createElement("button"); detail.type = "button"; detail.className = "btn"; detail.textContent = "查看历史"; detail.addEventListener("click", () => { void openObservationTaskHistory(task); }); taskActions.appendChild(detail);
          card.append(status, cardTitle, cardCopy, evidenceCopy, taskActions); grid.appendChild(card);
        }
      }
      if (actions.length) {
        const label = document.createElement("div"); label.className = "stock-task-section-label"; label.textContent = "系统建议的下一步 · 保存后才进入我的任务"; grid.appendChild(label);
        for (const action of actions) {
          const card = document.createElement("article"); card.className = "stock-task-card";
          const status = document.createElement("span"); status.className = "stock-task-status";
          status.textContent = {triggered: "需要复核", pending_data: "等待证据", watching: "持续观察"}[action.status] || "研究建议";
          const cardTitle = document.createElement("div"); cardTitle.className = "stock-task-title"; cardTitle.textContent = action.title || "继续核验研究证据";
          const cardCopy = document.createElement("div"); cardCopy.className = "stock-task-copy"; cardCopy.textContent = action.next_step || action.current_evidence || "继续按当前研究条件观察。";
          const evidenceCopy = document.createElement("div"); evidenceCopy.className = "stock-task-evidence"; evidenceCopy.textContent = action.current_evidence || "当前证据待补充。";
          const actionButtons = document.createElement("div"); actionButtons.className = "stock-task-actions";
          const save = document.createElement("button"); save.type = "button"; save.className = "btn primary"; save.textContent = "保存为我的任务"; save.addEventListener("click", () => { void saveObservationTaskFromAction(symbol, action, save); });
          const detail = document.createElement("button"); detail.type = "button"; detail.className = "btn"; detail.textContent = "查看任务依据"; detail.addEventListener("click", () => openReader(action.title || "研究任务", researchActionDetail(action), `${status.textContent} · ${action.severity || "常规"}`));
          actionButtons.append(save, detail); card.append(status, cardTitle, cardCopy, evidenceCopy, actionButtons); grid.appendChild(card);
        }
      }
      if (!userTasks.length && !actions.length) {
        const card = document.createElement("article"); card.className = "stock-task-card";
        const status = document.createElement("span"); status.className = "stock-task-status"; status.textContent = "下一步";
        const cardTitle = document.createElement("div"); cardTitle.className = "stock-task-title"; cardTitle.textContent = session?.current_stage?.label || "建立下一项观察条件";
        const cardCopy = document.createElement("div"); cardCopy.className = "stock-task-copy"; cardCopy.textContent = session?.next_question || "当前没有需要优先处理的新任务，可以继续核验反方证据和失效条件。";
        card.append(status, cardTitle, cardCopy); grid.appendChild(card);
      }
      container.appendChild(grid);
    }

    function renderStockSpaceHistory(session, workspace = null, tradeReviews = null, symbol = null) {
      const container = $("deepStockHistory");
      if (!container) return;
      container.innerHTML = "";
      const head = document.createElement("div"); head.className = "stock-space-section-head";
      const copyWrap = document.createElement("div");
      const title = document.createElement("div"); title.className = "stock-space-section-title"; title.textContent = "历史与复盘";
      const copy = document.createElement("div"); copy.className = "stock-space-section-copy"; copy.textContent = "报告和对话保留生成时的证据快照，后续新证据不会静默改写旧结论。";
      copyWrap.append(title, copy); head.appendChild(copyWrap); container.appendChild(head);
      const currentSymbol = symbol || session?.symbol || $("deepStockSymbol").value;
      const reviews = tradeReviews || state.stockTradeReviews[currentSymbol] || [];
      container.appendChild(renderTradeReviewWorkspace(currentSymbol, reviews));
      const grid = document.createElement("div"); grid.className = "stock-history-grid";
      const conversation = document.createElement("article"); conversation.className = "stock-history-card";
      const conversationTitle = document.createElement("div"); conversationTitle.className = "stock-history-title"; conversationTitle.textContent = session ? "绑定的研究对话" : "尚未建立绑定对话";
      const conversationCopy = document.createElement("div"); conversationCopy.className = "stock-history-copy";
      conversationCopy.textContent = session ? `${session.conversation?.message_count || 0} 条消息，七阶段问题会进入同一历史会话，方便连续追问和复核。` : "建立研究空间后，金融顾问会绑定一个可长期保存的历史对话。";
      conversation.append(conversationTitle, conversationCopy);
      if (session) {
        const actions = document.createElement("div"); actions.className = "stock-workspace-actions";
        const open = document.createElement("button"); open.type = "button"; open.className = "btn"; open.textContent = "继续对话"; open.addEventListener("click", () => { void continueDeepStockConversation(); });
        actions.appendChild(open); conversation.appendChild(actions);
      }
      const latestReport = workspace?.latest_report || session?.latest_report || null;
      const report = document.createElement("article"); report.className = "stock-history-card";
      const reportTitle = document.createElement("div"); reportTitle.className = "stock-history-title"; reportTitle.textContent = latestReport?.title || "最新服务器研究报告";
      const reportCopy = document.createElement("div"); reportCopy.className = "stock-history-copy"; reportCopy.textContent = readableResearchPreview(latestReport?.summary) || "尚未形成最新研究报告，历史对话仍可继续使用。";
      report.append(reportTitle, reportCopy);
      if (latestReport) {
        const meta = document.createElement("div"); meta.className = "stock-history-meta"; meta.textContent = `数据时间 ${readableTime(latestReport.market_timestamp)} · 生成于 ${readableTime(latestReport.generated_at)}`;
        const actions = document.createElement("div"); actions.className = "stock-workspace-actions";
        const read = document.createElement("button"); read.type = "button"; read.className = "btn primary"; read.textContent = "阅读完整报告";
        read.addEventListener("click", () => openReader(latestReport.title, latestReport.body || latestReport.summary, meta.textContent));
        actions.appendChild(read); report.append(meta, actions);
      }
      grid.append(conversation, report);
      const thesisHistory = workspace?.thesis_history || [];
      if (thesisHistory.length) {
        const statusLabels = {active: "当前生效", superseded: "历史版本", invalidated: "已失效", rejected: "未采纳", pending_confirmation: "待确认", draft: "草稿"};
        const card = document.createElement("article"); card.className = "stock-history-card";
        const cardTitle = document.createElement("div"); cardTitle.className = "stock-history-title"; cardTitle.textContent = "用户判断版本";
        const cardCopy = document.createElement("div"); cardCopy.className = "stock-history-copy"; cardCopy.textContent = `已保存 ${thesisHistory.length} 个版本；新判断不会静默覆盖旧版本。`;
        card.append(cardTitle, cardCopy);
        for (const item of thesisHistory.slice(0, 5)) {
          const row = document.createElement("div"); row.className = "stock-coverage-history-item";
          const meta = document.createElement("div"); meta.className = "stock-coverage-history-time"; meta.textContent = `版本 ${item.version_no || 1} · ${statusLabels[item.status] || item.status || "已保存"} · ${readableTime(item.confirmed_at || item.created_at)}`;
          const detail = document.createElement("div"); detail.className = "stock-coverage-history-change"; detail.textContent = item.reason_text || "未填写判断正文。";
          row.append(meta, detail); card.appendChild(row);
        }
        grid.appendChild(card);
      }
      const observationTasks = workspace?.observation_tasks?.items || [];
      if (observationTasks.length) {
        const card = document.createElement("article"); card.className = "stock-history-card";
        const cardTitle = document.createElement("div"); cardTitle.className = "stock-history-title"; cardTitle.textContent = "观察任务轨迹";
        const activeCount = workspace?.observation_tasks?.summary?.active || 0;
        const cardCopy = document.createElement("div"); cardCopy.className = "stock-history-copy"; cardCopy.textContent = `共 ${observationTasks.length} 项，其中 ${activeCount} 项进行中；这里只呈现已由用户保存的任务。`;
        card.append(cardTitle, cardCopy);
        for (const task of observationTasks.slice(0, 5)) {
          const row = document.createElement("div"); row.className = "stock-coverage-history-item";
          const latestEvent = task.history?.[0] || {};
          const meta = document.createElement("div"); meta.className = "stock-coverage-history-time"; meta.textContent = `${task.status_label || "观察任务"} · 版本 ${task.version || 1} · ${readableTime(latestEvent.created_at || task.updated_at || task.created_at)}`;
          const detail = document.createElement("div"); detail.className = "stock-coverage-history-change"; detail.textContent = task.description || task.title || "继续核验相关事实。";
          row.append(meta, detail); card.appendChild(row);
        }
        grid.appendChild(card);
      }
      const importantChanges = workspace?.important_changes || [];
      if (importantChanges.length) {
        const card = document.createElement("article"); card.className = "stock-history-card";
        const cardTitle = document.createElement("div"); cardTitle.className = "stock-history-title"; cardTitle.textContent = "重要变化记录";
        const cardCopy = document.createElement("div"); cardCopy.className = "stock-history-copy"; cardCopy.textContent = "变化只作为重新核验判断的证据，不会自动改写用户结论。";
        card.append(cardTitle, cardCopy);
        for (const changeItem of importantChanges.slice(0, 3)) {
          const row = document.createElement("div"); row.className = "stock-coverage-history-item";
          const meta = document.createElement("div"); meta.className = "stock-coverage-history-time"; meta.textContent = `${changeItem.source_label || "确定性变化"} · ${readableTime(changeItem.data_as_of || changeItem.created_at)}`;
          const detail = document.createElement("div"); detail.className = "stock-coverage-history-change"; detail.textContent = changeItem.summary || changeItem.title || "已有新证据，等待复核。";
          row.append(meta, detail); card.appendChild(row);
        }
        grid.appendChild(card);
      }
      const position = workspace?.position_snapshot || null;
      if (position?.available && position.current) {
        const positionCard = document.createElement("article"); positionCard.className = "stock-history-card";
        const positionTitle = document.createElement("div"); positionTitle.className = "stock-history-title"; positionTitle.textContent = "持仓与操作历史";
        const positionCopy = document.createElement("div"); positionCopy.className = "stock-history-copy";
        positionCopy.textContent = `当前 ${position.current.quantity} 股，移动平均成本 ${position.current.average_cost || "已归零"}；已保存 ${(position.operations || []).length} 笔操作、${(position.adjustments || []).length} 笔调整和 ${(position.snapshots || []).length} 个派生快照。`;
        const meta = document.createElement("div"); meta.className = "stock-history-meta"; meta.textContent = position.current.fees_complete ? "费用记录完整，可计算已实现净结果。" : "部分费用缺失，复盘不得展示伪精确净收益。";
        const actions = document.createElement("div"); actions.className = "stock-workspace-actions";
        const open = document.createElement("button"); open.type = "button"; open.className = "btn"; open.textContent = "查看操作与持仓"; open.addEventListener("click", () => activateStockSpaceTab("tasks"));
        actions.appendChild(open); positionCard.append(positionTitle, positionCopy, meta, actions); grid.appendChild(positionCard);
      }
      container.appendChild(grid);
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
      const canonical = String(symbol || "").trim();
      if (!canonical) return null;
      if (state.deepStockOverviewPromises[canonical]) {
        return state.deepStockOverviewPromises[canonical];
      }
      const request = loadDeepStockOverviewOnce(canonical);
      state.deepStockOverviewPromises[canonical] = request;
      try {
        return await request;
      } finally {
        if (state.deepStockOverviewPromises[canonical] === request) {
          delete state.deepStockOverviewPromises[canonical];
        }
      }
    }

    async function loadDeepStockOverviewOnce(symbol) {
      if (!symbol) return;
      state.deepStockOverviewSymbol = symbol;
      const container = $("deepStockOverview");
      state.deepStockKlineController?.destroy?.();
      state.deepStockKlineController = null;
      container.innerHTML = '<div class="empty">正在汇总行情、财务、股东、研报与事件…</div>';
      const encoded = encodeURIComponent(symbol);
      const isAShare = /\.(?:SS|SZ)$/i.test(symbol);
      const [pageResult] = await Promise.all([
        apiResult(`/v1/stocks/${encoded}/page?range=1y`),
        loadPendingReviewDrafts()
      ]);
      if (state.deepStockOverviewSymbol !== symbol) return;
      const pagePayload = pageResult.value || {};
      const pageModules = pagePayload.modules || {};
      const moduleData = name => pageModules[name]?.status === "available" ? pageModules[name].data : null;
      const workspace = moduleData("workspace");
      const history = moduleData("history");
      const fundamentals = moduleData("fundamentals");
      const earnings = moduleData("earnings_quality");
      const drivers = moduleData("financial_drivers");
      const shareholders = moduleData("shareholders");
      const expectations = moduleData("analyst_expectations");
      const events = moduleData("event_timeline");
      const information = moduleData("information");
      const workspaceLoadError = workspace ? null : (
        pageModules.workspace || pageResult.error || {status: null, message: "研究空间暂时没有完整返回"}
      );
      const actionPlansPayload = workspace?.action_plans || null;
      const tradeReviewsPayload = workspace?.trade_reviews || null;
      if (actionPlansPayload !== null) state.stockActionPlans[symbol] = listPayloadItems(actionPlansPayload);
      if (tradeReviewsPayload !== null) state.stockTradeReviews[symbol] = listPayloadItems(tradeReviewsPayload);

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
      const evidenceLayers = workspace?.evidence_layers || {};
      const evidenceLayerByKey = new Map(
        (evidenceLayers.dimensions || []).map(item => [item.key, item])
      );
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
      });
      const normalizeResearchItems = items => [...new Set((items || []).map(structuredItemText).filter(Boolean))];
      const counterevidenceText = item => {
        if (!item) return "";
        const dataTime = item.data_time
          ? (/^\d{4}-\d{2}-\d{2}$/.test(String(item.data_time)) ? item.data_time : readableTime(item.data_time))
          : "";
        return [
          item.statement,
          item.evidence ? `依据：${item.evidence}` : "",
          item.source_name ? `来源：${item.source_name}` : "",
          dataTime ? `数据时间：${dataTime}` : "",
          item.limitations?.[0] ? `边界：${item.limitations[0]}` : ""
        ].filter(Boolean).join("；");
      };
      const supportedClaims = researchClaims.filter(item => item.relation === "supports");
      const weakenedClaims = researchClaims.filter(item => item.relation === "weakens");
      const unresolvedClaims = researchClaims.filter(item => item.relation === "unresolved");
      const workspaceCounterevidence = workspace?.counterevidence || [];
      const directCounterItems = workspaceCounterevidence
        .filter(item => item.kind === "bear_case" || item.label === "反方证据")
        .map(counterevidenceText);
      const riskReviewItems = workspaceCounterevidence
        .filter(item => item.kind === "risk_committee" || item.label === "风险复核")
        .map(counterevidenceText);
      const supportedEvidenceItems = normalizeResearchItems(supportedClaims.length ? supportedClaims.map(researchClaimText) : [
        historyMetrics.trend_state ? `价格结构：${historyMetrics.trend_state}；20日收益 ${pct(historyMetrics.return_20d_pct)}。` : "",
        ...(earnings?.supports || []).slice(0, 2),
        ...(drivers?.confirmed_mechanical_drivers || []).slice(0, 2),
        events?.coverage?.official_events ? `已归档 ${events.coverage.official_events} 条公司公告或监管事件。` : ""
      ]);
      const counterEvidenceItems = normalizeResearchItems(directCounterItems.length ? directCounterItems : weakenedClaims.length ? weakenedClaims.map(researchClaimText) : [
        ...(earnings?.contradictions || []).slice(0, 3),
        ...(drivers?.plausible_clues || []).slice(0, 2)
      ]);
      const riskEvidenceItems = normalizeResearchItems(riskReviewItems.length ? riskReviewItems : unresolvedClaims.length ? unresolvedClaims.map(researchClaimText) : [
        ...(drivers?.unresolved_causes || []).slice(0, 2),
        ...(earnings?.review_points || []).slice(0, 2)
      ]);
      const informationGapItems = normalizeResearchItems(claimLedger?.information_gaps?.length ? claimLedger.information_gaps.map(item => item.description) : [
        ...(drivers?.unresolved_causes || []).slice(0, 3),
        ...(earnings?.review_points || []).slice(0, 3)
      ]);
      const invalidationItems = normalizeResearchItems((claimLedger?.invalidation_conditions || workspace?.invalidation_conditions || []).map(invalidationConditionText));
      const moduleAvailability = [
        Boolean(points.length), Boolean(fundamentals), earnings?.status === "available",
        drivers?.status === "available", Boolean(shareholders), Boolean(expectations),
        Boolean(events), Boolean(information)
      ];
      const availableModuleCount = moduleAvailability.filter(Boolean).length;

      container.innerHTML = "";
      const shell = document.createElement("div"); shell.className = "deep-overview-shell";
      if (workspaceLoadError) {
        const alert = document.createElement("section"); alert.className = "stock-load-alert"; alert.setAttribute("role", "alert");
        const copy = document.createElement("div"); copy.className = "stock-load-alert-copy";
        const title = document.createElement("div"); title.className = "stock-load-alert-title"; title.textContent = "股票研究空间未完整加载";
        const detail = document.createElement("div"); detail.className = "stock-load-alert-detail";
        detail.textContent = "当前判断、关系、任务和证据资料暂未返回。下方只展示本次已经取得的行情与分析模块，不会把缺失内容显示成“没有数据”。";
        const meta = document.createElement("div"); meta.className = "stock-load-alert-meta";
        meta.textContent = "重新加载不会清空已保存的判断、任务、持仓或历史对话。";
        copy.append(title, detail, meta);
        const retry = document.createElement("button"); retry.type = "button"; retry.className = "btn primary"; retry.textContent = "重新加载股票空间";
        retry.addEventListener("click", async () => {
          retry.disabled = true;
          retry.textContent = "正在重新加载…";
          await loadDeepStockOverview(symbol);
        });
        alert.append(copy, retry); shell.appendChild(alert);
      }
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
      const chartHost = document.createElement("div"); chartHost.className = "stock-space-kline-host"; chartCard.appendChild(chartHost);
      requestAnimationFrame(() => {
        if (!chartHost.isConnected || state.deepStockOverviewSymbol !== symbol) return;
        state.deepStockKlineController?.destroy?.();
        state.deepStockKlineController = window.QSKlineExplorer?.createExplorer(chartHost, {
          symbol,
          name,
          request: api,
          initialPeriod: "daily",
          initialRange: "1y",
          storageKey: `stock-space:${symbol}`
        }) || null;
      });
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

      const digest = document.createElement("aside"); digest.className = "stock-research-digest"; digest.setAttribute("aria-label", "当前研究重点");
      const digestHead = document.createElement("div"); digestHead.className = "stock-digest-head";
      const digestTitle = document.createElement("div"); digestTitle.className = "stock-digest-title"; digestTitle.textContent = "当前研究重点";
      const digestPriority = document.createElement("span"); digestPriority.className = "stock-digest-priority"; digestPriority.textContent = priorityLabel;
      digestHead.append(digestTitle, digestPriority);
      const digestSummary = document.createElement("div"); digestSummary.className = "stock-digest-summary";
      const digestSummaryLabel = document.createElement("span"); digestSummaryLabel.textContent = "先核验这件事";
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
      const viewEvidence = document.createElement("button"); viewEvidence.type = "button"; viewEvidence.className = "btn"; viewEvidence.textContent = "查看完整依据"; viewEvidence.addEventListener("click", () => activateStockSpaceTab("evidence"));
      const digestAgent = document.createElement("button"); digestAgent.type = "button"; digestAgent.className = "btn primary"; digestAgent.textContent = "继续问 Agent"; digestAgent.addEventListener("click", () => { void continueDeepStockConversation(pendingActions[0]?.next_step || session?.next_question || `请基于当前证据复核${name}的研究判断。`); });
      digestActions.append(viewEvidence, digestAgent);
      digest.append(digestHead, digestSummary, dimensions, digestStatusRow, digestActions);
      primaryGrid.append(chartCard, digest); shell.appendChild(primaryGrid);

      const workspaceSummary = document.createElement("div"); workspaceSummary.className = "stock-workspace-summary";
      const researchEntry = workspace?.research_entry || session?.research_entry || null;
      const thesisCard = document.createElement("section"); thesisCard.className = "stock-workspace-card primary";
      const thesisHead = document.createElement("div"); thesisHead.className = "stock-workspace-card-head";
      const thesisTitle = document.createElement("div"); thesisTitle.className = "stock-workspace-card-title"; thesisTitle.textContent = "当前研究判断";
      const thesisMeta = document.createElement("span"); thesisMeta.className = "stock-workspace-card-meta"; thesisMeta.textContent = workspace?.thesis?.summary ? `由你确认 · 版本 ${workspace.thesis.version || 1}` : researchEntry ? "筛选线索待确认" : "待你确认";
      thesisHead.append(thesisTitle, thesisMeta);
      const judgmentLayout = document.createElement("div"); judgmentLayout.className = "stock-judgment-layout";
      const judgmentMain = document.createElement("div"); judgmentMain.className = "stock-judgment-main";
      const judgmentLabel = document.createElement("div"); judgmentLabel.className = "stock-judgment-label"; judgmentLabel.textContent = "研究主线";
      const thesisCopy = document.createElement("div"); thesisCopy.className = "stock-workspace-copy";
      thesisCopy.textContent = workspace?.thesis?.summary || watchItem?.thesis || (researchEntry
        ? [
            `你从“${researchEntry.source_label || "研究候选筛选"}”进入研究空间。`,
            (researchEntry.matched_reasons || []).length ? `已保存的候选理由：${researchEntry.matched_reasons.slice(0, 4).join("；")}。` : "",
            (researchEntry.missing_fields || []).length ? `仍需补证：${researchEntry.missing_fields.slice(0, 4).join("、")}。` : "",
            "这些内容只是待核验线索，不会自动成为正式关注判断或推进研究阶段。"
          ].filter(Boolean).join(" ")
        : "还没有记录为什么关注这只股票、主要观察什么以及何时重新判断。补充后，Agent 会把它作为最高优先级私人上下文。");
      judgmentMain.append(judgmentLabel, thesisCopy);
      const systemObservation = document.createElement("aside"); systemObservation.className = "stock-system-observation";
      const systemTitle = document.createElement("strong"); systemTitle.textContent = "最新数据提示";
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
      const editThesis = document.createElement("button"); editThesis.type = "button"; editThesis.className = "btn"; editThesis.textContent = workspace?.relation?.in_watchlist ? "编辑当前判断" : "加入关注并记录判断";
      editThesis.addEventListener("click", () => {
        editThesis.hidden = true;
        thesisCopy.hidden = true;
        const editor = document.createElement("div"); editor.className = "stock-thesis-editor";
        const textarea = document.createElement("textarea");
        textarea.className = "insight-question";
        textarea.setAttribute("aria-label", `${name}当前判断`);
        textarea.placeholder = "写下为什么关注、主要观察什么，以及什么变化会让你重新判断";
        textarea.value = workspace?.thesis?.summary || watchItem?.thesis || "";
        let editBaseVersion = Number(workspace?.thesis?.version || 0);
        const status = document.createElement("div"); status.className = "stock-thesis-status";
        status.textContent = `保存会创建正式判断版本 ${editBaseVersion + 1}，原版本继续保留；如果其他页面已更新，系统不会静默覆盖。`;
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
            if (!workspace?.relation?.workspace_id) {
              await api("/me/watchlist", {
                method: "POST",
                body: JSON.stringify({ symbol, name: name === symbol ? null : name, market: currency === "USD" ? "美股" : "A股", thesis: null })
              });
              editBaseVersion = 0;
            }
            const draft = await api(`/v1/stocks/${encodeURIComponent(symbol)}/theses`, {
              method: "POST",
              body: JSON.stringify({
                reason_text: thesis,
                watch_items: workspace?.thesis?.watch_items || [],
                recheck_conditions: workspace?.thesis?.recheck_conditions || [],
                source: "user",
                base_version: editBaseVersion
              })
            });
            await api(`/v1/stocks/${encodeURIComponent(symbol)}/theses/${encodeURIComponent(draft.id)}/confirm`, {method: "POST"});
            closeEditor();
            await loadWatchlist();
            await loadDeepStockOverview(symbol);
          } catch (error) {
            save.disabled = false; cancel.disabled = false;
            if (error?.status === 409) {
              try {
                const latestWorkspace = await api(`/v1/stocks/${encodeURIComponent(symbol)}/workspace`);
                editBaseVersion = Number(latestWorkspace?.thesis?.version || 0);
                const latestText = latestWorkspace?.thesis?.summary || "当前没有正式判断";
                status.textContent = `正式判断已在其他页面更新到版本 ${editBaseVersion}。系统没有覆盖它；请对照最新判断后再次保存：${latestText}`;
              } catch {
                status.textContent = error?.message || "正式判断已经更新，系统没有覆盖新版本。请刷新后重试。";
              }
            } else {
              status.textContent = error?.message || "当前判断暂未保存，请稍后重试。";
            }
          }
        });
        editorActions.append(save, cancel); editor.append(textarea, status, editorActions);
        thesisCard.appendChild(editor);
        textarea.focus();
      });
      thesisActions.className = "stock-workspace-head-actions";
      const openThesisEvidence = document.createElement("button"); openThesisEvidence.type = "button"; openThesisEvidence.className = "btn"; openThesisEvidence.textContent = "查看完整证据"; openThesisEvidence.addEventListener("click", () => activateStockSpaceTab("evidence"));
      thesisActions.append(thesisMeta, openThesisEvidence, editThesis);
      thesisHead.replaceChildren(thesisTitle, thesisActions);
      thesisCard.append(thesisHead, judgmentLayout);

      const changesCard = document.createElement("section"); changesCard.className = "stock-workspace-card changes";
      const changesHead = document.createElement("div"); changesHead.className = "stock-workspace-card-head";
      const changesTitle = document.createElement("div"); changesTitle.className = "stock-workspace-card-title"; changesTitle.textContent = "最近发生了什么";
      const changesMeta = document.createElement("span"); changesMeta.className = "stock-workspace-card-meta"; changesMeta.textContent = `${changeItems.length} 项`;
      changesHead.append(changesTitle, changesMeta);
      const changesList = document.createElement("div"); changesList.className = "stock-workspace-list";
      if (changeItems.length) changeItems.slice(0, 2).forEach(item => appendStockWorkspaceItem(changesList, item.title, item.meta, {body: item.detail, meta: item.meta, url: item.url, linkId: item.linkId}));
      else appendStockWorkspaceItem(changesList, "当前没有需要优先处理的新变化", "继续按当前判断观察；新增公告和事件会进入这里。 ");
      const changeActions = document.createElement("div"); changeActions.className = "stock-workspace-actions";
      const openChanges = document.createElement("button"); openChanges.type = "button"; openChanges.className = "btn"; openChanges.textContent = changeItems.length > 2 ? `查看全部 ${changeItems.length} 项变化` : "查看数据与事件"; openChanges.addEventListener("click", () => activateStockSpaceTab("evidence"));
      changeActions.appendChild(openChanges); changesCard.append(changesHead, changesList, changeActions);

      const tasksCard = document.createElement("section"); tasksCard.className = "stock-workspace-card tasks";
      const tasksHead = document.createElement("div"); tasksHead.className = "stock-workspace-card-head";
      const tasksTitle = document.createElement("div"); tasksTitle.className = "stock-workspace-card-title"; tasksTitle.textContent = "下一步研究";
      const tasksMeta = document.createElement("span"); tasksMeta.className = "stock-workspace-card-meta"; tasksMeta.textContent = pendingActions.length ? `${pendingActions.length} 项` : session ? "1 项" : "未启动";
      tasksHead.append(tasksTitle, tasksMeta);
      const taskList = document.createElement("div"); taskList.className = "stock-workspace-list";
      if (pendingActions.length) pendingActions.slice(0, 2).forEach(action => appendStockWorkspaceItem(
        taskList,
        action.title || "继续研究",
        action.next_step || action.current_evidence || "继续核验相关证据。",
        {body: researchActionDetail(action), meta: `任务状态：${{triggered: "需要复核", pending_data: "等待证据", watching: "持续观察"}[action.status] || "研究任务"}`, label: "查看任务依据"}
      ));
      else appendStockWorkspaceItem(taskList, session?.current_stage?.label || "开始 AI 深度研究", session?.next_question || "启动后会持续保存研究阶段、未决问题和下一条需要核验的证据。 ");
      const taskActions = document.createElement("div"); taskActions.className = "stock-workspace-actions";
      const openTasks = document.createElement("button"); openTasks.type = "button"; openTasks.className = "btn"; openTasks.textContent = "管理全部任务"; openTasks.addEventListener("click", () => activateStockSpaceTab("tasks"));
      const askAgent = document.createElement("button"); askAgent.type = "button"; askAgent.className = "btn primary"; askAgent.textContent = "请 Agent 继续核验"; askAgent.addEventListener("click", () => { void continueDeepStockConversation(pendingActions[0]?.next_step || session?.next_question); });
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
          const layer = evidenceLayerByKey.get(dimension.key) || dimension;
          const card = document.createElement("article"); card.className = "evidence-coverage-card";
          const head = document.createElement("div"); head.className = "evidence-coverage-head";
          const label = document.createElement("div"); label.className = "evidence-coverage-label"; label.textContent = dimension.label;
          const status = document.createElement("span"); status.className = `evidence-coverage-status ${dimension.coverage_status}`; status.textContent = statusLabels[dimension.coverage_status] || "待核验";
          const headActions = document.createElement("div"); headActions.className = "evidence-coverage-head-actions";
          const detail = document.createElement("button"); detail.type = "button"; detail.className = "evidence-layer-detail"; detail.textContent = "四层详情";
          const aiEmpty = evidenceLayers.ai_status === "not_generated"
            ? "尚未生成可恢复的 Agent 解释"
            : "最近一次 Agent 未覆盖本维度";
          const aiSourceLabel = {
            bound_research_conversation: "当前股票绑定研究对话",
            same_stock_history: "同一用户的该股票最近研究对话"
          }[evidenceLayers.ai_source] || "";
          const layerDefinitions = [
            ["raw", "原始数据", layer.raw_data || [], "尚未取得可核验原始数据"],
            ["system", "系统计算", layer.system_calculations || [], "尚未形成确定性计算"],
            ["ai", "AI解释", layer.ai_explanations || [], aiEmpty],
            ["missing", "缺失项", layer.missing_items || [], dimension.coverage_status === "sufficient" ? "当前没有阻塞性缺口，仍需关注新增证据" : "尚未明确缺失项"]
          ];
          detail.setAttribute("aria-label", `${dimension.label}四层证据详情`);
          detail.addEventListener("click", () => {
            const body = layerDefinitions.map(([, layerLabel, values, emptyText]) => {
              const lines = values.length ? values : [emptyText];
              return `${layerLabel}\n${lines.map((item, index) => `${index + 1}. ${item}`).join("\n")}`;
            }).join("\n\n");
            const layerSources = layer.sources || dimension.sources || [];
            const layerTimes = layer.as_of || dimension.as_of || [];
            openReader(
              `${name} · ${dimension.label}四层证据`,
              body,
              [statusLabels[dimension.coverage_status] || "待核验", layerSources.join("、"), layerTimes.join("、"), aiSourceLabel].filter(Boolean).join(" · ")
            );
          });
          headActions.append(status, detail); head.append(label, headActions);
          const copy = document.createElement("div"); copy.className = "evidence-coverage-copy";
          const layerSources = layer.sources || dimension.sources || [];
          const layerTimes = layer.as_of || dimension.as_of || [];
          copy.textContent = [
            layerSources.length ? `来源：${layerSources.join("、")}` : "来源尚未建立",
            layerTimes.length ? `数据时间：${layerTimes.join("、")}` : "数据时间待补充"
          ].join(" · ");
          const layerStack = document.createElement("div"); layerStack.className = "evidence-layer-stack";
          layerDefinitions.forEach(([kind, layerLabel, values, emptyText]) => {
            const row = document.createElement("div"); row.className = `evidence-layer-row ${kind}`;
            const rowLabel = document.createElement("span"); rowLabel.className = "evidence-layer-label"; rowLabel.textContent = layerLabel;
            const rowValues = document.createElement("div"); rowValues.className = `evidence-layer-values${values.length ? "" : " empty"}`;
            const previews = values.length ? values.slice(0, 2) : [emptyText];
            previews.forEach(value => {
              const line = document.createElement("span"); line.textContent = value; rowValues.appendChild(line);
            });
            row.append(rowLabel, rowValues); layerStack.appendChild(row);
          });
          card.append(head, copy, layerStack); coverageGrid.appendChild(card);
        });
        const boundary = document.createElement("div"); boundary.className = "evidence-coverage-boundary"; boundary.textContent = [
          evidenceCoverage.boundary || "覆盖状态只表示证据完整程度，不是公司评分或买卖信号。",
          evidenceLayers.boundary
        ].filter(Boolean).join(" ");
        coverageGrid.appendChild(boundary); evidenceShell.appendChild(coverageGrid);
      }
      const researchBoard = document.createElement("div"); researchBoard.className = "deep-research-board";
      appendDeepBoardCard(researchBoard, {kind: "confirmed", title: "已确认的证据", items: supportedEvidenceItems});
      appendDeepBoardCard(researchBoard, {kind: "counter", title: "关键反证与压力", items: normalizeResearchItems([...counterEvidenceItems, ...riskEvidenceItems])});
      appendDeepBoardCard(researchBoard, {kind: "gaps", title: "仍需补证", items: informationGapItems});
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
      renderStockSpaceTasks(symbol, session, workspace, state.stockActionPlans[symbol] || []);
      renderStockSpaceHistory(session, workspace, state.stockTradeReviews[symbol] || [], symbol);
    }
