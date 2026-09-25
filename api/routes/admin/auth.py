"""
Admin sign-in, own account and (owner-only) account management.
"""

# Standard library imports
import uuid
from typing import List

# Third-party imports
from fastapi import APIRouter, Depends, HTTPException, Request, status

# Local imports
from api.container import AppContainer
from api.dependencies import OWNER_ROLES, READ_ROLES, client_ip, get_container, require_admin
from api.schemas.admin import AdminCreate, AdminOut, AdminUpdate, LoginRequest, PasswordChange, TokenResponse
from api.schemas.common import MessageResponse
from services.auth_service import AdminPrincipal

router = APIRouter(tags=["Admin: accounts"])

#: Sign-in attempts allowed per client IP and per e-mail each minute.
LOGIN_ATTEMPTS_PER_MINUTE = 5


@router.post("/auth/login", response_model=TokenResponse)
async def login(body: LoginRequest, request: Request, container: AppContainer = Depends(get_container)) -> TokenResponse:
    """Exchange e-mail and password for a session token."""
    for key in (f"login-ip:{client_ip(request)}", f"login-email:{body.email.lower()}"):
        retry_after = container.rate_limiter.hit(key, LOGIN_ATTEMPTS_PER_MINUTE)
        if retry_after is not None:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "Too many sign-in attempts; try again shortly",
                headers={"Retry-After": str(retry_after)},
            )
    user = await container.auth.authenticate(body.email, body.password)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect e-mail or password")
    token, expires_at = container.auth.issue_token(user)
    return TokenResponse(access_token=token, expires_at=expires_at, admin=AdminOut.model_validate(user))


@router.get("/auth/me", response_model=AdminOut)
async def me(
    principal: AdminPrincipal = Depends(require_admin(READ_ROLES)),
    container: AppContainer = Depends(get_container),
) -> AdminOut:
    """The signed-in admin."""
    return AdminOut.model_validate(await container.auth.get_admin(principal.id))


@router.post("/auth/password", response_model=MessageResponse)
async def change_password(
    body: PasswordChange,
    principal: AdminPrincipal = Depends(require_admin(READ_ROLES)),
    container: AppContainer = Depends(get_container),
) -> MessageResponse:
    """Change the signed-in admin's password."""
    await container.auth.change_password(principal.id, body.current_password, body.new_password)
    return MessageResponse(message="Password changed")


@router.get("/users", response_model=List[AdminOut], dependencies=[Depends(require_admin(OWNER_ROLES))])
async def list_users(container: AppContainer = Depends(get_container)) -> List[AdminOut]:
    """All admin accounts."""
    return [AdminOut.model_validate(user) for user in await container.auth.list_admins()]


@router.post("/users", response_model=AdminOut, status_code=201, dependencies=[Depends(require_admin(OWNER_ROLES))])
async def create_user(body: AdminCreate, container: AppContainer = Depends(get_container)) -> AdminOut:
    """Create an admin account."""
    return AdminOut.model_validate(await container.auth.create_admin(body.email, body.password, body.role))


@router.patch("/users/{admin_id}", response_model=AdminOut, dependencies=[Depends(require_admin(OWNER_ROLES))])
async def update_user(admin_id: uuid.UUID, body: AdminUpdate, container: AppContainer = Depends(get_container)) -> AdminOut:
    """Change an admin's role or disable the account."""
    return AdminOut.model_validate(await container.auth.update_admin(admin_id, body.role, body.disabled))
