(function (root, factory) {
  const api = factory(root);
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (root) root.QSKlineExplorer = api;
})(typeof window !== "undefined" ? window : globalThis, function (root) {
  "use strict";

  const PERIODS = Object.freeze([
    ["intraday", "分时"],
    ["daily", "日K"],
    ["weekly", "周K"],
    ["monthly", "月K"],
    ["yearly", "年K"]
  ]);
  const RANGES = Object.freeze([
    ["3mo", "近3月"],
    ["6mo", "近6月"],
    ["1y", "近1年"],
    ["2y", "近2年"],
    ["5y", "近5年"]
  ]);
  let activeDialog = null;

  function finite(value, fallback = null) {
    const number = Number(value);
    return Number.isFinite(number) ? number : fallback;
  }

  function formatNumber(value, digits = 2) {
    const number = finite(value);
    return number == null ? "—" : number.toLocaleString("zh-CN", {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits
    });
  }

  function formatPercent(value) {
    const number = finite(value);
    if (number == null) return "—";
    return `${number > 0 ? "+" : ""}${number.toFixed(2)}%`;
  }

  function compactVolume(value) {
    const number = finite(value, 0);
    if (number >= 1e8) return `${(number / 1e8).toFixed(2)}亿`;
    if (number >= 1e4) return `${(number / 1e4).toFixed(1)}万`;
    return Math.round(number).toLocaleString("zh-CN");
  }

  function readableTime(value, timezone = "Asia/Shanghai") {
    if (!value) return "时间待确认";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return new Intl.DateTimeFormat("zh-CN", {
      timeZone: timezone,
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false
    }).format(date).replace("24:", "00:");
  }

  function periodLabel(period) {
    return Object.fromEntries(PERIODS)[period] || "日K";
  }

  function rangeLabel(range) {
    return Object.fromEntries(RANGES)[range] || "近1年";
  }

  function safeStorage() {
    try { return root?.sessionStorage || null; } catch { return null; }
  }

  function loadSelection(key, fallback) {
    const storage = safeStorage();
    if (!storage || !key) return fallback;
    try {
      const saved = JSON.parse(storage.getItem(key) || "{}");
      return {
        period: PERIODS.some(([value]) => value === saved.period) ? saved.period : fallback.period,
        range: RANGES.some(([value]) => value === saved.range) ? saved.range : fallback.range
      };
    } catch {
      return fallback;
    }
  }

  function saveSelection(key, selection) {
    const storage = safeStorage();
    if (!storage || !key) return;
    try { storage.setItem(key, JSON.stringify(selection)); } catch {}
  }

  function createButton(label, className, pressed, handler) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `${className}${pressed ? " active" : ""}`;
    button.textContent = label;
    button.setAttribute("aria-pressed", pressed ? "true" : "false");
    button.addEventListener("click", handler);
    return button;
  }

  function metricsFor(points) {
    if (!points.length) return {};
    const first = points[0];
    const last = points.at(-1);
    const highs = points.map(item => finite(item.high)).filter(value => value != null);
    const lows = points.map(item => finite(item.low)).filter(value => value != null);
    const firstClose = finite(first.close);
    const lastClose = finite(last.close);
    return {
      latest: lastClose,
      change: firstClose && lastClose != null ? (lastClose / firstClose - 1) * 100 : null,
      high: highs.length ? Math.max(...highs) : null,
      low: lows.length ? Math.min(...lows) : null,
      volume: points.reduce((sum, item) => sum + finite(item.volume, 0), 0)
    };
  }

  function latestPeriodChange(points) {
    if (points.length < 2) return null;
    const previous = finite(points.at(-2)?.close);
    const latest = finite(points.at(-1)?.close);
    return previous && latest != null ? (latest / previous - 1) * 100 : null;
  }

  function createExplorer(container, options = {}) {
    if (!container) return null;
    const charts = root?.QSCharts;
    if (!charts?.createInteractiveKline || !charts?.aggregateCandles) {
      container.innerHTML = '<div class="empty">行情图表组件正在加载，请稍后重试。</div>';
      return null;
    }
    const symbol = String(options.symbol || "").trim();
    const name = options.name || symbol;
    const request = options.request;
    const storageKey = options.persist === false ? null : `qingshu:kline-explorer:v1:${options.storageKey || symbol}`;
    let selection = loadSelection(storageKey, {
      period: options.initialPeriod || "daily",
      range: options.initialRange || "1y"
    });
    let chartController = null;
    let destroyed = false;
    let renderToken = 0;
    const cache = new Map();

    container.innerHTML = "";
    container.classList.add("qs-kline-host");
    if (options.expanded) container.classList.add("expanded");
    const shell = document.createElement("section"); shell.className = "qs-kline-explorer";
    const head = document.createElement("div"); head.className = "qs-kline-head";
    const identity = document.createElement("div"); identity.className = "qs-kline-identity";
    const title = document.createElement("div"); title.className = "qs-kline-title"; title.textContent = name;
    const subtitle = document.createElement("div"); subtitle.className = "qs-kline-subtitle"; subtitle.textContent = symbol;
    identity.append(title, subtitle);
    const quote = document.createElement("div"); quote.className = "qs-kline-quote";
    const quotePrice = document.createElement("strong"); quotePrice.textContent = "—";
    const quoteChange = document.createElement("span"); quoteChange.textContent = "—";
    quote.append(quotePrice, quoteChange);
    head.append(identity, quote);

    const toolbar = document.createElement("div"); toolbar.className = "qs-kline-toolbar";
    const periodWrap = document.createElement("div"); periodWrap.className = "qs-kline-control";
    const periodName = document.createElement("span"); periodName.className = "qs-kline-control-label"; periodName.textContent = "周期";
    const periodButtons = document.createElement("div"); periodButtons.className = "qs-kline-buttons"; periodButtons.setAttribute("role", "group"); periodButtons.setAttribute("aria-label", "K线周期");
    periodWrap.append(periodName, periodButtons);
    const rangeWrap = document.createElement("div"); rangeWrap.className = "qs-kline-control";
    const rangeName = document.createElement("span"); rangeName.className = "qs-kline-control-label"; rangeName.textContent = "查看范围";
    const rangeButtons = document.createElement("div"); rangeButtons.className = "qs-kline-buttons"; rangeButtons.setAttribute("role", "group"); rangeButtons.setAttribute("aria-label", "K线查看范围");
    rangeWrap.append(rangeName, rangeButtons);
    const expand = document.createElement("button"); expand.type = "button"; expand.className = "qs-kline-expand"; expand.textContent = "放大查看"; expand.setAttribute("aria-label", `放大查看${name}行情详情`);
    toolbar.append(periodWrap, rangeWrap);
    if (options.showExpand !== false && !options.expanded) toolbar.appendChild(expand);

    const meta = document.createElement("div"); meta.className = "qs-kline-meta"; meta.textContent = "正在读取真实行情…";
    const chartWrap = document.createElement("div"); chartWrap.className = "qs-kline-chart-wrap";
    const canvas = document.createElement("canvas"); canvas.className = "qs-kline-canvas"; canvas.tabIndex = 0;
    const loading = document.createElement("div"); loading.className = "qs-kline-loading"; loading.textContent = "正在整理行情图表…";
    chartWrap.append(canvas, loading);
    const legend = document.createElement("div"); legend.className = "qs-kline-legend";
    legend.innerHTML = '<span><i class="ma5"></i>MA5</span><span><i class="ma10"></i>MA10</span><span><i class="ma20"></i>MA20</span><span>拖拽平移 · 滚轮缩放 · 双击复位</span>';
    const metricGrid = document.createElement("div"); metricGrid.className = "qs-kline-metrics";
    shell.append(head, toolbar, meta, chartWrap, legend, metricGrid); container.appendChild(shell);

    async function fetchPayload(period) {
      const historyRange = period === "yearly" ? "5y" : "2y";
      const key = period === "intraday" ? "intraday" : `history:${historyRange}`;
      if (cache.has(key)) return cache.get(key);
      if (typeof request !== "function") throw new Error("missing request function");
      const endpoint = period === "intraday"
        ? `/stocks/${encodeURIComponent(symbol)}/intraday`
        : `/stocks/${encodeURIComponent(symbol)}/history?range=${historyRange}`;
      const promise = Promise.resolve(request(endpoint)).catch(error => {
        cache.delete(key);
        throw error;
      });
      cache.set(key, promise);
      return promise;
    }

    function renderControls() {
      periodButtons.innerHTML = "";
      PERIODS.forEach(([value, label]) => {
        periodButtons.appendChild(createButton(label, "qs-kline-button", selection.period === value, () => {
          if (selection.period === value) return;
          selection.period = value;
          saveSelection(storageKey, selection);
          void render();
        }));
      });
      rangeButtons.innerHTML = "";
      if (selection.period === "intraday") {
        const today = createButton("当日", "qs-kline-button", true, () => {});
        today.disabled = true;
        rangeButtons.appendChild(today);
      } else {
        RANGES.forEach(([value, label]) => {
          rangeButtons.appendChild(createButton(label, "qs-kline-button", selection.range === value, () => {
            if (selection.range === value) return;
            selection.range = value;
            saveSelection(storageKey, selection);
            void render();
          }));
        });
      }
    }

    function renderMetrics(points, payload) {
      const visible = selection.period === "intraday" ? points : charts.candlesInRange(points, selection.range);
      const metrics = metricsFor(visible);
      const latestPrice = selection.period === "intraday"
        ? finite(payload.latest_price ?? payload.regular_market_price ?? metrics.latest)
        : finite(points.at(-1)?.close);
      const latestChange = selection.period === "intraday"
        ? finite(payload.pct_change)
        : latestPeriodChange(points);
      quotePrice.textContent = formatNumber(latestPrice);
      quoteChange.textContent = formatPercent(latestChange);
      quoteChange.className = latestChange > 0 ? "up" : latestChange < 0 ? "down" : "";
      metricGrid.innerHTML = "";
      for (const [label, value] of [
        [selection.period === "intraday" ? "当日涨跌" : "区间涨跌", formatPercent(metrics.change)],
        ["区间最高", formatNumber(metrics.high)],
        ["区间最低", formatNumber(metrics.low)],
        ["区间成交量", compactVolume(metrics.volume)]
      ]) {
        const item = document.createElement("div"); item.className = "qs-kline-metric";
        const labelNode = document.createElement("span"); labelNode.textContent = label;
        const valueNode = document.createElement("strong"); valueNode.textContent = value;
        item.append(labelNode, valueNode); metricGrid.appendChild(item);
      }
    }

    async function render() {
      const token = ++renderToken;
      renderControls();
      shell.classList.remove("custom-view");
      delete meta.dataset.viewport;
      loading.hidden = false;
      loading.textContent = "正在整理行情图表…";
      canvas.hidden = true;
      chartController?.destroy?.();
      chartController = null;
      try {
        const payload = await fetchPayload(selection.period);
        if (destroyed || token !== renderToken) return;
        const points = charts.aggregateCandles(payload.points || [], selection.period);
        if (!points.length) throw new Error("empty market series");
        const visibleBars = selection.period === "intraday"
          ? Math.min(points.length, 180)
          : charts.visibleBarsForRange(points, selection.range);
        const timezone = payload.timezone || options.timezone || "Asia/Shanghai";
        const asOf = payload.market_timestamp || points.at(-1)?.time;
        const source = payload.source || "公开行情源";
        const rangeText = selection.period === "intraday" ? "当日" : rangeLabel(selection.range);
        const basis = selection.period === "intraday"
          ? "1分钟行情"
          : selection.period === "daily"
            ? "日线OHLC（未额外复权）"
            : `由日线OHLC聚合的${periodLabel(selection.period)}`;
        meta.textContent = `${periodLabel(selection.period)} · ${rangeText} · 数据至 ${readableTime(asOf, timezone)} · ${basis} · ${source}`;
        canvas.setAttribute("aria-label", `${name}${periodLabel(selection.period)}，${rangeText}。方向键查看历史，加减键缩放，Home键或双击复位。`);
        canvas.hidden = false;
        loading.hidden = true;
        renderMetrics(points, payload);
        requestAnimationFrame(() => {
          if (destroyed || token !== renderToken || !canvas.isConnected) return;
          chartController = charts.createInteractiveKline(canvas, points, {
            visibleBars,
            minimumBars: ["monthly", "yearly"].includes(selection.period) ? 2 : selection.period === "weekly" ? 4 : 12,
            showMovingAverages: true,
            showVolume: true,
            onStateChange(viewport) {
              if (token !== renderToken || !viewport) return;
              const custom = viewport.historical || viewport.visibleBars !== visibleBars;
              shell.classList.toggle("custom-view", custom);
              if (custom) meta.dataset.viewport = `自定义视图 · ${viewport.visibleBars}根`;
              else delete meta.dataset.viewport;
            }
          });
        });
        options.onSelectionChange?.({...selection});
      } catch {
        if (destroyed || token !== renderToken) return;
        canvas.hidden = true;
        loading.hidden = false;
        loading.innerHTML = "";
        const copy = document.createElement("span"); copy.textContent = "行情图表暂未完整返回。";
        const retry = document.createElement("button"); retry.type = "button"; retry.className = "qs-kline-retry"; retry.textContent = "重新加载";
        retry.addEventListener("click", () => { cache.clear(); void render(); });
        loading.append(copy, retry);
        meta.textContent = "保留当前周期和查看范围，重新加载不会影响研究资料。";
        metricGrid.innerHTML = "";
      }
    }

    function setSelection(next = {}) {
      if (PERIODS.some(([value]) => value === next.period)) selection.period = next.period;
      if (RANGES.some(([value]) => value === next.range)) selection.range = next.range;
      saveSelection(storageKey, selection);
      void render();
    }

    expand.addEventListener("click", () => {
      open({...options, symbol, name, initialPeriod: selection.period, initialRange: selection.range, onClose: setSelection});
    });
    void render();

    return {
      render,
      setSelection,
      getSelection: () => ({...selection}),
      destroy() {
        destroyed = true;
        renderToken += 1;
        chartController?.destroy?.();
        chartController = null;
        container.classList.remove("qs-kline-host", "expanded");
      }
    };
  }

  function open(options = {}) {
    activeDialog?.close?.();
    const dialog = document.createElement("dialog"); dialog.className = "qs-kline-dialog";
    const frame = document.createElement("div"); frame.className = "qs-kline-dialog-frame";
    const dialogHead = document.createElement("div"); dialogHead.className = "qs-kline-dialog-head";
    const dialogTitle = document.createElement("strong"); dialogTitle.textContent = "行情详情";
    const close = document.createElement("button"); close.type = "button"; close.className = "qs-kline-dialog-close"; close.textContent = "关闭"; close.setAttribute("aria-label", "关闭行情详情");
    dialogHead.append(dialogTitle, close);
    const body = document.createElement("div"); body.className = "qs-kline-dialog-body";
    frame.append(dialogHead, body); dialog.appendChild(frame); document.body.appendChild(dialog);
    const explorer = createExplorer(body, {...options, expanded: true, showExpand: false, persist: false});
    let closed = false;
    function closeDialog() {
      if (closed) return;
      closed = true;
      options.onClose?.(explorer?.getSelection?.() || {});
      explorer?.destroy?.();
      if (dialog.open) dialog.close();
      dialog.remove();
      if (activeDialog?.dialog === dialog) activeDialog = null;
    }
    close.addEventListener("click", closeDialog);
    dialog.addEventListener("click", event => { if (event.target === dialog) closeDialog(); });
    dialog.addEventListener("cancel", event => { event.preventDefault(); closeDialog(); });
    activeDialog = {dialog, close: closeDialog};
    dialog.showModal();
    close.focus();
    return activeDialog;
  }

  return Object.freeze({PERIODS, RANGES, createExplorer, open, metricsFor, latestPeriodChange});
});
