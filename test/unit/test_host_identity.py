"""HostIdentityService verifies host-site tokens (real RSA keys; the visitor binding is stubbed, no database)."""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from services.host_identity_service import HostIdentityService, HostTokenError

ISSUER = "https://www.client.vn"
AUDIENCE = "https://chat.client.vn"


def _keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()
    return private_key, public_pem


PRIVATE_KEY, PUBLIC_PEM = _keypair()
OTHER_PRIVATE_KEY, _ = _keypair()


def _claims(**overrides):
    now = int(time.time())
    claims = {"sub": "user-42", "tier": "user", "iss": ISSUER, "aud": AUDIENCE,
              "iat": now, "exp": now + 600, "jti": "jti-1"}
    claims.update(overrides)
    return {key: value for key, value in claims.items() if value is not None}


def _token(key=PRIVATE_KEY, algorithm="RS256", headers=None, **overrides):
    return jwt.encode(_claims(**overrides), key, algorithm=algorithm, headers=headers)


def _service(mode="rs256", resolver=lambda _token: PUBLIC_PEM):
    service = HostIdentityService(None, mode, ISSUER, AUDIENCE, ["user", "premium"], 900, 30, resolver)
    service.bindings = []

    async def bind(token_id, visitor_id, expires_at):
        service.bindings.append((token_id, visitor_id))

    service._bind = bind
    return service


@pytest.mark.asyncio
async def test_a_valid_rs256_token_yields_the_user_and_tier_and_is_bound_to_the_visitor():
    service = _service()
    identity = await service.verify(_token(tier="premium"), "visitor-0001")
    assert (identity.user_id, identity.tier, identity.tier_level) == ("user-42", "premium", 2)
    assert service.bindings == [("jti-1", "visitor-0001")]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "token, reason",
    [
        (lambda: _token(key=OTHER_PRIVATE_KEY), "InvalidSignature"),
        (lambda: _token(exp=int(time.time()) - 120), "ExpiredSignature"),
        (lambda: _token(iss="https://evil.test"), "InvalidIssuer"),
        (lambda: _token(aud="https://other-chat.test"), "InvalidAudience"),
        (lambda: _token(jti=None), "MissingRequiredClaim"),
        (lambda: _token(tier="admin"), "unknown tier"),
        (lambda: _token(sub="<script>"), "sub is malformed"),
        (lambda: _token(iat=int(time.time()), exp=int(time.time()) + 3600), "lifetime exceeds"),
        # Algorithm confusion: an HS256 token "signed" with the public key must never pass as RS256.
        (lambda: jwt.encode(_claims(), "not-the-rsa-key-but-long-enough-0123456789", algorithm="HS256"), "RS256"),
    ],
)
async def test_invalid_tokens_are_refused(token, reason):
    with pytest.raises(HostTokenError, match=reason):
        await _service().verify(token(), "visitor-0001")


@pytest.mark.asyncio
async def test_hs256_mode_verifies_with_the_shared_secret_and_none_mode_ignores_tokens():
    secret = "s" * 48
    identity = await _service("hs256", lambda _token: secret).verify(_token(key=secret, algorithm="HS256"), "visitor-0001")
    assert identity.user_id == "user-42"
    with pytest.raises(HostTokenError, match="HS256"):
        await _service("hs256", lambda _token: secret).verify(_token(), "visitor-0001")
    disabled = _service("none", None)
    assert not disabled.enabled and disabled.tier_level("user") == 1
    with pytest.raises(HostTokenError, match="not configured"):
        await disabled.verify(_token(), "visitor-0001")


@pytest.fixture
def jwks_url():
    """A local HTTP server publishing the host's JWKS (PyJWT only fetches JWKS over http(s))."""
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(PRIVATE_KEY.public_key()))
    jwk.update({"kid": "host-key-1", "use": "sig", "alg": "RS256"})
    body = json.dumps({"keys": [jwk]}).encode()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/.well-known/jwks.json"
    server.shutdown()


@pytest.mark.asyncio
async def test_jwks_mode_picks_the_signing_key_by_kid(jwks_url, monkeypatch):
    monkeypatch.setenv("HOST_AUTH_MODE", "rs256")
    monkeypatch.setenv("HOST_JWKS_URL", jwks_url)
    monkeypatch.setenv("HOST_JWT_ISSUER", ISSUER)
    monkeypatch.setenv("HOST_JWT_AUDIENCE", AUDIENCE)
    service = HostIdentityService.from_config(None)

    async def bind(token_id, visitor_id, expires_at):
        return None

    service._bind = bind
    identity = await service.verify(_token(headers={"kid": "host-key-1"}), "visitor-0001")
    assert identity.user_id == "user-42"
    with pytest.raises(HostTokenError):
        await service.verify(_token(headers={"kid": "unknown-kid"}), "visitor-0001")
