# `backend/`

<!-- Keep this README true. Anyone (person or agent) who adds, removes or renames a file here,
     or hits a problem worth remembering, updates the matching section in the same PR. -->

## Purpose
The deployable backend component: one Python package (`app`) that serves the HTTP API, plus the
ingestion worker and the model server, all built from one Docker image. It owns its own venv,
requirements, Dockerfile, Alembic migrations and `.env.example`. Frontends (`frontends/widget`,
`frontends/admin`, `frontends/streamlit`) live outside this folder and talk to it over HTTP only;
compose files and the ops CLI live at the repo root and in `deploy/`.

## Files
| File | Public names | What it does |
|---|---|---|
| `Dockerfile` | — | Two-stage `python:3.11-slim` image: installs torch (`TORCH_INDEX`, default `cu126`), `paddlepaddle==3.2.0` from PyPI, then `requirements.txt`; bakes model weights with `python -m scripts.download_models`; runs as user `app`, `WORKDIR /app`, exposes 8500, healthcheck on `/health/ready`, `CMD ["start.sh"]`. |
| `start.sh` | — | Container entrypoint: runs `alembic upgrade head` unless `MIGRATE_ON_START=false` (compose sets it; the `migrate` service migrates as schema owner), then `exec python -m app.main`. |
| `requirements-torch.txt` | — | `torch` + `torchvision` pins, kept apart because each machine needs its own wheel index; install first. Bumped by hand (Dependabot ignores them). |
| `requirements.txt` | — | Every other pinned dependency: FastAPI/Uvicorn, SQLAlchemy async + asyncpg + Alembic + pgvector, PyJWT, LLM SDKs (openai, anthropic, google-genai), sentence-transformers, Docling, PaddleOCR, pytest. |
| `pyproject.toml` | — | Tool config only (no build system): pytest `testpaths = ["test"]`, `asyncio_mode = "strict"`, markers `hard_gate` and `red_team`. Lint config is the repo-root `ruff.toml`. |
| `alembic.ini` | — | Alembic config: `script_location = migrations`, dated revision file names. The DB URL is read by `migrations/env.py` from `POSTGRES_*`, not stored here. |
| `.env.example` | — | Template for `backend/.env`: `APP_ENV`, public domains, `POSTGRES_PASSWORD`, `ADMIN_JWT_SECRET`, `BFF_SERVICE_TOKEN`, `LLM_PROVIDER` + provider keys/models, embedding/reranker models, retrieval and router thresholds, OCR switches. |
| `.dockerignore` | — | Keeps venvs, `.env`, logs, model weights, `frontends/`, `deploy/`, `*.md` and `test_*` files out of the image. |

Runtime folders (gitignored, created on first run): `data/` (logs in `data/logs`, uploads in
`data/uploads`) and `model_weights/` (Hugging Face / OCR model cache).

### Folder map
| Folder | README | Responsibility |
|---|---|---|
| `app/` | [app/README.md](app/README.md) | The application package and its three entry points. |
| `app/api/` | [app/api/README.md](app/api/README.md) | Service container, auth dependencies, error mapping, SSE, health probes, HTTP schemas. |
| `app/api/v1/routes/` | [app/api/v1/routes/README.md](app/api/v1/routes/README.md) | Versioned endpoints: public chat and admin. |
| `app/config/` | [app/config/README.md](app/config/README.md) | Typed environment settings, grouped under `Config`. |
| `app/core/agent/` | [app/core/agent/README.md](app/core/agent/README.md) | LLM providers, chat routing, knowledge answers, prompts, tools. |
| `app/core/document_processing/` | [app/core/document_processing/README.md](app/core/document_processing/README.md) | Docling / OCR parsing and chunking strategies. |
| `app/core/guardrails/` | [app/core/guardrails/README.md](app/core/guardrails/README.md) | PII redaction and input screening. |
| `app/core/infrastructure/` | [app/core/infrastructure/README.md](app/core/infrastructure/README.md) | Logging, lifecycle, alerts, job scheduler, model server. |
| `app/core/retrieval/` | [app/core/retrieval/README.md](app/core/retrieval/README.md) | Embeddings, reranker, in-memory knowledge index, hybrid retriever. |
| `app/core/routing/` | [app/core/routing/README.md](app/core/routing/README.md) | Embedding router (small talk / human / off-topic / clarify). |
| `app/core/storage/` | [app/core/storage/README.md](app/core/storage/README.md) | SQLAlchemy tables, connection pool, repositories, upload store. |
| `app/middleware/` | [app/middleware/README.md](app/middleware/README.md) | App-wide ASGI middleware (only `main.py` imports it). |
| `app/models/` | [app/models/README.md](app/models/README.md) | Internal domain data classes. |
| `app/services/` | [app/services/README.md](app/services/README.md) | Use cases between `api/` and `core/`. |
| `app/utils/` | [app/utils/README.md](app/utils/README.md) | Pure, stateless helpers. |
| `migrations/` | [migrations/README.md](migrations/README.md) | Alembic schema migrations. |
| `scripts/` | [scripts/README.md](scripts/README.md) | One-off CLIs: setup, model download, admin management, demo data. |
| `scripts/eval/` | [scripts/eval/README.md](scripts/eval/README.md) | Retrieval, routing and robustness evaluations. |
| `test/` | [test/README.md](test/README.md) | Unit and integration tests. |

## Dependencies
- Layering inside `app`: `api -> services -> core -> models/utils`, with `config` at the bottom;
  only `main.py` imports `middleware`; only `api` and `middleware` import `fastapi`/`starlette`.
  Enforced by `test/unit/test_layering.py` (AST walk over every import, lazy and relative ones
  included).
