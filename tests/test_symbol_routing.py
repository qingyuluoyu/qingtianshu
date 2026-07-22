from app.main import _extract_symbol


def test_security_name_beats_t_plus_research_horizon() -> None:
    message = "英伟达之前的研究后来怎么样？请结合T+3、T+5、T+10进度说明。"

    assert _extract_symbol(None, message, watchlist=[]) == "NVDA"


def test_t_plus_horizon_does_not_become_at_and_t_ticker() -> None:
    assert _extract_symbol(None, "T+3、T+5、T+10进度", watchlist=[]) is None
    assert _extract_symbol(None, "T+3之后再看NVDA", watchlist=[]) == "NVDA"


def test_bare_ticker_t_remains_supported() -> None:
    assert _extract_symbol(None, "分析 T 的最新财报", watchlist=[]) == "T"
