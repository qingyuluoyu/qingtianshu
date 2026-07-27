$("agentResumeOpen").addEventListener("click", async event => {
      const button = event.currentTarget;
      const conversationId = button.dataset.conversationId;
      if (!conversationId) return;
      const original = button.textContent;
      button.disabled = true;
      button.textContent = "正在打开…";
      try {
        await openConversation(conversationId, true, "push");
      } catch {
        $("agentResumeMeta").textContent = "这条历史研究暂时无法打开，请稍后重试。";
      } finally {
        button.disabled = false;
        button.textContent = original;
      }
    });
    for (const id of ["conversationSearch", "conversationMobileSearch"]) {
      $(id).addEventListener("input", event => {
        state.conversationQuery = event.currentTarget.value;
        renderConversationList();
      });
    }
    for (const id of ["conversationScopeFilter", "conversationMobileScopeFilter"]) {
      $(id).addEventListener("change", event => {
        state.conversationScope = event.currentTarget.value;
        renderConversationList();
      });
    }
    $("stockScreenerForm").addEventListener("submit", event => {
      event.preventDefault();
      void loadStockScreener();
    });
    document.querySelectorAll("[data-li-zong-filter]").forEach(button => button.addEventListener("click", () => {
      state.liZongFilter = button.dataset.liZongFilter;
      void loadLiZongStrategy();
    }));
    $("liZongHistoryToggle").addEventListener("click", () => {
      state.liZongHistoryExpanded = !state.liZongHistoryExpanded;
      if (state.liZongHistory) renderLiZongHistory(state.liZongHistory);
    });
    document.querySelectorAll("[data-li-zong-backtest-period]").forEach(button => button.addEventListener("click", () => {
      state.liZongBacktestPeriod = button.dataset.liZongBacktestPeriod || "1y";
      void loadLiZongBacktest();
    }));
    document.querySelectorAll("[data-screening-jump]").forEach(button => button.addEventListener("click", () => {
      openScreeningSection(button.dataset.screeningJump || "general");
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
    $("marketDetailToggle").addEventListener("click", () => {
      const expanded = $("marketDashboard").classList.toggle("expanded");
      $("marketDetailToggle").textContent = expanded ? "收起市场结构" : "展开市场结构";
      $("marketDetailToggle").setAttribute("aria-expanded", expanded ? "true" : "false");
    });
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
      activateReviewTab(button.dataset.reviewTab, {historyMode: "push"});
      if (button.dataset.reviewTab === "trades") void loadTradeReviewCenter().catch(() => { $("tradeReviewSummary").textContent = "暂时无法读取交易复盘"; });
    }));
    $("tradeReviewStatus").addEventListener("change", () => { void loadTradeReviewCenter().catch(() => { $("tradeReviewSummary").textContent = "筛选结果暂时无法读取"; }); });
    $("tradeReviewSearch").addEventListener("input", () => {
      window.clearTimeout(state.tradeReviewSearchTimer);
      state.tradeReviewSearchTimer = window.setTimeout(() => { void loadTradeReviewCenter().catch(() => { $("tradeReviewSummary").textContent = "筛选结果暂时无法读取"; }); }, 260);
    });
    [$("reviewRunStatus"), $("reviewRunRepair"), $("reviewRunDays")].forEach(control => {
      control.addEventListener("change", () => { void refreshRunReviews(); });
    });
    $("reviewRunSearch").addEventListener("input", () => {
      window.clearTimeout(state.reviewRunSearchTimer);
      state.reviewRunSearchTimer = window.setTimeout(() => { void refreshRunReviews(); }, 260);
    });
    $("notificationButton").addEventListener("click", event => {
      event.stopPropagation();
      const panel = $("notificationPanel");
      panel.hidden = !panel.hidden;
      $("notificationButton").setAttribute("aria-expanded", panel.hidden ? "false" : "true");
    });
    $("notificationPanel").addEventListener("click", event => event.stopPropagation());
    $("notificationOpenAll").addEventListener("click", () => {
      $("notificationPanel").hidden = true;
      $("notificationButton").setAttribute("aria-expanded", "false");
      activateWorkspace("insights");
    });
    document.addEventListener("click", () => {
      hideGlobalSearch();
      $("notificationPanel").hidden = true;
      $("notificationButton").setAttribute("aria-expanded", "false");
    });

    window.addEventListener("popstate", () => { void restoreWorkspaceRoute(readWorkspaceRoute(), "none"); });

    state.workspaceBootPromise = (async function boot() {
      const initialRoute = readWorkspaceRoute();
      if (initialRoute.page === "screening") {
        state.screeningSection = initialRoute.screeningSection === "li_zong" ? "li_zong" : "general";
      }
      activateWorkspace(initialRoute.page || "insights", {historyMode: "none", scroll: false, trackNavigation: false});
      const bootNavigationVersion = state.workspaceNavigationVersion;
      if (initialRoute.page === "deep_stock") {
        state.pendingDeepStockSymbol = initialRoute.symbol || state.pendingDeepStockSymbol;
        state.deepStockOverviewSymbol = initialRoute.symbol || state.deepStockOverviewSymbol;
        activateStockSpaceTab(initialRoute.stockTab || "overview", {historyMode: "none"});
      } else if (initialRoute.page === "review") {
        activateReviewTab(initialRoute.reviewTab || "trades", {historyMode: "none"});
      }
      connectServerEvents();
      try {
        await Promise.all([loadHealth(), ensureUser()]);
        if (initialRoute.page === "agent") {
          await Promise.all([loadConversations(false, false), loadDeepStock()]);
          if (!state.conversationId && initialRoute.conversationId === "new") {
            startNewConversation(false, "none");
            await loadMemoryCandidates();
          }
          if (state.workspaceNavigationVersion === bootNavigationVersion) {
            await restoreWorkspaceRoute(initialRoute, "replace");
          }
          void Promise.allSettled([
            loadWatchlist(),
            loadTodayOverview(),
            loadMarketDashboard(),
            loadSectors(),
            loadLiveMarkets(),
            loadArticles(),
            loadKnowledge()
          ]);
          return;
        }
        if (initialRoute.page === "screening") {
          if (initialRoute.screeningSection === "li_zong") {
            await loadLiZongStrategy();
          }
          if (state.workspaceNavigationVersion === bootNavigationVersion) {
            await restoreWorkspaceRoute(initialRoute, "replace");
          }
          void Promise.allSettled([
            loadWatchlist(),
            loadTodayOverview(),
            loadMarketDashboard(),
            loadSectors(),
            loadLiveMarkets(),
            loadArticles(),
            loadKnowledge(),
            loadDeepStock(),
            loadConversations(false, false)
          ]);
          return;
        }
        if (initialRoute.page === "review") {
          activateReviewTab(initialRoute.reviewTab || "trades", {historyMode: "none"});
          await loadReviewCenter();
          if (state.workspaceNavigationVersion === bootNavigationVersion) {
            await restoreWorkspaceRoute(initialRoute, "replace");
          }
          return;
        }
        await loadWatchlist();
        await Promise.all([loadTodayOverview(), loadMarketDashboard(), loadSectors(), loadLiveMarkets(), loadArticles(), loadKnowledge(), loadDeepStock()]);
        await loadConversations(false, false);
        if (!state.conversationId) {
          startNewConversation(false, "none");
          await loadMemoryCandidates();
        }
        if (state.workspaceNavigationVersion === bootNavigationVersion) {
          await restoreWorkspaceRoute(initialRoute, "replace");
        }
      } catch (error) {
        $("systemStatus").textContent = "正在重新连接";
        addMessage("agent", "页面正在重新连接数据，请稍后刷新。");
      }
    })().finally(() => { state.workspaceBootReady = true; });
    setInterval(() => {
      liveRefreshRemaining -= 1;
      if (liveRefreshRemaining <= 0) loadLiveMarkets();
      $("liveCountdown").textContent = `${Math.max(0, liveRefreshRemaining)} 秒后刷新`;
    }, 1000);
    setInterval(loadArticles, 60000);
    setInterval(loadTodayOverview, 60000);
    setInterval(() => { loadMarketDashboard(); loadSectors(); }, 60000);
