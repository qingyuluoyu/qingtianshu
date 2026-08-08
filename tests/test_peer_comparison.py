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


def save_tushare_row(
    database: Database,
    dataset: str,
    scope_key: str,
    row: dict,
    *,
    as_of_date: str = "20260728",
) -> None:
    run = database.start_tushare_sync_run(
        job_scope=f"peer-test:{dataset}:{scope_key}",
        as_of_date=as_of_date,
        datasets=[dataset],
    )
    database.save_tushare_dataset_snapshot(
        dataset=dataset,
        scope_key=scope_key,
        as_of_date=as_of_date,
        report_period=None,
        source_updated_at="2026-07-28T15:00:00+08:00",
        sync_run_id=run["id"],
        data_version=f"version-{dataset}-{scope_key}-{as_of_date}-{run['id']}",
        data_status="stable",
        payload={"rows": [row]},
    )


def save_a_share_universe(
    database: Database,
    items: list[dict],
    *,
    as_of_date: str = "2026-07-28",
) -> None:
    run = database.start_tushare_sync_run(
        job_scope="peer-test:a-share-universe",
        as_of_date=as_of_date,
        datasets=["stock_basic", "daily_basic"],
    )
    database.save_tushare_dataset_snapshot(
        dataset="a_share_universe",
        scope_key="all",
        as_of_date=as_of_date,
        report_period=None,
        source_updated_at="2026-07-28T15:00:00+08:00",
        sync_run_id=run["id"],
        data_version=f"peer-universe-{as_of_date}-{run['id']}",
        data_status="stable",
        payload={"items": items},
    )


def test_fixed_peer_packet_uses_peer_median_without_rating_language(tmp_path: Path):
    database = Database(tmp_path / "workspaces")
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
    database = Database(tmp_path / "workspaces")
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


def test_catl_peer_packet_uses_fixed_battery_sample(tmp_path: Path):
    database = Database(tmp_path / "workspaces")
    database.initialize()
    values = {
        "300750.SZ": (21.0, 4.8, 1_800_000_000_000.0),
        "300014.SZ": (28.0, 3.2, 180_000_000_000.0),
        "002074.SZ": (34.0, 2.9, 110_000_000_000.0),
        "300207.SZ": (24.0, 2.5, 90_000_000_000.0),
    }
    service = PeerComparisonService(
        database, MappingProvider(values), MappingProvider({})
    )

    packet = service.get_packet("300750.SZ")

    assert packet["group_label"] == "动力与储能电池固定同行样本"
    assert [item["name"] for item in packet["peers"]] == [
        "亿纬锂能",
        "国轩高科",
        "欣旺达",
    ]
    assert packet["coverage"] == {"requested_peers": 3, "available_peers": 3}
    assert packet["metrics"]["pe_ttm"]["peer_median"] == 28.0
    assert packet["metrics"]["pe_ttm"]["subject_to_peer_median"] == 0.75


def test_dynamic_a_share_peer_packet_uses_same_day_industry_and_market_cap(
    tmp_path: Path,
):
    database = Database(tmp_path / "workspaces")
    database.initialize()
    rows = [
        ("600841.SH", "动力新科", "汽车配件", 760_000.0, 2.43, 1.18),
        ("600104.SH", "上汽集团", "汽车配件", 800_000.0, 8.0, 0.8),
        ("000338.SZ", "潍柴动力", "汽车配件", 700_000.0, 10.0, 1.5),
        ("000625.SZ", "长安汽车", "汽车配件", 1_000_000.0, 12.0, 1.9),
        ("002594.SZ", "比亚迪", "汽车配件", 8_000_000.0, 30.0, 5.0),
        ("601398.SH", "工商银行", "银行", 20_000_000.0, 6.0, 0.6),
    ]
    for ts_code, name, industry, total_mv, pe_ttm, pb in rows:
        save_tushare_row(
            database,
            "stock_basic",
            ts_code,
            {
                "ts_code": ts_code,
                "name": name,
                "industry": industry,
            },
        )
        save_tushare_row(
            database,
            "daily_basic",
            ts_code,
            {
                "ts_code": ts_code,
                "trade_date": "20260728",
                "total_mv": total_mv,
                "pe_ttm": pe_ttm,
                "pb": pb,
            },
        )
    service = PeerComparisonService(database, MappingProvider({}), MappingProvider({}))

    packet = service.get_packet("600841.SS")

    assert packet["method"] == "dynamic_same_day_peer_valuation_snapshot_v1"
    assert packet["as_of"] == "2026-07-28"
    assert packet["group_label"] == "汽车配件同日估值样本"
    assert [item["name"] for item in packet["peers"]] == [
        "上汽集团",
        "潍柴动力",
        "长安汽车",
    ]
    assert packet["subject"]["pe_ttm"] == 2.43
    assert packet["metrics"]["pe_ttm"]["peer_median"] == 10.0
    assert packet["metrics"]["pb"]["peer_median"] == 1.5
    assert packet["coverage"] == {"requested_peers": 3, "available_peers": 3}
    assert "总市值最接近" in packet["selection_basis"]


