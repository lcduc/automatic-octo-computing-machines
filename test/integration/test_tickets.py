"""
Async support tickets end to end (real app and PostgreSQL): opening triggers, visitor
contact with consent, masked contact, owner-only reveal, answers in the chat and by e-mail.
"""

import json

from .test_api import BFF_TOKEN, _admin_headers, client  # noqa: F401  (fixture)

HANDOFFS = "/api/v1/admin/handoffs"
VISITOR = "visitor-ticket01"


class FakeMailer:
    def __init__(self):
        self.sent = []

    async def send_async(self, recipients, subject, body):
        self.sent.append((list(recipients), subject, body))


def _headers(visitor=VISITOR):
    return {"X-Service-Token": BFF_TOKEN, "X-End-User-Id": visitor}


def _say(http, message, visitor=VISITOR, conversation_id=None):
    body = {"message": message, **({"conversation_id": conversation_id} if conversation_id else {})}
    response = http.post("/api/v1/chat/stream", json=body, headers=_headers(visitor))
    assert response.status_code == 200, response.text
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    return events[0]["conversation_id"], events[-1]


def _handoff_mode(http, admin):
    assert http.patch("/api/v1/admin/settings", json={"fallback_mode": "handoff"}, headers=admin).status_code == 200


def test_ticket_contact_answer_in_chat_and_by_email(client):  # noqa: F811
    admin = _admin_headers(client)
    mailer = FakeMailer()
    client.app.state.container.handoffs._mailer = mailer
    _handoff_mode(client, admin)
    conversation, done = _say(client, "cho tôi gặp nhân viên tư vấn")
    ticket = done["handoff_id"]
    assert done["outcome"] == "handoff" and done["reply_expected_by"]

    contact = f"/api/v1/handoffs/{ticket}/contact"
    assert client.post(contact, json={"consent": True}, headers=_headers()).status_code == 400  # anonymous: contact required
    assert client.post(contact, json={"email": "an@example.vn"}, headers=_headers()).status_code == 400  # no consent
    assert client.post(contact, json={"email": "an@example.vn", "consent": True}, headers=_headers("visitor-other1")).status_code == 404
    accepted = client.post(contact, json={"email": "an@example.vn", "details": "Hỏi về hợp đồng", "consent": True}, headers=_headers())
    assert accepted.status_code == 200

    listed = client.get(f"{HANDOFFS}?status=open", headers=admin).json()["items"][0]
    assert listed["contact_email"] == "a***@example.vn" and listed["has_contact"] and listed["due_at"]
    revealed = client.post(f"{HANDOFFS}/{ticket}/reveal-contact", headers=admin)
    assert revealed.json()["email"] == "an@example.vn"

    answered = client.post(f"{HANDOFFS}/{ticket}/answer", json={"text": "Chào bạn, hợp đồng thử việc là 60 ngày."}, headers=admin)
    assert answered.status_code == 200 and answered.json()["status"] == "answered" and answered.json()["emailed_at"]
    assert mailer.sent[0][0] == ["an@example.vn"] and "60 ngày" in mailer.sent[0][2]
    history = client.get(f"/api/v1/conversations/{conversation}", headers=_headers()).json()["messages"]
    assert history[-1]["outcome"] == "agent_reply" and "60 ngày" in history[-1]["content"]

    audit = client.get("/api/v1/admin/audit", headers=admin).json()["items"]
    assert any(entry["path"].endswith("/reveal-contact") for entry in audit)
    closed = client.patch(f"{HANDOFFS}/{ticket}", json={"status": "closed"}, headers=admin)
    assert closed.json()["closed_at"]


