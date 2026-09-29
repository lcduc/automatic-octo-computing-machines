"""
Feedback review and the golden eval set through the admin API (ADM-12, RET-R3).
"""

import uuid

from core.storage.tables.conversation_tables import Conversation, Feedback, Message
from core.storage.tables.eval_tables import EvalCase

from .test_api import _admin_headers, client  # noqa: F401  (fixture)

ADMIN = "/api/v1/admin"
CITATION = {"document_id": "doc-1", "chunk_id": "c-1", "title": "Sổ tay FAQs", "source": "FAQ", "score": 0.9}


async def _rated_answer(database):
    async with database.session() as session:
        conversation = Conversation(end_user_id="visitor-eval01")
        session.add(conversation)
        await session.flush()
        session.add(Message(conversation_id=conversation.id, role="user",
                            content="Tôi là An, số 0912345678, quên mật khẩu thì làm sao?"))
        await session.flush()
        answer = Message(conversation_id=conversation.id, role="assistant", content="Bấm 'Quên mật khẩu'.",
                         outcome="answered", citations=[CITATION])
        session.add(answer)
        await session.flush()
        feedback = Feedback(message_id=answer.id, rating=-1, comment="thiếu bước")
        session.add(feedback)
        await session.flush()
        return str(conversation.id), str(answer.id), str(feedback.id)


async def _delete_conversation(database, conversation_id):
    async with database.session() as session:
        await session.delete(await session.get(Conversation, conversation_id))


async def _case_count(database):
    async with database.session() as session:
        return len((await session.execute(EvalCase.__table__.select())).all())


def test_review_feedback_and_build_the_eval_set(client):  # noqa: F811
    admin = _admin_headers(client)
    database = client.app.state.container.database
    conversation_id, message_id, feedback_id = client.portal.call(_rated_answer, database)

    assert client.get(f"{ADMIN}/feedback?reviewed=false", headers=admin).json()["total"] == 1
    assert client.patch(f"{ADMIN}/feedback/{feedback_id}", json={"reviewed": True}, headers=admin).status_code == 200
    assert client.get(f"{ADMIN}/feedback?reviewed=false", headers=admin).json()["total"] == 0
    reviewed = client.get(f"{ADMIN}/feedback?reviewed=true", headers=admin).json()["items"][0]
    assert reviewed["reviewed_at"] and reviewed["reviewed_by"]

    created = client.post(f"{ADMIN}/messages/{message_id}/eval-case",
                          json={"expected_answer": "Bấm 'Quên mật khẩu' rồi kiểm tra e-mail."}, headers=admin)
    assert created.status_code == 201, created.text
    case = created.json()
    assert "0912345678" not in case["question"] and "quên mật khẩu" in case["question"]
    assert case["expected_sources"] == ["Sổ tay FAQs"] and case["document_ids"] == ["doc-1"]
    assert client.post(f"{ADMIN}/messages/{message_id}/eval-case", json={}, headers=admin).status_code == 201

    exported = client.get(f"{ADMIN}/eval-cases/export", headers=admin).json()
    assert exported[0]["query"] == case["question"] and exported[0]["expected_source"] == "Sổ tay FAQs"

    # No link back: deleting the conversation leaves the eval set untouched.
    client.portal.call(_delete_conversation, database, uuid.UUID(conversation_id))
    assert client.portal.call(_case_count, database) == 2
    assert client.delete(f"{ADMIN}/eval-cases/{case['id']}", headers=admin).status_code == 200
    assert client.get(f"{ADMIN}/eval-cases", headers=admin).json()["total"] == 1
