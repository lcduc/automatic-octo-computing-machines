import streamlit as st
import os
import sys
import time
import subprocess
import requests
import re
from utils.cleanup import cleanup_data_folders


def is_backend_healthy(base_url: str) -> bool:
    try:
        r = requests.get(f"{base_url}/", timeout=3)
        return r.ok
    except Exception:
        return False


def stream_chat(base_url: str, query: str, history: list = None):
    url = f"{base_url}/chat/"
    headers = {"accept": "text/event-stream", "content-type": "application/json"}
    payload = {"query": query}
    if history:
        payload["history"] = history
    with requests.post(url, json=payload, headers=headers, stream=True, timeout=300) as r:
        r.raise_for_status()
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


def start_backend_subprocess(host: str, port: int) -> bool:
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
            if is_backend_healthy(f"http://{host}:{port}"):
                return True
        return is_backend_healthy(f"http://{host}:{port}")
    except Exception:
        return False


def format_markdown_response(text: str) -> str:
    """Preprocess raw markdown from LLM for optimal Streamlit display.
    - Convert raw markdown escape sequences to actual newlines
    - Ensure proper spacing and structure for Streamlit rendering
    - Handle **Bước 1:** patterns with proper spacing
    - Make URLs clickable if not already formatted
    - Preserve markdown structure while improving readability
    """
    if not text:
        return text
    
    # Convert raw markdown escape sequences to actual newlines
    text = text.replace('\\n\\n', '\n\n')  # Double newlines for paragraph breaks
    text = text.replace('\\n', '\n')       # Single newlines
    
    # Ensure proper spacing around **Bước X:** patterns for better readability
    text = re.sub(r'(\*\*Bước \d+:\*\*)', r'\n\n\1\n', text)
    
    # Ensure proper spacing around other bold section headers
    text = re.sub(r'(\*\*[^:]+:\*\*)', r'\n\n\1\n', text)
    
    # Ensure proper spacing around ## headers
    text = re.sub(r'(## [^\n]+)', r'\n\n\1\n', text)
    
    # Ensure list items have proper spacing
    text = re.sub(r'(?<!\n)(- [^\n]+)', r'\n\1', text)
    text = re.sub(r'(?<!\n)(\d+\. [^\n]+)', r'\n\1', text)
    
    # Make URLs clickable (basic pattern) - only if not already formatted
    text = re.sub(r"(?<!\[)(https?://[^\s\)]+)(?!\])", r"[\1](\1)", text)
    
    # Fix double URL formatting issue
    text = re.sub(r"\[([^\]]+)\]\(\[([^\]]+)\]\([^)]+\)\)", r"[\1](\2)", text)
    
    # Clean up multiple consecutive newlines (max 2)
    text = re.sub(r"\n{3,}", "\n\n", text)
    
    # Trim extraneous surrounding whitespace
    return text.strip()


