"""
The golden evaluation set built from real answers (ADM-12, RET-R3).
"""

# Standard library imports
import uuid
from typing import Any, Dict, List

# Third-party imports
from fastapi import APIRouter, Depends, Query

# Local imports
from api.container import AppContainer
from api.dependencies import READ_ROLES, WRITE_ROLES, get_container, require_admin
from api.schemas.common import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, MessageResponse, Page
from api.schemas.evaluation import EvalCaseCreate, EvalCaseOut
from services.auth_service import AdminPrincipal

router = APIRouter(tags=["Admin: evaluation"])


@router.post("/messages/{message_id}/eval-case", response_model=EvalCaseOut, status_code=201)
async def add_eval_case(
    message_id: uuid.UUID,
    body: EvalCaseCreate,
    principal: AdminPrincipal = Depends(require_admin(WRITE_ROLES)),
    container: AppContainer = Depends(get_container),
) -> EvalCaseOut:
    """Copy an answer and its question into the eval set, without any link back to the conversation."""
    case = await container.eval_cases.create_from_message(message_id, body.expected_answer, body.note, principal.email)
    return EvalCaseOut.model_validate(case)


@router.get("/eval-cases", response_model=Page[EvalCaseOut], dependencies=[Depends(require_admin(READ_ROLES))])
async def list_eval_cases(
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(0, ge=0),
    container: AppContainer = Depends(get_container),
) -> Page[EvalCaseOut]:
    """The eval set, newest first."""
    cases, total = await container.eval_cases.list(limit, offset)
    return Page(items=[EvalCaseOut.model_validate(c) for c in cases], total=total, limit=limit, offset=offset)


@router.get("/eval-cases/export", dependencies=[Depends(require_admin(READ_ROLES))])
async def export_eval_cases(container: AppContainer = Depends(get_container)) -> List[Dict[str, Any]]:
    """The whole set as ``golden_queries.json`` for ``scripts/eval_rag.py``."""
    return await container.eval_cases.export()


@router.delete("/eval-cases/{case_id}", response_model=MessageResponse, dependencies=[Depends(require_admin(WRITE_ROLES))])
async def delete_eval_case(case_id: uuid.UUID, container: AppContainer = Depends(get_container)) -> MessageResponse:
    """Remove a case from the eval set."""
    await container.eval_cases.delete(case_id)
    return MessageResponse(message="Eval case deleted")
