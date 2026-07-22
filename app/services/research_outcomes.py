from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from typing import Any

from app.catalog import RESEARCH_TARGETS, normalize_symbol
from app.db import Database
from app.utils import utc_now


class ResearchOutcomeService:
    """Backfill observable 3/5/10-session research outcomes from stored bars.

    This evaluates whether documented price scenarios were observed after a
    research snapshot.  It deliberately does not score investment returns,
    strategy quality, or buy/sell accuracy.
    """

    HORIZONS = (3, 5, 10)
    METHOD = "stored_bar_research_outcome_v1"

    def __init__(self, database: Database):
        self.database = database

    def backfill(
        self, symbol: str | None = None, *, limit: int = 1000
    ) -> dict[str, Any]:
        canonical = normalize_symbol(symbol) if symbol else None
        reports = self.database.list_research_anchor_reports(canonical, limit=limit)
        updated = 0
        unchanged = 0
        status_counts = {"available": 0, "pending": 0, "unavailable": 0}
        touched_symbols: set[str] = set()
        latest_data_as_of: str | None = None

        bars_by_symbol: dict[str, list[dict[str, Any]]] = {}
        for report in reports:
            item_symbol = str(report["symbol"])
            if item_symbol not in bars_by_symbol:
                bars_by_symbol[item_symbol] = self.database.get_market_bars(
                    item_symbol, "1d", limit=4000
                )
            bars = bars_by_symbol[item_symbol]
            if bars:
                latest_data_as_of = max(
                    latest_data_as_of or str(bars[-1]["timestamp"]),
                    str(bars[-1]["timestamp"]),
                )
            for horizon in self.HORIZONS:
                outcome = self._calculate(report, bars, horizon)
                existing = self.database.research_outcome_for_anchor(
                    item_symbol,
                    outcome["anchor_timestamp"],
                    horizon,
                )
                if self._same_outcome(existing, outcome):
                    unchanged += 1
                else:
                    self.database.save_research_outcome(outcome)
                    updated += 1
                status_counts[outcome["result_status"]] += 1
                touched_symbols.add(item_symbol)

        for item_symbol in touched_symbols:
            self._index_common_knowledge(item_symbol)

        return {
            "status": "completed",
            "generated_at": utc_now(),
            "method": self.METHOD,
            "reports_scanned": len(reports),
            "outcomes_scanned": len(reports) * len(self.HORIZONS),
            "updated": updated,
            "unchanged": unchanged,
            **status_counts,
            "data_as_of": latest_data_as_of,
        }

    def get_packet(
        self, user_id: str, symbol: str | None = None, limit: int = 120
    ) -> dict[str, Any]:
        canonical = normalize_symbol(symbol) if symbol else None
        watchlist = self.database.list_watchlist(user_id)
        watchlist_map = {item["symbol"]: item for item in watchlist}
        symbols = [canonical] if canonical else list(watchlist_map)
        if canonical and canonical not in watchlist_map:
            watchlist_map[canonical] = {"symbol": canonical}

        for item_symbol in symbols[:20]:
            self.backfill(item_symbol, limit=300)

        outcomes = self.database.list_research_outcomes(symbols, limit=limit)
        grouped: dict[str, list[dict[str, Any]]] = {item: [] for item in symbols}
        for outcome in outcomes:
            grouped.setdefault(str(outcome["symbol"]), []).append(outcome)

        items = []
        for item_symbol in symbols:
            rows = grouped.get(item_symbol) or []
            report = self.database.latest_research_report(item_symbol)
            report_evidence = (report or {}).get("evidence") or {}
            report_metrics = report_evidence.get("metrics") or {}
            fundamentals = report_evidence.get("fundamentals") or {}
            fundamentals_summary = fundamentals.get("summary") or {}
            latest_financial = fundamentals_summary.get("latest_report") or {}
            name = (
                RESEARCH_TARGETS.get(item_symbol, {}).get("name")
                or watchlist_map.get(item_symbol, {}).get("name")
                or (report or {}).get("name")
                or item_symbol
            )
            anchors: dict[str, list[dict[str, Any]]] = {}
            for row in rows:
                anchors.setdefault(str(row["anchor_timestamp"]), []).append(row)
            latest_anchor = max(anchors, default=None)
            latest_rows = sorted(
                anchors.get(latest_anchor, []), key=lambda row: row["horizon_sessions"]
            )
            latest_available_by_horizon = []
            for horizon in self.HORIZONS:
                match = next(
                    (
                        row
                        for row in rows
                        if row["horizon_sessions"] == horizon
                        and row["result_status"] == "available"
                    ),
                    None,
                )
                if match:
                    latest_available_by_horizon.append(self.public_outcome(match))
            latest_progress = next(
                (row for row in rows if int(row.get("observed_sessions") or 0) > 0),
                None,
            )
            items.append(
                {
                    "symbol": item_symbol,
                    "name": name,
                    "thesis": watchlist_map.get(item_symbol, {}).get("thesis"),
                    "latest_anchor_at": latest_anchor,
                    "latest_anchor": [self.public_outcome(row) for row in latest_rows],
                    "latest_progress": self.public_outcome(latest_progress),
                    "latest_available": latest_available_by_horizon,
                    "current_research_context": {
                        "metrics": {
                            key: report_metrics.get(key)
                            for key in (
                                "latest_close",
                                "return_1d_pct",
                                "return_20d_pct",
                                "trend_state",
                                "technical_state",
                                "volatility_20d_annualized_pct",
                                "max_drawdown_60d_pct",
                            )
                        },
                        "latest_financial": {
                            key: latest_financial.get(key)
                            for key in (
                                "report_date_name",
                                "revenue_yoy_pct",
                                "net_profit_yoy_pct",
                            )
                        },
                        "operating_cashflow_to_net_profit": fundamentals_summary.get(
                            "operating_cashflow_to_net_profit"
                        ),
                    },
                    "coverage": {
                        "anchors": len(anchors),
                        "available": sum(
                            row["result_status"] == "available" for row in rows
                        ),
                        "pending": sum(row["result_status"] == "pending" for row in rows),
                    },
                }
            )

        return {
            "type": "research_outcome",
            "generated_at": utc_now(),
            "symbol": canonical,
            "items": items,
            "coverage": {
                "requested_symbols": len(symbols),
                "with_archives": sum(bool(item["latest_anchor"]) for item in items),
                "available_outcomes": sum(
                    item["coverage"]["available"] for item in items
                ),
                "pending_outcomes": sum(item["coverage"]["pending"] for item in items),
            },
            "method": (
                "只使用已写入数据库的复权日线，从每份研究快照之后按第3、5、10个交易日回填；"
                "同时记录区间内最大上行、最大下行和原条件情景是否被观察到。"
            ),
            "boundary": (
                "该复盘用于检查研究条件和反证，不评价买卖收益、策略胜率、"
                "荐股准确率或投资能力；未到期样本只显示观察进度。"
            ),
        }

    def _calculate(
        self,
        report: dict[str, Any],
        bars: list[dict[str, Any]],
        horizon: int,
    ) -> dict[str, Any]:
        evidence = report.get("evidence") or {}
        name = (
            RESEARCH_TARGETS.get(str(report["symbol"]), {}).get("name")
            or evidence.get("display_name")
            or report.get("name")
            or report["symbol"]
        )
        anchor_timestamp = str(
            report.get("market_timestamp")
            or (evidence.get("latest_bar") or {}).get("timestamp")
            or report["generated_at"]
        )
        anchor_dt = _parse_timestamp(anchor_timestamp)
        parsed_bars = [
            (parsed, row)
            for row in bars
            if (parsed := _parse_timestamp(row.get("timestamp"))) is not None
        ]
        anchor_match = None
        if anchor_dt is not None:
            anchor_match = next(
                (
                    row
                    for parsed, row in reversed(parsed_bars)
                    if parsed <= anchor_dt
                ),
                None,
            )
        if anchor_match is None:
            return self._unavailable_outcome(
                report, name, anchor_timestamp, horizon, "anchor_daily_bar_missing"
            )

        anchor_bar_dt = _parse_timestamp(anchor_match.get("timestamp"))
        anchor_close = _bar_close(anchor_match)
        if anchor_bar_dt is None or not anchor_close:
            return self._unavailable_outcome(
                report, name, anchor_timestamp, horizon, "anchor_close_missing"
            )

        future = [
            row for parsed, row in parsed_bars if parsed > anchor_bar_dt
        ]
        observed = future[:horizon]
        available = len(observed) >= horizon
        progress_close = _bar_close(observed[-1]) if observed else None
        partial_return = _pct_change(progress_close, anchor_close)
        highs = [_bar_high(row) for row in observed]
        lows = [_bar_low(row) for row in observed]
        highs = [value for value in highs if value is not None]
        lows = [value for value in lows if value is not None]
        raw_mfe = _pct_change(max(highs), anchor_close) if highs else None
        raw_mae = _pct_change(min(lows), anchor_close) if lows else None
        mfe = max(0.0, raw_mfe) if raw_mfe is not None else None
        mae = min(0.0, raw_mae) if raw_mae is not None else None
        price_levels = evidence.get("price_levels") or {}
        scenario_result, scenario_label = _evaluate_scenario(
            observed,
            price_levels,
        )
        outlook = evidence.get("conditional_outlook") or {}
        original_label = outlook.get("label") or outlook.get("price_signal_label")

        if available:
            conclusion = _available_conclusion(
                original_label, scenario_result, horizon
            )
        elif observed:
            conclusion = (
                f"T+{horizon}尚未到期；目前已观察{len(observed)}个交易日，"
                f"还差{horizon - len(observed)}个交易日。阶段价格情景为“{scenario_label}”。"
            )
        else:
            conclusion = f"T+{horizon}尚未开始形成后续交易日样本。"

        target = observed[-1] if available else None
        payload = {
            "method": self.METHOD,
            "original_outlook_label": original_label,
            "original_outlook_confidence": outlook.get("confidence"),
            "price_levels": {
                key: price_levels.get(key)
                for key in ("recent_20d_high", "recent_20d_low", "ma20", "ma60")
            },
            "scenario_label": scenario_label,
            "progress_timestamp": observed[-1].get("timestamp") if observed else None,
            "partial_return_pct": _round(partial_return),
            "source_report_generated_at": report.get("generated_at"),
            "source_report_title": report.get("title"),
            "data_as_of": bars[-1].get("timestamp") if bars else None,
            "protocol": {
                "anchor": "研究快照对应的数据库日线收盘价",
                "horizon": f"之后第{horizon}个已存交易日",
                "price_series": "优先使用复权收盘价；复权价缺失时使用原始收盘价",
                "mfe_mae": "区间内最大上行与最大下行，仅描述路径，不代表可实现收益",
            },
            "boundary": (
                "结果回填只检验研究条件后来是否出现，不把研究快照视为买卖信号。"
            ),
        }
        return {
            "report_id": report["id"],
            "symbol": report["symbol"],
            "name": name,
            "anchor_timestamp": anchor_timestamp,
            "horizon_sessions": horizon,
            "result_status": "available" if available else "pending",
            "observed_sessions": len(observed),
            "anchor_close": _round(anchor_close),
            "target_timestamp": target.get("timestamp") if target else None,
            "target_close": _round(_bar_close(target)) if target else None,
            "close_return_pct": _round(partial_return) if available else None,
            "maximum_favorable_excursion_pct": _round(mfe),
            "maximum_adverse_excursion_pct": _round(mae),
            "scenario_result": scenario_result,
            "review_conclusion": conclusion,
            "payload": payload,
            "calculated_at": utc_now(),
        }

    def _unavailable_outcome(
        self,
        report: dict[str, Any],
        name: str,
        anchor_timestamp: str,
        horizon: int,
        reason: str,
    ) -> dict[str, Any]:
        return {
            "report_id": report["id"],
            "symbol": report["symbol"],
            "name": name,
            "anchor_timestamp": anchor_timestamp,
            "horizon_sessions": horizon,
            "result_status": "unavailable",
            "observed_sessions": 0,
            "anchor_close": None,
            "target_timestamp": None,
            "target_close": None,
            "close_return_pct": None,
            "maximum_favorable_excursion_pct": None,
            "maximum_adverse_excursion_pct": None,
            "scenario_result": "not_evaluable",
            "review_conclusion": "缺少与研究快照对应的已存日线，当前不能进行结果复盘。",
            "payload": {
                "method": self.METHOD,
                "unavailable_reason": reason,
                "boundary": "不使用缺失或未来行情补算研究结果。",
            },
            "calculated_at": utc_now(),
        }

    @staticmethod
    def _same_outcome(
        existing: dict[str, Any] | None, outcome: dict[str, Any]
    ) -> bool:
        if existing is None:
            return False
        keys = (
            "report_id",
            "symbol",
            "name",
            "anchor_timestamp",
            "horizon_sessions",
            "result_status",
            "observed_sessions",
            "anchor_close",
            "target_timestamp",
            "target_close",
            "close_return_pct",
            "maximum_favorable_excursion_pct",
            "maximum_adverse_excursion_pct",
            "scenario_result",
            "review_conclusion",
        )
        return all(existing.get(key) == outcome.get(key) for key in keys) and (
            existing.get("payload") == outcome.get("payload")
        )

    @staticmethod
    def public_outcome(outcome: dict[str, Any] | None) -> dict[str, Any] | None:
        if outcome is None:
            return None
        payload = outcome.get("payload") or {}
        return {
            key: outcome.get(key)
            for key in (
                "id",
                "report_id",
                "symbol",
                "name",
                "anchor_timestamp",
                "horizon_sessions",
                "result_status",
                "observed_sessions",
                "anchor_close",
                "target_timestamp",
                "target_close",
                "close_return_pct",
                "maximum_favorable_excursion_pct",
                "maximum_adverse_excursion_pct",
                "scenario_result",
                "review_conclusion",
                "calculated_at",
            )
        } | {
            "original_outlook_label": payload.get("original_outlook_label"),
            "scenario_label": payload.get("scenario_label"),
            "progress_timestamp": payload.get("progress_timestamp"),
            "partial_return_pct": payload.get("partial_return_pct"),
            "data_as_of": payload.get("data_as_of"),
            "protocol": payload.get("protocol"),
            "boundary": payload.get("boundary"),
        }

    def _index_common_knowledge(self, symbol: str) -> None:
        rows = self.database.list_research_outcomes([symbol], limit=12)
        if not rows:
            return
        name = rows[0].get("name") or RESEARCH_TARGETS.get(symbol, {}).get("name") or symbol
        source_key = f"research-outcome:{symbol}"
        document_id = "outcome-" + hashlib.sha256(source_key.encode("utf-8")).hexdigest()[:24]
        lines = [
            f"# {name}研究结果复盘",
            "",
            f"方法：{self.METHOD}",
            "",
        ]
        for row in rows[:9]:
            public = self.public_outcome(row) or {}
            progress_return = (
                public.get("close_return_pct")
                if public.get("result_status") == "available"
                else public.get("partial_return_pct")
            )
            return_text = (
                f"{float(progress_return):.2f}%"
                if isinstance(progress_return, (int, float))
                else "尚无后续价格"
            )
            lines.extend(
                [
                    f"## {public.get('anchor_timestamp')} · T+{public.get('horizon_sessions')}",
                    f"- 状态：{public.get('result_status')}",
                    f"- 已观察交易日：{public.get('observed_sessions')}",
                    f"- 阶段/到期变化：{return_text}",
                    f"- 价格情景：{public.get('scenario_label') or '尚不可评估'}",
                    f"- 复盘结论：{public.get('review_conclusion')}",
                    "",
                ]
            )
        lines.append(
            "研究结果复盘只用于核验条件和反证，不代表买卖收益、策略胜率或荐股准确率。"
        )
        self.database.upsert_knowledge_document(
            document_id=document_id,
            owner_user_id=None,
            scope="common",
            title=f"{name}研究结果复盘",
            original_name=f"{symbol}-research-outcome.md",
            mime_type="text/markdown",
            content="\n".join(lines),
            source_key=source_key,
        )


