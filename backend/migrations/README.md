# `backend/migrations/`

<!-- Keep this README true. Anyone (person or agent) who adds, removes or renames a file here,
     or hits a problem worth remembering, updates the matching section in the same PR. -->

## Purpose
Alembic schema migrations for the application database (PostgreSQL + pgvector). Every schema change
ships as a revision here; there is no manual SQL on production (OPS-08). Table definitions themselves
live in `app/core/storage/tables/` (`Base.metadata`); the client's business database used by SQL tools is
not managed here (see `deploy/business_db/`).

## Files
| File | Public names | What it does |
|---|---|---|
| `env.py` | `run_migrations_offline`, `run_migrations_online` | Alembic environment: reads the URL from `Config.Database.DATABASE_URL()` and runs migrations over an async engine (`create_async_engine` + `run_sync`); `target_metadata = Base.metadata`, `compare_type=True` for autogenerate. Offline mode (`--sql`) prints SQL. |
| `script.py.mako` | — | Template for new revisions; pre-imports `alembic.op`, `sqlalchemy as sa` and `pgvector.sqlalchemy`. |
| `../alembic.ini` | — | Lives in `backend/`: `script_location = migrations`, `prepend_sys_path = .`, file names `YYYYMMDD_<rev>_<slug>.py`. |

### versions/
Applied in this order (the `down_revision` chain; file-name order differs on 2026-09-30):

| # | File | Revision | What it does |
|---|---|---|---|
| 1 | `20260924_3b5c8693432c_initial_schema.py` | `3b5c8693432c` | `CREATE EXTENSION vector`; admin users, API keys, app settings, knowledge sources/documents/chunks, conversations, messages, feedback, handoff requests, token usage. |
| 2 | `20260928_a7e4c2d19b53_ingestion_queue.py` | `a7e4c2d19b53` | Ingestion queue columns on `knowledge_documents` (`attempts`, `claimed_at`, `processed_at`). |
| 3 | `20260928_c3f81a6d0e24_chunking_strategy.py` | `c3f81a6d0e24` | Per-document chunking strategy, stored extracted text and method, `edited` flag on chunks. |
| 4 | `20260929_5d2e9b7c4a18_admin_audit_log.py` | `5d2e9b7c4a18` | `admin_audit_log` table, append-only via a trigger that raises on UPDATE/DELETE. |
| 5 | `20260930_8b41f2c6d7e5_host_identity.py` | `8b41f2c6d7e5` | `conversations.user_id` (owner) and `host_token_uses` (token-visitor bindings). |
| 6 | `20260930_2c7e19a4b6d3_api_key_limits.py` | `2c7e19a4b6d3` | API key expiry, per-key `rate_limit_per_minute`, `rotated_from_id`. |
| 7 | `20261001_6f3a8d21c9b4_usage_counters.py` | `6f3a8d21c9b4` | `usage_counters`, `model_prices`, cost and tier per `token_usage` row. |
| 8 | `20261001_9d4b7e2a1f60_sql_tools.py` | `9d4b7e2a1f60` | `sql_tools` registry table. |
| 9 | `20261002_4e8c1b7d2a95_document_lifecycle.py` | `4e8c1b7d2a95` | Document access tier, language, version, effective dates, `supersedes_id`. |
| 10 | `20261002_7a2f9c3e5b18_handoff_tickets.py` | `7a2f9c3e5b18` | Handoff requests become async tickets (contact, consent, answer, due time, legal hold); renames old status values in data. |
| 11 | `20261003_8d81aec5cb82_observability.py` | `8d81aec5cb82` | `alert_states`, `metrics_daily`, `message_traces` (ADM-05, OBS-03, OBS-04). |
| 12 | `20261004_87894e201f49_privacy.py` | `87894e201f49` | `eval_cases`, legal hold on conversations, feedback review columns; audit trigger now lets the purge delete entries older than 365 days. |
| 13 | `20261006_b4d7e1a92c35_document_review.py` | `b4d7e1a92c35` | Document review status/reviewer/note; existing rows set `approved`, then the server default is dropped so new rows take the app's `pending`. |
| 14 | `20261007_c5e2a8f31d96_message_answered_by.py` | `c5e2a8f31d96` | `messages.answered_by` (which staff member wrote a reply). Current head. |

## Dependencies
- May import: `app.config.settings` and `app.core.storage.tables` (in `env.py`); revisions import only
  `alembic`, `sqlalchemy` (and its postgresql dialect) and `pgvector.sqlalchemy`, not application code.
- Used by: `alembic` CLI only (`start.sh` with `MIGRATE_ON_START=true`, compose's one-shot `migrate`
  service, CI). Not imported by `app/`.
- External: PostgreSQL 17 with the `vector` extension (`pgvector/pgvector:pg17`). Under docker compose
  `migrate` runs as the schema owner (`chatbot`); the API connects as `chatbot_app`, which may read and
  write rows but not change the schema.

## Run / test
From `backend/` with the venv active. The URL comes from `POSTGRES_*` in `.env`, or `DATABASE_URL`
when set (it overrides the assembled value).
```bash
alembic upgrade head                                   # apply all
alembic current                                        # show the applied revision
alembic history                                        # list revisions
alembic revision --autogenerate -m "short description" # new revision from Base.metadata changes; review it
alembic downgrade -1                                   # undo the last revision
alembic downgrade base                                 # undo everything (drops all tables)
alembic upgrade head --sql                             # print SQL without connecting
```
CI (`.github/workflows/ci.yml`, step "Check migrations") runs
`alembic upgrade head && alembic downgrade base && alembic upgrade head` against an empty
`pgvector/pgvector:pg17` database, so every revision needs a working `downgrade()`.
Integration tests do not run migrations: `test/integration/conftest.py` builds the schema with
`Base.metadata.create_all`, so a table change that is not also in a revision passes tests but fails
the CI migration check or production.

## Known problems and history
- Migrations were added with the database layer in 83b6817 (2026-09-25); the first revision is dated
  2026-09-24.
- The audit log must stay append-only but retention must purge year-old entries -> revision 12 replaces
  the trigger function with one that allows DELETE of rows older than 365 days only (e029fc9, 2026-09-29).
- Documents that already answered questions had to stay visible when review was introduced -> revision 13
  adds `review_status` with default `approved`, then drops the default (0315318,
  `lcduc/automatic-octo-computing-machines#32`, 2026-10-07).
- Before `lcduc/automatic-octo-computing-machines#76` (06f0477, 2026-11-10) this folder and `alembic.ini`
  lived at the repo root; run `alembic` from `backend/` now.

## Status
- Last reviewed: 2026-11-10
- Open issues / follow-ups: migrations are not reverted by the ops `rollback`; restore the pre-deploy
  backup instead (docs/deployment.md).
- Ceilings (`# ceiling:` markers in this folder): none.
