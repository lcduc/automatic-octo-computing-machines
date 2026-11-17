# Dashboard monitoring — plan

## Why this exists
The admin Overview answers "is it up and what does it cost". A client deployment also gets asked:
**is it helping customers** (containment, gaps), **is it right** (grounding, feedback trend), **can support
keep up** (handoff timings), and, for us as the vendor, **why it is slow or failing** (per-step latency,
error causes, resource history). This plan covers all of that in three tiers, ordered by cost:

| Tier | What | New storage | Size |
|---|---|---|---|
| 1 | Show and add metrics computed from columns we **already store** | None (new keys inside `metrics_daily.breakdown` JSONB) | Mostly frontend |
| 2 | Client-value views: unanswered-question clusters (ADM-11), document health, traffic, visitors | One table (`question_clusters`) | Backend + frontend |
| 3 | Data we **don't collect yet**: handoff timings, error causes, resource history, job/backup status | Columns + two small tables, migrations | Backend + ops |

## Rules every slice follows
- **Rollup first.** Anything charted over time goes into `MetricsRepository.aggregate()` so it survives the
  retention purge (RET-R4). Only "right now" or "within retention" views query raw tables, and the page
  says so ("last 90 days").
- **Breakdown keys, not columns.** New daily aggregates go in `metrics_daily.breakdown` (JSONB), so they need no
  migration. Rows written before a key existed don't have it, so the UI shows "—" instead of 0. The rollup
  only recomputes the last `RECOMPUTED_DAYS`. A one-off `scripts/` backfill re-runs `rollup_day` for days
  whose raw data is still inside retention.
- **No PII in aggregates.** Counts and percentiles only. Visitors are counted by `end_user_id`, never stored.
  Cluster labels use the already-redacted message text.
- **Additive API.** New optional fields on `/admin/usage/summary` and `/admin/usage/history`, plus new endpoints
  under `/api/v1/admin/...`. `docs/api.md` + `openapi.json` regenerate in the same change (CQ-16).
- **Admin UI.** Every label goes in both `i18n/en.ts` and `i18n/vi.ts`. Charts follow the existing `TokenChart`
  pattern.

## Page layout
The Overview page is already full. Split it into tabs (same route, `?tab=`), each answering one question:

| Tab | Reader | Contents |
|---|---|---|
| **Overview** (business) | Client manager | Containment, conversations/visitors, cost per resolved conversation, projected month-end spend, top intents, traffic heatmap |
| **Quality** | Content editor | Thumbs-down rate, grounded rate, low-confidence rate, cache hit rate, question gaps (ADM-11), document health |
| **Support** | Support lead | Open queue now, time to first response, time to close, SLA breaches, handoff reasons, per-agent load, out-of-hours share |
| **System** | Vendor / ops | Today's system card + per-step latency, TTFT, errors by cause, guard/rate-limit rejections, GPU/disk/DB history, job and backup status |

The live feed and monthly history stay on Overview.

**Support tab dropped (2026-11-17, owner review).** The handoff queue page already serves the support lead, so
the tab and its handoff count/reasons cards were removed. Slice 8's timings go on the Handoffs page instead.
On Overview the cards are ordered: request types, busiest hours, visitors by tier, cost by tier. The
helpful/not-helpful KPI was removed from Quality; the not-helpful rate stays.

---

## Tier 1 — surface what we already store

