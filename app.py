import streamlit as st
import os
import sys
import time
import subprocess
import requests
import re
import base64
import urllib3
from utils.file_operations import cleanup_data_folders

# Disable SSL warnings for self-signed certificates
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


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
    url = f"{base_url}/chat/"
    headers = {"accept": "text/event-stream", "content-type": "application/json", **_auth_headers()}
    payload = {"query": query}
    if history:
        payload["history"] = history
    try:
        with requests.post(url, json=payload, headers=headers, stream=True, timeout=300, verify=False) as r:
            r.raise_for_status()
            try:
                for line in r.iter_lines(decode_unicode=True, chunk_size=1):
                    if not line:
                        continue
                    # Handle Server-Sent Events style lines like 'data: token'
                    if line.startswith("data:"):
                        token = line[5:].lstrip()
                    else:
                        token = line
                    # Skip keep-alive pings
                    if token in ("[DONE]", ":keep-alive"):
                        continue
                    yield token
            except (requests.exceptions.ChunkedEncodingError, requests.exceptions.ConnectionError, ConnectionResetError) as e:
                # Handle incomplete chunked read errors gracefully
                error_msg = f"[ERROR] Connection interrupted: {str(e)}"
                yield error_msg
                return
            except Exception as e:
                # Handle other streaming errors
                error_msg = f"[ERROR] Streaming error: {str(e)}"
                yield error_msg
                return
    except requests.exceptions.Timeout:
        yield "[ERROR] Request timeout - the server took too long to respond."
    except requests.exceptions.ConnectionError as e:
        yield f"[ERROR] Connection error: Could not connect to the server. {str(e)}"
    except requests.exceptions.RequestException as e:
        yield f"[ERROR] Request failed: {str(e)}"
    except Exception as e:
        yield f"[ERROR] Unexpected error: {str(e)}"


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


