from __future__ import annotations

from collections import Counter
import re
from typing import Any
from urllib.parse import quote

from app.catalog import RESEARCH_TARGETS, SECURITY_NAME_ALIASES, normalize_symbol
from app.db import Database


class GlobalSearchService:
    """Search public market reference data and one user's private research assets."""

    CONTRACT_VERSION = "global_search_v1"
    GROUP_LIMITS = {
        "stocks": 8,
        "industries": 5,
        "workspaces": 6,
        "conversations": 6,
        "reviews": 6,
    }

    def __init__(self, database: Database, trade_workflow: Any):
        self.database = database
        self.trade_workflow = trade_workflow

    def search(self, user_id: str, query: str, *, limit: int = 8) -> dict[str, Any]:
        raw_query = str(query or "").strip()
        normalized_query = self._fold(raw_query)
        safe_limit = max(1, min(int(limit), 20))
        if not normalized_query:
            return self._packet(raw_query, {})

        universe = self._universe_items()
        groups = {
            "stocks": self._search_stocks(universe, raw_query, safe_limit),
            "industries": self._search_industries(
                universe, raw_query, min(safe_limit, self.GROUP_LIMITS["industries"])
            ),
            "workspaces": self._search_workspaces(user_id, raw_query, safe_limit),
            "conversations": self._search_conversations(
                user_id, raw_query, safe_limit
            ),
            "reviews": self._search_reviews(user_id, raw_query, safe_limit),
        }
        return self._packet(raw_query, groups)

    def _packet(
        self, query: str, groups: dict[str, list[dict[str, Any]]]
    ) -> dict[str, Any]:
        ordered = [
            ("stocks", "股票"),
            ("industries", "行业"),
            ("workspaces", "我的研究"),
            ("conversations", "历史对话"),
            ("reviews", "交易复盘"),
        ]
        public_groups = [
            {"key": key, "label": label, "items": groups.get(key, [])}
            for key, label in ordered
            if groups.get(key)
        ]
        return {
            "contract_version": self.CONTRACT_VERSION,
            "query": query,
            "groups": public_groups,
            "total": sum(len(group["items"]) for group in public_groups),
            "boundary": "股票和行业来自本地稳定市场快照；研究、对话和复盘仅搜索当前用户空间。",
        }

    def _universe_items(self) -> list[dict[str, Any]]:
        snapshot = self.database.latest_tushare_dataset_snapshot(
            "a_share_universe", "all"
        )
        items = [
            dict(item)
            for item in ((snapshot or {}).get("payload") or {}).get("items", [])
            if isinstance(item, dict)
        ]
        by_symbol: dict[str, dict[str, Any]] = {}
        for item in items:
            try:
                symbol = normalize_symbol(
                    str(item.get("symbol") or item.get("ts_code") or "")
                )
            except ValueError:
                continue
            by_symbol[symbol] = {**item, "symbol": symbol}

        for symbol, target in RESEARCH_TARGETS.items():
            canonical = normalize_symbol(symbol)
            by_symbol.setdefault(
                canonical,
                {
                    "symbol": canonical,
                    "name": target.get("name") or canonical,
                    "market": target.get("market"),
                    "industry": None,
                    "exchange": None,
                },
            )
        for alias, symbol in SECURITY_NAME_ALIASES.items():
            canonical = normalize_symbol(symbol)
            item = by_symbol.setdefault(
                canonical,
                {
                    "symbol": canonical,
                    "name": alias,
                    "market": None,
                    "industry": None,
                    "exchange": None,
                },
            )
            aliases = set(item.get("aliases") or [])
            aliases.add(alias)
            item["aliases"] = sorted(aliases)
        return list(by_symbol.values())

    def _search_stocks(
        self, items: list[dict[str, Any]], query: str, limit: int
    ) -> list[dict[str, Any]]:
        matches: list[tuple[int, str, dict[str, Any]]] = []
        for item in items:
            symbol = str(item.get("symbol") or "")
            name = str(item.get("name") or symbol)
            score = self._score(
                query,
                [symbol, symbol.split(".", 1)[0], name, *(item.get("aliases") or [])],
            )
            if score is None:
                continue
            matches.append(
                (
                    score,
                    symbol,
                    {
                        "type": "stock",
                        "id": symbol,
                        "title": name,
                        "subtitle": " · ".join(
                            value
                            for value in (
                                symbol,
                                str(item.get("industry") or ""),
                                str(item.get("market") or ""),
                            )
                            if value
                        ),
                        "symbol": symbol,
                        "industry": item.get("industry"),
                        "url": f"/stocks/{quote(symbol, safe='')}",
                    },
                )
            )
        matches.sort(key=lambda row: (row[0], row[1]))
        return [row[2] for row in matches[: min(limit, self.GROUP_LIMITS["stocks"])]]

    def _search_industries(
        self, items: list[dict[str, Any]], query: str, limit: int
    ) -> list[dict[str, Any]]:
        counts = Counter(
            str(item.get("industry") or "").strip()
            for item in items
            if str(item.get("industry") or "").strip()
        )
        matches: list[tuple[int, str, dict[str, Any]]] = []
        for industry, count in counts.items():
            score = self._score(query, [industry])
            if score is None:
                continue
            examples = [
                str(item.get("name") or item.get("symbol") or "")
                for item in items
                if str(item.get("industry") or "").strip() == industry
            ][:3]
            question = f"分析{industry}板块的当前行情、核心驱动、反方证据和失效条件"
            matches.append(
                (
                    score,
                    industry,
                    {
                        "type": "industry",
                        "id": industry,
                        "title": industry,
                        "subtitle": f"{count} 只股票" + (
                            f" · {'、'.join(examples)}" if examples else ""
                        ),
                        "question": question,
                        "url": f"/research/new?question={quote(question)}",
                    },
                )
            )
        matches.sort(key=lambda row: (row[0], -counts[row[1]], row[1]))
        return [row[2] for row in matches[:limit]]

    def _search_workspaces(
        self, user_id: str, query: str, limit: int
    ) -> list[dict[str, Any]]:
        matches: list[tuple[int, str, dict[str, Any]]] = []
        for item in self.database.list_stock_workspaces(user_id):
            symbol = str(item.get("symbol") or "")
            name = str(item.get("name") or symbol)
            score = self._score(
                query,
                [symbol, symbol.split(".", 1)[0], name, *(item.get("attention_tags") or [])],
            )
            if score is None:
                continue
            matches.append(
                (
                    score,
                    str(item.get("updated_at") or ""),
                    {
                        "type": "workspace",
                        "id": str(item.get("id") or symbol),
                        "title": name,
                        "subtitle": " · ".join(
                            value
                            for value in (
                                symbol,
                                self._relation_label(item.get("relation_type")),
                                self._priority_label(item.get("priority")),
                            )
                            if value
                        ),
                        "symbol": symbol,
                        "updated_at": item.get("updated_at"),
                        "url": f"/stocks/{quote(symbol, safe='')}",
                    },
                )
            )
        matches.sort(key=lambda row: row[1], reverse=True)
        matches.sort(key=lambda row: row[0])
        return [row[2] for row in matches[: min(limit, self.GROUP_LIMITS["workspaces"])]]

    def _search_conversations(
        self, user_id: str, query: str, limit: int
    ) -> list[dict[str, Any]]:
        matches: list[tuple[int, str, dict[str, Any]]] = []
        for item in self.database.list_conversations(user_id, limit=200):
            score = self._score(
                query,
                [item.get("title"), item.get("last_message_preview")],
            )
            if score is None:
                continue
            conversation_id = str(item.get("id") or "")
            matches.append(
                (
                    score,
                    str(item.get("updated_at") or ""),
                    {
                        "type": "conversation",
                        "id": conversation_id,
                        "title": item.get("title") or "未命名研究对话",
                        "subtitle": item.get("last_message_preview")
                        or "继续这项历史研究",
                        "updated_at": item.get("updated_at"),
                        "url": f"/research/{quote(conversation_id, safe='')}",
                    },
                )
            )
        matches.sort(key=lambda row: row[1], reverse=True)
        matches.sort(key=lambda row: row[0])
        return [row[2] for row in matches[: min(limit, self.GROUP_LIMITS["conversations"])]]

    def _search_reviews(
        self, user_id: str, query: str, limit: int
    ) -> list[dict[str, Any]]:
        packet = self.trade_workflow.list_user_trade_reviews(
            user_id, query=query, limit=min(limit, self.GROUP_LIMITS["reviews"])
        )
        rows = []
        for item in packet.get("items") or []:
            review_id = str(item.get("id") or "")
            operation = item.get("operation") or {}
            version = item.get("current_version") or {}
            rows.append(
                {
                    "type": "review",
                    "id": review_id,
                    "title": f"{item.get('name') or item.get('symbol')} · 交易复盘",
                    "subtitle": operation.get("reason_text")
                    or version.get("logic_result")
                    or "查看价格结果、逻辑结果与改进项",
                    "symbol": item.get("symbol"),
                    "status": item.get("status"),
                    "updated_at": item.get("updated_at"),
                    "url": f"/reviews?tab=trades&review={quote(review_id, safe='')}",
                }
            )
        return rows

    @classmethod
    def _score(cls, query: str, values: list[Any]) -> int | None:
        needle = cls._fold(query)
        scores: list[int] = []
        for value in values:
            candidate = cls._fold(value)
            if not candidate:
                continue
            if candidate == needle:
                scores.append(0)
            elif candidate.startswith(needle):
                scores.append(10 + min(len(candidate) - len(needle), 20))
            elif needle in candidate:
                scores.append(40 + candidate.index(needle))
        return min(scores) if scores else None

    @staticmethod
    def _fold(value: Any) -> str:
        return re.sub(r"[\s.\-_/]+", "", str(value or "").strip().casefold())

    @staticmethod
    def _relation_label(value: Any) -> str:
        return {"watching": "关注中", "holding": "持有中", "ended": "已结束"}.get(
            str(value or ""), ""
        )

    @staticmethod
    def _priority_label(value: Any) -> str:
        return {"high": "高优先级", "normal": "普通优先级", "low": "低优先级"}.get(
            str(value or ""), ""
        )
