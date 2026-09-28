"""
Owner-only view of the append-only admin audit log.
"""

# Standard library imports
from datetime import datetime
from typing import Optional

# Third-party imports
from fastapi import APIRouter, Depends, Query

# Local imports
from api.container import AppContainer
from api.dependencies import OWNER_ROLES, get_container, require_admin
from api.schemas.admin import AuditEntryOut
from api.schemas.common import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, Page

router = APIRouter(tags=["Admin: audit"])


@router.get("/audit", response_model=Page[AuditEntryOut], dependencies=[Depends(require_admin(OWNER_ROLES))])
async def list_audit_entries(
    actor: Optional[str] = Query(None, max_length=255, description="Part of the actor's e-mail"),
    method: Optional[str] = Query(None, pattern="^(POST|PATCH|DELETE)$"),
    path_contains: Optional[str] = Query(None, max_length=200),
    since: Optional[datetime] = Query(None),
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(0, ge=0),
    container: AppContainer = Depends(get_container),
) -> Page[AuditEntryOut]:
    """Admin writes and sign-in attempts, newest first. There is no way to edit or delete them."""
    entries, total = await container.audit.list(actor, method, path_contains, since, limit, offset)
    return Page(items=[AuditEntryOut.model_validate(e) for e in entries], total=total, limit=limit, offset=offset)
