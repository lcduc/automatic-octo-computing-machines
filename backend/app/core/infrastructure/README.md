# `backend/app/core/infrastructure/`

<!-- Keep this README true. Anyone (person or agent) who adds, removes or renames a file here,
     or hits a problem worth remembering, updates the matching section in the same PR. -->

## Purpose
Process-level plumbing shared by the three entry points (`app/main.py` API, `app/worker.py`
ingestion worker, `app/model_server.py`): logging setup, the start-up banner, periodic jobs in the
worker, operator alerts and e-mail, and the model-server (its HTTP app, model host, GPU scheduler)
plus the client the API and worker use to call it. Domain logic does not belong here: alert *rules*
live in `services/alert_monitor_service.py`, ticket mail in `services/handoff_service.py`, service
construction and shutdown in `api/container.py`. Pure helpers go to `app/utils/`.

## Files

| File | Public names | What it does |
|---|---|---|
| `logging_setup.py` | `configure_logging`, `json_log_path`, `ContextFilter`, `JsonFormatter` | Called once per process: console handler plus rotating `<LOG_DIR>/app.jsonl` (10 MB x 5) read by the admin log viewer; every record gets the request id and passes PII redaction (when `PII_REDACTION_ENABLED`); quietens noisy libraries. |
| `lifecycle.py` | `StartupBanner` | Renders the operator start-up summary that `main.py` prints once the API is ready. |
| `job_scheduler.py` | `JobScheduler`, `ScheduledJob`, `lock_key` | Worker's periodic jobs (rollup, alert checks, retention purge): ticks every 30 s, runs due jobs one at a time under a PostgreSQL advisory lock per job so replicas never run the same job; failures go to `on_failure` and retry next interval. |
| `alert_notifier.py` | `AlertNotifier`, `AlertDeliveryError` | Sends one short operator alert to Telegram (Bot API), a Slack webhook or e-mail; also used by `scripts/manage.py test-alert`. |
| `smtp_mailer.py` | `SmtpMailer`, `MailDeliveryError` | Plain-text SMTP mail (stdlib `smtplib`) for alerts and handoff ticket replies; `send_async` runs it off the event loop. |
| `model_server_client.py` | `ModelServerClient`, `ModelServerError` | Blocking httpx client (one shared pool) for `/embed`, `/rerank`, `/ocr`, `/ready` with `X-Service-Token`; separate chat and ingestion timeouts. Used when `MODEL_SERVER_URL` is set. |

### `model_server/`
One process that owns the GPU models (embedding, reranker, OCR); entry point `app/model_server.py`.
Reachable only on the internal Docker network (no published port).

| File | Public names | What it does |
|---|---|---|
| `app.py` | `create_model_server_app`, `EmbedRequest`, `EmbedResponse`, `RerankRequest`, `RerankResponse`, `OcrResponse` | FastAPI app: `/health/live` (no token), `/ready`, `/embed`, `/rerank`, `/ocr`; every route but liveness needs `X-Service-Token: MODEL_SERVER_TOKEN`; request size caps; answers 503 with `Retry-After` when the scheduler is full. |
| `model_host.py` | `ModelHost` | Loads the embedding model, reranker and local OCR engine once and keeps them resident (RES-01); `apply_gpu_limits` caps paddle (`FLAGS_gpu_memory_limit_mb`) and torch GPU memory before any model loads; reports VRAM. |
| `scheduler.py` | `PriorityScheduler`, `Lane`, `SchedulerBusyError` | Two-lane scheduling of blocking model calls in threads: chat (query embedding, rerank) starts first; ingestion (passage embedding, OCR) waits while chat waits and is capped at `ingestion_limit`; bounded queues and wait timeouts raise `SchedulerBusyError`. |

### Flow (model-server mode)
```
api / ingestion-worker --ModelServerClient--> model_server/app.py
    -> PriorityScheduler.run(lane, ...) -> ModelHost (embedding | reranker | OCR engine)
```
Callers: `core/retrieval/remote_models.py` (embed, rerank) and
`core/document_processing/remote_ocr_engine.py` (OCR). Without `MODEL_SERVER_URL` the models run
in-process instead.

## Dependencies
- May import: `app.config` (`settings`, `model_server_settings`, `notification_settings`),
  `app.utils.request_context`, and other `core` packages (`core.storage.database`,
  `core.retrieval.embeddings`, `core.document_processing.ocr_base`; `engine_selector`, `get_embedding_service`
  and `core.guardrails.pii_redactor` are imported lazily inside functions). Never `api`, `services` or `middleware` (layering rule api -> services -> core ->
  models/utils, config at the bottom; only main.py imports middleware; enforced by
  `test/unit/test_layering.py`).
- Used by: `app/main.py`, `app/worker.py`, `app/model_server.py`, `api/container.py`,
  `services/alert_monitor_service.py`, `services/handoff_service.py`, `core/retrieval/remote_models.py`,
  `core/document_processing/engine_selector.py`, `core/document_processing/remote_ocr_engine.py`,
  `scripts/manage.py`.
- External: PostgreSQL (advisory locks), Telegram / Slack / SMTP, the model-server over HTTP, GPU
  (torch, paddle) and model weights in the model-server.

## Run / test
From `backend/` with `venv` active.
- Model-server: `python -m app.model_server` (needs `MODEL_SERVER_TOKEN`, else it exits).
- Unit: `pytest test/unit/test_model_server.py test/unit/test_alert_notifier.py`.
- Integration (needs `TEST_DATABASE_URL` to a pgvector database): `pytest test/integration/test_observability.py`
  (covers `JobScheduler` and its advisory lock).
- Lint from repo root: `ruff check .`.

## Known problems and history
- `logging_setup.py` lived in `utils/`, but `utils` must stay pure -> moved here in
  lcduc/automatic-octo-computing-machines#73 (`d2989b8`, 2026-11-10); its relative import
  `from .request_context` broke after the move and became the absolute `app.utils.request_context`.
- One process owns the GPU models with a two-lane scheduler so a big upload never starves chat
  (RES-01, RES-02) -> `model_server/` (`84da62f`, 2026-09-29); api and worker switched to it when
  `MODEL_SERVER_URL` is set (`caa7e10`, 2026-09-29).
- The scheduler queue was unbounded -> bounded per-lane queues with wait timeouts, refused calls answer
  503 with `Retry-After` (`07c6f95`, 2026-10-15).
- Several worker replicas could run the same periodic job -> advisory lock per job name (`54303d9`,
  2026-09-29).
- The shipped image installs the CPU paddle build, so the model-server runs OCR (PP-OCRv6) on the CPU;
  only embedding and reranker use the GPU (`docs/DEPLOYMENT.md`).
- GPU queue and VRAM numbers from `/ready` are shown on the admin overview as a live snapshot only;
  nothing stores or alerts on them (`docs/reports/REPO_ASSESSMENT.md`).
- Logs of the worker and model-server go to their own subfolders of `LOG_DIR`, never the API's rotating
  file (`app/worker.py`, `app/model_server.py`).

## Status
- Last reviewed: 2026-11-10
- Open issues / follow-ups: `model_server/app.py` imports FastAPI although the project layout says
  `core/` has no FastAPI imports (`test_layering.py` checks only `app.*` imports). No load test with an
  OCR job running during chat (RES-03).
- Ceilings (`# ceiling:` markers in this folder): none.
