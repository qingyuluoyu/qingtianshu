from __future__ import annotations

from pathlib import Path

import app.main as main
from app.services import chat_routing


def test_main_keeps_chat_routing_compatibility_exports() -> None:
    assert main._conversation_title is chat_routing._conversation_title
    assert main._extract_symbol is chat_routing._extract_symbol
    assert main._extract_symbols is chat_routing._extract_symbols
    assert main._question_price_direction is chat_routing._question_price_direction
    assert main._symbols_from_history is chat_routing._symbols_from_history


def test_chat_routing_module_does_not_import_main() -> None:
    source = Path(chat_routing.__file__).read_text(encoding="utf-8")
    assert "from app.main import" not in source
    assert "import app.main" not in source


def test_chat_routing_preserves_market_and_followup_semantics() -> None:
    assert chat_routing._is_market_query("美股为什么收盘跌了")
    assert not chat_routing._is_market_query("现在仍在盘中吗")
    assert chat_routing._prefers_stock_context_followup("它相对行业更强吗")
    assert chat_routing._needs_stock_market_context("宁德时代相对电池行业走弱吗")
    assert chat_routing._needs_stock_market_context("宁德时代相对CS电池指数走弱吗")
    assert chat_routing._question_price_direction("中兴通讯今天为什么跌") == -1


def test_market_focus_prioritizes_index_experience_gap_over_turnover_dimension() -> None:
    focus = chat_routing._market_question_focus(
        "今天A股到底发生了什么，为什么指数表现和大多数个股的体感不一样？"
        "请结合指数、涨跌分布和成交额分析。"
    )

    assert focus["key"] == "market_cause"
    assert focus["label"] == "指数与个股体感差异"
    assert "没有成分权重贡献或风格指数时不猜差异来源" in focus[
        "answer_requirements"
    ]


def test_chat_routing_restores_saved_research_context() -> None:
    history = [
        {
            "role": "assistant",
            "intent": "stock_comparison",
            "metadata": {
                "research_targets": [
                    {"symbol": "000063.SZ"},
                    {"symbol": "NVDA"},
                ],
                "market_key": "china",
            },
        }
    ]
    assert chat_routing._intent_from_history(history) == "stock_comparison"
    assert chat_routing._symbols_from_history(history) == ["000063.SZ", "NVDA"]
    assert chat_routing._market_key_from_history(history) == "china"
