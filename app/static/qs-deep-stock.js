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

    function boundStockQuickQuestions(session) {
      const name = session?.name || session?.symbol || "这只股票";
      const symbol = session?.symbol || "";
      const target = `${name}${symbol && name !== symbol ? `（${symbol}）` : ""}`;
      const profile = session?.research_entry?.profile_key || "general";
      const prompts = {
        quality: [
          ["为什么入选", `为什么${target}会进入经营改善候选？请逐条核验筛选理由与最新财报，不要把筛选线索当成已确认结论。`],
          ["改善能否持续", `${target}当前的营收和利润改善能否持续？请拆解业务驱动、毛利率、费用率和现金流。`],
          ["一次性因素", `${target}的利润改善中，有多少可能来自一次性损益、会计口径或低基数？`],
          ["反方证据", `只检查会推翻${target}经营改善判断的反方证据和失效条件。`],
          ["下期核验", `${target}下一份财报最需要核验哪三个指标，为什么？`]
        ],
        trend: [
          ["为何强于行业", `${target}近20日为什么强于所属行业？请区分行业驱动、公司事件和交易结构。`],
          ["上涨驱动", `${target}这轮上涨主要是行业共振还是个股因素？请给支持证据和反方证据。`],
          ["量价质量", `${target}当前量价结构是否健康？哪些信号仍需完整交易日确认？`],
          ["估值透支", `${target}的上涨是否已经透支估值或盈利预期？请与同行同口径比较。`],
          ["失效条件", `什么变化会让${target}的相对行业增强逻辑失效？`]
        ],
        value: [
          ["为什么便宜", `${target}为什么看起来估值较低？先核对PE、PB口径和报告期。`],
          ["低估还是变差", `${target}是被低估，还是市场在定价基本面变差？请列支持与反方证据。`],
          ["同行估值", `${target}与同行相比估值处于什么位置？请保持行业和盈利口径一致。`],
          ["盈利与负债", `${target}的盈利质量、现金流和负债是否支持当前估值？`],
          ["低估陷阱", `${target}最可能成为低估值陷阱的风险是什么？`]
        ],
        pullback: [
          ["回撤原因", `${target}近20日回撤的主要原因是什么？请区分市场、行业和公司因素。`],
          ["是否企稳", `${target}近5日企稳是否得到量价确认，还是只是短期反弹？`],
          ["基本面变化", `${target}回撤期间基本面、公告或盈利预期发生了什么变化？`],
          ["确认信号", `${target}还需要哪些完整交易日信号才能确认回撤结束？`],
          ["再次转弱", `什么条件会说明${target}再次转弱，原企稳假设失效？`]
        ],
        general: [
          ["今日涨跌", `${target}今天为什么涨跌？请基于最新可验证行情和事件直接回答。`],
          ["怎么赚钱", `${target}主要靠什么业务赚钱？当前最重要的增长驱动是什么？`],
          ["财务质量", `${target}最新财报的盈利质量和现金流怎么样？`],
          ["估值同行", `${target}当前估值与同行相比处于什么位置？`],
          ["主要风险", `${target}当前最需要警惕的三项反方证据和失效条件是什么？`]
        ]
      };
      return prompts[profile] || prompts.general;
    }

    function syncBoundStockQuickActions(session = state.deepStock) {
      const embedded = stockAgentIsEmbedded();
      document.querySelectorAll("[data-quick-general]").forEach(node => { node.hidden = embedded; });
      const group = $("stockQuickActionGroup");
      const container = $("stockQuickActionButtons");
      group.hidden = !embedded;
      if (!embedded) return;
      container.innerHTML = "";
      for (const [label, message] of boundStockQuickQuestions(session)) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "chip";
        button.textContent = label;
        button.dataset.message = message;
        container.appendChild(button);
      }
      $("quickActions").classList.remove("expanded");
    }

    function renderDeepStock(session) {
      state.deepStock = session || null;
      syncBoundStockQuickActions(session);
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

      const currentStage = session.current_stage || (session.stages || []).find(item => ["in_progress", "needs_review"].includes(item.status));
      if (currentStage) {
        const focus = document.createElement("section"); focus.className = "deep-current-stage";
        const focusLabel = document.createElement("span"); focusLabel.className = "deep-current-stage-label"; focusLabel.textContent = currentStage.status === "needs_review" ? "当前待复核" : "当前研究阶段";
        const focusTitle = document.createElement("strong"); focusTitle.textContent = currentStage.label;
        const focusCopy = document.createElement("p"); focusCopy.textContent = currentStage.description || session.next_question || "继续围绕当前阶段补齐证据。";
        const focusQuestion = document.createElement("button"); focusQuestion.type = "button"; focusQuestion.className = "deep-current-question"; focusQuestion.textContent = session.next_question || currentStage.question || "继续研究当前阶段";
        focusQuestion.addEventListener("click", () => { void continueDeepStockConversation(session.next_question || currentStage.question); });
        focus.append(focusLabel, focusTitle, focusCopy, focusQuestion); main.append(progress, focus);
      } else {
        main.appendChild(progress);
      }

      const stageDetails = document.createElement("details"); stageDetails.className = "deep-stage-details";
      const stageSummary = document.createElement("summary"); stageSummary.textContent = `查看完整研究路线（${session.stages?.length || 7} 个阶段）`;
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
      stageDetails.append(stageSummary, stages); main.appendChild(stageDetails);

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
          report.title || `${symbol}研究报告`,
          workspaceReportReaderBody(workspace),
          `公开证据研究底稿 · 更新于 ${readableTime(report.generated_at)} · 完整日线截至 ${marketDateLabel(report.market_timestamp, timezoneName)}`
        );
        button.textContent = "阅读分析";
      } catch (error) {
        openReader(`${symbol}研究报告`, error?.message || "研究资料正在更新，请稍后重试。", "这份研究报告正在准备，请稍后再看");
        button.textContent = original;
      } finally { button.disabled = false; }
    }
