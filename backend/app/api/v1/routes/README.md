# `backend/app/api/v1/routes/`

<!-- Keep this README true. Anyone (person or agent) who adds, removes or renames a file here,
     or hits a problem worth remembering, updates the matching section in the same PR. -->

## Purpose
Every versioned HTTP endpoint, mounted under `/api/v1`: the public chat API (used by client
frontends through their own server) and the admin API under `/api/v1/admin` (used by the admin web
and scripts). Routes only parse -> call a service on the container -> return a schema. Auth helpers,
the container and schemas live one level up in [`app/api/`](../../README.md); health probes are
unversioned in `app/api/health.py`. Breaking changes go into a new `v2` package, not here.

## Files
| File | Public names | What it does |
|---|---|---|
| `__init__.py` | `api_v1_router`, `API_V1_PREFIX` | Builds the `/api/v1` router from the chat and admin routers. |
| `chat.py` | `router`, `chat_stream`, `chat`, `get_conversation`, `submit_feedback`, `handoff_contact`, `widget_config`, `transcribe` | Public chat API: streamed (SSE) and JSON answers, a visitor's own conversation, feedback, handoff contact, widget config, voice transcription. |

### admin/
Mounted under `/api/v1/admin` by `admin/__init__.py` (`router`, which includes every file below).

| File | Public names | What it does |
|---|---|---|
| `admin/auth.py` | `router`, `login`, `logout`, `me`, `change_password`, `list_users`, `create_user`, `update_user`, `LOGIN_ATTEMPTS_PER_MINUTE` | Sign-in (sets the HttpOnly `admin_session` cookie and returns a Bearer token; 5 attempts/min per IP and per e-mail), sign-out, own account, owner-only account management. |
| `admin/knowledge.py` | `router`, `list_sources`, `create_source`, `update_source`, `delete_source`, `list_documents`, `upload_document`, `create_text_document`, `list_access_tiers`, `review_counts`, `review_document`, `get_document`, `update_document`, `document_citations`, `delete_document`, `export_knowledge`, `import_knowledge`, `add_chunk`, `update_chunk`, `delete_chunk`, `list_chunking_strategies`, `preview_chunking`, `rechunk_document` | Knowledge base under `/knowledge`: sources, documents (upload / typed text), review, citations, export/import bundles, chunk edits, chunking strategies, preview and re-chunk. |
| `admin/conversations.py` | `router`, `list_conversations`, `conversation_detail`, `message_trace`, `list_feedback`, `review_feedback`, `list_handoffs`, `answer_handoff`, `reveal_handoff_contact`, `update_handoff`, `OUTCOME_PATTERN` | Conversation list/detail, per-answer trace, feedback inbox, handoff tickets. |
| `admin/monitoring.py` | `router`, `usage_summary`, `usage_history`, `usage_live`, `logs`, `system_status`, `clear_cache`, `reindex`, `MAX_SUMMARY_DAYS`, `MAX_HISTORY_DAYS` | Usage summary/history, live SSE feed, log search, system status (version from `app.APP_VERSION`), cache clear, index rebuild. |
| `admin/configuration.py` | `router`, `get_settings`, `update_settings`, `get_setting_defaults`, `reset_setting`, `list_api_keys`, `create_api_key`, `rotate_api_key`, `revoke_api_key`, `list_prices`, `set_price`, `delete_price`, `list_tools`, `update_tool` | Runtime settings (applied on the next turn, new models tried first), API keys, model prices, SQL tool switches. |
| `admin/audit.py` | `router`, `list_audit_entries` | Owner-only read of the append-only audit log. |
| `admin/privacy.py` | `router`, `hold_conversation`, `hold_ticket`, `export_subject`, `delete_subject` | Owner-only legal hold and data-subject export/delete; all PUT/POST so the audit middleware records them. |
| `admin/evaluation.py` | `router`, `add_eval_case`, `list_eval_cases`, `export_eval_cases`, `delete_eval_case` | Golden eval set built from real answers; export feeds `scripts/eval/rag.py`. |

### Endpoints
Auth legend. Chat: **caller** = `X-Service-Token` (widget server) or `X-API-Key` with scope `chat`,
plus `X-End-User-Id`, plus an optional host-site `Authorization: Bearer`; **client** = the same
without the visitor header. Admin roles (from `app/api/dependencies.py`): **read** = owner, editor,
viewer, support_agent; **write** = owner, editor; **handoff** = owner, editor, support_agent;
**owner** = owner. `+key:<scope>` = an `X-API-Key` with that scope is also accepted; otherwise the
route is session-only (cookie or Bearer). Services are attributes of `AppContainer`.

