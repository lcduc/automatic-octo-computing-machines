"""
Daily rollup, alert rules and the job scheduler against a real PostgreSQL.
"""

import uuid
from datetime import datetime, time as dt_time, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
import pytest
from sqlalchemy import text

from app.core.infrastructure.job_scheduler import JobScheduler, ScheduledJob, lock_key
from app.core.storage.metrics_repository import MetricsRepository
from app.core.storage.tables.base import utc_now
from app.core.storage.tables.conversation_tables import Conversation, HandoffRequest, Message, TokenUsage
from app.core.storage.tables.knowledge_tables import KnowledgeDocument
from app.core.storage.tables.observability_tables import MessageTrace
from app.models.usage_policy import UsagePolicy
from app.services import alert_monitor_service
from app.services.alert_monitor_service import ALERT_COOLDOWN, AlertMonitorService
from app.services.metrics_rollup_service import MetricsRollupService

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
    assert today["breakdown"]["step_latency_ms"] == {"first_token": {"p50": 300.0, "p95": 300.0},
                                                     "total": {"p50": 800.0, "p95": 800.0}}
    async with database.session() as session:
        assert await session.scalar(text("SELECT count(*) FROM metrics_daily")) == 2


@pytest.mark.asyncio
async def test_rollup_counts_answer_quality_guard_reasons_and_step_latency(database):
    answers = [  # (outcome, citations, confidence, cached, guard_reason, steps_ms)
        ("answered", [{"source": "faq"}], 0.9, True, None, {"retrieval": 100, "llm": 1000, "note": "n/a"}),
        ("answered", [], 0.2, False, None, {"retrieval": 300, "llm": 2000, "ratio": 0.5}),
        ("answered", [{"source": "faq"}], None, False, None, {"retrieval": 200, "nested": {"ms": 5}}),
        ("blocked", [{"source": "faq"}], 0.1, True, "off_topic", {}),  # not answered: no answer counts
        ("error", [], None, False, "llm_timeout", {"retrieval": 99999999999}),  # too large to cast: skipped
        ("error", [], None, False, "llm_timeout", {}),
    ]
    async with database.session() as session:
        conversation = Conversation(end_user_id="visitor-quality")
        session.add(conversation)
        await session.flush()
        for outcome, citations, confidence, cached, guard_reason, steps_ms in answers:
            answer = Message(conversation_id=conversation.id, role="assistant", content="đáp", outcome=outcome,
                             citations=citations, confidence=confidence, cached=cached, guard_reason=guard_reason)
            session.add(answer)
            await session.flush()
            session.add(MessageTrace(message_id=answer.id, conversation_id=conversation.id, steps_ms=steps_ms))
        session.add(Message(conversation_id=conversation.id, role="user", content="hỏi", guard_reason="user_side"))
        session.add(HandoffRequest(conversation_id=conversation.id, reason="no_knowledge"))
        session.add(HandoffRequest(conversation_id=conversation.id, reason="user_request"))

    rollup = MetricsRollupService(database, TIMEZONE)
    await rollup.run()
    [today] = [row for row in await rollup.history(2) if row["turns"]]
    breakdown = today["breakdown"]
    assert today["handoffs"] == 2 and breakdown["conversations_handed_off"] == 1
    assert breakdown["outcomes"]["answered"] == 3
    assert breakdown["cited_answers"] == 2
    assert breakdown["low_confidence_answers"] == 1
    assert breakdown["cached_answers"] == 1
    assert breakdown["guard_reasons"] == {"off_topic": 1, "llm_timeout": 2}
    assert breakdown["step_latency_ms"] == {
        "retrieval": {"p50": 200.0, "p95": 290.0},
        "llm": {"p50": 1500.0, "p95": 1950.0},
    }


