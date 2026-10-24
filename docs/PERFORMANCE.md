# Performance: the chat pipeline under load

First measured numbers for the chat path (CAP-03, RES-03 in [PRODUCTION_CHECKLIST.md](PRODUCTION_CHECKLIST.md)).
The LLM is replaced by a stub with fixed timing, so these numbers are this application's own cost:
auth, quotas, routing, retrieval and reranking on the GPU, streaming and persistence. A real provider's
latency adds to them.

Measured 2026-10-24 on a development machine, not staging. See [Limits](#limits) before quoting the numbers.

## Summary

- **Knee at about 10 concurrent turns, about 4.7 turns/s.** Up to 10 concurrent users, TTFT p95 is ≤ 1.6 s and E2E p95 is ≤ 3.1 s, with 0 errors.
  Above that, throughput stays flat (4.7–5.0 turns/s) and the 16-turn admission cap (`MAX_CONCURRENT_CHATS`) refuses the excess with 503.
  Refusals are 14% at 20 users and 57% at 50. Admitted turns stay bounded: E2E p95 ≤ 4.7 s even at 50 users.
- **Bottleneck: cross-encoder reranking on the GPU.** Retrieval is the only stage that slows with load (449 ms p50 at 1 user, 1.9 s at 20).
  The GPU is 90–98% busy from 10 users, while the API process uses 1.3–1.6 of 20 CPU threads.
  With reranking switched off, retrieval falls to about 1 ms and throughput rises 2.4× to 11.7 turns/s, where the admission cap becomes the limit.
- **Headroom.** The checklist's design peak is 0.17 msg/s. The measured ceiling is about 28× that on an RTX 3060.
- **VRAM.** The API holds about 3.4 GB of the 12 GB card, flat from idle to 50 users.
  About 1.6 GB of that is PyTorch cache left over from loading the reranker in fp32 before halving it.
  Weights are 1.3 GB, and reranking activations peak at about 0.17 GB. RAM (API RSS) peaks at 1.74 GB.

## Setup

| Item | Value |
|---|---|
| Machine | Windows 11, Intel i5-14600KF (14 cores / 20 threads), 32 GB RAM, RTX 3060 12 GB (driver 591.86) |
| API | `python main.py`, one Uvicorn worker, models in-process on the GPU (`MODEL_SERVER_URL` empty) |
| Models | `intfloat/multilingual-e5-small` embeddings, `BAAI/bge-reranker-v2-m3` reranker, both fp16 |
| Database | PostgreSQL 17 + pgvector in Docker (`chatbot-eval-pg`), database `chatbot_load` |
| Knowledge | `scripts.seed_demo documents`: 10 documents, 66 chunks |
| LLM | `LLM_PROVIDER=stub`: first token after 400 ms, then 60 tokens 25 ms apart (generation ≈ 1.87 s) |
| Off for the test | moderation and tool calling (no OpenAI key), answer cache (`LLM_CACHE_TTL=0`) |
| Limits | `MAX_CONCURRENT_CHATS=16`, `RETRIEVAL_MAX_CONCURRENCY=4` (defaults); rate limits raised so they never trip, but their counters are still written on every request |
| Load | Locust, closed loop: N visitors, each asking the 51 golden questions back to back in new conversations; a refused visitor waits `Retry-After` (5 s) |
| Per level | 90 s after a 20 s warm-up; no other GPU job running (the runner checks before and after every level) |

Every setting is in [scripts/loadtest/loadtest.env](../scripts/loadtest/loadtest.env). The stale local `.env` is not read.

## Results

### Client side (what a widget visitor sees)

TTFT is measured from the request being sent to the first `delta` event, on answered turns only.
E2E is measured to the `done` event. Refused requests are HTTP 503 from the admission cap.

| Users | Requests | Completed turns/s | Refused | TTFT p50 / p95 (ms) | E2E p50 / p95 (ms) | GPU util mean (%) | API CPU mean (% of one core) |
|---|---|---|---|---|---|---|---|
| 1 | 49 | 0.54 | 0% | 872 / 911 | 2356 / 2415 | 18 | 22 |
| 5 | 250 | 2.73 | 0% | 786 / 1170 | 2192 / 2608 | 50 | 67 |
| 10 | 435 | 4.73 | 0% | 1041 / 1620 | 2468 / 3073 | 90 | 125 |
| 20 | 508 | 4.69 | 14.2% | 2358 / 2760 | 3806 / 4200 | 98 | 156 |
| 50 | 1066 | 4.98 | 56.6% | 2381 / 3255 | 3810 / 4661 | 97 | 159 |

### Server stages (`message_traces.steps_ms`)

All values are p50 / p95 in milliseconds.
`first_token` and `total` are counted from the end of request preparation: auth, quotas, and storing the user message.
That preparation adds about 15 ms; the difference between the client TTFT and the server `first_token` shows it.
The guard, rewrite and router steps cost 0–12 ms at every level and are left out of the table.

| Users | Turns | retrieval | generation | first_token | total | Outcomes |
|---|---|---|---|---|---|---|
| 1 | 49 | 449 / 483 | 1883 / 1900 | 857 / 893 | 2334 / 2386 | answered 38, denied 11 |
| 5 | 250 | 367 / 743 | 1876 / 1892 | 771 / 1155 | 2166 / 2582 | answered 195, denied 55 |
| 10 | 435 | 634 / 1185 | 1874 / 1892 | 1026 / 1577 | 2442 / 3044 | answered 346, denied 89 |
| 20 | 436 | 1935 / 2277 | 1874 / 1893 | 2337 / 2745 | 3778 / 4178 | answered 373, denied 63 |
| 50 | 463 | 1942 / 2435 | 1873 / 1892 | 2360 / 3168 | 3784 / 4551 | answered 366, denied 97 |

"Denied" turns are the golden set's deliberately off-topic questions, such as visas for the US or gold prices.
The router refuses them after retrieval, so they pay for the rerank but not for an LLM call.

### Bottleneck check: reranking switched off

This is the same setup with `RERANKING_ENABLED=false`, 60 s per level.
It only attributes the bottleneck: without the reranker, more on-topic questions are refused (30% denied vs 22%), so this is not a configuration to ship.

| Users | Completed turns/s | Refused | TTFT p50 / p95 (ms) | E2E p50 / p95 (ms) | retrieval p50 (ms) | GPU util mean (%) |
|---|---|---|---|---|---|---|
| 1 | 0.76 | 0% | 426 / 443 | 1917 / 1942 | 0 | 1 |
| 10 | 7.14 | 0% | 436 / 476 | 1923 / 1988 | 1 | 1 |
| 20 | 11.41 | 6.4% | 433 / 524 | 1913 / 2048 | 1 | 1 |
| 50 | 11.68 | 36.2% | 428 / 726 | 1914 / 2205 | 1 | 1 |

### Memory (RES-03)

| What | Value | How |
|---|---|---|
| GPU, desktop only (no API) | 1110 MiB | `nvidia-smi` total before the API started |
| GPU with the API, idle and at every load level | 4477 MiB, so the API holds about 3.4 GB | `nvidia-smi` total; WDDM on Windows cannot show memory per process |
| Embedding weights (e5-small, fp16) | 226 MiB | `torch.cuda.memory_allocated` in a separate process |
| Reranker weights (bge-reranker-v2-m3, fp16) | 1083 MiB | same |
| Reserved by PyTorch after loading | 2894 MiB (peak 2879 MiB during load) | `memory_reserved`: the reranker is moved to the GPU in fp32 and then halved, and the freed fp32 memory stays in PyTorch's cache |
| One rerank of 30 pairs at up to 512 tokens | +165 MiB activations | `max_memory_allocated` |
| API process RAM (RSS) | 1.71 GB at 1 user, 1.74 GB at 50 users | `psutil`, every 0.5 s |

## Why the reranker is the bottleneck

Every RAG turn scores 30 (question, chunk) pairs with a 568M-parameter cross-encoder:
`MIN_RERANK_POOL = 30`, in batches of 16, up to 512 tokens per pair.
A lone turn spends about 450 ms there. That is already most of the 500 ms retrieval budget, and the GPU is idle about 80% of the time between turns.

Under load, the four retrieval slots keep the GPU busy. Since the throughput ceiling is about 4.7 turns/s, the GPU's effective cost per turn is about 1 / 4.7 ≈ 210 ms.
At 20 users about 16 turns are admitted, so most of the 1.9 s "retrieval" step is waiting for a slot rather than computing.

Three observations rule out the other stages:
- **Generation** stays flat at 1.87 s at every level, so the event loop is never saturated.
- **The API process** never uses more than 2.4 of 20 CPU threads.
- **Without the reranker**, the same process serves 2.4× more turns, until the 16-turn cap is reached.

The 5-user row being faster than the 1-user row (retrieval 367 vs 449 ms) is most likely the GPU staying at higher clocks under steady load. That is not verified.

## Against the targets

| Target | Result |
|---|---|
| TTFT under 1–2 s | Met up to 10 concurrent users (p95 1.6 s). At 20 or more users p50 is 2.4 s, because turns wait for the reranker. These figures include the stub's 400 ms; a real provider's TTFT replaces that. |
| E2E p95 under 5–8 s | Met at every level for admitted turns (≤ 4.7 s), with 60-token answers. Longer real answers add the provider's streaming time on top of the same pipeline cost. |
| Retrieval + rerank under 300–500 ms | Under 500 ms at 1 user (p95 483 ms) but not under 300. p50 stays under 500 ms at 5 users. Above the knee it is 0.6–1.9 s, mostly queueing. |
| CAP-03: 3–5× the design peak (0.5–0.85 msg/s, about 1–3 turns in flight) | Covered by the 1- and 5-user rows: TTFT p95 ≤ 1.2 s, E2E p95 ≤ 2.6 s, no errors. |

## What would move the knee

These are not done here, and each needs `scripts/eval_rag.py` to confirm retrieval quality holds. Cheapest first:

1. **A smaller rerank pool.** Lower `MIN_RERANK_POOL` from 30 to 16, or cap the reranker at 256 tokens instead of 512 (the demo chunks are FAQ-sized). Either roughly halves the GPU work per turn.
2. **Batch reranking across concurrent turns** in one forward pass. The model-server's queue is the natural place for it.
3. **A smaller cross-encoder** for the tiers that tolerate it. `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` is already in `model_weights/`.
4. **Admission set to the knee.** With `MAX_CONCURRENT_CHATS=16`, the API admits about 6 more turns than the GPU can rerank promptly. At 10–12, overload becomes an earlier 503 with `Retry-After` instead of 2.4 s TTFTs. That is a product choice.
5. **Load the reranker in fp16 before moving it to the GPU.** This doesn't change speed, but it returns about 1.6 GB of VRAM, for example to the OCR models.

## Limits

- **Not staging hardware or OS.** Production runs Linux containers, and models live in the separate model-server (RES-01), which adds an HTTP hop per embedding or rerank call and its own bounded queue. Neither is measured here; models were in-process. Locust also ran on the same machine (20 threads; the API never used more than 2.4).
- **No OCR or ingestion during the test.** RES-03 asks for chat load while an OCR job runs, and that is still open.
- **The LLM is a stub.** Provider latency, rate limits, moderation and the tool-calling intent call are not included. Conversations are single-turn, so the query rewrite never calls the LLM.
- **A small, repeating question set.** 51 golden questions over a 66-chunk corpus. Query embeddings are cached (last 1,000 queries), so the router's embedding cost appears as 0–2 ms above 1 user instead of the 7–12 ms of a fresh question. Rerank cost does not depend on corpus size, since the pool is fixed at 30.
- **One 90 s run per level.** The first full run was discarded at 5, 10 and 20 users because other GPU jobs overlapped. The runner now waits for a free GPU before each level and flags any job seen afterwards.

## Reproduce

```bash
docker start chatbot-eval-pg
docker exec chatbot-eval-pg psql -U chatbot -d postgres -c "CREATE DATABASE chatbot_load"
docker exec chatbot-eval-pg psql -U chatbot -d chatbot_load -c "CREATE EXTENSION IF NOT EXISTS vector"
python -m dotenv -f scripts/loadtest/loadtest.env run --override -- python -m alembic upgrade head
python -m dotenv -f scripts/loadtest/loadtest.env run --override -- python -m scripts.seed_demo documents
python -m dotenv -f scripts/loadtest/loadtest.env run --override -- python main.py   # note the "Started server process [pid]"
```

The load generator has its own venv, so Locust's pins never touch the app's:

```bash
python -m venv scripts/loadtest/venv
scripts/loadtest/venv/Scripts/python -m pip install -r scripts/loadtest/requirements.txt
scripts/loadtest/venv/Scripts/python scripts/loadtest/run_levels.py --api-pid <pid> --out data/loadtest/<run>
python -m scripts.loadtest.report data/loadtest/<run>      # app venv; writes results.md next to the data
```

`run_levels.py` writes one CSV per level with every turn's TTFT and E2E, and one with GPU memory and load and the API's CPU and RAM.
`report.py` joins them with `message_traces` through the `X-Request-ID` tag.
