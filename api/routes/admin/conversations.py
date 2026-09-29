"""
Admin views of conversations, the feedback inbox and handoff requests.
"""

# Standard library imports
import uuid
from datetime import datetime
from typing import Optional

# Third-party imports
from fastapi import APIRouter, Depends, Query

# Local imports
from api.container import AppContainer
from api.dependencies import HANDOFF_ROLES, OWNER_ROLES, READ_ROLES, get_container, require_admin
from core.storage.tables.access_tables import SCOPE_CONVERSATIONS_READ
from api.schemas.admin import (
    AdminMessage,
    ConversationDetail,
    ConversationSummary,
    FeedbackItem,
    HandoffAnswer,
    HandoffContactOut,
    HandoffOut,
    HandoffUpdate,
)
from api.schemas.common import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, Page
from services.auth_service import AdminPrincipal

router = APIRouter(tags=["Admin: conversations"])
read_access = Depends(require_admin(READ_ROLES, key_scope=SCOPE_CONVERSATIONS_READ))

OUTCOME_PATTERN = "^(answered|smalltalk|denied|handoff|blocked|error)$"


@router.get("/conversations", response_model=Page[ConversationSummary], dependencies=[read_access])
async def list_conversations(
    outcome: Optional[str] = Query(None, pattern=OUTCOME_PATTERN, description="Only conversations with such an answer"),
    status: Optional[str] = Query(None, pattern="^(active|handoff_pending|closed)$"),
    since: Optional[datetime] = None,
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(0, ge=0),
    container: AppContainer = Depends(get_container),
) -> Page[ConversationSummary]:
    """Conversations, most recently active first."""
    conversations, total = await container.conversations.list_conversations(outcome, status, since, limit, offset)
    return Page(
        items=[ConversationSummary.model_validate(c) for c in conversations], total=total, limit=limit, offset=offset
    )


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail, dependencies=[read_access])
async def conversation_detail(
    conversation_id: uuid.UUID, container: AppContainer = Depends(get_container)
) -> ConversationDetail:
    """One conversation with every message, its diagnostics and feedback."""
    conversation = await container.conversations.conversation_detail(conversation_id)
    summary = ConversationSummary.model_validate(conversation).model_dump()
    return ConversationDetail(**summary, messages=[AdminMessage.from_message(m) for m in conversation.messages])


@router.get("/feedback", response_model=Page[FeedbackItem], dependencies=[read_access])
async def list_feedback(
    rating: Optional[int] = Query(None, ge=-1, le=1),
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(0, ge=0),
    container: AppContainer = Depends(get_container),
) -> Page[FeedbackItem]:
    """Visitor ratings newest first, with the question and the rated answer."""
    rows, total = await container.conversations.list_feedback(rating, limit, offset)
    items = [
        FeedbackItem(
            id=feedback.id,
            rating=feedback.rating,
            comment=feedback.comment,
            created_at=feedback.created_at,
            message_id=message.id,
            conversation_id=message.conversation_id,
            question=question,
            answer=message.content,
            outcome=message.outcome,
        )
        for feedback, message, question in rows
    ]
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.get("/handoffs", response_model=Page[HandoffOut], dependencies=[read_access])
async def list_handoffs(
    status: Optional[str] = Query(None, pattern="^(open|assigned|answered|closed)$"),
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(0, ge=0),
    container: AppContainer = Depends(get_container),
) -> Page[HandoffOut]:
    """Tickets, earliest due first."""
    requests, total = await container.handoffs.list(status, limit, offset)
    return Page(items=[HandoffOut.from_request(r) for r in requests], total=total, limit=limit, offset=offset)


@router.post("/handoffs/{handoff_id}/answer", response_model=HandoffOut)
async def answer_handoff(
    handoff_id: uuid.UUID,
    body: HandoffAnswer,
    principal: AdminPrincipal = Depends(require_admin(HANDOFF_ROLES)),
    container: AppContainer = Depends(get_container),
) -> HandoffOut:
    """Reply to the visitor: shown in their chat and e-mailed when they left an address."""
    return HandoffOut.from_request(await container.handoffs.answer(handoff_id, body.text, principal.email))


@router.post("/handoffs/{handoff_id}/reveal-contact", response_model=HandoffContactOut,
             dependencies=[Depends(require_admin(OWNER_ROLES))])
async def reveal_handoff_contact(handoff_id: uuid.UUID, container: AppContainer = Depends(get_container)) -> HandoffContactOut:
    """The unmasked contact details; a POST so every reveal is in the audit log (ADM-06)."""
    return HandoffContactOut(**await container.handoffs.reveal_contact(handoff_id))


@router.patch("/handoffs/{handoff_id}", response_model=HandoffOut)
async def update_handoff(
    handoff_id: uuid.UUID,
    body: HandoffUpdate,
    principal: AdminPrincipal = Depends(require_admin(HANDOFF_ROLES)),
    container: AppContainer = Depends(get_container),
) -> HandoffOut:
    """Assign, re-open or close a ticket, or change its internal note."""
    request = await container.handoffs.update(handoff_id, body.status, body.note, body.assigned_to, principal.email)
    return HandoffOut.from_request(request)