| Metric | Definition | Source | Change |
|---|---|---|---|
| TTFT p95 | first token latency | `metrics_daily.p95_first_token_ms` (already rolled up) | Frontend only (latency card hint + System chart) |
| Per-step latency p50/p95 | `guard`, `router`, `intent`, `rewrite`, `retrieval`, `generation` | `MessageTrace.steps_ms` | Breakdown key `step_latency_ms: {step: {p50, p95}}`; separates "LLM slow" from "we are slow" |
| Handoff reasons | count per reason | `breakdown.handoff_reasons` (already there) | Frontend chart (Support) |
| Intents / routes trend | count per intent per day | `breakdown.intents`, `breakdown.routes` (already there) | Frontend stacked chart (Overview) |
| Cost by tier, tokens by purpose | — | already in breakdown | Frontend (System or Overview cost card) |
| Containment rate | `1 − conversations_with_handoff / conversations` | `HandoffRequest.conversation_id` | Breakdown key `conversations_handed_off` (distinct conversations with a request created that day) |
| Unanswered share | `(denied + handoff) / turns` (today's definition) | `breakdown.outcomes` | Keep; label it per turn so it isn't confused with containment |
| Thumbs-down rate | `negative / (positive + negative)` and `negative / answered` | `breakdown.feedback` | Frontend (Quality trend) |
| Grounded rate | answered turns with ≥1 citation / answered turns | `Message.citations` | Breakdown key `cited_answers` |
| Low-confidence rate | answered turns with `confidence < LOW_CONFIDENCE` (0.35, `services/chat_service.py`) | `Message.confidence` | Breakdown key `low_confidence_answers`; move the constant into `core/` (core must not import services) |
| Cache hit rate | `cached` answers / answered | `Message.cached` | Breakdown key `cached_answers` |
| Guard rejections + coarse error causes | count per `guard_reason` (also `timeout` / `error` / `no_result` / aborted on error turns, set in `core/agent/chatbot.py` and `ChatService`) | `Message.guard_reason` | Breakdown key `guard_reasons` |
| Cost per conversation / per resolved conversation | `cost / conversations`, `cost / (conversations − handed_off)` | rollup | Frontend |
| Projected month-end spend | `month_spend / elapsed_days × days_in_month` vs spend alert threshold | `UsageService.month_spend()` + spend setting | Field on `/usage/summary` |
| Security summary | PII reveals, API-key actions, admin deletions in the period | `audit_log` | `GET /admin/audit/summary` (counts by action); owner-only like the audit viewer |

---

## Tier 2 — client-value views

### 2a. Unanswered-question clusters (ADM-11)
Clients get the most out of this view: it lists what people asked that the bot couldn't answer, which
tells them what content to write next. It is also the input for the KB curator (`KB_CURATOR_AGENT_PLAN.md`).

- **Input.** The user message right before an assistant message with outcome `denied` or `handoff`, plus
  thumbs-down answers. Only within retention. Text is already PII-redacted.
- **Job.** A new worker job `question_clusters`, nightly, after `metrics_rollup`. It embeds new inputs with the
  existing embedding model and assigns each to the nearest open cluster centroid when its cosine similarity is
  at least `CLUSTER_SIMILARITY` (a module constant). Otherwise it starts a new cluster.
  `# ceiling: greedy centroid assignment, O(inputs × clusters); move to HDBSCAN/pgvector ANN if clusters > ~5k`.
- **Table `question_clusters`.** `id`, `label` (the most central redacted question), `centroid` (vector),
  `count`, `first_seen`, `last_seen`, `status` (`open` / `reviewed` / `dismissed` / `covered`), `reviewed_by`.
  A link table `question_cluster_members(cluster_id, message_id ON DELETE CASCADE)`, so the retention purge
  removes members while counts stay.
- **UI.** A "Gaps" section in Quality: clusters sorted by count in the period, with a sparkline. A click opens
  the sample conversations. Actions: mark reviewed / dismiss / "covered by document X" / add to eval set
  (reuse ADM-12).
- **Privacy.** Add a row to `privacy-data-flows.md`. Labels are redacted text, so they fall under the same
  retention as traces. The label is refreshed from a live member, or the cluster is dropped when it has no
  members left.

### 2b. Document health
`GET /admin/knowledge/health`, computed over the retention window:
- Most cited documents, and documents never cited in the window. Counted with `jsonb_array_elements` over
  `Message.citations`, next to the single-document lookup ADM-18 uses
  (`ConversationRepository.answers_citing`).
- Documents with `effective_to` in the next 30 days, documents in a future `effective_from`, disabled documents.
- Documents linked to thumbs-down answers (count).

### 2c. Traffic heatmap
Hour of day × weekday, in the app time zone, from `Message.created_at` (user messages) over the last N days,
limited to retention. Field on `/usage/summary`. Used to staff support and to check working hours.

### 2d. Visitors (part of ADM-03)
Rollup breakdown keys:
- `visitors`: distinct `end_user_id`
- `returning_visitors`: had a conversation before that day
- `visitors_by_tier`: from `TokenUsage.tier`
- `single_turn_conversations`: one assistant reply, no follow-up, no handoff — an abandonment proxy

Turns per conversation = `turns / conversations` (frontend).

---

## Tier 3 — new collection

### 3a. Handoff timings (Handoffs page)
Today `HandoffRequest` has `created_at`, `assigned_to`, `answered_at`, `closed_at` and `due_at`, but no
**assigned** timestamp.
- Migration: `assigned_at`, set by `HandoffService` when the request is assigned.
- First response = the earlier of `answered_at` and the first `agent_reply` message in the conversation after
  `created_at`.
- Rollup breakdown `handoff_ops`: p50/p90 of time to assign, time to first response and time to close; SLA breaches
  (`first response > due_at`); out-of-hours share (using the working-hours settings); count per `assigned_to`.
- "Right now" fields on `/usage/summary`: open queue size and age of the oldest open request.
  The overdue alert rule already gets these from `MonitoringRepository.overdue_tickets`, so reuse that call.

### 3b. Error causes
Error turns already record a coarse cause in `guard_reason` (Tier 1). But `"error"` covers every exception
caught in `core/agent/chatbot.py`.
- No migration: in that `except`, write a finer value into `guard_reason` based on the exception class:
  `llm_rate_limited`, `llm_error`, `retrieval_error`, `tool_error`, `internal`. `timeout` already exists.
  Update the admin outcome filter / any code matching `"error"` in the same change.
- Rollup breakdown `fallback_activations` (how often fallback mode kicked in). The error split itself comes
  from `guard_reasons`.
- The IP rate-limit middleware and `RateLimitService.hit` keep an in-process counter of rejections per window,
  shown as a "right now" value on System. `# ceiling: per-process counter, lost on restart; persist via usage_counters if it must be charted`.
- Failed admin logins (`routes/admin/auth.py` raises 401 without a record): count them in the same counter,
  and audit-log 5+ failures per account per 15 min.

### 3c. Resource history
- New table `system_samples(ts, gpu_util_pct, vram_used_mb, vram_total_mb, disk_used_pct, db_bytes)`. The
  existing `alert_checks` job writes it every 5 minutes, since it already reads disk and model-server status.
- 30 days kept raw by the retention purge. The daily rollup adds `vram_peak_mb` and `disk_used_pct_max` to the
  breakdown so the trend outlives the samples.
- System tab: 24 h / 7 d / 30 d charts.

### 3d. Job and backup status
- `JobScheduler` doesn't persist runs. New table `job_status(name PK, last_started_at, last_success_at,
  last_error, last_duration_ms)`, written in `run_now`. System shows one row per job, red when
  `last_success_at` is older than twice the job's interval.
- Backups run on the host (`/etc/cron.d/chatbot`), outside the app. The `chatbot backup` ops command reports
  its result to `POST /api/v1/admin/system/backup-status` with a dedicated write-scoped API key, and the same
  table stores it as job `backup`.
- TLS expiry: `alert_checks` reads the certificate of both public domains, stores the days left in
  `job_status`, and alerts below 14 days.

### 3e. External uptime (OBS-05)
An ops task, not code: set up the vendor Uptime Kuma monitor per `deployment.md`. Listed here so it isn't
forgotten.

---

## Slices (each ends green: `ruff check .`, relevant pytest, admin `npm run build` + tests)
| # | Slice | Done when |
|---|---|---|
| 1 | Overview tabs + Tier-1 frontend-only metrics (TTFT, handoff reasons, intents, cost by tier, feedback rate, cost per conversation) | Four tabs render from the existing API; en/vi keys present |
| 2 | Tier-1 rollup keys (`conversations_handed_off`, `cited_answers`, `low_confidence_answers`, `cached_answers`, `guard_reasons`, `step_latency_ms`) + backfill script + month-end projection | `test_metrics_repository` covers each key; history shows "—" for days before the key existed |
| 3 | Audit summary endpoint + Security tile | Owner-only; test for the role check |
| 4 | Visitors + traffic heatmap | Rollup keys tested; heatmap in app TZ tested across midnight |
| 5 | Document health endpoint + Quality section | Uses the ADM-18 query; expiring/never-cited tested |
| 6 | `question_clusters` tables + job | Unit test: near-duplicates join one cluster, unrelated questions don't; purge cascade tested |
| 7 | Gaps UI + review actions + eval-set link | Mark reviewed/dismissed/covered works end to end |
| 8 | Handoff `assigned_at` + `handoff_ops` rollup + timings on the Handoffs page | Timings tested on fixed timestamps incl. out-of-hours |
| 9 | Finer error `guard_reason` + `fallback_activations` + rejection counters | Each exception class maps to one reason (test) |
| 10 | `system_samples` + resource charts | Sampler writes on `alert_checks`; purge keeps 30 days |
| 11 | `job_status` + backup-status endpoint + TLS expiry | Stale job shows red; backup POST needs its scope |

Slices 1–5 need no migration. Each slice updates the touched folders' READMEs and the checklist marks below.

### Slice 1 in detail (frontend only, `frontends/admin/src/`)
**Data.** `OverviewPage` loads `usage/summary?days=N` (raw rows, exact for the period) and
`usage/history?days=N` (daily rollup). The period selector drives both. The four panels get
`{ summary, history }` and render nothing of their own until both have loaded.
Rule: counts that exist on raw rows come from `summary`. Handoff requests, routes and first-token latency
only exist in the rollup, so they come from `history`.

Intents are only `rag` / `action` / `login`, which tells a client nothing, so **routes** stand in as
"request types". Real topics arrive with the clusters in slice 6.

**Shared pieces** (written first, so the panels can be built in parallel without touching the same files):

| File | Holds |
|---|---|
| `pages/overview/rollup.ts` (+ `rollup.test.ts`) | `OverviewData` type; `sumBreakdown(history, key)` sums a `breakdown` dict across days, skipping missing or malformed keys; `sumDaily(history, field)`; `slowestDay(history, field)` (max of the daily p95s, `null` when none); `share(part, whole)` (`null` when `whole` is 0); `usd(micro)` |
| `pages/overview/BreakdownBars.tsx` | Sorted horizontal bars for one `{key: count}` dict: label, value, share of total; empty text when no data |
| `lib/labels.ts` | `handoffReasonLabel` (moved out of `HandoffsPage`), `routeLabel` (new, falls back to `route.other`) |
| `lib/types.ts` | `ROUTES` constant mirroring `backend/app/models/turn_trace.py` |
| `styles/components.css` | `.breakdown*`, `.chart__first-token`, `.legend--first-token` |
| `i18n/vi.ts`, `i18n/en.ts` | Every new key for all four panels (listed in the panel table) |

**Panels** (`?tab=` like `KnowledgePage`; no param = Overview):

| File | KPIs | Cards |
|---|---|---|
| `BusinessTab.tsx` | Conversations (hint: answers, answers per conversation) · Cost in period (hint: this month) · Cost per conversation (hint: tokens) · Not answered (existing) | Request types (`routes`, BreakdownBars) · Cost by user tier (`summary.by_tier`) + tokens by purpose · Live activity · Monthly history |
| `QualityTab.tsx` | Answered share (`answered / turns`) · Helpful / not helpful (existing) · Not-helpful rate (`negative / ratings`) | Answer outcomes as BreakdownBars |
| `SupportTab.tsx` | Handoff requests (`Σ history.handoffs`, hint: share of turns) | Handoff reasons (`handoff_reasons`, BreakdownBars) · Link to `/handoffs` |
| `SystemTab.tsx` | Response time p95 (existing) · First token p95 (slowest day) · Error rate (`outcomes.error / turns`) · Indexed chunks (existing) | Latency per day chart (`LatencyChart.tsx`: daily p95 full answer vs first token) · Tokens per day (existing) · System status + maintenance (moved as is, still fetches `system` itself) |

**Done when.** The four tabs render against the smoke-test fixtures (a `usage/history` fixture gets added);
`rollup.test.ts` passes; `npm run typecheck`, `lint`, `test` and `build` pass; checked in the browser in both
themes and at phone width.

### Slice 2 in detail (backend rollup keys + their display)
**Contract.** New `metrics_daily.breakdown` keys, written for every day the rollup computes:

| Key | Shape | Definition (assistant messages / traces created that day) |
|---|---|---|
| `conversations_handed_off` | int | distinct `conversation_id` of `HandoffRequest` rows created that day |
| `cited_answers` | int | outcome `answered` with a non-empty `citations` array |
| `low_confidence_answers` | int | outcome `answered`, `confidence < LOW_CONFIDENCE` (constant moved to `models/chat_turn.py`) |
| `cached_answers` | int | outcome `answered`, `cached` |
| `guard_reasons` | `{reason: int}` | every non-null `guard_reason` (refusals and error causes) |
| `step_latency_ms` | `{step: {"p50": float, "p95": float}}` | every integer key of `MessageTrace.steps_ms` |

The denominator for the three answer rates is `breakdown.outcomes.answered`.
`/usage/summary` → `month` gains `projected_cost_micro_usd` and `spend_cap_micro_usd` (0 means no cap).
`projected_cost_micro_usd` is a linear projection: spend so far ÷ elapsed share of the month. It is `null`
during the first day of the month.

**Display.** The rates are computed only over days whose row has the key, so days rolled up before this slice
show "—" instead of 0:
- Overview: containment (`1 − handed_off / conversations`), cost per resolved conversation, projected spend
  vs. cap.
- Quality: grounded rate, low-confidence rate, cache hit rate.
- System: guard/error reasons, and time per pipeline step (p50/p95, slowest day).

**Backfill.** `python -m scripts.backfill_metrics --days N` (default 90, the trace retention) re-runs
`rollup_day`. `--days` is capped at the shortest chat/trace retention: re-running an already purged day would
overwrite its rollup, the only history left, with near-zero counts. `step_latency_ms` only reads values matching
`^[0-9]{1,9}$`, so a malformed or oversized value can't break the integer cast.

**Done when.** The rollup integration test asserts every new key; a unit test covers the projection; ruff, pytest and
the admin checks pass; the new figures show "—" for a day without the keys.

### Slices 3–5 in detail (contracts)
**Slice 3: `GET /api/v1/admin/audit/summary?days=N`** (owner only, like `/audit`; `days` 1–90, default 30).
Counts come from `admin_audit` by method, path and status. The middleware also records logins, including
failures.
```json
{"since": "iso", "logins_failed": 0, "logins_succeeded": 0, "contact_reveals": 0, "api_key_changes": 0,
 "account_changes": 0, "deletions": 0, "data_subject_requests": 0, "legal_hold_changes": 0, "denied": 0,
 "failed_login_ips": [{"client_ip": "10.0.0.1", "count": 3}]}
