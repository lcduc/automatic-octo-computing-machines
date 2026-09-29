"""
Verifies host-site tokens (ID-05/06): who the logged-in user is, and their tier.

The host backend mints a short-lived JWT (``sub``, ``tier``, ``iss``, ``aud``,
``iat``, ``exp``, ``jti``); the widget passes it along with each request. Only
a token that verifies here yields a ``user_id`` (checklist Invariant 1).

Checks, for every mode: the algorithm is exactly the configured one (no
``alg`` confusion), signature, ``iss``, ``aud``, ``exp``/``iat`` with a small
leeway, a lifetime no longer than ``HOST_TOKEN_MAX_TTL_SECONDS``, a known
``tier``, and that the ``jti`` was not first presented by another visitor.
"""

# Standard library imports
import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, List, Optional

# Third-party imports
import jwt
from sqlalchemy.dialects.postgresql import insert

# Local imports
from config.identity_settings import HOST_AUTH_HS256, HOST_AUTH_NONE, HOST_AUTH_RS256, HostAuthConfig
from core.storage.database import Database
from core.storage.tables.access_tables import HostTokenUse
from models.caller import ANONYMOUS_LEVEL

logger = logging.getLogger(__name__)

ALGORITHMS = {HOST_AUTH_RS256: "RS256", HOST_AUTH_HS256: "HS256"}
REQUIRED_CLAIMS = ["sub", "tier", "iss", "aud", "iat", "exp", "jti"]
#: Same alphabet and length as visitor ids, so a ``sub`` can never smuggle markup or PII formats.
SUBJECT_PATTERN = re.compile(r"^[A-Za-z0-9_\-:.@]{1,128}$")
JTI_MAX_LENGTH = 128
#: Seconds the JWKS document is cached before it is fetched again.
JWKS_CACHE_SECONDS = 300


class HostTokenError(Exception):
    """The presented host token is not acceptable (the message is safe to log)."""


@dataclass(frozen=True)
class HostIdentity:
    """A verified logged-in user of the host site."""

    user_id: str
    tier: str
    tier_level: int
    token_id: str
    expires_at: datetime


KeyResolver = Callable[[str], object]