def format_markdown_response(text: str) -> str:
    """Universal text formatter that intelligently structures any text response.
    
    This is a general solution that:
    - Works with any text format (raw markdown, plain text, mixed, HTML)
    - Automatically detects and formats common patterns
    - Improves readability without changing content
    - Handles edge cases and dense text
    - Detects HTML responses and returns them as-is for Streamlit rendering
    """
    if not text:
        return text
    
    # Check if the response is HTML (starts with < and contains HTML tags)
    if text.strip().startswith('<') and ('<' in text and '>' in text):
        # This is an HTML response, return as-is for Streamlit to render
        return text.strip()
    
    # Step 1: Basic cleaning and escape sequence handling
    text = text.strip()
    text = text.replace('\\n\\n', '\n\n')
    text = text.replace('\\n', '\n')
    
    # Step 2: Preserve Markdown hard line breaks (two+ spaces at end of line)
    text = re.sub(r'[ \t]{2,}(?=\n|$)', '\n', text)

    # Step 3: Universal pattern detection and formatting
    text = detect_and_format_patterns(text)
    
    # Step 4: URL formatting
    text = format_urls(text)
    
    # Step 5: Structure improvement
    text = improve_structure(text)
    
    # Step 6: Final cleanup
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def format_markdown_response_streaming(text: str) -> str:
    """Lightweight, streaming-safe formatter for partial LLM outputs.

    - Only applies idempotent, low-risk transforms suitable for partial tokens
    - Converts escaped newlines to actual newlines
    - Makes bare URLs clickable without restructuring surrounding text
    - Collapses excessive newlines
    - Does NOT try to insert headers/lists or bold markers to avoid flicker
    - Detects HTML responses and returns them as-is for Streamlit rendering
    """
    if not text:
        return text

    # Check if the response is HTML (starts with < and contains HTML tags)
    if text.strip().startswith('<') and ('<' in text and '>' in text):
        # This is an HTML response, return as-is for Streamlit to render
        return text.strip()

    # Convert escape sequences emitted by models
    text = text.replace('\\n\\n', '\n\n')
    text = text.replace('\\n', '\n')

    # Preserve Markdown hard line breaks (two+ spaces at end of line)
    text = re.sub(r'[ \t]{2,}(?=\n|$)', '\n', text)

    # Merge split digits during streaming: "1 0" -> "10" (idempotent)
    text = re.sub(r'(?<=\d)\s+(?=\d)', '', text)

    # Ensure a newline after a colon if it immediately starts a numbered list (e.g., ":1. …")
    # Keeps it idempotent by normalizing to exactly one newline
    text = re.sub(r':\s*(?=(\d+)\.\s)', '::NEWLINE_PLACEHOLDER::', text)
    text = text.replace('::NEWLINE_PLACEHOLDER::', ':\n')

    # Ensure a newline after a colon if followed by a URL or markdown link
    text = re.sub(r':\s*(?=(https?://|\[))', ':\n', text)

    # Ensure a newline after a colon if glued to a capitalized heading token (e.g., ":Tempate …")
    text = re.sub(r':(?=[A-ZÀ-Ỹ])', ':\n', text)

    # Make bare URLs clickable (idempotent)
    text = re.sub(r"(?<!\[)(https?://[^\s\)]+)(?!\])", r"[\1](\1)", text)

    # Clean up excessive newlines during streaming
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def detect_and_format_patterns(text: str) -> str:
    """Universal text structure formatter that intelligently detects and formats patterns."""
    
    # Fix cases where digits get split: "1 0" -> "10"
    text = re.sub(r'(?<=\d)\s+(?=\d)', '', text)

    # Step 1: Detect and format step patterns
    text = re.sub(r'(Bước \d+:)', r'**\1**', text)  # Vietnamese steps
    text = re.sub(r'(Step \d+:)', r'**\1**', text)  # English steps
    
    # Step 2: Detect and format section headers (lines ending with colon)
    text = re.sub(r'^([A-Za-zÀ-ỹ\s]+:)$', r'**\1**', text, flags=re.MULTILINE)
    
    # Step 3: Universal list detection and formatting
    # This handles any list pattern: bullet, numbered, dash, asterisk
    list_patterns = [
        (r'(?<!\n)(•\s)', r'\n\1'),      # Bullet points
        (r'(?<!\n)(–\s)', r'\n\1'),      # En dash list items
        # Numbered lists (ensure not preceded by a digit to avoid splitting "...4801" from "10.")
        (r'(?<!\n)(?<!\d)(\d+\.\s)', r'\n\1'),
        (r'(?<!\n)(-\s)', r'\n\1'),      # Dash lists
        (r'(?<!\n)(\*\s)', r'\n\1'),     # Asterisk lists
    ]
    
    for pattern, replacement in list_patterns:
        text = re.sub(pattern, replacement, text)
    
    # Step 4: Universal paragraph breaking
    # Break on sentence boundaries followed by capital letters or special characters
    # Require a space after the period to avoid breaking decimals/DOIs like "10.25073"
    paragraph_breaks = [
        (r'\.(\s+)(?=[A-ZÀ-Ỹ])', '.\n\n'),  # Period + space(s) + capital
        (r'\.(\s+)(?=–)', '.\n\n'),          # Period + space(s) + dash
        (r'\.(\s+)(?=•)', '.\n\n'),          # Period + space(s) + bullet
        # Period + space(s) + numbered list, but not when the number is preceded by a digit (e.g., "4801 10.")
        (r'\.(\s+)(?=(?<!\d)\d+\.)', '.\n\n'),
    ]

    for pattern, replacement in paragraph_breaks:
        text = re.sub(pattern, replacement, text)
    
    # Step 5: Handle dense text with no structure
    # If text is very long without breaks, add strategic breaks
    if len(text) > 500 and '\n' not in text:
        # Break on common sentence endings followed by common list starters
        text = re.sub(r'(\.)(\s*)([A-ZÀ-Ỹ])', r'\1\n\n\3', text)
    
    return text


def format_urls(text: str) -> str:
    """Format URLs to be clickable markdown links."""
    
    # Make URLs clickable (basic pattern) - only if not already formatted
    text = re.sub(r"(?<!\[)(https?://[^\s\)]+)(?!\])", r"[\1](\1)", text)
    
    # Fix double URL formatting issue
    text = re.sub(r"\[([^\]]+)\]\(\[([^\]]+)\]\([^)]+\)\)", r"[\1](\2)", text)
    
    # Fix malformed links like "[text]url" -> "[text](url)"
    text = re.sub(r'\[([^\]]+)\](https?://[^\s\)]+)', r'[\1](\2)', text)
    
    return text


