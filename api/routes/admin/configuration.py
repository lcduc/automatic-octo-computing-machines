"""
Admin configuration: runtime chat/widget settings and client API keys.
"""

# Standard library imports
import uuid
from typing import Any, Dict, List

# Third-party imports
from fastapi import APIRouter, Depends

# Local imports
from api.container import AppContainer
from api.dependencies import OWNER_ROLES, READ_ROLES, WRITE_ROLES, get_container, require_admin
from api.schemas.admin import ApiKeyCreate, ApiKeyCreated, ApiKeyOut, SettingsUpdate
from services.auth_service import AdminPrincipal

router = APIRouter(tags=["Admin: configuration"])


@router.get("/settings", dependencies=[Depends(require_admin(READ_ROLES))])
async def get_settings(container: AppContainer = Depends(get_container)) -> Dict[str, Any]:
    """Current fallback mode, canned replies, assistant instructions and widget look."""
    return container.settings.all()


@router.patch("/settings")
async def update_settings(
    body: SettingsUpdate,
    principal: AdminPrincipal = Depends(require_admin(WRITE_ROLES)),
    container: AppContainer = Depends(get_container),
) -> Dict[str, Any]:
    """Change settings; they apply to the next chat turn without a restart."""
    return await container.settings.update(body.model_dump(exclude_unset=True), principal.email)


@router.get("/api-keys", response_model=List[ApiKeyOut], dependencies=[Depends(require_admin(OWNER_ROLES))])
async def list_api_keys(container: AppContainer = Depends(get_container)) -> List[ApiKeyOut]:
    """Every client API key (secrets are never shown again)."""
    return [ApiKeyOut.model_validate(key) for key in await container.auth.list_api_keys()]


@router.post("/api-keys", response_model=ApiKeyCreated, status_code=201, dependencies=[Depends(require_admin(OWNER_ROLES))])
async def create_api_key(body: ApiKeyCreate, container: AppContainer = Depends(get_container)) -> ApiKeyCreated:
    """Issue a key for a frontend; copy it now, it is not retrievable later."""
    record, raw_key = await container.auth.create_api_key(body.name)
    return ApiKeyCreated(**ApiKeyOut.model_validate(record).model_dump(), key=raw_key)


@router.post("/api-keys/{key_id}/revoke", response_model=ApiKeyOut, dependencies=[Depends(require_admin(OWNER_ROLES))])
async def revoke_api_key(key_id: uuid.UUID, container: AppContainer = Depends(get_container)) -> ApiKeyOut:
    """Revoke a key (effective within a minute)."""
    return ApiKeyOut.model_validate(await container.auth.revoke_api_key(key_id))
