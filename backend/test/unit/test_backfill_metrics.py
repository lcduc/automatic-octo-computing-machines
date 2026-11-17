"""The metrics backfill CLI never rewrites a day whose raw rows retention already purged (no database)."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.models.retention_policy import RetentionPolicy
from scripts.backfill_metrics import MetricsBackfill

TIMEZONE = "Asia/Ho_Chi_Minh"


class FakeRollup:
    def __init__(self):
        self.days = []

    async def rollup_day(self, day):
        self.days.append(day)
        return {"turns": 0, "conversations": 0}


@pytest.mark.asyncio
async def test_backfill_runs_oldest_first_and_stops_at_the_shortest_retention():
    rollup = FakeRollup()
    policy = RetentionPolicy(chat_days=365, anonymous_chat_days=60, trace_days=30, ticket_days=730, audit_days=1095)
    assert await MetricsBackfill(rollup, TIMEZONE).run(400, policy) == 30
    today = datetime.now(ZoneInfo(TIMEZONE)).date()
    assert rollup.days == [today - timedelta(days=offset) for offset in range(29, -1, -1)]

    rollup.days.clear()
    assert await MetricsBackfill(rollup, TIMEZONE).run(3, policy) == 3
    assert rollup.days[-1] == today and rollup.days[0] == today - timedelta(days=2)
