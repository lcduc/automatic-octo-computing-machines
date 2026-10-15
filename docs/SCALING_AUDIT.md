# Repo Audit Guide: Chatbot Pipeline on a 16 GB GPU

**Purpose:** Instructions for Claude Code to audit this repository and decide whether it is ready to run the full pipeline (intent-router SLM, embedding, reranker, OCR) on a single 16 GB VRAM GPU at production level.

**Pipeline under audit**

| Component | Reference choice | Reference precision |
|---|---|---|
| Intent router | ~3B SLM (e.g. Qwen2.5-3B / Llama-3.2-3B), served with vLLM | INT8 |
| Embedding | BGE-M3 or Qwen3-Embedding-0.6B | FP16 |
| Reranker | bge-reranker-v2-m3 or Qwen3-Reranker-0.6B | FP16 |
| OCR | PaddleOCR-VL-1.6 (~0.96B VLM) + PP-DocLayoutV3 layout model | BF16 / FP16 |

The repo may use different models. Adapt the checks to what is actually there, and report any deviation from the reference choices.

---

## 0. How to use this guide (instructions for Claude Code)

1. **Read-only audit.** Do not modify code, configs, or models. Produce a report only.
2. For every check, search the repo (configs, Dockerfiles, compose files, launch scripts, Python/TS source, README, CI, benchmark or eval folders) and record **evidence**: file path and line, or the exact config value.
3. Assign each check one status:
   - **PASS**: evidence found and meets the criterion.
   - **FAIL**: evidence found and violates the criterion, or a required safeguard is absent.
   - **UNVERIFIED**: cannot be determined from the repo alone (typically runtime measurements). Say what measurement or log would settle it. **Never mark PASS without evidence, and never invent numbers.**
4. Do not assume flag names. vLLM and other engines rename options between versions, so check the version pinned in the repo (`requirements*.txt`, `pyproject.toml`, `Dockerfile`, lock files) and compare against that version's documented options.
5. Finish with the report in the format of section 10.

**Severity**

- **BLOCKER**: likely to cause OOM, wrong output, or outage in production.
- **MAJOR**: significant waste of VRAM or latency, or missing safeguard.
- **MINOR**: improvement, hygiene.

---

## 1. VRAM budget

Planning model (these are estimates, not measurements):

$$
\text{VRAM}_{\text{peak}} = \sum_i \left(\text{weights}_i + \text{KV/activations}_i\right) + n_{\text{proc}} \times \text{CUDA ctx}
$$

$$
\text{VRAM}_{\text{peak}} \le 0.85 \times 15\ \text{GB} \approx 13\ \text{GB}
$$

Target allocation:

| Process | Ceiling | Typical setting |
|---|---|---|
| Router (vLLM) | ~4.8 GB | `gpu_memory_utilization` ≈ 0.30 |
| OCR VLM (vLLM) | ~3.2 GB | `gpu_memory_utilization` ≈ 0.20 |
| Embedding + reranker (one process) | ~3 GB | batch caps in code |
| Layout model | ~0.7 GB | single instance, can live in the OCR worker |
| Reserved margin | ≥ 2 GB | never allocated |

**Checks**

- [ ] **[BLOCKER]** A per-process VRAM ceiling is explicitly configured (not left at engine defaults). Look in launch commands, `docker-compose*.yml`, systemd units, k8s manifests, `.env`.
- [ ] **[BLOCKER]** The sum of all `gpu_memory_utilization` fractions (and any other fixed reservations) is **< 1.0**, ideally ≤ 0.85.
- [ ] **[MAJOR]** The number of separate GPU processes is ≤ 3 (router, OCR, embedding + reranker). Each extra process costs roughly 0.3 to 0.5 GB for its CUDA context.
- [ ] **[MAJOR]** Startup is ordered or staggered for multiple vLLM instances (profiling at startup can interfere between instances).
- [ ] **[MINOR]** No training or fine-tuning job is configured to run on the serving GPU.

---

## 2. Router SLM (largest lever)

