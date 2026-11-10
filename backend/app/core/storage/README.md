# `backend/app/core/storage/`

<!-- Keep this README true. Anyone (person or agent) who adds, removes or renames a file here,
     or hits a problem worth remembering, updates the matching section in the same PR. -->

## Purpose
Everything that persists data: the async PostgreSQL connection pool, the SQLAlchemy ORM tables
(`tables/`), one repository class per area that runs queries on a session it is given, and the
on-disk store of original uploads. PostgreSQL + pgvector is the source of truth; the in-memory
search index is built from it in `core/retrieval/knowledge_index.py`. Business rules and
transactions do not belong here: services in `app/services/` open the session, call repositories
and commit. Schema changes go through Alembic (`backend/migrations/`), never by editing a live DB.

## Files

| File | Public names | What it does |
|---|---|---|
| `database.py` | `Database` | Owns the async engine and session factory; `connect()` once at start-up, `session()` commits on success / rolls back on error, `ping()`, `close()`. |
| `knowledge_repository.py` | `KnowledgeRepository`, `ClaimedUpload`, `IngestionQueueStats`, `IndexRow` | Sources, documents, chunks: listing, hash lookup, chunk replace/shift, review counts, stale-embedding scan, rows for the in-memory index, and the ingestion queue (claim with `SKIP LOCKED`, renew, release). |
| `conversation_repository.py` | `ConversationRepository` | Conversations, messages, feedback, handoff tickets, token usage, traces; admin listings and usage / latency / cost aggregates. |
| `access_repository.py` | `AccessRepository` | API keys (lookup by hash) and admin users (by email, active owners count). |
| `audit_repository.py` | `AuditRepository` | Insert and filtered listing of the admin audit log; nothing else. |
| `metrics_repository.py` | `MetricsRepository` | Aggregates one local day from the raw tables and upserts it into `metrics_daily` (OBS-03); history for dashboards. |
| `monitoring_repository.py` | `MonitoringRepository` | Queries behind alert rules (turn errors, failed uploads, overdue tickets) and the alert de-dup state (OBS-04). |
| `privacy_repository.py` | `PrivacyRepository` | Data-subject export/delete queries and legal-hold lookups (PRV-03, RET-R2). |
| `retention_repository.py` | `RetentionRepository` | One bulk `DELETE` per data type for the retention purge (PRV-04); legal-held conversations and kept tickets survive. |
| `usage_counter_repository.py` | `UsageCounterRepository`, `CounterTotals` | Upserts and reads time-bucketed rate-limit / spend counters (one `INSERT ... ON CONFLICT DO UPDATE` per check); purges old buckets. |
| `business_db_probe.py` | `BusinessDbProbe` | Connects with `BUSINESS_DB_URL`'s role and lists every way it could write (superuser, privileges, a write attempt on a probe table); empty list = read-only (TOOL-05, preflight). |
| `upload_store.py` | `UploadStore` | Original uploads on disk as `<document id>.<file type>`, written atomically (`.part` + `os.replace`); shared by API and worker, included in backups (OPS-03). |

### `tables/`
`__init__.py` imports every table module so they all register on `Base.metadata` (Alembic's
`migrations/env.py` imports `Base` from here). Add a new table module to it.

| File | Public names | What it does |
|---|---|---|
| `base.py` | `Base`, `NAMING_CONVENTION`, `utc_now`, `uuid_pk`, `created_at_column`, `updated_at_column` | Declarative base with a fixed constraint naming convention (stable Alembic names) and shared column helpers. |
| `knowledge_tables.py` | `KnowledgeSource`, `KnowledgeDocument`, `KnowledgeChunk`, `approved_by`, `DOCUMENT_STATUS_*`, `REVIEW_*` | Sources, documents (status, review, tier, validity, versions) and chunks with a pgvector `embedding` column and `embedding_model`. |
| `conversation_tables.py` | `Conversation`, `Message`, `Feedback`, `HandoffRequest`, `TokenUsage`, `CONVERSATION_STATUS_*`, `HANDOFF_STATUS_*` | Chat history (message content stored after PII redaction), feedback, handoff tickets, per-call token usage. |
| `access_tables.py` | `ApiKey`, `AdminUser`, `AppSetting`, `HostTokenUse`, `SCOPE_*`, `ROLE_*`, `API_KEY_SCOPES`, `ADMIN_ROLES` | API keys with scopes / expiry / rate limit, admin users and roles, live runtime settings, host-token bindings. |
| `audit_tables.py` | `AdminAuditEntry` | Append-only admin audit log; a PostgreSQL trigger refuses updates and deletes except entries older than the minimum audit retention. |
| `observability_tables.py` | `MessageTrace`, `DailyMetrics`, `AlertState` | Per-answer traces (purged with retention, ADM-05), daily rollups with no personal data (never purged), alert state. |
| `usage_tables.py` | `UsageCounter`, `ModelPrice`, `WINDOW_*`, `COUNTER_WINDOWS` | Minute/hour/day/month counter buckets and LLM prices. |
| `tool_tables.py` | `SqlToolDefinition` | Registry of predefined parameterized SQL tools over the client's business DB (TOOL-01); admins only toggle them. |
| `eval_tables.py` | `EvalCase` | Eval cases from real conversations (ADM-12): redacted question, expected answer, supporting docs, no link back to the conversation. |

