# Deploying on a single VPS

The whole product runs from one command on one machine:

```bash
docker compose up -d --build
```

| Service    | What it is                                              | Exposed            |
|------------|---------------------------------------------------------|--------------------|
| `caddy`    | HTTPS entry point (free Let's Encrypt certificate)      | ports 80/443       |
| `web`      | Next.js: chat widget, `embed.js`, admin web, BFF routes | internal only      |
| `api`      | FastAPI: RAG pipeline, admin API (GPU)                  | internal only      |
| `postgres` | PostgreSQL 17 + pgvector: all data and embeddings       | `127.0.0.1` only   |

The browser only talks to Caddy → `web`. The chat API key lives on the `web`
server, never in the browser. The API and database are unreachable from the
internet.

## Hardware budget (12 GB VRAM, 8 cores / 16 threads, 16 GB RAM)

- **One API worker.** The models, the in-memory knowledge index and the rate-limit
  counters live in that process. Concurrency comes from async I/O:
  - `MAX_CONCURRENT_CHATS` (default 16) caps turns generated at once.
  - `RETRIEVAL_MAX_CONCURRENCY` (default 4) caps GPU retrieval at once.
- **GPU:**
  - Embedding model (~0.5 GB) and reranker (~1.2 GB).
  - The PaddleOCR-VL engine (optional, a few GB) fits alongside them.
- **RAM:**
  - API ~4–6 GB (torch, Docling, OCR).
  - PostgreSQL ~0.5 GB, Next.js ~0.2 GB, Caddy negligible.
  - The knowledge index costs ~1.5 KB per chunk (100k chunks ≈ 150 MB).

## Prerequisites

1. Ubuntu 22.04/24.04 with Docker Engine and the Compose plugin.
2. NVIDIA driver plus the **NVIDIA Container Toolkit**, so the `api` container can
   use the GPU.
   - Without a GPU: delete the `deploy:` block of `api` in `docker-compose.yml`,
     and set `TORCH_INDEX=cpu` in the shell before building.
3. A DNS `A` record, e.g. `chat.example.com`, pointing at the VPS, with ports
   80 and 443 open.

## First deployment

```bash
git clone <repo> chatbot && cd chatbot

# 1. Backend + database settings
cp .env.example .env
#   set: POSTGRES_PASSWORD, ADMIN_JWT_SECRET, OPENAI_API_KEY (or another provider),
#        CHAT_DOMAIN=chat.example.com, CORS_ORIGINS=https://chat.example.com,
#        FRONTEND=<client>   (folder under frontends/)
python3 -c "import secrets; print(secrets.token_hex(32))"   # for ADMIN_JWT_SECRET

# 2. Web settings (the API key comes in step 4)
cp frontends/<client>/.env.example frontends/<client>/.env
#   set: VISITOR_COOKIE_SECRET (openssl rand -hex 32)
#        WIDGET_ALLOWED_PARENTS="https://example.com https://www.example.com"

# 3. Start everything (the first build downloads models; allow ~20-40 minutes)
docker compose up -d --build
docker compose logs -f api        # wait for "Chatbot API ready"

# 4. Create the first admin account and the web frontend's API key
docker compose exec api python -m scripts.manage create-admin --email you@example.com --role owner
docker compose exec api python -m scripts.manage create-api-key --name "client web"
#   put the printed key in frontends/<client>/.env as CHATBOT_API_KEY, then:
docker compose up -d web
```

Open `https://chat.example.com/admin`, sign in, and add knowledge
(**Tri thức** → *Tải tệp lên* / *Soạn nội dung*).

## Embedding the chat on the client site

Add one line before `</body>` on every page that should show the chat:

```html
<script src="https://chat.example.com/embed.js" defer
        data-label="Hỏi đáp" data-color="#0B5FFF" data-position="right"></script>
```

- The site must be listed in `WIDGET_ALLOWED_PARENTS`. Any other site is refused
  by `Content-Security-Policy: frame-ancestors`.
- Title, welcome text, colour and suggested questions are edited in
  **Cấu hình → Giao diện khung chat**. No change to the host site is needed.
- The widget stores only an anonymous, signed visitor cookie (partitioned, so it
  keeps working as browsers phase out third-party cookies).

## Updating

```bash
git pull
docker compose up -d --build        # migrations run automatically when api starts
```

## Backups

All state is in PostgreSQL: knowledge, embeddings, conversations, feedback,
settings and accounts. `data/logs` holds only logs. A nightly dump is enough:

```bash
# crontab -e
0 2 * * * cd /opt/chatbot && docker compose exec -T postgres pg_dump -U chatbot -Fc chatbot > backups/chatbot-$(date +\%F).dump
```

Restore with:

```bash
docker compose exec -T postgres pg_restore -U chatbot -d chatbot --clean < backups/<file>.dump
```

## Operations

| Task                               | Where                                                        |
|------------------------------------|--------------------------------------------------------------|
| Switch *deny* ↔ *handoff* fallback | Admin → Cấu hình → Cách trợ lý ảo trả lời (applies immediately) |
| Answer handed-off visitors         | Admin → Chuyển nhân viên                                      |
| Find knowledge gaps                | Admin → Đánh giá (👎 first), Hội thoại filtered by *Không có thông tin* |
| Token usage / live activity        | Admin → Tổng quan                                             |
| Logs (PII already masked)          | Admin → Nhật ký hệ thống, or `docker compose logs api`        |
| Rotate the web's API key           | Admin → Cấu hình → Khoá API: create new, update `.env`, `docker compose up -d web`, revoke old |
| Change embedding model             | Set `EMBEDDING_MODEL`, restart `api`: stale chunks are re-embedded at start |

## Local development

```bash
docker run -d --name chatbot-pg -e POSTGRES_USER=chatbot -e POSTGRES_PASSWORD=dev \
  -e POSTGRES_DB=chatbot -p 5432:5432 pgvector/pgvector:pg17
python -m venv venv && source venv/bin/activate      # Windows: venv\Scripts\Activate.ps1
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu126
pip install -r requirements.txt
cp .env.example .env    # APP_ENV=development, POSTGRES_HOST=localhost, POSTGRES_PASSWORD=dev
alembic upgrade head
python main.py          # API on :8500, docs on /docs

cd frontends/<client> && npm ci
cp .env.example .env.local && npm run dev   # web on :3000, /embed-demo shows the widget
```

Tests: `pytest` (unit tests need nothing; integration tests need
`TEST_DATABASE_URL` pointing at a throw-away database).
