# Production Readiness Review — RAG Chatbot

**Date:** 2026-07-31
**Scope:** whole repository (`main.py`, `api/`, `core/`, `services/`, `utils/`, `config/`, `models/`, Docker assets)
**Reference standards:** `CLAUDE.md`, `project1_agent_prompts.md`, `project1_rag_chatbot_implementation_plan.md`

---

## 0. Addendum — 2026-07-31, deployment-driven follow-up pass

Follow-up pass implementing the client's actual deployment constraints (private VPS, no
authentication infrastructure, one GPU with 12GB VRAM / 16GB RAM, English+Vietnamese corpus). This
resolved several of the open items from §5 by direct instruction rather than leaving them as
open questions:

| Item | Resolution |
|---|---|
| **P-1** (no auth) | Not building an auth system (explicitly out of scope for this deployment). Added an **optional** shared-secret header check (`API_KEY` env var, empty = disabled) as a near-zero-cost opt-in — see `api/middleware.py::APIKeyMiddleware`. `POST /cleanup/` (the actual dangerous surface) is separately disabled below. |
| **P-1** (delete-everything endpoint) | `POST /cleanup/` now returns `403` unless `DESTRUCTIVE_CLEANUP_ENABLED=true` is set. Off by default. `/cleanup/vectors/rebuild` and `/cleanup/query-adapter/update` are unaffected — neither deletes source data. |
| **V-4** (session memory) | Implemented **option 1** from the original review: the caller supplies its own history each turn (`ChatRequest.history`, already sent by the bundled Streamlit frontend but previously dropped by the API model). No new session store, no new infrastructure. `MAX_HISTORY_LENGTH` (default 10 messages, configurable) is enforced server-side regardless of what the caller sends. Found and fixed a real bug this surfaced: `app.py` was appending the current turn's question to `chat_history` *before* slicing it into `history`, so the model would have seen the same question twice — fixed to snapshot history first. |
| **V-2** (reranker language) | Default `RERANKER_MODEL` changed from the English-only `cross-encoder/ms-marco-MiniLM-L-6-v2` to `BAAI/bge-reranker-v2-m3` (multilingual). The embedding model was already multilingual. The embedding service's own emergency fallback chain also had an English-only entry (`all-MiniLM-L6-v2`) that could silently activate on a transient download failure — removed; both fallback candidates are now multilingual. |
| "Handle multiple requests at once" on a 12GB GPU | Found and fixed a real concurrency bug: `stream_response_with_history` — the only path the live `/chat/` route calls — ran hybrid search (embedding + BM25 + cross-encoder rerank) as a **synchronous, blocking call directly on the event loop**. One request's retrieval work stalled every other concurrent request. Now offloaded via `asyncio.to_thread`, bounded by a new `RETRIEVAL_MAX_CONCURRENCY` semaphore (default 4) so a burst of concurrent chats can't exceed the GPU's memory. Documented `UVICORN_WORKERS=1` as the correct choice for a single GPU (each worker would otherwise load its own copy of both models) and added a startup warning if set higher. |
| "Download models to project root" | Embedding and reranker loaders now pass `cache_folder`/`cache_dir=MODELS_DIR` (default `./models`) instead of the OS-wide Hugging Face cache. Added `scripts/download_models.py` and a `Dockerfile` build step that runs it, so weights are baked into the image and reviewable via `docker exec ... ls models/` rather than downloaded cold on first request (this also resolves P-4 from the original review). |
| Dead code adjacent to the history fix | Removed `ChatService.chat_with_memory` and `_get_cached_search_results` (unreachable — no route ever called them — and they implemented the exact same history bug being fixed elsewhere in this pass) along with the module-global `request_history`/`_history_lock` they used, which was itself a latent cross-user data leak: all callers in query-only mode shared one process-wide history list. The rest of the dead-code inventory from §4 (P-12) was **not** touched — out of scope for this pass, still awaiting the V-1 decision below. |

**Not done, by instruction:** complex authentication (JWT/OAuth), multi-worker horizontal
scaling. **Still open, unchanged from §5:** V-1 (bulk dead-code deletion), V-3 (OCR
preprocessing), V-5 (RRF vs. weighted fusion), V-6 (the venv is still broken — see below),
eval harness, CI/tests, groundedness verification, intent routing, query rewriting.

**Verification limitation carries over:** the project `venv` still cannot start (`venv/pyvenv.cfg`
points at a Python 3.10 install that no longer exists on this machine), so this pass is also
static-only — syntax-checked, import-resolution-checked, and config/env cross-checked with
Python 3.11, but never actually run. The Streamlit frontend change (`app.py`) in particular
could not be exercised in a browser.

---

## 0-B. Addendum — 2026-07-31, OCR replacement + actual runtime verification

This pass did two things: replaced the OCR stack per direct instruction, and — for the first
time this engagement — **actually ran the application** instead of relying on static analysis.
That distinction matters: static checks found zero problems in this codebase across two prior
passes, and running it for five minutes found a deadlock that would have hung every single chat
request in production, plus two library bugs. All are described below with what was found and
how.

### What changed: OCR stack replacement

Deleted the entire Tesseract/OpenCV OCR subsystem and replaced it with three interchangeable
engines under `core/document_processing/ocr/`:

| Engine | File | Used when |
|---|---|---|
| `PPOCRv6Engine` | `pp_ocr_engine.py` | Local, CPU. Default when no GPU is detected. |
| `PaddleOCRVLEngine` | `paddle_vl_engine.py` | Local, GPU. Default when a CUDA-capable PaddlePaddle build is detected. |
| `DatalabSuryaEngine` | `datalab_surya_engine.py` | Online, via Datalab's hosted Surya OCR API. Opt-in via `OCR_PROVIDER=datalab` + `DATALAB_API_KEY`. |

`get_ocr_engine()` (`engine_selector.py`) picks between these; GPU detection uses
**PaddlePaddle's own API** (`paddle.device.is_compiled_with_cuda()` + `cuda.device_count()`),
deliberately decoupled from the separate torch install that backs embeddings/reranking — the two
libraries are installed independently (different Dockerfile steps), so one being CPU-only must
not suppress the other's GPU path.

