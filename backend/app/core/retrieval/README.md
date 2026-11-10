# `backend/app/core/retrieval/`

<!-- Keep this README true. Anyone (person or agent) who adds, removes or renames a file here,
     or hits a problem worth remembering, updates the matching section in the same PR. -->

## Purpose
Search over the knowledge base: embeddings, the in-memory index snapshot, hybrid retrieval
(embeddings + BM25 fused by weighted RRF, then a cross-encoder rerank), and rendering the retrieved
chunks into the `<documents>` block for the LLM. Models run in-process or behind the model-server
(`MODEL_SERVER_URL`), with the same interface.
PostgreSQL is the source of truth; storage and repositories live in `../storage/`. Chunking and
parsing live in `../document_processing/`. Deciding whether to answer from the results is
`KnowledgeAnswerer` in [`../agent/`](../agent/).

## Files

| File | Public names | What it does |
|---|---|---|
| `__init__.py` | — | Package docstring only. |
| `knowledge_index.py` | `KnowledgeIndex`, `KnowledgeSnapshot`, `anonymous_only`, `UNREACHABLE_LEVEL`, `OPEN_START`, `OPEN_END` | Immutable snapshot of every searchable chunk (texts, normalized embeddings, BM25, source/tier/date arrays), rebuilt from PostgreSQL and swapped atomically; `request_refresh` coalesces bursts into one rebuild. |
| `retriever.py` | `ContextRetriever`, `RERANK_POOL_MULTIPLIER`, `MIN_RERANK_POOL`, `RRF_K` | `search`: source/tier/effective-date filter -> semantic + BM25 -> weighted RRF x source priority -> rerank pool (>= 30) -> threshold -> best match expanded with neighbouring chunks. |
| `embeddings.py` | `EmbeddingService`, `get_embedding_service`, `reset_embedding_service`, `get_embedder`, `get_device_info`, `E5_PROMPTS`, `MODEL_PROMPTS`, `PASSAGE_BATCH_SIZE`, `QUERY_CACHE_SIZE` | Process-wide sentence-transformers model (GPU fp16, else CPU fp32) with E5 query/passage prompts, an LRU query cache and an optional query adapter. |
| `reranker.py` | `Reranker`, `get_reranker`, `RERANKER_FALLBACK_MODEL`, `RERANK_BATCH_SIZE`, `RERANK_MAX_TOKENS` | Process-wide cross-encoder (`RERANKER_MODEL`, fallback mMiniLM) loaded through `transformers`; `score` returns sigmoid scores or `None` when unavailable. |
| `remote_models.py` | `RemoteEmbeddingService`, `RemoteReranker`, `embedding_service`, `model_server_client`, `PASSAGE_BATCH_SIZE` | Model-server-backed embedder/reranker; `embedding_service(client)` picks remote or in-process; remote rerank failures return `None` (hybrid scores used). |
| `context_assembler.py` | `ContextAssembler`, `MAX_METADATA_VALUE_LENGTH`, `MAX_METADATA_ATTRIBUTES`, `HIDDEN_METADATA_KEYS` | Renders chunks as `<document id source title ...>` elements within a character budget; escapes attributes and a closing `</document` inside chunk text. |
| `query_adapter.py` | `compute_query_adapter`, `save_query_adapter`, `build_from_evals` | Closed-form ridge-regression adapter for query embeddings; only used offline by `scripts/eval/build_query_adapter.py`. |

### Flow: one search
```
KnowledgeAnswerer._retrieve (thread, RETRIEVAL_MAX_CONCURRENCY semaphore, turn deadline)
  -> ContextRetriever.search(query, KnowledgeIndex.snapshot, top_k, semantic_weight, thresholds, ...)
       candidates   = source filter -> KnowledgeSnapshot.visible(access_level, today)
       semantic     = embeddings[candidates] @ embed_query(query)
       keyword      = BM25 scores
       fused        = weighted RRF (RRF_K=60) x source priority
       rerank pool  = max(MIN_RERANK_POOL, top_k * RERANK_POOL_MULTIPLIER) -> reranker.score
       matched      = rerank >= SIMILARITY_THRESHOLD (or cosine >= SEMANTIC_THRESHOLD when no reranker scored)
       result       = best match between its neighbours (expansion_radius), then other matches
  -> ContextAssembler.build(results, MAX_CONTEXT_LENGTH) -> <documents> block for the prompt
```

## Dependencies
- May import: `app.core.storage` (`Database`, `KnowledgeRepository`), `app.core.infrastructure.model_server_client`,
  `app.models.knowledge`, `app.utils.text_utils`, `app.config.*`. Layering: api -> services -> core ->
  models/utils; config at the bottom; only main.py imports middleware; enforced by
  `test/unit/test_layering.py`.
- Used by: `core/agent/` (`ChatbotService`, `KnowledgeAnswerer`), `app/api/container.py`, `app/worker.py`
  (passage embeddings), `core/infrastructure/model_server/model_host.py`, `services/knowledge_service.py`,
  `services/chunk_editing_service.py`, `services/index_sync_service.py`, `scripts/download_models.py`,
  many `scripts/eval/*` (rag, router, robustness, retrieval_variants, compare_configs, build_query_adapter, ...).
