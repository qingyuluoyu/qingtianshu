import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
MODULE = ROOT / "app" / "static" / "qs-charts.js"
DEMO = ROOT / "app" / "static" / "demo.html"
FRONTEND_ASSETS = (
    "demo.css",
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
const rows = Array.from({{length: 20}}, (_, index) => ({{close: index + 1}}));
const averages = charts.movingAverage(rows, 5);
const viewport = charts.computeViewport(rows, 12, 3);
const emptyViewport = charts.computeViewport([], 12, 9);
const nearest = charts.nearestCandleIndex(50, 200, 10, 40, 10);
const leftLabel = charts.clampRadarLabel(180, 120, -20, -5, 42, "left");
const rightLabel = charts.clampRadarLabel(180, 120, 220, 140, 42, "right");
process.stdout.write(JSON.stringify({{
  averages,
  viewport: {{start: viewport.start, end: viewport.end, count: viewport.count, panOffset: viewport.panOffset}},
  emptyViewport,
  nearest,
  leftLabel,
  rightLabel
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


def test_deep_stock_chart_uses_full_history_interactive_controller() -> None:
    html = frontend_source()

    assert '<script src="/static/qs-charts.js"></script>' in html
    assert "window.QSCharts.createInteractiveKline(canvas, points" in html
    assert "chartController?.setVisibleBars(limit)" in html
    assert "state.deepStockKlineController?.destroy?.()" in html
    assert "points.slice(-limit)" not in html
    assert "历史视图，双击复位" in html