def _parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc)


def _bar_close(bar: dict[str, Any] | None) -> float | None:
    if not bar:
        return None
    value = bar.get("adjusted_close")
    if not isinstance(value, (int, float)):
        value = bar.get("close")
    return float(value) if isinstance(value, (int, float)) else None


def _bar_high(bar: dict[str, Any]) -> float | None:
    adjusted = bar.get("adjusted_close")
    if isinstance(adjusted, (int, float)):
        return float(adjusted)
    value = bar.get("high") if isinstance(bar.get("high"), (int, float)) else bar.get("close")
    return float(value) if isinstance(value, (int, float)) else None


def _bar_low(bar: dict[str, Any]) -> float | None:
    adjusted = bar.get("adjusted_close")
    if isinstance(adjusted, (int, float)):
        return float(adjusted)
    value = bar.get("low") if isinstance(bar.get("low"), (int, float)) else bar.get("close")
    return float(value) if isinstance(value, (int, float)) else None


def _pct_change(value: float | None, base: float | None) -> float | None:
    if value is None or base is None or base == 0:
        return None
    return (float(value) / float(base) - 1.0) * 100.0


def _round(value: float | None, digits: int = 4) -> float | None:
    return round(float(value), digits) if isinstance(value, (int, float)) else None


def _evaluate_scenario(
    bars: list[dict[str, Any]], price_levels: dict[str, Any]
) -> tuple[str, str]:
    if not bars:
        return "not_started", "尚无后续交易日"
    closes = [_bar_close(row) for row in bars]
    closes = [value for value in closes if value is not None]
    if not closes:
        return "not_evaluable", "后续收盘价不可评估"
    upper = price_levels.get("recent_20d_high")
    lower = price_levels.get("recent_20d_low")
    ma20 = price_levels.get("ma20")
    has_upper = isinstance(upper, (int, float))
    has_lower = isinstance(lower, (int, float))
    upside = has_upper and any(value > float(upper) for value in closes)
    if upside and isinstance(ma20, (int, float)):
        upside = closes[-1] >= float(ma20)
    downside = has_lower and any(value < float(lower) for value in closes)
    if upside and downside:
        return "mixed_breaks", "上下边界均被触发"
    if downside:
        return "downside_triggered", "下行风险条件出现"
    if upside:
        return "upside_triggered", "向上条件出现"
    if has_upper and has_lower and all(
        float(lower) <= value <= float(upper) for value in closes
    ):
        return "range_held", "区间情景延续"
    return "no_clear_trigger", "尚无清晰情景触发"


def _available_conclusion(
    original_label: Any, scenario_result: str, horizon: int
) -> str:
    if scenario_result == "range_held" and "震荡" in str(original_label or ""):
        return f"T+{horizon}已到期：原区间观察假设暂获价格路径支持，仍需结合新事件复核。"
    if scenario_result in {"upside_triggered", "downside_triggered", "mixed_breaks"}:
        return f"T+{horizon}已到期：原条件展望的边界被触发，需要用最新证据重新计算。"
    return f"T+{horizon}已到期：尚无清晰条件触发，不能据此判断原研究正确或错误。"
