from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import Any

from app.catalog import RESEARCH_TARGETS, normalize_symbol
from app.db import Database
from app.providers.analyst_expectations import AShareAnalystExpectationsProvider
from app.utils import utc_now


class AnalystExpectationsService:
    METHOD = "deterministic_broker_consensus_v1"

    def __init__(
        self,
        database: Database,
        provider: AShareAnalystExpectationsProvider,
    ) -> None:
        self.database = database
        self.provider = provider

    def refresh_symbol(self, symbol: str) -> dict[str, Any]:
        canonical = normalize_symbol(symbol)
        fetched = self.provider.fetch(canonical)
        packet = self._build_packet(fetched)
        fingerprint = _fingerprint(packet)
        self.database.save_analyst_expectation_snapshot(packet, fingerprint)
        current = self._latest_with_revision(canonical)
        self._index_common_knowledge(current)
        return current

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
                        "latest_report_date": packet.get("latest_report_date"),
                        "rating_organization_count": packet.get(
                            "rating_organization_count"
                        ),
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
        self,
        symbol: str,
        *,
        refresh_max_age_seconds: int = 3600,
        refresh_if_missing: bool = True,
    ) -> dict[str, Any]:
        canonical = normalize_symbol(symbol)
        if not canonical.endswith((".SS", ".SZ")):
            raise ValueError("分析师一致预期当前只支持 A 股证券")
        snapshot = self.database.latest_analyst_expectation_snapshot(canonical)
        should_refresh = snapshot is None or _is_older_than(
            snapshot.get("created_at") if snapshot else None,
            refresh_max_age_seconds,
        )
        if should_refresh and refresh_if_missing:
            try:
                return self.refresh_symbol(canonical)
            except Exception:
                if snapshot is None:
                    raise
        if snapshot is not None:
            return self._latest_with_revision(canonical)
        return self._unavailable(canonical)

    def list_latest_reports(self, limit: int = 20) -> dict[str, Any]:
        """市场级券商研报列表：跨个股聚合已入库一致预期快照中的研报记录。"""
        bounded_limit = max(1, min(int(limit), 100))
        snapshots = self.database.list_latest_analyst_expectation_snapshots(
            limit=bounded_limit
        )
        items = []
        for snapshot in snapshots:
            payload = snapshot.get("payload") or {}
            symbol = str(payload.get("symbol") or snapshot.get("symbol") or "")
            name = (
                (RESEARCH_TARGETS.get(symbol) or {}).get("name")
                or payload.get("name")
                or snapshot.get("name")
                or symbol
            )
            for report in payload.get("latest_reports") or []:
                forecast_eps = [
                    {"year": item.get("year"), "value": item.get("value")}
                    for item in (report.get("forecast_eps") or [])
                    if item.get("year") is not None and item.get("value") is not None
                ]
                items.append(
                    {
                        "symbol": symbol,
                        "name": name,
                        "title": report.get("title"),
                        "institution": report.get("institution"),
                        "researchers": report.get("researchers"),
                        "published_at": report.get("published_at"),
                        "rating": report.get("rating"),
                        "previous_rating": report.get("previous_rating"),
                        "forecast_eps": forecast_eps,
                        "report_url": report.get("report_url"),
                        "summary": _report_view_summary(
                            institution=report.get("institution"),
                            rating=report.get("rating"),
                            previous_rating=report.get("previous_rating"),
                            forecast_eps=forecast_eps,
                        ),
                    }
                )
        items.sort(
            key=lambda item: str(item.get("published_at") or ""), reverse=True
        )
        items = items[:bounded_limit]
        return {
            "status": "ready" if items else "empty",
            "items": items,
            "method": (
                "deterministic_broker_report_list_v1：取每只入库个股最新一条"
                "分析师一致预期快照，汇总其中的券商研报记录并按发布时间倒序；"
                "EPS预测值为元/股直通不缩放；只聚合已入库快照，不实时抓取。"
            ),
            "warnings": (
                []
                if items
                else [
                    (
                        "当前没有已入库的券商研报快照；"
                        "等待后台刷新或单股分析师一致预期请求落库后自动出现。"
                    )
                ]
            ),
        }

    def _build_packet(self, fetched: dict[str, Any]) -> dict[str, Any]:
        reports = [
            item for item in fetched.get("reports") or [] if item.get("title")
        ]
        latest_report_date = next(
            (item.get("published_at") for item in reports if item.get("published_at")),
            None,
        )
        forecast_eps = list(fetched.get("forecast_eps") or [])
        estimates = [
            item for item in forecast_eps if item.get("kind") == "estimate"
        ]
        rating_counts = fetched.get("rating_counts") or {}
        organization_count = fetched.get("rating_organization_count")
        name = (
            fetched.get("name")
            or RESEARCH_TARGETS.get(fetched["symbol"], {}).get("name")
            or fetched["symbol"]
        )
        as_of_date = (
            latest_report_date
            or str(fetched.get("fetched_at") or utc_now())[:10]
        )
        rating_statement = _rating_statement(
            organization_count, rating_counts, fetched.get("rating_window")
        )
        forecast_statement = _forecast_statement(forecast_eps)
        status = "available" if estimates or reports else "insufficient"
        return {
            "type": "analyst_expectations",
            "symbol": fetched["symbol"],
            "name": name,
            "industry": fetched.get("industry"),
            "status": status,
            "generated_at": utc_now(),
            "as_of_date": as_of_date,
            "latest_report_date": latest_report_date,
            "method": self.METHOD,
            "rating_window": fetched.get("rating_window") or "近六个月",
            "rating_organization_count": organization_count,
            "rating_counts": rating_counts,
            "rating_statement": rating_statement,
            "forecast_eps": forecast_eps,
            "forecast_statement": forecast_statement,
            "latest_reports": reports[:12],
            "coverage": {
                "reports_returned": len(reports),
                "rating_organizations": organization_count,
                "forecast_years": len(forecast_eps),
                "estimate_years": len(estimates),
            },
            "sources": fetched.get("sources") or [],
            "source_fetched_at": fetched.get("fetched_at"),
            "review_points": [
                "把下一次一致预期快照与当前同一财年EPS比较，区分上修、下修和样本机构变化。",
                "将券商EPS预测与公司后续正式财报实际EPS对照，不把预测值当成已实现业绩。",
                "阅读最新研报原文并核对假设、业务口径和风险，不只看评级标签。",
            ],
            "boundary": (
                "该模块汇总第三方券商研报统计，不是公司业绩指引、监管披露或事实业绩。"
                "评级分布不构成买卖建议；目标价字段不进入清数智算证据包。"
                "一致预期的变化还可能来自样本机构增减，必须结合覆盖机构数解释。"
            ),
        }

    def _latest_with_revision(self, symbol: str) -> dict[str, Any]:
        snapshots = self.database.list_analyst_expectation_snapshots(
            symbol, limit=2
        )
        if not snapshots:
            return self._unavailable(symbol)
        current = dict(snapshots[0].get("payload") or {})
        previous = (
            dict(snapshots[1].get("payload") or {})
            if len(snapshots) > 1
            else None
        )
        current["snapshot_id"] = snapshots[0]["id"]
        current["snapshot_created_at"] = snapshots[0]["created_at"]
        current["revision"] = _revision_summary(current, previous, snapshots)
        return current

    def _index_common_knowledge(self, packet: dict[str, Any]) -> None:
        source_key = f"analyst-expectations:{packet['symbol']}"
        document_id = "analyst-expectations-" + hashlib.sha256(
            source_key.encode("utf-8")
        ).hexdigest()[:24]
        forecast_lines = "\n".join(
            f"- {item.get('year')}{'A' if item.get('kind') == 'actual' else 'E'}："
            f"每股收益 {item.get('value')}"
            for item in packet.get("forecast_eps") or []
        ) or "- 当前未取得可核验的EPS一致预期。"
        report_lines = "\n".join(
            f"- {item.get('published_at') or '日期待确认'}｜"
            f"{item.get('institution') or '机构待确认'}｜"
            f"{item.get('title')}｜评级 {item.get('rating') or '未披露'}"
            for item in (packet.get("latest_reports") or [])[:10]
        ) or "- 当前未取得个股研报列表。"
        revision = packet.get("revision") or {}
        content = (
            f"# {packet['name']}分析师一致预期与研报跟踪\n\n"
            f"证券代码：{packet['symbol']}\n\n"
            f"数据截至：{packet.get('as_of_date')}\n\n"
            f"## 覆盖与评级分布\n\n{packet.get('rating_statement')}\n\n"
            f"## EPS一致预期\n\n{forecast_lines}\n\n"
            f"{packet.get('forecast_statement')}\n\n"
            f"## 历史修订\n\n{revision.get('summary')}\n\n"
            f"## 最新研报\n\n{report_lines}\n\n"
            f"## 下一步复核\n\n"
            + "\n".join(
                f"- {item}" for item in packet.get("review_points") or []
            )
            + f"\n\n## 证据边界\n\n{packet.get('boundary')}\n"
        )
        self.database.upsert_knowledge_document(
            document_id=document_id,
            owner_user_id=None,
            scope="common",
            title=f"{packet['name']}分析师一致预期与研报跟踪",
            original_name=f"{packet['symbol']}-analyst-expectations.md",
            mime_type="text/markdown",
            content=content,
            source_key=source_key,
        )

    @staticmethod
    def _unavailable(symbol: str) -> dict[str, Any]:
        return {
            "type": "analyst_expectations",
            "symbol": symbol,
            "name": RESEARCH_TARGETS.get(symbol, {}).get("name") or symbol,
            "status": "insufficient",
            "generated_at": utc_now(),
            "method": AnalystExpectationsService.METHOD,
            "rating_counts": {},
            "forecast_eps": [],
            "latest_reports": [],
            "coverage": {
                "reports_returned": 0,
                "rating_organizations": 0,
                "forecast_years": 0,
                "estimate_years": 0,
            },
            "revision": {
                "available": False,
                "summary": "尚无可比较的一致预期快照。",
            },
            "review_points": ["取得至少一份带日期的券商研报或一致预期汇总。"],
            "boundary": "不使用缺失预测值生成评级、目标价或未来收益概率。",
        }


