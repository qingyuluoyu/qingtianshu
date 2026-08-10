import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent, type WheelEvent } from "react";
import { CHART_COLORS } from "../today/charts";
import type { CandlePoint } from "./adapters";

export { CHART_COLORS };

type CandlestickChartProps = {
  points: CandlePoint[];
  width?: number;
  height?: number;
};

type ValidCandle = CandlePoint & { open: number; high: number; low: number; close: number };

const PRICE_RATIO = 0.72;
const AXIS_PAD = { top: 26, right: 58, bottom: 20, left: 8 };
const MIN_VISIBLE = 12;
const MA_SERIES = [
  { period: 5, color: "#d92d20", key: "ma5" },
  { period: 10, color: "#2164d8", key: "ma10" },
  { period: 20, color: "#795add", key: "ma20" },
] as const;

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value));
}

function movingAverages(candles: ValidCandle[], period: number): Array<number | null> {
  let sum = 0;
  return candles.map((candle, index) => {
    sum += candle.close;
    if (index >= period) sum -= candles[index - period].close;
    return index + 1 >= period ? sum / period : null;
  });
}

/**
 * 真实日 K 蜡烛图 + 成交量副图 + MA5/10/20。
 * 缩放和平移只改变接口真实点的可见窗口，不补齐、不插值缺失交易日。
 */
