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
      container.innerHTML = "";
      const sectors = data.sectors || [];
      if (sectors.length) {
        const head = document.createElement("div"); head.className = "sector-table-head";
        for (const label of ["排名", "板块", "涨跌幅", "内部上涨", "主力净流入"]) {
          const cell = document.createElement("span"); cell.textContent = label; head.appendChild(cell);
        }
        container.appendChild(head);
      }
      sectors.forEach((item, index) => {
        const total = Number(item.advancers || 0) + Number(item.decliners || 0) + Number(item.unchanged || 0);
        const advanceRatio = total ? Number(item.advancers || 0) / total : 0;
        const row = document.createElement("button"); row.type = "button"; row.className = "sector-rotation-row";
        row.setAttribute("aria-label", `研究${item.name || item.code}板块`);
        const rank = document.createElement("span"); rank.className = `sector-rank${index < 3 ? " top" : ""}`; rank.textContent = index + 1;
        const name = document.createElement("span"); name.className = "sector-name"; name.textContent = item.name || item.code;
        const change = document.createElement("strong"); change.className = tone(item.pct_change); change.textContent = pct(item.pct_change);
        const breadth = document.createElement("div"); breadth.className = "sector-breadth";
        const track = document.createElement("div"); track.className = "sector-breadth-track";
        const fill = document.createElement("span"); fill.style.width = `${Math.max(0, Math.min(100, advanceRatio * 100))}%`; track.appendChild(fill);
        const breadthValue = document.createElement("small"); breadthValue.textContent = total ? `${Math.round(advanceRatio * 100)}%` : "—";
        breadth.append(track, breadthValue);
        const flow = document.createElement("span"); flow.className = `sector-flow ${tone(item.main_net_inflow)}`; flow.textContent = compactNumber(item.main_net_inflow);
        row.append(rank, name, change, breadth, flow);
        row.addEventListener("click", () => prepareAgentQuestion(`分析A股“${item.name || item.code}”板块当前表现：先说明涨跌幅、内部上涨比例和数据时间，再结合公开信息解释可能驱动、反方证据以及不能确认的部分；不要把主力净流入字段直接解释成真实资金意图。`));
        container.appendChild(row);
      });
      if (!container.children.length) container.innerHTML = '<div class="empty">板块快照正在整理</div>';
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

    function stockAssetRelationMeta(relationType) {
      return {
        holding: {label: "持仓研究", color: "#e0525a"},
        watching: {label: "关注研究", color: "#3478f6"},
        ended: {label: "已结束", color: "#9aa6b5"}
      }[relationType] || {label: "研究资产", color: "#9aa6b5"};
    }

    async function reviewWatchlistReportWithAgent(item, report, button) {
      const original = button.textContent;
      button.disabled = true;
      button.textContent = "正在进入即时研究…";
      try {
        const session = await api("/me/deep-stock", {
          method: "POST",
          body: JSON.stringify({symbol: item.symbol})
        });
        state.deepStock = session;
        await loadConversations(false);
        await loadDeepStock({force: true});
        const timezoneName = /\.(?:SS|SZ)$/i.test(item.symbol || "") ? "Asia/Shanghai" : "America/New_York";
        const completeBarDate = report?.market_timestamp
          ? marketDateLabel(report.market_timestamp, timezoneName)
          : "待确认";
        const question = `请用最新可验证数据复核${item.name || item.symbol}（${item.symbol}）的服务器预生成研究快照。快照生成于${readableTime(report?.generated_at)}，其中完整日线截至${completeBarDate}。请先说明本轮相较快照有哪些事实更新，再分别列出仍成立的判断、反方证据、失效条件和下一条最值得核验的证据；行情时间与财务报告期必须分开写。不要直接复述快照原文，不要给目标价或买卖建议。`;
        await continueDeepStockConversation(question, session);
        $("chatInput").value = "";
        await sendChat(question);
      } catch (error) {
        openReader(
          "即时复核暂未开始",
          error?.message || "股票研究空间暂时无法打开，请稍后重试。",
          "预生成报告仍保留，可先阅读报告"
        );
      } finally {
        button.disabled = false;
        button.textContent = original;
      }
    }

    async function updateWatchlistChange(linkId, action, button) {
      if (!linkId) return;
      const original = button.textContent;
      button.disabled = true;
      button.textContent = "保存中…";
      try {
        if (action === "read") {
          await api(`/v1/user-changes/${encodeURIComponent(linkId)}/read`, {method: "POST"});
        } else {
          await api(`/v1/user-changes/${encodeURIComponent(linkId)}/relevance`, {
            method: "POST",
            body: JSON.stringify({relevance_status: action})
          });
        }
        await loadWatchlist();
      } catch (error) {
        $("watchlistSource").textContent = error?.message || "变化处理状态暂未保存，请稍后重试。";
        button.disabled = false;
        button.textContent = original;
      }
    }

    function renderWatchlistReports(reportMap) {
      const container = $("watchlistReports"); container.innerHTML = "";
      const activeAssets = (state.stockAssets || [])
        .filter(item => item.relation_type !== "ended")
        .sort((a, b) => {
          const priorityRank = {high: 3, normal: 2, low: 1};
          const priorityGap = (priorityRank[b.priority] || 0) - (priorityRank[a.priority] || 0);
          const reportA = reportMap.get(a.symbol);
          const reportB = reportMap.get(b.symbol);
          const generatedA = Date.parse(reportA?.generated_at || "") || 0;
          const generatedB = Date.parse(reportB?.generated_at || "") || 0;
          return priorityGap || generatedB - generatedA;
        });
      const items = activeAssets.slice(0, 6);
      let availableCount = 0;
      let newestGeneratedAt = null;
      for (const item of items) {
        const report = reportMap.get(item.symbol) || null;
        if (report) {
          availableCount += 1;
          if (!newestGeneratedAt || Date.parse(report.generated_at || 0) > Date.parse(newestGeneratedAt)) {
            newestGeneratedAt = report.generated_at;
          }
        }
        const card = document.createElement("article"); card.className = "watchlist-report-item";
        const head = document.createElement("div"); head.className = "watchlist-report-item-head";
        const title = document.createElement("div"); title.className = "watchlist-report-item-title"; title.textContent = `${item.name || item.symbol} · ${item.symbol}`;
        const badge = document.createElement("span"); badge.className = "watchlist-report-badge";
        const freshness = item.report_freshness || {};
        badge.textContent = freshness.label || (report ? "已有快照" : "等待生成");
        if (freshness.status === "today") badge.classList.add("fresh");
        head.append(title, badge);
        const timezoneName = /\.(?:SS|SZ)$/i.test(item.symbol || "") ? "Asia/Shanghai" : "America/New_York";
        const meta = document.createElement("div"); meta.className = "watchlist-report-item-meta";
        meta.textContent = report
          ? `${report.source_scope_label || "服务器公共证据快照"} · 生成 ${readableTime(report.generated_at)} · 完整日线截至 ${marketDateLabel(report.market_timestamp, timezoneName)}`
          : "后台尚未形成这只股票的最新研究快照";
        const copy = document.createElement("div"); copy.className = "watchlist-report-item-copy";
        copy.textContent = report
          ? readableResearchPreview(report.summary)
          : (item.next_action?.next_step || item.thesis || "进入股票空间后可继续研究；报告生成前不会展示虚构摘要。");
        const change = item.latest_change;
        let changeNode = null;
        if (change?.summary) {
          changeNode = document.createElement("div");
          changeNode.className = `watchlist-report-change${change.link_id && !change.read_at ? " unread" : ""}`;
          const changeCopy = document.createElement("div");
          const stateLabel = change.link_id
            ? (change.relevance_status === "relevant" ? "已标相关" : change.relevance_status === "irrelevant" ? "已标无关" : change.read_at ? "已读" : "新变化")
            : "公共变化";
          const strong = document.createElement("strong"); strong.textContent = `${stateLabel} · `;
          changeCopy.append(strong, document.createTextNode(change.summary));
          changeNode.appendChild(changeCopy);
          if (change.link_id && (!change.read_at || change.relevance_status === "pending")) {
            const changeActions = document.createElement("div"); changeActions.className = "watchlist-change-actions";
            if (!change.read_at) {
              const read = document.createElement("button"); read.type = "button"; read.textContent = "标为已读";
              read.addEventListener("click", () => { void updateWatchlistChange(change.link_id, "read", read); });
              changeActions.appendChild(read);
            }
            if (change.relevance_status === "pending") {
              const relevant = document.createElement("button"); relevant.type = "button"; relevant.textContent = "与我有关";
              relevant.addEventListener("click", () => { void updateWatchlistChange(change.link_id, "relevant", relevant); });
              const irrelevant = document.createElement("button"); irrelevant.type = "button"; irrelevant.textContent = "与我无关";
              irrelevant.addEventListener("click", () => { void updateWatchlistChange(change.link_id, "irrelevant", irrelevant); });
              changeActions.append(relevant, irrelevant);
            }
            changeNode.appendChild(changeActions);
          }
        }
        const actions = document.createElement("div"); actions.className = "watchlist-report-item-actions";
        if (report) {
          const read = document.createElement("button"); read.type = "button"; read.className = "btn"; read.textContent = "阅读报告";
          read.addEventListener("click", () => { void openResearchReport(item.symbol, read); });
          const review = document.createElement("button"); review.type = "button"; review.className = "btn primary"; review.textContent = "用最新数据复核";
          review.addEventListener("click", () => { void reviewWatchlistReportWithAgent(item, report, review); });
          actions.append(read, review);
        } else {
          const open = document.createElement("button"); open.type = "button"; open.className = "btn primary"; open.textContent = "进入股票研究";
          open.addEventListener("click", () => { void openDeepStockSymbol(item.symbol); });
          actions.appendChild(open);
        }
        card.append(head, meta, copy);
        if (changeNode) card.appendChild(changeNode);
        card.appendChild(actions); container.appendChild(card);
      }
      if (!items.length) {
        container.innerHTML = '<div class="empty">添加关注后，后台研究报告与即时复核入口会出现在这里。</div>';
      }
      const hiddenCount = Math.max(0, activeAssets.length - items.length);
      $("watchlistReportSummary").textContent = activeAssets.length
        ? `${availableCount}/${items.length} 只股票已有研究快照${hiddenCount ? ` · 另有 ${hiddenCount} 项可在下方列表查看` : ""}${newestGeneratedAt ? ` · 最近更新 ${readableTime(newestGeneratedAt)}` : ""}。快照用于快速阅读，点击复核会基于最新数据重新研究。`
        : "添加关注后，系统会按可用数据生成研究快照；不会用虚构报告填充空状态。";
    }

    async function runWatchlistAgentBrief() {
      const button = $("watchlistAgentBrief");
      const original = button.textContent;
      button.disabled = true;
      button.textContent = "正在建立即时汇总…";
      try {
        startNewConversation(true, "push");
        await sendChat("请生成我的自选股每日研究摘要。基于当前持续跟踪的关注与持仓股票，以及最新可验证行情、重要变化、正式判断、观察任务和服务器研究快照，按优先级说明今天最值得先核验什么。每只股票必须区分最新报价时间、完整日线日期与财务报告期，并给出反方证据、失效条件和下一步研究任务。预生成报告只能作为证据，不能直接复述成当前回答；不要给目标价或买卖建议。");
      } finally {
        button.disabled = false;
        button.textContent = original;
      }
    }

    function renderWatchlistOverview(reportMap) {
      const stats = $("watchlistOverviewStats"); stats.innerHTML = "";
      const assets = state.stockAssets || [];
      const activeCount = assets.filter(item => item.relation_type !== "ended").length;
      const pausedCount = assets.filter(item => item.tracking_status === "paused" && item.relation_type !== "ended").length;
      const pendingCount = assets.reduce((sum, item) => sum + Number(item.open_task_count || 0), 0);
      for (const [label, value] of [["研究资产", assets.length], ["持续跟踪", activeCount - pausedCount], ["暂停跟踪", pausedCount], ["待处理任务", pendingCount]]) {
        const card = document.createElement("div"); card.className = "watchlist-overview-stat";
        const labelNode = document.createElement("span"); labelNode.textContent = label;
        const valueNode = document.createElement("strong"); valueNode.textContent = value;
        card.append(labelNode, valueNode); stats.appendChild(card);
      }
      const distribution = $("watchlistStatusDistribution"); distribution.innerHTML = "";
      const statuses = ["holding", "watching", "ended"];
      const counts = statuses.map(status => assets.filter(item => item.relation_type === status).length);
      const total = Math.max(1, counts.reduce((sum, value) => sum + value, 0));
      let cursor = 0;
      const stops = statuses.map((status, index) => {
        const start = cursor; cursor += counts[index] / total * 100;
        return `${stockAssetRelationMeta(status).color} ${start}% ${cursor}%`;
      });
      if (!counts.some(Boolean)) stops.splice(0, stops.length, "#dfe5ed 0 100%");
      const ring = document.createElement("div"); ring.className = "watchlist-status-ring"; ring.style.background = `conic-gradient(${stops.join(",")})`;
      const ringValue = document.createElement("strong"); ringValue.textContent = assets.length; ring.appendChild(ringValue);
      const legend = document.createElement("div"); legend.className = "watchlist-status-legend";
      statuses.forEach((status, index) => {
        const meta = stockAssetRelationMeta(status);
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

    async function updateStockAssetRelation(item, changes = {}) {
      if (!item?.workspace_id || !item?.version) {
        $("watchlistSource").textContent = "这项研究资产正在完成版本化迁移，暂时不能修改关系状态。";
        return;
      }
      const relationType = changes.relation_type || item.relation_type || "watching";
      const restoringEndedSpace = item.relation_type === "ended" && relationType !== "ended";
      const trackingStatus = relationType === "ended"
        ? "paused"
        : (changes.tracking_status || (restoringEndedSpace ? "active" : item.tracking_status) || "active");
      const payload = {
        base_version: item.version,
        relation_type: relationType,
        priority: relationType === "watching" ? (changes.priority || item.priority || "normal") : null,
        tracking_status: trackingStatus,
        workflow_status: relationType === "ended" ? "idle" : (item.workflow_status || "idle"),
        attention_tags: item.attention_tags || []
      };
      try {
        await api(`/v1/stocks/${encodeURIComponent(item.symbol)}/relation`, {method: "PATCH", body: JSON.stringify(payload)});
        await loadWatchlist();
      } catch (error) {
        $("watchlistSource").textContent = error?.status === 409
          ? "这项研究资产已在其他页面更新，列表已刷新；系统没有覆盖新版本。"
          : (error?.message || "研究资产状态暂未保存，请稍后重试。");
        if (error?.status === 409) await loadWatchlist();
      }
    }

    function renderWatchlist(data, actionsPacket = {}, assetsPacket = null) {
      const briefItems = data.items || [];
      const briefMap = new Map(briefItems.map(item => [item.symbol, item]));
      const rawAssets = assetsPacket?.items?.length
        ? assetsPacket.items
        : briefItems.map(item => ({
            ...item,
            workspace_id: null,
            version: null,
            relation_type: "watching",
            priority: "normal",
            tracking_status: "active",
            workflow_status: "idle",
            attention_tags: [],
            active_thesis: item.thesis ? {summary: item.thesis, version: 1} : null,
            open_task_count: 0
          }));
      state.stockAssets = rawAssets.map(asset => {
        const brief = briefMap.get(asset.symbol) || {};
        const quote = asset.quote || {};
        return {
          ...brief,
          ...asset,
          current_quote: brief.current_quote || quote,
          latest_bar: brief.latest_bar,
          metrics: brief.metrics,
          status: quote.status || brief.status,
          thesis: asset.active_thesis?.summary || asset.active_thesis?.reason_text || brief.thesis || null
        };
      });
      state.watchlist = state.stockAssets.filter(item => item.relation_type !== "ended");
      state.researchReports = state.stockAssets
        .map(item => item.report_meta)
        .filter(Boolean);
      state.researchActions = actionsPacket.items || [];
      state.researchActionSummary = actionsPacket.summary || {};
      refreshDeepStockSymbolOptions();
      const container = $("watchlist"); container.innerHTML = "";
      const reportMap = new Map(state.researchReports.map(item => [item.symbol, item]));
      const actionMap = new Map(state.researchActions.map(item => [item.symbol, item]));
      const visibleItems = state.stockAssets.filter(item => {
        const primaryMatch = state.watchlistFilter === "all" || item.relation_type === state.watchlistFilter;
        const secondaryMatch = state.watchlistSecondaryFilter === "all"
          || (state.watchlistSecondaryFilter === "paused" && item.tracking_status === "paused" && item.relation_type !== "ended")
          || (state.watchlistSecondaryFilter === "waiting_data" && item.workflow_status === "waiting_data")
          || item.priority === state.watchlistSecondaryFilter;
        return primaryMatch && secondaryMatch;
      });
      if (visibleItems.length) {
        const head = document.createElement("div"); head.className = "watchlist-table-head";
        for (const label of ["研究资产", "最新行情", "当前判断", "下一事项", "操作"]) {
          const cell = document.createElement("span"); cell.textContent = label; head.appendChild(cell);
        }
        container.appendChild(head);
      }
      for (const item of visibleItems) {
        const row = document.createElement("div");
        row.className = `watchlist-stock-row${state.selectedWatchlistSymbol === item.symbol ? " active" : ""}`;
        row.dataset.symbol = item.symbol;
        row.tabIndex = 0;

        const identity = document.createElement("div");
        const name = document.createElement("div"); name.className = "watchlist-stock-name"; name.textContent = item.name || item.symbol;
        const symbol = document.createElement("span"); symbol.className = "watchlist-stock-symbol"; symbol.textContent = item.symbol;
        const identityMeta = document.createElement("div"); identityMeta.className = "watchlist-asset-meta";
        const relationLabel = {watching: "关注", holding: "持仓", ended: "已结束"}[item.relation_type] || "关注";
        const priorityLabel = {high: "高优先级", normal: "普通优先级", low: "低优先级"}[item.priority || "normal"];
        const trackingLabel = item.relation_type === "ended" ? "历史保留" : item.tracking_status === "paused" ? "已暂停" : item.workflow_status === "waiting_data" ? "等待数据" : "跟踪中";
        for (const label of [item.market, relationLabel, item.relation_type === "watching" ? priorityLabel : null, trackingLabel].filter(Boolean)) {
          const tag = document.createElement("span"); tag.className = "watchlist-asset-tag"; tag.textContent = label; identityMeta.appendChild(tag);
        }
        identity.append(name, symbol, identityMeta);

        const management = document.createElement("details"); management.className = "watchlist-manage";
        management.addEventListener("click", event => event.stopPropagation());
        const managementSummary = document.createElement("summary"); managementSummary.className = "icon-button"; managementSummary.textContent = "更多";
        const managementMenu = document.createElement("div"); managementMenu.className = "watchlist-manage-menu";
        const relationField = document.createElement("label"); relationField.textContent = "关系";
        const relationSelect = document.createElement("select"); relationSelect.setAttribute("aria-label", `${item.name || item.symbol}关系状态`);
        for (const [value, label] of [["watching", "关注研究"], ["holding", "持仓研究"], ["ended", "已结束"]]) {
          const option = document.createElement("option"); option.value = value; option.textContent = label; option.selected = item.relation_type === value; relationSelect.appendChild(option);
        }
        relationSelect.disabled = !item.workspace_id || !item.version;
        relationSelect.addEventListener("click", event => event.stopPropagation());
        relationSelect.addEventListener("change", event => {
          event.stopPropagation();
          if (relationSelect.value === "ended" && !window.confirm("结束跟踪后，这只股票会移到“已结束”，原判断、任务和历史仍会保留。确定继续吗？")) {
            relationSelect.value = item.relation_type || "watching";
            return;
          }
          void updateStockAssetRelation(item, {relation_type: relationSelect.value});
        });
        relationField.appendChild(relationSelect); managementMenu.appendChild(relationField);
        if (item.relation_type === "watching") {
          const priorityField = document.createElement("label"); priorityField.textContent = "优先级";
          const prioritySelect = document.createElement("select"); prioritySelect.setAttribute("aria-label", `${item.name || item.symbol}关注优先级`);
          for (const [value, label] of [["high", "高优先级"], ["normal", "普通优先级"], ["low", "低优先级"]]) {
            const option = document.createElement("option"); option.value = value; option.textContent = label; option.selected = (item.priority || "normal") === value; prioritySelect.appendChild(option);
          }
          prioritySelect.disabled = !item.workspace_id || !item.version;
          prioritySelect.addEventListener("click", event => event.stopPropagation());
          prioritySelect.addEventListener("change", event => { event.stopPropagation(); void updateStockAssetRelation(item, {priority: prioritySelect.value}); });
          priorityField.appendChild(prioritySelect); managementMenu.appendChild(priorityField);
        }
        management.append(managementSummary, managementMenu);

        const quote = document.createElement("div"); quote.className = "watchlist-quote-cell";
        const quoteData = watchlistQuote(item);
        const latest = document.createElement("strong"); latest.textContent = numeric(quoteData.price);
        const change = document.createElement("span"); change.className = tone(quoteData.change); change.textContent = quoteData.price != null ? `${pct(quoteData.change)} · ${quoteData.label}` : "行情更新中";
        quote.append(latest, change);

        const actionItem = actionMap.get(item.symbol);
        const reason = document.createElement("div"); reason.className = "watchlist-stock-reason"; reason.textContent = item.thesis || "尚未形成正式判断；可进入股票研究空间补充。";
        if (item.active_thesis?.version) reason.title = `正式判断版本 ${item.active_thesis.version}`;
        const primaryAction = primaryResearchAction(actionItem);
        const next = document.createElement("div"); next.className = "watchlist-next-action"; next.textContent = item.next_action?.next_step || item.next_action?.title || primaryAction?.next_step || actionItem?.headline || item.latest_change?.summary || "继续观察行情与新增证据";
        next.title = `${Number(item.open_task_count || 0)} 项待处理 · 更新 ${readableTime(quoteData.marketTimestamp || item.latest_change?.created_at || actionItem?.data_as_of || item.market_timestamp)}`;

        const report = reportMap.get(item.symbol);
        const actions = document.createElement("div"); actions.className = "watchlist-stock-actions";
        const researchButton = document.createElement("button"); researchButton.type = "button"; researchButton.className = "icon-button primary-action"; researchButton.textContent = "查看研究";
        researchButton.title = `进入 ${item.name || item.symbol} 的长期研究空间`;
        researchButton.addEventListener("click", event => { event.stopPropagation(); void openDeepStockSymbol(item.symbol); });
        actions.appendChild(researchButton);
        if (report) {
          const reportButton = document.createElement("button"); reportButton.type = "button"; reportButton.className = "icon-button"; reportButton.textContent = "最新报告";
          reportButton.addEventListener("click", event => { event.stopPropagation(); void openResearchReport(item.symbol, reportButton); });
          managementMenu.appendChild(reportButton);
        }
        if (item.relation_type !== "ended") {
          const trackingButton = document.createElement("button"); trackingButton.type = "button"; trackingButton.className = "icon-button"; trackingButton.textContent = item.tracking_status === "paused" ? "恢复跟踪" : "暂停跟踪";
          trackingButton.disabled = !item.workspace_id || !item.version;
          trackingButton.addEventListener("click", event => { event.stopPropagation(); void updateStockAssetRelation(item, {tracking_status: item.tracking_status === "paused" ? "active" : "paused"}); });
          managementMenu.appendChild(trackingButton);
        }
        actions.appendChild(management);
        row.append(identity, quote, reason, next, actions);
        row.addEventListener("click", () => { void loadWatchlistDetail(item, state.watchlistTimeframe); });
        row.addEventListener("keydown", event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); void loadWatchlistDetail(item, state.watchlistTimeframe); } });
        container.appendChild(row);
      }
      if (!state.stockAssets.length) {
        container.innerHTML = '<div class="empty">还没有股票研究资产。点击右上角“添加关注”，或从透明选股保存一条候选线索。</div>';
        $("watchlistDetail").innerHTML = '<div class="empty">添加股票后可查看分时、日线和周线</div>';
        state.selectedWatchlistSymbol = null;
      } else if (!visibleItems.length) {
        container.innerHTML = '<div class="empty">当前关系和状态筛选下没有研究资产。</div>';
      } else {
        const selected = visibleItems.find(item => item.symbol === state.selectedWatchlistSymbol) || visibleItems[0];
        if (state.selectedWatchlistSymbol !== selected.symbol) void loadWatchlistDetail(selected, state.watchlistTimeframe);
      }
      renderWatchlistReports(reportMap);
      renderWatchlistOverview(reportMap);
      renderWatchlistTasks();
      renderWatchlistPulse();
      renderHomeFocus();
      renderAccountCenter();
      const coverage = data.coverage || {};
      const summary = assetsPacket?.summary || {};
      $("watchlistSource").textContent = `共 ${summary.total ?? state.stockAssets.length} 项研究资产；持仓 ${summary.holding ?? state.stockAssets.filter(item => item.relation_type === "holding").length}、关注 ${summary.watching ?? state.stockAssets.filter(item => item.relation_type === "watching").length}、已结束 ${summary.ended ?? state.stockAssets.filter(item => item.relation_type === "ended").length}。当前跟踪行情可用 ${coverage.available || 0}/${coverage.requested || state.watchlist.length}；结束跟踪不会删除判断和历史。`;
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
      if (window.QSCharts?.drawCandles) return window.QSCharts.drawCandles(canvas, points);
      if (!points || !points.length) return;
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
