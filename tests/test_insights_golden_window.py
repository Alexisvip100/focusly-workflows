"""The golden window is reported in the user's local time, not UTC."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.modules.insights.services.insights_service import InsightsService


def _sessions_at_utc(hour: int, count: int = 3):
    """A morning block each day: one session at `hour`, the next an hour later."""
    return [
        SimpleNamespace(startedAt=datetime(2026, 11, 2 + day, hour + extra, 0), durationMinutes=50)
        for day in range(count)
        for extra in (0, 1)
    ]


def test_golden_window_uses_the_users_time_zone():
    # 9 AM in Mexico City (UTC-6) is 15:00 UTC
    result = InsightsService(db=MagicMock()).calculate_golden_window(
        _sessions_at_utc(15), timezone_offset_minutes=360
    )
    assert result["value"] == "9 AM - 11 AM"


def test_golden_window_without_offset_stays_in_utc():
    result = InsightsService(db=MagicMock()).calculate_golden_window(_sessions_at_utc(15))
    assert result["value"] == "3 PM - 5 PM"


def test_golden_window_east_of_utc():
    # 10 AM in Madrid (UTC+1, offset -60) is 09:00 UTC
    result = InsightsService(db=MagicMock()).calculate_golden_window(
        _sessions_at_utc(9), timezone_offset_minutes=-60
    )
    assert result["value"] == "10 AM - 12 PM"


def test_golden_window_accepts_iso_strings():
    sessions = [
        SimpleNamespace(startedAt="2026-11-02T15:30:00Z", durationMinutes=50),
        SimpleNamespace(startedAt="2026-11-02T16:30:00Z", durationMinutes=50),
    ]
    result = InsightsService(db=MagicMock()).calculate_golden_window(
        sessions, timezone_offset_minutes=360
    )
    assert result["value"] == "9 AM - 11 AM"
