# `backend/app/services/`

<!-- Keep this README true. Anyone (person or agent) who adds, removes or renames a file here,
     or hits a problem worth remembering, updates the matching section in the same PR. -->

## Purpose
Use-case orchestration between the HTTP layer (`app/api/`) and the domain engine (`app/core/`): one
class per use case (chat turn, knowledge CRUD, API keys, budgets, retention, ...) that opens database
sessions, calls core repositories/engines and raises the exceptions in `errors.py`. Services hold no
FastAPI code: request parsing, Pydantic schemas and HTTP status mapping live in `app/api/`.
Retrieval, LLM providers, parsing/OCR, storage tables and repositories belong in `app/core/`; plain
data classes in `app/models/`.

## Files

### Chat
| File | Public names | What it does |
|---|---|---|
| `chat_service.py` | `ChatService`, `PreparedTurn` | One chat turn end to end: quotas, PII redaction, conversation state, runs the pipeline (`core/agent/chatbot.py` `ChatbotService`), stores messages, trace and token usage; `prepare` / `stream` / `answer` / `wait_for_pending_writes`. |
| `conversation_service.py` | `ConversationService` | Visitor and admin views of conversations, message traces, feedback (two thumbs-down in a row open a handoff ticket when handoff is on). |
| `transcription_service.py` | `TranscriptionService` | Speech-to-text for voice questions through the OpenAI transcription API; unavailable without an OpenAI key. |

### Handoff (transfer to a human)
| File | Public names | What it does |
|---|---|---|
| `handoff_service.py` | `HandoffService`, `mask_email`, `mask_phone` | Async support tickets (HND-13..16): create, answer (in chat and by e-mail via `SmtpMailer`), close; contact details masked by default. |
| `business_calendar.py` | `BusinessCalendar`, `CalendarError` | Support hours and holidays (HND-07): "is support open?" and "N working hours from now". |

### Knowledge base and ingestion
| File | Public names | What it does |
|---|---|---|
| `knowledge_service.py` | `KnowledgeService` | Sources and documents: CRUD, upload (queues the file), typed-text documents, review/approval, access tiers, answers citing a document; refreshes the search index after every change. |
| `chunk_editing_service.py` | `ChunkEditingService`, `chunk_off_loop` | Chunk-level edits: update/add/delete a chunk, `preview_chunking`, `rechunk`; re-embeds what it touches. `chunk_off_loop` runs chunking in a worker thread. |
| `index_sync_service.py` | `IndexSyncService` | Background upkeep of the in-memory index: `ingestion_queue` stats, `refresh_index_if_ingested`, `watch_ingestions` loop, `reembed_stale_chunks` (batches of `REEMBED_BATCH_SIZE`) when the embedding model changed. Owns the last-processed / ingestion-mark state. |
| `ingestion_service.py` | `IngestionService` | Parse (`extract`), `chunk` and `embed` uploaded files or typed text; caps concurrent OCR files. |
| `ingestion_worker.py` | `IngestionWorker` | Drains the ingestion queue: claims the oldest upload with a renewed lease, parses/embeds/stores it, fails crash-looping uploads after `MAX_ATTEMPTS`. Runs in the API (`INGESTION_WORKER=embedded`) or in `app/worker.py` (`external`). |
| `knowledge_transfer_service.py` | `KnowledgeTransferService` | Exports ready documents as one JSON bundle and imports them without embeddings (the API re-embeds at start-up). |

### Auth, identity and audit
| File | Public names | What it does |
|---|---|---|
| `auth_service.py` | `AuthService`, `VerifiedApiKey`, `AdminPrincipal`, `hash_password`, `verify_password` | Client API keys (`cb_live_` prefix, legacy `cbk_`; scopes, expiry, rotation with grace days, per-key rate limit), admin accounts with scrypt passwords and JWT session tokens, the BFF service token. |
| `host_identity_service.py` | `HostIdentityService`, `HostIdentity`, `HostTokenError` | Verifies host-site JWTs (ID-05/06): who the logged-in user is and their tier; JWKS cached; a `jti` first presented by another visitor is refused. |
| `audit_service.py` | `AuditService`, `AuditRecord`, `redact_secrets` | Writes and lists admin audit entries (every admin write and sign-in attempt); `redact_secrets` masks secret-looking keys at any depth. Called by `app/middleware/admin_audit_middleware.py`. |

### Limits, usage and cost
| File | Public names | What it does |
|---|---|---|
| `rate_limit_service.py` | `RateLimitService`, `Limit`, `TimeBuckets`, `hashed` | Request limits and token/cost totals in the `usage_counters` table, bucketed in the app time zone. |
| `usage_service.py` | `UsageService`, `BudgetVerdict`, `identity_scope`, `ip_scope` | Per-tier token budgets, per-IP budgets, monthly spend cap, dashboard usage statistics. |
| `pricing_service.py` | `PricingService` | LLM price table (ADM-08) cached in memory; cost of every recorded call. |