def _revision_summary(
    current: dict[str, Any],
    previous: dict[str, Any] | None,
    snapshots: list[dict[str, Any]],
) -> dict[str, Any]:
    if previous is None:
        return {
            "available": False,
            "summary": "当前为首个一致预期快照，尚不能判断EPS上修或下修。",
            "previous_snapshot_at": None,
            "organization_count_delta": None,
            "rating_count_deltas": {},
            "eps_revisions": [],
        }
    current_count = current.get("rating_organization_count")
    previous_count = previous.get("rating_organization_count")
    organization_delta = _difference(current_count, previous_count)
    rating_deltas = {
        key: _difference(
            (current.get("rating_counts") or {}).get(key),
            (previous.get("rating_counts") or {}).get(key),
        )
        for key in ("buy", "add", "neutral", "reduce", "sell")
    }
    previous_forecasts = {
        item.get("year"): item
        for item in previous.get("forecast_eps") or []
        if item.get("year") is not None
    }
    revisions = []
    for item in current.get("forecast_eps") or []:
        if item.get("kind") != "estimate":
            continue
        prior = previous_forecasts.get(item.get("year"))
        if not prior or prior.get("value") is None or item.get("value") is None:
            continue
        delta = round(float(item["value"]) - float(prior["value"]), 6)
        pct = (
            round(delta / abs(float(prior["value"])) * 100, 4)
            if float(prior["value"]) != 0
            else None
        )
        revisions.append(
            {
                "year": item["year"],
                "current": item["value"],
                "previous": prior["value"],
                "change": delta,
                "change_pct": pct,
                "direction": (
                    "up" if delta > 0 else "down" if delta < 0 else "flat"
                ),
            }
        )
    changed = [item for item in revisions if item["direction"] != "flat"]
    if changed:
        parts = [
            f"{item['year']}E EPS较上一快照"
            f"{'上修' if item['direction'] == 'up' else '下修'}"
            f" {abs(item['change_pct']):.2f}%"
            for item in changed
            if item.get("change_pct") is not None
        ]
        summary = "；".join(parts)
    elif organization_delta:
        summary = (
            f"同财年EPS预测未发生可见变化，但覆盖机构数较上一快照"
            f"{'增加' if organization_delta > 0 else '减少'} "
            f"{abs(organization_delta)} 家。"
        )
    else:
        summary = "与上一份不同内容快照相比，同财年EPS和评级覆盖未见可计算变化。"
    return {
        "available": True,
        "summary": summary,
        "previous_snapshot_at": snapshots[1].get("created_at"),
        "organization_count_delta": organization_delta,
        "rating_count_deltas": rating_deltas,
        "eps_revisions": revisions,
    }


