"""
FastAPI dependency providers: the service container and caller authentication.

* Public chat routes require either ``X-Service-Token`` (the chat widget's own
  server, with its installer-generated token) or ``X-API-Key`` (a key with the
  ``chat`` scope, for server-to-server integrations), plus ``X-End-User-Id``
  (the visitor). A logged-in visitor also carries the host site's token as
  ``Authorization: Bearer`` (forwarded unchanged by the widget server); only
  a token that verifies yields a user id and tier (checklist Invariant 1).
* Admin routes require an admin session token and a role allowed for the
  route. The token comes from the HttpOnly session cookie set at sign-in (the
  admin web) or ``Authorization: Bearer`` (scripts). Cookie-authenticated writes
  must also send ``X-Admin-Request: 1``, which a cross-site form cannot.
  Routes that name a key scope also accept ``X-API-Key`` with that scope
  (the client's backend, CI); managing keys, users, settings and the audit log
  never does.
* An API key is refused outright when the request carries headers only a
  browser sends: keys are for server-to-server calls, never for a web page.
  Each key has its own per-minute rate limit.
"""

# Standard library imports
import logging
import re
import uuid
from typing import Callable, Optional

# Third-party imports
from fastapi import Depends, Header, HTTPException, Request, status

# Local imports
from core.storage.tables.access_tables import ROLE_EDITOR, ROLE_OWNER, ROLE_SUPPORT_AGENT, ROLE_VIEWER, SCOPE_CHAT
from models.caller import ANONYMOUS_LEVEL, TIER_ANONYMOUS, ChatCaller
from services.auth_service import SERVICE_BFF, AdminPrincipal, VerifiedApiKey
from core.storage.tables.usage_tables import WINDOW_MINUTE
from services.host_identity_service import HostIdentity, HostTokenError
from services.rate_limit_service import Limit
from utils.request_context import current_request_id
from .container import AppContainer

logger = logging.getLogger(__name__)

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
#: Role recorded (e.g. in the audit log) for admin requests made with an API key.
API_KEY_ROLE = "api_key"
#: Headers only a browser adds; an API key arriving with one of them is refused.
BROWSER_ONLY_HEADERS = ("origin", "sec-fetch-site", "sec-fetch-mode")


def get_container(request: Request) -> AppContainer:
    """The process-wide service container built at start-up."""
    return request.app.state.container


def client_ip(request: Request) -> str:
    """Client address (already resolved from trusted ``X-Forwarded-For`` by Uvicorn)."""
    return request.client.host if request.client else "unknown"


async def _verified_api_key(request: Request, container: AppContainer, raw_key: str, scope: str) -> VerifiedApiKey:
    """
    Check a presented API key for ``scope`` and charge its rate limit.

    Raises:
        HTTPException: 403 from a browser context, 401 for an unknown, revoked
            or expired key, 403 without ``scope``, 429 over the key's rate limit.
    """
    if raw_key and any(request.headers.get(name) for name in BROWSER_ONLY_HEADERS):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "API keys are for server-to-server calls only, never a browser")
    key = await container.auth.verify_api_key(raw_key)
    if key is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid, expired or missing API key")
    if scope not in key.scopes:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"API key lacks the {scope} scope")
    retry_after = await container.rate_limiter.hit([Limit(f"apikey:{key.id}", WINDOW_MINUTE, key.rate_limit_per_minute)])
    if retry_after is not None:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "API key rate limit exceeded", headers={"Retry-After": str(retry_after)}
        )
    return key


async def _chat_client_key_id(
    request: Request, container: AppContainer, service_token: str, api_key: str
) -> Optional[uuid.UUID]:
    """
    Authenticate the frontend server behind a chat request.

    Returns:
        The API key's id, or ``None`` when the caller is our own BFF.

    Raises:
        HTTPException: As :func:`_verified_api_key` for the ``chat`` scope.
    """
    if container.auth.verify_service_token(service_token) == SERVICE_BFF:
        return None
    return (await _verified_api_key(request, container, api_key, SCOPE_CHAT)).id


async def require_client_key(
    request: Request,
    x_service_token: str = Header("", alias="X-Service-Token"),
    x_api_key: str = Header("", alias="X-API-Key"),
    container: AppContainer = Depends(get_container),
) -> None:
    """
    Authenticate a frontend server alone (for visitor-independent calls).

    Raises:
        HTTPException: 401 for missing/invalid credentials, 403 for a key without the chat scope.
    """
    await _chat_client_key_id(request, container, x_service_token, x_api_key)


async def _host_identity(container: AppContainer, authorization: str, visitor_id: str) -> Optional[HostIdentity]:
    """
    The logged-in host user behind a bearer token, or ``None`` for an anonymous visitor.

    With ``HOST_AUTH_MODE=none`` tokens are ignored and everyone is anonymous.

    Raises:
        HTTPException: 401 (``invalid_token``) for a token that does not verify,
            so the widget asks the host page for a fresh one.
    """
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip() or not container.host_identity.enabled:
        return None
    try:
        return await container.host_identity.verify(token.strip(), visitor_id)
    except HostTokenError as exc:
        logger.info("Host token refused: %s", exc)
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Sign-in expired or invalid; get a new token from the host page",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        ) from exc


async def require_chat_caller(
    request: Request,
    x_service_token: str = Header("", alias="X-Service-Token"),
    x_api_key: str = Header("", alias="X-API-Key"),
    x_end_user_id: str = Header("", alias="X-End-User-Id"),
    authorization: str = Header("", alias="Authorization"),
    container: AppContainer = Depends(get_container),
) -> ChatCaller:
    """
    Authenticate a public chat request and resolve the visitor's identity.

    Raises:
        HTTPException: 401 for missing/invalid credentials or host token, 403
            for a key without the chat scope, 400 for a missing or malformed visitor id.
    """
    api_key_id = await _chat_client_key_id(request, container, x_service_token, x_api_key)
    if not END_USER_ID_PATTERN.match(x_end_user_id or ""):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "X-End-User-Id header is missing or malformed")
    identity = await _host_identity(container, authorization, x_end_user_id)
    return ChatCaller(
        api_key_id=api_key_id,
        end_user_id=x_end_user_id,
        client_ip=client_ip(request),
        request_id=current_request_id(),
        user_id=identity.user_id if identity else None,
        tier=identity.tier if identity else TIER_ANONYMOUS,
        tier_level=identity.tier_level if identity else ANONYMOUS_LEVEL,
    )


def require_admin(roles=READ_ROLES, key_scope: Optional[str] = None) -> Callable:
    """
    Build a dependency admitting admins whose role is in ``roles``.

    Args:
        roles: Allowed roles, e.g. :data:`WRITE_ROLES`.
        key_scope: When set, an ``X-API-Key`` with this scope is admitted too
            (server-to-server automation); ``None`` keeps the route session-only.
    """

    async def dependency(
        request: Request,
        authorization: str = Header("", alias="Authorization"),
        x_api_key: str = Header("", alias="X-API-Key"),
        container: AppContainer = Depends(get_container),
    ) -> AdminPrincipal:
        if x_api_key and key_scope is not None:
            key = await _verified_api_key(request, container, x_api_key, key_scope)
            principal = AdminPrincipal(key.id, f"api-key:{key.name}", API_KEY_ROLE)
            request.state.admin = principal
            return principal
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