```
- `failed_login_ips`: top 5 by count.
- Failed login = `POST …/auth/login` → 401.
- Denied = any audited request → 403.
- Every other category counts 2xx responses only.

**Slice 4: visitors and traffic.** One query method `MetricsRepository.visitor_stats(start, end)` serves both the
rollup (daily breakdown keys) and `/usage/summary` (exact counts for the period):
- `visitors`: distinct `end_user_id` with a message in the window.
- `returning_visitors`: those who had a conversation created before the window.
- `visitors_by_tier`: `{tier: distinct end_user_id}` from `token_usage`.
- `single_turn_conversations`: conversations created in the window with exactly one assistant message and no
  handoff request.

`/usage/summary` gains `visitors: {total, returning, by_tier}`, `single_turn_conversations`, and
`traffic: int[7][24]`: user messages per weekday (Monday first) × local hour.

**Slice 5: `GET /api/v1/admin/knowledge/health?days=N&limit=M`** (read roles; `days` 1–90, default 30; `limit`
1–50, default 10). It is computed over citations in the window, so it is bounded by chat retention.
```json
{"since": "iso", "documents": 0, "disabled": 0, "failed": 0,
 "most_cited": [{"document_id": "", "title": "", "citations": 0}],
 "never_cited": {"count": 0, "items": [{"document_id": "", "title": "", "created_at": "iso"}]},
 "not_helpful": [{"document_id": "", "title": "", "count": 0}],
 "expiring": [{"document_id": "", "title": "", "effective_to": "date"}],
 "scheduled": [{"document_id": "", "title": "", "effective_from": "date"}]}
