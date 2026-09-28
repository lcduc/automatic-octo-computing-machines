# API reference

The FastAPI backend serves two APIs under `/api/v1`:

- **Public chat API**: used by a frontend's *server* (the chat widget's Next.js server, or any
  server-to-server integration). It needs an API key, which must never reach a browser.
- **Admin API** (`/api/v1/admin`): used by the admin web on its own domain, and by operator scripts.

The machine-readable schema is [`openapi.json`](openapi.json) (regenerate with
`python -m scripts.export_openapi`). The interactive docs at `/docs` are available when
`APP_ENV=development`. Breaking changes go to `/api/v2`; `/api/v1` only gains optional fields and new
endpoints.

---

## 1. Conventions

| Topic | Rule |
|---|---|
| Format | JSON in and out (`Content-Type: application/json`), except uploads (`multipart/form-data`) and streams (`text/event-stream`). |
| Ids | UUID strings, except knowledge sources, which use integer ids. |
| Times | ISO 8601 with time zone, e.g. `2026-09-29T08:00:00Z`. |
| Pagination | List endpoints take `limit` (default 50, max 200) and `offset`, and return `{"items": [...], "total": 123, "limit": 50, "offset": 0}`. |
| Request id | Every response has `X-Request-ID`. Send your own (8–64 of `A-Z a-z 0-9 -`) to correlate logs across services. |
| Errors | Always `{"detail": "..."}`. Validation errors (422) give `detail` as a list of `{loc, msg, type}`. 500s also carry `request_id`. |
| Body size | Uploads up to `MAX_FILE_SIZE` (default 50 MB); bigger requests get 413. |

### Status codes

