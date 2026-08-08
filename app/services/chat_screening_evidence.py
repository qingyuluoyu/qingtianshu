from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.chat_routing import _stock_screen_parameters
from app.services.li_zong_presentation import public_li_zong_candidate
from app.services.stock_screener import StockScreenerUnavailable


@dataclass(frozen=True, slots=True)
class ChatScreeningResult:
    evidence: dict[str, Any]
    symbol: str | None


class ChatScreeningEvidenceService:
    """Build deterministic evidence for standard and Li Zong screening chats."""

    def __init__(
        self,
        *,
        stock_screener: Any,
        li_zong_strategy: Any,
        li_zong_history: Any,
    ) -> None:
        self.stock_screener = stock_screener
        self.li_zong_strategy = li_zong_strategy
        self.li_zong_history = li_zong_history

    def build_standard(self, message: str) -> dict[str, Any]:
        screen_parameters = _stock_screen_parameters(message)
        try:
            return self.stock_screener.screen(**screen_parameters)
        except StockScreenerUnavailable:
            return {
                "type": "stock_screen",
                "status": "unavailable",
                "profile": {
                    "key": screen_parameters["profile"],
                    "label": "研究候选筛选",
                },
                "data_meta": {},
                "items": [],
                "warnings": ["完整市场截面仍在准备。"],
                "boundary": "系统不会在缺少确定性数据时生成临时候选。",
            }

    def build_li_zong(
        self,
        message: str,
        *,
        symbol: str | None,
    ) -> ChatScreeningResult:
        coverage = self.li_zong_strategy.coverage_packet()
        rule_funnel = self.li_zong_strategy.funnel_packet()
        requested_symbols = self.li_zong_strategy.resolve_universe_mentions(message)
        if symbol is not None and symbol not in requested_symbols:
            requested_symbols.insert(0, symbol)

        if requested_symbols:
            candidates = []
            for requested in requested_symbols:
                try:
                    candidates.append(self.li_zong_strategy.get_candidate(requested))
                except ValueError:
                    candidates.append(None)
            selection_mode = (
                "symbol_check"
                if len(requested_symbols) == 1
                else "symbol_comparison"
            )
            if len(requested_symbols) == 1:
                symbol = requested_symbols[0]
        else:
            candidates = self.li_zong_strategy.list_actionable_candidates(limit=50)
            selection_mode = "candidate_pool"

        public_items = [
            public_li_zong_candidate(item)
            for item in candidates
            if item is not None
        ]
        history_requested = any(
            keyword in message
            for keyword in ("历史", "以前", "曾经", "后来", "走势", "表现", "回放")
        )
        history_packet = (
            self.li_zong_history.history_packet(
                symbol=(
                    requested_symbols[0]
                    if len(requested_symbols) == 1 and history_requested
                    else None
                ),
                limit=12,
            )
            if history_requested or not public_items
            else None
        )

        evaluated = int(coverage.get("evaluated_symbols") or 0)
        universe_count = int(coverage.get("universe_count") or 0)
        if not universe_count:
            evaluated = max(evaluated, len(public_items))
        full_coverage = bool(coverage.get("full_market_coverage"))
        deep_eligible = int(coverage.get("deep_check_eligible_count") or 0)
        deep_processed = int(coverage.get("deep_processed_symbols") or 0)
        deep_complete = bool(coverage.get("deep_check_complete"))
        history_insufficient = int(coverage.get("history_insufficient_count") or 0)
        history_unknown = int(coverage.get("history_unknown_count") or 0)
        warnings = self._coverage_warnings(
            coverage=coverage,
            evaluated=evaluated,
            universe_count=universe_count,
            full_coverage=full_coverage,
            deep_eligible=deep_eligible,
            deep_processed=deep_processed,
            deep_complete=deep_complete,
            history_insufficient=history_insufficient,
            history_unknown=history_unknown,
            selection_mode=selection_mode,
            public_items=public_items,
            history_packet=history_packet,
        )

        missing_requested_symbols = (
            [
                requested
                for requested, candidate in zip(requested_symbols, candidates)
                if candidate is None
            ]
            if requested_symbols
            else []
        )
        if missing_requested_symbols:
            warnings.append(
                "以下股票尚未形成可用的李总策略快照："
                + "、".join(missing_requested_symbols)
                + "。"
            )

        strategy_counts = coverage.get("counts") or {}
        actionable_candidate_count = int(
            strategy_counts.get("qualified") or 0
        ) + int(strategy_counts.get("triggered") or 0)
        evidence = {
            "type": "stock_screen",
            "status": (
                "ready"
                if selection_mode in {"symbol_check", "symbol_comparison"}
                and requested_symbols
                and len(public_items) == len(requested_symbols)
                else "complete"
                if selection_mode == "candidate_pool"
                and full_coverage
                and deep_complete
                else "partial"
            ),
            "strategy": self.li_zong_strategy.get_definition(),
            "profile": {
                "key": "li_zong",
                "label": "李总策略",
                "description": "基本面、股性、量价与盘后触发的确定性规则。",
            },
            "selection_mode": selection_mode,
            "requested_symbol": (
                requested_symbols[0] if len(requested_symbols) == 1 else None
            ),
            "requested_symbols": requested_symbols,
            "missing_requested_symbols": missing_requested_symbols,
            "items": public_items,
            "rule_funnel": rule_funnel,
            "history": history_packet,
            "data_meta": {
                "universe_status": coverage.get("status"),
                "latest_completed_trade_date": coverage.get("as_of_date")
                or max(
                    (
                        str(item.get("as_of_date"))
                        for item in public_items
                        if item.get("as_of_date")
                    ),
                    default=None,
                ),
                "universe_count": universe_count,
                "evaluated_symbols": evaluated,
                "remaining_symbols": int(coverage.get("remaining_symbols") or 0),
                "coverage_ratio": float(coverage.get("coverage_ratio") or 0),
                "full_market_coverage": full_coverage,
                "deep_check_eligible_count": deep_eligible,
                "history_insufficient_count": history_insufficient,
                "history_unknown_count": history_unknown,
                "deep_processed_symbols": deep_processed,
                "deep_remaining_symbols": int(
                    coverage.get("deep_remaining_symbols") or 0
                ),
                "deep_processing_ratio": float(
                    coverage.get("deep_processing_ratio") or 0
                ),
                "deep_decisive_symbols": int(
                    coverage.get("deep_decisive_symbols") or 0
                ),
                "deep_data_incomplete_symbols": int(
                    coverage.get("deep_data_incomplete_symbols") or 0
                ),
                "deep_check_complete": deep_complete,
                "actionable_candidate_count": actionable_candidate_count,
            },
            "user_question": message,
            "warnings": warnings,
            "boundary": "该策略只生成研究候选和人工复核触发，不构成买卖建议。",
        }
        return ChatScreeningResult(evidence=evidence, symbol=symbol)

    @staticmethod
    def _coverage_warnings(
        *,
        coverage: dict[str, Any],
        evaluated: int,
        universe_count: int,
        full_coverage: bool,
        deep_eligible: int,
        deep_processed: int,
        deep_complete: bool,
        history_insufficient: int,
        history_unknown: int,
        selection_mode: str,
        public_items: list[dict[str, Any]],
        history_packet: dict[str, Any] | None,
    ) -> list[str]:
        warnings: list[str] = []
        if coverage.get("status") != "stable":
            warnings.append("全市场名单和市值快照尚未达到稳定发布门槛。")
        elif not full_coverage:
            warnings.append(
                f"当前已有 {evaluated}/{universe_count} 只股票形成预筛或规则状态；"
                "未处理股票不能推断为通过或不通过。"
            )
        if coverage.get("status") == "stable" and not deep_complete:
            warnings.append(
                f"当前已深度处理 {deep_processed}/{deep_eligible} 只可核验股票；"
                "尚未深度处理的股票不能推断为通过或不通过。"
            )
        if history_insufficient:
            warnings.append(
                f"另有 {history_insufficient} 只市值达标股票因上市后量价历史不足，"
                "已明确标记为数据不完整，未消耗逐股深度请求。"
            )
        if history_unknown:
            warnings.append(
                f"另有 {history_unknown} 只股票不能仅凭上市日期确认五年ROE是否可得，"
                "已纳入深度查询，不代表财务历史已经完整。"
            )
        if selection_mode == "candidate_pool" and not public_items:
            warnings.append(
                "当前已评估范围内尚无进入候选池或触发池的股票。"
                if not (full_coverage and deep_complete)
                else "本期全市场预筛与深度处理完成，尚无股票进入候选池或触发池。"
            )
            if history_packet and not (history_packet.get("items") or []):
                warnings.append("近期历史回放仍在后台增量生成，暂未发布可展示样本。")
        if selection_mode == "symbol_check" and not public_items:
            warnings.append("该股票尚未形成可用的李总策略快照。")
        return warnings
