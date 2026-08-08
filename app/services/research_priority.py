from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any

from app.catalog import RESEARCH_TARGETS, SECURITY_NAME_ALIASES
from app.db import Database
from app.services.security_master import SecurityMasterService
from app.utils import utc_now


class ResearchPriorityService:
    """Rank review urgency, never investment attractiveness or expected return."""

    METHOD = "watchlist_research_urgency_v1"
    _LOW_SIGNAL_EVENT_RE = re.compile(
        r"(?:目标价|券商评级|评级观察|获推荐|强烈推荐|买入评级|卖出评级)",
        re.IGNORECASE,
    )

    def __init__(self, database: Database):
        self.database = database
        self.security_master = SecurityMasterService(database)

    def get_packet(self, user_id: str, persist: bool = True) -> dict[str, Any]:
        watchlist = self.database.list_watchlist(user_id)
        items = [self._score_item(item) for item in watchlist]
        items.sort(
            key=lambda item: (
                item["priority_score"],
                item.get("data_as_of") or "",
                item["symbol"],
            ),
            reverse=True,
        )
        packet = {
            "type": "research_priority",
            "generated_at": utc_now(),
            "method": self.METHOD,
            "items": items,
            "coverage": {
                "requested": len(watchlist),
                "available": sum(item["status"] == "available" for item in items),
                "missing_baseline": sum(
                    item["status"] == "baseline_missing" for item in items
                ),
            },
            "sorting": "按研究复核紧迫度排序，不按预期收益或投资吸引力排序。",
            "boundary": (
                "优先级只表示今天先复核哪份证据；不是买卖评级、收益排名、"
                "目标价、持仓建议或未来涨跌概率。"
            ),
        }
        if persist:
            fingerprint = self._fingerprint(packet)
            snapshot = self.database.save_research_priority_snapshot(
                user_id, fingerprint, packet
            )
            packet["snapshot_id"] = snapshot["id"]
            packet["snapshot_created_at"] = snapshot["created_at"]
            self._index_user_knowledge(user_id, packet)
        return packet

    def _score_item(self, watchlist_item: dict[str, Any]) -> dict[str, Any]:
        symbol = str(watchlist_item["symbol"])
        report = self.database.latest_research_report(symbol)
        change = self.database.latest_research_change_event(symbol)
        if report is None:
            return {
                "symbol": symbol,
                "name": self.security_master.display_name(
                    symbol, watchlist_item.get("name")
                ),
                "thesis": watchlist_item.get("thesis"),
                "status": "baseline_missing",
                "priority_score": 45,
                "priority_label": "优先建立基线",
                "components": [
                    {
                        "key": "baseline",
                        "label": "缺少长期研究基线",
                        "points": 45,
                        "evidence": "尚无服务器研究报告，无法比较后续证据变化。",
                    }
                ],
                "reasons": ["尚无服务器研究报告，先建立行情、事件、财务与风险基线。"],
                "next_review": {
                    "focus": "建立首份六模块研究基线",
                    "checks": ["行情结构", "公告新闻", "基本面现金流", "同行与反方风险"],
                },
                "data_as_of": None,
            }

        evidence = report.get("evidence") or {}
        display_name = self.security_master.display_name(
            symbol,
            RESEARCH_TARGETS.get(symbol, {}).get("name"),
            evidence.get("display_name"),
            watchlist_item.get("name"),
            report.get("name"),
        )
        metrics = evidence.get("metrics") or {}
        board = evidence.get("analysis_board") or {}
        fundamentals = evidence.get("fundamentals") or {}
        summary = fundamentals.get("summary") or {}
        latest_financial = summary.get("latest_report") or {}
        components: list[dict[str, Any]] = []

        def add(key: str, label: str, points: int, detail: str) -> None:
            if points <= 0:
                return
            components.append(
                {
                    "key": key,
                    "label": label,
                    "points": points,
                    "evidence": detail,
                }
            )

        severity = str((change or {}).get("severity") or "stable")
        if severity == "attention":
            add("evidence_change", "重要证据变化", 25, str(change.get("summary")))
        elif severity == "notice":
            add("evidence_change", "新增证据待复核", 15, str(change.get("summary")))

        one_day = metrics.get("return_1d_pct")
        if isinstance(one_day, (int, float)):
            absolute = abs(float(one_day))
            points = 20 if absolute >= 5 else 12 if absolute >= 3 else 6 if absolute >= 1.5 else 0
            add("price_move", "单日价格异动", points, f"最新单日变化 {one_day:.2f}%。")

        drawdown = metrics.get("max_drawdown_60d_pct")
        if isinstance(drawdown, (int, float)):
            points = 15 if drawdown <= -20 else 8 if drawdown <= -10 else 0
            add("drawdown", "回撤风险", points, f"60日最大回撤 {drawdown:.2f}%。")

        volatility = metrics.get("volatility_20d_annualized_pct")
        if isinstance(volatility, (int, float)):
            points = 12 if volatility >= 60 else 7 if volatility >= 35 else 0
            add("volatility", "波动放大", points, f"20日年化波动率 {volatility:.2f}%。")

        technical = str(metrics.get("technical_state") or "")
        if any(term in technical for term in ("转弱", "偏弱", "超跌")):
            add("technical", "技术结构转弱", 10, f"技术状态为“{technical}”。")
        elif "偏热" in technical:
            add("technical", "短期结构偏热", 8, f"技术状态为“{technical}”。")

        volume_ratio = metrics.get("volume_ratio_5_20")
        if isinstance(volume_ratio, (int, float)):
            points = 8 if volume_ratio >= 1.5 else 4 if volume_ratio >= 1.2 else 0
            add("volume", "成交量变化", points, f"5/20日量比 {volume_ratio:.2f}。")

        negative_financials = []
        for key, label in (
            ("revenue_yoy_pct", "营收同比"),
            ("net_profit_yoy_pct", "净利润同比"),
        ):
            value = latest_financial.get(key)
            if isinstance(value, (int, float)) and value < 0:
                negative_financials.append(f"{label}{value:.2f}%")
        if negative_financials:
            add(
                "fundamentals",
                "基本面反证",
                min(14, len(negative_financials) * 7),
                "、".join(negative_financials) + "。",
            )

        cashflow_ratio = summary.get("operating_cashflow_to_net_profit")
        if isinstance(cashflow_ratio, (int, float)) and cashflow_ratio < 0:
            add(
                "cashflow",
                "现金流质量待复核",
                8,
                f"经营现金流/净利润为 {cashflow_ratio:.2f}。",
            )

        financial_drivers = evidence.get("financial_drivers") or {}
        negative_drivers = [
            item
            for item in (
                financial_drivers.get("confirmed_mechanical_drivers") or []
            )
            if item.get("direction") == "negative"
        ]
        if negative_drivers:
            add(
                "financial_drivers",
                "利润科目负向机械影响",
                min(15, len(negative_drivers) * 3),
                "；".join(
                    str(item.get("statement") or item.get("label"))
                    for item in negative_drivers[:2]
                ),
            )
        driver_clues = financial_drivers.get("plausible_clues") or []
        if driver_clues:
            add(
                "working_capital",
                "营运资金与现金流线索",
                min(10, len(driver_clues) * 2),
                "；".join(
                    str(item.get("evidence") or item.get("label"))
                    for item in driver_clues[:2]
                ),
            )

        recent_event = self._latest_recent_event(evidence, symbol, str(display_name))
        if recent_event:
            add(
                "event",
                "近期公司事件",
                10,
                f"{recent_event.get('title')}（{recent_event.get('published_at') or '时间待确认'}）。",
            )

        ready_modules = int(board.get("ready_modules") or 0)
        total_modules = int(board.get("total_modules") or 6)
        if total_modules and ready_modules < 4:
            add(
                "coverage",
                "关键证据覆盖不足",
                10,
                f"当前六模块覆盖 {ready_modules}/{total_modules}。",
            )

        score = min(100, sum(item["points"] for item in components))
        label = "优先复核" if score >= 55 else "今日关注" if score >= 30 else "持续观察"
        components.sort(key=lambda item: item["points"], reverse=True)
        reasons = [item["evidence"] for item in components[:4]]
        if not reasons:
            reasons = ["最新已存证据未出现需要立即复核的显著变化。"]
        tracking_plan = board.get("tracking_plan") or []
        next_review = tracking_plan[0] if tracking_plan else None
        return {
            "symbol": symbol,
            "name": display_name,
            "thesis": watchlist_item.get("thesis"),
            "status": "available",
            "priority_score": score,
            "priority_label": label,
            "components": components,
            "reasons": reasons,
            "next_review": next_review,
            "data_as_of": report.get("market_timestamp") or report.get("generated_at"),
            "report_id": report.get("id"),
            "change_severity": severity,
        }

    @staticmethod
    def _latest_recent_event(
        evidence: dict[str, Any], symbol: str, display_name: str
    ) -> dict[str, Any] | None:
        information = evidence.get("a_share_information") or {}
        global_information = evidence.get("global_information") or {}
        fundamentals = evidence.get("fundamentals") or {}
        items = [
            *((item, False) for item in (information.get("announcements") or [])),
            *((item, True) for item in (information.get("news") or [])),
            *((item, True) for item in (global_information.get("news") or [])),
            *((item, False) for item in (fundamentals.get("regulatory_filings") or [])),
        ]
        subject_terms = {
            display_name.casefold(),
            symbol.casefold(),
            symbol.split(".", 1)[0].casefold(),
            *(
                alias.casefold()
                for alias, target in SECURITY_NAME_ALIASES.items()
                if target == symbol
            ),
        }
        subject_terms.discard("")
        now = datetime.now(timezone.utc)
        recent: list[tuple[datetime, dict[str, Any]]] = []
        for item, requires_subject in items:
            title = str(item.get("title") or "").casefold()
            if ResearchPriorityService._LOW_SIGNAL_EVENT_RE.search(title):
                continue
            if requires_subject and not any(term in title for term in subject_terms):
                continue
            raw = item.get("published_at") or item.get("filing_date")
            if not raw:
                continue
            try:
                timestamp = datetime.fromisoformat(str(raw))
                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=timezone.utc)
                else:
                    timestamp = timestamp.astimezone(timezone.utc)
            except (TypeError, ValueError):
                continue
            if 0 <= (now - timestamp).total_seconds() <= 3 * 86400:
                recent.append((timestamp, item))
        return max(recent, default=(None, None), key=lambda pair: pair[0])[1]

    @staticmethod
    def _fingerprint(packet: dict[str, Any]) -> str:
        stable = [
            {
                "symbol": item["symbol"],
                "score": item["priority_score"],
                "label": item["priority_label"],
                "components": [
                    (component["key"], component["points"], component["evidence"])
                    for component in item.get("components", [])
                ],
                "data_as_of": item.get("data_as_of"),
            }
            for item in packet.get("items", [])
        ]
        return hashlib.sha256(
            json.dumps(stable, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()

    def _index_user_knowledge(self, user_id: str, packet: dict[str, Any]) -> None:
        source_key = f"research-priority:{user_id}"
        document_id = "priority-" + hashlib.sha256(source_key.encode("utf-8")).hexdigest()[:24]
        lines = [
            "# 我的最新研究优先级",
            "",
            f"生成时间：{packet['generated_at']}",
            f"方法：{self.METHOD}",
            "",
        ]
        for item in packet.get("items", []):
            lines.extend(
                [
                    f"## {item['name']}（{item['symbol']}）",
                    f"- 研究优先级：{item['priority_label']}（{item['priority_score']}）",
                    f"- 证据时间：{item.get('data_as_of') or '待建立'}",
                    f"- 主要原因：{'；'.join(item.get('reasons') or [])}",
                    "",
                ]
            )
        lines.append(packet["boundary"])
        self.database.upsert_knowledge_document(
            document_id=document_id,
            owner_user_id=user_id,
            scope="user",
            title="我的最新研究优先级",
            original_name="research-priority.md",
            mime_type="text/markdown",
            content="\n".join(lines),
            source_key=source_key,
        )
