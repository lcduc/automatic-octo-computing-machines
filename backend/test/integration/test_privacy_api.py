"""
Legal hold and data-subject requests through the admin API (PRV-03, RET-R2, RET-R5).
"""

from .test_api import _admin_headers, client  # noqa: F401  (fixture)
from .test_tickets import _handoff_mode, _headers, _say

ADMIN = "/api/v1/admin"


def _editor_headers(http):
    container = http.app.state.container
    http.portal.call(container.auth.create_admin, "editor@example.test", "editor-password-1", "editor")
    token = http.post(
        f"{ADMIN}/auth/login", json={"email": "editor@example.test", "password": "editor-password-1"}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_hold_export_and_delete_a_visitor(client):  # noqa: F811
    owner = _admin_headers(client)
    _handoff_mode(client, owner)
    kept, done = _say(client, "cho tôi gặp nhân viên tư vấn", visitor="visitor-priv01")
    ticket = done["handoff_id"]
    assert client.post(f"/api/v1/handoffs/{ticket}/contact", json={"email": "an@example.vn", "consent": True},
                       headers=_headers("visitor-priv01")).status_code == 200
    removed, _ = _say(client, "xin chào", visitor="visitor-priv01")

    editor = _editor_headers(client)
    assert client.put(f"{ADMIN}/handoffs/{ticket}/legal-hold", json={"held": True}, headers=editor).status_code == 403
    assert client.patch(f"{ADMIN}/settings", json={"retention_chat_days": 30}, headers=editor).status_code == 403
    held = client.put(f"{ADMIN}/handoffs/{ticket}/legal-hold", json={"held": True}, headers=owner)
    assert held.status_code == 200 and held.json()["legal_hold"] is True

    assert client.post(f"{ADMIN}/data-subjects/export", json={}, headers=owner).status_code == 422
    exported = client.post(f"{ADMIN}/data-subjects/export", json={"email": "AN@example.vn"}, headers=owner).json()
    assert [c["id"] for c in exported["conversations"]] == [kept]
    assert exported["tickets"][0]["contact_email"] == "an@example.vn"
    by_visitor = client.post(f"{ADMIN}/data-subjects/export", json={"visitor_id": "visitor-priv01"}, headers=owner).json()
    assert {c["id"] for c in by_visitor["conversations"]} == {kept, removed}

    deleted = client.post(f"{ADMIN}/data-subjects/delete", json={"visitor_id": "visitor-priv01"}, headers=owner).json()
    assert deleted["conversations"] == 1 and deleted["tickets"] == 0 and deleted["kept_on_hold"] == 2
    assert client.get(f"{ADMIN}/conversations/{removed}", headers=owner).status_code == 404
    assert client.get(f"{ADMIN}/conversations/{kept}", headers=owner).status_code == 200

    assert client.put(f"{ADMIN}/handoffs/{ticket}/legal-hold", json={"held": False}, headers=owner).status_code == 200
    released = client.post(f"{ADMIN}/data-subjects/delete", json={"email": "an@example.vn"}, headers=owner).json()
    assert released["conversations"] == 1 and released["kept_on_hold"] == 0
    assert client.get(f"{ADMIN}/conversations/{kept}", headers=owner).status_code == 404

    audit = client.get(f"{ADMIN}/audit?limit=50", headers=owner).json()["items"]
    paths = {entry["path"] for entry in audit}
    assert f"{ADMIN}/handoffs/{ticket}/legal-hold" in paths and f"{ADMIN}/data-subjects/delete" in paths