class HostIdentityService:
    """Turns a host token into a :class:`HostIdentity`, or refuses it."""

    def __init__(
        self,
        database: Database,
        mode: str,
        issuer: str,
        audience: str,
        tiers: List[str],
        max_ttl_seconds: int,
        leeway_seconds: int,
        key_resolver: Optional[KeyResolver] = None,
    ):
        """
        Args:
            database: Where token-visitor bindings are kept.
            mode: ``rs256``, ``hs256`` or ``none``.
            issuer: Required ``iss``.
            audience: Required ``aud``.
            tiers: Logged-in tiers, lowest first (level = position + 1).
            max_ttl_seconds: Longest accepted ``exp - iat``.
            leeway_seconds: Tolerated clock skew.
            key_resolver: Token -> verification key (PEM, JWKS lookup or HMAC secret).
        """
        self._database = database
        self._mode = mode
        self._issuer = issuer
        self._audience = audience
        self._tier_levels = {tier: index + 1 for index, tier in enumerate(tiers)}
        self._max_ttl = max_ttl_seconds
        self._leeway = leeway_seconds
        self._key_resolver = key_resolver

    @classmethod
    def from_config(cls, database: Database) -> "HostIdentityService":
        """The verifier described by the ``HOST_*`` settings."""
        mode = HostAuthConfig.HOST_AUTH_MODE()
        resolver: Optional[KeyResolver] = None
        if mode == HOST_AUTH_RS256 and HostAuthConfig.HOST_JWKS_URL():
            jwks = jwt.PyJWKClient(HostAuthConfig.HOST_JWKS_URL(), cache_keys=True, lifespan=JWKS_CACHE_SECONDS)
            resolver = lambda token: jwks.get_signing_key_from_jwt(token).key  # noqa: E731
        elif mode == HOST_AUTH_RS256 and HostAuthConfig.HOST_JWT_PUBLIC_KEY():
            public_key = HostAuthConfig.HOST_JWT_PUBLIC_KEY()
            resolver = lambda _token: public_key  # noqa: E731
        elif mode == HOST_AUTH_HS256 and HostAuthConfig.HOST_JWT_SECRET():
            secret = HostAuthConfig.HOST_JWT_SECRET()
            resolver = lambda _token: secret  # noqa: E731
        return cls(
            database, mode, HostAuthConfig.HOST_JWT_ISSUER(), HostAuthConfig.HOST_JWT_AUDIENCE(),
            HostAuthConfig.HOST_TIERS(), HostAuthConfig.HOST_TOKEN_MAX_TTL_SECONDS(),
            HostAuthConfig.HOST_TOKEN_LEEWAY_SECONDS(), resolver,
        )

    @property
    def enabled(self) -> bool:
        """False in ``none`` mode: every visitor is anonymous and tokens are ignored."""
        return self._mode != HOST_AUTH_NONE

    def tier_level(self, tier: str) -> int:
        """Access level of a tier name (0 for anonymous or unknown)."""
        return self._tier_levels.get(tier, ANONYMOUS_LEVEL)

    async def verify(self, token: str, visitor_id: str) -> HostIdentity:
        """
        Verify ``token`` presented by ``visitor_id``.

        Raises:
            HostTokenError: Invalid, expired, too long-lived, unknown tier, or
                replayed from another visitor.
        """
        if not self.enabled or self._key_resolver is None:
            raise HostTokenError("host sign-in is not configured")
        claims = await asyncio.to_thread(self._decode, token)
        subject, tier, token_id = str(claims["sub"]), str(claims["tier"]).lower(), str(claims["jti"])
        if not SUBJECT_PATTERN.match(subject):
            raise HostTokenError("sub is malformed")
        if tier not in self._tier_levels:
            raise HostTokenError(f"unknown tier {tier!r}")
        if not token_id or len(token_id) > JTI_MAX_LENGTH:
            raise HostTokenError("jti is malformed")
        if int(claims["exp"]) - int(claims["iat"]) > self._max_ttl:
            raise HostTokenError(f"token lifetime exceeds {self._max_ttl}s")
        expires_at = datetime.fromtimestamp(int(claims["exp"]), tz=timezone.utc)
        await self._bind(token_id, visitor_id, expires_at)
        return HostIdentity(subject, tier, self._tier_levels[tier], token_id, expires_at)

    def _decode(self, token: str) -> dict:
        """Signature and standard-claim checks (blocking: a JWKS lookup may hit the network)."""
        algorithm = ALGORITHMS[self._mode]
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") != algorithm:
                raise HostTokenError(f"token must be signed with {algorithm}")
            return jwt.decode(
                token, self._key_resolver(token), algorithms=[algorithm], audience=self._audience,
                issuer=self._issuer, leeway=self._leeway, options={"require": REQUIRED_CLAIMS},
            )
        except HostTokenError:
            raise
        except (jwt.PyJWTError, ValueError, TypeError) as exc:
            # An expired or foreign token is a normal client error, not a server failure.
            logger.warning("Host token rejected (%s)", type(exc).__name__)
            raise HostTokenError(f"{type(exc).__name__}: {exc}") from exc

    async def _bind(self, token_id: str, visitor_id: str, expires_at: datetime) -> None:
        """
        Record the first visitor to present ``token_id``; refuse any other.

        Raises:
            HostTokenError: The token is already bound to another visitor.
        """
        statement = insert(HostTokenUse).values(jti=token_id, visitor_id=visitor_id, expires_at=expires_at)
        # A no-op update makes RETURNING yield the existing row on conflict, in one round trip.
        statement = statement.on_conflict_do_update(
            index_elements=[HostTokenUse.jti], set_={"jti": statement.excluded.jti}
        ).returning(HostTokenUse.visitor_id)
        async with self._database.session() as session:
            bound_visitor = (await session.execute(statement)).scalar_one()
        if bound_visitor != visitor_id:
            logger.warning("Host token %s*** replayed from another visitor", token_id[:4])
            raise HostTokenError("token was issued to another browser session")
