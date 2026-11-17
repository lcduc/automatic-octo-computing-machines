"""Time buckets, the usage policy and the month-end spend projection (pure logic; no database)."""

from datetime import datetime, timezone

import pytest

from app.models.usage_policy import UsagePolicy
from app.services.rate_limit_service import TimeBuckets, hashed
from app.services.usage_service import project_month_spend

# 2026-09-30 23:30 in Ho Chi Minh City (UTC+7).
NOW = datetime(2026, 9, 30, 16, 30, 45, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "window, start, end",
    [
        ("minute", "2026-09-30T23:30:00+07:00", "2026-09-30T23:31:00+07:00"),
        ("hour", "2026-09-30T23:00:00+07:00", "2026-10-01T00:00:00+07:00"),
        ("day", "2026-09-30T00:00:00+07:00", "2026-10-01T00:00:00+07:00"),
        ("month", "2026-09-01T00:00:00+07:00", "2026-10-01T00:00:00+07:00"),
    ],
)
def test_buckets_follow_the_local_calendar(window, start, end):
    buckets = TimeBuckets("Asia/Ho_Chi_Minh", clock=lambda: NOW)
    bucket = buckets.start(window)
    assert bucket.isoformat() == start
    assert buckets.end(window, bucket).isoformat() == end


def test_december_rolls_into_the_next_year():
    buckets = TimeBuckets("Asia/Ho_Chi_Minh", clock=lambda: datetime(2026, 12, 15, tzinfo=timezone.utc))
    assert buckets.end("month", buckets.start("month")).isoformat() == "2027-01-01T00:00:00+07:00"


def test_policy_picks_the_tier_and_pauses_anonymous_visitors_first():
    policy = UsagePolicy(10, 60, 30_000, 20, 200, 200_000, 400_000, spend_cap_usd=100, anonymous_cutoff_ratio=0.9)
    assert policy.for_caller(logged_in=False) == (10, 60, 30_000)
    assert policy.for_caller(logged_in=True) == (20, 200, 200_000)
    assert policy.spend_limit_micro_usd(logged_in=True) == 100_000_000
    assert policy.spend_limit_micro_usd(logged_in=False) == 90_000_000


def test_personal_data_in_counter_keys_is_hashed():
    assert hashed("203.0.113.7") == hashed("203.0.113.7")
    assert "203.0.113.7" not in hashed("203.0.113.7") and len(hashed("x")) == 24


def _september(now_utc):
    """``(now, month start, month end)`` of September 2026 in Ho Chi Minh City."""
    buckets = TimeBuckets("Asia/Ho_Chi_Minh", clock=lambda: now_utc)
    start = buckets.start("month")
    return buckets.now(), start, buckets.end("month", start)


@pytest.mark.parametrize(
    "now_utc, spent, projected",
    [
        (datetime(2026, 9, 15, 17, tzinfo=timezone.utc), 1_500_000, 3_000_000),  # half of a 30-day month
        (datetime(2026, 9, 1, 17, tzinfo=timezone.utc), 100_000, 3_000_000),  # exactly one day in
        (datetime(2026, 9, 15, 17, tzinfo=timezone.utc), 0, 0),
        (datetime(2026, 9, 1, 16, 59, tzinfo=timezone.utc), 100_000, None),  # still the first local day
    ],
)
def test_month_spend_is_projected_linearly_after_the_first_day(now_utc, spent, projected):
    assert project_month_spend(spent, *_september(now_utc)) == projected
