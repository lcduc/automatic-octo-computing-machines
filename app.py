import streamlit as st
import os
import sys
import time
import subprocess
import requests
import re
import base64
import json
import urllib3
from utils.cleanup import cleanup_data_folders

# Disable SSL warnings for self-signed certificates
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

#: session_state when pre-filling a voice transcript for review.
CHAT_INPUT_KEY = "chat_input"
_PENDING_CHAT_PREFILL_KEY = "_pending_chat_prefill"


def _auth_headers() -> dict:
    """
    Build the ``X-API-Key`` header if the optional backend API key is set.

    Only needed when the deployment has opted into ``API_KEY`` (see
    ``config/settings.py``); returns an empty dict otherwise so this UI keeps
    working unmodified for deployments that don't use it.
    """
    api_key = os.getenv("API_KEY", "")
    return {"X-API-Key": api_key} if api_key else {}

# Ensure Streamlit can read secrets from environment variables when
# `.streamlit/secrets.toml` is not present. This copies common secret
# keys (currently `OPENAI_API_KEY`) into `st.secrets` when possible and
# falls back to `st.session_state` if assignment is not supported.
try:
    _env_secret_keys = ["OPENAI_API_KEY"]
    for _key in _env_secret_keys:
        _val = os.getenv(_key)
        if not _val:
            continue
        try:
            # Try writing into st.secrets (works on recent Streamlit versions)
            st.secrets[_key] = _val
        except Exception:
            # If st.secrets is read-only, provide a fallback in session state
            try:
                if hasattr(st, "session_state"):
                    st.session_state.setdefault(_key, _val)
            except Exception:
                # Best-effort only; do not raise here
                pass
except Exception:
    # Top-level safety: if Streamlit isn't initialised yet, skip silently
    pass

def get_image_base64(image_path):
    """Convert image to base64 for HTML embedding."""
    try:
        with open(image_path, "rb") as img_file:
            return base64.b64encode(img_file.read()).decode()
    except Exception:
        return None

def is_backend_healthy(base_url: str) -> bool:
    try:
        # Disable SSL verification for self-signed certificates
        r = requests.get(f"{base_url}/", timeout=3, verify=False)
        return r.ok
    except Exception:
        return False


def stream_chat(base_url: str, query: str, history: list = None):
    """
    Stream ``{"type": "delta"|"final"|"error", ...}`` events from ``/chat/stream``.

    The backend sends real SSE frames (``data: <json>\\n\\n``); each event is
    self-contained JSON on one line (``json.dumps`` escapes any newlines the
    answer text itself contains), so line-splitting never corrupts a frame.
    """
    url = f"{base_url}/chat/stream"
    headers = {"accept": "text/event-stream", "content-type": "application/json", **_auth_headers()}
    payload = {"query": query}
    if history:
        payload["history"] = history
    try:
        with requests.post(url, json=payload, headers=headers, stream=True, timeout=300, verify=False) as r:
            r.raise_for_status()
            try:
                for line in r.iter_lines(decode_unicode=True):
                    if not line or not line.startswith("data: "):
                        continue
                    try:
                        yield json.loads(line[len("data: "):])
                    except json.JSONDecodeError:
                        continue
            except (requests.exceptions.ChunkedEncodingError, requests.exceptions.ConnectionError, ConnectionResetError) as e:
                # Handle incomplete chunked read errors gracefully
                yield {"type": "error", "message": f"Connection interrupted: {str(e)}"}
                return
            except Exception as e:
                # Handle other streaming errors
                yield {"type": "error", "message": f"Streaming error: {str(e)}"}
                return
    except requests.exceptions.Timeout:
        yield {"type": "error", "message": "Request timeout - the server took too long to respond."}
    except requests.exceptions.ConnectionError as e:
        yield {"type": "error", "message": f"Connection error: Could not connect to the server. {str(e)}"}
    except requests.exceptions.RequestException as e:
        yield {"type": "error", "message": f"Request failed: {str(e)}"}
    except Exception as e:
        yield {"type": "error", "message": f"Unexpected error: {str(e)}"}