**Deleted** (all confirmed to have zero callers before removal): `preprocessing.py` (637 lines of
OpenCV enhancement — see V-3 below, this decision was made *for* you this pass), the Tesseract
`TesseractCliOcrOptions` wiring, `_process_pdf_page_by_page`/`_process_large_pdf_in_chunks`
(dead — only `process_document` was ever actually called), `_chunk_text_intelligently`/
`_chunk_by_sentences` (marked deprecated, already unused), `AsyncDoclingProcessor` (constructed
but never used), and the `tessdata/` directory (~18MB of now-orphaned language files). Also
removed, per your explicit "delete dead code" instruction from this session: `ChatbotService`'s
sync `get_batch_responses`/`_process_single_query`/`get_multi_document_response`/
`get_response_with_history`/`get_response_with_history_and_context` (superseded by the async
versions, now wired to the new batch endpoint below), `FaissVectorStore`, `docling_worker.py`,
`ContextRetriever.capture_user_feedback`/`debug_retrieval`, `parallel_processor.py`,
`EmbeddingService.async_encode`, and unused response models (`FileUploadResponse`,
`URLProcessResponse`, `QueryRequest`). `test_formatting_pipeline.py` was updated (not just left
broken) since it referenced a deleted method.

**New PDF-OCR decision logic**, replacing "OCR every PDF if Tesseract is installed" (the old
code's `OCR_FORCE_ALL_PDFS=False` path was actually dead — both its branches called the exact
same OCR conversion): a PDF is now only OCR'd when `Config.OCR.OCR_FORCE_ALL_PDFS()` is set, or
when none of its first 3 pages have an extractable text layer. Pages needing OCR are rendered via
PyMuPDF, sent through the selected engine (each call wrapped in `asyncio.to_thread`, bounded by
`OCR_CONCURRENT_PAGES`), and the result is chunked with `TextUtils.chunk_text` (existing
EN/VI-aware sentence chunker) rather than heading-based chunking, since OCR output has no
markdown structure.

### Bugs found only by actually running the app

**C-9 — Deadlock in `ServiceContainer` (critical).** `api/dependencies.py`'s `chatbot_service`
property acquired `self._lock`, then — *while still holding it* — read `self.context_retriever`,
a second property that tries to acquire the **same** lock. `threading.Lock` is not reentrant, so
this is a thread deadlocking against itself. Since `ServiceContainer` is a process-wide singleton
built lazily on the first request, this would have hung the **very first** `POST /chat/` call
forever, and every call after it (the container never finishes initializing). Static analysis
found nothing wrong here across two review passes; only sending a real request and watching curl
hang for 90 seconds with zero bytes back surfaced it. Fixed by changing the lock to
`threading.RLock()`. I audited every other `threading.Lock()` in the codebase for the same
nested-acquisition pattern (`monitor.py`, `openai_client.py`) — none of the others have it.

**C-10 — `CrossEncoder(cache_folder=...)` doesn't exist.** Last session's "download models to
project root" change passed `cache_folder=` to `sentence_transformers.CrossEncoder(...)`, copying
the parameter name from `SentenceTransformer`. `CrossEncoder` has no such parameter in the
installed version (2.5.1) — confirmed via `inspect.signature`. Every reranker load raised
`TypeError`, silently falling back to heuristic (non-cross-encoder) scoring. Fixed by passing
`automodel_args={"cache_dir": ...}` / `tokenizer_args={"cache_dir": ...}` instead, which
`CrossEncoder` forwards to the underlying `transformers.from_pretrained()` calls. Fixed in both
`core/retrieval/search/reranker.py` and `scripts/download_models.py`.

