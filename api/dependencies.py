"""
FastAPI dependency providers: the service container and caller authentication.

* Public chat routes require ``X-API-Key`` (a key with the ``chat`` scope,
  held by the frontend's server) plus ``X-End-User-Id`` (the visitor).
* Admin routes require an admin session token and a role allowed for the
  route. The token comes from the HttpOnly session cookie set at sign-in (the
  admin web) or ``Authorization: Bearer`` (scripts). Cookie-authenticated writes
  must also send ``X-Admin-Request: 1``, which a cross-site form cannot.
"""

# Standard library imports
import re
from typing import Callable

# Third-party imports
from fastapi import Depends, Header, HTTPException, Request, status

# Local imports
from core.storage.tables.access_tables import ROLE_EDITOR, ROLE_OWNER, ROLE_SUPPORT_AGENT, ROLE_VIEWER, SCOPE_CHAT
from models.caller import ChatCaller
from services.auth_service import AdminPrincipal
from utils.request_context import current_request_id
from .container import AppContainer

#: Visitor ids are opaque tokens minted by the frontend (never e-mails/phones).
END_USER_ID_PATTERN = re.compile(r"^[A-Za-z0-9_\-:.]{8,128}$")

#: Roles allowed by each admin permission level.
READ_ROLES = (ROLE_OWNER, ROLE_EDITOR, ROLE_VIEWER, ROLE_SUPPORT_AGENT)
WRITE_ROLES = (ROLE_OWNER, ROLE_EDITOR)
#: Who may take on and close transfer-to-human requests.
HANDOFF_ROLES = (ROLE_OWNER, ROLE_EDITOR, ROLE_SUPPORT_AGENT)
OWNER_ROLES = (ROLE_OWNER,)

#: HttpOnly cookie carrying the admin session token for the admin web.
ADMIN_SESSION_COOKIE = "admin_session"
#: Path the session cookie is scoped to, so no other route ever receives it.
ADMIN_COOKIE_PATH = "/api/v1/admin"
#: Header cookie-authenticated writes must carry (browsers never add it cross-site).
CSRF_HEADER = "X-Admin-Request"
#: Methods that change state and therefore need the CSRF header.
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


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
        request: Request,
        authorization: str = Header("", alias="Authorization"),
        container: AppContainer = Depends(get_container),
    ) -> AdminPrincipal:
        scheme, _, bearer = authorization.partition(" ")
        token = bearer if scheme.lower() == "bearer" and bearer else None
        from_cookie = token is None
        if from_cookie:
            token = request.cookies.get(ADMIN_SESSION_COOKIE)
        principal = await container.auth.verify_token(token) if token else None
        if principal is None:
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED, "Not signed in", headers={"WWW-Authenticate": "Bearer"}
            )
        if from_cookie and request.method in UNSAFE_METHODS and request.headers.get(CSRF_HEADER) != "1":
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Missing {CSRF_HEADER} header")
        if principal.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Your role does not allow this action")
        # Read by the audit middleware to attribute the change.
        request.state.admin = principal
        return principal

    return dependency
