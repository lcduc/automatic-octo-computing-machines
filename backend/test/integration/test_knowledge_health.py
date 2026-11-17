"""
Document health report (``GET /admin/knowledge/health``).
"""

import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.config.settings import Config
from app.core.storage.tables.conversation_tables import Conversation, Feedback, Message
from app.core.storage.tables.knowledge_tables import (
    DOCUMENT_STATUS_FAILED,
    DOCUMENT_STATUS_READY,
    REVIEW_APPROVED,
    REVIEW_PENDING,
    KnowledgeDocument,
    KnowledgeSource,
)
from .test_api import _admin_headers, client  # noqa: F401  (fixture)

HEALTH = "/api/v1/admin/knowledge/health"
#: Days back of documents and answers that fall before the default 30-day window.
OLD_DAYS = 60
OLDEST_DAYS = 90
OUTSIDE_WINDOW_DAYS = 40


def _today() -> date:
    return datetime.now(ZoneInfo(Config.Server.APP_TIMEZONE())).date()


def _cite(*documents: KnowledgeDocument) -> list:
    return [{"document_id": str(document.id), "chunk_id": str(uuid.uuid4())} for document in documents]


async def _seed(container) -> dict:
    """Documents covering every list and count, and answers citing some of them."""
    now = datetime.now(timezone.utc)
    old, oldest = now - timedelta(days=OLD_DAYS), now - timedelta(days=OLDEST_DAYS)
    today = _today()
    async with container.database.session() as session:
        source_id = (await session.execute(select(KnowledgeSource.id).limit(1))).scalar_one()

        def document(title, created_at=None, **fields):
            values = {"status": DOCUMENT_STATUS_READY, "review_status": REVIEW_APPROVED, "enabled": True, **fields}
            if created_at:
                values["created_at"] = created_at
            row = KnowledgeDocument(id=uuid.uuid4(), source_id=source_id, title=title, **values)
            session.add(row)
            return row

        docs = {
            "cited": document("Cited by three answers", old),
            "rated_down": document("Cited by a thumbs-down answer", old),
            "uncited": document("Old and uncited", old),
            "uncited_oldest": document("Oldest and uncited", oldest),
            "uncited_new": document("New and uncited"),
            "expiring": document("Expiring in ten days", effective_to=today + timedelta(days=10)),
            "expiring_today": document("Expiring today", effective_to=today),
            "far_future": document("Valid for long", effective_to=today + timedelta(days=200)),
            "expired": document("Expired yesterday", effective_to=today - timedelta(days=1)),
            "scheduled": document("In force next week", effective_from=today + timedelta(days=5)),
            "disabled": document("Disabled", old, enabled=False, effective_to=today + timedelta(days=3)),
            "failed": document("Failed upload", status=DOCUMENT_STATUS_FAILED),
            "pending": document("Waiting for review", old, review_status=REVIEW_PENDING),
        }
        await session.flush()
        conversation = Conversation(id=uuid.uuid4(), end_user_id="visitor-health")
        session.add(conversation)
        await session.flush()

        def answer(citations, role="assistant", created_at=None, rating=None):
            message = Message(id=uuid.uuid4(), conversation_id=conversation.id, role=role, content="…", citations=citations,
                              **({"created_at": created_at} if created_at else {}))
            session.add(message)
            if rating is not None:
                session.add(Feedback(message_id=message.id, rating=rating))

        cited, rated_down = docs["cited"], docs["rated_down"]
        answer(_cite(cited, cited))  # two chunks of one document: one answer
        answer(_cite(cited) + [{"document_id": "not-a-uuid"}, {"document_id": str(uuid.uuid4())}, {"title": "no id"}])
        answer(_cite(cited), rating=1)
        answer(_cite(rated_down), rating=-1)
        answer(_cite(docs["uncited"]), created_at=now - timedelta(days=OUTSIDE_WINDOW_DAYS))  # before the window
        answer(_cite(docs["uncited"]), role="user")  # not an answer
    return {key: str(row.id) for key, row in docs.items()}


def test_knowledge_health_reports_usage_and_validity(client):  # noqa: F811
    admin = _admin_headers(client)
    ids = client.portal.call(_seed, client.app.state.container)
    today = _today()

    assert client.get(f"{HEALTH}?limit=51", headers=admin).status_code == 422
    response = client.get(HEALTH, headers=admin)
    assert response.status_code == 200, response.text
    body = response.json()
    assert datetime.fromisoformat(body.pop("since")).date() == today - timedelta(days=29)

    def ref(key, title):
        return {"document_id": ids[key], "title": title}

    assert body == {
        "documents": 10,
        "disabled": 1,
        "failed": 1,
        "most_cited": [
            {**ref("cited", "Cited by three answers"), "citations": 3},
            {**ref("rated_down", "Cited by a thumbs-down answer"), "citations": 1},
        ],
        "never_cited": {
            "count": 2,
            "items": [
                {**ref("uncited_oldest", "Oldest and uncited"), "created_at": body["never_cited"]["items"][0]["created_at"]},
                {**ref("uncited", "Old and uncited"), "created_at": body["never_cited"]["items"][1]["created_at"]},
            ],
        },
        "not_helpful": [{**ref("rated_down", "Cited by a thumbs-down answer"), "count": 1}],
        "expiring": [
            {**ref("expiring_today", "Expiring today"), "effective_to": today.isoformat()},
            {**ref("expiring", "Expiring in ten days"), "effective_to": (today + timedelta(days=10)).isoformat()},
        ],
        "scheduled": [{**ref("scheduled", "In force next week"), "effective_from": (today + timedelta(days=5)).isoformat()}],
    }

    limited = client.get(f"{HEALTH}?limit=1", headers=admin).json()
    assert [row["document_id"] for row in limited["most_cited"]] == [ids["cited"]]
    assert limited["never_cited"]["count"] == 2
    assert [row["document_id"] for row in limited["never_cited"]["items"]] == [ids["uncited_oldest"]]

    # A 90-day window reaches the older answer, so that document is no longer uncited.
    wide = client.get(f"{HEALTH}?days=90", headers=admin).json()
    assert [row["document_id"] for row in wide["never_cited"]["items"]] == [ids["uncited_oldest"]]
