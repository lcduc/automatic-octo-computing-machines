# Optimization checklist

Where time, memory and size go, measured before changed. Runtime numbers come from
[performance.md](../performance.md); `CLAUDE.md` §5 forbids optimizing without a measurement that
justifies it, so every open item names what it would improve.

Last assessed: 2026-11-10 at `2c55f4e`.

## Chat path (runtime)

- [x] OPT-01 Throughput and bottleneck measured — knee at about 10 concurrent turns / 4.7 turns/s; GPU cross-encoder reranking is the only stage that slows with load; reranking off gives 11.7 turns/s ([performance.md](../performance.md), CAP-03)
- [ ] OPT-02 Rerank less per turn — lower `MIN_RERANK_POOL` from 30 to 16 or cap the reranker at 256 tokens; about half the GPU work per turn. Needs `scripts/eval/rag.py` to confirm retrieval quality holds
- [ ] OPT-03 Batch reranking across concurrent turns in one forward pass — the model-server queue (`core/infrastructure/model_server/`) is the natural place
- [ ] OPT-04 Load the reranker in fp16 before moving it to the GPU — `core/retrieval/reranker.py:92` halves after loading in fp32, leaving about 1.6 GB of PyTorch cache that OCR could use
- [-] OPT-05 Admission cap set to the knee (`MAX_CONCURRENT_CHATS` 16 → 10–12) — a product choice between earlier 503s and slower first tokens, not an engineering fix
- [x] OPT-06 Repeated answers cached and models preloaded at start — `core/agent/response_cache.py`, `AppContainer.start`
- [~] OPT-07 Memory measured under chat **and** OCR load — chat only: API about 3.4 GB VRAM and 1.74 GB RSS, flat to 50 users; RES-03 with an OCR job is open

## Build and CI

- [x] OPT-08 CI wall time under 5 minutes — longest job `Tests (pytest)` 2.6–3.5 min over the last three `main` runs; pip and embedding-model caches, superseded runs cancelled
- [x] OPT-09 Backend image ships only what runs — the build context is `app/`, `migrations/`, `scripts/` and the build files (5.1 MB); `test/` and `data/` are excluded (`backend/.dockerignore`, PRIV-01 in [privacy.md](privacy.md))
- [ ] OPT-10 Image sizes recorded and budgeted — not measured; the API image bakes torch, paddle and the embedding and reranker weights
- [x] OPT-11 Expensive image layers cached — `cache-from/cache-to: type=gha` in `docker-build.yml` and `release.yml`

## Frontends

- [ ] OPT-12 Admin web split into chunks — one 544 KB JS chunk (158 KB gzipped) for every page; Vite warns above 500 KB. Route-level `lazy()` imports would keep login and dashboard light
- [ ] OPT-13 Widget bundle size recorded — not measured; it loads inside the host site's iframe, so first-paint weight matters most here
