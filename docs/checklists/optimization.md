# Optimization checklist

Where time, memory and size go, measured before changed. Runtime numbers come from
[performance.md](../performance.md); `CLAUDE.md` §5 forbids optimizing without a measurement that
justifies it, so every open item names what it would improve.

Last assessed: 2026-11-10 at `2c55f4e`.

## Chat path (runtime)

- [x] OPT-01 Throughput and bottleneck measured — knee at about 10 concurrent turns / 4.7 turns/s; GPU cross-encoder reranking is the only stage that slows with load; reranking off gives 11.7 turns/s ([performance.md](../performance.md), CAP-03)
- [-] OPT-02 Rerank less per turn — pool kept at 30: `MIN_RERANK_POOL` 16 fails `scripts/eval/rag.py --check` on `golden_colloquial_dev` (MRR 1.000 → 0.970, past the 0.02 allowance; answerable questions clearing `SIMILARITY_THRESHOLD` 88% → 84%), with `golden_queries` and the holdout set unchanged (2026-11-12, demo corpus of 66 chunks). Colloquial questions need the deeper pool, as RET-04 found in September. The 256-token cap was not tried. Revisit with a client-sized corpus; OPT-03 raises throughput without touching quality
- [ ] OPT-03 Batch reranking across concurrent turns in one forward pass — the model-server queue (`core/infrastructure/model_server/`) is the natural place
- [x] OPT-04 Load the reranker in fp16 before moving it to the GPU — `core/retrieval/reranker.py` halves on the CPU, then moves; bge-reranker-v2-m3 on a GTX 1660 SUPER: CUDA reserved 2,672 → 1,092 MB, peak allocated 2,652 → 1,083 MB, scores on 32 pairs bit-identical (2026-11-11); `test_weights_are_halved_before_they_reach_the_gpu`
- [-] OPT-05 Admission cap set to the knee (`MAX_CONCURRENT_CHATS` 16 → 10–12) — a product choice between earlier 503s and slower first tokens, not an engineering fix
- [x] OPT-06 Repeated answers cached and models preloaded at start — `core/agent/response_cache.py`, `AppContainer.start`
- [~] OPT-07 Memory measured under chat **and** OCR load — chat only: API about 3.4 GB VRAM and 1.74 GB RSS, flat to 50 users; RES-03 with an OCR job is open

## Build and CI

- [x] OPT-08 CI wall time under 5 minutes — longest job `Tests (pytest)` 2.6–3.5 min over the last three `main` runs; pip and embedding-model caches, superseded runs cancelled
- [x] OPT-09 Backend image ships only what runs — the build context is `app/`, `migrations/`, `scripts/` and the build files (5.1 MB); `test/` and `data/` are excluded (`backend/.dockerignore`, PRIV-01 in [privacy.md](privacy.md))
- [~] OPT-10 Image sizes recorded and budgeted — API image 7.44 GB with CPU torch (local build, 2026-11-11; 0.73 GB of it the Docling PDF models baked for ING-13); the CUDA build that deployments run is larger and not yet measured; no budget set
- [x] OPT-11 Expensive image layers cached — `cache-from/cache-to: type=gha` in `docker-build.yml` and `release.yml`

## Frontends

- [ ] OPT-12 Admin web split into chunks — one 544 KB JS chunk (158 KB gzipped) for every page; Vite warns above 500 KB. Route-level `lazy()` imports would keep login and dashboard light
- [ ] OPT-13 Widget bundle size recorded — not measured; it loads inside the host site's iframe, so first-paint weight matters most here
