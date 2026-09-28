# Deploying on a client box

Each client runs the whole product on its own VPS/VM (one GPU box, §0 of the
production checklist), from tagged images, installed with one command. Nothing
on the box is configured by hand: every secret is generated, every connection
between our components is authenticated automatically, and the install checks
itself before it counts as done.

```bash
curl -fsSL https://raw.githubusercontent.com/lcduc/automatic-octo-computing-machine/v1.0.0/deploy/install.sh \
  | sudo sh -s -- --tag v1.0.0 --answers /root/client.toml
```

Without `--answers` it asks six questions on the terminal, plus the OpenAI key.

| Service            | What it is                                              | Networks                |
|--------------------|---------------------------------------------------------|-------------------------|
| `caddy`            | HTTPS entry point (automatic Let's Encrypt), ports 80/443 | edge                  |
| `web`              | Next.js: chat widget, `embed.js`, BFF routes            | edge                    |
| `admin`            | Admin web (static SPA), served on the admin domain      | edge                    |
| `api`              | FastAPI: RAG pipeline, admin API (GPU)                  | edge, internal          |
| `ingestion-worker` | Parses, OCRs and embeds uploaded files (same image)     | internal, egress        |
| `migrate`          | One-shot `alembic upgrade head` as the schema owner     | internal                |
| `postgres`         | PostgreSQL 17 + pgvector: all data and embeddings       | internal only, no port  |

`internal` is a Docker network with no route to the internet. Only Caddy
publishes ports. On the chat domain Caddy proxies to `web`; on the admin domain
it serves the admin web and proxies only `/api/v1/admin/*` to the API, and
answers 404 for every other `/api/*` path.

## What the installer does

`install.sh` (run as root) installs only what containers cannot bring
themselves: Docker Engine and, when an NVIDIA driver is present, the NVIDIA
Container Toolkit, each after confirmation (`--yes` skips the questions). It
writes `/usr/local/bin/chatbot` (the ops CLI, run from the `chatbot-ops` image of
the installed release) and `/etc/cron.d/chatbot` (nightly backup), then runs
`chatbot install`:

1. Copies the release's `docker-compose.yml` and `deploy/` assets to `/opt/chatbot`.
2. Takes the answers and writes `/opt/chatbot/.env` (app settings, 0600) and
   `/opt/chatbot/ops.env` (backup credentials, never mounted into an app container).
3. Generates every missing secret: database passwords (the schema owner's goes to
   `secrets/postgres_owner_password`, directory 0700), the admin session secret,
   the visitor cookie secret and the widget server's service token. A rerun keeps
   them.
4. Pulls the images and runs `chatbot preflight`: GPU visible to containers with
   enough free VRAM, RAM, disk, DNS for both domains, a test write to the backup
   target, and a test alert sent by the backend itself.
5. Deploys the tag and creates the first owner with a one-time password, printed once.
6. Runs the security self-check (`chatbot preflight --after-deploy`): only Caddy
   publishes ports and only 80/443; the database is on the internal network only;
   both domains serve valid certificates, HSTS and the right framing rules; the
   public API is not reachable from outside; no secret is missing or an example value.

The installation is done only when both checks pass. Finish with a port scan
from another host (`nmap -Pn chat.example.com` should show only 80 and 443).

### The answers

`deploy/answers.example.toml` documents every key. Keep one file per client
with the client's credentials; `install.sh --answers` makes a reinstall one command.

| Answer          | Example                              | Used for                                        |
|-----------------|--------------------------------------|-------------------------------------------------|
| `chat_domain`   | `chat.client.vn`                     | the widget, `embed.js`                          |
| `admin_domain`  | `admin.client.vn`                    | the admin web (never the chat domain)           |
| `host_origin`   | `https://www.client.vn`              | the only sites allowed to frame the widget      |
| `admin_email`   | `ops@client.vn`                      | the first owner account                         |
| `[backup]`      | `s3://bucket/prefix`, `sftp://…`, `/mnt/backups` | nightly and pre-migration backups   |
| `[alert]`       | `telegram`, `slack` or `smtp`        | operator alerts                                 |
| `openai_api_key`| `sk-…`                               | the LLM provider (a third-party secret)         |

Both domains need DNS records pointing at the box, and ports 80/443 open.

## Staging and releases

Client boxes run production only. Releases are tested on the vendor-side
staging environment, which uses the same compose file and image tags with its own
database, keys and a test host page (a `host_origin` of `http://localhost:8080`
is accepted there). A git tag `v*` makes `.github/workflows/release.yml` publish
`chatbot-api`, `chatbot-web`, `chatbot-admin` and `chatbot-ops` under that tag to
GHCR; the same images are then deployed to each client box.

## Operating a box

| Task                                   | Command                                                            |
|----------------------------------------|--------------------------------------------------------------------|
| Upgrade to a release                   | `chatbot deploy v1.1.0`                                            |
| Undo the last upgrade                  | `chatbot rollback` (or `chatbot rollback v1.0.0`)                  |
| Back up now / list backups             | `chatbot backup` / `chatbot backups`                               |
| Restore (the newest by default)        | `chatbot restore [NAME]` — prints the time taken (the RTO)          |
| Re-check the box                       | `chatbot preflight` and `chatbot preflight --after-deploy`         |
| Change an answer (domain, alerts, …)   | `chatbot install` again; existing values are the defaults          |
| Rotate the generated secrets           | `chatbot rotate-secrets` (admins sign in again)                    |
| Service logs                           | `docker compose -p chatbot logs -f api` in `/opt/chatbot`          |
| Ops log (with tracebacks)              | `/opt/chatbot/logs/ops.log`                                        |

`deploy` pulls the tag's images, backs up the database, makes sure the
application's database role exists with its current password, starts the stack
(`migrate` runs before the API) and waits until every service is healthy. A
failed deploy prints the `rollback` and `restore` commands to recover.
Migrations are not reverted by `rollback`; restore the pre-deploy backup it
names when the failed release already changed the schema.

The API connects as `chatbot_app`, which may read and write rows but not change
the schema; migrations and backups use the owner role. Container logs are
capped at 5 × 10 MB per service.

## Backups

A backup is a PostgreSQL dump (knowledge, embeddings, conversations, feedback,
settings, accounts) plus the original uploaded files (kept until their document
is deleted), shipped with rclone to the backup target and kept for `keep_days`.
The nightly cron entry runs `chatbot backup --label nightly`; `deploy` backs up
before every migration. The latest three backups also stay in
`/opt/chatbot/backups`.

`chatbot restore` stops the writers (web, api, worker), restores the dump in one
transaction (a failed restore leaves the database as it was), replaces the uploads
and restarts the stack.

Rebuilding a lost box: install the same release on a fresh VM with the same
answers file, then `chatbot restore`. Secrets are regenerated on the new box, so
admins sign in again and anonymous visitors start a new history.

## Hardware budget (12 GB VRAM, 8 cores / 16 threads, 16 GB RAM)

- **One API worker.** The models and the in-memory knowledge index live in that
  process. Concurrency comes from async I/O:
  - `MAX_CONCURRENT_CHATS` (default 16) caps turns generated at once.
  - `RETRIEVAL_MAX_CONCURRENCY` (default 4) caps GPU retrieval at once.
- **Memory limits** (compose, overridable in `.env`): postgres 3 GB, api 4 GB,
  worker 5 GB (and 3 CPUs), web 384 MB, caddy 256 MB, admin 128 MB.
- **CPU:** parsing/OCR in the worker uses `OCR_CPU_THREADS` (2) of its `WORKER_CPUS` (3).
- **GPU:** embedding model and reranker in `api`; the worker loads its own copy of
  the embedding model plus the OCR engine.

## Embedding the chat on the client site

Add one line before `</body>` on every page that should show the chat:

```html
<script src="https://chat.example.com/embed.js" defer
        data-label="Hỏi đáp" data-color="#0B5FFF" data-position="right"></script>
```

Only the `host_origin` sites may frame it (`Content-Security-Policy:
frame-ancestors`). Title, welcome text, colour and suggested questions are edited
in **Cấu hình → Giao diện khung chat**. The widget stores only an anonymous,
signed visitor cookie (partitioned, so it keeps working as browsers phase out
third-party cookies).

## Signed-in users of the host site

With `host_auth.mode = "rs256"` (the default) the installer generates a signing
key pair: the public key stays on the box (`secrets/host_jwt_public.pem`, read by
the API) and the private key is written only to `handover/host-integration.zip`,
together with ready-to-use token snippets for Node, PHP and Python, the host page
wiring and a README (all pre-filled with this box's issuer, audience and domains).
Give the zip to the host site's developers, then delete it from the box.

The host backend mints a 10-minute token for its signed-in user; the host page
hands it to `embed.js`, the widget keeps it in memory and sends it with every call,
and the API verifies it (`HOST_AUTH_MODE`, `iss`, `aud`, `exp`, lifetime ≤ 15 min,
`tier`). A token is bound to the browser that first used it. A conversation that
a signed-in user took part in is theirs alone from then on; after logout the
browser no longer sees it. `mode = "hs256"` shares a generated secret instead
(a startup warning reminds you to move to rs256); `mode = "none"` keeps every
visitor anonymous.

## Client deployments

`main` carries a generic chat widget in `frontends/widget`. For a client, branch off `main`
(e.g. `client/<name>`), customise `frontends/widget` there (look, texts, extra pages), and release
that branch's images with a client-specific tag. Backend and admin changes land on `main` and are
merged into the client branches, so a client branch differs only in the widget.

## Everyday admin tasks

| Task                                 | Where                                                                                            |
|--------------------------------------|--------------------------------------------------------------------------------------------------|
| Switch *deny* ↔ *handoff* fallback   | Admin → Cấu hình → Cách trả lời (applies immediately)                                            |
| Change chat model / retrieval tuning | Admin → Cấu hình → Mô hình & truy xuất (tested before saving; *Về mặc định* restores `.env`)     |
| See who changed what                 | Admin → Nhật ký thao tác (owners; append-only)                                                   |
| Answer handed-off visitors           | Admin → Chuyển nhân viên                                                                         |
| Find knowledge gaps                  | Admin → Đánh giá (👎 first), Hội thoại filtered by *Không có thông tin*                          |
| Token usage / live activity          | Admin → Tổng quan                                                                                |
| Server-to-server API keys            | Admin → Tài khoản & khoá API                                                                     |

## Local development

```bash
docker run -d --name chatbot-pg -e POSTGRES_USER=chatbot -e POSTGRES_PASSWORD=dev \
  -e POSTGRES_DB=chatbot -p 5432:5432 pgvector/pgvector:pg17
python -m venv venv && source venv/bin/activate      # Windows: venv\Scripts\Activate.ps1
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu126
pip install -r requirements.txt
cp .env.example .env    # APP_ENV=development, POSTGRES_PASSWORD=dev (host defaults to localhost)
alembic upgrade head
python main.py          # API on :8500, docs on /docs; parses uploads in-process
                        # (INGESTION_WORKER=embedded). To mirror production, set
                        # INGESTION_WORKER=external and also run: python worker.py

cd frontends/widget && npm ci
cp .env.example .env.local && npm run dev   # web on :3000, /embed-demo shows the widget
```

The whole stack from this checkout, with images built locally
(`docker-compose.override.yml` is merged automatically here and never shipped).
The installer writes `.env`, `ops.env` and `secrets/` into the checkout, so move
a native-development `.env` aside first:

```bash
python -m deploy.ops --dir . install --answers my-answers.toml --skip-deploy
docker compose up -d --build
```

Tests: `pytest` (unit tests need nothing; integration tests need
`TEST_DATABASE_URL` pointing at a throw-away database). The ops CLI's tests use
a fake Docker, so they run anywhere.