- External / heavy: `sentence-transformers`, `transformers`, `torch` (optional, GPU), `rank_bm25`, `numpy`;
  model weights in `model_weights/` (`MODELS_DIR`): `intfloat/multilingual-e5-small` (embeddings) and
  `BAAI/bge-reranker-v2-m3` (reranker) by default; PostgreSQL for snapshot rebuilds.

## Run / test
From `backend/` with `venv` active:
```
pytest test/unit/test_retriever.py test/unit/test_retrieval_filters.py test/unit/test_reranker.py \
       test/unit/test_embeddings.py test/unit/test_query_adapter.py test/unit/test_model_server.py
pytest -m hard_gate -v        # includes tier / effective-date retrieval filters (test_retrieval_filters.py)
pytest test/integration/test_knowledge_service.py test/integration/test_knowledge_transfer.py   # need TEST_DATABASE_URL (pgvector/pgvector:pg17)
python -m scripts.eval.rag    # retrieval eval against the golden sets (database + reranker; nightly in CI)
ruff check .                  # from the repo root
```
`ContextAssembler` is covered by `test_red_team.py` (documents cannot close their own element).

## Known problems and history
- Weighted reciprocal rank fusion and a 30-chunk rerank pool (RET-04): golden set hit@4 95.3% -> 97.7%
  with the reranker; the pool size made the difference, fusion alone changed nothing
  (lcduc/automatic-octo-computing-machines#22, 725a7a5, 2026-09-29).
- Tier and effective-date filtering happen per query before ranking (RET-05); a document tier the
  mapping does not know is unreachable (fail closed)
  (lcduc/automatic-octo-computing-machines#22, 5f90957, 2026-09-29).
- API and worker use the model-server when `MODEL_SERVER_URL` is set
  (lcduc/automatic-octo-computing-machines#22, caa7e10, 2026-09-29).
- Retrieval quality fixes (lcduc/automatic-octo-computing-machines#23, 2026-09-30): embed with
  multilingual-e5-small with its `query: `/`passage: ` prompts (8bae697); rerank with
  bge-reranker-v2-m3, mMiniLM fallback (5f135b5); rerank each chunk with its document title (1df421d);
  expand only the best match with its neighbours (61b1444); gate on a cosine threshold when no reranker
  scored, because the two scores live on different scales (2e815ff).
- No fallback embedding model on purpose: stored vectors live in `EMBEDDING_MODEL`'s space, any other
  model returns garbage. The reranker can fall back because its scores are computed per turn (code comments).
- `sentence_transformers.CrossEncoder` segfaults on Windows with this torch/transformers combo, and
  jinaai remote code no longer loads on transformers 5 -> the reranker is loaded with
  `AutoModelForSequenceClassification` and `low_cpu_mem_usage=False`; a jinaai model falls back
  (code comment in `reranker.py`; verified on transformers 4.53.3 and 5.20.2 / torch 2.13.0+cu126).
- Embedder and reranker run in fp16 on GPU, fp32 on CPU (731b04e, 2026-10-15).
- Concurrent first queries loaded the embedding model once per thread (8 threads, 8 loads), and the
  dict query cache raised "dictionary changed size during iteration" and grew past its bound -> load
  under a double-checked lock, `functools.lru_cache` for the query cache; two regression tests
  (lcduc/automatic-octo-computing-machines#54, 37de0b3, 2026-10-24).
- Query adapter: `compute_query_adapter` now accepts the fp16 embeddings the GPU embedder returns; the
  ridge adapter was worse than no adapter at every lambda (63.0% Recall@1), and `build_query_adapter`
  refuses to write a losing adapter without `--force`, because the app and the router load
  `QUERY_ADAPTER_PATH` at start-up (lcduc/automatic-octo-computing-machines#55, 7b055c6, 2026-10-24).
- Load test: retrieval + rerank p95 483 ms at 1 user; at 20+ concurrent users TTFT p50 is 2.4 s because
  turns wait for the reranker ([`docs/performance.md`](../../../../docs/performance.md) lists what would move the knee).
- Backend moved under `backend/app`; this folder used to be `core/retrieval/`
  (lcduc/automatic-octo-computing-machines#76, 06f0477, 2026-11-10).
- `context_builder.py` renamed to `context_assembler.py` to match its class `ContextAssembler`
  (branch `refactor/structure-fixes`, 2026-11-10).

## Status
- Last reviewed: 2026-11-10
- Open issues / follow-ups:
  - `embeddings.py` keeps module-level helpers marked for legacy compatibility (`get_embedder`,
    `get_device_info`) and lacks type hints on several public methods.
  - OPT-02 / OPT-04: smaller rerank pool (`MIN_RERANK_POOL` in `retriever.py`) and fp16 reranker loading (`reranker.py:92`) are the cheapest throughput and VRAM levers (docs/checklists/optimization.md).
- Ceilings (`# ceiling:` markers in this folder):
  - `knowledge_index.py:159` — whole corpus held in RAM and scanned brute-force (~1.5 KB/chunk at 384
    dims, a few ms per query for 100k chunks) — move semantic search to a pgvector HNSW index past ~500k chunks.
  - `retriever.py:89` — `rank_bm25` scores the whole corpus in Python (~100 ms at 100k chunks) —
    switch to PostgreSQL full-text search past that size.
