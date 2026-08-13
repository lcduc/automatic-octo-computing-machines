# Security Review

Review of the FastAPI RAG service covering the API surface, file/URL ingestion,
storage, secrets handling and dependencies. Findings are split into what was
**fixed in this pass** and what is **recommended follow-up**, with reasoning for
each deferral.

Scope note: this was a source-level review plus a dependency audit. No dynamic
testing (fuzzing, authenticated pen-test, container escape) was performed.

---

## Fixed in this pass

### 1. Destructive endpoints were reachable with no gate — HIGH

`POST /cleanup/vectors/rebuild` and `POST /cleanup/query-adapter/update` had no
`DESTRUCTIVE_CLEANUP_ENABLED` check, unlike `POST /cleanup/` directly above them
in the same module.

This mattered because `API_KEY` is empty by default, and `setup_middleware()` in
`api/middleware.py` only installs `APIKeyMiddleware` when a key is set — so on
shipped defaults there is no authentication in front of these routes at all.
Anyone able to route to the service could:

- force a full re-embed of the corpus (an expensive CPU/GPU operation, and it
  swaps the live vector store — a denial-of-service lever), or
- overwrite `data/vectors/query_adapter.npy` with a matrix fitted purely from
  attacker-supplied `queries`/`positives`, silently degrading retrieval quality
  for every subsequent query, with no confirmation step.

**Fix**: extracted `_require_destructive_cleanup_enabled()` in
`api/routes/cleanup.py` and applied it to all three routes.

**Note this is a gate, not authentication.** It means "an operator deliberately
turned this on", not "the caller is authorized". Set `API_KEY` for any
deployment that is not on a trusted private network.

### 2. Server-side request forgery in URL ingestion — HIGH → **eliminated**

`ValidationUtils.validate_url()` checked only that the URL parsed and used
`http`/`https`. The URL was then fetched server-side by `URLProcessor`
(`requests.Session()`), so a caller could name any host the server could reach:
cloud metadata (`169.254.169.254`), loopback services, or internal-network
addresses.

An SSRF guard was added first (DNS resolution + rejection of private, loopback,
link-local, reserved, multicast and unspecified addresses). **URL ingestion has
since been removed from the product entirely** — the route, service, processor,
config and validator are all deleted — so the guard was removed with it. The
class of vulnerability is gone rather than mitigated: the server no longer makes
outbound requests to caller-supplied addresses at all.

If URL ingestion is ever reintroduced, reinstate an SSRF check as part of that
work. Note that a validation-layer check alone does not close DNS rebinding (the
fetch performs its own lookup later); blocking egress at the network layer is
the airtight fix.

### 3. Wildcard CORS combined with credentials — MEDIUM

`CORS_ALLOW_CREDENTIALS` defaulted to `True` while `CORS_ORIGINS` defaults to
`*` — the classic CORS misconfiguration. `.env.example` shipped both, so copying
it reproduced the setting.

Exploitability today is limited because nothing authenticates via cookies (the
optional `API_KEY` travels in an `X-API-Key` header, which is not a CORS
credential), but it becomes live the moment any cookie-based flow is added.

**Fix**: default flipped to `False` in `config/settings.py`; `.env.example`
updated with a comment explaining when it is safe to enable. `CORS_ORIGINS`
was left at `*`, which is a reasonable default for this app's typical
private-network deployment.

> **Action required on existing deployments**: an existing `.env` copied from
> the old example still contains `CORS_ALLOW_CREDENTIALS=True` and will override
> the new default. Update it by hand.

### 4. Exception text returned to clients — LOW/MEDIUM

`str(e)` was placed directly into HTTP response bodies in `api/routes/cleanup.py`
(3 sites), `api/routes/chat.py` and `api/routes/models.py`, bypassing the generic
message that `ErrorHandlingMiddleware` already applies to unhandled exceptions.
Exception strings can carry filesystem paths, internal hostnames and library
versions.

