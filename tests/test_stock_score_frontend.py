from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "app" / "static" / "high-fidelity-demo.js"
CSS = ROOT / "app" / "static" / "high-fidelity-demo.css"


def test_five_factor_layout_has_descriptions_and_two_column_grid():
    js = JS.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")

    assert "function industryFactorDescription" in js
    assert "function industryFactorBand" in js
    assert "grid-template-columns:repeat(2,minmax(0,1fr))" in css
    assert "grid-template-columns:minmax(360px,420px) minmax(0,1fr)" in css
    assert "industry-factor-description" in css


def test_comparison_chart_clamps_positive_and_negative_labels():
    js = JS.read_text(encoding="utf-8")

    assert "function clampChartLabelY" in js
    assert "clampChartLabelY(" in js
    assert "zeroY" in js


def test_stock_status_uses_consumer_facing_chinese_labels():
    js = JS.read_text(encoding="utf-8")

    assert "function stockDataStateLabel" in js
    assert "数据更新中" in js