class ChatApp:
    """
    A Streamlit application for chatting with documents and websites.
    Interface-only version: UI elements without backend wiring.
    """

    def __init__(self):
        st.set_page_config(page_title="ChatBot 📚", initial_sidebar_state="collapsed")
        st.title("ChatBot 📚")

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
        st.toast("Session state reset (no file operations)", icon="✅")

    def reset_all(self):
        """Reset Streamlit session state (interface only, no file operations)."""
        # Clean project data: chunks, vectors, temp, logs
        with st.spinner("Cleaning data folders (chunks, vectors, temp, logs)..."):
            try:
                cleanup_data_folders()
                st.toast("Data folders cleaned", icon="✅")
            except Exception:
                st.toast("Failed to clean data folders", icon="❌")
        st.session_state.uploaded_docs = []
        st.session_state.uploaded_urls = []
        st.session_state.vectordb = None
        st.session_state.chat_history = []
        st.session_state.url_inputs = [""]
        # Reset file_uploader widget by changing its key
        st.session_state["uploaded_docs_uploader_key"] = str(time.time())
        st.toast("All session state reset", icon="✅")
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
                if st.button("❌", key=f"remove_url_{i}"):
                    # remove current index if exists
                    if i < len(new_url_inputs):
                        new_url_inputs.pop(i)
                    should_rerun = True

        st.session_state.url_inputs = new_url_inputs

        if should_rerun:
            st.rerun()

    def run(self):
        # Initialize API base URL and optionally auto-start backend regardless of sidebar visibility
        DEFAULT_API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8500")
        api_base_url = DEFAULT_API_BASE_URL
        if os.getenv("AUTO_START_API", "true").lower() == "true" and not is_backend_healthy(api_base_url):
            try:
                host_port = api_base_url.replace("http://", "").split(":")
                host = host_port[0]
                port = int(host_port[1]) if len(host_port) > 1 else 8500
                with st.spinner("Starting backend API..."):
                    started = start_backend_subprocess(host, port)
                    if started:
                        st.toast("Backend started", icon="✅")
                    else:
                        st.toast("Could not auto-start backend. Start it manually.", icon="⚠️")
            except Exception:
                st.toast("Auto-start attempt failed. Start the API manually.", icon="⚠️")

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

                if st.button("🚀 Process Inputs", use_container_width=True):
                    if not is_backend_healthy(api_base_url):
                        st.toast("Backend not reachable. Start FastAPI and try again.", icon="⚠️")
                    else:
                        # Upload files
                        if uploaded_docs:
                            files_payload = [("files", (f.name, f.getvalue(), f.type or "application/octet-stream")) for f in uploaded_docs]
                            try:
                                resp = requests.post(f"{api_base_url}/files/upload", files=files_payload, timeout=600)
                                if resp.ok:
                                    st.session_state.uploaded_docs.extend([f.name for f in uploaded_docs])
                                    st.toast("Files uploaded", icon="✅")
                                else:
                                    st.toast(f"Upload failed: {resp.status_code}", icon="❌")
                            except Exception as e:
                                st.toast(f"Upload error: {e}", icon="❌")
                        # Process URLs if enabled
                        if enable_urls:
                            urls = [u.strip() for u in st.session_state.url_inputs if u.strip()]
                            if urls:
                                try:
                                    resp2 = requests.post(f"{api_base_url}/files/url", json={"urls": urls}, timeout=600)
                                    if resp2.ok:
                                        st.session_state.uploaded_urls.extend(urls)
                                        st.toast("URLs processed", icon="✅")
                                    else:
                                        st.toast(f"URL processing failed: {resp2.status_code}", icon="❌")
                                except Exception as e:
                                    st.toast(f"URL error: {e}", icon="❌")

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
                                st.toast("Knowledge base refreshed", icon="✅")
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
                st.toast("Knowledge base is ready", icon="✅")

        # Render chat history
        for msg in st.session_state.chat_history:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        # Chat input (streams from backend /chat)
        user_input = st.chat_input("Type your question…")
        if user_input:
            st.session_state.chat_history.append({"role": "user", "content": user_input})
            with st.chat_message("user"):
                st.markdown(user_input)

            with st.chat_message("assistant"):
                placeholder = st.empty()
                accumulated = ""
                last_flush = time.time()
                try:
                    # Use api_base_url from sidebar and pass conversation history
                    for token in stream_chat(api_base_url, user_input, st.session_state.chat_history):
                        accumulated += token
                        now = time.time()
                        # Flush on punctuation/newline or every ~50ms to reduce flicker & CPU
                        if token.endswith((" ", "\n", ".", ",", ":", ";", "!", "?")) or (now - last_flush) > 0.05:
                            placeholder.markdown(format_markdown_response(accumulated), unsafe_allow_html=False)
                            last_flush = now
                    st.session_state.chat_history.append({"role": "assistant", "content": format_markdown_response(accumulated)})
                except Exception as e:
                    error_msg = f"Chat failed: {e}"
                    placeholder.markdown(error_msg)
                    st.session_state.chat_history.append({"role": "assistant", "content": error_msg})


if __name__ == "__main__":
    ChatApp().run()
