"""
Retention purge (PRV-04, RET-R1/R2/R4) against a real PostgreSQL.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import DBAPIError

from core.storage.tables.access_tables import ROLE_EDITOR, ROLE_OWNER
from core.storage.tables.audit_tables import AdminAuditEntry
from core.storage.tables.conversation_tables import (
    HANDOFF_STATUS_CLOSED,
    HANDOFF_STATUS_OPEN,
    Conversation,
    HandoffRequest,
    Message,
)
from core.storage.tables.observability_tables import DailyMetrics, MessageTrace
from services.errors import PermissionDeniedError
from services.metrics_rollup_service import MetricsRollupService
from services.rate_limit_service import RateLimitService, TimeBuckets
from services.retention_service import RetentionService
from services.settings_service import SettingsService

TIMEZONE = "Asia/Ho_Chi_Minh"
NOW = datetime.now(timezone.utc)


def _ago(days):
    return NOW - timedelta(days=days)


async def _conversation(session, label, idle_days, user_id=None, legal_hold=False, trace_days=None):
    conversation = Conversation(end_user_id=f"visitor-{label}", user_id=user_id, legal_hold=legal_hold,
                                created_at=_ago(idle_days), last_activity_at=_ago(idle_days))
    session.add(conversation)
    await session.flush()
    answer = Message(conversation_id=conversation.id, role="assistant", content=label, outcome="answered",
                     created_at=_ago(idle_days))
    session.add(answer)
    await session.flush()
    if trace_days is not None:
        session.add(MessageTrace(message_id=answer.id, conversation_id=conversation.id, route="rag",
                                 created_at=_ago(trace_days)))
    return conversation


async def _ticket(session, conversation, age_days, status=HANDOFF_STATUS_CLOSED, legal_hold=False):
    ticket = HandoffRequest(conversation_id=conversation.id, reason="user_request", status=status,
                            legal_hold=legal_hold, created_at=_ago(age_days))
    session.add(ticket)
    await session.flush()
    return ticket.id


def _service(database):
    return RetentionService(
        database, SettingsService(database), MetricsRollupService(database, TIMEZONE),
        RateLimitService(database, TimeBuckets(TIMEZONE)), clock=lambda: NOW,
    )


@pytest.mark.asyncio
async def test_purge_honours_periods_holds_and_tickets(database):
    async with database.session() as session:
        old_anonymous = await _conversation(session, "old-anon", 100)
        recent_anonymous = await _conversation(session, "recent-anon", 30, trace_days=30)
        signed_in = await _conversation(session, "user", 100, user_id="u1", trace_days=100)
        old_signed_in = await _conversation(session, "old-user", 400, user_id="u2")
        held = await _conversation(session, "held", 400, legal_hold=True, trace_days=400)
        with_ticket = await _conversation(session, "ticket", 400)
        kept_ticket = await _ticket(session, with_ticket, 100)
        old_ticket = await _ticket(session, recent_anonymous, 800)
        held_ticket = await _ticket(session, recent_anonymous, 800, legal_hold=True)
        open_ticket = await _ticket(session, recent_anonymous, 800, status=HANDOFF_STATUS_OPEN)
        session.add(AdminAuditEntry(method="PATCH", path="/old", status_code=200, created_at=_ago(1200)))
        session.add(AdminAuditEntry(method="PATCH", path="/new", status_code=200, created_at=_ago(10)))
        ids = {c.id for c in (old_anonymous, recent_anonymous, signed_in, old_signed_in, held, with_ticket)}

    counts = await _service(database).purge()

    async with database.session() as session:
        left = set((await session.execute(select(Conversation.id).where(Conversation.id.in_(ids)))).scalars())
        tickets = set((await session.execute(select(HandoffRequest.id))).scalars())
        traces = set((await session.execute(select(MessageTrace.conversation_id))).scalars())
        audit = set((await session.execute(select(AdminAuditEntry.path))).scalars())
        rollups = (await session.execute(select(func.count()).select_from(DailyMetrics))).scalar_one()

    assert left == {recent_anonymous.id, signed_in.id, held.id, with_ticket.id}
    assert tickets == {kept_ticket, held_ticket, open_ticket}
    assert old_ticket not in tickets
    # The 100-day trace goes (traces keep 90 days); held and recent ones stay.
    assert traces == {recent_anonymous.id, held.id}
    assert audit == {"/new"}
    assert counts["conversations"] == 2 and counts["tickets"] == 1 and counts["audit_entries"] == 1
    assert rollups > 0, "the rollup runs before anything is deleted"


@pytest.mark.asyncio
async def test_owner_changes_to_retention_reach_the_purge(database):
    async with database.session() as session:
        conversation = await _conversation(session, "anon-40", 40)
    await SettingsService(database).update({"retention_anonymous_chat_days": 30}, "owner@example.com")

    await _service(database).purge()

    async with database.session() as session:
        assert await session.get(Conversation, conversation.id) is None


@pytest.mark.asyncio
async def test_recent_audit_entries_stay_immutable(database):
    async with database.session() as session:
        session.add(AdminAuditEntry(method="PATCH", path="/recent", status_code=200, created_at=_ago(30)))
    with pytest.raises(DBAPIError, match="append-only"):
        async with database.session() as session:
            await session.execute(delete(AdminAuditEntry))


def test_only_owners_change_retention():
    SettingsService.check_role(["retention_chat_days"], ROLE_OWNER)
    SettingsService.check_role(["widget_title"], ROLE_EDITOR)
    with pytest.raises(PermissionDeniedError):
        SettingsService.check_role(["widget_title", "retention_chat_days"], ROLE_EDITOR)