def transcribe_audio(base_url: str, audio_bytes: bytes) -> str:
    """Send a recorded voice query to the backend and return the transcribed text."""
    url = f"{base_url}/chat/transcribe"
    files = {"audio": ("recording.wav", audio_bytes, "audio/wav")}
    try:
        r = requests.post(url, files=files, headers=_auth_headers(), timeout=60, verify=False)
        r.raise_for_status()
        return r.json().get("text", "")
    except requests.exceptions.RequestException as e:
        st.toast(f"Transcription failed: {e}")
        return ""


def start_backend_subprocess(host: str, port: int, protocol: str = "http") -> bool:
    """Start uvicorn for the FastAPI app in a background subprocess."""
    try:
        cmd = [
            sys.executable,
            "-m",
            "uvicorn",
            "main:app",
            "--host",
            host,
            "--port",
            str(port),
            "--workers",
            "1",
        ]
        creation = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        subprocess.Popen(cmd, creationflags=creation)
        # Wait briefly for server to come up
        for _ in range(30):
            time.sleep(0.2)
            if is_backend_healthy(f"{protocol}://{host}:{port}"):
                return True
        return is_backend_healthy(f"{protocol}://{host}:{port}")
    except Exception:
        return False


def format_urls(text: str) -> str:
    """Make bare URLs clickable Markdown links, without double-wrapping ones already linked."""

    text = re.sub(r"(?<!\[)(https?://[^\s\)]+)(?!\])", r"[\1](\1)", text)

    # Fix malformed links like "[text]url" -> "[text](url)"
    text = re.sub(r'\[([^\]]+)\](https?://[^\s\)]+)', r'[\1](\2)', text)

    return text


def format_markdown_response(text: str) -> str:
    """
    Sanitize Markdown streamed from the model for safe Streamlit rendering.

    The model is prompted to emit valid Markdown directly (see
    ``SystemPrompts.UNIVERSAL``), so this only normalizes escape sequences and
    linkifies bare URLs - it does not infer or rewrite structure. Safe to call
    on partial (mid-stream) text as well as the final response: every
    transform here is idempotent.
    """
    if not text:
        return text

    text = text.replace('\\n\\n', '\n\n')
    text = text.replace('\\n', '\n')

    # Preserve Markdown hard line breaks (two+ spaces at end of line)
    text = re.sub(r'[ \t]{2,}(?=\n|$)', '\n', text)

    text = format_urls(text)

    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def render_citations(citations: list) -> None:
    """
    Render a distinct "Sources" expander for the given citations.

    Kept as its own element (never concatenated into the answer's Markdown)
    so the frontend can show sources independently of the generated text.
    No-op when there is nothing to cite.
    """
    if not citations:
        return
    with st.expander(f"📚 Nguồn tham khảo ({len(citations)})"):
        for citation in citations:
            source = citation.get("source", "Không rõ nguồn")
            label = f"[{source}]({source})" if citation.get("type") == "url" else source
            chunk_id = citation.get("chunk_id")
            if chunk_id and chunk_id != "unknown":
                label = f"{label} ({chunk_id})"
            score = citation.get("score")
            suffix = f" · {score:.2f}" if isinstance(score, (int, float)) else ""
            st.markdown(f"- {label}{suffix}")


