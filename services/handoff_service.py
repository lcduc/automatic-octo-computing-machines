"""
Transfer-to-human as asynchronous tickets (HND-13..16).

A handoff opens a ticket due within the configured working hours. The visitor
may leave contact details (anonymous visitors must, with consent, PRV-02).
Support staff assign, answer and close tickets in the admin web; an answer is
e-mailed when an address was given and is also added to the conversation, so
the visitor sees it in the chat on their next visit (HND-15).
"""

# Standard library imports
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

# Local imports
from core.infrastructure.smtp_mailer import MailDeliveryError, SmtpMailer
from core.storage.conversation_repository import ConversationRepository
from core.storage.database import Database
from core.storage.tables.base import utc_now
from core.storage.tables.conversation_tables import (
    CONVERSATION_STATUS_ACTIVE,
    CONVERSATION_STATUS_HANDOFF,
    CONVERSATION_STATUS_STAFF_ACTIVE,
    HANDOFF_ACTIVE_STATUSES,
    HANDOFF_STATUS_ANSWERED,
    HANDOFF_STATUS_ASSIGNED,
    HANDOFF_STATUS_CLOSED,
    HANDOFF_STATUS_OPEN,
    HANDOFF_STATUSES,
    OUTCOME_AGENT_REPLY,
    Conversation,
    HandoffRequest,
    Message,
)
from models.caller import ChatCaller
from .business_calendar import CalendarError
from .errors import InvalidRequestError, NotFoundError
from .live_feed_service import LiveFeedService
from .settings_service import SettingsService

logger = logging.getLogger(__name__)

EMAIL_PATTERN = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")
PHONE_PATTERN = re.compile(r"^\+?[0-9][0-9 .\-]{7,18}$")
MAX_DETAILS_LENGTH = 2000
ANSWER_EMAIL_SUBJECT = "Phản hồi yêu cầu hỗ trợ của bạn"
ANSWER_EMAIL_FOOTER = "\n\n—\nBạn cũng có thể xem câu trả lời này trong khung trò chuyện trên website."


def mask_email(email: Optional[str]) -> Optional[str]:
    """``a***@example.com`` (ADM-06: contact details are masked by default)."""
    if not email:
        return None
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}"


def mask_phone(phone: Optional[str]) -> Optional[str]:
    """Last three digits only."""
    return f"***{phone[-3:]}" if phone else None


