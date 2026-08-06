import { CHART_COLORS } from "../today/charts";
import type { CandlePoint } from "./adapters";

export { CHART_COLORS };

type CandlestickChartProps = {
  points: CandlePoint[];
  width?: number;
  height?: number;
};

const PRICE_RATIO = 0.72;
const AXIS_PAD = { top: 10, right: 8, bottom: 18, left: 8 };

/**
 * 日 K 蜡烛图 + 成交量副图（纯 SVG，A 股红涨绿跌）。
 * 只渲染接口返回的真实 OHLC，不补齐、不插值缺失交易日。
 */
export function CandlestickChart({ points, width = 960, height = 420 }: CandlestickChartProps) {
  const candles = points.filter((point) =>
    point.open !== null && point.high !== null && point.low !== null && point.close !== null,
  ) as Array<CandlePoint & { open: number; high: number; low: number; close: number }>;
  if (candles.length < 2) return null;

  const highMax = Math.max(...candles.map((point) => point.high));
  const lowMin = Math.min(...candles.map((point) => point.low));
  const priceSpan = highMax - lowMin || 1;
  const volumeMax = Math.max(1, ...candles.map((point) => point.volume ?? 0));

  const plotWidth = width - AXIS_PAD.left - AXIS_PAD.right;
  const priceHeight = (height - AXIS_PAD.top - AXIS_PAD.bottom) * PRICE_RATIO;
  const volumeTop = AXIS_PAD.top + priceHeight + 8;
  const volumeHeight = height - AXIS_PAD.bottom - volumeTop;

  const slot = plotWidth / candles.length;
  const bodyWidth = Math.max(1.5, Math.min(12, slot * 0.62));
  const x = (index: number) => AXIS_PAD.left + slot * index + slot / 2;
  const yPrice = (price: number) => AXIS_PAD.top + (1 - (price - lowMin) / priceSpan) * priceHeight;
  const yVolume = (volume: number) => volumeTop + (1 - volume / volumeMax) * volumeHeight;

  const gridLevels = [0, 0.25, 0.5, 0.75, 1].map((ratio) => lowMin + priceSpan * ratio);
  const firstDate = candles[0]?.timestamp.slice(0, 10) ?? "";
  const lastDate = candles[candles.length - 1]?.timestamp.slice(0, 10) ?? "";
  const last = candles[candles.length - 1];

  return (
    <svg
      aria-label="日 K 蜡烛与成交量图"
      height={height}
      role="img"
      viewBox={`0 0 ${width} ${height}`}
      width="100%"
    >
      {gridLevels.map((level) => {
        const y = yPrice(level);
        return (
          <g key={level}>
            <line stroke="#edf1f6" strokeWidth={1} x1={AXIS_PAD.left} x2={width - AXIS_PAD.right} y1={y} y2={y} />
            <text fill="#98a2b3" fontSize={10} textAnchor="end" x={width - 2} y={y - 2}>{level.toFixed(2)}</text>
          </g>
        );
      })}
      <line stroke="#edf1f6" strokeWidth={1} x1={AXIS_PAD.left} x2={width - AXIS_PAD.right} y1={volumeTop - 4} y2={volumeTop - 4} />
      {candles.map((point, index) => {
        const rising = point.close >= point.open;
        const color = rising ? CHART_COLORS.up : CHART_COLORS.down;
        const cx = x(index);
        const bodyTop = yPrice(Math.max(point.open, point.close));
        const bodyBottom = yPrice(Math.min(point.open, point.close));
        const volume = point.volume ?? 0;
        return (
          <g key={point.timestamp}>
            <line stroke={color} strokeWidth={1} x1={cx} x2={cx} y1={yPrice(point.high)} y2={yPrice(point.low)} />
            <rect
              fill={rising ? "#ffffff" : color}
              height={Math.max(1, bodyBottom - bodyTop)}
              stroke={color}
              strokeWidth={1}
              width={bodyWidth}
              x={cx - bodyWidth / 2}
              y={bodyTop}
            >
              <title>{`${point.timestamp.slice(0, 10)} 开 ${point.open} 高 ${point.high} 低 ${point.low} 收 ${point.close}`}</title>
            </rect>
            {point.volume !== null ? (
              <rect
                fill={color}
                fillOpacity={0.5}
                height={Math.max(1, volumeTop + volumeHeight - yVolume(volume))}
                width={bodyWidth}
                x={cx - bodyWidth / 2}
                y={yVolume(volume)}
              />
            ) : null}
          </g>
        );
      })}
      {last ? (
        <line
          stroke="#667085"
          strokeDasharray="4 3"
          strokeWidth={1}
          x1={AXIS_PAD.left}
          x2={width - AXIS_PAD.right}
          y1={yPrice(last.close)}
          y2={yPrice(last.close)}
        />
      ) : null}
      <text fill="#98a2b3" fontSize={10} x={AXIS_PAD.left} y={height - 4}>{firstDate}</text>
      <text fill="#98a2b3" fontSize={10} textAnchor="end" x={width - AXIS_PAD.right} y={height - 4}>{lastDate}</text>
    </svg>
  );
}
