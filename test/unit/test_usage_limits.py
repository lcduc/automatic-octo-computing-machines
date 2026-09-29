"""Time buckets and the usage policy (pure logic; no database)."""

from datetime import datetime, timezone

import pytest

from models.usage_policy import UsagePolicy
from services.rate_limit_service import TimeBuckets, hashed

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