### 2.1 Model and quantization

- [ ] **[MAJOR]** The router model is quantized (INT8, FP8, AWQ, or GPTQ), unless it is already ≤ 1.5B.
- [ ] **[MAJOR]** Quantization is applied **after** fine-tuning, with calibration data from real queries (look for a calibration dataset or script).
- [ ] **[MAJOR]** An evaluation compares the serving precision against BF16 on a labeled routing test set. Look for an `eval/` or `tests/` folder, a labeled dataset (query, expected tool, expected arguments), and a results file or CI job.
- [ ] **[MAJOR]** Documented acceptance thresholds exist, with these suggested targets:

| Metric | Target |
|---|---|
| Route accuracy drop vs BF16 | ≤ 1 point |
| JSON validity | ≥ 99.5% |

Basis: AWQ (Lin et al., 2023, arXiv:2306.00978), GPTQ (Frantar et al., 2022, arXiv:2210.17323), SmoothQuant W8A8 (Xiao et al., 2022, arXiv:2211.10438), LLM.int8() (Dettmers et al., 2022, arXiv:2208.07339).

### 2.2 Prompt size (controls KV cache)

- [ ] **[BLOCKER]** The router prompt does **not** inject all tool schemas unbounded. Inspect how the prompt is built: how many tools, how many tokens per tool. If tools are fixed and the model is fine-tuned on them, a short prompt is acceptable.
- [ ] **[MAJOR]** Tool **shortlisting** happens before the router (embedding similarity or rules, top 3 to 5 candidates), or the full tool list is small enough that the prompt stays ≤ ~1k tokens (hard cap ~2k).
- [ ] **[MAJOR]** The prompt is structured with the **static prefix first** (instructions, tool list) and the **user query last**, so prefix caching can work. Flag any dynamic content (timestamps, user IDs, random examples) placed *before* the static part.
- [ ] **[MINOR]** Tool descriptions and schemas are compact (no verbose field docs, one example per tool).

### 2.3 Serving configuration (verify names against the pinned vLLM version)

| Intent | Typical option | Suggested value |
|---|---|---|
| Cap context | `--max-model-len` | 2048 |
| Cap concurrency | `--max-num-seqs` | 4 to 8 |
| VRAM ceiling | `--gpu-memory-utilization` | ≈ 0.30 |
| Prefix caching | `--enable-prefix-caching` (may be default in newer versions) | on |
| KV cache dtype | `--kv-cache-dtype fp8` | optional, only if GPU supports it and accuracy re-tested |

- [ ] **[BLOCKER]** `max_model_len` and `max_num_seqs` are both set explicitly.
- [ ] **[MAJOR]** Prefix caching is enabled (explicitly, or by confirmed default for the pinned version).
- [ ] **[MAJOR]** Structured / guided decoding is used with a JSON schema and an **enum of allowed tool names**, so malformed output and invented tool names are impossible.
- [ ] **[MINOR]** If FP8 KV cache is enabled, a post-change accuracy evaluation exists.

### 2.4 Capacity sanity check

The number of concurrent sequences the KV pool can hold:

$$
B_{\max} = \frac{\text{KV pool}}{\text{KV per token} \times T}
$$

Worked example for a 3B model with 28 layers, 8 KV heads, head dim 128 and FP16 KV (about 112 KB per token): with a ~1.2 GB KV pool and $T = 2048$,

$$
B_{\max} \approx \frac{1.2 \times 10^{9}}{112 \times 10^{3} \times 2048} \approx 5
$$

FP8 KV roughly doubles this. Prefix caching improves it further because the shared prefix is stored once.

- [ ] **[MAJOR]** `max_num_seqs` does not exceed the $B_{\max}$ computed from the repo's actual model architecture, prompt length, and KV dtype. Show the calculation in the report, and look up the real layer and KV-head counts from the model config rather than using the example numbers.

Basis: PagedAttention (Kwon et al., 2023, arXiv:2309.06180); RadixAttention prefix reuse (Zheng et al., 2023, arXiv:2312.07104).