- `scripts/` may import `app`; `app` never imports `scripts`.
- External services: PostgreSQL 17 + pgvector, one LLM API (OpenAI, Anthropic or Gemini, or an
  OpenAI-compatible server via `OPENAI_BASE_URL`), Hugging Face model downloads, optional SMTP and
  alert channel, optional client business database for the SQL tools.
- Heavy deps: torch, sentence-transformers, Docling, PaddleOCR/paddlepaddle.

## Run / test
Everything runs from `backend/` (runtime paths are relative to the working directory).

```bash
# Setup (Python 3.11, venv named venv)
python -m venv venv && source venv/bin/activate          # Windows: venv\Scripts\Activate.ps1
pip install -r requirements-torch.txt --index-url https://download.pytorch.org/whl/cu126   # no GPU: .../whl/cpu
pip install -r requirements.txt
cp .env.example .env                                      # then fill the secrets and LLM key
python -m scripts.download_models                         # optional: pre-fetch embedding/reranker/OCR weights

# Database: pgvector/pgvector:pg17 container, then
alembic upgrade head
python -m scripts.manage create-admin --email you@example.com --role owner   # once

# Processes
python -m app.main                # API on :8500 (Swagger at /docs unless APP_ENV=production)
python -m app.worker              # ingestion worker + scheduled jobs (with INGESTION_WORKER=external)
python -m app.model_server        # model server on :8600 (with MODEL_SERVER_URL + MODEL_SERVER_TOKEN)

# Docker (context = backend/): the chatbot-api image shared by compose's migrate, api, ingestion-worker, model-server
docker build -t chatbot-api .                          # no NVIDIA GPU: --build-arg TORCH_INDEX=cpu

# Tests and lint
pytest                            # integration tests skip unless TEST_DATABASE_URL is set
cd .. && ruff check .             # lint from the repo root (root ruff.toml)
```

- Runtime paths: `LOG_DIR=data/logs`, `UPLOAD_DIR=data/uploads`, `MODELS_DIR=model_weights`
  (defaults in `app/config/settings.py`). Native runs keep them under `backend/`; in Docker
  `WORKDIR /app` is the backend root and compose mounts the repo-root `data/` at `/app/data`.
- `.env`: `load_dotenv()` uses python-dotenv's `find_dotenv`, which walks up from the calling file,
  so `backend/.env` is found first and a repo-root `.env` is still found when there is none.
- Integration tests need `TEST_DATABASE_URL` pointing at a pgvector database
  (`pgvector/pgvector:pg17`); the schema is dropped and recreated.

## Known problems and history
- Backend lived at the repo root until Nov 2026 -> moved under `backend/app`, 647 import lines
  rewritten to `app.*`, routes moved to `api/v1/routes`, eval scripts to `scripts/eval`, Streamlit
  demo to `frontends/streamlit` (lcduc/automatic-octo-computing-machines#76, 2026-11-10).
- `../data` paths deliberately left out of `.env.example`: compose's `env_file: .env` would push
  them into the containers (#76).
- Paddle's own index (paddlepaddle.org.cn) returned 502 and failed every Docker build -> the CPU
  wheel `paddlepaddle==3.2.0` now comes from PyPI; the GPU build is only on Paddle's index
  (commented line in `Dockerfile`) (#83, 2026-11-10).
- paddlepaddle 3.3.x oneDNN/PIR CPU executor breaks text detection (PaddlePaddle/Paddle#77340) ->
  pinned to 3.2.0; re-verify before bumping (`Dockerfile` comment).
- torch/torchvision moved to their own pinned `requirements-torch.txt` (e4a63de, #47, 2026-10-21).
- ML model cache dir renamed to `model_weights/` to stop colliding with the `models/` package
  (139f439, 2026-08-04).
- On Windows, scripts that print Vietnamese crash with `UnicodeEncodeError` (cp1252) when output is
  redirected -> run with `PYTHONIOENCODING=utf-8`.
- `test/integration/test_api.py::test_rate_limit_and_roles` is timing-flaky (per-minute rate-limit
  window); passes on rerun.
- pip-audit (advisory CI job) failed for weeks: pypdf 6.21.2 CVEs, and Pillow 12 CVEs that docling and
  streamlit blocked with `pillow<13` -> pypdf 6.21.4, docling 2.148 and streamlit 1.67 lift the cap; Pillow
  is pinned to 13.0.0, uvicorn to 0.54 (with `ws=none`) and the audit runs with no ignores
  (Dependabot #77–#81; Pillow pin and audit cleanup on branch `chore/pillow-13-audit`, 2026-11-10).
- `.dockerignore` excluded `tests/` and `test_*`, which match only at the context root, so the whole
  `test/` suite shipped in the image; and it excluded only some `data/` subfolders, so a local
  `docker build backend` copied `data/logs/` (and anything else a local run wrote) into the image ->
  it now excludes `test/` and all of `data/` (the Dockerfile recreates the directories), checked by
  `test/unit/test_dockerignore.py` (PRIV-01, OPT-09, 2026-11-11). CI and release builds were never
  affected: they start from a clean checkout. `*.md` is excluded, so READMEs are not in the image.

## Status
- Last reviewed: 2026-11-11
- Open issues / follow-ups:
  - APPSEC-14: the `Dockerfile` copies the app with `--chown=app:app`, so the API process can rewrite its own code (docs/checklists/security.md).
  - SUP-13: the `python:3.11-slim` base image is a floating tag, not a digest (docs/checklists/ci-supply-chain.md).
- Ceilings (`# ceiling:` markers in this folder): none in the files directly here; see each package README.
