"""
Authentication: client API keys for the chat API and admin accounts for the management web.
"""

# Standard library imports
import base64
import hashlib
import hmac
import logging
import secrets
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

# Third-party imports
import jwt

# Local imports
from core.storage.access_repository import AccessRepository
from core.storage.database import Database
from core.storage.tables.base import utc_now
from core.storage.tables.access_tables import ADMIN_ROLES, ROLE_OWNER, SCOPE_CHAT, AdminUser, ApiKey
from .errors import ConflictError, InvalidRequestError, NotFoundError

logger = logging.getLogger(__name__)

#: Every issued API key starts with this marker so leaked keys are easy to spot.
API_KEY_PREFIX = "cbk_"
#: Characters of the key kept in clear for display.
DISPLAY_PREFIX_LENGTH = 12
#: Seconds a verified key stays cached before the database is asked again.
API_KEY_CACHE_SECONDS = 60
#: ``last_used_at`` is written at most this often per key.
LAST_USED_WRITE_INTERVAL = timedelta(minutes=5)
#: Cached key lookups (including misses) kept before the cache is reset.
MAX_CACHED_KEYS = 10_000

#: scrypt cost parameters (≈50 ms per hash on the target VPS CPU).
SCRYPT_N = 2 ** 14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_KEY_LENGTH = 64
SALT_BYTES = 16
MIN_PASSWORD_LENGTH = 10

JWT_ALGORITHM = "HS256"


@dataclass(frozen=True)
class VerifiedApiKey:
    """The parts of an API key needed per request."""

    id: uuid.UUID
    name: str
    scopes: Tuple[str, ...]


@dataclass(frozen=True)
class AdminPrincipal:
    """The admin behind a verified session token."""

    id: uuid.UUID
    email: str
    role: str


def hash_password(password: str) -> str:
    """Salted scrypt hash in the form ``scrypt$n$r$p$salt$hash`` (base64 parts)."""
    salt = secrets.token_bytes(SALT_BYTES)
    derived = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=SCRYPT_KEY_LENGTH
    )
    return "$".join(
        ["scrypt", str(SCRYPT_N), str(SCRYPT_R), str(SCRYPT_P),
         base64.b64encode(salt).decode(), base64.b64encode(derived).decode()]
    )


def verify_password(password: str, stored: str) -> bool:
    """Constant-time check of ``password`` against a :func:`hash_password` value."""
    try:
        scheme, n, r, p, salt_b64, hash_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = base64.b64decode(hash_b64)
        derived = hashlib.scrypt(
            password.encode("utf-8"), salt=base64.b64decode(salt_b64), n=int(n), r=int(r), p=int(p),
            dklen=len(expected),
        )
        return hmac.compare_digest(derived, expected)
    except (ValueError, TypeError):
        logger.exception("Malformed password hash")
        return False