---

## 3. Embedding and reranker

- [ ] **[MAJOR]** Both models are hosted in **one process** (for example Hugging Face TEI or a single service), not two separate GPU processes.
- [ ] **[MAJOR]** Precision is FP16/BF16 (or quantized), and **batch size and max sequence length are capped in code or config** (suggested: embedding batch 16 to 32, reranker batch 8 to 16, max length 512).
- [ ] **[MAJOR]** Reranker candidates are capped (suggested 20 to 30). Find the retrieval-to-rerank hand-off and the top-k value.
- [ ] **[MINOR]** Inputs are length-sorted or bucketed before batching to reduce padding waste.
- [ ] **[MINOR]** A CPU fallback or configuration switch exists for the embedding model (and optionally the reranker).
- [ ] **[MAJOR]** If the repo uses a larger reranker (e.g. 4B, ~8 GB in FP16), there is evidence (an eval) justifying it, because it likely breaks the 16 GB budget.
- [ ] **[MAJOR]** A retrieval evaluation set exists (recall@k or MRR with and without the reranker).

---

## 4. OCR (PaddleOCR-VL-1.6 + layout)

- [ ] **[BLOCKER]** OCR runs in a **separate worker/queue**, not inline in the request path of the chat router.
- [ ] **[BLOCKER]** OCR concurrency is limited to **1** (semaphore, queue consumer count, or worker count). Look for a semaphore, a Celery/RQ/Arq worker setting, or an equivalent.
- [ ] **[MAJOR]** Input resolution (longest side / DPI) and pages per job are capped, because visual tokens grow with resolution and drive activation and KV memory.
- [ ] **[MAJOR]** Multi-page PDFs are processed page by page, not as one batch.
- [ ] **[MAJOR]** The OCR VLM has its own VRAM ceiling (≈ 0.20 fraction if served with vLLM). Confirm the pinned vLLM version supports the OCR model (the model card lists a minimum version).
- [ ] **[MINOR]** OCR happens at **ingestion time** for known documents, not at query time.
- [ ] **[MINOR]** The layout model (PP-DocLayoutV3) runs inside the OCR worker, not as another GPU process.

---

## 5. Process and GPU hygiene

- [ ] **[MAJOR]** `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` (or equivalent fragmentation mitigation) is set for PyTorch services.
- [ ] **[BLOCKER]** There is a **request queue with a maximum length and a timeout**, so overload returns a clean "busy" response instead of an OOM. Check the API layer.
- [ ] **[MAJOR]** Each service has a health check and a restart policy, so one crash does not take down the rest.
- [ ] **[MAJOR]** Memory or concurrency limits are not silently overridden by environment-specific configs (compare dev, staging, and prod configs).

---

## 6. Caching layers

Caching reduces compute and latency. It does **not** reduce weight memory.

| Layer | Key | Saves | Suggested target |
|---|---|---|---|
| Prefix cache (in-engine) | token prefix | router prefill | automatic, bounded by KV pool |
| Embedding cache (e.g. Redis) | hash of normalized text | embedding calls | hit rate > 50% on repeated queries and chunks |
| OCR cache | file hash + OCR model version | whole OCR runs | ~100% on re-uploads |
| Rerank / retrieval cache | hash(query + candidate IDs) | reranker | frequent queries |
| Semantic cache (optional) | query-embedding similarity | whole pipeline | only if wrong-hit rate is acceptable |

- [ ] **[MAJOR]** An embedding cache exists, and an OCR cache keyed by file hash exists.
- [ ] **[MAJOR]** **Every cache key includes the model version** (and preprocessing version for OCR), so upgrades invalidate stale entries.
- [ ] **[MINOR]** TTLs are set, and hit rate is logged per layer.
- [ ] **[MINOR]** If a semantic cache exists, a similarity threshold and a wrong-hit evaluation exist.

---

## 7. Production safeguards

