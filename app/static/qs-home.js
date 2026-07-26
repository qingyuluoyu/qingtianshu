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
      renderAccountCenter();
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
      sessionTag.textContent = state.todayOverview?.session?.label
        ? `A股${state.todayOverview.session.label}`
        : openMarkets.length
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
      $("homeFocusCopy").textContent = state.todayOverview?.summary?.headline || `${marketCopy}${breadthCopy}${researchCopy}`;
    }

    async function openPriorityItem(item) {
      const action = item?.action || {};
      $("notificationPanel").hidden = true;
      $("notificationButton").setAttribute("aria-expanded", "false");
      if (action.type === "open_change_event" && action.link_id) {
        await openChangeEvent(action.link_id);
        return;
      }
      if (action.type === "open_trade_review" && action.review_id) {
        state.pendingTradeReviewId = action.review_id;
        state.reviewTab = "trades";
        $("tradeReviewStatus").value = "";
        $("tradeReviewSearch").value = "";
        activateWorkspace("review");
        return;
      }
      if (item?.symbol) {
        await openDeepStockSymbol(
          item.symbol,
          action.type === "open_stock_tasks" ? "tasks" : "overview"
        );
        return;
      }
      activateWorkspace("agent");
    }

    function renderNotificationCenter(priority) {
      const items = priority?.items || [];
      const count = $("notificationCount");
      count.textContent = String(items.length);
      count.hidden = !items.length;
      const container = $("notificationList"); container.innerHTML = "";
      for (const item of items) {
        const row = document.createElement("button"); row.type = "button"; row.className = "notification-item";
        const title = document.createElement("strong"); title.textContent = item.title || "待处理研究事项";
        const detail = document.createElement("span"); detail.textContent = [item.name || item.symbol, item.rank_reason, item.due_at ? readableTime(item.due_at) : null].filter(Boolean).join(" · ");
        row.append(title, detail);
        row.addEventListener("click", () => { void openPriorityItem(item); });
        container.appendChild(row);
      }
      if (!container.children.length) container.innerHTML = '<div class="notification-empty">今天没有需要立即处理的研究事项。</div>';
    }

    function renderTodayOverview(data) {
      state.todayOverview = data;
      state.todayOverviewAvailable = true;
      $("todayOverviewGrid").hidden = state.workspacePage !== "insights";
      const session = data.session || {};
      const priority = data.priority_items || {};
      const personalized = data.personalized || {};
      const priorityItems = priority.items || [];
      const priorityChangeIds = new Set(
        priorityItems
          .filter(item => item.kind === "change_event" && item.source_ref_id)
          .map(item => String(item.source_ref_id))
      );
      $("todaySessionBadge").textContent = session.label || "状态待确认";
      $("todayPrioritySummary").textContent = priorityItems.length
        ? `${priorityItems.length} 项需要处理；已按风险和时间优先级排序，点击即可继续核验。`
        : (priority.empty_message || "当前没有需要立即处理的个人研究事项。");
      const priorityContainer = $("todayPriorityItems"); priorityContainer.innerHTML = "";
      for (const item of priorityItems) {
        const row = document.createElement("button"); row.type = "button"; row.className = "today-item";
        const title = document.createElement("span"); title.className = "today-item-title"; title.textContent = item.title || "待处理研究事项";
        const badge = document.createElement("span"); badge.className = `today-item-badge ${item.category || "research_task"}`; badge.textContent = item.status_label || "待处理";
        const detail = document.createElement("span"); detail.className = "today-item-detail"; detail.textContent = item.detail || item.rank_reason || "进入研究空间继续核验";
        const meta = document.createElement("span"); meta.className = "today-item-meta";
        const parts = [item.name || item.symbol, item.due_at ? `${item.kind === "trade_review" ? "就绪" : "截止"} ${readableTime(item.due_at)}` : null].filter(Boolean);
        meta.textContent = parts.join(" · "); row.append(title, badge, detail, meta);
        row.addEventListener("click", () => { void openPriorityItem(item); });
        priorityContainer.appendChild(row);
      }
      if (!priorityContainer.children.length) priorityContainer.innerHTML = `<div class="empty">${escapeHtml(priority.empty_message || "当前没有需要立即处理的个人研究事项。")}</div>`;

      const allChanges = personalized.changes || [];
      const changes = allChanges.filter(item => !item.link_id || !priorityChangeIds.has(String(item.link_id)));
      const changesMovedToPriority = allChanges.length - changes.length;
      $("todayChangeCount").textContent = changes.length ? `${changes.length} 项` : changesMovedToPriority ? "已列入待办" : "0 项";
      const changesContainer = $("todayRelatedChanges"); changesContainer.innerHTML = "";
      for (const item of changes) {
        const row = document.createElement("button"); row.type = "button"; row.className = "today-item";
        const title = document.createElement("span"); title.className = "today-item-title"; title.textContent = item.title || item.summary || `${item.symbol || "关注股票"}出现研究变化`;
        const badge = document.createElement("span"); badge.className = `today-item-badge ${item.severity === "high" ? "risk_review" : "research_task"}`; badge.textContent = item.relevance_status_label || (item.severity === "high" ? "优先复核" : "研究变化");
        const detail = document.createElement("span"); detail.className = "today-item-detail"; detail.textContent = item.summary || item.boundary || "变化来自连续研究报告的确定性比较。";
        const meta = document.createElement("span"); meta.className = "today-item-meta"; meta.textContent = [item.name || item.symbol, item.event_type_label, item.event_time ? readableTime(item.event_time) : null, item.data_status_label].filter(Boolean).join(" · ");
        row.append(title, badge, detail, meta);
        row.addEventListener("click", () => {
          if (item.link_id) void openChangeEvent(item.link_id);
          else if (item.symbol) void openDeepStockSymbol(item.symbol);
        });
        changesContainer.appendChild(row);
      }
      if (!changesContainer.children.length) {
        const emptyMessage = changesMovedToPriority
          ? "需要你处理的变化已经归入左侧待办，这里不重复展示。"
          : (personalized.empty_message || "当前没有新的重要变化。");
        changesContainer.innerHTML = `<div class="empty">${escapeHtml(emptyMessage)}</div>`;
      }
      $("todayRelatedBoundary").textContent = changes.length
        ? "点击变化可查看事实、证据和下一步核验。"
        : "新的重要变化出现后，会在这里按事实时间更新。";
      renderNotificationCenter(priority);
      renderHomeFocus();
    }

    async function loadTodayOverview() {
      try { renderTodayOverview(await api("/v1/today/overview")); }
      catch {
        if (!state.todayOverview) {
          state.todayOverviewAvailable = false;
          $("todayOverviewGrid").hidden = true;
        }
      }
    }

    function renderAccountCenter() {
      if (!$("accountPanel")) return;
      const user = state.user || {};
      const pendingCount = state.researchActions.reduce((sum, item) => sum + (item.actions || []).filter(action => ["triggered", "pending_data", "watching"].includes(action.status)).length, 0);
      const healthSummary = state.health?.data_health?.summary || {};
      const background = state.health?.background_jobs || {};
      const userName = user.name || "个人研究空间";
      $("accountAvatar").textContent = userName.trim().slice(0, 1) || "清";
      $("accountName").textContent = userName;
      $("accountMeta").textContent = user.created_at
        ? `个人空间创建于 ${readableTime(user.created_at)} · 当前数据只按该用户恢复`
        : "会话和研究数据只在当前用户空间中恢复。";
      $("accountWatchlistCount").textContent = state.watchlist.length;
      $("accountStockSpaceCount").textContent = state.deepStockSessions.length;
      $("accountConversationCount").textContent = state.conversations.length;
      $("accountKnowledgeCount").textContent = state.knowledge.length;
      $("accountPendingCount").textContent = pendingCount;
      $("accountUserId").textContent = user.id ? `${String(user.id).slice(0, 8)}…` : "—";
      $("accountCreatedAt").textContent = user.created_at ? readableTime(user.created_at) : "—";
      $("accountSessionExpires").textContent = user.session_expires_at
        ? new Intl.DateTimeFormat("zh-CN", {year: "numeric", month: "2-digit", day: "2-digit"}).format(new Date(user.session_expires_at))
        : "当前会话中";
      $("accountResearchMode").textContent = state.health?.hermes_enabled ? "AI 实时研究已启用" : "基础研究可用";
      $("accountDataHealth").textContent = healthSummary.total
        ? `${healthSummary.healthy || 0}/${healthSummary.total} 数据集健康`
        : "正在检查数据";
      $("accountBackgroundJobs").textContent = background.running
        ? "后台刷新正常运行"
        : (background.enabled ? "后台刷新正在启动" : "当前未启用");
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
      renderAccountCenter();
      $("useHermes").disabled = !state.health.hermes_enabled;
      $("useHermes").checked = Boolean(state.health.hermes_enabled);
      $("useHermesLabel").hidden = true;
      renderImageAttachment();
    }
