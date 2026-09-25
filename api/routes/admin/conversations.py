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
from api.dependencies import READ_ROLES, WRITE_ROLES, get_container, require_admin
from api.schemas.admin import (
    AdminMessage,
    ConversationDetail,
    ConversationSummary,
    FeedbackItem,
    HandoffOut,
    HandoffUpdate,
)
from api.schemas.common import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, Page
from services.auth_service import AdminPrincipal

router = APIRouter(tags=["Admin: conversations"])
read_access = Depends(require_admin(READ_ROLES))

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
    status: Optional[str] = Query(None, pattern="^(pending|in_progress|resolved)$"),
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(0, ge=0),
    container: AppContainer = Depends(get_container),
) -> Page[HandoffOut]:
    """Transfer-to-human requests newest first."""
    requests, total = await container.handoffs.list(status, limit, offset)
    return Page(items=[HandoffOut.model_validate(r) for r in requests], total=total, limit=limit, offset=offset)


@router.patch("/handoffs/{handoff_id}", response_model=HandoffOut)
async def update_handoff(
    handoff_id: uuid.UUID,
    body: HandoffUpdate,
    principal: AdminPrincipal = Depends(require_admin(WRITE_ROLES)),
    container: AppContainer = Depends(get_container),
) -> HandoffOut:
    """Mark a handoff in progress or resolved, optionally with a note."""
    request = await container.handoffs.update(handoff_id, body.status, body.note, principal.email)
    return HandoffOut.model_validate(request)
