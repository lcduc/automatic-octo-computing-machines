# RAG Chatbot

A knowledge-grounded chatbot product, Vietnamese-first (it answers in the user's language):

- **Chat widget** embeddable on any website with one `<script>` tag.
- **Admin web** (`frontends/admin`, its own domain) for the client's staff:
  knowledge base with chunking strategies, conversations, feedback, handoffs,
  live token usage, logs, settings (incl. live model and retrieval tuning),
  accounts and an append-only audit log.
- **FastAPI backend**: hybrid retrieval over PostgreSQL + pgvector, grounded answers
  streamed from OpenAI (what the installer sets up), Anthropic or Gemini. Moderation,
  tool calling and voice transcription always use OpenAI, so they need an OpenAI key.

Everything runs on one GPU box. It is installed with `deploy/install.sh` and run with the
`chatbot` ops CLI (see [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)); a plain
`docker compose up -d` refuses to start without the secrets the installer generates.

## How a question is answered

1. **Guardrails** (free, rule-based plus OpenAI's free moderation):
   - Prompt-injection attempts are blocked.
   - Greetings and thanks get canned replies.
   - A request for a human agent triggers a handoff.
   - Personal data (phone, CCCD/CMND, email, card, bank account, tax code) is
     masked before anything is logged, stored or sent to the LLM.
2. **Retrieval:**
   - Follow-ups are rewritten into standalone questions.
   - Hybrid semantic + BM25 search, scaled by each source's priority, then
     cross-encoder reranking.
   - Neighbouring chunks of the same document are added for context.
3. **No relevant knowledge → no LLM call.** Depending on the fallback mode, set
   live in the admin web:
   - `deny`: reply with a configured message.
   - `handoff`: record a transfer-to-human request.
4. **Grounded answer:**
   - Documents go to the model with their source, title and metadata (url,
     effective date, …).
   - The answer streams to the visitor with citations.
   - It is cached, and its tokens are metered per visitor and per day.

## Measured results

Measured on 2026-10-23 at commit `a82183a`, on an RTX 3060 12 GB, with the default models
(`intfloat/multilingual-e5-small`, `BAAI/bge-reranker-v2-m3`) and the demo knowledge base from
`python -m scripts.seed_demo documents` (10 documents, 66 chunks).

**Retrieval:** 81 answerable questions from the three golden sets in `scripts/demo_data/`, ranked by
document, `RETRIEVAL_TOP_K=10`.

| Configuration | Recall@1 | Recall@5 | MRR@10 |
| --- | --- | --- | --- |
| Dense only (`SEMANTIC_WEIGHT=1.0`, no re-ranker) | 70.4% | 96.3% | 0.81 |
| BM25 only (`SEMANTIC_WEIGHT=0.0`, no re-ranker) | 71.6% | 97.5% | 0.82 |
| Dense + BM25 (`SEMANTIC_WEIGHT=0.7`, the default, no re-ranker) | 70.4% | 96.3% | 0.81 |
| Dense + BM25 + cross-encoder re-ranker (the default) | 97.5% | 100% | 0.99 |

The re-ranker carries the gain: at weight 0.7, BM25 fusion changed 1 of 116 rankings. The corpus is
small, so Recall@5 is near its ceiling; telling the fusion settings apart needs a larger benchmark.

**Routing:** 189 labelled Vietnamese messages across 6 routes (`router_eval.json` plus the three
golden sets). Accuracy is 84.7% (macro-F1 0.88), and no real question was taken by a shortcut
(0 of 122). Most misses are off-topic messages passed on to retrieval (28 of 40), which then
refuses most of them. Classification takes 6.2 ms median and 9.3 ms p95 per message (timed
separately; the eval script doesn't time).

**Tests:** all 417 pass with `TEST_DATABASE_URL` pointing at a pgvector Postgres 17; line coverage
is 81% (`pytest-cov` over `api`, `config`, `core`, `services`, `middleware`, `models`, `utils`).

To reproduce, seed a fresh database (settings changed in the admin web override these environment
defaults), then run once per golden set and configuration:

```bash
RETRIEVAL_TOP_K=10 SEMANTIC_WEIGHT=1.0 RERANKING_ENABLED=false python -m scripts.eval_rag --golden-set scripts/demo_data/golden_queries.json --out logs/rag_dense_only.json
python -m scripts.eval_router --golden-set scripts/demo_data/golden_colloquial_dev.json --golden-set scripts/demo_data/golden_colloquial_holdout.json --golden-set scripts/demo_data/golden_queries.json
```

`eval_rag` prints Recall@k at `RETRIEVAL_TOP_K` and MRR; Recall@1 and Recall@5 come from the
per-question `rank` in its `--out` report.

## Knowledge from multiple sources

- Knowledge is organised into **sources** (`FAQ`, `contracts`, `web_data`, …),
  each with an enabled flag and a retrieval **priority**.
- Documents (uploaded files or typed text) carry free-form **metadata**.
- Staff can edit a document's title, source and metadata, and each chunk's
  text and metadata, in the admin web. Edits are re-embedded and searchable
  immediately, with no full re-index.
- Each upload picks a **chunking strategy**: `auto` (per file type), `size`,
  `heading`, `legal_article` (one chunk per Điều, labelled for citation),
  `qa_pair`, `table_rows` or `whole`. The extracted text is kept, so staff can
  preview another strategy and re-chunk a document without uploading it again.
  Uploading with `enabled=false` keeps it out of answers until it is checked.
- Chat requests may restrict retrieval to given sources.

## Security

- **Browser access:** on the chat domain browsers only reach the Next.js server.
  Its routes hold the chat API key and sign an anonymous visitor cookie, so no
  secrets are in the page. The widget iframe may only be framed by allow-listed
  sites. The admin web lives on a separate domain that cannot be framed.
- **API access:** per-frontend API keys (hashed, revocable) and admin accounts
  with owner / editor / support agent / viewer roles. Admin sessions are an
  HttpOnly, SameSite=Strict cookie; cookie-authenticated writes also need an
  `X-Admin-Request` header.
- **Audit log:** every admin write and sign-in attempt is recorded (secrets
  redacted) in an append-only table that PostgreSQL itself refuses to change.
- **Rate limits:** per visitor and per IP, a daily token budget per visitor,
  and a cap on concurrent generations.
- **CORS:** the backend accepts only listed origins.
- **Headers and TLS:** strict security headers, and automatic HTTPS via Caddy.
- **Production start check:** the API refuses to start with a weak secret, an
  empty database password or CORS set to `*`.

## Repository layout

```text
main.py                 FastAPI wiring (middleware, routers, lifespan)
worker.py               ingestion worker: parses/OCRs queued uploads outside the API
api/                    routes (v1 public + admin), schemas, dependencies
middleware/             app-wide ASGI middleware, one class per file (only main.py imports it)
services/               use cases: chat, knowledge, ingestion, auth, settings, usage…
core/agent/             LLM providers (usage-reporting), chat pipeline, prompts, tools
core/retrieval/         embeddings, reranker, in-memory knowledge index, retriever
core/guardrails/        PII redactor, input guard
core/storage/           SQLAlchemy tables, repositories, connection pool
core/document_processing/  Docling / OCR parsing
migrations/             Alembic schema migrations
frontends/widget/         chat widget (Next.js); client deployments customise it on a branch
frontends/admin/          admin web shared by every deployment (Vite + React)
app.py                  internal Streamlit demo of the chat API
docs/DEPLOYMENT.md      VPS deployment, embedding, backups, operations
docs/API.md             API reference (public chat + admin); docs/openapi.json is its schema
docs/PERFORMANCE.md     load test of the chat pipeline (scripts/loadtest/): latency, ceiling, VRAM
```

## Development

See [docs/DEPLOYMENT.md#local-development](docs/DEPLOYMENT.md#local-development).

```bash
ruff check .
pytest                                  # unit tests; integration tests need TEST_DATABASE_URL
cd frontends/widget && npm run lint && npx next typegen && npx tsc --noEmit && npm run build
cd frontends/admin && npm run lint && npm run typecheck && npm test && npm run build
```

API documentation: `http://localhost:8500/docs` (disabled when `APP_ENV=production`).
