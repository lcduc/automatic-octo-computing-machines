# `backend/app/api/`

<!-- Keep this README true. Anyone (person or agent) who adds, removes or renames a file here,
     or hits a problem worth remembering, updates the matching section in the same PR. -->

## Purpose
The HTTP layer: the composition root that builds every shared service, the FastAPI dependencies
that authenticate callers, the mapping from service errors to HTTP statuses, SSE framing, the
unversioned health probes and the request/response schemas (the public API contract). Endpoints
themselves live in [v1/routes/](v1/routes/README.md). Business logic does not belong here: routes
parse, call a service, return; use cases go in `services/`, domain logic in `core/`. App-wide
middleware lives in `middleware/`, not here.

## Files
| File | Public names | What it does |
|---|---|---|
| `container.py` | `AppContainer`, `INGESTION_WATCH_SECONDS`, `MODEL_CHECK_PROMPT` | Composition root. `__init__` wires the database, services and optional SQL tools; `start()` connects, loads settings/prices, loads the embedding service and reranker (in-process or via the model server), creates the LLM, builds the chat pipeline (`ChatbotService`), `ChatService`, `KnowledgeService`, `ChunkEditingService`, `IndexSyncService`, re-embeds stale chunks, builds the first index snapshot and starts background loops; `stop()` drains and closes. `check_model()` tries a new model with one tiny prompt. |
| `dependencies.py` | `get_container`, `client_ip`, `require_client_key`, `require_chat_caller`, `require_admin`, `READ_ROLES`, `WRITE_ROLES`, `HANDOFF_ROLES`, `OWNER_ROLES`, `ADMIN_SESSION_COOKIE`, `ADMIN_COOKIE_PATH`, `CSRF_HEADER`, `END_USER_ID_PATTERN` | FastAPI `Depends()` providers: the container, chat-caller auth (`X-Service-Token` or a `chat`-scoped `X-API-Key`, plus `X-End-User-Id`, plus an optional host-site Bearer token), and `require_admin(roles, key_scope)` for admin routes (session cookie or Bearer; cookie writes need `X-Admin-Request: 1`; a scoped `X-API-Key` only where the route names a scope; keys are refused when browser-only headers are present). |
| `error_handlers.py` | `register_error_handlers`, `STATUS_BY_ERROR`, `UNAVAILABLE_RETRY_AFTER_SECONDS` | Maps `services.errors` types to 404/409/400/403/429/503 (with `Retry-After` for 429/503); any other exception -> logged, generic 500 with the request id. |
| `sse.py` | `encode_event`, `sse_stream`, `HEARTBEAT_SECONDS`, `STREAM_HEADERS`, `PING_FRAME` | Frames event dicts as Server-Sent Events, sends a ping every 15 s while the next event is slow, cancels the producer on client disconnect and emits an `error` event (text `AutoReplies.ERROR` from `core/agent/prompts.py`) if the stream fails. Used by `/chat/stream` and `/admin/usage/live`. |
| `health.py` | `router`, `live`, `ready` | Unversioned probes: `GET /health/live` (always 200) and `GET /health/ready` (200 only when database, pipeline, model server if used, and LLM provider answer; else 503). No auth, no internals. |
| `model_server_api.py` | `create_model_server_app`, `EmbedRequest`, `EmbedResponse`, `RerankRequest`, `RerankResponse`, `OcrResponse` | HTTP layer of the separate model-server process, served by `app/model_server.py`: `/health/live` (no token), `/ready`, `/embed`, `/rerank`, `/ocr`; every route but liveness needs `X-Service-Token: MODEL_SERVER_TOKEN`; request size caps; answers 503 with `Retry-After` when the scheduler is full. Wraps `core/infrastructure/model_server/` (`ModelHost`, `PriorityScheduler`). |
| `v1/__init__.py` | — | Marks API version 1, served under `/api/v1`. The routers are in `v1/routes/`. |

### schemas/
Pydantic request/response models: the HTTP contract that frontends depend on. Routes return these,
never internal `models/` objects.