def _rating_statement(
    organization_count: Any,
    counts: dict[str, Any],
    window: Any,
) -> str:
    if not isinstance(organization_count, int) or organization_count <= 0:
        return "当前未取得可核验的评级机构覆盖数。"
    return (
        f"{window or '近六个月'}统计覆盖 {organization_count} 家机构："
        f"买入 {counts.get('buy', 0)}，增持 {counts.get('add', 0)}，"
        f"中性 {counts.get('neutral', 0)}，减持 {counts.get('reduce', 0)}，"
        f"卖出 {counts.get('sell', 0)}。该分布只描述研报样本，不构成交易建议。"
    )


def _forecast_statement(forecasts: list[dict[str, Any]]) -> str:
    if not forecasts:
        return "当前未取得可核验的EPS一致预期。"
    values = "，".join(
        f"{item.get('year')}{'A' if item.get('kind') == 'actual' else 'E'} "
        f"{item.get('value')}"
        for item in forecasts
    )
    return (
        f"每股收益汇总为：{values}。A 表示历史实际值，E 表示券商预测均值；"
        "预测值不是公司正式指引或已实现业绩。"
    )


def _report_view_summary(
    *,
    institution: Any,
    rating: Any,
    previous_rating: Any,
    forecast_eps: list[dict[str, Any]],
) -> str | None:
    institution_text = str(institution or "").strip()
    rating_text = str(rating or "").strip()
    if not institution_text and not rating_text and not forecast_eps:
        return None
    parts = []
    if institution_text and rating_text:
        previous = str(previous_rating or "").strip()
        if previous and previous != rating_text:
            parts.append(
                f"{institution_text}将评级由「{previous}」调整为「{rating_text}」"
            )
        else:
            parts.append(f"{institution_text}给予「{rating_text}」评级")
    elif rating_text:
        parts.append(f"最新评级为「{rating_text}」")
    if forecast_eps:
        values = "，".join(
            f"{item.get('year')}E {item.get('value')}元"
            for item in forecast_eps[:2]
        )
        parts.append(f"预测每股收益（元/股直通值）：{values}")
    return "；".join(parts) + "。" if parts else None


def _difference(current: Any, previous: Any) -> int | None:
    if not isinstance(current, int) or not isinstance(previous, int):
        return None
    return current - previous


def _fingerprint(packet: dict[str, Any]) -> str:
    stable = {
        "symbol": packet.get("symbol"),
        "industry": packet.get("industry"),
        "rating_organization_count": packet.get("rating_organization_count"),
        "rating_counts": packet.get("rating_counts"),
        "forecast_eps": packet.get("forecast_eps"),
        "latest_reports": [
            {
                "title": item.get("title"),
                "institution": item.get("institution"),
                "published_at": item.get("published_at"),
                "rating": item.get("rating"),
                "forecast_eps": item.get("forecast_eps"),
            }
            for item in packet.get("latest_reports") or []
        ],
        "method": packet.get("method"),
    }
    return hashlib.sha256(
        json.dumps(stable, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _is_older_than(value: str | None, seconds: int) -> bool:
    if not value:
        return True
    try:
        timestamp = datetime.fromisoformat(value).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return True
    return datetime.now(timezone.utc) - timestamp > timedelta(seconds=seconds)