def improve_structure(text: str) -> str:
    """Improve overall text structure and spacing."""
    
    # Ensure proper spacing around **Bước X:** patterns
    text = re.sub(r'(\*\*Bước \d+:\*\*)', r'\n\n\1\n', text)
    
    # Ensure proper spacing around other bold section headers
    text = re.sub(r'(\*\*[^:]+:\*\*)', r'\n\n\1\n', text)
    
    # Ensure proper spacing around ## headers
    text = re.sub(r'(## [^\n]+)', r'\n\n\1\n', text)
    
    # Ensure list items have proper spacing
    text = re.sub(r'(?<!\n)(- [^\n]+)', r'\n\1', text)
    # Numbered list spacing: avoid triggering when preceded by a digit (e.g., DOI tails)
    text = re.sub(r'(?<!\n)(?<!\d)(\d+\. [^\n]+)', r'\n\1', text)
    
    return text


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
        if "uploaded_urls" not in st.session_state:
            st.session_state.uploaded_urls = []
        if "vectordb" not in st.session_state:
            st.session_state.vectordb = None
        if "chat_history" not in st.session_state:
            st.session_state.chat_history = []
        if "url_inputs" not in st.session_state:
            st.session_state.url_inputs = [""]

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
        st.session_state.uploaded_urls = []
        st.session_state.vectordb = None
        st.session_state.chat_history = []
        st.session_state.url_inputs = [""]
        # Reset file_uploader widget by changing its key
        st.session_state["uploaded_docs_uploader_key"] = str(time.time())
        st.toast("All session state reset")
        st.rerun()

    def _handle_url_inputs(self):
        """Render and manage the dynamic URL input fields in the sidebar."""
        if st.button("Add another URL"):
            st.session_state.url_inputs.append("")
            st.rerun()

        new_url_inputs = []
        should_rerun = False

        for i, url in enumerate(st.session_state.url_inputs):
            col1, col2 = st.columns([10, 1])
            with col1:
                new_url = st.text_input(
                    f"URL #{i+1}",
                    value=url,
                    key=f"url_{i}"
                )
                new_url_inputs.append(new_url)
            with col2:
                if st.button("", key=f"remove_url_{i}"):
                    # remove current index if exists
                    if i < len(new_url_inputs):
                        new_url_inputs.pop(i)
                    should_rerun = True

        st.session_state.url_inputs = new_url_inputs

        if should_rerun:
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

                st.subheader("Documents & URLs")
                uploader_key = st.session_state.get("uploaded_docs_uploader_key", "uploaded_docs_uploader")
                uploaded_docs = st.file_uploader(
                    "Upload (.pdf, .txt, .doc, .docx, .xls, .xlsx)",
                    type=["pdf", "txt", "doc", "docx", "xls", "xlsx"],
                    accept_multiple_files=True,
                    key=uploader_key
                )

                if uploaded_docs:
                    pass

                enable_urls = os.getenv("ENABLE_URL_INPUTS", "false").lower() == "true"
                if enable_urls:
                    crawl_links = st.checkbox("Crawl all links on the same domain", value=False, key="crawl_same_domain")
                    page_limit = 50
                    if crawl_links:
                        page_limit = st.number_input(
                            "Maximum pages to crawl", min_value=1, max_value=1000, value=50, key="page_limit"
                        )

                    self._handle_url_inputs()

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
                        # Process URLs if enabled
                        if enable_urls:
                            urls = [u.strip() for u in st.session_state.url_inputs if u.strip()]
                            if urls:
                                try:
                                    resp2 = requests.post(f"{api_base_url}/files/url", json={"urls": urls}, headers=_auth_headers(), timeout=600, verify=False)
                                    if resp2.ok:
                                        st.session_state.uploaded_urls.extend(urls)
                                        st.toast("URLs processed")
                                    else:
                                        st.toast(f"URL processing failed: {resp2.status_code}")
                                except Exception as e:
                                    st.toast(f"URL error: {e}")

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
        has_any_inputs = bool(st.session_state.uploaded_docs or st.session_state.uploaded_urls)

        if has_any_inputs and st.session_state.vectordb is None:
            with st.spinner("Updating knowledge base..."):
                st.session_state.vectordb = "placeholder"
                st.toast("Knowledge base is ready")

        # Render chat history
        for msg in st.session_state.chat_history:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"], unsafe_allow_html=True)

        # Chat input (streams from backend /chat)
        user_input = st.chat_input("Type your question…")
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
                last_flush = time.time()
                try:
                    for token in stream_chat(api_base_url, user_input, recent_history):
                        accumulated += token
                        now = time.time()
                        # Flush on punctuation/newline or every ~50ms to reduce flicker & CPU
                        if token.endswith((" ", "\n", ".", ",", ":", ";", "!", "?")) or (now - last_flush) > 0.05:
                            # Use streaming-safe formatter to avoid flicker during partial updates
                            placeholder.markdown(format_markdown_response_streaming(accumulated), unsafe_allow_html=True)
                            last_flush = now
                    # After full completion, apply full formatter and update the UI immediately
                    final_text = format_markdown_response(accumulated)
                    placeholder.markdown(final_text, unsafe_allow_html=True)
                    st.session_state.chat_history.append({"role": "assistant", "content": final_text})
                except Exception as e:
                    error_msg = f"Chat failed: {e}"
                    placeholder.markdown(error_msg)
                    st.session_state.chat_history.append({"role": "assistant", "content": error_msg})


if __name__ == "__main__":
    ChatApp().run()