class ChatApp:
    """
    A Streamlit application for chatting with documents and websites.
    Interface-only version: UI elements without backend wiring.
    """

    def __init__(self):
        st.set_page_config(page_title="ChatBot ", initial_sidebar_state="collapsed")
        # st.title("ChatBot ")

        # Initialize session state variables only if they are not already set
        if "uploaded_docs" not in st.session_state:
            st.session_state.uploaded_docs = []
        if "vectordb" not in st.session_state:
            st.session_state.vectordb = None
        if "chat_history" not in st.session_state:
            st.session_state.chat_history = []

    def _reset_session_dirs_and_state(self):
        """Interface-only reset: no filesystem operations."""
        st.toast("Session state reset (no file operations)")

    def reset_all(self):
        """Reset Streamlit session state (interface only, no file operations)."""
        # Clean project data: chunks, vectors, temp, logs
        with st.spinner("Cleaning data folders (chunks, vectors, temp, logs)..."):
            try:
                cleanup_data_folders()
                st.toast("Data folders cleaned")
            except Exception:
                st.toast("Failed to clean data folders")
        st.session_state.uploaded_docs = []
        st.session_state.vectordb = None
        st.session_state.chat_history = []
        # Reset file_uploader widget by changing its key
        st.session_state["uploaded_docs_uploader_key"] = str(time.time())
        st.toast("All session state reset")
        st.rerun()

    def run(self):
        # Thêm logo và title cùng dòng, logo bo góc tròn, size nhỏ
        logo_base64 = get_image_base64("assets/logo_tringhia.jpg")
        if logo_base64:
            st.markdown(
                f"""
                <div style="display: flex; align-items: center; justify-content: flex-start; gap: 10px; margin-top: 10px; margin-left: 10px;">
                    <img src="data:image/jpeg;base64,{logo_base64}" style="width:50px; height:50px; border-radius:50%; object-fit:cover;">
                    <h2 style="margin: 0;">TNT ChatBot</h2>
                </div>
                """,
                unsafe_allow_html=True,
            )
        else:
            st.header("TNT ChatBot")
        # Initialize API base URL and optionally auto-start backend regardless of sidebar visibility
        # Check if SSL certificates exist to determine protocol
        ssl_cert_file = "./SSL/fullchain.pem"
        ssl_key_file = "./SSL/privkey_converted.pem"
        protocol = "https" if os.path.exists(ssl_cert_file) and os.path.exists(ssl_key_file) else "http"
        DEFAULT_API_BASE_URL = os.getenv("API_BASE_URL", f"{protocol}://127.0.0.1:8500")
        api_base_url = DEFAULT_API_BASE_URL
        if os.getenv("AUTO_START_API", "true").lower() == "true" and not is_backend_healthy(api_base_url):
            try:
                # Parse URL to extract host and port
                if api_base_url.startswith("https://"):
                    host_port = api_base_url.replace("https://", "").split(":")
                else:
                    host_port = api_base_url.replace("http://", "").split(":")
                host = host_port[0]
                port = int(host_port[1]) if len(host_port) > 1 else 8500
                with st.spinner("Starting backend API..."):
                    started = start_backend_subprocess(host, port, protocol)
                    if started:
                        st.toast("Backend started")
                    else:
                        st.toast("Could not auto-start backend. Start it manually.")
            except Exception:
                st.toast("Auto-start attempt failed. Start the API manually.")

        # Sidebar hidden by default
        show_sidebar = False
        # Sidebar controlled via env only (no visible toggles)
        # show_sidebar = os.getenv("SHOW_SIDEBAR", "true").lower() == "true"
        if show_sidebar:
            with st.sidebar:
                # Startup handled above; sidebar UI only

                st.subheader("Documents")
                uploader_key = st.session_state.get("uploaded_docs_uploader_key", "uploaded_docs_uploader")
                uploaded_docs = st.file_uploader(
                    "Upload (.pdf, .txt, .docx, .xlsx)",
                    type=["pdf", "txt", "docx", "xlsx"],
                    accept_multiple_files=True,
                    key=uploader_key
                )

                if uploaded_docs:
                    pass

                if st.button(" Process Inputs", use_container_width=True):
                    if not is_backend_healthy(api_base_url):
                        st.toast("Backend not reachable. Start FastAPI and try again.")
                    else:
                        # Upload files
                        if uploaded_docs:
                            files_payload = [("files", (f.name, f.getvalue(), f.type or "application/octet-stream")) for f in uploaded_docs]
                            try:
                                resp = requests.post(f"{api_base_url}/files/upload", files=files_payload, headers=_auth_headers(), timeout=600, verify=False)
                                if resp.ok:
                                    st.session_state.uploaded_docs.extend([f.name for f in uploaded_docs])
                                    st.toast("Files uploaded")
                                else:
                                    st.toast(f"Upload failed: {resp.status_code}")
                            except Exception as e:
                                st.toast(f"Upload error: {e}")

                if os.getenv("ENABLE_MAINTENANCE", "true").lower() == "true":
                    st.markdown("---")
                    st.subheader("Maintenance")
                    col_m1, col_m2 = st.columns(2)
                    with col_m1:
                        if st.button("Reset", use_container_width=True):
                            self.reset_all()
                    with col_m2:
                        if st.button("Refresh Vector", use_container_width=True):
                            with st.spinner("Refreshing knowledge base..."):
                                st.session_state.vectordb = "placeholder"
                                st.toast("Knowledge base refreshed")
        else:
            # Sidebar hidden by configuration
            pass

        # -------------------------------
        # Vectorstore and Chat (interface only)
        # -------------------------------
        has_any_inputs = bool(st.session_state.uploaded_docs)

        if has_any_inputs and st.session_state.vectordb is None:
            with st.spinner("Updating knowledge base..."):
                st.session_state.vectordb = "placeholder"
                st.toast("Knowledge base is ready")

        # Render chat history
        for msg in st.session_state.chat_history:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])
                render_citations(msg.get("citations", []))

        if st.session_state.get(_PENDING_CHAT_PREFILL_KEY):
            st.session_state[CHAT_INPUT_KEY] = st.session_state.pop(_PENDING_CHAT_PREFILL_KEY)

        prompt = st.chat_input(
            "Type your question, or record a voice message…",
            accept_audio=True,
            key=CHAT_INPUT_KEY,
        )

        user_input = None
        if prompt and prompt.audio:
            with st.spinner("Transcribing…"):
                transcribed = transcribe_audio(api_base_url, prompt.audio.getvalue())
            if transcribed:
                st.session_state[_PENDING_CHAT_PREFILL_KEY] = transcribed
                st.rerun()
        elif prompt and prompt.text:
            user_input = prompt.text

        if user_input:
            # Snapshot history *before* appending this turn's question — it is
            # sent to the backend separately as `query`, so including it here
            # too would make the model see the same question twice.
            # Keep this in sync with the backend's MAX_HISTORY_TURNS (one turn
            # = one user message + one assistant reply).
            max_history_messages = int(os.getenv("MAX_HISTORY_TURNS", "10")) * 2
            recent_history = st.session_state.chat_history[-max_history_messages:] if st.session_state.chat_history else []

            st.session_state.chat_history.append({"role": "user", "content": user_input})
            with st.chat_message("user"):
                st.markdown(user_input)

            with st.chat_message("assistant"):
                placeholder = st.empty()
                accumulated = ""
                citations = []
                error_message = None
                last_flush = time.time()
                try:
                    for event in stream_chat(api_base_url, user_input, recent_history):
                        event_type = event.get("type")
                        if event_type == "delta":
                            delta = event.get("answer", {}).get("text", "")
                            accumulated += delta
                            now = time.time()
                            # Flush on punctuation/newline or every ~50ms to reduce flicker & CPU
                            if delta.endswith((" ", "\n", ".", ",", ":", ";", "!", "?")) or (now - last_flush) > 0.05:
                                placeholder.markdown(format_markdown_response(accumulated))
                                last_flush = now
                        elif event_type == "final":
                            citations = event.get("citations") or []
                        elif event_type == "error":
                            error_message = event.get("message", "Unknown error")
                            break

                    if error_message:
                        final_text = f"Chat failed: {error_message}"
                        placeholder.markdown(final_text)
                        st.session_state.chat_history.append({"role": "assistant", "content": final_text})
                    else:
                        # After full completion, apply full formatter and update the UI immediately
                        final_text = format_markdown_response(accumulated)
                        placeholder.markdown(final_text)
                        render_citations(citations)
                        st.session_state.chat_history.append(
                            {"role": "assistant", "content": final_text, "citations": citations}
                        )
                except Exception as e:
                    error_msg = f"Chat failed: {e}"
                    placeholder.markdown(error_msg)
                    st.session_state.chat_history.append({"role": "assistant", "content": error_msg})


if __name__ == "__main__":
    ChatApp().run()