async def _chat(session, visitor, answers, at=None, handoff=False):
    """A conversation of ``visitor`` with one user message per answer time (``None`` = now)."""
    conversation = Conversation(end_user_id=visitor, **({"created_at": at} if at else {}))
    session.add(conversation)
    await session.flush()
    for answered_at in answers:
        stamp = {"created_at": answered_at} if answered_at else {}
        session.add(Message(conversation_id=conversation.id, role="user", content="hỏi", **stamp))
        session.add(Message(conversation_id=conversation.id, role="assistant", content="đáp", outcome="answered", **stamp))
    if handoff:
        session.add(HandoffRequest(conversation_id=conversation.id, reason="user_request"))


@pytest.mark.asyncio
async def test_rollup_counts_visitors_tiers_and_single_turn_conversations(database):
    zone = ZoneInfo(TIMEZONE)
    today = datetime.now(zone).date()
    midnight = datetime.combine(today, dt_time.min, tzinfo=zone)
    yesterday = midnight - timedelta(hours=1)
    async with database.session() as session:
        await _chat(session, "visitor-a", [midnight - timedelta(days=3)], at=midnight - timedelta(days=3))
        await _chat(session, "visitor-a", [None])  # single turn
        await _chat(session, "visitor-a", [yesterday, None], at=yesterday)  # created yesterday: not today's
        await _chat(session, "visitor-b", [None], handoff=True)  # handed off: not single turn
        await _chat(session, "visitor-b", [None, None])  # two answers
        for end_user_id, tier in [("visitor-a", "anonymous"), ("visitor-a", "anonymous"), ("visitor-b", "member"),
                                  ("visitor-b", None), (None, "staff")]:
            session.add(TokenUsage(end_user_id=end_user_id, tier=tier, purpose="answer", provider="openai", model="m"))

    rollup = MetricsRollupService(database, TIMEZONE)
    breakdown = (await rollup.rollup_day(today))["breakdown"]
    assert breakdown["visitors"] == 2
    assert breakdown["returning_visitors"] == 1  # visitor-a had a conversation before today
    assert breakdown["visitors_by_tier"] == {"anonymous": 1, "member": 1, "unknown": 1}  # no visitor id: skipped
    assert breakdown["single_turn_conversations"] == 1
    before = (await rollup.rollup_day(today - timedelta(days=1)))["breakdown"]
    assert before["visitors"] == 1 and before["returning_visitors"] == 1
    assert before["single_turn_conversations"] == 0  # its conversation got a second answer today


@pytest.mark.asyncio
async def test_traffic_counts_user_messages_per_local_weekday_and_hour(database):
    # 2026-11-16 is a Monday; Asia/Ho_Chi_Minh is UTC+7.
    instants = [
        datetime(2026, 11, 16, 2, 30, tzinfo=timezone.utc),  # Monday 09:30 local
        datetime(2026, 11, 16, 2, 59, tzinfo=timezone.utc),  # Monday 09:59 local
        datetime(2026, 11, 22, 17, 15, tzinfo=timezone.utc),  # Sunday 17:15 UTC = Monday 00:15 local
        datetime(2026, 11, 22, 16, 45, tzinfo=timezone.utc),  # Sunday 23:45 local
    ]
    async with database.session() as session:
        conversation = Conversation(end_user_id="visitor-traffic")
        session.add(conversation)
        await session.flush()
        for instant in instants:
            session.add(Message(conversation_id=conversation.id, role="user", content="hỏi", created_at=instant))
            session.add(Message(conversation_id=conversation.id, role="assistant", content="đáp", created_at=instant))

    start, end = datetime(2026, 11, 16, tzinfo=timezone.utc), datetime(2026, 11, 23, tzinfo=timezone.utc)
    async with database.session() as session:
        grid = await MetricsRepository(session).traffic(start, end, TIMEZONE)
    assert len(grid) == 7 and all(len(row) == 24 for row in grid)
    assert grid[0][9] == 2 and grid[0][0] == 1 and grid[6][23] == 1
    assert sum(map(sum, grid)) == 4  # assistant messages are not traffic


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
