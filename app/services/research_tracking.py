from __future__ import annotations

from typing import Any

from app.catalog import normalize_symbol
from app.db import Database
from app.services.security_master import SecurityMasterService
from app.utils import utc_now


_SEVERITY_RANK = {"stable": 0, "notice": 1, "attention": 2}


def build_research_change_payload(
    report: dict[str, Any], previous_report: dict[str, Any] | None
) -> dict[str, Any]:
    current = report.get("evidence") or {}
    previous = (previous_report or {}).get("evidence") or {}
    name = report.get("name") or current.get("display_name") or report["symbol"]
    changes: list[dict[str, Any]] = []

    def add_change(
        dimension: str,
        label: str,
        before: Any,
        after: Any,
        detail: str,
        severity: str = "notice",
    ) -> None:
        changes.append(
            {
                "dimension": dimension,
                "label": label,
                "before": before,
                "after": after,
                "detail": detail,
                "severity": severity,
            }
        )

    current_metrics = current.get("metrics") or {}
    previous_metrics = previous.get("metrics") or {}
    for key, label in (
        ("trend_state", "中期趋势"),
        ("technical_state", "技术结构"),
    ):
        before = previous_metrics.get(key)
        after = current_metrics.get(key)
        if previous_report and before and after and before != after:
            severity = (
                "attention"
                if any(term in str(after) for term in ("偏弱", "转弱", "超跌"))
                else "notice"
            )
            add_change(
                "price_structure",
                label,
                before,
                after,
                f"{label}由“{before}”变为“{after}”。",
                severity,
            )

    _numeric_change(
        changes,
        previous_metrics,
        current_metrics,
        "max_drawdown_60d_pct",
        "60日最大回撤",
        threshold=2.0,
        worse_when_lower=True,
    )
    _numeric_change(
        changes,
        previous_metrics,
        current_metrics,
        "volatility_20d_annualized_pct",
        "20日年化波动率",
        threshold=5.0,
        worse_when_higher=True,
    )
    _numeric_change(
        changes,
        previous_metrics,
        current_metrics,
        "return_20d_pct",
        "20日收益",
        threshold=5.0,
        worse_when_lower=True,
    )

    current_information = current.get("a_share_information") or {}
    previous_information = previous.get("a_share_information") or {}
    current_sentiment = current_information.get("sentiment") or {}
    previous_sentiment = previous_information.get("sentiment") or {}
    if previous_report:
        before_band = previous_sentiment.get("band")
        after_band = current_sentiment.get("band")
        if before_band and after_band and before_band != after_band:
            add_change(
                "sentiment",
                "社区情绪",
                before_band,
                after_band,
                f"社区情绪样本由“{before_band}”变为“{after_band}”，只作为弱证据。",
            )

    current_fundamentals = current.get("fundamentals") or {}
    previous_fundamentals = previous.get("fundamentals") or {}
    current_report = (current_fundamentals.get("summary") or {}).get(
        "latest_report"
    ) or {}
    previous_financial = (previous_fundamentals.get("summary") or {}).get(
        "latest_report"
    ) or {}
    if previous_report and current_report.get("report_date") != previous_financial.get(
        "report_date"
    ) and current_report.get("report_date"):
        add_change(
            "fundamentals",
            "最新财务报告期",
            previous_financial.get("report_date"),
            current_report.get("report_date"),
            (
                f"结构化财务证据更新至{current_report.get('report_date_name') or current_report.get('report_date')}；"
                f"营收同比{_fmt_pct(current_report.get('revenue_yoy_pct'))}，"
                f"归母净利润同比{_fmt_pct(current_report.get('net_profit_yoy_pct'))}。"
            ),
            "attention"
            if any(
                isinstance(current_report.get(key), (int, float))
                and current_report[key] < 0
                for key in ("revenue_yoy_pct", "net_profit_yoy_pct")
            )
            else "notice",
        )

    current_quality = current.get("earnings_quality") or {}
    previous_quality = previous.get("earnings_quality") or {}
    current_quality_label = current_quality.get("overall_label")
    previous_quality_label = previous_quality.get("overall_label")
    if (
        previous_report
        and current_quality_label
        and current_quality_label != previous_quality_label
    ):
        contradictions = current_quality.get("contradictions") or []
        add_change(
            "earnings_quality",
            "财报质量",
            previous_quality_label,
            current_quality_label,
            (
                f"财报质量更新为“{current_quality_label}”"
                + (
                    f"；主要矛盾：{'；'.join(contradictions[:2])}。"
                    if contradictions
                    else "。"
                )
            ),
            "attention"
            if any(term in str(current_quality_label) for term in ("承压", "分化", "复核"))
            else "notice",
        )

    current_drivers = current.get("financial_drivers") or {}
    previous_drivers = previous.get("financial_drivers") or {}
    current_driver_label = current_drivers.get("overall_label")
    previous_driver_label = previous_drivers.get("overall_label")
    if (
        previous_report
        and current_driver_label
        and current_driver_label != previous_driver_label
    ):
        negative = [
            item.get("label")
            for item in (
                current_drivers.get("confirmed_mechanical_drivers") or []
            )
            if item.get("direction") == "negative"
        ]
        add_change(
            "financial_drivers",
            "利润与现金流驱动",
            previous_driver_label,
            current_driver_label,
            (
                f"利润与现金流驱动更新为“{current_driver_label}”"
                + (
                    f"；主要负向机械影响：{'；'.join(str(item) for item in negative[:2])}。"
                    if negative
                    else "。"
                )
            ),
            "attention"
            if any(term in str(current_driver_label) for term in ("承压", "负向"))
            else "notice",
        )

    current_expectations = current.get("analyst_expectations") or {}
    previous_expectations = previous.get("analyst_expectations") or {}
    current_forecasts = {
        item.get("year"): item.get("value")
        for item in current_expectations.get("forecast_eps") or []
        if item.get("kind") == "estimate" and item.get("year") is not None
    }
    previous_forecasts = {
        item.get("year"): item.get("value")
        for item in previous_expectations.get("forecast_eps") or []
        if item.get("kind") == "estimate" and item.get("year") is not None
    }
    if previous_report and current_forecasts != previous_forecasts:
        revision = current_expectations.get("revision") or {}
        detail = revision.get("summary") or "同财年EPS一致预期发生变化。"
        organization_delta = revision.get("organization_count_delta")
        if isinstance(organization_delta, int):
            detail += (
                f"覆盖机构数较上一快照{'增加' if organization_delta > 0 else '减少'}"
                f"{abs(organization_delta)}家。"
                if organization_delta
                else "覆盖机构数未变化。"
            )
        add_change(
            "analyst_expectations",
            "分析师一致预期",
            previous_forecasts,
            current_forecasts,
            detail,
            "notice",
        )

    current_outlook = current.get("conditional_outlook") or {}
    previous_outlook = previous.get("conditional_outlook") or {}
    if previous_report and current_outlook.get("label") and (
        current_outlook.get("label") != previous_outlook.get("label")
        or current_outlook.get("confidence") != previous_outlook.get("confidence")
    ):
        add_change(
            "outlook",
            "条件展望",
            {
                "label": previous_outlook.get("label"),
                "confidence": previous_outlook.get("confidence"),
            },
            {
                "label": current_outlook.get("label"),
                "confidence": current_outlook.get("confidence"),
            },
            (
                f"条件展望更新为“{current_outlook.get('label')}”，"
                f"证据置信度为{current_outlook.get('confidence')}；不代表涨跌概率。"
            ),
        )

    new_evidence = (
        _new_evidence_items(
            current,
            previous,
            extra_subject_terms=(name, report["symbol"].split(".", 1)[0]),
        )
        if previous_report
        else []
    )
    for item in new_evidence[:3]:
        add_change(
            "event",
            item["category_label"],
            None,
            item["title"],
            f"新增{item['category_label']}：{item['title']}。",
            "notice",
        )

    current_board = current.get("analysis_board") or {}
    previous_board = previous.get("analysis_board") or {}
    if previous_report and current_board.get("ready_modules") != previous_board.get(
        "ready_modules"
    ):
        current_total = current_board.get("total_modules") or 7
        previous_total = previous_board.get("total_modules") or current_total
        add_change(
            "coverage",
            "研究覆盖",
            previous_board.get("ready_modules"),
            current_board.get("ready_modules"),
            (
                f"研究模块覆盖由{previous_board.get('ready_modules')}/{previous_total}变为"
                f"{current_board.get('ready_modules')}/{current_total}。"
            ),
        )

    if previous_report is None:
        event_type = "baseline"
        severity = "stable"
        summary = (
            f"{name}已建立长期研究基线，覆盖行情、事件、情绪、基本面、"
            "分析师预期、同行和风险复核。"
        )
    else:
        event_type = "evidence_change"
        severity = max(
            (item["severity"] for item in changes),
            key=lambda value: _SEVERITY_RANK[value],
            default="stable",
        )
        if changes:
            summary = f"{name}最新变化：" + "；".join(
                item["detail"].rstrip("。") for item in changes[:3]
            ) + "。"
        else:
            summary = f"{name}证据时间已更新，核心研究判断暂未出现实质变化。"

    tracking_plan = current_board.get("tracking_plan") or []
    return {
        "symbol": report["symbol"],
        "name": name,
        "event_type": event_type,
        "severity": severity,
        "summary": summary,
        "data_as_of": report.get("market_timestamp") or report.get("generated_at"),
        "changes": changes,
        "new_evidence": new_evidence[:6],
        "current_state": {
            key: current_metrics.get(key)
            for key in (
                "latest_close",
                "return_1d_pct",
                "return_20d_pct",
                "trend_state",
                "technical_state",
                "rsi_14",
                "macd_histogram",
                "atr_14_pct",
                "volume_ratio_5_20",
                "volatility_20d_annualized_pct",
                "max_drawdown_60d_pct",
            )
        },
        "next_review": tracking_plan[0] if tracking_plan else None,
        "boundary": (
            "变化事件用于研究复核，不是买卖、止盈止损等交易指令，"
            "也不是下一交易日预测。"
        ),
    }