**Fix**: each now returns a fixed message and logs server-side via
`logger.exception(...)`.

### 5. Silent failures and unbounded logging — LOW

- `core/agent/query_rewriter.py` logged the full untruncated user query at DEBUG,
  inconsistent with the `query[:50]` convention used in `retriever.py` and
  `cache_service.py`. With file logging on by default, raising the log level for
  troubleshooting would persist complete queries to disk. Now truncated.
- `core/storage/{vector_store,document_store,metadata_store}.py` used `print()`
  inside `except` blocks in service classes — errors went to stdout with no
  level, no timestamp and no traceback. Now `logger.exception(...)`.
- `core/document_processing/extractors.py` had five `except Exception as e:
  return []` blocks that swallowed extraction failures entirely: a document that
  failed to parse silently produced zero chunks and looked like an empty file.
  Now logged with the filename.
- Four bare `except:` clauses (`core/retrieval/embeddings.py`,
  `utils/log_utils.py`) narrowed to specific exception types and logged.

### 6. Latent crash in URL chunking — MEDIUM (correctness) → **removed**

Found by the newly added lint step, not by manual review:
`core/document_processing/processors.py` referenced an undefined `URLConfig`
name, and the three settings it called (`URL_MIN_CHUNK_SIZE`, `URL_CHUNK_SIZE`,
`URL_CHUNK_OVERLAP`) did not exist anywhere in the config. Any URL that reached
`_chunk_web_content()` raised `NameError` — meaning that code path had never
worked. Fixed at the time, then removed outright along with the rest of URL
processing.

Worth noting as a lint-value data point: a whole feature path was dead on
arrival and nothing caught it, because no test covered it and no linter ran.

### 7. Unpinned dependency — LOW

`PyMuPDF` was the only unpinned entry in `requirements.txt`, against that file's
own stated policy. Pinned to `1.28.0` (the version currently installed).

---

## Recommended follow-up (not changed)

### A. Dependency vulnerabilities — partially resolved

`pip-audit` originally reported **90 known vulnerabilities across 12 packages**.
The low-risk half was upgraded and verified (tests pass, app boots, file upload
works end-to-end): **now 50 across 5**.

**Upgraded:**

| Package | From | To | Why it mattered |
|---|---|---|---|
| `python-multipart` | 0.0.20 | 0.0.32 | Parses every file upload, on the unauthenticated-by-default path |
| `fastapi` (→ `starlette`) | 0.115.6 (0.41.3) | 0.141.1 (1.3.1) | The ASGI layer itself; 9 advisories |
| `requests` | 2.32.3 | 2.34.2 | HTTP client |
| `nltk` | 3.8.1 | 3.10.3 | 19 advisories |
| `streamlit` | 1.52.0 | 1.61.1 | Frontend |
| `python-dotenv` | 1.0.1 | 1.2.2 | — |
| `pytest` / `pytest-asyncio` | 8.3.3 / 0.24.0 | 9.1.1 / 1.3.0 | Dev only. `pytest-asyncio` had to move too: 0.24 pins `pytest<9` |
| `beautifulsoup4` | 4.12.3 | *removed* | Only used by the deleted URL processor |

**Still outstanding** — all need functional testing against real documents, which
is why they were not bundled into a security pass:

| Package | Pinned | Vulns | Fix | Note |
|---|---|---|---|---|
| `pillow` | 11.3.0 | 25 | 12.3.0 | Transitive (docling/paddleocr/pandas). Image decoding in the OCR path, so attacker-supplied input reaches it — but a major bump under the OCR stack. Pinning it explicitly would also change the dependency contract. |
| `transformers` | 4.53.3 | 12 | 5.5.0 | Major bump; drives the reranker. Needs model-loading verification. |
| `docling` | 2.54.0 | 10 | 2.94.0 | 40 minor versions; core to document conversion. |
| `lxml` | 5.4.0 | 2 | 6.1.0 | Transitive; no longer used for HTML parsing now that URL ingestion is gone. |
| `PyPDF2` | 3.0.1 | 1 | — | Deprecated fork; see section B. |

