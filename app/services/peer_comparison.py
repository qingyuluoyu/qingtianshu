from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from statistics import median
from typing import Any

from app.catalog import PEER_GROUPS, RESEARCH_TARGETS, normalize_symbol
from app.db import Database
from app.providers.fundamentals import AShareFundamentalsProvider
from app.providers.us_fundamentals import USEquityFundamentalsProvider
from app.utils import utc_now


def _is_older_than(value: str | None, seconds: int) -> bool:
    if not value:
        return True
    try:
        timestamp = datetime.fromisoformat(value).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return True
    return datetime.now(timezone.utc) - timestamp > timedelta(seconds=seconds)


def _metric_summary(
    subject: dict[str, Any] | None,
    peers: list[dict[str, Any]],
    key: str,
) -> dict[str, Any] | None:
    peer_values = [
        float(item[key])
        for item in peers
        if isinstance(item.get(key), (int, float)) and float(item[key]) > 0
    ]
    if len(peer_values) < 2:
        return None
    peer_median = float(median(peer_values))
    subject_value = (
        float(subject[key])
        if subject
        and isinstance(subject.get(key), (int, float))
        and float(subject[key]) > 0
        else None
    )
    return {
        "subject_value": subject_value,
        "peer_median": round(peer_median, 6),
        "peer_min": round(min(peer_values), 6),
        "peer_max": round(max(peer_values), 6),
        "peer_sample_size": len(peer_values),
        "subject_to_peer_median": (
            round(subject_value / peer_median, 3)
            if subject_value is not None and peer_median != 0
            else None
        ),
    }


def _ratio(numerator: Any, denominator: Any) -> float | None:
    if not isinstance(numerator, (int, float)) or not isinstance(
        denominator, (int, float)
    ):
        return None
    if float(denominator) == 0:
        return None
    return round(float(numerator) / float(denominator), 4)


def _operating_metric_summary(
    subject: dict[str, Any] | None,
    peers: list[dict[str, Any]],
    key: str,
) -> dict[str, Any] | None:
    peer_values = [
        float(item[key]) for item in peers if isinstance(item.get(key), (int, float))
    ]
    if len(peer_values) < 2:
        return None
    subject_value = (
        float(subject[key])
        if subject and isinstance(subject.get(key), (int, float))
        else None
    )
    return {
        "subject_value": subject_value,
        "peer_median": round(float(median(peer_values)), 6),
        "peer_min": round(min(peer_values), 6),
        "peer_max": round(max(peer_values), 6),
        "peer_sample_size": len(peer_values),
    }


def _public_financial_period(period: dict[str, Any] | None) -> dict[str, Any] | None:
    if not period:
        return None
    return {
        key: period.get(key)
        for key in (
            "symbol",
            "name",
            "report_date",
            "report_type",
            "report_date_name",
            "notice_date",
            "currency",
            "revenue",
            "revenue_yoy_pct",
            "parent_net_profit",
            "net_profit_yoy_pct",
            "roe_weighted_pct",
            "gross_margin_pct",
            "net_margin_pct",
            "debt_asset_ratio_pct",
            "operating_cashflow",
            "period_basis",
            "source",
            "source_url",
            "fetched_at",
        )
    }


def _operating_row(period: dict[str, Any] | None) -> dict[str, Any] | None:
    public = _public_financial_period(period)
    if public is None:
        return None
    public["operating_cashflow_to_net_profit"] = _ratio(
        public.get("operating_cashflow"), public.get("parent_net_profit")
    )
    return public


