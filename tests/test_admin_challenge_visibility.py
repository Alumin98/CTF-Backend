from datetime import datetime, timedelta, timezone

from app.routes.admin_challenges import _as_naive_utc


def test_as_naive_utc_returns_none_for_none():
    assert _as_naive_utc(None) is None


def test_as_naive_utc_noops_for_naive_datetime():
    naive = datetime(2025, 10, 14, 9, 0, 0)
    assert _as_naive_utc(naive) is naive


def test_as_naive_utc_normalizes_timezone_aware_datetime():
    aware = datetime(2025, 10, 14, 9, 0, 0, tzinfo=timezone(timedelta(hours=2)))
    normalized = _as_naive_utc(aware)
    assert normalized == datetime(2025, 10, 14, 7, 0, 0)
    assert normalized.tzinfo is None
