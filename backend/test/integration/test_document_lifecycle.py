"""
Document lifecycle end to end (real app and PostgreSQL): access tier, validity dates,
superseding versions, citing answers, and disabled documents never cited (EVAL-09).
"""

import json
from datetime import date, timedelta

import pytest

from .test_api import BFF_TOKEN, _admin_headers, _approve, client  # noqa: F401  (fixture)

DOCUMENTS = "/api/v1/admin/knowledge/documents"
CONTENT = "Văn phòng mở cửa từ 8 giờ sáng các ngày trong tuần"


def _document(http, admin, title):
    body = {"source": "FAQ", "title": title, "content": CONTENT}
    response = http.post(f"{DOCUMENTS}/text", json=body, headers=admin)
    assert response.status_code == 201, response.text
    _approve(http, admin, response.json()["id"])
    return response.json()["id"]


def _answer(http):
    headers = {"X-Service-Token": BFF_TOKEN, "X-End-User-Id": "visitor-life01"}
    response = http.post("/api/v1/chat/stream", json={"message": CONTENT}, headers=headers)
    assert response.status_code == 200, response.text
    frames = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    return frames[-1]


def _patch(http, admin, document_id, **changes):
    response = http.patch(f"{DOCUMENTS}/{document_id}", json=changes, headers=admin)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.hard_gate
def test_disabled_members_only_and_expired_documents_are_never_cited(client):  # noqa: F811
    admin = _admin_headers(client)
    document = _document(client, admin, "Giờ làm việc")
    assert _answer(client)["citations"][0]["document_id"] == document

    _patch(client, admin, document, enabled=False)
    assert _answer(client)["citations"] == []
    _patch(client, admin, document, enabled=True, access_tier="user")
    assert _answer(client)["citations"] == []  # anonymous visitor
    _patch(client, admin, document, access_tier="anonymous", effective_to=str(date.today() - timedelta(days=1)))
    assert _answer(client)["citations"] == []
    assert client.patch(f"{DOCUMENTS}/{document}", json={"access_tier": "vip"}, headers=admin).status_code == 400


def test_a_new_version_closes_the_old_one_and_answers_citing_it_are_listed(client):  # noqa: F811
    admin = _admin_headers(client)
    old = _document(client, admin, "Nội quy 2025")
    assert _answer(client)["citations"][0]["document_id"] == old
    citing = client.get(f"{DOCUMENTS}/{old}/citations", headers=admin).json()
    assert len(citing) == 1 and citing[0]["content"]

    new = _document(client, admin, "Nội quy 2026")
    starts = date.today() + timedelta(days=10)
    updated = _patch(client, admin, new, supersedes_id=old, effective_from=str(starts), version="2026", language="vi")
    assert updated["supersedes_id"] == old and updated["version"] == "2026"
    assert client.get(f"{DOCUMENTS}/{old}", headers=admin).json()["effective_to"] == str(starts - timedelta(days=1))
    # Until the new version starts, only the old one answers (scheduled activation).
    assert {item["document_id"] for item in _answer(client)["citations"]} == {old}
    bad = client.patch(f"{DOCUMENTS}/{new}", json={"effective_from": "2026-05-01", "effective_to": "2026-04-01"}, headers=admin)
    assert bad.status_code == 400