## Dependencies
- May import: `app.models` (today only `data_subject` and `retention_policy`), `app.config`/`app.utils`
  if needed, SQLAlchemy, asyncpg, pgvector. It imports no other `core` package today. Settings (DB URL, pool size, upload dir) are passed in by callers. Never `api`, `services` or
  `middleware` (layering rule api -> services -> core -> models/utils, config at the bottom; only
  main.py imports middleware; enforced by `test/unit/test_layering.py`).
- Used by: almost every module in `app/services/`, `api/container.py`, `api/dependencies.py`,
  `core/retrieval/knowledge_index.py`, `core/agent/tools/sql_tool_executor.py`,
  `core/infrastructure/job_scheduler.py`, `app/worker.py`, `migrations/env.py`, `scripts/manage.py`,
  `scripts/eval/generate_synthetic_queries.py`, `scripts/loadtest/report.py`. A few admin routes and
  `middleware/ip_rate_limit_middleware.py` import constants from `tables/` (`SCOPE_*`, `WINDOW_MINUTE`).
- External: PostgreSQL with the `vector` extension (`pgvector/pgvector:pg17`); the client's business
  database (read-only role) for `business_db_probe.py`; the upload directory on disk (`data/uploads`,
  cwd-relative).

## Run / test
From `backend/` with `venv` active.
- Schema change: edit `tables/*.py`, then `alembic revision --autogenerate -m "<what>"` (files are named
  `YYYYMMDD_<rev>_<slug>.py` in `migrations/versions/`), review the generated script (triggers, DDL and
  data steps are not autogenerated), then `alembic upgrade head`. CI runs
  `alembic upgrade head && alembic downgrade base && alembic upgrade head` on an empty database.
- Unit: `pytest test/unit/test_upload_store.py`.
- Integration (skipped unless `TEST_DATABASE_URL` points at a pgvector database; the schema is dropped
  and recreated per test with `Base.metadata.create_all`, so never point it at real data):
  `pytest test/integration` — e.g. `test_knowledge_service.py`, `test_document_lifecycle.py`,
  `test_retention.py`, `test_privacy_api.py`, `test_observability.py`, `test_sql_tools.py`
  (covers `BusinessDbProbe`), `test_usage_limits_api.py`.
- Lint from repo root: `ruff check .`.

## Known problems and history
- Old vector stores and legacy upload/storage modules were removed and replaced by the PostgreSQL
  layer with Alembic (`6791de0`, `83b6817`, 2026-09-25).
- Rate limits kept in process memory reset on restart and did not hold across API processes ->
  time-bucketed counters in PostgreSQL (`usage_tables.py`, `usage_counter_repository.py`) (`ed7a595`,
  2026-09-29).
- Ingestion moved to a separate worker; workers claim uploads from the queue with `SKIP LOCKED` so
  replicas take distinct rows (`b13904d`, 2026-09-28; migration `a7e4c2d19b53`).
- Original uploads are kept on disk for off-server backups (OPS-03) -> `upload_store.py` (`8ffe6d1`,
  2026-09-28).
- The audit log trigger first refused every delete; it now lets the retention purge delete entries older
  than a year (migration `87894e201f49`, `e029fc9`, 2026-09-29). The trigger DDL lives both in
  `audit_tables.py` (for `create_all` in tests) and in the migrations; change both together.
- Handoff tickets: one open ticket per conversation (`1b98334`, 2026-10-01).

## Status
- Last reviewed: 2026-11-10
- Open issues / follow-ups: none recorded.
- Ceilings (`# ceiling:` markers in this folder): none.
