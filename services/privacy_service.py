"""
Legal hold (RET-R2) and data-subject export/delete (PRV-03, RET-R5).

A deletion request removes the person's data at once, whatever the retention
period, except anything under legal hold: a held conversation, a held
ticket, and the conversation behind a held ticket are kept and reported.
Every call comes through an admin POST/PUT, so the audit log records it.
"""

# Standard library imports
import logging
import uuid
from typing import Any, Dict

# Local imports
from core.storage.database import Database
from core.storage.privacy_repository import PrivacyRepository
from core.storage.tables.conversation_tables import Conversation, HandoffRequest
from models.data_subject import DataSubject
from .errors import NotFoundError

logger = logging.getLogger(__name__)


def _ticket_export(ticket: HandoffRequest) -> Dict[str, Any]:
    """Everything stored on a ticket, for the person's copy."""
    return {
        "id": str(ticket.id), "conversation_id": str(ticket.conversation_id), "reason": ticket.reason,
        "status": ticket.status, "contact_name": ticket.contact_name, "contact_email": ticket.contact_email,
        "contact_phone": ticket.contact_phone, "details": ticket.details,
        "consent_at": ticket.consent_at.isoformat() if ticket.consent_at else None,
        "answer": ticket.answer, "answered_at": ticket.answered_at.isoformat() if ticket.answered_at else None,
        "created_at": ticket.created_at.isoformat(),
    }


def _conversation_export(conversation: Conversation) -> Dict[str, Any]:
    """A conversation with its messages and ratings, for the person's copy."""
    return {
        "id": str(conversation.id), "created_at": conversation.created_at.isoformat(),
        "last_activity_at": conversation.last_activity_at.isoformat(),
        "messages": [
            {
                "role": message.role, "content": message.content, "created_at": message.created_at.isoformat(),
                "feedback": (
                    {"rating": message.feedback.rating, "comment": message.feedback.comment}
                    if message.feedback is not None else None
                ),
            }
            for message in conversation.messages
        ],
    }


class PrivacyService:
    """Legal hold and data-subject requests."""

    def __init__(self, database: Database):
        """
        Args:
            database: Connected database.
        """
        self._database = database

    async def hold_conversation(self, conversation_id: uuid.UUID, held: bool) -> Conversation:
        """
        Set or clear the legal hold of a conversation.

        Raises:
            NotFoundError: Unknown conversation.
        """
        async with self._database.session() as session:
            conversation = await PrivacyRepository(session).get_conversation(conversation_id)
            if conversation is None:
                raise NotFoundError("Conversation not found")
            conversation.legal_hold = held
        logger.info("Legal hold %s on conversation %s", "set" if held else "cleared", conversation_id)
        return conversation

    async def hold_ticket(self, ticket_id: uuid.UUID, held: bool) -> HandoffRequest:
        """
        Set or clear the legal hold of a ticket.

        Raises:
            NotFoundError: Unknown ticket.
        """
        async with self._database.session() as session:
            ticket = await PrivacyRepository(session).get_ticket(ticket_id)
            if ticket is None:
                raise NotFoundError("Ticket not found")
            ticket.legal_hold = held
        logger.info("Legal hold %s on ticket %s", "set" if held else "cleared", ticket_id)
        return ticket

    async def export(self, subject: DataSubject) -> Dict[str, Any]:
        """Everything stored about the person: conversations (with ratings) and tickets."""
        async with self._database.session() as session:
            repository = PrivacyRepository(session)
            tickets = await repository.tickets(subject)
            conversations = await repository.conversations(subject, [t.conversation_id for t in tickets])
        logger.info("Exported %d conversation(s) and %d ticket(s) for a data subject", len(conversations), len(tickets))
        return {
            "conversations": [_conversation_export(c) for c in conversations],
            "tickets": [_ticket_export(t) for t in tickets],
        }

    async def delete(self, subject: DataSubject) -> Dict[str, int]:
        """
        Delete the person's conversations, tickets and per-call usage now,
        except what is under legal hold.

        Returns:
            Deleted counts, and how many conversations/tickets were kept on hold.
        """
        async with self._database.session() as session:
            repository = PrivacyRepository(session)
            tickets = await repository.tickets(subject)
            conversations = await repository.conversations(subject, [t.conversation_id for t in tickets])
            held_conversations = {c.id for c in conversations if c.legal_hold}
            # Deleting a conversation cascades to its tickets, so a held ticket keeps its conversation.
            held_conversations |= {t.conversation_id for t in tickets if t.legal_hold}
            ticket_ids = [t.id for t in tickets if not t.legal_hold and t.conversation_id not in held_conversations]
            conversation_ids = [c.id for c in conversations if c.id not in held_conversations]
            counts = {
                "tickets": await repository.delete_tickets(ticket_ids),
                "conversations": await repository.delete_conversations(conversation_ids),
                "token_usage": await repository.delete_visitor_usage(subject.visitor_id) if subject.visitor_id else 0,
                "kept_on_hold": len({c.id for c in conversations} & held_conversations)
                + sum(1 for t in tickets if t.id not in ticket_ids),
            }
        logger.info("Data-subject deletion: %s", counts)
        return counts
