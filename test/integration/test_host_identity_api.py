"""
Logged-in host users end to end (real FastAPI app and PostgreSQL, fake models):
conversation ownership, anonymous -> logged-in upgrade, logout, cross-device
access and token replay from another browser.
"""

import asyncio
import json
import time
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from starlette.testclient import TestClient

from .conftest import TEST_DATABASE_URL
from .test_api import BFF_TOKEN, FakeContainer, _reset_schema

ISSUER = "https://www.client.vn"
AUDIENCE = "https://chat.client.vn"
PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PUBLIC_PEM = PRIVATE_KEY.public_key().public_bytes(
    serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
).decode()
LAPTOP = "visitor-laptop-01"
PHONE = "visitor-phone-001"


def _host_token(sub="user-42", tier="user"):
    now = int(time.time())
    claims = {"sub": sub, "tier": tier, "iss": ISSUER, "aud": AUDIENCE, "iat": now, "exp": now + 600,
              "jti": uuid.uuid4().hex}
    return jwt.encode(claims, PRIVATE_KEY, algorithm="RS256")


@pytest.fixture
def client(monkeypatch):
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL not set")
    asyncio.run(_reset_schema())
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    monkeypatch.setenv("ADMIN_JWT_SECRET", "test-secret-" + "x" * 40)
    monkeypatch.setenv("BFF_SERVICE_TOKEN", BFF_TOKEN)
    monkeypatch.setenv("TOOL_CALLING_ENABLED", "false")
    monkeypatch.setenv("HOST_AUTH_MODE", "rs256")
    monkeypatch.setenv("HOST_JWT_PUBLIC_KEY", PUBLIC_PEM.replace("\n", "\\n"))
    monkeypatch.setenv("HOST_JWT_ISSUER", ISSUER)
    monkeypatch.setenv("HOST_JWT_AUDIENCE", AUDIENCE)
    from main import create_app

    with TestClient(create_app(FakeContainer)) as test_client:
        yield test_client


def _headers(visitor, token=None):
    headers = {"X-Service-Token": BFF_TOKEN, "X-End-User-Id": visitor}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _chat(client, visitor, token=None, conversation_id=None, expect=200):
    body = {"message": "xin chào"}
    if conversation_id:
        body["conversation_id"] = conversation_id
    response = client.post("/api/v1/chat/stream", json=body, headers=_headers(visitor, token))
    assert response.status_code == expect, response.text
    if expect != 200:
        return response
    frames = [line[len("data: "):] for line in response.text.splitlines() if line.startswith("data: ")]
    return json.loads(frames[0])["conversation_id"]


def test_logged_in_conversation_follows_the_user_and_hides_from_anonymous_visitors(client):
    laptop_token = _host_token()
    conversation = _chat(client, LAPTOP, laptop_token)
    assert client.get(f"/api/v1/conversations/{conversation}", headers=_headers(LAPTOP, laptop_token)).status_code == 200

    # After logout the same browser is anonymous and no longer sees the private history (ID-09).
    assert client.get(f"/api/v1/conversations/{conversation}", headers=_headers(LAPTOP)).status_code == 404
    # The same user on another device, with its own token, does.
    phone_token = _host_token()
    assert client.get(f"/api/v1/conversations/{conversation}", headers=_headers(PHONE, phone_token)).status_code == 200
    # Another user never does.
    stranger = _host_token(sub="user-99")
    assert client.get(f"/api/v1/conversations/{conversation}", headers=_headers(PHONE, stranger)).status_code == 404


def test_logging_in_mid_conversation_keeps_it_for_the_user(client):
    conversation = _chat(client, LAPTOP)  # anonymous
    token = _host_token()
    assert _chat(client, LAPTOP, token, conversation) == conversation  # ID-08 upgrade
    assert client.get(f"/api/v1/conversations/{conversation}", headers=_headers(LAPTOP)).status_code == 404
    assert client.get(f"/api/v1/conversations/{conversation}", headers=_headers(LAPTOP, token)).status_code == 200


def test_invalid_or_replayed_tokens_are_refused_with_invalid_token(client):
    token = _host_token()
    _chat(client, LAPTOP, token)
    replay = _chat(client, PHONE, token, expect=401)  # copied into another browser
    assert replay.headers["www-authenticate"] == 'Bearer error="invalid_token"'
    expired = jwt.encode({"sub": "u", "tier": "user", "iss": ISSUER, "aud": AUDIENCE, "iat": 1, "exp": 2, "jti": "old"},
                         PRIVATE_KEY, algorithm="RS256")
    _chat(client, LAPTOP, expired, expect=401)
    # The legitimate browser keeps using its token until it expires.
    _chat(client, LAPTOP, token)
