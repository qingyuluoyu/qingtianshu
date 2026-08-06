from __future__ import annotations

from pathlib import Path

from app.db import Database
from app.services.peer_comparison import PeerComparisonService, _business_profile
from app.services.research_reports import ResearchReportService


class MappingProvider:
    def __init__(self, values):
        self.values = values

    def fetch_valuation(self, symbol: str):
        pe_ttm, pb, market_cap = self.values[symbol]
        return {
            "symbol": symbol,
            "name": symbol,
            "currency": "CNY" if symbol.endswith((".SS", ".SZ")) else "USD",
            "price": 100.0,
            "previous_close": 99.0,
            "pct_change": 1.01,
            "turnover_rate_pct": None,
            "pe_ttm": pe_ttm,
            "pe_dynamic": None,
            "pe_static": None,
            "pb": pb,
            "float_market_cap": market_cap * 0.8,
            "total_market_cap": market_cap,
            "market_timestamp": "2026-07-20T15:00:00+08:00",
            "source": "Mapping valuation",
            "source_url": "https://example.invalid/valuation",
            "fetched_at": "2026-07-20T07:01:00+00:00",
            "field_mapping": "mapping_v1",
            "warnings": [],
        }


def financial_period(
    symbol: str,
    name: str,
    *,
    report_date: str = "2026-03-31",
    revenue_yoy: float,
    profit_yoy: float,
    gross_margin: float,
    cashflow_ratio: float,
):
    profit = 1_000_000_000.0
    return {
        "symbol": symbol,
        "name": name,
        "report_date": report_date,
        "report_type": "一季报",
        "report_date_name": "2026一季报" if report_date == "2026-03-31" else "2025年报",
        "notice_date": "2026-04-25",
        "currency": "CNY",
        "eps_basic": 1.0,
        "eps_diluted": None,
        "book_value_per_share": 10.0,
        "revenue": 10_000_000_000.0,
        "revenue_yoy_pct": revenue_yoy,
        "parent_net_profit": profit,
        "net_profit_yoy_pct": profit_yoy,
        "roe_weighted_pct": 8.0,
        "gross_margin_pct": gross_margin,
        "net_margin_pct": 10.0,
        "debt_asset_ratio_pct": 45.0,
        "operating_cashflow": profit * cashflow_ratio,
        "operating_cashflow_per_share": 0.8,
        "total_assets": 50_000_000_000.0,
        "total_liabilities": 22_500_000_000.0,
        "total_equity": 27_500_000_000.0,
        "period_basis": "year_to_date_cumulative",
        "source": "Mapped financials",
        "source_url": "https://example.invalid/financials",
        "fetched_at": "2026-07-21T08:00:00+00:00",
        "warnings": [],
    }


def save_business_profile(database: Database, symbol: str, name: str) -> None:
    packet = {
        "type": "business_structure",
        "symbol": symbol,
        "name": name,
        "status": "available",
        "generated_at": "2026-07-21T08:00:00+00:00",
        "method": "deterministic_business_structure_v1",
        "anchor_report_date": "2025-12-31",
        "dimensions": [
            {
                "classification": "product",
                "label": "按产品",
                "segments": [
                    {
                        "item_name": f"{name}核心业务",
                        "revenue_share_pct": 60.0,
                        "gross_margin_pct": 30.0,
                    }
                ],
            }
        ],
        "coverage_limits": ["季度不披露分部构成"],
    }
    database.save_business_structure_snapshot(packet, f"profile-{symbol}")


