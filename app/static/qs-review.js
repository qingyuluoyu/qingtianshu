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
        .replace(/指数平均单日变化\s*—+%，代表性指数上涨比例\s*—+。/g, "由于跨市场交易时点不同，暂不计算整体平均涨跌和上涨比例。")
        .replace(/\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})/g, match => readableTime(match))
        .replace(/(代表性指数)?上涨比例\s+(0(?:\.\d+)?|1(?:\.0+)?)(?!%)/g, (_, prefix, ratio) => `${prefix || ""}上涨比例 ${(Number(ratio) * 100).toFixed(1)}%`)
        .replace(/置信度\s+low_to_medium\b/g, "置信度 中等偏低")
        .replace(/置信度\s+medium_to_high\b/g, "置信度 中等偏高")
        .replace(/置信度\s+medium\b/g, "置信度 中等")
        .replace(/置信度\s+low\b/g, "置信度 较低")
        .replace(/置信度\s+high\b/g, "置信度 较高");
    }

    function renderArticles(items = state.insightItems) {
      const container = $("articleFeed");
      container.innerHTML = "";
      const visibleItems = items.filter(item => item.category === "market");
      for (const article of visibleItems) {
        const row = document.createElement("button"); row.className = "article-item";
        const title = document.createElement("span"); title.className = "article-item-title"; title.textContent = article.title || "市场洞察";
        const time = document.createElement("span"); time.className = "article-item-time"; time.textContent = `${article.content_label || "市场短文"} · ${readableTime(article.created_at)}`;
        const summary = document.createElement("span"); summary.className = "article-item-summary"; summary.textContent = humanizeInsightText(article.summary || article.body || "");
        row.append(title, time, summary);
        row.addEventListener("click", () => openReader(article.title, humanizeInsightText(article.body || article.summary), `${article.content_label || "市场洞察"} · ${readableTime(article.created_at)}`));
        container.appendChild(row);
      }
      if (!container.children.length) container.innerHTML = '<div class="empty">新的市场复盘文章正在形成</div>';
      renderMarketReviewCenter(items);
      renderHomeFocus();
    }

    function renderMarketReviewCenter(items = state.insightItems) {
      const container = $("marketReviewList");
      if (!container) return;
      container.innerHTML = "";
      const marketItems = (items || []).filter(item => item.category === "market");
      for (const article of marketItems) {
        const row = document.createElement("button"); row.type = "button"; row.className = "market-review-item";
        const title = document.createElement("strong"); title.textContent = article.title || "市场复盘";
        const time = document.createElement("time"); time.textContent = readableTime(article.created_at);
        const summary = document.createElement("span"); summary.textContent = humanizeInsightText(article.summary || article.body || "");
        row.append(title, time, summary);
        row.addEventListener("click", () => openReader(article.title, humanizeInsightText(article.body || article.summary), `市场复盘 · ${readableTime(article.created_at)}`));
        container.appendChild(row);
      }
      if (!container.children.length) container.innerHTML = '<div class="empty">还没有已保存的市场复盘。新的市场结构记录会按时间出现在这里。</div>';
    }

    async function loadArticles() {
      const [articlesResult, reportsResult, actionsResult] = await Promise.allSettled([
        api("/articles?limit=12"),
        api("/research-reports?limit=12"),
        api("/me/research-actions")
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

    function activateReviewTab(tabName = "trades", options = {}) {
      const allowed = state.evaluationMode
        ? ["trades", "market", "outcomes", "runs", "evidence", "quality"]
        : ["trades", "market"];
      state.reviewTab = allowed.includes(tabName) ? tabName : "trades";
      document.querySelectorAll("[data-review-tab]").forEach(button => {
        const active = button.dataset.reviewTab === state.reviewTab;
        button.classList.toggle("active", active);
        button.setAttribute("aria-selected", active ? "true" : "false");
      });
      document.querySelectorAll("[data-review-panel]").forEach(panel => {
        panel.hidden = panel.dataset.reviewPanel !== state.reviewTab;
      });
      if (state.reviewTab === "market" && state.insightItems.length) renderMarketReviewCenter();
      if (state.workspacePage === "review") syncWorkspaceUrl(options.historyMode || "none");
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
        ["AI 综合", data.timings?.model_seconds],
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

    async function loadReviewCenter() {
      if (state.reviewTab === "market") {
        await loadArticles();
        renderMarketReviewCenter();
        activateReviewTab("market");
        return;
      }
      const results = await Promise.allSettled([
        loadTradeReviewCenter(state.pendingTradeReviewId),
        loadArticles()
      ]);
      if (results[0].status === "rejected") $("tradeReviewSummary").textContent = "暂时无法读取交易复盘";
      renderMarketReviewCenter();
      activateReviewTab(state.reviewTab);
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
        void loadTradeReviewCenter(state.pendingTradeReviewId).catch(() => {
          $("tradeReviewSummary").textContent = "暂时无法读取交易复盘";
        });
        void loadRunReviews().catch(() => { $("reviewRunSummary").textContent = "暂时无法读取回答记录"; });
        activateReviewTab(state.reviewTab);
      }
      catch {
        $("methodBoundary").textContent = "复盘内容正在整理；这不会影响正常研究对话。";
        $("reviewRunSummary").textContent = "暂时无法读取真实 Run";
        $("reviewOutcomeList").innerHTML = '<div class="empty">研究结果暂时无法读取，请稍后重试。</div>';
      }
    }