class ResearchTrackingService:
    def __init__(self, database: Database):
        self.database = database
        self.security_master = SecurityMasterService(database)

    def record_report(
        self,
        report: dict[str, Any],
        previous_report: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        existing = self.database.research_change_event_for_report(
            report["symbol"], report["id"]
        )
        if existing is not None:
            return existing
        if previous_report is None:
            history = self.database.list_research_reports(report["symbol"], limit=2)
            previous_report = next(
                (item for item in history if item["id"] != report["id"]), None
            )
        payload = build_research_change_payload(report, previous_report)
        return self.database.save_research_change_event(
            symbol=report["symbol"],
            report_id=report["id"],
            previous_report_id=(previous_report or {}).get("id"),
            event_type=payload["event_type"],
            severity=payload["severity"],
            summary=payload["summary"],
            payload=payload,
        )

    def ensure_existing_reports(self) -> int:
        created = 0
        for report in self.database.list_latest_research_reports(limit=500):
            if self.database.research_change_event_for_report(
                report["symbol"], report["id"]
            ) is None:
                self.record_report(report)
                created += 1
        return created

    def get_packet(
        self, user_id: str, symbol: str | None = None, limit: int = 20
    ) -> dict[str, Any]:
        watchlist = self.database.list_watchlist(user_id)
        watchlist_map = {item["symbol"]: item for item in watchlist}
        canonical = normalize_symbol(symbol) if symbol else None
        symbols = [canonical] if canonical else list(watchlist_map)
        events = self.database.list_research_change_events(symbols, limit=limit)
        states = []
        for item_symbol in symbols:
            report = self.database.latest_research_report(item_symbol)
            event = self.database.latest_research_change_event(item_symbol)
            evidence = (report or {}).get("evidence") or {}
            metrics = evidence.get("metrics") or {}
            item = watchlist_map.get(item_symbol) or {}
            states.append(
                {
                    "symbol": item_symbol,
                    "name": self.security_master.display_name(
                        item_symbol,
                        item.get("name"),
                        (report or {}).get("name"),
                    ),
                    "thesis": item.get("thesis"),
                    "in_watchlist": item_symbol in watchlist_map,
                    "latest_report_at": (report or {}).get("generated_at"),
                    "latest_change": self.public_event(event) if event else None,
                    "current_state": {
                        key: metrics.get(key)
                        for key in (
                            "latest_close",
                            "return_1d_pct",
                            "return_20d_pct",
                            "trend_state",
                            "technical_state",
                            "rsi_14",
                            "macd_histogram",
                            "atr_14_pct",
                            "volume_ratio_5_20",
                            "volatility_20d_annualized_pct",
                            "max_drawdown_60d_pct",
                        )
                    },
                    "next_review": (
                        ((evidence.get("analysis_board") or {}).get("tracking_plan") or [None])[0]
                    ),
                }
            )
        return {
            "type": "research_tracking",
            "generated_at": utc_now(),
            "symbol": canonical,
            "items": states,
            "events": [self.public_event(event) for event in events],
            "coverage": {
                "requested": len(symbols),
                "with_report": sum(item.get("latest_report_at") is not None for item in states),
                "with_change_archive": sum(item.get("latest_change") is not None for item in states),
            },
            "method": (
                "比较连续研究报告中的行情、技术、事件、情绪、基本面、"
                "分析师一致预期、条件展望和研究覆盖变化。"
            ),
            "boundary": (
                "研究变化档案是长期证据记录，不是收益评分、胜率或交易指令。"
            ),
        }

    def public_event(self, event: dict[str, Any] | None) -> dict[str, Any] | None:
        if event is None:
            return None
        payload = event.get("payload") or {}
        symbol = str(event.get("symbol") or payload.get("symbol") or "")
        original_name = str(payload.get("name") or "")
        display_name = self.security_master.display_name(
            symbol,
            original_name,
        )

        def localized(value: Any) -> Any:
            if not original_name or original_name == display_name:
                return value
            if isinstance(value, str):
                return value.replace(original_name, display_name)
            if isinstance(value, list):
                return [localized(item) for item in value]
            if isinstance(value, dict):
                return {key: localized(item) for key, item in value.items()}
            return value

        return {
            "id": event.get("id"),
            "symbol": event.get("symbol"),
            "event_type": event.get("event_type"),
            "severity": event.get("severity"),
            "summary": localized(event.get("summary")),
            "created_at": event.get("created_at"),
            "data_as_of": payload.get("data_as_of"),
            "changes": localized(payload.get("changes") or []),
            "new_evidence": localized(payload.get("new_evidence") or []),
            "current_state": payload.get("current_state") or {},
            "next_review": localized(payload.get("next_review")),
            "boundary": localized(payload.get("boundary")),
        }


def _numeric_change(
    changes: list[dict[str, Any]],
    previous: dict[str, Any],
    current: dict[str, Any],
    key: str,
    label: str,
    *,
    threshold: float,
    worse_when_lower: bool = False,
    worse_when_higher: bool = False,
) -> None:
    before = previous.get(key)
    after = current.get(key)
    if not isinstance(before, (int, float)) or not isinstance(after, (int, float)):
        return
    delta = float(after) - float(before)
    if abs(delta) < threshold:
        return
    worsened = (worse_when_lower and delta < 0) or (worse_when_higher and delta > 0)
    changes.append(
        {
            "dimension": "risk" if worsened else "price_structure",
            "label": label,
            "before": before,
            "after": after,
            "detail": f"{label}由{_fmt_pct(before)}变为{_fmt_pct(after)}。",
            "severity": "attention" if worsened else "notice",
        }
    )


def _new_evidence_items(
    current: dict[str, Any],
    previous: dict[str, Any],
    extra_subject_terms: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    subject_terms = {
        str(current.get("display_name") or "").casefold(),
        str(current.get("symbol") or "").split(".", 1)[0].casefold(),
    }
    fundamental_name = str(
        ((current.get("fundamentals") or {}).get("summary") or {}).get("name")
        or (current.get("fundamentals") or {}).get("name")
        or ""
    ).strip()
    if fundamental_name:
        subject_terms.add(fundamental_name.casefold())
        subject_terms.add(fundamental_name.split()[0].casefold())
    subject_terms.update(
        str(term).casefold() for term in extra_subject_terms if str(term).strip()
    )
    subject_terms.discard("")
    current_timeline = (current.get("event_timeline") or {}).get("events") or []
    previous_timeline = (previous.get("event_timeline") or {}).get("events") or []
    specs = (
        (("重要事件", current_timeline, previous_timeline, False),)
        if current_timeline
        else (
            (
                "公告",
                (current.get("a_share_information") or {}).get("announcements") or [],
                (previous.get("a_share_information") or {}).get("announcements") or [],
                False,
            ),
            (
                "公司新闻",
                (current.get("a_share_information") or {}).get("news") or [],
                (previous.get("a_share_information") or {}).get("news") or [],
                True,
            ),
            (
                "公司新闻",
                (current.get("global_information") or {}).get("news") or [],
                (previous.get("global_information") or {}).get("news") or [],
                False,
            ),
            (
                "监管文件",
                (current.get("fundamentals") or {}).get("regulatory_filings") or [],
                (previous.get("fundamentals") or {}).get("regulatory_filings") or [],
                False,
            ),
        )
    )
    output = []
    for category_label, current_items, previous_items, require_subject in specs:
        previous_keys = {
            str(item.get("url") or item.get("title")) for item in previous_items
        }
        for item in current_items:
            key = str(item.get("url") or item.get("title"))
            if not key or key in previous_keys or not item.get("title"):
                continue
            title_folded = str(item["title"]).casefold()
            if require_subject and not any(
                term in title_folded for term in subject_terms
            ):
                continue
            output.append(
                {
                    "category_label": (
                        f"{item.get('event_label')}（{item.get('evidence_label')}）"
                        if item.get("event_label") and item.get("evidence_label")
                        else category_label
                    ),
                    "title": item.get("title"),
                    "published_at": item.get("published_at")
                    or item.get("notice_date")
                    or item.get("filing_date"),
                }
            )
    return output


def _fmt_pct(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "—"
    return f"{float(value):.2f}%".replace("-0.00%", "0.00%")
