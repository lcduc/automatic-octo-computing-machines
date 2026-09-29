"""
Owner-only privacy actions: legal hold (RET-R2) and data-subject requests (PRV-03).

Every route is a PUT/POST so the audit middleware records who did it (ADM-02).
"""

# Standard library imports
import uuid

# Third-party imports
from fastapi import APIRouter, Depends

# Local imports
from api.container import AppContainer
from api.dependencies import OWNER_ROLES, get_container, require_admin
from api.schemas.privacy import DataSubjectDeleted, DataSubjectExport, DataSubjectQuery, LegalHoldOut, LegalHoldUpdate

router = APIRouter(tags=["Admin: privacy"], dependencies=[Depends(require_admin(OWNER_ROLES))])


@router.put("/conversations/{conversation_id}/legal-hold", response_model=LegalHoldOut)
async def hold_conversation(
    conversation_id: uuid.UUID, body: LegalHoldUpdate, container: AppContainer = Depends(get_container)
) -> LegalHoldOut:
    """Keep a conversation past its retention period (or release it)."""
    conversation = await container.privacy.hold_conversation(conversation_id, body.held)
    return LegalHoldOut(id=str(conversation.id), legal_hold=conversation.legal_hold)


@router.put("/handoffs/{handoff_id}/legal-hold", response_model=LegalHoldOut)
async def hold_ticket(
    handoff_id: uuid.UUID, body: LegalHoldUpdate, container: AppContainer = Depends(get_container)
) -> LegalHoldOut:
    """Keep a ticket (and its conversation) past its retention period (or release it)."""
    ticket = await container.privacy.hold_ticket(handoff_id, body.held)
    return LegalHoldOut(id=str(ticket.id), legal_hold=ticket.legal_hold)


@router.post("/data-subjects/export", response_model=DataSubjectExport)
async def export_subject(body: DataSubjectQuery, container: AppContainer = Depends(get_container)) -> DataSubjectExport:
    """A copy of everything stored about one person (conversations with ratings, tickets with contact)."""
    return DataSubjectExport(**await container.privacy.export(body.to_subject()))


@router.post("/data-subjects/delete", response_model=DataSubjectDeleted)
async def delete_subject(body: DataSubjectQuery, container: AppContainer = Depends(get_container)) -> DataSubjectDeleted:
    """Delete one person's data now, overriding retention; items under legal hold are kept."""
    return DataSubjectDeleted(**await container.privacy.delete(body.to_subject()))
