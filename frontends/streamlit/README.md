# `frontends/streamlit/`

<!-- Keep this README true. Anyone (person or agent) who adds, removes or renames a file here,
     or hits a problem worth remembering, updates the matching section in the same PR. -->

## Purpose
Internal Streamlit demo of the public chat API — not a client product. It calls the backend over HTTP
exactly like a client frontend's server would and never imports backend code. Knowledge management, settings
and accounts belong in the admin web (`frontends/admin`); the visitor-facing chat is `frontends/widget`.

## Files

| File | Public names | What it does |
|---|---|---|
| `app.py` | `ChatApp`, `api_base_url`, `auth_headers`, `is_backend_ready`, `stream_chat`, `transcribe_audio`, `format_markdown_response`, `render_citations` | The whole app: one chat page with streamed answers, citations, a "new conversation" button and voice input (recorded in `st.chat_input`, transcribed, then pre-filled for review). |
| `requirements.txt` | — | Its own pins: `streamlit`, `requests`, `python-dotenv`. |
| `.streamlit/config.toml` | — | Headless server on `0.0.0.0:8501`. |

**How it calls the backend** (`API_BASE_URL`, default `http://127.0.0.1:8500`):
- `GET /health/ready` — shows an error banner when the backend is not ready.
- `POST /api/v1/chat/stream` — SSE events `meta` (conversation id), `delta` (text), `done` (final text,
  citations), `error`.
- `POST /api/v1/chat/transcribe` — voice recording → text.
- Headers: `X-API-Key: $CHATBOT_API_KEY` (a chat-scope key) and `X-End-User-Id: streamlit-<uuid>` per browser
  session. `.env` is loaded with python-dotenv, which walks up from this folder, so the repo-root `.env` is found.

As CLAUDE.md notes, the planned `pages/`, `components/`, `api_client.py` and `Dockerfile` are not split out
yet; everything is in `app.py` and the demo is not part of `docker-compose.yml`.

## Dependencies
- May import: `streamlit`, `requests`, `python-dotenv` only. Never backend code.
- Talks to: the backend's `/health/ready` and `/api/v1/chat/*` routes.
- Used by: nobody; run by hand for demos.

## Run / test
From `frontends/streamlit`, with its own venv:

```bash
python -m venv venv
venv\Scripts\Activate.ps1            # or: source venv/bin/activate
pip install -r requirements.txt
# backend running (cd backend && python -m app.main); create a key: python -m scripts.manage create-api-key --name "streamlit demo"
# put CHATBOT_API_KEY=<key> (and API_BASE_URL if not local) in the root .env or the environment
streamlit run app.py                 # http://localhost:8501
```

No tests. Lint with `ruff check .` from the repo root.

## Known problems and history
- 2026-08-04: streaming client fixed and answers switched from HTML to Markdown (1c1ff63); voice input added
  (aac0be3).
- 2026-09-25: rewritten as a thin client of the `/api/v1` chat routes with a chat-scope API key; knowledge
  management moved to the admin web (2b086ca, app.py 435 → 180 lines).
- Moved from the repo root (`app.py`, `.streamlit/`) to `frontends/streamlit/`, with its dependencies split out
  of the backend `requirements.txt` into its own, in `lcduc/automatic-octo-computing-machines#76`
  (3fa9dda, 2026-11-10).
- The "backend not ready" banner said to start the backend with `python main.py`; it now says
  `python -m app.main` from `backend/` (branch `refactor/structure-fixes`, 2026-11-10).
- Streamlit's pillow pin keeps `pillow<13`, which blocks the pillow CVE fixes flagged by pip-audit.

## Status
- Last reviewed: 2026-11-10
- Open issues / follow-ups: split out `api_client.py` / `pages/` and add a
  Dockerfile only if the demo grows.
- Ceilings (`# ceiling:` markers in this folder): none.