```
- `documents`: enabled, ready and approved.
- `never_cited`: of those, the ones created before `since` and not cited in the window.
- `not_helpful`: documents cited by thumbs-down answers.
- `expiring`: enabled, with `effective_to` within 30 days.
- `scheduled`: `effective_from` after today.

**Display.**
- Overview: a visitors KPI, a visitors-by-tier card and the traffic heatmap. Monthly history gains a
  visitors/day column.
- Quality: the single-turn ("left after one answer") rate and a document-health section, fetched on its own
  over a fixed 30 days.
- System: an owner-only security card, linked to the audit log.

## Checklist items this closes
- **ADM-03** `[~]` → `[x]` after slices 1, 2, 4 (tiers, TTFT, resolution rate, handoff by reason).
- **ADM-11** `[ ]` → `[x]` after slices 6–7.
- **OBS-03** `[~]` → `[x]` after slices 1 and 10 (TTFT charted, VRAM history).
- **OBS-05** is ops (3e).
- Add new items to `production.md`:
  - ADM-22 document health
  - ADM-23 support timings
  - OBS-07 error causes
  - OBS-08 job/backup status

## Open questions (client-specific, decide per deployment)
- Is containment "no handoff", or "no handoff **and** no thumbs-down"? The plan uses the first; the second is
  one more breakdown key.
- SLA target per client: `due_at` already exists. Confirm it is set for every request, not only for tickets.
- Is the visitor count by `end_user_id` acceptable under the client's privacy notice? It is a count only, but
  the notice may need to mention analytics.
