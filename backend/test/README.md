# `backend/test/`

<!-- Keep this README true. Anyone (person or agent) who adds, removes or renames a file here,
     or hits a problem worth remembering, updates the matching section in the same PR. -->

## Purpose
The backend's pytest suite. `unit/` needs no network, no database and no model weights; `integration/`
runs against a real PostgreSQL + pgvector database with fake models and a fake LLM. Tests for the ops
CLI live in `deploy/ops/tests/`, frontend tests in each frontend, and retrieval/router evaluations in
`backend/scripts/eval/` (not pytest).

## Files
`__init__.py` files make `test`, `test/unit` and `test/integration` packages, so tests can import each
other (`from test.unit.test_chat_pipeline import FakeLLM`, `from .test_api import client`).

### Markers (`backend/pyproject.toml`, `asyncio_mode = "strict"`)
| Marker | Meaning | Files | CI step |
|---|---|---|---|
| `hard_gate` | EVAL-09: must pass 100% before any merge — tier gating, per-user data isolation, retrieval filters | `unit/test_chatbot_action_routing.py`, `unit/test_retrieval_filters.py`, `integration/test_document_lifecycle.py`, `integration/test_sql_tools.py` | `pytest -m hard_gate -v` |
| `red_team` | SEC-01: deterministic prompt-injection set — direct, via documents, via tool results | `unit/test_red_team.py` | `pytest -m red_team -v` |

Marked tests also run in the plain `pytest` step. Async tests need an explicit `@pytest.mark.asyncio`.

### unit/
| File | Covers |
|---|---|
| `test_alert_notifier.py` | `AlertNotifier` delivery to Telegram, Slack or e-mail (mocked transport and mailer). |
| `test_audit_redaction.py` | `redact_secrets`: audit entries never store secrets, at any nesting depth. |
| `test_business_calendar.py` | `BusinessCalendar` support hours, holidays and ticket due times (HND-07, HND-14). |
| `test_chat_pipeline.py` | `ChatbotService` routing, fallbacks, caching and token accounting; defines the fakes other unit tests reuse. |
| `test_chat_turn_recovery.py` | Regressions from the widget: bad query rewrite, replayed error, human request. |
| `test_chatbot_action_routing.py` | `hard_gate`: intent-based routing to the tool-calling agent. |
| `test_chunking_strategies.py` | Chunking strategies split extracted text as the admin chose. |
| `test_current_time_tool.py` | `CurrentTimeTool`, the reference `BaseTool`. |
| `test_embedding_router.py` | `EmbeddingRouter` decisions and how the pipeline acts on them. |
| `test_embeddings.py` | In-process embedding service with a fake model. |
| `test_eval_baseline.py` | `scripts.eval.baseline.EvalBaseline`: the router gate fails on real regressions, passes on noise. |
| `test_eval_compare_configs.py` | `scripts.eval.compare_configs` retrieval config comparison. |
| `test_eval_intent_router.py` | `scripts.eval.intent_router` intent-routing eval harness (fake router). |
| `test_extractors_text.py` | Local fallback extractors return chunks plus the full text kept for re-chunking. |
| `test_folder_readmes.py` | Every module under `app/` and `scripts/` is named in its nearest folder README. |
| `test_guardrails.py` | PII redaction and rule-based input screening. |
| `test_host_identity.py` | `HostIdentityService` token checks with real RSA keys (visitor binding stubbed). |
| `test_intent_router.py` | `IntentRouter`: RAG lookup vs action/tool call. |
| `test_knowledge_bundle.py` | `KnowledgeBundle` rejects import files it must not trust. |
| `test_layering.py` | Import direction api -> services -> core -> models/utils; only `main.py` imports middleware; relative imports are resolved and checked like absolute ones; `fastapi`/`starlette` may not be imported in services, core, models, utils or config. |
| `test_model_server.py` | Model-server app and client with a fake model host, remote embedding/reranker/OCR adapters, the two-lane scheduler, `ReadinessService`. |
| `test_no_answer_filter.py` | The no-answer marker is caught at the start of a stream and never shown. |
| `test_ocr_resource_limits.py` | Parsing/OCR stays within its CPU budget and off the event loop (`IngestionService`). |
| `test_openai_base_url.py` | `OpenAIClientProvider` targets an OpenAI-compatible server via `OPENAI_BASE_URL`. |
| `test_openai_completion_kwargs.py` | Token-limit/temperature kwargs per OpenAI model family. |
| `test_pdf_ocr_routing.py` | PDFs with a usable text layer skip OCR; empty or gibberish ones go to OCR. |
| `test_query_adapter.py` | `compute_query_adapter` fits fp16 embeddings and refuses an adapter worse than none. |
| `test_query_rewriter.py` | `QueryRewriter` condenses follow-ups into standalone queries. |
| `test_red_team.py` | `red_team`: prompt-injection set (SEC-01, OWASP LLM01), no model, no network. |
| `test_reranker.py` | Reranker model loading with fake transformers. |
| `test_retrieval_filters.py` | `hard_gate`: retrieval never returns documents the caller may not see or that are not in force. |
| `test_retriever.py` | Hybrid retrieval over a knowledge snapshot. |
| `test_service_token_auth.py` | `AuthService` recognises internal services by their generated tokens. |
| `test_stub_llm_provider.py` | Load-test stub LLM: fixed tokens, only with `LLM_PROVIDER=stub`, refused in production. |
| `test_synthetic_queries.py` | `scripts.eval` synthetic-query helpers: parsing, filtering, MRR, duplicate-free batches. |
| `test_text_utils.py` | `TextUtils` chat-shorthand expansion (whole words only). |
| `test_threshold_calibrator.py` | `scripts.eval.threshold_calibrator.ThresholdCalibrator`. |
| `test_tool_calling_agent.py` | `ToolCallingAgent` and `ToolRegistry`. |
| `test_transcription.py` | Voice transcription: `OpenAIClientProvider` and `TranscriptionService`. |
| `test_upload_store.py` | `UploadStore` keeps queued upload files on disk. |
| `test_usage_limits.py` | `TimeBuckets` and the usage policy (pure logic). |
| `test_vietnamese_parsing.py` | Vietnamese/English periods and money amounts for SQL tool arguments (TOOL-07). |
| `test_vietnamese_perturber.py` | `scripts.eval.vietnamese_perturber`: telex typos, missing diacritics, abbreviations. |

