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
from api.schemas.admin import ApiKeyCreate, ApiKeyCreated, ApiKeyOut, ApiKeyRotate, SettingsUpdate
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
    """
    Change settings; they apply to the next chat turn without a restart.

    A new chat or light model is tried with one tiny request first, so a
    mistyped model name is refused (400) instead of breaking every chat.
    """
    return await container.settings.update(
        body.model_dump(exclude_unset=True), principal.email, model_check=container.check_model
    )


@router.get("/settings/defaults", dependencies=[Depends(require_admin(READ_ROLES))])
async def get_setting_defaults(container: AppContainer = Depends(get_container)) -> Dict[str, Any]:
    """What each setting falls back to (``.env`` / built-in), to show saved overrides."""
    return container.settings.defaults()


@router.delete("/settings/{key}")
async def reset_setting(
    key: str,
    principal: AdminPrincipal = Depends(require_admin(WRITE_ROLES)),
    container: AppContainer = Depends(get_container),
) -> Dict[str, Any]:
    """Drop a saved override so the default applies again."""
    return await container.settings.reset(key, principal.email)


@router.get("/api-keys", response_model=List[ApiKeyOut], dependencies=[Depends(require_admin(OWNER_ROLES))])
async def list_api_keys(container: AppContainer = Depends(get_container)) -> List[ApiKeyOut]:
    """Every client API key (secrets are never shown again)."""
    return [ApiKeyOut.model_validate(key) for key in await container.auth.list_api_keys()]


@router.post("/api-keys", response_model=ApiKeyCreated, status_code=201, dependencies=[Depends(require_admin(OWNER_ROLES))])
async def create_api_key(body: ApiKeyCreate, container: AppContainer = Depends(get_container)) -> ApiKeyCreated:
    """Issue a server-to-server key; copy it now, only its hash is kept."""
    record, raw_key = await container.auth.create_api_key(
        body.name, list(body.scopes), body.rate_limit_per_minute, body.expires_in_days
    )
    return ApiKeyCreated(**ApiKeyOut.model_validate(record).model_dump(), key=raw_key)


@router.post("/api-keys/{key_id}/rotate", response_model=ApiKeyCreated, status_code=201,
             dependencies=[Depends(require_admin(OWNER_ROLES))])
async def rotate_api_key(key_id: uuid.UUID, body: ApiKeyRotate, container: AppContainer = Depends(get_container)) -> ApiKeyCreated:
    """Issue a replacement; the old key keeps working for the grace period so the client can switch."""
    record, raw_key = await container.auth.rotate_api_key(key_id, body.grace_days)
    return ApiKeyCreated(**ApiKeyOut.model_validate(record).model_dump(), key=raw_key)


@router.post("/api-keys/{key_id}/revoke", response_model=ApiKeyOut, dependencies=[Depends(require_admin(OWNER_ROLES))])
async def revoke_api_key(key_id: uuid.UUID, container: AppContainer = Depends(get_container)) -> ApiKeyOut:
    """Revoke a key (effective within a minute)."""
    return ApiKeyOut.model_validate(await container.auth.revoke_api_key(key_id))
