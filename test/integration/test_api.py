"""
End-to-end API test: the real FastAPI app and PostgreSQL, with fake models/LLM.

Covers auth + CORS, admin knowledge management, streamed chat with
citations, conversation restore, feedback, both fallback modes, handoffs,
usage accounting, logs, rate limiting and role checks.
"""

import asyncio
import json

import pytest
from sqlalchemy import text
from starlette.testclient import TestClient

from api.container import AppContainer
from core.storage.database import Database
from core.storage.tables import Base
from models.llm import LLMResult, LLMUsage, StreamDelta
from .conftest import DEFAULT_SOURCES, TEST_DATABASE_URL, FakeEmbeddingService, FakeProcessor

ORIGIN = "http://localhost:3000"
ADMIN_EMAIL = "owner@example.test"
ADMIN_PASSWORD = "correct-horse-battery"
VISITOR = {"X-End-User-Id": "visitor-0001"}


class FakeLLM:
    """Answers every question the same way and reports usage."""

    name = "fake"

    def __init__(self):
        self.stream_calls = 0

    def check_availability(self):
        return True

    def close(self):
        pass

    async def complete_async(self, messages, model=None):
        if model and model.startswith("missing-"):
            raise ValueError(f"The model {model} does not exist")
        return LLMResult(messages[-1]["content"].replace("Câu hỏi tiếp theo: ", ""), LLMUsage("fake", "light", 5, 5))

    async def stream(self, messages, model=None):
        self.stream_calls += 1
        for piece in ("Văn phòng ", "mở cửa ", "lúc 8 giờ."):
            yield StreamDelta(text=piece)
        yield StreamDelta(usage=LLMUsage("fake", "fake-main", 120, 30))


class FakeContainer(AppContainer):
    """The real container with model-backed parts replaced by fakes."""

    async def _load_embedding_service(self):
        return FakeEmbeddingService()

    async def _load_reranker(self):
        return None

    def _create_llm(self):
        return FakeLLM()

    def _openai_extras(self):
        return None

    def _processor_factory(self):
        return FakeProcessor


async def _reset_schema() -> None:
    db = Database(TEST_DATABASE_URL, pool_size=1)
    db.connect()
    async with db.engine.begin() as connection:
        await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
        for name in DEFAULT_SOURCES:
            await connection.execute(
                text("INSERT INTO knowledge_sources (name, description, priority, enabled) VALUES (:n, '', 1.0, true)"),
                {"n": name},
            )
    await db.close()


@pytest.fixture
def client(monkeypatch):
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL not set")
    asyncio.run(_reset_schema())
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    monkeypatch.setenv("ADMIN_JWT_SECRET", "test-secret-" + "x" * 40)
    monkeypatch.setenv("CORS_ORIGINS", ORIGIN)
    monkeypatch.setenv("SIMILARITY_THRESHOLD", "0.5")
    monkeypatch.setenv("RATE_LIMIT_USER_PER_MINUTE", "8")
    monkeypatch.setenv("TOOL_CALLING_ENABLED", "false")
    from main import create_app

    with TestClient(create_app(FakeContainer)) as test_client:
        container = test_client.app.state.container
        test_client.portal.call(container.auth.create_admin, ADMIN_EMAIL, ADMIN_PASSWORD, "owner")
        _, raw_key = test_client.portal.call(container.auth.create_api_key, "test frontend")
        test_client.api_key = raw_key
        yield test_client


