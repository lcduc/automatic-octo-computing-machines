"""
Server-to-server API keys end to end (real app and PostgreSQL): scopes per
endpoint, session-only routes, browser refusal, expiry, rotation, per-key
rate limits and audit attribution.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import update

from core.storage.tables.access_tables import ApiKey
from .test_api import _admin_headers, client  # noqa: F401  (fixture)

SOURCES = "/api/v1/admin/knowledge/sources"
TEXT_DOCUMENT = "/api/v1/admin/knowledge/documents/text"
CONVERSATIONS = "/api/v1/admin/conversations"


def _admin(http):
    """Bearer headers of the owner; the login cookie is dropped so key requests carry no session."""
    headers = _admin_headers(http)
    http.cookies.clear()
    return headers


def _create_key(http, admin, **body):
    response = http.post("/api/v1/admin/api-keys", json={"name": "client backend", **body}, headers=admin)
    assert response.status_code == 201, response.text
    created = response.json()
    assert created["key"].startswith("cb_live_") and created["key_prefix"] == created["key"][:12]
    return created


def _key(created):
    return {"X-API-Key": created["key"]}


def test_scopes_decide_which_admin_endpoints_a_key_reaches(client):  # noqa: F811
    admin = _admin(client)
    writer = _create_key(client, admin, scopes=["documents:write", "admin:read"])
    reader = _create_key(client, admin, scopes=["conversations:read"])

    document = {"source": "FAQ", "title": "Giờ làm việc", "content": "Văn phòng mở cửa từ 8 giờ"}
    assert client.post(TEXT_DOCUMENT, json=document, headers=_key(writer)).status_code == 201
    assert client.get(SOURCES, headers=_key(writer)).status_code == 200
    assert client.get(CONVERSATIONS, headers=_key(writer)).status_code == 403
    assert client.get(CONVERSATIONS, headers=_key(reader)).status_code == 200
    assert client.post(TEXT_DOCUMENT, json=document, headers=_key(reader)).status_code == 403

    # Keys, users, settings and the audit log are managed with a signed-in session only.
    for method, path in (("get", "/api/v1/admin/api-keys"), ("get", "/api/v1/admin/audit"), ("get", "/api/v1/admin/settings")):
        assert getattr(client, method)(path, headers=_key(writer)).status_code == 401

    audit = client.get("/api/v1/admin/audit", headers=admin).json()["items"]
    assert any(entry["actor_email"] == "api-key:client backend" and entry["path"] == TEXT_DOCUMENT for entry in audit)


def test_keys_are_refused_in_browser_contexts(client):  # noqa: F811
    created = _create_key(client, _admin(client), scopes=["admin:read"])
    for header in ({"Origin": "https://evil.test"}, {"Sec-Fetch-Site": "cross-site"}, {"Sec-Fetch-Mode": "cors"}):
        response = client.get(SOURCES, headers={**_key(created), **header})
        assert response.status_code == 403 and "server-to-server" in response.json()["detail"]


def test_expired_and_revoked_keys_stop_working(client):  # noqa: F811
    admin = _admin(client)
    created = _create_key(client, admin, scopes=["admin:read"], expires_in_days=30)
    assert created["expires_at"] is not None
    assert client.get(SOURCES, headers=_key(created)).status_code == 200

    async def expire():
        async with client.app.state.container.database.session() as session:
            await session.execute(update(ApiKey).where(ApiKey.id == created["id"]).values(
                expires_at=datetime.now(timezone.utc) - timedelta(minutes=1)))
        client.app.state.container.auth._key_cache.clear()

    client.portal.call(expire)
    assert client.get(SOURCES, headers=_key(created)).status_code == 401

    other = _create_key(client, admin, scopes=["admin:read"])
    assert client.post(f"/api/v1/admin/api-keys/{other['id']}/revoke", headers=admin).status_code == 200
    assert client.get(SOURCES, headers=_key(other)).status_code == 401


def test_rotation_keeps_both_keys_working_during_the_grace_period(client):  # noqa: F811
    admin = _admin(client)
    old = _create_key(client, admin, scopes=["admin:read"], rate_limit_per_minute=100)
    rotated = client.post(f"/api/v1/admin/api-keys/{old['id']}/rotate", json={"grace_days": 7}, headers=admin)
    assert rotated.status_code == 201
    new = rotated.json()
    assert new["rotated_from_id"] == old["id"] and new["scopes"] == ["admin:read"] and new["rate_limit_per_minute"] == 100
    assert client.get(SOURCES, headers=_key(old)).status_code == 200
    assert client.get(SOURCES, headers=_key(new)).status_code == 200
    listed = {key["id"]: key for key in client.get("/api/v1/admin/api-keys", headers=admin).json()}
    assert listed[old["id"]]["expires_at"] is not None and listed[new["id"]]["expires_at"] is None

    immediate = client.post(f"/api/v1/admin/api-keys/{new['id']}/rotate", json={"grace_days": 0}, headers=admin).json()
    client.app.state.container.auth._key_cache.clear()
    assert client.get(SOURCES, headers=_key(new)).status_code == 401
    assert client.get(SOURCES, headers=_key(immediate)).status_code == 200


def test_each_key_has_its_own_rate_limit_and_scopes_are_validated(client):  # noqa: F811
    admin = _admin(client)
    limited = _create_key(client, admin, scopes=["admin:read"], rate_limit_per_minute=2)
    assert [client.get(SOURCES, headers=_key(limited)).status_code for _ in range(3)] == [200, 200, 429]
    assert client.post("/api/v1/admin/api-keys", json={"name": "x", "scopes": ["root"]}, headers=admin).status_code == 422
    assert client.post("/api/v1/admin/api-keys", json={"name": "x", "scopes": []}, headers=admin).status_code == 422
