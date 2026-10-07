"""
Document review against real PostgreSQL: every new document waits for an owner or
editor to approve it before the assistant may answer from it.
"""

import uuid

import pytest

from services.errors import ConflictError, InvalidRequestError, NotFoundError
from .test_api import _admin_headers, _approve, client  # noqa: F401  (fixture)
from .test_knowledge_service import kb  # noqa: F401  (fixture)

DOCUMENTS = "/api/v1/admin/knowledge/documents"
TEXT = {"source": "FAQ", "title": "Giờ làm việc", "content": "Văn phòng mở cửa từ 8 giờ sáng"}
REVIEWER = "editor@x.test"


@pytest.mark.asyncio
async def test_new_documents_are_not_searchable_until_approved_and_the_decision_is_recorded(kb):  # noqa: F811
    service, index = kb.service, kb.index
    typed = await service.create_text_document("FAQ", "Giờ làm việc", "Văn phòng mở cửa từ 8 giờ sáng.", {}, "owner@x.test")
    uploaded = await service.upload_file(b"Muc luong toi thieu\n\nThoi gian thu viec", "policy.txt", "contracts", None, {}, "owner@x.test")
    await kb.worker.process_next()
    await index.refresh()

    assert (typed.review_status, uploaded.review_status) == ("pending", "pending")
    assert index.snapshot.is_empty  # even though the owner created both

    approved = await service.review_document(typed.id, True, REVIEWER, "looks right")
    assert (approved.review_status, approved.reviewed_by, approved.review_note) == ("approved", REVIEWER, "looks right")
    assert approved.reviewed_at is not None
    assert {chunk.source for chunk in index.snapshot.chunks} == {"FAQ"}
    assert await service.review_counts() == {"pending": 1, "approved": 1, "rejected": 0}


@pytest.mark.asyncio
async def test_rejected_documents_stay_out_and_a_decision_is_final(kb):  # noqa: F811
    service, index = kb.service, kb.index
    document = await service.create_text_document("FAQ", "Doc", "some text", {}, None)

    rejected = await service.review_document(document.id, False, REVIEWER, "outdated")
    assert rejected.review_status == "rejected" and index.snapshot.is_empty
    for approve in (True, False):
        with pytest.raises(ConflictError, match="already rejected"):
            await service.review_document(document.id, approve, REVIEWER)
    with pytest.raises(NotFoundError):
        await service.review_document(uuid.uuid4(), True, REVIEWER)


@pytest.mark.asyncio
async def test_a_document_still_processing_cannot_be_approved(kb):  # noqa: F811
    document = await kb.service.upload_file(b"a\n\nb", "doc.txt", "general", None, {}, None)

    with pytest.raises(ConflictError, match="finished processing"):
        await kb.service.review_document(document.id, True, REVIEWER)
    assert (await kb.service.review_document(document.id, False, REVIEWER)).review_status == "rejected"


@pytest.mark.asyncio
async def test_only_an_approved_document_can_supersede_another(kb):  # noqa: F811
    service = kb.service
    old = await service.create_text_document("FAQ", "Old", "old text", {}, None, auto_approve=True)
    new = await service.create_text_document("FAQ", "New", "new text", {}, None)

    with pytest.raises(InvalidRequestError, match="Approve the document"):
        await service.update_document(new.id, {"supersedes_id": old.id})
    assert (await service.get_document(old.id)).effective_to is None

    await service.review_document(new.id, True, REVIEWER)
    await service.update_document(new.id, {"supersedes_id": old.id})
    assert (await service.get_document(old.id)).effective_to is not None


def test_access_tiers_start_with_everyone_then_the_host_tiers(client):  # noqa: F811
    tiers = client.get("/api/v1/admin/knowledge/access-tiers", headers=_admin_headers(client)).json()
    assert tiers[0] == "anonymous" and len(tiers) > 1


def _login(http, admin, role):
    email = f"{role}@example.test"
    http.post("/api/v1/admin/users", json={"email": email, "password": f"{role}-password-1", "role": role}, headers=admin)
    token = http.post("/api/v1/admin/auth/login", json={"email": email, "password": f"{role}-password-1"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_only_owner_and_editor_review_and_the_owner_is_not_exempt(client):  # noqa: F811
    owner = _admin_headers(client)
    created = client.post(f"{DOCUMENTS}/text", json=TEXT, headers=owner).json()
    assert created["review_status"] == "pending"
    review = f"{DOCUMENTS}/{created['id']}/review"

    for role in ("viewer", "support_agent"):
        assert client.post(review, json={"approve": True}, headers=_login(client, owner, role)).status_code == 403
    assert client.get(f"{DOCUMENTS}/{created['id']}", headers=owner).json()["review_status"] == "pending"

    editor = _login(client, owner, "editor")
    approved = client.post(review, json={"approve": True, "note": "ok"}, headers=editor)
    assert approved.status_code == 200 and approved.json()["reviewed_by"] == "editor@example.test"
    assert client.post(review, json={"approve": False}, headers=owner).status_code == 409

    pending = client.get(f"{DOCUMENTS}?review_status=pending", headers=owner).json()
    assert pending["total"] == 0
    assert client.get("/api/v1/admin/knowledge/review/counts", headers=owner).json() == {
        "pending": 0, "approved": 1, "rejected": 0,
    }


def test_an_api_key_cannot_approve_what_it_uploaded(client):  # noqa: F811
    owner = _admin_headers(client)
    key = client.post("/api/v1/admin/api-keys", json={"name": "ci", "scopes": ["documents:write"]}, headers=owner).json()["key"]
    client.cookies.clear()

    created = client.post(f"{DOCUMENTS}/text", json=TEXT, headers={"X-API-Key": key})
    assert created.status_code == 201 and created.json()["review_status"] == "pending"
    denied = client.post(f"{DOCUMENTS}/{created.json()['id']}/review", json={"approve": True}, headers={"X-API-Key": key})
    assert denied.status_code == 401