class HandoffService:
    """Creates, answers and closes support tickets."""

    def __init__(self, database: Database, live_feed: LiveFeedService, settings: SettingsService,
                 mailer: Optional[SmtpMailer] = None):
        """
        Args:
            database: Connected database.
            live_feed: Tells admin dashboards about new tickets.
            settings: Support hours, holidays and reply time.
            mailer: Sends answers by e-mail (``None`` without SMTP).
        """
        self._database = database
        self._live_feed = live_feed
        self._settings = settings
        self._mailer = mailer

    def due_at(self, opened_at: datetime) -> Optional[datetime]:
        """When a ticket opened at ``opened_at`` should be answered (``None`` if support is never open)."""
        try:
            return self._settings.support_calendar().add_working_hours(opened_at, self._settings.ticket_reply_hours())
        except CalendarError:
            logger.exception("Cannot compute a ticket due time")
            return None

    def open_request(
        self, repository: ConversationRepository, conversation: Conversation, message_id: Optional[uuid.UUID],
        reason: str, user_id: Optional[str],
    ) -> HandoffRequest:
        """Stage a new open ticket inside the caller's transaction."""
        request = HandoffRequest(
            conversation_id=conversation.id, message_id=message_id, reason=reason, status=HANDOFF_STATUS_OPEN,
            user_id=user_id, due_at=self.due_at(datetime.now(timezone.utc)),
        )
        repository.add(request)
        conversation.status = CONVERSATION_STATUS_HANDOFF
        return request

    async def notify(self, request: HandoffRequest) -> None:
        """Tell staff about a new ticket (after it was committed)."""
        logger.info("Ticket opened for conversation %s (%s)", request.conversation_id, request.reason)
        await self._live_feed.publish({
            "type": "handoff", "handoff_id": str(request.id), "conversation_id": str(request.conversation_id),
            "reason": request.reason, "due_at": request.due_at.isoformat() if request.due_at else None,
        })

    async def open_unless_active(self, conversation_id: uuid.UUID, message_id: uuid.UUID, reason: str,
                                 user_id: Optional[str]) -> Optional[HandoffRequest]:
        """Open a ticket unless the conversation already has one in progress (feedback trigger)."""
        async with self._database.session() as session:
            repository = ConversationRepository(session)
            if await repository.active_handoff(conversation_id, HANDOFF_ACTIVE_STATUSES) is not None:
                return None
            conversation = await repository.get_conversation(conversation_id)
            request = self.open_request(repository, conversation, message_id, reason, user_id)
            await repository.flush()
        await self.notify(request)
        return request

    # ------------------------------------------------------------------
    # Visitor side
    # ------------------------------------------------------------------

    async def add_contact(self, handoff_id: uuid.UUID, caller: ChatCaller, name: Optional[str], email: Optional[str],
                          phone: Optional[str], details: Optional[str], consent: bool) -> HandoffRequest:
        """
        Record how to reach the visitor (HND-13).

        Raises:
            NotFoundError: Unknown ticket, or it is someone else's.
            InvalidRequestError: Anonymous without a contact, no consent, or malformed contact.
        """
        email, phone = (email or "").strip() or None, (phone or "").strip() or None
        if not caller.logged_in and not (email or phone):
            raise InvalidRequestError("Please give an e-mail address or a phone number so we can reply")
        if (email or phone) and not consent:
            raise InvalidRequestError("Please accept how your contact details will be used")
        if email and not EMAIL_PATTERN.match(email):
            raise InvalidRequestError("The e-mail address does not look right")
        if phone and not PHONE_PATTERN.match(phone):
            raise InvalidRequestError("The phone number does not look right")
        async with self._database.session() as session:
            repository = ConversationRepository(session)
            request = await repository.get_handoff(handoff_id)
            conversation = await repository.get_conversation(request.conversation_id) if request else None
            if request is None or conversation is None or not caller.owns(conversation.user_id, conversation.end_user_id):
                raise NotFoundError("Request not found")
            request.contact_name = (name or "").strip()[:128] or None
            request.contact_email, request.contact_phone = email, phone
            request.details = (details or "").strip()[:MAX_DETAILS_LENGTH] or None
            request.consent_at = utc_now() if consent else None
        logger.info("Contact details recorded for ticket %s", handoff_id)
        return request

    # ------------------------------------------------------------------
    # Support side
    # ------------------------------------------------------------------

    async def list(self, status: Optional[str], limit: int, offset: int) -> Tuple[List[HandoffRequest], int]:
        """Tickets, most urgent first within a status."""
        async with self._database.session() as session:
            return await ConversationRepository(session).list_handoffs(status, limit, offset)

    async def update(self, handoff_id: uuid.UUID, status: Optional[str], note: Optional[str],
                     assigned_to: Optional[str], updated_by: str) -> HandoffRequest:
        """
        Assign, re-open or close a ticket, or change its note.

        Raises:
            NotFoundError: Unknown ticket.
            InvalidRequestError: Unknown status.
        """
        if status is not None and status not in HANDOFF_STATUSES:
            raise InvalidRequestError(f"status must be one of {', '.join(HANDOFF_STATUSES)}")
        async with self._database.session() as session:
            repository = ConversationRepository(session)
            request = await self._require(repository, handoff_id)
            if assigned_to is not None:
                request.assigned_to = assigned_to or None
                if request.status == HANDOFF_STATUS_OPEN and assigned_to:
                    request.status = HANDOFF_STATUS_ASSIGNED
            if status is not None:
                request.status = status
                request.closed_at = utc_now() if status == HANDOFF_STATUS_CLOSED else None
            if note is not None:
                request.note = note
            if request.status in (HANDOFF_STATUS_ANSWERED, HANDOFF_STATUS_CLOSED):
                await self._after_staff_action(repository, request)
        logger.info("Ticket %s updated by %s (status=%s)", handoff_id, updated_by, request.status)
        return request

    async def answer(self, handoff_id: uuid.UUID, text: str, answered_by: str) -> HandoffRequest:
        """
        Answer a ticket: add the reply to the conversation and e-mail it when an address was given.

        Raises:
            NotFoundError: Unknown ticket.
            InvalidRequestError: Empty answer or a closed ticket.
        """
        text = text.strip()
        if not text:
            raise InvalidRequestError("The answer is empty")
        async with self._database.session() as session:
            repository = ConversationRepository(session)
            request = await self._require(repository, handoff_id)
            if request.status == HANDOFF_STATUS_CLOSED:
                raise InvalidRequestError("This ticket is closed; re-open it first")
            repository.add(Message(conversation_id=request.conversation_id, role="assistant", content=text,
                                   outcome=OUTCOME_AGENT_REPLY, model=None))
            request.answer, request.answered_at = text, utc_now()
            request.assigned_to = request.assigned_to or answered_by
            request.status = HANDOFF_STATUS_ANSWERED
            await self._after_staff_action(repository, request)
            recipient = request.contact_email
        if recipient and self._mailer is not None:
            await self._email(request, recipient, text)
        logger.info("Ticket %s answered by %s", handoff_id, answered_by)
        return request

    async def _email(self, request: HandoffRequest, recipient: str, text: str) -> None:
        """Send the answer; a failure is logged and leaves ``emailed_at`` empty (the chat still has it)."""
        try:
            await self._mailer.send_async([recipient], ANSWER_EMAIL_SUBJECT, text + ANSWER_EMAIL_FOOTER)
        except MailDeliveryError:
            logger.exception("Could not e-mail the answer of ticket %s", request.id)
            return
        async with self._database.session() as session:
            stored = await ConversationRepository(session).get_handoff(request.id)
            stored.emailed_at = utc_now()
        request.emailed_at = stored.emailed_at

    async def reveal_contact(self, handoff_id: uuid.UUID) -> Dict[str, Optional[str]]:
        """
        The unmasked contact details (owners only; the route is audit-logged, ADM-06).

        Raises:
            NotFoundError: Unknown ticket.
        """
        async with self._database.session() as session:
            request = await self._require(ConversationRepository(session), handoff_id)
        return {"name": request.contact_name, "email": request.contact_email, "phone": request.contact_phone}

    @staticmethod
    async def _require(repository: ConversationRepository, handoff_id: uuid.UUID) -> HandoffRequest:
        """
        Raises:
            NotFoundError: Unknown ticket.
        """
        request = await repository.get_handoff(handoff_id)
        if request is None:
            raise NotFoundError("Handoff request not found")
        return request

    @staticmethod
    async def _after_staff_action(repository: ConversationRepository, request: HandoffRequest) -> None:
        """
        Who talks next: once staff have replied the bot stays silent (a bot talking over a live
        person is worse than none), and it answers again when the ticket is closed.
        """
        conversation = await repository.get_conversation(request.conversation_id)
        if conversation is not None:
            conversation.status = (
                CONVERSATION_STATUS_ACTIVE if request.status == HANDOFF_STATUS_CLOSED else CONVERSATION_STATUS_STAFF_ACTIVE
            )