def _admin_headers(client):
    response = client.post("/api/v1/admin/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _chat(client, message, conversation_id=None, user=VISITOR):
    body = {"message": message}
    if conversation_id:
        body["conversation_id"] = conversation_id
    response = client.post("/api/v1/chat/stream", json=body, headers={"X-API-Key": client.api_key, **user})
    assert response.status_code == 200, response.text
    events = []
    for frame in response.text.split("\n\n"):
        data = [line[len("data: "):] for line in frame.splitlines() if line.startswith("data: ")]
        if data:
            events.append(json.loads(data[0]))
    return events


def test_auth_cors_and_security_headers(client):
    preflight = client.options(
        "/api/v1/chat/stream",
        headers={"Origin": ORIGIN, "Access-Control-Request-Method": "POST",
                 "Access-Control-Request-Headers": "x-api-key,x-end-user-id,content-type"},
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == ORIGIN

    denied = client.post("/api/v1/chat/stream", json={"message": "hi"}, headers={"Origin": ORIGIN, **VISITOR})
    assert denied.status_code == 401
    assert denied.headers["access-control-allow-origin"] == ORIGIN
    assert denied.headers["x-content-type-options"] == "nosniff"
    assert denied.headers["x-request-id"]

    no_visitor = client.post("/api/v1/chat/stream", json={"message": "hi"}, headers={"X-API-Key": client.api_key})
    assert no_visitor.status_code == 400
    assert client.get("/api/v1/admin/settings").status_code == 401
    assert client.get("/health/ready").json()["status"] == "ok"


def test_knowledge_chat_feedback_and_admin_views(client):
    admin = _admin_headers(client)
    created = client.post(
        "/api/v1/admin/knowledge/documents/text",
        json={"source": "FAQ", "title": "Giờ làm việc", "content": "Văn phòng mở cửa từ 8 giờ sáng các ngày trong tuần",
              "metadata": {"url": "https://example.test/gio-lam-viec"}},
        headers=admin,
    )
    assert created.status_code == 201, created.text

    events = _chat(client, "văn phòng mở cửa mấy giờ")
    assert [e["type"] for e in events][0] == "meta" and events[-1]["type"] == "done"
    done = events[-1]
    assert done["outcome"] == "answered"
    assert done["citations"][0]["source"] == "FAQ"
    assert done["citations"][0]["url"] == "https://example.test/gio-lam-viec"
    conversation_id, message_id = events[0]["conversation_id"], events[0]["message_id"]

    follow_up = _chat(client, "văn phòng mở cửa ngày nào", conversation_id=conversation_id)
    assert follow_up[0]["conversation_id"] == conversation_id

    history = client.get(
        f"/api/v1/conversations/{conversation_id}", headers={"X-API-Key": client.api_key, **VISITOR}
    ).json()
    assert [m["role"] for m in history["messages"]] == ["user", "assistant", "user", "assistant"]
    stranger = client.get(
        f"/api/v1/conversations/{conversation_id}", headers={"X-API-Key": client.api_key, "X-End-User-Id": "someone-else"}
    )
    assert stranger.status_code == 404

    rated = client.post(
        "/api/v1/feedback", json={"message_id": message_id, "rating": -1, "comment": "thiếu giờ nghỉ trưa"},
        headers={"X-API-Key": client.api_key, **VISITOR},
    )
    assert rated.status_code == 200
    inbox = client.get("/api/v1/admin/feedback", headers=admin).json()
    assert inbox["items"][0]["question"] == "văn phòng mở cửa mấy giờ"
    assert inbox["items"][0]["comment"] == "thiếu giờ nghỉ trưa"

    detail = client.get(f"/api/v1/admin/conversations/{conversation_id}", headers=admin).json()
    assert detail["messages"][1]["prompt_tokens"] == 120
    summary = client.get("/api/v1/admin/usage/summary?days=1", headers=admin).json()
    assert summary["totals"]["completion_tokens"] >= 60
    assert summary["outcomes"]["answered"] == 2
    assert client.get("/api/v1/admin/logs?contains=chat/stream", headers=admin).status_code == 200
    system = client.get("/api/v1/admin/system", headers=admin).json()
    assert system["ingestion_queue"] == {"pending": 0, "in_progress": 0, "oldest_pending_seconds": None}


def test_fallback_modes_skip_the_llm_and_record_handoffs(client):
    admin = _admin_headers(client)
    llm = client.app.state.container.llm

    denied = _chat(client, "dự báo thời tiết Hà Nội ngày mai")[-1]
    assert denied["outcome"] == "denied" and "chưa có thông tin" in denied["text"]

    assert client.patch("/api/v1/admin/settings", json={"fallback_mode": "handoff"}, headers=admin).status_code == 200
    handed_off = _chat(client, "dự báo thời tiết Hà Nội ngày mai")[-1]
    assert handed_off["outcome"] == "handoff" and handed_off["handoff_id"]
    requested = _chat(client, "cho tôi gặp nhân viên tư vấn")[-1]
    assert requested["outcome"] == "handoff"
    assert llm.stream_calls == 0

    handoffs = client.get("/api/v1/admin/handoffs?status=pending", headers=admin).json()
    assert handoffs["total"] == 2
    resolved = client.patch(
        f"/api/v1/admin/handoffs/{handoffs['items'][0]['id']}", json={"status": "resolved", "note": "đã gọi lại"},
        headers=admin,
    )
    assert resolved.json()["status"] == "resolved"


def test_rate_limit_and_roles(client):
    admin = _admin_headers(client)
    headers = {"X-API-Key": client.api_key, "X-End-User-Id": "burst-visitor-1"}
    statuses = [client.post("/api/v1/chat/stream", json={"message": "xin chào"}, headers=headers).status_code
                for _ in range(9)]
    assert statuses[:8] == [200] * 8 and statuses[8] == 429

    container = client.app.state.container
    client.portal.call(container.auth.create_admin, "viewer@example.test", "viewer-password-1", "viewer")
    token = client.post(
        "/api/v1/admin/auth/login", json={"email": "viewer@example.test", "password": "viewer-password-1"}
    ).json()["access_token"]
    viewer = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/v1/admin/knowledge/sources", headers=viewer).status_code == 200
    forbidden = client.post(
        "/api/v1/admin/knowledge/documents/text",
        json={"source": "FAQ", "title": "x", "content": "y"}, headers=viewer,
    )
    assert forbidden.status_code == 403
    assert client.get("/api/v1/admin/api-keys", headers=viewer).status_code == 403
    assert client.get("/api/v1/admin/api-keys", headers=admin).status_code == 200


def test_chunking_strategies_preview_and_rechunk(client):
    admin = _admin_headers(client)
    strategies = client.get("/api/v1/admin/knowledge/chunking/strategies", headers=admin).json()
    assert {s["name"] for s in strategies} >= {"auto", "legal_article", "qa_pair"}

    bad = client.post(
        "/api/v1/admin/knowledge/documents/upload",
        data={"source": "general", "chunking": '{"strategy": "legal_article", "max_chars": 5}'},
        files={"file": ("luat.txt", "Điều 1. Nội dung".encode("utf-8"), "text/plain")},
        headers=admin,
    )
    assert bad.status_code == 422 and "Invalid chunking" in bad.text
    held = client.post(
        "/api/v1/admin/knowledge/documents/upload",
        data={"source": "general", "chunking": '{"strategy": "legal_article"}', "enabled": "false"},
        files={"file": ("luat.txt", "Điều 1. Nội dung".encode("utf-8"), "text/plain")},
        headers=admin,
    ).json()
    assert held["enabled"] is False and held["chunking"]["strategy"] == "legal_article"

    created = client.post(
        "/api/v1/admin/knowledge/documents/text",
        json={"source": "FAQ", "title": "Hỏi đáp", "content": "Hỏi: Phí bao nhiêu?\nĐáp: Miễn phí.\nHỏi: Ở đâu?\nĐáp: Hà Tĩnh.",
              "chunking": {"strategy": "qa_pair"}},
        headers=admin,
    ).json()
    assert created["chunk_count"] == 2 and created["can_rechunk"] is True
    url = f"/api/v1/admin/knowledge/documents/{created['id']}"

    preview = client.post(f"{url}/chunking/preview", json={"chunking": {"strategy": "whole"}, "limit": 1}, headers=admin)
    assert preview.status_code == 200, preview.text
    assert preview.json()["chunk_count"] == 1 and len(preview.json()["chunks"]) == 1
    assert client.get(url, headers=admin).json()["chunk_count"] == 2  # a preview saves nothing

    rechunked = client.post(f"{url}/rechunk", json={"chunking": {"strategy": "whole"}}, headers=admin)
    assert rechunked.status_code == 200, rechunked.text
    assert rechunked.json()["chunk_count"] == 1 and rechunked.json()["chunking"] == {"strategy": "whole"}
    unknown = client.post(
        "/api/v1/admin/knowledge/documents/00000000-0000-0000-0000-000000000000/rechunk",
        json={"chunking": {"strategy": "auto"}}, headers=admin,
    )
    assert unknown.status_code == 404

    container = client.app.state.container
    client.portal.call(container.auth.create_admin, "reader@example.test", "reader-password-1", "viewer")
    token = client.post(
        "/api/v1/admin/auth/login", json={"email": "reader@example.test", "password": "reader-password-1"}
    ).json()["access_token"]
    viewer = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/v1/admin/knowledge/chunking/strategies", headers=viewer).status_code == 200
    assert client.post(f"{url}/chunking/preview", json={"chunking": {"strategy": "auto"}}, headers=viewer).status_code == 403


def _cookie_login(client, email=ADMIN_EMAIL, password=ADMIN_PASSWORD):
    response = client.post("/api/v1/admin/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response


def test_cookie_session_needs_the_csrf_header_for_writes_and_logout_clears_it(client):
    login = _cookie_login(client)
    cookie = login.headers["set-cookie"].lower()
    assert "admin_session=" in cookie and "httponly" in cookie and "samesite=strict" in cookie
    assert "path=/api/v1/admin" in cookie

    assert client.get("/api/v1/admin/auth/me").json()["email"] == ADMIN_EMAIL
    body = {"greeting_message": "Xin chào!"}
    assert client.patch("/api/v1/admin/settings", json=body).status_code == 403
    assert client.patch("/api/v1/admin/settings", json=body, headers={"X-Admin-Request": "1"}).status_code == 200

    assert client.post("/api/v1/admin/auth/logout").status_code == 200
    assert client.get("/api/v1/admin/auth/me").status_code == 401


def test_admin_writes_and_sign_ins_are_audited_without_secrets(client):
    admin = _admin_headers(client)
    client.cookies.clear()
    assert client.post("/api/v1/admin/auth/login", json={"email": ADMIN_EMAIL, "password": "wrong-password"}).status_code == 401
    client.patch("/api/v1/admin/settings", json={"thanks_message": "Cảm ơn!"}, headers=admin)
    created = client.post(
        "/api/v1/admin/users", json={"email": "agent@example.test", "password": "agent-password-1", "role": "support_agent"},
        headers=admin,
    )
    assert created.status_code == 201

    entries = client.get("/api/v1/admin/audit", headers=admin).json()["items"]
    by_path = {(e["method"], e["path"], e["status_code"]): e for e in entries}
    settings_entry = by_path[("PATCH", "/api/v1/admin/settings", 200)]
    assert settings_entry["actor_email"] == ADMIN_EMAIL and settings_entry["actor_role"] == "owner"
    assert settings_entry["request_body"] == {"thanks_message": "Cảm ơn!"}
    assert settings_entry["response_body"]["thanks_message"] == "Cảm ơn!"
    user_entry = by_path[("POST", "/api/v1/admin/users", 201)]
    assert user_entry["request_body"]["password"] == "***"
    failed = by_path[("POST", "/api/v1/admin/auth/login", 401)]
    assert failed["actor_email"] == ADMIN_EMAIL and failed["request_body"]["password"] == "***"
    assert by_path[("POST", "/api/v1/admin/auth/login", 200)]["response_body"]["access_token"] == "***"

    async def tamper():
        db = Database(TEST_DATABASE_URL, pool_size=1)
        db.connect()
        try:
            async with db.engine.begin() as connection:
                await connection.execute(text("UPDATE admin_audit_log SET actor_email = 'someone-else'"))
        finally:
            await db.close()

    with pytest.raises(Exception, match="append-only"):
        asyncio.run(tamper())


def test_support_agent_works_handoffs_but_cannot_change_knowledge_or_read_audit(client):
    admin = _admin_headers(client)
    client.post(
        "/api/v1/admin/users", json={"email": "agent@example.test", "password": "agent-password-1", "role": "support_agent"},
        headers=admin,
    )
    client.patch("/api/v1/admin/settings", json={"fallback_mode": "handoff"}, headers=admin)
    done = _chat(client, "cho tôi gặp nhân viên tư vấn")[-1]
    assert done["outcome"] == "handoff"

    token = client.post(
        "/api/v1/admin/auth/login", json={"email": "agent@example.test", "password": "agent-password-1"}
    ).json()["access_token"]
    agent = {"Authorization": f"Bearer {token}"}
    handoff_id = client.get("/api/v1/admin/handoffs", headers=agent).json()["items"][0]["id"]
    assert client.patch(f"/api/v1/admin/handoffs/{handoff_id}", json={"status": "in_progress"}, headers=agent).status_code == 200
    denied = client.post(
        "/api/v1/admin/knowledge/documents/text", json={"source": "FAQ", "title": "x", "content": "y"}, headers=agent
    )
    assert denied.status_code == 403
    assert client.get("/api/v1/admin/audit", headers=agent).status_code == 403


def test_models_and_retrieval_settings_apply_live_and_reset_to_defaults(client):
    admin = _admin_headers(client)
    client.post(
        "/api/v1/admin/knowledge/documents/text",
        json={"source": "FAQ", "title": "Giờ làm việc", "content": "Văn phòng mở cửa từ 8 giờ sáng các ngày trong tuần"},
        headers=admin,
    )
    assert _chat(client, "văn phòng mở cửa mấy giờ")[-1]["outcome"] == "answered"

    rejected = client.patch("/api/v1/admin/settings", json={"chat_model": "missing-model-9"}, headers=admin)
    assert rejected.status_code == 400 and "Model not available" in rejected.text
    defaults = client.get("/api/v1/admin/settings/defaults", headers=admin).json()
    assert client.get("/api/v1/admin/settings", headers=admin).json()["chat_model"] == defaults["chat_model"]
    assert client.patch("/api/v1/admin/settings", json={"chat_model": "fake-main-2"}, headers=admin).status_code == 200

    client.patch("/api/v1/admin/settings", json={"similarity_threshold": 1.0}, headers=admin)
    assert _chat(client, "văn phòng mở cửa lúc mấy giờ vậy")[-1]["outcome"] == "denied"
    reset = client.delete("/api/v1/admin/settings/similarity_threshold", headers=admin).json()
    assert reset["similarity_threshold"] == defaults["similarity_threshold"]
    assert _chat(client, "văn phòng mở cửa lúc mấy giờ vậy")[-1]["outcome"] == "answered"
