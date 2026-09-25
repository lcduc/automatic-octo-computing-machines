"""
FastAPI dependency providers: the service container and caller authentication.

* Public chat routes require ``X-API-Key`` (a key with the ``chat`` scope,
  held by the frontend's server) plus ``X-End-User-Id`` (the visitor).
* Admin routes require ``Authorization: Bearer <admin session token>`` and a
  role allowed for the route.
"""

# Standard library imports
import re
from typing import Callable

# Third-party imports
from fastapi import Depends, Header, HTTPException, Request, status

# Local imports
from core.storage.tables.access_tables import ROLE_EDITOR, ROLE_OWNER, ROLE_VIEWER, SCOPE_CHAT
from models.caller import ChatCaller
from services.auth_service import AdminPrincipal
from utils.request_context import current_request_id
from .container import AppContainer

#: Visitor ids are opaque tokens minted by the frontend (never e-mails/phones).
END_USER_ID_PATTERN = re.compile(r"^[A-Za-z0-9_\-:.]{8,128}$")

#: Roles allowed by each admin permission level.
READ_ROLES = (ROLE_OWNER, ROLE_EDITOR, ROLE_VIEWER)
WRITE_ROLES = (ROLE_OWNER, ROLE_EDITOR)
OWNER_ROLES = (ROLE_OWNER,)


def get_container(request: Request) -> AppContainer:
    """The process-wide service container built at start-up."""
    return request.app.state.container


def client_ip(request: Request) -> str:
    """Client address (already resolved from trusted ``X-Forwarded-For`` by Uvicorn)."""
    return request.client.host if request.client else "unknown"


async def require_client_key(
    x_api_key: str = Header("", alias="X-API-Key"),
    container: AppContainer = Depends(get_container),
):
    """
    Authenticate a frontend by API key alone (for visitor-independent calls).

    Raises:
        HTTPException: 401 for a missing or invalid key.
    """
    key = await container.auth.verify_api_key(x_api_key)
    if key is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or missing API key")
    return key


async def require_chat_caller(
    request: Request,
    x_api_key: str = Header("", alias="X-API-Key"),
    x_end_user_id: str = Header("", alias="X-End-User-Id"),
    container: AppContainer = Depends(get_container),
) -> ChatCaller:
    """
    Authenticate a public chat request.

    Raises:
        HTTPException: 401 for a missing/invalid key, 403 for a key without the
            chat scope, 400 for a missing or malformed visitor id.
    """
    key = await container.auth.verify_api_key(x_api_key)
    if key is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or missing API key")
    if SCOPE_CHAT not in key.scopes:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "API key is not allowed to chat")
    if not END_USER_ID_PATTERN.match(x_end_user_id or ""):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "X-End-User-Id header is missing or malformed")
    return ChatCaller(
        api_key_id=key.id, end_user_id=x_end_user_id, client_ip=client_ip(request), request_id=current_request_id()
    )


def require_admin(roles=READ_ROLES) -> Callable:
    """
    Build a dependency admitting admins whose role is in ``roles``.

    Args:
        roles: Allowed roles, e.g. :data:`WRITE_ROLES`.
    """

    async def dependency(
        authorization: str = Header("", alias="Authorization"),
        container: AppContainer = Depends(get_container),
    ) -> AdminPrincipal:
        scheme, _, token = authorization.partition(" ")
        principal = await container.auth.verify_token(token) if scheme.lower() == "bearer" and token else None
        if principal is None:
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED, "Not signed in", headers={"WWW-Authenticate": "Bearer"}
            )
        if principal.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Your role does not allow this action")
        return principal

    return dependency
