# `backend/app/`

<!-- Keep this README true. Anyone (person or agent) who adds, removes or renames a file here,
     or hits a problem worth remembering, updates the matching section in the same PR. -->

## Purpose
The one application package. Imports read `from app.<package> ...` and every command runs from
`backend/`. The `.py` files directly here are the three process entry points and contain wiring
only; behaviour lives in the sub-packages. One-off CLIs belong in `backend/scripts/`, never here.

## Files
| File | Public names | What it does |
|---|---|---|
| `main.py` | `create_app`, `main`, `app`, `APP_VERSION`, `CORS_ALLOWED_HEADERS`, `CORS_ALLOWED_METHODS` | API process. `create_app(container_factory)` builds the FastAPI app: error handlers, middleware, health router, `/api/v1` router, and a lifespan that starts/stops `AppContainer` and prints the startup banner. `main()` runs Uvicorn with one worker. |
| `worker.py` | `build_scheduler`, `run_worker`, `main` | Ingestion worker process: parses/OCRs/embeds queued uploads (`IngestionWorker`) and runs the scheduled jobs `metrics_rollup` (hourly), `alert_checks` (5 min) and `retention_purge` (daily) through `JobScheduler`. Stops on SIGTERM/SIGINT and hands its current upload back. |
| `model_server.py` | `main` | Model-server process: the one process that holds the GPU models (embedding, reranker, OCR) and serves them to the API and the worker through a `PriorityScheduler`. Refuses to start without `MODEL_SERVER_TOKEN`. |

How each starts (from `backend/`):

| Command | Starts | Notes |
|---|---|---|
| `python -m app.main [--host H] [--port P]` | Uvicorn on `Config.Server.HOST/PORT` (default `:8500`) | `workers=1` on purpose: models, the knowledge index and in-process state live in memory. `DEBUG` on -> reload with the `"app.main:app"` import string; off -> the app object. HTTPS when `./SSL/fullchain.pem` + `./SSL/privkey_converted.pem` exist. |
| `python -m app.worker` | Worker loop + job scheduler | Set `INGESTION_WORKER=external` on the API so it does not also parse uploads. Logs to `data/logs/worker/`. DB pool of `WORKER_DB_POOL_SIZE = 6`. |
| `python -m app.model_server` | Uvicorn on `0.0.0.0:MODEL_SERVER_PORT` (8600) | Clients set `MODEL_SERVER_URL` + the same `MODEL_SERVER_TOKEN`. Logs to `data/logs/model-server/`. |

Startup order inside `main.py` matters: `load_dotenv()` first, then the Windows asyncio/Uvicorn
fixes before any event loop exists, then `configure_logging()` and `Config.validate()` at import.
Middleware is added innermost-first, so the runtime order (outermost first) is CORS, request
context, security headers, body size limit, per-IP rate limit, admin audit.

### Package map
| Package | One line |
|---|---|
| [api/](api/README.md) | Service container, auth dependencies, error mapping, SSE framing, health probes and the HTTP schemas. |
| [api/v1/routes/](api/v1/routes/README.md) | Versioned endpoints under `/api/v1`: public chat and `/admin`. |
| [config/](config/README.md) | Typed environment settings grouped under `Config`; validated at start-up. |
| [core/agent/](core/agent/README.md) | LLM providers, chat routing (`ChatbotService`), knowledge answers, prompts, tool calling. |
| [core/document_processing/](core/document_processing/README.md) | Docling / OCR parsing and chunking strategies. |
| [core/guardrails/](core/guardrails/README.md) | PII redaction, input guard, sensitive-topic matching. |
| [core/infrastructure/](core/infrastructure/README.md) | Logging setup, startup banner, alerts, job scheduler, SMTP, model server. |
| [core/retrieval/](core/retrieval/README.md) | Embeddings, reranker, in-memory knowledge index, hybrid retriever. |
| [core/routing/](core/routing/README.md) | Embedding router over `routes.json` examples. |
| [core/storage/](core/storage/README.md) | SQLAlchemy tables, connection pool, repositories, upload store. |
| [middleware/](middleware/README.md) | App-wide ASGI middleware; only `main.py` imports it. |
| [models/](models/README.md) | Internal domain data classes (never returned straight from a route). |
| [services/](services/README.md) | Use-case orchestration between `api/` and `core/`. |
| [utils/](utils/README.md) | Pure, stateless helpers. |

## Dependencies
- May import: everything. The entry points are the composition roots; `main.py` is the only module
  allowed to import `middleware` (layering: api -> services -> core -> models/utils, config at the
  bottom; enforced by `test/unit/test_layering.py`).
- Used by: Uvicorn / Docker (`start.sh` runs `python -m app.main`; compose runs `app.worker` and
  `app.model_server`); `test/integration` imports `create_app`; `scripts/export_openapi.py` imports
  `create_app` to dump the schema.
- External: PostgreSQL (API and worker), model weights or the model server, the LLM API.

## Run / test
```bash
python -m app.main
python -m app.worker
python -m app.model_server
pytest test/integration/test_api.py   # builds create_app() with a test container; needs TEST_DATABASE_URL
pytest test/unit/test_model_server.py
```

## Known problems and history
- Backend moved from the repo root into `backend/app` (647 import lines rewritten to `app.*`)
  (lcduc/automatic-octo-computing-machines#76, 06f0477, 2026-11-10).
- `logging_setup` moved from `utils/` to `core/infrastructure/logging_setup.py` because `utils` must
  stay pure; its relative `from .request_context` import broke and became absolute (#73, d2989b8).
- Ingestion moved out of the API into `worker.py` so Docling/OCR get their own CPU/memory limits and
  a parse crash cannot take the API down (b13904d, 2026-09-28).
- GPU models moved into `model_server.py` with a two-lane (chat / ingestion) scheduler (84da62f,
  2026-09-29); the scheduler queue got a bound and wait timeouts (07c6f95, 2026-10-15).
- `main()` re-imports `app.main:app` only when reload is on (5709055, 2026-08-04).
- `main.py` prints the startup banner with `print()` on purpose (operator-facing console output).

## Status
- Last reviewed: 2026-11-10
- Open issues / follow-ups: the module docstrings of `worker.py` and `model_server.py` still show
  `python worker.py` / `python model_server.py`; since #76 the commands are `python -m app.worker` and
  `python -m app.model_server`. `APP_VERSION = "3.0.0"` is also defined in
  `api/v1/routes/admin/monitoring.py`; keep the two in sync.
- Ceilings (`# ceiling:` markers in this folder): none.
