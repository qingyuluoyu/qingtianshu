from pathlib import Path

from app.services import agent as agent_module
from app.services.agent_output_guard_common import _number_value
from app.services.agent_output_guard import AgentOutputGuard
from app.services.agent_output_guard_market import (
    _has_unproven_downtrend_claim,
    _has_wrong_index_return_extreme_claim,
)
from app.services.agent_output_guard_stock import (
    _normalize_stock_research_number_precision,
    _stock_current_quote_required_but_missing,
)


def test_agent_reexports_extracted_output_guard_functions():
    assert (
        agent_module.AgentService._validate_model_output
        is AgentOutputGuard._validate_model_output
    )
    assert (
        agent_module.AgentService._repair_guard_failure
        is AgentOutputGuard._repair_guard_failure
    )
    assert (
        agent_module._has_wrong_index_return_extreme_claim
        is _has_wrong_index_return_extreme_claim
    )
    assert (
        agent_module._normalize_stock_research_number_precision
        is _normalize_stock_research_number_precision
    )


def test_output_guard_modules_do_not_import_agent_service():
    service_dir = Path(agent_module.__file__).parent
    for filename in (
        "agent_output_guard.py",
        "agent_output_guard_common.py",
        "agent_output_guard_market.py",
        "agent_output_guard_stock.py",
    ):
        source = (service_dir / filename).read_text(encoding="utf-8")
        assert "from app.services.agent import" not in source
        assert "AgentService" not in source


def test_common_number_parser_is_shared_by_guard_domains():
    assert _number_value("1,234.50%") == 1234.5
    assert _number_value("not-a-number") is None


def test_market_guard_preserves_cautious_trend_language():
    assert _has_unproven_downtrend_claim("市场仍处于下跌趋势") is True
    assert _has_unproven_downtrend_claim("单日下跌不代表市场仍处于下跌趋势") is False


def test_stock_guard_requires_current_quote_for_today_question():
    evidence = {
        "user_question": "中兴通讯今天怎么样",
        "current_quote": {
            "price": 41.26,
            "pct_change": -2.56,
            "market_timestamp": "2026-07-24T15:00:00+08:00",
        },
        "provenance": {"market_timestamp": "2026-07-23T15:00:00+08:00"},
    }
    assert _stock_current_quote_required_but_missing("今日下跌，但价格待核验。", evidence)
    assert not _stock_current_quote_required_but_missing(
        "今日最新报价41.26元，下跌2.56%。", evidence
    )
