from __future__ import annotations

import hashlib
import json
from typing import Any

from app.catalog import RESEARCH_TARGETS
from app.db import Database
from app.services.research_priority import ResearchPriorityService
from app.services.security_master import SecurityMasterService
from app.utils import utc_now


_ACTION_STATUS_RANK = {"triggered": 3, "pending_data": 2, "watching": 1}
_SEVERITY_RANK = {"high": 3, "medium": 2, "low": 1}


class ResearchActionService:
    """Build a persistent research worklist, never a trading alert list."""

    METHOD = "deterministic_research_action_board_v1"

    def __init__(
        self,
        database: Database,
        research_priority: ResearchPriorityService | None = None,
    ):
        self.database = database
        self.research_priority = research_priority or ResearchPriorityService(database)
        self.security_master = SecurityMasterService(database)

    def get_packet(self, user_id: str, persist: bool = True) -> dict[str, Any]:
        watchlist = self.database.list_watchlist(user_id)
        priority_packet = self.research_priority.get_packet(user_id, persist=False)
        priority_by_symbol = {
            str(item["symbol"]): item for item in priority_packet.get("items", [])
        }
        items = [
            self._build_item(item, priority_by_symbol.get(str(item["symbol"]), {}))
            for item in watchlist
        ]
        items.sort(
            key=lambda item: (
                self._research_status_rank(item["research_status"]),
                item.get("priority_score") or 0,
                item["symbol"],
            ),
            reverse=True,
        )
        all_actions = [action for item in items for action in item.get("actions", [])]
        packet = {
            "type": "research_actions",
            "generated_at": utc_now(),
            "method": self.METHOD,
            "items": items,
            "summary": {
                "symbols": len(items),
                "triggered": sum(
                    action["status"] == "triggered" for action in all_actions
                ),
                "pending_data": sum(
                    action["status"] == "pending_data" for action in all_actions
                ),
                "watching": sum(
                    action["status"] == "watching" for action in all_actions
                ),
                "priority_research": sum(
                    item["research_status"] in {"priority_research", "risk_review"}
                    for item in items
                ),
            },
            "status_legend": {
                "triggered": "已有确定性证据达到复核条件",
                "pending_data": "当前资料仍缺少完成判断所需的证据",
                "watching": "条件尚未触发，继续按已定义变量观察",
            },
            "boundary": (
                "研究行动只决定下一步核验哪份证据；不是价格提醒、买卖信号、"
                "仓位建议、目标价或未来涨跌预测。"
            ),
        }
        if persist:
            snapshot = self.database.save_research_action_snapshot(
                user_id, self._fingerprint(packet), packet
            )
            packet["snapshot_id"] = snapshot["id"]
            packet["snapshot_created_at"] = snapshot["created_at"]
            self._index_user_knowledge(user_id, packet)
        return packet

    def _build_item(
        self,
        watchlist_item: dict[str, Any],
        priority_item: dict[str, Any],
    ) -> dict[str, Any]:
        symbol = str(watchlist_item["symbol"])
        report = self.database.latest_research_report(symbol)
        name = self.security_master.display_name(
            symbol,
            RESEARCH_TARGETS.get(symbol, {}).get("name"),
            priority_item.get("name"),
            watchlist_item.get("name"),
            (report or {}).get("name"),
        )
        if report is None:
            action = self._action(
                symbol,
                "baseline",
                category="coverage",
                title="建立首份长期研究基线",
                status="triggered",
                severity="high",
                condition="服务器尚无该标的的研究报告",
                current_evidence="无法比较行情、事件、财务和风险证据的后续变化。",
                next_step="生成并保存首份七模块研究报告，再建立观察条件。",
            )
            return {
                "symbol": symbol,
                "name": name,
                "thesis": watchlist_item.get("thesis"),
                "research_status": "priority_research",
                "research_status_label": "优先建立基线",
                "priority_score": priority_item.get("priority_score", 45),
                "data_as_of": None,
                "latest_report_id": None,
                "headline": "缺少长期研究基线，需要先完成证据建档。",
                "actions": [action],
            }

        evidence = report.get("evidence") or {}
        metrics = evidence.get("metrics") or {}
        board = evidence.get("analysis_board") or {}
        readiness = evidence.get("evidence_readiness") or board.get("readiness") or {}
        change = self.database.latest_research_change_event(symbol)
        data_as_of = report.get("market_timestamp") or report.get("generated_at")
        actions: list[dict[str, Any]] = []

        if change and change.get("event_type") == "evidence_change":
            severity = str(change.get("severity") or "notice")
            if severity in {"attention", "notice"}:
                payload = change.get("payload") or {}
                actions.append(
                    self._action(
                        symbol,
                        "evidence_change",
                        category="new_evidence",
                        title="复核最新证据变化",
                        status="triggered",
                        severity="high" if severity == "attention" else "medium",
                        condition="连续研究报告出现新的价格、事件或基本面证据",
                        current_evidence=str(change.get("summary") or "发现新证据。"),
                        next_step="打开最新研究报告，逐项核对变化是否影响原关注理由。",
                        checks=[
                            str(item.get("detail") or item.get("title"))
                            for item in (
                                (payload.get("changes") or [])
                                + (payload.get("new_evidence") or [])
                            )[:3]
                            if item.get("detail") or item.get("title")
                        ],
                    )
                )

        event_timeline = evidence.get("event_timeline") or {}
        risk_event = next(iter(event_timeline.get("risk_events") or []), None)
        if risk_event:
            official = risk_event.get("evidence_level") in {
                "official_disclosure",
                "regulatory_filing",
            }
            actions.append(
                self._action(
                    symbol,
                    "event_risk_review",
                    category="new_evidence",
                    title="阅读最新风险事件原文",
                    status="triggered" if official else "pending_data",
                    severity="high" if official else "medium",
                    condition="事件脉络出现需优先复核的事件",
                    current_evidence=(
                        f"{risk_event.get('event_date') or '日期待确认'}｜"
                        f"{risk_event.get('evidence_label')}｜"
                        f"{risk_event.get('title')}"
                    ),
                    next_step=(
                        "阅读官方原文，再与用户关注理由、财务和价格证据交叉核验。"
                        if official
                        else "寻找公司公告或监管文件进行确认，不把媒体标题写成已证实风险。"
                    ),
                )
            )

        drawdown = self._number(metrics.get("max_drawdown_60d_pct"))
        if drawdown is not None:
            actions.append(
                self._action(
                    symbol,
                    "drawdown_review",
                    category="risk",
                    title="复核回撤是否破坏原假设",
                    status="triggered" if drawdown <= -10 else "watching",
                    severity="high" if drawdown <= -20 else "medium",
                    condition="60日最大回撤达到 -10% 或更深",
                    current_evidence=f"当前60日最大回撤 {drawdown:.2f}%。",
                    next_step=(
                        "把回撤与公告、财务和行业证据交叉核验，不把价格下跌自动解释为基本面恶化。"
                    ),
                )
            )

        volatility = self._number(metrics.get("volatility_20d_annualized_pct"))
        if volatility is not None:
            actions.append(
                self._action(
                    symbol,
                    "volatility_review",
                    category="risk",
                    title="检查波动是否显著放大",
                    status="triggered" if volatility >= 35 else "watching",
                    severity="medium",
                    condition="20日年化波动率达到 35% 或更高",
                    current_evidence=f"当前20日年化波动率 {volatility:.2f}%。",
                    next_step="结合ATR、成交量和最新事件判断波动来自单日扰动还是持续结构变化。",
                )
            )

        latest_close = self._number(metrics.get("latest_close"))
        ma20 = self._number(metrics.get("ma20"))
        if latest_close is not None and ma20 is not None:
            below = latest_close < ma20
            actions.append(
                self._action(
                    symbol,
                    "ma20_structure",
                    category="price_structure",
                    title="确认收盘与20日均线的关系",
                    status="triggered" if below else "watching",
                    severity="medium" if below else "low",
                    condition="收盘位于MA20下方时复核中期结构；重新站上后继续验证持续性",
                    current_evidence=(
                        f"最新价 {latest_close:.2f}，MA20 {ma20:.2f}，"
                        f"当前{'位于下方' if below else '位于上方'}。"
                    ),
                    next_step="同时查看5日、20日收益和MACD，避免用单一均线生成结论。",
                )
            )

        volume_ratio = self._number(metrics.get("volume_ratio_5_20"))
        if volume_ratio is not None:
            actions.append(
                self._action(
                    symbol,
                    "volume_change",
                    category="price_structure",
                    title="检查量能是否出现异常变化",
                    status="triggered" if volume_ratio >= 1.5 else "watching",
                    severity="medium" if volume_ratio >= 1.5 else "low",
                    condition="5/20日量比达到 1.5 或更高",
                    current_evidence=f"当前5/20日量比 {volume_ratio:.2f}。",
                    next_step="把量能与涨跌方向、波动率和公司事件交叉核验，不把放量等同于资金动机。",
                )
            )

        missing_core = list(readiness.get("missing_core_modules") or [])
        optional_gaps = list(readiness.get("optional_gaps") or [])
        if missing_core:
            actions.append(
                self._action(
                    symbol,
                    "core_evidence_gap",
                    category="coverage",
                    title="补齐核心研究证据",
                    status="pending_data",
                    severity="high",
                    condition="七模块核心证据存在缺口",
                    current_evidence="缺少：" + "、".join(map(str, missing_core)),
                    next_step="优先取得缺失模块的确定性数据，再让 Agent 综合解释。",
                )
            )
        if optional_gaps:
            actions.append(
                self._action(
                    symbol,
                    "optional_evidence_gap",
                    category="coverage",
                    title="补充可提高判断质量的资料",
                    status="pending_data",
                    severity="low",
                    condition="核心回答可用，但仍有重要扩展维度未接入",
                    current_evidence="待补充：" + "、".join(map(str, optional_gaps[:3])),
                    next_step="将新增的一手披露或用户资料保存进资料库，供后续对话长期复用。",
                )
            )

        limits = list(
            ((evidence.get("business_structure") or {}).get("coverage_limits") or [])
        )
        if limits:
            actions.append(
                self._action(
                    symbol,
                    "business_evidence_gap",
                    category="coverage",
                    title="追踪主营结构仍待补证的维度",
                    status="pending_data",
                    severity="medium",
                    condition="现有主营收入结构不能直接回答订单、客户或政策影响",
                    current_evidence="；".join(
                        str(item.get("label") or item.get("boundary"))
                        for item in limits[:3]
                    ),
                    next_step="；".join(
                        str(item.get("next_evidence")).rstrip("。；")
                        for item in limits[:2]
                        if item.get("next_evidence")
                    ) + "。",
                )
            )

        tracking_plan = list(board.get("tracking_plan") or [])
        if tracking_plan:
            next_review = tracking_plan[0]
            actions.append(
                self._action(
                    symbol,
                    "scheduled_review",
                    category="scheduled_review",
                    title=str(next_review.get("focus") or "执行下一次研究复核"),
                    status="watching",
                    severity="low",
                    condition=(
                        f"按 T+{next_review.get('horizon_sessions') or 3} 交易日周期复核"
                    ),
                    current_evidence="已建立可重复执行的观察清单。",
                    next_step="逐项核验观察条件，并把新的事实写入下一份研究快照。",
                    checks=[str(item) for item in (next_review.get("checks") or [])[:4]],
                )
            )

        if not watchlist_item.get("thesis"):
            actions.append(
                self._action(
                    symbol,
                    "missing_thesis",
                    category="user_context",
                    title="补充关注理由",
                    status="pending_data",
                    severity="medium",
                    condition="自选股缺少用户关注理由",
                    current_evidence="当前无法判断哪些新证据真正改变了用户原假设。",
                    next_step="写下关注业务、风险和最希望验证的问题。",
                )
            )

        actions.sort(
            key=lambda item: (
                _ACTION_STATUS_RANK[item["status"]],
                _SEVERITY_RANK[item["severity"]],
                item["key"],
            ),
            reverse=True,
        )
        triggered = sum(item["status"] == "triggered" for item in actions)
        pending = sum(item["status"] == "pending_data" for item in actions)
        watching = sum(item["status"] == "watching" for item in actions)
        high_triggered = any(
            item["status"] == "triggered" and item["severity"] == "high"
            for item in actions
        )
        priority_score = int(priority_item.get("priority_score") or 0)
        if high_triggered:
            research_status = "risk_review"
            research_label = "风险复核"
        elif triggered or priority_score >= 55:
            research_status = "priority_research"
            research_label = "优先研究"
        elif pending:
            research_status = "pending_review"
            research_label = "待补证"
        else:
            research_status = "observe"
            research_label = "持续观察"
        return {
            "symbol": symbol,
            "name": name,
            "thesis": watchlist_item.get("thesis"),
            "research_status": research_status,
            "research_status_label": research_label,
            "priority_score": priority_score,
            "priority_label": priority_item.get("priority_label"),
            "data_as_of": data_as_of,
            "latest_report_id": report.get("id"),
            "latest_report_at": report.get("generated_at"),
            "headline": f"{triggered}项需要复核 · {pending}项待补证 · {watching}项继续观察",
            "actions": actions[:8],
        }

    @staticmethod
    def _action(
        symbol: str,
        key: str,
        *,
        category: str,
        title: str,
        status: str,
        severity: str,
        condition: str,
        current_evidence: str,
        next_step: str,
        checks: list[str] | None = None,
    ) -> dict[str, Any]:
        identity = hashlib.sha256(
            f"{symbol}|{key}|{condition}".encode("utf-8")
        ).hexdigest()[:20]
        return {
            "id": identity,
            "key": key,
            "category": category,
            "title": title,
            "status": status,
            "severity": severity,
            "condition": condition,
            "current_evidence": current_evidence,
            "next_step": next_step,
            "checks": checks or [],
        }

    @staticmethod
    def _number(value: Any) -> float | None:
        if isinstance(value, (int, float)):
            return float(value)
        return None

    @staticmethod
    def _research_status_rank(status: str) -> int:
        return {
            "risk_review": 4,
            "priority_research": 3,
            "pending_review": 2,
            "observe": 1,
        }.get(status, 0)

    @staticmethod
    def _fingerprint(packet: dict[str, Any]) -> str:
        stable = [
            {
                "symbol": item["symbol"],
                "research_status": item["research_status"],
                "data_as_of": item.get("data_as_of"),
                "actions": [
                    {
                        "key": action["key"],
                        "status": action["status"],
                        "severity": action["severity"],
                        "current_evidence": action["current_evidence"],
                    }
                    for action in item.get("actions", [])
                ],
            }
            for item in packet.get("items", [])
        ]
        return hashlib.sha256(
            json.dumps(stable, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()

    def _index_user_knowledge(self, user_id: str, packet: dict[str, Any]) -> None:
        source_key = f"research-actions:{user_id}"
        document_id = "actions-" + hashlib.sha256(
            source_key.encode("utf-8")
        ).hexdigest()[:24]
        lines = [
            "# 我的最新研究行动与观察条件",
            "",
            f"生成时间：{packet['generated_at']}",
            f"方法：{self.METHOD}",
            "",
        ]
        for item in packet.get("items", []):
            lines.extend(
                [
                    f"## {item['name']}（{item['symbol']}）",
                    f"- 研究状态：{item['research_status_label']}",
                    f"- 关注理由：{item.get('thesis') or '尚未填写'}",
                    f"- 证据时间：{item.get('data_as_of') or '待建立'}",
                ]
            )
            for action in item.get("actions", []):
                lines.extend(
                    [
                        f"- [{action['status']}] {action['title']}",
                        f"  - 条件：{action['condition']}",
                        f"  - 当前证据：{action['current_evidence']}",
                        f"  - 下一步：{action['next_step']}",
                    ]
                )
            lines.append("")
        lines.append(packet["boundary"])
        self.database.upsert_knowledge_document(
            document_id=document_id,
            owner_user_id=user_id,
            scope="user",
            title="我的最新研究行动与观察条件",
            original_name="research-actions.md",
            mime_type="text/markdown",
            content="\n".join(lines),
            source_key=source_key,
        )
