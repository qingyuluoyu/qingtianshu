from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "app/static/high-fidelity-demo.js").read_text(encoding="utf-8")
CSS = (ROOT / "app/static/high-fidelity-demo.css").read_text(encoding="utf-8")
HTML = (ROOT / "app/static/high-fidelity-demo.html").read_text(encoding="utf-8")


def test_today_dashboard_recovers_missing_modules_and_uses_market_date_only():
    assert "todayModuleNeedsRefresh" in JS
    assert "todayAlignmentRecoveryKeys" in JS
    assert "renderTodayDataStatus" in JS
    assert "asOfMarketDate" in JS
    assert "dateAlignment" in JS
    assert "Promise.allSettled" in JS
    assert "String(payload.generatedAt||'').slice(0,10)" not in JS
    assert "数据截止" in JS
    assert "页面更新" in JS


def test_today_charts_require_real_sector_history_and_fixed_bar_plot():
    assert "trendStatus" in JS
    assert "trendMarketDates" in JS
    assert "Number.isFinite(five)" in JS
    assert "bar-column" in JS
    assert "bar-plot" in JS
    assert ".bar-plot" in CSS
    assert ".bar-fill" in CSS
    assert "历史走势补齐中" in JS
    assert "fiveDayChangePct:None" not in JS
    assert "正在读取真实行业历史" in HTML
    assert (
        ".rank-row>*:nth-child(4),.rank-row>*:nth-child(6){display:none}"
        not in CSS
    )