**C-11 — `paddlepaddle==3.3.0` cannot run CPU inference.** The first real OCR test failed with
`NotImplementedError: (Unimplemented) ConvertPirAttribute2RuntimeAttribute not support
[pir::ArrayAttribute<pir::DoubleAttribute>]`. This is a confirmed upstream bug
([PaddlePaddle/Paddle#77340](https://github.com/PaddlePaddle/Paddle/issues/77340)) in 3.3.0's
oneDNN/PIR CPU executor — not something in this codebase. Downgrading to `paddlepaddle==3.2.0`
fixed it outright: re-running the identical OCR call against a test image returned the exact
text drawn on it (`"Hello World Test 123"`). Pinned to 3.2.0 in both `requirements.txt` and the
Dockerfile (both CPU and the commented GPU install line), with the finding documented inline so a
future upgrade attempt knows to re-verify this specific failure mode first.

**Also discovered (dependency conflict, not a runtime bug):** `paddleocr[doc-parser]` — the
install command shown in PaddleOCR-VL's own documentation — pulls in `paddlex`'s `genai-client`
extra, which forces `openai>=1.63`, silently upgrading this project's `openai==1.57.0` pin to
`2.51.0`, a major version bump that could have broken every OpenAI call in the app. Verified that
bare `paddleocr==3.7.0` (no extra) still exposes both `PaddleOCR` and `PaddleOCRVL` — the extra is
only needed for an OpenAI-compatible *remote* serving mode this project doesn't use. Fixed by
removing the extra from `requirements.txt`, with the reasoning documented inline so nobody
re-adds it later while chasing a different problem.

### What was and wasn't verified end-to-end

Actually run, against the real app, in this pass:

- Server boot (`uvicorn main:app`) — clean, no errors, both before and after all fixes above.
- `GET /`, `GET /status` — correct responses.
- `POST /chat/` — real OpenAI call, real streamed answer, in Vietnamese per the system prompt.
- Answer cache — repeat of the identical query dropped from ~3.2s to ~0.03s.
- `POST /chat/batch` — two independent queries answered correctly and independently.
- Batch size limit — 21 queries against a limit of 20 correctly returned `422`.
- Multi-turn history — a follow-up question correctly recalled a name stated in the supplied
  history.
- `POST /cleanup/` — correctly blocked with `403` (default `DESTRUCTIVE_CLEANUP_ENABLED=False`).
- `POST /cleanup/vectors/rebuild` — correctly allowed (non-destructive).
- OCR text extraction (`PPOCRv6Engine.extract_text`) — called directly against a synthetic test
  image, correctly returned the exact text drawn on it.
- GPU/CPU auto-detection — correctly selected `pp_ocrv6[cpu]` on this GPU-less dev machine.

**Not verified in this pass — genuinely out of reach in this environment:**

- **A real scanned PDF through the full upload pipeline** — the OCR *engines* were verified in
  isolation (see §0-C below); the full chain (upload → text-layer detection → page rendering →
  chunking → vector store) was reviewed but not exercised with an actual multi-page scanned
  document.
- **The Streamlit frontend** (`app.py`) — still not exercised in a browser; no browser available
  in this environment.
- Anything requiring the destructive-cleanup-enabled path, rate limiting, or the optional API key
  middleware (all off by default, so not exercised — code review only for these three).

---

## 0-C. Addendum — 2026-08-03, GPU + Datalab verification

You confirmed this dev machine has a real GPU and provided a Datalab API key, closing the two
items §0-B flagged as unverified. Findings:

### GPU detection: `nvidia-smi` — GeForce GTX 1660, 6GB VRAM, driver 560.94, CUDA 12.6

The CPU-only `paddlepaddle` installed in §0-B cannot report GPU availability regardless of
physical hardware — it's a property of which *wheel* is installed, not the machine. Installed
`paddlepaddle-gpu==3.2.0` from the matching `cu126` package index; confirmed
`paddle.device.is_compiled_with_cuda()` → `True`, `cuda.device_count()` → `1`. The engine
selector correctly picked `paddleocr_vl[gpu:0]` once the GPU-capable build was in place —
`get_local_engine()`'s GPU-detection logic works as designed.

### Datalab Surya OCR — fully verified, works correctly

Ran `DatalabSuryaEngine.extract_text()` against a synthetic test image (two lines: "Hello World
Test 123" / "Xin chao Viet Nam") using the real key. Result: exact match,
`"Hello World Test 123\nXin chao Viet Nam"`. The submit → poll → parse implementation, built
from Datalab's API reference docs without a live call in §0-B, is now confirmed correct end to
end against the real service. No code changes needed. The deprecation note from §0-B stands: the
`/api/v1/ocr` endpoint is marked deprecated by Datalab and should be revisited if they remove it.

### PaddleOCR-VL on GPU — code confirmed correct, but genuinely out of memory on this card

Ran `PaddleOCRVLEngine.extract_text()` against the same test image on the real GPU. Result:
**`ResourceExhaustedError`** — paddle allocated the full 6GB card and still needed ~400MB more,
just to load the layout-detection model (PP-DocLayoutV3) alongside the 0.9B-parameter VLM. Tried
the standard mitigation (`FLAGS_allocator_strategy=auto_growth`, which lets paddle grow its
allocation incrementally instead of grabbing a large fraction upfront) — this let loading
proceed *further* (both models loaded, weights loaded successfully) but inference itself then
failed with `fatal: Memory allocation failure` / `RuntimeError: ... radix_sort: failed on 2nd
step`, a CUDA kernel failure from running out of workspace memory during post-processing.

**This is not a bug in the integration code** — my `extract_text()` caught the exception exactly
as designed and returned an empty string; nothing crashed. It is a real capacity finding: on
this specific 6GB card, the layout model + 0.9B VLM + paddle/cuDNN framework overhead does not
fit, even before running a single image through it.

Also noticed in passing: a `paddlepaddle-gpu==3.2.0` packaging inconsistency — its own metadata
declares `nvidia-cudnn-cu12==9.5.1.17` as a hard dependency, but at runtime it logs "compiled
with CUDNN 9.9, but CUDNN version in your machine is 9.5." I tried installing the matching 9.9.x
build; pip immediately flagged it as violating paddle's own declared requirement, so I reverted.
This looks like an upstream packaging bug in the paddle release itself (build-time cuDNN version
vs. declared runtime dependency don't match) — not something fixable from this project's side,
and not the cause of the OOM (the OOM is a straightforward "not enough VRAM," confirmed by the
math: 6GB total, ~604MB already used by the OS/other apps, paddle needed essentially all of the
remaining ~5.3GB and then some).

**What this means for your actual deployment:** your production target has 12GB — double this
card's 6GB — which should give real headroom. But "double" is not the same as "verified," and
this test showed the margin on 6GB was not small (paddle wanted the entire card, not just a
slightly-too-big slice of it). Two things worth knowing before you rely on the GPU OCR path in
production:

1. **Please run this same check on the actual 12GB VPS** before depending on it — install
   `paddlepaddle-gpu` there (Dockerfile has the commented install line ready) and run one real
   document through `PaddleOCRVLEngine` before trusting it for real traffic. I'd want to see it
   succeed on the real hardware, not just infer it from a memory-size ratio.
2. **Capacity planning on that 12GB card isn't just the VLM alone.** The embedding model and
   reranker (already sharing that GPU per the original review's `RETRIEVAL_MAX_CONCURRENCY`
   tuning) will be resident in VRAM *at the same time* as PaddleOCR-VL if a chat request and a
   document upload happen concurrently. If the 12GB test also runs tight, the fallback is simply
   `OCR_PROVIDER=datalab` (fully verified working above) or accept CPU OCR (`PPOCRv6Engine`,
   also fully verified, just slower) — both are already correctly wired and require no code
   changes, only an env var.

---

## 1. Verdict

The system is **functionally impressive but not production-ready as it stood**. The retrieval
stack (hybrid BM25 + dense, cross-encoder reranking, context expansion, FAISS/HDF5 storage) is
genuinely well built. What was missing is the operational layer around it: the process was
rebuilding its entire ML stack on every HTTP request, the knowledge base went stale the moment a
document was uploaded, conversation memory silently did nothing, and there is no authentication on
any endpoint.

I fixed the mechanical and structural problems (§3). Everything that changes product behaviour or
needs a business decision is left untouched and listed in §5 for your confirmation.

| Area | Before | After this pass |
|---|---|---|
| Per-request cost | Reranker + OpenAI probe + vector-store load **per request** | Loaded once per process |
| Uploads visible to chat | Only after a restart | Immediately |
| Largest module | `chatbot.py` — 1269 lines | 633 lines, 4 collaborators |
| `main.py` | 337 lines, business logic inline | 175 lines, wiring only |
| Security middleware | Written but never wired | Wired and config-driven |
| Config drift | 3 conflicting defaults, 2 misnamed vars, 21 undocumented | `.env.example` verified against code |
| Authentication | None | **Still none** — see P-1 |

---

## 2. How I reviewed

- Read every tracked Python module (~90 files) plus `Dockerfile`, `docker-compose.yml`,
  `start.sh`, `.env.example`, `requirements.txt`.
- Cross-checked every `Config.<Group>.<SETTING>()` call site against `config/settings.py`
  (script-verified: 0 mismatches).
- Cross-checked every local `from x import y` against the target module (script-verified: 0
  unresolved).
- Diffed environment variables read by code against `.env.example` (script-verified: exact match).
- Syntax-checked the tree with Python 3.11 `compileall`.

**Verification limit:** the project `venv` is broken — `venv/pyvenv.cfg` points at
`C:\Users\TNT_AI\AppData\Local\Programs\Python\Python310\python.exe`, which no longer exists, so
`venv\Scripts\python.exe` fails to start. I could not run the app, `pip install`, or the test
scripts. All checks above are static. See **V-6**.

---

## 3. What I changed

### 3.1 Critical correctness fixes

| # | Fix | Files |
|---|---|---|
| C-1 | **Uploaded documents never reached chat until restart.** `ModelPreloader` cached the `(embeddings, documents)` tuple at startup and `ChatService` read that snapshot forever, while ingestion rebuilt a *different* `OptimizedVectorStore` instance. Introduced `VectorStoreProvider`: one shared store, explicitly invalidated after every rebuild/cleanup. | `core/storage/vector_stores/provider.py` (new), `services/chat_service.py`, `services/document_service.py`, `api/routes/cleanup.py`, `utils/performance/model_preloader.py`, `core/retrieval/search/retriever.py` |
| C-2 | **`ChatService.get_knowledge_base_status()` raised `NameError`** on every call — it referenced an undefined `vector_store` local. The bare `except` hid it, so `/health` style checks always reported `"status": "error"`. | `services/chat_service.py:342` |
| C-3 | **`GET /status` was permanently broken.** It called `Config.HOST()`, `Config.PORT()` … on the grouped `Config` object, which has no such attributes → `AttributeError` → always returned the error branch. | `api/routes/health.py` |
| C-4 | **`LogManager.get_rag_debug_info` flagged every log line as an error** — the condition was `if "error" in line_lower or "" in line:`, and `"" in line` is always `True`. | `utils/system/log_utils.py:132` |
| C-5 | **Security/rate-limit/error middleware was dead code.** `api/middleware.py` defined `setup_middleware()` with five middlewares; `main.py` never called it. The app ran with only CORS + GZip — no security headers, no rate limiting. Now wired and driven by `RATE_LIMIT_ENABLED` / `REQUEST_LOGGING_ENABLED`. | `main.py`, `api/middleware.py` |
| C-6 | **Semantic cache key bug.** `_cache_response()` called `self._get_semantic_cache_key(cache_key)` — passing an MD5 digest where a query string was expected. The resulting `_semantic_cache` dict was also never read anywhere. Removed with the cache rewrite. | `core/ai_services/llm/chatbot.py` |
| C-7 | **FAISS index was never used.** `ContextRetriever` built its own `OptimizedVectorStore` and never loaded it, so `faiss_index` was always `None` and the code silently fell through to full NumPy cosine. Now uses the shared, loaded store. The FAISS branch also only fetched `k` candidates, which would have left most documents with a zero semantic score once it started working — widened to a proper candidate pool so fused scoring matches the exact-cosine path. | `core/retrieval/search/retriever.py` |
| C-8 | **`validate_config()` never ran under `uvicorn main:app`** (the Docker path) — it was only called from `main()`. Same for logging configuration. Both now run at module import, so both entry points behave identically. | `main.py`, `setting.py` |

### 3.2 Performance fixes

| # | Fix | Impact |
|---|---|---|
| P-A | `get_chat_service()` is a FastAPI `Depends`, so **every `/chat/` request** constructed a `ContextRetriever` (loading a cross-encoder into memory), a `ChatbotService`, an `AsyncOpenAI` client, an `httpx.Client` that was never closed, and called `ChatbotService._test_api()` — **a real, billed chat completion**. Added `ServiceContainer` so these are built once per worker. | Removes a model load + a paid API call + a leaked connection pool from every request |
| P-B | `_test_api()` burned a chat completion just to check reachability. Replaced with `client.models.list()` (free metadata call) inside `OpenAIClientProvider.check_availability()`. | One free call at startup instead of one billed call per request |
| P-C | `ChatService` called `PerformanceMonitor.record_system_metrics()` inline, which ran `psutil.cpu_percent(interval=1)` — **a 1-second blocking sleep in the request path**. Moved to a 30s background sampling loop using the non-blocking form. | −1s per request on that path |
| P-D | `GET /status` had the same blocking `psutil.cpu_percent(interval=1)`; `GET /cache-stats` built the whole chat pipeline just to read counters. Both now read shared singletons directly. | Monitoring no longer triggers model loading |
| P-E | The reranker was instantiated twice (once by `ModelPreloader`, once per `ContextRetriever`) and the preloaded one was never used. Added `get_reranker()`. | One cross-encoder in memory instead of N |
| P-F | Log files grew without bound (`logging.FileHandler`). Switched to `RotatingFileHandler` honouring the already-defined-but-unused `LOG_MAX_SIZE` / `LOG_BACKUP_COUNT`. | Bounded disk usage |
| P-G | `RateLimitingMiddleware.requests` grew one entry per unique client IP forever. Added pruning. | Bounded memory when rate limiting is enabled |

### 3.3 Structural refactor (CLAUDE.md §1–§2 compliance)

**`core/ai_services/llm/chatbot.py`: 1269 → 633 lines.** It contained seven near-identical
generate-and-package flows; the 14-line confidence-payload block appeared eight times and the
OpenAI client was constructed inline four times. Extracted:

- `core/ai_services/llm/response_cache.py` — `ResponseCache`: TTL + LRU, thread-safe, one key builder.
- `core/ai_services/llm/openai_client.py` — `OpenAIClientProvider`: owns the pooled sync/async
  clients, availability probe, `complete()`, `stream()`, `close()`.
- `core/ai_services/llm/response_factory.py` — `ChatResponseFactory`: single definition of the
  confidence / search-metadata / response payloads.
- `core/retrieval/search/context_builder.py` — `ContextAssembler`: the `[Chunk n]` join-and-truncate
  logic that was duplicated five times across `chatbot.py` and `chat_service.py`.

**`main.py`: 337 → 175 lines.** Business logic moved out:

- `core/infrastructure/lifecycle.py` — `ApplicationLifecycle` (ordered startup/shutdown steps) and
  `StartupBanner`.
- `utils/system/logging_setup.py` — `configure_logging()`.
- `scripts/build_query_adapter.py` — `QueryAdapterBuilder`, replacing the ~30 lines of pandas/eval
  handling that lived inside `main()`. The `--build-query-adapter` CLI flag still works.
- Removed the `DEBUG: ServerConfig.PORT = …` debug `print()`s (CLAUDE.md §4).

**`config/settings.py`** rewritten around typed `env_str/env_int/env_float/env_bool/env_list`
helpers with logged fallbacks on malformed input (previously `int(os.getenv(...))` would crash the
process on a typo'd env var). Every variable is now defined exactly once; grouped classes alias the
canonical definition. Conflicts resolved:

| Variable | Was | Now |
|---|---|---|
| `EMBEDDING_MODEL` | `LLM` → `sentence-transformers/all-MiniLM-L6-v2`, `RAG` → `paraphrase-multilingual-MiniLM-L12-v2` | one definition, multilingual default (matches the Vietnamese corpus and `.env.example`) |
| `RERANKER_MODEL` | `LLM` → `BAAI/bge-reranker-base`, `RAG` → `cross-encoder/ms-marco-MiniLM-L6-v2` | one definition on `RAG`; see **V-2** |
| `TEMP_DIR`, `CHUNKS_DIR`, `VECTORS_DIR`, `VECTOR_STORE_PATH`, `LOG_DIR` | defined in 2–3 classes | one definition, aliased |
| `QUERY_ADAPTER_PATH` | default `data/query_adapter.pkl` while `np.save`/`np.load` use `.npy` — the adapter could never load back | `data/vectors/query_adapter.npy` |

Also removed dead accessors (`MAX_TOKENS`, `TEMPERATURE`, `TOP_K_RESULTS`,
`QUERY_EXPANSION_ENABLED`, `OCRConfig.get_config_by_name`) and the `LegacyConfig` shim in
`setting.py`. `config/__init__.py` kept its aliases, and `HealthConfig` now points at `Config.Health`
instead of the wrong `Config.Server`.

**Error handling** (CLAUDE.md §4): replaced `logger.error(f"...{e}")` with `logger.exception(...)`
throughout the touched modules so stack traces are actually captured.

### 3.4 Configuration & deployment

- **`.env.example` rewritten.** It had two variables the code never reads under those names —
  `RERANKER_ENABLED` (code reads `RERANKING_ENABLED`) and `RAG_QUERY_ADAPTER_PATH` (code reads
  `QUERY_ADAPTER_PATH`) — so reranking could not actually be disabled and the adapter path was
  ignored. Six more were dead (`RELOAD`, `LLM_CACHE_ENABLED`, `VECTOR_STORE_BACKEND`,
  `CACHE_EMBEDDINGS`, `EMBEDDING_BATCH_SIZE`, `HEALTH_CHECK_*`), and 21 real settings were
  undocumented. Now script-verified to match the code exactly, grouped and commented.
- **`docker-compose.yml`**: dropped the 50-entry `environment:` pass-through list that had drifted
  from the code (it silently omitted every new variable); `env_file: .env` already covers it.
  Healthcheck now falls back to HTTP like the Dockerfile's, and `start_period` raised to 90s to
  cover first-boot model downloads. Removed the empty `deploy: resources: {}` and the unused
  `./logs` mount (logs live under `data/logs`).
- **`requirements.txt`**: added `transformers`, `PyMuPDF`, `Pillow`, `opencv-python-headless`
  (imported directly by our code but only present transitively) and `pytest`/`pytest-asyncio`.
  Removed `redis` and `pydantic-settings`, neither of which is imported anywhere. See **V-6**.

---

## 4. Findings still open (not fixed — needs a decision or a larger change)

Ordered by severity.

### P-1 — No authentication or authorization on any endpoint 🔴

`POST /cleanup/` **deletes the entire knowledge base, all chunks, vectors and logs**. `POST
/files/upload` and `POST /files/url` ingest arbitrary content. `POST /cleanup/vectors/rebuild`
triggers a full re-embedding. None require a credential. With `CORS_ORIGINS=*` and the container
published on `0.0.0.0:8500`, anyone who can reach the port can wipe the corpus.

*Recommendation:* an API-key dependency on all mutating routes at minimum; ideally split the
admin/maintenance router behind separate credentials.

### P-2 — Multi-turn conversation memory does not work end-to-end 🔴

Three independent breaks in the same path:

1. `api/routes/chat.py` accepts `QueryRequest`, which has **no `history` field**. The Streamlit
   frontend *does* send `payload["history"]` (`app.py:61-62`), and Pydantic silently discards it.
   The `ChatRequest` model that has a `history` field (`models/responses.py:275`) is never used.
2. In `with_history` mode the route passes a literal `[]`.
3. In `query_only` mode it passes `None`, which falls back to `ChatService.request_history` — a
   list that `stream_chat_with_memory` reads but never appends to (see its closing comment).

So `CHAT_MODE=with_history` changes nothing observable. Fixing this properly means adding session
storage — the reference plan's Step 11 (Postgres `sessions`/`messages` tables). See **V-4**.

### P-3 — The streaming path bypasses every cache 🟠

`stream_response_with_history` never consults `ResponseCache`, and `SmartCacheService` is only
reachable from `ChatService.chat_with_memory`, which **no route calls**. Since `/chat/` is the only
chat endpoint and it is streaming-only, the answer cache currently has a 0% hit rate in production
and `SmartCacheService`'s embedding work is pure overhead. Either wire a cache check before the
stream starts (buffer-and-replay on hit) or remove the unused cache layer.

### P-4 — ML models are downloaded at container runtime 🟠

`SentenceTransformer(...)` and `CrossEncoder(...)` pull from Hugging Face on first use. The image
therefore needs outbound HF access at boot, first start is slow, and builds are not reproducible —
an upstream model change or HF outage breaks a deploy. Bake the weights into the image
(`huggingface-cli download` in the Dockerfile) or mount a pre-populated `HF_HOME` volume.

### P-5 — Advanced OCR preprocessing has never executed 🟠

`docling_processor.py` referenced `PreprocessingConfigManager`, a name only ever bound in the
*failure* branch of its import guard. In the success path it was undefined, so `if
PreprocessingConfigManager:` raised `NameError` on every call, the surrounding `except Exception`
caught it, and `_advanced_preprocessing_enabled` was set to `False`. The entire 637-line
`preprocessing.py` module and the `PREPROCESSING_CONFIG` / `preprocessing_config` plumbing are
therefore dead. I made the failure explicit and loud rather than silent, but **kept the behaviour
disabled** — see **V-3**.

### P-6 — Prompt injection → HTML injection in the operator UI 🟠

`SystemPrompts.UNIVERSAL` instructs the model to return a raw HTML fragment including
`<a href="…">`, and `app.py` renders responses with `unsafe_allow_html=True`
(`app.py:504,526,530`). Content ingested from `POST /files/url` is attacker-controllable, so a
crafted page can steer the model into emitting markup rendered in the operator's browser.
Sanitise model output (allow-list tags/attributes, e.g. `bleach`) before rendering, or switch the
prompt to Markdown and render with `unsafe_allow_html=False`.

### P-7 — Pickle deserialization from a writable bind mount 🟡

`SmartCacheService._load_persistent_cache()` unpickles `data/temp/smart_cache.pkl` and the legacy
`VectorStore.load_vector_store()` unpickles `data/vectors/vector_store.pkl`. `./data` is a host
bind mount. Anyone who can write there gets code execution in the container. Prefer JSON/HDF5 for
the cache (the optimized store already avoids pickle).

### P-8 — Scoring fusion is not RRF 🟡

`hybrid_search` min-max-normalises both score lists and takes a weighted sum
(`SEMANTIC_WEIGHT * dense + (1-w) * bm25`). Min-max normalisation is unstable when one list is
nearly uniform, and it makes `SIMILARITY_THRESHOLD=0.7` mean different things per query. Both
reference documents specify Reciprocal Rank Fusion (`k=60`), which is rank-based and immune to
score-scale drift. This is a retrieval-quality decision — see **V-5**.

### P-9 — Rate limiting is per-process 🟡

Counters live in worker memory, so with `UVICORN_WORKERS=N` the effective limit is `N ×` the
configured value. Documented in the middleware docstring. For real enforcement use a shared store
or an edge proxy.

### P-10 — No test suite, no CI 🟡

`test/` contains four **manual scripts**, not tests: only `test_formatting_pipeline.py` defines
`test_*` functions, none use `pytest`, several call the live OpenAI API. There is no `.github/`,
no `pytest.ini`/`pyproject.toml`. Both reference documents require a CI workflow (Step 0) and unit
tests with mocked LLMs (Step 13). Highest-value first tests: fusion ranking, `ContextAssembler`
truncation, `ResponseCache` TTL/LRU, `VectorStoreProvider` invalidation.

### P-11 — Remaining oversized modules 🟡

Against CLAUDE.md's ~300–400 line limit:

| File | Lines | Note |
|---|---|---|
| `core/document_processing/processors/docling_processor.py` | 887 | not touched this pass — splitting the OCR pipeline is a separate, risky job |
| `core/document_processing/processors/preprocessing.py` | 637 | dead until P-5 is resolved |
| `core/ai_services/llm/chatbot.py` | 633 | down from 1269; the rest is the unused public API in **V-1** |
| `services/chat_service.py` | 550 | `chat_with_memory` (~190 lines) is unreachable — see **V-1** |
| `core/retrieval/search/retriever.py` | 542 | `debug_retrieval` (~100 lines) duplicates `hybrid_search` |
| `config/settings.py` | 536 | mostly one-line accessors + docstrings; acceptable |
| `app.py` | 539 | Streamlit UI; splitting is cosmetic |

### P-12 — Dead code inventory 🟢

Flagged, not deleted (see **V-1**):

- `core/document_processing/processors/docling_worker.py` — never invoked; its docstring points at
  `core.processing.docling_worker`, a module path that no longer exists.
- `core/storage/vector_stores/vector_store.py::FaissVectorStore` — never instantiated, and would
  raise `TypeError` on construction (`Config.File.VECTOR_STORE_PATH + ".faiss"` concatenates a
  *method object*, not its return value).
- `ContextRetriever.capture_user_feedback` — an empty `if/else` with two `pass` branches.
- `models/responses.py::ChatRequest`, `URLProcessResponse`, `URLProcessingResponse`,
  `FileUploadResponse` — unreferenced.
- `EmbeddingService.async_encode` — unused, and creates a fresh `ThreadPoolExecutor` per call.
- `core/retrieval/search/parallel_processor.py` — exported but never called.
- `DOCLING_OCR_LANGS` / `DOCLING_OCR_DPI` / `DOCLING_OCR_GPU` — read only inside a debug `print` in
  the dead worker.

### P-13 — Smaller items 🟢

- `EmbeddingService` uses `print()` for status output rather than logging (CLAUDE.md §4).
- `EmbeddingService._embedding_cache` evicts via `next(iter(...))` — insertion order, not LRU.
- `DocumentService.__del__` calls `self.close()`; `__del__` is not a reliable resource hook and can
  raise during interpreter shutdown. Prefer an explicit lifecycle call.
- `CORS_ORIGINS=*` combined with `CORS_ALLOW_CREDENTIALS=True` should be an explicit origin list in
  production.
- `.env.example` shipped `TESSERACT_CMD=C:\Program Files\...` while the runtime image is Linux; I
  changed the sample to `/usr/bin/tesseract`.
- `start.sh` reads `SSL_CERT_FILE` for the *inbound* server certificate, while
  `ApplicationLifecycle._probe_openai` deletes that variable so it cannot poison *outbound* trust.
  The collision works today but is fragile — consider renaming the inbound variable.

---

## 5. Items awaiting your confirmation

> These are behaviour or policy decisions. Nothing here has been changed. Reply with a
> decision per item and I will implement them in a follow-up pass.

### V-1 — Delete the unused public API surface?

These are public methods with no caller anywhere in the repo. Removing them takes
`chatbot.py` to roughly 250 lines and `chat_service.py` to roughly 350, both inside the CLAUDE.md
limit. I preserved them because external tooling of yours might call them.

| Symbol | Lines | Note |
|---|---|---|
| `ChatbotService.get_response` | ~25 | only used by the other dead methods |
| `ChatbotService.get_batch_responses` / `_process_single_query` / `_batch_failure` | ~70 | |
| `ChatbotService.get_multi_document_response` | ~60 | |
| `ChatbotService.get_response_with_history` | ~25 | |
| `ChatbotService.async_get_response` / `async_get_batch_responses` | ~70 | |
| `ChatService.chat_with_memory` | ~190 | the non-streaming path; no route reaches it |
| `ChatService._get_cached_search_results` | ~25 | only used by the above |
| Everything in P-12 | ~200 | |

**Decision needed:** delete all / delete some / keep. ☐

### V-2 — Reranker model name

`.env.example` shipped `RERANKER_MODEL=cross-encoder/ms-marco-MiniLM-L6-v2`, but the hard-coded
fallback inside `reranker.py:37` is `cross-encoder/ms-marco-MiniLM-L-6-v2` (extra hyphen). If the
configured name is not a real repository, `Reranker.__init__` logs a warning, fails, and silently
falls back to the second candidate — so reranking has probably been running on the fallback model
all along, after a wasted download attempt per process. I set both the default and `.env.example`
to the hyphenated form to match the in-code fallback.

**Decision needed:** confirm the intended reranker, and whether you want a multilingual
cross-encoder instead — `ms-marco-MiniLM` is English-trained and your corpus and prompts are
Vietnamese. `BAAI/bge-reranker-v2-m3` or `jinaai/jina-reranker-v2-base-multilingual` would be
better matched (the jinaai branch in `reranker.py` suggests this was already being considered). ☐

### V-3 — Enable the OCR preprocessing pipeline? (P-5)

The fix is small — replace the dead lookup with the already-imported factory:

```python
self._preprocessor = DocumentPreprocessor(create_ocr_optimized_config())
```

But this switches on 637 lines of OpenCV image processing that has never run against your
documents. It will change OCR output and increase per-page cost.

**Decision needed:** enable it (and re-ingest to compare quality), or delete
`preprocessing.py` and the `PREPROCESSING_CONFIG` plumbing as abandoned. ☐

### V-4 — Session memory: how far do you want to go? (P-2)

Options, cheapest first:

1. **Client-supplied history** — add `history` to `QueryRequest` and pass it through. ~20 lines,
   works immediately with the existing Streamlit frontend, no new infrastructure. Stateless.
2. **In-process session store** — a `SessionStore` keyed by `session_id` with a TTL. Survives
   nothing, breaks with `UVICORN_WORKERS > 1`.
3. **Postgres-backed sessions** — the reference plan's Step 11 schema. Correct and durable, but
   adds a database to your deployment (currently there is none).

**Decision needed:** which option, and confirm that `CHAT_MODE=with_history` should be the
default once it works. ☐

### V-5 — Switch score fusion to RRF? (P-8)

Both reference documents specify RRF with `k=60`. Your current weighted-normalised-sum is tunable
via `SEMANTIC_WEIGHT` but scale-fragile. Switching changes retrieval results for every query and
makes `SIMILARITY_THRESHOLD` meaningless in its current form (RRF scores live around
`1/(60+rank)`), so the threshold semantics would need rethinking too.

**Decision needed:** switch to RRF, keep weighted fusion, or make it selectable by config so you
can A/B it. I'd suggest selectable plus a small eval set to decide with numbers rather than
opinion. ☐

### V-6 — Rebuild the venv and pin dependencies

`venv/pyvenv.cfg` points at a Python 3.10 install that no longer exists, so the venv cannot start
and I could not run anything. The only working interpreter on this machine is Python 3.11 at
`D:\lcduc\Downloads\Python\Python311`. The Dockerfile builds on Python 3.10-slim.

```powershell
Remove-Item -Recurse -Force venv
python -m venv venv
venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
pip freeze > requirements.lock.txt   # then pin the four unpinned entries
```

The four newly declared packages (`transformers`, `PyMuPDF`, `Pillow`,
`opencv-python-headless`) are intentionally unpinned so the resolver can keep them compatible with
`docling==2.54.0` and `sentence-transformers==2.5.1`; pin them from the freeze output.

**Decision needed:** confirm the target Python version (3.10 to match Docker, or 3.11), then I can
verify the refactor at runtime. ☐

### V-7 — Authentication scheme (P-1)

**Decision needed:** static API key header, OAuth2/JWT, or network-level restriction only
(the service is only reachable inside your VPN)? If the last, say so and I will document it as an
accepted risk rather than adding auth. ☐

### V-8 — Behaviour changes I made that you should sanity-check

Small, deliberate, but worth eyeballing:

- **Default `EMBEDDING_MODEL`** when unset changed from `all-MiniLM-L6-v2` to
  `paraphrase-multilingual-MiniLM-L12-v2`. Your `.env` sets it explicitly, so no runtime effect —
  but if the vector store was ever built with the English model, embedding dimensions differ and a
  rebuild is required. ☐
- **`RERANKING_ENABLED` now actually works.** It was previously unreachable (`.env` set
  `RERANKER_ENABLED`), so reranking was always on. If your `.env` carries `RERANKER_ENABLED=false`
  expecting it to disable reranking, rename it. ☐
- **FAISS is now genuinely used** when `USE_FAISS_INDEX=True` (C-7). `IndexFlatIP` is exact, and
  I widened the candidate pool so fused scores match the old NumPy path — but this is the change
  most worth spot-checking against a few known queries. ☐
- **Security headers + cache-control middleware are now active** on every response (C-5). ☐
- **`RATE_LIMIT_ENABLED` defaults to `False`**, preserving today's behaviour. Set it to `True`
  once you have decided the limits. ☐

---

## 6. Gap analysis vs. the reference documents

Your repo is a different, more mature product than the reference build (Vietnamese corpus, Docling
OCR, HDF5+FAISS instead of Qdrant, no Postgres). The table maps intent, not file paths.

| Reference capability | Status here |
|---|---|
| Hybrid dense + lexical retrieval | ✅ dense embeddings + BM25 |
| Reciprocal Rank Fusion (`k=60`) | ⚠️ weighted normalised sum instead — **V-5** |
| Cross-encoder reranking | ✅ with heuristic fallback |
| Context assembly + budget trimming | ✅ `ContextAssembler` (new) |
| Token-by-token streaming | ✅ SSE |
| Groundedness / Self-RAG check | ❌ `ConfidenceScorer` is a heuristic quality score, **not** a grounded-vs-context verification. No `{"grounded": bool}` LLM judge, no caveat appended to ungrounded answers |
| Intent router (chitchat / out_of_scope / needs_rag) | ❌ every query runs the full pipeline |
| Query rewriter (history → standalone query) | ❌ |
| Session memory | ❌ — **P-2 / V-4** |
| Eval harness (`recall@5`, groundedness rate, latency) | ❌ no dataset, no runner, no numbers |
| Ablation table + RAGAS | ❌ |
| Semantic cache | ⚠️ `SmartCacheService` exists with embedding similarity matching, but is unreachable from the live route — **P-3** |
| Prometheus `/metrics` + Grafana | ❌ `PerformanceMonitor` exposes JSON at `/performance`, not Prometheus format |
| CI (lint + pytest on push) | ❌ — **P-10** |
| Unit tests with mocked LLM | ❌ — **P-10** |
| README with real eval numbers + design trade-offs | ⚠️ README exists; no eval numbers, no trade-offs section |

**The single highest-leverage gap is the eval harness.** Without `recall@5` and a groundedness pass
rate you cannot tell whether V-2 (reranker choice), V-3 (OCR preprocessing) or V-5 (RRF) actually
help. Every other retrieval decision is currently being made on intuition.

---

## 7. Suggested order of work

1. **V-6** — rebuild the venv so this refactor can be verified at runtime. Blocks everything.
2. **P-1 / V-7** — auth on mutating endpoints. An unauthenticated "delete everything" endpoint is
   the most serious issue in the repo.
3. **P-2 / V-4** — make conversation memory real, starting with option 1 (client-supplied history).
4. **P-10** — pytest + CI. Then the remaining decisions can be made with measurements.
5. **Eval harness** — 30–50 QA pairs against the real corpus; gives you the numbers for V-2/V-3/V-5.
6. **V-1** — delete the dead code once tests exist to prove nothing regressed.
7. **P-4** — bake models into the image before any serious deployment.
8. **P-6 / P-7** — output sanitisation and de-pickling.

---

## Appendix — files added or changed in this pass

**Added**

```
core/storage/vector_stores/provider.py        VectorStoreProvider
core/ai_services/llm/response_cache.py        ResponseCache
core/ai_services/llm/openai_client.py         OpenAIClientProvider
core/ai_services/llm/response_factory.py      ChatResponseFactory
core/retrieval/search/context_builder.py      ContextAssembler
core/infrastructure/lifecycle.py              ApplicationLifecycle, StartupBanner
utils/system/logging_setup.py                 configure_logging
scripts/build_query_adapter.py                QueryAdapterBuilder
docs/PRODUCTION_READINESS_REVIEW.md           this document
```

**Changed**

```
main.py                                       337 -> 175 lines, wiring only
setting.py                                    legacy shim reduced to validate_config
config/settings.py                            deduplicated, typed env helpers
config/__init__.py                            aliases corrected
api/dependencies.py                           ServiceContainer
api/middleware.py                             rate-limit rewrite, structured logs
api/routes/chat.py                            SSE headers, error handling
api/routes/health.py                          Config fix, non-blocking psutil
api/routes/cleanup.py                         provider-based, cache invalidation
services/chat_service.py                      provider, NameError fix, ContextAssembler
services/document_service.py                  provider + invalidation
core/ai_services/llm/chatbot.py               1269 -> 633 lines
core/ai_services/llm/__init__.py              new exports
core/ai_services/llm/prompts.py               (unchanged)
core/retrieval/search/retriever.py            shared store, FAISS fix, constants
core/retrieval/search/reranker.py             get_reranker() singleton
core/retrieval/search/__init__.py             new exports
core/storage/vector_stores/__init__.py        new exports
core/infrastructure/__init__.py               new exports
core/document_processing/processors/docling_processor.py   silent failure made explicit
utils/performance/model_preloader.py          delegates to provider
utils/performance/monitor.py                  non-blocking CPU sampling
utils/performance/background_tasks.py         metrics loop, cancellation
utils/system/log_utils.py                     always-true condition fixed
utils/system/__init__.py                      new export
.env.example                                  rewritten, verified against code
docker-compose.yml                            drift removed, healthcheck fallback
Dockerfile                                    healthcheck start_period
requirements.txt                              missing direct deps added
```
