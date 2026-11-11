# `backend/app/models/`

<!-- Keep this README true. Anyone (person or agent) who adds, removes or renames a file here,
     or hits a problem worth remembering, updates the matching section in the same PR. -->

## Purpose
Internal domain data classes passed between `services/` and `core/`: who is calling, what a chat
turn needs and produces, knowledge chunks and retrieval results, LLM usage, policies. Validation
only, no I/O and no behaviour beyond small helpers. These are NOT the HTTP contract: request and
response models live in `app/api/schemas/`, and services convert between the two. SQLAlchemy
tables live in `core/storage/tables/`.

## Files
| File | Public names | What it does |
|---|---|---|
| `caller.py` | `ChatCaller`, `TIER_ANONYMOUS`, `ANONYMOUS_LEVEL` | Resolved caller of a public chat request: API key id (`None` for the widget server), opaque visitor id, client IP, and `user_id`/`tier` only from a verified host token. |
| `chat_turn.py` | `TurnRequest`, `TurnDelta`, `TurnUsage`, `TurnResult`, `TurnEvent`, `TurnOutcome`, `HandoffReason`, `ChatPolicy`, `or_default`, `FALLBACK_MODE_DENY`, `FALLBACK_MODE_HANDOFF`, `FALLBACK_MODES` | Contract between `ChatService` and the chat pipeline: the request, the streamed events (`TurnEvent = Union[TurnDelta, TurnUsage, TurnResult]`), how a turn ended, why it was handed off, the runtime chat policy; `or_default` returns an admin-set value or the env default. |
| `data_subject.py` | `DataSubject` | The person behind a data-subject request (PRV-03): any of their identifiers, at least one set. |
| `intent.py` | `IntentType` | Which engine a turn goes to: `RAG`, `ACTION` (tool call) or `LOGIN_REQUIRED` (ID-11); produced by `core/agent/intent_router.py`. |
| `knowledge.py` | `ChunkingSpec`, `ChunkDraft`, `ChunkingResult`, `ExtractedDocument`, `IndexedChunk`, `RetrievalResults`, `RetrievedChunk`, `AUTO_STRATEGY`, `EXTRACTION_*` | Chunking strategy + parameters, chunks before embedding, a parsed upload, chunks held by the in-memory index, and retrieval results with scores. |
| `knowledge_bundle.py` | `KnowledgeBundle`, `BundleSource`, `BundleDocument`, `BundleChunk`, `ImportResult`, `BUNDLE_VERSION`, `SOURCE_NAME_PATTERN` | Portable knowledge base (sources, documents, chunk text, no embeddings) for `export-knowledge` / `import-knowledge`. Pydantic, because it is read from and written to JSON. `SOURCE_NAME_PATTERN` is the one definition; `api/schemas/knowledge.py` imports and re-exports it. |
| `llm.py` | `LLMUsage`, `LLMResult`, `StreamDelta` | Provider-neutral LLM call results carrying token usage for cost accounting. |
| `metadata.py` | `NormalizedMetadata`, `MetadataBuilder`, `ProcessingMethod`, `SourceType`, `ProcessingStatus` | Normalized per-document processing metadata (pydantic) built by `core/document_processing/docling_processor.py`. |
| `retention_policy.py` | `RetentionPolicy`, `DEFAULT_*_DAYS`, `MIN_RETENTION_DAYS`, `MAX_RETENTION_DAYS`, `MIN_AUDIT_RETENTION_DAYS` | How long each kind of personal data is kept (PRV-04); owner-editable; bounds reused by `api/schemas/admin.py`. |
| `tool_context.py` | `ToolContext` | The caller's identity as tools see it; set by the chat service from the verified caller, never by the LLM. |
| `turn_trace.py` | `TurnTrace`, `ToolCallRecord`, `ROUTE_*`, `SCORE_DIGITS` | Step-by-step diagnostics of one turn (ADM-05, ORC-06): route, retrieval, tools (argument values not kept), timings. |
| `usage_policy.py` | `UsagePolicy`, `MICRO_USD_PER_USD` | Per-tier request limits, token budgets and monthly spend cap (SEC-08, ID-02, ADM-09); env defaults, live-editable in the admin web. |

Most classes are `@dataclass` (many `frozen=True`); `knowledge_bundle.py` and `metadata.py` use
pydantic.

## Dependencies
- May import: stdlib, pydantic, other `models` modules (`config` is allowed; none import it today). Must not import `api`, `services`,
  `middleware` or `core` (layering: api -> services -> core -> models/utils, config at the bottom;
  enforced by `test/unit/test_layering.py`).
- Used by: `core/` (agent, retrieval, document_processing, storage), `services/`, `api/schemas/` and
  `api/v1/routes/admin/knowledge.py` (`KnowledgeBundle` as request/response body), tests.
- External: none.

## Run / test
```bash
pytest test/unit/test_knowledge_bundle.py test/unit/test_chat_turn_recovery.py test/unit/test_chat_pipeline.py \
       test/unit/test_chunking_strategies.py test/unit/test_usage_limits.py
```

## Known problems and history
- `ChatbotService` split into routing + `KnowledgeAnswerer` + `TurnDeadline`; `chat_turn.py` gained
  `or_default` and the `TurnEvent` union (lcduc/automatic-octo-computing-machines#75, 67254df, 2026-11-10).
- ML model cache dir renamed to `model_weights/` because `models/` (this package) collided with it
  (139f439, 2026-08-04).
- Knowledge bundle models added with export/import (54b76a5, #32, 2026-10-07).
- Backend moved under `backend/app` (#76, 2026-11-10).
- Unused `normalize_legacy_metadata` deleted; `SOURCE_NAME_PATTERN`, duplicated in
  `api/schemas/knowledge.py`, now defined only here (branch `refactor/structure-fixes`, 2026-11-10).

## Status
- Last reviewed: 2026-11-10
- Open issues / follow-ups:
  - CQ-11: `metadata.py:36` uses Pydantic's deprecated class-based `Config` (warns on every test run; removed in Pydantic v3) (docs/checklists/code-quality.md).
- Ceilings (`# ceiling:` markers in this folder): none.
