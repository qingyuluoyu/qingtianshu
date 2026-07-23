from app.main import _extract_symbol, _extract_symbols, _symbols_from_history


def test_security_name_beats_t_plus_research_horizon() -> None:
    message = "英伟达之前的研究后来怎么样？请结合T+3、T+5、T+10进度说明。"

    assert _extract_symbol(None, message, watchlist=[]) == "NVDA"


def test_t_plus_horizon_does_not_become_at_and_t_ticker() -> None:
    assert _extract_symbol(None, "T+3、T+5、T+10进度", watchlist=[]) is None
    assert _extract_symbol(None, "T+3之后再看NVDA", watchlist=[]) == "NVDA"


def test_bare_ticker_t_remains_supported() -> None:
    assert _extract_symbol(None, "分析 T 的最新财报", watchlist=[]) == "T"


def test_multiple_named_stocks_are_extracted_in_user_order() -> None:
    assert _extract_symbols(
        None,
        "比较中兴通讯、中际旭创和英伟达的盈利质量、估值和风险",
        watchlist=[],
    ) == ["000063.SZ", "300308.SZ", "NVDA"]


def test_full_a_share_code_does_not_turn_exchange_suffix_into_second_symbol() -> None:
    assert _extract_symbols(
        None,
        "000001.SZ在李总策略里通过了吗？",
        watchlist=[],
    ) == ["000001.SZ"]


def test_comparison_targets_can_be_restored_from_conversation_metadata() -> None:
    history = [
        {
            "role": "assistant",
            "intent": "stock_comparison",
            "metadata": {
                "research_targets": [
                    {"symbol": "000063.SZ", "name": "中兴通讯"},
                    {"symbol": "NVDA", "name": "英伟达"},
                ]
            },
        }
    ]

    assert _symbols_from_history(history) == ["000063.SZ", "NVDA"]