- [ ] **[BLOCKER]** The router has a **confidence threshold and a fallback** (to a larger API LLM or a clarifying question) for low confidence or schema-validation failure.
- [ ] **[MAJOR]** Tool-call arguments are validated against the schema before execution, with a path for asking the user for missing fields.
- [ ] **[MAJOR]** A "none of the above / general chat" route exists, so the router is not forced to pick a tool.
- [ ] **[MAJOR]** Untrusted content (OCR output, retrieved documents, web pages) cannot trigger tool calls directly. Look for a boundary between data and instructions, and a confirmation step for destructive actions.
- [ ] **[MAJOR]** Every routing decision is logged (query, chosen route, confidence, latency, fallback used).
- [ ] **[MINOR]** Dashboards or alerts for VRAM, queue depth, cache hit rate, fallback rate, and p95 latency.

---

## 8. Measurement and evaluation (mostly UNVERIFIED from code alone)

Look for scripts, CI jobs, or result files. If none exist, mark each as **UNVERIFIED** and list the missing artifact as a gap.

- [ ] **[BLOCKER]** A load test exists that includes the worst case: **an OCR upload arriving during peak chat load**.
- [ ] **[MAJOR]** Peak VRAM per process was recorded (for example via `nvidia-smi --query-gpu=memory.used --format=csv -l 1` plus a per-process view) and stored.
- [ ] **[MAJOR]** vLLM KV cache usage and the number of preempted requests were recorded. Preemptions indicate the KV pool is too small.
- [ ] **[MAJOR]** p50 and p95 latency per stage (router, retrieval, rerank, OCR) were recorded.
- [ ] **[MAJOR]** Route accuracy, argument exact-match, JSON validity, and fallback rate were measured **with the production quantization and KV settings enabled**.
- [ ] **[MAJOR]** The full eval is re-run automatically when a tool description, model, or quantization setting changes (CI hook).

**Suggested acceptance criteria** (adjust to product requirements):

| Metric | Target |
|---|---|
| Peak VRAM | ≤ 14 GB, no OOM in a multi-hour soak test |
| Router p95 latency | < 300 to 500 ms |
| Route accuracy vs BF16 | drop ≤ 1 point |
| JSON validity | ≥ 99.5% |
| vLLM request preemptions | ~0 at target load |

---

## 9. If the budget does not close (remediation order, cheapest first)

Recommend these in order, based on what the audit found:

1. Shorten the router prompt further (shortlist tools, compress descriptions).
2. Enable FP8 KV cache and lower `max_num_seqs`.
3. Move the embedding model to CPU (saves ~1.5 to 2 GB).
4. Move the reranker to CPU or reduce candidate count (saves ~1.5 to 2 GB).
5. Drop the router from 3B to ~1.5B, then re-run the accuracy eval.
6. Move OCR to a separate small GPU or a queue-backed worker.
7. Move to a 24 GB GPU.

---

## 10. Report format (what Claude Code should output)

```
# Audit Report

## Verdict
READY / READY WITH CONDITIONS / NOT READY   (one sentence why)

## Detected stack
- Router: <model, precision, engine + version>
- Embedding / reranker: <models, host process>
- OCR: <models, host process>
- Pinned versions: <vLLM, torch, etc.>

## Estimated VRAM (static, from repo config)
| Process | Config ceiling | Estimated weights | Notes |
Total vs 13 GB target: <result>, with the calculation shown.

## Findings
### BLOCKER
- [check id] <title>: status, evidence (path:line or config value), fix
### MAJOR
- ...
### MINOR
- ...

## UNVERIFIED (needs runtime measurement)
- <check>: what artifact or measurement would settle it

## Recommended next steps (ordered)
1. ...
```

**Verdict rules**

- Any BLOCKER with status FAIL: **NOT READY**.
- No BLOCKER failures, but UNVERIFIED blockers (for example no load test): **READY WITH CONDITIONS**, and list the conditions.
- All BLOCKER and MAJOR checks PASS, with only MINOR gaps: **READY**.

All VRAM figures in this guide are planning estimates derived from parameter counts and architecture. Treat them as hypotheses until confirmed by measurement (section 8).