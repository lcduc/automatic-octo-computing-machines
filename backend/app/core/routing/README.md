# `backend/app/core/routing/`

<!-- Keep this README true. Anyone (person or agent) who adds, removes or renames a file here,
     or hits a problem worth remembering, updates the matching section in the same PR. -->

## Purpose
The embedding router: sorts a message by meaning into greeting, thanks, handoff request, ambiguous,
off topic or a real question (`rag_question`), with no LLM call. It embeds the message with the
retriever's embedding model and compares it with example messages per route. When unsure it says
`rag_question`: a missed shortcut costs one retrieval, a wrong shortcut refuses or misroutes a real
question. What to do with each route (canned reply, clarify, handoff) is decided by `ChatbotService`
in [`../agent/`](../agent/); rule-based screening is in [`../guardrails/`](../guardrails/).

Spec: [`docs/CHATBOT_ROUTING_SPEC.md`](../../../../docs/CHATBOT_ROUTING_SPEC.md) (stage S3, rules
`R*`, fast-path rule `F3`, deviation `DV1` for the LLM `IntentRouter`).

## Files

| File | Public names | What it does |
|---|---|---|
| `__init__.py` | — | Empty. |
| `embedding_router.py` | `EmbeddingRouter`, `RouteDecision`, `RouteIntent`, `with_accent_free_forms`, `DEFAULT_THRESHOLDS`, `SHORT_ONLY`, `ACCENT_FREE_ROUTES`, `SHORT_MESSAGE_MAX_CHARS`, `ROUTES_FILE` | Embeds every example once (thread-safe, first use), then `classify` picks the closest route if it clears its threshold and leads the runner-up by `ROUTE_MARGIN`; `RouteDecision.is_off_topic` is the second off-topic test used after an empty retrieval. |
| `routes.json` | — | Example messages per route (`greeting` 20, `thanks` 18, `handoff_request` 22, `ambiguous` 20, `off_topic` 40, `rag_question` 39). Edit examples, never thresholds, to change what a route catches. |

Decision rules in `EmbeddingRouter`:
- Greeting, thanks and ambiguous only apply to messages up to `SHORT_MESSAGE_MAX_CHARS` (40), so
  "hi, delete my account" is a question (spec `F3`).
- Thresholds: `DEFAULT_THRESHOLDS` (0.90, off topic 0.93), overridable per route with
  `ROUTE_<NAME>_THRESHOLD`; margin `ROUTE_MARGIN` (0.01). Off-topic after empty retrieval:
  `ROUTE_OFF_TOPIC_LEAD`, `ROUTE_OFF_TOPIC_MAX_RERANK`, `ROUTE_OFF_TOPIC_MIN_LEAD` (`Config.Routing`).
- Every route except `handoff_request` also matches accent-free copies of its examples.

## Dependencies
- May import: `app.config.settings`, `app.utils.text_utils`, `numpy`. Layering: api -> services ->
  core -> models/utils; config at the bottom; only main.py imports middleware; enforced by
  `test/unit/test_layering.py`.
- Used by: `core/agent/chatbot.py` (`classify` in a worker thread), `core/agent/knowledge_answerer.py`
  (`RouteDecision.is_off_topic`), `app/api/container.py` (builds it over the shared embedding service),
  `scripts/eval/router.py`, `scripts/eval/robustness.py`, `scripts/eval/router_classifier.py`.
- External: the embedding model through the injected service (in-process or model-server); default
  `intfloat/multilingual-e5-small`. Thresholds are calibrated for that model.

## Run / test
From `backend/` with `venv` active:
```
pytest test/unit/test_embedding_router.py test/unit/test_chat_pipeline.py
python -m scripts.eval.router                       # labelled eval: accuracy, confusion matrix, stolen questions
python -m scripts.eval.router --check \
  --golden-set scripts/demo_data/golden_colloquial_dev.json \
  --golden-set scripts/demo_data/golden_colloquial_holdout.json \
  --golden-set scripts/demo_data/golden_queries.json
python -m scripts.eval.router --write-baseline      # after an intended change; commit scripts/demo_data/eval_baseline.json
```
**Router eval gate (CI):** the backend CI job runs `python -m scripts.eval.router --check` with the three
golden sets above. It fails when any real question is taken by a shortcut, or accuracy drops more than
`max(2%, 2 messages)` below the committed baseline (`scripts/eval/baseline.py`). It needs only the
e5-small model (cached in CI), no LLM and no secrets. Re-run it after every `routes.json` edit.

## Known problems and history
- Added with the chat routing rework: route by meaning before retrieval, hand off when the documents
  do not answer (lcduc/automatic-octo-computing-machines#25, e9f71e5, 2026-10-01).
- Unaccented Vietnamese scored far below the thresholds (0 of 40 off-topic messages caught with
  accents stripped) -> accent-free copies of examples added at load time, `routes.json` keeps one
  spelling. Router eval with accents stripped: accuracy 74.1% -> 86.2%, off topic 0 -> 19 of 40, no real
  question stolen. `handoff_request` is left out: the guard already catches unaccented handoff
  requests, and its stripped examples pulled two long unaccented questions into a handoff (0.902 and
  0.909 against 0.90) (lcduc/automatic-octo-computing-machines#57, 7e44c74, 2026-10-24).
- A fine-tuned e5-small embedder dropped router accuracy to 79-82% because the cosine thresholds are
  calibrated on the base model -> changing `EMBEDDING_MODEL` means recalibrating thresholds
  (lcduc/automatic-octo-computing-machines#55, 7b055c6, 2026-10-24;
  [`docs/reports/SYNTHETIC_FINETUNE_RESULTS.md`](../../../../docs/reports/SYNTHETIC_FINETUNE_RESULTS.md)).
- Eval scripts moved from `scripts/` to `scripts/eval/` (imports must be `from scripts.eval import x`);
  backend moved under `backend/app`, this folder used to be `core/routing/`
  (lcduc/automatic-octo-computing-machines#76, 30cfa1c and 06f0477, 2026-11-10).

## Status
- Last reviewed: 2026-11-10
- Open issues / follow-ups: none recorded.
- Ceilings (`# ceiling:` markers in this folder): none.
