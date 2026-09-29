"""
Admin configuration: runtime chat/widget settings and client API keys.
"""

# Standard library imports
import uuid
from typing import Any, Dict, List

# Third-party imports
from fastapi import APIRouter, Depends, Path

# Local imports
from api.container import AppContainer
from api.dependencies import OWNER_ROLES, READ_ROLES, WRITE_ROLES, get_container, require_admin
from api.schemas.admin import (
    ApiKeyCreate,
    ApiKeyCreated,
    ApiKeyOut,
    ApiKeyRotate,
    MAX_MODEL_NAME,
    MODEL_NAME_PATTERN,
    ModelPriceIn,
    ModelPriceOut,
    SettingsUpdate,
    SqlToolOut,
    SqlToolUpdate,
)
from services.errors import NotFoundError
from api.schemas.common import MessageResponse
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


@router.get("/prices", response_model=List[ModelPriceOut], dependencies=[Depends(require_admin(READ_ROLES))])
async def list_prices(container: AppContainer = Depends(get_container)) -> List[ModelPriceOut]:
    """LLM prices applied to recorded calls (models without a price cost nothing toward the spend cap)."""
    return [ModelPriceOut.model_validate(price) for price in await container.pricing.list()]


@router.put("/prices/{model:path}", response_model=ModelPriceOut)
async def set_price(
    body: ModelPriceIn,
    model: str = Path(..., min_length=1, max_length=MAX_MODEL_NAME, pattern=MODEL_NAME_PATTERN),
    principal: AdminPrincipal = Depends(require_admin(OWNER_ROLES)),
    container: AppContainer = Depends(get_container),
) -> ModelPriceOut:
    """Set a model's price; applies to calls recorded from now on."""
    price = await container.pricing.upsert(
        model, body.input_usd_per_million, body.output_usd_per_million, principal.email
    )
    return ModelPriceOut.model_validate(price)


@router.delete("/prices/{model:path}", response_model=MessageResponse, dependencies=[Depends(require_admin(OWNER_ROLES))])
async def delete_price(model: str, container: AppContainer = Depends(get_container)) -> MessageResponse:
    """Remove a model's price."""
    await container.pricing.delete(model)
    return MessageResponse(message="Price removed")


@router.get("/tools", response_model=List[SqlToolOut], dependencies=[Depends(require_admin(READ_ROLES))])
async def list_tools(container: AppContainer = Depends(get_container)) -> List[SqlToolOut]:
    """SQL tools of this deployment (empty without a business database)."""
    if container.sql_tools is None:
        return []
    return [SqlToolOut.model_validate(tool) for tool in await container.sql_tools.list()]


@router.patch("/tools/{name}", response_model=SqlToolOut)
async def update_tool(
    name: str,
    body: SqlToolUpdate,
    principal: AdminPrincipal = Depends(require_admin(WRITE_ROLES)),
    container: AppContainer = Depends(get_container),
) -> SqlToolOut:
    """Enable or disable a tool without a deploy; applies to the next turn."""
    if container.sql_tools is None:
        raise NotFoundError("No business database is configured")
    return SqlToolOut.model_validate(await container.sql_tools.set_enabled(name, body.enabled, principal.email))