### integration/
All skip when `TEST_DATABASE_URL` is unset.

| File | Covers |
|---|---|
| `conftest.py` | Fixture `database` (fresh schema + default sources per test), `TEST_DATABASE_URL`, `DEFAULT_SOURCES`, `FakeEmbeddingService` (bag-of-words via `zlib.crc32`), `FakeReranker`, `FakeProcessor` (splits text on blank lines; `.bad` files fail). |
| `test_api.py` | Real FastAPI app via `create_app(FakeContainer)` (an `AppContainer` with fake models/LLM); defines the `client` fixture and helpers (`_admin_headers`, `_approve`, `BFF_TOKEN`) the API tests below import. Includes `test_rate_limit_and_roles`. |
| `test_api_keys.py` | Server-to-server API keys: scopes per endpoint, session-only routes, browser refusal, expiry, rotation, per-key limits, audit attribution. |
| `test_document_lifecycle.py` | `hard_gate`: access tier, validity dates, superseding versions, citing answers, disabled documents never cited. |
| `test_document_review.py` | New documents wait for owner/editor approval before the assistant may answer from them. |
| `test_eval_cases_api.py` | Feedback review and the golden eval set through the admin API (ADM-12, RET-R3). |
| `test_host_identity_api.py` | Logged-in host users: conversation ownership, anonymous -> logged-in upgrade, logout, cross-device access, token replay. |
| `test_knowledge_service.py` | `KnowledgeService`, `ChunkEditingService`, `IndexSyncService`, `IngestionWorker`: CRUD keeps the index in sync, uploads go through the queue. |
| `test_knowledge_transfer.py` | `KnowledgeTransferService`: a knowledge base round-trips without embeddings. |
| `test_observability.py` | Daily rollup, alert rules and the job scheduler. |
| `test_privacy_api.py` | Legal hold and data-subject requests through the admin API (PRV-03, RET-R2, RET-R5). |
| `test_retention.py` | Retention purge (PRV-04, RET-R1/R2/R4). |
| `test_sql_tools.py` | `hard_gate`: SQL tools on the demo shop in a separate `chatbot_business_test` database via a read-only `chatbot_reader` role with RLS; anonymous never reaches a private tool, user A never gets user B's rows. Loads `deploy/business_db/demo_tools.json`. |
| `test_tickets.py` | Async support tickets: triggers, contact with consent, masking, owner-only reveal, answers in chat and by e-mail. |
| `test_usage_limits_api.py` | Durable limits: counters shared across instances, per-IP token budgets, prices and cost per call, spend cap, LISTEN/NOTIFY live feed. |

