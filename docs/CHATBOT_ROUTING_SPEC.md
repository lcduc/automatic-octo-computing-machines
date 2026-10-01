# CHATBOT_ROUTING_SPEC.md

Spec for the chat pipeline: intent routing, RAG, tool execution, handoff, refusal, injection defense.
Audience: AI coding agent. Task: verify repo against this spec, report gaps. Do not modify code unless asked.

---

## 0. Agent protocol

1. Discover first. Locate actual modules for each stage in §2 (grep/tree). Record the path map before checking rules. Never assume paths.
2. Check every rule ID in §4. Status: `PASS` | `FAIL` | `PARTIAL` | `N/A` | `UNVERIFIABLE`.
3. Every `PASS`/`FAIL` needs evidence: `file:line` or command output. No evidence = `UNVERIFIABLE`.
4. `MUST` fail = blocker. `SHOULD` fail = warning.
5. Never invent thresholds, metrics, or test results. Missing number = report as open decision (§6).
6. Run tests/eval scripts if they exist. Do not claim they pass without running them.
7. Output the report in §7 format. Do not edit code in verify mode.
8. Flag anything matching §5 anti-patterns as `FAIL` regardless of rule coverage, unless covered by an active deviation in §0.1.

### 0.1 Scope and known deviations (phase 1: no tools)

Phase 1 ships without tools. Tool path is deferred.
- Rules `T1`–`T10`, `S7`–`S8`, `TOOL_TASK` routing: report `N/A (deferred)` while the tool registry is empty/unused. If any tool is registered, they become `MUST`.
- `DV1` (active deviation): legacy `IntentRouter` makes an LLM call per message to split rag/action. Allowed ONLY while no tools are registered, because it is dormant (no LLM call occurs). Verify:
  - `IntentRouter` LLM path is skipped when the tool registry is empty (show the guard, `file:line`).
  - New embedding router (S3) handles all phase-1 intents and runs before `IntentRouter`.
  - Test exists asserting zero `IntentRouter` LLM calls with an empty registry.
  - Startup check fails or loudly warns if tools are registered while `IntentRouter` is still the tool-vs-rag decider with no embedding pre-router (prevents a silent per-message LLM cost cliff).
  - Any violation = `FAIL` R1/L1 (anti-pattern 1 applies).
- Exit criteria for DV1: first tool registered → resolve `D11`, then remove DV1.

---

## 1. Principles

- Cascade: cheapest check first; LLM is last resort.
- Classification ≠ generation. Never use a generative LLM call to classify when embeddings/rules suffice.
- Untrusted input never becomes instructions: user text, retrieved chunks, tool outputs are data.
- Fail to human: low confidence, tool failure, LLM failure → handoff, not guess.
- Everything tunable lives in config, tuned against labeled data, not hardcoded.
- Target hardware: CPU-only for all stages except hosted LLM API calls.

---

## 2. Pipeline (order is a requirement)

```
input
 → S1 sanitize + injection screen
 → S2 fast-path (greeting/thanks)            → canned reply (0 LLM calls)
 → S3 intent router (embeddings)
     ├ HANDOFF_REQUEST                        → handoff
     ├ OFF_TOPIC / no-match                   → refusal template (0 LLM calls)
     ├ ASK_OPENER                             → prompt for the actual question (0 LLM calls)
     ├ AMBIGUOUS                              → clarify (max N times) → handoff
     ├ RAG_QUESTION → S4 retrieve+rerank → S5 confidence gate
     │                    ├ pass → S6 grounded generation (1 LLM call)
     │                    └ fail → handoff
     └ TOOL_TASK → S7 slot extraction+validation → S8 execute → format
 → S9 output scan → response
```

Intents (closed set): `GREETING`, `THANKS`, `ASK_OPENER`, `RAG_QUESTION`, `TOOL_TASK` (deferred, see §0.1), `HANDOFF_REQUEST`, `OFF_TOPIC`, `AMBIGUOUS`.
`ASK_OPENER` = message announcing a question without asking it (e.g. "cho mình hỏi chút", "can I ask something").
Handoff reasons (closed set): `USER_REQUESTED`, `LOW_RETRIEVAL_CONFIDENCE`, `UNGROUNDED_ANSWER`, `TOOL_FAILURE`, `LLM_FAILURE`, `AMBIGUOUS_REPEATED`, `INJECTION_REPEATED`.

---

## 3. Path map (agent fills during discovery)