| Method | Path | Handler | Auth | Service called |
|---|---|---|---|---|
| POST | `/api/v1/chat/stream` | `chat_stream` | caller | `ChatService.prepare`, `.stream` (SSE) |
| POST | `/api/v1/chat` | `chat` | caller | `ChatService.prepare`, `.answer` |
| GET | `/api/v1/conversations/{conversation_id}` | `get_conversation` | caller | `ConversationService.visitor_conversation` |
| POST | `/api/v1/feedback` | `submit_feedback` | caller | `ConversationService.submit_feedback` |
| POST | `/api/v1/handoffs/{handoff_id}/contact` | `handoff_contact` | caller | `HandoffService.add_contact` |
| GET | `/api/v1/widget/config` | `widget_config` | client | `SettingsService.public_widget_config` |
| POST | `/api/v1/chat/transcribe` | `transcribe` | caller | `TranscriptionService.transcribe` |
| POST | `/api/v1/admin/auth/login` | `login` | none (rate-limited) | `RateLimitService.hit`, `AuthService.authenticate`, `.issue_token` |
| POST | `/api/v1/admin/auth/logout` | `logout` | none | — (clears the cookie) |
| GET | `/api/v1/admin/auth/me` | `me` | read | `AuthService.get_admin` |
| POST | `/api/v1/admin/auth/password` | `change_password` | read | `AuthService.change_password` |
| GET | `/api/v1/admin/users` | `list_users` | owner | `AuthService.list_admins` |
| POST | `/api/v1/admin/users` | `create_user` | owner | `AuthService.create_admin` |
| PATCH | `/api/v1/admin/users/{admin_id}` | `update_user` | owner | `AuthService.update_admin` |
| GET | `/api/v1/admin/knowledge/sources` | `list_sources` | read +key:admin:read | `KnowledgeService.list_sources` |
| POST | `/api/v1/admin/knowledge/sources` | `create_source` | write +key:documents:write | `KnowledgeService.create_source` |
| PATCH | `/api/v1/admin/knowledge/sources/{source_id}` | `update_source` | write +key:documents:write | `KnowledgeService.update_source` |
| DELETE | `/api/v1/admin/knowledge/sources/{source_id}` | `delete_source` | write +key:documents:write | `KnowledgeService.delete_source` |
| GET | `/api/v1/admin/knowledge/documents` | `list_documents` | read +key:admin:read | `KnowledgeService.list_documents` |
| POST | `/api/v1/admin/knowledge/documents/upload` | `upload_document` | write +key:documents:write | `KnowledgeService.upload_file` (202) |
| POST | `/api/v1/admin/knowledge/documents/text` | `create_text_document` | write +key:documents:write | `KnowledgeService.create_text_document` |
| GET | `/api/v1/admin/knowledge/access-tiers` | `list_access_tiers` | read +key:admin:read | `KnowledgeService.access_tiers` |
| GET | `/api/v1/admin/knowledge/review/counts` | `review_counts` | read +key:admin:read | `KnowledgeService.review_counts` |
| POST | `/api/v1/admin/knowledge/documents/{document_id}/review` | `review_document` | write (session only) | `KnowledgeService.review_document` |
| GET | `/api/v1/admin/knowledge/documents/{document_id}` | `get_document` | read +key:admin:read | `KnowledgeService.get_document` |
| PATCH | `/api/v1/admin/knowledge/documents/{document_id}` | `update_document` | write +key:documents:write | `KnowledgeService.update_document` |
| GET | `/api/v1/admin/knowledge/documents/{document_id}/citations` | `document_citations` | read +key:admin:read | `KnowledgeService.answers_citing` |
| DELETE | `/api/v1/admin/knowledge/documents/{document_id}` | `delete_document` | write +key:documents:write | `KnowledgeService.delete_document` |
| GET | `/api/v1/admin/knowledge/export` | `export_knowledge` | read +key:admin:read | `KnowledgeTransferService.export_bundle` |
| POST | `/api/v1/admin/knowledge/import` | `import_knowledge` | write +key:documents:write | `KnowledgeTransferService.import_bundle`, `IndexSyncService.reembed_stale_chunks` |
| POST | `/api/v1/admin/knowledge/documents/{document_id}/chunks` | `add_chunk` | write +key:documents:write | `ChunkEditingService.add_chunk` |
| PATCH | `/api/v1/admin/knowledge/chunks/{chunk_id}` | `update_chunk` | write +key:documents:write | `ChunkEditingService.update_chunk` |
| DELETE | `/api/v1/admin/knowledge/chunks/{chunk_id}` | `delete_chunk` | write +key:documents:write | `ChunkEditingService.delete_chunk` |
| GET | `/api/v1/admin/knowledge/chunking/strategies` | `list_chunking_strategies` | read +key:admin:read | — (`schemas.chunking.strategy_catalog`) |
| POST | `/api/v1/admin/knowledge/documents/{document_id}/chunking/preview` | `preview_chunking` | write +key:documents:write | `ChunkEditingService.preview_chunking` |
| POST | `/api/v1/admin/knowledge/documents/{document_id}/rechunk` | `rechunk_document` | write +key:documents:write | `ChunkEditingService.rechunk` |
| GET | `/api/v1/admin/conversations` | `list_conversations` | read +key:conversations:read | `ConversationService.list_conversations` |
| GET | `/api/v1/admin/conversations/{conversation_id}` | `conversation_detail` | read +key:conversations:read | `ConversationService.conversation_detail` |
| GET | `/api/v1/admin/messages/{message_id}/trace` | `message_trace` | read +key:conversations:read | `ConversationService.message_trace` |
| GET | `/api/v1/admin/feedback` | `list_feedback` | read +key:conversations:read | `ConversationService.list_feedback`, `EvalCaseService.questions_in_set` |
| PATCH | `/api/v1/admin/feedback/{feedback_id}` | `review_feedback` | write | `ConversationService.mark_feedback_reviewed` |
| GET | `/api/v1/admin/handoffs` | `list_handoffs` | read +key:conversations:read | `HandoffService.list` |
| POST | `/api/v1/admin/handoffs/{handoff_id}/answer` | `answer_handoff` | handoff | `HandoffService.answer` |
| POST | `/api/v1/admin/handoffs/{handoff_id}/reveal-contact` | `reveal_handoff_contact` | owner | `HandoffService.reveal_contact` |
| PATCH | `/api/v1/admin/handoffs/{handoff_id}` | `update_handoff` | handoff | `HandoffService.update` |
| GET | `/api/v1/admin/usage/summary` | `usage_summary` | read +key:admin:read | `UsageService.summary` |
| GET | `/api/v1/admin/usage/history` | `usage_history` | read +key:admin:read | `MetricsRollupService.history` |
| GET | `/api/v1/admin/usage/live` | `usage_live` | read +key:admin:read | `LiveFeedService.subscribe` / `.unsubscribe` (SSE) |
| GET | `/api/v1/admin/logs` | `logs` | read +key:admin:read | `LogService.query` |
| GET | `/api/v1/admin/system` | `system_status` | read +key:admin:read | `Database.ping`, `KnowledgeIndex.snapshot`, `IndexSyncService.ingestion_queue`, `ReadinessService.model_server_status`, `SettingsService.all`, pipeline cache stats |
| POST | `/api/v1/admin/system/cache/clear` | `clear_cache` | write | `ChatbotService.cache.clear` |
| POST | `/api/v1/admin/system/reindex` | `reindex` | write | `KnowledgeIndex.refresh` |
| GET | `/api/v1/admin/settings` | `get_settings` | read | `SettingsService.all` |
| PATCH | `/api/v1/admin/settings` | `update_settings` | write (retention: owner) | `SettingsService.check_role`, `.update` (with `AppContainer.check_model`) |
| GET | `/api/v1/admin/settings/defaults` | `get_setting_defaults` | read | `SettingsService.defaults` |
| DELETE | `/api/v1/admin/settings/{key}` | `reset_setting` | write | `SettingsService.check_role`, `.reset` |
| GET | `/api/v1/admin/api-keys` | `list_api_keys` | owner | `AuthService.list_api_keys` |
| POST | `/api/v1/admin/api-keys` | `create_api_key` | owner | `AuthService.create_api_key` |
| POST | `/api/v1/admin/api-keys/{key_id}/rotate` | `rotate_api_key` | owner | `AuthService.rotate_api_key` |
| POST | `/api/v1/admin/api-keys/{key_id}/revoke` | `revoke_api_key` | owner | `AuthService.revoke_api_key` |
| GET | `/api/v1/admin/prices` | `list_prices` | read | `PricingService.list` |
| PUT | `/api/v1/admin/prices/{model:path}` | `set_price` | owner | `PricingService.upsert` |
| DELETE | `/api/v1/admin/prices/{model:path}` | `delete_price` | owner | `PricingService.delete` |
| GET | `/api/v1/admin/tools` | `list_tools` | read | `SqlToolCatalog.list` |
| PATCH | `/api/v1/admin/tools/{name}` | `update_tool` | write | `SqlToolCatalog.set_enabled` |
| GET | `/api/v1/admin/audit` | `list_audit_entries` | owner | `AuditService.list` |
| PUT | `/api/v1/admin/conversations/{conversation_id}/legal-hold` | `hold_conversation` | owner | `PrivacyService.hold_conversation` |
| PUT | `/api/v1/admin/handoffs/{handoff_id}/legal-hold` | `hold_ticket` | owner | `PrivacyService.hold_ticket` |
| POST | `/api/v1/admin/data-subjects/export` | `export_subject` | owner | `PrivacyService.export` |
| POST | `/api/v1/admin/data-subjects/delete` | `delete_subject` | owner | `PrivacyService.delete` |
| POST | `/api/v1/admin/messages/{message_id}/eval-case` | `add_eval_case` | write | `EvalCaseService.create_from_message` |
| GET | `/api/v1/admin/eval-cases` | `list_eval_cases` | read | `EvalCaseService.list` |
| GET | `/api/v1/admin/eval-cases/export` | `export_eval_cases` | read | `EvalCaseService.export` |
| DELETE | `/api/v1/admin/eval-cases/{case_id}` | `delete_eval_case` | write | `EvalCaseService.delete` |

