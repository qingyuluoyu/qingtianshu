from app.main import (
    _extract_symbol,
    _extract_symbols,
    _extract_industry_topic,
    _is_market_query,
    _is_peer_comparison_query,
    _is_stock_screen_query,
    _symbols_from_history,
)


def test_security_name_beats_t_plus_research_horizon() -> None:
    message = "英伟达之前的研究后来怎么样？请结合T+3、T+5、T+10进度说明。"

    assert _extract_symbol(None, message, watchlist=[]) == "NVDA"


def test_t_plus_horizon_does_not_become_at_and_t_ticker() -> None:
    assert _extract_symbol(None, "T+3、T+5、T+10进度", watchlist=[]) is None
    assert _extract_symbol(None, "T+3之后再看NVDA", watchlist=[]) == "NVDA"


def test_bare_ticker_t_remains_supported() -> None:
    assert _extract_symbol(None, "分析 T 的最新财报", watchlist=[]) == "T"


def test_single_letter_section_labels_do_not_become_stock_tickers() -> None:
    assert _extract_symbol(
        None,
        "交互验收B：请继续说明这些财务压力能确认什么",
        watchlist=[],
    ) is None
    assert _extract_symbols(
        None,
        "方案A和方案B哪个更适合当前研究？",
        watchlist=[],
    ) == []


def test_generic_financial_product_acronyms_do_not_become_stock_tickers() -> None:
    assert _extract_symbols(
        None,
        "基金、ETF、LOF、REIT和QDII有什么区别？",
        watchlist=[],
    ) == []
    assert _extract_symbol("ETF", "分析证券代码ETF", watchlist=[]) == "ETF"


def test_cs_industry_index_name_does_not_become_second_stock() -> None:
    message = (
        "用最新数据重新分析：宁德时代今天相对CS电池行业是增强还是走弱？"
        "请给出个股与指数差值。"
    )

    assert _extract_symbols(None, message, watchlist=[]) == ["300750.SZ"]


def test_fund_product_choice_does_not_start_a_share_stock_screening() -> None:
    assert not _is_stock_screen_query(
        "我快退休了，不知道该选股票基金还是债券基金"
    )
    assert not _is_stock_screen_query("帮我筛选基金和ETF")
    assert _is_stock_screen_query("帮我筛选几只股票做研究候选")


def test_company_market_demand_and_industry_boundary_are_not_market_objects() -> None:
    message = (
        "库存增加主要是为下半年市场需求而提前备货；"
        "同时保留毛利率、现金流和行业边界。"
    )

    assert _is_market_query(message) is False
    assert _extract_industry_topic(message) is None


def test_existing_screening_card_reference_does_not_restart_stock_screening() -> None:
    assert not _is_stock_screen_query(
        "请先直接回答，再说明哪些原因目前没有证据；不要复述选股卡片。"
    )
    assert not _is_stock_screen_query("解释一下刚才的选股结果，不要重新跑筛选")
    assert _is_stock_screen_query("请重新选股，给我一批新的股票候选")


def test_peer_valuation_wording_does_not_become_stock_screening() -> None:
    message = (
        "宁德时代的PE和PB分别相对亿纬锂能、国轩高科、欣旺达处于什么位置？"
        "请说明估值约束。"
    )

    assert _is_peer_comparison_query(message) is True
    assert _is_stock_screen_query(message) is False
    assert _is_stock_screen_query("按估值约束筛选") is True


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