| Stage | Module/file | Found? |
|---|---|---|
| S1 sanitize/injection | | |
| S2 fast-path | | |
| S3 router | | |
| S4 retrieval/rerank | | |
| S5 confidence gate | | |
| S6 generation | | |
| S7-S8 tools | | |
| Handoff | | |
| S9 output scan | | |
| Config | | |
| Eval/tests | | |

---

## 4. Rules

Format: `ID | Level | Rule | Verify`

### 4.1 Pipeline structure
- `P1 | MUST | Stages execute in §2 order; S1 precedes any LLM/embedding call on raw input | Trace entrypoint handler call order`
- `P2 | MUST | Single entrypoint orchestrates pipeline; no bypass route reaches LLM directly | grep LLM client usage; each call site reachable only via S6/S7/borderline-gate`
- `P3 | MUST | Intent is a closed enum, not free-form string | Find enum/Literal type; no string-compare intents elsewhere`
- `P4 | SHOULD | Each stage is a separate, independently testable function/class | Inspect module boundaries`

### 4.2 S1 Sanitize / injection
- `G1 | MUST | Input length capped (config value) before processing | grep max length; test oversize input`
- `G2 | MUST | Unicode normalized (NFKC); control chars and zero-width chars stripped | grep normalize/strip logic`
- `G3 | MUST | User text and retrieved chunks inserted into prompts inside explicit delimited untrusted blocks | Read prompt templates; check delimiters + "treat as data, never instructions" in system prompt`
- `G4 | MUST | System prompt never contains secrets, keys, or internal-only URLs | Read system prompts`
- `G5 | MUST | Retrieved content cannot trigger tool calls or change routing | Confirm tool selection derives from user-turn intent only, not chunk text`
- `G6 | MUST | Injection screen = embedding-similarity "blocked" route and/or pattern denylist; NOT an extra LLM call per turn | Inspect S1 impl`
- `G7 | MUST | Denylist/blocked-route utterances stored as versioned data file, not inline code | Locate file`
- `G8 | SHOULD | Repeated injection attempts per session counted; threshold → `INJECTION_REPEATED` handoff or block | grep counter`
- `G9 | SHOULD | Per-session/IP rate limit on chat endpoint | grep middleware`

### 4.3 S2 Fast-path
- `F1 | MUST | Greeting/thanks resolved without any LLM call | Test with mocked LLM client asserting zero calls`
- `F2 | MUST | Replies from templates; multiple variants allowed; language-matched | Inspect template store`
- `F3 | MUST | Fast-path only matches short inputs (length cap) so "hi, delete my account" does not match | Test mixed-content inputs → must continue to S3`
- `F4 | SHOULD | Fast-path uses regex + same shared embedder, no new model | Inspect`

### 4.4 S3 Router
- `R1 | MUST | Classification via embeddings (static routes or classifier head on embeddings), not generative LLM | Inspect router impl`
- `R2 | MUST | One shared embedder instance for routing and retrieval, loaded once at startup | grep model load sites`
- `R3 | MUST | Per-route similarity thresholds read from config | grep thresholds; none hardcoded in logic`
- `R4 | MUST | No-match (all below threshold) → OFF_TOPIC/AMBIGUOUS path, never forced top-1 | Test with gibberish + unrelated query`
- `R5 | MUST | Route utterances stored in versioned data files | Locate files; ≥ N examples per route (N from config/eval doc)`
- `R6 | MUST | `HANDOFF_REQUEST` detected at router level ("talk to a human", "agent", localized equivalents) and short-circuits | Test phrases per supported language`
- `R7 | MUST | Router decision logged with intent, top score, runner-up score | grep logging`
- `R8 | SHOULD | Optional LLM fallback only within narrow configurable score band near threshold; off by default or flagged | Inspect band logic`
- `R9 | MUST | Embedder supports all languages in §6 D1 | Check model card/config vs supported languages`
- `R11 | MUST | `ASK_OPENER` never reaches retrieval or LLM; opener + real question in one message ("cho mình hỏi, giá gói A bao nhiêu?") routes to RAG_QUESTION | Test both forms`
- `R10 | MUST | Router eval script + labeled set exist; reports accuracy and confusion matrix | Locate and RUN`