def test_one_ticket_per_conversation_and_the_bot_goes_quiet_once_staff_replied(client):  # noqa: F811
    admin = _admin_headers(client)
    _handoff_mode(client, admin)
    conversation, first = _say(client, "cho tôi gặp nhân viên tư vấn")
    assert first["handoff_id"]

    # Another handoff trigger while the ticket is open: same reply, no second ticket.
    _, second = _say(client, "tôi muốn khiếu nại dịch vụ", conversation_id=conversation)
    assert second["outcome"] == "handoff" and second["handoff_id"] is None
    assert len(client.get(HANDOFFS, headers=admin).json()["items"]) == 1

    ticket = first["handoff_id"]
    assert client.post(f"{HANDOFFS}/{ticket}/answer", json={"text": "Chào bạn, mình là nhân viên."}, headers=admin).status_code == 200
    listed = client.get("/api/v1/admin/conversations?status=staff_active", headers=admin).json()["items"]
    assert [item["id"] for item in listed] == [conversation]

    # Staff are in the conversation: the bot does not answer, even a plain greeting, and opens no ticket.
    _, quiet = _say(client, "xin chào", conversation_id=conversation)
    assert quiet["outcome"] == "handoff" and "Nhân viên hỗ trợ đang theo dõi" in quiet["text"]
    assert quiet["handoff_id"] is None and len(client.get(HANDOFFS, headers=admin).json()["items"]) == 1

    # Closing the ticket gives the conversation back to the bot.
    assert client.patch(f"{HANDOFFS}/{ticket}", json={"status": "closed"}, headers=admin).status_code == 200
    _, back = _say(client, "xin chào", conversation_id=conversation)
    assert back["outcome"] == "smalltalk"


def test_support_agents_answer_but_cannot_reveal_contact(client):  # noqa: F811
    admin = _admin_headers(client)
    _handoff_mode(client, admin)
    _, done = _say(client, "cho tôi gặp nhân viên")
    client.post("/api/v1/admin/users", json={"email": "agent@example.test", "password": "agent-password-1", "role": "support_agent"}, headers=admin)
    login = client.post("/api/v1/admin/auth/login", json={"email": "agent@example.test", "password": "agent-password-1"}).json()
    agent = {"Authorization": f"Bearer {login['access_token']}"}
    client.cookies.clear()
    assert client.post(f"{HANDOFFS}/{done['handoff_id']}/reveal-contact", headers=agent).status_code == 403
    assigned = client.patch(f"{HANDOFFS}/{done['handoff_id']}", json={"assigned_to": "agent@example.test"}, headers=agent)
    assert assigned.json()["status"] == "assigned"


def test_sensitive_topics_and_repeated_thumbs_down_open_tickets(client):  # noqa: F811
    admin = _admin_headers(client)
    _, denied_mode = _say(client, "tôi muốn khiếu nại dịch vụ")
    assert denied_mode["outcome"] != "handoff"  # fallback_mode=deny never hands off
    _handoff_mode(client, admin)
    _, done = _say(client, "tôi muốn khiếu nại dịch vụ")
    assert done["outcome"] == "handoff" and done["handoff_id"]
    tickets = client.get(HANDOFFS, headers=admin).json()["items"]
    assert tickets[0]["reason"] == "sensitive_topic"

    client.post("/api/v1/admin/knowledge/documents/text",
                json={"source": "FAQ", "title": "Giờ", "content": "Văn phòng mở cửa từ 8 giờ sáng các ngày trong tuần"}, headers=admin)
    conversation, first = _say(client, "Văn phòng mở cửa từ 8 giờ sáng các ngày trong tuần", visitor="visitor-rate0001")
    _, second = _say(client, "Văn phòng mở cửa từ 8 giờ sáng các ngày trong tuần", visitor="visitor-rate0001", conversation_id=conversation)
    rate = lambda message: client.post("/api/v1/feedback", json={"message_id": message, "rating": -1},  # noqa: E731
                                       headers=_headers("visitor-rate0001")).json()
    assert rate(first.get("message_id") or _message_ids(client, conversation)[0])["handoff_id"] is None
    assert rate(_message_ids(client, conversation)[1])["handoff_id"] is not None


def _message_ids(http, conversation):
    messages = http.get(f"/api/v1/conversations/{conversation}", headers=_headers("visitor-rate0001")).json()["messages"]
    return [message["id"] for message in messages if message["role"] == "assistant"]


def test_support_calendar_settings_are_validated(client):  # noqa: F811
    admin = _admin_headers(client)
    assert client.patch("/api/v1/admin/settings", json={"support_hours": {"mon": "17:00-08:00"}}, headers=admin).status_code == 400
    assert client.patch("/api/v1/admin/settings", json={"support_holidays": ["2027-02-06", "31/12"]}, headers=admin).status_code == 400
    ok = client.patch("/api/v1/admin/settings", json={"support_holidays": ["2027-02-06", "09-02"], "ticket_reply_hours": 4}, headers=admin)
    assert ok.status_code == 200
