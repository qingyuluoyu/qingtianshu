import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
MODULE = ROOT / "app" / "static" / "qs-charts.js"
EXPLORER = ROOT / "app" / "static" / "qs-kline-explorer.js"
DEMO = ROOT / "app" / "static" / "demo.html"
FRONTEND_ASSETS = (
    "demo.css",
    "qs-kline-explorer.js",
    "qs-format.js",
    "qs-screening.js",
    "demo.js",
    "qs-agent-entry.js",
    "qs-workspace.js",
    "qs-reader.js",
    "qs-agent-ui.js",
    "qs-knowledge.js",
    "qs-home.js",
    "qs-watchlist.js",
    "qs-market.js",
    "qs-stock-core.js",
    "qs-stock-workflow.js",
    "qs-stock-space.js",
    "qs-deep-stock.js",
    "qs-review.js",
    "qs-chat-runtime.js",
    "demo-boot.js",
)


def frontend_source() -> str:
    static = DEMO.parent
    return "\n".join(
        [DEMO.read_text(encoding="utf-8")]
        + [(static / name).read_text(encoding="utf-8") for name in FRONTEND_ASSETS]
    )


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required for chart contracts")
def test_qs_charts_pure_function_contracts() -> None:
    script = f"""
const charts = require({json.dumps(str(MODULE))});
const explorer = require({json.dumps(str(EXPLORER))});
const rows = Array.from({{length: 20}}, (_, index) => ({{close: index + 1}}));
const averages = charts.movingAverage(rows, 5);
const viewport = charts.computeViewport(rows, 12, 3);
const emptyViewport = charts.computeViewport([], 12, 9);
const nearest = charts.nearestCandleIndex(50, 200, 10, 40, 10);
const leftLabel = charts.clampRadarLabel(180, 120, -20, -5, 42, "left");
const rightLabel = charts.clampRadarLabel(180, 120, 220, 140, 42, "right");
const candles = [
  {{timestamp: "2026-01-30T01:30:00Z", open: 10, high: 12, low: 9, close: 11, volume: 100}},
  {{timestamp: "2026-02-02T01:30:00Z", open: 11, high: 13, low: 10, close: 12, volume: 120}},
  {{timestamp: "2026-02-06T01:30:00Z", open: 12, high: 14, low: 11, close: 13, volume: 130}},
  {{timestamp: "2026-02-09T01:30:00Z", open: 13, high: 15, low: 12, close: 14, volume: 140}},
  {{timestamp: "2026-03-02T01:30:00Z", open: 14, high: 16, low: 13, close: 15, volume: 150}}
];
const weekly = charts.aggregateCandles(candles, "weekly");
const monthly = charts.aggregateCandles(candles, "monthly");
const oneMonth = charts.candlesInRange(monthly, "1mo");
const narrowViewport = charts.computeViewport(monthly, 1, 0, 2);
process.stdout.write(JSON.stringify({{
  averages,
  viewport: {{start: viewport.start, end: viewport.end, count: viewport.count, panOffset: viewport.panOffset}},
  emptyViewport,
  nearest,
  leftLabel,
  rightLabel,
  weekly,
  monthly,
  oneMonth,
  visibleMonthBars: charts.visibleBarsForRange(monthly, "1mo"),
  narrowViewport: {{start: narrowViewport.start, end: narrowViewport.end, count: narrowViewport.count}},
  latestWeeklyChange: explorer.latestPeriodChange(weekly)
}}));
"""
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)

    assert result["averages"][:4] == [None, None, None, None]
    assert result["averages"][4] == pytest.approx(3)
    assert result["averages"][-1] == pytest.approx(18)
    assert result["viewport"] == {"start": 5, "end": 17, "count": 12, "panOffset": 3}
    assert result["emptyViewport"]["count"] == 0
    assert result["emptyViewport"]["panOffset"] == 0
    assert result["nearest"] == 0
    assert result["leftLabel"] == {"x": 6, "y": 10, "alignment": "left"}
    assert result["rightLabel"] == {"x": 174, "y": 110, "alignment": "right"}
    assert len(result["weekly"]) == 4
    assert result["weekly"][1] == {
        "time": "2026-02-02",
        "open": 11,
        "high": 14,
        "low": 10,
        "close": 13,
        "volume": 250,
    }
    assert result["monthly"][1] == {
        "time": "2026-02-01",
        "open": 11,
        "high": 15,
        "low": 10,
        "close": 14,
        "volume": 390,
    }
    assert len(result["oneMonth"]) == 2
    assert result["visibleMonthBars"] == 2
    assert result["narrowViewport"] == {"start": 1, "end": 3, "count": 2}
    assert result["latestWeeklyChange"] == pytest.approx((15 / 14 - 1) * 100)


def test_stock_pages_share_period_range_and_expanded_kline_explorer() -> None:
    html = frontend_source()

    assert '<script src="/static/qs-charts.js"></script>' in html
    assert '<script src="/static/qs-kline-explorer.js"></script>' in html
    assert EXPLORER.exists()
    assert "window.QSKlineExplorer?.createExplorer(chartHost" in html
    assert "state.deepStockKlineController?.destroy?.()" in html
    assert "charts.createInteractiveKline(canvas, points" in html
    assert "charts.aggregateCandles(payload.points || [], selection.period)" in html
    assert "charts.visibleBarsForRange(points, selection.range)" in html
    assert '`/stocks/${encodeURIComponent(symbol)}/history?range=2y`' in html
    assert '`/stocks/${encodeURIComponent(symbol)}/intraday`' in html
    assert '["intraday", "分时"]' in html
    assert '["daily", "日K"]' in html
    assert '["weekly", "周K"]' in html
    assert '["monthly", "月K"]' in html
    assert '["1y", "近1年"]' in html
    assert "放大查看" in html
    assert "拖拽平移 · 滚轮缩放 · 双击复位" in html
    assert "function aggregateWeekly(points = [])" not in html