### Admin settings, tools and evaluation
| File | Public names | What it does |
|---|---|---|
| `settings_service.py` | `SettingsService` | Runtime settings edited in the admin web (fallback mode, canned replies, widget look, chat models, retrieval tuning, limits, support hours, retention) in `app_settings`, cached in memory; owner-only and public-widget key sets. |
| `sql_tool_catalog.py` | `SqlToolCatalog` | The deployment's SQL tools from the `sql_tools` table (TOOL-08), toggled in the admin web; a `ToolSource` for the tool registry. |
| `eval_case_service.py` | `EvalCaseService` | Golden eval set from real answers (ADM-12, RET-R3), PII-masked; create/list/delete/export. |
| `log_service.py` | `LogService` | Reads `app.jsonl` and rotated copies for the admin log viewer, newest first. |

### Observability and operations
| File | Public names | What it does |
|---|---|---|
| `alert_monitor_service.py` | `AlertMonitorService`, `Problem` | Operator alert rules (OBS-04, ADM-09): service down, error spike, disk, overdue tickets, spend, failed uploads, failed jobs; cool-down and "resolved" messages. Runs in the worker. |
| `metrics_rollup_service.py` | `MetricsRollupService` | Daily `metrics_daily` rollup (OBS-03) so dashboards keep history after raw data is purged. |
| `readiness_service.py` | `ReadinessService` | `/health/ready` checks (ARC-07): database, pipeline, model-server, LLM provider (LLM check cached). |
| `live_feed_service.py` | `LiveFeedService`, `asyncpg_dsn` | Admin live feed (answered turns, new handoffs) over PostgreSQL `LISTEN/NOTIFY`; any process publishes, every API process listens. |

### Privacy and retention
| File | Public names | What it does |
|---|---|---|
| `privacy_service.py` | `PrivacyService` | Legal hold (RET-R2) and data-subject export/delete (PRV-03, RET-R5). |
| `retention_service.py` | `RetentionService` | Daily purge (PRV-04, RET-R1) of conversations, tickets, traces, token usage, audit entries, expired host-token bindings and usage counters past their retention; reports deleted counts. |

### Shared
| File | Public names | What it does |
|---|---|---|
| `errors.py` | `ServiceError`, `NotFoundError`, `ConflictError`, `InvalidRequestError`, `PermissionDeniedError`, `RateLimitedError`, `ServiceUnavailableError` | Service exceptions; `app/api/error_handlers.py` maps them to 404/409/400/403/429/503. Their messages are safe to show callers. |
| `__init__.py` | — | Package docstring only. |

### Wiring
Services are built in two places, never by routes:

- **API process** — `app/api/container.py` `AppContainer`. `__init__` builds the database-only services
  (`rate_limiter`, `settings`, `usage`, `metrics`, `pricing`, `live_feed`, `handoffs`, `conversations`,
  `privacy`, `eval_cases`, `auth`, `host_identity`, `logs`, `audit`, `readiness`, `knowledge_transfer`,
  optional `sql_tools`). `start()` loads models, then builds `chat`, `transcription`, `knowledge`,
  `chunks` (`ChunkEditingService`), `index_sync` (`IndexSyncService`) and, in embedded mode, the
  `IngestionWorker`; it re-embeds stale chunks, refreshes the index and starts the
  `index_sync.watch_ingestions` loop. Routes reach them through `app/api/dependencies.py`
  (`container.knowledge`, `container.chunks`, ...).
- **Worker process** — `app/worker.py` builds `SettingsService`, `RateLimitService`, `UsageService`,
  `AlertMonitorService`, `MetricsRollupService`, `RetentionService` (scheduled jobs) and
  `IngestionService` + `IngestionWorker`.

Upload flow: `KnowledgeService.upload_file` stores the file and queues the document ->
`IngestionWorker` claims, parses, embeds and stores chunks -> `IndexSyncService.watch_ingestions`
notices finished uploads and refreshes `KnowledgeIndex`.

## Dependencies
- May import: `app.core.*`, `app.models.*`, `app.utils.*`, `app.config.*`. Never `app.api` or
  `app.middleware` (layering rule api -> services -> core -> models/utils; config at the bottom; only
  `main.py` imports middleware; enforced by `test/unit/test_layering.py`). `chat_service.py` imports the
  pipeline class from `core/agent/chatbot.py`.
- Used by: `app/api/container.py`, `app/api/v1/routes/*` (through the container), `app/api/error_handlers.py`
  (`errors.py`), `app/middleware/admin_audit_middleware.py` (`AuditRecord`), `app/worker.py`,
  `backend/scripts/` CLIs.
