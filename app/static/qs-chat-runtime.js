function connectServerEvents() {
      const stream = new EventSource("/events");
      stream.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === "article_published") loadArticles();
          if (data.type === "market_updated") {
            loadLiveMarkets();
            loadMarketDashboard();
            loadSectors();
            loadTodayOverview();
          }
          if (data.type === "research_reports_updated") {
            loadWatchlist();
            loadArticles();
            loadTodayOverview();
            if (state.workspacePage === "review" && state.evaluationMode) loadResearchMethod();
          }
          if (data.type === "evidence_tasks_updated" && state.workspacePage === "review" && state.evaluationMode) loadResearchMethod();
          if (data.type === "stock_strategy_updated" && data.strategy_id === "li_zong") {
            if (state.workspacePage === "screening") void loadLiZongStrategy();
          }
          if (data.type === "stock_strategy_backtest_updated" && data.strategy_id === "li_zong") {
            if (state.workspacePage === "screening") void loadLiZongBacktest();
          }
          if (data.type === "agent_progress" && data.request_id) {
            const request = state.pendingAgentRequests.get(data.request_id);
            const pending = request?.node || request;
            if (pending?.isConnected && data.label) renderStreamingProgress(pending, data.label, data.evidence_progress);
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
        void loadHealth().catch(() => {
          renderSystemHealth(state.health?.data_health || {status: "initializing", user_label: "数据正在同步"});
        });
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
            replaceFinal: true
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

    async function sendChat(message, options = {}) {
      const attachedImage = state.pendingImage;
      const question = message.trim() || (attachedImage ? "请分析这张图片，并说明可验证的观察和不能确认的内容。" : "");
      if (!question) return;
      if (!state.workspaceBootReady && state.workspaceBootPromise) {
        $("sendButton").disabled = true;
        $("sendButton").textContent = "正在恢复对话";
        await state.workspaceBootPromise.catch(() => {});
        $("sendButton").textContent = "发送";
      }
      state.agentContextQuestion = question;
      state.agentResearchRunning = true;
      syncAgentEntryHubVisibility();
      setAgentProcessExpanded(false);
      renderAgentResearchContext(state.agentContextMetadata, question);
      // Saved reports may enrich the evidence packet, but they never replace
      // the live answer generated for the current question.
      const directHermes = Boolean(state.health?.hermes_enabled);
      const requestId = directHermes
        ? (globalThis.crypto?.randomUUID?.() || `chat-${Date.now()}-${Math.random().toString(16).slice(2)}`)
        : null;
      if (!options.reuseUserMessage) {
        addMessage("user", attachedImage ? `已附加图片：${attachedImage.original_name}\n${question}` : question);
      }
      const pending = addMessage(
        "agent",
        directHermes
          ? "AI 正在检索实时证据、资料库和金融研究工具，并针对这个问题生成回答…"
          : "正在读取数据并构建证据…",
        true
      );
      renderStreamingProgress(
        pending,
        directHermes
          ? "正在识别问题，并检索实时证据与资料库…"
          : "正在读取数据并构建证据…"
      );
      let privateStream = null;
      $("sendButton").disabled = true;
      $("attachImage").disabled = true;
      try {
        if (!directHermes) {
          renderAgentFailure(pending, question, null, false);
          return false;
        }
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
            prefer_precomputed: false,
            image_id: attachedImage?.id || null,
            conversation_id: state.conversationId,
            request_id: requestId,
            quality_scope: state.evaluationMode ? "evaluation" : "user"
          })
        });
        state.conversationId = data.conversation_id || state.conversationId;
        if (state.workspacePage === "agent") syncWorkspaceUrl("replace");
        else if (stockAgentIsEmbedded()) syncWorkspaceUrl("replace");
        $("conversationTitle").textContent = data.conversation_title || $("conversationTitle").textContent;
        if (attachedImage) clearImageAttachment();
        const responseMetadata = {
          knowledgeSources: data.knowledge?.items || [],
          marketSources: data.evidence?.market_drivers?.items || [],
          evidenceSources: data.evidence_sources || [],
          structured_answer: data.structured_answer || null,
          intent: data.intent,
          status: data.status,
          researchTargets: diagnosisResearchTargets(data),
          symbol: inferDiagnosisSymbol(data, question),
          marketKey: inferDiagnosisMarketKey(data, question),
          analysisTarget: data.evidence?.analysis_target || null,
          liveAlignment: data.evidence?.live_alignment || null
        };
        state.agentContextMetadata = responseMetadata;
        renderAgentResearchContext(responseMetadata, question);
        let responseNode = pending;
        if (data.intent === "memory_candidate" && data.evidence?.memory) {
          pending.remove();
          responseNode = null;
          renderMemoryCandidate(data.evidence.memory, data.answer || "");
        } else if (data.answer) {
          responseNode = finalizeStreamingMessage(pending, data.answer, responseMetadata);
        }
        else if (data.article) {
          responseNode = finalizeStreamingMessage(
            pending,
            `${data.article.title}\n\n${data.article.summary || data.article.body}\n\n发布状态：${data.decision}`,
            responseMetadata
          );
          await loadArticles();
        } else {
          responseNode = finalizeStreamingMessage(pending, data.reason || "任务已完成。", responseMetadata);
        }
        if (responseNode && data.status !== "completed") {
          appendAgentRunBoundary(responseNode, {
            kind: "degraded",
            title: "本轮仅展示已核验事实",
            copy: "即时解读暂未形成完整结论。已取得的行情与证据仍可查看；研究进度保持不变，可重新提问或继续核验下一条证据。",
            question
          });
        }
        if (["watchlist_update", "watchlist_brief"].includes(data.intent)) await loadWatchlist();
        if (["research_priority", "research_outcome"].includes(data.intent)) await loadKnowledge();
        if (data.deep_stock_session) {
          state.deepStock = data.deep_stock_session;
          const index = state.deepStockSessions.findIndex(item => item.symbol === data.deep_stock_session.symbol);
          if (index >= 0) state.deepStockSessions[index] = data.deep_stock_session;
          else state.deepStockSessions.unshift(data.deep_stock_session);
          renderDeepStock(data.deep_stock_session);
        }
        await maybeUpdateDiagnosis(data, question);
        await loadConversations(false);
        return data.status === "completed";
      } catch (error) {
        renderAgentFailure(pending, question, error, true);
        return false;
      } finally {
        if (requestId) {
          privateStream?.source?.close();
          state.pendingAgentRequests.delete(requestId);
        }
        state.agentResearchRunning = false;
        syncAgentEntryHubVisibility();
        setAgentProcessExpanded(false);
        renderAgentResearchContext(state.agentContextMetadata, state.agentContextQuestion);
        $("sendButton").textContent = "发送";
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
    $("agentMarketDiagnosis").addEventListener("click", () => { void runMarketDiagnosisEntry(); });
    $("agentStockDiagnosisForm").addEventListener("submit", event => {
      event.preventDefault();
      void runStockDiagnosisEntry($("agentStockDiagnosisQuery").value);
    });
    $("deepStockSymbol").addEventListener("change", () => {
      const symbol = $("deepStockSymbol").value;
      state.deepStockOverviewSymbol = symbol;
      const session = state.deepStockSessions.find(item => item.symbol === symbol) || null;
      activateStockSpaceTab("overview", {historyMode: "none"});
      renderDeepStock(session);
      activateStockSpaceTab("overview", {historyMode: "none"});
      void loadDeepStockOverview(symbol).then(() => syncWorkspaceUrl("push"));
    });
    document.querySelectorAll("[data-stock-space-tab]").forEach(button => button.addEventListener("click", () => {
      activateStockSpaceTab(button.dataset.stockSpaceTab || "overview", {historyMode: "push"});
    }));
    $("addWatchlist").addEventListener("click", () => {
      resetWatchlistForm();
      $("watchlistAddForm").hidden = false;
      $("watchlistSymbol").focus();
    });
    $("watchlistAgentBrief").addEventListener("click", () => { void runWatchlistAgentBrief(); });
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
    $("watchlistSecondaryFilter").addEventListener("change", event => {
      state.watchlistSecondaryFilter = event.currentTarget.value || "all";
      void loadWatchlist();
    });
    $("globalSearch").addEventListener("input", event => {
      const query = event.currentTarget.value.trim();
      window.clearTimeout(state.globalSearchTimer);
      if (!query) { hideGlobalSearch(); return; }
      state.globalSearchTimer = window.setTimeout(() => { void performGlobalSearch(query); }, 260);
    });
    $("globalSearch").addEventListener("keydown", event => {
      if (event.isComposing) return;
      if (event.key === "ArrowDown") {
        event.preventDefault();
        setGlobalSearchActive(state.globalSearchActiveIndex + 1);
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        setGlobalSearchActive(state.globalSearchActiveIndex <= 0 ? state.globalSearchItems.length - 1 : state.globalSearchActiveIndex - 1);
      } else if (event.key === "Enter") {
        event.preventDefault();
        const item = state.globalSearchActiveIndex >= 0
          ? state.globalSearchItems[state.globalSearchActiveIndex]
          : null;
        if (item) void openGlobalSearchItem(item);
        else if (event.currentTarget.value.trim()) void openGlobalSearchPage(event.currentTarget.value.trim());
      } else if (event.key === "Escape") {
        hideGlobalSearch();
      }
    });
    $("globalSearchResults").addEventListener("click", event => event.stopPropagation());
    $("searchAskAi").addEventListener("click", () => openAiFromSearch());
    $("searchPageBack").addEventListener("click", () => activateWorkspace("insights"));
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
    $("readerEventRelevant").addEventListener("click", () => { void setReaderChangeRelevance("relevant"); });
    $("readerEventIrrelevant").addEventListener("click", () => { void setReaderChangeRelevance("irrelevant"); });
    $("readerContinue").addEventListener("click", () => {
      const context = state.readerContext;
      closeReader();
      prepareAgentQuestion(
        context?.agentQuestion
          || `请结合当前资料继续研究“${context?.title || "这项内容"}”，说明它与当前判断的关系、反方证据和下一步需要核验什么。`
      );
    });
    $("readerBackdrop").addEventListener("click", event => {
      if (event.target === $("readerBackdrop")) closeReader();
    });
    document.addEventListener("keydown", event => {
      if (event.key === "Escape") closeReader();
    });
    $("newConversation").addEventListener("click", () => startNewConversation(true));
    $("agentHistoryNew").addEventListener("click", () => startNewConversation(true));
