function liZongStatusLabel(value) {
      return {
        qualified: "候选待观察",
        triggered: "今日触发",
        near_8_of_9: "接近满足 8/9",
        watch_6_7_of_9: "研究观察 6–7/9",
        data_incomplete: "数据待补",
        invalidated: "规则已失效",
        not_qualified: "未满足"
      }[value] || "待核验";
    }

    function liZongRuleLabel(value) {
      return {
        "LZ-F-01": "总市值严格大于150亿元",
        "LZ-F-02": "连续五个完整年度ROE达标",
        "LZ-F-04": "非自然人股东至少5名",
        "LZ-C-01": "近一年至少6次收盘涨停",
        "LZ-C-02": "近一年出现连续两日涨停",
        "LZ-C-03": "近十日存在收盘涨停",
        "LZ-C-04": "近十日无5%阴线",
        "LZ-VP-01": "近二十日出现360日复权新高",
        "LZ-VP-02": "连续三日成交量达到基准两倍",
        "LZ-T-01": "当日收盘涨停",
        "LZ-T-02": "高开至少3.5%且收阳",
        "LZ-T-03": "振幅严格大于9.8%且收阳"
      }[value] || value;
    }

    function liZongRuleStatus(value) {
      return {passed: "通过", failed: "未通过", data_incomplete: "数据不完整"}[value] || "待核验";
    }

    function strategyShortValue(value) {
      if (value === null || value === undefined) return "—";
      if (typeof value === "number") return numeric(value);
      if (typeof value === "string") return value;
      const text = JSON.stringify(value, null, 0);
      return text.length > 220 ? `${text.slice(0, 220)}…` : text;
    }

    function showLiZongDetail(item) {
      const observationBand = item.observation_band || null;
      const lines = [
        `# ${item.name || item.internal_symbol}｜李总策略逐规则证据`,
        `策略版本：${item.strategy_version || "—"}；参数版本：${item.parameter_version || "—"}；数据交易日：${item.as_of_date || "待确认"}`,
        "",
        ...(observationBand
          ? [
              `观察分层：${liZongStatusLabel(observationBand)}；已通过 ${item.candidate_rule_pass_count || 0}/${item.candidate_rule_total || 9} 条候选规则。`,
              `明确未通过：${(item.failed_candidate_rule_ids || []).map(liZongRuleLabel).join("、") || "待确认"}。`,
              "该分层只用于研究排序，不是候选或触发标的，严格规则没有放宽。",
              ""
            ]
          : []),
        "## 规则核验"
      ];
      (item.rule_results || []).forEach(rule => {
        lines.push(`- ${rule.rule_id} ${liZongRuleLabel(rule.rule_id)}｜${liZongRuleStatus(rule.status)}`);
        lines.push(`  实际值：${strategyShortValue(rule.actual_value)}`);
        lines.push(`  阈值：${strategyShortValue(rule.threshold)}`);
        lines.push(`  证据时间：${rule.evidence_date || rule.report_period || "待确认"}；来源：${rule.source || "待确认"}；公式：${rule.formula_version || "—"}`);
        (rule.limitations || []).forEach(value => lines.push(`  限制：${value}`));
      });
      if (item.limitations?.length) {
        lines.push("", "## 当前边界", ...item.limitations.map(value => `- ${value}`));
      }
      lines.push("", `- ${item.boundary || "仅用于研究候选和人工复核。"}`);
      openReader(`${item.name || item.internal_symbol}｜李总策略证据`, lines.join("\n"), `${liZongStatusLabel(observationBand || item.status)} · ${item.as_of_date || "数据时间待确认"}`);
    }

    function createLiZongHistoryChart(path) {
      const points = (path || []).filter(item => Number.isFinite(Number(item.stock_return_pct)) && Number.isFinite(Number(item.benchmark_return_pct)));
      if (points.length < 2) return null;
      const values = points.flatMap(item => [Number(item.stock_return_pct), Number(item.benchmark_return_pct), 0]);
      const min = Math.min(...values); const max = Math.max(...values); const span = Math.max(1, max - min);
      const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      svg.setAttribute("viewBox", "0 0 320 74"); svg.classList.add("li-zong-history-chart"); svg.setAttribute("role", "img"); svg.setAttribute("aria-label", "信号后个股与沪深300累计收益走势");
      const coordinates = key => points.map((item, index) => {
        const x = 8 + index * (304 / Math.max(1, points.length - 1));
        const y = 66 - ((Number(item[key]) - min) / span) * 58;
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      }).join(" ");
      const zero = document.createElementNS("http://www.w3.org/2000/svg", "line");
      const zeroY = 66 - ((0 - min) / span) * 58;
      zero.setAttribute("x1", "8"); zero.setAttribute("x2", "312"); zero.setAttribute("y1", zeroY.toFixed(1)); zero.setAttribute("y2", zeroY.toFixed(1)); zero.setAttribute("stroke", "#dbe3ee"); zero.setAttribute("stroke-width", "1");
      const benchmark = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
      benchmark.setAttribute("points", coordinates("benchmark_return_pct")); benchmark.setAttribute("fill", "none"); benchmark.setAttribute("stroke", "#9aa9bc"); benchmark.setAttribute("stroke-width", "2");
      const stock = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
      stock.setAttribute("points", coordinates("stock_return_pct")); stock.setAttribute("fill", "none"); stock.setAttribute("stroke", "#3673d9"); stock.setAttribute("stroke-width", "2.4");
      svg.append(zero, benchmark, stock); return svg;
    }

    function createLiZongBacktestChart(points) {
      const rows = (points || []).filter(item => Number.isFinite(Number(item.return_pct)) && Number.isFinite(Number(item.benchmark_return_pct)));
      if (rows.length < 2) return null;
      const sampled = rows.length > 380 ? rows.filter((_, index) => index % Math.ceil(rows.length / 380) === 0 || index === rows.length - 1) : rows;
      const values = sampled.flatMap(item => [Number(item.return_pct), Number(item.benchmark_return_pct), 0]);
      const min = Math.min(...values); const max = Math.max(...values); const span = Math.max(1, max - min);
      const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      svg.setAttribute("viewBox", "0 0 720 190"); svg.setAttribute("role", "img"); svg.setAttribute("aria-label", "李总策略等权组合与沪深300历史累计收益曲线");
      const coordinates = key => sampled.map((item, index) => {
        const x = 42 + index * (650 / Math.max(1, sampled.length - 1));
        const y = 166 - ((Number(item[key]) - min) / span) * 138;
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      }).join(" ");
      const zero = document.createElementNS("http://www.w3.org/2000/svg", "line");
      const zeroY = 166 - ((0 - min) / span) * 138;
      zero.setAttribute("x1", "42"); zero.setAttribute("x2", "692"); zero.setAttribute("y1", zeroY.toFixed(1)); zero.setAttribute("y2", zeroY.toFixed(1)); zero.setAttribute("class", "zero-line");
      const benchmark = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
      benchmark.setAttribute("points", coordinates("benchmark_return_pct")); benchmark.setAttribute("class", "benchmark-line");
      const strategy = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
      strategy.setAttribute("points", coordinates("return_pct")); strategy.setAttribute("class", "strategy-line");
      const start = document.createElementNS("http://www.w3.org/2000/svg", "text"); start.setAttribute("x", "42"); start.setAttribute("y", "184"); start.textContent = sampled[0].trade_date || "";
      const end = document.createElementNS("http://www.w3.org/2000/svg", "text"); end.setAttribute("x", "692"); end.setAttribute("y", "184"); end.setAttribute("text-anchor", "end"); end.textContent = sampled.at(-1).trade_date || "";
      const high = document.createElementNS("http://www.w3.org/2000/svg", "text"); high.setAttribute("x", "36"); high.setAttribute("y", "31"); high.setAttribute("text-anchor", "end"); high.textContent = `${max.toFixed(1)}%`;
      const low = document.createElementNS("http://www.w3.org/2000/svg", "text"); low.setAttribute("x", "36"); low.setAttribute("y", "169"); low.setAttribute("text-anchor", "end"); low.textContent = `${min.toFixed(1)}%`;
      svg.append(zero, benchmark, strategy, start, end, high, low); return svg;
    }

    function renderLiZongBacktest(payload) {
      state.liZongBacktest = payload;
      const period = payload?.selected_period || state.liZongBacktestPeriod || "1y";
      state.liZongBacktestPeriod = period;
      document.querySelectorAll("[data-li-zong-backtest-period]").forEach(button => {
        const active = button.dataset.liZongBacktestPeriod === period;
        button.classList.toggle("active", active); button.setAttribute("aria-selected", String(active));
      });
      const result = payload?.result || null; const progress = payload?.progress || {};
      const metrics = $("liZongBacktestMetrics"); const chart = $("liZongBacktestChart"); const legend = $("liZongBacktestLegend"); const list = $("liZongBacktestRebalanceList");
      const build = $("liZongBacktestBuild"); const buildBar = $("liZongBacktestBuildBar");
      if (!result) {
        metrics.hidden = true; legend.hidden = true; list.hidden = true;
        const marketDays = Number(progress.available_market_days || 0); const requiredDays = Number(progress.required_market_days || 0);
        const evaluated = Number(progress.evaluated_symbols || 0); const eligible = Number(progress.eligible_symbols || 0);
        const marketRatio = requiredDays ? marketDays / requiredDays : 0; const symbolRatio = eligible ? evaluated / eligible : 0;
        const ratio = Math.max(0, Math.min(1, marketDays < requiredDays ? marketRatio : symbolRatio)); const percent = Math.round(ratio * 1000) / 10;
        build.hidden = false; build.setAttribute("aria-valuenow", String(Math.round(ratio * 100))); buildBar.style.width = `${ratio * 100}%`;
        $("liZongBacktestProgress").textContent = marketDays < requiredDays
          ? `历史市值 ${marketDays}/${requiredDays} 个交易日（${percent}%）· 数据完整后自动进入逐股规则核验`
          : `规则核验 ${evaluated}/${eligible || "待识别"} 只（${percent}%）· 预计剩余 ${Number(progress.estimated_evaluation_batches || 0)} 个计算批次`;
        chart.innerHTML = `<div class="screener-empty">${marketDays < requiredDays ? "正在补齐历史股票范围和每日市值。" : "正在构建无前视候选序列和等权换仓净值。"}<br>完整覆盖前不会发布可能有样本偏差的收益率。</div>`;
        return;
      }
      build.hidden = false; build.setAttribute("aria-valuenow", "100"); buildBar.style.width = "100%";
      $("liZongBacktestProgress").textContent = `${result.start_date} 至 ${result.end_date} · ${result.trading_days} 个交易日 · 历史市值达标范围 ${Number(result.eligible_symbol_count || 0).toLocaleString("zh-CN")} 只`;
      metrics.hidden = false;
      $("liZongBacktestReturn").textContent = pct(result.period_return_pct);
      $("liZongBacktestAnnualized").textContent = pct(result.annualized_return_pct);
      $("liZongBacktestBenchmark").textContent = pct(result.benchmark_return_pct);
      $("liZongBacktestExcess").textContent = pct(result.excess_return_pct);
      $("liZongBacktestDrawdown").textContent = pct(result.max_drawdown_pct);
      $("liZongBacktestRebalances").textContent = `${Number(result.selection_update_count || 0)} 次`;
      chart.innerHTML = ""; const svg = createLiZongBacktestChart(result.points || []);
      if (svg) { chart.appendChild(svg); legend.hidden = false; }
      else { chart.innerHTML = '<div class="screener-empty">区间内没有形成足够的组合净值点。</div>'; legend.hidden = true; }
      list.innerHTML = ""; const rebalances = (result.rebalances || []).slice(-8).reverse(); list.hidden = !rebalances.length;
      rebalances.forEach(item => {
        const row = document.createElement("div"); row.className = "li-zong-backtest-rebalance";
        const date = document.createElement("strong"); date.textContent = item.trade_date || "—";
        const detail = document.createElement("span"); detail.textContent = item.holding_count
          ? `${item.holding_count}只等权 · ${item.names?.slice(0, 4).join("、") || item.symbols?.slice(0, 4).join("、") || "组合更新"}${item.holding_count > 4 ? "等" : ""}`
          : "候选清空，转为现金观察";
        const turnover = document.createElement("small"); turnover.textContent = `由 ${item.signal_date || "前一交易日"} 信号触发 · 换手 ${numeric(item.turnover_pct)}%`;
        row.append(date, detail, turnover); list.appendChild(row);
      });
    }

    async function loadLiZongBacktest() {
      if (state.liZongBacktestLoading) return;
      state.liZongBacktestLoading = true;
      try {
        const payload = await api(`/v1/stock-strategies/li-zong/backtest?period=${encodeURIComponent(state.liZongBacktestPeriod || "1y")}`);
        renderLiZongBacktest(payload);
      } catch {
        if (!state.liZongBacktest) $("liZongBacktestProgress").textContent = "回测结果暂时没有加载完成，后台数据仍会继续保留。";
      } finally {
        state.liZongBacktestLoading = false;
      }
    }

    function showLiZongHistoryDetail(item) {
      const performance = item.performance || {}; const horizons = performance.horizons || {};
      const lines = [
        `# ${item.name || item.internal_symbol}｜${item.signal_date} 历史信号`,
        `信号状态：${item.signal_type === "triggered" ? "进入候选池并触发人工复核" : "进入候选池"}`,
        "",
        "## 信号后表现"
      ];
      [5, 10, 20].forEach(day => {
        const horizon = horizons[String(day)] || {};
        if (horizon.status === "available") lines.push(`- ${day}个交易日：个股 ${pct(horizon.stock_return_pct)}；沪深300 ${pct(horizon.benchmark_return_pct)}；超额 ${pct(horizon.excess_return_pct)}；区间最大上行 ${pct(horizon.max_upside_pct)}（${horizon.max_upside_date || "日期待确认"}）；区间最大下行 ${pct(horizon.max_drawdown_pct)}（${horizon.max_drawdown_date || "日期待确认"}）；观察日 ${horizon.target_date}`);
        else lines.push(`- ${day}个交易日：观察尚未完整。`);
      });
      lines.push("", "## 当时逐规则证据");
      (item.rule_results || []).forEach(rule => {
        lines.push(`- ${liZongRuleLabel(rule.rule_id)}｜${liZongRuleStatus(rule.status)}｜证据时间 ${rule.evidence_date || rule.report_period || "待确认"}`);
        lines.push(`  实际值：${strategyShortValue(rule.actual_value)}；阈值：${strategyShortValue(rule.threshold)}；来源：${rule.source || "待确认"}`);
      });
      lines.push("", "## 回放边界", "- 只使用信号日及以前日线、当日历史市值和当时已公告财务及股东数据。", "- 收益从信号日收盘计算，未计交易成本、涨跌停可成交性和实际成交滑点。", "- 单个历史样本不代表未来结果，也不用于计算胜率式荐股评价。");
      const agentQuestion = `请基于李总策略的真实历史回放，复盘${item.name || item.internal_symbol}（${item.internal_symbol}）在${item.signal_date}的信号。针对性说明当时为什么满足规则、信号后5/10/20个交易日相对沪深300的走势、反方证据、样本边界，以及它对当前研究有什么和没有什么启示。不要把历史样本写成未来预测。`;
      openReader(
        `${item.name || item.internal_symbol}｜历史回放`,
        lines.join("\n"),
        `${item.signal_date} · 对照沪深300`,
        "",
        {agentQuestion}
      );
    }

    function renderLiZongLoadState(loadState, message) {
      const panel = $("liZongPanel");
      panel.dataset.loadState = loadState;
      panel.hidden = state.screeningSection !== "li_zong";
      $("liZongState").textContent = message;
      if (state.liZongStrategy) return;
      $("liZongStats").hidden = true;
      $("liZongHistoryPanel").hidden = true;
      const container = $("liZongResults"); container.innerHTML = "";
      const empty = document.createElement("div"); empty.className = "screener-empty";
      empty.textContent = loadState === "loading"
        ? "正在读取最新策略结果，当前页面可以继续浏览，完成后会自动显示。"
        : "暂时没有取得最新策略结果，已保存的研究和关注不会受影响。";
      container.appendChild(empty);
      if (loadState === "error") {
        const retry = document.createElement("button"); retry.type = "button"; retry.className = "btn"; retry.textContent = "重新加载策略结果";
        retry.addEventListener("click", () => { void loadLiZongStrategy(); });
        container.appendChild(retry);
      }
    }

    function syncScreeningSection(options = {}) {
      const section = state.screeningSection === "li_zong" ? "li_zong" : "general";
      state.screeningSection = section;
      $("generalScreenerPanel").hidden = section !== "general";
      $("liZongPanel").hidden = section !== "li_zong";
      document.querySelectorAll("[data-screening-jump]").forEach(button => {
        const active = button.dataset.screeningJump === section;
        button.classList.toggle("active", active);
        button.setAttribute("aria-selected", active ? "true" : "false");
      });
      if (options.load === false || !state.user) return;
      if (section === "li_zong" && !state.liZongStrategy && !state.liZongLoading) {
        void loadLiZongStrategy();
      }
    }

    function openScreeningSection(section, options = {}) {
      state.workspaceNavigationVersion += 1;
      state.screeningSection = section === "li_zong" ? "li_zong" : "general";
      syncScreeningSection();
      syncWorkspaceUrl(options.historyMode || "push");
      if (options.scroll !== false) window.scrollTo({top: 0, behavior: "smooth"});
    }

    function renderLiZongHistory(payload) {
      state.liZongHistory = payload;
      const panel = $("liZongHistoryPanel"); const container = $("liZongHistoryResults");
      const counts = state.liZongStrategy?.counts || {};
      const noCurrentCandidates = Number(counts.qualified || 0) + Number(counts.triggered || 0) === 0;
      const shouldShow = state.liZongFilter === "qualified" && noCurrentCandidates;
      panel.hidden = !shouldShow;
      if (!shouldShow) return;
      const coverage = payload?.coverage || {}; const items = payload?.items || [];
      const expected = Number(coverage.expected_symbols || 0); const completed = Number(coverage.completed_symbols || 0);
      $("liZongHistoryCoverage").textContent = expected ? `近期回放 ${completed}/${expected} 只 · ${items.length} 个已发布信号` : "近期回放正在准备";
      const toggle = $("liZongHistoryToggle");
      toggle.hidden = !items.length;
      toggle.textContent = state.liZongHistoryExpanded ? "收起历史详情" : `展开 ${items.length} 条历史详情`;
      toggle.setAttribute("aria-expanded", String(state.liZongHistoryExpanded));
      container.innerHTML = "";
      if (!items.length) {
        container.hidden = false;
        const empty = document.createElement("div"); empty.className = "screener-empty";
        empty.textContent = completed ? "已完成的近期回放中暂未发现历史命中，后台会继续按近似程度扩展覆盖。" : "后台正在优先回放最接近当前规则的股票，完成后会在这里显示真实历史信号及后续走势。";
        container.appendChild(empty); return;
      }
      container.hidden = !state.liZongHistoryExpanded;
      if (!state.liZongHistoryExpanded) return;
      items.forEach(item => {
        const performance = item.performance || {}; const horizons = performance.horizons || {};
        const card = document.createElement("article"); card.className = "li-zong-history-card";
        const head = document.createElement("div"); head.className = "li-zong-card-head";
        const identity = document.createElement("div");
        const name = document.createElement("div"); name.className = "li-zong-card-name"; name.textContent = item.name || item.internal_symbol;
        const meta = document.createElement("div"); meta.className = "li-zong-history-meta"; meta.textContent = `${item.internal_symbol} · ${item.signal_date} · ${item.signal_type === "triggered" ? "触发人工复核" : "进入候选池"}`;
        identity.append(name, meta);
        const badge = document.createElement("span"); badge.className = `li-zong-badge ${item.signal_type === "triggered" ? "triggered" : ""}`; badge.textContent = "历史真实信号";
        head.append(identity, badge); card.appendChild(head);
        const grid = document.createElement("div"); grid.className = "li-zong-history-grid";
        [5, 10, 20].forEach(day => {
          const horizon = horizons[String(day)] || {}; const node = document.createElement("div"); node.className = "li-zong-history-horizon";
          const label = document.createElement("span"); label.textContent = `${day}个交易日后`;
          const value = document.createElement("strong"); value.textContent = horizon.status === "available" ? `个股 ${pct(horizon.stock_return_pct)}` : "观察未完整";
          const detail = document.createElement("small"); detail.textContent = horizon.status === "available" ? `沪深300 ${pct(horizon.benchmark_return_pct)} · 超额 ${pct(horizon.excess_return_pct)}` : "不会使用不足周期的数据补算";
          node.append(label, value, detail); grid.appendChild(node);
        });
        card.appendChild(grid);
        const chart = createLiZongHistoryChart(performance.path || []);
        if (chart) {
          card.appendChild(chart);
          const legend = document.createElement("div"); legend.className = "li-zong-history-legend"; legend.innerHTML = '<span><i style="background:#3673d9"></i>个股</span><span><i style="background:#9aa9bc"></i>沪深300</span><span>纵轴为信号日收盘后的累计收益</span>'; card.appendChild(legend);
        }
        const actions = document.createElement("div"); actions.className = "li-zong-actions";
        const detailButton = document.createElement("button"); detailButton.type = "button"; detailButton.className = "btn"; detailButton.textContent = "查看当时证据"; detailButton.addEventListener("click", () => showLiZongHistoryDetail(item));
        const ask = document.createElement("button"); ask.type = "button"; ask.className = "btn primary"; ask.textContent = "让 Agent 复盘";
        ask.addEventListener("click", () => { void researchCandidateWithAgent(item, ask, {source_kind: "li_zong_strategy", source_label: "李总策略历史回放", display_name: item.name, profile_key: item.history_version, as_of_date: item.signal_date, candidate_status: `historical_${item.signal_type}`, matched_reasons: (item.rule_results || []).filter(rule => rule.status === "passed").map(rule => liZongRuleLabel(rule.rule_id)), missing_fields: []}, `请基于李总策略的真实历史回放，复盘${item.name}（${item.internal_symbol}）在${item.signal_date}的信号。针对性说明当时为什么满足规则、信号后5/10/20个交易日相对沪深300的走势、反方证据、样本边界，以及它对当前研究有什么和没有什么启示。不要把历史样本写成未来预测。`); });
        actions.append(detailButton, ask); card.appendChild(actions); container.appendChild(card);
      });
    }

    function renderLiZongFunnel(funnel) {
      const container = $("liZongFunnel"); container.innerHTML = "";
      const steps = funnel?.steps || [];
      if (!steps.length) { container.hidden = true; return; }
      container.hidden = false;
      steps.forEach(step => {
        const node = document.createElement("div"); node.className = "li-zong-funnel-step"; node.title = liZongRuleLabel(step.rule_id);
        const label = document.createElement("span"); label.textContent = liZongRuleLabel(step.rule_id);
        const value = document.createElement("strong"); value.textContent = `${Number(step.remaining_count || 0).toLocaleString("zh-CN")} 只`;
        const removed = document.createElement("small"); removed.textContent = `本步减少 ${Number(step.removed_at_step || 0).toLocaleString("zh-CN")} 只`;
        node.append(label, value, removed); container.appendChild(node);
      });
    }

    function renderLiZongStrategy(payload) {
      const items = payload?.items || [];
      const counts = payload?.counts || {};
      const meta = payload?.data_meta || {};
      const definition = payload?.strategy || {};
      const universe = Number(meta.universe_count || 0);
      const publishable = payload?.status === "ready" || universe > 0 || items.length > 0;
      if (!publishable) {
        if (state.liZongStrategy) {
          state.liZongFilter = state.liZongRenderedFilter;
          $("liZongPanel").dataset.loadState = "ready";
          $("liZongState").textContent = "显示最近可用结果";
          document.querySelectorAll("[data-li-zong-filter]").forEach(button => button.classList.toggle("active", button.dataset.liZongFilter === state.liZongFilter));
        } else {
          renderLiZongLoadState("error", "策略结果正在准备");
        }
        return;
      }
      state.liZongStrategy = payload;
      $("liZongPanel").dataset.loadState = "ready";
      if (payload?.observation_counts) state.liZongObservationCounts = payload.observation_counts;
      state.liZongRenderedFilter = state.liZongFilter;
      $("liZongPanel").hidden = state.screeningSection !== "li_zong";
      $("liZongStats").hidden = !universe && !items.length;
      $("liZongVersion").textContent = definition.current_version || definition.version?.version || "li_zong_v1";
      $("liZongDate").textContent = meta.latest_as_of_date || "—";
      const evaluated = Number(meta.evaluated_symbols || 0);
      const coveragePct = universe ? `${(Number(meta.coverage_ratio || 0) * 100).toFixed(1)}%` : "";
      const deepEligible = Number(meta.deep_check_eligible_count ?? meta.market_cap_eligible_count ?? 0);
      const deepProcessed = Number(meta.deep_processed_symbols ?? 0);
      const deepRemaining = Number(meta.deep_remaining_symbols ?? Math.max(0, deepEligible - deepProcessed));
      const deepPct = deepEligible ? `${(Number(meta.deep_processing_ratio || 0) * 100).toFixed(1)}%` : "100.0%";
      $("liZongUniverse").textContent = universe ? `${universe} 只` : "—";
      $("liZongUniverse").title = universe ? `当前覆盖 ${evaluated}/${universe} 只，比例 ${coveragePct}` : "";
      $("liZongDeepEligible").textContent = universe ? `${deepEligible} 只` : "—";
      $("liZongHistoryInsufficient").textContent = universe ? `${Number(meta.history_insufficient_count || 0)} 只` : "—";
      $("liZongHistoryUnknown").textContent = universe ? `${Number(meta.history_unknown_count || 0)} 只` : "—";
      $("liZongCoverage").textContent = deepEligible ? `${deepProcessed}/${deepEligible}` : "0/0";
      $("liZongCoverage").title = universe
        ? `真实深度处理进度 ${deepPct}；仍待深度处理 ${deepRemaining} 只；已完成完整规则判断 ${meta.deep_decisive_symbols || 0} 只；深度处理后仍有缺口 ${meta.deep_data_incomplete_symbols || 0} 只`
        : "";
      $("liZongQualified").textContent = counts.qualified ?? 0;
      $("liZongTriggered").textContent = counts.triggered ?? 0;
      $("liZongIncomplete").textContent = counts.data_incomplete ?? 0;
      renderLiZongFunnel(payload?.funnel);
      $("liZongState").textContent = meta.full_market_coverage && meta.deep_check_complete
        ? "最新策略结果"
        : "当前可核验结果";
      document.querySelectorAll("[data-li-zong-filter]").forEach(button => button.classList.toggle("active", button.dataset.liZongFilter === state.liZongFilter));

      const observationFilter = ["near_8_of_9", "watch_6_7_of_9"].includes(state.liZongFilter);
      const filtered = items.filter(item => observationFilter
        ? item.observation_band === state.liZongFilter
        : item.status === state.liZongFilter);
      if (observationFilter) {
        const observationTotal = Number(state.liZongObservationCounts?.[state.liZongFilter] || 0);
        $("liZongState").textContent = `展示 ${filtered.length}/${observationTotal} 只研究观察`;
      }
      const container = $("liZongResults"); container.innerHTML = "";
      if (!filtered.length) {
        const empty = document.createElement("div"); empty.className = "screener-empty";
        empty.textContent = observationFilter
          ? `${liZongStatusLabel(state.liZongFilter)}当前为空。这里只统计已完整核验9条候选规则且无数据缺口的股票，不会放宽规则补足数量。`
          : state.liZongFilter === "qualified" && Number(counts.qualified || 0) + Number(counts.triggered || 0) === 0
          ? "当前没有股票同时满足全部严格规则。下方展示同一规则的历史真实命中及后续相对大盘走势。"
          : `${liZongStatusLabel(state.liZongFilter)}列表当前为空。可以切换其他分类，或使用下方通用筛选。`;
        container.appendChild(empty);
        if (state.liZongHistory) renderLiZongHistory(state.liZongHistory);
        return;
      }
      filtered.forEach(item => {
        const observationBand = item.observation_band || null;
        const summary = item.summary || {};
        const card = document.createElement("article"); card.className = "li-zong-card";
        const head = document.createElement("div"); head.className = "li-zong-card-head";
        const identity = document.createElement("div");
        const name = document.createElement("div"); name.className = "li-zong-card-name"; name.textContent = item.name || item.internal_symbol;
        const metaNode = document.createElement("div"); metaNode.className = "li-zong-card-meta"; metaNode.textContent = `${item.symbol || item.internal_symbol} · ${item.as_of_date || "数据时间待确认"} · ${item.parameter_version || "默认参数"}`;
        identity.append(name, metaNode);
        const badge = document.createElement("span"); badge.className = `li-zong-badge ${observationBand || item.status || ""}`; badge.textContent = liZongStatusLabel(observationBand || item.status);
        head.append(identity, badge); card.appendChild(head);

        const metricRows = [
          ...(observationBand
            ? [
                ["候选规则", `${item.candidate_rule_pass_count || 0}/${item.candidate_rule_total || 9}（非候选）`],
                ["明确未通过", (item.failed_candidate_rule_ids || []).map(liZongRuleLabel).join("、") || "待确认"]
              ]
            : []),
          ["总市值", summary.market_cap_yi == null ? "—" : `${numeric(summary.market_cap_yi)}亿`],
          ["五年ROE最低", summary.roe_min_pct == null ? "—" : `${numeric(summary.roe_min_pct)}%`],
          ["机构股东", summary.non_natural_holder_count == null ? "—" : `${summary.non_natural_holder_count}名`],
          ["一年涨停", summary.annual_limit_up_count == null ? "—" : `${summary.annual_limit_up_count}次`],
          ["出现连板", summary.has_consecutive_limit_up ? "是" : "否"],
          ["十日涨停", summary.recent_limit_up_count == null ? "—" : `${summary.recent_limit_up_count}次`],
          ["十日5%阴线", summary.recent_bearish_drop_count == null ? "—" : `${summary.recent_bearish_drop_count}次`],
          ["近期新高", summary.new_high_dates?.length ? summary.new_high_dates.at(-1) : "未命中"],
          ["三日倍量", summary.volume_sequences?.length ? `${summary.volume_sequences.length}段` : "未命中"],
          ["当前触发", item.triggered_rule_ids?.length ? item.triggered_rule_ids.join("、") : "未触发"]
        ];
        const metrics = document.createElement("div"); metrics.className = "li-zong-metrics";
        metricRows.forEach(([label, value]) => {
          const node = document.createElement("div"); node.className = "li-zong-metric";
          const labelNode = document.createElement("span"); labelNode.textContent = label;
          const valueNode = document.createElement("strong"); valueNode.textContent = value;
          node.append(labelNode, valueNode); metrics.appendChild(node);
        });
        card.appendChild(metrics);
        if (observationBand) {
          const observationBoundary = document.createElement("div"); observationBoundary.className = "li-zong-limitations";
          observationBoundary.textContent = "这是完整规则核验后的研究观察分层，不是候选、触发或买卖建议；严格9条候选规则和3条触发规则保持不变。";
          card.appendChild(observationBoundary);
        }
        if (item.limitations?.length) {
          const limitations = document.createElement("div"); limitations.className = "li-zong-limitations";
          limitations.textContent = item.limitations.slice(0, 2).join("；"); card.appendChild(limitations);
        }
        const entryContext = {
          source_kind: "li_zong_strategy",
          source_label: observationBand ? "李总策略接近满足观察池" : "李总策略",
          display_name: item.name,
          profile_key: item.parameter_version || item.strategy_version,
          as_of_date: item.as_of_date,
          candidate_status: observationBand || item.status,
          matched_reasons: (item.rule_results || []).filter(rule => rule.status === "passed").map(rule => liZongRuleLabel(rule.rule_id)),
          missing_fields: observationBand
            ? (item.failed_candidate_rule_ids || []).map(liZongRuleLabel)
            : item.limitations || []
        };
        const actions = document.createElement("div"); actions.className = "li-zong-actions";
        const detail = document.createElement("button"); detail.type = "button"; detail.className = "btn"; detail.textContent = "查看逐规则证据"; detail.addEventListener("click", () => showLiZongDetail(item));
        const follow = document.createElement("button"); follow.type = "button"; follow.className = "btn"; follow.textContent = observationBand ? "加入研究观察" : item.status === "triggered" ? "加入重点关注" : "加入关注"; follow.addEventListener("click", () => { void addScreenCandidateToWatchlist(item, follow, observationBand ? "李总策略研究观察" : "李总策略"); });
        const research = document.createElement("button"); research.type = "button"; research.className = "btn primary"; research.textContent = observationBand ? "保存观察线索并研究" : "保存线索并研究";
        research.addEventListener("click", () => { void enterScreenCandidateResearch(item, research, entryContext); });
        const ask = document.createElement("button"); ask.type = "button"; ask.className = "btn"; ask.textContent = "让 Agent 核验"; ask.addEventListener("click", () => { void researchCandidateWithAgent(item, ask, entryContext, observationBand
          ? `请核验${item.name}（${item.internal_symbol}）当前李总策略${liZongStatusLabel(observationBand)}的结果。它只通过${item.candidate_rule_pass_count || 0}/9条候选规则，明确未通过${(item.failed_candidate_rule_ids || []).map(liZongRuleLabel).join("、") || "待确认规则"}，不是候选。请说明通过规则的证据、未通过规则、反方证据、数据时间、失效条件与下一步核验；明确候选资格只由9条候选规则决定，3条触发规则只决定候选后的人工复核层级；不要把观察池写成荐股或买卖指令。`
          : `请核验${item.name}（${item.internal_symbol}）的李总策略结果。逐条说明基本面、股性、量价和触发规则的证据时间、反方证据、数据缺口、失效条件与下一步需要核验什么；不要输出买卖指令。`); });
        actions.append(detail, follow, research, ask); card.appendChild(actions); container.appendChild(card);
      });
      if (state.liZongHistory) renderLiZongHistory(state.liZongHistory);
    }

    async function loadLiZongStrategy() {
      if (!state.liZongBacktestLoading) void loadLiZongBacktest();
      const filter = state.liZongFilter || "qualified";
      const observationFilter = ["near_8_of_9", "watch_6_7_of_9"].includes(filter);
      const loadToken = ++state.liZongLoadToken;
      const hadPublishedResult = Boolean(state.liZongStrategy);
      state.liZongLoading = true;
      if (hadPublishedResult) {
        $("liZongPanel").dataset.loadState = "loading";
        $("liZongPanel").hidden = state.screeningSection !== "li_zong";
        $("liZongState").textContent = "正在更新策略结果";
      } else {
        renderLiZongLoadState("loading", "正在读取最新策略结果");
      }
      try {
        const [candidateResult, historyResult] = await Promise.allSettled([
          api(observationFilter
            ? `/v1/stock-strategies/li-zong/observation-pool?band=${encodeURIComponent(filter)}&limit=30`
            : `/v1/stock-strategies/li-zong/candidates?status=${encodeURIComponent(filter)}&limit=200`),
          filter === "qualified"
            ? api("/v1/stock-strategies/li-zong/history?limit=30")
            : Promise.resolve(state.liZongHistory)
        ]);
        if (loadToken !== state.liZongLoadToken) return;
        if (candidateResult.status !== "fulfilled") throw candidateResult.reason;
        renderLiZongStrategy(candidateResult.value);
        if (historyResult.status === "fulfilled" && historyResult.value) renderLiZongHistory(historyResult.value);
      } catch {
        if (loadToken !== state.liZongLoadToken) return;
        if (hadPublishedResult) {
          state.liZongFilter = state.liZongRenderedFilter;
          $("liZongPanel").dataset.loadState = "ready";
          $("liZongPanel").hidden = state.screeningSection !== "li_zong";
          $("liZongState").textContent = "显示最近可用结果";
          document.querySelectorAll("[data-li-zong-filter]").forEach(button => button.classList.toggle("active", button.dataset.liZongFilter === state.liZongFilter));
        } else {
          renderLiZongLoadState("error", "暂时没有取得最新策略结果");
        }
      } finally {
        if (loadToken === state.liZongLoadToken) state.liZongLoading = false;
      }
    }

    function stockScreenFieldLabel(key) {
      return {
        revenue_yoy: "营收同比",
        net_profit_yoy: "净利润同比",
        roe: "ROE",
        gross_margin: "毛利率",
        net_margin: "净利率",
        debt_to_assets: "资产负债率",
        pe_ttm: "PE TTM",
        pb: "PB",
        ps_ttm: "PS TTM",
        volume_ratio: "量比",
        turnover_rate_pct: "换手率"
      }[key] || key;
    }

    function renderStockScreener(payload) {
      state.stockScreener = payload;
      const profile = payload?.profile || {};
      const meta = payload?.data_meta || {};
      const contract = payload?.data_contract || {};
      const coverage = contract.coverage || {};
      const items = payload?.items || [];
      $("stockScreenTitle").textContent = profile.label || "研究候选";
      $("stockScreenCountBadge").textContent = `${items.length} 只`;
      const periods = meta.financial_report_periods || [];
      const snapshotCoverage = coverage.market_snapshot || {};
      const snapshotCoverageText = snapshotCoverage.expected
        ? `股票池 ${Number(snapshotCoverage.available || 0).toLocaleString("zh-CN")}/${Number(snapshotCoverage.expected || 0).toLocaleString("zh-CN")}（${(Number(snapshotCoverage.ratio || 0) * 100).toFixed(1)}%）`
        : "";
      const coverageLabel = (label, value) => value?.expected
        ? `${label} ${(Number(value.ratio || 0) * 100).toFixed(1)}%`
        : "";
      const coverageSummary = [
        coverageLabel("行情", coverage.market_snapshot),
        coverageLabel("市值", coverage.market_cap),
        coverageLabel("估值", coverage.valuation),
        coverageLabel("20日收益", coverage.return_20d),
        coverageLabel("候选财务", coverage.financial_candidate_pool)
      ].filter(Boolean).join(" / ");
      const dataVersion = String(contract.data_version || meta.data_version || "");
      $("stockScreenMeta").textContent = [
        meta.latest_completed_trade_date ? `行情交易日 ${meta.latest_completed_trade_date}` : "行情日期待确认",
        meta.return_20d_base_date ? `20日比较基准 ${meta.return_20d_base_date}` : "",
        periods.length ? `财务报告期 ${periods.slice(0, 3).join("、")}` : "财务报告期逐只展示",
        snapshotCoverageText,
        coverageSummary ? `数据覆盖 ${coverageSummary}` : "",
        dataVersion ? `数据版本 ${dataVersion.slice(-8)}` : "",
        profile.sort_rule || ""
      ].filter(Boolean).join(" · ");
      $("stockScreenBoundary").textContent = payload?.boundary || "这是可解释的研究候选筛选，不构成推荐、评级、目标价或交易建议。";

      const rules = $("stockScreenRules"); rules.innerHTML = "";
      (payload?.rules || []).slice(0, 10).forEach(rule => {
        const node = document.createElement("div"); node.className = "screener-rule";
        node.textContent = `${rule.field} ${rule.operator} ${rule.value}${rule.unit || ""}`;
        node.title = rule.reason || "确定性筛选条件";
        rules.appendChild(node);
      });
      if (!rules.childElementCount) {
        const node = document.createElement("div"); node.className = "screener-rule"; node.textContent = "当前规则正在整理。"; rules.appendChild(node);
      }

      const container = $("stockScreenResults"); container.innerHTML = "";
      if (!items.length) {
        const empty = document.createElement("div"); empty.className = "screener-empty";
        empty.textContent = payload?.status === "empty"
          ? "当前没有股票同时满足全部条件。建议一次只放宽一项规则后重新筛选。"
          : "当前没有可展示的候选。可以调整一个筛选条件后重新执行。";
        container.appendChild(empty); return;
      }
      items.forEach(item => {
        const card = document.createElement("article"); card.className = "screener-card";
        const head = document.createElement("div"); head.className = "screener-card-head";
        const identity = document.createElement("div");
        const name = document.createElement("div"); name.className = "screener-stock-name"; name.textContent = item.name || item.internal_symbol;
        const stockMeta = document.createElement("div"); stockMeta.className = "screener-stock-meta"; stockMeta.textContent = `${item.internal_symbol || item.ts_code} · ${item.industry || "行业待确认"}`;
        identity.append(name, stockMeta);
        const period = document.createElement("div"); period.className = "screener-period";
        period.textContent = item.financials?.report_period ? `财务报告期\n${item.financials.report_period}` : "财务报告期\n待补充";
        head.append(identity, period); card.appendChild(head);

        const metricRows = [
          ["近5日", pct(item.metrics?.return_5d_pct)],
          ["近20日", pct(item.metrics?.return_20d_pct)],
          ["行业超额", pct(item.metrics?.industry_excess_20d_pct)],
          ["PE TTM", numeric(item.metrics?.pe_ttm)],
          ["PB", numeric(item.metrics?.pb)],
          ["总市值", item.metrics?.total_mv_yi == null ? "—" : `${numeric(item.metrics.total_mv_yi)}亿`]
        ];
        const metrics = document.createElement("div"); metrics.className = "screener-metrics";
        metricRows.forEach(([label, value]) => {
          const metric = document.createElement("div"); metric.className = "screener-metric";
          const labelNode = document.createElement("span"); labelNode.textContent = label;
          const valueNode = document.createElement("strong"); valueNode.textContent = value;
          metric.append(labelNode, valueNode); metrics.appendChild(metric);
        });
        card.appendChild(metrics);

        const reasons = document.createElement("ul"); reasons.className = "screener-reasons";
        (item.matched_reasons || []).slice(0, 4).forEach(value => { const li = document.createElement("li"); li.textContent = value; reasons.appendChild(li); });
        card.appendChild(reasons);
        if (item.missing_fields?.length) {
          const missing = document.createElement("div"); missing.className = "screener-missing";
          const reasonByField = new Map((item.missing_reasons || []).map(entry => [entry.field, entry.reason]));
          missing.textContent = `数据缺口：${item.missing_fields.slice(0, 6).map(field => {
            const reason = reasonByField.get(field);
            return `${stockScreenFieldLabel(field)}${reason ? `（${reason}）` : ""}`;
          }).join("；")}`;
          card.appendChild(missing);
        }
        const entryContext = {
          source_kind: "stock_screen",
          source_label: profile.label || "研究候选筛选",
          display_name: item.name,
          profile_key: profile.key,
          as_of_date: meta.latest_completed_trade_date,
          candidate_status: payload?.status,
          matched_reasons: item.matched_reasons || [],
          missing_fields: (item.missing_fields || []).map(stockScreenFieldLabel)
        };
        const actions = document.createElement("div"); actions.className = "screener-actions";
        const follow = document.createElement("button"); follow.type = "button"; follow.className = "btn"; follow.textContent = "加入关注";
        follow.addEventListener("click", () => { void addScreenCandidateToWatchlist(item, follow); });
        const research = document.createElement("button"); research.type = "button"; research.className = "btn primary"; research.textContent = "保存线索并研究";
        research.addEventListener("click", () => { void enterScreenCandidateResearch(item, research, entryContext); });
        const ask = document.createElement("button"); ask.type = "button"; ask.className = "btn"; ask.textContent = "让 Agent 继续研究";
        ask.addEventListener("click", () => { void researchCandidateWithAgent(item, ask, entryContext, `请继续研究${item.name}（${item.internal_symbol}）。它命中了“${profile.label || "研究候选"}”筛选，请核验最新财务、公告、反方证据、失效条件和当前仍缺失的信息。`); });
        actions.append(follow, research, ask); card.appendChild(actions); container.appendChild(card);
      });
    }

    async function loadStockScreener() {
      if (state.stockScreenerLoading) return;
      state.stockScreenerLoading = true;
      const button = $("runStockScreener"); button.disabled = true; button.textContent = "筛选中…";
      $("stockScreenResults").innerHTML = '<div class="screener-empty">正在应用已选研究条件…</div>';
      const filters = {};
      const industry = $("stockScreenIndustry").value.trim();
      const minCap = $("stockScreenMinCap").value;
      const maxPe = $("stockScreenMaxPe").value;
      if (industry) filters.industry = industry;
      if (minCap !== "") filters.min_market_cap_yi = Number(minCap);
      if (maxPe !== "") filters.max_pe_ttm = Number(maxPe);
      try {
        const payload = await api("/me/stock-screener", {
          method: "POST",
          body: JSON.stringify({
            profile: $("stockScreenProfile").value,
            market: $("stockScreenMarket").value,
            max_results: Number($("stockScreenCount").value),
            filters
          })
        });
        renderStockScreener(payload);
      } catch (error) {
        state.stockScreener = null;
        const unavailable = error?.status === 503;
        $("stockScreenTitle").textContent = unavailable ? "智能选股数据正在准备" : "本次筛选暂未完成";
        $("stockScreenMeta").textContent = unavailable
          ? "服务器尚未配置完整选股数据，完成数据服务配置后即可重新执行。"
          : "请检查筛选条件并重新执行；已有候选不会因此被清空。";
        $("stockScreenCountBadge").textContent = unavailable ? "待准备" : "可重试";
        $("stockScreenResults").innerHTML = unavailable
          ? '<div class="screener-empty"><strong>服务器尚未配置选股数据</strong><br>请按 README 的 Tushare 数据配置说明完成设置并重启服务，然后点击“执行确定性筛选”。</div>'
          : '<div class="screener-empty">筛选服务暂时没有完成本次计算。调整条件或稍后重新执行。</div>';
      } finally {
        state.stockScreenerLoading = false;
        button.disabled = false; button.textContent = "执行确定性筛选";
      }
    }

    async function addScreenCandidateToWatchlist(item, button, sourceLabel = null) {
      button.disabled = true;
      try {
        await api("/me/watchlist", {
          method: "POST",
          body: JSON.stringify({
            symbol: item.internal_symbol,
            name: item.name,
            market: "A股",
            thesis: `由${sourceLabel || state.stockScreener?.profile?.label || "研究候选筛选"}进入关注；需要继续核验财务、公告和反方证据。`
          })
        });
        button.textContent = "已加入关注";
        await loadWatchlist();
      } catch {
        button.disabled = false; button.textContent = "重试加入关注";
      }
    }

    async function enterScreenCandidateResearch(item, button, entryContext) {
      const symbol = item.internal_symbol || item.symbol;
      if (!symbol) return;
      const original = button.textContent;
      button.disabled = true;
      button.textContent = "正在保存研究线索…";
      try {
        const session = await api("/me/deep-stock", {
          method: "POST",
          body: JSON.stringify({symbol, entry_context: entryContext})
        });
        state.deepStock = session;
        await loadConversations(false);
        await loadDeepStock({force: true});
        await openDeepStockSymbol(symbol);
        button.textContent = "已进入研究空间";
      } catch (error) {
        button.disabled = false;
        button.textContent = original;
        openReader("研究空间暂未建立", error.message || "保存候选研究线索失败，请稍后重试。", "当前筛选结果仍保留在页面");
      }
    }

    async function researchCandidateWithAgent(item, button, entryContext, question) {
      const symbol = item.internal_symbol || item.symbol;
      if (!symbol) return;
      const original = button.textContent;
      button.disabled = true;
      button.textContent = "正在进入长期研究对话…";
      try {
        const session = await api("/me/deep-stock", {
          method: "POST",
          body: JSON.stringify({symbol, entry_context: entryContext})
        });
        state.deepStock = session;
        await loadConversations(false);
        await loadDeepStock({force: true});
        await continueDeepStockConversation(question, session);
        button.textContent = "已进入研究对话";
      } catch (error) {
        button.disabled = false;
        button.textContent = original;
        openReader("长期研究对话暂未打开", error.message || "请稍后重试。", "候选线索没有被自动写成正式判断");
      }
    }