def test_fixed_peer_packet_uses_peer_median_without_rating_language(tmp_path: Path):
    database = Database(tmp_path / "db.sqlite", tmp_path / "workspaces")
    database.initialize()
    values = {
        "000063.SZ": (40.0, 3.0, 100_000_000_000.0),
        "600498.SS": (20.0, 2.0, 50_000_000_000.0),
        "000938.SZ": (30.0, 4.0, 80_000_000_000.0),
        "301165.SZ": (100.0, 6.0, 120_000_000_000.0),
    }
    service = PeerComparisonService(
        database, MappingProvider(values), MappingProvider({})
    )

    packet = service.get_packet("000063.SZ")

    assert packet["coverage"] == {"requested_peers": 3, "available_peers": 3}
    assert [item["name"] for item in packet["peers"]] == [
        "烽火通信",
        "紫光股份",
        "锐捷网络",
    ]
    pe = packet["metrics"]["pe_ttm"]
    assert pe["subject_value"] == 40.0
    assert pe["peer_median"] == 30.0
    assert pe["subject_to_peer_median"] == 1.333
    assert packet["method"] == "fixed_peer_valuation_snapshot_v1"
    assert "rating" not in packet
    assert any("不允许直接改写" in warning for warning in packet["warnings"])


def test_peer_refresh_persists_subject_and_all_peers(tmp_path: Path):
    database = Database(tmp_path / "db.sqlite", tmp_path / "workspaces")
    database.initialize()
    values = {
        "000063.SZ": (40.0, 3.0, 100.0),
        "600498.SS": (20.0, 2.0, 50.0),
        "000938.SZ": (30.0, 4.0, 80.0),
        "301165.SZ": (100.0, 6.0, 120.0),
    }
    service = PeerComparisonService(
        database, MappingProvider(values), MappingProvider({})
    )

    result = service.refresh_symbol("000063.SZ")

    assert result["completed"] == 4
    assert database.latest_valuation_snapshot("301165.SZ")["pe_ttm"] == 100.0


def test_peer_operating_packet_compares_exact_period_and_persists_knowledge(
    tmp_path: Path,
):
    database = Database(tmp_path / "db.sqlite", tmp_path / "workspaces")
    database.initialize()
    rows = [
        financial_period(
            "000063.SZ",
            "中兴通讯",
            revenue_yoy=6.0,
            profit_yoy=-46.0,
            gross_margin=28.0,
            cashflow_ratio=-1.5,
        ),
        financial_period(
            "600498.SS",
            "烽火通信",
            revenue_yoy=10.0,
            profit_yoy=12.0,
            gross_margin=24.0,
            cashflow_ratio=0.8,
        ),
        financial_period(
            "000938.SZ",
            "紫光股份",
            revenue_yoy=20.0,
            profit_yoy=18.0,
            gross_margin=22.0,
            cashflow_ratio=1.1,
        ),
        financial_period(
            "301165.SZ",
            "锐捷网络",
            revenue_yoy=30.0,
            profit_yoy=24.0,
            gross_margin=40.0,
            cashflow_ratio=1.4,
        ),
    ]
    database.upsert_financial_periods(rows)
    for row in rows:
        save_business_profile(database, row["symbol"], row["name"])
    service = PeerComparisonService(database, MappingProvider({}), MappingProvider({}))

    packet = service.get_operating_packet("000063.SZ")

    assert packet["status"] == "available"
    assert packet["anchor_report_date"] == "2026-03-31"
    assert packet["coverage"] == {
        "requested_peers": 3,
        "same_period_financial_peers": 3,
        "business_profile_peers": 3,
    }
    assert packet["metrics"]["revenue_yoy_pct"]["peer_median"] == 20.0
    assert packet["metrics"]["operating_cashflow_to_net_profit"][
        "peer_sample_size"
    ] == 3
    assert all(item["status"] == "comparable" for item in packet["peers"])
    snapshot = database.latest_peer_operating_snapshot("000063.SZ")
    assert snapshot["payload"]["method"] == "fixed_peer_operating_comparison_v1"
    documents = database.list_knowledge_documents(None)
    assert any(
        item["source_key"] == "peer-operating:000063.SZ" for item in documents
    )


