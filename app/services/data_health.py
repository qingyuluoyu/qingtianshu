from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.catalog import LIVE_MARKET_CATALOG, PEER_GROUPS
from app.config import Settings
from app.db import Database
from app.services.live_market import market_session_details


_REQUIRED_BACKGROUND_JOBS = {
    "market_intraday_refresh",
    "market_pulse_article",
    "a_share_information_refresh",
    "a_share_filing_refresh",
    "business_structure_refresh",
    "shareholder_structure_refresh",
    "analyst_expectations_refresh",
    "a_share_fundamentals_refresh",
    "us_equity_fundamentals_refresh",
    "earnings_quality_refresh",
    "financial_driver_refresh",
    "peer_valuation_refresh",
    "outlook_calibration_refresh",
    "stock_research_reports_refresh",
    "research_outcomes_backfill",
}


def _age_seconds(value: str | None, now: datetime) -> int | None:
    if not value:
        return None
    try:
        timestamp = datetime.fromisoformat(value).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None
    return max(0, int((now - timestamp).total_seconds()))


def _check(
    key: str,
    category: str,
    status: str,
    label: str,
    **details: Any,
) -> dict[str, Any]:
    return {
        "key": key,
        "category": category,
        "status": status,
        "label": label,
        **details,
    }


class DataHealthService:
    def __init__(self, database: Database, settings: Settings):
        self.database = database
        self.settings = settings

    def audit(
        self, now_utc: datetime | None = None, persist: bool = True
    ) -> dict[str, Any]:
        now = now_utc or datetime.now(timezone.utc)
        checks = [
            *self._market_checks(now),
            *self._market_breadth_checks(now),
            *self._fundamental_checks(now),
            *self._earnings_quality_checks(),
            *self._financial_driver_checks(),
            *self._filing_checks(),
            *self._business_structure_checks(),
            *self._peer_operating_checks(),
            *self._shareholder_structure_checks(),
            *self._analyst_expectation_checks(),
            *self._event_timeline_checks(),
            *self._information_checks(now),
            *self._report_checks(),
            *self._background_checks(),
        ]
        critical = sum(item["status"] == "critical" for item in checks)
        attention = sum(item["status"] == "attention" for item in checks)
        if critical:
            status = "degraded"
            user_label = "部分数据同步中"
        elif attention:
            status = "attention"
            user_label = "部分数据同步中"
        else:
            status = "healthy"
            user_label = "数据已连接"
        snapshot = {
            "status": status,
            "user_label": user_label,
            "created_at": now.isoformat(timespec="seconds"),
            "summary": {
                "total": len(checks),
                "healthy": sum(item["status"] == "healthy" for item in checks),
                "attention": attention,
                "critical": critical,
            },
            "checks": checks,
            "method": "deterministic_data_health_audit_v1",
        }
        return (
            self.database.save_data_health_snapshot(snapshot) if persist else snapshot
        )

    def latest(self, generate_if_missing: bool = False) -> dict[str, Any] | None:
        snapshot = self.database.latest_data_health_snapshot()
        if snapshot is None and generate_if_missing:
            snapshot = self.audit()
        return snapshot

    @staticmethod
    def public_summary(snapshot: dict[str, Any] | None) -> dict[str, Any]:
        if snapshot is None:
            return {
                "status": "initializing",
                "user_label": "数据正在同步",
                "checked_at": None,
                "summary": {"total": 0, "healthy": 0, "attention": 0, "critical": 0},
            }
        return {
            "status": snapshot.get("status"),
            "user_label": snapshot.get("user_label") or "部分数据同步中",
            "checked_at": snapshot.get("created_at"),
            "summary": snapshot.get("summary") or {},
        }

    def _market_checks(self, now: datetime) -> list[dict[str, Any]]:
        checks = []
        for market in LIVE_MARKET_CATALOG:
            interval = "5m" if market.get("provider") == "sina_global_futures" else "1m"
            bars = self.database.get_market_bars(market["symbol"], interval, limit=1)
            session = market_session_details(market, now)
            if not bars:
                checks.append(
                    _check(
                        f"market:{market['key']}",
                        "market",
                        "critical",
                        f"{market['name']}缺少分钟线",
                        is_open=session["is_open"],
                        calendar_status=session.get("calendar_status"),
                    )
                )
                continue
            latest = bars[-1]
            age = _age_seconds(latest.get("timestamp"), now)
            if session.get("calendar_status") == "fallback":
                status = "attention"
                label = f"{market['name']}交易日历已降级"
            elif session["is_open"] and (
                age is None or age > (900 if interval == "5m" else 300)
            ):
                status = "critical"
                label = f"{market['name']}盘中分钟线延迟"
            elif not session["is_open"] and (age is None or age > 7 * 86400):
                status = "attention"
                label = f"{market['name']}最近收盘记录较旧"
            else:
                status = "healthy"
                label = f"{market['name']}分钟线正常"
            checks.append(
                _check(
                    f"market:{market['key']}",
                    "market",
                    status,
                    label,
                    is_open=session["is_open"],
                    session_status=session.get("session_status"),
                    age_seconds=age,
                    timestamp=latest.get("timestamp"),
                    calendar_status=session.get("calendar_status"),
                    calendar_coverage_end=session.get("calendar_coverage_end"),
                )
            )
        return checks

    def _market_breadth_checks(self, now: datetime) -> list[dict[str, Any]]:
        snapshot = self.database.get_cache(
            "sina:a-share-market-breadth:hs_a", allow_stale=True
        )
        if snapshot is None:
            return [
                _check(
                    "market:china_breadth",
                    "market",
                    "critical",
                    "A股全市场涨跌家数缺失",
                    scope="all_a_shares_including_beijing",
                )
            ]
        coverage = snapshot.get("coverage") or {}
        breadth = snapshot.get("breadth") or {}
        turnover = snapshot.get("turnover") or {}
        history = turnover.get("history_comparison") or {}
        distribution = snapshot.get("distribution") or {}
        age = _age_seconds(snapshot.get("fetched_at"), now)
        max_age = max(900, self.settings.sector_cache_seconds * 10)
        directional_count = (breadth.get("advancers") or 0) + (
            breadth.get("decliners") or 0
        )
        complete = (
            snapshot.get("status") == "available"
            and coverage.get("coverage_ratio") == 1.0
            and breadth.get("total") == coverage.get("expected")
            and directional_count > 0
            and turnover.get("status") == "available"
            and (turnover.get("total_amount_cny") or 0) > 0
            and (turnover.get("coverage") or {}).get("coverage_ratio") == 1.0
            and distribution.get("status") == "available"
            and (distribution.get("coverage") or {}).get("coverage_ratio") == 1.0
        )
        history_issue = self._turnover_history_issue(snapshot)
        if not complete:
            status, label = "critical", "A股全市场广度或成交分布覆盖不完整"
        elif history_issue and history_issue["severity"] == "critical":
            status, label = "critical", "A股成交额历史比较存在数量级或日期异常"
        elif history_issue:
            status, label = "attention", "A股成交额历史比较已排除不完整快照"
        elif snapshot.get("is_stale") or age is None or age > max_age:
            status, label = "attention", "A股全市场广度与成交分布快照较旧"
        else:
            status, label = "healthy", "A股全市场广度、成交额与涨跌分布正常"
        return [
            _check(
                "market:china_breadth",
                "market",
                status,
                label,
                age_seconds=age,
                total=breadth.get("total"),
                advancers=breadth.get("advancers"),
                decliners=breadth.get("decliners"),
                unchanged=breadth.get("unchanged"),
                total_amount_cny=turnover.get("total_amount_cny"),
                total_amount_100m_cny=turnover.get("total_amount_100m_cny"),
                turnover_unit=turnover.get("unit"),
                turnover_amount_basis=turnover.get("amount_basis") or {},
                market_date=snapshot.get("market_date"),
                latest_tick_time=coverage.get("latest_tick_time"),
                history_status=history.get("status"),
                previous_market_date=history.get("previous_market_date"),
                previous_total_amount_cny=history.get("previous_total_amount_cny"),
                change_vs_previous_pct=history.get("change_vs_previous_pct"),
                history_issue=history_issue,
                median_pct_change=distribution.get("median_pct_change"),
                coverage_ratio=coverage.get("coverage_ratio"),
                scope=snapshot.get("scope"),
            )
        ]

    @staticmethod
    def _turnover_history_issue(
        snapshot: dict[str, Any],
    ) -> dict[str, Any] | None:
        turnover = snapshot.get("turnover") or {}
        history = turnover.get("history_comparison") or {}
        status = history.get("status")
        if status == "anomaly":
            return {
                "severity": "critical",
                "reason": history.get("anomaly_reason") or "history_anomaly",
                "magnitude_ratio": history.get("magnitude_ratio"),
                "candidate_previous_market_date": history.get(
                    "candidate_previous_market_date"
                ),
                "candidate_previous_total_amount_cny": history.get(
                    "candidate_previous_total_amount_cny"
                ),
            }
        if status == "available":
            market_date = str(snapshot.get("market_date") or "")
            previous_date = str(history.get("previous_market_date") or "")
            current_total = turnover.get("total_amount_cny")
            previous_total = history.get("previous_total_amount_cny")
            if not previous_date or previous_date >= market_date:
                return {
                    "severity": "critical",
                    "reason": "history_date_order_mismatch",
                    "market_date": market_date,
                    "previous_market_date": previous_date or None,
                }
            if (
                isinstance(current_total, (int, float))
                and isinstance(previous_total, (int, float))
                and current_total > 0
                and previous_total > 0
            ):
                magnitude_ratio = max(
                    float(current_total) / float(previous_total),
                    float(previous_total) / float(current_total),
                )
                if magnitude_ratio > 10:
                    return {
                        "severity": "critical",
                        "reason": "order_of_magnitude_mismatch",
                        "magnitude_ratio": round(magnitude_ratio, 4),
                        "market_date": market_date,
                        "previous_market_date": previous_date,
                        "current_total_amount_cny": current_total,
                        "previous_total_amount_cny": previous_total,
                    }
        excluded = list(history.get("excluded_prior_sessions") or [])
        if excluded:
            return {
                "severity": "attention",
                "reason": "incompatible_history_excluded",
                "excluded_prior_sessions": excluded,
            }
        return None

    def _fundamental_checks(self, now: datetime) -> list[dict[str, Any]]:
        checks = []
        valuation_max_age = max(
            7200, self.settings.background_fundamentals_refresh_seconds * 2
        )
        for symbol in self.settings.default_research_symbols:
            valuation = self.database.latest_valuation_snapshot(symbol)
            periods = self.database.list_financial_periods(symbol, limit=1)
            age = _age_seconds(valuation.get("fetched_at") if valuation else None, now)
            if valuation is None:
                valuation_status, valuation_label = "critical", f"{symbol}缺少估值快照"
            elif age is None or age > valuation_max_age:
                valuation_status, valuation_label = "attention", f"{symbol}估值快照较旧"
            else:
                valuation_status, valuation_label = "healthy", f"{symbol}估值快照正常"
            checks.append(
                _check(
                    f"valuation:{symbol}",
                    "fundamentals",
                    valuation_status,
                    valuation_label,
                    age_seconds=age,
                    market_timestamp=(valuation or {}).get("market_timestamp"),
                )
            )
            checks.append(
                _check(
                    f"financial:{symbol}",
                    "fundamentals",
                    "healthy" if periods else "critical",
                    f"{symbol}结构化财务{'正常' if periods else '缺失'}",
                    latest_report_date=(
                        periods[0].get("report_date") if periods else None
                    ),
                )
            )
            group = PEER_GROUPS.get(symbol) or {}
            available_peers = sum(
                self.database.latest_valuation_snapshot(item["symbol"]) is not None
                for item in group.get("peers", [])
            )
            requested_peers = len(group.get("peers", []))
            checks.append(
                _check(
                    f"peers:{symbol}",
                    "fundamentals",
                    "healthy"
                    if available_peers == requested_peers and requested_peers
                    else "attention",
                    f"{symbol}同行估值覆盖 {available_peers}/{requested_peers}",
                    available=available_peers,
                    requested=requested_peers,
                )
            )
        return checks

    def _information_checks(self, now: datetime) -> list[dict[str, Any]]:
        checks = []
        max_age = max(7200, self.settings.background_info_refresh_seconds * 3)
        latest_jobs = {
            item["job_name"]: item for item in self.database.latest_background_jobs()
        }
        for symbol in self.settings.default_research_symbols:
            is_a_share = symbol.endswith((".SS", ".SZ"))
            categories = (
                ("announcement", "news", "social")
                if is_a_share
                else ("regulatory_filing", "global_news")
            )
            items = self.database.list_news(symbol, limit=20, categories=categories)
            content_ages = [
                age
                for item in items
                if (age := _age_seconds(item.get("fetched_at"), now)) is not None
            ]
            content_age = min(content_ages) if content_ages else None
            job_name = (
                "a_share_information_refresh"
                if is_a_share
                else "us_equity_fundamentals_refresh"
            )
            job = latest_jobs.get(job_name) or {}
            poll_age = _age_seconds(job.get("finished_at"), now)
            summary = job.get("summary") or {}
            refresh_result = next(
                (
                    item
                    for item in summary.get("information_results") or []
                    if item.get("symbol") == symbol
                ),
                None,
            )
            sources = (refresh_result or {}).get("sources") or {}
            source_status = {
                category: str((sources.get(category) or {}).get("status") or "missing")
                for category in categories
            }
            sources_polled = sum(status == "ok" for status in source_status.values())
            has_fresh_source_audit = bool(
                job.get("status") == "completed"
                and poll_age is not None
                and poll_age <= max_age
                and refresh_result is not None
            )
            all_sources_polled = bool(
                has_fresh_source_audit and sources_polled == len(categories)
            )
            if not items:
                status, label = "critical", f"{symbol}缺少事件信息"
                freshness_basis = "missing_content"
            elif all_sources_polled:
                status, label = "healthy", f"{symbol}事件信息正常"
                freshness_basis = "successful_source_poll"
            elif has_fresh_source_audit:
                status, label = "attention", f"{symbol}事件信息部分来源待补"
                freshness_basis = "partial_source_poll"
            elif content_age is None or content_age > max_age:
                status, label = "attention", f"{symbol}事件信息较旧"
                freshness_basis = "latest_item_fetch"
            else:
                status, label = "healthy", f"{symbol}事件信息正常"
                freshness_basis = "latest_item_fetch"
            checks.append(
                _check(
                    f"information:{symbol}",
                    "information",
                    status,
                    label,
                    items=len(items),
                    age_seconds=poll_age if has_fresh_source_audit else content_age,
                    poll_age_seconds=poll_age,
                    content_fetch_age_seconds=content_age,
                    freshness_basis=freshness_basis,
                    sources_expected=len(categories),
                    sources_polled=sources_polled,
                    source_status=source_status,
                )
            )
        return checks

    def _earnings_quality_checks(self) -> list[dict[str, Any]]:
        checks = []
        for symbol in self.settings.default_research_symbols:
            latest_periods = self.database.list_financial_periods(symbol, limit=1)
            snapshot = self.database.latest_earnings_quality_snapshot(symbol)
            payload = (snapshot or {}).get("payload") or {}
            snapshot_report_date = (payload.get("latest_report") or {}).get(
                "report_date"
            )
            financial_report_date = (
                latest_periods[0].get("report_date") if latest_periods else None
            )
            if snapshot is None:
                status, label = "critical", f"{symbol}缺少财报质量分析"
            elif (
                financial_report_date and snapshot_report_date != financial_report_date
            ):
                status, label = "attention", f"{symbol}财报质量分析待更新"
            elif payload.get("status") != "available":
                status, label = "critical", f"{symbol}财报质量证据不足"
            else:
                status, label = "healthy", f"{symbol}财报质量分析正常"
            checks.append(
                _check(
                    f"earnings-quality:{symbol}",
                    "fundamentals",
                    status,
                    label,
                    report_date=snapshot_report_date,
                    financial_report_date=financial_report_date,
                    overall_label=payload.get("overall_label"),
                )
            )
        return checks

    def _financial_driver_checks(self) -> list[dict[str, Any]]:
        checks = []
        for symbol in self.settings.default_research_symbols:
            details = self.database.list_financial_statement_details(symbol, limit=3)
            snapshot = self.database.latest_financial_driver_snapshot(symbol)
            payload = (snapshot or {}).get("payload") or {}
            detail_report_date = details[0].get("report_date") if details else None
            snapshot_report_date = (payload.get("latest_period") or {}).get(
                "report_date"
            )
            if not details:
                status, label = "critical", f"{symbol}缺少详细三表"
            elif snapshot is None:
                status, label = "critical", f"{symbol}缺少利润现金流驱动分析"
            elif detail_report_date != snapshot_report_date:
                status, label = "attention", f"{symbol}利润现金流驱动分析待更新"
            elif payload.get("status") != "available":
                status, label = "critical", f"{symbol}利润现金流驱动证据不足"
            else:
                status, label = "healthy", f"{symbol}利润现金流驱动分析正常"
            checks.append(
                _check(
                    f"financial-drivers:{symbol}",
                    "fundamentals",
                    status,
                    label,
                    report_date=snapshot_report_date,
                    detailed_statement_report_date=detail_report_date,
                    overall_label=payload.get("overall_label"),
                    statement_types=sorted(
                        {item.get("statement_type") for item in details}
                    ),
                )
            )
        return checks

    def _report_checks(self) -> list[dict[str, Any]]:
        return [
            _check(
                f"report:{symbol}",
                "reports",
                "healthy"
                if (report := self.database.latest_research_report(symbol))
                else "critical",
                f"{symbol}预生成报告{'存在' if report else '缺失'}",
                generated_at=(report or {}).get("generated_at"),
            )
            for symbol in self.settings.default_research_symbols
        ]

    def _filing_checks(self) -> list[dict[str, Any]]:
        checks = []
        for symbol in self.settings.default_research_symbols:
            if not symbol.endswith((".SS", ".SZ")):
                continue
            details = self.database.list_financial_statement_details(symbol, limit=1)
            report_period = details[0].get("report_date") if details else None
            documents = self.database.list_filing_documents(symbol, limit=6)
            document = next(
                (
                    item
                    for item in documents
                    if report_period is None
                    or item.get("report_period") == report_period
                ),
                None,
            )
            snapshot = (
                self.database.latest_filing_evidence_snapshot(
                    symbol, report_period=report_period
                )
                if report_period
                else self.database.latest_filing_evidence_snapshot(symbol)
            )
            payload = (snapshot or {}).get("payload") or {}
            if not details:
                status, label = "critical", f"{symbol}缺少可匹配的详细财务期"
            elif document is None:
                status, label = "critical", f"{symbol}缺少当前报告期财报全文"
            elif snapshot is None:
                status, label = "critical", f"{symbol}缺少财报全文原因摘录"
            elif payload.get("status") != "available":
                status, label = "attention", f"{symbol}财报原文原因证据有限"
            else:
                status, label = "healthy", f"{symbol}财报全文证据正常"
            checks.append(
                _check(
                    f"filing-evidence:{symbol}",
                    "fundamentals",
                    status,
                    label,
                    report_period=report_period,
                    article_code=(document or {}).get("article_code"),
                    content_chars=(document or {}).get("content_chars"),
                    explicit_explanations=len(
                        payload.get("explicit_company_explanations") or []
                    ),
                )
            )
        return checks

    def _business_structure_checks(self) -> list[dict[str, Any]]:
        checks = []
        for symbol in self.settings.default_research_symbols:
            if not symbol.endswith((".SS", ".SZ")):
                continue
            rows = self.database.list_business_segment_rows(symbol, limit=500)
            snapshot = self.database.latest_business_structure_snapshot(symbol)
            payload = (snapshot or {}).get("payload") or {}
            latest_report_date = rows[0].get("report_date") if rows else None
            snapshot_report_date = payload.get("anchor_report_date")
            if not rows:
                status, label = "critical", f"{symbol}缺少主营构成数据"
            elif snapshot is None:
                status, label = "critical", f"{symbol}缺少主营结构分析"
            elif latest_report_date != snapshot_report_date:
                status, label = "attention", f"{symbol}主营结构分析待更新"
            elif payload.get("status") != "available":
                status, label = "critical", f"{symbol}主营结构证据不足"
            else:
                status, label = "healthy", f"{symbol}主营结构分析正常"
            checks.append(
                _check(
                    f"business-structure:{symbol}",
                    "fundamentals",
                    status,
                    label,
                    report_date=snapshot_report_date,
                    rows=len(rows),
                    dimensions=len(payload.get("dimensions") or []),
                )
            )
        return checks

    def _peer_operating_checks(self) -> list[dict[str, Any]]:
        checks = []
        for symbol in self.settings.default_research_symbols:
            if not symbol.endswith((".SS", ".SZ")):
                continue
            snapshot = self.database.latest_peer_operating_snapshot(symbol)
            payload = (snapshot or {}).get("payload") or {}
            coverage = payload.get("coverage") or {}
            requested = int(coverage.get("requested_peers") or 0)
            comparable = int(coverage.get("same_period_financial_peers") or 0)
            latest_periods = self.database.list_financial_periods(symbol, limit=1)
            latest_report_date = (
                latest_periods[0].get("report_date") if latest_periods else None
            )
            anchor_report_date = payload.get("anchor_report_date")
            if snapshot is None:
                status, label = "critical", f"{symbol}缺少同行经营比较"
            elif latest_report_date and anchor_report_date != latest_report_date:
                status, label = "attention", f"{symbol}同行经营比较待更新"
            elif requested and comparable == requested:
                status, label = "healthy", f"{symbol}同行经营比较正常"
            elif comparable >= 2:
                status, label = "attention", f"{symbol}同行经营样本部分可比"
            else:
                status, label = "critical", f"{symbol}同行经营样本不足"
            checks.append(
                _check(
                    f"peer-operating:{symbol}",
                    "fundamentals",
                    status,
                    label,
                    anchor_report_date=anchor_report_date,
                    latest_report_date=latest_report_date,
                    requested_peers=requested,
                    same_period_financial_peers=comparable,
                    business_profile_peers=coverage.get("business_profile_peers", 0),
                )
            )
        return checks

    def _shareholder_structure_checks(self) -> list[dict[str, Any]]:
        checks = []
        for symbol in self.settings.default_research_symbols:
            if not symbol.endswith((".SS", ".SZ")):
                continue
            snapshot = self.database.latest_shareholder_structure_snapshot(symbol)
            payload = (snapshot or {}).get("payload") or {}
            holder_count_as_of = payload.get("holder_count_as_of")
            top10_report_date = payload.get("top10_report_date")
            if snapshot is None:
                status, label = "critical", f"{symbol}缺少股东结构分析"
            elif payload.get("status") != "available":
                status, label = "critical", f"{symbol}股东结构证据不足"
            elif not top10_report_date:
                status, label = "attention", f"{symbol}十大股东报告期待补"
            else:
                status, label = "healthy", f"{symbol}股东结构分析正常"
            checks.append(
                _check(
                    f"shareholder-structure:{symbol}",
                    "fundamentals",
                    status,
                    label,
                    holder_count_as_of=holder_count_as_of,
                    top10_report_date=top10_report_date,
                    holder_history_points=len(payload.get("holder_history") or []),
                    top_holders=len(payload.get("top_holders") or []),
                )
            )
        return checks

    def _analyst_expectation_checks(self) -> list[dict[str, Any]]:
        checks = []
        for symbol in self.settings.default_research_symbols:
            if not symbol.endswith((".SS", ".SZ")):
                continue
            snapshot = self.database.latest_analyst_expectation_snapshot(symbol)
            payload = (snapshot or {}).get("payload") or {}
            coverage = payload.get("coverage") or {}
            if snapshot is None:
                status, label = "critical", f"{symbol}缺少分析师一致预期快照"
            elif payload.get("status") != "available":
                status, label = "attention", f"{symbol}分析师预期证据有限"
            elif not (
                coverage.get("estimate_years") or coverage.get("reports_returned")
            ):
                status, label = "attention", f"{symbol}分析师预期覆盖待补"
            else:
                status, label = "healthy", f"{symbol}分析师预期与研报正常"
            checks.append(
                _check(
                    f"analyst-expectations:{symbol}",
                    "fundamentals",
                    status,
                    label,
                    as_of_date=payload.get("as_of_date"),
                    latest_report_date=payload.get("latest_report_date"),
                    rating_organizations=payload.get("rating_organization_count"),
                    estimate_years=coverage.get("estimate_years", 0),
                    reports=coverage.get("reports_returned", 0),
                )
            )
        return checks

    def _event_timeline_checks(self) -> list[dict[str, Any]]:
        checks = []
        for symbol in self.settings.default_research_symbols:
            if not symbol.endswith((".SS", ".SZ")):
                continue
            snapshot = self.database.latest_event_timeline_snapshot(symbol)
            payload = (snapshot or {}).get("payload") or {}
            coverage = payload.get("coverage") or {}
            if snapshot is None:
                status, label = "critical", f"{symbol}缺少事件脉络快照"
            elif not coverage.get("events_returned"):
                status, label = "attention", f"{symbol}事件脉络待补"
            elif not coverage.get("official_events"):
                status, label = "attention", f"{symbol}事件脉络缺少官方披露"
            else:
                status, label = "healthy", f"{symbol}事件脉络正常"
            checks.append(
                _check(
                    f"event-timeline:{symbol}",
                    "information",
                    status,
                    label,
                    as_of_date=payload.get("as_of_date"),
                    events=coverage.get("events_returned", 0),
                    official_events=coverage.get("official_events", 0),
                    media_events=coverage.get("media_events", 0),
                    risk_events=coverage.get("risk_events", 0),
                )
            )
        return checks

    def _background_checks(self) -> list[dict[str, Any]]:
        latest = {
            item["job_name"]: item for item in self.database.latest_background_jobs()
        }
        checks = []
        for job_name in sorted(_REQUIRED_BACKGROUND_JOBS):
            job = latest.get(job_name)
            if job is None:
                status, label = "attention", f"{job_name}尚未运行"
            elif job.get("status") != "completed":
                status, label = "critical", f"{job_name}最近运行未完成"
            else:
                status, label = "healthy", f"{job_name}最近运行完成"
            checks.append(
                _check(
                    f"background:{job_name}",
                    "background",
                    status,
                    label,
                    started_at=(job or {}).get("started_at"),
                    finished_at=(job or {}).get("finished_at"),
                )
            )
        return checks