export function CandlestickChart({ points, width = 960, height = 420 }: CandlestickChartProps) {
  const candles = useMemo(() => points.filter((point) =>
    point.open !== null && point.high !== null && point.low !== null && point.close !== null,
  ) as ValidCandle[], [points]);
  const initialWindow = Math.min(80, candles.length);
  const [windowSize, setWindowSize] = useState(initialWindow);
  const [windowEnd, setWindowEnd] = useState(candles.length);
  const [activeIndex, setActiveIndex] = useState<number | null>(null);
  const drag = useRef<{ pointerId: number; startX: number; startEnd: number } | null>(null);

  useEffect(() => {
    setWindowSize(Math.min(80, candles.length));
    setWindowEnd(candles.length);
    setActiveIndex(null);
  }, [candles.length]);

  const minimumVisible = Math.min(MIN_VISIBLE, candles.length);
  const safeWindowSize = clamp(windowSize || candles.length, minimumVisible, candles.length || 1);
  const safeWindowEnd = clamp(windowEnd || candles.length, safeWindowSize, candles.length || safeWindowSize);
  const startIndex = Math.max(0, safeWindowEnd - safeWindowSize);
  const visible = candles.slice(startIndex, safeWindowEnd);
  const averages = useMemo(() => Object.fromEntries(MA_SERIES.map((series) => [series.key, movingAverages(candles, series.period)])) as Record<(typeof MA_SERIES)[number]["key"], Array<number | null>>, [candles]);

  if (candles.length < 2) return null;

  const highMax = Math.max(...visible.map((point) => point.high));
  const lowMin = Math.min(...visible.map((point) => point.low));
  const priceSpan = highMax - lowMin || 1;
  const volumeMax = Math.max(1, ...visible.map((point) => point.volume ?? 0));
  const plotWidth = width - AXIS_PAD.left - AXIS_PAD.right;
  const priceHeight = (height - AXIS_PAD.top - AXIS_PAD.bottom) * PRICE_RATIO;
  const volumeTop = AXIS_PAD.top + priceHeight + 8;
  const volumeHeight = height - AXIS_PAD.bottom - volumeTop;
  const slot = plotWidth / visible.length;
  const bodyWidth = Math.max(1.5, Math.min(12, slot * 0.62));
  const x = (index: number) => AXIS_PAD.left + slot * index + slot / 2;
  const yPrice = (price: number) => AXIS_PAD.top + (1 - (price - lowMin) / priceSpan) * priceHeight;
  const yVolume = (volume: number) => volumeTop + (1 - volume / volumeMax) * volumeHeight;
  const gridLevels = [0, 0.25, 0.5, 0.75, 1].map((ratio) => lowMin + priceSpan * ratio);
  const firstDate = visible[0]?.timestamp.slice(0, 10) ?? "";
  const lastDate = visible[visible.length - 1]?.timestamp.slice(0, 10) ?? "";
  const last = visible[visible.length - 1];
  const selected = activeIndex === null ? null : visible[clamp(activeIndex, 0, visible.length - 1)];
  const selectedIndex = activeIndex === null ? null : clamp(activeIndex, 0, visible.length - 1);

  const reset = () => {
    setWindowSize(Math.min(80, candles.length));
    setWindowEnd(candles.length);
    setActiveIndex(null);
  };

  const zoom = (zoomIn: boolean) => {
    const next = clamp(Math.round(safeWindowSize * (zoomIn ? 0.8 : 1.25)), minimumVisible, candles.length);
    const anchor = selectedIndex === null ? safeWindowEnd : startIndex + selectedIndex + 1;
    setWindowSize(next);
    setWindowEnd(clamp(anchor + Math.round(next / 2), next, candles.length));
    setActiveIndex(null);
  };

  const onWheel = (event: WheelEvent<SVGSVGElement>) => {
    zoom(event.deltaY < 0);
  };

  const onPointerDown = (event: PointerEvent<SVGSVGElement>) => {
    drag.current = { pointerId: event.pointerId, startX: event.clientX, startEnd: safeWindowEnd };
    event.currentTarget.setPointerCapture?.(event.pointerId);
  };

  const onPointerMove = (event: PointerEvent<SVGSVGElement>) => {
    if (drag.current?.pointerId === event.pointerId) {
      const rect = event.currentTarget.getBoundingClientRect();
      const slots = Math.round(((drag.current.startX - event.clientX) / Math.max(1, rect.width)) * safeWindowSize);
      setWindowEnd(clamp(drag.current.startEnd + slots, safeWindowSize, candles.length));
      return;
    }
    const rect = event.currentTarget.getBoundingClientRect();
    const chartX = ((event.clientX - rect.left) / Math.max(1, rect.width)) * width;
    setActiveIndex(clamp(Math.floor((chartX - AXIS_PAD.left) / slot), 0, visible.length - 1));
  };

  const onPointerUp = (event: PointerEvent<SVGSVGElement>) => {
    if (drag.current?.pointerId === event.pointerId) {
      event.currentTarget.releasePointerCapture?.(event.pointerId);
      drag.current = null;
    }
  };

  const onKeyDown = (event: KeyboardEvent<SVGSVGElement>) => {
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      event.preventDefault();
      const current = activeIndex ?? visible.length - 1;
      setActiveIndex(clamp(current + (event.key === "ArrowLeft" ? -1 : 1), 0, visible.length - 1));
    } else if (event.key === "+" || event.key === "=") {
      event.preventDefault();
      zoom(true);
    } else if (event.key === "-") {
      event.preventDefault();
      zoom(false);
    } else if (event.key === "0") {
      event.preventDefault();
      reset();
    }
  };

  return (
    <svg
      aria-keyshortcuts="ArrowLeft ArrowRight + - 0"
      aria-description={`当前显示 ${visible.length} 个真实交易日；滚轮缩放、拖动平移、方向键检查。`}
      aria-label="日 K 蜡烛与成交量图"
      data-visible-count={visible.length}
      height={height}
      onDoubleClick={reset}
      onKeyDown={onKeyDown}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onWheel={onWheel}
      role="img"
      style={{ cursor: drag.current ? "grabbing" : "crosshair", touchAction: "none" }}
      tabIndex={0}
      viewBox={`0 0 ${width} ${height}`}
      width="100%"
    >
      <desc>滚轮或加减键缩放，拖动平移，方向键检查蜡烛，双击或数字 0 重置。</desc>
      <g aria-hidden="true">
        {MA_SERIES.map((series, index) => <text fill={series.color} fontSize={10} key={series.key} x={AXIS_PAD.left + index * 62} y={14}>{series.key.toUpperCase()}</text>)}
      </g>
      {gridLevels.map((level) => {
        const y = yPrice(level);
        return <g key={level}><line stroke="#edf1f6" strokeWidth={1} x1={AXIS_PAD.left} x2={width - AXIS_PAD.right} y1={y} y2={y} /><text fill="#8a99af" fontSize={10} textAnchor="start" x={width - AXIS_PAD.right + 5} y={y + 3}>{level.toFixed(2)}</text></g>;
      })}
      <line stroke="#edf1f6" strokeWidth={1} x1={AXIS_PAD.left} x2={width - AXIS_PAD.right} y1={volumeTop - 4} y2={volumeTop - 4} />
      {visible.map((point, index) => {
        const rising = point.close >= point.open;
        const color = rising ? CHART_COLORS.up : CHART_COLORS.down;
        const cx = x(index);
        const bodyTop = yPrice(Math.max(point.open, point.close));
        const bodyBottom = yPrice(Math.min(point.open, point.close));
        const volume = point.volume ?? 0;
        return <g key={`${point.timestamp}-${startIndex + index}`}><line stroke={color} strokeWidth={1} x1={cx} x2={cx} y1={yPrice(point.high)} y2={yPrice(point.low)} /><rect fill={rising ? "#ffffff" : color} height={Math.max(1, bodyBottom - bodyTop)} stroke={color} strokeWidth={1} width={bodyWidth} x={cx - bodyWidth / 2} y={bodyTop}><title>{`${point.timestamp.slice(0, 10)} 开 ${point.open} 高 ${point.high} 低 ${point.low} 收 ${point.close}`}</title></rect>{point.volume !== null ? <rect fill={color} fillOpacity={0.46} height={Math.max(1, volumeTop + volumeHeight - yVolume(volume))} width={bodyWidth} x={cx - bodyWidth / 2} y={yVolume(volume)} /> : null}</g>;
      })}
      {MA_SERIES.map((series) => {
        const values = averages[series.key];
        const chartPoints = visible.flatMap((_, index) => {
          const value = values[startIndex + index];
          return value === null ? [] : [`${x(index).toFixed(2)},${yPrice(value).toFixed(2)}`];
        });
        return chartPoints.length >= 2 ? <polyline data-series={series.key} fill="none" key={series.key} points={chartPoints.join(" ")} stroke={series.color} strokeLinejoin="round" strokeWidth={1.35} /> : null;
      })}
      {last ? <line stroke="#5f7089" strokeDasharray="4 3" strokeWidth={1} x1={AXIS_PAD.left} x2={width - AXIS_PAD.right} y1={yPrice(last.close)} y2={yPrice(last.close)} /> : null}
      {selected && selectedIndex !== null ? <g data-testid="kline-crosshair"><line stroke="#667085" strokeDasharray="3 3" x1={x(selectedIndex)} x2={x(selectedIndex)} y1={AXIS_PAD.top} y2={volumeTop + volumeHeight} /><line stroke="#667085" strokeDasharray="3 3" x1={AXIS_PAD.left} x2={width - AXIS_PAD.right} y1={yPrice(selected.close)} y2={yPrice(selected.close)} /><rect fill="rgba(9,25,54,.86)" height="34" rx="5" width="238" x={clamp(x(selectedIndex) - 119, AXIS_PAD.left, width - AXIS_PAD.right - 238)} y={30} /><text fill="#fff" fontSize="10" x={clamp(x(selectedIndex) - 109, AXIS_PAD.left + 10, width - AXIS_PAD.right - 228)} y={44}>{selected.timestamp.slice(0, 10)}　开 {selected.open.toFixed(2)}　收 {selected.close.toFixed(2)}</text><text fill="#d8e7fb" fontSize="10" x={clamp(x(selectedIndex) - 109, AXIS_PAD.left + 10, width - AXIS_PAD.right - 228)} y={57}>高 {selected.high.toFixed(2)}　低 {selected.low.toFixed(2)}　量 {selected.volume ?? "--"}</text></g> : null}
      <text fill="#8a99af" fontSize={10} x={AXIS_PAD.left} y={height - 4}>{firstDate}</text>
      <text fill="#8a99af" fontSize={10} textAnchor="end" x={width - AXIS_PAD.right} y={height - 4}>{lastDate}</text>
    </svg>
  );
}