def _business_profile(snapshot: dict[str, Any] | None) -> dict[str, Any] | None:
    payload = (snapshot or {}).get("payload") or snapshot or {}
    if payload.get("status") != "available":
        return None
    dimensions = payload.get("dimensions") or []
    preferred = next(
        (item for item in dimensions if item.get("classification") == "product"),
        None,
    ) or next(
        (item for item in dimensions if item.get("classification") == "industry"),
        None,
    )
    segments = []
    adjustments = []
    for item in (preferred or {}).get("segments") or []:
        public_item = {
            "item_name": item.get("item_name"),
            "revenue_share_pct": item.get("revenue_share_pct"),
            "gross_margin_pct": item.get("gross_margin_pct"),
        }
        share = item.get("revenue_share_pct")
        if (
            isinstance(share, (int, float))
            and float(share) < 0
            or "抵消" in str(item.get("item_name") or "")
        ):
            adjustments.append(public_item)
        else:
            segments.append(public_item)
    return {
        "anchor_report_date": payload.get("anchor_report_date"),
        "dimension": (preferred or {}).get("classification"),
        "dimension_label": (preferred or {}).get("label"),
        "top_segments": segments[:3],
        "composition_adjustments": adjustments[:3],
        "coverage_limits": payload.get("coverage_limits") or [],
    }


