Technical review · lcduc/automatic-octo-computing-machines

# RAG Chatbot Assessment

Reviewed 2026-10-21 at `28576fe` Updated after [PR #47](https://github.com/lcduc/automatic-octo-computing-machines/pull/47), merged as `4905ddd` Target: 20–50 users, one on-prem GPU, VI + EN data

Deployment **Deployable after fixes**

As a supervised pilot. PR #47 fixed dependency and doc problems; none of the blockers changed.

Seniority **Strong mid-level, borderline senior**

Senior-grade system and production design. Mid-level ML evaluation and prioritisation. Confidence: medium (about 60%).

## Since the review

- **Torch is pinned.** `torch==2.13.0` and `torchvision==0.28.0` live in `requirements-torch.txt`, and the Dockerfile, CI and the setup docs install from it. CI had been quietly installing torch 2.14.1.
- **transformers 4.53.3 → 5.20.2.** The bge and mmarco rerankers give identical scores, e5 embeddings are identical (cosine 1.0), docling output is identical, the router eval holds at 84.7%, and 335 tests pass. All 13 ignored transformers CVEs are gone. The jina reranker no longer loads, and nothing uses it.
- **The doc drift is fixed.** The README describes the real install path and says which features need OpenAI. DEPLOYMENT says `api` has no GPU and the shipped image runs OCR on CPU. The privacy doc lists Datalab as a sub-processor.
- **Pillow 12.3.0 has 8 CVEs** (published Oct 19) with no fix anyone can install: docling, docling-core, docling-ibm-models and streamlit all cap `pillow<13`. They are documented ignores in `ci.yml`, with a trigger for removing them. Watch
- **New finding: the nightly retrieval eval mostly doesn't run.** 8 of its last 10 runs were cancelled at the 45-minute timeout, during the last golden set. New
- **Corrections to this review.** Chat history does *not* go to OpenAI unmasked: user messages are PII-redacted before they are stored, rewritten or moderated, and history is read back from those redacted rows. Only the retrieved document passages are sent as-is. p95 latency *is* measured: per turn, in daily rollups (with p95 time to first token), and on the admin Overview. Corrected
- **GPU queue and VRAM now on the admin Overview.** The model-server already reported both on `/ready`, but nothing read them. Admin `/system` now passes them through. They are a live snapshot only: nothing stores or alerts on them. Fixed after #47
- **Redaction covers passports and dates of birth.** Both are keyword-gated, like the CMND and bank account rules. Names and addresses are still not masked, and voice input reaches OpenAI transcription as raw audio. Fixed after #47
- **Not yet confirmed:** CI and the Docker image build for the merged commit were still running when this page was written.

How this was checked

## Scope

- **Read in full:** entry points, the chat pipeline, retrieval, the model server, OCR selection, guardrails, SQL tools, auth, config, CI, Dockerfile and compose.
- **Read in part:** two subagents reviewed the frontends and the deploy tooling and docs, and their key claims were spot-checked. Most of `services/` was only skimmed.
- **Ran:** `ruff` (clean) and `pytest` (335 passed, 76 skipped for lack of a database), plus the before/after comparison for the transformers bump.
- **Did not run:** the integration tests locally, the evals against a real knowledge base, or an install on real hardware.

Claims are verified in code unless marked *inferred*.

1

## Overview

A Vietnamese-first RAG chatbot *product*. A FastAPI API, an ingestion worker and a GPU model-server (e5-small embeddings, bge-reranker-v2-m3, PaddleOCR) sit on PostgreSQL with pgvector as the source of truth. Search runs on an in-memory hybrid index, and answers come from a cloud LLM (OpenAI by default). It ships with a Next.js chat widget with a server-side layer, a Vite admin app, Docker Compose, Caddy and an ops CLI. That's about 38k lines of Python and 10k of TypeScript, over 289 commits since August 2025.

Key framing: it was built as an **embeddable public-website widget for anonymous visitors** (the demo domain is labour migration to Germany), not as an internal tool for staff.

2

## Key features

- **Pipeline ordered by cost:** rule guard → embedding router → tool intent → query rewrite → retrieval → canned fallback with no LLM call → answer cache → streamed answer with a `[NO_ANSWER]` filter. core/agent/chatbot.py:147-330
- **Hybrid retrieval:** weighted rank fusion of cosine and BM25, source priority, cross-encoder rerank and neighbouring chunks. Tier and date filters run before ranking. core/retrieval/retriever.py, knowledge_index.py:69-89
- **Ingestion:** Docling plus PaddleOCR or Datalab, with 7 chunking strategies, including one chunk per Điều (legal article). core/document_processing/
- **GPU scheduler:** chat requests go before ingestion, and bounded queues answer 503 when full. core/infrastructure/model_server/scheduler.py
- **SQL tools:** fixed, parameterised SELECT templates with `user_id` bound from the verified caller. No text-to-SQL. core/agent/tools/sql_tool.py
- **Guardrails and operations:** PII redaction and regex guards (core/guardrails/); handoff tickets, budgets, audit log, retention and alerts (services/).
- **Evals:** a router gate in CI, a nightly retrieval recall/MRR check and a manual outcome eval. scripts/eval\_\*.py

3

## Architecture and tech stack

```
caddy ─▶ web (widget server) ─▶ api ─▶ postgres · model-server · cloud LLM
ingestion-worker ─────────────────▶ postgres · model-server
```

- **One process owns the GPU.** This suits a single-GPU box. Code is layered api → services → core, wired through a DI container (api/container.py).
- **The index is rebuilt on every knowledge edit.** It is a brute-force numpy + `rank_bm25` snapshot, with its limit documented (knowledge_index.py:159). Fine at this scale.
- **The API runs one uvicorn worker on purpose** (main.py:137).
- **The provider abstraction is incomplete.** Tool calling, moderation and transcription only work with OpenAI (api/container.py:221-238), and the installer hard-codes `LLM_PROVIDER=openai`. There is no `base_url` setting, so no local LLM can be used. Documented in #47
- **Widget server:** secrets stay server-side and the visitor cookie is HMAC-signed. The SSE and markdown code is duplicated between the two frontends and has already drifted.

4

## Deployment readiness

| Item | Rating | Justification |
| --- | --- | --- |
| Setup and installation | Partial | The installer and preflight exist, but preflight has never run on a real box (PRODUCTION_CHECKLIST.md:411). NVIDIA driver setup isn't documented. The Windows demo path isn't documented or reproducible. README install claim fixed in #47 |
| Containerization | Readywas Partial | Multi-stage build, non-root user, healthchecks, memory limits, tagged images. Torch is now pinned with the rest. Fixed in #47 The image build for the merged commit hadn't finished when this was written. |
| Config and secrets | Ready | The installer generates `.env` and `secrets/`, and production refuses unsafe config (config/settings.py:556-571). `.env` has never been committed. *Inferred:* backups leave out `secrets/`. |
| Hardware vs constraints | Partial | The GPU load is light, and OCR actually runs on CPU in the shipped image. Docs corrected in #47 There is no load test (CAP-03) and no VRAM measurement (RES-03), and throughput is only an estimate. Each answer makes 2–3 cloud calls, and latency hasn't been measured. |
| Error handling | Ready | Every failure ends the stream with a safe reply (chatbot.py:163-170). A turn is saved even if the visitor disconnects. The reranker falls back to cosine scores, and the model-server answers 503 with `Retry-After`. |
| Logging and monitoring | Partial | JSONL logs carry request IDs and mask PII. Per-turn traces are stored, p50/p95 latency and p95 time to first token are rolled up daily and shown in the admin, and there are alert rules. GPU queue depth and free VRAM are now shown live on the admin Overview. *Inferred:* alerts run inside the worker, so a dead worker means no alerts. Queue and VRAM are not stored over time and have no alert rule. Corrected |
| Testing and evaluation | Partial | 335 tests pass, with hard-gate and red-team markers. The retrieval benchmark is saturated (116 queries over 10 documents, recall@k 1.0), all in Vietnamese, and there is no faithfulness eval. The nightly retrieval gate was cancelled in 8 of its last 10 runs. New The confidence score is an uncalibrated word-overlap heuristic that triggers handoffs. |
| Security | Partial | Access control is strong: scrypt passwords, hashed keys, login throttling, an append-only audit log, CSP, safe SQL tools. User messages and chat history are PII-redacted before anything reaches OpenAI (on by default). The gaps: retrieved internal document passages go to OpenAI as-is, redaction is regex-only (names and addresses pass through; passports and birth dates now covered), voice input is sent as raw audio, the injection guard is only regex, and admins have no 2FA. Corrected Dependency audit clean except documented ignores |
| Maintainability without ML staff | Partial | The admin web covers upload, editing, re-chunking and review. But the router examples are hard-coded to the Germany-visa domain (core/routing/routes.json). Swapping the embedding model or rebuilding the index isn't documented, and documents only arrive by manual upload. |

**Verdict: deployable after fixes, as a supervised pilot.** The code is well past prototype. What's missing is proof on real hardware, evaluation on the client's own domain, and a decision on what data may leave the box. PR #47 did not change any of these three.

5

## Seniority assessment

### Senior signals

- Trade-offs are written down with an upgrade trigger: the `# ceiling:` comments.
- Access control fails closed and is enforced in code, not left to the prompt.
- Cost-aware design: no LLM call when there's no knowledge, and moderation overlaps retrieval.
- SQL tools without text-to-SQL, priority GPU scheduling, and ops tooling with restore, rollback and secret rotation.
- Dependency bugs root-caused and documented; separate dev and holdout golden sets.

### Mid-level signals

- Evaluation rigour trails the engineering: the benchmark is saturated, there's no faithfulness metric, the confidence score is uncalibrated, and the nightly gate times out.
- Nothing is measured: no load test, no VRAM figure. `docs/SCALING_AUDIT.md` is a prompt template for an AI audit of a different stack, not a set of results.
- Doc drift in five places, plus an outdated reason for ignoring the CVEs. Fixed in #47
- Uneven module quality: a dict cache used across threads without a lock in embeddings.py:44, and dead code in Reranker.rerank().
- Scope: host SDKs in 3 languages, visitor tiers and a live feed were built while the real-box install, restore drill and load test are still open.

**Context:** at review time, 177 of 289 commits carried `Co-Authored-By: Claude`. So polish is weak evidence of individual skill, and the judgment calls are the better evidence. The remaining gaps are in measurement, evaluation design and prioritisation, which AI assistance doesn't cover. The #47 fixes were hygiene, so the verdict stands.

6

## Top risks

1. **Data leaving the box vs an on-prem expectation.** Every answer sends the retrieved internal document passages to OpenAI. The user's messages and history go too, but with PII masked by regex. There is no local fallback. This could block go-live.
2. **Wrong domain on day one** (only if the client's documents are not about German labour migration). The router examples and golden sets are about German labour migration: all 39 `rag_question` examples in `routes.json` mention Germany, so a question about another topic can be routed to off-topic and refused before retrieval runs. How the bot answers or refuses on the client's documents is unmeasured, and the nightly gate that would catch regressions rarely finishes.
3. **The first client install becomes the first integration test.** Preflight has never run on real hardware and there is no load test. The only live deployment, the Windows demo, uses a different path that never restarts the model-server.
4. **Recovery is unproven.** There is no restore test, the RTO is blank, and (*inferred*) secrets are not in the backups.
5. **The product doesn't match the user base.** It assumes anonymous visitors and host-site JWT tiers. An internal tool for 20–50 staff needs company sign-in and per-department access.

7

## Prioritised recommendations

| # | Action | Effort | Status |
| --- | --- | --- | --- |
| 1 | Agree with the client what data may leave the box. If it must stay local, add an OpenAI-compatible `base_url` provider (vLLM or Ollama, 7–8B 4-bit) and evaluate it in Vietnamese. | 0.5 d + 1–2 d + 3–5 d | Open |
| 2 | Build a client golden set of 150–300 questions in Vietnamese and English, including unanswerable and off-topic ones. Measure recall per chunk, re-author `routes.json`, recalibrate thresholds. | 3–5 d | Open |
| 3 | Do a dry run on matching hardware: preflight, a load test, p95 and VRAM figures, and a restore drill with a measured RTO. Back up `secrets/`. | 3–4 d | Open |
| 4 | Pin torch, move to transformers 5.x, drop the CVE ignores. | 0.5–1 d | Done #47 |
| 5 | Add an answer-quality eval (LLM judge plus about 50 human labels), and calibrate or replace the confidence score. | 3–5 d | Open |
| 6 | Fix doc drift; replace `SCALING_AUDIT.md` with measured numbers; add an uptime check that doesn't depend on the worker. | 1 d | Doc drift done |
| 7 | Make the nightly retrieval eval finish: raise or split the 45-minute budget, or run it on a GPU runner. | 0.5 d | New |
| 8 | Feature freeze until 1–3 are done; clean up `embeddings.py` and the dead reranker code. | 0.5 d | Open |
| 9 | Pin `pillow>=13` and drop its 8 ignores once docling and streamlit allow it. | 0.5 h | Waiting upstream |

Items 1–3 move the deployment verdict to "deployable". Items 2, 3 and 5 are what would move the seniority verdict to senior.

Prepared from a read-only review on 2026-10-21, then updated the same day after PR #47 merged. File and line references point at the review-time commit.