## Dependencies
- May import: anything under `app` and `scripts.eval` (tests sit outside the layering rule); tests never
  load real model weights or call an LLM.
- Used by: CI job `test` in `.github/workflows/ci.yml`.
- External: integration tests need PostgreSQL 17 with pgvector. The user must be allowed to create
  extensions, databases and roles (`test_sql_tools.py` creates `chatbot_business_test` and
  `chatbot_reader`); the container's `POSTGRES_USER` is a superuser.

## Run / test
From `backend/` with `venv` active (run there so `app` and `scripts` import):
```bash
pytest test/unit                          # fast, no database
pytest -m hard_gate -v                    # merge gates
pytest -m red_team -v                     # prompt-injection set
pytest test/unit/test_layering.py         # one file
ruff check .                              # from the repo root
```
Integration tests locally with a throwaway pgvector container (never point `TEST_DATABASE_URL` at a
database holding real data — the schema is dropped and recreated for every test):
```bash
docker run -d --name pg-test -e POSTGRES_USER=chatbot -e POSTGRES_PASSWORD=chatbot \
  -e POSTGRES_DB=chatbot_test -p 127.0.0.1:55432:5432 pgvector/pgvector:pg17
TEST_DATABASE_URL=postgresql+asyncpg://chatbot:chatbot@127.0.0.1:55432/chatbot_test pytest
#   PowerShell: $env:TEST_DATABASE_URL = "postgresql+asyncpg://chatbot:chatbot@127.0.0.1:55432/chatbot_test"; pytest
docker rm -f pg-test                      # when done
```
The schema comes from `Base.metadata.create_all`, not Alembic; CI checks migrations separately
(`alembic upgrade head && alembic downgrade base && alembic upgrade head`, see `migrations/README.md`).

CI order (job `test`): migrations check -> `pytest -m hard_gate -v` -> `pytest -m red_team -v` ->
`pytest` -> router eval gate (`python -m scripts.eval.router --check`).

## Known problems and history
- `integration/test_api.py::test_rate_limit_and_roles` is timing-flaky: it depends on the per-minute
  rate-limit window and passes on rerun.
- Fake embeddings bucketed words with Python's `hash()`, which is seeded per run, so scores changed
  between runs -> `zlib.crc32` instead, and `FakeContainer` got a `FakeReranker` so `SIMILARITY_THRESHOLD`
  gates as it does with a real reranker -> `lcduc/automatic-octo-computing-machines#24` (1b5a547,
  2026-09-30). The embedding router stays off in `FakeContainer`: bag-of-words vectors cannot route by meaning.
- The prompt-injection red-team set became its own CI step (dbb077f, 2026-09-29); the demo business
  database with RLS and per-tool tests arrived in 2469e45 (2026-09-29).
- `test_layering.py` added (1f8e699) and six loose tests moved from `test/` into `test/unit/` (f433798)
  -> `lcduc/automatic-octo-computing-machines#73` (2026-11-10).
- Backend moved under `backend/`; ops CLI tests moved to `deploy/ops/tests` with their own CI job
  (55daf18); eval scripts moved to `scripts/eval`, so tests import `from scripts.eval import ...` — two
  `from scripts import ...` forms were missed at first and fixed ->
  `lcduc/automatic-octo-computing-machines#76` (2026-11-10).
- `test_layering.py` checked absolute imports only -> it now resolves relative imports and fails on
  a web-framework import below the HTTP layer (branch `refactor/structure-fixes`, 2026-11-10).

## Status
- Last reviewed: 2026-11-10
- Open issues / follow-ups:
  - EVAL-09 SEC-11 impersonation and ADM-01a role tests are not yet `hard_gate`
    (docs/checklists/production.md).
  - TST-06: coverage (83% of `app/` lines on 2026-11-10) is measured only locally, not in CI (docs/checklists/testing.md).
  - TST-10: `integration/test_api.py::test_rate_limit_and_roles` is timing-flaky (see Known problems) (docs/checklists/testing.md).
- Ceilings (`# ceiling:` markers in this folder): none.