Cookie-authenticated admin writes also need `X-Admin-Request: 1` (CSRF guard in `require_admin`).

## Dependencies
- May import: `app.api` (container, dependencies, schemas, sse), `services`, `core` (constants such
  as access scopes, usage windows), `models`, `config`. Never `middleware` (layering: api -> services
  -> core -> models/utils, config at the bottom; only `main.py` imports middleware; enforced by
  `test/unit/test_layering.py`).
- Used by: `app/main.py` (`include_router(api_v1_router)`); `frontends/widget` (chat routes through its
  server), `frontends/admin` (admin routes), `frontends/streamlit`.
- External: none directly; everything goes through services on the container.

## Run / test
```bash
pytest test/integration/test_api.py                 # chat, auth, roles, CSRF, audit, chunking, settings
pytest test/integration/test_api_keys.py test/integration/test_eval_cases_api.py \
       test/integration/test_privacy_api.py test/integration/test_host_identity_api.py \
       test/integration/test_usage_limits_api.py test/integration/test_document_review.py
```
All need `TEST_DATABASE_URL` (pgvector/pgvector:pg17); they are skipped otherwise. Swagger UI:
`http://localhost:8500/docs` when `APP_ENV` is not production. Reference docs: `docs/API.md`.

## Known problems and history
- Routes lived in `api/routes/` until they moved to `api/v1/routes/` with the backend move
  (lcduc/automatic-octo-computing-machines#76, 0787fab, 2026-11-10).
- Document review is session-only (no API key) so an integration that uploads cannot also approve
  what it uploaded (comment in `admin/knowledge.py`; review workflow 0315318, 2026-10-07).
- Knowledge import embeds inside the request (`# ceiling:` in `admin/knowledge.py`); move to the
  ingestion queue if imports time out (export/import added in 54b76a5, #32).
- Privacy routes are PUT/POST only so the audit middleware records who did it (ADM-02) (baf0dd9,
  2026-09-29).
- `APP_VERSION` duplicated `app/main.py` and now comes from `app/__init__.py`; the `chat.py`
  docstring now names `X-Service-Token` or `X-API-Key`; `docs/openapi.json` regenerated
  (branch `refactor/structure-fixes`, 2026-11-10).
- `test_api.py::test_rate_limit_and_roles` is timing-flaky (per-minute rate-limit window); passes
  on rerun.

## Status
- Last reviewed: 2026-11-10
- Open issues / follow-ups: none.
- Ceilings (`# ceiling:` markers in this folder): `admin/knowledge.py:226` — knowledge import embeds
  inside the request — move to the ingestion queue if imports time out.
