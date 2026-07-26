from datetime import datetime, timezone

from app.services.background import is_china_pre_market_refresh_due


def test_pre_market_refresh_runs_once_after_china_target_time_on_weekday():
    now = datetime(2026, 7, 24, 0, 5, tzinfo=timezone.utc)  # 08:05 China time

    assert is_china_pre_market_refresh_due(now, None, hour=7, minute=30) is True


def test_pre_market_refresh_does_not_repeat_on_same_china_date_or_weekend():
    now = datetime(2026, 7, 24, 0, 5, tzinfo=timezone.utc)
    same_day = datetime(2026, 7, 23, 23, 35, tzinfo=timezone.utc)  # 07:35 China
    saturday = datetime(2026, 7, 25, 0, 5, tzinfo=timezone.utc)

    assert is_china_pre_market_refresh_due(now, same_day, hour=7, minute=30) is False
    assert is_china_pre_market_refresh_due(saturday, None, hour=7, minute=30) is False