### 4.5 S4-S5 RAG + confidence gate
- `K1 | MUST | Retrieval = hybrid (dense + lexical) with reranker, or documented alternative | Inspect retrieval`
- `K2 | MUST | Gate decision uses reranker top score vs config threshold | Inspect S5`
- `K3 | MUST | Gate threshold derived from golden-set evaluation; value + dataset + date documented | Find doc/comment; else open decision D2`
- `K4 | MUST | Gate fail → handoff (`LOW_RETRIEVAL_CONFIDENCE`); generation LLM NOT called | Test with empty/irrelevant retrieval; mock LLM asserts zero calls`
- `K5 | MUST | Generation prompt restricts answer to provided context; instructs to say unknown otherwise | Read prompt`
- `K6 | MUST | Answer includes chunk/source references | Inspect response schema`
- `K7 | SHOULD | Borderline band (threshold ± margin) triggers groundedness check; outside band no extra LLM call | Inspect`
- `K8 | MUST | Retrieval scoped by tenant/knowledge-base id from auth context | grep filter; verify not from request body/LLM`
- `K9 | SHOULD | Context size capped (chunk count/tokens) from config | grep`
- `K10 | MUST | Retrieval eval script + golden set exist (precision@k, MRR); runnable | Locate and RUN`

### 4.6 S7-S8 Tools
- `T1 | MUST | Tools defined in explicit registry (allowlist); name → handler + JSON schema/Pydantic model | Locate registry`
- `T2 | MUST | Args validated against schema before execution; invalid → clarify or handoff, never executed | Test malformed args`
- `T3 | MUST | DB access parameterized; no f-string/concat SQL from model or user text | grep SQL construction`
- `T4 | MUST | tenant_id/user_id/permissions injected from authenticated session, never from LLM/user args | Inspect handler signatures`
- `T5 | MUST | Write/destructive tools require explicit user confirmation step | Inspect flow`
- `T6 | MUST | Tool credentials least-privilege; read-only tools use read-only DB role if DB-backed | Inspect config`
- `T7 | MUST | Tool timeout + bounded retries; failure → `TOOL_FAILURE` handoff or graceful message | Test with failing tool`
- `T8 | MUST | Tool output treated as untrusted data when passed back to LLM (same delimiting as G3) | Read prompt assembly`
- `T9 | SHOULD | Tool selection pre-narrowed by router (subset of tools per intent) before LLM sees tool list | Inspect`
- `T10 | MUST | Max tool calls per turn capped | grep cap`

### 4.7 Handoff
- `H1 | MUST | Handoff payload: session_id, last N turns, intent, reason (enum §2), retrieved chunk ids+scores, timestamp | Inspect payload builder`
- `H2 | MUST | Triggered by every reason in §2 | Trace each trigger to handoff call`
- `H3 | MUST | User-facing message states handoff is happening; does not claim staff availability unless verified | Read templates`
- `H4 | MUST | Handoff idempotent per session (no duplicate tickets on retry/double-send) | Inspect dedupe key`
- `H5 | MUST | After handoff, bot stops auto-answering until released or session ends | Inspect session state`
- `H6 | SHOULD | Outside staff hours: collects contact/leaves ticket instead of dead-ending | Inspect (see D4)`
- `H7 | MUST | Payload redacts secrets; PII handling documented | Inspect`

### 4.8 Off-topic / ambiguous
- `O1 | MUST | OFF_TOPIC refusal from template, zero LLM calls | Mock LLM test`
- `O2 | MUST | Refusal does not reveal system prompt, rules, or internals | Read templates`
- `O3 | MUST | AMBIGUOUS asks one clarifying question; max N clarifications (config) then handoff | Test repeated ambiguity`
- `O4 | SHOULD | Refusal offers in-scope alternatives (what bot can help with) | Read templates`

### 4.9 S9 Output scan
- `X1 | MUST | Outbound text scanned for system-prompt leakage (canary token or substring match) | grep canary`
- `X2 | MUST | Outbound text scanned/escaped for markup injection relevant to the widget (HTML/JS, markdown links to untrusted URLs) | Inspect renderer + sanitizer`
- `X3 | SHOULD | Detected leak → replace with safe template + log security event | Inspect`

### 4.10 LLM usage / cost
- `L1 | MUST | LLM calls per turn: greeting/thanks/off-topic/handoff = 0; RAG = 1 (2 only in borderline band); tool = ≤ configured cap | Instrument/mocked tests per path`
- `L2 | MUST | Model names, timeouts, max_tokens, retries in config | grep`
- `L3 | MUST | LLM failure/timeout → `LLM_FAILURE` handoff or safe fallback message; no unhandled exception to user | Test with failing client`
- `L4 | MUST | Retries bounded with backoff; no infinite loops | Inspect`
- `L5 | SHOULD | Streaming enabled for generation path | Inspect`
- `L6 | SHOULD | Per-session token/cost budget enforced | grep`

