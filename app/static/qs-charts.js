(function (root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (root) root.QSCharts = api;
})(typeof window !== "undefined" ? window : globalThis, function () {
  "use strict";

  const COLORS = Object.freeze({
    up: "#e5484d",
    down: "#18a06f",
    flat: "#9aa7b8",
    primary: "#2f6fec",
    compare: "#7a5af8",
    grid: "rgba(82,105,139,.12)",
    axis: "#78869a",
    crosshair: "#7c8da6"
  });
  const DEFAULT_MA_PERIODS = Object.freeze([5, 10, 20]);
  const MA_COLORS = Object.freeze({5: COLORS.up, 10: COLORS.primary, 20: COLORS.compare});

  function clamp(value, minimum, maximum) {
    return Math.max(minimum, Math.min(maximum, value));
  }

  function finite(value, fallback = 0) {
    const number = Number(value);
    return Number.isFinite(number) ? number : fallback;
  }

  function normalizeCandles(points) {
    return (Array.isArray(points) ? points : [])
      .map(point => {
        const close = finite(point?.close, NaN);
        const open = finite(point?.open, close);
        const high = finite(point?.high, Math.max(open, close));
        const low = finite(point?.low, Math.min(open, close));
        return {
          time: point?.timestamp || point?.time || point?.date || point?.datetime,
          open,
          high,
          low,
          close,
          volume: Math.max(0, finite(point?.volume ?? point?.vol, 0))
        };
      })
      .filter(row => row.time && [row.open, row.high, row.low, row.close].every(Number.isFinite))
      .sort((left, right) => new Date(left.time) - new Date(right.time));
  }

  function aggregateCandles(points, period = "daily") {
    const rows = normalizeCandles(points);
    if (["intraday", "daily"].includes(period)) return rows;
    const groups = new Map();
    for (const row of rows) {
      const date = new Date(row.time);
      if (Number.isNaN(date.getTime())) continue;
      let key;
      if (period === "weekly") {
        const weekday = date.getUTCDay() || 7;
        date.setUTCDate(date.getUTCDate() - weekday + 1);
        key = date.toISOString().slice(0, 10);
      } else if (period === "monthly") {
        key = `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, "0")}-01`;
      } else {
        return rows;
      }
      const current = groups.get(key);
      if (!current) {
        groups.set(key, {...row, time: key});
        continue;
      }
      current.high = Math.max(current.high, row.high);
      current.low = Math.min(current.low, row.low);
      current.close = row.close;
      current.volume += row.volume;
    }
    return [...groups.values()];
  }

  function candlesInRange(points, range = "1y") {
    const rows = normalizeCandles(points);
    if (!rows.length || range === "max") return rows;
    const monthCount = {"1mo": 1, "3mo": 3, "6mo": 6, "1y": 12, "2y": 24, "5y": 60}[range];
    if (!monthCount) return rows;
    const latest = new Date(rows.at(-1).time);
    if (Number.isNaN(latest.getTime())) return rows;
    const cutoff = new Date(latest);
    cutoff.setUTCMonth(cutoff.getUTCMonth() - monthCount);
    return rows.filter(row => new Date(row.time) >= cutoff);
  }

  function visibleBarsForRange(points, range = "1y") {
    const rows = normalizeCandles(points);
    if (!rows.length) return 0;
    return Math.max(1, candlesInRange(rows, range).length);
  }

  function movingAverage(rows, period) {
    const size = Math.max(1, Math.floor(finite(period, 1)));
    let sum = 0;
    return rows.map((row, index) => {
      sum += row.close;
      if (index >= size) sum -= rows[index - size].close;
      return index >= size - 1 ? sum / size : null;
    });
  }

  function computeViewport(rows, visibleBars, panOffset, minimumBars = 12) {
    const total = rows.length;
    const requested = visibleBars == null ? Math.min(90, total) : Math.floor(finite(visibleBars, total));
    const minimum = Math.max(1, Math.floor(finite(minimumBars, 12)));
    const count = total ? clamp(requested, Math.min(minimum, total), total) : 0;
    const maximumOffset = Math.max(0, total - count);
    const offset = clamp(Math.floor(finite(panOffset, 0)), 0, maximumOffset);
    const end = Math.max(0, total - offset);
    const start = Math.max(0, end - count);
    return {
      rows: rows.slice(start, end),
      start,
      end,
      count: end - start,
      panOffset: offset,
      maximumOffset,
      total
    };
  }

  function chartLayout(width, height, rowCount, showVolume) {
    const left = width >= 420 ? 50 : 42;
    const right = 12;
    const top = 12;
    const bottom = 18;
    const volumeHeight = showVolume && height >= 180 ? Math.max(44, Math.round(height * 0.2)) : 0;
    const gap = volumeHeight ? 11 : 0;
    const priceBottom = height - bottom - volumeHeight - gap;
    const plotWidth = Math.max(1, width - left - right);
    const priceHeight = Math.max(28, priceBottom - top);
    return {
      left,
      right,
      top,
      bottom,
      gap,
      volumeHeight,
      volumeTop: priceBottom + gap,
      priceBottom,
      plotWidth,
      priceHeight,
      step: plotWidth / Math.max(1, rowCount)
    };
  }

  function nearestCandleIndex(x, width, rowCount, left = 50, right = 12) {
    if (!rowCount) return -1;
    const plotWidth = Math.max(1, width - left - right);
    const step = plotWidth / rowCount;
    return clamp(Math.round((x - left) / step - 0.5), 0, rowCount - 1);
  }

  function setupCanvas(canvas, minimumHeight = 92) {
    const rect = canvas.getBoundingClientRect();
    const ratio = typeof window !== "undefined" ? window.devicePixelRatio || 1 : 1;
    const width = Math.max(180, Math.round(rect.width || canvas.clientWidth || 180));
    const height = Math.max(minimumHeight, Math.round(rect.height || canvas.clientHeight || minimumHeight));
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
    const context = canvas.getContext("2d");
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    context.clearRect(0, 0, width, height);
    return {context, width, height, ratio};
  }

  function marketDate(value) {
    const text = String(value || "");
    return /^\d{4}-\d{2}-\d{2}/.test(text) ? text.slice(0, 10) : text;
  }

  function compactVolume(value) {
    const number = finite(value, 0);
    if (number >= 1e8) return `${(number / 1e8).toFixed(2)}亿`;
    if (number >= 1e4) return `${(number / 1e4).toFixed(1)}万`;
    return Math.round(number).toLocaleString("zh-CN");
  }

  function drawLine(context, values, viewportStart, layout, mapY, color) {
    let started = false;
    context.beginPath();
    for (let index = 0; index < layout.rowCount; index++) {
      const value = values[viewportStart + index];
      if (!Number.isFinite(value)) {
        started = false;
        continue;
      }
      const x = layout.left + layout.step * (index + 0.5);
      const y = mapY(value);
      if (started) context.lineTo(x, y);
      else {
        context.moveTo(x, y);
        started = true;
      }
    }
    context.strokeStyle = color;
    context.lineWidth = 1.35;
    context.lineJoin = "round";
    context.stroke();
  }

  function drawTooltip(context, width, layout, row, previousClose, x) {
    const change = previousClose ? (row.close / previousClose - 1) * 100 : 0;
    const lines = [
      marketDate(row.time),
      `开 ${row.open.toFixed(2)}　高 ${row.high.toFixed(2)}`,
      `低 ${row.low.toFixed(2)}　收 ${row.close.toFixed(2)}`,
      `涨跌 ${change >= 0 ? "+" : ""}${change.toFixed(2)}%`,
      `成交量 ${compactVolume(row.volume)}`
    ];
    context.font = "11px -apple-system, BlinkMacSystemFont, 'Microsoft YaHei', sans-serif";
    const boxWidth = Math.max(...lines.map(line => context.measureText(line).width)) + 18;
    const boxHeight = lines.length * 17 + 12;
    const preferredLeft = x > width * 0.58 ? layout.left + 8 : width - layout.right - boxWidth - 8;
    const boxLeft = clamp(preferredLeft, layout.left + 4, width - layout.right - boxWidth - 4);
    const boxTop = layout.top + 6;
    context.fillStyle = "rgba(255,255,255,.96)";
    context.fillRect(boxLeft, boxTop, boxWidth, boxHeight);
    context.strokeStyle = "#d5e0ef";
    context.strokeRect(boxLeft + 0.5, boxTop + 0.5, boxWidth, boxHeight);
    context.textAlign = "left";
    context.textBaseline = "middle";
    lines.forEach((line, index) => {
      context.fillStyle = index === 3 ? (change >= 0 ? COLORS.up : COLORS.down) : "#243957";
      context.fillText(line, boxLeft + 9, boxTop + 13 + index * 17);
    });
  }

  function drawCandles(canvas, points, options = {}) {
    if (!canvas) return null;
    const rows = normalizeCandles(points);
    if (!rows.length) {
      const context = canvas.getContext?.("2d");
      if (context) context.clearRect(0, 0, canvas.width || 0, canvas.height || 0);
      return null;
    }
    const viewport = computeViewport(rows, options.visibleBars, options.panOffset, options.minimumBars);
    const minimumHeight = options.interactive ? 220 : 92;
    const {context, width, height} = setupCanvas(canvas, minimumHeight);
    const showVolume = options.showVolume === true;
    const layout = chartLayout(width, height, viewport.count, showVolume);
    layout.rowCount = viewport.count;
    const priceValues = viewport.rows.flatMap(row => [row.high, row.low, row.open, row.close]);
    let high = Math.max(...priceValues);
    let low = Math.min(...priceValues);
    const margin = (high - low) * 0.08 || Math.max(Math.abs(high) * 0.01, 1);
    high += margin;
    low -= margin;
    const priceSpan = high - low || 1;
    const mapY = value => layout.top + (high - finite(value, low)) / priceSpan * layout.priceHeight;

    context.strokeStyle = COLORS.grid;
    context.lineWidth = 1;
    context.font = "10px -apple-system, BlinkMacSystemFont, 'Microsoft YaHei', sans-serif";
    context.textBaseline = "middle";
    for (let level = 0; level < 4; level++) {
      const y = layout.top + layout.priceHeight * level / 3;
      context.beginPath();
      context.moveTo(layout.left, y);
      context.lineTo(width - layout.right, y);
      context.stroke();
      if (options.interactive) {
        context.fillStyle = COLORS.axis;
        context.textAlign = "right";
        context.fillText((high - priceSpan * level / 3).toFixed(2), layout.left - 5, y);
      }
    }

    const bodyWidth = Math.max(1, Math.min(options.interactive ? 9 : 4, layout.step * 0.62));
    viewport.rows.forEach((row, index) => {
      const x = layout.left + layout.step * (index + 0.5);
      const rising = row.close >= row.open;
      const color = rising ? COLORS.up : COLORS.down;
      const bodyTop = Math.min(mapY(row.open), mapY(row.close));
      const bodyHeight = Math.max(1.5, Math.abs(mapY(row.open) - mapY(row.close)));
      context.strokeStyle = color;
      context.fillStyle = color;
      context.beginPath();
      context.moveTo(x, mapY(row.high));
      context.lineTo(x, mapY(row.low));
      context.stroke();
      context.fillRect(x - bodyWidth / 2, bodyTop, bodyWidth, bodyHeight);
    });

    if (options.showMovingAverages) {
      for (const period of options.maPeriods || DEFAULT_MA_PERIODS) {
        drawLine(
          context,
          movingAverage(rows, period),
          viewport.start,
          layout,
          mapY,
          MA_COLORS[period] || COLORS.primary
        );
      }
    }

    if (layout.volumeHeight) {
      const maximumVolume = Math.max(...viewport.rows.map(row => row.volume), 1);
      context.strokeStyle = COLORS.grid;
      context.beginPath();
      context.moveTo(layout.left, layout.volumeTop);
      context.lineTo(width - layout.right, layout.volumeTop);
      context.stroke();
      viewport.rows.forEach((row, index) => {
        const x = layout.left + layout.step * (index + 0.5);
        const heightValue = row.volume / maximumVolume * layout.volumeHeight;
        context.fillStyle = row.close >= row.open ? "rgba(229,72,77,.62)" : "rgba(24,160,111,.62)";
        context.fillRect(
          x - bodyWidth / 2,
          layout.volumeTop + layout.volumeHeight - heightValue,
          bodyWidth,
          heightValue
        );
      });
    }

    context.fillStyle = COLORS.axis;
    context.textAlign = "center";
    context.textBaseline = "top";
    const tickCount = Math.min(5, viewport.count);
    for (let tick = 0; tick < tickCount; tick++) {
      const index = Math.round(tick * (viewport.count - 1) / Math.max(1, tickCount - 1));
      const x = layout.left + layout.step * (index + 0.5);
      context.fillText(marketDate(viewport.rows[index].time).slice(5), x, height - 14);
    }

    let hover = null;
    const crosshair = options.crosshair;
    if (crosshair && options.interactive) {
      const index = nearestCandleIndex(crosshair.x, width, viewport.count, layout.left, layout.right);
      if (index >= 0) {
        const row = viewport.rows[index];
        const x = layout.left + layout.step * (index + 0.5);
        const pointerY = clamp(finite(crosshair.y, layout.top), layout.top, layout.priceBottom);
        const priceAtPointer = high - (pointerY - layout.top) / layout.priceHeight * priceSpan;
        context.setLineDash([4, 3]);
        context.strokeStyle = COLORS.crosshair;
        context.beginPath();
        context.moveTo(x, layout.top);
        context.lineTo(x, layout.volumeTop + layout.volumeHeight);
        context.stroke();
        context.beginPath();
        context.moveTo(layout.left, pointerY);
        context.lineTo(width - layout.right, pointerY);
        context.stroke();
        context.setLineDash([]);
        const label = priceAtPointer.toFixed(2);
        context.font = "10px -apple-system, BlinkMacSystemFont, 'Microsoft YaHei', sans-serif";
        const labelWidth = context.measureText(label).width + 8;
        context.fillStyle = "#526680";
        context.fillRect(width - layout.right - labelWidth, pointerY - 8, labelWidth, 16);
        context.fillStyle = "#fff";
        context.textAlign = "right";
        context.textBaseline = "middle";
        context.fillText(label, width - layout.right - 4, pointerY);
        const previous = rows[viewport.start + index - 1];
        drawTooltip(context, width, layout, row, previous?.close || row.open, x);
        hover = {index, globalIndex: viewport.start + index, row, x, y: pointerY, priceAtPointer};
      }
    }
    return {...viewport, layout, hover};
  }

  function safeStorage(storageKey) {
    if (!storageKey || typeof window === "undefined") return null;
    try {
      return window.sessionStorage;
    } catch {
      return null;
    }
  }

  function createInteractiveKline(canvas, points, options = {}) {
    let rows = normalizeCandles(points);
    const minimumBars = Math.max(1, Math.floor(finite(options.minimumBars, 12)));
    const defaultVisibleBars = clamp(
      Math.floor(finite(options.visibleBars, Math.min(90, rows.length))),
      Math.min(minimumBars, rows.length || minimumBars),
      Math.max(minimumBars, rows.length)
    );
    const storageKey = options.storageKey ? `qingshu:kline:v1:${options.storageKey}` : null;
    const storage = safeStorage(storageKey);
    let restored = {};
    if (storage && storageKey) {
      try { restored = JSON.parse(storage.getItem(storageKey) || "{}"); } catch { restored = {}; }
    }
    const state = {
      visibleBars: finite(restored.visibleBars, defaultVisibleBars),
      panOffset: finite(restored.panOffset, 0),
      crosshair: null,
      dragging: null
    };
    let frame = 0;
    let lastResult = null;

    function persist() {
      if (!storage || !storageKey) return;
      try {
        storage.setItem(storageKey, JSON.stringify({
          visibleBars: state.visibleBars,
          panOffset: state.panOffset
        }));
      } catch {}
    }

    function notify() {
      const viewport = computeViewport(rows, state.visibleBars, state.panOffset, minimumBars);
      state.visibleBars = viewport.count;
      state.panOffset = viewport.panOffset;
      persist();
      options.onStateChange?.({
        visibleBars: viewport.count,
        panOffset: viewport.panOffset,
        maximumOffset: viewport.maximumOffset,
        start: viewport.start,
        end: viewport.end,
        total: viewport.total,
        historical: viewport.panOffset > 0
      });
    }

    function render() {
      frame = 0;
      lastResult = drawCandles(canvas, rows, {
        ...options,
        interactive: true,
        showMovingAverages: options.showMovingAverages !== false,
        showVolume: options.showVolume !== false,
        visibleBars: state.visibleBars,
        panOffset: state.panOffset,
        crosshair: state.crosshair
      });
      return lastResult;
    }

    function schedule() {
      if (frame) return;
      frame = requestAnimationFrame(render);
    }

    function pointerPosition(event) {
      const rect = canvas.getBoundingClientRect();
      return {x: event.clientX - rect.left, y: event.clientY - rect.top};
    }

    function pointerDown(event) {
      if (!rows.length || (event.button != null && event.button !== 0)) return;
      const position = pointerPosition(event);
      state.dragging = {pointerId: event.pointerId, x: position.x, panOffset: state.panOffset, moved: false};
      state.crosshair = null;
      canvas.classList.add("is-dragging");
      canvas.setPointerCapture?.(event.pointerId);
    }

    function pointerMove(event) {
      const position = pointerPosition(event);
      if (state.dragging) {
        const delta = position.x - state.dragging.x;
        if (Math.abs(delta) >= 3) state.dragging.moved = true;
        if (state.dragging.moved) {
          const viewport = computeViewport(rows, state.visibleBars, state.dragging.panOffset, minimumBars);
          const step = Math.max(2, (canvas.clientWidth - 62) / Math.max(1, viewport.count));
          state.panOffset = state.dragging.panOffset + Math.round(delta / step);
          notify();
          schedule();
        }
        return;
      }
      if (event.pointerType === "touch") return;
      state.crosshair = position;
      schedule();
    }

    function pointerUp(event) {
      if (!state.dragging) return;
      canvas.releasePointerCapture?.(event.pointerId);
      state.dragging = null;
      canvas.classList.remove("is-dragging");
      notify();
      schedule();
    }

    function pointerLeave() {
      if (state.dragging || !state.crosshair) return;
      state.crosshair = null;
      schedule();
    }

    function zoom(direction) {
      const viewport = computeViewport(rows, state.visibleBars, state.panOffset, minimumBars);
      const factor = direction === "in" ? 0.78 : 1.28;
      state.visibleBars = clamp(
        Math.round(viewport.count * factor),
        Math.min(minimumBars, rows.length),
        rows.length
      );
      notify();
      schedule();
    }

    function wheel(event) {
      if (!rows.length) return;
      event.preventDefault();
      zoom(event.deltaY < 0 ? "in" : "out");
    }

    function reset() {
      state.visibleBars = defaultVisibleBars;
      state.panOffset = 0;
      state.crosshair = null;
      notify();
      schedule();
    }

    function keydown(event) {
      if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
        event.preventDefault();
        state.panOffset += event.key === "ArrowLeft" ? 1 : -1;
        notify();
        schedule();
      } else if (event.key === "+" || event.key === "=") {
        event.preventDefault();
        zoom("in");
      } else if (event.key === "-") {
        event.preventDefault();
        zoom("out");
      } else if (event.key === "Home") {
        event.preventDefault();
        reset();
      }
    }

    canvas.tabIndex = canvas.tabIndex >= 0 ? canvas.tabIndex : 0;
    canvas.addEventListener("pointerdown", pointerDown);
    canvas.addEventListener("pointermove", pointerMove);
    canvas.addEventListener("pointerup", pointerUp);
    canvas.addEventListener("pointercancel", pointerUp);
    canvas.addEventListener("pointerleave", pointerLeave);
    canvas.addEventListener("wheel", wheel, {passive: false});
    canvas.addEventListener("dblclick", reset);
    canvas.addEventListener("keydown", keydown);
    const resizeObserver = typeof ResizeObserver !== "undefined"
      ? new ResizeObserver(() => schedule())
      : null;
    resizeObserver?.observe(canvas);
    notify();
    render();

    return {
      render,
      reset,
      zoom,
      setVisibleBars(value, {resetPan = true} = {}) {
        state.visibleBars = value == null ? rows.length : finite(value, rows.length);
        if (resetPan) state.panOffset = 0;
        state.crosshair = null;
        notify();
        schedule();
      },
      setPanOffset(value) {
        state.panOffset = finite(value, 0);
        notify();
        schedule();
      },
      updateData(nextPoints, nextOptions = {}) {
        rows = normalizeCandles(nextPoints);
        if (nextOptions.visibleBars != null) state.visibleBars = nextOptions.visibleBars;
        state.panOffset = nextOptions.preservePan ? state.panOffset : 0;
        state.crosshair = null;
        notify();
        schedule();
      },
      getState() {
        return {...state, rows: rows.slice(), result: lastResult};
      },
      destroy() {
        if (frame) cancelAnimationFrame(frame);
        resizeObserver?.disconnect();
        canvas.classList.remove("is-dragging");
        canvas.removeEventListener("pointerdown", pointerDown);
        canvas.removeEventListener("pointermove", pointerMove);
        canvas.removeEventListener("pointerup", pointerUp);
        canvas.removeEventListener("pointercancel", pointerUp);
        canvas.removeEventListener("pointerleave", pointerLeave);
        canvas.removeEventListener("wheel", wheel);
        canvas.removeEventListener("dblclick", reset);
        canvas.removeEventListener("keydown", keydown);
      }
    };
  }

  function clampRadarLabel(width, height, x, y, textWidth, alignment) {
    let clampedX = x;
    if (alignment === "left") clampedX = clamp(x, 6, width - 6 - textWidth);
    else if (alignment === "right") clampedX = clamp(x, 6 + textWidth, width - 6);
    else clampedX = clamp(x, 6 + textWidth / 2, width - 6 - textWidth / 2);
    return {x: clampedX, y: clamp(y, 10, height - 10), alignment};
  }

  function drawRadar(canvas, labels, series, options = {}) {
    if (!canvas || !Array.isArray(labels) || labels.length < 3) return;
    const {context, width, height} = setupCanvas(canvas, 180);
    const count = labels.length;
    const centerX = width / 2;
    const centerY = height / 2 + 4;
    const radius = Math.min(width, height) * 0.32;
    const point = (index, distance) => {
      const angle = -Math.PI / 2 + index * Math.PI * 2 / count;
      return {x: centerX + Math.cos(angle) * distance, y: centerY + Math.sin(angle) * distance, angle};
    };
    for (let level = 1; level <= 5; level++) {
      context.beginPath();
      labels.forEach((_, index) => {
        const position = point(index, radius * level / 5);
        if (index) context.lineTo(position.x, position.y);
        else context.moveTo(position.x, position.y);
      });
      context.closePath();
      context.strokeStyle = "#dfe7f3";
      context.stroke();
    }
    context.font = "11px -apple-system, BlinkMacSystemFont, 'Microsoft YaHei', sans-serif";
    context.textBaseline = "middle";
    labels.forEach((label, index) => {
      const edge = point(index, radius);
      context.beginPath();
      context.moveTo(centerX, centerY);
      context.lineTo(edge.x, edge.y);
      context.strokeStyle = "#e5ebf4";
      context.stroke();
      const labelPoint = point(index, radius + 22);
      const cosine = Math.cos(labelPoint.angle);
      const alignment = cosine > 0.3 ? "left" : cosine < -0.3 ? "right" : "center";
      const placement = clampRadarLabel(
        width,
        height,
        labelPoint.x,
        labelPoint.y,
        context.measureText(label).width,
        alignment
      );
      context.textAlign = placement.alignment;
      context.fillStyle = "#344a6a";
      context.fillText(label, placement.x, placement.y);
    });
    (Array.isArray(series) ? series : []).forEach((item, seriesIndex) => {
      const values = (item.values || []).map(value => clamp(finite(value, 0), 0, 100));
      const color = item.color || (seriesIndex ? COLORS.compare : COLORS.primary);
      context.beginPath();
      values.forEach((value, index) => {
        const position = point(index, radius * value / 100);
        if (index) context.lineTo(position.x, position.y);
        else context.moveTo(position.x, position.y);
      });
      context.closePath();
      context.fillStyle = item.fill || `${color}18`;
      context.fill();
      context.strokeStyle = color;
      context.lineWidth = 2;
      context.stroke();
      if (options.annotateValues !== false) {
        context.font = "10px -apple-system, BlinkMacSystemFont, 'Microsoft YaHei', sans-serif";
        values.forEach((value, index) => {
          if (!value) return;
          const distance = seriesIndex ? Math.max(10, radius * value / 100 - 12) : radius * value / 100 + 12;
          const valuePoint = point(index, distance > radius + 9 ? Math.max(10, radius * value / 100 - 12) : distance);
          const cosine = Math.cos(valuePoint.angle);
          const alignment = cosine > 0.3 ? "left" : cosine < -0.3 ? "right" : "center";
          const text = String(Math.round(value));
          const placement = clampRadarLabel(width, height, valuePoint.x, valuePoint.y, context.measureText(text).width, alignment);
          context.textAlign = placement.alignment;
          context.fillStyle = color;
          context.fillText(text, placement.x, placement.y);
        });
      }
    });
  }

  return Object.freeze({
    colors: COLORS,
    normalizeCandles,
    aggregateCandles,
    candlesInRange,
    visibleBarsForRange,
    movingAverage,
    computeViewport,
    chartLayout,
    nearestCandleIndex,
    clampRadarLabel,
    drawCandles,
    createInteractiveKline,
    drawRadar
  });
});
