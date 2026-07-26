async function openDeepStockSymbol(symbol, tabKey = "overview", options = {}) {
      state.pendingDeepStockSymbol = symbol;
      refreshDeepStockSymbolOptions();
      const select = $("deepStockSymbol");
      if (![...select.options].some(option => option.value === symbol)) {
        const option = document.createElement("option"); option.value = symbol; option.textContent = symbol; select.appendChild(option);
      }
      select.value = symbol;
      state.deepStockOverviewSymbol = symbol;
      activateWorkspace("deep_stock", {historyMode: "none", loadStockOverview: false});
      activateStockSpaceTab(tabKey, {historyMode: "none"});
      const session = state.deepStockSessions.find(item => item.symbol === symbol) || null;
      renderDeepStock(session);
      activateStockSpaceTab(tabKey, {historyMode: "none"});
      await loadDeepStockOverview(symbol);
      if ($("deepStockSymbol").value === symbol) state.pendingDeepStockSymbol = null;
      syncWorkspaceUrl(options.historyMode || "push");
    }

    function deepStageStateLabel(status) {
      return {completed: "已完成", needs_review: "待复核", in_progress: "当前阶段", pending: "待研究"}[status] || "待研究";
    }

    function renderDeepStock(session) {
      state.deepStock = session || null;
      const symbol = session?.symbol || $("deepStockSymbol").value || state.deepStockOverviewSymbol || "";
      if (symbol) renderStockSpaceTasks(symbol, session, null, state.stockActionPlans[symbol] || []);
      renderStockSpaceHistory(session, null, state.stockTradeReviews[symbol] || [], symbol);
      const journey = $("deepStockJourney");
      const aiEmpty = $("deepStockContent");
      journey.innerHTML = "";
      aiEmpty.innerHTML = "";
      if (!session) {
        $("deepStockAgent").disabled = true;
        $("deepStockAgent").hidden = true;
        $("deepStockAgent").textContent = "先建立研究";
        $("startDeepStock").hidden = true;
        journey.hidden = true;
        aiEmpty.hidden = false;
        aiEmpty.className = "";
        if (!state.deepStockLoaded) {
          const loading = document.createElement("section"); loading.className = "deep-session-cta";
          loading.setAttribute("aria-live", "polite");
          const copyWrap = document.createElement("div");
          const title = document.createElement("div"); title.className = "deep-session-cta-title"; title.textContent = "正在恢复绑定对话";
          const copy = document.createElement("div"); copy.className = "deep-session-cta-copy"; copy.textContent = "正在读取这只股票已有的研究对话、阶段和证据，不会新建重复会话。";
          const points = document.createElement("div"); points.className = "deep-session-cta-points";
          for (const text of ["恢复历史消息", "同步研究阶段", "核对唯一绑定关系"]) {
            const point = document.createElement("span"); point.className = "deep-session-cta-point"; point.textContent = text; points.appendChild(point);
          }
          copyWrap.append(title, copy, points); loading.appendChild(copyWrap); aiEmpty.appendChild(loading);
          syncAgentPlacement();
          return;
        }
        const cta = document.createElement("section"); cta.className = "deep-session-cta";
        const copyWrap = document.createElement("div");
        const title = document.createElement("div"); title.className = "deep-session-cta-title"; title.textContent = "开始这只股票的 AI 深度研究";
        const copy = document.createElement("div"); copy.className = "deep-session-cta-copy"; copy.textContent = "Agent 会围绕经营、行业、估值、反方证据和风险逐步研究，并把对话、证据缺口与报告持续保存在当前股票下。";
        const points = document.createElement("div"); points.className = "deep-session-cta-points";
        for (const text of ["七阶段研究进度", "证据缺口持续补齐", "报告与对话长期保存"]) {
          const point = document.createElement("span"); point.className = "deep-session-cta-point"; point.textContent = text; points.appendChild(point);
        }
        copyWrap.append(title, copy, points);
        const action = document.createElement("button"); action.type = "button"; action.className = "btn primary"; action.textContent = "建立并打开 AI 研究"; action.addEventListener("click", () => { void continueDeepStockConversation(); });
        cta.append(copyWrap, action); aiEmpty.appendChild(cta);
        syncAgentPlacement();
        return;
      }
      $("deepStockSymbol").value = session.symbol;
      $("deepStockAgent").disabled = false;
      $("deepStockAgent").hidden = true;
      $("deepStockAgent").textContent = "继续与 AI 研究";
      $("startDeepStock").hidden = true;
      journey.hidden = false;
      aiEmpty.hidden = true;
      journey.className = "stock-research-journey deep-stock-body";
      const container = journey;

      const main = document.createElement("div"); main.className = "deep-stock-main";
      const progress = document.createElement("section"); progress.className = "deep-stock-progress";
      const progressHead = document.createElement("div"); progressHead.className = "deep-stock-progress-head";
      const progressIdentity = document.createElement("div");
      const progressValue = document.createElement("div"); progressValue.className = "deep-stock-progress-value"; progressValue.textContent = `研究流程 ${session.progress?.completed || 0}/${session.progress?.total || 7}`;
      const progressMeta = document.createElement("div"); progressMeta.className = "deep-stock-progress-meta";
      progressMeta.textContent = session.current_stage
        ? `${session.current_stage.status === "needs_review" ? "待复核" : "当前"}：${session.current_stage.label} · 绑定对话已有 ${session.conversation?.message_count || 0} 条消息`
        : (session.progress?.completed >= session.progress?.total
          ? "七个阶段已完成，后续继续复核新增证据"
          : `仍有 ${(session.progress?.total || 7) - (session.progress?.completed || 0)} 个阶段待研究或复核`);
      progressIdentity.append(progressValue, progressMeta);
      progressHead.append(progressIdentity);
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
        const review = document.createElement("div"); review.className = "deep-stage-review";
        review.textContent = (item.review_reasons || [])[0] || "";
        review.hidden = item.status !== "needs_review" || !review.textContent;
        const action = document.createElement("span"); action.className = "deep-stage-action"; action.textContent = "点击进入该阶段对话 →";
        card.tabIndex = 0; card.setAttribute("role", "button"); card.setAttribute("aria-label", `${item.label}：进入该阶段对话`);
        card.addEventListener("click", () => { void continueDeepStockConversation(item.question); });
        card.addEventListener("keydown", event => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            void continueDeepStockConversation(item.question);
          }
        });
        card.append(head, title, copy, review, action); stages.appendChild(card);
      }
      main.append(progress, stages);

      const side = document.createElement("aside"); side.className = "deep-stock-side";
      const entry = session.research_entry;
      if (entry) {
        const entryCard = document.createElement("section"); entryCard.className = "deep-stock-card";
        const entryTitle = document.createElement("div"); entryTitle.className = "deep-stock-card-title"; entryTitle.textContent = "本次研究入口";
        const entryCopy = document.createElement("div"); entryCopy.className = "deep-stock-card-copy";
        entryCopy.textContent = `${entry.source_label || "研究候选筛选"}${entry.as_of_date ? ` · 数据日 ${entry.as_of_date}` : ""}。这些是待核验线索，不会自动完成研究阶段。`;
        entryCard.append(entryTitle, entryCopy);
        const entryItems = [
          ...(entry.matched_reasons || []).slice(0, 4).map(value => `命中：${value}`),
          ...(entry.missing_fields || []).slice(0, 4).map(value => `待补：${value}`)
        ];
        if (entryItems.length) {
          const entryList = document.createElement("ul"); entryList.className = "deep-stock-list";
          entryItems.forEach(value => { const li = document.createElement("li"); li.textContent = value; entryList.appendChild(li); });
          entryCard.appendChild(entryList);
        }
        side.appendChild(entryCard);
      }
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
      syncAgentPlacement();
    }

    async function loadDeepStock({force = false} = {}) {
      if (!state.user) return null;
      if (state.deepStockLoadPromise) {
        if (!force) return state.deepStockLoadPromise;
        await state.deepStockLoadPromise;
      }
      if (!force && state.deepStockLoaded) return {items: state.deepStockSessions};
      if (!state.deepStockLoaded && state.workspacePage === "deep_stock") renderDeepStock(null);
      state.deepStockLoadPromise = (async () => {
        try {
          const data = await api("/me/deep-stock?limit=50");
          state.deepStockSessions = data.items || [];
          state.deepStockLoaded = true;
          renderAccountCenter();
          refreshDeepStockSymbolOptions();
          if (state.pendingDeepStockSymbol && [...$("deepStockSymbol").options].some(option => option.value === state.pendingDeepStockSymbol)) {
            $("deepStockSymbol").value = state.pendingDeepStockSymbol;
          } else if (!state.deepStock && state.deepStockSessions.length) {
            $("deepStockSymbol").value = state.deepStockSessions[0].symbol;
          }
          const selected = $("deepStockSymbol").value;
          renderDeepStock(state.deepStockSessions.find(item => item.symbol === selected) || null);
          if (selected === state.pendingDeepStockSymbol) state.pendingDeepStockSymbol = null;
          return data;
        } catch {
          $("deepStockJourney").innerHTML = "";
          $("deepStockContent").className = "deep-stock-empty";
          $("deepStockContent").hidden = false;
          $("deepStockContent").textContent = "个股研究状态正在重新连接。";
          syncAgentPlacement();
          return null;
        } finally {
          state.deepStockLoadPromise = null;
        }
      })();
      return state.deepStockLoadPromise;
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
        await loadDeepStock({force: true});
        await loadDeepStockOverview(symbol);
        return session;
      } catch (error) {
        $("deepStockContent").className = "deep-stock-empty";
        $("deepStockContent").textContent = error.message || "这只股票暂时无法建立研究空间。";
        return null;
      } finally { $("startDeepStock").disabled = false; }
    }

    async function openBoundStockConversation(prefillQuestion = null) {
      const selected = $("deepStockSymbol").value;
      const session = state.deepStock?.symbol === selected
        ? state.deepStock
        : state.deepStockSessions.find(item => item.symbol === selected) || null;
      if (!session?.conversation_id) return false;
      state.deepStock = session;
      if (state.conversationId !== session.conversation_id) {
        await loadConversations(false);
        await openConversation(session.conversation_id, false, "none");
      }
      syncAgentPlacement();
      $("modelTier").value = "deep";
      updateAgentMode();
      if (prefillQuestion) $("chatInput").value = prefillQuestion;
      else if (!$("chatInput").value.trim() && !(state.conversationMessages || []).length) {
        $("chatInput").value = session.next_question || "请继续当前个股研究阶段。";
      }
      $("chatInput").focus();
      return true;
    }

    async function continueDeepStockConversation(prefillQuestion = null, targetSession = null) {
      const session = targetSession || state.deepStock || await startDeepStockSession();
      if (!session?.conversation_id) return;
      state.deepStock = session;
      if (state.workspacePage !== "deep_stock" || $("deepStockSymbol").value !== session.symbol) {
        await openDeepStockSymbol(session.symbol, "ai", {historyMode: "none"});
      } else {
        activateStockSpaceTab("ai", {historyMode: "none"});
      }
      await openBoundStockConversation(prefillQuestion);
      syncWorkspaceUrl("push");
    }

    function workspaceReportReaderBody(workspace) {
      const report = workspace?.latest_report || {};
      const sections = [report.body || report.summary || "报告正文暂不可用。"];
      const dimensions = workspace?.evidence_summary?.dimensions || [];
      if (dimensions.length) {
        const coverageLabels = {sufficient: "充分", partial: "部分", insufficient: "不足", unavailable: "不可用"};
        const rows = dimensions.map(item => {
          const sources = (item.sources || []).map(source => {
            if (typeof source === "string") return source;
            return source?.source_name || source?.name || source?.title || "";
          }).filter(Boolean);
          const asOf = (item.as_of || []).filter(Boolean);
          return `- ${item.label || item.key || "证据维度"}：${coverageLabels[item.coverage_status] || item.coverage_status || "待核验"}${sources.length ? `；来源 ${sources.slice(0, 3).join("、")}` : ""}${asOf.length ? `；时间 ${asOf.slice(0, 3).join("、")}` : ""}`;
        });
        sections.push(`证据覆盖与来源\n${rows.join("\n")}`);
      }
      const counters = (workspace?.counterevidence || []).slice(0, 3).map(item => {
        const dataTime = item.data_time ? `；数据时间 ${String(item.data_time).slice(0, 10)}` : "";
        const source = item.source_name ? `；来源 ${item.source_name}` : "";
        return `- ${item.statement || structuredItemText(item) || "反方证据待核验"}${source}${dataTime}`;
      });
      sections.push(`反方证据\n${counters.length ? counters.join("\n") : "- 当前快照未形成可确认的结构化反方证据，不能据此理解为没有风险。"}`);
      const invalidations = (workspace?.invalidation_conditions || []).slice(0, 5).map(item => `- ${typeof item === "string" ? item : invalidationConditionText(item)}`);
      sections.push(`失效条件\n${invalidations.length ? invalidations.join("\n") : "- 当前快照未形成明确失效条件，相关判断只能视为待核验。"}`);
      const nextEvidence = (workspace?.next_evidence || []).slice(0, 4).map(item => `- ${item.description || item.next_step || structuredItemText(item)}`).filter(item => item !== "- ");
      if (nextEvidence.length) sections.push(`下一步证据\n${nextEvidence.join("\n")}`);
      sections.push("边界\n服务器报告是公共证据快照，不是当前用户的私有判断；报告不会替代 Hermes 即时复核，也不构成目标价或买卖建议。");
      return sections.join("\n\n");
    }

    async function openResearchReport(symbol, button) {
      const original = button.textContent;
      button.disabled = true;
      button.textContent = "读取中…";
      try {
        const workspace = await api(`/v1/stocks/${encodeURIComponent(symbol)}/workspace`);
        const report = workspace.latest_report;
        if (!report) throw new Error("研究报告尚未生成");
        const timezoneName = /\.(?:SS|SZ)$/i.test(symbol || "") ? "Asia/Shanghai" : "America/New_York";
        openReader(
          report.title || `${symbol}研究快照`,
          workspaceReportReaderBody(workspace),
          `服务器公共证据快照 · 生成于 ${readableTime(report.generated_at)} · 完整日线截至 ${marketDateLabel(report.market_timestamp, timezoneName)}`
        );
        button.textContent = "阅读分析";
      } catch (error) {
        openReader(`${symbol}研究快照`, error?.message || "研究证据正在更新，请稍后重试。", "尚未生成可阅读版本；读取不会触发同步生成");
        button.textContent = original;
      } finally { button.disabled = false; }
    }
