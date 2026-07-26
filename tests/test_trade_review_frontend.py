from __future__ import annotations

from pathlib import Path


def test_personal_review_frontend_uses_real_trade_and_research_endpoints():
    script = (
        Path(__file__).parents[1] / "app" / "static" / "high-fidelity-demo.js"
    ).read_text(encoding="utf-8")

    assert "watchRequest('/api/v1/me/trade-reviews')" in script
    assert "watchRequest('/me/run-reviews')" in script
    assert "已实现盈亏" in script
    assert "未实现盈亏" in script
    assert "交易费用" in script
    assert "净盈亏" in script
    assert "未平仓持仓不计入胜率" in script

    html = (
        Path(__file__).parents[1] / "app" / "static" / "high-fidelity-demo.html"
    ).read_text(encoding="utf-8")
    assert "+5,220.00" not in html
    assert "60.00%" not in html
    assert "本周已完成交易记录" not in html