class PeerComparisonService:
    OPERATING_METHOD = "fixed_peer_operating_comparison_v1"

    def __init__(
        self,
        database: Database,
        a_share_provider: AShareFundamentalsProvider,
        us_provider: USEquityFundamentalsProvider,
        fundamentals_service: Any | None = None,
        us_fundamentals_service: Any | None = None,
        business_structure_service: Any | None = None,
    ):
        self.database = database
        self.a_share_provider = a_share_provider
        self.us_provider = us_provider
        self.fundamentals_service = fundamentals_service
        self.us_fundamentals_service = us_fundamentals_service
        self.business_structure_service = business_structure_service

    def _group(self, symbol: str) -> dict[str, Any]:
        group = PEER_GROUPS.get(symbol)
        if group is not None:
            return group
        return self._dynamic_a_share_group(symbol)

    @staticmethod
    def _snapshot_rows(record: dict[str, Any] | None) -> list[dict[str, Any]]:
        rows = ((record or {}).get("payload") or {}).get("rows") or []
        return [dict(row) for row in rows if isinstance(row, dict)]

    @staticmethod
    def _date_string(value: Any) -> str | None:
        digits = "".join(
            character for character in str(value or "") if character.isdigit()
        )
        if len(digits) < 8:
            return None
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"

    @staticmethod
    def _number(value: Any) -> float | None:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) else None

    def _dynamic_a_share_group(self, symbol: str) -> dict[str, Any]:
        canonical = normalize_symbol(symbol)
        if not canonical.endswith((".SS", ".SZ")):
            raise ValueError("该证券尚未配置固定同行样本")

        stock_by_symbol: dict[str, dict[str, Any]] = {}
        valuation_by_symbol: dict[str, dict[str, Any]] = {}
        universe = self.database.latest_tushare_dataset_snapshot(
            "a_share_universe", "all"
        )
        universe_items = ((universe or {}).get("payload") or {}).get("items") or []
        for raw_item in universe_items:
            if not isinstance(raw_item, dict):
                continue
            item = dict(raw_item)
            raw_symbol = str(item.get("symbol") or item.get("ts_code") or "").strip()
            if not raw_symbol:
                continue
            row_symbol = normalize_symbol(raw_symbol)
            stock_by_symbol[row_symbol] = item
            valuation_by_symbol[row_symbol] = {
                **item,
                "snapshot_as_of_date": (universe or {}).get("as_of_date"),
                "snapshot_created_at": (universe or {}).get("created_at"),
                "data_version": (universe or {}).get("data_version"),
            }

        if not stock_by_symbol or canonical not in valuation_by_symbol:
            stock_records = self.database.list_latest_tushare_dataset_snapshots(
                "stock_basic",
                data_status="stable",
                limit=20_000,
            )
            valuation_records = self.database.list_latest_tushare_dataset_snapshots(
                "daily_basic",
                data_status="stable",
                limit=20_000,
            )
            for record in stock_records:
                for row in self._snapshot_rows(record)[:1]:
                    raw_symbol = str(row.get("ts_code") or "").strip()
                    if not raw_symbol:
                        continue
                    row_symbol = normalize_symbol(raw_symbol)
                    if row_symbol:
                        stock_by_symbol[row_symbol] = row
            for record in valuation_records:
                for row in self._snapshot_rows(record)[:1]:
                    raw_symbol = str(row.get("ts_code") or "").strip()
                    if not raw_symbol:
                        continue
                    row_symbol = normalize_symbol(raw_symbol)
                    if not row_symbol:
                        continue
                    valuation_by_symbol[row_symbol] = {
                        **row,
                        "snapshot_as_of_date": record.get("as_of_date"),
                        "snapshot_created_at": record.get("created_at"),
                        "data_version": record.get("data_version"),
                    }

        subject_basic = stock_by_symbol.get(canonical) or {}
        subject_valuation = valuation_by_symbol.get(canonical) or {}
        industry = str(subject_basic.get("industry") or "").strip()
        subject_market_cap = self._market_cap_cny(subject_valuation)
        subject_date = self._date_string(
            subject_valuation.get("trade_date")
            or subject_valuation.get("snapshot_as_of_date")
        )
        if not industry or subject_market_cap in {None, 0} or not subject_date:
            raise ValueError("该证券尚缺少可建立同日同行估值样本的行业或市值数据")

        candidates: list[tuple[float, str, dict[str, Any]]] = []
        for peer_symbol, peer_basic in stock_by_symbol.items():
            if peer_symbol == canonical:
                continue
            if str(peer_basic.get("industry") or "").strip() != industry:
                continue
            peer_valuation = valuation_by_symbol.get(peer_symbol) or {}
            if (
                self._date_string(
                    peer_valuation.get("trade_date")
                    or peer_valuation.get("snapshot_as_of_date")
                )
                != subject_date
            ):
                continue
            peer_market_cap = self._market_cap_cny(peer_valuation)
            pe_ttm = self._number(peer_valuation.get("pe_ttm"))
            pb = self._number(peer_valuation.get("pb"))
            name = str(peer_basic.get("name") or "").strip()
            if (
                peer_market_cap in {None, 0}
                or pe_ttm is None
                or pe_ttm <= 0
                or pb is None
                or pb <= 0
                or not name
                or "ST" in name.upper()
            ):
                continue
            distance = abs(math.log(float(peer_market_cap) / float(subject_market_cap)))
            candidates.append(
                (
                    distance,
                    peer_symbol,
                    {
                        "symbol": peer_symbol,
                        "name": name,
                        "valuation": peer_valuation,
                    },
                )
            )
        selected = [item for _, _, item in sorted(candidates)[:3]]
        if len(selected) < 2:
            raise ValueError("同日同业且估值字段完整的可比公司不足两家")
        return {
            "label": f"{industry}同日估值样本",
            "basis": (
                f"在生产数据库{subject_date}同一Tushare行业标签“{industry}”内，"
                "选择总市值最接近且PE TTM、PB均有效的最多3家公司；"
                "该样本不是完整行业指数或投资评级"
            ),
            "peers": selected,
            "dynamic": True,
            "industry": industry,
            "as_of_date": subject_date,
            "subject": {
                "symbol": canonical,
                "name": str(subject_basic.get("name") or canonical),
                "valuation": subject_valuation,
            },
        }

    @classmethod
    def _market_cap_cny(cls, valuation: dict[str, Any]) -> float | None:
        value_yi = cls._number(valuation.get("total_mv_yi"))
        if value_yi is not None:
            return value_yi * 100_000_000.0
        tushare_value = cls._number(valuation.get("total_mv"))
        if tushare_value is not None:
            return tushare_value * 10_000.0
        return None

    @classmethod
    def _dynamic_public_valuation(
        cls,
        item: dict[str, Any],
        *,
        fallback_symbol: str,
        fallback_name: str,
        as_of_date: str,
    ) -> dict[str, Any]:
        valuation = item.get("valuation") or {}
        return {
            "symbol": str(item.get("symbol") or fallback_symbol),
            "name": str(item.get("name") or fallback_name),
            "currency": "CNY",
            "pe_ttm": cls._number(valuation.get("pe_ttm")),
            "pb": cls._number(valuation.get("pb")),
            "total_market_cap": cls._market_cap_cny(valuation),
            "market_timestamp": f"{as_of_date}T15:00:00+08:00",
            "source": "Tushare Pro daily_basic stable snapshot",
        }

    def _dynamic_packet(
        self,
        canonical: str,
        group: dict[str, Any],
    ) -> dict[str, Any]:
        as_of_date = str(group.get("as_of_date") or "")
        subject_entry = group.get("subject") or {}
        subject = self._dynamic_public_valuation(
            subject_entry,
            fallback_symbol=canonical,
            fallback_name=canonical,
            as_of_date=as_of_date,
        )
        public_peers = [
            self._dynamic_public_valuation(
                item,
                fallback_symbol=str(item.get("symbol") or ""),
                fallback_name=str(item.get("name") or item.get("symbol") or "同行"),
                as_of_date=as_of_date,
            )
            for item in group.get("peers") or []
        ]
        metrics = {
            key: summary
            for key in ("pe_ttm", "pb", "total_market_cap")
            if (summary := _metric_summary(subject, public_peers, key)) is not None
        }
        return {
            "symbol": canonical,
            "name": subject.get("name") or canonical,
            "group_label": group["label"],
            "selection_basis": group["basis"],
            "generated_at": utc_now(),
            "as_of": as_of_date,
            "subject": subject,
            "peers": public_peers,
            "metrics": metrics,
            "coverage": {
                "requested_peers": len(group.get("peers") or []),
                "available_peers": len(public_peers),
            },
            "operating_comparison": self._build_operating_packet(canonical, group),
            "refresh": None,
            "warnings": [
                "同行样本来自同一交易日、同一Tushare行业标签和同一估值字段口径，不是完整行业指数或投资评级。",
                "样本按总市值接近度确定；业务结构、会计口径和成长阶段差异仍需单独核对。",
                "样本比较不允许直接改写成高估、低估、便宜或昂贵。",
            ],
            "method": "dynamic_same_day_peer_valuation_snapshot_v1",
        }

    def _fetch_valuation(self, symbol: str) -> dict[str, Any]:
        if symbol.endswith((".SS", ".SZ")):
            return self.a_share_provider.fetch_valuation(symbol)
        return self.us_provider.fetch_valuation(symbol)

    def refresh_symbol(self, symbol: str) -> dict[str, Any]:
        canonical = normalize_symbol(symbol)
        group = self._group(canonical)
        if group.get("dynamic"):
            packet = self._dynamic_packet(canonical, group)
            return {
                "symbol": canonical,
                "refreshed_at": utc_now(),
                "requested": 1 + len(group.get("peers") or []),
                "completed": 1 + len(packet.get("peers") or []),
                "results": [
                    {
                        "symbol": item.get("symbol"),
                        "status": "ok",
                        "market_timestamp": item.get("market_timestamp"),
                    }
                    for item in [
                        packet.get("subject") or {},
                        *(packet.get("peers") or []),
                    ]
                ],
                "operating_comparison": {
                    "status": (packet.get("operating_comparison") or {}).get("status"),
                    "anchor_report_date": (
                        packet.get("operating_comparison") or {}
                    ).get("anchor_report_date"),
                    "coverage": (packet.get("operating_comparison") or {}).get(
                        "coverage"
                    )
                    or {},
                },
            }
        symbols = [canonical, *(item["symbol"] for item in group["peers"])]
        results = []
        for peer_symbol in symbols:
            try:
                valuation = self._fetch_valuation(peer_symbol)
                self.database.save_valuation_snapshot(valuation)
                results.append(
                    {
                        "symbol": peer_symbol,
                        "status": "ok",
                        "market_timestamp": valuation.get("market_timestamp"),
                    }
                )
            except Exception as exc:
                results.append(
                    {
                        "symbol": peer_symbol,
                        "status": "failed",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
        operating = self.refresh_operating_symbol(canonical)
        return {
            "symbol": canonical,
            "refreshed_at": utc_now(),
            "requested": len(symbols),
            "completed": sum(item["status"] == "ok" for item in results),
            "results": results,
            "operating_comparison": {
                "status": operating.get("status"),
                "anchor_report_date": operating.get("anchor_report_date"),
                "coverage": operating.get("coverage") or {},
            },
        }

    def get_packet(
        self, symbol: str, refresh_max_age_seconds: int = 3600
    ) -> dict[str, Any]:
        canonical = normalize_symbol(symbol)
        group = self._group(canonical)
        if group.get("dynamic"):
            return self._dynamic_packet(canonical, group)
        subject = self.database.latest_valuation_snapshot(canonical)
        peers = []
        for item in group["peers"]:
            valuation = self.database.latest_valuation_snapshot(item["symbol"])
            if valuation:
                peers.append(valuation)
        should_refresh = (
            subject is None
            or len(peers) < len(group["peers"])
            or _is_older_than(
                subject.get("fetched_at") if subject else None,
                refresh_max_age_seconds,
            )
            or any(
                _is_older_than(item.get("fetched_at"), refresh_max_age_seconds)
                for item in peers
            )
        )
        refresh = None
        if should_refresh:
            refresh = self.refresh_symbol(canonical)
            subject = self.database.latest_valuation_snapshot(canonical)
            peers = [
                valuation
                for item in group["peers"]
                if (
                    valuation := self.database.latest_valuation_snapshot(item["symbol"])
                )
            ]

        peer_name_by_symbol = {item["symbol"]: item["name"] for item in group["peers"]}
        public_peers = []
        for item in peers:
            public_peers.append(
                {
                    "symbol": item["symbol"],
                    "name": peer_name_by_symbol.get(item["symbol"]) or item.get("name"),
                    "currency": item.get("currency"),
                    "pe_ttm": item.get("pe_ttm"),
                    "pb": item.get("pb"),
                    "total_market_cap": item.get("total_market_cap"),
                    "market_timestamp": item.get("market_timestamp"),
                    "source": item.get("source"),
                }
            )
        metrics = {
            key: summary
            for key in ("pe_ttm", "pb", "total_market_cap")
            if (summary := _metric_summary(subject, public_peers, key)) is not None
        }
        timestamps = [
            item.get("market_timestamp")
            for item in [subject or {}, *public_peers]
            if item.get("market_timestamp")
        ]
        target = RESEARCH_TARGETS.get(canonical) or {}
        operating = self.get_operating_packet(canonical)
        return {
            "symbol": canonical,
            "name": target.get("name") or (subject or {}).get("name") or canonical,
            "group_label": group["label"],
            "selection_basis": group["basis"],
            "generated_at": utc_now(),
            "as_of": max(timestamps) if timestamps else None,
            "subject": (
                {
                    "symbol": canonical,
                    "name": target.get("name") or subject.get("name"),
                    "currency": subject.get("currency"),
                    "pe_ttm": subject.get("pe_ttm"),
                    "pb": subject.get("pb"),
                    "total_market_cap": subject.get("total_market_cap"),
                    "market_timestamp": subject.get("market_timestamp"),
                    "source": subject.get("source"),
                }
                if subject
                else None
            ),
            "peers": public_peers,
            "metrics": metrics,
            "coverage": {
                "requested_peers": len(group["peers"]),
                "available_peers": len(public_peers),
            },
            "operating_comparison": operating,
            "refresh": refresh,
            "warnings": [
                "同行样本由产品固定配置，不是完整行业指数或投资评级。",
                "不同公司业务结构、会计口径和成长阶段不同；相对倍数只能作为进一步研究线索。",
                "样本比较不允许直接改写成高估、低估、便宜或昂贵。",
            ],
            "method": "fixed_peer_valuation_snapshot_v1",
        }

    def get_operating_packet(
        self, symbol: str, refresh_max_age_seconds: int = 21_600
    ) -> dict[str, Any]:
        canonical = normalize_symbol(symbol)
        group = self._group(canonical)
        if group.get("dynamic"):
            return self._build_operating_packet(canonical, group)
        snapshot = self.database.latest_peer_operating_snapshot(canonical)
        current_periods = self.database.list_financial_periods(canonical, limit=1)
        current_report_date = (
            current_periods[0].get("report_date") if current_periods else None
        )
        if snapshot:
            payload = dict(snapshot.get("payload") or {})
            if payload.get(
                "anchor_report_date"
            ) == current_report_date and not _is_older_than(
                snapshot.get("created_at"), refresh_max_age_seconds
            ):
                payload["cache_hit"] = True
                return payload
        return self.refresh_operating_symbol(canonical)

    def refresh_operating_symbol(self, symbol: str) -> dict[str, Any]:
        canonical = normalize_symbol(symbol)
        group = self._group(canonical)
        symbols = [canonical, *(item["symbol"] for item in group["peers"])]
        for item_symbol in symbols:
            if item_symbol.endswith((".SS", ".SZ")):
                if self.fundamentals_service is not None:
                    try:
                        self.fundamentals_service.get_packet(
                            item_symbol, refresh_max_age_seconds=3600
                        )
                    except Exception:
                        pass
                if self.business_structure_service is not None:
                    try:
                        self.business_structure_service.get_packet(item_symbol)
                    except Exception:
                        pass
            elif self.us_fundamentals_service is not None:
                try:
                    self.us_fundamentals_service.get_packet(item_symbol)
                except Exception:
                    pass

        packet = self._build_operating_packet(canonical, group)
        if packet.get("anchor_report_date"):
            stable = {
                key: value
                for key, value in packet.items()
                if key
                not in {
                    "generated_at",
                    "snapshot_id",
                    "snapshot_created_at",
                    "cache_hit",
                }
            }
            fingerprint = hashlib.sha256(
                json.dumps(
                    stable, ensure_ascii=False, sort_keys=True, default=str
                ).encode("utf-8")
            ).hexdigest()
            saved = self.database.save_peer_operating_snapshot(packet, fingerprint)
            packet["snapshot_id"] = saved["id"]
            packet["snapshot_created_at"] = saved["created_at"]
            self._index_common_knowledge(packet)
        return packet

    def _build_operating_packet(
        self, canonical: str, group: dict[str, Any]
    ) -> dict[str, Any]:
        target = RESEARCH_TARGETS.get(canonical) or {}
        subject_periods = self.database.list_financial_periods(canonical, limit=8)
        if not subject_periods:
            return {
                "type": "peer_operating_comparison",
                "symbol": canonical,
                "name": target.get("name") or canonical,
                "status": "unavailable",
                "generated_at": utc_now(),
                "anchor_report_date": None,
                "subject": None,
                "peers": [],
                "metrics": {},
                "coverage": {
                    "requested_peers": len(group["peers"]),
                    "same_period_financial_peers": 0,
                    "business_profile_peers": 0,
                },
                "missing_items": ["本标的结构化财务报告期不可用"],
                "warnings": ["缺少本标的报告期时不能建立同行经营比较。"],
                "method": self.OPERATING_METHOD,
            }

        anchor = subject_periods[0]
        anchor_date = str(anchor.get("report_date"))
        anchor_basis = anchor.get("period_basis")
        subject_financial = _operating_row(anchor)
        subject_structure = _business_profile(
            self.database.latest_business_structure_snapshot(canonical)
        )
        peer_name_by_symbol = {item["symbol"]: item["name"] for item in group["peers"]}
        peers = []
        comparable_financials = []
        missing_items = []
        for peer in group["peers"]:
            peer_symbol = peer["symbol"]
            periods = self.database.list_financial_periods(peer_symbol, limit=8)
            comparable = next(
                (
                    item
                    for item in periods
                    if str(item.get("report_date")) == anchor_date
                    and item.get("period_basis") == anchor_basis
                ),
                None,
            )
            financial = _operating_row(comparable)
            latest = _public_financial_period(periods[0] if periods else None)
            structure = _business_profile(
                self.database.latest_business_structure_snapshot(peer_symbol)
            )
            if financial:
                comparable_financials.append(financial)
            else:
                missing_items.append(
                    f"{peer_name_by_symbol.get(peer_symbol) or peer_symbol}缺少与{anchor_date}同报告期的结构化财务"
                )
            peers.append(
                {
                    "symbol": peer_symbol,
                    "name": peer_name_by_symbol.get(peer_symbol) or peer_symbol,
                    "status": "comparable" if financial else "period_mismatch",
                    "financial": financial,
                    "latest_available_financial": latest,
                    "business_profile": structure,
                }
            )

        metric_keys = (
            "revenue_yoy_pct",
            "net_profit_yoy_pct",
            "gross_margin_pct",
            "net_margin_pct",
            "operating_cashflow_to_net_profit",
            "debt_asset_ratio_pct",
        )
        metrics = {
            key: summary
            for key in metric_keys
            if (
                summary := _operating_metric_summary(
                    subject_financial, comparable_financials, key
                )
            )
            is not None
        }
        comparable_count = len(comparable_financials)
        business_count = sum(bool(item.get("business_profile")) for item in peers)
        status = (
            "available"
            if comparable_count == len(group["peers"])
            else "partial"
            if comparable_count
            else "unavailable"
        )
        return {
            "type": "peer_operating_comparison",
            "symbol": canonical,
            "name": target.get("name")
            or (subject_financial or {}).get("name")
            or canonical,
            "status": status,
            "group_label": group["label"],
            "selection_basis": group["basis"],
            "generated_at": utc_now(),
            "anchor_report_date": anchor_date,
            "anchor_report_type": anchor.get("report_type"),
            "anchor_report_date_name": anchor.get("report_date_name"),
            "anchor_period_basis": anchor_basis,
            "subject": {
                "symbol": canonical,
                "name": target.get("name")
                or (subject_financial or {}).get("name")
                or canonical,
                "financial": subject_financial,
                "business_profile": subject_structure,
            },
            "peers": peers,
            "metrics": metrics,
            "coverage": {
                "requested_peers": len(group["peers"]),
                "same_period_financial_peers": comparable_count,
                "business_profile_peers": business_count,
            },
            "missing_items": missing_items,
            "warnings": [
                "只比较相同报告日和相同累计口径；报告期不一致的公司不会进入中位数。",
                "同行业务结构不同，增长率、利润率和现金流差异不能直接改写成公司优劣或交易评级。",
                "主营构成通常来自最近年报或中报，只用于解释业务底盘，不能冒充当季利润归因。",
            ],
            "method": self.OPERATING_METHOD,
        }

    def _index_common_knowledge(self, packet: dict[str, Any]) -> None:
        source_key = f"peer-operating:{packet['symbol']}"
        document_id = (
            "peer-operating-"
            + hashlib.sha256(source_key.encode("utf-8")).hexdigest()[:20]
        )
        metric_labels = {
            "revenue_yoy_pct": "营收同比",
            "net_profit_yoy_pct": "净利润同比",
            "gross_margin_pct": "毛利率",
            "net_margin_pct": "净利率",
            "operating_cashflow_to_net_profit": "经营现金流/净利润",
            "debt_asset_ratio_pct": "资产负债率",
        }
        metric_lines = []
        for key, metric in (packet.get("metrics") or {}).items():
            metric_lines.append(
                f"- {metric_labels.get(key, key)}：本标的 {metric.get('subject_value')}，"
                f"同行中位数 {metric.get('peer_median')}，样本 {metric.get('peer_sample_size')} 家"
            )
        peer_lines = []
        comparison_rows = [packet.get("subject") or {}, *(packet.get("peers") or [])]
        for item in comparison_rows:
            financial = item.get("financial") or {}
            profile = item.get("business_profile") or {}
            segments = "、".join(
                f"{segment.get('item_name')} {segment.get('revenue_share_pct')}%"
                for segment in (profile.get("top_segments") or [])
                if segment.get("item_name")
            )
            adjustments = "、".join(
                f"{segment.get('item_name')} {segment.get('revenue_share_pct')}%"
                for segment in (profile.get("composition_adjustments") or [])
                if segment.get("item_name")
            )
            status_label = (
                "同报告期可比"
                if item is comparison_rows[0] or item.get("status") == "comparable"
                else "报告期不匹配"
            )
            peer_lines.append(
                f"- {item.get('name')}（{item.get('symbol')}）："
                f"{status_label}，营收同比 {financial.get('revenue_yoy_pct')}%，"
                f"净利润同比 {financial.get('net_profit_yoy_pct')}%，毛利率 {financial.get('gross_margin_pct')}%，"
                f"经营现金流 {financial.get('operating_cashflow')}，"
                f"经营现金流/净利润 {financial.get('operating_cashflow_to_net_profit')}；"
                f"主营构成报告期 {profile.get('anchor_report_date') or '未取得'}"
                + (f"，主要业务 {segments}" if segments else "")
                + (f"，构成调整项 {adjustments}" if adjustments else "")
            )
        business_periods = [
            str((item.get("business_profile") or {}).get("anchor_report_date"))
            for item in comparison_rows
            if (item.get("business_profile") or {}).get("anchor_report_date")
        ]
        business_period_note = (
            f"四家公司主营构成报告期均为 {business_periods[0]}，但产品分类名称不是统一分类口径。"
            if len(business_periods) == len(comparison_rows)
            and len(set(business_periods)) == 1
            else "各公司主营构成报告期必须逐家读取，不能默认视为同一报告期。"
        )
        content = (
            f"# {packet.get('name')}固定同行经营比较\n\n"
            f"财务报告期：{packet.get('anchor_report_date_name') or packet.get('anchor_report_date')}；"
            "只纳入相同报告日和相同累计口径。\n\n"
            "## 同口径指标\n\n"
            + ("\n".join(metric_lines) or "暂无至少两家同报告期样本。")
            + "\n\n## 同行明细\n\n"
            + "\n".join(peer_lines)
            + "\n\n## 主营构成口径\n\n- "
            + business_period_note
            + "\n\n## 边界\n\n"
            + "\n".join(f"- {item}" for item in packet.get("warnings") or [])
        )
        self.database.upsert_knowledge_document(
            document_id=document_id,
            scope="common",
            title=f"{packet.get('name')}固定同行经营与主营构成",
            original_name=f"{packet['symbol']}-peer-operating.md",
            mime_type="text/markdown",
            content=content,
            source_key=source_key,
            owner_user_id=None,
        )

    def refresh_symbols(self, symbols: list[str]) -> dict[str, Any]:
        results = []
        for symbol in sorted(set(symbols)):
            try:
                result = self.refresh_symbol(symbol)
                results.append(
                    {
                        "symbol": result["symbol"],
                        "status": "ok" if result["completed"] >= 3 else "partial",
                        "completed": result["completed"],
                        "requested": result["requested"],
                        "operating_status": (
                            result.get("operating_comparison") or {}
                        ).get("status"),
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
            "requested": len(set(symbols)),
            "completed": sum(item["status"] in {"ok", "partial"} for item in results),
            "results": results,
        }