CI runs `pip-audit` on every push (advisory, non-blocking) and Dependabot opens
weekly upgrade PRs, so this stays visible rather than drifting.

### B. `PyPDF2` is deprecated — MEDIUM

`PyPDF2` is an unmaintained fork; the maintained successor is `pypdf` (the
"fix version 3.9.0" reported by the audit is a `pypdf` version — there is no
`PyPDF2` release to upgrade to). It receives no further security patches, and it
parses attacker-supplied PDFs. Migration is mostly an import rename but needs
testing against real PDFs, so it was left out of this pass.

### C. No decompression-bomb or resource caps in document processing — MEDIUM

`core/document_processing/` enforces only a 50MB raw-file cap. There is no
`PIL.Image.MAX_IMAGE_PIXELS` limit, no PDF page-count ceiling, and no
post-decompression size check. `.docx`/`.xlsx` are zip-based and PDFs can carry
highly-compressed streams, so a file under the raw cap can still expand to
GB-scale in memory, and a pathologically-paged PDF drives an unbounded OCR loop.
This is a resource-exhaustion (availability) risk, not data exposure. Adding the
caps is a scoped feature with its own test cases.

### D. Upload allowlist is extension-only — INFORMATIONAL

`is_format_supported()` checks `Path(filename).suffix` against
`ALLOWED_EXTENSIONS` with no magic-byte verification. The allowlist is the
correct primary control and a mislabeled file simply fails to parse downstream;
content sniffing would be defense-in-depth, not a fix for a live hole.

### E. `pickle` for vector-store persistence — LOW

`core/storage/vector_store.py` uses `pickle.load`/`pickle.dump` on
`data/vectors/vector_store.pkl`. The path is fixed and server-side — never
derived from request input — so this is not remotely exploitable today. It is
recorded because pickle is unsafe by construction: if a future feature (backup
restore, object-storage sync, multi-tenant data dir) ever lets an untrusted
actor influence that file, it becomes remote code execution. Prefer a
non-executable format if that persistence layer is revisited.

### F. Rate limiting is per-process and off by default — INFORMATIONAL

`RATE_LIMIT_ENABLED` defaults to `False`, and the counters are per worker
process, so limits multiply by `UVICORN_WORKERS`. Documented in the middleware
docstring already. Use an edge proxy or shared store for a cluster-wide limit.

---

## Verified as sound (no action)

- **No secrets logged.** API keys are read via `os.getenv` and passed straight
  into SDK constructors; no logging statement references a key value.
  `.env.example` contains only placeholders.
- **No path traversal.** The only user-controlled string reaching a filesystem
  path is the upload filename used for the chunk directory name, and it goes
  through `sanitize_filename()` first, which strips `/\<>:"|?*`. Uploaded bytes
  are processed in memory and never written under an attacker-chosen path.
- **API key comparison is timing-safe** — `hmac.compare_digest`.
- **Container hardening** — non-root `app` user, `no-new-privileges`,
  read-only SSL mount, `tmpfs /tmp` with `noexec,nosuid`.
- **Security headers** — `X-Content-Type-Options`, `X-Frame-Options`,
  `Referrer-Policy` set by `SecurityHeadersMiddleware`.

---

## Deployment checklist

1. Set `API_KEY` unless the service is on a trusted private network. Without it
   there is **no authentication on any endpoint**.
2. Keep `DESTRUCTIVE_CLEANUP_ENABLED=false` outside maintenance windows.
3. Set `RATE_LIMIT_ENABLED=true` for any internet-facing deployment.
4. Narrow `CORS_ORIGINS` to real origins; leave `CORS_ALLOW_CREDENTIALS=false`
   unless you have narrowed origins first.
5. Confirm `DEBUG=false`.
6. Work through the dependency upgrades in section A.