| Code | Meaning |
|---|---|
| 200 / 201 / 202 | OK / created / accepted (upload queued for processing) |
| 400 | The request is well-formed but not allowed (e.g. unknown source, a chunking strategy that finds nothing) |
| 401 | Missing or invalid credentials (API key, session) |
| 403 | Authenticated, but the key's scope or the admin's role forbids it, or the CSRF header is missing |
| 404 | Not found (also returned for another visitor's conversation) |
| 409 | Conflicts with the current state (duplicate file, document still processing, hand-edited chunks) |
| 413 | Body too large |
| 422 | Validation failed (field types, lengths, bounds) |
| 429 | Rate limited; wait `Retry-After` seconds |
| 503 | Temporarily unavailable (e.g. too many answers being generated at once) |

### Rate limits

| Limit | Default | Setting |
|---|---|---|
| Requests per client IP (every route except `/health`) | 120 / minute | `RATE_LIMIT_IP_PER_MINUTE` |
| Chat messages per visitor | 20 / minute | `RATE_LIMIT_USER_PER_MINUTE` |
| Tokens per visitor per day (0 = unlimited) | 60 000 | `DAILY_TOKEN_BUDGET_PER_USER` |
| Answers generated at the same time | 16 (503 beyond) | `MAX_CONCURRENT_CHATS` |
| Admin sign-in attempts per IP and per e-mail | 5 / minute | fixed |

---

## 2. Authentication

### Public chat API

| Header | Required | Value |
|---|---|---|
| `X-API-Key` | always | A key with the `chat` scope, created in the admin web (*Tài khoản & khoá API*) or with `python -m scripts.manage create-api-key`. Shown once; stored hashed. |
| `X-End-User-Id` | all routes except `/widget/config` | An opaque, stable id for the visitor, 8–128 of `A-Z a-z 0-9 _ - : .`. Never an e-mail or phone number. Conversations are only visible to the visitor id that created them. |

The chat widget's server keeps the key in `CHATBOT_API_KEY` and derives the visitor id from a signed
cookie; browsers never see either.

### Admin API

Sign in with `POST /api/v1/admin/auth/login`. The response:

- sets the **`admin_session` cookie**: `HttpOnly`, `SameSite=Strict`, `Path=/api/v1/admin`, and `Secure`
  in production, valid for `ADMIN_TOKEN_TTL_MINUTES` (default 480). This is what the admin web uses;
- returns the same token as `access_token`, for scripts, which send `Authorization: Bearer <token>`.

With the cookie, every `POST` / `PATCH` / `DELETE` must also send **`X-Admin-Request: 1`**, or it gets
403. Browsers never add this header to cross-site requests, so it blocks forged requests.

Roles (each route below lists the lowest role it needs):

| Role | Can |
|---|---|
| `viewer` | Read everything except accounts, API keys and the audit log |
| `support_agent` | Viewer, plus work handoffs |
| `editor` | Support agent, plus change knowledge, settings and run maintenance |
| `owner` | Everything, including accounts, API keys and the audit log |

The role is re-read on every request, so disabling an account or changing its role applies at once.
Every admin write and every sign-in attempt is recorded in the append-only audit log (section 5.9).

---

## 3. Health

| Method | Path | Auth | Response |
|---|---|---|---|
| GET | `/health/live` | none | `{"status": "ok"}` while the process runs |
| GET | `/health/ready` | none | `200 {"status": "ok", "checks": {"database": true, "chat_pipeline": true}}`, or `503` with the failing check |

---

## 4. Public chat API

### 4.1 `POST /api/v1/chat/stream`: ask a question, streamed

Request (`ChatRequest`):

| Field | Type | Notes |
|---|---|---|
| `message` | string | 1–`MAX_MESSAGE_LENGTH` (default 2000) characters, not blank |
| `conversation_id` | uuid, optional | Continue this conversation; omit to start a new one |
| `sources` | string[], optional | Only search these knowledge sources (at most 10) |

The response is `text/event-stream`. Each frame is `event: <type>` + `data: <json>`; comment lines
(`: ping`) are keep-alives sent while the answer is slow.

| Event | Data | When |
|---|---|---|
| `meta` | `{"type", "conversation_id", "message_id"}` | First; keep `conversation_id` for the next turn and `message_id` for feedback |
| `delta` | `{"type", "text"}` | Zero or more pieces of the answer, in order |
| `done` | `{"type", "outcome", "text", "citations", "confidence", "cached", "handoff_id"}` | Last. `text` is the full answer. Canned replies (deny, handoff, blocked) come only here, never as deltas. |
| `error` | `{"type", "message"}` | Instead of `done` if the pipeline fails; `message` is safe to show |

`outcome` is one of `answered`, `smalltalk`, `denied` (nothing relevant in the knowledge base),
`handoff` (transferred to staff; `handoff_id` is set), `blocked` (safety rules), `error`.

A citation is `{"document_id", "chunk_id", "title", "source", "url", "score"}`, at most one per
document, best first. `url` is the document's `url` metadata, when it has one.

If the client disconnects mid-answer, what was generated so far is still saved.

```bash
curl -N https://api.internal/api/v1/chat/stream \
  -H "X-API-Key: $CHATBOT_API_KEY" -H "X-End-User-Id: visitor-7f3a9c" \
  -H "Content-Type: application/json" \
  -d '{"message": "Văn phòng mở cửa mấy giờ?"}'
```

```text
event: meta
data: {"type": "meta", "conversation_id": "4b0e…", "message_id": "a91c…"}

event: delta
data: {"type": "delta", "text": "Văn phòng mở cửa "}

event: done
data: {"type": "done", "outcome": "answered", "text": "Văn phòng mở cửa từ 8 giờ sáng.", "citations": [{"document_id": "…", "chunk_id": "…", "title": "Giờ làm việc", "source": "FAQ", "url": "https://example.com/gio-lam-viec", "score": 0.83}], "confidence": 0.78, "cached": false, "handoff_id": null}
```

Errors: 401 bad key, 403 key without `chat` scope, 400 missing or malformed `X-End-User-Id`,
429 visitor rate limit or daily token budget (with `Retry-After`), 503 too many concurrent answers.

### 4.2 `POST /api/v1/chat`: ask a question, complete JSON

Same request and errors as 4.1. Returns `ChatAnswer`, which is the `done` payload plus
`conversation_id` and `message_id`. Meant for server-to-server integrations that don't stream.

### 4.3 `GET /api/v1/conversations/{conversation_id}`

Restores the widget after a reload. Returns `{"id", "status", "messages": [...]}`, where each message is
`{"id", "role": "user" | "assistant", "content", "outcome", "citations", "created_at", "feedback_rating"}`.
Returns 404 when the conversation belongs to another visitor id.

### 4.4 `POST /api/v1/feedback`

`{"message_id": uuid, "rating": 1 | -1, "comment": "optional, ≤1000 chars"}` → `{"message": "Feedback recorded"}`.
Only the visitor who received the answer can rate it; rating again replaces the earlier rating.

### 4.5 `GET /api/v1/widget/config`

Needs only `X-API-Key`. Returns the look set in the admin web:
`{"title", "welcome_message", "primary_color": "#RRGGBB", "suggested_questions": [...]}`.

### 4.6 `POST /api/v1/chat/transcribe`

`multipart/form-data` with an `audio` file (up to `MAX_AUDIO_FILE_SIZE`, default 25 MB) → `{"text": "..."}`.
Needs `OPENAI_API_KEY` on the backend (503 without it). 400 for an empty file, 413 when too large.

---

## 5. Admin API

All paths below are relative to `/api/v1/admin`.

### 5.1 Session and own account

| Method | Path | Role | Body → response |
|---|---|---|---|
| POST | `/auth/login` | none | `{"email", "password"}` → `{"access_token", "token_type": "bearer", "expires_at", "admin": AdminOut}`, and sets the session cookie. 401 wrong credentials, 429 too many attempts. |
| POST | `/auth/logout` | none | Clears the session cookie → `{"message"}` |
| GET | `/auth/me` | viewer | → `AdminOut` |
| POST | `/auth/password` | viewer | `{"current_password", "new_password" (≥10 chars)}` → `{"message"}` |

`AdminOut` = `{"id", "email", "role", "disabled", "created_at", "last_login_at"}`.

### 5.2 Accounts and API keys (owner)

| Method | Path | Body → response |
|---|---|---|
| GET | `/users` | → `AdminOut[]` |
| POST | `/users` | `{"email", "password" (≥10), "role" (default viewer)}` → 201 `AdminOut` |
| PATCH | `/users/{admin_id}` | `{"role"?, "disabled"?}` → `AdminOut`. The last enabled owner cannot be demoted or disabled. Accounts are disabled, never deleted. |
| GET | `/api-keys` | → `[{"id", "name", "key_prefix", "scopes", "created_at", "last_used_at", "revoked_at"}]` |
| POST | `/api-keys` | `{"name"}` → 201 the same plus `"key"`, **shown only this once** |
| POST | `/api-keys/{key_id}/revoke` | → the revoked key |

### 5.3 Knowledge: sources

A source is a group of documents (e.g. `FAQ`, `contracts`) that can be switched off as a unit and
weighted in retrieval.

| Method | Path | Role | Body → response |
|---|---|---|---|
| GET | `/knowledge/sources` | viewer | → `[{"id", "name", "description", "priority", "enabled", "document_count"}]` |
| POST | `/knowledge/sources` | editor | `{"name" (A-Z a-z 0-9 _ -, ≤64), "description"?, "priority" 0.1–5 (default 1), "enabled"?}` → 201 source |
| PATCH | `/knowledge/sources/{source_id}` | editor | any of the same fields → source |
| DELETE | `/knowledge/sources/{source_id}` | editor | → `{"message"}`; 409 while the source still has documents |

### 5.4 Knowledge: documents

`DocumentOut` = `{"id", "title", "source", "original_filename", "file_type", "status": "processing" | "ready" | "failed",
"error", "enabled", "chunk_count", "metadata", "chunking", "can_rechunk", "created_by", "created_at", "updated_at"}`.
`DocumentDetail` adds `"chunks": ChunkOut[]`, where `ChunkOut` = `{"id", "position", "content", "metadata", "edited", "updated_at"}`.

| Method | Path | Role | Details |
|---|---|---|---|
| GET | `/knowledge/documents` | viewer | Query: `source`, `status`, `search` (title or file name), `limit`, `offset` → `Page<DocumentOut>` |
| POST | `/knowledge/documents/upload` | editor | Multipart, see below → **202** `DocumentOut` with status `processing` |
| POST | `/knowledge/documents/text` | editor | `{"source", "title", "content" (≤200 000 chars), "metadata"?, "chunking"?}` → 201 `DocumentOut`, embedded at once |
| GET | `/knowledge/documents/{document_id}` | viewer | → `DocumentDetail` |
| PATCH | `/knowledge/documents/{document_id}` | editor | `{"title"?, "source"?, "metadata"?, "enabled"?}` → `DocumentDetail`. Metadata changes need no re-embedding. `enabled: false` removes the document from answers at once. |
| DELETE | `/knowledge/documents/{document_id}` | editor | Deletes the document and its chunks → `{"message"}` |

**Upload form fields**

| Field | Required | Notes |
|---|---|---|
| `file` | yes | `.pdf .docx .txt .md .csv .xlsx` (`ALLOWED_EXTENSIONS`), up to `MAX_FILE_SIZE`; PDFs up to `MAX_PDF_PAGES` (300) pages |
| `source` | yes | An existing source name |
| `title` | no | Defaults to the file name |
| `metadata` | no | JSON object string (see *Metadata*) |
| `chunking` | no | JSON string, default `{"strategy": "auto"}` (see 5.6); 422 when invalid |
| `enabled` | no | `false` holds the document back from answers until an admin switches it on (review first) |

Parsing, OCR and embedding run in the ingestion worker. Poll `GET /knowledge/documents/{id}` until
`status` is `ready` or `failed` (then `error` explains why). Uploading the same file into the same
source again is refused with 409, unless the earlier copy failed, in which case it is replaced.

**Metadata**: a flat object of at most 30 keys (`[A-Za-z_][A-Za-z0-9_]{0,63}`), 4 KB in total, with
scalar or list-of-scalar values. The model sees the values; `url` becomes the citation link. Chunk
metadata overrides the document's for that chunk.

### 5.5 Knowledge: chunks

| Method | Path | Role | Body → response |
|---|---|---|---|
| POST | `/knowledge/documents/{document_id}/chunks` | editor | `{"content" (≤20 000), "metadata"?, "position"?}` → 201 `ChunkOut`; inserted before `position`, or appended |
| PATCH | `/knowledge/chunks/{chunk_id}` | editor | `{"content"?, "metadata"?}` → `ChunkOut`; new content is re-embedded |
| DELETE | `/knowledge/chunks/{chunk_id}` | editor | → `{"message"}`; later positions close the gap |

Added or edited chunks get `edited: true`, so a later re-chunk asks before discarding them.

### 5.6 Knowledge: chunking strategies, preview, re-chunk

The text extracted from each upload is stored, so a document can be re-chunked without uploading it
again. Documents uploaded before this existed have `can_rechunk: false`.

`chunking` is an object whose `strategy` selects the parameters (unknown keys give 422):

| `strategy` | Parameters (defaults) | Splits |
|---|---|---|
| `auto` | none | Each file type's own way: Docling by heading, OCR and plain text by size |
| `size` | `max_chars` (`CHUNK_SIZE`), `overlap` (false) | Whole sentences packed up to the limit |
| `heading` | `max_level` 1–6 (2), `max_chars` (3000) | One chunk per heading section; long sections by size |
| `legal_article` | `split_at`: `chapter` \| `section` \| `article` \| `clause` (`article`), `max_chars` (3000), `breadcrumb` (true) | Vietnamese legal texts at Chương / Mục / Điều / Khoản. Each chunk gets `chapter` / `section` / `article` / `clause` metadata (e.g. `"article": "Điều 12"`) and, with `breadcrumb`, its enclosing titles as a first line. |
| `qa_pair` | none | One chunk per question/answer, from `Hỏi:`/`Đáp:` (or `Q:`/`A:`) lines or a table with question and answer columns; `question` metadata. 400 when no pair is found. |
| `table_rows` | `rows_per_chunk` 1–200 (10), `max_chars` (3000) | Groups of table rows, each repeating the header row; `rows` (and `sheet`) metadata |
| `whole` | none | The whole text as one chunk (400 above 20 000 characters) |

`max_chars` is always 200–20 000.

| Method | Path | Role | Body → response |
|---|---|---|---|
| GET | `/knowledge/chunking/strategies` | viewer | → `[{"name", "description", "params_schema"}]`; `params_schema` is the JSON Schema of the parameters, for building forms |
| POST | `/knowledge/documents/{document_id}/chunking/preview` | editor | `{"chunking", "limit" 1–1000 (200)}` → `{"chunk_count", "min_chars", "max_chars", "avg_chars", "warnings", "chunks": [{"position", "content", "metadata", "char_count"}]}`. Nothing is saved or embedded. |
| POST | `/knowledge/documents/{document_id}/rechunk` | editor | `{"chunking", "discard_manual_edits" (false)}` → `DocumentDetail` with the new chunks, embedded and searchable |

Preview and re-chunk return 409 while the document is still processing or has no stored text. Re-chunk
also returns 409 when chunks were edited by hand, unless `discard_manual_edits` is true. `warnings` flags
a fallback (e.g. no Điều markers found), very short or very long chunks, and duplicates.

### 5.7 Conversations, feedback, handoffs

| Method | Path | Role | Details |
|---|---|---|---|
| GET | `/conversations` | viewer | Query: `outcome`, `status` (`active` \| `handoff_pending` \| `closed`), `since`, `limit`, `offset` → `Page<{"id", "end_user_id", "channel", "status", "message_count", "created_at", "last_activity_at"}>` |
| GET | `/conversations/{conversation_id}` | viewer | The summary plus `messages`. Each message adds `outcome`, `citations`, `confidence`, `model`, `prompt_tokens`, `completion_tokens`, `latency_ms`, `cached`, `guard_reason`, `request_id` and `feedback` to the visitor's view of it. |
| GET | `/feedback` | viewer | Query: `rating` (`1` or `-1`), `limit`, `offset` → `Page<{"id", "rating", "comment", "created_at", "message_id", "conversation_id", "question", "answer", "outcome"}>` |
| GET | `/handoffs` | viewer | Query: `status` (`pending` \| `in_progress` \| `resolved`), `limit`, `offset` → `Page<{"id", "conversation_id", "message_id", "reason", "status", "note", "created_at", "updated_at"}>`. `reason` is `user_request` or `no_knowledge`. |
| PATCH | `/handoffs/{handoff_id}` | support_agent | `{"status", "note"? (≤2000)}` → the handoff |

### 5.8 Monitoring and maintenance

| Method | Path | Role | Details |
|---|---|---|---|
| GET | `/usage/summary?days=1..90` | viewer | `{"since", "daily": [{"day", "model", "prompt_tokens", "completion_tokens", "calls"}], "by_purpose": [{"purpose", "tokens", "calls"}], "outcomes": {outcome: count}, "feedback": {"positive", "negative"}, "latency": {"p50_ms", "p95_ms", "conversations"}, "totals": {...}}` |
| GET | `/usage/live` | viewer | Server-Sent Events: `hello`, then `turn` (`conversation_id`, `message_id`, `outcome`, `prompt_tokens`, `completion_tokens`, `latency_ms`, `model`) and `handoff` (`handoff_id`, `conversation_id`, `reason`); `: ping` every 15 s. Read it with `fetch`, since `EventSource` cannot send the session headers. |
| GET | `/logs` | viewer | Query: `level`, `request_id`, `contains`, `since`, `limit` ≤500 → `[{"ts", "level", "logger", "message", "request_id", "exception"}]`, newest first, PII already masked |
| GET | `/system` | viewer | `{"version", "uptime_seconds", "database", "knowledge_index_version", "indexed_chunks", "indexed_sources", "llm_provider", "llm_model", "embedding_model", "reranker_loaded", "cache", "fallback_mode", "ingestion_queue": {"pending", "in_progress", "oldest_pending_seconds"}}` |
| POST | `/system/cache/clear` | editor | Empties the answer cache |
| POST | `/system/reindex` | editor | Rebuilds the search index from the database |

### 5.9 Settings

Runtime settings apply from the next chat turn, with no restart.

| Method | Path | Role | Details |
|---|---|---|---|
| GET | `/settings` | viewer | Every setting and its current value |
| GET | `/settings/defaults` | viewer | What each setting falls back to (`.env` / built-in); compare with `/settings` to see overrides |
| PATCH | `/settings` | editor | Any subset of the keys below → all settings |
| DELETE | `/settings/{key}` | editor | Drops the saved override so the default applies again → all settings |

| Key | Type / bounds | Meaning |
|---|---|---|
| `fallback_mode` | `deny` \| `handoff` | What happens when nothing relevant is found |
| `deny_message`, `handoff_message`, `guard_block_message`, `greeting_message`, `thanks_message` | string ≤2000 | Canned replies |
| `assistant_instructions` | string ≤4000 | Extra system-prompt instructions (persona, scope, tone) |
| `widget_title` (≤80), `widget_welcome_message` (≤500), `widget_primary_color` (`#RRGGBB`), `widget_suggested_questions` (≤6) | | The widget's look (public via `/widget/config`) |
| `chat_model`, `light_model` | model id ≤100, `[A-Za-z0-9._:/-]` | Answer model and the cheaper rewrite/routing model of the configured provider. **A new value is tried with one tiny request first; if the provider rejects it you get 400 and nothing is saved.** |
| `similarity_threshold` | 0–1 | Minimum relevance a chunk needs |
| `semantic_weight` | 0–1 | Semantic share of the hybrid score (the rest is keyword search) |
| `retrieval_top_k`, `max_context_chunks` | 1–20 | Chunks kept after reranking; cap after neighbour expansion |

The embedding and reranker models are `.env`-only, because changing them re-embeds everything at
start-up.

### 5.10 Audit log (owner)

`GET /audit`, query: `actor` (part of an e-mail), `method` (`POST` \| `PATCH` \| `DELETE`),
`path_contains`, `since`, `limit`, `offset` → `Page<{"id", "created_at", "actor_id", "actor_email",
"actor_role", "method", "path", "status_code", "request_id", "client_ip", "request_body", "response_body"}>`.

It records every admin write and sign-in attempt, successful or not. Passwords, keys and tokens are
replaced by `***`. Bodies over 16 KB, and uploads, are summarised as `{"omitted": content_type, "bytes": n}`.
There is no endpoint to change or delete entries, and the database itself rejects `UPDATE` and `DELETE`
on the table.