| File | Public names | What it does |
|---|---|---|
| `schemas/admin.py` | `LoginRequest`, `TokenResponse`, `AdminOut`, `AdminCreate`, `AdminUpdate`, `PasswordChange`, `ApiKeyOut`, `ApiKeyCreate`, `ApiKeyRotate`, `ApiKeyCreated`, `SqlToolOut`, `SqlToolUpdate`, `ModelPriceIn`, `ModelPriceOut`, `SettingsUpdate`, `ConversationSummary`, `ConversationDetail`, `AdminMessage`, `MessageTraceOut`, `TraceCall`, `FeedbackOut`, `FeedbackItem`, `FeedbackReview`, `HandoffOut`, `HandoffUpdate`, `HandoffAnswer`, `HandoffContactOut`, `LogEntry`, `IngestionQueueStatus`, `ModelServerLoad`, `SystemStatus`, `AuditEntryOut` | Admin web contract: accounts, API keys, SQL tools, model prices, runtime settings (with limits such as `MAX_INSTRUCTIONS`, `MAX_SPEND_CAP_USD`), conversations and traces, feedback inbox, handoff tickets (contact masked), logs, system status, audit entries. |
| `schemas/chat.py` | `ChatRequest`, `ChatAnswer`, `Citation`, `FeedbackRequest`, `FeedbackResult`, `HandoffContact`, `ConversationMessage`, `ConversationHistory`, `WidgetConfig`, `TranscriptionResponse` | Public chat contract used by the widget's server and server-to-server integrations. |
| `schemas/chunking.py` | `AutoChunking`, `SizeChunking`, `HeadingChunking`, `LegalArticleChunking`, `QaPairChunking`, `TableRowsChunking`, `WholeChunking`, `CHUNKING_ADAPTER`, `to_spec`, `strategy_catalog`, `ChunkingPreviewRequest`, `RechunkRequest`, `PreviewChunk`, `ChunkingPreview`, `ChunkingStrategyInfo` | One model per chunking strategy (discriminated union via `CHUNKING_ADAPTER`), conversion to the internal `ChunkingSpec`, and the strategy catalog with JSON schemas for the admin form. |
| `schemas/common.py` | `ApiModel`, `Page`, `MessageResponse`, `validate_metadata`, `DEFAULT_PAGE_SIZE`, `MAX_PAGE_SIZE` | Shared pieces: ORM-friendly base model, generic page (`items`, `total`, `limit`, `offset`), plain message, flat-metadata validation (key pattern, 30 keys, 4096 bytes). |
| `schemas/evaluation.py` | `EvalCaseCreate`, `EvalCaseOut` | Golden eval-set cases created from real answers (ADM-12). |
| `schemas/knowledge.py` | `SourceOut`, `SourceCreate`, `SourceUpdate`, `DocumentOut`, `DocumentDetail`, `DocumentUpdate`, `TextDocumentCreate`, `ReviewDecision`, `ReviewCounts`, `CitingAnswer`, `ChunkOut`, `ChunkCreate`, `ChunkUpdate`, `ImportResultOut`, `SOURCE_NAME_PATTERN` | Knowledge-base contract: sources, documents, review, chunks, import results. `SOURCE_NAME_PATTERN` is imported from `models/knowledge_bundle.py` and re-exported. |
| `schemas/privacy.py` | `LegalHoldUpdate`, `LegalHoldOut`, `DataSubjectQuery`, `DataSubjectExport`, `DataSubjectDeleted` | Legal hold and data-subject export/delete (PRV-03); `DataSubjectQuery.to_subject()` builds the internal `DataSubject`. |

Flow of one request: middleware -> route in `v1/routes/` -> `Depends(get_container)` +
`require_*` auth -> `container.<service>.<method>()` -> schema object returned (or a
`ServiceError` turned into a status by `error_handlers.py`).

## Dependencies
- May import: `services`, `core`, `models`, `utils`, `config`. Must not import `middleware`
  (layering: api -> services -> core -> models/utils, config at the bottom; only `main.py` imports
  middleware; enforced by `test/unit/test_layering.py`).
- Used by: `main.py` (container, error handlers, health and v1 routers); `model_server.py`
  (`model_server_api.py`); `middleware/` reads
  `scope["app"].state.container` (rate limiter) at runtime; `scripts/export_openapi.py` via `create_app`.
- External: PostgreSQL, the LLM provider, the model server when `MODEL_SERVER_URL` is set, the
  client's business DB when `BUSINESS_DB_URL` is set, SMTP.

### Versioning
- Versioned endpoints live under `/api/v1` (`API_V1_PREFIX` in `v1/routes/__init__.py`); health
  probes stay unversioned at `/health/*`.
- Breaking changes go into a new `v2` package served under `/api/v2`, never as edits to v1.
- `schemas/` is the HTTP contract; `models/` is internal. Services convert between them. Exception
  today: `/admin/knowledge/export` and `/admin/knowledge/import` use the pydantic
  `models.knowledge_bundle.KnowledgeBundle` directly as response/request body.

## Run / test
```bash
pytest test/integration/test_api.py         # auth, roles, CORS/headers, CSRF, audit, chat, chunking; needs TEST_DATABASE_URL
pytest test/integration/test_api_keys.py test/integration/test_host_identity_api.py test/integration/test_privacy_api.py
pytest test/unit/test_service_token_auth.py test/unit/test_model_server.py
python -m scripts.export_openapi            # rewrite docs/openapi.json after a schema change
```

## Known problems and history
- Versioned routes moved from `api/routes/` to `api/v1/routes/`; health probes stayed unversioned
  in `health.py` (lcduc/automatic-octo-computing-machines#76, 0787fab, 2026-11-10).
- `KnowledgeService` split -> the container gained `container.chunks` (`ChunkEditingService`) and
  `container.index_sync` (`IndexSyncService`) (#74, 7990db1).
- Middleware moved out of `api/` into its own `middleware/` package (3b8c60d, 2026-09-28).
- Tool calling, moderation and transcription need an OpenAI client: `_openai_extras()` reuses the
  chat provider when it is OpenAI, otherwise creates one only if `OPENAI_API_KEY` or
  `OPENAI_BASE_URL` is set (`OPENAI_BASE_URL` added in #63, 2026-10-27).
- Admin API keys are scope-checked and rate-limited per key (61e49cb, 2026-09-28); the widget
  server authenticates with a generated service token (61c64d1, 2026-09-28).
- `model_server_api.py` moved here from `core/infrastructure/model_server/app.py` so `core/` has no
  FastAPI import; `sse.py` now uses `AutoReplies.ERROR` instead of a hardcoded Vietnamese string;
  `SOURCE_NAME_PATTERN` is no longer duplicated; `docs/openapi.json` regenerated
  (branch `refactor/structure-fixes`, 2026-11-10).

## Status
- Last reviewed: 2026-11-10
- Open issues / follow-ups: none.
- Ceilings (`# ceiling:` markers in this folder): see [v1/routes/](v1/routes/README.md)
  (`admin/knowledge.py:226`). None in the files directly here.
