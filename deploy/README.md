# `deploy/`

<!-- Keep this README true. Anyone (person or agent) who adds, removes or renames a file here,
     or hits a problem worth remembering, updates the matching section in the same PR. -->

## Purpose
Assets for running the stack on one client box: the one-command installer, the public Caddy config, the
PostgreSQL init script, the business-database hand-over files, and the ops CLI (`ops/`, see
[`ops/README.md`](ops/README.md)). The compose files themselves are at the repo root
(`docker-compose.yml`, `docker-compose.override.yml`). VPS / Windows demo deployment is out of scope now
(project handed over); this README describes what the files do, not how to operate a server.

## Files

| File | What it does |
|---|---|
| `__init__.py` | Package marker so the ops CLI runs as `python -m deploy.ops` from a checkout. The ops image copies it too. |
| `install.sh` | POSIX `sh` installer for Ubuntu/Debian (`--tag`, `--answers`, `--dir` default `/opt/chatbot`, `--registry` default `ghcr.io/lcduc`, `--yes`). Installs Docker Engine and, when `nvidia-smi` exists, the NVIDIA Container Toolkit (each after confirmation), writes `/usr/local/bin/chatbot` (runs the `chatbot-ops:<tag>` image with the Docker socket and install dir mounted; `deploy`/`rollback` pick the target tag's image), writes `/etc/cron.d/chatbot` (nightly `chatbot backup --label nightly` at 02:30), then runs `chatbot install`. Rerunning is safe. |
| `Caddyfile` | Public entry point with automatic HTTPS. Chat domain (`PUBLIC_DOMAIN_CHAT`) → `web:3000` (widget; SSE unbuffered, 60 MB bodies). Admin domain (`PUBLIC_DOMAIN_ADMIN`) → `admin:80`, with only `/api/v1/admin/*` proxied to `api:8500`, `/api/chat/*` to the widget server (admin demo chat), every other `/api/*` answered 404, and a strict CSP (`frame-ancestors 'none'`, `frame-src` the chat domain). Mounted by `docker-compose.yml`. |
| `answers.example.toml` | Template for `chatbot install --answers client.toml`: domains, host origin, admin email, OpenAI key, sector, and `[backup]`, `[alert]`, optional `[host_auth]`, `[business_db]`, `[env]` sections. Holds secrets once filled in. Everything not asked is generated. |

### `postgres/`

| File | What it does |
|---|---|
| `10-app-role.sh` | Creates or updates the DML-only role the app connects as (`POSTGRES_APP_USER` / `POSTGRES_APP_PASSWORD`): read/write rows, no schema changes; migrations and backups use the owner role. Runs from `docker-entrypoint-initdb.d` on an empty volume and again on every `chatbot deploy`, so a rotated password is applied. Rejects quotes and backslashes. |

### `business_db/`
The client's own business database, reached read-only by the SQL tools.

| File | What it does |
|---|---|
| `reader_grants.sql` | Hand-over for the client's DBA: a `chatbot_reader` login role (read-only transactions, `statement_timeout` 3 s, `NOBYPASSRLS`), views exposing only needed columns, row-level security on `app.user_id`. Copied into the ops image; `chatbot preflight` checks the role cannot write. |
| `demo_role.sh` | Demo/dev only: creates `chatbot_reader` in the demo business DB (mounted as `10-demo_role.sh` by the `business-db` service, compose profile `demo`). |
| `demo_schema.sql` | Demo/dev only: a tiny `shop` schema (products view, per-user orders behind RLS), mounted as `20-demo_schema.sql`. Idempotent. |
| `demo_tools.json` | Demo SQL tool definitions (e.g. `get_product_price`) loaded with `python -m scripts.manage sync-sql-tools --file deploy/business_db/demo_tools.json`. |

### `ops/`
The stdlib-only ops CLI and its image. See [`ops/README.md`](ops/README.md).

## Dependencies
- Used by: `docker-compose.yml` (mounts `Caddyfile` and `postgres/`), `docker-compose.override.yml` (demo
  `business-db` mounts `business_db/demo_role.sh` and `demo_schema.sql`), `deploy/ops/Dockerfile` (copies
  `__init__.py`, `Caddyfile`, `postgres/`, `business_db/reader_grants.sql`), `.github/workflows/release.yml`
  (builds `chatbot-ops`), `backend/test/integration/test_sql_tools.py` (reads `demo_tools.json` and
  `demo_schema.sql`).
- External: Docker Engine, NVIDIA Container Toolkit, Caddy (Let's Encrypt), PostgreSQL (pgvector image), the
  `ghcr.io/lcduc` registry.

## Run / test
- Local stack with the generated settings (from the repo root):
  `python -m deploy.ops install --dir . --answers deploy/answers.example.toml --skip-deploy`, then
  `docker compose up -d --build`.
- Demo business DB: `docker compose --profile demo up -d business-db`.
- Tests: `python -m pytest deploy/ops/tests` (repo root; CI job `ops`). The business-DB files are exercised by
  `backend/test/integration/test_sql_tools.py` (needs `TEST_DATABASE_URL`).

## Known problems and history
- The ops CLI, production compose with internal networks, the DML-only app role and `install.sh` were added
  on 2026-09-28 (2712c00, 7028f1c, d02af7e and neighbours); the business-database answer, read-only preflight
  and DBA hand-over on 2026-09-29 (2b3af4a).
- The admin domain started serving the admin demo chat (`/api/chat/*`) and the widget preview frame on
  2026-09-30 (5e464aa).
- `deploy/windows/` (`deploy.ps1`, `start-all.ps1`) and `.github/workflows/deploy.yml` drove a self-hosted
  Windows demo server (PRs #33–#40, 2026-10-08); deleted in `lcduc/automatic-octo-computing-machines#73`
  (bc824b4, 2026-11-10) because that deployment is out of scope.
- The ops tests moved from `test/unit/` to `deploy/ops/tests/` with their own CI job in #76 (55daf18).

## Status
- Last reviewed: 2026-11-10
- Open issues / follow-ups: none recorded. `docs/deployment.md` still describes VPS deployment, which is out
  of scope now.
- Ceilings (`# ceiling:` markers in this folder): none.
