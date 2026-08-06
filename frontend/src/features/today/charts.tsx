export const CHART_COLORS = {
  up: "#d92d20",
  down: "#039855",
  flat: "#98a2b3",
} as const;

type SparklineProps = {
  values: number[];
  width?: number;
  height?: number;
  className?: string;
};

/** 近 1 月日线收盘走势图；涨跌色由首尾收盘比较决定（A 股红涨绿跌）。 */
export function Sparkline({ values, width = 230, height = 52, className = "" }: SparklineProps) {
  if (values.length < 2) return null;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const pad = 2;
  const points = values.map((value, index) => {
    const x = pad + (index / (values.length - 1)) * (width - pad * 2);
    const y = pad + (1 - (value - min) / span) * (height - pad * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const rising = values[values.length - 1] >= values[0];
  const stroke = rising ? CHART_COLORS.up : CHART_COLORS.down;
  const areaPoints = `${pad},${height - pad} ${points.join(" ")} ${width - pad},${height - pad}`;
  return (
    <svg aria-hidden="true" className={className} height={height} viewBox={`0 0 ${width} ${height}`} width="100%">
      <polygon fill={stroke} fillOpacity={0.08} points={areaPoints} stroke="none" />
      <polyline fill="none" points={points.join(" ")} stroke={stroke} strokeLinejoin="round" strokeWidth={1.6} />
    </svg>
  );
}

type DonutSegment = { label: string; value: number; color: string };

type DonutChartProps = {
  segments: DonutSegment[];
  size?: number;
  thickness?: number;
};

/** 三段环图（上涨/下跌/平盘家数占比）。 */
export function DonutChart({ segments, size = 132, thickness = 18 }: DonutChartProps) {
  const total = segments.reduce((sum, segment) => sum + segment.value, 0);
  const radius = (size - thickness) / 2;
  const circumference = 2 * Math.PI * radius;
  let offsetRatio = 0;
  return (
    <svg aria-hidden="true" height={size} viewBox={`0 0 ${size} ${size}`} width={size}>
      <circle
        cx={size / 2}
        cy={size / 2}
        fill="none"
        r={radius}
        stroke="#f2f4f7"
        strokeWidth={thickness}
      />
      {total > 0 ? segments.map((segment) => {
        const ratio = segment.value / total;
        const dash = `${(ratio * circumference).toFixed(2)} ${circumference.toFixed(2)}`;
        const offset = (-offsetRatio * circumference).toFixed(2);
        offsetRatio += ratio;
        return (
          <circle
            cx={size / 2}
            cy={size / 2}
            fill="none"
            key={segment.label}
            r={radius}
            stroke={segment.color}
            strokeDasharray={dash}
            strokeDashoffset={offset}
            strokeWidth={thickness}
            transform={`rotate(-90 ${size / 2} ${size / 2})`}
          />
        );
      }) : null}
    </svg>
  );
}

type HistogramBin = { label: string; count: number; tone: "up" | "down" | "flat" };

type HistogramProps = { bins: HistogramBin[] };

const TONE_COLORS: Record<HistogramBin["tone"], string> = {
  up: CHART_COLORS.up,
  down: CHART_COLORS.down,
  flat: CHART_COLORS.flat,
};

/** 涨跌分布直方图（CSS 柱，柱高按最大桶归一）。 */
export function Histogram({ bins }: HistogramProps) {
  const max = Math.max(1, ...bins.map((bin) => bin.count));
  return (
    <div aria-hidden="true" style={{ display: "flex", alignItems: "flex-end", gap: 10, minHeight: 120 }}>
      {bins.map((bin) => (
        <div key={bin.label} style={{ display: "flex", flex: 1, flexDirection: "column", alignItems: "center", gap: 4, minWidth: 0 }}>
          <span style={{ fontSize: 11, color: "#475467", fontVariantNumeric: "tabular-nums" }}>{bin.count}</span>
          <div style={{ width: "100%", maxWidth: 44, height: `${Math.max(4, (bin.count / max) * 84)}px`, borderRadius: 3, background: TONE_COLORS[bin.tone] }} />
          <span style={{ fontSize: 10, color: "#98a2b3", whiteSpace: "nowrap" }}>{bin.label}</span>
        </div>
      ))}
    </div>
  );
}

type BarPoint = { label: string; value: number };

type BarChartProps = { points: BarPoint[] };

/** 最近 N 日成交额柱状图（金额为后端已换算的亿元，直通）。 */
export function BarChart({ points }: BarChartProps) {
  if (points.length === 0) return null;
  const max = Math.max(1, ...points.map((point) => point.value));
  return (
    <div aria-hidden="true" style={{ display: "flex", alignItems: "flex-end", gap: 8, minHeight: 110 }}>
      {points.map((point) => (
        <div key={point.label} style={{ display: "flex", flex: 1, flexDirection: "column", alignItems: "center", gap: 4, minWidth: 0 }}>
          <div
            style={{
              width: "100%",
              maxWidth: 36,
              height: `${Math.max(4, (point.value / max) * 72)}px`,
              borderRadius: 3,
              background: "#2e90fa",
            }}
            title={`${point.label} ${point.value} 亿元`}
          />
          <span style={{ fontSize: 10, color: "#98a2b3", whiteSpace: "nowrap" }}>{point.label.slice(5)}</span>
        </div>
      ))}
    </div>
  );
}
