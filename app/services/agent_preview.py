from __future__ import annotations

from typing import Any, Callable

from app.services.agent_preview_market import render_market_preview
from app.services.agent_preview_misc import render_misc_preview
from app.services.agent_preview_stock import render_stock_preview


def render_preview(
    evidence: dict[str, Any],
    *,
    render_li_zong_preview: Callable[[dict[str, Any]], str],
) -> str:
    stock_preview = render_stock_preview(
        evidence,
        render_li_zong_preview=render_li_zong_preview,
    )
    if stock_preview is not None:
        return stock_preview

    market_preview = render_market_preview(evidence)
    if market_preview is not None:
        return market_preview

    misc_preview = render_misc_preview(evidence)
    if misc_preview is not None:
        return misc_preview

    return "证据已保存，但 preview 暂无对应的展示模板。"
