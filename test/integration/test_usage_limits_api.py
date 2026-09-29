"""
Durable limits end to end (real app and PostgreSQL): counters shared across
service instances, per-IP token budgets, prices and cost per call, the spend
cap pausing anonymous visitors first, and the LISTEN/NOTIFY live feed.
"""

import asyncio

from core.storage.tables.usage_tables import WINDOW_MINUTE
from services.live_feed_service import LiveFeedService, asyncpg_dsn
from services.rate_limit_service import Limit, RateLimitService, TimeBuckets
from .conftest import TEST_DATABASE_URL
from .test_api import BFF_TOKEN, _admin_headers, client  # noqa: F401  (fixture)

FAQ = {"source": "FAQ", "title": "Giờ làm việc", "content": "Văn phòng mở cửa từ 8 giờ sáng các ngày trong tuần"}


def _ask(http, visitor):
    # Every TestClient request comes from the same client address.
    headers = {"X-Service-Token": BFF_TOKEN, "X-End-User-Id": visitor}
    return http.post("/api/v1/chat/stream", json={"message": FAQ["content"]}, headers=headers)


def _seed(http):
    admin = _admin_headers(http)
    assert http.post("/api/v1/admin/knowledge/documents/text", json=FAQ, headers=admin).status_code == 201
    return admin


def test_counters_are_shared_by_every_service_instance(client):  # noqa: F811
    database = client.app.state.container.database
    first = RateLimitService(database, TimeBuckets("Asia/Ho_Chi_Minh"))
    second = RateLimitService(database, TimeBuckets("Asia/Ho_Chi_Minh"))  # e.g. after a restart
    limit = [Limit("test:shared", WINDOW_MINUTE, 2)]
    assert client.portal.call(first.hit, limit) is None
    assert client.portal.call(second.hit, limit) is None
    assert client.portal.call(first.hit, limit) >= 1


def test_prices_set_the_cost_of_each_call_and_the_ip_budget_spans_visitors(client, monkeypatch):  # noqa: F811
    admin = _seed(client)
    price = {"input_usd_per_million": "1.000000", "output_usd_per_million": "4.000000"}
    assert client.put("/api/v1/admin/prices/fake-main", json=price, headers=admin).status_code == 200
    assert _ask(client, "visitor-aaaa01").status_code == 200

    summary = client.get("/api/v1/admin/usage/summary", headers=admin).json()
    # The fake answer model reports 120 prompt + 30 completion tokens: 120*1 + 30*4 micro-dollars.
    assert summary["month"]["cost_micro_usd"] == 240
    assert summary["totals"]["cost_micro_usd"] == 240
    assert {row["tier"] for row in summary["by_tier"]} == {"anonymous"}

    # Visitors behind one IP share its daily budget, so a new visitor id (cleared cookies) does not reset it.
    patch = {"tokens_ip_per_day": 100}
    assert client.patch("/api/v1/admin/settings", json=patch, headers=admin).status_code == 200
    refused = _ask(client, "visitor-bbbb02")
    assert refused.status_code == 429 and "hết lượt" in refused.json()["detail"]


def test_spend_cap_pauses_anonymous_visitors_before_signed_in_users(client):  # noqa: F811
    admin = _seed(client)
    client.put("/api/v1/admin/prices/fake-main",
               json={"input_usd_per_million": "1000", "output_usd_per_million": "1000"}, headers=admin)
    assert _ask(client, "visitor-dddd04").status_code == 200  # costs 150k micro-dollars
    patch = {"spend_cap_monthly_usd": 0.16, "spend_anonymous_cutoff_ratio": 0.5}
    assert client.patch("/api/v1/admin/settings", json=patch, headers=admin).status_code == 200
    paused = _ask(client, "visitor-eeee05")
    assert paused.status_code == 429 and "chưa đăng nhập" in paused.json()["detail"]
    assert int(paused.headers["retry-after"]) > 0


def test_live_events_reach_listeners_in_other_processes(client):  # noqa: F811
    database = client.app.state.container.database

    async def roundtrip():
        other_process = LiveFeedService(database, asyncpg_dsn(TEST_DATABASE_URL))
        await other_process.start()
        try:
            assert await other_process.wait_listening(10)
            queue = other_process.subscribe()
            await client.app.state.container.live_feed.publish({"type": "handoff", "handoff_id": "h-1"})
            return await asyncio.wait_for(queue.get(), 10)
        finally:
            await other_process.stop()

    assert client.portal.call(roundtrip) == {"type": "handoff", "handoff_id": "h-1"}
