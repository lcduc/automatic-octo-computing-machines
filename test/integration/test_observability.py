"""
Daily rollup, alert rules and the job scheduler against a real PostgreSQL.
"""

import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import text

from core.infrastructure.job_scheduler import JobScheduler, ScheduledJob, lock_key
from core.storage.tables.base import utc_now
from core.storage.tables.conversation_tables import Conversation, HandoffRequest, Message, TokenUsage
from core.storage.tables.knowledge_tables import KnowledgeDocument
from core.storage.tables.observability_tables import MessageTrace
from models.usage_policy import UsagePolicy
from services import alert_monitor_service
from services.alert_monitor_service import ALERT_COOLDOWN, AlertMonitorService
from services.metrics_rollup_service import MetricsRollupService

TIMEZONE = "Asia/Ho_Chi_Minh"


class FakeNotifier:
    def __init__(self):
        self.sent = []

    async def send(self, subject, body):
        self.sent.append((subject, body))


class FakeSettings:
    def __init__(self, spend_cap_usd=0.0):
        self.spend_cap_usd = spend_cap_usd

    async def load(self):
        return None

    def usage_policy(self):
        return UsagePolicy(10, 100, 1000, 10, 100, 1000, 1000, self.spend_cap_usd, 0.5)


class FakeUsage:
    def __init__(self):
        self.cost_micro_usd = 0

    async def month_spend(self):
        return {"tokens": 0, "cost_micro_usd": self.cost_micro_usd}


class Clock:
    def __init__(self):
        self.now = datetime.now(timezone.utc)

    def __call__(self):
        return self.now


async def _conversation(database, outcomes, latency_ms=800):
    async with database.session() as session:
        conversation = Conversation(end_user_id="visitor-obs")
        session.add(conversation)
        await session.flush()
        for outcome in outcomes:
            session.add(Message(conversation_id=conversation.id, role="user", content="hỏi"))
            answer = Message(conversation_id=conversation.id, role="assistant", content="đáp", outcome=outcome, latency_ms=latency_ms)
            session.add(answer)
            await session.flush()
            session.add(MessageTrace(message_id=answer.id, conversation_id=conversation.id, route="rag", intent="rag",
                                     steps_ms={"first_token": 300, "total": latency_ms}))
            session.add(TokenUsage(conversation_id=conversation.id, message_id=answer.id, purpose="answer", provider="openai",
                                   model="gpt-test", prompt_tokens=100, completion_tokens=20, cost_micro_usd=50, tier="anonymous"))
        return conversation.id


@pytest.mark.asyncio
async def test_rollup_aggregates_the_day_and_is_idempotent(database):
    conversation_id = await _conversation(database, ["answered", "answered", "error"])
    async with database.session() as session:
        session.add(HandoffRequest(conversation_id=conversation_id, reason="user_request"))

    rollup = MetricsRollupService(database, TIMEZONE)
    assert await rollup.run() == 1
    assert await rollup.run() == 2  # yesterday and today are always recomputed
    [today] = [row for row in await rollup.history(2) if row["turns"]]
    assert today["turns"] == 3 and today["errors"] == 1 and today["conversations"] == 1 and today["handoffs"] == 1
    assert today["p95_latency_ms"] == 800 and today["p95_first_token_ms"] == 300
    assert today["prompt_tokens"] == 300 and today["cost_micro_usd"] == 150
    assert today["breakdown"]["cost_by_model"] == {"gpt-test": 150}
    assert today["breakdown"]["handoff_reasons"] == {"user_request": 1}
    assert today["breakdown"]["routes"] == {"rag": 3}
    async with database.session() as session:
        assert await session.scalar(text("SELECT count(*) FROM metrics_daily")) == 2


def _monitor(database, notifier, clock, settings=None, usage=None, ready=None, disk_path="."):
    factory = None
    if ready is not None:
        factory = lambda: httpx.AsyncClient(transport=httpx.MockTransport(ready))  # noqa: E731
    return AlertMonitorService(database, notifier, settings or FakeSettings(), usage or FakeUsage(), disk_path,
                               "http://api/health/ready" if ready else "", factory, clock)


