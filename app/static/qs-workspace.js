function readWorkspaceRoute() {
      const path = window.location.pathname.replace(/\/+$/, "") || "/";
      const params = new URLSearchParams(window.location.search);
      if (path === "/watchlist") return {page: "watchlist"};
      if (path === "/account") return {page: "account"};
      if (path === "/knowledge") return {page: "knowledge"};
      if (path === "/search") return {page: "search", query: params.get("q") || ""};
      if (path === "/reviews") return {page: "review", reviewTab: params.get("tab") || "trades", reviewId: params.get("review") || null};
      if (path.startsWith("/stocks/")) {
        let symbol = path.slice("/stocks/".length);
        try { symbol = decodeURIComponent(symbol); } catch {}
        return {page: "deep_stock", symbol, stockTab: params.get("tab") || "overview"};
      }
      if (path === "/research" && params.get("mode") === "screening") {
        return {
          page: "screening",
          screeningSection: params.get("section") === "li_zong" ? "li_zong" : "general"
        };
      }
      if (path === "/research" || path.startsWith("/research/")) {
        let conversationId = path.startsWith("/research/") ? path.slice("/research/".length) : "new";
        try { conversationId = decodeURIComponent(conversationId); } catch {}
        return {page: "agent", conversationId, question: params.get("question") || ""};
      }
      return {page: "insights"};
    }

    function workspaceUrl(page = state.workspacePage) {
      if (page === "watchlist") return "/watchlist";
      if (page === "account") return "/account";
      if (page === "knowledge") return "/knowledge";
      if (page === "search") return `/search?q=${encodeURIComponent(state.searchQuery || "")}`;
      if (page === "screening") {
        const params = new URLSearchParams({mode: "screening"});
        if (state.screeningSection === "li_zong") params.set("section", "li_zong");
        return `/research?${params.toString()}`;
      }
      if (page === "agent") return `/research/${encodeURIComponent(state.conversationId || "new")}`;
      if (page === "review") {
        const params = new URLSearchParams({tab: state.reviewTab || "trades"});
        if (state.selectedTradeReviewId && state.reviewTab === "trades") params.set("review", state.selectedTradeReviewId);
        return `/reviews?${params.toString()}`;
      }
      if (page === "deep_stock") {
        const symbol = state.deepStockOverviewSymbol || $("deepStockSymbol")?.value || state.pendingDeepStockSymbol;
        if (!symbol) return "/stocks/000063.SZ";
        const params = new URLSearchParams({tab: state.stockSpaceTab || "overview"});
        return `/stocks/${encodeURIComponent(symbol)}?${params.toString()}`;
      }
      return "/today";
    }

    function syncWorkspaceUrl(mode = "push") {
      if (mode === "none") return;
      const target = workspaceUrl();
      const current = `${window.location.pathname}${window.location.search}`;
      if (target === current) return;
      const method = mode === "replace" ? "replaceState" : "pushState";
      window.history[method]({qingshu: true}, "", target);
    }

    function stockAgentIsEmbedded() {
      return state.workspacePage === "deep_stock"
        && state.stockSpaceTab === "ai"
        && Boolean(state.deepStock?.conversation_id);
    }

    function syncAgentPlacement() {
      const agent = $("agentSection");
      const embedded = stockAgentIsEmbedded();
      if (embedded) {
        const aiPane = $("stockSpaceAiPane");
        const journey = $("deepStockJourney");
        if (agent.parentElement !== aiPane || agent.nextElementSibling !== journey) aiPane.insertBefore(agent, journey);
      } else if (agent.previousElementSibling !== $("agentSectionHome")) {
        $("agentSectionHome").after(agent);
      }
      const visible = state.workspacePage === "agent" || embedded;
      agent.hidden = !visible;
      document.body.classList.toggle("agent-page", visible);
      document.body.classList.toggle("stock-agent-page", embedded);
      if (typeof syncBoundStockQuickActions === "function") {
        syncBoundStockQuickActions(state.deepStock);
      }
    }

    function syncReviewModeVisibility() {
      document.querySelectorAll("[data-review-whitebox]").forEach(node => {
        node.hidden = !state.evaluationMode;
      });
    }

    function activateWorkspace(page = "insights", options = {}) {
      const pages = {
        insights: ["市场总览", "全球行情、A股全景、行业轮动与个人研究脉冲"],
        search: ["搜索", "查找股票、行业和已保存的个人研究资产"],
        agent: ["AI 投研对话", "连续对话、历史研究、自动 K 线与证据链"],
        screening: ["AI 研究 · 透明选股", "用确定性规则生成可解释研究候选，再进入个股空间继续核验"],
        deep_stock: ["个股研究", "围绕一只股票持续保存判断、变化、证据、任务、对话和报告"],
        watchlist: ["我的关注", "按关系、优先级和跟踪状态管理长期股票研究资产"],
        knowledge: ["金融资料库", "集中查看通用研究资料与个人资料，并管理可被 Agent 检索的内容"],
        review: ["复盘中心", "跟踪研究结论、后续验证与风险变化"],
        account: ["个人中心", "查看个人空间、研究资产、资料用量与真实服务状态"]
      };
      if (!pages[page]) page = "insights";
      if (options.trackNavigation !== false) state.workspaceNavigationVersion += 1;
      state.workspacePage = page;
      const insightsVisible = page === "insights";
      $("homeFocus").hidden = !insightsVisible;
      $("todayOverviewGrid").hidden = !insightsVisible || !state.todayOverviewAvailable;
      $("liveSection").hidden = !insightsVisible;
      $("marketDashboard").hidden = !insightsVisible;
      $("insightSection").hidden = !insightsVisible;
      $("insightAsk").hidden = !insightsVisible;
      $("searchPanel").hidden = page !== "search";
      $("watchlistPanel").hidden = page !== "watchlist";
      $("stockScreenerPanel").hidden = page !== "screening";
      $("deepStockPanel").hidden = page !== "deep_stock";
      $("knowledgePanel").hidden = page !== "knowledge";
      $("accountPanel").hidden = page !== "account";
      $("methodSection").hidden = page !== "review";
      $("productNotice").hidden = page === "agent" || page === "review";
      syncAgentPlacement();
      syncAgentEntryHubVisibility();
      document.body.classList.toggle("review-page", page === "review");
      $("workspaceTitle").textContent = pages[page][0];
      $("workspaceSubtitle").textContent = pages[page][1];
      const activeNavigationPage = page === "screening" ? "agent" : page;
      let activeNavigationButton = null;
      for (const button of document.querySelectorAll(".nav-item[data-page]")) {
        const active = button.dataset.page === activeNavigationPage;
        button.classList.toggle("active", active);
        if (active) activeNavigationButton = button;
      }
      if (activeNavigationButton && window.matchMedia("(max-width: 600px)").matches) {
        requestAnimationFrame(() => {
          const mobileNavigation = activeNavigationButton.closest(".sidebar");
          if (!mobileNavigation) return;
          const navigationRect = mobileNavigation.getBoundingClientRect();
          const buttonRect = activeNavigationButton.getBoundingClientRect();
          const centeredLeft = mobileNavigation.scrollLeft
            + buttonRect.left - navigationRect.left
            - (mobileNavigation.clientWidth - buttonRect.width) / 2;
          mobileNavigation.scrollLeft = Math.max(0, centeredLeft);
        });
      }
      updateAgentMode();
      if (page === "agent" && state.conversationMessages.length) {
        requestAnimationFrame(() => { void syncDiagnosisFromConversation(state.conversationMessages); });
      }
      if (page === "review") {
        syncReviewModeVisibility();
        if (state.user) {
          if (state.evaluationMode) void loadResearchMethod();
          else void loadReviewCenter();
        }
      }
      if (page === "watchlist") void loadWatchlist();
      if (page === "screening") {
        syncScreeningSection({load: Boolean(state.user)});
      }
      if (page === "deep_stock") {
        if (state.user) {
          const stockLoad = loadDeepStock();
          if (options.loadStockOverview !== false) {
            void stockLoad.then(() => {
              if (state.workspacePage !== "deep_stock") return;
              const symbol = $("deepStockSymbol").value;
              if (symbol) void loadDeepStockOverview(symbol);
            });
          }
        }
      }
      if (page === "knowledge") void loadKnowledge();
      if (page === "account") {
        renderAccountCenter();
        void loadRiskProfile();
      }
      syncWorkspaceUrl(options.historyMode || "push");
      if (options.scroll !== false) window.scrollTo({top: 0, behavior: "smooth"});
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
      if (!response.ok) {
        const detail = Array.isArray(payload.detail)
          ? payload.detail.map(item => item?.msg || item?.message || "请求参数未通过校验").join("；")
          : payload.detail;
        const error = new Error(typeof detail === "string" ? detail : `请求失败：${response.status}`);
        error.status = response.status;
        error.payload = payload;
        throw error;
      }
      return payload;
    }

    function hideGlobalSearch() {
      window.clearTimeout(state.globalSearchTimer);
      state.globalSearchToken += 1;
      $("globalSearchResults").hidden = true;
      $("globalSearch").setAttribute("aria-expanded", "false");
      state.globalSearchItems = [];
      state.globalSearchActiveIndex = -1;
    }

    function setGlobalSearchActive(index) {
      if (!state.globalSearchItems.length) return;
      const next = Math.max(0, Math.min(index, state.globalSearchItems.length - 1));
      state.globalSearchActiveIndex = next;
      $("globalSearchResults").querySelectorAll(".global-search-item").forEach((node, nodeIndex) => {
        const active = nodeIndex === next;
        node.classList.toggle("active", active);
        node.setAttribute("aria-selected", active ? "true" : "false");
        if (active) node.scrollIntoView({block: "nearest"});
      });
    }

    async function openGlobalSearchItem(item) {
      hideGlobalSearch();
      $("globalSearch").value = "";
      if (item.type === "stock" || item.type === "workspace") {
        await openDeepStockSymbol(item.symbol);
        return;
      }
      if (item.type === "conversation") {
        await openConversation(item.id, true);
        return;
      }
      if (item.type === "review") {
        state.pendingTradeReviewId = item.id;
        activateWorkspace("review", {historyMode: "none"});
        activateReviewTab("trades", {historyMode: "none"});
        await loadTradeReviewCenter(item.id);
        syncWorkspaceUrl("push");
        return;
      }
      if (item.type === "industry") {
        state.screeningSection = "general";
        activateWorkspace("screening", {historyMode: "none"});
        syncScreeningSection({load: false});
        $("stockScreenIndustry").value = item.industry || item.title || "";
        await loadStockScreener();
        syncWorkspaceUrl("push");
      }
    }

    function openAiFromSearch(query = state.searchQuery) {
      const question = String(query || "").trim();
      startNewConversation(true);
      $("chatInput").value = question
        ? `请研究“${question}”，先识别对象，再说明当前事实、核心驱动、反方证据和下一步核验项。`
        : "";
      $("chatInput").focus();
    }

    function appendGlobalSearchActions(container, query, hasResults) {
      const actions = document.createElement("div"); actions.className = "global-search-actions";
      const all = document.createElement("button"); all.type = "button"; all.className = "btn"; all.textContent = hasResults ? "查看全部结果" : "打开搜索页";
      all.addEventListener("click", () => { void openGlobalSearchPage(query); });
      const ask = document.createElement("button"); ask.type = "button"; ask.className = "btn primary"; ask.textContent = "向 AI 提问";
      ask.addEventListener("click", () => openAiFromSearch(query));
      actions.append(all, ask); container.appendChild(actions);
    }

    function renderGlobalSearch(data, query) {
      const container = $("globalSearchResults");
      container.innerHTML = "";
      state.globalSearchItems = [];
      state.globalSearchActiveIndex = -1;
      const icons = {stock: "股", industry: "业", workspace: "研", conversation: "聊", review: "盘", ai: "AI"};
      for (const group of (data.groups || [])) {
        const section = document.createElement("section"); section.className = "global-search-group";
        const label = document.createElement("div"); label.className = "global-search-group-title"; label.textContent = group.label;
        section.appendChild(label);
        for (const item of (group.items || [])) {
          const index = state.globalSearchItems.length;
          state.globalSearchItems.push(item);
          const button = document.createElement("button"); button.type = "button"; button.className = "global-search-item"; button.dataset.searchIndex = String(index); button.setAttribute("role", "option"); button.setAttribute("aria-selected", "false");
          const icon = document.createElement("span"); icon.className = "global-search-item-icon"; icon.textContent = icons[item.type] || "搜";
          const copy = document.createElement("span"); copy.className = "global-search-item-copy";
          const title = document.createElement("span"); title.className = "global-search-item-title"; title.textContent = item.title || "搜索结果";
          const subtitle = document.createElement("span"); subtitle.className = "global-search-item-subtitle"; subtitle.textContent = item.subtitle || "打开查看";
          copy.append(title, subtitle); button.append(icon, copy); button.addEventListener("click", () => { void openGlobalSearchItem(item); }); section.appendChild(button);
        }
        container.appendChild(section);
      }
      if (!state.globalSearchItems.length) {
        const empty = document.createElement("div"); empty.className = "global-search-status"; empty.textContent = `没有找到与“${query}”匹配的股票、行业或已保存研究。`;
        container.appendChild(empty);
      }
      appendGlobalSearchActions(container, query, Boolean(state.globalSearchItems.length));
      container.hidden = false;
      $("globalSearch").setAttribute("aria-expanded", "true");
    }

    function renderSearchPage(data, query) {
      state.searchQuery = query;
      state.searchResults = data;
      $("searchPageTitle").textContent = `搜索“${query}”`;
      $("searchPageSummary").textContent = "结果按股票、行业和你的研究资产分组；任何搜索都不会自动创建对话或运行 Agent。";
      $("searchPageStatus").textContent = data.total
        ? `共找到 ${data.total} 个结果。选择一个对象继续查看。`
        : "没有匹配的已存对象。你可以修改关键词，或主动选择向 AI 提问。";
      const container = $("searchPageGroups"); container.innerHTML = "";
      const icons = {stock: "股", industry: "业", workspace: "研", conversation: "聊", review: "盘"};
      for (const group of (data.groups || [])) {
        const section = document.createElement("section"); section.className = "search-page-group";
        const heading = document.createElement("div"); heading.className = "search-page-group-title"; heading.textContent = group.label;
        const count = document.createElement("span"); count.textContent = `${(group.items || []).length} 项`; heading.appendChild(count);
        const list = document.createElement("div"); list.className = "search-page-list";
        for (const item of (group.items || [])) {
          const button = document.createElement("button"); button.type = "button"; button.className = "search-page-item";
          const icon = document.createElement("span"); icon.className = "global-search-item-icon"; icon.textContent = icons[item.type] || "搜";
          const copy = document.createElement("span"); copy.className = "global-search-item-copy";
          const title = document.createElement("span"); title.className = "global-search-item-title"; title.textContent = item.title || "搜索结果";
          const subtitle = document.createElement("span"); subtitle.className = "global-search-item-subtitle"; subtitle.textContent = item.subtitle || "打开查看";
          copy.append(title, subtitle); button.append(icon, copy); button.addEventListener("click", () => { void openGlobalSearchItem(item); }); list.appendChild(button);
        }
        section.append(heading, list); container.appendChild(section);
      }
    }

    async function openGlobalSearchPage(query, options = {}) {
      const normalized = String(query || "").trim();
      if (!normalized) return;
      hideGlobalSearch();
      state.searchQuery = normalized;
      $("globalSearch").value = normalized;
      activateWorkspace("search", {historyMode: "none"});
      $("searchPageTitle").textContent = `搜索“${normalized}”`;
      $("searchPageStatus").textContent = "正在查找股票、行业和你的研究记录…";
      $("searchPageGroups").innerHTML = "";
      try {
        const data = await api(`/v1/search?q=${encodeURIComponent(normalized)}&limit=20`);
        renderSearchPage(data, normalized);
      } catch {
        $("searchPageStatus").textContent = "搜索暂时未完成，请稍后重试。";
      }
      syncWorkspaceUrl(options.historyMode || "push");
    }

    async function performGlobalSearch(query) {
      const token = ++state.globalSearchToken;
      const container = $("globalSearchResults");
      container.innerHTML = '<div class="global-search-status">正在搜索股票和你的研究记录…</div>';
      container.hidden = false;
      $("globalSearch").setAttribute("aria-expanded", "true");
      try {
        const data = await api(`/v1/search?q=${encodeURIComponent(query)}&limit=8`);
        if (token !== state.globalSearchToken) return;
        renderGlobalSearch(data, query);
      } catch {
        if (token !== state.globalSearchToken) return;
        container.innerHTML = '<div class="global-search-status">搜索暂时未完成，请稍后重试。</div>';
      }
    }

    async function restoreWorkspaceRoute(route, historyMode = "none") {
      if (route.page === "search" && route.query) {
        await openGlobalSearchPage(route.query, {historyMode});
        return;
      }
      if (route.page === "deep_stock" && route.symbol) {
        await openDeepStockSymbol(route.symbol, route.stockTab || "overview", {historyMode});
        return;
      }
      if (route.page === "agent") {
        activateWorkspace("agent", {historyMode: "none", scroll: false});
        if (route.conversationId && route.conversationId !== "new") {
          try { await openConversation(route.conversationId, false, historyMode); }
          catch { startNewConversation(false, historyMode); }
        } else {
          startNewConversation(false, historyMode);
        }
        if (route.question) $("chatInput").value = route.question;
        return;
      }
      if (route.page === "review") {
        activateWorkspace("review", {historyMode: "none", scroll: false});
        activateReviewTab(route.reviewTab || "trades", {historyMode: "none"});
        if (state.reviewTab === "trades") {
          state.pendingTradeReviewId = route.reviewId || null;
          await loadTradeReviewCenter(route.reviewId || null).catch(() => {});
        }
        syncWorkspaceUrl(historyMode);
        return;
      }
      if (route.page === "screening") {
        state.screeningSection = route.screeningSection === "li_zong" ? "li_zong" : "general";
      }
      activateWorkspace(route.page || "insights", {historyMode, scroll: false});
    }
