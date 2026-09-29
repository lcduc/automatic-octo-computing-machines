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
from core.storage.tables.access_tables import (
    ADMIN_ROLES,
    API_KEY_SCOPES,
    DEFAULT_API_KEY_RATE_LIMIT,
    ROLE_OWNER,
    SCOPE_CHAT,
    AdminUser,
    ApiKey,
)
from .errors import ConflictError, InvalidRequestError, NotFoundError

logger = logging.getLogger(__name__)

#: Every issued API key starts with this marker so leaked keys are easy to spot (and scanners can match it).
API_KEY_PREFIX = "cb_live_"
#: Prefix of keys issued before the ``cb_live_`` format; still accepted.
LEGACY_API_KEY_PREFIX = "cbk_"
#: Longest per-key rate limit and expiry an owner can set.
MAX_API_KEY_RATE_LIMIT = 10_000
MAX_API_KEY_LIFETIME_DAYS = 3650
#: How long a rotated key keeps working by default, so clients can switch without downtime.
DEFAULT_ROTATION_GRACE_DAYS = 7
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

#: Name of the chat widget's server (BFF) among the internal services.
SERVICE_BFF = "bff"


@dataclass(frozen=True)
class VerifiedApiKey:
    """The parts of an API key needed per request."""

    id: uuid.UUID
    name: str
    scopes: Tuple[str, ...]
    rate_limit_per_minute: int = DEFAULT_API_KEY_RATE_LIMIT
    expires_at: Optional[datetime] = None

    def expired(self, now: datetime) -> bool:
        """True once the key's expiry has passed."""
        return self.expires_at is not None and now >= self.expires_at


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

    def __init__(
        self,
        database: Database,
        jwt_secret: str,
        token_ttl_minutes: int,
        service_tokens: Optional[Dict[str, str]] = None,
    ):
        """
        Args:
            database: Connected database.
            jwt_secret: HMAC secret for admin tokens.
            token_ttl_minutes: Admin token lifetime.
            service_tokens: Internal service name -> its generated token (e.g.
                ``{"bff": ...}``); services with an empty token are never admitted.
        """
        self._database = database
        self._jwt_secret = jwt_secret
        self._token_ttl = timedelta(minutes=token_ttl_minutes)
        self._key_cache: Dict[str, Tuple[Optional[VerifiedApiKey], float]] = {}
        self._service_tokens = {name: token for name, token in (service_tokens or {}).items() if token}

    # ------------------------------------------------------------------
    # Internal services
    # ------------------------------------------------------------------

    def verify_service_token(self, presented: str) -> Optional[str]:
        """
        Identify one of our own services by its generated token.

        Returns:
            The service name (e.g. ``bff``), or ``None`` for a missing or unknown token.
        """
        if not presented:
            return None
        for name, token in self._service_tokens.items():
            if hmac.compare_digest(presented.encode("utf-8"), token.encode("utf-8")):
                return name
        return None

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
            The key's identity, scopes and limits, or ``None`` for unknown,
            revoked or expired keys.
        """
        if not raw_key or not raw_key.startswith((API_KEY_PREFIX, LEGACY_API_KEY_PREFIX)):
            return None
        key_hash = self._hash_key(raw_key)
        now = datetime.now(timezone.utc)
        cached = self._key_cache.get(key_hash)
        if cached is not None and cached[1] > time.monotonic():
            return cached[0] if cached[0] is None or not cached[0].expired(now) else None

        async with self._database.session() as session:
            record = await AccessRepository(session).api_key_by_hash(key_hash)
            verified = None
            if record is not None and record.revoked_at is None:
                verified = VerifiedApiKey(
                    record.id, record.name, tuple(record.scopes or ()), record.rate_limit_per_minute, record.expires_at
                )
                if not verified.expired(now) and (
                    record.last_used_at is None or now - record.last_used_at > LAST_USED_WRITE_INTERVAL
                ):
                    record.last_used_at = utc_now()
        if len(self._key_cache) >= MAX_CACHED_KEYS:
            self._key_cache.clear()
        self._key_cache[key_hash] = (verified, time.monotonic() + API_KEY_CACHE_SECONDS)
        return verified if verified is None or not verified.expired(now) else None

    @staticmethod
    def _validate_key_settings(scopes: List[str], rate_limit_per_minute: int, expires_in_days: Optional[int]) -> None:
        """
        Raises:
            InvalidRequestError: Unknown or no scopes, or limits out of range.
        """
        unknown = sorted(set(scopes) - set(API_KEY_SCOPES))
        if not scopes or unknown:
            raise InvalidRequestError(f"scopes must be one or more of {', '.join(API_KEY_SCOPES)}")
        if not 1 <= rate_limit_per_minute <= MAX_API_KEY_RATE_LIMIT:
            raise InvalidRequestError(f"rate_limit_per_minute must be between 1 and {MAX_API_KEY_RATE_LIMIT}")
        if expires_in_days is not None and not 1 <= expires_in_days <= MAX_API_KEY_LIFETIME_DAYS:
            raise InvalidRequestError(f"expires_in_days must be between 1 and {MAX_API_KEY_LIFETIME_DAYS}")

    async def create_api_key(
        self,
        name: str,
        scopes: Optional[List[str]] = None,
        rate_limit_per_minute: int = DEFAULT_API_KEY_RATE_LIMIT,
        expires_in_days: Optional[int] = None,
        rotated_from_id: Optional[uuid.UUID] = None,
    ) -> Tuple[ApiKey, str]:
        """
        Issue a new ``cb_live_`` key.

        Returns:
            ``(record, raw_key)`` — only the SHA-256 is stored; the raw key cannot be shown again.

        Raises:
            InvalidRequestError: Unknown scopes or limits out of range.
        """
        scopes = list(dict.fromkeys(scopes or [SCOPE_CHAT]))
        self._validate_key_settings(scopes, rate_limit_per_minute, expires_in_days)
        raw_key = API_KEY_PREFIX + secrets.token_urlsafe(32)
        record = ApiKey(
            name=name,
            key_prefix=raw_key[:DISPLAY_PREFIX_LENGTH],
            key_hash=self._hash_key(raw_key),
            scopes=scopes,
            rate_limit_per_minute=rate_limit_per_minute,
            expires_at=datetime.now(timezone.utc) + timedelta(days=expires_in_days) if expires_in_days else None,
            rotated_from_id=rotated_from_id,
        )
        async with self._database.session() as session:
            repository = AccessRepository(session)
            repository.add(record)
            await repository.flush()
        logger.info("API key created: %s (%s***) scopes=%s", name, record.key_prefix, ",".join(scopes))
        return record, raw_key

    async def rotate_api_key(self, key_id: uuid.UUID, grace_days: int = DEFAULT_ROTATION_GRACE_DAYS) -> Tuple[ApiKey, str]:
        """
        Issue a replacement with the same name, scopes and limit; the old key
        keeps working for ``grace_days`` (0 = revoke it now), so both are valid
        while the client switches.

        Returns:
            ``(new_record, raw_key)``.

        Raises:
            NotFoundError: Unknown key.
            InvalidRequestError: The key is revoked or expired, or ``grace_days`` is out of range.
        """
        if not 0 <= grace_days <= 90:
            raise InvalidRequestError("grace_days must be between 0 and 90")
        now = datetime.now(timezone.utc)
        async with self._database.session() as session:
            old = await AccessRepository(session).get_api_key(key_id)
            if old is None:
                raise NotFoundError("API key not found")
            if old.revoked_at is not None or (old.expires_at is not None and old.expires_at <= now):
                raise InvalidRequestError("Only an active key can be rotated")
            ends = now + timedelta(days=grace_days)
            if grace_days == 0:
                old.revoked_at = now
            elif old.expires_at is None or old.expires_at > ends:
                old.expires_at = ends
            name, scopes, limit, old_hash = old.name, list(old.scopes or []), old.rate_limit_per_minute, old.key_hash
        self._key_cache.pop(old_hash, None)
        record, raw_key = await self.create_api_key(name, scopes, limit, rotated_from_id=key_id)
        logger.info("API key %s rotated; the old key works for %d more day(s)", key_id, grace_days)
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