def test_peer_operating_packet_excludes_period_mismatch_from_metrics(tmp_path: Path):
    database = Database(tmp_path / "db.sqlite", tmp_path / "workspaces")
    database.initialize()
    database.upsert_financial_periods(
        [
            financial_period(
                "000063.SZ",
                "中兴通讯",
                revenue_yoy=6.0,
                profit_yoy=-46.0,
                gross_margin=28.0,
                cashflow_ratio=-1.5,
            ),
            financial_period(
                "600498.SS",
                "烽火通信",
                revenue_yoy=10.0,
                profit_yoy=12.0,
                gross_margin=24.0,
                cashflow_ratio=0.8,
            ),
            financial_period(
                "000938.SZ",
                "紫光股份",
                revenue_yoy=20.0,
                profit_yoy=18.0,
                gross_margin=22.0,
                cashflow_ratio=1.1,
            ),
            financial_period(
                "301165.SZ",
                "锐捷网络",
                report_date="2025-12-31",
                revenue_yoy=30.0,
                profit_yoy=24.0,
                gross_margin=40.0,
                cashflow_ratio=1.4,
            ),
        ]
    )
    service = PeerComparisonService(database, MappingProvider({}), MappingProvider({}))

    packet = service.get_operating_packet("000063.SZ")

    assert packet["status"] == "partial"
    assert packet["coverage"]["same_period_financial_peers"] == 2
    assert packet["metrics"]["revenue_yoy_pct"]["peer_sample_size"] == 2
    mismatch = next(item for item in packet["peers"] if item["symbol"] == "301165.SZ")
    assert mismatch["status"] == "period_mismatch"
    assert mismatch["financial"] is None


def test_peer_business_profile_keeps_negative_consolidation_adjustment():
    profile = _business_profile(
        {
            "payload": {
                "status": "available",
                "anchor_report_date": "2025-12-31",
                "dimensions": [
                    {
                        "classification": "product",
                        "label": "按产品",
                        "segments": [
                            {
                                "item_name": "ICT基础设施与服务",
                                "revenue_share_pct": 79.43,
                                "gross_margin_pct": 16.51,
                            },
                            {
                                "item_name": "IT产品分销与供应链服务",
                                "revenue_share_pct": 26.42,
                                "gross_margin_pct": 5.2,
                            },
                            {
                                "item_name": "合并抵消",
                                "revenue_share_pct": -6.35,
                                "gross_margin_pct": None,
                            },
                        ],
                    }
                ],
            }
        }
    )

    assert profile is not None
    assert [item["item_name"] for item in profile["top_segments"]] == [
        "ICT基础设施与服务",
        "IT产品分销与供应链服务",
    ]
    assert profile["composition_adjustments"] == [
        {
            "item_name": "合并抵消",
            "revenue_share_pct": -6.35,
            "gross_margin_pct": None,
        }
    ]


def test_background_refresh_builds_peer_operating_snapshots_and_health(app):
    result = app.state.background._refresh_peer_valuations()

    assert result["completed"] == 3
    assert result["operating_completed"] >= 2
    zte = app.state.database.latest_peer_operating_snapshot("000063.SZ")
    assert zte["payload"]["coverage"]["same_period_financial_peers"] == 3
    checks = app.state.data_health._peer_operating_checks()
    assert {item["key"] for item in checks} == {
        "peer-operating:000063.SZ",
        "peer-operating:300308.SZ",
    }
    assert all(item["status"] == "healthy" for item in checks)


def test_research_report_fingerprint_changes_with_peer_operating_evidence():
    base = {
        "symbol": "000063.SZ",
        "peer_comparison": {
            "metrics": {},
            "operating_comparison": {
                "status": "available",
                "anchor_report_date": "2026-03-31",
                "coverage": {"same_period_financial_peers": 3},
                "metrics": {
                    "gross_margin_pct": {
                        "subject_value": 28.0,
                        "peer_median": 30.0,
                        "peer_sample_size": 3,
                    }
                },
                "peers": [],
            },
        },
    }
    changed = {
        **base,
        "peer_comparison": {
            **base["peer_comparison"],
            "operating_comparison": {
                **base["peer_comparison"]["operating_comparison"],
                "metrics": {
                    "gross_margin_pct": {
                        "subject_value": 28.0,
                        "peer_median": 35.0,
                        "peer_sample_size": 3,
                    }
                },
            },
        },
    }

    assert ResearchReportService._fingerprint(base) != ResearchReportService._fingerprint(
        changed
    )