def test_dynamic_peer_packet_prefers_current_full_market_universe_over_stale_symbol(
    tmp_path: Path,
):
    database = Database(tmp_path / "workspaces")
    database.initialize()
    save_tushare_row(
        database,
        "stock_basic",
        "600841.SH",
        {"ts_code": "600841.SH", "name": "动力新科", "industry": "汽车配件"},
        as_of_date="20260227",
    )
    save_tushare_row(
        database,
        "daily_basic",
        "600841.SH",
        {
            "ts_code": "600841.SH",
            "trade_date": "20260227",
            "total_mv_yi": 152.94,
            "pe_ttm": None,
            "pb": None,
        },
        as_of_date="20260227",
    )
    save_a_share_universe(
        database,
        [
            {
                "symbol": "600841.SS",
                "ts_code": "600841.SH",
                "name": "动力新科",
                "industry": "汽车配件",
                "trade_date": "2026-07-28",
                "total_mv_yi": 75.91,
                "pe_ttm": 2.43,
                "pb": 1.18,
            },
            {
                "symbol": "600104.SS",
                "ts_code": "600104.SH",
                "name": "上汽集团",
                "industry": "汽车配件",
                "trade_date": "2026-07-28",
                "total_mv_yi": 80.0,
                "pe_ttm": 8.0,
                "pb": 0.8,
            },
            {
                "symbol": "000338.SZ",
                "ts_code": "000338.SZ",
                "name": "潍柴动力",
                "industry": "汽车配件",
                "trade_date": "2026-07-28",
                "total_mv_yi": 70.0,
                "pe_ttm": 10.0,
                "pb": 1.5,
            },
        ],
    )
    service = PeerComparisonService(database, MappingProvider({}), MappingProvider({}))

    packet = service.get_packet("600841.SS")

    assert packet["as_of"] == "2026-07-28"
    assert packet["subject"]["pe_ttm"] == 2.43
    assert [item["name"] for item in packet["peers"]] == [
        "上汽集团",
        "潍柴动力",
    ]


def test_peer_operating_packet_compares_exact_period_and_persists_knowledge(
    tmp_path: Path,
):
    database = Database(tmp_path / "workspaces")
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
    assert (
        packet["metrics"]["operating_cashflow_to_net_profit"]["peer_sample_size"] == 3
    )
    assert all(item["status"] == "comparable" for item in packet["peers"])
    snapshot = database.latest_peer_operating_snapshot("000063.SZ")
    assert snapshot["payload"]["method"] == "fixed_peer_operating_comparison_v1"
    documents = database.list_knowledge_documents(None)
    assert any(item["source_key"] == "peer-operating:000063.SZ" for item in documents)


def test_peer_operating_packet_excludes_period_mismatch_from_metrics(tmp_path: Path):
    database = Database(tmp_path / "workspaces")
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

    assert ResearchReportService._fingerprint(
        base
    ) != ResearchReportService._fingerprint(changed)
