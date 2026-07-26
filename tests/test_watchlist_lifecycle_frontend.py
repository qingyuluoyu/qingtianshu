from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_watchlist_form_contains_research_fields_not_trade_or_position_fields():
    html = (ROOT / "app/static/high-fidelity-demo.html").read_text(encoding="utf-8")

    assert 'id="watchAddReason"' in html
    assert 'id="watchAddPriority"' in html
    assert 'id="watchAddCatalyst"' in html
    assert 'id="watchAddInvalidation"' in html
    assert 'id="watchAddFrequency"' in html
    assert "watchAddStatus" not in html
    assert "watchAddPurchasePrice" not in html
    assert "watchAddHoldingQuantity" not in html
    assert "watchAddSellPrice" not in html


def test_watchlist_frontend_uses_typed_lifecycle_endpoints_and_independent_statuses():
    script = (ROOT / "app/static/high-fidelity-demo.js").read_text(encoding="utf-8")

    assert "watchRequest('/api/v1/me/watchlist'" in script
    assert "watchRequest('/api/v1/me/positions'" in script
    assert "/api/v1/me/positions/'+encodeURIComponent(positionId)+'/trades" in script
    assert "转为模拟持仓" in script
    assert "记录实盘持仓" in script
    assert "关注状态" in script
    assert "研究状态" in script
    assert "持仓状态" in script
    assert "legacy_position_hint" in script
    assert "focus_status" not in script
    assert "holding_quantity" not in script
    assert "purchase_price" not in script
    assert "sell_price" not in script


def test_session_failure_never_silently_creates_a_new_user():
    script = (ROOT / "app/static/high-fidelity-demo.js").read_text(encoding="utf-8")

    assert "watchRequest('/users',{method:'POST'" not in script
    assert "会话已失效，请重新登录" in script