class AuthService:
    """Issues and verifies API keys and admin session tokens."""

    #: Hash compared against when the e-mail is unknown, so timing does not reveal accounts.
    _DUMMY_HASH = hash_password(secrets.token_hex(16))

    def __init__(self, database: Database, jwt_secret: str, token_ttl_minutes: int):
        """
        Args:
            database: Connected database.
            jwt_secret: HMAC secret for admin tokens.
            token_ttl_minutes: Admin token lifetime.
        """
        self._database = database
        self._jwt_secret = jwt_secret
        self._token_ttl = timedelta(minutes=token_ttl_minutes)
        self._key_cache: Dict[str, Tuple[Optional[VerifiedApiKey], float]] = {}

    # ------------------------------------------------------------------
    # API keys
    # ------------------------------------------------------------------

    @staticmethod
    def _hash_key(raw_key: str) -> str:
        """SHA-256 of a raw key (keys are high-entropy, so no salt/KDF is needed)."""
        return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

    async def verify_api_key(self, raw_key: str) -> Optional[VerifiedApiKey]:
        """
        Resolve a presented key.

        Returns:
            The key's identity and scopes, or ``None`` for unknown/revoked keys.
        """
        if not raw_key or not raw_key.startswith(API_KEY_PREFIX):
            return None
        key_hash = self._hash_key(raw_key)
        cached = self._key_cache.get(key_hash)
        if cached is not None and cached[1] > time.monotonic():
            return cached[0]

        async with self._database.session() as session:
            record = await AccessRepository(session).api_key_by_hash(key_hash)
            verified = None
            if record is not None and record.revoked_at is None:
                verified = VerifiedApiKey(record.id, record.name, tuple(record.scopes or ()))
                now = datetime.now(timezone.utc)
                if record.last_used_at is None or now - record.last_used_at > LAST_USED_WRITE_INTERVAL:
                    record.last_used_at = utc_now()
        if len(self._key_cache) >= MAX_CACHED_KEYS:
            self._key_cache.clear()
        self._key_cache[key_hash] = (verified, time.monotonic() + API_KEY_CACHE_SECONDS)
        return verified

    async def create_api_key(self, name: str, scopes: Optional[List[str]] = None) -> Tuple[ApiKey, str]:
        """
        Issue a new key.

        Returns:
            ``(record, raw_key)`` — the raw key is not stored and cannot be shown again.
        """
        raw_key = API_KEY_PREFIX + secrets.token_urlsafe(32)
        record = ApiKey(
            name=name,
            key_prefix=raw_key[:DISPLAY_PREFIX_LENGTH],
            key_hash=self._hash_key(raw_key),
            scopes=scopes or [SCOPE_CHAT],
        )
        async with self._database.session() as session:
            repository = AccessRepository(session)
            repository.add(record)
            await repository.flush()
        logger.info("API key created: %s (%s***)", name, record.key_prefix)
        return record, raw_key

    async def list_api_keys(self) -> List[ApiKey]:
        """All keys (hashes only), newest first."""
        async with self._database.session() as session:
            return await AccessRepository(session).list_api_keys()

    async def revoke_api_key(self, key_id: uuid.UUID) -> ApiKey:
        """
        Revoke a key; it stops working within :data:`API_KEY_CACHE_SECONDS`.

        Raises:
            NotFoundError: Unknown key.
        """
        async with self._database.session() as session:
            record = await AccessRepository(session).get_api_key(key_id)
            if record is None:
                raise NotFoundError("API key not found")
            if record.revoked_at is None:
                record.revoked_at = datetime.now(timezone.utc)
        self._key_cache.pop(record.key_hash, None)
        logger.info("API key revoked: %s (%s***)", record.name, record.key_prefix)
        return record

    # ------------------------------------------------------------------
    # Admin accounts
    # ------------------------------------------------------------------

    async def create_admin(self, email: str, password: str, role: str) -> AdminUser:
        """
        Create an admin account.

        Raises:
            InvalidRequestError: Weak password or unknown role.
            ConflictError: The e-mail is taken.
        """
        if role not in ADMIN_ROLES:
            raise InvalidRequestError(f"role must be one of {', '.join(ADMIN_ROLES)}")
        if len(password) < MIN_PASSWORD_LENGTH:
            raise InvalidRequestError(f"Password must have at least {MIN_PASSWORD_LENGTH} characters")
        async with self._database.session() as session:
            repository = AccessRepository(session)
            if await repository.admin_by_email(email):
                raise ConflictError("An admin with this e-mail already exists")
            user = AdminUser(email=email.strip().lower(), password_hash=hash_password(password), role=role)
            repository.add(user)
            await repository.flush()
        logger.info("Admin account created with role %s", role)
        return user

    async def authenticate(self, email: str, password: str) -> Optional[AdminUser]:
        """Return the enabled admin matching the credentials, else ``None``."""
        async with self._database.session() as session:
            user = await AccessRepository(session).admin_by_email(email.strip())
            if user is None or user.disabled:
                verify_password(password, self._DUMMY_HASH)
                return None
            if not verify_password(password, user.password_hash):
                return None
            user.last_login_at = utc_now()
        return user

    def issue_token(self, user: AdminUser) -> Tuple[str, datetime]:
        """Sign a session token for ``user``; returns ``(token, expires_at)``."""
        now = datetime.now(timezone.utc)
        expires_at = now + self._token_ttl
        claims = {"sub": str(user.id), "email": user.email, "role": user.role, "iat": now, "exp": expires_at}
        return jwt.encode(claims, self._jwt_secret, algorithm=JWT_ALGORITHM), expires_at

    async def verify_token(self, token: str) -> Optional[AdminPrincipal]:
        """
        Validate a session token and re-check the account is still enabled.

        Returns:
            The principal (with the account's current role), or ``None``.
        """
        try:
            claims = jwt.decode(token, self._jwt_secret, algorithms=[JWT_ALGORITHM])
            admin_id = uuid.UUID(claims["sub"])
        except (jwt.PyJWTError, KeyError, ValueError):
            return None
        async with self._database.session() as session:
            user = await AccessRepository(session).get_admin(admin_id)
        if user is None or user.disabled:
            return None
        return AdminPrincipal(user.id, user.email, user.role)

    async def get_admin(self, admin_id: uuid.UUID) -> AdminUser:
        """
        One admin account.

        Raises:
            NotFoundError: Unknown admin.
        """
        async with self._database.session() as session:
            user = await AccessRepository(session).get_admin(admin_id)
        if user is None:
            raise NotFoundError("Admin not found")
        return user

    async def list_admins(self) -> List[AdminUser]:
        """All admin accounts."""
        async with self._database.session() as session:
            return await AccessRepository(session).list_admins()

    async def update_admin(self, admin_id: uuid.UUID, role: Optional[str], disabled: Optional[bool]) -> AdminUser:
        """
        Change an admin's role or enabled state, never leaving zero owners.

        Raises:
            NotFoundError: Unknown admin.
            InvalidRequestError: Unknown role, or the change would remove the last owner.
        """
        if role is not None and role not in ADMIN_ROLES:
            raise InvalidRequestError(f"role must be one of {', '.join(ADMIN_ROLES)}")
        async with self._database.session() as session:
            repository = AccessRepository(session)
            user = await repository.get_admin(admin_id)
            if user is None:
                raise NotFoundError("Admin not found")
            loses_owner = user.role == ROLE_OWNER and not user.disabled and (
                (role is not None and role != ROLE_OWNER) or disabled is True
            )
            if loses_owner and await repository.count_active_owners() <= 1:
                raise InvalidRequestError("At least one enabled owner must remain")
            if role is not None:
                user.role = role
            if disabled is not None:
                user.disabled = disabled
        logger.info("Admin %s updated (role=%s, disabled=%s)", admin_id, role, disabled)
        return user

    async def change_password(self, admin_id: uuid.UUID, current_password: str, new_password: str) -> None:
        """
        Change one's own password.

        Raises:
            InvalidRequestError: Wrong current password or weak new password.
        """
        if len(new_password) < MIN_PASSWORD_LENGTH:
            raise InvalidRequestError(f"Password must have at least {MIN_PASSWORD_LENGTH} characters")
        async with self._database.session() as session:
            user = await AccessRepository(session).get_admin(admin_id)
            if user is None or not verify_password(current_password, user.password_hash):
                raise InvalidRequestError("Current password is incorrect")
            user.password_hash = hash_password(new_password)
        logger.info("Admin %s changed their password", admin_id)
