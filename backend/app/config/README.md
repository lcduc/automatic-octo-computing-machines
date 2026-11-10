# `backend/app/config/`

<!-- Keep this README true. Anyone (person or agent) who adds, removes or renames a file here,
     or hits a problem worth remembering, updates the matching section in the same PR. -->

## Purpose
Every environment-driven setting, read through typed helpers and grouped into classes of static
methods (`Config.LLM.ACTIVE_MODEL()`, `Config.Server.PORT()`, ...). Each env var is defined in
exactly one place. Only values that vary by environment belong here; fixed values are module-level
constants in the module that uses them. Settings that admins change live at runtime
(`SettingsService`, stored in PostgreSQL) use these values only as defaults.

## Files
| File | Public names | What it does |
|---|---|---|
| `__init__.py` | `Config` | Re-exports `Config` from `settings.py`. |
| `env.py` | `env_str`, `env_int`, `env_float`, `env_bool`, `env_list` | Typed `os.getenv` readers; a malformed int/float logs a warning and falls back to the default instead of crashing at import. `true/1/yes/on` are truthy. |
| `settings.py` | `Config`, `PathConfig`, `LoggingConfig`, `MIN_JWT_SECRET_LENGTH` | The namespace `Config` (`Paths`, `Database`, `LLM`, `File`, `Server`, `Security`, `RAG`, `Routing`, `Chat`, `OCR`, `Logging`, `Alerts`, `Smtp`, `HostAuth`, `ModelServer`) over the `*_settings.py` groups, plus paths and logging. `Config.problems()` lists unsafe settings; `Config.validate()` creates `LOG_DIR`, raises in production, warns in development. |
| `llm_settings.py` | `LLMConfig`, `STUB_PROVIDER`, `STUB_MODEL` | LLM provider, credentials, models and answer-cache tuning; `stub` is the load-test provider. |
| `knowledge_settings.py` | `FileConfig`, `RAGConfig`, `OCRConfig`, `RoutingConfig` | Upload and chunk limits, retrieval and ranking, OCR and ingestion mode, embedding-router margins. |
| `platform_settings.py` | `DatabaseConfig`, `ServerConfig`, `SecurityConfig`, `ChatConfig` | PostgreSQL connection (`POSTGRES_*`, `DB_POOL_SIZE`, `DATABASE_URL` override), HTTP server and `APP_ENV`, auth secrets / CORS / rate limits / guardrail switches, chat-policy defaults. |
| `identity_settings.py` | `HostAuthConfig` | How host-site visitor tokens are verified: `HOST_AUTH_MODE` = `rs256` (default; JWKS URL or PEM), `hs256` (shared secret, fallback) or `none` (anonymous only); issuer, audience, tiers, TTL, leeway; its own `problems()`. |
| `model_server_settings.py` | `ModelServerConfig` | `MODEL_SERVER_URL`/`TOKEN`/`PORT` (8600) and scheduler slots, queue bound and wait timeouts. URL unset = each process loads its own models. |
| `notification_settings.py` | `AlertConfig`, `SmtpConfig`, `ALERT_CHANNELS`, `SMTP_SECURITY_MODES` | Operator alert channel (`telegram`, `slack`, `smtp`) and SMTP server for alerts and ticket replies; all optional. |
| `tool_settings.py` | `BusinessDbConfig` | Read-only URL, pool size and statement timeout of the client's business database behind the SQL tools; empty URL = no SQL tools. Not part of the `Config` namespace (imported directly). |

Runtime path defaults (`PathConfig`, all relative to the working directory, i.e. `backend/`):
`LOG_DIR=data/logs`, `MODELS_DIR=model_weights`, `UPLOAD_DIR=data/uploads`.

## Dependencies
- May import: stdlib and `python-dotenv` only. Must not import `api`, `services`, `core` or
  `middleware` (config sits at the bottom of api -> services -> core -> models/utils; only `main.py`
  imports middleware; enforced by `test/unit/test_layering.py`).
- Used by: modules across `app/`, `scripts/` and `test/` (mostly `app.config.settings`),
  `migrations/env.py`, and the entry points (`main.py`, `worker.py`, `model_server.py` call `validate()` or
  read `ModelServerConfig`).
- External: environment variables only; `settings.py` calls `load_dotenv()` at import, which finds
  `backend/.env` or, failing that, a repo-root `.env` (python-dotenv walks up from the caller).

## Run / test
```bash
python -c "from app.config.settings import Config; print(Config.problems())"   # what production would refuse
pytest test/unit/test_model_server.py test/unit/test_stub_llm_provider.py
```
`.env.example` in `backend/` is the template for the commonly changed variables.

## Known problems and history
- Production refuses to start with a short `ADMIN_JWT_SECRET`/`BFF_SERVICE_TOKEN`, an empty
  database password, `CORS_ORIGINS=*`, `LLM_PROVIDER=stub` or a missing LLM key; development only
  warns (`Config.problems()` / `validate()`).
- `env.py` and `platform_settings.py` were added with the database layer (83b6817, 2026-09-25);
  identity (9ad3531), notification (17cc4e1), model-server (84da62f) and tool (9c643cf) settings
  followed in their own modules, 2026-09-28/29.
- `OPENAI_BASE_URL` added for OpenAI-compatible servers; with it set the OpenAI key may stay empty
  (lcduc/automatic-octo-computing-machines#63, 56f1039, 2026-10-27).
- `LLM_PROVIDER=stub` (deterministic canned tokens) added for load tests and refused in production
  (af18efb, 2026-10-24).
- ML model cache dir is `model_weights/`, named apart from the `models/` package after a collision
  (139f439, 2026-08-04).
- Backend moved under `backend/app`; config imports became `app.config.*` (#76, 2026-11-10).
- `settings.py` was 616 lines; it was split along the existing `*_settings.py` pattern into
  `llm_settings.py` and `knowledge_settings.py`, and the unused `HealthConfig` was deleted
  (branch `refactor/structure-fixes`, 2026-11-10).

## Status
- Last reviewed: 2026-11-10
- Open issues / follow-ups: none.
- Ceilings (`# ceiling:` markers in this folder): none.
