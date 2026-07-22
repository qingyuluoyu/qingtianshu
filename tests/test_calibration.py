from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.db import Database
from app.services.analysis import analyze_history, build_conditional_outlook
from app.services.calibration import (
    OutlookCalibrationService,
    attach_outlook_calibration,
    build_walk_forward_calibration,
    generate_walk_forward_records,
)


def make_points(count: int = 500) -> list[dict]:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    points = []
    close = 100.0
    for index in range(count):
        regime = (index // 80) % 3
        drift = 0.45 if regime == 0 else -0.35 if regime == 1 else 0.03
        close = max(10.0, close + drift + ((index % 7) - 3) * 0.06)
        points.append(
            {
                "timestamp": (start + timedelta(days=index)).isoformat(timespec="seconds"),
                "open": close - 0.2,
                "high": close + 0.5,
                "low": close - 0.5,
                "close": close,
                "volume": 1_000_000 + index,
            }
        )
    return points


def test_walk_forward_signal_uses_only_prefix_and_non_overlapping_future_window():
    points = make_points(180)
    records = generate_walk_forward_records(points, horizon=10)
    assert records
    assert all(
        right["signal_index"] - left["signal_index"] == 10
        for left, right in zip(records, records[1:])
    )
    for record in records:
        index = record["signal_index"]
        prefix = points[: index + 1]
        metrics = analyze_history({"points": prefix})
        recent = prefix[-20:]
        levels = {
            "recent_20d_high": max(item["high"] for item in recent),
            "recent_20d_low": min(item["low"] for item in recent),
            "ma20": metrics["ma20"],
            "ma60": metrics["ma60"],
        }
        expected = build_conditional_outlook(metrics, levels)
        assert record["label"] == expected["label"]
        assert record["evaluated_at"] == points[index + 10]["timestamp"]


def test_calibration_uses_last_thirty_percent_as_chronological_holdout():
    calibration = build_walk_forward_calibration(make_points())
    ten_day = calibration["horizons"]["10d"]
    in_sample = ten_day["in_sample"]
    out_of_sample = ten_day["out_of_sample"]
    assert ten_day["total_samples"] > 20
    assert out_of_sample["sample_size"] > 0
    assert in_sample["period"]["last_evaluated_at"] <= out_of_sample["period"][
        "first_signal_at"
    ]
    assert sum(
        item["sample_size"] for item in out_of_sample["by_label"].values()
    ) == out_of_sample["sample_size"]
    assert calibration["method"] == "fixed_rule_prequential_oos_v2"
    assert calibration["history"]["price_basis"] == "adjusted_close_when_available"


def test_attached_calibration_never_becomes_future_probability():
    outlook = build_conditional_outlook(
        {
            "latest_close": 110.0,
            "ma20": 105.0,
            "ma60": 100.0,
            "return_20d_pct": 8.0,
            "volatility_20d_annualized_pct": 20.0,
        },
        {"recent_20d_high": 112.0, "recent_20d_low": 96.0},
    )
    calibration = {
        "method": "fixed_rule_prequential_oos_v2",
        "horizons": {
            "10d": {
                "total_samples": 40,
                "out_of_sample": {
                    "sample_size": 12,
                    "period": {
                        "first_signal_at": "2025-01-01T00:00:00+00:00",
                        "last_evaluated_at": "2026-01-01T00:00:00+00:00",
                    },
                    "by_label": {
                        "偏强观察": {
                            "sample_size": 9,
                            "median_forward_return_pct": 2.1,
                            "p25_forward_return_pct": -1.0,
                            "p75_forward_return_pct": 4.0,
                            "historical_positive_share": 0.667,
                            "direction_consistency": 0.667,
                            "reliability": "directionally_consistent",
                        }
                    },
                },
            }
        },
    }
    attached = attach_outlook_calibration(outlook, calibration, "偏强观察")
    assert attached["method"] == "transparent_rule_based_outlook_v2"
    assert attached["probability"] is None
    assert attached["calibration"]["historical_analog"]["sample_size"] == 9
    assert "历史频率不等于未来概率" in attached["warning"]


def test_calibration_service_persists_latest_snapshot(tmp_path: Path):
    points = make_points(300)

    class Provider:
        def fetch_history(self, symbol, range_name="5y"):
            return {
                "symbol": symbol,
                "source": "fake history",
                "fetched_at": "2026-07-20T00:00:00+00:00",
                "points": points,
            }

    database = Database(tmp_path / "db.sqlite", tmp_path / "workspaces")
    database.initialize()
    service = OutlookCalibrationService(database, Provider())
    packet = service.get_packet("NVDA")
    assert packet["symbol"] == "NVDA"
    assert packet["history_points"] == 300
    stored = database.latest_outlook_calibration("NVDA")
    assert stored["calibration"]["method"] == "fixed_rule_prequential_oos_v2"
