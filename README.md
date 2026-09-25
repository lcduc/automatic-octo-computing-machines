# RAG Chatbot

A knowledge-grounded Vietnamese chatbot product:

- **Chat widget** embeddable on any website with one `<script>` tag.
- **Admin web** for the client's staff: knowledge base, conversations, feedback,
  handoffs, live token usage, logs and settings.
- **FastAPI backend**: hybrid retrieval over PostgreSQL + pgvector, grounded answers
  streamed from OpenAI, Anthropic or Gemini.

Everything runs on one VPS with `docker compose up -d` (see
[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)).

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

## Knowledge from multiple sources

- Knowledge is organised into **sources** (`FAQ`, `contracts`, `web_data`, …),
  each with an enabled flag and a retrieval **priority**.
- Documents (uploaded files or typed text) carry free-form **metadata**.
- Staff can edit a document's title, source and metadata, and each chunk's
  text and metadata, in the admin web. Edits are re-embedded and searchable
  immediately, with no full re-index.
- Chat requests may restrict retrieval to given sources.

## Security

- **Browser access:** browsers only reach the Next.js server. Its routes hold
  the chat API key and sign an anonymous visitor cookie, so no secrets are in
  the page. The widget iframe may only be framed by allow-listed sites.
- **API access:** per-frontend API keys (hashed, revocable) and admin accounts
  with owner/editor/viewer roles (JWT).
- **Rate limits:** per visitor and per IP, a daily token budget per visitor,
  and a cap on concurrent generations.
- **CORS:** the backend accepts only listed origins.
- **Headers and TLS:** strict security headers, and automatic HTTPS via Caddy.
- **Production start check:** the API refuses to start with a weak secret, an
  empty database password or CORS set to `*`.

## Repository layout

```text
main.py                 FastAPI wiring (middleware, routers, lifespan)
api/                    routes (v1 public + admin), schemas, dependencies, middleware
services/               use cases: chat, knowledge, ingestion, auth, settings, usage…
core/agent/             LLM providers (usage-reporting), chat pipeline, prompts, tools
core/retrieval/         embeddings, reranker, in-memory knowledge index, retriever
core/guardrails/        PII redactor, input guard
core/storage/           SQLAlchemy tables, repositories, connection pool
core/document_processing/  Docling / OCR parsing
migrations/             Alembic schema migrations
frontends/<client>/       per-client frontend (widget + admin web), consumes the API
app.py                  internal Streamlit demo of the chat API
docs/DEPLOYMENT.md      VPS deployment, embedding, backups, operations
```

## Development

See [docs/DEPLOYMENT.md#local-development](docs/DEPLOYMENT.md#local-development).

```bash
ruff check .
pytest                                  # unit tests; integration tests need TEST_DATABASE_URL
cd frontends/<client> && npm run lint && npx tsc --noEmit && npm run build
```

API documentation: `http://localhost:8500/docs` (disabled when `APP_ENV=production`).
