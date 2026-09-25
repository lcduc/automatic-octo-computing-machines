"""
Internal Streamlit demo of the chat API (not a client product).

Talks to the backend exactly like a client frontend's server would: the
``/api/v1`` chat routes with a chat-scope ``CHATBOT_API_KEY`` and a per-session
visitor id. Knowledge management lives in the admin web (frontends/).

Run:  streamlit run app.py
"""

import json
import os
import re
import uuid

import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

#: session_state keys.
CHAT_INPUT_KEY = "chat_input"
_PENDING_CHAT_PREFILL_KEY = "_pending_chat_prefill"
#: Seconds allowed for one streamed answer.
STREAM_TIMEOUT_SECONDS = 300
TRANSCRIBE_TIMEOUT_SECONDS = 60
HEALTH_TIMEOUT_SECONDS = 3


def api_base_url() -> str:
    """Backend root URL."""
    return os.getenv("API_BASE_URL", "http://127.0.0.1:8500").rstrip("/")


def auth_headers() -> dict:
    """API key and this browser session's visitor id."""
    if "visitor_id" not in st.session_state:
        st.session_state.visitor_id = f"streamlit-{uuid.uuid4()}"
    return {"X-API-Key": os.getenv("CHATBOT_API_KEY", ""), "X-End-User-Id": st.session_state.visitor_id}


def is_backend_ready() -> bool:
    """True when the backend reports ready."""
    try:
        return requests.get(f"{api_base_url()}/health/ready", timeout=HEALTH_TIMEOUT_SECONDS).ok
    except requests.RequestException:
        return False


def stream_chat(message: str, conversation_id: str | None):
    """
    Yield ``(event, payload)`` pairs from ``/api/v1/chat/stream``.

    Events: ``meta`` (ids), ``delta`` (text), ``done`` (outcome, citations) or ``error``.
    """
    body = {"message": message}
    if conversation_id:
        body["conversation_id"] = conversation_id
    try:
        with requests.post(
            f"{api_base_url()}/api/v1/chat/stream",
            json=body,
            headers={"accept": "text/event-stream", **auth_headers()},
            stream=True,
            timeout=STREAM_TIMEOUT_SECONDS,
        ) as response:
            if not response.ok:
                detail = response.json().get("detail", response.text) if response.headers.get("content-type", "").startswith("application/json") else response.text
                yield "error", {"message": f"{response.status_code}: {detail}"}
                return
            event = "message"
            for line in response.iter_lines(decode_unicode=True):
                if line.startswith("event:"):
                    event = line[len("event:"):].strip()
                elif line.startswith("data:"):
                    yield event, json.loads(line[len("data:"):].strip())
    except requests.RequestException as exc:
        yield "error", {"message": f"Không kết nối được máy chủ: {exc}"}


def transcribe_audio(audio_bytes: bytes) -> str:
    """Send a recorded voice query to the backend and return the transcribed text."""
    try:
        response = requests.post(
            f"{api_base_url()}/api/v1/chat/transcribe",
            files={"audio": ("recording.wav", audio_bytes, "audio/wav")},
            headers=auth_headers(),
            timeout=TRANSCRIBE_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json().get("text", "")
    except requests.RequestException as exc:
        st.toast(f"Transcription failed: {exc}")
        return ""


def format_markdown_response(text: str) -> str:
    """Linkify bare URLs and collapse blank lines (idempotent, safe mid-stream)."""
    if not text:
        return text
    text = re.sub(r"(?<![\[(])(https?://[^\s)]+)", r"[\1](\1)", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def render_citations(citations: list) -> None:
    """Show the documents an answer is based on."""
    if not citations:
        return
    with st.expander(f"📚 Nguồn tham khảo ({len(citations)})"):
        for citation in citations:
            title = citation.get("title", "Không rõ")
            label = f"[{title}]({citation['url']})" if citation.get("url") else title
            st.markdown(f"- {label} · {citation.get('source', '')} · {citation.get('score', 0):.2f}")


class ChatApp:
    """Streamlit chat page over the public chat API."""

    def __init__(self):
        st.set_page_config(page_title="ChatBot demo", initial_sidebar_state="collapsed")
        st.session_state.setdefault("chat_history", [])
        st.session_state.setdefault("conversation_id", None)

    def _answer(self, user_input: str) -> None:
        """Stream one answer into the page and the session history."""
        with st.chat_message("assistant"):
            placeholder = st.empty()
            accumulated, citations = "", []
            for event, payload in stream_chat(user_input, st.session_state.conversation_id):
                if event == "meta":
                    st.session_state.conversation_id = payload["conversation_id"]
                elif event == "delta":
                    accumulated += payload.get("text", "")
                    placeholder.markdown(format_markdown_response(accumulated))
                elif event == "done":
                    accumulated = payload.get("text") or accumulated
                    citations = payload.get("citations") or []
                elif event == "error":
                    accumulated = f"Chat failed: {payload.get('message', 'unknown error')}"
            final_text = format_markdown_response(accumulated)
            placeholder.markdown(final_text)
            render_citations(citations)
        st.session_state.chat_history.append({"role": "assistant", "content": final_text, "citations": citations})

    def run(self) -> None:
        """Render the page."""
        st.header("ChatBot demo")
        if not os.getenv("CHATBOT_API_KEY"):
            st.warning("Set CHATBOT_API_KEY (create one in the admin web) to chat.")
        if not is_backend_ready():
            st.error(f"Backend not ready at {api_base_url()}. Start it with `python main.py`.")

        if st.button("Cuộc trò chuyện mới"):
            st.session_state.chat_history = []
            st.session_state.conversation_id = None

        for message in st.session_state.chat_history:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])
                render_citations(message.get("citations", []))

        if st.session_state.get(_PENDING_CHAT_PREFILL_KEY):
            st.session_state[CHAT_INPUT_KEY] = st.session_state.pop(_PENDING_CHAT_PREFILL_KEY)

        prompt = st.chat_input("Nhập câu hỏi, hoặc ghi âm…", accept_audio=True, key=CHAT_INPUT_KEY)
        if prompt and prompt.audio:
            with st.spinner("Đang chuyển giọng nói…"):
                transcribed = transcribe_audio(prompt.audio.getvalue())
            if transcribed:
                st.session_state[_PENDING_CHAT_PREFILL_KEY] = transcribed
                st.rerun()
        elif prompt and prompt.text:
            st.session_state.chat_history.append({"role": "user", "content": prompt.text})
            with st.chat_message("user"):
                st.markdown(prompt.text)
            self._answer(prompt.text)


if __name__ == "__main__":
    ChatApp().run()