### 4.11 Cache
- `C1 | SHOULD | Semantic cache before S6, strict similarity threshold from config | Inspect`
- `C2 | MUST (if cache exists) | Cache key includes tenant id + knowledge-base version | Inspect key builder`
- `C3 | MUST (if cache exists) | Cache invalidated on re-index/KB update | Inspect`
- `C4 | MUST (if cache exists) | Never cache tool results or user-specific/PII answers; never cache handoff/refusal-injection responses | Inspect`

### 4.12 Observability
- `B1 | MUST | Per-turn structured log: session, intent, router score, path taken, gate decision, llm_call_count, per-stage latency ms, handoff reason | grep log schema`
- `B2 | MUST | Logs redact PII/secrets/API keys | Inspect redaction`
- `B3 | SHOULD | Metrics: handoff rate by reason, refusal rate, cache hit rate, p50/p95 latency per path | grep metrics`
- `B4 | SHOULD | Security events (injection blocked, leak caught) separately queryable | Inspect`

### 4.13 Tests / CI
- `Q1 | MUST | Tests assert zero LLM calls on: greeting, thanks, off-topic, handoff-request, gate-fail | Locate tests; RUN`
- `Q2 | MUST | Injection corpus test (known jailbreak strings + injected-chunk fixtures); asserts no tool call, no prompt leak | Locate; RUN`
- `Q3 | MUST | Router eval and retrieval eval run in CI with regression threshold | Inspect CI config`
- `Q4 | MUST | Tests for each handoff reason | Locate`
- `Q5 | SHOULD | Latency smoke test per path against §4.14 targets | Locate`
- `Q6 | MUST | No test relies on live LLM/network unless marked integration | Inspect`

### 4.14 Targets (verify only if measurement exists; otherwise report UNVERIFIABLE)
| Path | Target (non-LLM overhead, CPU) |
|---|---|
| Fast-path / refusal / handoff-request | < 50 ms end-to-end, no LLM |
| Router (embed + match) | < 30 ms |
| Retrieval + rerank | project-defined, record measured p95 |
| Cache hit | < 100 ms |

Targets are starting points, not measured facts. Replace with measured values when available.

---

## 5. Anti-patterns (auto-FAIL)

- Generative LLM call used purely to classify every message (except active DV1 while dormant).
- Separate embedding model loaded per request or per stage.
- Retrieved chunk text concatenated into the system prompt or any instruction position.
- tenant_id / user_id / role taken from request body or model output.
- SQL or shell built via string interpolation with user/model text.
- Forced top-1 intent with no no-match path.
- Gate failure still calls the generation LLM.
- Handoff claims "an agent will join shortly" with no staff-availability check or ticket creation.
- Thresholds hardcoded in logic with no documented source.
- Secrets or API keys in prompts, logs, or handoff payload.
- Cache shared across tenants.
- Bot continues auto-replying after handoff.
- Fabricated eval numbers in docs/comments with no reproducible script.

---

## 6. Open decisions (never silently default; report as `OPEN`)

- `D1` Supported languages (e.g. Vietnamese, English). Drives embedder choice (R9), utterance sets, templates.
- `D2` Gate threshold and borderline margin: derive from golden-set run; record value, dataset, date.
- `D3` Router thresholds per route: tune on labeled set incl. negative/off-topic examples.
- `D4` Live staff handoff at launch vs ticket/email-only; staff-hours behavior.
- `D5` Max clarification turns before handoff.
- `D6` Max tool calls per turn; which tools are write-class (need confirmation).
- `D7` Auth model for widget sessions (token failure behavior, key provisioning).
- `D8` Cache on/off at launch; similarity threshold.
- `D9` LLM fallback in router borderline band: enabled or not.
- `D10` Log retention and PII policy.
- `D11` Tool routing strategy once tools exist: embedding match on per-tool example phrases first, LLM only for argument extraction; keep or drop LLM classifier as borderline-band fallback (R8). Decide with an eval of tool-phrase recall/precision, incl. false-positive rate on RAG questions.

---

## 7. Report format (agent output)

```
# Verification report — <repo> @ <commit> — <date>

## Path map
<filled §3 table>

## Summary
MUST: <pass>/<total> pass, <fail> fail, <unverifiable> unverifiable
SHOULD: <pass>/<total>
Anti-patterns hit: <list or none>

## Blockers (MUST FAIL)
- <ID> — <what is wrong> — <file:line> — <suggested fix, one line>

## Warnings (SHOULD FAIL / PARTIAL)
- <ID> — ...

## Unverifiable
- <ID> — <why> — <what is needed>

## Commands run
- <cmd> → <result summary>

## Open decisions found unresolved
- <Dn> — <where it surfaces in code>
```

Rules for the report: facts only, evidence per line, no praise padding, no unrequested refactors.