@pytest.mark.asyncio
async def test_error_spike_alerts_once_per_cooldown_and_resolves(database):
    notifier, clock = FakeNotifier(), Clock()
    monitor = _monitor(database, notifier, clock)
    await _conversation(database, ["error"] * 6 + ["answered"])

    assert await monitor.check() == ["error_spike"]
    assert "6 of 7 answers failed" in notifier.sent[0][1]
    assert await monitor.check() == []  # still firing, inside the cool-down
    async with database.session() as session:  # the cool-down has passed
        await session.execute(text("UPDATE alert_states SET last_sent_at = :sent"),
                              {"sent": clock() - ALERT_COOLDOWN - timedelta(minutes=1)})
    assert await monitor.check() == ["error_spike"]
    assert len(notifier.sent) == 2
    clock.now += timedelta(hours=1)  # the errors are now outside the window
    assert await monitor.check() == ["error_spike"]
    assert notifier.sent[-1][0].startswith("Resolved")


@pytest.mark.asyncio
async def test_overdue_tickets_service_down_disk_and_jobs(database, monkeypatch):
    notifier, clock = FakeNotifier(), Clock()
    conversation_id = await _conversation(database, ["handoff"])
    async with database.session() as session:
        session.add(HandoffRequest(conversation_id=conversation_id, reason="no_knowledge", due_at=clock() - timedelta(hours=2)))

    def not_ready(request):
        return httpx.Response(503, json={"status": "unavailable", "checks": {"database": True, "llm": False}})

    usage_tuple = type("Usage", (), {"total": 100, "used": 91, "free": 9})
    monkeypatch.setattr(alert_monitor_service.shutil, "disk_usage", lambda path: usage_tuple)
    monitor = _monitor(database, notifier, clock, ready=not_ready)
    assert sorted(await monitor.check()) == ["disk_usage", "overdue_tickets", "service_down"]
    subjects = {subject: body for subject, body in notifier.sent}
    assert "Failing checks: llm." in subjects["Chat API is not ready"]
    assert "91% full" in subjects["Disk almost full"]

    await monitor.job_failed("metrics_rollup", RuntimeError("boom"))
    assert notifier.sent[-1][0] == "Scheduled job 'metrics_rollup' failed"
    await monitor.job_succeeded("metrics_rollup")
    assert notifier.sent[-1][0].startswith("Resolved")
    await monitor.job_succeeded("metrics_rollup")  # nothing to resolve twice
    assert len(notifier.sent) == 5


@pytest.mark.asyncio
async def test_spend_levels_and_failed_uploads_alert_once(database):
    notifier, clock, usage = FakeNotifier(), Clock(), FakeUsage()
    monitor = _monitor(database, notifier, clock, settings=FakeSettings(spend_cap_usd=10.0), usage=usage)
    assert await monitor.check() == []  # first run bookmarks the upload failures

    usage.cost_micro_usd = 6_000_000  # past the 50% anonymous cut-off
    async with database.session() as session:
        source_id = await session.scalar(text("SELECT id FROM knowledge_sources LIMIT 1"))
        session.add(KnowledgeDocument(id=uuid.uuid4(), source_id=source_id, title="Bảng giá", original_filename="gia.pdf",
                                      status="failed", processed_at=utc_now()))
    assert sorted(await monitor.check()) == ["ingestion_failed", "spend"]
    assert await monitor.check() == []
    usage.cost_micro_usd = 10_000_000
    assert await monitor.check() == ["spend"]
    assert notifier.sent[-1][0] == "Monthly spend cap reached"
    assert await monitor.check() == []


@pytest.mark.asyncio
async def test_scheduler_skips_a_job_locked_elsewhere_and_reports_failures(database):
    calls, failures = [], []

    async def works():
        calls.append("ran")

    async def breaks():
        raise RuntimeError("broken job")

    async def on_failure(name, error):
        failures.append((name, str(error)))

    now = [0.0]
    scheduler = JobScheduler(database, [ScheduledJob("works", 60, works), ScheduledJob("breaks", 60, breaks)],
                             on_failure=on_failure, clock=lambda: now[0])
    assert await scheduler.run_due() == []  # the first run waits for start-up
    now[0] = 61.0
    async with database.engine.connect() as other_worker:
        await other_worker.execute(text("SELECT pg_advisory_lock(:key)"), {"key": lock_key("works")})
        assert await scheduler.run_due() == ["breaks"]
        await other_worker.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": lock_key("works")})
    assert failures == [("breaks", "broken job")] and calls == []
    now[0] = 200.0
    assert await scheduler.run_due() == ["works", "breaks"]
    assert calls == ["ran"]
