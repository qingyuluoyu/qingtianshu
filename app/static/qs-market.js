function inferDiagnosisMarketKey(data, question = "") {
      const evidenceKey = data?.evidence?.market_drivers?.market_key || data?.market_key;
      const normalized = evidenceKey === "gold" ? "london_gold" : evidenceKey;
      if (["china", "japan", "korea", "us", "london_gold"].includes(normalized)) return normalized;
      const folded = String(question || "").toLowerCase();
      if (/(伦敦金|黄金|xau)/.test(folded)) return "london_gold";
      if (/(美股|纳指|纳斯达克|标普|道指|nasdaq|s&p)/.test(folded)) return "us";
      if (/(日股|日经|日本股市)/.test(folded)) return "japan";
      if (/(韩股|韩国股市|kospi)/.test(folded)) return "korea";
      if (/(a股|大盘|上证|深证|创业板|沪深)/i.test(folded)) return "china";
      return null;
    }

    function inferDiagnosisSymbol(data, question = "") {
      const direct = data?.evidence?.symbol || data?.evidence?.item?.symbol || data?.evidence?.requested_symbol || data?.symbol;
      if (direct) return String(direct);
      const tracked = data?.evidence?.events || data?.evidence?.items;
      if (Array.isArray(tracked) && tracked.length === 1) {
        const trackedSymbol = tracked[0]?.internal_symbol || tracked[0]?.symbol;
        if (trackedSymbol) return String(trackedSymbol);
      }
      const sixDigits = String(question).match(/(?<!\d)(\d{6})(?!\d)/);
      if (sixDigits) return sixDigits[1];
      const aliases = [
        [/中兴通讯|中兴/, "000063.SZ"],
        [/中际旭创|中际/, "300308.SZ"],
        [/贵州茅台|茅台/, "600519.SS"],
        [/英伟达|nvidia|nvda/i, "NVDA"]
      ];
      for (const [pattern, symbol] of aliases) if (pattern.test(String(question))) return symbol;
      const ticker = String(question).match(/(?<![A-Z0-9])([A-Z]{1,5})(?![A-Z0-9])/);
      if (!ticker) return null;
      const candidate = ticker[1];
      const marketTerms = new Set(["A", "AI", "ETF", "GDP", "CPI", "RSI", "MACD", "IPO", "PMI", "KOSPI", "XAU"]);
      return marketTerms.has(candidate) ? null : candidate;
    }

    function diagnosisResearchTargets(data) {
      const explicit = data?.researchTargets || data?.research_targets || data?.metadata?.research_targets;
      const targets = [];
      const push = item => {
        const symbol = String(item?.symbol || item?.internal_symbol || "").trim();
        if (!symbol || targets.some(target => target.symbol === symbol)) return;
        targets.push({symbol, name: String(item?.name || symbol).trim() || symbol});
      };
      if (Array.isArray(explicit)) explicit.forEach(push);
      if (targets.length) return targets;
      const evidence = data?.evidence || {};
      if (!["symbol_check", "symbol_comparison"].includes(evidence.selection_mode)) return targets;
      const bySymbol = new Map((evidence.items || []).map(item => [String(item.internal_symbol || item.symbol || ""), item]));
      const requested = evidence.requested_symbols || (evidence.requested_symbol ? [evidence.requested_symbol] : []);
      requested.forEach(symbol => push(bySymbol.get(String(symbol)) || {symbol}));
      return targets;
    }

    function fundProductDiagnosisContext(data, question = "") {
      const context = data?.evidence?.fund_product_context
        || data?.fundProductContext
        || data?.fund_product_context
        || data?.metadata?.fund_product_context
        || null;
      if (context) return context;
      const text = String(question || "");
      const codes = [...text.matchAll(/(?<!\d)(\d{6})(?!\d)/g)].map(match => match[1]);
      const hasFundTerm = /(基金|ETF|etf|联接|债基|货基|场内|场外)/.test(text);
      if (hasFundTerm || (codes.length && codes.every(code => code.startsWith("1") || code.startsWith("5")))) {
        return {mode: codes.length > 1 ? "comparison" : "single_product"};
      }
      return null;
    }

    function renderFundProductDiagnosis(context = {}) {
      const comparison = context.comparison || {};
      const products = comparison.products || (context.product ? [context.product] : []);
      const names = products.map(item => item.name || item.code).filter(Boolean);
      setAgentContextCollapsed(false);
      $("diagnosisContext").hidden = false;
      $("diagnosisTitle").textContent = names.length
        ? `${names.join("、")} · 产品事实`
        : "基金与 ETF · 产品研究";
      $("diagnosisMeta").textContent = "基金净值与 ETF 场内成交价分开呈现；历史收益不代表未来表现。";
      $("diagnosisPrice").textContent = "—";
      $("diagnosisChange").className = "diagnosis-change flat";
      $("diagnosisChange").textContent = "—";
      const metricsNode = $("diagnosisMetrics");
      metricsNode.innerHTML = "";
      const metrics = products.flatMap(item => [
        {
          label: `${item.name || item.code} · 净值`,
          value: item.nav == null ? "—" : `${numeric(item.nav)} · ${item.nav_date || "日期待核验"}`
        },
        {
          label: `${item.name || item.code} · 场内价`,
          value: item.live_quote?.price == null ? "不适用或暂未取得" : `${numeric(item.live_quote.price)} · ${pct(item.live_quote.pct_change)}`
        }
      ]).slice(0, 4);
      if (!metrics.length) metrics.push({label: "研究对象", value: "基金或 ETF"});
      for (const item of metrics) {
        const card = document.createElement("div"); card.className = "diagnosis-metric";
        const label = document.createElement("div"); label.className = "diagnosis-metric-label"; label.textContent = item.label;
        const value = document.createElement("div"); value.className = "diagnosis-metric-value"; value.textContent = item.value;
        card.append(label, value); metricsNode.appendChild(card);
      }
      const canvas = $("diagnosisKline");
      canvas.getContext("2d")?.clearRect(0, 0, canvas.width, canvas.height);
      renderAgentResearchContext();
    }

    function renderDiagnosisChart({title, meta, price, change, points, metrics = []}) {
      setAgentContextCollapsed(false);
      $("diagnosisContext").hidden = false;
      $("diagnosisTitle").textContent = title || "已识别研究对象";
      $("diagnosisMeta").textContent = meta || "数据时间待确认";
      $("diagnosisPrice").textContent = numeric(price);
      $("diagnosisChange").className = `diagnosis-change ${tone(Number(change || 0))}`;
      $("diagnosisChange").textContent = pct(change);
      const metricsNode = $("diagnosisMetrics");
      metricsNode.innerHTML = "";
      for (const item of metrics) {
        const card = document.createElement("div"); card.className = "diagnosis-metric";
        const label = document.createElement("div"); label.className = "diagnosis-metric-label"; label.textContent = item.label;
        const value = document.createElement("div"); value.className = "diagnosis-metric-value"; value.textContent = item.value ?? "—";
        card.append(label, value); metricsNode.appendChild(card);
      }
      renderAgentResearchContext();
      requestAnimationFrame(() => drawCandles($("diagnosisKline"), points || []));
    }

    const DIAGNOSIS_INDEX = {
      china: {symbol: "000001.SS", name: "上证综指"},
      us: {symbol: "^GSPC", name: "标普500"},
      japan: {symbol: "^N225", name: "日经225"},
      korea: {symbol: "^KS11", name: "韩国KOSPI"}
    };

    function diagnosisMarketEvidence(context = {}) {
      return context?.evidence || context || {};
    }

    function diagnosisTargetIndex(evidence, marketKey) {
      const preferred = DIAGNOSIS_INDEX[marketKey];
      const aligned = (evidence?.indices || []).filter(item =>
        item?.status === "available" && item?.same_date_as_analysis_target !== false
      );
      return aligned.find(item => item.symbol === preferred?.symbol) || aligned[0] || preferred || null;
    }

    function pointMarketDate(point, timezoneName) {
      return marketSessionDate(point?.timestamp, timezoneName || "UTC");
    }

    async function loadMarketDiagnosis(marketKey, context = {}) {
      if (!marketKey) return;
      const evidence = diagnosisMarketEvidence(context);
      const analysisTarget = evidence.analysis_target || context.analysis_target || context.analysisTarget || {};
      const targetMarketDate = analysisTarget.market_date || null;
      const liveAlignment = evidence.live_alignment || context.live_alignment || context.liveAlignment || {};
      if (!state.liveMarkets.length) {
        const data = await api("/markets/live");
        state.liveMarkets = data.markets || [];
      }
      const market = state.liveMarkets.find(item => item.key === marketKey);
      if (targetMarketDate && marketKey !== "london_gold") {
        const targetIndex = diagnosisTargetIndex(evidence, marketKey);
        let history = null;
        if (targetIndex?.symbol) {
          try {
            history = await api(`/indices/${encodeURIComponent(targetIndex.symbol)}/history?range=3mo`);
          } catch { /* use the evidence packet below */ }
        }
        const timezoneName = history?.timezone || market?.timezone || "UTC";
        const historyPoints = (history?.points || []).filter(point =>
          pointMarketDate(point, timezoneName) <= targetMarketDate
        );
        const evidencePoints = (targetIndex?.recent_bars || []).filter(point =>
          pointMarketDate(point, timezoneName) <= targetMarketDate
        );
        const points = historyPoints.length ? historyPoints : evidencePoints;
        const latest = points.at(-1) || targetIndex?.latest_bar || {};
        const previous = points.at(-2) || {};
        const evidenceChange = targetIndex?.metrics?.return_1d_pct;
        const computedChange = Number(previous.close)
          ? (Number(latest.close) / Number(previous.close) - 1) * 100
          : null;
        const targetChange = evidenceChange ?? computedChange;
        const liveMarketDate = liveAlignment.live_market_date
          || (market?.market_timestamp ? marketSessionDate(market.market_timestamp, market.timezone) : null);
        const newerLive = Boolean(liveMarketDate && liveMarketDate > targetMarketDate);
        const marketName = market?.name || evidence?.market_drivers?.market_label || "目标市场";
        const indexName = targetIndex?.name || market?.instrument || "代表性指数";
        const metaParts = [`Agent 本轮分析交易日 ${targetMarketDate}`, "日 K 与回答同一口径"];
        if (newerLive) metaParts.push(`最新分钟行情至 ${liveMarketDate}，未并入本轮回答`);
        renderDiagnosisChart({
          title: `${marketName} · ${indexName}`,
          meta: metaParts.join(" · "),
          price: latest.close ?? targetIndex?.metrics?.latest_close,
          change: targetChange,
          points,
          metrics: [
            {label: "回答交易日", value: targetMarketDate},
            {label: "当日涨跌", value: targetChange == null ? "—" : pct(targetChange)},
            {label: "最新行情日期", value: liveMarketDate || "待确认"},
            {label: "时间口径", value: newerLive ? "已分离，避免混用" : "与回答一致"},
            {label: "最新行情", value: market?.pct_change == null ? "—" : pct(market.pct_change)}
          ]
        });
        return;
      }
      if (!market || !(market.points || []).length) return;
      renderDiagnosisChart({
        title: `${market.name} · ${market.instrument}`,
        meta: `${market.session_label || "市场状态待确认"} · ${market.interval || "分钟"} K · 数据至 ${readableTime(market.market_timestamp)}`,
        price: market.latest_price,
        change: market.pct_change,
        points: market.points,
        metrics: [
          {label: "交易状态", value: market.session_label},
          {label: "行情周期", value: market.interval || "—"},
          {label: "数据时点", value: readableTime(market.market_timestamp)},
          {label: "前收", value: numeric(market.previous_close)},
          {label: "更新时间", value: delayText(market.delay_seconds, market.freshness)}
        ]
      });
    }

    async function loadStockDiagnosis(symbol) {
      if (!symbol) return;
      state.diagnosisSymbol = symbol;
      try {
        const isAShare = /\.(?:SS|SZ)$/i.test(String(symbol));
        const [history, fundamentals] = await Promise.all([
          api(`/stocks/${encodeURIComponent(symbol)}/history?range=3mo`),
          isAShare
            ? api(`/a-share/${encodeURIComponent(symbol)}/fundamentals`).catch(() => null)
            : Promise.resolve(null)
        ]);
        const metrics = history.metrics || {};
        const latest = (history.points || []).at(-1) || {};
        const quote = fundamentals?.valuation || null;
        const historyTimestamp = history.market_timestamp || latest.timestamp;
        const quoteTimestamp = quote?.market_timestamp || null;
        const quoteIsNewer = quoteTimestamp && (
          !historyTimestamp || Date.parse(quoteTimestamp) > Date.parse(historyTimestamp)
        );
        const quoteLabel = quote?.quote_label || "报价快照";
        renderDiagnosisChart({
          title: `${history.display_name || history.symbol || symbol} · ${history.symbol || symbol}`,
          meta: quoteIsNewer
            ? `${quoteLabel}至 ${readableTime(quoteTimestamp)} · 日 K 至 ${marketDateLabel(historyTimestamp, history?.timezone || "Asia/Shanghai")}`
            : `日 K · 数据至 ${marketDateLabel(historyTimestamp, history?.timezone || "Asia/Shanghai")} · 只描述已发生的技术结构`,
          price: quoteIsNewer ? quote.price : (metrics.latest_close ?? latest.close),
          change: quoteIsNewer ? quote.pct_change : metrics.return_1d_pct,
          points: history.points || [],
          metrics: [
            {label: "技术状态", value: metrics.technical_state || metrics.trend_state},
            {label: "RSI14", value: numeric(metrics.rsi_14)},
            {label: "MACD 柱", value: numeric(metrics.macd_histogram)},
            {label: "ATR14", value: metrics.atr_14_pct == null ? "—" : `${numeric(metrics.atr_14_pct)}%`},
            {label: "5/20日量比", value: numeric(metrics.volume_ratio_5_20)}
          ]
        });
      } catch {
        $("diagnosisMeta").textContent = "这只股票的 K 线正在同步，研究回答仍会保留已取得的证据。";
      }
    }

    function renderMultiStockDiagnosis(targets) {
      const names = targets.map(item => item.name || item.symbol);
      setAgentContextCollapsed(false);
      $("diagnosisContext").hidden = false;
      $("diagnosisTitle").textContent = `${names.join("、")} · 多股比较`;
      $("diagnosisMeta").textContent = `本轮同时研究 ${targets.length} 只股票；继续指定其中一只，可加载对应日 K 线。`;
      $("diagnosisPrice").textContent = "—";
      $("diagnosisChange").className = "diagnosis-change flat";
      $("diagnosisChange").textContent = "—";
      const metricsNode = $("diagnosisMetrics");
      metricsNode.innerHTML = "";
      [
        {label: "研究模式", value: "多股比较"},
        {label: "研究对象", value: `${targets.length} 只`},
        {label: "行情联动", value: "指定单只后展示"}
      ].forEach(item => {
        const card = document.createElement("div"); card.className = "diagnosis-metric";
        const label = document.createElement("div"); label.className = "diagnosis-metric-label"; label.textContent = item.label;
        const value = document.createElement("div"); value.className = "diagnosis-metric-value"; value.textContent = item.value;
        card.append(label, value); metricsNode.appendChild(card);
      });
      const canvas = $("diagnosisKline");
      canvas.getContext("2d")?.clearRect(0, 0, canvas.width, canvas.height);
      renderAgentResearchContext();
    }

    async function maybeUpdateDiagnosis(data, question = "") {
      const fundContext = fundProductDiagnosisContext(data, question);
      if (fundContext) {
        state.diagnosisSymbol = null;
        renderFundProductDiagnosis(fundContext);
        return;
      }
      const targets = diagnosisResearchTargets(data);
      if (targets.length > 1) {
        renderMultiStockDiagnosis(targets);
        return;
      }
      if (targets.length === 1) {
        await loadStockDiagnosis(targets[0].symbol);
        return;
      }
      const symbol = inferDiagnosisSymbol(data, question);
      if (symbol) {
        await loadStockDiagnosis(symbol);
        return;
      }
      const marketKey = inferDiagnosisMarketKey(data, question);
      if (marketKey) await loadMarketDiagnosis(marketKey, data);
    }

    async function syncDiagnosisFromConversation(messages) {
      if (!messages.length) return;
      const lastAssistant = [...messages].reverse().find(item => item.role === "assistant");
      const lastUser = [...messages].reverse().find(item => item.role === "user");
      const metadata = lastAssistant?.metadata || {};
      const context = {
        symbol: metadata.symbol,
        market_key: metadata.market_key,
        research_targets: metadata.research_targets || metadata.researchTargets || [],
        analysis_target: metadata.analysis_target || null,
        fund_product_context: metadata.fund_product_context || null
      };
      const fundContext = fundProductDiagnosisContext(context, lastUser?.content || "");
      if (fundContext) {
        state.diagnosisSymbol = null;
        renderFundProductDiagnosis(fundContext);
        return;
      }
      const targets = diagnosisResearchTargets(context);
      if (targets.length > 1) {
        renderMultiStockDiagnosis(targets);
        return;
      }
      if (targets.length === 1) {
        await loadStockDiagnosis(targets[0].symbol);
        return;
      }
      const symbol = inferDiagnosisSymbol(context, lastUser?.content || "");
      if (symbol) {
        await loadStockDiagnosis(symbol);
        return;
      }
      const marketKey = inferDiagnosisMarketKey(context, lastUser?.content || "");
      if (marketKey) await loadMarketDiagnosis(marketKey, context);
    }

    function marketDateLabel(value, timezoneName = "Asia/Shanghai") {
      if (!value) return "市场日期待确认";
      const matched = String(value).match(/^(\d{4})-(\d{2})-(\d{2})$/);
      if (matched) return `${matched[1]}-${matched[2]}-${matched[3]}`;
      const marketDate = marketSessionDate(value, timezoneName);
      return /^\d{4}-\d{2}-\d{2}$/.test(String(marketDate || ""))
        ? marketDate
        : readableTime(value);
    }

    function drawSparkline(canvas, points, changeValue = 0) {
      if (!canvas || !points?.length) return;
      const rect = canvas.getBoundingClientRect();
      const ratio = window.devicePixelRatio || 1;
      const width = Math.max(80, rect.width || 96);
      const height = Math.max(42, rect.height || 62);
      canvas.width = width * ratio; canvas.height = height * ratio;
      const ctx = canvas.getContext("2d"); ctx.scale(ratio, ratio); ctx.clearRect(0, 0, width, height);
      const values = points.map(item => Number(item.close)).filter(Number.isFinite);
      if (values.length < 2) return;
      const min = Math.min(...values); const max = Math.max(...values); const span = max - min || 1;
      const pad = 5; const color = Number(changeValue) >= 0 ? "#e34b52" : "#15966a";
      const coordinates = values.map((value, index) => ({x: pad + index / (values.length - 1) * (width - pad * 2), y: pad + (max - value) / span * (height - pad * 2)}));
      const gradient = ctx.createLinearGradient(0, 0, 0, height);
      gradient.addColorStop(0, Number(changeValue) >= 0 ? "rgba(227,75,82,.17)" : "rgba(21,150,106,.16)");
      gradient.addColorStop(1, "rgba(255,255,255,0)");
      ctx.beginPath(); ctx.moveTo(coordinates[0].x, height - pad);
      for (const point of coordinates) ctx.lineTo(point.x, point.y);
      ctx.lineTo(coordinates.at(-1).x, height - pad); ctx.closePath(); ctx.fillStyle = gradient; ctx.fill();
      ctx.beginPath(); coordinates.forEach((point, index) => index ? ctx.lineTo(point.x, point.y) : ctx.moveTo(point.x, point.y));
      ctx.strokeStyle = color; ctx.lineWidth = 1.7; ctx.lineJoin = "round"; ctx.lineCap = "round"; ctx.stroke();
    }

    function renderAShareIndices(data) {
      const container = $("aShareIndexCards"); container.innerHTML = "";
      const order = ["000001.SS", "399001.SZ", "399006.SZ", "000688.SS"];
      const indexMap = new Map((data.indices || []).map(item => [item.symbol, item]));
      const items = order.map(symbol => indexMap.get(symbol)).filter(Boolean);
      for (const item of items) {
        const metrics = item.metrics || {};
        const card = document.createElement("article"); card.className = "ashare-index-card interactive";
        card.tabIndex = 0;
        card.setAttribute("role", "button");
        card.setAttribute("aria-label", `研究${item.name}`);
        const identity = document.createElement("div");
        const name = document.createElement("div"); name.className = "ashare-index-name"; name.textContent = item.name;
        const symbol = document.createElement("div"); symbol.className = "ashare-index-symbol"; symbol.textContent = `${item.symbol} · ${marketDateLabel(item.latest_bar?.timestamp || item.market_timestamp)}`;
        const value = document.createElement("div"); value.className = "ashare-index-value"; value.textContent = numeric(metrics.latest_close);
        const change = document.createElement("div"); change.className = `ashare-index-change ${tone(metrics.return_1d_pct)}`; change.textContent = pct(metrics.return_1d_pct);
        identity.append(name, symbol, value, change);
        const canvas = document.createElement("canvas"); canvas.className = "ashare-sparkline"; canvas.setAttribute("aria-label", `${item.name}最近五个交易日走势`);
        const meta = document.createElement("div"); meta.className = "ashare-index-meta";
        const period = document.createElement("span"); period.textContent = `5日 ${pct(metrics.return_5d_pct)} · RSI ${numeric(metrics.rsi_14)}`;
        const technical = document.createElement("span"); technical.className = "technical-tag"; technical.textContent = metrics.technical_state || metrics.trend_state || "技术结构待确认";
        meta.append(period, technical); card.append(identity, canvas, meta); container.appendChild(card);
        const question = `分析${item.name}当前行情：先区分最新数据时点和上一完整交易日，再说明已发生的技术结构、可能驱动、反方证据和不能确认的部分。`;
        card.addEventListener("click", () => prepareAgentQuestion(question));
        card.addEventListener("keydown", event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); prepareAgentQuestion(question); } });
        requestAnimationFrame(() => drawSparkline(canvas, item.recent_bars || [], metrics.return_1d_pct));
      }
      if (!items.length) container.innerHTML = '<div class="empty">A 股指数快照正在更新</div>';
    }

    function marketTurnoverLabel(value) {
      const amount = Number(value || 0);
      if (!Number.isFinite(amount) || amount <= 0) return "—";
      return amount >= 10000
        ? `${(amount / 10000).toFixed(2)} 万亿元`
        : `${numeric(amount)} 亿元`;
    }

    function renderMarketQuickRead() {
      const container = $("marketQuickGrid");
      if (!container) return;
      const packet = state.marketBreadth || {};
      const breadth = packet.breadth || {};
      const distribution = packet.distribution || {};
      const turnover = packet.turnover || {};
      const sectors = state.marketSectors || [];
      const marketDate = packet.market_date || "";
      const total = Number(breadth.total || 0);
      const marketState = breadth.state || (total ? "市场结构已更新" : "更新中");

      $("marketQuickTitle").textContent = total ? `A股${marketState}` : "A股一眼看懂";
      $("marketQuickMeta").textContent = total
        ? `${marketDate ? `${marketDate} · ` : ""}覆盖沪深京 ${Number(total).toLocaleString("zh-CN")} 只股票；以下只描述已经发生的市场结构。`
        : "正在汇总全市场涨跌、成交和领涨方向";

      const medianRaw = distribution.median_pct_change;
      const median = medianRaw === null || medianRaw === undefined
        ? Number.NaN
        : Number(medianRaw);
      const turnoverTotal = Number(turnover.total_amount_100m_cny || 0);
      const turnoverHistory = turnover.history_comparison || {};
      const leadingSector = sectors[0] || null;
      const leadingName = leadingSector?.name || "更新中";
      const leadingChangeRaw = leadingSector?.pct_change;
      const leadingChange = leadingChangeRaw === null || leadingChangeRaw === undefined
        ? Number.NaN
        : Number(leadingChangeRaw);
      const turnoverChangeRaw = turnoverHistory.change_vs_previous_pct;
      const turnoverChange = turnoverChangeRaw === null || turnoverChangeRaw === undefined
        ? Number.NaN
        : Number(turnoverChangeRaw);
      const cards = [
        {
          label: "市场状态",
          value: total ? marketState : "更新中",
          detail: total
            ? `上涨 ${Number(breadth.advancers || 0).toLocaleString("zh-CN")} 只 · 下跌 ${Number(breadth.decliners || 0).toLocaleString("zh-CN")} 只`
            : "正在读取涨跌家数",
          valueClass: Number(breadth.advancers || 0) >= Number(breadth.decliners || 0) ? "up" : "down"
        },
        {
          label: "全市场涨跌中位数",
          value: Number.isFinite(median) ? pct(median) : "—",
          detail: Number.isFinite(median) ? "一半股票高于该值，一半低于该值" : "正在计算大多数股票的表现",
          valueClass: Number.isFinite(median) ? tone(median) : ""
        },
        {
          label: "当日累计成交额",
          value: marketTurnoverLabel(turnoverTotal),
          detail: turnoverHistory.status === "available" && Number.isFinite(turnoverChange)
            ? `较上一完整交易日 ${pct(turnoverChange)}`
            : "同口径历史正在逐日积累",
          valueClass: ""
        },
        {
          label: "领涨方向",
          value: leadingName,
          detail: Number.isFinite(leadingChange)
            ? `${pct(leadingChange)} · 按板块涨幅排序，不是买入建议`
            : "正在读取板块表现",
          valueClass: Number.isFinite(leadingChange) ? tone(leadingChange) : ""
        }
      ];
      container.innerHTML = "";
      cards.forEach(item => {
        const card = document.createElement("article"); card.className = "market-quick-card";
        const label = document.createElement("span"); label.textContent = item.label;
        const value = document.createElement("strong"); value.className = item.valueClass || ""; value.textContent = item.value;
        const detail = document.createElement("small"); detail.textContent = item.detail;
        card.append(label, value, detail); container.appendChild(card);
      });
    }

    function updateMarketDashboardDate() {
      const breadth = state.marketBreadth;
      if (!breadth?.market_date) return;
      const liveChina = state.liveMarkets.find(item => item.name === "中国A股" || item.instrument === "上证综指");
      const liveDate = liveChina?.market_timestamp ? marketSessionDate(liveChina.market_timestamp, "Asia/Shanghai") : null;
      const isPreviousCompleteSession = Boolean(liveDate && breadth.market_date < liveDate);
      const label = isPreviousCompleteSession ? "上一完整交易日" : "市场日期";
      $("marketDashboardDate").textContent = `${label} ${marketDateLabel(breadth.market_date)} · 沪深京 ${breadth.coverage?.returned || breadth.breadth?.total || 0} 只`;
    }

    function renderMarketBreadth(data) {
      state.marketBreadth = data;
      renderHomeFocus();
      renderMarketQuickRead();
      const breadth = data.breadth || {};
      const container = $("marketBreadthOverview"); container.innerHTML = "";
      if (data.status !== "available" || !breadth.total) {
        container.innerHTML = '<div class="empty">全市场广度正在整理</div>'; return;
      }
      const advance = Math.max(0, Number(breadth.advance_ratio || 0) * 100);
      const unchanged = Math.max(0, Number(breadth.unchanged_ratio || 0) * 100);
      const declineStart = Math.min(100, advance + unchanged);
      const ring = document.createElement("div"); ring.className = "breadth-ring";
      ring.style.background = `conic-gradient(var(--red) 0 ${advance}%, #cfd6df ${advance}% ${declineStart}%, var(--green) ${declineStart}% 100%)`;
      const center = document.createElement("div"); center.className = "breadth-ring-center";
      const total = document.createElement("strong"); total.textContent = numeric(breadth.total);
      const totalLabel = document.createElement("span"); totalLabel.textContent = "覆盖股票"; center.append(total, totalLabel); ring.appendChild(center);
      const list = document.createElement("div"); list.className = "breadth-stat-list";
      for (const [label, value, dotClass, ratio] of [["上涨", breadth.advancers, "up-dot", breadth.advance_ratio], ["平盘", breadth.unchanged, "", breadth.unchanged_ratio], ["下跌", breadth.decliners, "down-dot", breadth.decline_ratio]]) {
        const item = document.createElement("div"); item.className = "breadth-stat";
        const dot = document.createElement("i"); dot.className = `breadth-stat-dot ${dotClass}`;
        const labelNode = document.createElement("span"); labelNode.textContent = `${label} ${(Number(ratio || 0) * 100).toFixed(2)}%`;
        const valueNode = document.createElement("strong"); valueNode.textContent = numeric(value);
        item.append(dot, labelNode, valueNode); list.appendChild(item);
      }
      container.append(ring, list);
      $("breadthState").textContent = breadth.state || "市场广度已更新";
      updateMarketDashboardDate();
    }

    function renderMarketDistribution(data) {
      const distribution = data.distribution || {};
      const container = $("marketDistribution"); container.innerHTML = "";
      const bins = distribution.bins || {};
      const items = [
        ["≥ 3%", bins.strong_advancers_ge_3, "advance"],
        ["0 ～ 3%", bins.mild_advancers_gt_0_lt_3, "advance"],
        ["平盘", bins.unchanged, "flat"],
        ["-3% ～ 0", bins.mild_decliners_lt_0_gt_neg3, "decline"],
        ["≤ -3%", bins.strong_decliners_le_neg3, "decline"]
      ];
      if (distribution.status !== "available" || !items.some(item => Number(item[1]) > 0)) {
        container.innerHTML = '<div class="empty">涨跌分布正在整理</div>'; return;
      }
      const summary = document.createElement("div"); summary.className = "distribution-summary";
      const p25 = document.createElement("span"); p25.textContent = `25%分位 `; const p25Value = document.createElement("strong"); p25Value.className = tone(distribution.p25_pct_change); p25Value.textContent = pct(distribution.p25_pct_change); p25.appendChild(p25Value);
      const p75 = document.createElement("span"); p75.textContent = `75%分位 `; const p75Value = document.createElement("strong"); p75Value.className = tone(distribution.p75_pct_change); p75Value.textContent = pct(distribution.p75_pct_change); p75.appendChild(p75Value);
      summary.append(p25, p75);
      const bars = document.createElement("div"); bars.className = "distribution-bars";
      const max = Math.max(...items.map(item => Number(item[1] || 0)), 1);
      for (const [label, value, kind] of items) {
        const column = document.createElement("div"); column.className = "distribution-column";
        const count = document.createElement("span"); count.className = "distribution-value"; count.textContent = numeric(value || 0);
        const bar = document.createElement("div"); bar.className = `distribution-bar ${kind}`; bar.style.height = `${Math.max(4, Number(value || 0) / max * 92)}px`;
        const labelNode = document.createElement("span"); labelNode.className = "distribution-label"; labelNode.textContent = label;
        column.append(count, bar, labelNode); bars.appendChild(column);
      }
      container.append(summary, bars);
      $("distributionMedian").textContent = `中位数 ${pct(distribution.median_pct_change)}`;
    }

    function renderTurnover(data) {
      const turnover = data.turnover || {};
      const container = $("marketTurnover"); container.innerHTML = "";
      if (turnover.status !== "available") {
        container.innerHTML = '<div class="empty">成交额正在汇总</div>'; return;
      }
      const total = Number(turnover.total_amount_100m_cny || 0);
      const exchanges = turnover.exchanges || {};
      const values = [["沪市", exchanges.shanghai?.amount_100m_cny || 0], ["深市", exchanges.shenzhen?.amount_100m_cny || 0], ["北交所", exchanges.beijing?.amount_100m_cny || 0]];
      const totalRow = document.createElement("div"); totalRow.className = "turnover-total";
      const totalValue = document.createElement("strong"); totalValue.textContent = numeric(total);
      const unit = document.createElement("span"); unit.textContent = "亿元 · 当日累计"; totalRow.append(totalValue, unit);
      const track = document.createElement("div"); track.className = "turnover-track";
      values.forEach(([, value]) => { const segment = document.createElement("span"); segment.style.width = `${total ? Number(value) / total * 100 : 0}%`; track.appendChild(segment); });
      const exchangeGrid = document.createElement("div"); exchangeGrid.className = "turnover-exchanges";
      values.forEach(([label, value]) => {
        const item = document.createElement("div"); item.className = "turnover-exchange";
        const labelNode = document.createElement("span"); labelNode.textContent = label;
        const valueNode = document.createElement("strong"); valueNode.textContent = `${numeric(value)} 亿`;
        item.append(labelNode, valueNode); exchangeGrid.appendChild(item);
      });
      const history = turnover.history_comparison || {};
      const foot = document.createElement("div"); foot.className = "turnover-foot";
      foot.textContent = history.status === "available" && history.change_vs_previous_pct !== null
        ? `较上一交易日 ${pct(history.change_vs_previous_pct)}；同口径历史由本系统逐日积累。`
        : "同口径历史正在逐日积累，当前不判断放量或缩量。";
      container.append(totalRow, track, exchangeGrid, foot);
      $("turnoverStatus").textContent = `覆盖 ${turnover.coverage?.valid_amount || data.coverage?.returned || 0} 只`;
    }

    async function loadMarketDashboard() {
      const [indicesResult, breadthResult] = await Promise.allSettled([
        api("/indices?scope=all&group=china"),
        api("/markets/breadth")
      ]);
      if (indicesResult.status === "fulfilled") renderAShareIndices(indicesResult.value);
      else $("aShareIndexCards").innerHTML = '<div class="empty">A 股指数快照正在更新</div>';
      if (breadthResult.status === "fulfilled") {
        renderMarketBreadth(breadthResult.value);
        renderMarketDistribution(breadthResult.value);
        renderTurnover(breadthResult.value);
      } else {
        $("marketBreadthOverview").innerHTML = '<div class="empty">全市场广度正在更新</div>';
        $("marketDistribution").innerHTML = '<div class="empty">涨跌分布正在更新</div>';
        $("marketTurnover").innerHTML = '<div class="empty">成交额正在更新</div>';
        $("marketDashboardDate").textContent = "正在对齐最新市场日期";
      }
    }

    function renderLiveMarkets(data) {
      state.liveMarkets = data.markets || [];
      const container = $("liveMarkets"); container.innerHTML = "";
      for (const market of data.markets || []) {
        const card = document.createElement("div"); card.className = `live-card interactive${market.is_open ? " open" : ""}`;
        card.tabIndex = 0;
        card.setAttribute("role", "button");
        card.setAttribute("aria-label", `研究${market.name}${market.instrument}`);
        const top = document.createElement("div"); top.className = "live-card-top";
        const identity = document.createElement("div");
        const name = document.createElement("div"); name.className = "live-market-name"; name.textContent = market.name;
        const instrument = document.createElement("div"); instrument.className = "live-instrument"; instrument.textContent = market.instrument;
        identity.append(name, instrument);
        const badge = document.createElement("span"); badge.className = `session-badge${market.is_open ? " open" : ""}`; badge.textContent = market.session_label;
        top.append(identity, badge);
        const priceRow = document.createElement("div"); priceRow.className = "live-price-row";
        const price = document.createElement("span"); price.className = "live-price"; price.textContent = numeric(market.latest_price);
        const change = document.createElement("span"); change.className = `live-change ${tone(market.pct_change)}`; change.textContent = pct(market.pct_change);
        priceRow.append(price, change);
        const canvas = document.createElement("canvas"); canvas.className = "kline"; canvas.setAttribute("aria-label", `${market.instrument}当日K线`);
        const meta = document.createElement("div"); meta.className = "live-meta";
        const marketTime = market.market_timestamp ? new Date(market.market_timestamp).toLocaleTimeString("zh-CN", {hour:"2-digit", minute:"2-digit"}) : "未知";
        meta.textContent = `${market.interval || "—"} · 最新 ${marketTime} · ${delayText(market.delay_seconds, market.freshness)}`;
        card.append(top, priceRow, canvas, meta); container.appendChild(card);
        const question = `分析${market.name}的${market.instrument}当前行情：先说明报价和数据时间，再分析已发生的结构、可能驱动、反方证据和不能确认的部分。`;
        card.addEventListener("click", () => prepareAgentQuestion(question));
        card.addEventListener("keydown", event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); prepareAgentQuestion(question); } });
        requestAnimationFrame(() => drawCandles(canvas, market.points));
      }
      if (!container.children.length) container.innerHTML = '<div class="empty">盘中数据正在同步</div>';
      const coverage = data.coverage || {};
      $("liveSource").textContent = `覆盖 ${coverage.available || 0}/${coverage.requested || 0}，当前交易中 ${coverage.open || 0} 个。${data.session_method || ""}`;
      liveRefreshRemaining = data.refresh_after_seconds || 30;
      updateMarketDashboardDate();
      renderHomeFocus();
    }

    let liveRefreshRemaining = 30;
    async function loadLiveMarkets() {
      $("refreshLive").disabled = true;
      try { renderLiveMarkets(await api("/markets/live")); }
      catch (error) { $("liveSource").textContent = "行情正在重新连接，页面将自动重试"; }
      finally { $("refreshLive").disabled = false; }
    }

    async function loadSectors() {
      try { renderSectors(await api("/sectors/hot?limit=10")); }
      catch (error) { $("sectorSource").textContent = "正在整理最新板块市场快照"; }
    }

    async function loadWatchlist() {
      if (!state.user) return;
      try {
        const [watchlistResult, assetsResult, actionsResult] = await Promise.allSettled([
          api("/me/watchlist/brief"),
          api("/v1/stock-workspaces"),
          api("/me/research-actions")
        ]);
        if (watchlistResult.status !== "fulfilled") throw watchlistResult.reason;
        const watchlist = watchlistResult.value;
        const assets = assetsResult.status === "fulfilled" ? assetsResult.value : null;
        const actions = actionsResult.status === "fulfilled" ? actionsResult.value : {items: [], summary: {}};
        renderWatchlist(watchlist, actions, assets);
      } catch (error) { $("watchlistSource").textContent = "自选股正在更新"; }
    }
