"""
Security summary of the admin audit log (``GET /admin/audit/summary``).
"""

from datetime import datetime, timedelta, timezone

from app.core.storage.audit_repository import AuditRepository
from app.core.storage.tables.audit_tables import AdminAuditEntry
from .test_api import ADMIN_EMAIL, _admin_headers, client  # noqa: F401  (fixture)

ADMIN = "/api/v1/admin"
LOGIN = f"{ADMIN}/auth/login"
#: Days back of the entry that only the 90-day window reaches.
OLD_ENTRY_DAYS = 40

#: (method, path, status, client IP) of the seeded entries inside the default 30-day window.
RECENT_ENTRIES = [
    *[("POST", LOGIN, 401, "10.0.0.1")] * 3,
    *[("POST", LOGIN, 401, "10.0.0.2")] * 2,
    *[("POST", LOGIN, 401, f"10.0.0.{n}") for n in range(3, 7)],
    ("POST", LOGIN, 401, None),  # failed, but no IP to list
    ("POST", LOGIN, 429, "10.0.0.1"),  # rate limited: neither failed nor succeeded
    ("POST", f"{ADMIN}/handoffs/abc/reveal-contact", 200, "10.1.0.1"),
    ("POST", f"{ADMIN}/handoffs/abc/reveal-contact", 404, "10.1.0.1"),  # not a reveal
    ("POST", f"{ADMIN}/handoffs/abc/reveal-contact", 403, "10.1.0.1"),  # denied, not a reveal
    ("POST", f"{ADMIN}/api-keys", 201, "10.1.0.1"),
    ("POST", f"{ADMIN}/api-keys/k1/rotate", 200, "10.1.0.1"),
    ("POST", f"{ADMIN}/api-keys/k1/revoke", 200, "10.1.0.1"),
    ("PATCH", f"{ADMIN}/users/u1", 200, "10.1.0.1"),
    ("POST", f"{ADMIN}/auth/password", 200, "10.1.0.1"),
    ("DELETE", f"{ADMIN}/knowledge/documents/d1", 200, "10.1.0.1"),
    ("DELETE", f"{ADMIN}/settings/thanks_message", 200, "10.1.0.1"),
    ("DELETE", f"{ADMIN}/knowledge/documents/d2", 404, "10.1.0.1"),  # nothing deleted
    ("POST", f"{ADMIN}/data-subjects/export", 200, "10.1.0.1"),
    ("POST", f"{ADMIN}/data-subjects/delete", 200, "10.1.0.1"),
    ("POST", f"{ADMIN}/data-subjects/export", 422, "10.1.0.1"),  # invalid request
    ("PUT", f"{ADMIN}/conversations/c1/legal-hold", 200, "10.1.0.1"),
]
OLD_ENTRIES = [("POST", LOGIN, 401, "10.0.0.9"), ("DELETE", f"{ADMIN}/eval-cases/e1", 200, "10.1.0.1")]


async def _seed(container) -> None:
    """Insert the entries directly, so status codes, IPs and dates are exact."""
    old = datetime.now(timezone.utc) - timedelta(days=OLD_ENTRY_DAYS)
    async with container.database.session() as session:
        repository = AuditRepository(session)
        for entries, created_at in ((RECENT_ENTRIES, None), (OLD_ENTRIES, old)):
            for method, path, status_code, client_ip in entries:
                repository.add(
                    AdminAuditEntry(method=method, path=path, status_code=status_code, client_ip=client_ip,
                                    **({"created_at": created_at} if created_at else {}))
                )


def test_audit_summary_counts_each_category_for_owners_only(client):  # noqa: F811
    owner = _admin_headers(client)  # a successful sign-in from "testclient"
    client.cookies.clear()
    for _ in range(2):
        assert client.post(LOGIN, json={"email": ADMIN_EMAIL, "password": "wrong-password"}).status_code == 401
    new_user = {"email": "editor@example.test", "password": "editor-password-1", "role": "editor"}
    assert client.post(f"{ADMIN}/users", json=new_user, headers=owner).status_code == 201
    editor_token = client.post(LOGIN, json={"email": new_user["email"], "password": new_user["password"]}).json()["access_token"]
    client.cookies.clear()
    editor = {"Authorization": f"Bearer {editor_token}"}
    other_user = {**new_user, "email": "another@example.test"}
    assert client.post(f"{ADMIN}/users", json=other_user, headers=editor).status_code == 403
    client.portal.call(_seed, client.app.state.container)

    assert client.get(f"{ADMIN}/audit/summary", headers=editor).status_code == 403
    assert client.get(f"{ADMIN}/audit/summary?days=0", headers=owner).status_code == 422
    assert client.get(f"{ADMIN}/audit/summary?days=91", headers=owner).status_code == 422

    summary = client.get(f"{ADMIN}/audit/summary", headers=owner)
    assert summary.status_code == 200, summary.text
    body = summary.json()
    since = datetime.fromisoformat(body.pop("since"))
    assert timedelta(days=29) < datetime.now(timezone.utc) - since <= timedelta(days=30, minutes=1)
    assert body == {
        "logins_failed": 2 + 3 + 2 + 4 + 1,
        "logins_succeeded": 2,
        "contact_reveals": 1,
        "api_key_changes": 3,
        "account_changes": 3,  # the real POST /users, PATCH /users/u1, POST /auth/password
        "deletions": 2,
        "data_subject_requests": 2,
        "legal_hold_changes": 1,
        "denied": 2,  # the editor's POST /users and the refused reveal
        "failed_login_ips": [
            {"client_ip": "10.0.0.1", "count": 3},
            {"client_ip": "10.0.0.2", "count": 2},
            {"client_ip": "testclient", "count": 2},
            {"client_ip": "10.0.0.3", "count": 1},
            {"client_ip": "10.0.0.4", "count": 1},
        ],
    }

    wide = client.get(f"{ADMIN}/audit/summary?days=90", headers=owner).json()
    assert wide["logins_failed"] == body["logins_failed"] + 1 and wide["deletions"] == body["deletions"] + 1
