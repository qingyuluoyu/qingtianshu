from __future__ import annotations

import hashlib
import json
from typing import Any

from app.catalog import RESEARCH_TARGETS, normalize_symbol
from app.db import Database
from app.providers.shareholders import AShareShareholderProvider
from app.utils import utc_now


class ShareholderStructureAnalysisService:
    METHOD = "deterministic_shareholder_structure_v1"

    def __init__(
        self, database: Database, provider: AShareShareholderProvider
    ) -> None:
        self.database = database
        self.provider = provider

    def refresh_symbol(self, symbol: str) -> dict[str, Any]:
        canonical = normalize_symbol(symbol)
        fetched = self.provider.fetch(canonical)
        packet = self._build_packet(fetched)
        fingerprint = _fingerprint(packet)
        saved = self.database.save_shareholder_structure_snapshot(
            packet, fingerprint
        )
        packet["snapshot_id"] = saved["id"]
        packet["snapshot_created_at"] = saved["created_at"]
        self._index_common_knowledge(packet)
        return packet

    def refresh_symbols(self, symbols: list[str]) -> dict[str, Any]:
        canonical_symbols = sorted(
            {
                normalize_symbol(symbol)
                for symbol in symbols
                if normalize_symbol(symbol).endswith((".SS", ".SZ"))
            }
        )
        results = []
        for symbol in canonical_symbols:
            try:
                packet = self.refresh_symbol(symbol)
                results.append(
                    {
                        "symbol": symbol,
                        "status": "ok",
                        "analysis_status": packet.get("status"),
                        "holder_count_as_of": packet.get("holder_count_as_of"),
                        "top10_report_date": packet.get("top10_report_date"),
                    }
                )
            except Exception as exc:
                results.append(
                    {
                        "symbol": symbol,
                        "status": "failed",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
        return {
            "requested": len(canonical_symbols),
            "completed": sum(item["status"] == "ok" for item in results),
            "results": results,
        }

    def get_packet(
        self, symbol: str, *, refresh_if_missing: bool = True
    ) -> dict[str, Any]:
        canonical = normalize_symbol(symbol)
        if not canonical.endswith((".SS", ".SZ")):
            raise ValueError("股东结构分析当前只支持 A 股证券")
        snapshot = self.database.latest_shareholder_structure_snapshot(canonical)
        if snapshot is not None:
            return dict(snapshot.get("payload") or {})
        if refresh_if_missing:
            return self.refresh_symbol(canonical)
        return self._unavailable(canonical)

    def _build_packet(self, fetched: dict[str, Any]) -> dict[str, Any]:
        history = list(fetched.get("holder_history") or [])
        latest = history[0]
        change_pct = latest.get("holder_count_change_pct")
        if isinstance(change_pct, (int, float)) and change_pct < 0:
            signal = "concentration_clue"
            signal_label = "持股集中度上升线索"
            direction_statement = (
                f"股东户数较上次下降 {_pct(abs(change_pct))}，"
                "只能说明持有人数量减少和持股集中度线索，不能证明机构吸筹。"
            )
        elif isinstance(change_pct, (int, float)) and change_pct > 0:
            signal = "dispersion_clue"
            signal_label = "持有人分散线索"
            direction_statement = (
                f"股东户数较上次上升 {_pct(change_pct)}，"
                "只能说明持有人数量增加和分散线索，不能直接预测股价下跌。"
            )
        else:
            signal = "stable_or_unknown"
            signal_label = "户数变化有限或待确认"
            direction_statement = "最新股东户数变化有限，暂不形成集中或分散方向判断。"

        streak_direction = None
        streak_count = 0
        for item in history:
            value = item.get("holder_count_change_pct")
            if not isinstance(value, (int, float)) or value == 0:
                break
            direction = "decrease" if value < 0 else "increase"
            if streak_direction is None:
                streak_direction = direction
            if direction != streak_direction:
                break
            streak_count += 1
        if streak_count >= 2 and streak_direction == "decrease":
            recent_pattern = f"最近 {streak_count} 次披露的股东户数连续下降。"
        elif streak_count >= 2 and streak_direction == "increase":
            recent_pattern = f"最近 {streak_count} 次披露的股东户数连续上升。"
        else:
            recent_pattern = "最近披露尚未形成至少两次同方向的连续变化。"

        top_holders = list(fetched.get("top_holders") or [])
        ratios = [
            item.get("holding_ratio_pct")
            for item in top_holders
            if isinstance(item.get("holding_ratio_pct"), (int, float))
        ]
        top10_ratio = round(sum(ratios), 6) if ratios else None
        top3_ratio = round(sum(ratios[:3]), 6) if ratios else None
        top_statement = (
            f"最近可用十大股东报告期为 {fetched.get('top10_report_date')}，"
            f"前十名合计持股 {_pct(top10_ratio)}，前三名合计 {_pct(top3_ratio)}。"
            if top10_ratio is not None
            else "尚未取得可核验的十大股东报告期数据。"
        )
        name = (
            fetched.get("name")
            or RESEARCH_TARGETS.get(fetched["symbol"], {}).get("name")
            or fetched["symbol"]
        )
        summary = (
            f"{name}最新股东户数披露截至 {latest.get('as_of')}，"
            f"股东户数 {_integer_text(latest.get('holder_count'))}，"
            f"较上次变化 {_signed_pct(change_pct)}。{top_statement}"
        )
        special_name_notes = []
        if any("香港中央结算代理人有限公司" in item.get("name", "") for item in top_holders):
            special_name_notes.append(
                "香港中央结算代理人有限公司通常对应 H 股登记代理口径，不能自动等同北向资金。"
            )
        if any(item.get("name") == "香港中央结算有限公司" for item in top_holders):
            special_name_notes.append(
                "香港中央结算有限公司的报告期持股是存量披露，不能直接写成当日北向资金流入或流出。"
            )

        return {
            "type": "shareholder_structure",
            "symbol": fetched["symbol"],
            "name": name,
            "status": "available",
            "generated_at": utc_now(),
            "method": self.METHOD,
            "holder_count_as_of": latest.get("as_of"),
            "announced_at": latest.get("announced_at"),
            "holder_count": latest.get("holder_count"),
            "previous_holder_count": latest.get("previous_holder_count"),
            "holder_count_change": latest.get("holder_count_change"),
            "holder_count_change_pct": change_pct,
            "average_holding": latest.get("average_holding"),
            "average_market_cap": latest.get("average_market_cap"),
            "interval_price_change_pct": latest.get("interval_price_change_pct"),
            "previous_holder_count_as_of": latest.get("previous_as_of"),
            "holder_count_signal": signal,
            "holder_count_signal_label": signal_label,
            "holder_count_statement": direction_statement,
            "recent_pattern": recent_pattern,
            "holder_count_streak_direction": streak_direction,
            "holder_count_streak_count": streak_count,
            "holder_history": history[:12],
            "top10_report_date": fetched.get("top10_report_date"),
            "top10_ratio_pct": top10_ratio,
            "top3_ratio_pct": top3_ratio,
            "top10_historical_comparison_available": False,
            "top_holders": top_holders,
            "top_holders_statement": top_statement,
            "special_name_notes": special_name_notes,
            "summary": summary,
            "sources": fetched.get("sources") or [],
            "latest_fetched_at": fetched.get("fetched_at"),
            "coverage": fetched.get("coverage") or {},
            "review_points": [
                "把下一次股东户数披露与本次方向比较，确认集中或分散线索是否持续。",
                "等待下一份定期报告更新十大股东，避免把报告期存量当成当前实时持仓。",
                "如需判断机构变化，应取得同一股东跨报告期的可比持股数量和身份披露，不能只凭名称猜测。",
            ],
            "boundary": (
                "股东户数下降仅是持股集中度线索，不等于机构吸筹或利好；"
                "股东户数上升仅是持有人分散线索，不直接预测下跌。"
                "十大股东比例是报告期存量，不是当前实时持仓；"
                "不根据股东名称自动判断机构、国家背景或资金流向。"
            ),
        }

    def _index_common_knowledge(self, packet: dict[str, Any]) -> None:
        source_key = f"shareholder-structure:{packet['symbol']}"
        document_id = "shareholders-" + hashlib.sha256(
            source_key.encode("utf-8")
        ).hexdigest()[:24]
        history_lines = "\n".join(
            f"- {item.get('as_of')}：股东户数 {_integer_text(item.get('holder_count'))}，"
            f"较上次 {_signed_pct(item.get('holder_count_change_pct'))}，"
            f"区间股价变化 {_signed_pct(item.get('interval_price_change_pct'))}"
            for item in (packet.get("holder_history") or [])[:8]
        )
        holder_lines = "\n".join(
            f"- 第{item.get('rank')}名 {item.get('name')}：持股"
            f" {_integer_text(item.get('holding'))}，占总股本"
            f" {_pct(item.get('holding_ratio_pct'))}，股份类型"
            f" {item.get('share_type') or '未披露'}"
            for item in packet.get("top_holders") or []
        ) or "- 尚未取得可核验的十大股东数据。"
        notes = "\n".join(
            f"- {item}" for item in packet.get("special_name_notes") or []
        ) or "- 当前无额外名称口径提示。"
        content = (
            f"# {packet['name']}股东结构与股东户数\n\n"
            f"{packet.get('summary')}\n\n"
            f"## 最新解释\n\n- {packet.get('holder_count_statement')}\n"
            f"- {packet.get('recent_pattern')}\n"
            f"- {packet.get('top_holders_statement')}\n\n"
            f"## 股东户数历史\n\n{history_lines}\n\n"
            f"## 十大股东\n\n报告期：{packet.get('top10_report_date') or '待取得'}\n\n"
            f"{holder_lines}\n\n"
            f"## 特殊名称口径\n\n{notes}\n\n"
            f"## 下一步复核\n\n"
            + "\n".join(f"- {item}" for item in packet.get("review_points") or [])
            + f"\n\n## 证据边界\n\n{packet.get('boundary')}\n"
        )
        self.database.upsert_knowledge_document(
            document_id=document_id,
            owner_user_id=None,
            scope="common",
            title=f"{packet['name']}股东结构与股东户数",
            original_name=f"{packet['symbol']}-shareholder-structure.md",
            mime_type="text/markdown",
            content=content,
            source_key=source_key,
        )

    def _unavailable(self, symbol: str) -> dict[str, Any]:
        return {
            "type": "shareholder_structure",
            "symbol": symbol,
            "name": RESEARCH_TARGETS.get(symbol, {}).get("name") or symbol,
            "status": "insufficient",
            "generated_at": utc_now(),
            "method": self.METHOD,
            "summary": "尚未取得可核验的股东户数和十大股东数据。",
            "holder_history": [],
            "top_holders": [],
            "review_points": ["先取得公司最新股东户数披露和最近一期十大股东。"],
            "boundary": "缺少披露时，不根据公司属性或市场传闻补写股东结构。",
        }


def _fingerprint(packet: dict[str, Any]) -> str:
    stable = {
        "symbol": packet.get("symbol"),
        "holder_count_as_of": packet.get("holder_count_as_of"),
        "holder_count": packet.get("holder_count"),
        "holder_count_change_pct": packet.get("holder_count_change_pct"),
        "holder_history": packet.get("holder_history") or [],
        "top10_report_date": packet.get("top10_report_date"),
        "top_holders": packet.get("top_holders") or [],
        "method": packet.get("method"),
    }
    return hashlib.sha256(
        json.dumps(stable, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _pct(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "待确认"
    return f"{value:.3f}".rstrip("0").rstrip(".") + "%"


def _signed_pct(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "待确认"
    return f"{value:+.3f}".rstrip("0").rstrip(".") + "%"


def _integer_text(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "待确认"
    return f"{int(value):,}"
