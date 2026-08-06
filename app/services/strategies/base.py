from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Mapping, Protocol, runtime_checkable


RuleStatus = Literal["passed", "failed", "data_incomplete"]
StrategyStatus = Literal[
    "qualified",
    "triggered",
    "not_qualified",
    "data_incomplete",
]


@dataclass(frozen=True)
class StrategyRuleResult:
    """Auditable result for one deterministic strategy rule."""

    rule_id: str
    status: RuleStatus
    actual_value: Any
    threshold: Any
    source: str
    formula_version: str
    evidence_date: str | None = None
    report_period: str | None = None
    limitations: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["limitations"] = list(self.limitations)
        return payload


@dataclass(frozen=True)
class StrategyEvaluation:
    """Stable envelope shared by deterministic stock-selection strategies."""

    strategy_id: str
    strategy_version: str
    parameter_version: str
    method: str
    symbol: str
    as_of_date: str
    status: StrategyStatus
    candidate_qualified: bool
    triggered_rule_ids: tuple[str, ...]
    rule_results: tuple[StrategyRuleResult, ...]
    limitations: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "parameter_version": self.parameter_version,
            "method": self.method,
            "symbol": self.symbol,
            "as_of_date": self.as_of_date,
            "status": self.status,
            "candidate_qualified": self.candidate_qualified,
            "triggered_rule_ids": list(self.triggered_rule_ids),
            "rule_results": [result.to_dict() for result in self.rule_results],
            "limitations": list(self.limitations),
            "boundary": "仅用于确定性研究候选筛选和人工复核，不构成买卖建议或自动交易指令。",
        }


@runtime_checkable
class StockSelectionStrategy(Protocol):
    """Interface for versioned, deterministic stock-selection strategies."""

    strategy_id: str
    strategy_version: str
    method: str

    def evaluate(
        self,
        data: Mapping[str, Any] | Any,
        *,
        parameters: Mapping[str, Any] | Any | None = None,
    ) -> dict[str, Any]: ...


class StrategyRegistry:
    """Small explicit registry; strategy execution stays outside web requests."""

    def __init__(self, strategies: list[StockSelectionStrategy] | None = None) -> None:
        self._strategies: dict[str, StockSelectionStrategy] = {}
        for strategy in strategies or []:
            self.register(strategy)

    def register(self, strategy: StockSelectionStrategy) -> None:
        if not isinstance(strategy, StockSelectionStrategy):
            raise TypeError("strategy must implement StockSelectionStrategy")
        if strategy.strategy_id in self._strategies:
            raise ValueError(f"strategy already registered: {strategy.strategy_id}")
        self._strategies[strategy.strategy_id] = strategy

    def get(self, strategy_id: str) -> StockSelectionStrategy:
        try:
            return self._strategies[strategy_id]
        except KeyError as exc:
            raise KeyError(f"unknown strategy: {strategy_id}") from exc

    def list(self) -> list[dict[str, str]]:
        return [
            {
                "strategy_id": strategy.strategy_id,
                "strategy_version": strategy.strategy_version,
                "method": strategy.method,
            }
            for strategy in self._strategies.values()
        ]