- External: PostgreSQL via `core/storage/database.py` (most services; `eval_case_service`,
  `host_identity_service`, `ingestion_worker`, `live_feed_service`, `pricing_service`, `settings_service`,
  `sql_tool_catalog` also query with SQLAlchemy directly); `asyncpg` for LISTEN (`live_feed_service`);
  PyJWT (`auth_service`, `host_identity_service`); `httpx` (`alert_monitor_service` ready probe); OpenAI API
  (`transcription_service`); SMTP (`handoff_service`); embedding/OCR models through `IngestionService`.

## Run / test
Run from `backend/`:
```bash
pytest test/unit                       # no database
pytest test/integration                # needs TEST_DATABASE_URL (see test/README.md)
ruff check .                           # from the repo root
```
Covering tests: unit `test_audit_redaction.py`, `test_business_calendar.py`, `test_host_identity.py`,
`test_model_server.py` (readiness), `test_ocr_resource_limits.py` (ingestion), `test_service_token_auth.py`,
`test_transcription.py`, `test_usage_limits.py`; integration `test_knowledge_service.py` (knowledge,
chunk editing, index sync, ingestion worker), `test_knowledge_transfer.py`, `test_observability.py`,
`test_retention.py`, `test_sql_tools.py`, `test_usage_limits_api.py`, plus the API-level tests in
`test_api.py`, `test_api_keys.py`, `test_tickets.py`, `test_privacy_api.py`, `test_eval_cases_api.py`,
`test_document_review.py`, `test_document_lifecycle.py`, `test_host_identity_api.py`.

## Known problems and history
- `knowledge_service.py` had grown too large -> split into `knowledge_service.py` (sources, documents,
  upload, review), `chunk_editing_service.py` and `index_sync_service.py`; the container gained
  `container.chunks` and `container.index_sync`. `rechunk` raises `NotFoundError` if the document vanished
  while it was re-chunking -> `lcduc/automatic-octo-computing-machines#74` (7990db1, 2026-11-10).
- Ingestion moved out of the request path to a queue drained by `IngestionWorker`, runnable as a
  separate process, with OCR CPU capped ->
  `lcduc/automatic-octo-computing-machines#19` (b13904d, 2026-09-28).
- An upload that kills the worker (OOM, segfault) would be re-claimed forever -> claims carry a lease
  renewed every `CLAIM_RENEW_SECONDS`, and an upload claimed more than `MAX_ATTEMPTS` times is failed with
  `CRASH_LOOP_ERROR`; PDF page limit and retry of failed uploads added ->
  `lcduc/automatic-octo-computing-machines#20` (1e1c650, 2026-09-28).
- Rate limits moved from process memory to PostgreSQL time-bucket counters shared by every process
  (`rate_limit_service.py`, ed7a595, 2026-09-29).
- When the client disconnects mid-stream, the partial answer is still stored, with guard reason
  `client_disconnected` (`ABORTED_GUARD_REASON` in `chat_service.py`).
- Follow-up questions were rewritten badly and human requests were ignored when handoff was off -> rewrite
  from a quoted transcript, answer human requests anyway -> `lcduc/automatic-octo-computing-machines#23`
  (7fa0e9e, 2026-09-30).
- Handoff changed to one open ticket per conversation, with the bot silent after a staff reply -> `lcduc/automatic-octo-computing-machines#25` (1b98334, 2026-10-01).
- Before `lcduc/automatic-octo-computing-machines#76` (06f0477, 2026-11-10) this folder lived at the repo
  root as `services/`; imports were rewritten to `app.services.*`.

## Status
- Last reviewed: 2026-11-10
- Open issues / follow-ups:
  - ARC-11 is partial — `LISTEN/NOTIFY` carries only the admin live feed, not
    config reloads (docs/checklists/production.md); `ingestion_worker.py` and `business_calendar.py` /
    `sql_tool_catalog.py` do not follow the `<name>_service.py` naming.
  - CQ-03: `knowledge_service.py` (445), `auth_service.py` (435) and `chat_service.py` (407) are over ~400 lines (docs/checklists/code-quality.md).
- Ceilings (`# ceiling:` markers in this folder):
  - `chat_service.py:276` — "unhelpful" turn is an outcome + confidence heuristic — replace with a router
    "unclear/declined" signal once ORC-03 clarifications exist.
  - `chunk_editing_service.py:186` — re-chunk chunks and embeds inside the request — move to the ingestion
    queue if re-chunk requests time out.
  - `knowledge_transfer_service.py:52` — whole knowledge base held in memory — stream per document if it
    outgrows RAM.
  - `log_service.py:24` — scans up to ~60 MB of rotated logs per query — ship logs to Loki or similar if the
    log view gets slow or needs longer history.
  - `pricing_service.py:4` — prices cached per process — reload on a timer if several API processes run.
  - `rate_limit_service.py:9` — fixed windows allow up to 2x a limit across a bucket boundary — two-bucket
    sliding estimate if boundary bursts matter.
  - `sql_tool_catalog.py:4` — tools cached per process — reload on a timer if several API processes run.
